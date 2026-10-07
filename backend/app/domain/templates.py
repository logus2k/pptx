"""Templates (spec AD-3, PM-9; technical design section 1.2). Administrator templates are files in TEMPLATES_DIR listed
in templates.json, read and checked at start-up. A project's own templates are its assets of kind "template". A deck
records which one it was made from."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from .. import storage
from ..docengine import files, fonts, svg
from ..storage import Layout, NotFound

log = logging.getLogger("slides.templates")


class TemplateError(Exception):
    pass


class AdminTemplates:
    """templates.json: {schema_version, templates: [{id, file, name: {pt, en}, description: {pt, en}, default}]}."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.items: dict[str, dict] = {}
        self.data: dict[str, bytes] = {}
        listing = json.loads((folder / "templates.json").read_text(encoding="utf-8"))
        for t in listing["templates"]:
            raw = (folder / t["file"]).read_bytes()
            checked = files.check(raw, max_bytes=200 * 1024 * 1024)  # opens, no macros: or start-up fails
            self.data[t["id"]] = checked.data
            self.items[t["id"]] = {
                "kind": "admin",
                "id": t["id"],
                "name": t["name"],
                "description": t.get("description", {}),
                "default": bool(t.get("default")),
                "layouts": files.layouts(checked.data),
            }
        defaults = [t for t in self.items.values() if t["default"]]
        if len(defaults) != 1:
            raise TemplateError(f"templates.json must mark exactly one template as the default ({len(defaults)} found)")
        self.default_id = defaults[0]["id"]
        log.info("administrator templates loaded", extra={"templateCount": len(self.items)})


