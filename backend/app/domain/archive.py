"""A whole project as a ZIP archive, and an archive imported as a new project (spec PJ-14).

The archive holds `data/`, the project's own files as they are stored (every deck version, the conversations'
records, the assets with their passages, memory, instructions, settings: what the round trip needs to lose nothing),
and `readable/`, what the specification names for people: each deck's current version as <title>.pptx, each
conversation as Markdown, the instructions and the memory as JSON. Renders (a cache) and the drafts of pending
proposals are left out.

An archive is the person's file, so nothing in it is trusted: only the paths a project has are read, every record is
checked against its schema as it is written, every deck version passes the upload checks, every picture is opened;
the new project gets a new ID and the person importing it as its only member (the archive's members are not given
access to anything)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import PurePosixPath

from PIL import Image

from .. import storage
from ..docengine import files
from ..storage import Layout

FORMAT = 1
MAX_ENTRIES = 20_000
MAX_TOTAL = 2 << 30  # what it unpacks to, at most (2 GiB), as files.check allows a deck
ASSET_EXT = {"pptx", "potx", "png", "jpg", "jpeg", "gif", "webp", "pdf", "docx", "txt", "md"}


class BadArchive(ValueError):
    pass


def _safe_name(title: str, used: set[str]) -> str:
    keep = "".join(c if c.isalnum() or c in " -_.()" else "_" for c in title).strip(" .") or "deck"
    name, n = keep[:80], 2
    while name.lower() in used:
        name, n = f"{keep[:76]} ({n})", n + 1
    used.add(name.lower())
    return name


def export(layout: Layout, project: dict, conversations: list[dict], messages_of) -> bytes:
    """The archive's bytes. `messages_of(cid)` gives a conversation's messages (for its Markdown)."""
    root = layout.project(project["id"])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = {"format": FORMAT, "kind": "slides-project", "name": project["name"]}
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if path.is_dir() or rel.startswith("renders/") or "/proposals/" in rel:
                continue
            z.write(path, f"data/{rel}")
        # readable/: what people open
        instructions = {"instructions": project.get("instructions", "")}
        z.writestr("readable/instructions.json", json.dumps(instructions, ensure_ascii=False, indent=1))
        memory = root / "memory.json"
        z.writestr("readable/memory.json", memory.read_text(encoding="utf-8") if memory.exists() else '{"items": []}')
        used: set[str] = set()
        decks = root / "decks"
        for deck_json in sorted(decks.glob("*/deck.json")) if decks.exists() else []:
            deck = json.loads(deck_json.read_text(encoding="utf-8"))
            current = deck_json.parent / "versions" / f"{deck['current_version']}.pptx"
            if current.exists():
                z.write(current, f"readable/decks/{_safe_name(deck['title'], used)}.pptx")
        used = set()
        for c in conversations:
            lines = [f"# {c.get('title') or 'Conversation'}", ""]
            for m in messages_of(c["id"]):
                if m.get("role") == "user" and (m.get("content") or "").strip():
                    at = m.get("at", "")[:16].replace("T", " ")
                    lines += [f"**{m.get('author') or 'Person'}** ({at})", "", m["content"].strip(), ""]
                elif m.get("role") == "assistant" and (m.get("content") or "").strip():
                    lines += [f"**Assistant** ({m.get('at', '')[:16].replace('T', ' ')})", "", m["content"].strip(), ""]
            z.writestr(f"readable/conversations/{_safe_name(c.get('title') or 'Conversation', used)}.md", "\n".join(lines))
    return out.getvalue()


def _allowed(rel: str, assets_listed: set[str]) -> str | None:
    """The kind of a data/ entry a project has, or None: project, memory, descriptions, deck, version, conversation,
    messages, assets, asset, passages."""
    parts = PurePosixPath(rel).parts
    if len(parts) == 1 and parts[0] in ("project.json", "memory.json", "descriptions.json"):
        return parts[0].removesuffix(".json")
    if len(parts) == 3 and parts[0] == "decks" and storage.is_id(parts[1]) and parts[2] == "deck.json":
        return "deck"
    if len(parts) == 4 and parts[0] == "decks" and storage.is_id(parts[1]) and parts[2] == "versions":
        stem, _, ext = parts[3].partition(".")
        return "version" if ext == "pptx" and stem.isdigit() and 0 < int(stem) < 100_000 else None
    if len(parts) == 3 and parts[0] == "conversations" and storage.is_id(parts[1]):
        return {"conversation.json": "conversation", "messages.jsonl": "messages"}.get(parts[2])
    if len(parts) == 2 and parts[0] == "assets":
        if parts[1] == "assets.json":
            return "assets"
        stem, _, ext = parts[1].partition(".")
        if storage.is_id(stem) and ext == "passages.json":
            return "passages"
        if storage.is_id(stem) and ext in ASSET_EXT and parts[1] in assets_listed:
            return "asset"
    return None


def unpack(raw: bytes, max_bytes: int) -> dict[str, bytes]:
    """The archive's data/ entries a project has ({relative path: bytes}); BadArchive when it is not such an archive,
    is too large, or names a path a project does not have."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise BadArchive("this is not a ZIP archive") from None
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_TOTAL:
            raise BadArchive("the archive unpacks to too much")
        names = {i.filename for i in infos}
        if "manifest.json" not in names or "data/project.json" not in names:
            raise BadArchive("this is not a project archive (no manifest.json, data/project.json)")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("kind") != "slides-project" or manifest.get("format") != FORMAT:
            raise BadArchive("this archive is from another application or format")
        listed: set[str] = set()
        if "data/assets/assets.json" in names:
            listed = {a.get("file", "") for a in json.loads(z.read("data/assets/assets.json")).get("assets", [])}
        out = {}
        for i in infos:
            if i.is_dir() or not i.filename.startswith("data/"):
                continue
            rel = i.filename.removeprefix("data/")
            if _allowed(rel, listed) is None:
                raise BadArchive(f"the archive holds a file a project does not have: {rel[:120]}")
            if i.file_size > max_bytes:
                raise BadArchive(f"a file in the archive is larger than {max_bytes >> 20} MB")
            out[rel] = z.read(i)
    return out


