import sys
sys.path.insert(0, "/src/backend")
from app.docengine import ops, read, layouts
data, res = ops.apply(open("/src/templates/bancoctt.pptx", "rb").read(), "add_slide", {"layout": "4_Gráficos", "content": {"title": "Crédito"}})
prs = read.open_deck(data); s = prs.slides.get(res["slides"][0] if isinstance(res, dict) else res[0])
print("shapes.title:", s.shapes.title)
print([(ph.placeholder_format.idx, ph.placeholder_format.type.name if ph.placeholder_format.type else None, ph.text_frame.text if ph.has_text_frame else None) for ph in s.placeholders])
print("slots heading idx:", layouts.slots(s.slide_layout, prs.slide_width, prs.slide_height)["heading"])
