"""The REST API (spec section 9, technical design section 10), under /api/. Every route reads the person from the
proxy's identity (identity.current_user); a project the person is not a member of answers 404, as one that does not
exist."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import audit, identity
from .docengine import files, ops, read, render
from .domain.decks import Decks
from .domain.projects import Projects
from .domain.templates import ProjectAssets, Templates
from .kb import KBError
from . import storage
from .domain import archive
from .domain.leases import Leased
from .storage import Layout, NotFound

log = logging.getLogger("slides.api")
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class Renderer:
    """Renders a version's slides in the background once it is published, and serves a slide's images: a request
    for a slide whose images are not made yet waits for that background work rather than starting LibreOffice twice."""

    def __init__(self, layout: Layout) -> None:
        self.layout = layout
        self._running: dict[tuple[str, str], asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()

    on_warm = None  # also told of every version warmed: the describer (describe.py)

    def warm(self, pid: str, data: bytes) -> None:
        if self.on_warm is not None:
            self.on_warm(pid, data)
        key = (pid, hashlib.sha256(data).hexdigest())
        if key in self._running:
            return
        task = asyncio.create_task(render.ensure(data, self.layout.renders(pid)))
        self._running[key] = task
        self._tasks.add(task)

        def done(t: asyncio.Task) -> None:
            self._running.pop(key, None)
            self._tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                log.error("rendering a deck failed", exc_info=t.exception())

        task.add_done_callback(done)

    async def image(self, pid: str, data: bytes, slide_id: int, size: str):
        cache = self.layout.renders(pid)
        keys = {k["id"]: k["key"] for k in await asyncio.to_thread(render.keys, data)}
        if slide_id not in keys:
            raise NotFound("slide")
        path = cache / keys[slide_id] / f"{size}.png"
        if not path.exists():
            running = self._running.get((pid, hashlib.sha256(data).hexdigest()))
            if running is not None:
                try:
                    await asyncio.shield(running)
                except Exception:  # noqa: BLE001, S110 - the deck's render failed: try this slide alone below
                    pass
            if not path.exists():
                await render.ensure(data, cache, only={slide_id})
        return path, keys[slide_id]


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class SettingsChanges(BaseModel):
    kb_domains: list[str] | None = Field(default=None, max_length=50)  # [] = all the person's domains (spec PJ-12)
    language: Literal["pt", "en"] | None = None


class ProjectChanges(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, max_length=20000)
    archived: bool | None = None
    settings: SettingsChanges | None = None


class Member(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: str = Field(min_length=5, max_length=6)


class MemoryText(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class NewConversation(BaseModel):
    title: str = Field(default="", max_length=200)
    deck_id: str | None = None


class Decision(BaseModel):
    accept: bool
    slides: dict[str, list[int]] | None = None


class TemplateRef(BaseModel):
    kind: str = Field(min_length=1, max_length=16)
    id: str = Field(min_length=1, max_length=64)


class NewDeck(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    template: TemplateRef


class DeckChanges(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ManualEdit(BaseModel):
    """An edit made by hand in the editor (spec PM-7): a shape's text, a slide moved, a slide deleted. base_version is
    the version the page showed: a deck that has moved on since answers 409 (technical design section 5.2)."""

    base_version: int = Field(ge=1)
    op: Literal["text", "move", "delete", "tool"]
    slide_id: int | None = Field(default=None, ge=256)
    shape_id: int | None = Field(default=None, ge=1)
    paragraphs: list[str] | None = Field(default=None, max_length=500)
    position: int | None = Field(default=None, ge=0)
    # op "tool": one of the assistant's editing tools (MANUAL_TOOLS) with its arguments, checked against the same schema
    # (contracts/tools): every change the assistant can make has a control (the user's rule, 2026-10-07)
    tool: str | None = Field(default=None, max_length=40)
    args: dict | None = None


# the editing tools the editor's controls use, applied as the assistant's are (agent/tools.py), published at once as
# a "manual" version that undo takes back
MANUAL_TOOLS = ("redesign_slide", "add_slide", "duplicate_slide", "move_slide", "delete_slide", "change_layout", "add_chart",
                "edit_chart",
                "draw_diagram", "insert_image", "replace_image", "set_alt_text", "set_notes", "edit_table", "format_text",
                "fit_text", "copy_slides", "change_template")  # fmt: skip


class IdeasAsk(BaseModel):
    wish: str = Field(default="", max_length=300)  # what the person wishes, in their words; empty: the Artist's own


class GenerationSource(BaseModel):
    kind: Literal["kb_topic", "kb_document", "document"]
    query: str | None = Field(default=None, max_length=500)
    domain: str | None = Field(default=None, max_length=200)
    path: str | None = Field(default=None, max_length=1000)
    asset_id: str | None = Field(default=None, max_length=64)


class GenerationTarget(BaseModel):
    kind: Literal["new", "deck"] = "new"
    deck_id: str | None = Field(default=None, max_length=64)
    template: TemplateRef | None = None


class NewGeneration(BaseModel):
    """A deck from a source (spec NL-12): a corporate presentation or a training."""

    kind: Literal["corporate", "training"] = "corporate"
    source: GenerationSource
    slides: int | None = Field(default=None, ge=1, le=40)
    focus: str = Field(default="", max_length=1000)
    audience: str = Field(default="", max_length=300)
    language: Literal["pt", "en"] = "pt"
    target: GenerationTarget = Field(default_factory=GenerationTarget)


class OutlineSlide(BaseModel):
    role: Literal["content", "objectives", "section", "questions", "summary"] = "content"
    title: str = Field(min_length=1, max_length=300)
    points: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=6000)
    sources: list[str] = Field(default_factory=list, max_length=20)
    design: dict | None = None  # the Artist's proposal the person kept or chose (checked again: agent/artist.checked)
    task: str = Field(default="", max_length=1000)  # the Planner's (agent/outline.plan): kept through the person's edits
    goal: int = Field(default=0, ge=0, le=8)
    review: dict | None = None  # the Critic's last word (agent/critic.py), kept through the person's edits


class OutlineEdit(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    slides: list[OutlineSlide] = Field(min_length=1, max_length=60)


class TemplateChanges(BaseModel):
    """An administrator template renamed, retired or brought back, or made the default (spec AD-4)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    retired: bool | None = None
    default: Literal[True] | None = None


