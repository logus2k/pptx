"""Writes fixtures/audio/: recorded spoken requests for the browser's microphone in the voice checks (technical design
section 12: E2E S3 "with recorded audio and fake speech clients"). Spoken once by tts_server (Kokoro) - the only
time a real speech service is used for the tests - as WAV, the format Chrome's fake microphone plays
(--use-file-for-fake-audio-capture). Run on the services' network:
  docker run --rm --network logus2k_network -v $PWD:/src -w /src slides-test python scripts/make_audio_fixtures.py"""

from __future__ import annotations

import asyncio
from pathlib import Path

import socketio

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "audio"
REQUESTS = {
    "s3-pt.wav": ("Aumenta o título do gráfico e lê-me o que está no diapositivo seguinte.", "pf_dora"),
}


async def speak(text: str, voice: str) -> bytes:
    chunks, done = [], asyncio.Event()
    client = socketio.AsyncClient(reconnection=False)
    cid = "slides-fixtures"
    client.on("tts_audio_chunk", lambda e: chunks.append(bytes(e.get("audio_buffer") or b"")))
    client.on("tts_response_complete", lambda *a: done.set())
    await client.connect(f"http://tts_server:7700?type=browser&format=binary&main_client_id={cid}", transports=["websocket"])
    await client.emit(
        "register_audio_client", {"main_client_id": cid, "connection_type": "browser", "mode": "tts", "format": "binary"}
    )
    await client.emit("tts_configure_client", {"client_id": cid, "voice": voice, "speed": 1.0})
    await client.emit("tts_text_chunk", {"chunk": text, "target_client_id": cid, "final": True})
    await asyncio.wait_for(done.wait(), 60)
    await client.disconnect()
    if len(chunks) != 1 or not chunks[0].startswith(b"RIFF"):
        raise SystemExit(f"expected one WAV from tts_server, got {len(chunks)} chunks")
    return chunks[0]


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (text, voice) in REQUESTS.items():
        (OUT / name).write_bytes(await speak(text, voice))
        print(f"wrote fixtures/audio/{name}: {text}")


if __name__ == "__main__":
    asyncio.run(main())
