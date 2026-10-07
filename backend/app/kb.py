"""The Knowledge Base: Cortex's integration API (technical design section 8; Cortex's Developer SDK manual,
static/help/sdk/). This app's service key, and the signed-in person's address in X-On-Behalf-Of on every call, so
Cortex answers with that person's access (spec KB-5). Called from the server only, at the internal address.

Timeouts of 30 s; 429 is retried after Retry-After, 502 and network errors up to three times with a growing pause;
anything else is a KBError the tools turn into a tool error."""

from __future__ import annotations

import logging
import time
from urllib.parse import quote

import requests

log = logging.getLogger("slides.kb")
TIMEOUT = 30
RETRIES = 3
MAX_WAIT = 20  # seconds: a longer Retry-After is not waited for inside a turn


class KBError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


class KnowledgeBase:
    def __init__(self, base_url: str, key: str) -> None:
        self.base = base_url.rstrip("/")
        self.key = key
        self._domains: dict[str, tuple[float, list[dict]]] = {}  # address -> (when, the person's domains)

    @property
    def available(self) -> bool:
        return bool(self.key)

    # ── the routes ───────────────────────────────────────────────────
    def domains(self, email: str) -> list[dict]:
        """The domains this person can query ({id, name, description}); kept a minute."""
        hit = self._domains.get(email.lower())
        if hit and time.monotonic() - hit[0] < 60:
            return hit[1]
        out = self._call("GET", "domains", email).json().get("domains", [])
        self._domains[email.lower()] = (time.monotonic(), out)
        return out

    def search(self, email: str, query: str, domains: list[str] | None = None, top_k: int = 6, documents=None) -> dict:
        body: dict = {"query": query, "top_k": max(1, min(int(top_k), 20))}
        if domains:
            body["domains"] = domains
        if documents:
            body["documents"] = documents
        return self._call("POST", "search", email, json=body).json()

    def passage(self, email: str, passage_id: str) -> dict:
        return self._call("GET", f"passages/{quote(passage_id, safe='')}", email).json()

    def document_passages(self, email: str, domain: str, path: str, after: int = 0, limit: int = 50) -> dict:
        params = {"domain": domain, "path": path, "after": max(0, int(after)), "limit": max(1, min(int(limit), 200))}
        return self._call("GET", "documents/passages", email, params=params).json()

    def images(self, email: str, domain: str, path: str) -> list[dict]:
        return self._call("GET", "documents/images", email, params={"domain": domain, "path": path}).json().get("images", [])

    def image(self, email: str, domain: str, path: str, image_id: str) -> tuple[bytes, str]:
        r = self._call("GET", f"documents/images/{quote(image_id, safe='')}", email, params={"domain": domain, "path": path})
        return r.content, r.headers.get("Content-Type", "application/octet-stream").split(";")[0]

    # ── one call ─────────────────────────────────────────────────────
    def _call(self, method: str, route: str, email: str, **kw) -> requests.Response:
        if not self.key:
            raise KBError(503, "the knowledge base is not configured (no service key)")
        headers = {"Authorization": f"Bearer {self.key}", "X-On-Behalf-Of": email}
        pause = 1.0
        for attempt in range(RETRIES + 1):
            try:
                r = requests.request(method, f"{self.base}/{route}", headers=headers, timeout=TIMEOUT, **kw)
            except requests.RequestException as e:
                if attempt == RETRIES:
                    raise KBError(502, f"the knowledge base did not answer ({type(e).__name__})") from None
                time.sleep(pause)
                pause *= 2
                continue
            if r.status_code == 429 and attempt < RETRIES:
                wait = _seconds(r.headers.get("Retry-After"), pause)
                if wait > MAX_WAIT:
                    raise KBError(429, f"the knowledge base asks to wait {wait:.0f} s")
                time.sleep(wait)
                continue
            if r.status_code == 502 and attempt < RETRIES:
                time.sleep(pause)
                pause *= 2
                continue
            if r.status_code >= 400:
                raise KBError(r.status_code, _detail(r))
            return r
        raise KBError(502, "the knowledge base did not answer")


def _seconds(value: str | None, default: float) -> float:
    try:
        return max(0.0, float(value)) if value is not None else default
    except ValueError:
        return default


def _detail(r: requests.Response) -> str:
    try:
        d = r.json().get("detail")
    except ValueError:
        d = None
    if isinstance(d, list):  # a 422: which fields
        d = "; ".join(str(x.get("msg", x)) for x in d if isinstance(x, dict)) or str(d)
    return str(d or f"HTTP {r.status_code}")
