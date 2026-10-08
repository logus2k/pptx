import sys
sys.path.insert(0, "/src/backend")
from app.docengine import ops, read
for path in ("/src/templates/bancoctt.pptx", "/src/templates/default.pptx"):
    prs = read.open_deck(open(path, "rb").read())
    print(path.split("/")[-1], "section:", ops.section_layout(prs).name, "| cover:", ops._layout_for_content(prs, {"title": "a", "subtitle": "b"}).name)
