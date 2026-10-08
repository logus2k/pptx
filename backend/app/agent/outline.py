"""An outline of slides from a source (spec NL-12): a project's reference document, a knowledge-base document, or
what the knowledge base holds on a topic; for a corporate presentation or a training. The application reads the whole
source - in parts that fit the model's window, never a part of it left unread - asks the model for each part's key
points (prompts/points.md, with where each comes from), then for an outline of the kind asked for
(prompts/outline.md, with the kind's structure below). The outline is shown to the person, who may edit it, before the
slides are made (domain/generations.py).

A 4B model with a 32K window cannot read a document and plan slides in one answer; read in parts, each answer is
small and checkable. A document too large to read in MAX_PARTS parts is refused with its size: the person narrows it
(a section, a focus), rather than having slides made from a part of it. Points too many for one outline request are
condensed by the same reading, again in parts (never cut)."""

from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("slides.outline")

PART_TOKENS = 6000  # a part's passages: what a 4B model reads well at once
MAX_PARTS = 30  # a document: about 180 000 tokens, some 150 pages
TOPIC_PASSAGES = 20  # the knowledge base's search answers at most 20
TOPIC_DOCUMENTS = 3  # a topic: the documents its best passages come from, read whole, while they fit TOPIC_PARTS
TOPIC_PARTS = 12
POINTS_TOKENS = 1500
OUTLINE_TOKENS = 6000

# what each kind of deck is (the person's choice; spec NL-12 and the user's two cases, 2026-10-07)
KINDS = {
    "corporate": {
        "slides": (4, 12, 8),  # at least, at most, by default
        "rules": (
            "A corporate presentation{audience}: one key message per slide, as its title; 3 to 5 short bullets "
            "(at most 12 words each) that support it. Order the slides as a presentation flows - the situation first, "
            "conclusions or next steps last - and never label a title with its place in that order (no \"Context:\", "
            "\"Conclusions:\"). Speaker notes: two or three sentences the presenter can say "
            "about the slide, from the points. Every slide's role is \"content\"."
        ),
    },
    "training": {
        "slides": (8, 24, 14),
        "rules": (
            "A training{audience} that a trainer will deliver. The first slide's role is \"objectives\": what the "
            "learners will be able to do, 3 to 5 bullets. Then 2 to 4 modules, each opened by a slide whose role is "
            "\"section\" (the module's name as title, its one-line aim as the only bullet), then its \"content\" "
            "slides: one idea each, 3 to 6 bullets (at most 20 words each) with the steps, rules and examples the "
            "source gives. Then a slide whose role is \"questions\": 3 questions that check what was learnt (the "
            "answers in its notes). The last slide's role is \"summary\": the key takeaways. Speaker notes for every "
            "slide: what the trainer says, 3 to 6 sentences explaining the slide, from the points."
        ),
    },
}
ROLES = ("content", "objectives", "section", "questions", "summary")


class SourceTooLarge(Exception):
    pass


class SourceEmpty(Exception):
    pass


async def _kb_document(app, email: str, domain: str, path: str) -> tuple[str, list[dict]]:
    out, after, title = [], 0, path
    while True:
        r = await asyncio.to_thread(app.kb.document_passages, email, domain, path, after, 200)
        title = r.get("title") or title
        got = r.get("passages") or []
        for p in got:
            where = p.get("section") or (f"p. {p['page']}" if p.get("page") else "")
            out.append({"text": p.get("text", ""), "where": where, "document": title, "link": p.get("link")})
        if not got or r.get("next") is None:
            return title, out
        after = r["next"]


async def gather(app, email: str, pid: str, source: dict, domains: list[str] | None, count) -> tuple[str, list[dict]]:
    """(the source's title, its passages in reading order: [{text, where, document, link?}])."""
    kind = source.get("kind")
    if kind == "document":
        asset = app.assets.get(pid, source["asset_id"])
        passages = app.assets.passages(pid, source["asset_id"])
        return asset["name"], [{"text": p["text"], "where": p.get("where") or "", "document": asset["name"]} for p in passages]
    if kind == "kb_document":
        return await _kb_document(app, email, source["domain"], source["path"])
    if kind == "kb_topic":
        # the topic's best passages, then the documents they come from read whole while they fit (measured: 20
        # passages are a few paragraphs of one document; a training needs the whole of its rules and steps)
        r = await asyncio.to_thread(app.kb.search, email, source["query"], domains, TOPIC_PASSAGES)
        hits = r.get("passages") or []
        out, seen_docs, size = [], [], 0
        for p in hits:
            key = (p.get("domain"), p.get("document"))
            if p.get("domain") and p.get("document") and key not in seen_docs:
                seen_docs.append(key)
        for domain, path in seen_docs[:TOPIC_DOCUMENTS]:
            _, passages = await _kb_document(app, email, domain, path)
            tokens = sum(count(_line(x)) for x in passages)
            if out and size + tokens > TOPIC_PARTS * PART_TOKENS:
                continue  # a document that would make the topic too long to read: its best passages stand for it
            out += passages
            size += tokens
        read_docs = {x["document"] for x in out}
        for p in hits:  # the passages of the documents not read whole
            document = p.get("title") or p.get("document") or ""
            if document not in read_docs:
                where = p.get("section") or (f"p. {p['page']}" if p.get("page") else "")
                out.append({"text": p.get("text", ""), "where": where, "document": document, "link": p.get("link")})
        return source["query"], out
    raise ValueError(f"unknown source kind {kind!r}")


