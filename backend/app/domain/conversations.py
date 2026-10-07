"""Conversations (spec PJ-4; technical design section 4): conversation.json and an append-only messages.jsonl,
numbered. A conversation remembers its active deck, its rolling summary, and what its turn is waiting for."""

from __future__ import annotations

import json

from .. import storage
from ..storage import Layout, NotFound
from .projects import Projects


class Conversations:
    def __init__(self, layout: Layout, projects: Projects) -> None:
        self.layout = layout
        self.projects = projects

    def _dir(self, pid: str, cid: str):
        if not storage.is_id(cid):
            raise NotFound("conversation")
        return self.layout.project(pid) / "conversations" / cid

    def _read(self, pid: str, cid: str) -> dict:
        return storage.read_json(self._dir(pid, cid) / "conversation.json")

    def write(self, pid: str, conversation: dict) -> None:
        conversation["updated_at"] = storage.now()
        storage.write_json(self._dir(pid, conversation["id"]) / "conversation.json", conversation, "conversation")

    def list(self, pid: str, email: str) -> list[dict]:
        self.projects.get(pid, email)
        folder = self.layout.project(pid) / "conversations"
        out = []
        if folder.exists():
            for d in folder.iterdir():
                if storage.is_id(d.name):
                    try:
                        c = self._read(pid, d.name)
                    except NotFound:
                        continue
                    out.append({k: c[k] for k in ("id", "title", "created_by", "created_at", "updated_at", "active_deck")})
        return sorted(out, key=lambda c: c["updated_at"], reverse=True)

    def get(self, pid: str, cid: str, email: str) -> dict:
        self.projects.get(pid, email)
        return self._read(pid, cid)

    async def create(self, pid: str, email: str, title: str = "", active_deck: str | None = None) -> dict:
        self.projects.get(pid, email, roles=("owner", "editor"))
        cid = storage.new_id()
        at = storage.now()
        c = {
            "schema_version": 1,
            "id": cid,
            "project_id": pid,
            "title": title.strip(),  # untitled until the first message names it
            "created_by": email,
            "created_at": at,
            "updated_at": at,
            "summary": "",
            "summary_upto": 0,
            "active_deck": active_deck,
            "pending": None,
            "next_seq": 1,
        }
        async with storage.lock(pid):
            self.write(pid, c)
        return c

    async def rename(self, pid: str, cid: str, email: str, title: str) -> dict:
        async with storage.lock(pid):
            self.projects.get(pid, email, roles=("owner", "editor"))
            c = self._read(pid, cid)
            c["title"] = title.strip() or c["title"]
            self.write(pid, c)
        return c

    async def delete(self, pid: str, cid: str, email: str) -> None:
        import shutil

        async with storage.lock(pid):
            self.projects.get(pid, email, roles=("owner", "editor"))
            folder = self._dir(pid, cid)
            if not folder.exists():
                raise NotFound("conversation")
            shutil.rmtree(folder)

    def append(self, pid: str, conversation: dict, message: dict) -> dict:
        """Add a message (the caller holds the project's lock and writes the conversation after)."""
        message = {"seq": conversation["next_seq"], "at": storage.now(), **message}
        conversation["next_seq"] += 1
        storage.append_line(self._dir(pid, conversation["id"]) / "messages.jsonl", message, "message")
        return message

    def messages(self, pid: str, cid: str, after: int = 0) -> list[dict]:
        path = self._dir(pid, cid) / "messages.jsonl"
        if not path.exists():
            return []
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    m = json.loads(line)
                    if m["seq"] > after:
                        out.append(m)
        return out
