"""The assistant's tools (spec section 5; technical design section 6.4): their definitions are the JSON Schemas in
contracts/tools/, and each has an executor here. Executors validate the arguments against the schema, check the
person's role, act on the turn's draft, and return a result or an error {code, message, hint} the model can act on.

Reading tools see the draft when this turn's proposal has one for the deck, so the model sees its own changes.
Editing tools apply to the draft (never to a saved version) and are recorded in the proposal. ask_user,
propose_plan and update_instructions pause the turn until the person answers."""

from __future__ import annotations

import copy

import asyncio
import base64
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
from PIL import Image

from ..config import REPO_DIR
from ..docengine import files, ops, read, render
from .. import search, storage
from .context import describe as context_describe
from ..kb import KBError
from ..domain.leases import Leased
from ..storage import NotFound

log = logging.getLogger("slides.tools")

TOOLS_DIR = REPO_DIR / "contracts" / "tools"
EDITING = (
    "redesign_slide",
    "update_text",
    "fill_slide",
    "add_slides",
    "add_chart",
    "edit_chart",
    "draw_diagram",
    "duplicate_shape",
    "connect_shapes",
    "fit_text",
    "change_template",
    "copy_slides",
    "edit_paragraphs",
    "format_text",
    "add_slide",
    "duplicate_slide",
    "delete_slide",
    "move_slide",
    "change_layout",
    "add_shape",
    "move_resize_shape",
    "delete_shape",
    "insert_image",
    "replace_image",
    "set_alt_text",
    "edit_table",
    "set_notes",
)
WAITING = ("ask_user", "propose_plan", "update_instructions")


def load_schemas(folder: Path = TOOLS_DIR) -> dict[str, dict]:
    return {
        p.name.removesuffix(".schema.json"): json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(folder.glob("*.schema.json"))
    }


KB_TOOLS = ("kb_search", "kb_get", "kb_read_document")
SOURCE_KEYS = ("domain", "document", "title", "section", "page", "updated", "link")  # what a passage carries to cite it


def sources_of(messages: list[dict]) -> list[dict]:
    """The knowledge-base documents the stored tool results hold (spec KB-3), once each in the order first read, with
    the sections and pages read in them: {domain, document, title, updated, link, sections, pages}."""
    out: dict[tuple, dict] = {}
    for m in messages:
        if m.get("role") != "tool" or m.get("name") not in KB_TOOLS:
            continue
        try:
            r = json.loads(m.get("content") or "{}")
        except ValueError:
            continue
        for p in r.get("passages") or ([r] if r.get("document") else []):
            item = {k: r[k] for k in ("domain", "document", "title", "updated") if k in r} | p  # a page names its document once
            if not item.get("document"):
                continue
            doc = out.setdefault(
                (item.get("domain"), item["document"]),
                {k: item[k] for k in ("domain", "document", "title", "updated", "link") if item.get(k) is not None}
                | {"sections": [], "pages": []},
            )
            if item.get("section") and item["section"] not in doc["sections"]:
                doc["sections"].append(item["section"])
            if item.get("page") is not None and item["page"] not in doc["pages"]:
                doc["pages"].append(item["page"])
    return list(out.values())


def _point_text_of(point) -> tuple[str, str]:
    """A point as (heading, text), as ops reads it."""
    if isinstance(point, dict):
        return str(point.get("heading") or "").strip(), str(point.get("text") or "").strip()
    return "", str(point).strip()


def _figures(text: str) -> set[str]:
    """The figures a text states, as values: "80.000€" and "80 000" are 80000, "450.000,00" is 450000, "44/2024" is 44
    and 2024; at least two digits ("8.º" is not one). String methods only: a lexical fact."""
    out = set()
    for word in str(text).replace("/", " ").replace("(", " ").replace(")", " ").split():
        kept = "".join(c for c in word if c.isdigit() or c in ".,").strip(".,")
        whole = kept.split(",")[0].replace(".", "")  # the decimal part aside, the thousands' dots out
        if len(whole) >= 2 and whole.isdigit():
            out.add(str(int(whole)))
    return out


def _passages_holding(messages: list[dict], content: dict) -> list[dict]:
    """The stored knowledge-base results reduced to the passages that hold, word for word, one of the content's lines of
    25 characters or more (case and spacing aside), or two of its figures or more, as sources_of reads them (measured:
    a slide written from the cover's turn's passages, in the model's own words - "Idade: Mutuário(s) entre 18 e 35
    anos", "80.000€", "450.000" - matched none word for word and had no source, 3 runs in 6; the figures it keeps
    exactly, as the prompt asks)."""
    flat = lambda x: " ".join(str(x).split()).lower()  # noqa: E731
    lines = []
    for point in content.get("points") or []:
        lines += list(point.values()) if isinstance(point, dict) else [point]
    # a line's own end punctuation aside (measured: "...anos de idade." in the slide, "...anos de idade;" in the passage)
    figures = set().union(*[_figures(x) for x in lines]) if lines else set()
    lines = [flat(x).rstrip(".;:, ") for x in lines if len(flat(x)) >= 25]
    out = []
    for m in messages:
        if m.get("role") != "tool" or m.get("name") not in KB_TOOLS or not (lines or len(figures) >= 2):
            continue
        try:
            r = json.loads(m.get("content") or "{}")
        except ValueError:
            continue
        held = [p for p in r.get("passages") or []
                if any(x in flat(p.get("text") or "") for x in lines) or len(figures & _figures(p.get("text") or "")) >= 2]
        if held:
            out.append({**m, "content": json.dumps({**r, "passages": held}, ensure_ascii=False)})
    return out


def _without_nulls(node):
    """An optional field sent as null is a field left out (measured: gemma-4 sends "theme_color": null on every run,
    and repeated the refused call until the turn ended); a required one, left out, is then refused by name."""
    if isinstance(node, dict):
        return {k: _without_nulls(v) for k, v in node.items() if v is not None}
    if isinstance(node, list):
        return [_without_nulls(v) for v in node]
    return node


PARAGRAPH_KEYS = ("level", "alignment", "runs", "text")
RUN_KEYS = ("text", "bold", "italic", "theme_color")


def _plain_paragraphs(node):
    """A paragraph given as {"text": ...} (measured: gemma-4 writes them so) is a paragraph of one run; keys a
    paragraph or a run does not have (measured: "type": "body" inside paragraphs, repeated after the refusal) are
    dropped there - and only there: anywhere else an unknown key is still refused."""
    if isinstance(node, dict):
        out = {k: _plain_paragraphs(v) for k, v in node.items()}
        if isinstance(out.get("paragraphs"), list):
            paragraphs = []
            for p in out["paragraphs"]:
                if isinstance(p, dict):
                    p = {k: v for k, v in p.items() if k in PARAGRAPH_KEYS}
                    if "runs" not in p and isinstance(p.get("text"), str):
                        # plain text: its line breaks are new paragraphs (measured: gemma-4 sent a four-bullet list as
                        # one "text" with \n); line breaks inside a paragraph stay possible with runs
                        lines = p.pop("text").split("\n")
                        paragraphs += [{**p, "runs": [{"text": line}]} for line in lines[:-1]]
                        p["runs"] = [{"text": lines[-1]}]
                    if isinstance(p.get("runs"), list):
                        p["runs"] = [
                            {k: v for k, v in r.items() if k in RUN_KEYS} if isinstance(r, dict) else r for r in p["runs"]
                        ]
                paragraphs.append(p)
            out["paragraphs"] = paragraphs
        return out
    if isinstance(node, list):
        return [_plain_paragraphs(v) for v in node]
    return node


def _split_lists(name: str, args: dict) -> str:
    """A long point that is a list ("Critérios: A; B; C; ...": over 200 characters, three or more parts between "; ")
    becomes a point per part (measured: a 7-item criteria list as one point did not fit its box even at 14 pt, and the
    turn ended with it overflowing). Literal splitting at "; " only. Returns the note."""
    items = args.get("slides") if name == "add_slides" else [args.get("content")]
    said = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("points"):
            continue
        out = []
        for n, point in enumerate(item["points"], 1):
            parts = [x.strip() for x in point.split("; ")] if isinstance(point, str) and len(point) > 200 else []
            if len([x for x in parts if x]) >= 3:
                out += [x.rstrip(";") for x in parts if x]
                said.append(str(n))
            else:
                out.append(point)
        item["points"] = out
    if not said:
        return ""
    return f" Point{'s' if len(said) > 1 else ''} {', '.join(said)} held a list: each of its items is a point of its own."


def _drop_echo(name: str, args: dict) -> str:
    """A point that only says the slide's title again is left out, and said (measured: the model's one point was the
    title again on a cover, and on a slide it wrote without reading the knowledge base, 7 runs in 14; refused, covers
    failed 4 runs in 4). Literal repetition only: the same words, ignoring case and spacing. Returns the note."""
    def same(a, b):
        return bool(a) and bool(b) and " ".join(str(a).split()).lower() == " ".join(str(b).split()).lower()

    items = args.get("slides") if name == "add_slides" else [args.get("content")]
    note = ""
    for item in items or []:
        if not isinstance(item, dict) or not item.get("points"):
            continue
        kept = []
        for point in item["points"]:
            words = [point.get("heading"), point.get("text")] if isinstance(point, dict) else [point]
            if not any(same(w, item.get("title")) or same(w, item.get("subtitle")) for w in words):
                kept.append(point)
        if len(kept) < len(item["points"]):
            item["points"] = kept
            note = " A point that only repeated the title was left out."
            if not kept and not item.get("subtitle"):
                note += (" The slide says only its title: if the person asked for its content, find it (kb_search for"
                         " facts) and write it (fill_slide).")
    return note


