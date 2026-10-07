"""Each turn's context (technical design section 6.2), within the model's window: 20% kept for the answer; the system
prompt and the tool definitions counted exactly (a model where they take more than 25% of the window is refused);
the rest shared: project instructions in full; the deck list (5%); the active deck's outline (20%, cut to the slides
nearest the selection when longer, saying so); the selected slide in full (30%); the conversation's summary and its
recent messages verbatim (35%, plus whatever the others leave). Project and slide text is data, never instructions:
it is wrapped in <data> and the system prompt says so."""

from __future__ import annotations

import json
import logging

from .. import search
from ..docengine import read
from . import llm

ANSWER_SHARE = 0.20
# the prompt and the tools offered, at most this share of the window: they vary per turn now (router.py), and every
# tool together measured 25.4% for gemma-4 (32,768 tokens); a routed turn offers far fewer
FIXED_LIMIT = 0.30
ESTIMATE_LIMIT = 0.5  # an estimate over-counts: refused only past this
log = logging.getLogger("slides.agent")
SHARES = {"memory": 0.05, "decks": 0.05, "outline": 0.20, "slide": 0.30, "conversation": 0.35}


class ModelTooSmall(Exception):
    pass


def _data(title: str, body: str) -> str:
    return f"## {title}\n<data>\n{body}\n</data>"


def budget(models: llm.Models, model: dict, tool_defs: list[dict]) -> tuple[int, int]:
    """(tokens for the context after the answer and the fixed part, the answer's max_tokens)."""
    window = models.window(model)
    fixed = models.count(llm.prompt("slides_assistant"), model) + models.count(json.dumps(tool_defs, ensure_ascii=False), model)
    if fixed > FIXED_LIMIT * window:
        why = f"the system prompt and tools take {fixed} of {window} tokens (more than {int(FIXED_LIMIT * 100)}%)"
        if not models.estimating(model) or fixed > ESTIMATE_LIMIT * window:
            raise ModelTooSmall(why)
        # an estimate (the tokenizer is down: a ratio chosen to over-count) never refuses the model; the budgets
        # below stay as small as the estimate makes them
        log.warning(f"{why}, by estimate; going on")
    answer = int(window * ANSWER_SHARE)
    return window - answer - fixed, answer


def _text(d: dict) -> str:
    lines = (" ".join("".join(r.get("text", "") for r in p.get("runs", [])).split()) for p in d.get("paragraphs") or [])
    return " / ".join(x for x in lines if x)


def _at(d: dict) -> str:
    """Where a free shape is (fractions of the slide): a diagram's boxes are placed and copied by it (measured: without
    positions, a new box for a diagram went to the slide's centre, over the others)."""
    b = d.get("box")
    if not b or d["type"] not in ("shape", "text_box", "connector"):
        return ""
    return f", at {b['x']:.2f},{b['y']:.2f} size {b['w']:.2f}x{b['h']:.2f}"


