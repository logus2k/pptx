"""The server: the REST API, the socket.io channel and the frontend's files in one ASGI app, as Cortex assembles them
(cortex/server/app.py). create_app() builds it; main() serves it."""

from __future__ import annotations

import asyncio
import inspect
import logging

import socketio
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import api as api_routes
from . import audit, identity, telemetry
from .config import Settings
from .agent.llm import Models
from .agent.loop import Agent
from .docengine import read
from .domain.conversations import Conversations
from .domain.decks import Decks
from .describe import Describer
from .domain.memory import Memory
from .domain.projects import Projects
from .domain.proposals import Proposals
from .domain.templates import AdminTemplates, ProjectAssets, Templates
from .domain.leases import Leases
from .domain.generations import Generations
from .imagegen import ImageGenerator
from .kb import KnowledgeBase
from .search import Reranker
from .speech import MAX_SECONDS as SPEECH_SECONDS
from .speech import SAMPLE_RATE, SttClient, voice_text
from .storage import Layout, NotFound

log = logging.getLogger("slides")

# paths that are not the page's routes (everything else answers with index.html: the History API router decides)
NOT_PAGES = ("/api/", "/static/", "/socket.io/")
# no proxy secret needed: the container's own health check (it reads nothing and changes nothing)
OPEN_PATHS = frozenset({"/api/health"})


async def _span_by_route(request: Request) -> None:
    """Names the request's span by its route once routing has run (telemetry.name_span)."""
    telemetry.name_span(request.scope)


def base_path(prefix_header: str | None) -> str:
    """Where the app is served: the proxy says so in X-Forwarded-Prefix ("/slides"); reached directly, "/". Only
    plain path segments are accepted (letters, digits, - and _), so the value is safe inside the page's <base href>."""
    parts = [p for p in (prefix_header or "").strip().split("/") if p]
    if not all(p.replace("-", "").replace("_", "").isalnum() and p.isascii() for p in parts):
        return "/"
    return "/" + "".join(p + "/" for p in parts)


def _index_html(settings: Settings, prefix_header: str | None) -> str:
    """index.html with its <base href> set to where the app is served, so relative addresses ("static/...") resolve
    the same under any page route (/slides/projects/<id>/...)."""
    page = (settings.frontend_dir / "index.html").read_text(encoding="utf-8")
    return page.replace('<base href="/">', f'<base href="{base_path(prefix_header)}">', 1)


class Services:
    """What the routes and the agent share."""

    def __init__(
        self, settings: Settings, models: Models | None = None, kb: KnowledgeBase | None = None, stt=None, reranker=None,
        imagegen=None,
    ) -> None:
        self.settings = settings
        self.layout = Layout(settings.data_dir)
        self.projects = Projects(self.layout)
        self.assets = ProjectAssets(self.layout)
        # spec AD-4: managed from the template screen in DATA_DIR/templates, seeded from the configured folder
        self.templates = Templates(AdminTemplates(settings.templates_dir, settings.data_dir / "templates"), self.assets)
        self.renderer = api_routes.Renderer(self.layout)
        minutes = float((settings.file.get("limits") or {}).get("lease_idle_minutes", 10))  # spec PJ-13: 10 by default
        self.decks = Decks(self.layout, self.projects, self.templates, Leases(minutes))
        self.conversations = Conversations(self.layout, self.projects)
        self.proposals = Proposals(self.layout)
        services = settings.file.get("services", {})
        self.memory = Memory(self.layout, self.projects)
        self.describer = None  # set below, once the models are
        self.reranker = reranker or Reranker(services.get("reranker", ""))
        self.stt = stt or SttClient(services.get("stt", "http://stt_server:2700"))
        self.imagegen = imagegen or ImageGenerator(services.get("image_generation"))  # spec IM-6: off unless configured
        self.kb = kb or KnowledgeBase(services.get("cortex_api", "http://proxy_server:8710/cortex/api/v1"), settings.cortex_key)
        self.models = models or Models(
            services.get("agent_server", "http://agent_server:7701"),
            services.get("tokenizer", "http://llama-vision:8500/tokenize"),
        )
        self.generations = Generations(self)  # decks generated from a source (spec NL-12)
        self.describer = Describer(self)  # what the decks' pictures show (spec IM-4), after each version is published
        self.renderer.on_warm = self.describer.warm