def _long_points(args: dict, schema: dict) -> str:
    """Which points are longer than a point may be, and by how much: "Points 1, 4 (238, 215 characters) are longer
    than 200 characters." (for add_slides, by slide)."""
    items = args.get("slides") if isinstance(args.get("slides"), list) else [args.get("content") or {}]
    said = []
    for n, item in enumerate(items, 1):
        long = []
        for k, point in enumerate((item or {}).get("points") or [], 1):
            # a line holds 200 characters; a {heading, text} point, 200 and 300 (the contract's limits)
            if isinstance(point, dict):
                size = max(len(str(point.get("heading") or "")) - 200, len(str(point.get("text") or "")) - 300)
                over = size > 0 and max(len(str(point.get("heading") or "")), len(str(point.get("text") or "")))
            else:
                over = len(str(point)) > 200 and len(str(point))
            if over:
                long.append((k, over))
        if long:
            where = f"slide {n}: " if len(items) > 1 else ""
            nums, sizes = ", ".join(str(k) for k, _ in long), ", ".join(str(c) for _, c in long)
            said.append(f"{where}point{'s' if len(long) > 1 else ''} {nums} ({sizes} characters)")
    if not said:
        return "A point is too long."
    text = "; ".join(said)
    return text[0].upper() + text[1:] + " - longer than a point may be (200 characters; a text under a heading, 300)."


def _content_slips(args: dict) -> None:
    """What the model puts on the wrong side of content, moved where it goes: the slide's text beside content; and
    (measured on "a new slide with a chart / a diagram", 6 runs in 6) content.layout, the same as the call's layout,
    refused and sent again unchanged up to five times, and the chart's title in content.chart, as add_chart takes it."""
    stray = [k for k in ("title", "subtitle", "points", "sources", "chart", "diagram") if k in args]
    if stray and (isinstance(args.get("content"), dict) or "content" not in args):
        # what the slide says, beside content instead of in it (measured: "title" beside content, 2 runs in 4 of a KB
        # slide and turn 2 of the first-use index; refused, the model gave up): put in it, unless content says it too
        content = args.setdefault("content", {})
        for k in stray:
            value = args.pop(k)
            content.setdefault(k, value)
    content = args.get("content")
    if not isinstance(content, dict):
        return
    if "layout" in content:
        layout = content.pop("layout")
        args.setdefault("layout", layout)
    chart = content.get("chart")
    if isinstance(chart, dict) and "title" in chart:
        title = chart.pop("title")
        if isinstance(title, str) and title.strip() and not content.get("title"):
            content["title"] = title  # the slide's heading says it (a chart's own title would say it twice)


def _enum_case(args: dict, schema: dict) -> None:
    """A value the schema lists in another case ("TEXT_BOX" for "text_box": measured, gemma-4 sends both) is taken
    as the listed one. Exact comparison of the lower-cased strings; anything else is left for validation to refuse."""
    for _ in range(20):  # one fix per pass; a call has few enum fields
        error = next(
            (
                e
                for e in jsonschema.Draft202012Validator(schema).iter_errors(args)
                if e.validator == "enum" and isinstance(e.instance, str)
            ),
            None,
        )
        if error is None:
            return
        match = [v for v in error.validator_value if isinstance(v, str) and v.lower() == error.instance.lower()]
        if len(match) != 1:
            return
        *path, last = list(error.absolute_path)
        target = args
        for key in path:
            target = target[key]
        target[last] = match[0]


# checked here, never needed by the model to write a call (it reads requirements in the descriptions): left out of
# what it is sent, which is a fifth of a 32k window otherwise
VALIDATION_ONLY = (
    *("allOf", "anyOf", "if", "then", "else", "additionalProperties"),
    *("maxLength", "minLength", "maxItems", "minItems", "$schema", "$id"),
)


def _for_model(node):
    """The schema without the keywords only validation uses (a model server may turn tool schemas into a grammar),
    and without the properties marked "x-hidden" (accepted, not offered: paragraphs' runs where text is enough)."""
    if isinstance(node, dict):
        out = {k: _for_model(v) for k, v in node.items() if k not in VALIDATION_ONLY and k != "x-hidden"}
        if isinstance(node.get("properties"), dict):
            out["properties"] = {
                k: _for_model(v) for k, v in node["properties"].items() if not (isinstance(v, dict) and v.get("x-hidden"))
            }
        return out
    if isinstance(node, list):
        return [_for_model(v) for v in node]
    return node


TEXT_EDITS = (
    "update_text", "edit_paragraphs", "add_slide", "add_shape", "duplicate_shape", "format_text", "change_layout", "edit_table",
    "fit_text", "fill_slide", "add_slides",
)  # fmt: skip

# what the context already gives (the decks, the layouts) or another tool returns (kb_search: the passages' text):
# still run when called, not offered - each costs part of the fixed share of the window (technical design 6.2: 25%)
NOT_OFFERED = ("list_decks", "list_layouts", "kb_get", "build_generation")  # build_generation: the app's, after approval


def definitions(schemas: dict[str, dict]) -> list[dict]:
    """The tools as the model is given them (OpenAI's function format)."""
    out = []
    for name, s in schemas.items():
        if name in NOT_OFFERED:
            continue
        params = _for_model({k: v for k, v in s.items() if k in ("type", "properties", "required", "additionalProperties")})
        out.append({"type": "function", "function": {"name": name, "description": s["description"], "parameters": params}})
    return out


def without_figures(definition: dict) -> dict:
    """add_slide as offered when no chart or diagram is asked for: its content without chart and diagram (measured: with
    them, and draw_diagram offered, the model wrote "a slide with the conditions of the product" without reading the
    knowledge base 7 runs in 14; without both, it read it 6 runs in 6). They are still accepted if sent."""
    out = copy.deepcopy(definition)
    fn = out["function"]
    fn["description"] = fn["description"].replace(", or a chart or diagram", "")
    content = fn["parameters"]["properties"].get("content") or {}
    for k in ("chart", "diagram"):
        (content.get("properties") or {}).pop(k, None)
    return out


class ToolError(Exception):
    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code, self.hint = code, hint

    def as_dict(self) -> dict:
        return {"error": {"code": self.code, "message": str(self), "hint": self.hint}}


@dataclass
class Turn:
    """What a turn's tools work on."""

    pid: str
    cid: str
    email: str
    conversation: dict
    images: list[bytes] = field(default_factory=list)  # rendered slides to show the model next
    proposal: dict | None = None
    changed: set[str] = field(default_factory=set)  # decks changed this turn
    can_see: bool = False
    failed_edits: int = 0  # editing calls that returned an error this turn
    tool_defs: list = field(default_factory=list)  # the tools offered this turn (Agent._offered)
    intent: str = ""  # what the person wants, as the router understood it
    changes: bool = True  # does it need a change (the router chose some groups)?
    kind: str = "change"  # change | question | unclear, as the router read the request
    done: list[str] = field(default_factory=list)  # the edits made this turn, in words, for the "## Now" section
    groups: set[str] | None = None  # the tool groups the router chose (None: every tool)
    start_order: dict[str, list[int]] = field(default_factory=dict)  # deck id -> its slide IDs when the request was made
    focus: int | None = None  # the slide (ID) the request is about, as the router named it: the deck map centres there
    located: list[str] = field(default_factory=list)  # where the deck holds the words the request names (router.locate)
    overflowing: set = field(default_factory=set)  # (deck, slide id, shape id) an edit of this turn left too long
    result_chars: int = 12_000  # how much one tool result may hold (the loop sets it from the context budget)
    read_calls: set = field(default_factory=set)  # (tool, arguments) called this turn: a reading call is not repeated
    model: str = "application"  # the model's id (the loop sets it); "application": a call the application made
    idea: int | None = None  # the Artist's idea the person chose, as the router read it (loop._artist_step)
    made_calls: set = field(default_factory=set)  # (tool, arguments) of the edits made this turn: never made twice
    sources_asked: bool = False  # the turn was told once that a new slide had its title alone (_unfounded)


# reading tools a turn need not call twice with the same arguments (the deck changes only by the turn's own edits,
# whose results say what changed)
REPEAT_GUARD = ("get_slide", "get_deck_outline", "list_layouts", "list_templates", "list_decks", "kb_search", "kb_get",
                "kb_read_document", "kb_list_images", "search_project", "search_conversations")  # fmt: skip


def slide_name(t: Turn, did: str, sid: int) -> str:
    """A slide as the request numbers it ("slide 4"), or by its ID when this turn made it (measured: a new slide
    named by its place, "slide 32", was taken for the slide 32 of the request's numbering, and resized)."""
    start = t.start_order.get(did) or []
    return f"slide {start.index(sid) + 1}" if sid in start else f"the new slide (ID {sid})"


