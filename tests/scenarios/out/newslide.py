import sys
sys.path.insert(0, "/src/backend")
from app.docengine import ops, read
for deck in ("simple.pptx",):
    for content in ({}, {"title": "Processo de crédito"}):
        prs = read.open_deck(open(f"/src/fixtures/decks/{deck}", "rb").read())
        lay = ops._layout_for_content(prs, content)
        r = ops.add_slide(prs, lay.name, after_slide_id=read.outline(prs)[-1]["slide_id"], content=content)
        sid = r["slides"][0] if isinstance(r, dict) else r[0]
        s = prs.slides.get(sid)
        print(deck, content, "layout:", lay.name, "| placeholders:", [(p.placeholder_format.type.name, p.text_frame.text if p.has_text_frame else None) for p in s.placeholders])
