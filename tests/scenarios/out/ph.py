import sys
sys.path.insert(0, "/src/backend")
from app.docengine import read, layouts
prs = read.open_deck(open("/src/templates/default.pptx", "rb").read())
lay = prs.slide_layouts[0]
print(lay.name, [(ph.placeholder_format.idx, ph.placeholder_format.type.name) for ph in lay.placeholders])
print([(x["role"], x.get("idx")) for x in layouts.placeholders(lay, prs.slide_width, prs.slide_height)])
