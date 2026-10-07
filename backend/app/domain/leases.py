"""Edit leases (spec PJ-13, technical design 5.2): while a member has a deck open in the editor, it is held for them;
other members see who holds it and can view the deck, not change it. A lease is held in memory (one instance:
technical design A-3), renewed by the open editor, released when it closes or after the idle time (default 10
minutes). A restart drops every lease, which is safe: a change still names the version it was made on."""

from __future__ import annotations

import threading
import time


class Leased(Exception):
    """The deck is held by someone else."""

    def __init__(self, holder: str) -> None:
        super().__init__(f"the deck is being edited by {holder}")
        self.holder = holder


class Leases:
    def __init__(self, minutes: float = 10) -> None:
        self.seconds = minutes * 60
        self._held: dict[str, tuple[str, float]] = {}  # deck id -> (holder, expires at, monotonic)
        self._lock = threading.Lock()

    def _current(self, did: str) -> tuple[str, float] | None:
        held = self._held.get(did)
        if held and held[1] <= time.monotonic():
            del self._held[did]
            return None
        return held

    def take(self, did: str, email: str) -> dict:
        """Take or renew the deck's lease for `email`; Leased when someone else holds it."""
        with self._lock:
            held = self._current(did)
            if held and held[0] != email:
                raise Leased(held[0])
            self._held[did] = (email, time.monotonic() + self.seconds)
            return {"holder": email, "seconds_left": int(self.seconds)}

    def release(self, did: str, email: str) -> None:
        with self._lock:
            held = self._current(did)
            if held and held[0] == email:
                del self._held[did]

    def holder(self, did: str) -> dict | None:
        """Who holds the deck, and for how much longer; None when it is free."""
        with self._lock:
            held = self._current(did)
            return {"holder": held[0], "seconds_left": int(held[1] - time.monotonic())} if held else None

    def check(self, did: str, email: str) -> None:
        """Leased when someone other than `email` holds the deck."""
        with self._lock:
            held = self._current(did)
            if held and held[0] != email:
                raise Leased(held[0])