def _line(p: dict) -> str:
    where = " · ".join(x for x in (p.get("document"), p.get("where")) if x)
    return f"[{where}] {' '.join(p['text'].split())}"


def _parts(lines: list[str], count, limit: int = PART_TOKENS) -> list[list[str]]:
    parts, current, size = [], [], 0
    for line in lines:
        n = count(line)
        if current and size + n > limit:
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


async def _points(app, model, title: str, parts: list[list[str]], progress, stage: str) -> list[dict]:
    points: list[dict] = []
    for i, part in enumerate(parts):
        await progress(stage, i, len(parts))
        ask = f"Part {i + 1} of {len(parts)} of «{title}»:\n" + "\n".join(part)
        got = _json(await _ask(app, model, "slides_points", ask, POINTS_TOKENS)) or {}
        points += [x for x in got.get("points") or [] if isinstance(x, dict) and str(x.get("point") or "").strip()]
    await progress(stage, len(parts), len(parts))
    return points


def _clean(plan: dict, kind: str) -> list[dict]:
    out = []
    for s in plan.get("slides") or []:
        if not isinstance(s, dict) or not str(s.get("title") or "").strip():
            continue
        role = str(s.get("role") or "content").strip().lower()
        out.append({
            "role": role if role in ROLES else "content",
            "title": " ".join(str(s["title"]).split()),
            "points": [" ".join(str(p).split()) for p in s.get("points") or [] if str(p).strip()],
            "notes": str(s.get("notes") or "").strip(),
            "sources": [str(x) for x in s.get("sources") or [] if str(x).strip()],
        })  # fmt: skip
    if kind == "corporate":
        for s in out:
            s["role"] = "content"
    return out


async def _noop(*_args) -> None:
    return None


async def draft(app, model: dict, email: str, pid: str, source: dict, *, kind: str = "corporate", slides: int | None = None,
                focus: str = "", audience: str = "", language: str = "pt", domains: list[str] | None = None,
                progress=_noop) -> dict:  # fmt: skip
    """{title, kind, slides: [{role, title, points, notes, sources}], sources: [{document, link?}], read: {...}}.
    progress(stage, done, total): "reading" (parts read) and "planning"."""
    spec = KINDS[kind]
    count = lambda s: app.models.count(s, model)  # noqa: E731
    title, passages = await gather(app, email, pid, source, domains, count)
    passages = [p for p in passages if p["text"].strip()]
    if not passages:
        raise SourceEmpty("the source has no text")
    lines = [_line(p) for p in passages]
    parts = await asyncio.to_thread(_parts, lines, count)
    if len(parts) > MAX_PARTS:
        raise SourceTooLarge(f"{len(passages)} passages, {len(parts)} parts of {PART_TOKENS} tokens (at most {MAX_PARTS})")
    points = await _points(app, model, title, parts, progress, "reading")
    log.info("source read", extra={"passageCount": len(passages), "partCount": len(parts), "pointCount": len(points)})
    low, high, default = spec["slides"]
    wanted = max(low, min(int(slides or default), high))
    lang = "European Portuguese (Portugal: diapositivo, ecrã; a training is a formação)" if language == "pt" else "English"
    rules = spec["rules"].format(audience=f" for {audience}" if audience.strip() else "")
    head = (f"Make {wanted} slides from «{title}», in {lang}.\n{rules}"
            + (f"\nThe person asked for: {focus}" if focus.strip() else "") + "\nKey points:\n")  # fmt: skip
    room = app.models.window(model) - OUTLINE_TOKENS - count(llm_prompt("slides_outline")) - count(head) - 512
    rounds = 0
    while True:
        listed = [f"- {x['point']} ({x.get('where') or title})" for x in points]
        if count("\n".join(listed)) <= room or rounds >= 3 or len(points) < 2:
            break
        # too many points for one request: condensed the way the source was read, in parts (never cut)
        rounds += 1
        points = await _points(app, model, f"key points of {title}", _parts(listed, count), progress, "condensing")
        log.info("points condensed", extra={"round": rounds, "pointCount": len(points)})
    await progress("planning", 0, 1)
    plan = _json(await _ask(app, model, "slides_outline", head + "\n".join(listed), OUTLINE_TOKENS)) or {}
    made = _clean(plan, kind)
    seen, sources = set(), []
    for p in passages:
        if p["document"] not in seen:
            seen.add(p["document"])
            sources.append({k: p[k] for k in ("document", "link") if p.get(k)})
    deck_title = " ".join(str(plan.get("title") or title).split())
    return {"title": deck_title, "kind": kind, "slides": made, "sources": sources,
            "read": {"passages": len(passages), "parts": len(parts), "points": len(points)}}  # fmt: skip


def llm_prompt(preset: str) -> str:
    from . import llm

    return llm.prompt(preset)
