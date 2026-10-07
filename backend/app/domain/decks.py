"""Decks and their versions (spec 3.1, PM-1 to PM-9; technical design sections 4 and 5.2). A deck is a folder with
deck.json and versions/<n>.pptx; a version is never changed once written. A new version is published by writing its
file first and deck.json last, so a reader never sees a version without its file."""

from __future__ import annotations

import hashlib
import shutil

from .. import storage
from ..docengine import files, render
from ..storage import Layout, NotFound
from .projects import Projects
from .templates import Templates

WRITE_ROLES = ("owner", "editor")


def _summary(deck: dict) -> dict:
    current = next(v for v in deck["versions"] if v["number"] == deck["current_version"])
    return {
        "id": deck["id"],
        "project_id": deck["project_id"],
        "title": deck["title"],
        "template": deck["template"],
        "current_version": deck["current_version"],
        "slide_count": current["slide_count"],
        "created_at": deck["created_at"],
        "updated_at": deck["updated_at"],
    }


class Decks:
    def __init__(self, layout: Layout, projects: Projects, templates: Templates) -> None:
        self.layout = layout
        self.projects = projects
        self.templates = templates

    def _json(self, pid: str, did: str):
        return self.layout.deck(pid, did) / "deck.json"

    def _read(self, pid: str, did: str) -> dict:
        return storage.read_json(self._json(pid, did))

    # ── reading ──────────────────────────────────────────────────────
    def list(self, pid: str, email: str) -> list[dict]:
        self.projects.get(pid, email)
        folder = self.layout.project(pid) / "decks"
        out = []
        if folder.exists():
            for d in folder.iterdir():
                if storage.is_id(d.name):
                    try:
                        out.append(_summary(self._read(pid, d.name)))
                    except NotFound:
                        continue
        return sorted(out, key=lambda d: d["updated_at"], reverse=True)

    def get(self, pid: str, did: str, email: str) -> dict:
        self.projects.get(pid, email)
        return self._read(pid, did)

    def version_bytes(self, pid: str, did: str, email: str, number: int | None = None) -> tuple[dict, bytes]:
        deck = self.get(pid, did, email)
        n = deck["current_version"] if number is None else int(number)
        if not any(v["number"] == n for v in deck["versions"]):
            raise NotFound("version")
        return deck, self.layout.version_file(pid, did, n).read_bytes()

    def slides(self, pid: str, did: str, email: str, number: int | None = None) -> dict:
        """The slides of a version, with each one's render key (its images' name in the project's render cache)."""
        deck, data = self.version_bytes(pid, did, email, number)
        info = files.slides(data)
        keys = {k["id"]: k["key"] for k in render.keys(data)}
        for s in info:
            s["key"] = keys[s["id"]]
        return {"deck": _summary(deck), "version": deck["current_version"] if number is None else int(number), "slides": info}

    # ── writing ──────────────────────────────────────────────────────
    async def _publish(
        self, pid: str, deck: dict, data: bytes, source: str, author: str, history: str = "change", **extra
    ) -> dict:
        """Write the next version of `deck` (the project's lock is held by the caller). history: "change" (the
        replaced version goes on the undo stack, the redo stack empties), "undo" or "redo" (section 5.2)."""
        number = max(v["number"] for v in deck["versions"]) + 1 if deck["versions"] else 1
        storage.write_bytes(self.layout.version_file(pid, deck["id"], number), data)
        files.slides(data)  # it reopens: a file that does not is never published
        at = storage.now()
        version = {
            "number": number,
            "source": source,
            "author": author,
            "created_at": at,
            "slide_count": len(files.slides(data)),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            **extra,
        }
        if deck["versions"]:
            if history == "change":
                deck["undo"].append(deck["current_version"])
                deck["redo"] = []
            elif history == "undo":
                deck["redo"].append(deck["current_version"])
            elif history == "redo":
                deck["undo"].append(deck["current_version"])
        deck["versions"].append(version)
        deck["current_version"] = number
        deck["updated_at"] = at
        storage.write_json(self._json(pid, deck["id"]), deck, "deck")
        await self.projects.touch(pid)
        return deck

    async def _new(self, pid: str, email: str, title: str, template: dict | None, data: bytes, source: str, **extra) -> dict:
        did = storage.new_id()
        at = storage.now()
        deck = {
            "schema_version": 1,
            "id": did,
            "project_id": pid,
            "title": title.strip() or "Untitled",
            "template": template,
            "current_version": 1,
            "versions": [],
            "undo": [],
            "redo": [],
            "created_at": at,
            "updated_at": at,
        }
        async with storage.lock(pid):
            self.projects.get(pid, email, roles=WRITE_ROLES)
            await self._publish(pid, deck, data, source, email, **extra)
        return deck

    async def duplicate(self, pid: str, did: str, email: str, title: str = "") -> dict:
        """A new deck, a copy of this one's current version, with its template (spec PJ-2)."""
        source = self.get(pid, did, email)
        _, data = self.version_bytes(pid, did, email)
        return await self._new(pid, email, title or f"{source['title']} (copy)", source.get("template"), data, "duplicate")

    async def upload(self, pid: str, email: str, file_name: str, raw: bytes, max_bytes: int) -> dict:
        """An uploaded .pptx (PM-1): checked by content; a deck of its own masters (no template)."""
        self.projects.get(pid, email, roles=WRITE_ROLES)
        checked = files.check(raw, max_bytes=max_bytes)
        title = file_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if title.lower().endswith((".pptx", ".potx")):
            title = title[:-5]
        return await self._new(pid, email, title, None, checked.data, "upload", file_name=file_name[-200:])

    async def from_template(self, pid: str, email: str, title: str, template: dict) -> dict:
        """A new, empty deck from a template (PM-2, PM-9)."""
        self.projects.get(pid, email, roles=WRITE_ROLES)
        data = files.without_slides(self.templates.bytes_of(pid, template))
        return await self._new(pid, email, title, {"kind": template["kind"], "id": template["id"]}, data, "template")

    async def set_template(self, pid: str, did: str, email: str, ref: dict) -> dict:
        async with storage.lock(pid):
            self.projects.get(pid, email, roles=WRITE_ROLES)
            deck = self._read(pid, did)
            deck["template"] = {"kind": ref["kind"], "id": ref["id"]}
            deck["updated_at"] = storage.now()
            storage.write_json(self._json(pid, did), deck, "deck")
        return deck

    async def rename(self, pid: str, did: str, email: str, title: str) -> dict:
        async with storage.lock(pid):
            self.projects.get(pid, email, roles=WRITE_ROLES)
            deck = self._read(pid, did)
            deck["title"] = title.strip() or deck["title"]
            deck["updated_at"] = storage.now()
            storage.write_json(self._json(pid, did), deck, "deck")
        return deck

    async def delete(self, pid: str, did: str, email: str) -> None:
        async with storage.lock(pid):
            self.projects.get(pid, email, roles=WRITE_ROLES)
            folder = self.layout.deck(pid, did)
            if not folder.exists():
                raise NotFound("deck")
            shutil.rmtree(folder)
            await self.projects.touch(pid)

    async def restore(self, pid: str, did: str, email: str, number: int) -> dict:
        """Restore a version (PM-6): a new version identical to it; history is never rewritten (section 5.2)."""
        async with storage.lock(pid):
            self.projects.get(pid, email, roles=WRITE_ROLES)
            deck = self._read(pid, did)
            if not any(v["number"] == int(number) for v in deck["versions"]):
                raise NotFound("version")
            data = self.layout.version_file(pid, did, int(number)).read_bytes()
            return await self._publish(pid, deck, data, "restore", email, restored_from=int(number))

    async def publish(
        self, pid: str, did: str, email: str, data: bytes, source: str, base_version: int | None = None, **extra
    ) -> dict:
        """A new version from outside the deck's own routes (an accepted proposal). With base_version, refused
        (ValueError) when the deck has moved on since: the caller replays instead."""
        async with storage.lock(pid):
            self.projects.get(pid, email, roles=WRITE_ROLES)
            deck = self._read(pid, did)
            if base_version is not None and deck["current_version"] != base_version:
                raise ValueError("the deck has changed since")
            return await self._publish(pid, deck, data, source, email, **extra)

    async def undo(self, pid: str, did: str, email: str, steps: int = 1, redo: bool = False) -> dict:
        """Undo (or redo) `steps` accepted changes: each step publishes a copy of the version it returns to
        (spec NL-10; section 5.2). NotFound-free: with nothing to undo, ValueError."""
        async with storage.lock(pid):
            self.projects.get(pid, email, roles=WRITE_ROLES)
            deck = self._read(pid, did)
            stack = deck["redo"] if redo else deck["undo"]
            if not stack:
                raise ValueError("nothing to redo" if redo else "nothing to undo")
            for _ in range(max(1, int(steps))):
                if not stack:
                    break
                target = stack.pop()
                data = self.layout.version_file(pid, did, target).read_bytes()
                deck = await self._publish(
                    pid, deck, data, "redo" if redo else "undo", email, history="redo" if redo else "undo", restored_from=target
                )
                stack = deck["redo"] if redo else deck["undo"]
            return deck
