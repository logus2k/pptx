"""A project's memory (spec PJ-9; technical design section 4: memory.json): durable facts and decisions ("pricing in
EUR", "the client prefers fewer bullets"), each with the conversation it came from and who kept it. The assistant
keeps one when the person asked it to or after saying so in its reply (system prompt); people see, edit and delete
them on the project page."""

from __future__ import annotations

from .. import storage
from ..storage import Layout, NotFound
from .projects import Projects

WRITE = ("owner", "editor")
MAX_ITEMS = 200


class Memory:
    def __init__(self, layout: Layout, projects: Projects) -> None:
        self.layout = layout
        self.projects = projects

    def _path(self, pid: str):
        return self.layout.project(pid) / "memory.json"

    def _items(self, pid: str) -> list[dict]:
        try:
            return storage.read_json(self._path(pid))["items"]
        except NotFound:
            return []

    def list(self, pid: str, email: str) -> list[dict]:
        self.projects.get(pid, email)
        return self._items(pid)

    async def add(self, pid: str, email: str, text: str, conversation_id: str | None = None) -> dict:
        self.projects.get(pid, email, roles=WRITE)
        text = " ".join(str(text).split())
        if not text:
            raise ValueError("an empty memory item")
        if len(text) > 500:
            raise ValueError("a memory item is a short fact (at most 500 characters)")
        async with storage.lock(pid):
            items = self._items(pid)
            same = next((m for m in items if m["text"].casefold() == text.casefold()), None)
            if same:  # kept once
                return same
            if len(items) >= MAX_ITEMS:
                raise ValueError(f"the project's memory is full ({MAX_ITEMS} items): delete some first")
            now = storage.now()
            item = {
                "id": storage.new_id(),
                "text": text,
                "conversation_id": conversation_id,
                "author": email,
                "created_at": now,
                "updated_at": now,
            }
            storage.write_json(self._path(pid), {"schema_version": 1, "items": [*items, item]}, "memory")
        return item

    async def update(self, pid: str, email: str, mid: str, text: str) -> dict:
        self.projects.get(pid, email, roles=WRITE)
        text = " ".join(str(text).split())
        if not text or len(text) > 500:
            raise ValueError("a memory item is a short fact (1 to 500 characters)")
        async with storage.lock(pid):
            items = self._items(pid)
            item = next((m for m in items if m["id"] == mid), None)
            if item is None:
                raise NotFound("memory item")
            item.update(text=text, updated_at=storage.now())
            storage.write_json(self._path(pid), {"schema_version": 1, "items": items}, "memory")
        return item

    async def delete(self, pid: str, email: str, mid: str) -> None:
        self.projects.get(pid, email, roles=WRITE)
        async with storage.lock(pid):
            items = self._items(pid)
            if not any(m["id"] == mid for m in items):
                raise NotFound("memory item")
            storage.write_json(self._path(pid), {"schema_version": 1, "items": [m for m in items if m["id"] != mid]}, "memory")
