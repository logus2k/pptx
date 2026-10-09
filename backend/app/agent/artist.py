"""The Artist (the user, 2026-10-08: "a Creative Artist Designer ... that will plan for the best layout and content
presentation on each slide", and "we should be able to ask the Artist for ideas or a different proposal at any time").
For one slide it proposes a form - bullets, columns, key figures, a highlight, a table, a chart or a diagram - and the
slide's content shaped for it (contracts/storage/design.schema.json); the application chooses the template's layout for
the form (docengine/ops.add_designed), as it does for covers and lists, because the model chose layouts badly when it
did (measured: four columns for "create a slide", a list spread over banner boxes).

Every proposal is checked before it is used: against the schema, and every number it shows must be in the slide's own
text (points and notes: the source's, read by agent/outline.py) - a lexical fact; one that fails becomes the slide's
list. One short call a slide (preset slides_artist): a 4B model does well with one slide, poorly with a whole deck."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import jsonschema

from ..config import REPO_DIR
from .outline import loads

log = logging.getLogger("slides.artist")

FORMS = ("bullets", "columns", "figures", "highlight", "table", "chart", "diagram")
DESIGNED_ROLES = ("content",)  # objectives, questions and the summary stay lists, sections dividers (looked at: a
# summary's three takeaways as loose columns of small text, weaker than the list they are)
_SCHEMA = json.loads(Path(REPO_DIR / "contracts" / "storage" / "design.schema.json").read_text(encoding="utf-8"))


def _figures(text: str) -> set[str]:
    from .tools import _figures as figures

    return figures(text)


PUNCTUATION = ".,;:!?()[]{}«»\"'/-" + "\u201c\u201d\u2018\u2019\u2013\u2014"  # and typographic quotes and dashes


def _words(text: str) -> list[str]:
    """The words of a text that carry its meaning: 4 letters or more, lower case, without the punctuation around them."""
    out = []
    for w in text.casefold().split():
        w = w.strip(PUNCTUATION)
        if len(w) >= 4:
            out.append(w)
    return out


def _named(node: str, text: str) -> bool:
    """Does the slide's text name this step? Most of its words are in the text (a lexical fact; a step reworded in a
    few words keeps most of them)."""
    words, said = _words(node), set(_words(text))
    return not words or sum(w in said for w in words) * 2 >= len(words)


def _numbers_in(design: dict) -> list[str]:
    """The texts of the design that state numbers (values, cells, a statement)."""
    form = design.get("form")
    if form == "chart":
        return [str(v) for s in design["chart"]["series"] for v in s["values"]]
    if form == "figures":
        return [f["value"] for f in design["figures"]]
    if form == "highlight":
        return [design["highlight"]["statement"]]
    if form == "table":
        return [c for row in design["table"]["rows"] for c in row]
    return []


def _value_text(v: str) -> str:
    """A chart's number as people write it, for the lexical check (17.5 -> "17,5", 80000.0 -> "80000")."""
    try:
        f = float(v)
    except ValueError:
        return v
    return str(int(f)) if f == int(f) else str(f).replace(".", ",")