def check(entries: dict[str, bytes], max_bytes: int) -> None:
    """Every file as the application would accept it: records by their schemas (validated as they are written),
    deck versions by the upload checks, pictures opened; BadArchive with the first that is not."""
    listed = set()
    if "assets/assets.json" in entries:
        listed = {a.get("file", "") for a in json.loads(entries["assets/assets.json"]).get("assets", [])}
    for rel, data in entries.items():
        kind = _allowed(rel, listed)
        try:
            if kind in ("version",) or (kind == "asset" and rel.rsplit(".", 1)[-1] in ("pptx", "potx")):
                files.check(data, max_bytes)
            elif kind == "asset" and rel.rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "gif", "webp"):
                with Image.open(io.BytesIO(data)) as img:
                    img.verify()
            elif kind == "messages":
                for line in data.decode("utf-8").splitlines():
                    if line.strip():
                        storage.validate(json.loads(line), "message")
            elif rel.endswith(".json"):
                storage.validate(json.loads(data), {"project": "project", "memory": "memory", "descriptions": "descriptions",
                                                    "deck": "deck", "conversation": "conversation", "assets": "assets",
                                                    "passages": "passages"}[kind])  # fmt: skip
        except Exception as e:  # noqa: BLE001 - whatever the file's fault (schema, image, zip), it is refused by name
            raise BadArchive(f"{rel[:120]} is not a valid file of a project ({type(e).__name__})") from None


def write(layout: Layout, entries: dict[str, bytes], pid: str, email: str) -> dict:
    """The entries written as project `pid`, owned by `email` alone; returns its project record."""
    project = json.loads(entries["project.json"])
    now = storage.now()
    project.update(id=pid, owner=email, members=[{"email": email, "role": "owner"}], created_at=now, updated_at=now)
    root = layout.project(pid)
    for rel, data in entries.items():
        if rel == "project.json":
            continue
        storage.write_bytes(root / rel, data)
    storage.write_json(root / "project.json", project, "project")
    return project
