"""Speech (M5; technical design section 7): the level a recording is raised to, the transcription's language retry,
the socket.io round trip with the scripted recogniser, and the real client against a stand-in stt_server."""

from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
import pytest
import socketio
import uvicorn

from app import speech

from .test_agent import Chat, setup


def tone(seconds: float, dbfs: float) -> bytes:
    t = np.arange(int(seconds * speech.SAMPLE_RATE)) / speech.SAMPLE_RATE
    x = np.sin(2 * np.pi * 220 * t) * 10 ** (dbfs / 20) * np.sqrt(2)
    return (x * 32767).astype(np.int16).tobytes()


def level(pcm: bytes) -> float:
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) / 32768.0
    return 10 * np.log10((x**2).mean() + 1e-12)


def test_a_quiet_recording_is_raised_and_a_loud_one_left_alone():
    quiet, gain = speech.raised(tone(1, -60))
    assert gain > 30 and level(quiet) > -30  # stt_server rejects clips under -45 dBFS
    loud = tone(1, -18)
    assert speech.raised(loud) == (loud, 0.0)


class Answers:
    def __init__(self, *answers) -> None:
        self.answers, self.calls = list(answers), []

    async def transcribe(self, pcm16, language, prompt=None, timeout=60):
        self.calls.append(language)
        return self.answers.pop(0)


def test_marks_only_in_the_persons_language_are_asked_again_with_the_language_detected():
    stt = Answers({"text": ".....", "rejected": None}, {"text": "make the title bigger", "rejected": None})
    assert asyncio.run(speech.voice_text(stt, tone(2, -20), "pt")) == ("make the title bigger", None)
    assert stt.calls == ["pt", None]


def test_too_short_too_long_and_unreachable():
    assert asyncio.run(speech.voice_text(Answers(), tone(0.1, -20), "pt")) == ("", None)  # nothing said
    text, error = asyncio.run(speech.voice_text(Answers(), b"\0\0" * speech.SAMPLE_RATE * (speech.MAX_SECONDS + 1), "pt"))
    assert text == "" and "longer than 2 minutes" in error  # refused, never cut
    text, error = asyncio.run(speech.voice_text(Answers(None), tone(1, -20), "en"))
    assert text == "" and "not reachable" in error


def test_a_spoken_request_comes_back_as_text_for_the_composer(server, fake_stt):
    pid, did, cid = setup(server)
    chat = Chat(server, pid, cid)
    heard = threading.Event()
    got = {}

    def on(data):
        got.update(data)
        heard.set()

    chat.sio.on("voice_text", on)
    try:
        assert chat.sio.call("voice_begin", {"project_id": pid, "deck_id": did, "language": "en"}, timeout=10)["ok"]
        audio = tone(1.5, -25)
        for i in range(0, len(audio), 3200):  # 100 ms packets, as the page's worklet sends them
            chat.sio.emit("voice_audio", audio[i : i + 3200])
        time.sleep(0.3)
        chat.sio.call("voice_end", {}, timeout=10)
        assert heard.wait(10)
    finally:
        chat.close()
    assert got == {"text": "muda o título do diapositivo dois"}
    call = fake_stt.calls[-1]
    assert call["bytes"] == len(audio) and call["language"] == "en"
    assert call["prompt"].startswith("Proposta para o Cliente X, Agenda, Antes e depois")  # the open deck's slide titles first
    assert assert_no_turn(chat)


def assert_no_turn(chat) -> bool:
    """A spoken request is only text for the composer: no message was sent, no turn started."""
    return not any(n in ("message", "turn_started") for n, _ in chat.events)


def test_the_end_without_a_beginning_is_said(server):
    pid, _, cid = setup(server, deck=None)
    chat = Chat(server, pid, cid)
    heard = threading.Event()
    got = {}
    chat.sio.on("voice_text", lambda d: (got.update(d), heard.set()))
    try:
        assert chat.sio.call("voice_end", {}, timeout=10) == {"ok": False}
        assert heard.wait(5)
    finally:
        chat.close()
    assert got == {"text": "", "error": "the microphone was not on"}


@pytest.fixture
def stand_in_stt():
    """A stand-in stt_server: socket.io with its `transcribe` call (stt_server.py's contract)."""
    sio = socketio.AsyncServer(async_mode="asgi")
    seen = []

    @sio.event
    async def transcribe(sid, data):
        seen.append({k: (len(v) if isinstance(v, bytes) else v) for k, v in data.items()})
        return {"text": "olá", "rejected": None}

    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(socketio.ASGIApp(sio), host="127.0.0.1", port=port, log_level="warning", log_config=None))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", seen
    srv.should_exit = True


def test_the_client_speaks_stt_servers_protocol(stand_in_stt):
    url, seen = stand_in_stt
    client = speech.SttClient(url)
    answer = asyncio.run(client.transcribe(b"\x01\x00" * 8000, "pt", "Agenda, Riscos"))
    assert answer == {"text": "olá", "rejected": None}
    assert seen == [{"audio": 16000, "language": "pt", "words": False, "prompt": "Agenda, Riscos"}]
    assert asyncio.run(speech.SttClient("http://127.0.0.1:1").transcribe(b"\0\0", "pt")) is None  # unreachable: None