def checked(design: dict | None, slide: dict) -> dict:
    """The design as it will be used: valid and founded, else the slide's list (bullets of its points)."""
    fallback = {"form": "bullets", "points": list(slide.get("points") or [])}
    if not isinstance(design, dict) or design.get("form") not in FORMS:
        return fallback
    design = {k: v for k, v in design.items() if k in ("form", "why", design.get("form"), "points")}
    if design["form"] == "bullets":
        design["points"] = design.get("points") or fallback["points"]
    try:
        jsonschema.validate(design, _SCHEMA)
    except jsonschema.ValidationError:
        log.info("a design was not valid: the list", extra={"form": design["form"]})
        return fallback
    if design["form"] not in ("bullets",) and not design.get(design["form"]):
        return fallback
    if design["form"] == "chart":
        if any(len(s["values"]) != len(design["chart"]["categories"]) for s in design["chart"]["series"]):
            return fallback
    shown = {"columns": lambda d: sum(len(c.get("points") or []) for c in d["columns"]), "figures": lambda d: len(d["figures"]),
             "diagram": lambda d: len(d["diagram"]["nodes"])}  # (looked at: four points drawn as a diagram of two steps)
    if design["form"] in shown and shown[design["form"]](design) < len(slide.get("points") or []):
        # fewer items than the slide has points: some of it was left out (measured: four points on refunds' notice
        # periods and fees shown as two columns of one vague line each)
        log.info("a design left points out: the list", extra={"form": design["form"]})
        return fallback
    text = " ".join([slide.get("title") or "", *(slide.get("points") or []), slide.get("notes") or ""])
    if design["form"] == "columns" and any(not _named(item, text) for c in design["columns"] for item in c.get("points") or []):
        # an item the slide does not say (looked at: "Foco específico" under a column heading, in no point or note)
        log.info("a column showed an item not in the slide: the list")
        return fallback
    if design["form"] == "diagram" and any(not _named(node, text) for node in design["diagram"]["nodes"]):
        # a step the slide does not name (measured: "Fase 1: Elegibilidade automática" ... drawn for a slide whose text
        # said only "o processo tem 7 fases" and what happens in phase 6)
        log.info("a diagram showed steps not in the slide: the list")
        return fallback
    if design["form"] == "diagram":
        # every point of the slide in a step, but one that introduces them (looked at, in 4 decks of 22: a diagram of the
        # four steps one point names, the tranches, the documents and the licence of the other three nowhere on the
        # slide; "Epic, Feature, PBI, Task" for a slide whose DoR and DoD points were left out)
        named = {w for node in design["diagram"]["nodes"] for w in _words(node)}
        bare = [p for p in slide.get("points") or [] if not named & set(_words(p))]
        if len(bare) > 1:
            log.info("a diagram left points out: the list", extra={"count": len(bare)})
            return fallback
    said = _figures(text)
    for text in _numbers_in(design):
        shown = _figures(_value_text(text)) if design["form"] == "chart" else _figures(text)
        if shown - said:  # a number the slide's own text does not hold: invented
            log.info("a design showed a number not in the slide: the list", extra={"form": design["form"]})
            return fallback
    return design


def _ask(slide: dict, before: list[str], wish: str = "", avoid: list[str] | None = None, kind: str = "") -> str:
    # kind: the presentation's goal in words (its kind, audience, focus, title: goal_of), so the form and the words serve
    # it (the user, 2026-10-08: "relevant and useful for the stated goals")
    lines = [f"The presentation's goal: {kind}"] if kind else []
    # the Planner's storyboard (agent/outline.plan): what the slide must achieve and the goal it serves (the user,
    # 2026-10-09: the planning identifies the tasks "before giving it for the Artist to execute its art")
    if slide.get("goal_text"):
        lines.append(f"The goal this slide serves: {slide['goal_text']}")
    if slide.get("task"):
        lines.append(f"The slide's task: {slide['task']}")
    lines += [f"The slide's title: {slide.get('title') or ''}", "Its points:"]
    lines += [f"- {p}" for p in slide.get("points") or []] or ["(none)"]
    if slide.get("notes"):
        lines.append(f"Its notes: {slide['notes']}")
    lines.append(f"The forms of the slides before it: {', '.join(before) or '(none)'}")
    if wish.strip():
        lines.append(f"The person wishes: {wish.strip()}")
    if avoid:
        lines.append(f"Forms not to use: {', '.join(avoid)}")
    return "\n".join(lines)


async def _call(app, model: dict, content: str) -> dict | None:
    """The Artist's JSON answer; asked once more when it is not JSON (measured: a bracket closed out of order,
    "...defeito."}]}]}, and the slide's columns were lost)."""
    for attempt in (1, 2):
        text = ""
        try:
            async for chunk in app.models.stream(model, "slides_artist", [{"role": "user", "content": content}], None, 1200):
                text += ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
            got = loads(text)  # its brackets mended when they do not match (outline.balanced)
            if got is None:
                raise ValueError("not JSON")
            return got
        except ValueError:
            if attempt == 2:
                log.warning("the Artist's answer was not JSON")
        except Exception as e:  # noqa: BLE001 - no proposal: the slide keeps its list
            log.warning("the Artist did not answer", extra={"err.type": type(e).__name__})
            return None
    return None