def create_app(
    settings: Settings, models: Models | None = None, kb: KnowledgeBase | None = None, stt=None, reranker=None,
    imagegen=None,
) -> socketio.ASGIApp:
    api = FastAPI(title="slides", docs_url=None, redoc_url=None, dependencies=[Depends(_span_by_route)])
    api.state.settings = settings
    profiles = identity.Profiles(settings)

    @api.middleware("http")
    async def require_proxy(request: Request, call_next):
        """Only requests that came through the proxy (technical design section 1.1)."""
        if request.url.path not in OPEN_PATHS and not identity.proxy_secret_ok(
            settings, request.headers.get(identity.SECRET_HEADER)
        ):
            return JSONResponse({"detail": "not through the proxy"}, status_code=401)
        return await call_next(request)

    @api.get("/api/health")
    async def health():
        return {"status": "ok", "version": telemetry.VERSION}

    # projects, decks, templates, renders, conversations, proposals; the audit trail of every change (section 11.2)
    app = Services(settings, models, kb, stt, reranker, imagegen)
    # the pages allowed to open it (identity.origin_allowed; [] would check none: security review M1)
    sio = socketio.AsyncServer(
        async_mode="asgi", cors_allowed_origins=lambda origin, environ=None: identity.origin_allowed(settings, origin),
        max_http_buffer_size=10 * 1024 * 1024,
    )

    async def emit(event: str, payload: dict, cid: str) -> None:
        await sio.emit(event, {"conversation_id": cid, **payload}, room=f"conv:{cid}")

    agent = Agent(app, emit)
    audit.middleware(
        api, app.layout.audit, lambda request: identity.address_of(settings, request.headers.get(identity.EMAIL_HEADER))
    )
    api.include_router(
        api_routes.build(
            settings,
            app.layout,
            app.projects,
            app.decks,
            app.assets,
            app.templates,
            app.renderer,
            app.conversations,
            app.proposals,
            agent,
            app.kb,
            app.memory,
            app.generations,
        )
    )

    @api.get("/api/me")
    async def me(user: identity.User = Depends(identity.current_user)):
        """Who the proxy says is signed in. Name and photo come over socket.io (whoami), where the proxy forwards the
        token they need."""
        return {"email": user.email, "is_admin": user.is_admin}

    api.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")

    @api.get("/{path:path}", include_in_schema=False)
    async def page(path: str, request: Request):
        if ("/" + path).startswith(NOT_PAGES):
            return JSONResponse({"detail": "not found"}, status_code=404)
        return HTMLResponse(
            _index_html(settings, request.headers.get("x-forwarded-prefix")), headers={"Cache-Control": "no-store"}
        )

    users: dict[str, dict] = {}  # sid -> what the proxy forwarded on the handshake

    @sio.event
    async def connect(sid, environ):
        if not identity.proxy_secret_ok(settings, environ.get("HTTP_X_SLIDES_PROXY_SECRET")):
            log.warning("socket connect refused: not through the proxy")
            return False
        email = identity.address_of(settings, environ.get("HTTP_X_AUTH_REQUEST_EMAIL"))
        if not email:
            log.warning("socket connect refused: no identity")
            return False
        users[sid] = {
            "email": email,
            "token": environ.get("HTTP_X_ACCESS_TOKEN") or "",
            "id_token": (environ.get("HTTP_X_ID_TOKEN") or "").removeprefix("Bearer ").strip(),
        }
        log.info("socket connected")

    @sio.event
    async def disconnect(sid, *args):
        users.pop(sid, None)
        voices.pop(sid, None)

    @sio.event
    async def whoami(sid, data=None):
        """The signed-in person for the profile menu: address, name and photo (from the provider, with the token the
        proxy forwards), the sign-out address, and whether they administer the app."""
        u = users.get(sid)
        if not u:
            return {"authenticated": False}
        info = await profiles.of(u["token"])
        email = u["email"]
        return {
            "authenticated": True,
            "email": email,
            "name": info.get("name") or info.get("preferred_username") or email.split("@")[0],
            "picture": info.get("picture") or None,
            "signOutUrl": identity.sign_out_url(settings.file["identity"]["sign_out_url"], u["id_token"]),
            "is_admin": email in settings.administrators,
        }

    # ── the assistant's channel (technical design section 10) ──
    def who(sid) -> str:
        u = users.get(sid)
        if not u:
            raise PermissionError("not signed in")
        return u["email"]

    def ids(data) -> tuple[str, str]:
        data = data or {}
        return str(data.get("project_id") or ""), str(data.get("conversation_id") or "")

    async def guarded(fn):
        try:
            return {"ok": True, **((await fn()) or {})}
        except NotFound:
            return {"ok": False, "error": "not found"}
        except (ValueError, PermissionError) as e:
            return {"ok": False, "error": str(e)}

    def recorded(sid, event: str, target: dict) -> None:
        audit.record(app.layout.audit, users.get(sid, {}).get("email"), f"socket {event}", target)

    @sio.event
    async def join_conversation(sid, data=None):
        """Follow a conversation: its messages after `after` (the catch-up after a reconnection) come back."""
        pid, cid = ids(data)

        async def run():
            conv = app.conversations.get(pid, cid, who(sid))
            for room in list(sio.rooms(sid)):
                if room.startswith("conv:"):
                    await sio.leave_room(sid, room)
            await sio.enter_room(sid, f"conv:{cid}")
            open_p = app.proposals.open_in(pid, cid)
            return {
                "conversation": conv,
                "messages": app.conversations.messages(pid, cid, int((data or {}).get("after") or 0)),
                "proposal": agent.describe(pid, open_p) if open_p and open_p["status"] == "pending" else None,
                "busy": agent.busy(cid),
            }

        return await guarded(run)

    @sio.event
    async def user_message(sid, data=None):
        pid, cid = ids(data)
        d = data or {}

        async def run():
            text = str(d.get("text") or "").strip()
            if not text:
                raise ValueError("an empty message")
            if len(text) > 8000:  # refused, never cut: the model gets what the person wrote or nothing
                raise ValueError(f"The message is too long: {len(text)} characters, at most 8000.")
            await agent.user_message(pid, cid, who(sid), text, d.get("deck_id"), d.get("selection"), d.get("attachments"))
            recorded(sid, "user_message", {"pid": pid, "cid": cid})

        return await guarded(run)

    # ── a spoken request (technical design section 7; spec VO-1): voice_begin, then the audio (PCM16 16 kHz mono, in
    # packets of ~100 ms) while the microphone is on, then voice_end; the words come back as voice_text, to the
    # composer, for the person to check before sending. Audio in memory only, one recording per connection.
    voices: dict[str, dict] = {}

    def vocabulary(email: str, pid: str, did: str | None) -> str:
        """Words the recogniser should know (Whisper's preceding context, read as text it has heard): the project's
        name, its decks' titles, the open deck's slide titles - the names people say. Whisper reads 224 tokens of it
        at most, so the most specific come first: the open deck's slides, then the decks, then the project."""
        words: list[str] = []
        try:
            project = app.projects.get(pid, email)
            if did:
                _, data = app.decks.version_bytes(pid, did, email)
                words += [o["title"] for o in read.outline(read.open_deck(data)) if o["title"]]
            words += [d["title"] for d in app.decks.list(pid, email)]
            words.append(project["name"])
        except NotFound:
            return ""
        seen, out, size = set(), [], 0
        for w in words:
            w = " ".join(w.split())
            if w and w.lower() not in seen and size + len(w) < 600:  # ~200 tokens: Whisper's prompt window
                seen.add(w.lower())
                out.append(w)
                size += len(w) + 2
        return ", ".join(out)

    @sio.event
    async def voice_begin(sid, data=None):
        """{project_id, deck_id?, language ("pt" | "en")}: the microphone is on."""
        email = who(sid)
        d = data or {}
        language = "en" if d.get("language") == "en" else "pt"
        prompt = await asyncio.to_thread(vocabulary, email, str(d.get("project_id") or ""), d.get("deck_id"))
        voices[sid] = {"pcm": bytearray(), "language": language, "prompt": prompt}
        return {"ok": True}

    @sio.event
    async def voice_audio(sid, data):
        v = voices.get(sid)
        if v is not None and isinstance(data, (bytes, bytearray)) and len(v["pcm"]) < (SPEECH_SECONDS + 5) * SAMPLE_RATE * 2:
            v["pcm"] += data

    @sio.event
    async def voice_cancel(sid, data=None):
        """The recording is dropped unheard (hands-free turned off in the middle of a request: spec VO-2)."""
        voices.pop(sid, None)
        return {"ok": True}

    @sio.event
    async def voice_end(sid, data=None):
        v = voices.pop(sid, None)
        if v is None:
            await sio.emit("voice_text", {"text": "", "error": "the microphone was not on"}, to=sid)
            return {"ok": False}
        text, error = await voice_text(app.stt, bytes(v["pcm"]), v["language"], v["prompt"] or None)
        await sio.emit("voice_text", {"text": text, **({"error": error} if error else {})}, to=sid)
        recorded(sid, "voice", {"seconds": round(len(v["pcm"]) / SAMPLE_RATE / 2, 1)})
        return {"ok": True}

    @sio.event
    async def cancel_turn(sid, data=None):
        pid, cid = ids(data)

        async def run():
            # a member of the conversation's project only (security review L2: any signed-in person, any conversation)
            await asyncio.to_thread(app.conversations.get, pid, cid, who(sid))
            agent.cancel(cid)

        return await guarded(run)

    @sio.event
    async def answer(sid, data=None):
        """The person's answer to a question, a plan (approve, comment) or proposed instructions (accept)."""
        pid, cid = ids(data)
        d = data or {}

        async def run():
            decision = {k: d[k] for k in ("answer", "approve", "comment", "accept") if k in d}
            await agent.resolve(pid, cid, who(sid), decision)
            recorded(sid, "answer", {"pid": pid, "cid": cid})

        return await guarded(run)

    @sio.event
    async def proposal_decision(sid, data=None):
        pid, cid = ids(data)
        d = data or {}

        async def run():
            p = await agent.decide(pid, cid, str(d.get("proposal_id") or ""), who(sid), bool(d.get("accept")), d.get("slides"))
            recorded(sid, "proposal_decision", {"pid": pid, "cid": cid, "prid": p["id"], "status": p["status"]})
            return {"status": p["status"]}

        return await guarded(run)

    if settings.file.get("services", {}).get("agent_server") and models is None:
        try:
            app.models.register_presets()
        except Exception as e:  # noqa: BLE001 - the app runs; turns fail until agent_server answers
            log.warning(
                f"agent_server presets not registered ({type(e).__name__}); the assistant is unavailable until it answers"
            )

    _instrument_socket_events(sio, users)
    return socketio.ASGIApp(sio, other_asgi_app=api)