def _shape_lines(d: dict, role: str, indent: str = "  ") -> list[str]:
    """One line per shape: its ID (what the editing tools take), its role on the slide, and its whole text."""
    kind = d["type"]
    lock = (", locked" if d.get("locked") else "") + _at(d)
    if kind == "table" and d.get("table"):
        t = d["table"]
        head = f"{indent}shape {d['shape_id']} (table, {t['rows']} rows x {t['cols']} columns, both counted from 0{lock}):"
        rows = [f"{indent}  row {i}: " + " | ".join(" ".join(c.split()) for c in row) for i, row in enumerate(t["cells"])]
        return [head, *rows]
    if kind == "group":
        out = [f"{indent}shape {d['shape_id']} (group{lock}):"]
        for c in d.get("shapes", []):
            out += _shape_lines(c, _plain_role(c), indent + "  ")
        return out
    if kind == "picture":
        alt = d.get("alt_text")
        shows = f"; it shows: {d['description']}" if d.get("description") else ""
        return [f"{indent}shape {d['shape_id']} (picture{lock}): " + (f"alt text: {alt}" if alt else "no alt text") + shows]
    if kind == "connector" and d.get("connects"):
        ends = d["connects"]
        return [f"{indent}shape {d['shape_id']} (connector{lock}): from shape {ends[0]} to shape {ends[1]}"]
    if kind in ("chart", "other"):
        return [f"{indent}shape {d['shape_id']} ({d.get('subtype') or kind}, read-only)"]
    if d.get("overflow"):
        lock += ", does not fit its box"
    paragraphs = [
        (i, p) for i, p in enumerate(d.get("paragraphs") or []) if "".join(r.get("text", "") for r in p.get("runs", [])).strip()
    ]
    if len(paragraphs) <= 1:  # its text first, then its ID: an ID between two texts was read as the next one's
        # (replayed, devai-01 on Banco CTT's agenda: "shape 115 (body): Future Roles..." then "shape 93 (body): 04",
        # the model edited 93 in 4 to 8 runs of 10; as «Future Roles...» (shape 115, body), 115 in 10 of 10)
        words = _text(d)
        return [f"{indent}{f'«{words}»' if words else '(empty)'} (shape {d['shape_id']}, {role}{lock})"]
    # one paragraph a line, indented by its level: as update_text takes them back (measured: joined on one line with
    # " / ", the model wrote a five-bullet agenda back as a single paragraph and dropped a bullet)
    lines = [f"{indent}shape {d['shape_id']} ({role}{lock}), {len(paragraphs)} paragraphs:"]
    for i, p in paragraphs:  # [i]: the paragraph's index in the shape, as edit_paragraphs takes it
        text = " ".join("".join(r.get("text", "") for r in p.get("runs", [])).split())
        level = int(p.get("level") or 0)
        lines.append(f"{indent}  {'  ' * level}[{i}] {text}" + (f"  (level {level})" if level else ""))
    return lines


def _plain_role(d: dict) -> str:
    return {"text_box": "text box", "shape": "shape", "connector": "connector"}.get(d["type"], d["type"])


def roles(s: dict) -> dict[int, str]:
    """Each top-level shape's role on the slide (read.slide's output): title, subtitle, body - left and right when the
    layout has two - date, footer, slide number, text box, table, picture, group."""
    bodies = [
        x
        for x in s["shapes"]
        if x["type"] == "placeholder"
        and x["placeholder"]["type"] not in ("title", "center_title", "subtitle")
        and x["placeholder"]["type"] not in ("date", "footer", "slide_number")
    ]
    sides = {}
    if len(bodies) == 2 and all(b.get("box") for b in bodies):
        left, right = sorted(bodies, key=lambda b: b["box"]["x"])
        sides = {left["shape_id"]: "body, left", right["shape_id"]: "body, right"}
    out = {}
    for d in s["shapes"]:
        ph = (d.get("placeholder") or {}).get("type")
        if ph in ("title", "center_title"):
            out[d["shape_id"]] = "title"
        elif ph == "subtitle":
            out[d["shape_id"]] = "subtitle"
        elif ph in ("date", "footer", "slide_number"):
            out[d["shape_id"]] = ph.replace("_", " ")
        elif ph:
            out[d["shape_id"]] = sides.get(d["shape_id"], "body")
        else:
            out[d["shape_id"]] = _plain_role(d)
    return out


def slide_map(s: dict, number: str | None = None) -> str:
    """A slide as the model targets it (read.slide's output): a header line, then every shape with its ID and role
    (roles()), table with its cells, picture with its alt text, group with its members), then the speaker notes.
    number: the slide's number in the request's numbering ("new" for a slide made in it); its place by default."""
    number = number or str(s["index"] + 1)
    label = "new slide" if number == "new" else f"slide {number}"
    head = f"{label} · id {s['slide_id']} · {s['layout']}" + (" · hidden" if s["hidden"] else "")
    lines = [head]
    named = roles(s)
    for d in s["shapes"]:
        lines += _shape_lines(d, named[d["shape_id"]])
    if s.get("notes"):
        lines.append("  speaker notes: " + " / ".join(x for x in (" ".join(n.split()) for n in s["notes"].splitlines()) if x))
    return "\n".join(lines)