SHAPES = {  # the field each form needs, as the second request asks for it
    "columns": '{"columns": [{"heading": "...", "points": ["..."]}, {"heading": "...", "points": ["..."]}]}',
    "figures": '{"figures": [{"value": "...", "label": "..."}, {"value": "...", "label": "..."}]}',
    "highlight": '{"highlight": {"statement": "...", "detail": "..."}}',
    "table": '{"table": {"rows": [["heading", "heading"], ["cell", "cell"]]}}',
    "chart": '{"chart": {"kind": "column", "categories": ["..."], "series": [{"name": "...", "values": [1, 2]}]}}',
    "diagram": '{"diagram": {"nodes": ["first step", "next step"], "direction": "right"}}',
    "bullets": '{"points": ["..."]}',
}


async def design(app, model: dict, slide: dict, before: list[str] | None = None, wish: str = "",
                 avoid: list[str] | None = None, kind: str = "") -> dict:  # fmt: skip
    """One proposal for the slide, checked (a list when it does not hold). The form first; when the answer names a form
    without its content, the content in a second, smaller request (measured: {"form": "columns", "why": "..."} and no
    columns, 3 slides in 4, each then a list)."""
    got = await _call(app, model, _ask(slide, before or [], wish, avoid, kind))
    form = (got or {}).get("form")
    if form in SHAPES and form != "bullets" and not (got or {}).get(form):
        ask = (_ask(slide, before or [], wish, None, kind) + f"\n\nShow this slide as {form}. Answer with JSON only, "
               f"in the slide's language, with what its points and notes say: {SHAPES[form]}")  # fmt: skip
        shaped = await _call(app, model, ask)
        if isinstance(shaped, dict) and shaped.get(form):
            got = {**got, form: shaped[form]}
    nodes = ((got or {}).get("diagram") or {}).get("nodes") or [] if form == "diagram" else []
    if any(len(str(n)) > 40 or "->" in str(n) for n in nodes):
        # a step a box, in a few words (looked at: "Enquadramento (Certificados ...) -> Formalização (FAP)" in one box)
        ask = (_ask(slide, before or [], wish, None, kind) + "\n\nShow this slide as a diagram: one step a box, each step "
               f"at most 5 words, in order. Answer with JSON only: {SHAPES['diagram']}")  # fmt: skip
        shorter = await _call(app, model, ask)
        if isinstance(shorter, dict) and (shorter.get("diagram") or {}).get("nodes"):
            got = {**got, "diagram": shorter["diagram"]}
    return checked(got, slide)


async def ideas(app, model: dict, slide: dict, count: int = 3, wish: str = "", kind: str = "") -> list[dict]:
    """Several proposals, each in another form (the forms already proposed are given as not to use); checked, and
    without repeats - fewer when the content has fewer forms to offer."""
    out: list[dict] = []
    tried: list[str] = []
    for _ in range(count + 2):  # a proposal that falls back to a list repeats one: a try or two more
        got = await design(app, model, slide, [], wish, tried, kind)
        tried.append(got["form"])
        if all(x["form"] != got["form"] for x in out):
            out.append(got)
        if len(out) >= count:
            break
    return out


async def design_outline(app, model: dict, slides: list[dict], kind: str = "", progress=None,
                         goals: list[str] | None = None) -> list[dict]:  # fmt: skip
    """Each slide of a generated outline with its design (the roles DESIGNED_ROLES; the others as they are): in order,
    each told the forms before it, so the deck varies where its content allows, and its task and goal as planned."""
    forms: list[str] = []
    out = []
    todo = [i for i, s in enumerate(slides) if s.get("role", "content") in DESIGNED_ROLES]
    for n, (i, slide) in enumerate((i, slides[i]) for i in todo):
        if progress is not None:
            await progress("designing", n, len(todo))
        goal = slide.get("goal") or 0
        planned = {**slide, "goal_text": goals[goal - 1]} if goals and 1 <= goal <= len(goals) else slide
        got = await design(app, model, planned, forms[-2:], kind=kind)
        forms.append(got["form"])
        slides[i] = {**slide, "design": got}
    for s in slides:
        out.append(s)
    if progress is not None:
        await progress("designing", len(todo), len(todo))
    log.info("outline designed", extra={"slideCount": len(todo), "forms": ",".join(forms)})
    return out


