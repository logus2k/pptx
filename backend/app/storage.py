"""Files on disk under DATA_DIR (technical design section 4): the only persistence. Every write goes through here:
JSON and .pptx are written to a temporary file in the same folder and moved into place (os.replace), so a crash never
leaves half a file; writes within a project are serialised by its lock; every JSON file is validated against its
schema in contracts/storage/ before it is written. Correct only with one application process (assumption A-3)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path

import jsonschema

from .config import REPO_DIR

_SCHEMAS: dict[str, dict] = {}
_locks: dict[str, asyncio.Lock] = {}


class NotFound(Exception):
    """A project, deck, version or asset that does not exist (or the person may not see: the same answer)."""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id() -> str:
    return secrets.token_hex(8)


def is_id(value: str) -> bool:
    """An id this module made: 16 lowercase hex characters. Checked before an id from a request becomes a path."""
    return len(value) == 16 and all(c in "0123456789abcdef" for c in value)


def lock(project_id: str) -> asyncio.Lock:
    if project_id not in _locks:
        _locks[project_id] = asyncio.Lock()
    return _locks[project_id]


def _schema(name: str) -> dict:
    if name not in _SCHEMAS:
        _SCHEMAS[name] = json.loads((REPO_DIR / "contracts" / "storage" / f"{name}.schema.json").read_text(encoding="utf-8"))
    return _SCHEMAS[name]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def validate(data, schema: str) -> None:
    """Raise jsonschema's ValidationError when `data` is not a valid `schema` record (an archive's files: archive.py)."""
    jsonschema.validate(data, _schema(schema))


def write_json(path: Path, data: dict, schema: str) -> None:
    jsonschema.validate(data, _schema(schema))
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NotFound(str(path.name)) from None


def write_bytes(path: Path, data: bytes) -> None:
    _atomic_write(path, data)


def copy_file(src: Path, dst: Path) -> None:
    """A copy that appears whole or not at all."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=f".{dst.name}.", suffix=".tmp")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def append_line(path: Path, record: dict, schema: str | None = None) -> None:
    """One JSON line appended (audit trails): a single write of a whole line."""
    if schema:
        jsonschema.validate(record, _schema(schema))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class Layout:
    """Where everything lives (technical design section 4)."""

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir

    @property
    def projects(self) -> Path:
        return self.root / "projects"

    @property
    def trash(self) -> Path:
        return self.root / "trash"

    @property
    def audit(self) -> Path:
        return self.root / "audit.jsonl"

    def project_audit(self, pid: str) -> Path:
        """The assistant's work in the project (technical design section 11.2): deleted with the project."""
        return self.project(pid) / "audit.jsonl"

    def project(self, pid: str) -> Path:
        if not is_id(pid):
            raise NotFound("project")
        return self.projects / pid

    def deck(self, pid: str, did: str) -> Path:
        if not is_id(did):
            raise NotFound("deck")
        return self.project(pid) / "decks" / did

    def version_file(self, pid: str, did: str, number: int) -> Path:
        return self.deck(pid, did) / "versions" / f"{int(number)}.pptx"

    def assets(self, pid: str) -> Path:
        return self.project(pid) / "assets"

    def renders(self, pid: str) -> Path:
        return self.project(pid) / "renders"
