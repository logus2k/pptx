"""Training examples for the tool-group router (router/slides_tools.yaml; labs/jev's router_clf): requests a person
might make, written by the local model per group and per common combination of groups, labelled with them. Only
for training: the router is tested on tests/eval/requests.json (written separately, never seen here), labelled from
their expectations (router/test.jsonl, made by this script too). Run on the host (agent_server's port 7701):
  .venv/bin/python scripts/router_data.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "eval"))
AGENT = "http://127.0.0.1:7701"
PER_LABEL, PER_COMBO = 40, 15
COMBOS = [  # groups requests often need together
    ["structure", "text"], ["knowledge", "structure", "text", "notes"], ["knowledge", "text"], ["images", "structure"],
    ["decks", "structure"], ["text", "notes"], ["memory", "text"], ["table", "text"], ["images", "text"],
]  # fmt: skip


def model_id() -> str:
    for m in requests.get(f"{AGENT}/v1/models", timeout=10).json()["data"]:
        if m.get("active") and m.get("kind") == "chat":
            return m["id"]
    raise SystemExit("agent_server has no active chat model")


# words the generator puts before a request ("In Portuguese:", "Pictures:"): never part of a real message, and a cue
# the classifier would learn instead of the request (seen in the first generated set)
LEAKED = {"in", "em", "portuguese", "português", "portugues", "european", "europeu", "de", "portugal", "(pt)", "pt",
          "english", "inglês", "ingles", "pictures", "picture", "text", "notes", "table", "request", "pedido"}  # fmt: skip


def clean(text: str) -> str:
    head, sep, rest = text.partition(":")
    if sep and len(head) <= 30 and head.split() and all(w.lower() in LEAKED for w in head.split()):
        return rest.strip()
    return text


def ask(model: str, what: str, n: int) -> list[str]:
    prompt = (
        f"Write {n} different requests a person could type or say to an assistant that edits PowerPoint presentations "
        f"in a bank's web application. Every request must need exactly this: {what}\n"
        "Vary them: about half in European Portuguese (Portugal, never Brazilian) and half in English; short and long; "
        "some naming a slide by number, some by its title or content, some about 'this slide'; some polite, some terse, "
        "some spoken (no punctuation). Business subjects: reports, proposals, products, prices, risks, plans. "
        "Write only the request itself: no label, language name or prefix before it. "
        'Answer with JSON only: {"requests": ["...", "..."]}'
    )
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.9, "max_tokens": 4000,
            "response_format": {"type": "json_object"}, "chat_template_kwargs": {"enable_thinking": False}}  # fmt: skip
    r = requests.post(f"{AGENT}/v1/chat/completions", json=body, timeout=300)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    try:
        out = json.loads(text[text.find("{") : text.rfind("}") + 1])["requests"]
    except (ValueError, KeyError):
        print(f"  unreadable answer for: {what[:60]}")
        return []
    return [clean(" ".join(str(x).split())) for x in out if str(x).strip()]


def main() -> None:
    profile = yaml.safe_load((ROOT / "router" / "slides_tools.yaml").read_text(encoding="utf-8"))
    labels = profile["labels"]
    model = model_id()
    rows = []
    for name, desc in labels.items():
        for text in ask(model, desc, PER_LABEL):
            rows.append({"text": text, "labels": [name], "source": "generated"})
        print(f"{name}: {sum(1 for r in rows if r['labels'] == [name])}")
    for text in ask(model, profile["none"]["description"], PER_LABEL):
        rows.append({"text": text, "labels": [], "source": "generated"})
    for combo in COMBOS:
        what = "all of these in one request: " + "; ".join(labels[c] for c in combo)
        for text in ask(model, what, PER_COMBO):
            rows.append({"text": text, "labels": sorted(combo), "source": "generated"})
        print(f"{'+'.join(combo)}: {sum(1 for r in rows if r['labels'] == sorted(combo))}")
    seen, unique = set(), []
    for r in rows:
        if r["text"].lower() not in seen:
            seen.add(r["text"].lower())
            unique.append(r)
    lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in unique)
    (ROOT / "router" / "train.jsonl").write_text(lines, encoding="utf-8")
    print(f"router/train.jsonl: {len(unique)} examples")

    from groups import oracle_groups  # the evaluation's own expectations, as the test set's labels

    spec = json.loads((ROOT / "tests" / "eval" / "requests.json").read_text(encoding="utf-8"))
    test = [{"text": r["request"], "labels": sorted(oracle_groups(r) - {"core"}), "group": r["id"]} for r in spec["requests"]]
    (ROOT / "router" / "test.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in test), encoding="utf-8")
    print(f"router/test.jsonl: {len(test)} examples")


if __name__ == "__main__":
    main()