def build(
    settings,
    layout: Layout,
    projects: Projects,
    decks: Decks,
    assets: ProjectAssets,
    templates: Templates,
    renderer: Renderer,
    conversations=None,
    proposals=None,
    agent=None,
    kb=None,
    memory=None,
    generations=None,
) -> APIRouter:
    r = APIRouter(prefix="/api")
    max_bytes = settings.file["limits"]["upload_mb"] * 1024 * 1024

    def leased(e: Leased) -> HTTPException:  # spec PJ-13: another member has the deck open
        return HTTPException(409, {"code": "leased", "holder": e.holder, "message": f"The deck is being edited by {e.holder}."})

    def found(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotFound:
            raise HTTPException(404, "not found") from None
        except Leased as e:
            raise leased(e) from None

    async def afound(coro):
        try:
            return await coro
        except NotFound:
            raise HTTPException(404, "not found") from None
        except Leased as e:
            raise leased(e) from None

    async def read_upload(upload: UploadFile) -> bytes:
        data = await upload.read(max_bytes + 1)
        if len(data) > max_bytes:
            message = f"The file is larger than {max_bytes // (1024 * 1024)} MB."
            raise HTTPException(413, {"code": "too_large", "message": message})
        return data

    # ── projects ─────────────────────────────────────────────────────
    @r.get("/projects")
    async def list_projects(user: identity.User = Depends(identity.current_user)):
        return {"projects": await asyncio.to_thread(projects.list, user.email)}

    @r.post("/projects", status_code=201)
    async def create_project(body: NewProject, request: Request, user: identity.User = Depends(identity.current_user)):
        project = await projects.create(user.email, body.name, body.description)
        request.state.audit = {"pid": project["id"]}
        return project

    @r.get("/projects/{pid}")
    async def get_project(pid: str, user: identity.User = Depends(identity.current_user)):
        project = found(projects.get, pid, user.email)
        return {**project, "role": next(m["role"] for m in project["members"] if m["email"] == user.email)}

    # ── members (spec PJ-13, as Cortex's project members: owners add, change and remove; anyone may leave) ──
    @r.put("/projects/{pid}/members")
    async def set_member(pid: str, body: Member, request: Request, user: identity.User = Depends(identity.current_user)):
        try:
            project = await afound(projects.set_member(pid, user.email, body.email, body.role))
        except ValueError as e:
            raise HTTPException(400, {"code": "member", "message": str(e)}) from None
        request.state.audit = {"member": body.email.strip().lower(), "role": body.role}
        return {"members": project["members"]}

    @r.delete("/projects/{pid}/members/{member}")
    async def remove_member(pid: str, member: str, user: identity.User = Depends(identity.current_user)):
        try:
            project = await afound(projects.remove_member(pid, user.email, member))
        except ValueError as e:
            raise HTTPException(400, {"code": "member", "message": str(e)}) from None
        return {"members": project["members"] if member.strip().lower() != user.email else []}

    # ── a project's archive (spec PJ-14): exported whole, imported as a new project ──
    @r.get("/projects/{pid}/export")
    async def export_project(pid: str, user: identity.User = Depends(identity.current_user)):
        project = found(projects.get, pid, user.email)
        convs = found(conversations.list, pid, user.email) if conversations is not None else []
        data = await asyncio.to_thread(
            archive.export, layout, project, convs, lambda cid: conversations.messages(pid, cid) if conversations else []
        )
        name = "".join(c if c.isalnum() or c in " -_" else "_" for c in project["name"]).strip() or "project"
        disposition = f'attachment; filename="{name[:80]}.zip"'
        return Response(data, media_type="application/zip", headers={"Content-Disposition": disposition})

    @r.post("/projects/import", status_code=201)
    async def import_project(request: Request, file: UploadFile, user: identity.User = Depends(identity.current_user)):
        raw = await file.read(max_bytes * 10 + 1)
        if len(raw) > max_bytes * 10:
            raise HTTPException(413, {"code": "too_large", "message": f"The archive is larger than {max_bytes * 10 >> 20} MB."})
        try:
            entries = await asyncio.to_thread(archive.unpack, raw, max_bytes)
            await asyncio.to_thread(archive.check, entries, max_bytes)
        except archive.BadArchive as e:
            raise HTTPException(422, {"code": "archive", "message": str(e)}) from None
        pid = storage.new_id()
        project = await asyncio.to_thread(archive.write, layout, entries, pid, user.email)
        request.state.audit = {"pid": pid}
        return {"id": pid, "name": project["name"]}

    @r.patch("/projects/{pid}")
    async def change_project(pid: str, body: ProjectChanges, user: identity.User = Depends(identity.current_user)):
        return await afound(projects.update(pid, user.email, body.model_dump(exclude_none=True)))

    # ── the project's memory (spec PJ-9): people see, edit and delete what the assistant kept ──
    @r.get("/projects/{pid}/memory")
    async def list_memory(pid: str, user: identity.User = Depends(identity.current_user)):
        return {"items": found(memory.list, pid, user.email)}

    @r.post("/projects/{pid}/memory", status_code=201)
    async def add_memory(pid: str, body: MemoryText, user: identity.User = Depends(identity.current_user)):
        try:
            return await afound(memory.add(pid, user.email, body.text))
        except ValueError as e:
            raise HTTPException(400, {"code": "memory", "message": str(e)}) from None

    @r.patch("/projects/{pid}/memory/{mid}")
    async def change_memory(pid: str, mid: str, body: MemoryText, user: identity.User = Depends(identity.current_user)):
        try:
            return await afound(memory.update(pid, user.email, mid, body.text))
        except ValueError as e:
            raise HTTPException(400, {"code": "memory", "message": str(e)}) from None

    @r.delete("/projects/{pid}/memory/{mid}", status_code=204)
    async def delete_memory(pid: str, mid: str, user: identity.User = Depends(identity.current_user)):
        await afound(memory.delete(pid, user.email, mid))
        return Response(status_code=204)

    @r.get("/kb/domains")
    async def kb_domains(user: identity.User = Depends(identity.current_user)):
        """The knowledge-base domains this person can use (for a project's settings, spec PJ-12)."""
        if kb is None or not kb.available:
            return {"available": False, "domains": []}
        try:
            return {"available": True, "domains": await asyncio.to_thread(kb.domains, user.email)}
        except KBError as e:
            log.warning("the knowledge base's domains are unavailable", extra={"status": e.status})
            return {"available": False, "domains": [], "error": str(e)}

    @r.delete("/projects/{pid}", status_code=204)
    async def delete_project(pid: str, user: identity.User = Depends(identity.current_user)):
        await afound(projects.delete(pid, user.email))
        return Response(status_code=204)

    # ── decks generated from a source (spec NL-12): the form's path (the assistant's: agent/tools.py) ──
    def generation_error(e: Exception) -> HTTPException:
        return HTTPException(400, {"code": "generation", "message": str(e)})

    @r.post("/projects/{pid}/generations", status_code=201)
    async def start_generation(
        pid: str, body: NewGeneration, request: Request, user: identity.User = Depends(identity.current_user)
    ):
        req = body.model_dump(exclude_none=True)
        try:
            record = await afound(generations.start(pid, user.email, req))
        except ValueError as e:
            raise generation_error(e) from None
        request.state.audit = {"gid": record["id"]}
        return record

    @r.get("/projects/{pid}/generations/{gid}")
    async def get_generation(pid: str, gid: str, user: identity.User = Depends(identity.current_user)):
        return found(generations.get, pid, gid, user.email)

    @r.put("/projects/{pid}/generations/{gid}/outline")
    async def edit_generation(pid: str, gid: str, body: OutlineEdit, user: identity.User = Depends(identity.current_user)):
        try:
            return found(generations.edit, pid, gid, user.email, body.title, [x.model_dump() for x in body.slides])
        except ValueError as e:
            raise generation_error(e) from None

    @r.post("/projects/{pid}/generations/{gid}/slides/{index}/ideas")
    async def outline_slide_ideas(
        pid: str, gid: str, index: int, body: IdeasAsk, user: identity.User = Depends(identity.current_user)
    ):
        """The Artist's ideas for one slide of an outline under review: [design] (each in another form)."""
        try:
            return {"ideas": await afound(generations.ideas(pid, gid, user.email, index, body.wish))}
        except ValueError as e:
            raise generation_error(e) from None

    @r.post("/projects/{pid}/decks/{did}/slides/{slide_id}/ideas")
    async def deck_slide_ideas(
        pid: str, did: str, slide_id: int, body: IdeasAsk, user: identity.User = Depends(identity.current_user)
    ):
        """The Artist's ideas for a slide of a deck (the editor's Ask the Artist): {slide, ideas: [design]}; the one the
        person chooses is applied with POST /edits {op: "tool", tool: "redesign_slide", args: {slide_id, design}}."""
        from .agent import artist

        found(projects.get, pid, user.email, ("owner", "editor"))
        return await afound(artist.ideas_for_deck_slide(generations.app, pid, did, slide_id, user.email, body.wish))

    @r.post("/projects/{pid}/generations/{gid}/build")
    async def build_generation(pid: str, gid: str, request: Request, user: identity.User = Depends(identity.current_user)):
        try:
            record = await afound(generations.build(pid, gid, user.email))
        except ValueError as e:
            raise generation_error(e) from None
        request.state.audit = {"gid": gid, "did": record["deck_id"]}
        deck = found(decks.get, pid, record["deck_id"], user.email)
        renderer.warm(pid, layout.version_file(pid, deck["id"], deck["current_version"]).read_bytes())
        return record

    @r.get("/projects/{pid}/kb/documents")
    async def kb_documents(
        pid: str, q: str = Query(min_length=2, max_length=300), user: identity.User = Depends(identity.current_user)
    ):
        """Knowledge-base documents for a query (the form's "a knowledge-base document"): the documents the best
        passages come from, once each, in the order found."""
        project = found(projects.get, pid, user.email)
        if kb is None or not kb.available:
            return {"available": False, "documents": []}
        try:
            r_ = await asyncio.to_thread(kb.search, user.email, q, project["settings"].get("kb_domains") or None, 20)
        except KBError as e:
            return {"available": False, "documents": [], "error": str(e)}
        seen, docs = set(), []
        for p in r_.get("passages") or []:
            key = (p.get("domain"), p.get("document"))
            if p.get("domain") and p.get("document") and key not in seen:
                seen.add(key)
                docs.append({"domain": p["domain"], "path": p["document"], "title": p.get("title") or p["document"]})
        return {"available": True, "documents": docs}

    # ── templates and assets ─────────────────────────────────────────
    @r.get("/templates")
    async def list_templates(project: str | None = None, user: identity.User = Depends(identity.current_user)):
        if project:
            found(projects.get, project, user.email)
        return {"templates": templates.listing(project), "default": templates.admin.default_id}

    # ── administration (spec AD-4, AD-5, AD-6): administrators only, as Cortex's _admin ──
    def admin(user: identity.User = Depends(identity.current_user)) -> identity.User:
        """A dependency: it runs before the request's body is read, so anyone else is refused before anything else."""
        if not user.is_admin:
            raise HTTPException(403, "administrators only")
        return user

    template_changes = asyncio.Lock()  # one change to templates.json at a time

    @r.get("/admin/templates")
    async def admin_templates(user: identity.User = Depends(admin)):
        return {"templates": list(templates.admin.items.values()), "default": templates.admin.default_id}

    @r.post("/admin/templates", status_code=201)
    async def admin_add_template(
        request: Request,
        name: str = Form(..., min_length=1, max_length=120),
        description: str = Form("", max_length=500),
        file: UploadFile = File(...),
        user: identity.User = Depends(admin),
    ):
        data = await read_upload(file)
        try:
            async with template_changes:
                t = await asyncio.to_thread(templates.admin.add, name.strip(), data, description.strip())
        except files.Rejected as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
        request.state.audit = {"tid": t["id"]}
        return t

    @r.patch("/admin/templates/{tid}")
    async def admin_change_template(tid: str, body: TemplateChanges, user: identity.User = Depends(admin)):
        try:
            async with template_changes:
                return await asyncio.to_thread(found, templates.admin.change, tid, **body.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(400, {"code": "template", "message": str(e)}) from None

    @r.get("/audit")
    async def audit_list(user_filter: str = Query("", alias="user"), q: str = "", since: str = "", until: str = "",
                         limit: int = 100, before: int | None = None,
                         user: identity.User = Depends(admin)):  # fmt: skip
        limit = max(1, min(500, limit))
        return await asyncio.to_thread(audit.search, layout.audit, user_filter, q, since, until, before, limit)

    @r.get("/audit.csv")
    async def audit_csv(user_filter: str = Query("", alias="user"), q: str = "", since: str = "", until: str = "",
                        user: identity.User = Depends(admin)):  # fmt: skip
        rows = (await asyncio.to_thread(audit.search, layout.audit, user_filter, q, since, until, None, 50_000))["entries"]
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["when (UTC)", "user", "what", "action", "which data"])
        for e in rows:
            target = json.dumps(e.get("target", {}), ensure_ascii=False, sort_keys=True)
            w.writerow([e.get("at", ""), e.get("user", ""), e.get("label", ""), e.get("action", ""), target])
        disposition = 'attachment; filename="slides-audit.csv"'
        return Response(out.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": disposition})

    @r.get("/usage")
    async def usage(since: str = "", until: str = "", by: Literal["day", "week", "month"] = "week",
                    user: identity.User = Depends(admin)):  # fmt: skip
        return {"by": by, "periods": await asyncio.to_thread(audit.usage, layout.audit, since, until, by)}

    @r.get("/projects/{pid}/assets")
    async def list_assets(pid: str, user: identity.User = Depends(identity.current_user)):
        found(projects.get, pid, user.email)
        return {"assets": assets.list(pid)}

    @r.post("/projects/{pid}/assets", status_code=201)
    async def upload_asset(
        pid: str,
        request: Request,
        kind: str = Form(...),
        file: UploadFile = File(...),
        user: identity.User = Depends(identity.current_user),
    ):
        found(projects.get, pid, user.email, roles=("owner", "editor"))
        if kind not in ("template", "image", "document"):
            raise HTTPException(400, {"code": "kind", "message": "Templates, images and documents can be uploaded."})
        data = await read_upload(file)
        try:
            if kind == "template":
                asset = await assets.add_template(pid, user.email, (file.filename or "template")[-200:], data, max_bytes)
            elif kind == "document":
                asset = await assets.add_document(pid, user.email, (file.filename or "document")[-200:], data, max_bytes)
            else:
                asset = await assets.add_image(pid, user.email, (file.filename or "image")[-200:], data, max_bytes)
        except files.Rejected as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
        request.state.audit = {"aid": asset["id"]}
        return asset

    @r.get("/projects/{pid}/assets/{aid}/file")
    async def asset_file(pid: str, aid: str, user: identity.User = Depends(identity.current_user)):
        """An asset's stored file (an image, a document, a template), to the project's members."""
        found(projects.get, pid, user.email)
        asset = found(assets.get, pid, aid)
        docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        types = {"png": "image/png", "jpg": "image/jpeg", "pdf": "application/pdf", "docx": docx,
                 "md": "text/markdown; charset=utf-8", "txt": "text/plain; charset=utf-8"}  # fmt: skip
        ext = asset["file"].rsplit(".", 1)[-1]
        return FileResponse(
            layout.assets(pid) / asset["file"],
            media_type=types.get(ext, "application/octet-stream"),
            filename=asset["name"],
            headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
        )

    @r.delete("/projects/{pid}/assets/{aid}", status_code=204)
    async def delete_asset(pid: str, aid: str, user: identity.User = Depends(identity.current_user)):
        found(projects.get, pid, user.email, roles=("owner", "editor"))
        await afound(assets.remove(pid, aid))
        return Response(status_code=204)

    # ── decks ────────────────────────────────────────────────────────
    @r.get("/projects/{pid}/decks")
    async def list_decks(pid: str, user: identity.User = Depends(identity.current_user)):
        return {"decks": found(decks.list, pid, user.email)}

    @r.post("/projects/{pid}/decks", status_code=201)
    async def add_deck(pid: str, request: Request, user: identity.User = Depends(identity.current_user)):
        """Either a multipart upload (field "file") or JSON {title, template} for a new deck from a template."""
        kind = request.headers.get("content-type", "")
        try:
            if kind.startswith("multipart/form-data"):
                form = await request.form()
                upload = form.get("file")
                if upload is None or not hasattr(upload, "read"):
                    raise HTTPException(400, {"code": "file", "message": 'Send the presentation in the field "file".'})
                data = await read_upload(upload)
                deck = await afound(decks.upload(pid, user.email, upload.filename or "Presentation.pptx", data, max_bytes))
            else:
                body = NewDeck.model_validate(await request.json())
                if body.template.kind not in ("admin", "asset"):
                    raise HTTPException(400, {"code": "template", "message": "Unknown template kind."})
                if body.template.kind == "admin" and templates.admin.items.get(body.template.id, {}).get("retired"):
                    raise HTTPException(400, {"code": "template", "message": "This template has been retired."})
                deck = await afound(decks.from_template(pid, user.email, body.title, body.template.model_dump()))
        except files.Rejected as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
        request.state.audit = {"did": deck["id"]}
        renderer.warm(pid, layout.version_file(pid, deck["id"], deck["current_version"]).read_bytes())
        return deck

    @r.get("/projects/{pid}/decks/{did}")
    async def get_deck(pid: str, did: str, version: int | None = None, user: identity.User = Depends(identity.current_user)):
        """The deck's record and the slides of a version (the current one by default), each with its render key."""
        info = await asyncio.to_thread(found, decks.slides, pid, did, user.email, version)
        info["record"] = found(decks.get, pid, did, user.email)
        info["lease"] = decks.leases.holder(did) if decks.leases is not None else None
        return info

    @r.patch("/projects/{pid}/decks/{did}")
    async def rename_deck(pid: str, did: str, body: DeckChanges, user: identity.User = Depends(identity.current_user)):
        return await afound(decks.rename(pid, did, user.email, body.title))

    @r.delete("/projects/{pid}/decks/{did}", status_code=204)
    async def delete_deck(pid: str, did: str, user: identity.User = Depends(identity.current_user)):
        await afound(decks.delete(pid, did, user.email))
        return Response(status_code=204)

    # ── the edit lease (spec PJ-13): the open editor takes and renews it, and releases it on closing ──
    @r.post("/projects/{pid}/decks/{did}/lease")
    async def take_lease(pid: str, did: str, user: identity.User = Depends(identity.current_user)):
        found(decks.get, pid, did, user.email)
        found(projects.get, pid, user.email, roles=("owner", "editor"))
        try:
            return decks.leases.take(did, user.email)
        except Leased as e:
            raise leased(e) from None

    @r.delete("/projects/{pid}/decks/{did}/lease", status_code=204)
    async def release_lease(pid: str, did: str, user: identity.User = Depends(identity.current_user)):
        found(decks.get, pid, did, user.email)
        decks.leases.release(did, user.email)
        return Response(status_code=204)

    @r.get("/projects/{pid}/decks/{did}/versions")
    async def versions(pid: str, did: str, user: identity.User = Depends(identity.current_user)):
        deck = found(decks.get, pid, did, user.email)
        return {"current_version": deck["current_version"], "versions": list(reversed(deck["versions"]))}

    @r.post("/projects/{pid}/decks/{did}/versions/{number}/restore")
    async def restore(pid: str, did: str, number: int, user: identity.User = Depends(identity.current_user)):
        deck = await afound(decks.restore(pid, did, user.email, number))
        renderer.warm(pid, layout.version_file(pid, did, deck["current_version"]).read_bytes())
        return deck

    @r.get("/projects/{pid}/decks/{did}/download")
    async def download(pid: str, did: str, version: int | None = None, user: identity.User = Depends(identity.current_user)):
        deck = found(decks.get, pid, did, user.email)
        n = deck["current_version"] if version is None else version
        if not any(v["number"] == n for v in deck["versions"]):
            raise HTTPException(404, "not found")
        name = f"{deck['title']}.pptx" if n == deck["current_version"] else f"{deck['title']} (v{n}).pptx"
        return FileResponse(layout.version_file(pid, did, n), media_type=PPTX, filename=name)

    @r.get("/projects/{pid}/decks/{did}/pdf")
    async def pdf(pid: str, did: str, version: int | None = None, user: identity.User = Depends(identity.current_user)):
        """A version as PDF (spec PM-5), rendered by LibreOffice as the previews are; kept by the version's content,
        so a second download is immediate."""
        deck = found(decks.get, pid, did, user.email)
        n = deck["current_version"] if version is None else version
        if not any(v["number"] == n for v in deck["versions"]):
            raise HTTPException(404, "not found")
        data = layout.version_file(pid, did, n).read_bytes()
        cached = layout.renders(pid) / "pdf" / f"{hashlib.sha256(data).hexdigest()}.pdf"
        if not cached.exists():
            count = len(read.outline(read.open_deck(data)))
            async with render._gate:
                try:
                    out = await asyncio.to_thread(render._convert, data, count)
                except render.RenderError as e:
                    log.error("a PDF could not be made", extra={"reason": str(e)[:300]})
                    raise HTTPException(502, {"code": "render", "message": "The PDF could not be made."}) from None
            cached.parent.mkdir(parents=True, exist_ok=True)
            storage.write_bytes(cached, out)
        name = f"{deck['title']}.pdf" if n == deck["current_version"] else f"{deck['title']} (v{n}).pdf"
        return FileResponse(cached, media_type="application/pdf", filename=name)

    @r.get("/projects/{pid}/decks/{did}/slides/{slide_id}")
    async def get_slide(
        pid: str, did: str, slide_id: int, version: int | None = None, user: identity.User = Depends(identity.current_user)
    ):
        """A slide as the assistant sees it (contracts/slide.schema.json): the stage draws its selection boxes from it."""
        _, data = await asyncio.to_thread(found, decks.version_bytes, pid, did, user.email, version)
        try:
            return await asyncio.to_thread(lambda: read.slide(read.open_deck(data), slide_id))
        except KeyError:
            raise HTTPException(404, "not found") from None

    @r.get("/projects/{pid}/decks/{did}/slides/{slide_id}/image")
    async def slide_image(
        pid: str,
        did: str,
        slide_id: int,
        size: str = "thumb",
        version: int | None = None,
        user: identity.User = Depends(identity.current_user),
    ):
        if size not in ("thumb", "preview"):
            raise HTTPException(400, "size is thumb or preview")
        _, data = await asyncio.to_thread(found, decks.version_bytes, pid, did, user.email, version)
        try:
            path, key = await renderer.image(pid, data, slide_id, size)
        except NotFound:
            raise HTTPException(404, "not found") from None
        except render.RenderError as e:
            log.error("a slide could not be rendered", extra={"reason": str(e)[:300]})
            raise HTTPException(502, "the slide could not be rendered") from None
        # a version never changes, so its slide's image at a versioned address never does; without a version the
        # address follows the current version and must be checked each time (the ETag is what decides the pixels)
        cache = "private, max-age=31536000, immutable" if version is not None else "private, no-cache"
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": cache, "ETag": f'"{key}-{size}"'})

    # ── undo, redo (spec NL-10; technical design section 5.2) ─────────
    async def _history(pid: str, did: str, email: str, redo: bool):
        try:
            deck = await decks.undo(pid, did, email, 1, redo=redo)
        except NotFound:
            raise HTTPException(404, "not found") from None
        except Leased as e:
            raise leased(e) from None
        except ValueError as e:
            raise HTTPException(409, {"code": "nothing", "message": "Nothing to redo." if redo else "Nothing to undo."}) from e
        renderer.warm(pid, layout.version_file(pid, did, deck["current_version"]).read_bytes())
        return deck

    @r.post("/projects/{pid}/decks/{did}/edits")
    async def manual_edit(
        pid: str, did: str, body: ManualEdit, request: Request, user: identity.User = Depends(identity.current_user)
    ):
        """One edit by hand: applied with the assistant's own operations, published as a version (source "manual") that
        undo can take back."""
        if body.op != "tool" and body.slide_id is None:
            raise HTTPException(422, {"code": "bad", "message": "This edit needs slide_id."})
        if body.op == "text":
            if body.shape_id is None or body.paragraphs is None or any(len(p) > 5000 for p in body.paragraphs):
                raise HTTPException(422, {"code": "bad", "message": "A text edit needs shape_id and paragraphs."})
            name, args = "set_texts", {"slide_id": body.slide_id, "shape_id": body.shape_id, "texts": body.paragraphs}
        elif body.op == "move":
            if body.position is None:
                raise HTTPException(422, {"code": "bad", "message": "A move needs position."})
            name, args = "move_slide", {"slide_id": body.slide_id, "position": body.position}
        elif body.op == "delete":
            name, args = "delete_slide", {"slide_id": body.slide_id}
        record, data = await asyncio.to_thread(found, decks.version_bytes, pid, did, user.email, None)
        if record["current_version"] != body.base_version:
            raise HTTPException(409, {"code": "moved_on", "message": "The deck has changed since: reload it."})
        template_ref = None
        if body.op == "tool":
            name, args = body.tool or "", await asyncio.to_thread(manual_tool_args, pid, did, user.email, body, data)
            template_ref = args.pop("template_ref", None)
        try:
            new, result = await asyncio.to_thread(ops.apply, data, name, args)
        except ops.OpError as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
        try:
            deck = await afound(decks.publish(pid, did, user.email, new, "manual", base_version=body.base_version))
        except ValueError:
            raise HTTPException(409, {"code": "moved_on", "message": "The deck has changed since: reload it."}) from None
        if template_ref:  # the deck's template is now the one it was changed to (PM-10), as an accepted proposal does
            await decks.set_template(pid, did, user.email, template_ref)
        request.state.audit = {"version": deck["current_version"], "op": body.tool if body.op == "tool" else body.op}
        renderer.warm(pid, layout.version_file(pid, did, deck["current_version"]).read_bytes())
        keys = ("slides", "new_slide_ids", "left_out", "continued", "instead_of", "layout", "shape_id", "unmatched", "covers",
                "moved_to_notes")
        said = {k: result[k] for k in keys if isinstance(result, dict) and k in result}
        return {**deck, "result": said}

    def manual_tool_args(pid: str, did: str, email: str, body: ManualEdit, data: bytes) -> dict:
        """A control's tool call: an editing tool, its arguments checked against the tool's schema and resolved as the
        assistant's are (an asset's image, a template's file, the deck slides are copied from)."""
        from .agent.tools import ToolError, Turn

        if body.tool not in MANUAL_TOOLS or agent is None:
            raise HTTPException(422, {"code": "bad", "message": f"{body.tool!r} is not an edit the editor makes."})
        executor = agent.executor
        t = Turn(pid=pid, cid="", email=email, conversation={})
        if body.tool == "redesign_slide":  # the design the person chose among the Artist's ideas, checked again
            from .agent import artist
            from .docengine import layouts

            sid = (body.args or {}).get("slide_id")
            prs = read.open_deck(data)
            s = prs.slides.get(int(sid)) if isinstance(sid, int) else None
            if s is None or not isinstance((body.args or {}).get("design"), dict):
                raise HTTPException(422, {"code": "bad", "message": "A redesign needs slide_id and design."})
            slide = artist.slide_of(read.slide(prs, int(sid)), layouts.heading(s.slide_layout, prs.slide_width, prs.slide_height))
            return {"slide_id": int(sid), "design": artist.checked(body.args["design"], slide)}
        try:
            args = executor.parse(body.tool, body.args or {})
            args.pop("deck_id", None)  # this deck: the route's
            if body.tool == "add_slide" and not args.get("layout"):
                if not isinstance(args.get("content"), dict):
                    raise ToolError("BAD_ARGUMENTS", "A new slide needs a layout or its content.", "")
                prs = read.open_deck(data)
                first = not len(prs.slides) or args.get("position") == 0
                args["layout"] = ops.layout_for_new(prs, args["content"], first).name
            if body.tool == "copy_slides":
                args = executor._copy_source(t, did, args)
            return executor.resolve(t)(body.tool, args)
        except ToolError as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None

    @r.get("/projects/{pid}/decks/{did}/layouts")
    async def deck_layouts(pid: str, did: str, user: identity.User = Depends(identity.current_user)):
        """The layouts of the deck's current version, for the editor's Add slide and Change layout: each name, and
        whether a list of points, a subtitle or a chart has a place on it."""
        from .docengine import layouts as lay

        _, data = await asyncio.to_thread(found, decks.version_bytes, pid, did, user.email, None)

        def listed():
            prs = read.open_deck(data)
            out = []
            for x in prs.slide_layouts:
                where = lay.slots(x, prs.slide_width, prs.slide_height)
                roles = {p["role"] for p in lay.placeholders(x, prs.slide_width, prs.slide_height)}
                out.append({"name": x.name, "heading": where["heading"] is not None, "subtitle": where["subtitle"] is not None,
                            "points": len(where["items"]), "chart": "chart" in roles, "table": "table" in roles,
                            "picture": "picture" in roles})  # fmt: skip
            return out

        return {"layouts": await asyncio.to_thread(listed)}

    @r.post("/projects/{pid}/decks/{did}/undo")
    async def undo(pid: str, did: str, user: identity.User = Depends(identity.current_user)):
        return await _history(pid, did, user.email, redo=False)

    @r.post("/projects/{pid}/decks/{did}/redo")
    async def redo(pid: str, did: str, user: identity.User = Depends(identity.current_user)):
        return await _history(pid, did, user.email, redo=True)

    if conversations is None:
        return r

    # ── conversations (spec PJ-4) ────────────────────────────────────
    @r.get("/projects/{pid}/conversations")
    async def list_conversations(pid: str, user: identity.User = Depends(identity.current_user)):
        return {"conversations": found(conversations.list, pid, user.email)}

    @r.post("/projects/{pid}/conversations", status_code=201)
    async def new_conversation(
        pid: str, body: NewConversation, request: Request, user: identity.User = Depends(identity.current_user)
    ):
        if body.deck_id:
            found(decks.get, pid, body.deck_id, user.email)
        c = await afound(conversations.create(pid, user.email, body.title, body.deck_id))
        request.state.audit = {"cid": c["id"]}
        return c

    @r.get("/projects/{pid}/conversations/{cid}")
    async def get_conversation(pid: str, cid: str, after: int = 0, user: identity.User = Depends(identity.current_user)):
        c = found(conversations.get, pid, cid, user.email)
        open_p = proposals.open_in(pid, cid)
        return {
            "conversation": c,
            "messages": conversations.messages(pid, cid, after),
            "proposal": agent.describe(pid, open_p) if open_p and open_p["status"] == "pending" else None,
            "busy": agent.busy(cid),
        }

    @r.patch("/projects/{pid}/conversations/{cid}")
    async def rename_conversation(
        pid: str, cid: str, body: NewConversation, user: identity.User = Depends(identity.current_user)
    ):
        return await afound(conversations.rename(pid, cid, user.email, body.title))

    @r.delete("/projects/{pid}/conversations/{cid}", status_code=204)
    async def delete_conversation(pid: str, cid: str, user: identity.User = Depends(identity.current_user)):
        await afound(conversations.delete(pid, cid, user.email))
        return Response(status_code=204)

    # ── proposals (spec NL-9) ────────────────────────────────────────
    @r.get("/projects/{pid}/conversations/{cid}/proposals/{prid}")
    async def get_proposal(pid: str, cid: str, prid: str, user: identity.User = Depends(identity.current_user)):
        found(conversations.get, pid, cid, user.email)
        return agent.describe(pid, found(proposals.get, pid, cid, prid))

    @r.post("/projects/{pid}/conversations/{cid}/proposals/{prid}/decision")
    async def decide(
        pid: str, cid: str, prid: str, body: Decision, request: Request, user: identity.User = Depends(identity.current_user)
    ):
        found(conversations.get, pid, cid, user.email)
        try:
            p = await agent.decide(pid, cid, prid, user.email, body.accept, body.slides)
        except NotFound:
            raise HTTPException(404, "not found") from None
        except ValueError as e:
            raise HTTPException(409, {"code": "decided", "message": str(e)}) from None
        request.state.audit = {"status": p["status"]}  # spec AD-5: accepted and rejected are counted from the audit
        return {"id": p["id"], "status": p["status"]}

    @r.get("/projects/{pid}/conversations/{cid}/proposals/{prid}/decks/{did}/slides/{slide_id}/image")
    async def draft_image(
        pid: str,
        cid: str,
        prid: str,
        did: str,
        slide_id: int,
        size: str = "thumb",
        user: identity.User = Depends(identity.current_user),
    ):
        """A slide of a proposal's draft (the "after" of the diff view)."""
        if size not in ("thumb", "preview"):
            raise HTTPException(400, "size is thumb or preview")
        found(conversations.get, pid, cid, user.email)
        p = found(proposals.get, pid, cid, prid)
        draft = proposals.draft_path(pid, p, did)
        if did not in p["decks"] or not draft.exists():
            raise HTTPException(404, "not found")
        try:
            path, key = await renderer.image(pid, draft.read_bytes(), slide_id, size)
        except NotFound:
            raise HTTPException(404, "not found") from None
        except render.RenderError:
            raise HTTPException(502, "the slide could not be rendered") from None
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=31536000, immutable", "ETag": f'"{key}-{size}"'},
        )

    return r
