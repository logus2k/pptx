"""The real app with a scripted model, for the browser checks (technical design section 12: e2e never calls a real model).
The script is a JSON file (FAKE_SCRIPT) the browser test writes before each turn: a list of steps, each {"text"} or
{"tools": [[name, args], ...]}; each completion takes the next step. Run inside the test image, where LibreOffice renders:
  docker run --rm -d -p 2722:2722 -v $PWD:/src -w /src -e FAKE_SCRIPT=/src/tests/e2e/out/script.json slides-test \
      python tests/e2e/fake_app.py"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import config, telemetry  # noqa: E402

telemetry.setup("e2e")
from app import main  # noqa: E402

sys.path.insert(0, str(ROOT / "backend"))
from tests.fakes import FakeKB, FakeModels  # noqa: E402

SCRIPT = Path(os.environ.get("FAKE_SCRIPT", "/tmp/fake-script.json"))  # noqa: S108


class FileScript(FakeModels):
    """FakeModels whose next step is read from the script file each time (the test rewrites it per turn)."""

    async def stream(self, model, preset, messages, tools, max_tokens=None):
        # only the assistant's calls take a step: the router, the describer and the summariser answer by themselves
        # (FakeModels), so a turn's routing never eats the step its test wrote for the assistant
        if preset == "slides_assistant":
            steps = json.loads(SCRIPT.read_text()) if SCRIPT.exists() else []
            self.script = [
                {"text": s["text"]} if "tools" not in s else {"text": s.get("text"), "tools": [tuple(t) for t in s["tools"]]}
                for s in steps
            ]
            async for chunk in super().stream(model, preset, messages, tools, max_tokens):
                yield chunk
            SCRIPT.write_text(json.dumps(steps[1:]))
            return
        async for chunk in super().stream(model, preset, messages, tools, max_tokens):
            yield chunk


OUT = ROOT / "tests" / "e2e" / "out"


class HeardStt:
    """stt_server for the voice checks: the words of tests/e2e/out/stt.txt, but only for audio that was heard (half a
    second at least, above -50 dBFS: the browser's microphone really streamed); each request kept in stt.json."""

    async def transcribe(self, pcm16: bytes, language, prompt=None, timeout: float = 60):
        import numpy as np

        x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float64) / 32768.0
        dbfs = float(10 * np.log10((x**2).mean() + 1e-12)) if len(x) else -120.0
        seen = json.loads((OUT / "stt.json").read_text()) if (OUT / "stt.json").exists() else []
        seen.append({"seconds": round(len(x) / 16000, 2), "dbfs": round(dbfs, 1), "language": language, "prompt": prompt})
        (OUT / "stt.json").write_text(json.dumps(seen, ensure_ascii=False))
        if len(x) < 8000 or dbfs < -50:
            return {"text": "", "rejected": "silence"}
        return {
            "text": (OUT / "stt.txt").read_text(encoding="utf-8").strip() if (OUT / "stt.txt").exists() else "",
            "rejected": None,
        }


def fake_tts():
    """tts_server for the voice checks, at /tts/socket.io as the domain proxy serves it: what it is asked to say is kept
    in tts.json, and each request is answered with a WAV of 3 s (a tone: long enough to interrupt)."""
    import io
    import wave

    import numpy as np
    import socketio

    sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
    voices: dict[str, str] = {}
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        t = np.arange(int(3 * 24000)) / 24000
        w.writeframes((np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16).tobytes())
    clip = buf.getvalue()

    def keep(entry: dict) -> None:
        seen = json.loads((OUT / "tts.json").read_text()) if (OUT / "tts.json").exists() else []
        seen.append(entry)
        (OUT / "tts.json").write_text(json.dumps(seen, ensure_ascii=False))

    @sio.event
    async def tts_configure_client(sid, data):
        voices[sid] = (data or {}).get("voice")

    @sio.event
    async def tts_text_chunk(sid, data):
        keep({"text": (data or {}).get("chunk"), "voice": voices.get(sid)})
        await sio.emit("tts_audio_chunk", {"audio_buffer": clip}, to=sid)
        await sio.emit("tts_response_complete", {}, to=sid)

    @sio.event
    async def stop_generation(sid, data=None):
        keep({"stop": True})

    return socketio.ASGIApp(sio, socketio_path="tts/socket.io")


data = Path(tempfile.mkdtemp(prefix="slides-e2e-"))
cfg = json.loads((ROOT / "config" / "config.json").read_text())
cfg["templates_dir"] = str(ROOT / "templates")
cfg["identity"]["profile"] = False
cfg["administrators"] = ["admin@example.com"]  # the administration's checks (m8admin.mjs); never the real addresses
(data / "config.json").write_text(json.dumps(cfg))
settings = config.load(
    {
        "SLIDES_CONFIG_FILE": str(data / "config.json"),
        "SLIDES_DATA_DIR": str(data / "data"),
        "SLIDES_FRONTEND_DIR": str(ROOT / "frontend"),
        "SLIDES_PORT": "2722",
        "SLIDES_PROXY_SECRET": os.environ.get("SLIDES_PROXY_SECRET", "e2e-secret"),
    }
)
import uvicorn  # noqa: E402

slides = telemetry.instrument_asgi(main.create_app(settings, models=FileScript(), kb=FakeKB(), stt=HeardStt()))
speech_out = fake_tts()


async def combined(scope, receive, send):
    """The app, and the speech service at the domain's /tts/socket.io (as the proxy has it)."""
    if scope["type"] in ("http", "websocket") and scope["path"].startswith("/tts/socket.io"):
        return await speech_out(scope, receive, send)
    return await slides(scope, receive, send)


uvicorn.run(
    combined,
    host="0.0.0.0",  # noqa: S104 - inside its container, published on the host's 2722 only
    port=2722,
    log_level="warning",
    log_config=None,
)
