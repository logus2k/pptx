import sys
sys.path.insert(0, "/src/backend"); sys.path.insert(0, "/src/tests/scenarios")
import run
for name in ("a-chart-from-figures-then-a-value-changed", "a-diagram-from-a-description"):
    slides = run.slides_of(open(f"/src/tests/scenarios/out/20261007-115958/{name}.pptx", "rb").read())
    print(name, [(n + 1, s["covered"], s["empty_placeholders"]) for n, s in enumerate(slides)])
    print(" ", run.judge({"no_covered_text": True, "no_empty_placeholders": True}, {}, slides))
