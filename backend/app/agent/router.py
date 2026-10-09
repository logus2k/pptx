"""The tool-group router (a decision model): before a turn, the model is asked in one short call what the person wants
done and which groups of tools that needs; the turn is then offered those groups and the core, not every tool.

Measured on the evaluation set (tests/eval, 72 requests, gemma-4 E4B): with every tool offered, ~60% targeting;
offered exactly the groups each request needs (an oracle, from the expected answers), ~75%; routed by this prompt,
which asks for the intent first and shows the deck's sketch, 73% (76.4 / 69.4), a needed group missed on 8.3% of
requests, 0.08 extra groups a request. A classifier trained on generated examples (labs/jev's router_clf) missed
29% (router/: kept to retrain on real requests). The groups' descriptions are also the profile router_clf reads
(scripts/router_data.py writes router/slides_tools.yaml from them)."""

from __future__ import annotations

import difflib
import json

GROUPS: dict[str, list[str]] = {
    "core": ["ask_user", "propose_plan", "get_slide", "get_deck_outline"],
    "text": ["update_text", "edit_paragraphs", "format_text", "fit_text", "fill_slide"],
    "table": ["edit_table", "add_chart", "edit_chart", "draw_diagram"],
    "notes": ["set_notes"],
    "images": ["insert_image", "replace_image", "set_alt_text", "render_slide", "kb_list_images", "generate_image"],
    "structure": ["add_slide", "duplicate_slide", "delete_slide", "move_slide", "change_layout", "add_shape",
                  "move_resize_shape", "delete_shape", "duplicate_shape", "connect_shapes", "add_slides", "ask_artist",
                  "redesign_slide"],
    "decks": ["create_deck", "duplicate_deck", "copy_slides", "change_template", "list_templates", "generate_deck"],
    "knowledge": ["kb_search", "kb_read_document", "search_project"],
    "memory": ["remember", "search_conversations", "update_instructions"],
    "history": ["undo", "redo", "decide_changes"],
}  # fmt: skip

NONE = (
    "A question about the deck, the project or how to do something, answered in words without changing any slide; "
    "or a greeting, a thank-you, or a request too vague to act on."
)
DESCRIPTIONS = {
    "text": "Write, rewrite, shorten, translate, correct or format the text already on a slide: a title, a subtitle, a "
    "bullet or a list of bullets, a column, a text box; change a word, a number, a date, a name; make text bigger, "
    "bold or another colour.",
    "table": "Change a table on a slide: a cell's value, add or remove a row or a column, correct a figure in a table. "
    "Make or change a chart (bar, column, line, pie) from figures; draw a diagram of a process, a flow or an "
    "organisation.",
    "notes": "Write, change or add to the speaker notes of a slide; cite a source in the notes.",
    "images": "Pictures: insert, replace or remove an image or photo, put a picture from a document on a slide, write "
    "or fix the alt text of an image, look at what an image shows.",
    "structure": "The deck's slides and shapes: add a new slide, duplicate, delete or move slides, change a slide's "
    "layout or number of columns, add, copy, move, resize or delete a shape or text box; a diagram's boxes and the "
    "arrows between them; ideas for how a slide shows its content, or showing it in another form (the Artist).",
    "decks": "Whole decks: create a new deck or presentation, copy a deck, copy or move slides between two decks, "
    "change a deck's template or look; make a whole presentation or a training from the knowledge base or a document.",
    "knowledge": "Facts from the organisation's documents: search the knowledge base or the project's reference "
    "documents for policies, products, figures, prices or procedures to use on slides.",
    "memory": "Remember a lasting decision or preference for this project, recall what was discussed or decided in "
    "an earlier conversation, or set a rule for the project's instructions.",
    "history": 'Undo or redo the last change, or accept or reject the changes waiting for review ("yes, apply it", '
    '"reject slide five").',
}
ALL = set(GROUPS) - {"core"}
FALLBACK = {"text", "structure", "table", "notes", "history"}  # unrouted, when every tool does not fit


