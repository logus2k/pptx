"""The model client (technical design section 6.1), modelled on Cortex's cortex/llm/__init__.py:

- the local model through agent_server: OpenAI-compatible /v1/chat/completions with `model` = one of this app's
  presets (slides_*), registered at start-up from backend/app/agent/prompts/ through agent_server's admin API; the
  preset serves whichever local model is active;
- Claude when ANTHROPIC_API_KEY is set: the same preset prompt as the system prompt, OpenAI-style messages and tools
  converted to Anthropic's and the stream converted back (Cortex's stream_claude_openai), so the agent loop reads one
  format;
- exact token counts with the local model's tokenizer (Cortex's count_tokens), a conservative estimate otherwise.

Everything streams as OpenAI chunks: {"choices":[{"delta":{content|tool_calls|reasoning_content}, "finish_reason"}]}."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import requests

log = logging.getLogger("slides.llm")
PROMPTS = Path(__file__).resolve().parent / "prompts"
LOCAL_CONTEXT_TOKENS = int(os.environ.get("SLIDES_LOCAL_CONTEXT_TOKENS", "32768"))
FALLBACK_CHARS_PER_TOKEN = 2.5  # Cortex's measured floor for gemma-4: errs towards fitting
CLAUDE_MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5"},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5"},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
]
CLAUDE_CONTEXT = {"claude-opus-5-5": 1_000_000, "claude-sonnet-5": 1_000_000, "claude-haiku-4-5": 200_000}
# this app's presets: name -> (prompt file, parameters)
PRESETS = {
    "slides_assistant": (
        "system.md",
        {"max_tokens": 4096, "temperature": 0.3, "top_p": 0.9, "chat_template_kwargs": {"enable_thinking": False}},
    ),
    "slides_router": (
        "router.md",
        {"max_tokens": 1024, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}},
    ),
    "slides_checker": (  # did a turn's changes do all the request asks (agent/loop.py: a step left out)
        "checker.md",
        {"max_tokens": 200, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}},
    ),
    "slides_artist": (  # how one slide shows its content: its form (agent/artist.py)
        "artist.md",
        {"max_tokens": 1200, "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}},
    ),
    "slides_titler": (  # a slide's title when the model sent its points alone (agent/tools.py: _untitled)
        "titler.md",
        {"max_tokens": 100, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}},
    ),
    "slides_describer": (
        "describer.md",
        {"max_tokens": 512, "temperature": 0.2, "top_p": 0.9, "chat_template_kwargs": {"enable_thinking": False}},
    ),
    "slides_summariser": (
        "summary.md",
        {"max_tokens": 1500, "temperature": 0.2, "top_p": 0.9, "chat_template_kwargs": {"enable_thinking": False}},
    ),
    # a deck from a source (outline.py, spec NL-12): each part's key points, then the Planner's goals and storyboard,
    # then each slide by the Writer
    "slides_points": (
        "points.md",
        {"max_tokens": 1500, "temperature": 0.1, "chat_template_kwargs": {"enable_thinking": False}},
    ),
    # the Planner and the Writer think before they answer (measured on the same requests, thinking off / on: a slide
    # about the module itself 6 of 6 / 1 of 6; one question a goal 0 of 5 / 5 of 5; a summary's takeaways the goals said
    # again 4 of 4 / facts 4 of 4); their answers then begin with <think>...</think>, which the readers leave out
    "slides_planner": (
        "planner.md",
        {"max_tokens": 10000, "temperature": 0.2, "top_p": 0.9, "chat_template_kwargs": {"enable_thinking": True}},
    ),
    "slides_storyboard": (
        "storyboard.md",
        {"max_tokens": 10000, "temperature": 0.2, "top_p": 0.9, "chat_template_kwargs": {"enable_thinking": True}},
    ),
    # the Critic (critic.py): one rendered slide, judged as its audience sees it
    "slides_critic": (
        "critic.md",
        {"max_tokens": 900, "temperature": 0.2, "top_p": 0.9, "chat_template_kwargs": {"enable_thinking": False}},
    ),
    "slides_writer": (
        "writer.md",
        {"max_tokens": 6000, "temperature": 0.2, "top_p": 0.9, "chat_template_kwargs": {"enable_thinking": True}},
    ),
}


def prompt(name: str) -> str:
    return (PROMPTS / PRESETS[name][0]).read_text(encoding="utf-8")


class Models:
    def __init__(self, agent_server: str, tokenizer: str) -> None:
        self.agent_server = agent_server.rstrip("/")
        self.tokenizer = tokenizer
        self._tokens: dict[tuple[str, str], int] = {}
        self._tokenizer_down = False

    # ── what is on offer ─────────────────────────────────────────────
    def register_presets(self) -> None:
        """Create or update the presets from prompts/ (agent_server's admin API; Cortex's register_presets)."""
        for name, (_, params) in PRESETS.items():
            body = {"name": name, "system_prompt": prompt(name), "params_override": params, "memory_policy": "none"}
            r = requests.put(f"{self.agent_server}/admin/api/agents/{name}", json=body, timeout=15)
            if r.status_code == 404:
                r = requests.post(f"{self.agent_server}/admin/api/agents", json=body, timeout=15)
            r.raise_for_status()
        log.info("agent_server presets registered", extra={"presetCount": len(PRESETS)})

    def local(self) -> dict | None:
        try:
            r = requests.get(f"{self.agent_server}/v1/models", timeout=10)
            r.raise_for_status()
            for m in r.json().get("data", []):
                if m.get("active") and m.get("kind") == "chat":
                    return {"id": m["id"], "label": m.get("display_name") or m["id"], "provider": "local"}
        except Exception as e:  # noqa: BLE001 - the list degrades to Claude only
            log.warning(f"agent_server's model list is unavailable: {type(e).__name__}")
        return None

    def catalog(self) -> list[dict]:
        out = []
        local = self.local()
        if local:
            out.append(local)
        if os.environ.get("ANTHROPIC_API_KEY"):
            out += [{**m, "provider": "claude"} for m in CLAUDE_MODELS]
        return out

    def resolve(self, model_id: str | None) -> dict:
        """The project's model if it is on offer, else the first on offer."""
        models = self.catalog()
        if not models:
            raise RuntimeError("no model is available: agent_server does not answer and no Claude key is set")
        return next((m for m in models if m["id"] == model_id), models[0])

    @staticmethod
    def window(model: dict) -> int:
        return LOCAL_CONTEXT_TOKENS if model["provider"] == "local" else CLAUDE_CONTEXT.get(model["id"], 200_000)

    def count(self, text: str, model: dict) -> int:
        """Exact with the local model's tokenizer (cached per text); an estimate for Claude."""
        if not text:
            return 0
        if model["provider"] != "local":
            return int(len(text) / FALLBACK_CHARS_PER_TOKEN) + 1
        key = (model["id"], text)
        if key in self._tokens:
            return self._tokens[key]
        try:
            # the model named, as Cortex does: llama-vision serves several models and refuses a request without one
            body = {"content": text, "model": model["id"]}
            r = requests.post(self.tokenizer, params={"model": model["id"]}, json=body, timeout=10)
            r.raise_for_status()
            n = len(r.json()["tokens"])
        except Exception as e:  # noqa: BLE001 - budgeting still works, with a safe estimate
            if not self._tokenizer_down:
                log.warning(f"the tokenizer is unavailable ({type(e).__name__}); estimating")
                self._tokenizer_down = True
            return int(len(text) / FALLBACK_CHARS_PER_TOKEN) + 1
        self._tokenizer_down = False  # back: exact again
        if len(self._tokens) > 20000:
            self._tokens.clear()
        self._tokens[key] = n
        return n

    def estimating(self, model: dict) -> bool:
        """Are this model's counts estimates (Claude's always; the local model's while its tokenizer is down)?"""
        return model["provider"] != "local" or self._tokenizer_down

    def vision(self, model: dict) -> bool:
        """Can this model see images? Claude can. A local model only when its server loaded a vision projector
        (without one the request still succeeds and the model answers blind), so it is tested, as Cortex does: an
        image with a number drawn in it, which the model must read back."""
        if model["provider"] != "local":
            return True
        try:
            import base64
            import io

            from PIL import Image, ImageDraw, ImageFont

            img = Image.new("RGB", (320, 160), "white")
            try:
                font = ImageFont.load_default(size=96)
            except TypeError:
                font = ImageFont.load_default()
            ImageDraw.Draw(img).text((90, 20), "73", fill="black", font=font)
            buf = io.BytesIO()
            img.save(buf, "JPEG")
            url = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
            body = {
                "model": model["id"],
                "max_tokens": 16,
                "temperature": 0,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "What number is written in the image? Reply with the digits only."},
                            {"type": "image_url", "image_url": {"url": url}},
                        ],
                    }
                ],
            }
            r = requests.post(f"{self.agent_server}/v1/chat/completions", json=body, timeout=120)
            r.raise_for_status()
            ok = "73" in (r.json()["choices"][0]["message"].get("content") or "")
        except Exception as e:  # noqa: BLE001 - no vision is the safe answer
            log.warning(f"the vision test failed: {type(e).__name__}")
            ok = False
        log.info("model vision tested", extra={"model": model["id"], "vision": ok})
        return ok

    # ── a streamed completion with tools ─────────────────────────────
    async def stream(
        self, model: dict, preset: str, messages: list[dict], tools: list[dict] | None, max_tokens: int | None = None
    ) -> AsyncIterator[dict]:
        if model["provider"] == "local":
            async for chunk in self._stream_local(preset, messages, tools, max_tokens):
                yield chunk
        else:
            async for chunk in _aiter_sync(
                lambda: _stream_claude_openai(
                    model["id"], prompt(preset), messages, tools, max_tokens or PRESETS[preset][1]["max_tokens"]
                )
            ):
                yield chunk

    async def _stream_local(self, preset: str, messages: list[dict], tools: list[dict] | None, max_tokens: int | None):
        payload: dict[str, Any] = {
            "model": preset,
            "messages": messages,
            "stream": True,
            # the preset's own (one place decides; a request's value would override the preset's)
            "chat_template_kwargs": PRESETS[preset][1].get("chat_template_kwargs", {}),
        }
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        if max_tokens:
            payload["max_tokens"] = max_tokens
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=60, pool=10)) as client:
            async with client.stream("POST", f"{self.agent_server}/v1/chat/completions", json=payload) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", "replace")[:300]
                    raise RuntimeError(f"the model answered {r.status_code}: {body}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if chunk.get("error"):
                        raise RuntimeError(f"model error: {chunk['error'].get('message', chunk['error'])}")
                    if ((chunk.get("choices") or [{}])[0]).get("finish_reason") == "length":
                        # an answer cut at max_tokens: never silent (the caps are ceilings, set to not be reached)
                        log.warning("an answer reached its max_tokens and was cut", extra={"preset": preset})
                    yield chunk


async def _aiter_sync(make) -> AsyncIterator[Any]:
    """A blocking generator as an async iterator, in a thread (Cortex's aiter_sync); its exception is raised here."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    def run() -> None:
        try:
            for item in make():
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as e:  # noqa: BLE001 - raised in the caller
            loop.call_soon_threadsafe(queue.put_nowait, e)
        loop.call_soon_threadsafe(queue.put_nowait, done)

    import contextvars

    threading.Thread(target=contextvars.copy_context().run, args=(run,), daemon=True).start()
    while (item := await queue.get()) is not done:
        if isinstance(item, Exception):
            raise item
        yield item


# ── Claude, in OpenAI's format (Cortex's _claude_from_openai and stream_claude_openai) ──
_claude_turns: dict[str, list[dict]] = {}


def _claude_from_openai(messages: list[dict]) -> tuple[str, list[dict]]:
    system, out = [], []
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            system.append(content if isinstance(content, str) else "")
        elif role == "user":
            if isinstance(content, list):
                blocks = []
                for part in content:
                    if part.get("type") == "text":
                        blocks.append({"type": "text", "text": part["text"]})
                    elif part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        media, b64 = url[5:].split(";base64,", 1)
                        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}})
                out.append({"role": "user", "content": blocks})
            else:
                out.append({"role": "user", "content": [{"type": "text", "text": content or " "}]})
        elif role == "assistant":
            calls = m.get("tool_calls") or []
            kept = _claude_turns.get(calls[0].get("id")) if calls else None
            if kept is not None:
                blocks = kept
            else:
                blocks = [{"type": "text", "text": content}] if content else []
                for c in calls:
                    try:
                        args = json.loads(c["function"].get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    blocks.append({"type": "tool_use", "id": c["id"], "name": c["function"]["name"], "input": args})
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.get("tool_call_id"), "content": content or ""}
            if out and out[-1]["role"] == "user" and all(b["type"] == "tool_result" for b in out[-1]["content"]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return "\n\n".join(s for s in system if s), out


def _stream_claude_openai(
    model_id: str, system: str, messages: list[dict], tools: list[dict] | None, max_tokens: int
) -> Iterator[dict]:
    import anthropic

    extra, msgs = _claude_from_openai(messages)
    kwargs: dict[str, Any] = {
        "model": model_id,
        "max_tokens": max_tokens * 2,
        "system": "\n\n".join(s for s in (system, extra) if s),
        "messages": msgs,
    }
    if tools:
        kwargs["tools"] = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description") or "",
                "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}},
            }
            for t in tools
            if t.get("type") == "function"
        ]
    if model_id != "claude-haiku-4-5":
        kwargs["thinking"] = {"type": "adaptive", "display": "omitted"}
        kwargs["output_config"] = {"effort": "medium"}

    def chunk(delta: dict, finish: str | None = None) -> dict:
        return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    calls = 0
    with anthropic.Anthropic().messages.stream(**kwargs) as s:
        for event in s:
            if event.type == "content_block_start" and event.content_block.type == "tool_use":
                yield chunk(
                    {
                        "tool_calls": [
                            {
                                "index": calls,
                                "id": event.content_block.id,
                                "type": "function",
                                "function": {"name": event.content_block.name, "arguments": ""},
                            }
                        ]
                    }
                )
                calls += 1
            elif event.type == "content_block_delta":
                d = event.delta
                if d.type == "text_delta":
                    yield chunk({"content": d.text})
                elif d.type == "input_json_delta" and d.partial_json:
                    yield chunk({"tool_calls": [{"index": calls - 1, "function": {"arguments": d.partial_json}}]})
        final = s.get_final_message()
    blocks = [b.model_dump(exclude_none=True) for b in final.content]
    ids = [b["id"] for b in blocks if b["type"] == "tool_use"]
    if ids:
        if len(_claude_turns) > 500:
            _claude_turns.clear()
        _claude_turns[ids[0]] = blocks
    if final.stop_reason == "refusal":
        raise RuntimeError(f"{model_id} declined the request")
    yield chunk({}, "tool_calls" if ids else "length" if final.stop_reason == "max_tokens" else "stop")
