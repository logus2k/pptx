"""The audit trail (technical design section 11.2), as Cortex records it (cortex/api/audit.py): who changed which data
and when, never the change itself. A middleware records every POST / PUT / PATCH / DELETE that answered below 400:
the person, the route template, its label, and the target by identifiers only (the route's parameters, the query,
and what the handler names in request.state.audit). Cortex keeps its trail in SQLite; with no database here it is
DATA_DIR/audit.jsonl, one line per change. Each record is also a log record (eventName: audit), so the evidence reaches
the append-only log platform with the person as a pseudonym."""

from __future__ import annotations

import asyncio
import json
import logging

from . import storage

log = logging.getLogger("slides.audit")
CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# routes that change no data (as Cortex's NOT_CHANGES): the open editor renews its lease every minute
NOT_CHANGES = frozenset({"POST /api/projects/{pid}/decks/{did}/lease", "DELETE /api/projects/{pid}/decks/{did}/lease"})

# what each changing route does, in words (a route without a label is still recorded, by its template)
LABELS = {
    "POST /api/projects": "created a project",
    "PATCH /api/projects/{pid}": "changed a project",
    "DELETE /api/projects/{pid}": "deleted a project",
    "POST /api/projects/import": "imported a project",
    "PUT /api/projects/{pid}/members": "shared a project",
    "DELETE /api/projects/{pid}/members/{member}": "removed a project member",
    "POST /api/projects/{pid}/decks": "added a deck",
    "PATCH /api/projects/{pid}/decks/{did}": "renamed a deck",
    "DELETE /api/projects/{pid}/decks/{did}": "deleted a deck",
    "POST /api/projects/{pid}/decks/{did}/versions/{number}/restore": "restored a deck version",
    "POST /api/projects/{pid}/assets": "uploaded an asset",
    "DELETE /api/projects/{pid}/assets/{aid}": "deleted an asset",
    "POST /api/projects/{pid}/decks/{did}/edits": "edited a deck by hand",
    "POST /api/projects/{pid}/decks/{did}/undo": "undid a change",
    "POST /api/projects/{pid}/decks/{did}/redo": "redid a change",
    "POST /api/projects/{pid}/conversations": "started a conversation",
    "PATCH /api/projects/{pid}/conversations/{cid}": "renamed a conversation",
    "DELETE /api/projects/{pid}/conversations/{cid}": "deleted a conversation",
    "POST /api/projects/{pid}/conversations/{cid}/proposals/{prid}/decision": "decided on the assistant's changes",
    "POST /api/admin/templates": "added a template",
    "PATCH /api/admin/templates/{tid}": "changed a template",
    "socket user_message": "asked the assistant",
    "socket answer": "answered the assistant",
    "socket proposal_decision": "decided on the assistant's changes",
    "assistant decide_changes": "decided on the assistant's changes, in words",
    "turn failed": "the assistant's turn failed",
}


def record(path, user: str | None, action: str, target: dict) -> None:
    line = {"at": storage.now(), "user": user or "anonymous", "action": action, "target": target}
    if action in LABELS:
        line["label"] = LABELS[action]
    storage.append_line(path, line, "audit-line")
    # the person is the log record's userId (the request's context: telemetry.instrument_asgi), a pseudonym
    log.info("audit", extra={"eventName": "audit", "action": action, "label": LABELS.get(action, ""), "target": target})


def middleware(app, path, email_of):
    """Install the recording middleware on the FastAPI app. `email_of(request)` gives the person."""

    @app.middleware("http")
    async def audit_changes(request, call_next):
        response = await call_next(request)
        if request.method in CHANGING and response.status_code < 400:
            route = request.scope.get("route")
            template = getattr(route, "path", None)
            if template and f"{request.method} {template}" not in NOT_CHANGES:
                action = f"{request.method} {template}"
                target = {
                    **dict(request.query_params),
                    **(request.scope.get("path_params") or {}),
                    **(getattr(request.state, "audit", None) or {}),
                }
                await asyncio.to_thread(record, path, email_of(request), action, target)
        return response


# ── reading it (spec AD-5, AD-6; as Cortex's cortex/api/audit.py: filters, keyset pages, CSV) ──────────────────────
def entries(path) -> list[dict]:
    """Every record, oldest first, each with its id (its line number: the file is only ever appended to)."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if line.strip():
                    try:
                        out.append({"id": n, **json.loads(line)})
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    return out


def search(path, user: str = "", q: str = "", since: str = "", until: str = "", before: int | None = None, limit: int = 100):
    """{entries (newest first), more, users}: by person, by words in what was done or its data, by period (ISO times)."""
    every = entries(path)
    q = q.strip().lower()
    hits = []
    for e in reversed(every):
        if before is not None and e["id"] >= before:
            continue
        if user and e.get("user") != user:
            continue
        if since and e.get("at", "") < since:
            continue
        if until and e.get("at", "") > until:
            continue
        words = f"{e.get('label', '')} {e.get('action', '')} {json.dumps(e.get('target', {}), ensure_ascii=False)}"
        if q and q not in words.lower():
            continue
        hits.append(e)
        if len(hits) > limit:
            break
    return {"entries": hits[:limit], "more": len(hits) > limit, "users": sorted({e.get("user", "") for e in every} - {""})}


def usage(path, since: str = "", until: str = "", by: str = "week") -> list[dict]:
    """Per period (day, week from Monday, or month): active people, projects worked on, assistant turns, proposals
    accepted and rejected, the assistant's failed turns (spec AD-5: built from the audit log)."""
    import datetime as dt

    def period(at: str) -> str:
        d = dt.date.fromisoformat(at[:10])
        if by == "day":
            return d.isoformat()
        if by == "month":
            return d.strftime("%Y-%m")
        return (d - dt.timedelta(days=d.weekday())).isoformat()

    rows: dict[str, dict] = {}
    for e in entries(path):
        at = e.get("at", "")
        if not at or (since and at < since) or (until and at > until):
            continue
        blank = {"people": set(), "projects": set(), "turns": 0, "accepted": 0, "rejected": 0, "errors": 0}
        r = rows.setdefault(period(at), blank)
        if e.get("user") and e["user"] != "anonymous":
            r["people"].add(e["user"])
        target = e.get("target") or {}
        if target.get("pid"):
            r["projects"].add(target["pid"])
        action = e.get("action", "")
        if action == "socket user_message":
            r["turns"] += 1
        elif action == "turn failed":
            r["errors"] += 1
        status = target.get("status")
        if action in ("socket proposal_decision", "assistant decide_changes",
                      "POST /api/projects/{pid}/conversations/{cid}/proposals/{prid}/decision"):  # fmt: skip
            if status in ("accepted", "partially_accepted"):
                r["accepted"] += 1
            elif status == "rejected":
                r["rejected"] += 1
    counts = ("turns", "accepted", "rejected", "errors")
    return [
        {"period": k, "people": len(v["people"]), "projects": len(v["projects"]), **{c: v[c] for c in counts}}
        for k, v in sorted(rows.items())
    ]