def slide_of(one: dict, layout_heading: int | None) -> dict:
    """A deck's slide as the Artist reads it ({title, points, notes}), from the read model (docengine/read.slide): its
    heading's text as the title, every other paragraph and table row as a point, a chart's data as its points."""
    title, points = "", []
    for sh in one.get("shapes") or []:
        for x in [sh, *(sh.get("shapes") or [])]:
            lines = ["".join(r.get("text") or "" for r in p.get("runs") or []).strip() for p in x.get("paragraphs") or []]
            lines = [x_ for x_ in lines if x_]
            if (x.get("placeholder") or {}).get("idx") == layout_heading and lines and not title:
                title = " ".join(lines)
                continue
            points += lines
            for row in (x.get("table") or {}).get("cells") or []:
                points.append(" | ".join(c if isinstance(c, str) else "" for c in row))
            chart = x.get("chart") or {}
            for s in chart.get("series") or []:
                pairs = ", ".join(f"{c}: {v}" for c, v in zip(chart.get("categories") or [], s.get("values") or [], strict=False))
                points.append(f"{s.get('name') or ''}: {pairs}")
    return {"title": title, "points": points[:30], "notes": one.get("notes") or ""}


async def ideas_for_deck_slide(app, pid: str, did: str, slide_id: int, email: str, wish: str = "", count: int = 3) -> dict:
    """The Artist's ideas for a slide of a deck: {slide: {title, points}, ideas: [design]} (the editor's Ask the Artist
    and the assistant's ask_artist)."""
    import asyncio

    from ..docengine import layouts, read

    project = app.projects.get(pid, email)
    _, data = app.decks.version_bytes(pid, did, email)
    prs = read.open_deck(data)
    s = prs.slides.get(int(slide_id))
    if s is None:
        from ..storage import NotFound

        raise NotFound("slide")
    one = read.slide(prs, int(slide_id))
    slide = slide_of(one, layouts.heading(s.slide_layout, prs.slide_width, prs.slide_height))
    model = await asyncio.to_thread(app.models.resolve, project["settings"]["model"])
    goal = goal_of(title=app.decks.get(pid, did, email).get("title") or "")
    return {"slide": slide, "ideas": await ideas(app, model, slide, count, wish, goal)}


def goal_of(kind: str = "", audience: str = "", focus: str = "", title: str = "") -> str:
    """The presentation's goal in words, for the Artist: "A training for balcão staff, on: the eligibility rules
    («Crédito Habitação Jovem»)"."""
    what = {"corporate": "A corporate presentation", "training": "A training a trainer delivers"}.get(kind, "A presentation")
    out = what + (f" for {audience.strip()}" if audience.strip() else "")
    if focus.strip():
        out += f", on: {focus.strip()}"
    if title.strip():
        out += f" («{title.strip()}»)"
    return out


def describe(design: dict) -> str:
    """A design in a line, for the person and the model: "columns: Requisitos pessoais | Requisitos financeiros"."""
    form = design.get("form")
    if form == "columns":
        what = " | ".join(c["heading"] for c in design["columns"])
    elif form == "figures":
        what = " | ".join(f"{f['value']} {f['label']}" for f in design["figures"])
    elif form == "highlight":
        what = design["highlight"]["statement"]
    elif form == "table":
        what = " | ".join(design["table"]["rows"][0])
    elif form == "chart":
        what = f"{design['chart']['kind']}: {', '.join(design['chart']['categories'][:6])}"
    elif form == "diagram":
        what = " → ".join(design["diagram"]["nodes"])
    else:
        what = f"{len(design.get('points') or [])} points"
    return f"{form}: {what}"