class Executor:
    def __init__(self, app) -> None:
        self.app = app  # the services: projects, decks, proposals, assets, templates, renderer
        self.schemas = load_schemas()

    # ── helpers ──────────────────────────────────────────────────────
    def _deck_id(self, t: Turn, args: dict) -> str:
        did = args.pop("deck_id", None) or t.conversation.get("active_deck")
        if not did:
            raise ToolError("NO_ACTIVE_DECK", "No deck is open.", "Call list_decks and give deck_id, or create_deck.")
        try:
            self.app.decks.get(t.pid, did, t.email)
        except NotFound:
            raise ToolError(
                "DECK_NOT_FOUND", f"There is no deck {did} in this project.", "Call list_decks for the deck IDs."
            ) from None
        return did

    def _bytes(self, t: Turn, did: str) -> bytes:
        """The deck as this turn sees it: its draft when the turn has changed it, else its current version."""
        p = t.proposal
        if p and did in p["decks"]:
            return self.app.proposals.draft_path(t.pid, p, did).read_bytes()
        _, data = self.app.decks.version_bytes(t.pid, did, t.email)
        return data

    async def _title_for(self, t: Turn, points: list) -> str:
        """A short title for points sent without one: from the person's request and the points (slides_titler); "" when
        it cannot be had (the slide is then made as sent)."""
        try:
            request = next((m["content"] for m in reversed(self.app.conversations.messages(t.pid, t.cid))
                            if m["role"] == "user"), "")  # fmt: skip
            lines = "\n".join(f"- {' '.join(x for x in _point_text_of(p) if x)}" for p in points)
            ask = f"The request:\n<request>{request}</request>\n\nThe slide's points:\n{lines}"
            model = await asyncio.to_thread(self.app.models.resolve, None if t.model == "application" else t.model)
            got = ""
            async for chunk in self.app.models.stream(model, "slides_titler", [{"role": "user", "content": ask}], None, 100):
                got += ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
            title = json.loads(got[got.find("{") : got.rfind("}") + 1]).get("title") or ""
            return " ".join(str(title).split())[:120]
        except Exception as e:  # noqa: BLE001 - no title rather than no slide
            log.warning("no title could be given", extra={"err.type": type(e).__name__})
            return ""

    def _unsaid(self, t: Turn, title: str) -> bool:
        """Is a title in none of the person's words (its words of 4 letters or more, "slide" and "diapositivo" aside,
        in no message of theirs)? A lexical fact: "Novo Slide", "Título do Slide" for "Cria um slide"."""
        words = {w for w in (x.strip(".,;:!?«»\"'()").casefold() for x in title.split())
                 if len(w) >= 4 and w not in ("slide", "slides", "diapositivo", "diapositivos")}  # fmt: skip
        said = " ".join(str(m.get("content") or "") for m in self.app.conversations.messages(t.pid, t.cid)
                        if m["role"] == "user").casefold()  # fmt: skip
        return not any(w in said for w in words)

    def _untitled(self, t: Turn, name: str, args: dict) -> bool:
        """Points sent with no title, for a new slide or one whose heading is empty (a chart's or a diagram's slide
        aside: their figure is the content)."""
        c = args.get("content")
        if not isinstance(c, dict) or not c.get("points") or str(c.get("title") or "").strip():
            return False
        if c.get("chart") or c.get("diagram"):
            return False
        if name == "add_slide" or not args.get("slide_id"):
            return True
        try:
            order = read.outline(read.open_deck(self._bytes(t, self._deck_id(t, args))))
        except (NotFound, ToolError):
            return False
        x = int(args["slide_id"])
        found = order[x - 1] if x < 256 and 1 <= x <= len(order) else next((o for o in order if o["slide_id"] == x), None)
        return found is None or not (found.get("title") or "").strip()

    def _copy_source(self, t: Turn, did: str, args: dict) -> dict:
        """The deck slides are copied from: in the project, not the target, not itself in review (its slides would
        differ from any version); its slides named by number or ID; its version recorded for the replay."""
        src = str(args["from_deck_id"])
        if src == did:
            raise ToolError("SAME_DECK", "The slides are already in this deck.", "Use duplicate_slide to copy within a deck.")
        if t.proposal and src in t.proposal["decks"]:
            raise ToolError("SOURCE_IN_REVIEW", "That deck has changes in this proposal.", "Copy from it before changing it.")
        try:
            deck = self.app.decks.get(t.pid, src, t.email)
            _, data = self.app.decks.version_bytes(t.pid, src, t.email)
        except NotFound:
            raise ToolError(
                "DECK_NOT_FOUND", f"There is no deck {src} in the project.", "The decks are in your context."
            ) from None
        order = [o["slide_id"] for o in read.outline(read.open_deck(data))]
        ids = []
        for x in args["slide_ids"]:
            x = int(x)
            if x < 256:
                if not 1 <= x <= len(order):
                    raise ToolError("SLIDE_NOT_FOUND", f"Deck {src} has slides 1 to {len(order)}.", "")
                x = order[x - 1]
            elif x not in order:
                raise ToolError("SLIDE_NOT_FOUND", f"Deck {src} has no slide {x}.", "get_deck_outline lists its slides.")
            ids.append(x)
        return {**args, "from_deck_id": src, "slide_ids": ids, "from_version": deck["current_version"]}

    @staticmethod
    def _positions(args: dict, data: bytes, start: list[int] | None = None) -> dict:
        """Slides named by their number in the deck (1 = first, as people say them) become their IDs: a slide ID is 256
        or more (ECMA-376 ST_SlideId) and a deck has at most 200 slides, so the two never meet (measured: gemma-4
        guessed slide 350 for "slide 150" of a 200-slide deck). A number means what it meant when the request was made
        (`start`, the deck's order then): the person, the router and the deck map all number the deck as it was, and
        a slide deleted in this turn is not its neighbour (measured: "delete slide 39", repeated on the renumbered
        deck, deleted slides 39, 40 and 41)."""
        keys = [k for k in ("slide_id", "after_slide_id", "before_slide_id") if isinstance(args.get(k), int) and args[k] < 256]
        if not keys:
            return args
        now = [o["slide_id"] for o in read.outline(read.open_deck(data))]
        order = start or now
        out = dict(args)
        for k in keys:
            if k != "slide_id" and (not now or (k == "after_slide_id" and args[k] == 0)):
                # an empty deck has one place for a new slide; "after slide 0" is the first place (measured: a new deck
                # from a template, empty, refused "add a slide" five times with "the deck has slides 1 to 0")
                del out[k]
                if now:
                    out["before_slide_id"] = now[0]
                continue
            if not 1 <= args[k] <= len(order):
                # the slides that exist, by number and ID, and the way to the end (measured: "after slide 18" in a
                # one-slide deck, told only "the deck has slides 1 to 1", was sent again unchanged twice, 2 runs in 8)
                added = [s for s in now if s not in order]
                hint = f"Slide {len(order)}, the last, is ID {order[-1]}." if order else ""
                if added:
                    hint += f" Slides added in this request are named by their ID: {', '.join(map(str, added))}."
                if k == "after_slide_id":
                    hint += " For the end of the deck, leave after_slide_id out."
                if not now:  # measured: fill_slide on "slide 1" of an empty deck, four times
                    hint = "The deck has no slides: add_slide makes the first (with its content)."
                said = f"There is no slide {args[k]}: the deck has slides 1 to {len(order)}. Nothing was changed."
                raise ToolError("SLIDE_NOT_FOUND", said, hint.strip())
            sid = order[args[k] - 1]
            if sid not in now:
                raise ToolError(
                    "SLIDE_DELETED",
                    f"Slide {args[k]} was deleted earlier in this request.",
                    "It is done: do not delete another slide in its place. Say what you changed.",
                )
            out[k] = sid
        return out

    def _missing_slide(self, t: Turn, args: dict) -> bool:
        """Is the slide fill_slide names absent from the deck (by number or ID)?"""
        try:
            data = self._bytes(t, self._deck_id(t, args))
        except (NotFound, ToolError):
            return False
        ids = [o["slide_id"] for o in read.outline(read.open_deck(data))]
        sid = int(args.get("slide_id") or 0)
        start = t.start_order.get(self._deck_id(t, args)) or ids
        return (sid < 256 and not 1 <= sid <= len(start)) or (sid >= 256 and sid not in ids)

    def _empty_focus(self, t: Turn, args: dict) -> int | None:
        """The slide the router named for this request (t.focus), when it has no text at all and add_slide brings
        text content (not a figure) right after it or with no place given; None otherwise."""
        content = args.get("content")
        if not isinstance(content, dict) or content.get("chart") or content.get("diagram"):
            return None
        if not (content.get("title") or content.get("points")):
            return None
        try:
            prs = read.open_deck(self._bytes(t, self._deck_id(t, args)))
        except (NotFound, ToolError):
            return None
        order = [o["slide_id"] for o in read.outline(prs)]
        focus = t.focus if t.focus in order else (order[0] if len(order) == 1 else None)  # no slide named: the only one
        if focus is None:
            return None
        after = args.get("after_slide_id")
        start = t.start_order.get(self._deck_id(t, args)) or order
        after_id = start[after - 1] if isinstance(after, int) and 0 < after <= len(start) else after
        if after is not None and after_id != focus:
            return None
        s = read.slide(prs, focus)
        texts = [p for sh in s["shapes"] for x in [sh, *(sh.get("shapes") or [])] for p in x.get("paragraphs") or []
                 if any((r.get("text") or "").strip() for r in p.get("runs") or [])]
        has_table = any(sh.get("type") in ("table", "chart") for sh in s["shapes"])
        if texts and not has_table:
            # its title alone, in none of the person's words, is a placeholder: the slide is still to be written
            # (measured: "Cria um slide" made "Novo Slide" / "Título do Slide", and the next request's index went on a
            # second slide, 4 runs in 8)
            # (a cover's heading is a text box, not a title placeholder: measured, the outline's title was "" and
            # "Novo Slide" on "2_Capa S/Imagem" was not seen; so: one box with text, a short line)
            holders = [sh for sh in s["shapes"] if any(any((r.get("text") or "").strip() for r in p.get("runs") or [])
                                                        for p in sh.get("paragraphs") or [])]  # fmt: skip
            words = " ".join(" ".join("".join(r.get("text") or "" for r in p.get("runs") or []) for p in texts).split())
            if len(holders) == 1 and len(words.split()) <= 8 and self._unsaid(t, words):
                return focus
        return None if texts or has_table else focus

    def _same_text(self, t: Turn, name: str, args: dict) -> bool:
        """Does the edit only write back the text the shape already has (each paragraph set to its own text)?"""
        try:
            prs = read.open_deck(self._bytes(t, self._deck_id(t, args)))
            sid = args["slide_id"]
            order = [o["slide_id"] for o in read.outline(prs)]
            start = t.start_order.get(self._deck_id(t, args)) or order
            if isinstance(sid, int) and sid < 256:
                sid = start[sid - 1] if 0 < sid <= len(start) else None
            shape = next(x for x in read.slide(prs, sid)["shapes"] if x["shape_id"] == args.get("shape_id"))
        except (NotFound, ToolError, KeyError, StopIteration, TypeError, ValueError):
            return False
        now = ["".join(r.get("text", "") for r in p.get("runs") or []).strip() for p in shape.get("paragraphs") or []]
        if name == "update_text":
            new = [str(p.get("text") or "".join(r.get("text", "") for r in p.get("runs") or [])).strip()
                   for p in args.get("paragraphs") or []]  # fmt: skip
            return bool(new) and new == now
        ops_ = args.get("operations") or []
        if ops_ and all(o.get("op") == "insert" for o in ops_):
            # a paragraph the shape already holds, inserted again (measured: asked to fit a box it could not, the model
            # inserted its 300-character point a second time)
            return all(" ".join(str(o.get("text") or "").split()) in [" ".join(x.split()) for x in now] for o in ops_)
        if not ops_ or any(o.get("op") != "set" for o in ops_):
            return False
        def same(o):
            i = o.get("index")
            return isinstance(i, int) and 0 <= i < len(now) and str(o.get("text") or "").strip() == now[i]

        return all(same(o) for o in ops_)

    def _next_slide(self, t: Turn, args: dict) -> bool:
        """Does a figure name, by its number, the slide after the last one (a slide not made yet)?"""
        if not self._missing_slide(t, args):
            return False
        data = self._bytes(t, self._deck_id(t, args))
        start = t.start_order.get(self._deck_id(t, args)) or [o["slide_id"] for o in read.outline(read.open_deck(data))]
        return int(args.get("slide_id") or 0) == len(start) + 1

    def _added_next(self, t: Turn, args: dict) -> int | None:
        """The slide this turn added right after the slides the request numbered, if any (then "slide N+1" is it)."""
        did = self._deck_id(t, args)
        now = [o["slide_id"] for o in read.outline(read.open_deck(self._bytes(t, did)))]
        start = t.start_order.get(did) or now
        n = len(start)
        return now[n] if len(now) > n and now[n] not in start else None

    async def _figure_on_a_new_slide(self, t: Turn, name: str, args: dict) -> dict:
        """A diagram or chart for "a new slide with ...", named by the next number: the slide is added at the end, then
        the figure drawn on it (measured: the model drew a diagram on "slide 4" of a three-slide deck, was told it is
        not there, and ended the turn saying it was done). A chart's title becomes the slide's heading; a diagram, which
        has none, goes on the template's blank layout. Tried first on a copy, so a figure refused leaves no slide."""
        did = self._deck_id(t, args)
        prs = read.open_deck(self._bytes(t, did))
        title = str(args.get("title") or "").strip() if name == "add_chart" else ""
        lay = ops._layout_for_content(prs, {"title": title}) if title else ops.blank_layout(prs)
        slide = {"layout": lay.name, **({"content": {"title": title}} if title else {})}
        figure = {k: v for k, v in args.items() if not (name == "add_chart" and k == "title")}
        try:  # the whole of it on a copy first
            sid = ops.add_slide(prs, lay.name, **({"content": slide["content"]} if title else {}))
            sid = (sid["slides"] if isinstance(sid, dict) else sid)[-1]
            getattr(ops, name)(prs, **{**{k: v for k, v in figure.items() if k != "deck_id"}, "slide_id": sid})
        except ops.OpError as e:
            return {"error": e.as_dict()}
        if args.get("deck_id"):
            slide["deck_id"] = args["deck_id"]
        made = await self._edit(t, "add_slide", slide)
        if "error" in made:
            return made
        sid = made["new_slide_ids"][-1]
        done = await self._edit(t, name, {**figure, "slide_id": sid})
        if "error" not in done:
            how = "with the chart's title as its heading" if title else "without a title (fill_slide gives it one)"
            done["note"] += f" There was no slide {args['slide_id']}: slide {sid} was added at the end for it, {how}."
            done["new_slide_ids"] = [sid]
        return done

    def _unfounded(self, t: Turn, name: str, args: dict) -> dict | None:
        """A new slide with its title alone on a layout with a place for text, said once (measured: "a slide with the
        conditions of the product" made with its title alone, the text box showing its prompt). Not checked: whether
        points come from a source - refused when not the person's words verbatim, dictation rephrased, a thank-you
        slide and a list of metrics were refused too, and the model gave up instead of searching (4 requests of 88)."""
        since = []
        for m in self.app.conversations.messages(t.pid, t.cid):
            since = [] if m["role"] == "user" else [*since, m]
        items = args.get("slides") if name == "add_slides" else [args.get("content") or {}]
        points = []
        for item in items or []:
            for point in (item or {}).get("points") or []:
                points += [v for v in (point.values() if isinstance(point, dict) else [point]) if str(v).strip()]
        offered = {d["function"]["name"] for d in t.tool_defs}
        if name == "add_slide" and not points and isinstance(args.get("content"), dict) and args.get("layout"):
            content = args["content"]
            if content.get("title") and not content.get("subtitle") and not content.get("chart") and not content.get("diagram"):
                from ..docengine import layouts

                try:
                    prs = read.open_deck(self._bytes(t, self._deck_id(t, args)))
                    lay = ops._layout(prs, args["layout"])
                except (ops.OpError, NotFound, ToolError):
                    return None
                if layouts.slots(lay, prs.slide_width, prs.slide_height)["items"]:
                    where = "search first (kb_search) and " if "kb_search" in offered and not sources_of(since) else ""
                    # the empty slide first (measured: told only to write the points, after "Decide tu" the model
                    # wrote a slide of invented welcome points for "Cria um slide")
                    return {"error": {"code": "TITLE_ALONE", "message": f"{args['layout']!r} has a place for text, "
                            "and the slide has its title alone.", "hint": "If the request names no content, make the "
                            "slide empty for the person to write: add_slide with the layout alone, no content. If it "
                            f"names a subject: {where}give the slide its points; or, for a title alone, choose a layout "
                            "with no text place."}}  # fmt: skip
        return None

    async def _cite(self, t: Turn, did: str, sid: int | None, content: dict) -> None:
        """A slide written from the knowledge base gets its sources in its notes (spec KB-3: "Fonte: <title>, <section
        or p. N>, <date> - <link>"): the documents the content names, as this turn read them; when it names none it
        recognises, every document the turn read, as consulted (measured: told to cite in the notes, the model did not,
        2 runs in 2; and the reranker cannot tell the documents a slide used from those a search returned: 0.97 for
        one unused, 0.60 for one used)."""
        if sid is None:
            return
        since, every = [], self.app.conversations.messages(t.pid, t.cid)
        for m in every:
            since = [] if m["role"] == "user" else [*since, m]
        read_docs = sources_of(since)
        if not read_docs:
            # read in an earlier turn of the conversation: cited only for what the slide says in a passage's own words
            # (measured: the cover's turn searched, the next slide was written from those passages without searching
            # again, 3 runs in 3, and its notes had no source); a literal match, case and spacing aside
            read_docs = sources_of(_passages_holding(every, content))
            for d in read_docs:  # its own words: the source, not only consulted
                content = {**content, "sources": [*(content.get("sources") or []), d.get("title") or d.get("document")]}
        if not read_docs:
            return
        named = {" ".join(str(x).split()).lower() for x in content.get("sources") or []}
        used = [d for d in read_docs if {(d.get("title") or "").lower(), (d.get("document") or "").lower()} & named]
        docs, label = (used, "Fonte") if used else (read_docs, "Fontes consultadas")
        lines = []
        for d in docs:
            where = ", ".join([*d.get("sections", [])[:2], *(f"p. {n}" for n in d.get("pages", [])[:2])])
            date = (d.get("updated") or "")[:10]
            parts = [d.get("title") or d.get("document"), where, date]
            line = ", ".join(x for x in parts if x) + (f" - {d['link']}" if d.get("link") else "")
            lines.append(f"{label}: {line}" if label == "Fonte" else f"- {line}")
        text = "\n".join(lines) if label == "Fonte" else "Fontes consultadas:\n" + "\n".join(lines)
        try:  # what the notes said stays, the sources under it
            had = (read.slide(read.open_deck(self._bytes(t, did)), sid).get("notes") or "").strip()
        except (KeyError, NotFound):
            had = ""
        if text not in had:
            await self._edit(t, "set_notes", {"slide_id": sid, "text": f"{had}\n\n{text}" if had else text, "deck_id": did})

    def _image(self, t: Turn, ref: dict) -> bytes:
        try:
            asset = self.app.assets.get(t.pid, ref["asset_id"])
        except NotFound:
            raise ToolError(
                "IMAGE_NOT_FOUND", "There is no such image in the project.", "Use an asset_id the person attached."
            ) from None
        if asset["kind"] != "image":
            raise ToolError("IMAGE_NOT_FOUND", "That asset is not an image.", "")
        return self.app.assets.read(t.pid, ref["asset_id"])

    def resolve(self, t: Turn):
        """The recorded arguments as the operation takes them (asset IDs become image bytes): for replays too."""

        def run(name: str, args: dict) -> dict:
            args = dict(args)
            if "image" in args and isinstance(args["image"], dict):
                args["image"] = self._image(t, args["image"])
            if name == "change_template":  # the template's file, emptied of its sample slides
                ref = args.pop("template")
                args["template"] = files.without_slides(self.app.templates.bytes_of(t.pid, ref))
                args["template_ref"] = ref
            if name == "copy_slides":  # the source deck at the version copied from (versions never change)
                args.pop("move", None)
                version = args.pop("from_version")
                args["source"] = self.app.layout.version_file(t.pid, args["from_deck_id"], version).read_bytes()
            return args

        return run

    # ── dispatch ─────────────────────────────────────────────────────
    def parse(self, name: str, raw_args: str | dict) -> dict:
        """The tool's arguments, checked against its schema; ToolError otherwise."""
        if name not in self.schemas:
            raise ToolError("UNKNOWN_TOOL", f'There is no tool "{name}".', "")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
        except ValueError:
            raise ToolError(
                "BAD_ARGUMENTS", "The arguments are not valid JSON.", "Send the arguments as one JSON object."
            ) from None
        if not isinstance(args, dict):
            raise ToolError("BAD_ARGUMENTS", "The arguments must be a JSON object.", "")
        args = _plain_paragraphs(_without_nulls(args))
        _enum_case(args, self.schemas[name])
        if name in ("add_slide", "fill_slide"):
            _content_slips(args)
        try:
            jsonschema.validate(args, self.schemas[name])
        except jsonschema.ValidationError as e:
            where = "/".join(str(x) for x in e.absolute_path) or "(arguments)"
            hint = "Correct what the message names (the allowed values are in it, or in the tool's parameters) and call again."
            if e.validator == "maxLength" and "points" in e.absolute_path:
                # every point too long, by its length (measured: the message quoted the whole passage and named the
                # first only; the model sent the same points again, or fixed one and met the next: 3 runs in 3)
                raise ToolError("POINTS_TOO_LONG", "Nothing was changed: a point is longer than 1000 characters.",
                                "A point is one short line on a slide: say each in your words, the key fact only; "
                                "the details can go in the speaker notes (set_notes).") from None  # fmt: skip
            if name == "edit_paragraphs" and "'index' is a required property" in e.message:
                hint = "set and delete need the paragraph's [n] from the deck map; update_text replaces all of a shape's text."
            # "nothing was changed": measured, after a refused add_slide the model edited "the slide it had added"
            prefix = "Nothing was changed. " if name in EDITING else ""
            raise ToolError("BAD_ARGUMENTS", f"{prefix}{where}: {e.message}", hint) from None
        return args

    async def call(self, t: Turn, name: str, raw_args: str | dict) -> dict:
        """The result the model reads (a dict, sent as JSON), errors included; each call recorded in the project's
        audit trail with its arguments, the model and its result (security review M4: never written)."""
        if name in ("add_slide", "fill_slide"):
            try:
                parsed = self.parse(name, raw_args)
            except ToolError:
                parsed = None
            if parsed is not None and self._untitled(t, name, parsed):
                # points and no title for an untitled slide (measured: an index sent as its points alone went without
                # a heading, 1 run in 4; refused, the model gave up or asked the person, 3 runs in 3; told to write the
                # title after, it wrote it to "slide 2", a slide that was not there, 3 runs in 3): titled from the
                # request and the points, in the same call (prompts/titler.md)
                title = await self._title_for(t, parsed["content"]["points"])
                if title:
                    raw_args = {**parsed, "content": {**parsed["content"], "title": title}}
        result = await self._call(t, name, raw_args)
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except ValueError:
            args = raw_args
        error = result.get("error") if isinstance(result, dict) else None
        line = {"at": storage.now(), "user": t.email, "event": "tool_call", "conversation_id": t.cid, "tool": name,
                "arguments": args, "model": t.model or "application", "ok": not error,
                **({"error": str(error.get("code") or "error")} if isinstance(error, dict) else {}),
                "deck_id": (result.get("deck_id") if isinstance(result, dict) else None) or None,
                "proposal_id": (t.proposal or {}).get("id"),
                **({"version": result["current_version"]} if isinstance(result, dict)
                   and isinstance(result.get("current_version"), int) else {})}  # fmt: skip
        try:
            await asyncio.to_thread(storage.append_line, self.app.layout.project_audit(t.pid), line, "project-audit-line")
        except Exception as e:  # noqa: BLE001 - the trail never stops the work; its failure is logged (type only)
            log.error("the project's audit line was not written", extra={"err.type": type(e).__name__})
        return result

    async def _call(self, t: Turn, name: str, raw_args: str | dict) -> dict:
        try:
            args = self.parse(name, raw_args)
            key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
            if name in REPEAT_GUARD and key in t.read_calls:
                # measured: a question answered after two searches went on with get_slide 15 times, to the turn's limit
                hint = "Its result is above: use it. If you have what you need, answer the person now."
                said = f"{name} was already called with these arguments."
                return {"error": {"code": "ALREADY_READ", "message": said, "hint": hint}}
            t.read_calls.add(key)
            echo = _drop_echo(name, args) if name in ("add_slide", "fill_slide", "add_slides") else ""
            if name in ("add_slide", "fill_slide", "add_slides"):
                echo += _split_lists(name, args)
            if name in ("add_slide", "fill_slide", "add_slides") and "longer" in _long_points(args, {}):
                # placed, and said (measured: refused, a 438-character point was sent again unchanged and the slide
                # was lost, 3 runs in 6): the slide exists, its text fitted to its box, to be shortened
                echo += " " + _long_points(args, {}).replace("longer than a point may be", "long for a point") + (
                    " A point is one short line: shorten them (edit_paragraphs), the details in the notes (set_notes).")
            if name == "add_slide" and not args.get("layout"):
                # with content, the layout it fits (measured: content sent without a layout was refused, and the turn
                # ended with nothing made)
                if not isinstance(args.get("content"), dict):
                    raise ToolError("BAD_ARGUMENTS", "Nothing was changed: add_slide needs a layout or the slide's content.",
                                    "Give the slide's content (the layout it fits is chosen), or a layout.")  # fmt: skip
                prs = read.open_deck(self._bytes(t, self._deck_id(t, args)))
                first = not len(prs.slides) or args.get("position") == 0
                args["layout"] = ops.layout_for_new(prs, args["content"], first).name
            if name == "add_slide" and self._empty_focus(t, args) is not None:
                # the slide the request is about has no text yet: its content goes on it (measured: "Cria um slide",
                # then "write an index of the topics": the index made a second slide, the first left showing its
                # prompts, 2 runs in 3; told the slide was empty, the model filled it 3 replays in 10)
                sid = self._empty_focus(t, args)
                fill = {"slide_id": sid, "content": args["content"], **({"layout": args["layout"]} if args.get("layout") else {})}
                if args.get("deck_id"):
                    fill["deck_id"] = args["deck_id"]
                done = await self._edit(t, "fill_slide", fill)
                if "error" not in done:
                    # the call as sent counts as made (measured: the same add_slide sent again went on three new
                    # slides, the index twice in the deck)
                    t.made_calls.add((name, json.dumps(args, sort_keys=True, ensure_ascii=False)))
                    # its number said (measured: told only "written on it", the closing message said "a new slide,
                    # slide 2" for a one-slide deck)
                    order = [o["slide_id"] for o in read.outline(read.open_deck(self._bytes(t, self._deck_id(t, args))))]
                    done["note"] += (f" The slide the request is about, slide {order.index(sid) + 1}, had no text yet: the"
                                     " content was written on it and no slide was added. Say so.")
                    done["written_on"] = order.index(sid) + 1  # for the turn's list of what was done (loop._done)
                return done
            if name == "fill_slide" and not args.get("slide_id"):
                # (measured: on an empty deck the model sent fill_slide with no slide, refused, and the cover was lost)
                did = self._deck_id(t, args)
                order = [o["slide_id"] for o in read.outline(read.open_deck(self._bytes(t, did)))]
                if t.focus in order:
                    args["slide_id"] = t.focus
                elif len(order) == 1:
                    args["slide_id"] = order[0]
                elif not order:
                    args["slide_id"] = 1  # not there yet: made below, as a slide named by the next number is
                else:
                    raise ToolError("BAD_ARGUMENTS", "Nothing was changed: fill_slide needs the slide (slide_id).",
                                    "Name the slide by its number or ID; for a new slide, use add_slide.")  # fmt: skip
            if name == "fill_slide" and self._missing_slide(t, args):
                empty = self._empty_focus(t, {**args, "slide_id": None})
                if empty is not None:  # a slide not there yet, while the one the request is about is empty: that one
                    args = {**args, "slide_id": empty}
            if name == "fill_slide" and self._missing_slide(t, args):
                # a slide that is not there yet: written, it is made (measured: on an empty deck the model called
                # fill_slide for "slide 1" 30 times, told each time to use add_slide)
                data = self._bytes(t, self._deck_id(t, args))
                prs = read.open_deck(data)
                lay = ops.layout_for_new(prs, args["content"], first=not len(prs.slides))
                if args.get("layout"):
                    try:
                        lay = ops._layout(prs, args["layout"])
                    except ops.OpError:
                        pass
                new = {"layout": lay.name, "content": args["content"]}
                if args.get("deck_id"):
                    new["deck_id"] = args["deck_id"]
                made = await self._edit(t, "add_slide", new)
                if "error" not in made:
                    made["note"] += f" There was no slide {args['slide_id']}: a new slide was made with this content." + echo
                return made
            if name in ("add_slide", "fill_slide", "add_slides") and not t.sources_asked:
                said = self._unfounded(t, name, args)
                if said:
                    t.sources_asked = True
                    return said
            if name in ("draw_diagram", "add_chart") and self._next_slide(t, args):
                added = self._added_next(t, args)
                if added is None:
                    return await self._figure_on_a_new_slide(t, name, args)
                args = {**args, "slide_id": added}  # the slide this turn added there: the figure goes on it
            if name in ("edit_paragraphs", "update_text") and self._same_text(t, name, args):
                # (measured: "shorten the agenda's points" sent every point back unchanged, was told "ok", and the
                # reply said they were shortened)
                return {"error": {"code": "SAME_TEXT", "message": "Nothing was changed: the new text is the slide's text "
                        "as it is.", "hint": "Write the changed text the request asks for."}}  # fmt: skip
            if name == "redesign_slide":  # the idea chosen, or the wish, made into the design to apply
                args = await self._redesign_args(t, args)
            key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
            if name in EDITING and key in t.made_calls:
                # (measured: told its answer said something was still to do, the model made the same fill_slide again,
                # and the index was on two slides)
                return {"error": {"code": "ALREADY_MADE", "message": "Nothing was changed: this exact change was made "
                        "earlier in this turn.", "hint": "If the request is done, say what you changed."}}  # fmt: skip
            if name in EDITING:
                done = await self._edit(t, name, args)
                if "error" not in done:
                    t.made_calls.add(key)
                if echo and "error" not in done:
                    done["note"] += echo
                return done
            return await getattr(self, f"t_{name}")(t, args)
        except ToolError as e:
            return e.as_dict()
        except ops.OpError as e:
            out = {"error": e.as_dict()}
            if name == "fill_slide" and e.code == "SLIDE_NOT_FOUND":
                # measured: meaning a new slide, the model called fill_slide on the next ID five times
                out["error"]["hint"] = "fill_slide writes an existing slide: for a new one, call add_slide with this content."
            return out

    async def _edit(self, t: Turn, name: str, args: dict) -> dict:
        self.app.projects.get(t.pid, t.email, roles=("owner", "editor"))
        did = self._deck_id(t, args)
        leases = getattr(self.app.decks, "leases", None)
        if leases is not None:  # spec PJ-13: a deck another member has open is not changed
            try:
                leases.check(did, t.email)
            except Leased as e:
                raise ToolError(
                    "DECK_LEASED", f"The deck is being edited by {e.holder}.", "Tell the person; change it when they close it."
                ) from None
        if t.proposal is None:
            open_p = self.app.proposals.open_in(t.pid, t.cid)
            if open_p and open_p["status"] == "pending":
                raise ToolError(
                    "PROPOSAL_WAITING",
                    "Earlier changes are waiting for the person's decision.",
                    "Ask the person to accept or reject them before making new ones.",
                )
            t.proposal = open_p or self.app.proposals.start(t.pid, t.cid)
        caption = None
        if isinstance(args.get("image"), dict) and "kb_image_id" in args["image"]:
            args, caption = await self._kb_image_asset(t, args)  # recorded with the asset: replays never call Cortex
        deck = self.app.decks.get(t.pid, did, t.email)
        _, current = self.app.decks.version_bytes(t.pid, did, t.email)
        data = self.app.proposals.draft(t.pid, t.proposal, did, deck["current_version"], current)
        if name == "copy_slides":
            args = self._copy_source(t, did, args)
        args = self._positions(args, data, t.start_order.get(did))  # recorded with the IDs: a replay never depends on positions
        new, result = ops.apply(data, name, self.resolve(t)(name, args))
        removed = [int(args["slide_id"])] if name == "delete_slide" else None
        if name == "change_layout":
            removed = [int(args["slide_id"])]
        self.app.proposals.record(t.pid, t.proposal, did, name, {**args, "deck_id": did}, result, new, removed)
        t.changed.add(did)
        t.read_calls.clear()  # the deck changed: reading it again is new
        if name in ("add_slide", "fill_slide") and (args.get("content") or {}) and "error" not in result:
            await self._cite(t, did, (result.get("new_slide_ids") or result.get("slides") or [None])[0], args["content"])
        if name == "add_slides" and "error" not in result:
            for sid, item in zip(result.get("new_slide_ids") or [], args.get("slides") or [], strict=False):
                await self._cite(t, did, sid, item)
        out = {"ok": True, "deck_id": did, **result, "note": "Applied to the draft; the person reviews it before it is saved."}
        if result.get("unmatched"):
            out["note"] += " Text that had no place in the new layout was kept as a text box: mention it."
        if result.get("left_out"):
            out["note"] += f" Its layout has no place for the {' and '.join(result['left_out'])}: it was left out; say so."
        if result.pop("moved_to_notes", None):
            out.pop("moved_to_notes", None)
            out["note"] += " The cover's subtitle sentence did not fit with its other lines: it is in the slide's notes; say so."
        if name == "add_slide" and result.get("continued"):
            ids = ", ".join(map(str, result["slides"][1:]))
            out["note"] += f" Its points did not fit one slide: they continue on {result['continued']} more (ID {ids}), in order."
        if name == "add_slide" and result.get("instead_of"):
            why = "has no place for its title" if result.get("figure") else "has no place for this content"
            out["note"] += f" {result['instead_of']!r} {why}: the slide is on {result['layout']!r}."
        if name == "fill_slide" and result.get("layout"):
            out["note"] += f" The slide is now on the layout {result['layout']!r}, which has a place for each part: say so."
        if name == "fit_text":
            out["note"] += (
                f" The box was made {result['grown_pt']} pt taller, into free space below it."
                if result.get("grown_pt")
                else f" The text is at {round(result.get('scale', 1) * 100)}% of its size."
            )
        if name == "add_slide" and result.get("figure") == "chart":
            out["note"] += f" Its chart is shape {result['shape_id']}."
        if name == "add_slide" and result.get("figure") == "diagram":
            boxes, arrows = ", ".join(map(str, result["shape_ids"])), ", ".join(map(str, result["connector_ids"])) or "none"
            out["note"] += f" Its diagram: boxes {boxes} (in the nodes' order), arrows {arrows}."
        if name == "draw_diagram":
            boxes, arrows = ", ".join(map(str, result["shape_ids"])), ", ".join(map(str, result["connector_ids"])) or "none"
            out["note"] += f" Boxes {boxes} (in the nodes' order), styled like {result['styled_from']}; arrows {arrows}."
            if result.get("covers"):  # as add_chart's (ops.draw_diagram now says what its boxes cover)
                ids = ", ".join(map(str, result["covers"]))
                out["note"] += (f" It covers shape {ids}: move what is under it (move_resize_shape), or draw it on a "
                                "slide of its own.")
            out.pop("covers", None)
        if name == "add_chart":
            out["note"] += f" The chart is shape {result['shape_id']}."
            if result.get("covers"):
                out["note"] += f" It covers shape {', '.join(map(str, result['covers']))}: move one (move_resize_shape)."
        if name in ("duplicate_shape", "connect_shapes"):
            what = "copy" if name == "duplicate_shape" else "connector"
            out["note"] += f" The {what} is shape {result['shape_id']}."
            if result.get("covers"):  # placed over others: said, so it is moved (move_resize_shape)
                ids = ", ".join(map(str, result["covers"]))
                out["note"] += f" It covers shape {ids}: move it to a free place (move_resize_shape), or leave the box out."
            if result.get("moved"):
                out["note"] += " The place asked for covered other shapes: it is at the nearest free place to it."
            out.pop("covers", None)  # said in the note
            out.pop("moved", None)
        if name in ("delete_slide", "move_slide"):
            out["note"] += (
                " This step is done. Slide numbers keep their meaning until the person decides: the deck map keeps them"
                + (" and marks this slide deleted." if name == "delete_slide" else ".")
            )
        if name in ("add_slide", "duplicate_slide", "copy_slides") and result.get("slides"):
            # where the new slides are: the model names slides by number, and guessed one past the end without it
            # numbers keep the request's meaning (_positions): a new slide is named by its ID (measured: without it,
            # the model named the new slide 10 in a deck of 9)
            new_ids = [int(s) for s in result["slides"]]
            many = len(new_ids) > 1
            ids = ", ".join(map(str, new_ids))
            out["note"] += f" The new slide{'s are' if many else ' is'} ID {ids}: name {'them' if many else 'it'} by ID."
            out["new_slide_ids"] = new_ids
        if name == "copy_slides" and args.get("move"):  # a move: the slides leave the deck they came from
            for sid in args["slide_ids"]:
                await self._edit(t, "delete_slide", {"deck_id": args["from_deck_id"], "slide_id": sid})
            out["note"] += f" They were removed from deck {args['from_deck_id']}."
        if name in TEXT_EDITS:  # the self-check (spec section 10: overflow): what this edit left too long for its box
            prs, was = read.open_deck(new), read.open_deck(data)
            for sid in result.get("slides", []):
                try:
                    shapes = read.slide(prs, int(sid))["shapes"]
                except KeyError:
                    continue
                try:  # a shape that did not fit before the edit is the template's design, not this edit's doing
                    # (measured on a real template: an agenda's seven 36 pt numbers in 40 pt boxes, all reported)
                    before = {x["shape_id"] for x in read.slide(was, int(sid))["shapes"] if x.get("overflow")}
                except KeyError:
                    before = set()
                for sh in shapes:
                    if sh.get("overflow") and sh["shape_id"] not in before:
                        t.overflowing.add((did, int(sid), sh["shape_id"]))  # checked again before the turn ends
                        on = slide_name(t, did, int(sid))
                        out["note"] += (
                            f" The text of shape {sh['shape_id']} on {on} does not fit its box:"
                            " fit it (fit_text), shorten it, make the box larger (move_resize_shape),"
                            " or split it over two slides."
                        )
        if name in ("insert_image", "replace_image") and not caption:
            out["note"] += " If the picture has no alt text, write one with set_alt_text (one sentence on what it shows)."
        if caption:
            out["caption"] = caption
            out["note"] += " The document gives this picture a caption: use it for the alt text (set_alt_text)."
        return out

    # ── the project's memory and search (spec PJ-9, PJ-10, PJ-11) ───
    async def t_remember(self, t: Turn, args: dict) -> dict:
        try:
            item = await self.app.memory.add(t.pid, t.email, args["text"], t.cid)
        except ValueError as e:
            raise ToolError("MEMORY_REFUSED", str(e), "") from None
        return {
            "ok": True,
            "kept": item["text"],
            "note": "Say in your reply what you kept: the person can edit it on the project page.",
        }

    async def _ranked(self, t: Turn, query: str, passages: list[dict], top_k: int, left: int) -> dict:
        found, note = await asyncio.to_thread(search.rank, self.app.reranker, query, passages, top_k)
        for p in found:
            p["text"] = f"<data>{p['text']}</data>"
        out = {"query": query, "passages": found}
        if left:
            out["left_out"] = f"{left} older passages were not searched: ask more precisely, or name the conversation."
        if note:
            out["note"] = note
        if not found:
            out["note"] = (out.get("note", "") + " Nothing found.").strip()
        return out

    async def t_search_conversations(self, t: Turn, args: dict) -> dict:
        convs = sorted(self.app.conversations.list(t.pid, t.email), key=lambda c: c.get("updated_at") or "", reverse=True)
        passages: list[dict] = []
        for c in convs:  # the most recent first, up to the maximum
            passages += search.conversation_passages(c, self.app.conversations.messages(t.pid, c["id"]))
        left = max(len(passages) - search.MAX_PASSAGES, 0)
        return await self._ranked(t, args["query"], passages[: search.MAX_PASSAGES], int(args.get("top_k", 5)), left)

    async def t_search_project(self, t: Turn, args: dict) -> dict:
        docs = sorted(
            (a for a in self.app.assets.list(t.pid) if a["kind"] == "document"), key=lambda a: a["created_at"], reverse=True
        )
        if not docs:
            return {"query": args["query"], "passages": [], "note": "The project has no reference documents."}
        passages = [
            {"asset_id": a["id"], "document": a["name"], "where": x["where"], "text": x["text"]}
            for a in docs
            for x in self.app.assets.passages(t.pid, a["id"])
        ]
        left = max(len(passages) - search.MAX_PASSAGES, 0)
        return await self._ranked(t, args["query"], passages[: search.MAX_PASSAGES], int(args.get("top_k", 5)), left)

    # ── the knowledge base (technical design section 8) ─────────────
    async def _kb(self, fn, *a, **kw):
        try:
            return await asyncio.to_thread(fn, *a, **kw)
        except KBError as e:
            code, hint = {
                404: ("KB_NOT_FOUND", "It does not exist, or the person cannot read it. Search again."),
                400: ("KB_BAD_REQUEST", "Check the arguments."),
                413: ("KB_TOO_LARGE", "Choose another picture."),
                429: ("KB_BUSY", "The knowledge base is busy: try again in a moment, or tell the person."),
                503: ("KB_UNAVAILABLE", "The knowledge base is not configured here: tell the person."),
            }.get(e.status, ("KB_FAILED", "The knowledge base did not answer: tell the person."))
            raise ToolError(code, f"Knowledge base: {e}", hint) from None

    async def _kb_domains(self, t: Turn, asked: list[str] | None) -> list[str] | None:
        """The domains to search: those asked for, else the project's (spec PJ-12), always within the person's own;
        None for all of the person's."""
        want = asked or self.app.projects.get(t.pid, t.email)["settings"].get("kb_domains") or []
        if not want:
            return None
        mine = {d["id"] for d in await self._kb(self.app.kb.domains, t.email)}
        ok = [d for d in want if d in mine]
        if not ok:
            raise ToolError(
                "KB_NO_DOMAIN",
                "None of these knowledge-base domains is open to the person.",
                f"The domains they can use: {', '.join(sorted(mine)) or 'none'}.",
            )
        return ok

    def _passage(self, t: Turn, p: dict) -> dict:
        """A passage as the model reads it: its text wrapped as data (spec KB-6), with the source fields the chat
        lists (sources_of)."""
        src = {k: p[k] for k in SOURCE_KEYS if p.get(k) is not None}
        out = {k: p[k] for k in ("id", "index", "score") if p.get(k) is not None}
        return {**out, **src, "text": f"<data>{p.get('text', '')}</data>"}

    def _fit(self, t: Turn, items: list[dict]) -> tuple[list[dict], int]:
        """As many whole items as one result may hold (never a cut item); and how many were left out."""
        kept, size = [], 0
        for item in items:
            n = len(json.dumps(item, ensure_ascii=False))
            if kept and size + n > t.result_chars:
                break
            kept.append(item)
            size += n
        return kept, len(items) - len(kept)

    async def t_kb_search(self, t: Turn, args: dict) -> dict:
        domains = None if args.get("documents") else await self._kb_domains(t, args.get("domains"))
        r = await self._kb(self.app.kb.search, t.email, args["query"], domains, args.get("top_k", 6), args.get("documents"))
        passages, left = self._fit(t, [self._passage(t, p) for p in r.get("passages", [])])
        out = {"query": r.get("query", args["query"]), "domains": r.get("domains"), "passages": passages}
        if left:
            out["left_out"] = f"{left} more passages did not fit: search more precisely to see them."
        if not passages:
            out["note"] = "Nothing found. Try other words, or ask the person where it is."
        return out

    async def t_kb_get(self, t: Turn, args: dict) -> dict:
        return self._passage(t, await self._kb(self.app.kb.passage, t.email, args["id"]))

    async def t_kb_read_document(self, t: Turn, args: dict) -> dict:
        after = int(args.get("after", 0))
        r = await self._kb(self.app.kb.document_passages, t.email, args["domain"], args["path"], after, 50)
        passages, left = self._fit(
            t,
            [
                self._passage(t, {**p, **{k: r.get(k) for k in ("domain", "document", "title", "updated")}})
                for p in r.get("passages", [])
            ],
        )
        out = {k: r.get(k) for k in ("domain", "document", "title", "updated", "total")}
        out["passages"] = passages
        nxt = passages[-1]["index"] + 1 if left and passages else r.get("next")
        if nxt is not None:
            out["next"] = nxt
            out["note"] = f"More follows: call again with after={nxt} if you need it."
        if r.get("total") == 0:
            out["note"] = "The document has no passages yet (it may have just been added to the knowledge base)."
        return out

    async def t_generate_image(self, t: Turn, args: dict) -> dict:
        """A new picture from the configured service (spec IM-6), kept as a project image for insert_image."""
        from ..imagegen import ImageGenError

        self.app.projects.get(t.pid, t.email, roles=("owner", "editor"))
        try:
            png = await asyncio.to_thread(self.app.imagegen.generate, args["prompt"], args.get("shape") or "wide")
        except ImageGenError as e:
            raise ToolError("IMAGE_GENERATION_FAILED", f"No picture: {e}.", "Tell the person; do not try another way.") from None
        name = f"generated - {' '.join(args['prompt'].split())[:60]}.png"
        try:
            limit = self.app.settings.file["limits"]["upload_mb"] << 20
            asset = await self.app.assets.add_image(t.pid, t.email, name, png, limit)
        except files.Rejected as e:
            raise ToolError("IMAGE_REFUSED", str(e), "") from None
        note = "A new image of the project: put it on a slide with insert_image; its alt text says it was generated."
        return {"ok": True, "asset_id": asset["id"], "note": note}

    async def t_kb_list_images(self, t: Turn, args: dict) -> dict:
        images = await self._kb(self.app.kb.images, t.email, args["domain"], args["path"])
        images = sorted(images, key=lambda i: i.get("repeats", 1) > 1)  # pictures repeated on many pages (logos) last
        kept, left = self._fit(t, images)
        out = {"domain": args["domain"], "document": args["path"], "images": kept}
        if left:
            out["left_out"] = f"{left} more pictures did not fit in this answer."
        return out

    async def _kb_image_asset(self, t: Turn, args: dict) -> tuple[dict, str | None]:
        ref = args["image"]
        data, _ = await self._kb(self.app.kb.image, t.email, ref["kb_domain"], ref["kb_document"], ref["kb_image_id"])
        name = f"{ref['kb_document'].rsplit('/', 1)[-1]} - {ref['kb_image_id']}"[-200:]
        try:
            asset = await self.app.assets.add_image(
                t.pid, t.email, name, data, self.app.settings.file["limits"]["upload_mb"] << 20
            )
        except files.Rejected as e:
            raise ToolError("IMAGE_REFUSED", str(e), "Choose another picture.") from None
        listed = await self._kb(self.app.kb.images, t.email, ref["kb_domain"], ref["kb_document"])
        caption = next((i.get("caption") for i in listed if i.get("id") == ref["kb_image_id"]), None)
        return {**args, "image": {"asset_id": asset["id"]}}, caption

    # ── reading ──────────────────────────────────────────────────────
    async def t_list_decks(self, t: Turn, args: dict) -> dict:
        return {
            "decks": [
                {k: d[k] for k in ("id", "title", "slide_count", "updated_at", "template")}
                for d in self.app.decks.list(t.pid, t.email)
            ],
            "active_deck": t.conversation.get("active_deck"),
        }

    async def t_list_templates(self, t: Turn, args: dict) -> dict:
        return {
            "templates": [
                {
                    "kind": x["kind"],
                    "id": x["id"],
                    "name": x["name"].get("en") if isinstance(x["name"], dict) else x["name"],
                    "layouts": x.get("layouts", []),
                }
                for x in self.app.templates.listing(t.pid)
            ]
        }

    async def t_get_deck_outline(self, t: Turn, args: dict) -> dict:
        did = self._deck_id(t, args)
        return {"deck_id": did, "slides": read.outline(read.open_deck(self._bytes(t, did)))}

    def _slide_in(self, t: Turn, args: dict):
        """(deck id, the presentation as this turn sees it, the slide's ID) for a slide named by number or ID."""
        did = self._deck_id(t, args)
        prs = read.open_deck(self._bytes(t, did))
        order = [o["slide_id"] for o in read.outline(prs)]
        start = t.start_order.get(did) or order
        sid = int(args["slide_id"])
        if sid < 256:
            sid = start[sid - 1] if 0 < sid <= len(start) else -1
        if sid not in order:
            raise ToolError("SLIDE_NOT_FOUND", f"The deck has slides 1 to {len(order)}.", "Name the slide by its number.")
        return did, prs, sid

    async def t_ask_artist(self, t: Turn, args: dict) -> dict:
        """The Artist's ideas for a slide (agent/artist.py), kept on the conversation for the person to choose by number
        in a later turn; nothing changes."""
        from ..docengine import layouts
        from . import artist

        did, prs, sid = self._slide_in(t, args)
        s = prs.slides.get(sid)
        slide = artist.slide_of(read.slide(prs, sid), layouts.heading(s.slide_layout, prs.slide_width, prs.slide_height))
        model = await asyncio.to_thread(self.app.models.resolve, None if t.model == "application" else t.model)
        goal = artist.goal_of(title=self.app.decks.get(t.pid, did, t.email).get("title") or "")
        found = await artist.ideas(self.app, model, slide, 3, str(args.get("wish") or ""), goal)
        async with storage.lock(t.pid):
            conv = self.app.conversations.get(t.pid, t.cid, t.email)
            conv["artist_ideas"] = {"deck_id": did, "slide_id": sid, "ideas": found}
            self.app.conversations.write(t.pid, conv)
        listed = [f"{n}. {artist.describe(d)}" + (f" ({d['why']})" if d.get("why") else "") for n, d in enumerate(found, 1)]
        return {"ok": True, "ideas": listed, "note": "Nothing was changed. Tell the person these ideas, numbered, in their "
                "language and in words (not as JSON); apply the one they choose with redesign_slide and its number."}

    async def _redesign_args(self, t: Turn, args: dict) -> dict:
        """{slide_id, design}: the idea of that number from the last ask_artist for this slide, or the Artist's
        proposal for the wish."""
        from ..docengine import layouts
        from . import artist

        did, prs, sid = self._slide_in(t, args)
        if args.get("idea"):
            kept = (self.app.conversations.get(t.pid, t.cid, t.email).get("artist_ideas") or {})
            ideas = kept.get("ideas") or []
            if kept.get("deck_id") != did or kept.get("slide_id") != sid or not 1 <= int(args["idea"]) <= len(ideas):
                raise ToolError("NO_SUCH_IDEA", "Nothing was changed: there is no such idea for this slide.",
                                "Call ask_artist for this slide first, then give the number of the idea chosen.")  # fmt: skip
            chosen = ideas[int(args["idea"]) - 1]
        else:
            s = prs.slides.get(sid)
            slide = artist.slide_of(read.slide(prs, sid), layouts.heading(s.slide_layout, prs.slide_width, prs.slide_height))
            model = await asyncio.to_thread(self.app.models.resolve, None if t.model == "application" else t.model)
            goal = artist.goal_of(title=self.app.decks.get(t.pid, did, t.email).get("title") or "")
            chosen = await artist.design(self.app, model, slide, wish=str(args.get("wish") or ""), kind=goal)
        return {"slide_id": sid, "design": chosen, **({"deck_id": did} if args.get("deck_id") else {})}

    async def t_get_slide(self, t: Turn, args: dict) -> dict:
        did = self._deck_id(t, args)
        args = self._positions(args, self._bytes(t, did), t.start_order.get(did))
        try:
            s = read.slide(read.open_deck(self._bytes(t, did)), int(args["slide_id"]))
            if getattr(self.app, "describer", None):
                s = context_describe(s, self.app.describer.descriptions.all(t.pid))
        except KeyError:
            raise ToolError(
                "SLIDE_NOT_FOUND", f"There is no slide {args['slide_id']}.", "Read the outline for the slide IDs."
            ) from None
        return {"deck_id": did, **s}

    async def t_list_layouts(self, t: Turn, args: dict) -> dict:
        did = self._deck_id(t, args)
        return {"deck_id": did, "layouts": read.layouts(read.open_deck(self._bytes(t, did)))}

    async def t_render_slide(self, t: Turn, args: dict) -> dict:
        if not t.can_see:
            raise ToolError("NO_VISION", "This model cannot see images.", "Check the text with get_slide instead.")
        did = self._deck_id(t, args)
        data = self._bytes(t, did)
        args = self._positions(args, data, t.start_order.get(did))
        cache = self.app.layout.renders(t.pid)
        keys = {k["id"]: k["key"] for k in await render.ensure(data, cache, only={int(args["slide_id"])})}
        if int(args["slide_id"]) not in keys:
            raise ToolError("SLIDE_NOT_FOUND", f"There is no slide {args['slide_id']}.", "")
        png = (cache / keys[int(args["slide_id"])] / "preview.png").read_bytes()
        img = Image.open(io.BytesIO(png)).convert("RGB")
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        t.images.append(buf.getvalue())
        return {"ok": True, "note": "The slide's image follows; LibreOffice renders it, so it is close to PowerPoint, not exact."}

    # ── project ──────────────────────────────────────────────────────
    async def t_build_generation(self, t: Turn, args: dict) -> dict:
        """The slides of a generated outline the person approved (domain/generations.py)."""
        try:
            record = await self.app.generations.build(t.pid, args["generation_id"], t.email)
        except NotFound:
            raise ToolError("NOT_FOUND", "There is no such generated outline.", "") from None
        except ValueError as e:
            raise ToolError("NOT_READY", str(e), "Tell the person.") from None
        t.conversation["active_deck"] = record["deck_id"]
        title = record["outline"]["title"]
        n = len(record["slide_ids"])
        return {"ok": True, "deck_id": record["deck_id"], "note": f"The deck «{title}» was made: {n} slides, now the "
                "open deck. The person reviews it as any change (undo takes it back)."}  # fmt: skip

    async def t_create_deck(self, t: Turn, args: dict) -> dict:
        project = self.app.projects.get(t.pid, t.email, roles=("owner", "editor"))
        active = t.conversation.get("active_deck")
        if active:
            try:
                empty = not read.outline(read.open_deck(self._bytes(t, active)))
            except (NotFound, ToolError):
                empty = False
            if empty:  # measured: "create the cover of a presentation" on a new, empty deck made a second deck
                raise ToolError(
                    "ACTIVE_DECK_EMPTY",
                    "The open deck has no slides yet: it is the presentation to make.",
                    "Add the slides to it with add_slide (no new deck).",
                )
        ref = args.get("template") or project["settings"]["default_template"]
        try:
            deck = await self.app.decks.from_template(t.pid, t.email, args["title"], ref)
        except NotFound:
            raise ToolError("TEMPLATE_NOT_FOUND", "There is no such template.", "Call list_templates.") from None
        t.conversation["active_deck"] = deck["id"]
        return {"ok": True, "deck_id": deck["id"], "note": "The new deck is now the active deck. It has no slides yet."}

    async def t_duplicate_deck(self, t: Turn, args: dict) -> dict:
        did = self._deck_id(t, args)
        try:
            deck = await self.app.decks.duplicate(t.pid, did, t.email, args.get("title") or "")
        except NotFound:
            raise ToolError("DECK_NOT_FOUND", "There is no such deck.", "The decks are in your context.") from None
        t.conversation["active_deck"] = deck["id"]
        return {"ok": True, "deck_id": deck["id"], "title": deck["title"], "note": "The copy is now the active deck."}

    async def t_undo(self, t: Turn, args: dict, redo: bool = False) -> dict:
        did = self._deck_id(t, args)
        if t.proposal is not None and did in t.proposal["decks"]:
            raise ToolError("PROPOSAL_WAITING", "This deck has changes in review.", "Undo works on accepted changes only.")
        try:
            deck = await self.app.decks.undo(t.pid, did, t.email, int(args.get("steps", 1)), redo=redo)
        except ValueError as e:
            raise ToolError("NOTHING_TO_UNDO", str(e), "") from None
        t.changed.add(did)
        return {"ok": True, "deck_id": did, "current_version": deck["current_version"]}

    async def t_redo(self, t: Turn, args: dict) -> dict:
        return await self.t_undo(t, args, redo=True)


def image_message(images: list[bytes]) -> dict:
    """The rendered slides, as a user message the model sees after the tool results (OpenAI content parts)."""
    parts: list[dict] = [{"type": "text", "text": "The rendered slide(s) you asked for:"}]
    for jpg in images:
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(jpg).decode()}"}})
    return {"role": "user", "content": parts}
