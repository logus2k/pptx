"""Logging and tracing, as Banco CTT's Centralized Logging Standard (v1.1) requires.

Slides: copied from Cortex (~/env/assets/cortex/cortex/telemetry.py), whose observability/README.md says how each of the
standard's rules is met. Changes, each marked "Slides:": the names (SLIDES_* variables, service "slides"), the pseudonym
key's file (DATA_DIR), and Cortex's NeMo/CUDA log filters removed (this app has neither).

setup(component) - once, first thing, in the process (app/__main__.py). After it:
  - every record of Python's logging - the app's own and the libraries' - is one JSON object per line on stdout, with
    the standard's fields: timestamp (ISO 8601 UTC), level, message, service, env, version, host, logger, and when they
    apply traceId / spanId, correlationId, userId, http.method / http.route / http.status_code, err.type / err.message
    / err.stack, plus the custom fields a call passes in `extra` (lowerCamelCase);
  - with OTEL_EXPORTER_OTLP_ENDPOINT set, the same records and the traces go by OTLP/HTTP to that OpenTelemetry
    Collector, from the SDK's background batch processors: a collector that is down costs telemetry, never a request;
  - a trace is joined or started for each request (instrument_asgi) and carried on every outgoing httpx / requests call
    (W3C traceparent): the app never makes trace or span ids itself.

Personal data: the person is `userId`, a keyed pseudonym of their address (pseudonym(); the key in
SLIDES_LOG_PSEUDONYM_KEY, else DATA_DIR/log_pseudonym.key), never the address. As a last line, any address-like word in a
message or a text field is replaced by its pseudonym (mask(): a lexical scan for '@', no pattern matching). Call sites
log ids, counts and lengths - never what people said, typed or named.

Request context (who, which flow, which route) is held in context variables, set by instrument_asgi for HTTP and by the
socket.io wrapper (app/main.py) for events; asyncio tasks and asyncio.to_thread inherit it.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import sys
from pathlib import Path
from typing import Any

SERVICE = os.environ.get("SLIDES_SERVICE_NAME") or "slides"
ENVS = ("dev", "test", "preprod", "prod")
ENV = (os.environ.get("SLIDES_ENV") or "dev").strip().lower()
VERSION = os.environ.get("SLIDES_VERSION") or "unknown"
HOST = socket.gethostname()
MAX_MESSAGE = 5000  # bytes: a longer message is truncated above DEBUG (Log Volumes: "anything larger than 5 kb")
MAX_STACK = 16000  # bytes of an error's stack
NOT_TRACED = ("/static/", "/socket.io/")  # path prefixes no span is made for (files; socket.io: a span per event)
# libraries whose per-call INFO lines are noise (91 % of the lines measured 2026-10-05: httpx's "HTTP Request: ..."):
# the traces carry those calls; their warnings and errors still come through
# Slides: Cortex's NeMo, lightning and CUDA entries and filters removed (this app loads no speech models)
QUIET = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "requests": logging.WARNING,
    "engineio": logging.WARNING,
    "socketio": logging.WARNING,
}


_user: contextvars.ContextVar[str | None] = contextvars.ContextVar("slides_user", default=None)  # a pseudonym
_correlation: contextvars.ContextVar[str | None] = contextvars.ContextVar("slides_correlation", default=None)
_http: contextvars.ContextVar[dict | None] = contextvars.ContextVar("slides_http", default=None)  # the ASGI scope

# the attributes every LogRecord has: anything else on a record came from `extra`
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "slides"}
_done = False
_tracer = None
_component = ""
_key: bytes | None = None


# ── who: a keyed pseudonym, never the address ─────────────────────────────────────────────────────────────────────────
def _pseudonym_key() -> bytes:
    global _key
    if _key is not None:
        return _key
    env = os.environ.get("SLIDES_LOG_PSEUDONYM_KEY")
    if env:
        _key = env.encode()
        return _key
    path = Path(os.environ.get("SLIDES_DATA_DIR", "/slides/data")) / "log_pseudonym.key"  # Slides: DATA_DIR
    try:
        if not path.exists():  # every process of this app shares it: the same person, the same userId
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(secrets.token_hex(32))
            except FileExistsError:  # another process made it first
                pass
        _key = path.read_text().strip().encode()
    except OSError:  # no DATA_DIR (a test outside the container): stable for this process only
        _key = secrets.token_hex(32).encode()
    return _key


def pseudonym(address: str | None) -> str | None:
    """The person's userId in logs and traces: 'u-' + 16 hex characters, the same for the same address (case ignored)
    under one key. Whoever holds the key and the list of addresses can tell who it is (tokenisation); nobody else."""
    a = (address or "").strip().lower()
    if not a:
        return None
    return "u-" + hmac.new(_pseudonym_key(), a.encode(), hashlib.sha256).hexdigest()[:16]


_LOCAL = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-")
_DOMAIN = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")


def mask(text: str) -> str:
    """Every address-like word (letters, digits and ._%+- before an '@', a domain of letters, digits, dots and hyphens
    after it) replaced by its pseudonym. A lexical scan around each '@', not a pattern."""
    if "@" not in text:
        return text
    out, i, last = [], 0, 0
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        a = at
        while a > last and text[a - 1] in _LOCAL:
            a -= 1
        b = at + 1
        while b < len(text) and text[b] in _DOMAIN:
            b += 1
        while b > at + 1 and text[b - 1] in ".-":  # a full stop after the address is not part of it
            b -= 1
        domain = text[at + 1 : b]
        if a < at and domain and domain[0].isalnum():
            out.append(text[last:a])
            out.append(pseudonym(text[a:b]) or "")
            last = b
        i = max(b, at + 1)
    out.append(text[last:])
    return "".join(out)


# ── the request context ───────────────────────────────────────────────────────────────────────────────────────────────
def set_user(address: str | None) -> contextvars.Token:
    return _user.set(pseudonym(address))


def set_correlation(value: str | None) -> contextvars.Token:
    """A business flow's id (a recording's session...), never personal: kept to 128 printable characters."""
    v = "".join(ch for ch in (value or "") if ch.isprintable() and not ch.isspace())[:128] or None
    return _correlation.set(mask(v) if v else None)


def user() -> str | None:
    return _user.get()


# ── the fields ────────────────────────────────────────────────────────────────────────────────────────────────────────
_LEVELS = {"WARNING": "WARN", "CRITICAL": "FATAL"}


def _plain(v: Any) -> Any:
    if isinstance(v, str):
        return mask(v)
    if isinstance(v, (bool, int, float)) or v is None:
        return v
    return mask(json.dumps(v, ensure_ascii=False, default=str))


def _cap(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", "ignore") + f" … [truncated {len(raw) - limit} bytes]"


def fields(record: logging.LogRecord) -> dict:
    """The record as the standard's JSON object (computed once per record; both handlers use it)."""
    f = getattr(record, "slides", None)
    if f is not None:
        return f
    try:
        message = record.getMessage()
    except Exception:  # noqa: BLE001 - a call with wrong arguments still leaves a line
        message = f"{record.msg!r} {record.args!r}"
    message = mask(str(message))
    if record.levelno > logging.DEBUG:
        message = _cap(message, MAX_MESSAGE)
    f = {
        "timestamp": dt.datetime.fromtimestamp(record.created, dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "level": _LEVELS.get(record.levelname, record.levelname),
        "message": message,
        "service": SERVICE,
        "env": ENV,
        "version": VERSION,
        "host": HOST,
        "logger": record.name,
    }
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            f["traceId"] = f"{ctx.trace_id:032x}"
            f["spanId"] = f"{ctx.span_id:016x}"
    except Exception:  # noqa: BLE001
        pass
    if _correlation.get():
        f["correlationId"] = _correlation.get()
    if _user.get():
        f["userId"] = _user.get()
    scope = _http.get()
    if scope is not None:
        f["http.method"] = scope.get("method")
        route = scope.get("route")
        f["http.route"] = getattr(route, "path", None) or scope.get("path")
        if scope.get("slides_status"):
            f["http.status_code"] = scope["slides_status"]
    if record.exc_info and record.exc_info[0] is not None:
        import traceback

        etype, value, _ = record.exc_info
        f["err.type"] = etype.__name__
        f["err.message"] = _cap(mask(str(value)), MAX_MESSAGE)
        f["err.stack"] = _cap(mask("".join(traceback.format_exception(*record.exc_info))), MAX_STACK)
    for k, v in vars(record).items():  # `extra`: custom fields (they may override the context's)
        if k not in _STANDARD_ATTRS and not k.startswith("_"):
            f[k] = _plain(v)
    record.slides = f
    return f


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(fields(record), ensure_ascii=False, default=str)


# the fields an OTLP log record carries natively, or in the resource: not repeated as attributes
_NATIVE = frozenset({"timestamp", "level", "message", "traceId", "spanId", "service", "env", "version", "host"})


class _OtlpHandler(logging.Handler):
    """The same records to the OpenTelemetry logs pipeline (BatchLogRecordProcessor: queued, exported in the
    background). Built on the logs API itself: the SDK's LoggingHandler is deprecated in 1.45."""

    def __init__(self, provider) -> None:
        super().__init__()
        self.provider = provider

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from opentelemetry import context as otel_context
            from opentelemetry._logs import LogRecord
            from opentelemetry.sdk._logs._internal import std_to_otel

            f = fields(record)
            self.provider.get_logger(record.name).emit(
                LogRecord(
                    timestamp=int(record.created * 1e9),
                    context=otel_context.get_current(),
                    severity_text=f["level"],
                    severity_number=std_to_otel(record.levelno),
                    body=f["message"],
                    event_name=f.get("eventName"),
                    attributes={k: v for k, v in f.items() if k not in _NATIVE and v is not None},
                )
            )
        except Exception:  # noqa: BLE001 - a logging failure never breaks the work it reports
            pass


# ── setup ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _level() -> int:
    wanted = (os.environ.get("SLIDES_LOG_LEVEL") or "INFO").strip().upper()
    level = logging.getLevelName(wanted) if wanted in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else logging.INFO
    if ENV == "prod" and level < logging.INFO:  # DEBUG in production only with a time-boxed override
        until = os.environ.get("SLIDES_LOG_DEBUG_UNTIL") or ""
        try:
            ok = dt.datetime.fromisoformat(until.replace("Z", "+00:00")) > dt.datetime.now(dt.timezone.utc)
        except ValueError:
            ok = False
        if not ok:
            level = logging.INFO
    return level


def adopt_library_loggers() -> None:
    """Libraries that write through handlers of their own bypass the JSON handler: their stream handlers are removed
    and their records go up to the root. Called by setup() and again after a library is imported late."""
    for name, lg in list(logging.root.manager.loggerDict.items()):
        if not isinstance(lg, logging.Logger):
            continue
        own = [h for h in lg.handlers if not isinstance(h, logging.NullHandler)]
        if own:
            for h in own:
                lg.removeHandler(h)
            lg.propagate = True
        elif not lg.propagate and lg.handlers == []:
            lg.propagate = True
    for name, level in QUIET.items():
        logging.getLogger(name).setLevel(level)


def setup(component: str = "server") -> None:
    """Configure logging (and, with an endpoint, the OTLP export of logs and traces) for this process."""
    global _done, _tracer, _component
    if _done:
        return
    _done = True
    _component = component
    logging.raiseExceptions = False  # a handler's failure is not printed into the output either
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create(
        {
            "service.name": SERVICE,
            "service.version": VERSION,
            "deployment.environment.name": ENV,
            "host.name": HOST,
            "service.instance.id": f"{HOST}:{component}:{os.getpid()}",
        }
    )
    exporting = bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"))
    # a tracer provider always (trace ids exist and travel to the next service, and logs carry them); its sampler from
    # the SDK's own OTEL_TRACES_SAMPLER variables (default: parent-based, always on)
    provider = TracerProvider(resource=resource)
    if exporting:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider.add_span_processor(BatchSpanProcessor(_MaskedSpanExporter(OTLPSpanExporter())))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("slides")

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    out = logging.StreamHandler(sys.stdout)
    out.setFormatter(_JsonFormatter())
    root.addHandler(out)
    if exporting:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        logs = LoggerProvider(resource=resource)
        logs.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        set_logger_provider(logs)
        root.addHandler(_OtlpHandler(logs))
    root.setLevel(_level())
    logging.captureWarnings(True)  # Python's warnings as log records too, not raw stderr lines
    adopt_library_loggers()
    # outgoing calls carry the trace (W3C traceparent) and get their own spans
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        HTTPXClientInstrumentor().instrument()
        RequestsInstrumentor().instrument()
    except Exception:  # noqa: BLE001 - tracing must not stop the app from starting
        logging.getLogger("slides.telemetry").exception("outgoing calls are not instrumented")
    logging.getLogger("slides.telemetry").info(
        f"logging: JSON on stdout, level {logging.getLevelName(root.level)}, env {ENV}"
        + (
            f"; OTLP to {os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT') or os.environ.get('OTEL_EXPORTER_OTLP_LOGS_ENDPOINT')}"
            if exporting
            else "; no OTLP export (OTEL_EXPORTER_OTLP_ENDPOINT is not set)"
        )
        + (f" ({os.environ.get('SLIDES_ENV')!r} is not one of {ENVS})" if ENV not in ENVS else "")
    )


def tracer():
    from opentelemetry import trace

    return _tracer or trace.get_tracer("slides")


# ── HTTP: a span per request, and its context for the logs ────────────────────────────────────────────────────────────
def instrument_asgi(app):
    """The whole ASGI app (socket.io in front of FastAPI) wrapped: each HTTP request joins the caller's trace (W3C
    traceparent) or starts one, except NOT_TRACED paths; its logs get http.method / http.route, the person (the
    proxy's identity header) and correlationId
    (the X-Correlation-ID header). A 5xx answer is logged with its status. The span is named by its route once
    routing has run (name_span)."""
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

    traced = OpenTelemetryMiddleware(app, exclude_spans=["receive", "send"])
    log = logging.getLogger("slides.http")

    async def middleware(scope, receive, send):
        if scope.get("type") != "http":
            return await app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        # Slides: no integration API here, so every request's person is the proxy's identity header
        tokens = (_http.set(scope), _user.set(pseudonym(headers.get("x-auth-request-email"))), _correlation.set(None))
        set_correlation(headers.get("x-correlation-id"))

        async def watch(message):
            if message.get("type") == "http.response.start":
                scope["slides_status"] = message.get("status")
            await send(message)

        try:
            inner = app if any(scope.get("path", "").startswith(p) for p in NOT_TRACED) else traced
            await inner(scope, receive, watch)
        finally:
            status = scope.get("slides_status") or 0
            if status >= 500:
                log.error("request failed")
            _http.reset(tokens[0])
            _user.reset(tokens[1])
            _correlation.reset(tokens[2])

    return middleware


def name_span(scope: dict) -> None:
    """The request's span named by its route template ("DELETE /api/keys/{kid}"), not its path: ids in paths would make
    a name per id. Called once routing has run (app/main.py: an app-wide FastAPI dependency)."""
    from opentelemetry import trace

    route = getattr(scope.get("route"), "path", None)
    span = trace.get_current_span()
    if route and span.is_recording():
        span.update_name(f"{scope.get('method', '')} {route}")
        span.set_attribute("http.route", route)


# ── spans: the same last line as the logs ─────────────────────────────────────────────────────────────────────────────
# attributes that hold a URL: their query string is dropped (it carries filters people typed, document paths, addresses)
URL_ATTRS = frozenset({"http.url", "http.target", "url.full", "url.query"})


class _MaskedSpanExporter:
    """Wraps the OTLP span exporter: before a span leaves, its name and text attributes are masked (mask()) and the
    query string of its URL attributes dropped."""

    def __init__(self, inner) -> None:
        self.inner = inner

    @staticmethod
    def _clean(key: str, value):
        if isinstance(value, str):
            if key in URL_ATTRS:
                value = "" if key == "url.query" else value.split("?", 1)[0]
            return mask(value)
        if isinstance(value, (list, tuple)):
            return type(value)(mask(v) if isinstance(v, str) else v for v in value)
        return value

    def export(self, spans):
        from opentelemetry.sdk.trace import Event, ReadableSpan

        out = []
        for s in spans:
            try:
                out.append(
                    ReadableSpan(
                        name=mask(s.name),
                        context=s.context,
                        parent=s.parent,
                        resource=s.resource,
                        attributes={k: self._clean(k, v) for k, v in (s.attributes or {}).items()},
                        events=[
                            Event(e.name, {k: self._clean(k, v) for k, v in (e.attributes or {}).items()}, e.timestamp)
                            for e in s.events
                        ],
                        links=s.links,
                        kind=s.kind,
                        status=s.status,
                        start_time=s.start_time,
                        end_time=s.end_time,
                        instrumentation_scope=s.instrumentation_scope,
                    )
                )
            except Exception:  # noqa: BLE001 - a span that cannot be cleaned is not sent
                pass
        return self.inner.export(out)

    def shutdown(self):
        return self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000):
        return self.inner.force_flush(timeout_millis)
