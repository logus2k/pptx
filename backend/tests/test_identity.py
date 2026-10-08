"""Identity from the proxy (technical design section 1.1): the shared secret, the address, administrators, the page."""

from __future__ import annotations

import base64
import json

import pytest
import requests
import socketio

from app import config, identity

from .conftest import ADMIN, SECRET


def proxied(email: str | None = None, secret: str | None = SECRET) -> dict:
    h = {}
    if secret is not None:
        h["X-Slides-Proxy-Secret"] = secret
    if email is not None:
        h["X-Auth-Request-Email"] = email
    return h


def test_request_without_the_secret_is_refused(server):
    r = requests.get(f"{server}/api/me", headers=proxied("ana@example.com", secret=None), timeout=5)
    assert r.status_code == 401
    assert r.json() == {"detail": "not through the proxy"}
    r = requests.get(f"{server}/api/me", headers=proxied("ana@example.com", secret="wrong"), timeout=5)
    assert r.status_code == 401


def test_page_and_static_files_also_need_the_secret(server):
    assert requests.get(f"{server}/", timeout=5).status_code == 401
    assert requests.get(f"{server}/static/css/tokens.css", timeout=5).status_code == 401


def test_health_needs_no_secret(server):
    r = requests.get(f"{server}/api/health", timeout=5)
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_me_is_the_forwarded_address_lower_case(server):
    r = requests.get(f"{server}/api/me", headers=proxied("Ana.Costa@Example.com"), timeout=5)
    assert r.status_code == 200
    assert r.json() == {"email": "ana.costa@example.com", "is_admin": False}


def test_administrators_are_recognised_whatever_the_case(server):
    r = requests.get(f"{server}/api/me", headers=proxied(ADMIN), timeout=5)
    assert r.json() == {"email": ADMIN, "is_admin": True}


def test_no_identity_is_401(server):
    r = requests.get(f"{server}/api/me", headers=proxied(None), timeout=5)
    assert r.status_code == 401


def test_page_routes_answer_index_html_with_the_base_path(server):
    for path in ("/", "/projects/abc", "/projects/abc/decks/def"):
        r = requests.get(f"{server}{path}", headers={**proxied("ana@example.com"), "X-Forwarded-Prefix": "/slides"}, timeout=5)
        assert r.status_code == 200, path
        assert '<base href="/slides/">' in r.text, path
    r = requests.get(f"{server}/projects/abc", headers=proxied("ana@example.com"), timeout=5)
    assert '<base href="/">' in r.text  # reached directly: the root


def test_base_path_accepts_only_plain_segments():
    from app.main import base_path

    assert base_path("/slides") == "/slides/"
    assert base_path("/slides/") == "/slides/"
    assert base_path("/a/b-c_d") == "/a/b-c_d/"
    assert base_path(None) == "/"
    assert base_path('/x"><script>') == "/"
    assert base_path("/sl ides") == "/"


def test_unknown_api_route_is_404_not_the_page(server):
    r = requests.get(f"{server}/api/nope", headers=proxied("ana@example.com"), timeout=5)
    assert r.status_code == 404


def test_socket_connection_needs_the_secret_and_an_identity(server):
    refused = socketio.Client()
    with pytest.raises(socketio.exceptions.ConnectionError):
        refused.connect(server, headers=proxied("ana@example.com", secret="wrong"), transports=["websocket"])
    anonymous = socketio.Client()
    with pytest.raises(socketio.exceptions.ConnectionError):
        anonymous.connect(server, headers=proxied(None), transports=["websocket"])


def test_whoami_over_socket(server):
    sio = socketio.Client()
    sio.connect(server, headers=proxied("Ana@Example.com"), transports=["websocket"])
    try:
        me = sio.call("whoami", {}, timeout=5)
    finally:
        sio.disconnect()
    assert me["authenticated"] is True
    assert me["email"] == "ana@example.com"
    assert me["name"] == "ana"  # no profile lookup in tests: the start of the address
    assert me["is_admin"] is False
    assert me["signOutUrl"].startswith("/oauth2-entra/sign_out?rd=")


def test_dev_user_only_without_a_secret(make_settings):
    s = make_settings(SLIDES_PROXY_SECRET=None, SLIDES_DEV_USER="dev@example.com")
    assert identity.address_of(s, None) == "dev@example.com"
    s = make_settings(SLIDES_DEV_USER="dev@example.com")  # with a secret: no stand-in
    assert identity.address_of(s, None) is None


