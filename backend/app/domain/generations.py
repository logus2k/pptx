"""Decks generated from a source (spec NL-12): a corporate presentation or a training, from what the knowledge base
holds on a topic, a knowledge-base document, or a project's reference document. Started from the project page's form
or by the assistant (both: the user's rule, 2026-10-07); either way one generation: the source read in the background
(agent/outline.py), its outline shown to the person - who edits it - then the slides made in one new version of a new
or an existing deck, each slide's notes saying what to present and where it comes from.

Kept as DATA_DIR/projects/<pid>/generations/<id>.json (a draft, as proposals: not in the project's archive). A
generation still reading when the server stops is marked failed when it is next read (its task is gone)."""

from __future__ import annotations

import asyncio
import logging

from .. import storage
from ..agent import artist, critic, outline
from ..docengine import files, ops, read
from ..storage import NotFound

log = logging.getLogger("slides.generations")
WRITE_ROLES = ("owner", "editor")


class Generations:
    def __init__(self, app) -> None:
        self.app = app
        self._tasks: dict[str, asyncio.Task] = {}
        self._vision: dict[str, bool] = {}  # a model's sight, tested once (llm.Models.vision)

    def _path(self, pid: str, gid: str):
        if not storage.is_id(gid):
            raise NotFound("generation")
        return self.app.layout.project(pid) / "generations" / f"{gid}.json"

    def _write(self, pid: str, record: dict) -> None:
        record["updated_at"] = storage.now()
        storage.write_json(self._path(pid, record["id"]), record, "generation")

    def get(self, pid: str, gid: str, email: str) -> dict:
        self.app.projects.get(pid, email)
        record = storage.read_json(self._path(pid, gid))
        if record["status"] == "reading" and gid not in self._tasks:
            record["status"], record["error"] = "failed", "The reading was interrupted (the server restarted): start it again."
            self._write(pid, record)
        return record

    async def start(self, pid: str, email: str, request: dict, on_progress=None) -> dict:
        """A new generation, its source read in the background; on_progress(record) after each step (the assistant's
        progress in the panel)."""
        project = self.app.projects.get(pid, email, roles=WRITE_ROLES)
        source = request["source"]
        need = {"document": ("asset_id",), "kb_document": ("domain", "path"), "kb_topic": ("query",)}[source["kind"]]
        if any(not str(source.get(k) or "").strip() for k in need):
            raise ValueError(f"A {source['kind']} source needs {', '.join(need)}.")
        if source["kind"] == "document":
            asset = self.app.assets.get(pid, source["asset_id"])  # NotFound when it is not the project's
            if asset["kind"] != "document":
                raise ValueError("That file is not a reference document.")
        elif self.app.kb is None or not self.app.kb.available:
            raise ValueError("The knowledge base is not available here.")
        if request.get("target", {}).get("kind") == "deck":
            self.app.decks.get(pid, request["target"]["deck_id"], email)
        now = storage.now()
        record = {"schema_version": 1, "id": storage.new_id(), "created_by": email, "created_at": now, "updated_at": now,
                  "status": "reading", "progress": {"stage": "reading", "done": 0, "total": 0}, "request": request}  # fmt: skip
        self._write(pid, record)
        model = await asyncio.to_thread(self.app.models.resolve, project["settings"]["model"])
        domains = project["settings"].get("kb_domains") or None
        task = asyncio.create_task(self._read(pid, email, record, model, domains, on_progress))
        self._tasks[record["id"]] = task
        task.add_done_callback(lambda _t, gid=record["id"]: self._tasks.pop(gid, None))
        return record

    async def wait(self, pid: str, gid: str) -> None:
        task = self._tasks.get(gid)
        if task is not None:
            await asyncio.shield(task)

    async def _read(self, pid: str, email: str, record: dict, model: dict, domains, on_progress) -> None:
        req = record["request"]

        async def progress(stage: str, done: int, total: int) -> None:
            record["progress"] = {"stage": stage, "done": done, "total": total}
            await asyncio.to_thread(self._write, pid, record)
            if on_progress is not None:
                await on_progress(record)

        try:
            got = await outline.draft(
                self.app, model, email, pid, req["source"], kind=req["kind"], slides=req.get("slides"),
                focus=req.get("focus") or "", audience=req.get("audience") or "", language=req.get("language") or "pt",
                domains=domains, progress=progress,
            )  # fmt: skip
            if not got["slides"]:
                raise outline.SourceEmpty("the outline came back empty")
            # each slide's form, by the Artist (agent/artist.py): checked, a list when its proposal does not hold
            goal = artist.goal_of(req["kind"], req.get("audience") or "", req.get("focus") or "", got.get("title") or "")
            got["slides"] = await artist.design_outline(self.app, model, got["slides"], goal, progress, got.get("goals"))
            # each slide judged as rendered, and revised while the Critic asks (agent/critic.py); a model that cannot
            # see skips it, said in the log
            if model["id"] not in self._vision:
                self._vision[model["id"]] = await asyncio.to_thread(self.app.models.vision, model)
            if self._vision[model["id"]]:
                blank = await asyncio.to_thread(self._blank, pid, email, req)
                lang = "European Portuguese (Portugal)" if (req.get("language") or "pt") == "pt" else "English"
                got["slides"] = await critic.refine(self.app, model, blank, got["slides"], got.get("goals") or [], goal,
                                                    lang, self.app.layout.renders(pid), progress, req["kind"])  # fmt: skip
            else:
                log.info("the model cannot see: the slides not reviewed")
            got["slides"] = [{k: v for k, v in s.items() if k != "_spare"} for s in got["slides"]]  # the Critic's only
            record["outline"] = got
            record["status"] = "ready"
            log.info("outline ready", extra={"slideCount": len(got["slides"]), "kind": req["kind"]})
        except outline.SourceTooLarge as e:
            said = f"The source is too long to read whole ({e}): choose a section or narrow the topic."
            record["status"], record["error"] = "failed", said
        except outline.SourceEmpty:
            record["status"], record["error"] = "failed", "Nothing was found to make slides from: try another topic or document."
        except Exception as e:  # noqa: BLE001 - any failure is the generation's, said to the person by its kind
            log.error("generation failed", extra={"err.type": type(e).__name__})
            # (measured: the model server stalled for 15 minutes, every call timed out - said as the source's fault)
            slow = type(e).__name__ in ("ReadTimeout", "ConnectTimeout", "Timeout", "ConnectionError")
            said = "The model service did not answer in time: try again in a few minutes." if slow else (
                f"The source could not be read ({type(e).__name__}).")
            record["status"], record["error"] = "failed", said
        record["progress"] = {"stage": record["status"], "done": 1, "total": 1}
        await asyncio.to_thread(self._write, pid, record)
        if on_progress is not None:
            await on_progress(record)

    def _blank(self, pid: str, email: str, req: dict) -> bytes:
        """The deck the slides will go on, without slides: the target deck's, or the chosen (or the project's) template."""
        target = req.get("target") or {"kind": "new"}
        if target["kind"] == "deck":
            _, data = self.app.decks.version_bytes(pid, target["deck_id"], email)
            return files.without_slides(data)
        template = target.get("template") or self.app.projects.get(pid, email)["settings"]["default_template"]
        return files.without_slides(self.app.templates.bytes_of(pid, template))

    def edit(self, pid: str, gid: str, email: str, title: str, slides: list[dict]) -> dict:
        """The person's edits to the outline before the slides are made."""
        self.app.projects.get(pid, email, roles=WRITE_ROLES)
        record = self.get(pid, gid, email)
        if record["status"] != "ready":
            raise ValueError("Only an outline that is ready can be changed.")
        record["outline"]["title"] = " ".join(title.split()) or record["outline"]["title"]
        kept = []
        for slide in slides:  # a design sent back is checked again (agent/artist.checked); none, the slide's list
            slide = {k: v for k, v in slide.items() if v is not None}
            if slide.get("design"):
                slide["design"] = artist.checked(slide["design"], slide)
            kept.append(slide)
        record["outline"]["slides"] = kept
        self._write(pid, record)
        return record

    async def ideas(self, pid: str, gid: str, email: str, index: int, wish: str = "") -> list[dict]:
        """The Artist's ideas for one slide of an outline under review (the outline editor's Other ideas)."""
        project = self.app.projects.get(pid, email, roles=WRITE_ROLES)
        record = self.get(pid, gid, email)
        if record["status"] != "ready":
            raise ValueError("Only an outline that is ready can be changed.")
        slides = record["outline"]["slides"]
        if not 0 <= index < len(slides):
            raise NotFound("slide")
        model = await asyncio.to_thread(self.app.models.resolve, project["settings"]["model"])
        req = record["request"]
        goal = artist.goal_of(req.get("kind", ""), req.get("audience") or "", req.get("focus") or "", record["outline"]["title"])
        goals, slide = record["outline"].get("goals") or [], slides[index]
        if 1 <= (slide.get("goal") or 0) <= len(goals):  # its task and goal, as planned (agent/outline.plan)
            slide = {**slide, "goal_text": goals[slide["goal"] - 1]}
        return await artist.ideas(self.app, model, slide, 3, wish, goal)

    def notes_of(self, record: dict, item: dict) -> str:
        """What the presenter says, then where it comes from (spec KB-3: the sources in the notes)."""
        links = {s["document"]: s.get("link") for s in (record["outline"].get("sources") or []) if s.get("document")}
        lines = []
        for where in item.get("sources") or []:
            link = next((u for d, u in links.items() if u and d and d in where), None)
            lines.append(f"Fonte: {where}" + (f" - {link}" if link else ""))
        return "\n\n".join(x for x in (item.get("notes") or "", "\n".join(lines)) if x)

    async def build(self, pid: str, gid: str, email: str) -> dict:
        """The slides: a new deck (from the chosen template, or the project's) or after an existing deck's last slide,
        in one new version. Returns the record, with deck_id and slide_ids."""
        project = self.app.projects.get(pid, email, roles=WRITE_ROLES)
        record = self.get(pid, gid, email)
        if record["status"] != "ready":
            ready = "The outline is not ready." if record["status"] == "reading" else "This outline was already made into slides."
            raise ValueError(ready)
        out, req = record["outline"], record["request"]
        target = req.get("target") or {"kind": "new"}
        if target["kind"] == "deck":
            did = target["deck_id"]
            deck, data = self.app.decks.version_bytes(pid, did, email)
            order = [o["slide_id"] for o in read.outline(read.open_deck(data))]
            after, cover = (order[-1] if order else None), (None if order else {"title": out["title"]})
        else:
            template = target.get("template") or project["settings"]["default_template"]
            deck = await self.app.decks.from_template(pid, email, out["title"], template)
            did = deck["id"]
            _, data = self.app.decks.version_bytes(pid, did, email)
            after, cover = None, {"title": out["title"], **({"subtitle": req["audience"]} if req.get("audience") else {})}
        slides = [{**s, "notes": self.notes_of(record, s)} for s in out["slides"]]
        args = {"slides": slides, "cover": cover, "after_slide_id": after}
        new, result = await asyncio.to_thread(ops.apply, data, "add_outline", args)
        await self.app.decks.publish(pid, did, email, new, "generated", base_version=deck["current_version"])
        record["status"], record["deck_id"], record["slide_ids"] = "built", did, result["slides"]
        self._write(pid, record)
        made = self.app.decks.get(pid, did, email)["current_version"]
        line = {"at": storage.now(), "user": email, "event": "generation_built", "generation_id": gid, "deck_id": did,
                "version": made}  # the project's audit trail (security review M4)
        await asyncio.to_thread(storage.append_line, self.app.layout.project_audit(pid), line, "project-audit-line")
        log.info("generated deck built", extra={"slideCount": len(result["slides"])})
        return record
