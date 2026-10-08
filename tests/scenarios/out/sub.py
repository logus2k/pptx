import sys
sys.path.insert(0, "/src/backend")
from app.docengine import ops, read, layouts
prs = read.open_deck(open("/src/templates/bancoctt.pptx", "rb").read())
for flag in (False, True):
    lay = ops._best_layout(prs, 1, flag)
    print("subtitle preferred" if flag else "old choice", lay.name, "subtitle place:", layouts.slots(lay, prs.slide_width, prs.slide_height)["subtitle"])