def describe(slide: dict, descriptions: dict[str, str]) -> dict:
    """A slide's pictures with what they show (spec IM-4), from the project's descriptions."""
    for sh in slide["shapes"]:
        for x in [sh, *sh.get("shapes", [])]:
            if x.get("type") == "picture" and x.get("image_sha256") in descriptions:
                x["description"] = descriptions[x["image_sha256"]]
    return slide


def deck_map(
    prs, selected: int | None, limit_tokens: int, count, descriptions: dict | None = None, start: list[int] | None = None
) -> tuple[str, int]:
    """Every slide of the deck: in full (slide_map) when it all fits in `limit_tokens`; otherwise every slide still
    has its line (ID, position, layout, title) and the slides nearest the selected one (the first ones when none is)
    are in full, as many as fit. Returns the text and how many slides have their line only. start: the deck's slide
    IDs when the request was made: slides keep those numbers for the whole turn, a slide made in it is "new", and
    the ones deleted in it are listed (measured: renumbered after "delete slide 39", the map showed another slide 39,
    and it was deleted too)."""
    outline = read.outline(prs)
    number = {sid: str(i + 1) for i, sid in enumerate(start)} if start else {}
    label = lambda o: number.get(o["slide_id"], "new") if start else str(o["index"] + 1)  # noqa: E731
    lines = {}
    for o in outline:
        hidden = " · hidden" if o["hidden"] else ""
        head = "new slide" if label(o) == "new" else f"slide {label(o)}"
        lines[o["slide_id"]] = f"{head} · id {o['slide_id']}{hidden} · {o['title'] or '(no title)'}"
    full = [
        (o["slide_id"], slide_map(describe(read.slide(prs, o["slide_id"]), descriptions or {}), label(o))) for o in outline
    ]
    now = {o["slide_id"] for o in outline}
    gone = [str(i + 1) for i, sid in enumerate(start or []) if sid not in now]
    tail = f"\nDeleted in this request: slide{'s' if len(gone) > 1 else ''} {', '.join(gone)}" if gone else ""
    text = "\n".join(b for _, b in full)
    if count(text + tail) <= limit_tokens:
        return text + tail, 0
    listed = set(window(list(lines.items()), selected, limit_tokens, count))
    room = limit_tokens - count("\n".join(lines[sid] for sid in lines if sid in listed))
    shown = set(window(full, selected, room, count)) if room > 0 else set()
    blocks = [block if sid in shown else lines[sid] for sid, block in full if sid in shown or sid in listed]
    return "\n".join(blocks) + tail, len(outline) - len(shown)


def window(blocks: list[tuple[int, str]], selected: int | None, limit_tokens: int, count) -> list[int]:
    """The IDs of the blocks ((id, text), in order) nearest the selected one (the first when none is) whose texts fit
    together in `limit_tokens`."""
    if not blocks:
        return []
    texts = [b for _, b in blocks]
    centre = next((i for i, (sid, _) in enumerate(blocks) if sid == selected), 0)
    if count(texts[centre]) > limit_tokens:
        return []
    lo = hi = centre
    keep = [texts[centre]]
    while True:
        grew = False
        for j in (hi + 1, lo - 1):
            if 0 <= j < len(texts) and count("\n".join([*keep, texts[j]])) <= limit_tokens:
                if j > hi:
                    hi = j
                    keep.append(texts[j])
                else:
                    lo = j
                    keep.insert(0, texts[j])
                grew = True
        if not grew:
            return [sid for sid, _ in blocks[lo : hi + 1]]


