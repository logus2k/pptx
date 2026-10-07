"""Train the tool-group router on router/train.jsonl and test it on router/test.jsonl (the evaluation's requests,
never trained on), with labs/jev's router_clf; save it to router/model.{npz,json} for the app. Measures, per
threshold: miss rate (a group the request needs not selected: the assistant then lacks a tool) and extra groups
per request (offered but not needed), the trade-off a router is chosen on. Run with jev's environment:
  ~/env/labs/jev/.venv/bin/python scripts/router_train.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JEV = Path.home() / "env" / "labs" / "jev"
sys.path.insert(0, str(JEV))

from router_clf.embed import Embedder  # noqa: E402
from router_clf.model import fit_trained, fit_zero_shot  # noqa: E402
from router_clf.profile import load_dataset, load_profile  # noqa: E402


def score(router, X, examples, threshold):
    sel = router.select(router.predict_proba(X), threshold)
    misses = sum(len(e.labels - s) > 0 for e, s in zip(examples, sel, strict=True))
    extras = sum(len(s - e.labels) for e, s in zip(examples, sel, strict=True))
    exact = sum(s == e.labels for e, s in zip(examples, sel, strict=True))
    return misses / len(examples), extras / len(examples), exact / len(examples), sel


def main() -> int:
    profile = load_profile(str(ROOT / "router" / "slides_tools.yaml"))
    train = load_dataset(profile)
    test = load_dataset(profile, str(ROOT / "router" / "test.jsonl"))
    emb = Embedder(url=profile.embed_url, model_tag=profile.embed_model, cache_path=str(ROOT / "router" / ".cache.sqlite"))
    desc = dict(zip(profile.descriptions().keys(), emb.embed(list(profile.descriptions().values())), strict=True))
    Xtr, Xte = emb.embed([e.text for e in train]), emb.embed([e.text for e in test])
    trained, zero = fit_trained(profile, Xtr, train, desc), fit_zero_shot(profile, desc)
    print(f"train {len(train)} generated examples, test {len(test)} evaluation requests")
    print("method      threshold  miss   extras/request  exact")
    for name, router in (("zero-shot", zero), ("trained", trained)):
        for th in (0.1, 0.2, 0.3, 0.5):
            m, x, e, _ = score(router, Xte, test, th)
            print(f"{name:<11} {th:<9}  {m:5.1%}  {x:6.2f}          {e:5.1%}")
    m, x, e, sel = score(trained, Xte, test, 0.2)
    for ex, s in zip(test, sel, strict=True):
        if ex.labels - s:
            print(f"  MISS {ex.text[:70]!r}: needs {sorted(ex.labels)}, chose {sorted(s)}")
    trained.save(str(ROOT / "router" / "model"))
    print("saved router/model.npz, router/model.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
