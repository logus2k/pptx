import sys
sys.path.insert(0, "/src/backend")
from app.docengine import layouts, read
for path in ("/src/fixtures/decks/simple.pptx", "/src/templates/default.pptx", "/src/templates/bancoctt.pptx"):
    prs = read.open_deck(open(path, "rb").read())
    print("==", path)
    for lay in prs.slide_layouts:
        roles = [x["role"] for x in layouts.placeholders(lay, prs.slide_width, prs.slide_height)]
        print("  ", lay.name, roles)