def slide_lines(shapes: list[dict], title_id: int | None, roles: dict[int, str] | None = None) -> list[str]:
    """All of a slide's text after its title (read.slide's shapes), one paragraph or table row a line, and the
    pictures' alt text. Whole, never cut (measured: cut at 90 characters, "taxa de abandono 3,1%" and "Day 5" were
    hidden from the router); a line each (measured: joined with " / ", the router copied the wrong row of a table
    and took a subtitle for part of the title). roles (context.roles): with more than one block of text, each block
    is headed by its role (measured: two columns run together, the router named all their lines as the one that
    changed)."""
    blocks = []
    for sh in shapes:
        if sh.get("shape_id") == title_id:
            continue
        out = []
        lines = [" ".join("".join(r.get("text", "") for r in p.get("runs", [])).split()) for p in sh.get("paragraphs") or []]
        out += [x for x in lines if x]
        for row in (sh.get("table") or {}).get("cells") or []:
            out.append(" | ".join(" ".join(c.split()) if isinstance(c, str) else "" for c in row))
        if sh.get("type") == "picture":
            out.append(f"picture ({sh['alt_text']})" if sh.get("alt_text") else "picture")
        if sh.get("shapes"):
            out += slide_lines(sh["shapes"], None)
        if out:
            blocks.append(((roles or {}).get(sh.get("shape_id"), ""), out))
    if roles and len(blocks) > 1:
        return [x for role, lines in blocks for x in ([f"{role}:"] if role else []) + [f"  {y}" for y in lines]]
    return [x for _, lines in blocks for x in lines]


def sketch(slides: list[dict], selected: str = "", whole: set[int] | None = None) -> str:
    """The deck as the router sees it: [{index, title, lines, kinds}] -> per slide a line with its number, title and
    what it holds besides text, then its text a line at a time; and what the person has selected (measured: without
    it, "add it here" went to the wrong slide). whole: when the deck is too large for the router's window, the slides
    (indexes) whose text is kept; the others show their titles."""
    out = []
    for s in slides:
        kinds = f" [{', '.join(sorted(s['kinds']))}]" if s["kinds"] else ""
        layout = f" ({s['layout']} layout)" if s.get("layout") else ""  # "Agenda Layout", "Separador": what a slide is
        out.append(f"Slide {s['index'] + 1}{layout}, title: {s['title'] or '(none)'}{kinds}")
        if whole is None or s["index"] in whole:
            out += [f"    {x}" for x in s.get("lines") or []]
    if selected:
        out.append(f"Selected by the person: {selected}")
    return "\n".join(out)


def prompt(request: str, deck: str, count: int = 0, ideas: str = "") -> str:
    groups = "\n".join(f"- {k}: {v}" for k, v in DESCRIPTIONS.items())
    # the Artist's last ideas in this conversation, so a choice of one ("the second") is read as its number (loop._route)
    shown = (f"The Artist's last ideas in this conversation, {ideas}\n\n" if ideas else "")
    return (
        f"The open deck{f' ({count} slides)' if count else ''}:\n{deck or '(no deck open)'}\n\n" + shown +
        f"The person's request:\n<request>{request}</request>\n\n"
        "First, intent: one sentence, in the request's language, saying what the person wants done or asks. "
        "Then where: the slide number; when part of a slide's text changes, also the one line of the deck that "
        "changes, copied as it is; for a whole slide (add, delete, move, duplicate) the slide number alone. Then "
        "choose the groups of tools that are needed:\n"
        f"{groups}\n\n"
        "How to tell them apart:\n"
        "- Adding, changing or removing a point, bullet, item, word, number or line in existing text is text "
        "(not structure). Structure is for whole slides (add, delete, move, duplicate, layout) and shapes.\n"
        "- A new slide also needs text (its title and points are written).\n"
        "- At the end, last: after the deck's last slide (measured: \"at the end\" was put before the annexes).\n"
        '- A slide named by its title or subject ("the agenda", "the thank-you slide") to delete, move or duplicate '
        "is the whole slide: say slide N in the intent; where is the slide number alone.\n"
        "- A value that is in a table (see the deck) is table.\n"
        "- A new chart or diagram is table.\n"
        "- Facts the request says come from documents, the knowledge base or policies need knowledge; content "
        "written from it onto slides also needs text or structure, and notes for the source.\n"
        '- "Here" and "this" mean what the person has selected.\n'
        "- kind: change (something must change: choose its groups), question (only an answer: no groups), unclear "
        '(too vague to know what to change, like "change it": no groups), ideas (asks for ideas, proposals or another '
        'way to show a slide - "more visual", "how could this look" - without choosing one: where is that slide, no '
        "groups).\n"
        + ('- When the person chooses one of the Artist\'s last ideas (by its number or its words), kind: change, and '
           '"idea": its number.\n' if ideas else "")
        + 'Answer with JSON only: {"intent": "...", "where": "slide N: \\"the deck\'s words\\"", '
        '"kind": "change|question|unclear|ideas", "groups": ["..."]' + (', "idea": 0}' if ideas else "}")
    )