def memory_text(app, t, query: str, limit_tokens: int, count) -> str:
    """The project's memory (spec PJ-9), within its share (technical design 6.2: 5%): all of it when it fits, else
    the items nearest the person's request (reranked), and how many were left out."""
    items = app.memory.list(t.pid, t.email)
    if not items:
        return ""
    lines = [f"- {m['text']} ({m['created_at'][:10]})" for m in items]
    text = "\n".join(lines)
    if count(text) <= limit_tokens:
        return text
    order = list(range(len(items)))
    if query:
        try:
            scores = app.reranker.scores(query, [m["text"] for m in items])
            order.sort(key=lambda i: -scores[i])
        except search.SearchUnavailable:
            order.reverse()  # the most recent first
    else:
        order.reverse()
    kept: list[int] = []
    for i in order:
        if count("\n".join(lines[j] for j in [*kept, i])) > limit_tokens:
            break
        kept.append(i)
    left = len(items) - len(kept)
    return "\n".join(lines[i] for i in sorted(kept)) + f"\n({left} more items: search_conversations finds where they came from)"


def layouts_text(prs) -> str:
    """The deck's layouts for add_slide and change_layout: each one the deck uses with an example slide's placeholders
    (idx and what that slide has there), so a new slide can be made like an existing one; the others by name
    (measured: a template's layouts named "3_Texto", "10_Texto", with no title placeholder: the model sent a title
    to a layout without one and gave up)."""
    examples: dict[str, str] = {}
    for o in read.outline(prs):
        if o["layout"] in examples:
            continue
        s = read.slide(prs, o["slide_id"])
        held = []
        for sh in s["shapes"]:
            ph = sh.get("placeholder") or {}
            if not ph or ph.get("type") in ("date", "footer", "slide_number"):
                continue
            text = _text(sh)
            held.append(f"idx {ph.get('idx')} ({ph.get('type')})" + (f" «{text}»" if text else ""))
        if held:
            examples[o["layout"]] = f"{o['layout']} (as slide {o['index'] + 1}): " + "; ".join(held)
    names = sorted({x["name"] for x in read.layouts(prs)})
    others = [n for n in names if n not in examples]
    text = "\n".join(examples[n] for n in names if n in examples)
    if others:
        text += ("\nOther layouts: " if text else "") + ", ".join(others)
    return f"## Layouts of this deck (add_slide, change_layout; placeholders by idx)\n{text}"


