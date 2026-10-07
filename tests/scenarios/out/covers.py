import sys
sys.path.insert(0, "/src/backend")
from app.docengine import ops, read
prs = read.open_deck(open("/src/tests/scenarios/out/20261007-115958/a-chart-from-figures-then-a-value-changed.pptx", "rb").read())
s = list(prs.slides)[-1]
W, H = prs.slide_width, prs.slide_height
for sh in s.shapes:
    print(sh.shape_id, sh.name, "placeholder" if sh.is_placeholder else "", round(sh.left / W, 2), round(sh.top / H, 2), round(sh.width / W, 2), round(sh.height / H, 2),
          "area>half" if sh.width * sh.height > W * H / 2 else "", repr(sh.text_frame.text[:30]) if sh.has_text_frame else "")
chart = next(sh for sh in s.shapes if getattr(sh, "has_chart", False))
print("boxes considered:", ops._boxes(prs, s, {chart.shape_id}))
