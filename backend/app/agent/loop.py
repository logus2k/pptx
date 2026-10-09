"""The agent loop (technical design sections 5 and 6): a turn streams the model's answer and runs its tools until the
model answers without tools, asks the person (ask_user), presents a plan (propose_plan), proposes instructions
(update_instructions), the person cancels, or a limit is reached (16 model calls, 40 tool calls, 180 s). Changes go
to a proposal the person accepts or rejects slide by slide (decide)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from .. import audit, search, storage
from ..domain.proposals import FINAL, Stale
from ..domain.leases import Leased
from ..storage import NotFound
from . import context, llm, router
from ..docengine import read
from .tools import (EDITING, WAITING, Executor, ToolError, Turn, definitions, image_message, slide_name, sources_of,
                    without_figures)  # fmt: skip

log = logging.getLogger("slides.agent")
MAX_MODEL_CALLS, MAX_TOOL_CALLS, MAX_SECONDS = 16, 40, 180
# spec NL-8 (and PJ-6: cross-deck changes): made only after a plan the person approved
DELETING = ("delete_slide", "delete_shape", "copy_slides", "change_template")


def speakable(text: str, limit: int = 300) -> str:
    """The reply's first sentence: what is read aloud (spec VO-3), the full text staying on screen."""
    text = " ".join((text or "").split())
    for i, ch in enumerate(text):
        if ch in ".!?" and (i + 1 == len(text) or text[i + 1] == " ") and i >= 12:
            return text[: i + 1][:limit]
    return text[:limit]


OVERFLOW_NUDGE = (
    "(A note from the application, not from the person.) The text you changed still does not fit its box: {where}. "
    "Fix it before you finish: fit_text shrinks it to fit; else shorten it, make the box larger (move_resize_shape), or "
    "split it over two slides."
)
FAILED_NUDGE = (
    "(A note from the application, not from the person.) Nothing has changed yet: your edits failed. If the error tells "
    "you what to do, call the tool again now, as your answer says; if it cannot be done, tell the person why."
)
# the tools left out first when the offered ones do not fit the window's fixed share: the rarely needed, then the
# ones a request can do without (another tool or the person can do it), the core never
EXPENDABLE = (
    "kb_read_document", "search_project", "list_templates", "duplicate_deck", "change_template", "copy_slides",
    "search_conversations", "render_slide", "kb_list_images", "generate_image", "set_alt_text", "connect_shapes",
    "duplicate_shape", "move_resize_shape", "format_text", "fit_text", "edit_chart", "change_layout", "add_shape",
    "draw_diagram", "add_slides", "duplicate_slide", "move_slide",
)  # fmt: skip
# tools that only read: a turn that called only these has changed nothing
READS = {"ask_artist",
         "get_slide", "get_deck_outline", "render_slide", "list_decks", "list_layouts", "list_templates", "kb_search",
         "kb_get", "kb_read_document", "kb_list_images", "search_project", "search_conversations", "draft_outline"}  # fmt: skip
UNDONE_NUDGE = (
    "(A note from the application, not from the person.) The person asked for a change and nothing has changed yet: "
    "{intent}. Make it now with the tools, from what you have read or found (every change is reviewed before it is "
    "saved): do not describe it, propose it or ask for approval in words. If it cannot be done, say why."
)
STILL_NUDGE = (
    "(A note from the application, not from the person.) Still nothing has changed: your answer says what you would do "
    "or did, but no tool was called. Call the tool now with the arguments; if it cannot be done, say why in one sentence."
)
CHECK_NUDGE = (
    "(A note from the application, not from the person.) Your answer says this is still to be done: {missing}. This turn "
    "already made: {done}. If one of those already does it, change nothing and say so in one sentence. Otherwise do it "
    "now with the tools, keeping what you already wrote (add to a text, never replace it); if it is the person's to do, "
    "say so."
)
NUDGE = (
    "(A note from the application, not from the person.) Your answer called no tool, so nothing has happened yet. "
    "If the person asked for a change, it is made only by calling the tool: call it now (for a deletion or a change "
    "to several slides, propose_plan). If you need something from the person, call ask_user. If they only asked a "
    "question about the deck, give your answer again."
)


def _ask(question: str) -> dict:
    """An ask_user call made by the application with the model's question (a request the router found unclear)."""
    return {
        "id": f"app-{uuid.uuid4().hex}",
        "type": "function",
        "function": {"name": "ask_user", "arguments": json.dumps({"question": question.strip()}, ensure_ascii=False)},
    }


def _done(name: str, raw: str | dict, result: dict) -> str:
    """One edit made this turn, in words ("duplicate_slide on slide 3, new slide 4"): the "## Now" section lists them
    (measured: told only "do it now" after the edit had succeeded, the model went on calling tools, 10 times in 10, and
    made the same edit twice; told it was done, it answered, 10 in 10)."""
    try:
        args = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    except ValueError:
        args = {}
    # the slide edited, as the request numbers it; a new slide by its ID only (measured: an invented "after slide 18"
    # in an empty deck, dropped by the executor, came back as "add_slide on slide 18" and into the reply)
    if name == "build_generation":  # the generated deck, as its result says it
        return str(result.get("note") or "the generated deck was made").split(" The person reviews")[0]
    if result.get("written_on"):  # add_slide written on the empty slide the request is about (measured: listed as
        # "add_slide", the closing message said "a new slide, slide 2" of a one-slide deck, 8 runs in 8)
        return f"the content written on slide {result['written_on']} (no slide added)"
    where = f" on slide {args['slide_id']}" if isinstance(args, dict) and "slide_id" in args else ""
    new = result.get("new_slide_ids")
    return f"{name}{where}" + (f", new slide ID {', '.join(map(str, new))}" if new else "")