def system_context(
    app,
    t,
    model,
    room: int,
    active_bytes: bytes | None,
    selection: dict | None,
    map_tokens: int | None = None,
    query: str = "",
) -> tuple[str, int]:
    """The context message and the tokens it used."""
    count = lambda s: app.models.count(s, model)  # noqa: E731
    project = app.projects.get(t.pid, t.email)
    parts = [f"## Project\nName: <data>{project['name']}</data>"]
    if project["instructions"].strip():
        parts.append(
            _data("Project instructions (the person's rules for this project: follow them)", project["instructions"].strip())
        )
    decks = app.decks.list(t.pid, t.email)
    active = t.conversation.get("active_deck")
    deck_lines = "\n".join(
        f"{d['id']} | {d['title']} | {d['slide_count']} slides{' | ACTIVE' if d['id'] == active else ''}" for d in decks
    )
    parts.append(_data("Decks (id | title | slides)", deck_lines or "(none yet)"))
    remembered = memory_text(app, t, query, int(room * SHARES["memory"]), count)
    if remembered:
        parts.append(_data("Project memory (facts and decisions kept from earlier conversations: follow them)", remembered))
    assets = [a for a in app.assets.list(t.pid) if a["kind"] in ("image", "document")]
    if assets:
        listed = "\n".join(f"{a['id']} | {a['kind']} | {a['name']}" for a in assets[-40:])
        more = f"\n({len(assets) - 40} older assets not listed)" if len(assets) > 40 else ""
        parts.append(
            _data("Project assets (id | kind | name): images for insert_image; documents for search_project", listed + more)
        )
    if active and active_bytes is not None:
        prs = read.open_deck(active_bytes)
        selected = (selection or {}).get("slide_id")
        # the window of slides in full: around the selected slide, else around the one the request is about (the
        # router's where; measured: on a 46-slide deck the slide asked about was outside the window, line only)
        centre = selected or getattr(t, "focus", None)
        described = app.describer.descriptions.all(t.pid) if getattr(app, "describer", None) else {}
        start = (getattr(t, "start_order", None) or {}).get(active)
        text, brief = deck_map(prs, centre, map_tokens or int(room * SHARES["outline"]), count, described, start)
        note = f"\n({brief} slides in one line only: get_slide gives their shape IDs and text)" if brief else ""
        heading = "Active deck, slide by slide (slide numbers or IDs, and shape IDs, are what the editing tools take)"
        parts.append(_data(f"{heading}{note}", text))
        parts.append(layouts_text(prs))
        if selected:
            try:
                s = read.slide(prs, int(selected))
            except KeyError:
                s = None
            if s is not None:
                sel = json.dumps(s, ensure_ascii=False, separators=(",", ":"))
                shapes = (selection or {}).get("shape_ids") or []
                label = f"Selected slide {selected}" + (f", selected shapes {shapes}" if shapes else "") + ' ("this slide")'
                if count(sel) <= int(room * SHARES["slide"]):
                    parts.append(_data(label, sel))
                else:
                    parts.append(f"## {label}\n(too large to include: call get_slide)")
    waiting = app.proposals.open_in(t.pid, t.cid)
    if waiting and waiting["status"] == "pending":  # spec VO-6: the model knows what a "yes, apply it" refers to
        lines = []
        for did, d in waiting["decks"].items():
            title = next((x["title"] for x in app.decks.list(t.pid, t.email) if x["id"] == did), did)
            lines.append(f"deck «{title}»: {len(set(o_s for op in d['operations'] for o_s in op['slides']))} slides changed")
        parts.append(
            "## Changes waiting for the person's decision (decide_changes when they accept or reject in words)\n"
            + "\n".join(lines)
        )
    if t.conversation.get("summary"):
        parts.append(_data("Earlier in this conversation (summary)", t.conversation["summary"]))
    if getattr(t, "intent", ""):  # last, nearest the request: what to do now, as one instruction
        where = "".join(f"\n{x}." for x in getattr(t, "located", []) or [])
        if t.changes and getattr(t, "done", None):  # the edits so far: done, not to be made again
            parts.append(
                f"## Now\nThe person wants: {t.intent}{where}\nDone in this turn: {'; '.join(t.done)}.\nIf that is all the "
                "request asks, call no tool again: say in one sentence what you changed. Otherwise call the tools for "
                "what is still missing."
            )
        elif t.changes:
            parts.append(
                f"## Now\nThe person wants: {t.intent}{where}\nDo it now by calling your tools, writing any text yourself; "
                "then say in one sentence what you changed."
            )
        elif getattr(t, "kind", "") == "unclear":
            # without the router's intent (measured on the same call: with a long intent, ask_user 0 times in 10;
            # without it, 10 in 10)
            parts.append(
                "## Now\nThe request is too vague to act on. Ask the person, with ask_user, the one question that tells "
                "you what to change; change nothing yet."
            )
        else:
            parts.append(f"## Now\nThe person asks: {t.intent}\nAnswer from the deck and your context; change nothing.")
    text = "\n\n".join(parts)
    return text, count(text)


def history_messages(stored: list[dict]) -> list[dict]:
    """Stored messages as the model takes them (OpenAI roles)."""
    out = []
    for m in stored:
        if m["role"] == "user":
            content = m.get("content") or ""
            if m.get("attachments"):
                content += "\n\n(Attached images, by asset_id: " + ", ".join(m["attachments"]) + ")"
            if m.get("selection"):
                content += f"\n\n(Context: active deck {m.get('deck_id')}, selection {json.dumps(m['selection'])})"
            out.append({"role": "user", "content": content})
        elif m["role"] == "assistant":
            msg = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = m["tool_calls"]
            out.append(msg)
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m.get("content") or ""})
    return out


def turns(stored: list[dict]) -> list[list[dict]]:
    """The messages cut into turns, each starting at a user message (never split a tool call from its result)."""
    out: list[list[dict]] = []
    for m in stored:
        if m["role"] == "user" or not out:
            out.append([m])
        else:
            out[-1].append(m)
    return out
