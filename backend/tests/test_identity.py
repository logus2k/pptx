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
