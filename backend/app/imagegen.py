"""Image generation (spec IM-6): the environment's text-to-image service, as tti_server serves it (POST /api/generate
-> {id}; GET /api/stream/{id}, server-sent events "progress", then "done" or "failed"; GET /api/image/{id} -> PNG).
Off unless `services.image_generation` is configured: the tool is then not offered."""

from __future__ import annotations

import json
import logging

import requests

log = logging.getLogger("slides.imagegen")
SIZES = {"square": (1024, 1024), "wide": (1344, 768), "tall": (768, 1344)}
WAIT_SECONDS = 180  # a generation's longest wait (a 4-step model takes seconds; the GPU may be busy)


class ImageGenError(Exception):
    pass


class ImageGenerator:
    def __init__(self, base_url: str | None) -> None:
        self.base = (base_url or "").rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self.base)

    def generate(self, prompt: str, shape: str = "wide") -> bytes:
        """The picture's PNG bytes; ImageGenError with the service's own words when it fails."""
        if not self.available:
            raise ImageGenError("no image-generation service is configured")
        width, height = SIZES.get(shape, SIZES["wide"])
        try:
            r = requests.post(f"{self.base}/api/generate", json={"prompt": prompt, "width": width, "height": height}, timeout=30)
            r.raise_for_status()
            job = r.json()["id"]
            with requests.get(f"{self.base}/api/stream/{job}", stream=True, timeout=(10, WAIT_SECONDS)) as events:
                events.raise_for_status()
                event = None
                for line in events.iter_lines(decode_unicode=True):
                    if line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:") and event in ("done", "failed"):
                        data = json.loads(line.split(":", 1)[1])
                        if event == "failed":
                            raise ImageGenError(str(data.get("message") or "the service failed"))
                        break
                else:
                    raise ImageGenError("the service ended without a picture")
            img = requests.get(f"{self.base}/api/image/{job}", timeout=30)
            img.raise_for_status()
        except requests.RequestException as e:
            raise ImageGenError(f"the image service did not answer ({type(e).__name__})") from None
        except (KeyError, ValueError) as e:
            raise ImageGenError(f"the image service answered unexpectedly ({type(e).__name__})") from None
        log.info("image generated", extra={"byteCount": len(img.content), "promptLength": len(prompt)})
        return img.content
