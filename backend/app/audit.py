"""The audit trail (technical design section 11.2), as Cortex records it (cortex/api/audit.py): who changed which data
and when, never the change itself. A middleware records every POST / PUT / PATCH / DELETE that answered below 400:
the person, the route template, its label, and the target by identifiers only (the route's parameters, the query,
and what the handler names in request.state.audit). Cortex keeps its trail in SQLite; with no database here it is
DATA_DIR/audit.jsonl, one line per change. Each record is also a log record (eventName: audit), so the evidence reaches
the append-only log platform with the person as a pseudonym."""

from __future__ import annotations

import asyncio
import logging

from . import storage

log = logging.getLogger("slides.audit")
CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# what each changing route does, in words (a route without a label is still recorded, by its template)
LABELS = {
    "POST /api/projects": "created a project",
    "PATCH /api/projects/{pid}": "changed a project",
    "DELETE /api/projects/{pid}": "deleted a project",
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
    "socket user_message": "asked the assistant",
    "socket answer": "answered the assistant",
    "socket proposal_decision": "decided on the assistant's changes",
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
            if template:
                action = f"{request.method} {template}"
                target = {
                    **dict(request.query_params),
                    **(request.scope.get("path_params") or {}),
                    **(getattr(request.state, "audit", None) or {}),
                }
                await asyncio.to_thread(record, path, email_of(request), action, target)
        return response
