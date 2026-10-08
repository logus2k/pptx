"""Speech to text (technical design section 7; spec VO-1, VO-5): a spoken request, recorded in the browser (PCM16,
16 kHz, mono), transcribed by Whisper on stt_server, as Cortex does (cortex/transcription/refine.py SttClient and
raised(), cortex/server/assistant.py _voice_text). The audio is kept in memory only (spec section 8, Privacy).

stt_server's `transcribe` call: {audio, language (a Whisper code, or None to detect), prompt (preceding context: a
vocabulary)} -> {text, rejected}. It rejects clips under -45 dBFS as silence, so the recording is raised first."""

from __future__ import annotations

import asyncio
import logging

import numpy as np
import socketio

log = logging.getLogger("slides.speech")
SAMPLE_RATE = 16000
MAX_SECONDS = 120  # a request is seconds: a longer recording is refused, never cut (the page stops at this length)
TARGET_DBFS = -20.0  # Cortex's: speech raised to this level, at most MAX_GAIN_DB, never lowered
MAX_GAIN_DB = 40.0


class SttClient:
    """One socket.io connection to stt_server, shared; requests one at a time (stt_server's workers are shared with
    the other applications)."""

    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self._client: socketio.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def transcribe(self, pcm16: bytes, language: str | None, prompt: str | None = None, timeout: float = 60) -> dict | None:
        """{"text", "rejected"}, or None when stt_server cannot be reached."""
        if not self.url:
            return None
        async with self._lock:
            try:
                if self._client is None or not self._client.connected:
                    self._client = socketio.AsyncClient(reconnection=False)
                    await self._client.connect(self.url, transports=["websocket"], wait_timeout=10)
                request = {"audio": pcm16, "language": language, "words": False}
                if prompt:
                    request["prompt"] = prompt
                return await self._client.call("transcribe", request, timeout=timeout)
            except Exception as e:  # noqa: BLE001 - unreachable, timeout, disconnect
                log.warning("stt_server unavailable", extra={"err.type": type(e).__name__})  # the type only (security review L5)
                client, self._client = self._client, None
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception as e2:  # noqa: BLE001 - it is being dropped anyway
                        log.debug(f"stt_server disconnect: {type(e2).__name__}")
                return None


def raised(pcm: bytes) -> tuple[bytes, float]:
    """Cortex's raised(): the 90th-percentile 100 ms level to TARGET_DBFS (at most MAX_GAIN_DB, never lowered), with
    a soft limiter. Returns (PCM16, gain in dB)."""
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    f = SAMPLE_RATE // 10
    if len(x) < f:
        return pcm, 0.0
    levels = 10 * np.log10((x[: len(x) // f * f].reshape(-1, f).astype(np.float64) ** 2).mean(1) + 1e-12)
    gain = float(np.clip(TARGET_DBFS - np.percentile(levels, 90), 0.0, MAX_GAIN_DB))
    if gain < 1.0:
        return pcm, 0.0
    y = np.tanh(x * 10 ** (gain / 20)) * 0.9
    return (y * 32767).astype(np.int16).tobytes(), gain


def _worded(text: str) -> bool:
    return any(c.lower() != c.upper() for c in text)


async def voice_text(stt, pcm16: bytes, language: str, prompt: str | None = None) -> tuple[str, str | None]:
    """The words of a spoken request: (text, error). `language`: "pt", "en" (or a regional code). As Cortex: held to
    the person's language, Whisper writes only marks when they spoke another one (measured in Cortex: English speech
    held to Portuguese gave '.....' in 20 of 20); then it is asked again with the language detected."""
    if len(pcm16) < SAMPLE_RATE * 2 // 4:  # under a quarter of a second: nothing was said
        return "", None
    if len(pcm16) > MAX_SECONDS * SAMPLE_RATE * 2:
        return "", f"the recording is longer than {MAX_SECONDS // 60} minutes: say it in parts"
    code = language.split("-")[0].lower() if language else None
    audio, gain = raised(pcm16)
    answer = await stt.transcribe(audio, code, prompt)
    if answer is None:
        return "", "the speech recogniser (stt_server) is not reachable"
    text = "" if answer.get("rejected") else (answer.get("text") or "").strip()
    if code and not answer.get("rejected") and not _worded(text):
        answer = await stt.transcribe(audio, None, prompt) or {}
        text = "" if answer.get("rejected") else (answer.get("text") or "").strip()
    log.info("voice text", extra={"seconds": round(len(pcm16) / SAMPLE_RATE / 2, 1), "gainDb": round(gain), "chars": len(text)})
    return text, None
