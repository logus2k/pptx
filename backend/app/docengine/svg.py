"""SVG images become PNG (spec IM-1), by LibreOffice (already here for rendering: no new dependency). An SVG can
name other files or addresses, and declare entities: a converter that followed them would read the server's files or
call other services, so such an SVG is refused first. Allowed references: inside the file (#id) and data: URIs."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024


class SvgRefused(Exception):
    pass


def is_svg(raw: bytes) -> bool:
    head = raw[:4096].lstrip().lower()
    return head.startswith((b"<?xml", b"<svg", b"<!--")) and b"<svg" in head


def _references(text: str) -> list[str]:
    """The values of every href / xlink:href attribute (plain string search: lexical facts about the file)."""
    out, lower, at = [], text.lower(), 0
    while True:
        at = lower.find("href", at)
        if at < 0:
            return out
        rest = text[at + 4 :].lstrip()
        at += 4
        if not rest.startswith("="):
            continue
        rest = rest[1:].lstrip()
        if rest[:1] in ("'", '"'):
            end = rest.find(rest[0], 1)
            out.append(rest[1:end] if end > 0 else rest[1:])


def check(raw: bytes) -> str:
    if len(raw) > MAX_BYTES:
        raise SvgRefused(f"The SVG is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SvgRefused("The SVG is not UTF-8 text.") from None
    if "<!entity" in text.lower():
        raise SvgRefused("The SVG declares entities: it is refused.")
    for ref in _references(text):
        if not ref.strip().startswith(("#", "data:")):
            raise SvgRefused("The SVG refers to other files or addresses: only self-contained SVGs are accepted.")
    return text


def to_png(raw: bytes) -> bytes:
    check(raw)
    with tempfile.TemporaryDirectory(prefix="slides-svg-") as tmp:
        src = Path(tmp) / "image.svg"
        src.write_bytes(raw)
        cmd = ["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{tmp}/profile",
               "--convert-to", "png", "--outdir", tmp, str(src)]  # fmt: skip
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, check=False)  # noqa: S603 - fixed argv
        except subprocess.TimeoutExpired:
            raise SvgRefused("The SVG took too long to convert.") from None
        png = Path(tmp) / "image.png"
        if not png.exists():
            raise SvgRefused("The SVG could not be converted.")
        return png.read_bytes()