UNTRACED = ("voice_audio",)  # audio packets, ten a second: no span each (technical design section 11)


def _instrument_socket_events(sio: socketio.AsyncServer, users: dict[str, dict]) -> None:
    """Every socket.io handler wrapped, as Cortex does: its logs carry who sent it (userId, a pseudonym) and it runs in a
    span of its own, a new trace per event (a websocket lives for hours: one span for it would never end)."""
    from opentelemetry.context import Context
    from opentelemetry.trace import SpanKind

    handlers = sio.handlers.get("/", {})

    def wrapped(event: str, handler):
        async def run(sid, *args):
            email = (users.get(sid) or {}).get("email")
            token = telemetry.set_user(email)
            try:
                with telemetry.tracer().start_as_current_span(
                    f"socket.io {event}",
                    context=Context(),
                    kind=SpanKind.SERVER,
                    attributes={"rpc.system": "socket.io", "rpc.method": event},
                ):
                    result = handler(sid, *args)
                    if inspect.isawaitable(result):
                        result = await result
                return result
            finally:
                telemetry._user.reset(token)

        return run

    for event, handler in list(handlers.items()):
        if event in UNTRACED:
            continue
        handlers[event] = wrapped(event, handler)


def main(settings: Settings) -> None:
    app = create_app(settings)
    log.info(f"serving on http://0.0.0.0:{settings.port}")
    # log_config=None: uvicorn's records go through the JSON handler (telemetry.py), not its own
    uvicorn.run(
        telemetry.instrument_asgi(app),
        host="0.0.0.0",  # noqa: S104 - inside its container; the port is reached only through the proxy
        port=settings.port,
        log_level="warning",
        log_config=None,
    )
