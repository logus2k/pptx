"""Proposals (spec NL-8, NL-9; technical design section 5.1). A proposal is created by the first editing tool call of
a turn; for each deck it touches, its draft starts as a copy of the current version. Each validated operation is
applied to the draft and recorded with the tool's own arguments (images by asset ID), so it can be replayed.

On accept: if the deck is still at the base version and every slide is accepted, the draft becomes the next version.
Otherwise the accepted operations are replayed on the current version (an operation touching several slides is
accepted or rejected as a unit); slides created along the way get new IDs on replay, and later operations are
re-pointed to them. If an operation no longer applies, the proposal is stale. Drafts are deleted once it is settled."""

from __future__ import annotations

import shutil

from .. import storage
from ..docengine import ops
from ..storage import Layout, NotFound

FINAL = ("accepted", "partially_accepted", "rejected", "superseded", "stale", "failed")
# operations whose result holds slides that did not exist before (their IDs change on replay)
CREATING = ("add_slide", "duplicate_slide", "change_layout")


class Stale(Exception):
    pass


class Proposals:
    def __init__(self, layout: Layout) -> None:
        self.layout = layout

    def _dir(self, pid: str, cid: str, prid: str):
        if not storage.is_id(prid):
            raise NotFound("proposal")
        return self.layout.project(pid) / "conversations" / cid / "proposals" / prid

    def get(self, pid: str, cid: str, prid: str) -> dict:
        return storage.read_json(self._dir(pid, cid, prid) / "proposal.json")

    def write(self, pid: str, p: dict) -> None:
        storage.write_json(self._dir(pid, p["conversation_id"], p["id"]) / "proposal.json", p, "proposal")

    def draft_path(self, pid: str, p: dict, did: str):
        return self._dir(pid, p["conversation_id"], p["id"]) / "drafts" / f"{did}.pptx"

    def open_in(self, pid: str, cid: str) -> dict | None:
        """The conversation's proposal still drafting or waiting for a decision, if any (at most one)."""
        folder = self.layout.project(pid) / "conversations" / cid / "proposals"
        if not folder.exists():
            return None
        for d in folder.iterdir():
            if storage.is_id(d.name):
                try:
                    p = storage.read_json(d / "proposal.json")
                except NotFound:
                    continue
                if p["status"] in ("drafting", "pending"):
                    return p
        return None

    def start(self, pid: str, cid: str) -> dict:
        p = {
            "schema_version": 1,
            "id": storage.new_id(),
            "conversation_id": cid,
            "status": "drafting",
            "created_at": storage.now(),
            "decks": {},
        }
        self.write(pid, p)
        return p

    def draft(self, pid: str, p: dict, did: str, current_version: int, current_bytes: bytes) -> bytes:
        """The deck's draft bytes in this proposal, started from the current version when first touched."""
        if did not in p["decks"]:
            storage.write_bytes(self.draft_path(pid, p, did), current_bytes)
            p["decks"][did] = {"base_version": current_version, "operations": []}
            self.write(pid, p)
        return self.draft_path(pid, p, did).read_bytes()

    def record(
        self, pid: str, p: dict, did: str, name: str, args: dict, result: dict, new_bytes: bytes, removed: list[int] | None = None
    ) -> None:
        storage.write_bytes(self.draft_path(pid, p, did), new_bytes)
        entry = {"name": name, "args": args, "slides": [int(s) for s in result.get("slides", [])]}
        if removed:
            entry["removed"] = removed
        p["decks"][did]["operations"].append(entry)
        self.write(pid, p)

    def affected(self, p: dict, did: str) -> list[int]:
        """The deck's slides this proposal touches, in the order first touched (removed ones included)."""
        seen: list[int] = []
        for op in p["decks"][did]["operations"]:
            for s in [*op["slides"], *op.get("removed", [])]:
                if s not in seen:
                    seen.append(s)
        return seen

    def drop_drafts(self, pid: str, p: dict) -> None:
        shutil.rmtree(self._dir(pid, p["conversation_id"], p["id"]) / "drafts", ignore_errors=True)

    # ── accepting ────────────────────────────────────────────────────
    @staticmethod
    def replay(current: bytes, operations: list[dict], accepted: set[int], resolve) -> tuple[bytes, int]:
        """Apply the accepted operations to `current`. `resolve(name, args)` turns the recorded arguments into the
        operation's (image bytes for asset IDs). Returns the bytes and how many operations applied. Raises Stale."""
        id_map: dict[int, int] = {}
        data = current
        applied = 0
        for op in operations:
            touched = set(op["slides"]) | set(op.get("removed", []))
            if touched and not touched <= accepted:
                continue
            args = dict(op["args"])
            for key in ("slide_id", "after_slide_id", "before_slide_id"):
                if key in args and int(args[key]) in id_map:
                    args[key] = id_map[int(args[key])]
            try:
                data, result = ops.apply(data, op["name"], resolve(op["name"], args))
            except ops.OpError as e:
                raise Stale(f"{op['name']}: {e}") from e
            if op["name"] in CREATING:
                for old, new in zip(op["slides"], result.get("slides", []), strict=False):
                    id_map[int(old)] = int(new)
            applied += 1
        return data, applied
