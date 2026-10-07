"""Shared fixtures: a configuration in a temporary directory and the real server on a free port."""

from __future__ import annotations

import json
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from app import config, main, telemetry

REPO = Path(__file__).resolve().parents[2]
SECRET = "test-proxy-secret"
ADMIN = "admin@example.com"


def _config_file(tmp: Path) -> Path:
    data = json.loads((REPO / "config" / "config.json").read_text(encoding="utf-8"))
    data["administrators"] = [ADMIN.upper()]  # case must not matter
    data["identity"]["profile"] = False  # never call Microsoft from tests
    # the administrator templates: the plain one only, as the default (the tests never depend on an organisation's)
    (tmp / "templates").mkdir(exist_ok=True)
    shutil.copy(REPO / "templates" / "default.pptx", tmp / "templates" / "default.pptx")
    listing = json.loads((REPO / "templates" / "templates.json").read_text(encoding="utf-8"))
    plain = [{**t, "default": True} for t in listing["templates"] if t["id"] == "default"]
    (tmp / "templates" / "templates.json").write_text(json.dumps({**listing, "templates": plain}), encoding="utf-8")
    data["templates_dir"] = str(tmp / "templates")
    path = tmp / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def make_settings(tmp_path):
    """Settings over a temporary DATA_DIR and a copy of the real frontend, with the given environment overrides."""
    frontend = tmp_path / "frontend"
    shutil.copytree(REPO / "frontend", frontend)

    def make(**env):
        base = {
            "SLIDES_CONFIG_FILE": str(_config_file(tmp_path)),
            "SLIDES_DATA_DIR": str(tmp_path / "data"),
            "SLIDES_FRONTEND_DIR": str(frontend),
            "SLIDES_PROXY_SECRET": SECRET,
        }
        base.update({k: v for k, v in env.items() if v is not None})
        for k in [k for k, v in env.items() if v is None]:
            base.pop(k, None)
        return config.load(base)

    return make


@pytest.fixture
def fake_model():
    """The scripted model the server uses (tests set its script before a turn)."""
    from .fakes import FakeModels

    return FakeModels()


@pytest.fixture
def fake_kb():
    """The knowledge base the server uses (fixture documents; every call recorded with its address)."""
    from .fakes import FakeKB

    return FakeKB()


@pytest.fixture
def fake_stt():
    """The speech recogniser the server uses (records the audio's length, language and vocabulary)."""
    from .fakes import FakeStt

    return FakeStt()


@pytest.fixture
def fake_reranker():
    from .fakes import FakeReranker

    return FakeReranker()


@pytest.fixture
def fake_imagegen():
    """An image-generation service, off unless a test turns it on (spec IM-6)."""
    from .fakes import FakeImageGen

    return FakeImageGen()


@pytest.fixture
def server(make_settings, fake_model, fake_kb, fake_stt, fake_reranker, fake_imagegen):
    """The real ASGI app served by uvicorn on a free port, in a thread, with the scripted model; yields its base URL."""
    telemetry.setup("test")
    settings = make_settings()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(
        uvicorn.Config(
            telemetry.instrument_asgi(
                main.create_app(
                    settings, models=fake_model, kb=fake_kb, stt=fake_stt, reranker=fake_reranker, imagegen=fake_imagegen
                )
            ),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            log_config=None,
        )
    )
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started, "the server did not start"
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)