def parse(text: str) -> tuple[set[str] | None, str, str]:
    """The groups the answer names (known ones only; None when it cannot be read: then every tool is offered), the
    intent it states with where in the deck, and its kind: change | question | unclear."""
    try:
        answer = json.loads(text[text.find("{") : text.rfind("}") + 1])
        groups = answer["groups"]
    except (ValueError, KeyError, TypeError):
        return None, "", "change"
    intent = " ".join(str(answer.get("intent") or "").split())
    where = " ".join(str(answer.get("where") or "").split())
    # measured: an intent naming the deck's words got the right shape 10 times in 10, without them 5
    if where and intent and answer.get("kind") == "change":
        intent = f"{intent} (where: {where})"
    kind = answer.get("kind") if answer.get("kind") in ("change", "question", "unclear", "ideas") else "change"
    chosen = {g for g in groups if g in ALL} if isinstance(groups, list) else None
    if kind == "change" and not chosen:
        chosen = None  # a change with no group named: every tool, rather than none
    elif kind == "change":
        # the text tools with every change: text is in almost all of them, and without them a bullet routed to
        # "structure" was made by deleting the list and adding a text box
        chosen |= {"text"}
    return chosen, intent, kind


QUOTES = (("'", "'"), ('"', '"'), ("«", "»"), ("“", "”"), ("‘", "’"))  # noqa: RUF001 - the typographic quotes are meant


def unquoted(text: str) -> str:
    """The request without the pieces it quotes: those are found in the deck by their own exact text (locate), and are
    often the new text to write (measured: «Margem acima do objetivo», to add to slide 5, shared "acima do objetivo"
    with slide 3, and the turn edited slide 3)."""
    out = " ".join(text.split())
    for piece in quoted(text):
        for open_, close in QUOTES:
            out = out.replace(f"{open_}{piece}{close}", " ")
    return " ".join(out.split())


def quoted(text: str) -> list[str]:
    """The pieces of a request between quotation marks ('...', "...", «...», “...”), read character by character."""
    out = []
    for open_, close in QUOTES:
        at = 0
        while True:
            i = text.find(open_, at)
            if i < 0:
                break
            j = text.find(close, i + 1)
            if j < 0:
                break
            piece = " ".join(text[i + 1 : j].split())
            if len(piece) >= 3:
                out.append(piece)
            at = j + 1
    return out


def where_text(text: str) -> str:
    """The deck's words the answer's where quotes (after "slide N:" and a role such as "body:"), or ""."""
    try:
        where = str(json.loads(text[text.find("{") : text.rfind("}") + 1]).get("where") or "")
    except (ValueError, AttributeError):
        return ""
    rest = where.split(":", 1)[1] if ":" in where else ""
    for role in ("text box:", "body, left:", "body, right:", "body:", "table:", "shape:", "title:", "subtitle:"):
        if rest.strip().lower().startswith(role):
            rest = rest.strip()[len(role) :]
    return " ".join(rest.strip().strip('"«»“”').split())