class Agent:
    def __init__(self, app, emit, nudge: bool = True) -> None:
        self.app = app
        self.nudge = nudge
        self.emit = emit  # async emit(event, payload, cid)
        self.executor = Executor(app)
        self.tool_defs = definitions(self.executor.schemas)
        self._running: dict[str, asyncio.Task] = {}
        self._cancel: set[str] = set()
        self._vision: dict[str, bool] = {}

    # ── entry points (socket.io events) ──────────────────────────────
    def busy(self, cid: str) -> bool:
        task = self._running.get(cid)
        return task is not None and not task.done()

    async def user_message(
        self,
        pid: str,
        cid: str,
        email: str,
        text: str,
        deck_id: str | None = None,
        selection: dict | None = None,
        attachments: list[str] | None = None,
    ) -> None:
        if self.busy(cid):
            raise ValueError("the assistant is still answering")
        conv = self.app.conversations.get(pid, cid, email)
        self.app.projects.get(pid, email, roles=("owner", "editor"))
        if conv["pending"]:  # a typed message answers what the turn was waiting for
            await self.resolve(pid, cid, email, {"answer": text})
            return
        async with storage.lock(pid):
            conv = self.app.conversations.get(pid, cid, email)
            if deck_id:
                self.app.decks.get(pid, deck_id, email)
                conv["active_deck"] = deck_id
            message = {"role": "user", "author": email, "content": text, "deck_id": conv["active_deck"]}
            if selection:
                message["selection"] = selection
            if attachments:
                message["attachments"] = list(attachments)
            stored = self.app.conversations.append(pid, conv, message)
            conv["route"] = None  # a new request is routed afresh (a carried route belongs to an answered wait)
            if not conv["title"] and text.strip():  # the first message names the conversation
                conv["title"] = " ".join(text.split())[:60]
            self.app.conversations.write(pid, conv)
        await self.emit("message", stored, cid)
        self._start(pid, cid, email)

    async def resolve(self, pid: str, cid: str, email: str, decision: dict) -> None:
        """The person answers what the turn waits for: {answer} to a question, {approve, comment} to a plan,
        {accept} to proposed instructions. The answer becomes the waiting tool call's result and the turn goes on."""
        # an owner or editor: an answer lets the turn change the deck (security review L7: a viewer approved a plan)
        self.app.projects.get(pid, email)  # a member (NotFound otherwise)
        try:
            self.app.projects.get(pid, email, roles=("owner", "editor"))
        except NotFound:
            raise PermissionError("Only the project's owners and editors can answer the assistant.") from None
        async with storage.lock(pid):
            conv = self.app.conversations.get(pid, cid, email)
            pending = conv["pending"]
            if not pending:
                raise ValueError("nothing is waiting for an answer")
            kind = pending["kind"]
            then = pending["payload"].get("then") if kind == "plan" else None
            if then:  # a plan the application made for a deletion: the deletion runs (or not) as its result
                conv["pending"] = None
                self.app.conversations.write(pid, conv)
        if then:
            if bool(decision.get("approve", "answer" in decision)):  # as for any plan: a typed answer goes ahead
                t = Turn(pid=pid, cid=cid, email=email, conversation=conv)
                t.proposal = self.app.proposals.open_in(pid, cid)
                t.start_order = {k: list(v) for k, v in ((conv.get("route") or {}).get("order") or {}).items()}
                await self.emit("tool_progress", {"tool": then["name"]}, cid)
                result = await self.executor.call(t, then["name"], then["arguments"])
                if "error" not in result and (conv.get("route") or {}).get("done") is not None:
                    # in the words of the plan the person approved ("Apagar o diapositivo 3 «Antes e depois»"), not the
                    # slide's ID (measured: "delete_slide on slide 258" for "Apaga o diapositivo antes e depois", and the
                    # model went on to delete the slides before and after slide 3, 2 runs in 6)
                    steps = pending["payload"].get("steps") or []
                    conv["route"]["done"].append(
                        f"{steps[0]} (done)" if len(steps) == 1 else _done(then["name"], then["arguments"], result)
                    )
            else:
                hint = "Ask what they want instead, or leave it."
                result = {"error": {"code": "NOT_APPROVED", "message": "The person did not approve this.", "hint": hint}}
            route = conv.get("route")
            async with storage.lock(pid):
                conv = self.app.conversations.get(pid, cid, email)
                conv["route"] = route
                if then["name"] == "build_generation" and result.get("deck_id"):  # the generated deck is the open one
                    conv["active_deck"] = result["deck_id"]
                stored = self.app.conversations.append(
                    pid,
                    conv,
                    {
                        "role": "tool",
                        "tool_call_id": pending["tool_call_id"],
                        "name": then["name"],
                        "content": json.dumps(result, ensure_ascii=False),
                    },
                )
                self.app.conversations.write(pid, conv)
            await self.emit("message", stored, cid)
            self._start(pid, cid, email)
            return
        async with storage.lock(pid):
            conv = self.app.conversations.get(pid, cid, email)
            if kind == "question":
                result = {"answer": str(decision.get("answer", ""))}
            elif kind == "plan":
                approved = bool(decision.get("approve", "answer" in decision))
                result = {"approved": approved, "comment": str(decision.get("comment") or decision.get("answer") or "")}
            else:
                accepted = bool(decision.get("accept", False))
                if accepted:
                    project = self.app.projects.get(pid, email, roles=("owner", "editor"))
                    await self.app.projects.update_locked(project, {"instructions": pending["payload"]["text"]})
                result = {"accepted": accepted}
            stored = self.app.conversations.append(
                pid,
                conv,
                {
                    "role": "tool",
                    "tool_call_id": pending["tool_call_id"],
                    "name": {"question": "ask_user", "plan": "propose_plan"}.get(kind, "update_instructions"),
                    "content": json.dumps(result, ensure_ascii=False),
                },
            )
            conv["pending"] = None
            self.app.conversations.write(pid, conv)
        await self.emit("message", stored, cid)
        if kind == "instructions":
            await self.emit("instructions_changed", {"accepted": result["accepted"]}, cid)
        self._start(pid, cid, email)

    def cancel(self, cid: str) -> None:
        if self.busy(cid):
            self._cancel.add(cid)

    def _start(self, pid: str, cid: str, email: str) -> None:
        task = asyncio.create_task(self._turn(pid, cid, email))
        self._running[cid] = task

        def done(t: asyncio.Task) -> None:
            if not t.cancelled() and t.exception() is not None:
                log.error("a turn failed", exc_info=t.exception())

        task.add_done_callback(done)

    # ── a turn ───────────────────────────────────────────────────────
    async def _vision_of(self, model: dict) -> bool:
        if model["id"] not in self._vision:
            self._vision[model["id"]] = await asyncio.to_thread(self.app.models.vision, model)
        return self._vision[model["id"]]

    async def _turn(self, pid: str, cid: str, email: str) -> None:
        self._cancel.discard(cid)
        conv = self.app.conversations.get(pid, cid, email)
        t = Turn(pid=pid, cid=cid, email=email, conversation=conv)
        open_p = self.app.proposals.open_in(pid, cid)
        if open_p and open_p["status"] == "drafting":
            t.proposal = open_p  # a turn resumed after a plan or a question goes on with it
        status = "done"
        try:
            project = self.app.projects.get(pid, email)
            model = await asyncio.to_thread(self.app.models.resolve, project["settings"]["model"])
            t.model = model["id"]  # for the project's audit trail (tools.Executor.call)
            t.can_see = await self._vision_of(model)
            carried = conv.get("route")
            if carried:  # the turn goes on after an answer: the same request, with the edits it already made
                t.intent, t.kind, t.done = carried["intent"], carried["kind"], list(carried["done"])
                if t.kind == "unclear":  # the person answered the question: the request is clear now, its tools offered
                    # (measured: kept "unclear", the turn offered ask_user alone after the answer, and the model asked
                    # the same question again until the turn's limit: "Cria um slide", answered "Decide tu.", 13 times)
                    t.kind = "change"
                t.changes = t.kind == "change"
                t.groups = set(carried["groups"]) if carried["groups"] is not None else None
                t.focus = carried.get("focus")
                t.located = list(carried.get("located") or [])
                t.overflowing = {tuple(x) for x in carried.get("overflowing") or []}
                routed = router.tools_of(t.groups)
                async with storage.lock(pid):
                    conv = self.app.conversations.get(pid, cid, email)
                    conv["route"] = None
                    self.app.conversations.write(pid, conv)
                    t.conversation = conv
            else:
                routed = await self._route(t, model)
            # the deck's order when the request was made: what its slide numbers mean for the whole turn
            t.start_order = {k: list(v) for k, v in ((carried or {}).get("order") or {}).items()}
            did = conv.get("active_deck")
            if did and did not in t.start_order:
                try:
                    data = await asyncio.to_thread(self.executor._bytes, t, did)
                    t.start_order[did] = [o["slide_id"] for o in read.outline(read.open_deck(data))]
                except NotFound:
                    pass
            t.tool_defs = [
                d for d in await asyncio.to_thread(self._offered, t) if routed is None or d["function"]["name"] in routed
            ]
            if routed is not None and "add_chart" not in routed:  # no chart or diagram asked for: add_slide without them
                t.tool_defs = [without_figures(d) if d["function"]["name"] == "add_slide" else d for d in t.tool_defs]
            if t.kind == "unclear":  # too vague to act on: asking is the only right step (measured: offered the core,
                # the model asked in its reply text, which is no question the person can answer in the panel)
                t.tool_defs = [d for d in t.tool_defs if d["function"]["name"] == "ask_user"] or t.tool_defs
            if t.kind == "ideas" or t.idea:
                await self._artist_step(pid, t)
            try:
                room, answer_tokens = await asyncio.to_thread(context.budget, self.app.models, model, t.tool_defs)
            except context.ModelTooSmall:
                if routed is None:
                    # no route, and every tool together does not fit the window's fixed share (measured: 39 tools,
                    # 29.4% of 32 768): the groups most requests need, rather than a refused turn
                    usual = router.FALLBACK | ({"knowledge"} if self._has_sources(t) else set())
                    fallback = router.tools_of(usual)
                    t.tool_defs = [d for d in t.tool_defs if d["function"]["name"] in fallback]
                    log.warning("every tool does not fit: the usual groups offered", extra={"toolCount": len(t.tool_defs)})
                room, answer_tokens = await self._fitted_budget(t, model)
            t.result_chars = int(room * 0.15 * 3)  # a tool result: a sixth of the room, at ~3 characters a token
            started, model_calls, tool_calls, failed_nudged, overflow_nudged = time.monotonic(), 0, 0, False, False
            undone_nudged, called, still_nudged, checked = False, set(), False, False  # the tools called this turn
            await self.emit("turn_started", {"model": model["label"]}, cid)
            while True:
                if cid in self._cancel:
                    status = "cancelled"
                    break
                if model_calls >= MAX_MODEL_CALLS or tool_calls >= MAX_TOOL_CALLS or time.monotonic() - started > MAX_SECONDS:
                    status = "limit"
                    await self._say(
                        pid, t, "I stopped here: this request took more steps than one turn allows. Tell me how to continue."
                    )
                    break
                messages = await self._messages(t, model, room)
                first = model_calls == 0  # the turn's first answer is held back until it is known to act
                text, calls = await self._complete(model, messages, answer_tokens, cid, show=not first, tools=t.tool_defs)
                model_calls += 1
                if not calls and first and t.kind == "unclear" and text.strip():
                    # the router found the request too vague, and the answer is the question in words: it becomes the
                    # question the person answers in the panel (measured: the wording of the instruction alone moved
                    # ask_user between 0 and 10 calls in 10; the question written was a good one every time)
                    calls = [_ask(text)]
                    text = ""
                if not calls and first and self.nudge and not t.done:
                    # (not when this turn has already changed the deck: measured, after the deletion the person approved,
                    # "your answer called no tool, so nothing has happened" made the model delete more slides)
                    # measured (tests/eval): a small model often says it changed the deck, or asks for leave, without
                    # calling a tool; asked once more with the reason, it acts, asks properly, or answers again
                    retry = [*messages, {"role": "assistant", "content": text}, {"role": "user", "content": NUDGE}]
                    text, calls = await self._complete(model, retry, answer_tokens, cid, tools=t.tool_defs)
                    model_calls += 1
                    log.info("the first answer called no tool: asked again", extra={"actedOnRetry": bool(calls)})
                if not calls and t.failed_edits and not t.done and not failed_nudged and self.nudge:
                    # measured: after an error, the model wrote "I will try again with layout 1_Texto" and the turn
                    # ended there; asked once more, it makes the call it announced, or says why it cannot
                    failed_nudged = True
                    retry = [*messages, {"role": "assistant", "content": text}, {"role": "user", "content": FAILED_NUDGE}]
                    text, calls = await self._complete(model, retry, answer_tokens, cid, tools=t.tool_defs)
                    model_calls += 1
                    log.info("every edit had failed: asked again", extra={"actedOnRetry": bool(calls)})
                if (not calls and called and called <= READS and t.kind == "change" and not t.failed_edits
                        and not undone_nudged and self.nudge and not self._declined(t)):  # fmt: skip
                    # measured (tests/scenarios, first use): after kb_search found the topics, the answer described
                    # the slide, or "proposed a plan" in words, or said it was done, and the turn ended unchanged (3 in 3)
                    undone_nudged = True
                    note = UNDONE_NUDGE.format(intent=t.intent or "what the person asked")
                    retry = [*messages, {"role": "assistant", "content": text}, {"role": "user", "content": note}]
                    text, calls = await self._complete(model, retry, answer_tokens, cid, tools=t.tool_defs)
                    model_calls += 1
                    log.info("a change was asked and none made: asked again", extra={"actedOnRetry": bool(calls)})
                if not calls and t.overflowing and not overflow_nudged and self.nudge:
                    # measured (renders of real decks): an 11th item added to a full list ran 49 pt past its box, and
                    # the turn ended with the self-check's note unread; asked once, it fixes what still does not fit
                    still = await asyncio.to_thread(self._still_overflowing, t)
                    if still:
                        overflow_nudged = True
                        where = "; ".join(f"{n}, shape {i}" for n, i in still)
                        retry = [*messages, {"role": "assistant", "content": text},
                                 {"role": "user", "content": OVERFLOW_NUDGE.format(where=where)}]  # fmt: skip
                        text, calls = await self._complete(model, retry, answer_tokens, cid, tools=t.tool_defs)
                        model_calls += 1
                        log.info("text left too long: asked again", extra={"actedOnRetry": bool(calls)})
                nudged = failed_nudged or undone_nudged or (model_calls >= 2 and not called)
                if (not calls and nudged and t.kind == "change" and not t.done and not (called - READS - set(EDITING))
                        and not still_nudged and self.nudge and not self._declined(t)):  # fmt: skip
                    # asked once already and answered in words again (measured: "vou aplicar as alterações agora", or
                    # "the slide was added" after an approved plan, and the turn ended with nothing made, 3 runs in 9)
                    still_nudged = True
                    retry = [*messages, {"role": "assistant", "content": text}, {"role": "user", "content": STILL_NUDGE}]
                    text, calls = await self._complete(model, retry, answer_tokens, cid, tools=t.tool_defs)
                    model_calls += 1
                    log.info("still nothing made: asked a last time", extra={"actedOnRetry": bool(calls)})
                if (not calls and t.kind == "change" and t.done and not checked and self.nudge and not self._declined(t)
                        and not called & {"propose_plan", "ask_user"}):  # fmt: skip
                    # changes made, the turn ending in words that say something is still to do (measured, squad-16: the
                    # box copied, "Preciso agora liga-lo ... com uma seta" and the turn ended, 2 runs in 6; the nudges
                    # above fire only when nothing was changed)
                    checked = True
                    missing = await self._missing(t, model, text)
                    if missing:
                        # with the changes made (measured: "update slide 1 with the topics", already done, made the model
                        # insert more points, and the box overflowed; the same change made again, an index on two slides)
                        note = CHECK_NUDGE.format(missing=missing, done="; ".join(t.done))
                        retry = [*messages, {"role": "assistant", "content": text}, {"role": "user", "content": note}]
                        text, calls = await self._complete(model, retry, answer_tokens, cid, tools=t.tool_defs)
                        model_calls += 1
                    said = {"missing": bool(missing), "actedOnRetry": bool(calls)}
                    log.info("changes checked against the request", extra=said)
                if not calls:
                    await self._say(pid, t, text)
                    break
                async with storage.lock(pid):
                    conv = self.app.conversations.get(pid, cid, email)
                    conv["active_deck"] = t.conversation.get("active_deck")
                    stored = self.app.conversations.append(pid, conv, {"role": "assistant", "content": text, "tool_calls": calls})
                    self.app.conversations.write(pid, conv)
                    t.conversation = conv
                if text.strip():
                    await self.emit("message", stored, cid)
                waiting = False
                for call in calls:
                    name, raw = call["function"]["name"], call["function"].get("arguments") or "{}"
                    called.add(name)
                    if name in WAITING:
                        if waiting:
                            result = {"error": {"code": "ONE_AT_A_TIME", "message": "Ask one thing at a time.", "hint": ""}}
                        else:
                            try:
                                args = self.executor.parse(name, raw)
                                await self._wait(pid, t, call["id"], name, args)
                                waiting = True
                                continue
                            except ToolError as e:
                                result = e.as_dict()
                    elif name == "decide_changes":  # spec VO-6: the review's buttons, in words
                        try:
                            result = await self._decide_in_words(t, self.executor.parse(name, raw))
                        except ToolError as e:
                            result = e.as_dict()
                    elif name == "generate_deck":
                        # a deck from a source (spec NL-12): the application reads it and plans the slides; the outline
                        # is the plan the person approves (or edits in the outline's editor) before the slides are made
                        try:
                            result = await self._generate(pid, t, self.executor.parse(name, raw))
                        except ToolError as e:
                            result = e.as_dict()
                        if "plan" in result:
                            await self._wait(pid, t, call["id"], "propose_plan", result["plan"])
                            waiting = True
                            continue
                    elif name in DELETING and not self._plan_approved(t):
                        # spec NL-8: a deletion waits for the person's approval; the model need not remember to
                        # plan it first (measured: gemma-4 "proposed" deletions in its reply and never made them)
                        try:
                            args = self.executor.parse(name, raw)
                            # a slide this request already deleted is not proposed again (its number is not reused)
                            target = dict(args)
                            did = self.executor._deck_id(t, target)
                            self.executor._positions(target, self.executor._bytes(t, did), t.start_order.get(did))
                        except ToolError as e:
                            result = e.as_dict()
                        else:
                            plan = {"steps": [self._step(t, name, args)], "then": {"name": name, "arguments": args}}
                            await self._wait(pid, t, call["id"], "propose_plan", plan)
                            waiting = True
                            continue
                    else:
                        await self.emit("tool_progress", {"tool": name}, cid)
                        result = await self.executor.call(t, name, raw)
                        tool_calls += 1
                        if name in EDITING and "error" in result:
                            t.failed_edits += 1
                        elif name in EDITING:
                            t.done.append(_done(name, raw, result))
                    await self._tool_result(pid, t, call["id"], name, result)
                if waiting:
                    status = "waiting"
                    break
        except context.ModelTooSmall as e:
            status = "failed"
            await self.emit("assistant_error", {"message": f"The model cannot be used: {e}"}, cid)
        except Exception as e:
            status = "failed"
            log.error("a turn failed", exc_info=e)
            # spec AD-5: the usage screen counts model-service errors from the audit log (the error's type only)
            failure = {"pid": pid, "cid": cid, "error": type(e).__name__}
            await asyncio.to_thread(audit.record, self.app.layout.audit, email, "turn failed", failure)
            if t.proposal is not None:
                t.proposal["status"] = "failed"
                self.app.proposals.write(pid, t.proposal)
                self.app.proposals.drop_drafts(pid, t.proposal)
                t.proposal = None
            await self.emit(
                "assistant_error", {"message": "The assistant could not finish: the model or a service failed. Try again."}, cid
            )
        finally:
            self._cancel.discard(cid)
        if t.proposal is not None and status in ("done", "limit", "cancelled"):
            if any(d["operations"] for d in t.proposal["decks"].values()):
                t.proposal["status"] = "pending"
                self.app.proposals.write(pid, t.proposal)
                await self.emit("proposal_updated", self.describe(pid, t.proposal), cid)
        for did in t.changed:
            if t.proposal is None or did not in t.proposal["decks"]:
                await self.emit("deck_changed", {"deck_id": did}, cid)
        await self.emit("turn_ended", {"status": status}, cid)

    async def _messages(self, t: Turn, model: dict, room: int) -> list[dict]:
        """The context message, then the conversation since its summary (folding older turns into the summary when
        they exceed their share), then the slides rendered for the model."""
        did = t.conversation.get("active_deck")
        active_bytes = None
        if did:
            try:
                active_bytes = self.executor._bytes(t, did)
            except NotFound:
                active_bytes = None
        last_user = next((m for m in reversed(self.app.conversations.messages(t.pid, t.cid)) if m["role"] == "user"), None)
        selection = (last_user or {}).get("selection")
        stored = self.app.conversations.messages(t.pid, t.cid, after=t.conversation["summary_upto"])
        history = context.history_messages(stored)
        # the deck map takes what the conversation does not use yet, between its share and half the room (measured:
        # at 20%, a 200-slide deck's one-line index left no slide in full, and the model guessed shape IDs)
        spoken = await asyncio.to_thread(self.app.models.count, json.dumps(history, ensure_ascii=False), model)
        map_tokens = max(int(room * context.SHARES["outline"]), min(int(room * 0.5), room - spoken - int(room * 0.3)))
        query = (last_user or {}).get("content") or ""  # what the memory is ranked against when it does not all fit
        ctx, used = await asyncio.to_thread(
            context.system_context, self.app, t, model, room, active_bytes, selection, map_tokens, query
        )
        allowed = room - used
        size = await asyncio.to_thread(self.app.models.count, json.dumps(history, ensure_ascii=False), model)
        if size > allowed:
            await self._fold(t, model, stored, allowed)
            ctx, used = await asyncio.to_thread(context.system_context, self.app, t, model, room, active_bytes, selection)
            history = context.history_messages(
                self.app.conversations.messages(t.pid, t.cid, after=t.conversation["summary_upto"])
            )
        out = [{"role": "system", "content": ctx}, *history]
        if t.images:
            out.append(image_message(t.images))
            t.images = []
        return out

    async def _fold(self, t: Turn, model: dict, stored: list[dict], allowed: int) -> None:
        """Fold the oldest turns into the conversation's summary until the rest fits (always keeping the turn in
        progress), with the summariser (a separate model call; technical design section 6.2)."""
        groups = context.turns(stored)
        fold: list[dict] = []
        while len(groups) > 1:
            rest = [m for g in groups for m in g]
            size = await asyncio.to_thread(
                self.app.models.count, json.dumps(context.history_messages(rest), ensure_ascii=False), model
            )
            if size <= allowed * 0.6:  # leave room to grow before the next fold
                break
            fold += groups.pop(0)
        if not fold:
            return
        lines = []
        for m in fold:
            if m["role"] == "user":
                lines.append(f"Person: {m.get('content') or ''}")
            elif m["role"] == "assistant" and (m.get("content") or "").strip():
                lines.append(f"Assistant: {m['content']}")
            elif m["role"] == "tool":
                # whole: the references the summary keeps (slide IDs, titles, versions) are in the tool results
                lines.append(f"(tool {m.get('name') or ''}: {m.get('content') or ''})")
        text = await self._summarise(model, t.conversation["summary"] or "", lines)
        async with storage.lock(t.pid):
            conv = self.app.conversations.get(t.pid, t.cid, t.email)
            conv["summary"] = text.strip()
            conv["summary_upto"] = fold[-1]["seq"]
            self.app.conversations.write(t.pid, conv)
            t.conversation = conv
        log.info("conversation summarised", extra={"foldedMessages": len(fold)})

    async def _summarise(self, model: dict, summary: str, lines: list[str]) -> str:
        """The summary updated with `lines`, everything sent: when they do not fit the summariser's window in one
        call, they go in successive parts, each part's summary carried into the next. Only a single line larger than
        a whole part (one huge tool result) is shortened, and the summariser is told so."""
        budget = int(self.app.models.window(model) * 0.6)  # the rest: the preset's prompt and the summary it writes

        def count(text: str) -> int:
            return self.app.models.count(text, model)

        def prompt(part: list[str]) -> str:
            return f"Summary so far:\n{summary or '(none)'}\n\nNext part of the conversation:\n" + "\n".join(part)

        async def call(part: list[str]) -> str:
            out = ""
            messages = [{"role": "user", "content": prompt(part)}]
            async for chunk in self.app.models.stream(model, "slides_summariser", messages, None):
                out += ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
            return out.strip()

        async def room() -> int:  # what a part may hold beside the summary so far (which grows)
            return max(budget - await asyncio.to_thread(count, prompt([])), budget // 4)

        sizes = await asyncio.to_thread(lambda: [count(x) + 1 for x in lines])
        part: list[str] = []
        used, free = 0, await room()
        for line, size in zip(lines, sizes, strict=True):
            if part and used + size > free:
                summary = await call(part)
                part, used, free = [], 0, await room()
            if size > free:  # one line alone is too large: its start goes, and the summariser is told the rest did not
                log.info("a tool result was shortened for the summary", extra={"tokens": size, "room": free})
                note = f" … (about {size - free} more tokens of this did not fit and were left out)"
                line = line[: int(len(line) * free * 0.9 / size)] + note
                size = free
            part.append(line)
            used += size
        if part:
            summary = await call(part)
        return summary

    async def _complete(
        self, model: dict, messages: list[dict], max_tokens: int, cid: str, show: bool = True, tools: list | None = None
    ) -> tuple[str, list[dict]]:
        """One streamed completion: its text (streamed to the page unless `show` is false) and its tool calls."""
        text = ""
        calls: dict[int, dict] = {}
        # an empty list is no tools (the Artist's ideas, said: loop._artist_step), not every tool
        offered = self.tool_defs if tools is None else tools
        async for chunk in self.app.models.stream(model, "slides_assistant", messages, offered, max_tokens):
            delta = ((chunk.get("choices") or [{}])[0].get("delta")) or {}
            if delta.get("content"):
                text += delta["content"]
                if show:
                    await self.emit("assistant_delta", {"text": delta["content"]}, cid)
            for tc in delta.get("tool_calls") or []:
                i = tc.get("index", len(calls))
                c = calls.setdefault(
                    i, {"id": tc.get("id") or f"call_{i}", "type": "function", "function": {"name": "", "arguments": ""}}
                )
                if tc.get("id"):
                    c["id"] = tc["id"]
                f = tc.get("function") or {}
                c["function"]["name"] += f.get("name") or ""
                c["function"]["arguments"] += f.get("arguments") or ""
        return text, [calls[i] for i in sorted(calls)]

    async def _say(self, pid: str, t: Turn, text: str) -> None:
        async with storage.lock(pid):
            conv = self.app.conversations.get(pid, t.cid, t.email)
            conv["active_deck"] = t.conversation.get("active_deck")
            message = {"role": "assistant", "content": text, "speakable": speakable(text)}
            if t.failed_edits and not t.changed:
                message["notice"] = "nothing_changed"  # the application's record, not the model's words
            since = []  # what the turn read since the person's last message, across any pauses (question, plan)
            for m in self.app.conversations.messages(pid, t.cid):
                since = [] if m["role"] == "user" else [*since, m]
            sources = sources_of(since)
            if sources:
                message["sources"] = sources  # spec KB-3: shown under the reply, with their links
            if t.proposal is not None and any(d["operations"] for d in t.proposal["decks"].values()):
                message["proposal_id"] = t.proposal["id"]
            stored = self.app.conversations.append(pid, conv, message)
            self.app.conversations.write(pid, conv)
            t.conversation = conv
        await self.emit("assistant_message", stored, t.cid)

    async def _artist_step(self, pid: str, t: Turn) -> None:
        """The Artist's ideas asked for, or the one chosen applied, by the application itself, as the router read the
        request (kind "ideas"; "idea": n), the call and its result in the conversation as if the model had made it; the
        model then says them (measured: offered ask_artist, the model wrote ideas of its own - "Ícones e Ilustrações" -
        and called nothing, 3 runs in 3; told "use the first idea", it rewrote the slide with fill_slide, 2 in 2)."""
        if t.idea:
            kept = t.conversation.get("artist_ideas") or {}
            name, args = "redesign_slide", {"slide_id": kept.get("slide_id"), "idea": t.idea}
            if not kept.get("slide_id"):
                return
        else:
            last = next((m for m in reversed(self.app.conversations.messages(pid, t.cid)) if m["role"] == "user"), {})
            sid = t.focus or (last.get("selection") or {}).get("slide_id")  # the slide named, else the one selected
            if sid is None:
                # no slide named or selected: unclear, asked in the panel (measured: "Melhora isto." read as ideas, the
                # model asked in its reply's words, which is no question the person can answer there - squad-11)
                t.kind = "unclear"
                t.tool_defs = [d for d in t.tool_defs if d["function"]["name"] == "ask_user"] or [
                    d for d in await asyncio.to_thread(self._offered, t) if d["function"]["name"] == "ask_user"]
                return
            name, args = "ask_artist", {"slide_id": sid, "wish": (last.get("content") or "")[:300]}
        call_id = f"artist-{uuid.uuid4().hex[:12]}"
        call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
        async with storage.lock(pid):
            conv = self.app.conversations.get(pid, t.cid, t.email)
            self.app.conversations.append(pid, conv, {"role": "assistant", "content": "", "tool_calls": [call]})
            self.app.conversations.write(pid, conv)
            t.conversation = conv
        await self.emit("tool_progress", {"tool": name}, t.cid)
        result = await self.executor.call(t, name, args)
        await self._tool_result(pid, t, call_id, name, result)
        if name == "ask_artist" and result.get("ok"):
            t.kind, t.changes = "question", False  # the ideas said, nothing changed: no editing tool offered
            t.tool_defs = []
        elif name == "redesign_slide" and result.get("ok"):
            t.done.append(_done(name, args, result))
        log.info("the Artist's step", extra={"tool": name, "ok": bool(result.get("ok"))})

    async def _tool_result(self, pid: str, t: Turn, call_id: str, name: str, result: dict) -> None:
        async with storage.lock(pid):
            conv = self.app.conversations.get(pid, t.cid, t.email)
            conv["active_deck"] = t.conversation.get("active_deck")
            self.app.conversations.append(
                pid,
                conv,
                {"role": "tool", "tool_call_id": call_id, "name": name, "content": json.dumps(result, ensure_ascii=False)},
            )
            self.app.conversations.write(pid, conv)
            t.conversation = conv

    async def _route(self, t: Turn, model: dict) -> set[str] | None:
        """The tools the person's last message needs (router.py: a short call to the model, intent first, with the
        deck's sketch); None - every tool - when there is no message or the answer cannot be read."""
        last = next((m for m in reversed(self.app.conversations.messages(t.pid, t.cid)) if m["role"] == "user"), None)
        if not last or not (last.get("content") or "").strip():
            return None
        slides, selected, picked_index, order_ids, paragraphs = [], "", None, [], []
        picked = (last.get("selection") or {}).get("slide_id")
        did = t.conversation.get("active_deck")
        if did:
            try:
                prs = read.open_deck(self.executor._bytes(t, did))
                for o, s in zip(read.outline(prs), prs.slides, strict=True):
                    one = read.slide(prs, o["slide_id"])
                    shapes = one["shapes"]
                    kinds = {sh["type"] for sh in shapes} & {"table", "picture", "chart", "group"}
                    title_id = s.shapes.title.shape_id if s.shapes.title is not None else None
                    lines = router.slide_lines(shapes, title_id, context.roles(one))
                    for sh in shapes:  # every paragraph and cell, for finding words the request names (router.locate)
                        for x in [sh, *(sh.get("shapes") or [])]:
                            for i, p in enumerate(x.get("paragraphs") or []):
                                words = "".join(r.get("text", "") for r in p.get("runs", []))
                                # a slide's title names the slide (measured: "delete the agenda", located as the
                                # title's shape, deleted the title)
                                place = "title" if x["shape_id"] == title_id else f"[{i}]"
                                paragraphs.append((o["index"] + 1, x["shape_id"], place, words))
                            for r, row in enumerate((x.get("table") or {}).get("cells") or []):
                                # the row as the router's sketch writes it, then each cell (measured: the router named a
                                # whole row as where, found nowhere cell by cell, and the model edited the row above)
                                line = " | ".join(" ".join(c.split()) if isinstance(c, str) else "" for c in row)
                                paragraphs.append((o["index"] + 1, x["shape_id"], f"row {r}", line))
                                for c, cell in enumerate(row):
                                    if isinstance(cell, str):
                                        paragraphs.append((o["index"] + 1, x["shape_id"], f"row {r}, column {c}", cell))
                    slides.append(
                        {"index": o["index"], "title": o["title"], "layout": o["layout"], "lines": lines, "kinds": kinds}
                    )
                    order_ids.append(o["slide_id"])
                    if picked == o["slide_id"]:  # what "here" means: the slide, and its shapes by role and text
                        picked_index = o["index"]
                        ids = last["selection"].get("shape_ids") or []
                        named = context.roles(one)
                        parts = [
                            f"the {named[sh['shape_id']]} ({' / '.join(router.slide_lines([sh], None)) or 'empty'})"
                            for sh in shapes
                            if sh["shape_id"] in ids
                        ]
                        selected = f"slide {o['index'] + 1}" + (f", {'; '.join(parts)}" if parts else "")
            except (NotFound, ToolError):
                pass
        from . import artist

        kept = t.conversation.get("artist_ideas") or {}
        ideas = ""
        if kept.get("ideas") and kept.get("slide_id") in order_ids:
            n_ = order_ids.index(kept["slide_id"]) + 1
            ideas = f"for slide {n_}:\n" + "\n".join(f"{i}. {artist.describe(d)}" for i, d in enumerate(kept["ideas"], 1))
        request = router.prompt(last["content"], router.sketch(slides, selected), len(slides), ideas)
        # the whole deck when it fits (measured: 392 tokens for 8 slides, 5 075 for 200); a deck too large for the
        # window keeps in full the slides the reranker finds nearest the request, and the selected one
        room = self.app.models.window(model) - llm.PRESETS["slides_router"][1]["max_tokens"] - 512
        if await asyncio.to_thread(self.app.models.count, request, model) > room:
            passages = [{"index": s["index"], "text": "\n".join([s["title"], *s["lines"]])} for s in slides]
            top, _ = await asyncio.to_thread(search.rank, self.app.reranker, last["content"], passages, 30)
            whole = {p["index"] for p in top} | ({picked_index} if picked_index is not None else set())
            request = router.prompt(last["content"], router.sketch(slides, selected, whole), len(slides), ideas)
            log.info("the deck is too large for the router: the nearest slides in full", extra={"whole": len(whole)})
        messages = [{"role": "user", "content": request}]
        text = ""
        try:
            async for chunk in self.app.models.stream(model, "slides_router", messages, None):
                text += ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
        except Exception as e:  # noqa: BLE001 - routing is an optimisation: without it, every tool is offered
            log.warning(f"routing failed ({type(e).__name__}): every tool offered")
            return None
        groups, t.intent, t.kind = router.parse(text)
        if groups is not None and t.kind in ("change", "question") and self._has_sources(t):
            # the organisation's documents with every change and question, the assistant deciding whether to search
            # (measured: "write an index of the topics of home loans" routed without them 5 times in 5, and the slide
            # was written from the model's own knowledge; a question has no tools at all to check a fact with)
            groups = groups | {"knowledge"}
        t.changes = t.kind == "change"
        t.groups = groups
        t.idea = router.idea_of(text) if ideas else None
        n = router.where_slide(text)
        named = router.phrase_slide(router.unquoted(last["content"]), slides) if slides else None
        if named and named[0] != n and t.kind == "change":
            # the request names a slide's own words: that slide, whatever the router read (its intent restated
            # from the person's words, with that slide as where)
            n = named[0]
            t.intent = f"{' '.join(last['content'].split())} (where: slide {n}: «{named[1]}»)"
        if n and 1 <= n <= len(slides):  # the slide the request is about: the deck map centres there
            t.focus = order_ids[n - 1]
        # the words the request quotes, and the line the router named, found in the deck (a lexical fact each)
        texts = {(s, sid, place): " ".join(words.split()) for s, sid, place, words in paragraphs}

        def place(s, sid, p):
            # as the call to make, with the whole line it is in (replayed, devai-01: "shape 115, paragraph
            # [0]" took the next line's shape 10 times in 10; as shape_id and index, the right one 10 in 10;
            # without the line, the paragraph was set to the corrected word alone)
            if p.startswith("["):
                line = texts.get((s, sid, p), "")
                said = f"slide {s}, in «{line}»: change it with shape_id {sid}, paragraph index {p[1:-1]}"
                # the router names one line; a request about a list is about all of it (measured: "shorten the agenda's
                # points", located as its first point, edited that one alone, 8 runs in 8): the shape's lines with it
                rest = [(q[1:-1], w) for (s_, sid_, q), w in texts.items() if s_ == s and sid_ == sid and q.startswith("[")]
                if 1 < len(rest) <= 15:
                    lines = "; ".join(f"[{i}] «{w}»" for i, w in rest if w)
                    said += f" (its shape's paragraphs: {lines}; if the request is about more of them, change each)"
                # the slide's title beside it: the router's line is a reading, not always the part meant (measured: the
                # same router input gave the title of a section header slide or its subtitle, 4 and 4, at temperature 0;
                # told only the subtitle's shape, "rename the section header" renamed the subtitle)
                title = next(((sid_, w) for (s_, sid_, q), w in texts.items() if s_ == s and q == "title"), None)
                if title and title[0] != sid and title[1]:
                    said = (f"slide {s}, in «{line}» (shape_id {sid}, paragraph index {p[1:-1]}), or its title «{title[1]}»"
                            f" (shape_id {title[0]}): change the one the request means" + said[len(said.split(" (its")[0]):])
                return said
            return f"slide {s}, shape_id {sid}, {p}"

        found, quoted_found = [], False
        for needle in [*router.quoted(last["content"]), router.where_text(text)]:
            if quoted_found and needle == router.where_text(text):
                break  # the words the person quoted, found, tell where better than the router's line
            hits = router.locate(paragraphs, needle) if needle else []
            if not hits and needle and not quoted_found:  # lines run together: each one it holds, named with its text
                parts = router.contained([p for p in paragraphs if not n or p[0] == n], needle)
                if 1 <= len(parts) <= 4:
                    for s_, sid_, place_, text_ in parts:
                        where_ = f"paragraph index {place_[1:-1]}" if place_.startswith("[") else place_
                        found.append(f"«{text_}» is in the deck at slide {s_}: shape_id {sid_}, {where_}")
                    continue
            others = []
            if n and any(h[0] == n for h in hits) and any(h[0] != n for h in hits):
                # words on several slides, the request about one: that one (measured: given all three places, the
                # model changed "Time Logging Extention" on slides 4, 42 and 46 for "in the agenda")
                others = sorted({h[0] for h in hits if h[0] != n})
                hits = [h for h in hits if h[0] == n]
            if 1 <= len(hits) <= 3:
                quoted_found = quoted_found or needle != router.where_text(text)
                titles = [s for s, _, p in hits if p == "title"]
                if titles and len(titles) == len(hits) and needle == router.where_text(text) and (
                    " ".join(needle.split()).casefold() not in " ".join(last["content"].split()).casefold()
                ):
                    # the router named the slide by its title, words the person did not say: the slide, whole
                    # (measured: "translate the last slide", where "Questions?", the title alone translated, 3 runs in 3)
                    t.intent = f"{t.intent.split(' (where: ')[0]} (where: slide {titles[0]})"
                    continue
                if titles and len(titles) == len(hits):
                    # a title names its slide; with the title's shape given, "delete the agenda" deleted the title
                    # (replayed: 6 delete_shape and 4 update_text in 10; worded as naming the slide, delete_slide 10)
                    found.append(f'«{needle}» is the title of slide {titles[0]}: "{needle}" names slide {titles[0]}')
                    continue
                places = "; ".join(place(s, sid, p) for s, sid, p in hits if p != "title")
                also = ""
                if len(others) > 5:  # measured: on a 200-slide deck, 199 numbers listed and the edit went astray
                    also = f" (also on {len(others)} other slides: not asked)"
                elif others:
                    also = f" (also on slide{'s' if len(others) > 1 else ''} {', '.join(map(str, others))}: not asked)"
                found.append(f"«{needle}» is in the deck at {places}{also}")
        t.located = list(dict.fromkeys(found))
        if quoted_found:  # the router's line may be the wrong one (measured: it named another agenda item)
            t.intent = t.intent.split(" (where: ")[0]
        log.info("routed", extra={"groups": ",".join(sorted(groups)) if groups is not None else "all"})
        return router.tools_of(groups)

    async def _missing(self, t: Turn, model: dict, closing: str) -> str:
        """What the turn's closing message says is still to be done, in a few words, or "" (the slides_checker preset,
        on the message alone: measured, asked to judge the request against the changes, it named "create the cover"
        and "the subtitle" after complete turns, and the model overwrote a cover's lines; asked only what the message
        says is pending, it named the 3 promises of squad-16 and none of 5 complete runs, 2 of ~40 other messages)."""
        if not closing.strip():
            return ""
        ask = f"The closing message:\n<message>{closing}</message>"
        try:
            got = ""
            async for chunk in self.app.models.stream(model, "slides_checker", [{"role": "user", "content": ask}], None, 200):
                got += ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
            answer = json.loads(got[got.find("{") : got.rfind("}") + 1])
            return " ".join(str(answer.get("pending") or "").split())[:300]
        except Exception as e:  # noqa: BLE001 - a check that fails leaves the turn as it was
            log.warning("the closing message could not be checked", extra={"err.type": type(e).__name__})
            return ""

    async def _fitted_budget(self, t: Turn, model: dict) -> tuple[int, int]:
        """The context budget with the offered tools trimmed, the least needed first, until they fit the window's fixed
        share (measured: a request needing slides, a table, a picture and the knowledge base was offered tools
        taking 34.1% of 32 768 with the prompt, and the turn was refused)."""
        while True:
            try:
                return await asyncio.to_thread(context.budget, self.app.models, model, t.tool_defs)
            except context.ModelTooSmall:
                names = [d["function"]["name"] for d in t.tool_defs]
                drop = next((n for n in EXPENDABLE if n in names), None)
                if drop is None:
                    raise
                t.tool_defs = [d for d in t.tool_defs if d["function"]["name"] != drop]
                log.warning("the tools do not fit: one left out", extra={"toolCount": len(t.tool_defs)})

    def _declined(self, t: Turn) -> bool:
        """Did the person just say no to a plan or the instructions (their last answer)?"""
        for m in reversed(self.app.conversations.messages(t.pid, t.cid)):
            if m["role"] == "user":
                return False
            if m["role"] == "tool":
                content = m.get("content") or ""
                return "NOT_APPROVED" in content or '"approved": false' in content or '"accepted": false' in content
        return False

    def _has_sources(self, t: Turn) -> bool:
        """Is there anything to search: the knowledge base, or the project's reference documents?"""
        return bool(self.app.kb.available) or any(a["kind"] == "document" for a in self.app.assets.list(t.pid))

    def _offered(self, t: Turn) -> list[dict]:
        """The tools this turn can use: the ones that apply to the project and deck as they are now. Each offered
        tool costs part of the window's fixed share, and a small model chooses worse among more (measured: 36 tools
        reached 24.6% of the window; targeting fell as tools were added). Any tool still runs when called."""
        p = self.app.proposals.open_in(t.pid, t.cid)
        decks = self.app.decks.list(t.pid, t.email)
        did = t.conversation.get("active_deck")
        try:
            deck = self.app.decks.get(t.pid, did, t.email) if did else None  # the whole record: its undo and redo stacks
        except NotFound:
            deck = None
        shapes: set[str] = set()
        if deck:
            try:
                prs = read.open_deck(self.executor._bytes(t, did))
                shapes = {sh.shape_type.name for s in prs.slides for sh in s.shapes if sh.shape_type is not None}
                shapes |= {"TABLE" for s in prs.slides for sh in s.shapes if getattr(sh, "has_table", False) and sh.has_table}
            except (NotFound, ToolError):
                pass
        others = len(self.app.conversations.list(t.pid, t.email)) > 1 or bool(t.conversation.get("summary"))
        when = {
            "decide_changes": bool(p and p["status"] == "pending"),
            "undo": bool(deck and deck.get("undo")),
            "redo": bool(deck and deck.get("redo")),
            "search_project": any(a["kind"] == "document" for a in self.app.assets.list(t.pid)),
            "search_conversations": others,
            "copy_slides": len(decks) > 1,
            "duplicate_deck": bool(deck),
            "edit_table": "TABLE" in shapes,
            "replace_image": "PICTURE" in shapes,
            "render_slide": t.can_see,
            "kb_search": self.app.kb.available,
            "kb_read_document": self.app.kb.available,
            "kb_list_images": self.app.kb.available,
            "generate_image": bool(getattr(getattr(self.app, "imagegen", None), "available", False)),
        }
        return [d for d in self.tool_defs if when.get(d["function"]["name"], True)]

    def _still_overflowing(self, t: Turn) -> list[tuple[str, int]]:
        """The shapes this turn's edits left too long that are still too long in the draft: [(slide, shape)]."""
        out = []
        for did, sid, shape_id in sorted(t.overflowing):
            try:
                prs = read.open_deck(self.executor._bytes(t, did))
                order = [s.slide_id for s in prs.slides]
                if sid not in order:
                    continue
                if any(x["shape_id"] == shape_id and x.get("overflow") for x in read.slide(prs, sid)["shapes"]):
                    out.append((slide_name(t, did, sid), shape_id))
            except (NotFound, KeyError, ValueError):
                continue
        return out

    def _plan_approved(self, t: Turn) -> bool:
        """Has the person approved a plan since their last message (so its deletions are theirs)?"""
        approved = False
        for m in self.app.conversations.messages(t.pid, t.cid):
            if m["role"] == "user":
                approved = False
            elif m["role"] == "tool" and m.get("name") == "propose_plan":
                try:
                    approved = approved or json.loads(m.get("content") or "{}").get("approved") is True
                except ValueError:
                    pass
        return approved

    def _step(self, t: Turn, name: str, args: dict) -> str:
        """The plan step for a deletion or a cross-deck copy, in the project's language: which slides, which decks."""
        pt = self.app.projects.get(t.pid, t.email).get("language", "pt") != "en"
        if name == "change_template":
            names = {(x["kind"], x["id"]): x["name"] for x in self.app.templates.listing(t.pid)}
            new = names.get((args["template"].get("kind"), args["template"].get("id")), args["template"].get("id"))
            if isinstance(new, dict):  # a name per language
                new = new.get("pt" if pt else "en") or next(iter(new.values()), "")
            return f"Mudar o modelo da apresentação para «{new}»" if pt else f"Change the deck's template to «{new}»"
        if name == "copy_slides":
            title = lambda did: next((d["title"] for d in self.app.decks.list(t.pid, t.email) if d["id"] == did), did)  # noqa: E731
            target = args.get("deck_id") or t.conversation.get("active_deck")
            slides = ", ".join(str(x) for x in args["slide_ids"])
            if pt:
                verb = "Mover" if args.get("move") else "Copiar"
                return f"{verb} os diapositivos {slides} de «{title(args['from_deck_id'])}» para «{title(target)}»"
            verb = "Move" if args.get("move") else "Copy"
            return f"{verb} slides {slides} from «{title(args['from_deck_id'])}» to «{title(target)}»"
        try:
            did = self.executor._deck_id(t, args)
            data = self.executor._bytes(t, did)
            deck = read.open_deck(data)
            sid = self.executor._positions({"slide_id": args["slide_id"]}, data, t.start_order.get(did))["slide_id"]
            o = next(x for x in read.outline(deck) if x["slide_id"] == int(sid))
            where = f"{o['index'] + 1} «{o['title']}»" if o["title"] else str(o["index"] + 1)
            shape = next(
                (s["name"] for s in read.slide(deck, o["slide_id"])["shapes"] if s["shape_id"] == args.get("shape_id")), ""
            )
        except (NotFound, StopIteration, KeyError, ToolError):
            where, shape = str(args.get("slide_id")), ""
        if name == "delete_slide":
            return f"Apagar o diapositivo {where}" if pt else f"Delete slide {where}"
        return f"Apagar a forma «{shape}» do diapositivo {where}" if pt else f"Delete the shape «{shape}» on slide {where}"

    async def _generate(self, pid: str, t: Turn, args: dict) -> dict:
        """generate_deck: the generation started and read (its progress in the panel), then {"plan"} - the outline's
        slides as the plan's steps, the build as its "then" - or an error the model tells the person."""
        target = {"kind": "new"}
        if args.get("new_deck") is False and t.conversation.get("active_deck"):
            target = {"kind": "deck", "deck_id": t.conversation["active_deck"]}
        request = {k: args[k] for k in ("kind", "source", "slides", "focus", "audience", "language") if args.get(k)}
        request["target"] = target

        async def progress(record: dict) -> None:
            pr = record.get("progress") or {}
            if pr.get("stage") in ("reading", "condensing") and pr.get("total"):
                detail = f"Reading part {min(pr['done'] + 1, pr['total'])} of {pr['total']}"
            elif pr.get("stage") == "planning":
                detail = "Planning the goals and the storyboard"
            elif pr.get("stage") == "writing" and pr.get("total"):
                detail = f"Writing slide {min(pr['done'] + 1, pr['total'])} of {pr['total']}"
            elif pr.get("stage") == "reviewing" and pr.get("total"):
                detail = f"Reviewing slide {min(pr['done'] + 1, pr['total'])} of {pr['total']}"
            elif pr.get("stage") == "designing" and pr.get("total"):
                detail = f"Designing slide {min(pr['done'] + 1, pr['total'])} of {pr['total']}"
            else:
                return
            await self.emit("tool_progress", {"tool": "generate_deck", "detail": detail}, t.cid)

        try:
            record = await self.app.generations.start(pid, t.email, request, on_progress=progress)
        except NotFound:
            hint = "Use an id from the project's documents."
            raise ToolError("NOT_FOUND", "There is no such document in the project.", hint) from None
        except ValueError as e:
            raise ToolError("BAD_SOURCE", str(e), "Tell the person.") from None
        await self.app.generations.wait(pid, record["id"])
        record = self.app.generations.get(pid, record["id"], t.email)
        if record["status"] != "ready":
            raise ToolError("NOT_GENERATED", record.get("error") or "The outline could not be made.", "Tell the person why.")
        out = record["outline"]
        steps = [f"Capa: «{out['title']}»"] + [f"{s['title']}" for s in out["slides"]]
        plan = {"steps": steps, "generation_id": record["id"], "goals": out.get("goals") or [],
                "then": {"name": "build_generation", "arguments": {"generation_id": record["id"]}}}  # fmt: skip
        return {"plan": plan}

    async def _wait(self, pid: str, t: Turn, call_id: str, name: str, args: dict) -> None:
        kind = {"ask_user": "question", "propose_plan": "plan", "update_instructions": "instructions"}[name]
        if kind == "instructions":
            project = self.app.projects.get(pid, t.email, roles=("owner", "editor"))
            args = {"text": args["text"], "before": project["instructions"]}
        async with storage.lock(pid):
            conv = self.app.conversations.get(pid, t.cid, t.email)
            conv["pending"] = {"kind": kind, "tool_call_id": call_id, "payload": args}
            conv["route"] = {
                "intent": t.intent,
                "kind": t.kind,
                "groups": sorted(t.groups) if t.groups is not None else None,
                "done": list(t.done),
                "order": {k: list(v) for k, v in t.start_order.items()},
                "focus": t.focus,
                "located": list(t.located),
                "overflowing": [list(x) for x in sorted(t.overflowing)],
            }
            self.app.conversations.write(pid, conv)
            t.conversation = conv
        await self.emit(kind if kind != "instructions" else "instructions_proposed", {"tool_call_id": call_id, **args}, t.cid)

    # ── proposals ────────────────────────────────────────────────────
    def describe(self, pid: str, p: dict) -> dict:
        """A proposal as the page shows it: per deck, its base version and the slides it touches (before/after)."""
        decks = {}
        for did, d in p["decks"].items():
            draft = self.app.proposals.draft_path(pid, p, did)
            after = {s["id"]: s for s in (self._slides_of(draft.read_bytes()) if draft.exists() else [])}
            before = {}
            try:
                before = {
                    s["id"]: s for s in self._slides_of(self.app.layout.version_file(pid, did, d["base_version"]).read_bytes())
                }
            except FileNotFoundError:
                pass
            slides = []
            for sid in self.app.proposals.affected(p, did):
                state = (
                    "added"
                    if sid not in before and sid in after
                    else "removed"
                    if sid in before and sid not in after
                    else "changed"
                )
                if sid not in before and sid not in after:
                    continue  # created and removed within the proposal
                slides.append({"slide_id": sid, "state": state, "title": (after.get(sid) or before.get(sid))["title"]})
            decks[did] = {
                "base_version": d["base_version"],
                "slides": slides,
                "operations": [{"name": o["name"], "slides": o["slides"]} for o in d["operations"]],
                # the draft's slides in order (the editor's strip while reviewing), with each one's state
                "order": [
                    {
                        "id": sid,
                        "title": s["title"],
                        "hidden": s["hidden"],
                        "state": next((x["state"] for x in slides if x["slide_id"] == sid), "same"),
                    }
                    for sid, s in after.items()
                ],
            }
        return {"id": p["id"], "conversation_id": p["conversation_id"], "status": p["status"], "decks": decks}

    @staticmethod
    def _slides_of(data: bytes) -> list[dict]:
        from ..docengine import files

        return files.slides(data)

    async def _decide_in_words(self, t: Turn, args: dict) -> dict:
        """decide_changes: the pending proposal accepted or rejected, all of it or the slides named by their number in
        the review (the draft's order, as the review strip shows them)."""
        p = self.app.proposals.open_in(t.pid, t.cid)
        if not p or p["status"] != "pending":
            raise ToolError("NOTHING_IN_REVIEW", "No changes are waiting for a decision.", "")
        decision = args["decision"]
        if decision in ("accept_all", "reject_all"):
            done = await self.decide(t.pid, t.cid, p["id"], t.email, decision == "accept_all")
            await asyncio.to_thread(audit.record, self.app.layout.audit, t.email, "assistant decide_changes",
                                    {"pid": t.pid, "cid": t.cid, "prid": p["id"], "status": done["status"]})  # fmt: skip
            return {"ok": True, "status": done["status"]}
        shown = self.describe(t.pid, p)["decks"]
        named = {int(n) for n in args.get("slides") or []}
        if not named:
            raise ToolError("BAD_ARGUMENTS", f"{decision} needs the slides' numbers.", "")
        keep: dict[str, list[int]] = {}
        for did, d in shown.items():
            order = [x["id"] for x in d["order"]] + [x["slide_id"] for x in d["slides"] if x["state"] == "removed"]
            changed = [x["slide_id"] for x in d["slides"]]
            picked = {order[n - 1] for n in named if 1 <= n <= len(order)}
            keep[did] = [s for s in changed if (s in picked) == (decision == "accept_only")]
        if not any(keep.values()):
            done = await self.decide(t.pid, t.cid, p["id"], t.email, False)
        else:
            done = await self.decide(t.pid, t.cid, p["id"], t.email, True, keep)
        return {"ok": True, "status": done["status"]}

    async def decide(
        self, pid: str, cid: str, prid: str, email: str, accept: bool, slides: dict[str, list[int]] | None = None
    ) -> dict:
        """Accept (all, or the slides given per deck) or reject a pending proposal (spec NL-9; section 5.1)."""
        self.app.projects.get(pid, email, roles=("owner", "editor"))
        p = self.app.proposals.get(pid, cid, prid)
        if p["status"] in FINAL:
            raise ValueError(f"this proposal is already {p['status']}")
        if p["status"] == "drafting":
            raise ValueError("this proposal is still being made")
        if not accept:
            p.update(status="rejected", decided_at=storage.now(), decided_by=email)
            self.app.proposals.write(pid, p)
            self.app.proposals.drop_drafts(pid, p)
            await self.emit("proposal_updated", self.describe(pid, p) | {"status": "rejected"}, cid)
            return p
        leases = getattr(self.app.decks, "leases", None)
        for did in p["decks"] if leases is not None else []:  # every deck free before any is published (spec PJ-13)
            try:
                leases.check(did, email)
            except Leased as e:
                raise ValueError(f"the deck is being edited by {e.holder}: accept when they have closed it") from None
        t = Turn(pid=pid, cid=cid, email=email, conversation=self.app.conversations.get(pid, cid, email))
        partial = False
        try:
            for did, d in p["decks"].items():
                every = set(self.app.proposals.affected(p, did))
                wanted = set(int(s) for s in (slides or {}).get(did, every)) & every
                if wanted != every:
                    partial = True
                if not wanted:
                    continue
                draft = self.app.proposals.draft_path(pid, p, did).read_bytes()
                deck = self.app.decks.get(pid, did, email)
                if wanted == every and deck["current_version"] == d["base_version"]:
                    published = await self.app.decks.publish(
                        pid, did, email, draft, "assistant", base_version=d["base_version"], proposal_id=p["id"]
                    )
                else:
                    _, current = self.app.decks.version_bytes(pid, did, email)
                    data, applied = await asyncio.to_thread(
                        self.app.proposals.replay, current, d["operations"], wanted, self.executor.resolve(t)
                    )
                    if not applied:
                        continue
                    published = await self.app.decks.publish(pid, did, email, data, "assistant", proposal_id=p["id"])
                changed = [op["args"]["template"] for op in d["operations"] if op["name"] == "change_template"]
                if changed and wanted == every:  # the deck's template is now the one it was changed to (PM-10)
                    await self.app.decks.set_template(pid, did, email, changed[-1])
                d["accepted_slides"] = sorted(wanted)
                d["result_version"] = published["current_version"]
                self.app.renderer.warm(pid, self.app.layout.version_file(pid, did, published["current_version"]).read_bytes())
                await self.emit("deck_changed", {"deck_id": did}, cid)
            p.update(status="partially_accepted" if partial else "accepted", decided_at=storage.now(), decided_by=email)
            versions = {k: d["result_version"] for k, d in p["decks"].items() if d.get("result_version")}
            line = {"at": storage.now(), "user": email, "event": "proposal_accepted", "conversation_id": cid,
                    "proposal_id": p["id"], "versions": versions}  # the versions its tool calls became (M4)
            await asyncio.to_thread(storage.append_line, self.app.layout.project_audit(pid), line, "project-audit-line")
        except Stale as e:
            # the edit and its error code, never its message (security review L5: it may quote what was written)
            cause = e.__cause__
            code = getattr(cause, "code", type(cause).__name__)
            log.info("a proposal went stale", extra={"op": str(e).split(":")[0][:40], "code": code})
            p.update(status="stale", decided_at=storage.now(), decided_by=email)
        self.app.proposals.write(pid, p)
        self.app.proposals.drop_drafts(pid, p)
        await self.emit(
            "proposal_updated",
            {
                "id": p["id"],
                "conversation_id": cid,
                "status": p["status"],
                "decks": {k: {"result_version": v.get("result_version")} for k, v in p["decks"].items()},
            },
            cid,
        )
        return p


__all__ = ["Agent", "llm", "speakable"]
