"""Projects (spec section 3.6, PJ-1): a folder each under DATA_DIR/projects, with project.json. Only members see a
project: to anyone else it does not exist (NotFound), as Cortex answers for what a person may not read."""

from __future__ import annotations

import shutil

from .. import storage
from ..storage import Layout, NotFound

DEFAULT_TEMPLATE = {"kind": "admin", "id": "default"}


def _role(project: dict, email: str) -> str | None:
    for m in project["members"]:
        if m["email"] == email:
            return m["role"]
    return None


def summary(project: dict, email: str) -> dict:
    return {
        "id": project["id"],
        "name": project["name"],
        "description": project["description"],
        "owner": project["owner"],
        "role": _role(project, email),
        "archived": project["archived"],
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
    }


class Projects:
    def __init__(self, layout: Layout) -> None:
        self.layout = layout

    def _path(self, pid: str):
        return self.layout.project(pid) / "project.json"

    def get(self, pid: str, email: str, roles: tuple[str, ...] = ("owner", "editor", "viewer")) -> dict:
        """The project, if `email` is a member in one of `roles`; NotFound otherwise."""
        project = storage.read_json(self._path(pid))
        if _role(project, email) not in roles:
            raise NotFound("project")
        return project

    def list(self, email: str) -> list[dict]:
        out = []
        if not self.layout.projects.exists():
            return out
        for folder in self.layout.projects.iterdir():
            if not storage.is_id(folder.name):
                continue
            try:
                project = storage.read_json(folder / "project.json")
            except NotFound:
                continue
            if _role(project, email):
                out.append(summary(project, email))
        return sorted(out, key=lambda p: p["updated_at"], reverse=True)

    async def create(self, email: str, name: str, description: str = "", language: str = "pt") -> dict:
        pid = storage.new_id()
        at = storage.now()
        project = {
            "schema_version": 1,
            "id": pid,
            "name": name.strip(),
            "description": description.strip(),
            "owner": email,
            "members": [{"email": email, "role": "owner"}],
            "settings": {"default_template": dict(DEFAULT_TEMPLATE), "language": language, "kb_domains": [], "model": None},
            "instructions": "",
            "archived": False,
            "created_at": at,
            "updated_at": at,
        }
        async with storage.lock(pid):
            storage.write_json(self._path(pid), project, "project")
        return project

    async def update(self, pid: str, email: str, changes: dict) -> dict:
        """Rename, describe, archive, settings (owner and editors; archive by the owner)."""
        async with storage.lock(pid):
            project = self.get(pid, email, roles=("owner", "editor"))
            for key in ("name", "description", "instructions"):
                if key in changes:
                    project[key] = str(changes[key]).strip()
            if "archived" in changes:
                if _role(project, email) != "owner":
                    raise NotFound("project")
                project["archived"] = bool(changes["archived"])
            if "settings" in changes:
                project["settings"].update({k: v for k, v in changes["settings"].items() if k in project["settings"]})
            project["updated_at"] = storage.now()
            storage.write_json(self._path(pid), project, "project")
        return project

    async def update_locked(self, project: dict, changes: dict) -> dict:
        """The same as update, for a caller already holding the project's lock (asyncio's lock is not re-entrant)."""
        for key in ("name", "description", "instructions"):
            if key in changes:
                project[key] = str(changes[key]).strip()
        project["updated_at"] = storage.now()
        storage.write_json(self._path(project["id"]), project, "project")
        return project

    async def touch(self, pid: str) -> None:
        """Something in the project changed: its last change is now (the project list's order)."""
        project = storage.read_json(self._path(pid))
        project["updated_at"] = storage.now()
        storage.write_json(self._path(pid), project, "project")

    async def delete(self, pid: str, email: str) -> None:
        """The owner deletes: the folder moves to DATA_DIR/trash (kept for the retention period, then removed)."""
        async with storage.lock(pid):
            self.get(pid, email, roles=("owner",))
            self.layout.trash.mkdir(parents=True, exist_ok=True)
            stamp = storage.now().replace(":", "").replace("-", "")
            shutil.move(str(self.layout.project(pid)), str(self.layout.trash / f"{pid}-{stamp}"))
