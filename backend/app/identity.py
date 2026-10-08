"""Who is calling (technical design section 1.1), as Cortex does it (cortex/server/identity.py, config.py, live.py):
the domain proxy signs people in with Microsoft Entra ID and forwards their address in X-Auth-Request-Email, plus a
shared secret in X-Slides-Proxy-Secret without which nothing is trusted. On the socket.io route it also forwards the
Microsoft Graph access token (X-Access-Token) and the ID token (X-Id-Token), used only for the person's own name and
photo and for the sign-out hint."""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

import requests
from fastapi import HTTPException, Request

from .config import Settings

log = logging.getLogger("slides.identity")

SECRET_HEADER = "x-slides-proxy-secret"  # noqa: S105 - a header name, not a secret
EMAIL_HEADER = "x-auth-request-email"


@dataclass(frozen=True)
class User:
    email: str
    is_admin: bool


def proxy_secret_ok(settings: Settings, value: str | None) -> bool:
    """True when the request came through the proxy (or no secret is configured: development only)."""
    if not settings.proxy_secret:
        return True
    # in constant time (security review L3: == returns at the first differing character)
    return value is not None and hmac.compare_digest(value.encode(), settings.proxy_secret.encode())


def origin_allowed(settings: Settings, origin: str | None) -> bool:
    """May a browser page at `origin` open the live connection (security review M1: no origin was checked, so any site
    a signed-in person visited could open it with their cookie)? public_url's own origin, and each allowed_origins
    entry: scheme://host[:port], an entry without a port matching that host on any port (a local install). A request
    with no Origin header is no browser page and is not refused here (the proxy secret and identity still apply)."""
    if not origin:
        return True
    from urllib.parse import urlsplit

    try:
        got = urlsplit(origin.strip().lower())
        got_port = got.port
    except ValueError:
        return False
    for entry in [settings.file["public_url"], *settings.file.get("allowed_origins", [])]:
        want = urlsplit(entry.strip().lower())
        if want.scheme != got.scheme or want.hostname != got.hostname:
            continue
        if want.port is None and urlsplit(entry).netloc.count(":") == 0 and entry != settings.file["public_url"]:
            return True  # no port given: any port of that host
        default = {"http": 80, "https": 443}.get(got.scheme)
        if (want.port or default) == (got_port or default):
            return True
    return False


def address_of(settings: Settings, header_value: str | None) -> str | None:
    """The signed-in address, lower case; in development without a secret, SLIDES_DEV_USER stands in for it."""
    email = (header_value or "").strip().lower()
    if not email and not settings.proxy_secret and settings.dev_user:
        email = settings.dev_user
    return email or None


def user_of(settings: Settings, email: str) -> User:
    return User(email=email, is_admin=email in settings.administrators)


def current_user(request: Request) -> User:
    """FastAPI dependency: the signed-in person, or 401. (The proxy-secret middleware has already run.)"""
    settings: Settings = request.app.state.settings
    email = address_of(settings, request.headers.get(EMAIL_HEADER))
    if not email:
        raise HTTPException(401, "not signed in: the proxy forwards no identity")
    return user_of(settings, email)


def sign_out_url(template: str, id_token: str) -> str:
    """Slides: Cortex's _sign_out_url (cortex/server/identity.py), unchanged in behaviour. The configured sign-out
    address with its placeholders filled from the person's ID token, each URL-encoded for a provider's sign-out address
    carried inside the proxy's rd= address:
      {logout_hint}    `&logout_hint=<the token's login_hint claim>`: what Microsoft Entra ID needs to end the session
                       without asking which account
      {id_token_hint}  `&id_token_hint=<the ID token>`: the OpenID Connect standard hint
    Without a token, or without the claim, a placeholder becomes nothing (the provider then asks)."""
    ok = bool(id_token) and all(c.isalnum() or c in "-_." for c in id_token) and id_token.count(".") == 2
    hint = ""
    if ok:
        try:
            body = id_token.split(".")[1]
            hint = str(json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))).get("login_hint") or "")
        except (ValueError, UnicodeDecodeError):
            hint = ""
    twice = quote(quote(hint, safe=""), safe="")
    return template.replace("{logout_hint}", f"%26logout_hint%3D{twice}" if hint else "").replace(
        "{id_token_hint}", f"%26id_token_hint%3D{id_token}" if ok else ""
    )


class Profiles:
    """The person's name and photo from the OpenID Connect UserInfo endpoint and Microsoft Graph, with the access token
    the proxy forwards; cached 15 minutes per token; any failure degrades to {} (the page then shows the address and
    initials). Slides: Cortex's IdentityMixin._userinfo_of as a class."""

    def __init__(self, settings: Settings) -> None:
        ident = settings.file["identity"]
        self.userinfo_url = ident["userinfo_url"]
        self.photo_url = ident["photo_url"]
        self.enabled = ident.get("profile", True)
        self._cache: dict[str, tuple[float, dict]] = {}

    def _fetch(self, token: str) -> dict:
        r = requests.get(self.userinfo_url, headers={"Authorization": f"Bearer {token}"}, timeout=5)
        if r.status_code >= 400:
            log.warning("userinfo answered HTTP %s", r.status_code)
            return {}
        body = r.json()
        if self.photo_url:
            # the photo needs the token to be read (Microsoft Graph): downloaded here and handed to the page as data,
            # never as that address. No photo (404) or too large: the page shows the initials.
            body.pop("picture", None)
            ph = requests.get(self.photo_url, headers={"Authorization": f"Bearer {token}"}, timeout=5)
            kind = ph.headers.get("content-type", "").split(";")[0].strip()
            if ph.status_code == 200 and kind.startswith("image/") and len(ph.content) <= 200_000:
                body["picture"] = f"data:{kind};base64,{base64.b64encode(ph.content).decode()}"
        return body

    async def of(self, token: str) -> dict:
        if not token or not self.enabled:
            return {}
        now = time.time()
        hit = self._cache.get(token)
        if hit and hit[0] > now:
            return hit[1]
        try:
            info = await asyncio.to_thread(self._fetch, token)
        except Exception as ex:  # noqa: BLE001 - decoration, never fatal
            log.warning("userinfo failed: %s", type(ex).__name__)
            info = {}
        if len(self._cache) > 256:
            self._cache.clear()
        self._cache[token] = (now + 900, info)
        return info
