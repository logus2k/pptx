"""The assistant's tools (spec section 5; technical design section 6.4): their definitions are the JSON Schemas in
contracts/tools/, and each has an executor here. Executors validate the arguments against the schema, check the
person's role, act on the turn's draft, and return a result or an error {code, message, hint} the model can act on.

Reading tools see the draft when this turn's proposal has one for the deck, so the model sees its own changes.
Editing tools apply to the draft (never to a saved version) and are recorded in the proposal. ask_user,
propose_plan and update_instructions pause the turn until the person answers."""

from __future__ import annotations

import asyncio
import base64
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
from PIL import Image

from ..config import REPO_DIR
from ..docengine import files, ops, read, render
from .. import search
from .context import describe as context_describe
from ..kb import KBError
from ..storage import NotFound

TOOLS_DIR = REPO_DIR / "contracts" / "tools"
EDITING = (
    "update_text",
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
    "fit_text",
)  # fmt: skip

# what the context already gives (the decks, the layouts) or another tool returns (kb_search: the passages' text):
# still run when called, not offered - each costs part of the fixed share of the window (technical design 6.2: 25%)
NOT_OFFERED = ("list_decks", "list_layouts", "kb_get")


def definitions(schemas: dict[str, dict]) -> list[dict]:
    """The tools as the model is given them (OpenAI's function format)."""
    out = []
    for name, s in schemas.items():
        if name in NOT_OFFERED:
            continue
        params = _for_model({k: v for k, v in s.items() if k in ("type", "properties", "required", "additionalProperties")})
        out.append({"type": "function", "function": {"name": name, "description": s["description"], "parameters": params}})
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
            if not 1 <= args[k] <= len(order):
                hint = "New slides are named by their ID." if start else "Use a slide number or ID from the deck map."
                raise ToolError("SLIDE_NOT_FOUND", f"The deck has slides 1 to {len(order)}.", hint)
            sid = order[args[k] - 1]
            if sid not in now:
                raise ToolError(
                    "SLIDE_DELETED",
                    f"Slide {args[k]} was deleted earlier in this request.",
                    "It is done: do not delete another slide in its place. Say what you changed.",
                )
            out[k] = sid
        return out

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
        try:
            jsonschema.validate(args, self.schemas[name])
        except jsonschema.ValidationError as e:
            where = "/".join(str(x) for x in e.absolute_path) or "(arguments)"
            hint = "Correct what the message names (the allowed values are in it, or in the tool's parameters) and call again."
            if name == "edit_paragraphs" and "'index' is a required property" in e.message:
                hint = "set and delete need the paragraph's [n] from the deck map; update_text replaces all of a shape's text."
            raise ToolError("BAD_ARGUMENTS", f"{where}: {e.message}", hint) from None
        return args

    async def call(self, t: Turn, name: str, raw_args: str | dict) -> dict:
        """The result the model reads (a dict, sent as JSON), errors included."""
        try:
            args = self.parse(name, raw_args)
            if name in EDITING:
                return await self._edit(t, name, args)
            return await getattr(self, f"t_{name}")(t, args)
        except ToolError as e:
            return e.as_dict()
        except ops.OpError as e:
            return {"error": e.as_dict()}

    async def _edit(self, t: Turn, name: str, args: dict) -> dict:
        self.app.projects.get(t.pid, t.email, roles=("owner", "editor"))
        did = self._deck_id(t, args)
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
        out = {"ok": True, "deck_id": did, **result, "note": "Applied to the draft; the person reviews it before it is saved."}
        if result.get("unmatched"):
            out["note"] += " Text that had no place in the new layout was kept as a text box: mention it."
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
    async def t_create_deck(self, t: Turn, args: dict) -> dict:
        project = self.app.projects.get(t.pid, t.email, roles=("owner", "editor"))
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
