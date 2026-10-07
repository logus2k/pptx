import sys
sys.path.insert(0, "/src/backend")
from app.docengine import ops, read
ctt = open("/src/templates/bancoctt.pptx", "rb").read()
data, res = ops.apply(ctt, "add_slide", {"layout": "4_Gráficos", "content": {"title": "Crédito"}})
sid = res["slides"][0] if isinstance(res, dict) else res[0]
print("title only, read model:", [(sh.get("placeholder"), "paragraphs" in sh) for sh in read.slide(read.open_deck(data), sid)["shapes"]])
chart = {"kind": "column", "categories": ["a", "b"], "series": [{"name": "s", "values": [1, 2]}]}
data, res = ops.apply(ctt, "add_slide", {"layout": "4_Gráficos", "content": {"title": "Crédito", "chart": chart}})
prs = read.open_deck(data); s = prs.slides.get(res["slides"][0])
print("with chart:", [(ph.placeholder_format.idx, ph.placeholder_format.type.name) for ph in s.placeholders])
