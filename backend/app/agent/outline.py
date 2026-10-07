"""An outline of slides from a source (spec NL-12): a project's reference document, a knowledge-base document, or
what the knowledge base holds on a topic. The application reads the whole source - in parts that fit the model's
window, never a part of it left unread - asks the model for each part's key points (prompts/points.md, with where
each comes from), then for an outline of the slides asked for (prompts/outline.md). The assistant turns the outline
into slides with its usual tools (propose_plan, add_slide), citing the sources in the notes.

A 4B model with a 32K window cannot read a document and plan slides in one answer; read in parts, each answer is
small and checkable. A source too large to read in MAX_PARTS parts is refused with its size: the person narrows it
(a section, a focus), rather than having slides made from a part of it."""

from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("slides.outline")

PART_TOKENS = 6000  # a part's passages: what a 4B model reads well at once
MAX_PARTS = 30  # about 180 000 tokens of source, some 150 pages
TOPIC_PASSAGES = 24  # what the knowledge base holds on a topic: its best passages across documents
POINTS_TOKENS = 1500
OUTLINE_TOKENS = 3000


class SourceTooLarge(Exception):
    pass


async def _gather(app, email: str, pid: str, source: dict) -> tuple[str, list[dict]]:
    """(the source's title, its passages in reading order: [{text, where, document, link?}])."""
    kind = source.get("kind")
    if kind == "document":
        asset = app.assets.get(pid, source["asset_id"])
        passages = app.assets.passages(pid, source["asset_id"])
        return asset["name"], [{"text": p["text"], "where": p.get("where") or "", "document": asset["name"]} for p in passages]
    if kind == "kb_document":
        out, after, title = [], 0, source["path"]
        while True:
            r = await asyncio.to_thread(app.kb.document_passages, email, source["domain"], source["path"], after, 200)
            title = r.get("title") or title
            got = r.get("passages") or []
            for p in got:
                where = p.get("section") or (f"p. {p['page']}" if p.get("page") else "")
                out.append({"text": p.get("text", ""), "where": where, "document": title, "link": p.get("link")})
            if not got or r.get("next") is None:
                return title, out
            after = r["next"]
    if kind == "kb_topic":
        r = await asyncio.to_thread(app.kb.search, email, source["query"], None, TOPIC_PASSAGES)
        out = []
        for p in r.get("passages") or []:
            where = p.get("section") or (f"p. {p['page']}" if p.get("page") else "")
            document = p.get("title") or p.get("document") or ""
            out.append({"text": p.get("text", ""), "where": where, "document": document, "link": p.get("link")})
        return source["query"], out
    raise ValueError(f"unknown source kind {kind!r}")


def _line(p: dict) -> str:
    where = " · ".join(x for x in (p.get("document"), p.get("where")) if x)
    return f"[{where}] {' '.join(p['text'].split())}"


def _parts(lines: list[str], count) -> list[list[str]]:
    parts, current, size = [], [], 0
    for line in lines:
        n = count(line)
        if current and size + n > PART_TOKENS:
            parts.append(current)
            current, size = [], 0
        current.append(line)
        size += n
    if current:
        parts.append(current)
    return parts


def _json(text: str) -> dict | None:
    try:
        return json.loads(text[text.find("{") : text.rfind("}") + 1])
    except ValueError:
        return None


async def _ask(app, model, preset: str, content: str, max_tokens: int) -> str:
    text = ""
    async for chunk in app.models.stream(model, preset, [{"role": "user", "content": content}], None, max_tokens):
        text += ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
    return text


async def draft(app, model: dict, email: str, pid: str, source: dict, slides: int, focus: str = "") -> dict:
    """{title, slides: [{title, points, sources}], sources: [{document, where, link}], read: {passages, parts}}."""
    title, passages = await _gather(app, email, pid, source)
    passages = [p for p in passages if p["text"].strip()]
    if not passages:
        return {"title": title, "slides": [], "sources": [], "read": {"passages": 0, "parts": 0}}
    count = lambda s: app.models.count(s, model)  # noqa: E731
    lines = [_line(p) for p in passages]
    parts = await asyncio.to_thread(_parts, lines, count)
    if len(parts) > MAX_PARTS:
        raise SourceTooLarge(f"{len(passages)} passages, {len(parts)} parts of {PART_TOKENS} tokens (at most {MAX_PARTS})")
    points: list[dict] = []
    for i, part in enumerate(parts):
        ask = f"Part {i + 1} of {len(parts)} of «{title}»:\n" + "\n".join(part)
        got = _json(await _ask(app, model, "slides_points", ask, POINTS_TOKENS)) or {}
        points += [x for x in got.get("points") or [] if isinstance(x, dict) and str(x.get("point") or "").strip()]
    log.info("source read", extra={"passageCount": len(passages), "partCount": len(parts), "pointCount": len(points)})
    wanted = max(1, min(int(slides or 6), 20))
    ask = (
        f"Make {wanted} slides from «{title}»."
        + (f"\nThe person asked for: {focus}" if focus else "")
        + "\nKey points:\n"
        + "\n".join(f"- {x['point']} ({x.get('where') or title})" for x in points)
    )
    plan = _json(await _ask(app, model, "slides_outline", ask, OUTLINE_TOKENS)) or {}
    made = [
        {"title": str(s.get("title") or "").strip(), "points": [str(p) for p in s.get("points") or [] if str(p).strip()],
         "sources": [str(x) for x in s.get("sources") or []]}
        for s in plan.get("slides") or [] if isinstance(s, dict) and str(s.get("title") or "").strip()
    ]  # fmt: skip
    seen, sources = set(), []
    for p in passages:
        key = (p["document"], p.get("link"))
        if key not in seen:
            seen.add(key)
            sources.append({k: p[k] for k in ("document", "link") if p.get(k)})
    return {"title": title, "slides": made, "sources": sources, "read": {"passages": len(passages), "parts": len(parts)}}