class ProjectAssets:
    """A project's assets (assets/assets.json and the files beside it). M1: templates."""

    def __init__(self, layout: Layout) -> None:
        self.layout = layout

    def _index(self, pid: str) -> Path:
        return self.layout.assets(pid) / "assets.json"

    def list(self, pid: str) -> list[dict]:
        try:
            return storage.read_json(self._index(pid))["assets"]
        except NotFound:
            return []

    def get(self, pid: str, aid: str) -> dict:
        for a in self.list(pid):
            if a["id"] == aid:
                return a
        raise NotFound("asset")

    def read(self, pid: str, aid: str) -> bytes:
        return (self.layout.assets(pid) / self.get(pid, aid)["file"]).read_bytes()

    async def add_template(self, pid: str, email: str, name: str, raw: bytes, max_bytes: int) -> dict:
        """A template the person uploads (PM-9): checked like a deck, plus at least one master and layout; the fonts
        it names that the server lacks are listed, so the person is told previews substitute them (A-5)."""
        checked = files.check(raw, max_bytes=max_bytes)
        layouts = files.layouts(checked.data)
        if not layouts:
            raise files.Rejected("no_layouts", "This file has no slide layouts to use as a template.")
        aid = storage.new_id()
        asset = {
            "id": aid,
            "kind": "template",
            "file": f"{aid}.pptx",
            "name": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            "created_by": email,
            "created_at": storage.now(),
            "layouts": layouts,
            "missing_fonts": fonts.missing(files.fonts(checked.data)),
        }
        async with storage.lock(pid):
            storage.write_bytes(self.layout.assets(pid) / asset["file"], checked.data)
            index = {"schema_version": 1, "assets": [*self.list(pid), asset]}
            storage.write_json(self._index(pid), index, "assets")
        return asset

    async def add_image(self, pid: str, email: str, name: str, raw: bytes, max_bytes: int) -> dict:
        """An image the person attaches (spec IM-1): PNG and JPEG kept as they are, SVG, WebP and other bitmaps
        converted to PNG; it must open as an image."""
        import io as _io

        from PIL import Image

        if len(raw) > max_bytes:
            raise files.Rejected("too_large", f"The image is larger than {max_bytes // (1024 * 1024)} MB.")
        if svg.is_svg(raw):  # converted to PNG first (IM-1), after checking it names nothing outside itself
            try:
                raw = await asyncio.to_thread(svg.to_png, raw)
            except svg.SvgRefused as e:
                raise files.Rejected("svg", str(e)) from None
            name = (name.rsplit(".", 1)[0] if "." in name else name) + ".png"
        try:
            img = Image.open(_io.BytesIO(raw))
            img.load()
        except Exception:  # noqa: BLE001 - Pillow raises many kinds for what is not an image
            raise files.Rejected("not_image", "This file is not an image (PNG, JPEG or WebP).") from None
        if img.width * img.height > 60_000_000:
            raise files.Rejected("too_large", "The image has too many pixels.")
        if img.format in ("PNG", "JPEG"):
            data, ext = raw, "png" if img.format == "PNG" else "jpg"
        else:
            out = _io.BytesIO()
            img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB").save(out, "PNG")
            data, ext = out.getvalue(), "png"
        aid = storage.new_id()
        asset = {
            "id": aid,
            "kind": "image",
            "file": f"{aid}.{ext}",
            "name": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "created_by": email,
            "created_at": storage.now(),
        }
        async with storage.lock(pid):
            storage.write_bytes(self.layout.assets(pid) / asset["file"], data)
            index = {"schema_version": 1, "assets": [*self.list(pid), asset]}
            storage.write_json(self._index(pid), index, "assets")
        return asset

    async def add_document(self, pid: str, email: str, name: str, raw: bytes, max_bytes: int) -> dict:
        """A reference document (spec PJ-11: PDF, DOCX, TXT, MD), its text extracted now into passages kept beside it
        (<id>.passages.json, read only by search: assets.json stays small)."""
        from .. import documents

        if len(raw) > max_bytes:
            raise files.Rejected("too_large", f"The document is larger than {max_bytes // (1024 * 1024)} MB.")
        try:
            kind = documents.kind_of(name, raw)
            passages = documents.passages(kind, raw)
        except documents.Unreadable as e:
            raise files.Rejected("not_document", str(e)) from None
        if not passages:
            raise files.Rejected("no_text", "No text could be read from this document (a scan without text?).")
        aid = storage.new_id()
        asset = {
            "id": aid,
            "kind": "document",
            "file": f"{aid}.{kind}",
            "name": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            "created_by": email,
            "created_at": storage.now(),
            "passages": len(passages),
        }
        async with storage.lock(pid):
            storage.write_bytes(self.layout.assets(pid) / asset["file"], raw)
            storage.write_json(
                self.layout.assets(pid) / f"{aid}.passages.json", {"schema_version": 1, "passages": passages}, "passages"
            )
            index = {"schema_version": 1, "assets": [*self.list(pid), asset]}
            storage.write_json(self._index(pid), index, "assets")
        return asset

    def passages(self, pid: str, aid: str) -> list[dict]:
        """A reference document's passages ([{where, text}])."""
        try:
            return storage.read_json(self.layout.assets(pid) / f"{aid}.passages.json")["passages"]
        except NotFound:
            return []

    async def remove(self, pid: str, aid: str) -> None:
        async with storage.lock(pid):
            asset = self.get(pid, aid)
            index = {"schema_version": 1, "assets": [a for a in self.list(pid) if a["id"] != aid]}
            storage.write_json(self._index(pid), index, "assets")
            (self.layout.assets(pid) / asset["file"]).unlink(missing_ok=True)
            (self.layout.assets(pid) / f"{aid}.passages.json").unlink(missing_ok=True)


class Templates:
    def __init__(self, admin: AdminTemplates, assets: ProjectAssets) -> None:
        self.admin = admin
        self.assets = assets

    def listing(self, pid: str | None) -> list[dict]:
        out = list(self.admin.items.values())
        if pid:
            out += [
                {
                    "kind": "asset",
                    "id": a["id"],
                    "name": {"pt": a["name"], "en": a["name"]},
                    "description": {},
                    "default": False,
                    "layouts": a.get("layouts", []),
                    "missing_fonts": a.get("missing_fonts", []),
                }
                for a in self.assets.list(pid)
                if a["kind"] == "template"
            ]
        return out

    def bytes_of(self, pid: str, ref: dict) -> bytes:
        if ref["kind"] == "admin":
            if ref["id"] not in self.admin.data:
                raise NotFound("template")
            return self.admin.data[ref["id"]]
        asset = self.assets.get(pid, ref["id"])
        if asset["kind"] != "template":
            raise NotFound("template")
        return self.assets.read(pid, ref["id"])