def locate(paragraphs: list[tuple[int, int, str, str]], needle: str) -> list[tuple[int, int, str]]:
    """Where the deck holds `needle` word for word (spaces and case aside): [(slide number, shape id, the paragraph's
    place: "[n]" or "row r, column c")]. A lexical fact (the text is there or not), for the model to edit the shape the
    words are in (measured: given the words only, it edited a neighbouring shape)."""
    want = " ".join(needle.split()).casefold()
    if len(want) < 3:
        return []
    return [(n, sid, place) for n, sid, place, text in paragraphs if want in " ".join(text.split()).casefold()]


def phrase_slide(request: str, slides: list[dict], least: int = 15, ahead: int = 5) -> tuple[int, str] | None:
    """The slide (number) sharing the longest run of characters with the request word for word ("4.3 Incidentes -
    BINCs") when that run is long (`least`) and clearly ahead of every other slide's (`ahead`): a lexical fact the
    router's where can be checked against (measured: on an 80-slide deck the router named 31 for that title, on 29,
    and a wording change in its prompt moved it). [(number, the shared text)]; None when no slide stands out."""
    req = " ".join(request.split())
    low = req.casefold()
    # a whole line of one slide, and of no other, in the request word for word: that slide, however close another
    # slide's words come (measured: "KPIs Enabling 2/2" shared 18 characters with its slide and 15 with "KPIs Enabling
    # 1/2"'s, not ahead enough; the router's where named slide 10, and slide 9 was duplicated)
    holders: dict[str, set[int]] = {}
    for s in slides:
        for line in [s.get("title") or "", *s.get("lines", [])]:
            key = " ".join(line.split()).casefold()
            if len(key) >= 8 and " " in key:  # two words at least (one, "Destaques", is said in passing)
                holders.setdefault(key, set()).add(s["index"] + 1)
    whole = sorted((len(k), k) for k in holders if k in low)
    if whole and len(holders[whole[-1][1]]) == 1:
        at = low.find(whole[-1][1])
        return next(iter(holders[whole[-1][1]])), req[at : at + whole[-1][0]]
    scored = []
    for s in slides:
        text = " ".join(" ".join([s.get("title") or "", *s.get("lines", [])]).split()).casefold()
        m = difflib.SequenceMatcher(None, low, text, autojunk=False).find_longest_match(0, len(low), 0, len(text))
        scored.append((m.size, s["index"] + 1, req[m.a : m.a + m.size].strip()))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < least or (len(scored) > 1 and scored[0][0] - scored[1][0] < ahead):
        return None
    return scored[0][1], scored[0][2]


def contained(paragraphs: list[tuple[int, int, str, str]], needle: str) -> list[tuple[int, int, str, str]]:
    """The paragraphs a longer text holds whole (the router's where ran two lines of the deck together, found in no
    single paragraph): [(slide, shape, place, the paragraph's text)], each at least 12 characters (measured: unnamed,
    the model set the paragraph before the one to change)."""
    have = " ".join(needle.split()).casefold()
    out = []
    for n, sid, place, text in paragraphs:
        t = " ".join(text.split())
        if len(t) >= 12 and t.casefold() in have:
            out.append((n, sid, place, t))
    return out


def idea_of(text: str) -> int | None:
    """The number of the Artist's idea the answer says the person chose ("idea": 2), or None."""
    try:
        idea = json.loads(text[text.find("{") : text.rfind("}") + 1]).get("idea")
    except (ValueError, AttributeError):
        return None
    return idea if isinstance(idea, int) and 1 <= idea <= 5 else None


def where_slide(text: str) -> int | None:
    """The slide number the answer's where names ("slide 15: ...", "Slide 2", "16"), read with string operations;
    None when it names none."""
    try:
        where = str(json.loads(text[text.find("{") : text.rfind("}") + 1]).get("where") or "")
    except (ValueError, AttributeError):
        return None
    rest = where.strip().lower()
    if rest.startswith("slide"):
        rest = rest[5:].lstrip()
    digits = ""
    for ch in rest:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits else None


def tools_of(groups: set[str] | None) -> set[str] | None:
    """The tool names the groups and the core hold; None (every tool) when there was no route."""
    if groups is None:
        return None
    return {name for g in groups | {"core"} for name in GROUPS[g]}