def test_production_refuses_no_secret_or_a_dev_user(make_settings):
    with pytest.raises(config.ConfigError):
        make_settings(SLIDES_ENV="prod", SLIDES_PROXY_SECRET=None)
    with pytest.raises(config.ConfigError):
        make_settings(SLIDES_ENV="prod", SLIDES_DEV_USER="dev@example.com")


def _jwt(claims: dict) -> str:
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{part}.sig"


def test_sign_out_url_carries_the_login_hint():
    template = "/oauth2-entra/sign_out?rd=x{logout_hint}"
    assert identity.sign_out_url(template, _jwt({"login_hint": "a b"})) == "/oauth2-entra/sign_out?rd=x%26logout_hint%3Da%2520b"
    assert identity.sign_out_url(template, "") == "/oauth2-entra/sign_out?rd=x"
    assert identity.sign_out_url(template, "not-a-token") == "/oauth2-entra/sign_out?rd=x"


def test_only_the_apps_own_pages_and_a_local_install_may_open_the_live_connection(make_settings):
    """Security review M1: no origin was checked, so any site a signed-in person visited could open the assistant's
    connection with their cookie. Allowed: public_url's origin, and localhost / 127.0.0.1 on any port (a laptop install)."""
    from app.identity import origin_allowed

    settings = make_settings()
    for ok in ("https://logus2k.com", "https://LOGUS2K.com", "http://localhost:2720", "http://localhost:5173",
               "http://127.0.0.1:8080", "http://localhost", None, ""):  # fmt: skip
        assert origin_allowed(settings, ok), ok
    for bad in ("https://evil.example", "http://logus2k.com", "https://logus2k.com:8443", "https://logus2k.com.evil.example",
                "https://localhost:2720", "http://localhost.evil.example", "null", "not a url:99999"):  # fmt: skip
        assert not origin_allowed(settings, bad), bad


def test_a_page_of_another_site_cannot_open_the_live_connection(server):
    """The handshake as a browser makes it, one Origin header (socketio.Client adds its own beside one given)."""
    import websocket

    from .conftest import SECRET

    url = server.replace("http://", "ws://") + "/socket.io/?EIO=4&transport=websocket"
    headers = [f"X-Slides-Proxy-Secret: {SECRET}", "X-Auth-Request-Email: ana@example.com"]
    for origin, allowed in (("https://logus2k.com", True), ("http://localhost:5173", True), ("https://evil.example", False)):
        try:
            ws = websocket.create_connection(url, header=headers, origin=origin, timeout=5)
            opened = ws.recv().startswith("0")  # Engine.IO's open packet
            ws.close()
        except websocket.WebSocketException:
            opened = False
        assert opened == allowed, origin


def test_local_mode_runs_only_on_localhost_with_its_person_and_no_proxy(make_settings, tmp_path):
    """Security review L4, the user's choice: a Slides on a person's own computer (SLIDES_ENV=local), reached at
    localhost, without a proxy; an unknown SLIDES_ENV is refused. (Messages checked as plain substrings.)"""
    import json

    from app import config

    def refused(**env) -> str:
        with pytest.raises(config.ConfigError) as e:
            config.load(env)
        return str(e.value)

    make_settings()  # writes tmp_path/config.json (public_url on logus2k.com)
    path = tmp_path / "config.json"
    base = {"SLIDES_ENV": "local", "SLIDES_CONFIG_FILE": str(path), "SLIDES_DATA_DIR": str(tmp_path / "d"),
            "SLIDES_DEV_USER": "ana@example.com"}  # fmt: skip
    assert "localhost" in refused(**base)
    data = json.loads(path.read_text())
    data["public_url"] = "http://localhost:2720/"
    path.write_text(json.dumps(data))
    s = config.load(base)
    assert s.env == "local" and s.dev_user == "ana@example.com"
    assert "SLIDES_DEV_USER" in refused(**{**base, "SLIDES_DEV_USER": ""})
    assert "no proxy" in refused(**{**base, "SLIDES_PROXY_SECRET": "x"})
    assert "SLIDES_ENV must be one of" in refused(**{**base, "SLIDES_ENV": "production"})
