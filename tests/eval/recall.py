"""SP-7 (technical design section 13): is reranking alone - no index - good enough for conversation and document
search? The questions of recall.json against the real reranker (embeddings-server's bge-reranker): the right passage
must be in the top 3 for >= 90%. Then the time of one search over the largest project searched in one call
(search.MAX_PASSAGES passages). Run on the reranker's network (make eval):
  docker run --rm --network cortex-kb -v $PWD:/src -w /src slides-test python tests/eval/recall.py"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import documents, search  # noqa: E402


def main() -> int:
    spec = json.loads((Path(__file__).parent / "recall.json").read_text(encoding="utf-8"))
    config = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    reranker = search.Reranker(config["services"]["reranker"])
    passages: list[dict] = []
    for i, c in enumerate(spec["conversations"]):
        messages = [
            {"role": r, "content": t, "seq": n + 1, "at": "2026-10-04T10:00:00Z"} for n, (r, t) in enumerate(c["messages"])
        ]
        passages += search.conversation_passages({"id": f"c{i}", "title": c["title"]}, messages)
    for path in spec["documents"]:
        raw = (ROOT / path).read_bytes()
        name = Path(path).name
        passages += [{"document": name, **p} for p in documents.passages(documents.kind_of(name, raw), raw)]
    # distractors on the same subjects (prices, calendars, risks, revenue): each slide of the evaluation decks
    from app.docengine import read

    for name in ("report", "onboarding", "marketing", "injection"):
        prs = read.open_deck((ROOT / "fixtures" / "eval" / f"{name}.pptx").read_bytes())
        for o in read.outline(prs):
            text = f"{o['title']}: {o['summary']}"
            passages.append({"document": f"{name}.pptx", "where": f"slide {o['index'] + 1}", "text": text})
    counts = f"{len(spec['conversations'])} conversations, {len(spec['documents'])} documents, the evaluation decks' slides"
    print(f"{len(passages)} passages: {counts}")

    hits, times, misses = 0, [], []
    for q in spec["questions"]:
        t0 = time.perf_counter()
        top, note = search.rank(reranker, q["q"], passages, 3)
        times.append(time.perf_counter() - t0)
        if note:
            print(f"the reranker is not answering: {note}")
            return 1

        def right(p: dict, q=q) -> bool:
            where = (
                p.get("conversation_id") == f"c{q['conversation']}" if "conversation" in q else p.get("document") == q["document"]
            )
            return where and q["contains"] in p["text"]

        if any(right(p) for p in top):
            hits += 1
        else:
            misses.append(
                (q["q"], [(p.get("conversation_id") or p.get("document"), round(p["score"], 3), p["text"][:70]) for p in top])
            )
    rate = hits / len(spec["questions"])
    print(f"top-3 recall: {hits}/{len(spec['questions'])} = {rate:.0%} (target >= 90%); {sum(times) / len(times):.2f} s a search")
    for q, top in misses:
        print(f"  MISS {q!r}: {top}")

    # the largest search: MAX_PASSAGES passages scored in one call
    big = (passages * (search.MAX_PASSAGES // len(passages) + 1))[: search.MAX_PASSAGES]
    t0 = time.perf_counter()
    search.rank(reranker, "Em que moeda ficaram os valores da proposta?", big, 5)
    print(f"one search over {len(big)} passages: {time.perf_counter() - t0:.1f} s")
    return 0 if rate >= 0.9 else 2


if __name__ == "__main__":
    sys.exit(main())
