"""What the pictures in a project's decks show (spec IM-4: "the slide with the factory photo" resolves), by the
model's vision: each new image described once, in one sentence, in the background after a version is published
(the renderer's warm-up calls it), one image at a time - the local model is shared. Kept per project by the image's
hash (descriptions.json): the same picture in another deck or version is not described again."""

from __future__ import annotations

import asyncio
import base64
import io
import logging

from PIL import Image

from . import storage
from .docengine import read
from .storage import NotFound

log = logging.getLogger("slides.describe")
PER_VERSION = 20  # new images described per published version; the rest at the next
SIDE = 768  # pixels: the image is made smaller before it is sent
PROMPT = (
    "Describe this image in one short sentence, in European Portuguese, saying what it shows (objects, people, "
    "places, kind of chart), so it can be found later. Only the sentence."
)


class Descriptions:
    def __init__(self, layout: storage.Layout) -> None:
        self.layout = layout

    def _path(self, pid: str):
        return self.layout.project(pid) / "descriptions.json"

    def all(self, pid: str) -> dict[str, str]:
        try:
            return {k: v["text"] for k, v in storage.read_json(self._path(pid))["images"].items()}
        except NotFound:
            return {}

    async def put(self, pid: str, sha: str, text: str) -> None:
        async with storage.lock(pid):
            try:
                images = storage.read_json(self._path(pid))["images"]
            except NotFound:
                images = {}
            images[sha] = {"text": text[:400], "at": storage.now()}
            storage.write_json(self._path(pid), {"schema_version": 1, "images": images}, "descriptions")


def _small(blob: bytes) -> str:
    img = Image.open(io.BytesIO(blob))
    img.thumbnail((SIDE, SIDE))
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


class Describer:
    def __init__(self, app) -> None:
        self.app = app
        self.descriptions = Descriptions(app.layout)
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    def warm(self, pid: str, data: bytes) -> None:
        task = asyncio.create_task(self._run(pid, data))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, pid: str, data: bytes) -> None:
        async with self._lock:
            try:
                images = await asyncio.to_thread(read.pictures, data)
                known = self.descriptions.all(pid)
                new = [(sha, blob) for sha, blob in images.items() if sha not in known][:PER_VERSION]
                if not new:
                    return
                project = storage.read_json(self.app.layout.project(pid) / "project.json")
                model = await asyncio.to_thread(self.app.models.resolve, project["settings"].get("model"))
                if not await asyncio.to_thread(self.app.models.vision, model):
                    return
                for sha, blob in new:
                    text = await self._describe(model, blob)
                    if text:
                        await self.descriptions.put(pid, sha, text)
                log.info("pictures described", extra={"images": len(new)})
            except Exception as e:  # noqa: BLE001 - background work: a failure leaves the pictures undescribed
                log.warning("pictures not described", extra={"err.type": type(e).__name__})  # the type only (security review L5)

    async def _describe(self, model: dict, blob: bytes) -> str:
        try:
            url = await asyncio.to_thread(_small, blob)
        except Exception:  # noqa: BLE001 - an image Pillow cannot open (an EMF, an SVG kept as such)
            return ""
        messages = [
            {"role": "user", "content": [{"type": "text", "text": PROMPT}, {"type": "image_url", "image_url": {"url": url}}]}
        ]
        text = ""
        async for chunk in self.app.models.stream(model, "slides_describer", messages, None):
            text += ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
        return " ".join(text.split())
