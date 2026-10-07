"""Search by meaning within a project (technical design section 4; spec PJ-10, PJ-11): its conversations and its
reference documents, split into passages and scored against a query by embeddings-server's bge-reranker, as Cortex
reranks (cortex/kbase/retrieval.py). No index is kept: every passage of the project is scored, most recent first up
to a maximum, and the answer says how many were left out.

Scores: the reranker's relevance logits through a sigmoid, so 0..1 and a fixed threshold means the same for every
query. Without the reranker, a case- and accent-insensitive word match, and the answer says so."""

from __future__ import annotations

import logging
import math
import unicodedata

import requests

log = logging.getLogger("slides.search")
BATCH = 64  # passages per rerank call
MAX_PASSAGES = 2000  # per search; the most recent first
CONVERSATION_WINDOW, CONVERSATION_STEP = 3, 2  # consecutive messages per passage, and how far each starts from the last


class SearchUnavailable(Exception):
    pass


class Reranker:
    def __init__(self, url: str, model: str = "bge-reranker") -> None:
        self.url = url.rstrip("/")
        self.model = model

    @property
    def available(self) -> bool:
        return bool(self.url)

    def scores(self, query: str, texts: list[str]) -> list[float]:
        """Each text's relevance to `query`, 0..1 (sigmoid of the reranker's logit). Raises SearchUnavailable."""
        if not self.url:
            raise SearchUnavailable("no reranker is configured")
        out = [0.0] * len(texts)
        for start in range(0, len(texts), BATCH):
            batch = texts[start : start + BATCH]
            try:
                r = requests.post(
                    f"{self.url}/v1/rerank", json={"model": self.model, "query": query, "documents": batch}, timeout=60
                )
                r.raise_for_status()
                results = r.json().get("results") or []
            except (requests.RequestException, ValueError) as e:
                raise SearchUnavailable(f"the reranker did not answer ({type(e).__name__})") from None
            for x in results:
                i = int(x.get("index", -1))
                if 0 <= i < len(batch):
                    out[start + i] = 1 / (1 + math.exp(-float(x.get("relevance_score", -20))))
        return out


def _plain(text: str) -> list[str]:
    """Words, lower case, accents off (a fallback matcher's view of a text)."""
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    words, word = [], []
    for c in folded:
        if c.isalnum():
            word.append(c)
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return words


def word_scores(query: str, texts: list[str]) -> list[float]:
    """Without the reranker: the share of the query's words (3 letters or more) a text contains."""
    wanted = {w for w in _plain(query) if len(w) >= 3}
    if not wanted:
        return [0.0] * len(texts)
    return [len(wanted & set(_plain(t))) / len(wanted) for t in texts]


def rank(reranker: Reranker | None, query: str, passages: list[dict], top_k: int) -> tuple[list[dict], str | None]:
    """The best `top_k` passages ({..., "text"}) with a "score"; and a note when the word match stood in."""
    if not passages:
        return [], None
    texts = [p["text"] for p in passages]
    note = None
    try:
        if reranker is None:
            raise SearchUnavailable("no reranker is configured")
        scores = reranker.scores(query, texts)
    except SearchUnavailable as e:
        log.warning(f"search by words only: {e}")
        scores = word_scores(query, texts)
        note = f"Search by meaning is unavailable ({e}): passages were matched by their words only."
    order = sorted(range(len(passages)), key=lambda i: -scores[i])[:top_k]
    return [{**passages[i], "score": round(scores[i], 3)} for i in order if scores[i] > 0], note


def conversation_passages(conversation: dict, messages: list[dict]) -> list[dict]:
    """A conversation as passages of a few consecutive messages (what the person and the assistant said; tool calls
    and their results left out), each with where it is."""
    said = [m for m in messages if m["role"] in ("user", "assistant") and (m.get("content") or "").strip()]
    if not said:
        return []
    out = []
    starts = list(range(0, max(len(said) - CONVERSATION_WINDOW, 0) + 1, CONVERSATION_STEP))
    if said and starts[-1] + CONVERSATION_WINDOW < len(said):  # the last messages too
        starts.append(len(said) - CONVERSATION_WINDOW)
    for start in starts:
        part = said[start : start + CONVERSATION_WINDOW]
        text = "\n".join(f"{'Person' if m['role'] == 'user' else 'Assistant'}: {m['content'].strip()}" for m in part)
        out.append(
            {
                "conversation_id": conversation["id"],
                "conversation": conversation.get("title") or "",
                "from_message": part[0]["seq"],
                "date": (part[0].get("at") or conversation.get("updated_at") or "")[:10],
                "text": text,
            }
        )
    return out
