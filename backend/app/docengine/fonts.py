"""Which fonts the server has (assumption A-5): fontconfig's list of installed families, read once. A template's
fonts that are not among them are substituted in previews and overflow estimates, and the person is told so."""

from __future__ import annotations

import functools
import shutil
import subprocess


@functools.cache
def installed() -> frozenset[str] | None:
    """The installed font families, lower case; None when fontconfig's fc-list is not available (then nothing can be
    said about missing fonts)."""
    if not shutil.which("fc-list"):
        return None
    run = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=30, check=False)  # noqa: S607
    families: set[str] = set()
    for line in run.stdout.splitlines():
        for name in line.split(","):  # one line per font: its family names, comma-separated
            if name.strip():
                families.add(name.strip().lower())
    return frozenset(families)


def missing(names: list[str]) -> list[str]:
    have = installed()
    if have is None:
        return []
    return [n for n in names if n.lower() not in have]
