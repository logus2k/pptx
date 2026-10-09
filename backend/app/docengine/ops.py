"""Editing operations on one deck (spec section 5; technical design sections 6.4 and 9). Each takes the loaded
presentation and the tool's arguments, changes only the elements it targets, and returns the affected slide IDs.
Errors are OpError(code, message, hint): what the model reads to correct itself. Styles of new content come from
the layouts and the theme, never hard-coded values (spec section 6)."""

from __future__ import annotations

import copy
import difflib
import io
from types import SimpleNamespace

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.constants import RELATIONSHIP_TARGET_MODE as RTM
from pptx.opc.package import Part, _Relationship
from pptx.opc.packuri import PackURI
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Emu, Inches, Pt

from . import read

MIN_BODY_PT = 14  # spec section 6: never below this for body text (configurable later)
THEME = {
    "text1": "tx1",
    "text2": "tx2",
    "background1": "bg1",
    "background2": "bg2",
    "accent1": "accent1",
    "accent2": "accent2",
    "accent3": "accent3",
    "accent4": "accent4",
    "accent5": "accent5",
    "accent6": "accent6",
    "hyperlink": "hlink",
    "followed_hyperlink": "folHlink",
}
ALIGN = {"left": "l", "center": "ctr", "right": "r", "justify": "just"}
# relationships of a slide that belong to the slide's own content (copied with it); the layout and notes are not
CONTENT_RELS = {
    RT.IMAGE,
    RT.MEDIA,
    RT.VIDEO,
    RT.AUDIO,
    RT.CHART,
    RT.OLE_OBJECT,
    RT.PACKAGE,
    RT.HYPERLINK,
    RT.DIAGRAM_DATA,
    RT.DIAGRAM_LAYOUT,
    RT.DIAGRAM_COLORS,
    RT.DIAGRAM_QUICK_STYLE,
    "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing",
    "http://schemas.microsoft.com/office/2007/relationships/media",
}


class OpError(Exception):
    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint

    def as_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "hint": self.hint}


# ── finding things ───────────────────────────────────────────────────
def get_slide(prs: Presentation, slide_id: int):
    s = prs.slides.get(int(slide_id))
    if s is None:
        raise OpError(
            "SLIDE_NOT_FOUND",
            f"There is no slide {slide_id} in this deck.",
            "Read the outline (get_deck_outline) for the slide IDs.",
        )
    return s


def _walk(shapes):
    for sh in shapes:
        yield sh
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(sh.shapes)


def get_shape(slide, shape_id: int, *, editable: bool = True):
    for sh in _walk(slide.shapes):
        if sh.shape_id == int(shape_id):
            if editable and read.shape(sh, 1, 1)["locked"]:
                raise OpError(
                    "LOCKED_ELEMENT",
                    f"Shape {shape_id} cannot be changed safely (a chart, SmartArt, media or embedded object).",
                    "A chart's data and title: edit_chart. Else leave it, or ask the person to change it in PowerPoint.",
                )
            return sh
    # the slide's shapes in the answer: the model can retry at once (measured: after "read the slide", gemma-4
    # read it and then said the change was made, without making it)
    shapes = []
    for sh in _walk(slide.shapes):
        text = " ".join(sh.text_frame.text.split())[:40] if getattr(sh, "has_text_frame", False) and sh.has_text_frame else ""
        kind = (
            sh.placeholder_format.type.name.lower()
            if sh.is_placeholder and sh.placeholder_format.type
            else sh.shape_type and sh.shape_type.name.lower()
        )
        shapes.append(f"{sh.shape_id} ({kind}){f': {text}' if text else ''}")
    raise OpError(
        "SHAPE_NOT_FOUND",
        f"There is no shape {shape_id} on slide {slide.slide_id}. Its shapes: {'; '.join(shapes) or 'none'}.",
        "Call the tool again with one of these shape IDs.",
    )


def _layout(prs: Presentation, name: str):
    layouts = [layout for master in prs.slide_masters for layout in master.slide_layouts]
    for layout in layouts:
        if layout.name == name:
            return layout
    # the same name written another way ("title_and_content" for "Title and Content": measured, gemma-4 writes them so)
    plain = " ".join(name.replace("_", " ").split()).casefold()
    same = [layout for layout in layouts if " ".join(layout.name.split()).casefold() == plain]
    if len(same) == 1:
        return same[0]
    names = ", ".join(sorted({lay.name for m in prs.slide_masters for lay in m.slide_layouts}))
    raise OpError("LAYOUT_NOT_FOUND", f'The template has no layout "{name}".', f"Use one of: {names}.")


def _place(
    prs: Presentation, slide, position: int | None, after_slide_id: int | None, before_slide_id: int | None, default: int
) -> int:
    """Where `slide` goes, among the other slides (itself left out): right after or before another slide (by ID: no
    counting for the caller), or at `position` counted from 0, or `default`."""
    others = [int(e.get("id")) for e in prs.slides._sldIdLst if int(e.get("id")) != slide.slide_id]
    for anchor, shift in ((after_slide_id, 1), (before_slide_id, 0)):
        if anchor is not None:
            if int(anchor) not in others:
                raise OpError("SLIDE_NOT_FOUND", f"There is no other slide {anchor}.", "Use a slide ID from the deck map.")
            return others.index(int(anchor)) + shift
    return default if position is None else int(position)


def _move_to(prs: Presentation, slide, position: int) -> None:
    ids = prs.slides._sldIdLst
    entries = list(ids)
    me = next(e for e in entries if int(e.get("id")) == slide.slide_id)
    ids.remove(me)
    position = max(0, min(int(position), len(ids)))
    ids.insert(position, me)


# ── text ─────────────────────────────────────────────────────────────
def _new_rpr(base, run: dict):
    rpr = copy.deepcopy(base) if base is not None else etree.SubElement(etree.Element(qn("a:r")), qn("a:rPr"))
    rpr.tag = qn("a:rPr")
    if "bold" in run:
        rpr.set("b", "1" if run["bold"] else "0")
    if "italic" in run:
        rpr.set("i", "1" if run["italic"] else "0")
    if "theme_color" in run:
        for old in rpr.findall(qn("a:solidFill")):
            rpr.remove(old)
        fill = etree.Element(qn("a:solidFill"))
        etree.SubElement(fill, qn("a:schemeClr")).set("val", THEME[run["theme_color"]])
        # solidFill goes before effects, highlight, fonts and hyperlinks in a:rPr's sequence
        anchor = next(
            (
                c
                for c in rpr
                if c.tag
                in (
                    qn("a:effectLst"),
                    qn("a:highlight"),
                    qn("a:latin"),
                    qn("a:ea"),
                    qn("a:cs"),
                    qn("a:sym"),
                    qn("a:hlinkClick"),
                    qn("a:hlinkMouseOver"),
                    qn("a:rtl"),
                    qn("a:extLst"),
                )
            ),
            None,
        )
        if anchor is not None:
            anchor.addprevious(fill)
        else:
            rpr.append(fill)
    return rpr


def _paragraph_xml(para: dict, template_p):
    """An a:p for `para`, keeping the template paragraph's own properties (bullets, spacing) and its first run's
    formatting as the base of the new runs."""
    p = etree.Element(qn("a:p"))
    tpl_ppr = template_p.find(qn("a:pPr")) if template_p is not None else None
    ppr = copy.deepcopy(tpl_ppr) if tpl_ppr is not None else etree.Element(qn("a:pPr"))
    level = int(para.get("level", 0))
    if level:
        ppr.set("lvl", str(level))
    elif "lvl" in ppr.attrib:
        del ppr.attrib["lvl"]
    if "alignment" in para:
        ppr.set("algn", ALIGN[para["alignment"]])
    if len(ppr) or ppr.attrib:
        p.append(ppr)
    base = template_p.find(f"{qn('a:r')}/{qn('a:rPr')}") if template_p is not None else None
    for run in para["runs"]:
        parts = run["text"].split("\n")
        for i, piece in enumerate(parts):
            if i:
                br = etree.SubElement(p, qn("a:br"))
                if base is not None:
                    br.append(_new_rpr(base, {}))
            if piece:
                r = etree.SubElement(p, qn("a:r"))
                rpr = _new_rpr(base, run)
                if len(rpr) or rpr.attrib:
                    r.append(rpr)
                etree.SubElement(r, qn("a:t")).text = piece
    end = template_p.find(qn("a:endParaRPr")) if template_p is not None else None
    if end is not None:
        p.append(copy.deepcopy(end))
    return p


def _bulleted(text_frame) -> None:
    """Each paragraph a bullet ("•", a hanging indent), set on the paragraph itself so a body style without bullets (Banco
    CTT's) does not hide them; its text size as it is (the user, 2026-10-08: "add bullets and keep the font size")."""
    for p in text_frame._txBody.findall(qn("a:p")):
        ppr = p.find(qn("a:pPr"))
        if ppr is None:
            ppr = etree.SubElement(p, qn("a:pPr"))
            p.remove(ppr)
            p.insert(0, ppr)
        for old in list(ppr):
            if old.tag in (qn("a:buNone"), qn("a:buChar"), qn("a:buAutoNum"), qn("a:buFont")):
                ppr.remove(old)
        ppr.set("marL", "285750")
        ppr.set("indent", "-285750")
        font = etree.Element(qn("a:buFont"), typeface="Arial")
        char = etree.Element(qn("a:buChar"), char="•")
        # in the schema's order: the bullet's font and character before the tab list, the run defaults, extensions
        after = next((c for c in ppr if c.tag in (qn("a:tabLst"), qn("a:defRPr"), qn("a:extLst"))), None)
        if after is None:
            ppr.extend([font, char])
        else:
            after.addprevious(font)
            after.addprevious(char)


def _set_paragraphs(text_frame, paragraphs: list[dict]) -> None:
    body = text_frame._txBody
    old = body.findall(qn("a:p"))
    for i, para in enumerate(paragraphs):
        template = old[min(i, len(old) - 1)] if old else None
        body.append(_paragraph_xml(para, template))
    for p in old:
        body.remove(p)


def _text_frame(sh):
    if not getattr(sh, "has_text_frame", False) or not sh.has_text_frame:
        raise OpError(
            "NO_TEXT",
            f"Shape {sh.shape_id} holds no text.",
            "Choose a placeholder or text box (get_slide shows their paragraphs).",
        )
    return sh.text_frame


def update_text(prs, slide_id: int, shape_id: int, paragraphs: list[dict], deck_id=None) -> list[int]:
    s = get_slide(prs, slide_id)
    _set_paragraphs(_text_frame(get_shape(s, shape_id)), paragraphs)
    return [s.slide_id]


def _level(p) -> int:
    ppr = p.find(qn("a:pPr"))
    return int(ppr.get("lvl", 0)) if ppr is not None else 0


def set_texts(prs, slide_id: int, shape_id: int, texts: list[str], deck_id=None) -> list[int]:
    """A shape's text as the person typed it in the editor (spec PM-7), one paragraph a line: matched against its
    paragraphs (difflib's longest matching runs: a lexical comparison of whole lines) and made into edit_paragraphs
    operations, so a paragraph left as it was keeps its formatting exactly, and a changed or new one takes its
    neighbour's (the formatting of single words inside a changed paragraph is not kept)."""
    get_slide(prs, slide_id)  # an unknown slide: SLIDE_NOT_FOUND
    shape = next((x for x in read.slide(prs, slide_id)["shapes"] if x["shape_id"] == shape_id), None)
    if shape is None or "paragraphs" not in shape:
        raise OpError("NOT_TEXT", f"Shape {shape_id} holds no text.", "")
    old = ["".join(r.get("text", "") for r in p.get("runs", [])) for p in shape["paragraphs"]]
    new = [line for text in texts for line in str(text).split("\n")]
    operations: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        common = min(i2 - i1, j2 - j1)  # a replaced run: line for line, then the rest inserted or deleted
        operations += [{"op": "set", "index": i1 + k, "text": new[j1 + k]} for k in range(common)]
        operations += [{"op": "delete", "index": i} for i in range(i1 + common, i2)]
        if j2 - j1 > common:
            operations.append({"op": "insert", "after": i1 + common - 1, "text": "\n".join(new[j1 + common : j2])})
    if not operations:
        return []
    return edit_paragraphs(prs, slide_id, shape_id, operations)


def edit_paragraphs(prs, slide_id: int, shape_id: int, operations: list[dict], deck_id=None) -> list[int]:
    """Change some paragraphs of a shape, by their index in it (0 first, as read): {op: insert, after, text, level}
    (after -1: first; left out: last) | {op: set, index, text, level} | {op: delete, index}. Indices name the
    paragraphs before the call. The paragraphs not named are kept exactly as they are; a new or changed one takes its
    neighbour's formatting (bullets, spacing, its first run's font) and level unless one is given. A text's line
    breaks make separate paragraphs."""
    s = get_slide(prs, slide_id)
    body = _text_frame(get_shape(s, shape_id))._txBody
    old = body.findall(qn("a:p"))
    n = len(old)
    deleted, changed, inserted = set(), {}, {}
    for op in operations:
        kind = op.get("op")
        if kind in ("set", "delete"):
            i = op.get("index")
            if i is None or not 0 <= int(i) < n:
                raise OpError("BAD_PARAGRAPH", f"The shape has paragraphs 0-{n - 1}.", "Use the indices the deck map shows.")
            if kind == "delete":
                deleted.add(int(i))
            else:
                changed[int(i)] = op
        elif kind == "insert":
            # after the last or past it: at the end (measured: "after 5" for five paragraphs meant just that)
            after = min(int(op.get("after", n - 1)), n - 1)
            if after < -1:
                raise OpError("BAD_PARAGRAPH", f"The shape has paragraphs 0-{n - 1}; after -1 puts it first.", "")
            inserted.setdefault(after, []).append(op)
        else:
            raise OpError("BAD_ARGUMENTS", f"Unknown operation {kind!r}.", "Use insert, set or delete.")
        if kind in ("insert", "set") and not isinstance(op.get("text"), str):
            raise OpError("BAD_ARGUMENTS", f"{kind} needs text.", "")

    def made(op: dict, template) -> list:
        level = int(op["level"]) if op.get("level") is not None else _level(template)
        return [_paragraph_xml({"runs": [{"text": line}], "level": level}, template) for line in op["text"].split("\n")]

    new = [x for op in inserted.get(-1, []) for x in made(op, old[0])]
    for i, p in enumerate(old):
        if i not in deleted:
            new += made(changed[i], p) if i in changed else [p]
        new += [x for op in inserted.get(i, []) for x in made(op, p)]
    if not new:  # a text body keeps one paragraph
        new = [_paragraph_xml({"runs": [{"text": ""}]}, old[0])]
    for p in old:
        body.remove(p)
    for p in new:
        body.append(p)
    return [s.slide_id]


def _is_body(sh) -> bool:
    if not sh.is_placeholder:
        return True
    t = sh.placeholder_format.type
    return t is None or t.name not in ("TITLE", "CENTER_TITLE", "SUBTITLE", "DATE", "FOOTER", "SLIDE_NUMBER")


def format_text(prs, slide_id: int, shape_id: int, style: dict, range: dict | None = None, deck_id=None) -> list[int]:
    """style: {size_pt?, bold?, italic?, theme_color?, alignment?}; range: {first_paragraph?, last_paragraph?}."""
    s = get_slide(prs, slide_id)
    sh = get_shape(s, shape_id)
    tf = _text_frame(sh)
    size = style.get("size_pt")
    if size is not None and size < MIN_BODY_PT and _is_body(sh):
        raise OpError(
            "TEXT_TOO_SMALL",
            f"Body text may not be smaller than {MIN_BODY_PT} pt.",
            "Shorten the text, split it across slides, or ask the user.",
        )
    paras = tf.paragraphs
    first = int((range or {}).get("first_paragraph", 0))
    last = int((range or {}).get("last_paragraph", len(paras) - 1))
    if not 0 <= first <= last < len(paras):
        raise OpError("BAD_RANGE", f"The shape has paragraphs 0 to {len(paras) - 1}.", "")
    for p in paras[first : last + 1]:
        if "alignment" in style:
            p._p.get_or_add_pPr().set("algn", ALIGN[style["alignment"]])
        for r in p.runs:
            if size is not None:
                r.font.size = Pt(size)
            rpr = _new_rpr(r._r.get_or_add_rPr(), {k: style[k] for k in ("bold", "italic", "theme_color") if k in style})
            r._r.replace(r._r.find(qn("a:rPr")), rpr)
    return [s.slide_id]


# ── slides ───────────────────────────────────────────────────────────
NOT_CONTENT = ("title", "center_title", "subtitle", "date", "footer", "slide_number")


def _fill_placeholder(slide, spec: dict) -> None:
    target = None
    for ph in slide.placeholders:
        pf = ph.placeholder_format
        if ("idx" in spec and pf.idx == int(spec["idx"])) or (
            "type" in spec and pf.type is not None and pf.type.name.lower() == spec["type"]
        ):
            target = ph
            break
    # idx 0 and 1 are PowerPoint's title and body: on a layout numbered otherwise they mean its title and its body
    # (measured: on a template whose body is idx 16, the model sent idx 1 three times, the layout's list in front of it)
    if target is None and "idx" in spec and int(spec["idx"]) in (0, 1) and not spec.get("type"):
        spec = {**spec, "type": "title" if int(spec["idx"]) == 0 else "body"}
        spec.pop("idx")
        return _fill_placeholder(slide, spec)
    if target is None and spec.get("type") in ("title", "subtitle"):
        # a layout whose heading is typed "body" (Banco CTT's): the placeholder its place and size make the heading or
        # the subtitle (layouts.py)
        from . import layouts

        pres = slide.part.package.presentation_part.presentation
        find = layouts.heading if spec["type"] == "title" else layouts.subtitle
        idx = find(slide.slide_layout, pres.slide_width, pres.slide_height)
        target = next((ph for ph in slide.placeholders if ph.placeholder_format.idx == idx), None) if idx is not None else None
    if target is None and spec.get("type") in ("title", "body"):
        # the roles the deck map names: "title" (a title slide's is a centred title), "body" (the main content
        # placeholder, whatever its type: object, body)
        kinds = [(ph.placeholder_format.idx, ph) for ph in slide.placeholders if ph.placeholder_format.type is not None]
        if spec["type"] == "title":
            found = [ph for _, ph in kinds if ph.placeholder_format.type.name.lower() == "center_title"]
        else:
            found = [
                ph for _, ph in sorted(kinds, key=lambda x: x[0]) if ph.placeholder_format.type.name.lower() not in NOT_CONTENT
            ]
        target = found[0] if found else None
    if target is None:
        # what the layout does have, top to bottom (measured: told to look at list_layouts, which is not offered, the
        # model sent the same placeholders again and gave up on a template whose layouts have no title placeholder)
        kind = lambda ph: ph.placeholder_format.type.name.lower() if ph.placeholder_format.type else "body"  # noqa: E731
        found = sorted(slide.placeholders, key=lambda ph: (ph.top or 0, ph.left or 0))
        have = "; ".join(
            f"idx {ph.placeholder_format.idx} ({kind(ph)}, {ph.name})"
            for ph in found
            if kind(ph) not in ("date", "footer", "slide_number")
        )
        raise OpError(
            "PLACEHOLDER_NOT_FOUND",
            f"The layout {slide.slide_layout.name!r} has no placeholder {spec.get('idx', spec.get('type'))}.",
            f"Its placeholders, top to bottom: {have or 'none'}. Give each text an idx from these, or choose another layout.",
        )
    paragraphs = spec.get("paragraphs") or [{"runs": [{"text": line}]} for line in str(spec.get("text", "")).split("\n")]
    _set_paragraphs(target.text_frame, paragraphs)


def _fitting(prs, points: int) -> str:
    """The deck's layouts with a heading and a place for `points` points: a box each, or one with room for them all
    (measured: told only "choose a layout with text boxes", the model asked the person which layout, 3 runs in 3)."""
    from . import layouts

    names = []
    for lay in prs.slide_layouts:
        where = layouts.slots(lay, prs.slide_width, prs.slide_height)
        items = where["items"]
        if where["heading"] is not None and items and (len(items) >= points or max(i["room"] for i in items) >= points):
            names.append(lay.name)
    return ", ".join(names[:8]) or "none: add a text box with add_shape"


def _point_text(point) -> tuple[str, str]:
    """A point as (its heading, its text): a string is all text."""
    if isinstance(point, dict):
        return str(point.get("heading") or "").strip(), str(point.get("text") or "").strip()
    return "", str(point).strip()


def _subtitle_to_notes(prs, sid: int, sentence: str) -> None:
    """A cover's subtitle sentence that did not fit with its lines, kept in the slide's notes (under what they said)."""
    s = get_slide(prs, sid)
    had = (s.notes_slide.notes_text_frame.text.strip() if s.has_notes_slide else "")
    set_notes(prs, sid, f"{had}\n\n{sentence}" if had else sentence)


def _cover_subtitle(prs, lay, content: dict, first: bool) -> dict:
    """A deck's first slide on a cover (a subtitle place and no text area): up to three short points - who it is for,
    the date - become the subtitle's lines, a point repeating the title left out, rather than the slide moved to a
    layout with a box for each (measured: "a cover for the sales team, October 2026", the model sent the audience and
    the date as points, and the cover went on "4_Texto" and "6_Texto", its lines scattered in boxes, 2 runs in 2)."""
    from . import layouts

    points = [p for p in content.get("points") or [] if any(_point_text(p))]
    if not first or not points or len(points) > 3:
        return content
    where = layouts.slots(lay, prs.slide_width, prs.slide_height)
    if where["items"] or where["subtitle"] is None:
        return content
    texts = [" ".join(" ".join(x for x in _point_text(p) if x).split()) for p in points]
    if any(len(x) > 80 for x in texts):
        return content
    title = " ".join(str(content.get("title") or "").split()).casefold()
    lines = []
    for x in [" ".join(str(content.get("subtitle") or "").split()), *texts]:
        if x and x.casefold() != title and x.casefold() not in [y.casefold() for y in lines]:
            lines.append(x)
    out = {k: v for k, v in content.items() if k != "points"}
    if lines:
        out["subtitle"] = "\n".join(lines)
    return out


LIST_PT = 24  # the largest a slide's list is set (the user, 2026-10-09: small text in a corner "will not be usable"; 24 pt
# is what a projected training slide's body is set in; looked at: 20 pt, top-aligned, still left half of each slide empty)
COLUMN_PT = 20  # the largest a column's or card's text is set


def _grow(boxes: list, top_pt: int) -> int | None:
    """Generated text set as large as fits, up to top_pt, never smaller than the template sets it; one size for all the
    boxes (columns side by side read as one). Then the height left over spread between the paragraphs, up to a line
    each, so a short list fills its place instead of sitting at its top. The size set, or None (left as it was)."""
    from . import textfit

    if not boxes or any(textfit.measure(b) is None or textfit.measure(b)["font_scale"] < 1 for b in boxes):
        return None  # not measurable, or already shrunk to fit: nothing to grow
    now = max(textfit.smallest_size(b) or 0 for b in boxes)
    if not now or now >= top_pt:
        return None
    saved = [copy.deepcopy(b.text_frame._txBody) for b in boxes]

    def size(pt: float) -> None:
        for b in boxes:
            for p in b.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(pt)

    for pt in range(int(top_pt), int(now), -1):
        size(pt)
        if all(textfit.overflows(b) is False for b in boxes):
            for share in (1.5, 1.0, 0.75, 0.5, 0.25):  # the room left, between the paragraphs
                for b in boxes:
                    for p in b.text_frame.paragraphs[1:]:
                        p.space_before = Pt(round(pt * share, 1))
                if all(textfit.overflows(b) is False for b in boxes):
                    return pt
            for b in boxes:
                for p in b.text_frame.paragraphs[1:]:
                    p.space_before = None
            return pt
    for b, old in zip(boxes, saved, strict=True):  # no larger size fits: as it was
        b.text_frame._txBody.getparent().replace(b.text_frame._txBody, old)
    return None


def _centre(box) -> None:
    """A text that fills less than two thirds of its place, set in the middle of it rather than at its top (looked at: a
    four-point list at its place's top, the lower half of the slide empty)."""
    from . import textfit

    m = textfit.measure(box)
    if m is None or m["anchor"] != "t" or m["extent"] > 2 / 3 * (m["box_h"] - (m["tIns"] + m["bIns"]) / textfit.EMU_PT):
        return
    body = box.text_frame._txBody.find(qn("a:bodyPr"))
    body.set("anchor", "ctr")


def _shape_columns(prs, on: dict, items: list[dict], used: int) -> None:
    """Columns (a heading over its text, side by side) shaped to what they hold (looked at: Banco CTT's "4_Texto", two
    or three short lines at the top of 4.7-inch outlined boxes, the cards mostly empty; "10_Texto", three columns in
    four places, the last quarter empty, an inch of nothing between each heading and its text):
    - fewer columns than places in the row: the columns used share the row's whole width, the gutter kept;
    - a body far below its heading (more than the heading's height) comes up under it;
    - each body as tall as the tallest text among them (equal cards), never taller than the layout made it;
    - a column of several lines is a bulleted list (the user, 2026-10-08: "add bullets and keep the font size").
    Only columns with their heading and a body anchored at the top: a box centred on a number (an agenda) keeps its
    place."""
    from . import textfit

    cols = []
    for item in items[:used]:
        head, body = on.get(item["header"]), on.get(item["body"])
        if head is None or body is None or not head.text_frame.text.strip() or not body.text_frame.text.strip():
            return
        if (textfit.measure(body) or {}).get("anchor", "t") != "t":
            return
        cols.append((head, body))
    if len(cols) < 2:
        return

    def put(sh, left, top, width, height):  # all four set: a placeholder's own xfrm replaces its layout's whole
        sh.left, sh.top, sh.width, sh.height = int(left), int(top), int(width), int(height)

    row = sorted((on[i["header"]] for i in items if i["header"] in on and on[i["header"]].top == cols[0][0].top),
                 key=lambda sh: sh.left)  # fmt: skip
    if len(row) > used and len(row) >= 2:
        gutter = max(row[1].left - (row[0].left + row[0].width), 0)
        span = row[-1].left + row[-1].width - row[0].left
        width = (span - gutter * (used - 1)) / used
        for n, (head, body) in enumerate(sorted(cols, key=lambda c: c[0].left)):
            left = row[0].left + n * (width + gutter)
            put(head, left, head.top, width, head.height)
            put(body, left, body.top, width, body.height)
    for head, body in cols:
        below = head.top + head.height
        if body.top - below > head.height:
            put(body, body.left, below + head.height // 5, body.width, body.height + body.top - below - head.height // 5)
        if len(body.text_frame.paragraphs) > 1:
            _bulleted(body.text_frame)
    _grow([body for _, body in cols], COLUMN_PT)  # as large as the layout's cards hold, then the cards fitted to it
    needs = []
    for _, body in cols:
        m = textfit.measure(body)
        if m is None or m["broken"]:
            return
        needs.append((m["extent"] + (m["tIns"] + m["bIns"]) / textfit.EMU_PT) * textfit.EMU_PT)
    tall = max(needs) + Inches(0.15)  # a line's breath under the text, inside the card
    for _, body in cols:  # under their headings, where the template puts them (looked at: centred lower in the slide,
        # the cards floated away from the title)
        if tall < body.height:
            put(body, body.left, body.top, body.width, tall)



def _place_content(prs, s, content: dict) -> list[str]:
    """A slide's content put where its layout made a place for it (layouts.slots): the title in its heading, the
    subtitle under it, each point in a text box of its own with the box's column heading and number when the layout
    has as many, else every point as one list in the box with the most room; then the text placeholders left empty
    are removed, so no "Click to add text" is left on the slide (measured: the model, given ten unnamed boxes, wrote a
    list into a subtitle box or into one agenda box, or nowhere, 3 runs in 3)."""
    from . import layouts

    lay = s.slide_layout
    where = layouts.slots(lay, prs.slide_width, prs.slide_height)
    on = {ph.placeholder_format.idx: ph for ph in s.placeholders}

    def put(idx, paragraphs):
        _set_paragraphs(on[idx].text_frame, paragraphs)

    def para(text, bold=False):
        return {"runs": [{"text": text, **({"bold": True} if bold else {})}]}

    left_out = []
    said = lambda key: " ".join(str(content.get(key) or "").split()).casefold()  # noqa: E731
    if said("subtitle") == said("title"):
        # a subtitle that is the title again is left out (measured: "Índice de Crédito à Habitação" sent as both, and
        # the slide showed it twice)
        content = {k: v for k, v in content.items() if k != "subtitle"}
    for key in ("title", "subtitle"):
        if content.get(key):
            idx = where["heading" if key == "title" else "subtitle"]
            if idx is None or idx not in on:
                # the rest is placed, this reported (measured: a subtitle for "Title and Content" refused the slide
                # three times, and no slide was made)
                left_out.append(key)
                continue
            # a subtitle's lines (a cover's: what, for whom, when) each a paragraph
            lines = [x.strip() for x in str(content[key]).strip().split("\n") if x.strip()] if key == "subtitle" else []
            put(idx, [para(x) for x in lines] if len(lines) > 1 else [para(str(content[key]).strip())])
    points = [p for p in content.get("points") or [] if any(_point_text(p))]
    items = [i for i in where["items"] if i["body"] in on]
    if points and not items:
        raise OpError(
            "NO_PLACE",
            f"The layout {lay.name!r} has no place for points.",
            f"Change the slide's layout with change_layout to one that has (then call again): {_fitting(prs, len(points))}.",
        )
    series = 1 < len(points) <= len(items) and _alike(lay, items[: len(points)], prs.slide_width, prs.slide_height)
    if points and 1 < len(items) and len(points) <= len(items) and not content.get("as_list") and series:
        numbers = content.get("numbers") or []  # key figures: each value in its box's number place (ops.add_designed)
        for n, (point, item) in enumerate(zip(points, items, strict=False)):
            heading, text = _point_text(point)
            body = [para(x) for x in text.split("\n") if x.strip()] if text else []  # a column's lines, each a paragraph
            if item["header"] is not None and item["header"] in on and heading:
                put(item["header"], [para(heading)])
                if body or not numbers:  # a key figure's label once, in its header (looked at: written twice)
                    put(item["body"], body or [para(heading)])
            else:
                put(item["body"], [p for p in (heading and para(heading, bold=bool(text)), *body) if p])
            if item["number"] is not None and item["number"] in on:
                put(item["number"], [para(numbers[n] if n < len(numbers) else f"{n + 1:02d}")])
        _shape_columns(prs, on, items, len(points))
    elif points:
        lines = []
        for point in points:
            heading, text = _point_text(point)
            lines.append(para(f"{heading}: {text}" if heading and text else heading or text))
        box = where["large"] if where["large"] in on else items[0]["body"]
        put(box, lines)
        if content.get("as_list"):  # a generated slide's list: bulleted
            _bulleted(on[box].text_frame)
        _grow([on[box]], LIST_PT)  # as large as its place holds (the user, 2026-10-09: small text in a corner is unusable)
        _centre(on[box])
    # places left empty go; a title alone keeps the layout's main text box, to be filled (measured: an empty tag kept
    # on a title-only slide showed "Click to add Text" in the preview)
    keep = set() if points or not items else {where["large"] if where["large"] in on else items[0]["body"]}  # the roomiest
    for ph in list(s.placeholders):
        kind = ph.placeholder_format.type.name.lower() if ph.placeholder_format.type is not None else "body"
        empty = ph.has_text_frame and not ph.text_frame.text.strip()
        if kind in ("body", "object", "title", "center_title", "subtitle") and empty and ph.placeholder_format.idx not in keep:
            ph._element.getparent().remove(ph._element)
        # an empty photo place over the whole slide hides the layout's background as a grey box (looked at: Banco CTT's
        # "1_Capa C/ Imagem", its red under a full-slide picture place); a photo can still be added
        whole = (ph.width or 0) * (ph.height or 0) >= 0.9 * prs.slide_width * prs.slide_height
        if kind == "picture" and whole and ph._element.tag.endswith("}sp"):
            ph._element.getparent().remove(ph._element)
    from . import textfit

    # two filled text places that overlap: the upper ends where the lower begins, so a long text in it is fitted above
    # the other's (measured: a divider layout's title box reaches 0.2 inch into its subtitle's; a four-line title ran
    # into the subtitle's first line)
    filled = [ph for ph in s.placeholders if ph.has_text_frame and ph.text_frame.text.strip() and ph.width and ph.height]
    for up in filled:
        for low in filled:
            across = min(up.left + up.width, low.left + low.width) - max(up.left, low.left)
            if low is not up and across > 0 and up.top < low.top < up.top + up.height:
                # only when its text reaches into the other's box: a short text keeps its place (looked at: a key
                # figure's box, trimmed though its one line was clear of its label, sat higher than its row's others)
                m = textfit.measure(up)
                gap = Inches(0.1)  # (looked at: a divider's long title touching its subtitle's first line)
                if m is not None and up.top + m["bottom"] * textfit.EMU_PT > low.top - gap:
                    up.left, up.top, up.width, up.height = up.left, up.top, up.width, low.top - gap - up.top
    for ph in list(s.placeholders):  # what was placed is fitted to its box, as fit_text does (measured: a title of
        # three words ran past the narrow 40 pt title of "1_Texto", and the model fitted the subtitle instead)
        if ph.has_text_frame and ph.text_frame.text.strip() and textfit.overflows(ph):
            try:
                fit_text(prs, s.slide_id, ph.shape_id)
            except OpError:
                pass  # too long even at 14 pt: the executor's self-check reports it
    # a row's numbers (key figures, an agenda's) at one size: the smallest any of them was fitted to (looked at: "450 000
    # €" fitted smaller than "35" and "100%" beside it, and higher in its box)
    numbers = [on[i["number"]] for i in items if i["number"] is not None and i["number"] in on
               and on[i["number"]]._element.getparent() is not None and on[i["number"]].text_frame.text.strip()]  # fmt: skip
    scales = [(textfit.measure(ph) or {}).get("font_scale", 1.0) for ph in numbers]
    if len(numbers) > 1 and min(scales) < max(scales):
        for ph in numbers:
            body = ph.text_frame._txBody.find(qn("a:bodyPr"))
            for tag in ("a:spAutoFit", "a:noAutofit", "a:normAutofit"):
                for x in body.findall(qn(tag)):
                    body.remove(x)
            etree.SubElement(body, qn("a:normAutofit")).set("fontScale", str(round(min(scales) * 100000)))
    return left_out


def add_slide(prs, layout: str, position: int | None = None, placeholders: list[dict] | None = None,
              after_slide_id: int | None = None, before_slide_id: int | None = None, content: dict | None = None,
              deck_id=None):  # fmt: skip
    """A new slide (_add_one); a list too long for its box even at the smallest size goes on as many slides as it
    needs, the same layout and title, the points in order (measured: ten criteria from the knowledge base, 1183
    characters, ran past the slide's bottom 3 runs in 3, and the model said so instead of splitting them)."""
    first = len(prs.slides) == 0 or position == 0
    res = _add_one(prs, layout, position, placeholders, after_slide_id, before_slide_id, content)
    points = [p for p in (content or {}).get("points") or [] if any(_point_text(p))]
    if points and content and not placeholders and not _cover_subtitle(prs, _layout(prs, layout), content, first).get("points"):
        # a cover whose points are its subtitle's lines: one slide, fitted (measured: the four lines overflowed its
        # subtitle, the list went on over a second slide, and the date landed on "4_Texto")
        sid = _ids(res)[0]
        if content.get("subtitle") and _overflowing(prs, sid):
            pos = [x.slide_id for x in prs.slides].index(sid)
            delete_slide(prs, sid)
            lean = {k: v for k, v in content.items() if k != "subtitle"}
            res = _add_one(prs, layout, pos, None, None, None, lean)
            sid = _ids(res)[0]
            _subtitle_to_notes(prs, sid, content["subtitle"])
            res = {**(res if isinstance(res, dict) else {}), "slides": [sid], "moved_to_notes": "subtitle"}
        return res
    sid = (res["slides"] if isinstance(res, dict) else res)[0]
    if len(points) < 2 or placeholders or (content or {}).get("chart") or (content or {}).get("diagram"):
        return res
    if not _overflowing(prs, sid):
        return res
    lay = (res.get("layout") if isinstance(res, dict) else None) or layout
    pos = [x.slide_id for x in prs.slides].index(sid)
    delete_slide(prs, sid)
    made, rest = [], points
    while rest and len(made) < 4:  # at most four slides for one request
        for k in range(len(rest), 0, -1):  # the most points that fit on this slide, in order
            sid = _ids(_add_one(prs, lay, pos, None, None, None, {**content, "points": rest[:k]}))[0]
            if k == 1 or not _overflowing(prs, sid):
                break
            delete_slide(prs, sid)
        made.append(sid)
        rest, pos = rest[k:], pos + 1
    out = dict(res) if isinstance(res, dict) else {}
    out["slides"] = made
    out["continued"] = len(made) - 1
    if rest:
        out["left_out"] = [*out.get("left_out", []), f"{len(rest)} points (more than four slides hold)"]
    return out


def _ids(res) -> list[int]:
    return res["slides"] if isinstance(res, dict) else res


def _overflowing(prs, sid: int) -> bool:
    """Does a text place of the slide still run past its box (after the fitting placement does)? A word wider than its
    box is not counted: another slide would not make it narrower."""
    from . import textfit

    s = prs.slides.get(sid)
    return any(ph.has_text_frame and ph.text_frame.text.strip() and textfit.overflows(ph, words=False) for ph in s.placeholders)


def _add_one(
    prs,
    layout: str,
    position: int | None = None,
    placeholders: list[dict] | None = None,
    after_slide_id: int | None = None,
    before_slide_id: int | None = None,
    content: dict | None = None,
    deck_id=None,
) -> list[int]:
    from . import layouts

    lay = _layout(prs, layout)
    instead = None
    if content and not placeholders:  # a new first slide on a cover: its short points are the subtitle's lines
        first = len(prs.slides) == 0 or position == 0
        content = _cover_subtitle(prs, lay, content, first)
    # a chart or a diagram as the slide's content: drawn where its list would go, under its title (measured: asked for
    # "a new slide with a diagram of the process", the model put the boxes in add_slide first, 8 turns in 8; for a
    # chart it wrote a filler point and drew the chart over it, 4 runs in 4)
    kind = next((k for k in ("chart", "diagram") if content and content.get(k)), None)
    figure, dropped = (content or {}).get(kind), []
    if kind:
        content = {k: v for k, v in content.items() if k not in ("chart", "diagram")}
        if content.get("points"):
            content.pop("points")
            dropped.append(f"points (the {kind} takes their place)")
        heading = layouts.slots(lay, prs.slide_width, prs.slide_height)["heading"]
        if content.get("title") and not placeholders and heading is None:
            better = _layout_for_content(prs, {"title": content["title"]})  # a heading for its title (it chose "Blank")
            if better.name != lay.name:
                lay, instead = better, lay.name
    npoints = len([p for p in (content or {}).get("points") or [] if any(_point_text(p))])
    if npoints and not placeholders and not layouts.slots(lay, prs.slide_width, prs.slide_height)["items"]:
        # a layout with no place for the points: the one they fit (measured: the cover's layout named for an index)
        better = _best_layout(prs, npoints, bool(content.get("subtitle")))
        if better is not None and better.name != lay.name:
            lay, instead = better, lay.name
    more_than_a_title = content and (content.get("subtitle") or content.get("points"))  # a title alone: a chart slide's
    if more_than_a_title and not placeholders and _needs_other_content(prs, lay):
        # text alone on a layout made for a table, a chart or a diagram, left empty: the layout the text fits (measured:
        # a cover on "7_Tabela", its table place left on the slide, 2 runs in 3)
        better = _layout_for_content(prs, content)
        if better.name != lay.name:
            lay, instead = better, lay.name
    s = prs.slides.add_slide(lay)
    _move_to(prs, s, _place(prs, s, position, after_slide_id, before_slide_id, default=len(prs.slides) - 1))
    for spec in placeholders or []:
        _fill_placeholder(s, spec)
    left_out = (_place_content(prs, s, content) if content else []) + dropped
    drawn = _draw_figure(prs, s, kind, figure) if kind else {}
    if left_out or instead or drawn:
        return {"slides": [s.slide_id], **({"left_out": left_out} if left_out else {}),
                **({"layout": lay.name, "instead_of": instead} if instead else {}), **drawn}  # fmt: skip
    return [s.slide_id]


def _draw_figure(prs, s, kind: str, figure: dict) -> dict:
    """A new slide's chart or diagram, in the place its layout keeps for its text (the largest text placeholder left
    empty, which goes), or a chart in the layout's chart place; else under the title."""
    holders = [ph for ph in s.placeholders if ph.has_text_frame and not ph.text_frame.text.strip()
               and ph.placeholder_format.type is not None
               and ph.placeholder_format.type.name in ("BODY", "OBJECT")]  # fmt: skip
    kinds = {ph.placeholder_format.type.name for ph in s.placeholders if ph.placeholder_format.type is not None}
    chart_place = "CHART" in kinds
    box = None
    if holders and not (kind == "chart" and chart_place):
        # the area all the empty text places cover together: the layout's content under its title (looked at: drawn in
        # the largest place alone, a seven-step diagram used the slide's upper half, the places under it left empty)
        # (the layout's places: the slide's own empty ones were removed when its title was placed)
        from . import layouts

        W, H = prs.slide_width, prs.slide_height
        where = layouts.slots(s.slide_layout, W, H)
        head = next((ph for ph in s.slide_layout.placeholders if ph.placeholder_format.idx == where["heading"]), None)
        under = head.top + head.height if head is not None else 0
        places = [ph for ph in s.slide_layout.placeholders if ph.placeholder_format.type is not None
                  and ph.placeholder_format.type.name in ("BODY", "OBJECT") and ph.top >= under
                  and ph.placeholder_format.idx not in (where["heading"], where["subtitle"])] or holders  # fmt: skip
        left, top = min(ph.left for ph in places), min(ph.top for ph in places)
        right = max(ph.left + ph.width for ph in places)
        bottom = max(ph.top + ph.height for ph in places)
        box = {"x": left / W, "y": top / H, "w": (right - left) / W, "h": (bottom - top) / H}
    if kind == "chart":
        got = add_chart(prs, s.slide_id, figure["kind"], figure["categories"], figure["series"],
                        number_format=figure.get("number_format"), box=box)  # fmt: skip
        out = {"figure": "chart", "shape_id": got["shape_id"], **({"covers": got["covers"]} if got.get("covers") else {})}
    else:
        got = draw_diagram(prs, s.slide_id, figure["nodes"], figure.get("edges"), figure.get("direction", "right"), box=box)
        out = {"figure": "diagram", "shape_ids": got["shape_ids"], "connector_ids": got["connector_ids"],
               "styled_from": got["styled_from"]}  # fmt: skip
    for ph in list(s.placeholders):  # a new slide: a text place still empty would show its prompt (measured: the
        # text box kept for the list, beside a chart put in the layout's chart place)
        if ph.has_text_frame and not ph.text_frame.text.strip():
            ph._element.getparent().remove(ph._element)
    return out


def _needs_other_content(prs, lay) -> bool:
    """Does the layout have a place for a table, a chart or a diagram (which text cannot fill)?"""
    from . import layouts

    roles = {p["role"] for p in layouts.placeholders(lay, prs.slide_width, prs.slide_height)}
    return bool(roles & {"table", "chart", "diagram"})


def _relayout(s, lay) -> None:
    """The slide put on another layout in place (its ID kept): its placeholders are the new layout's, empty; its other
    shapes stay. For a slide whose content is about to be written whole (fill_slide)."""
    for rel in s.part.rels.values():
        if rel.reltype == RT.SLIDE_LAYOUT:
            rel._target = lay.part
            for cached in ("target_part", "target_partname", "target_ref"):  # python-pptx's lazy properties
                rel.__dict__.pop(cached, None)
    s.__dict__.pop("slide_layout", None)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    s.shapes.clone_layout_placeholders(lay)


def _alike(lay, items: list[dict], width: int, height: int) -> bool:
    """Are these text boxes a series - rows of an agenda, columns of a comparison - each meant for one point: the same
    text size and weight, their widths and heights within 30% of each other? (Looked at: a list spread over "2_Texto"'s
    bold banner, large body and two small columns read as fragments; over "1_Texto"'s five equal rows it reads as an
    index.)"""
    from . import layouts

    if len(items) < 2:
        return True
    ps = {p["idx"]: p for p in layouts.placeholders(lay, width, height)}
    boxes = [ps[i["body"]] for i in items if i["body"] in ps]
    if len(boxes) != len(items):
        return False
    same = len({(b["size"], b["bold"]) for b in boxes}) == 1
    w, h = [b["w"] for b in boxes], [b["h"] for b in boxes]
    return same and max(w) <= 1.3 * min(w) and max(h) <= 1.3 * min(h)


def _best_layout(prs, points: int, subtitle: bool = False):
    """The layout with a heading and the fewest text boxes that still give each point one (else the one with a box
    with the most room); with a subtitle, one that also has its place when the deck has one (measured: a cover with a
    subtitle and one point went on a layout with no subtitle place, the subtitle left out and the reply claiming it)."""
    from . import layouts

    best = None
    for lay in prs.slide_layouts:
        where = layouts.slots(lay, prs.slide_width, prs.slide_height)
        items = where["items"]
        if where["heading"] is None or not items or _needs_other_content(prs, lay):  # (measured: a cover on "7_Tabela")
            continue
        series = len(items) >= points and _alike(lay, items[:points], prs.slide_width, prs.slide_height)
        fit = len(items) - points if series else (1000 if max(i["room"] for i in items) >= points else None)
        if fit is not None and subtitle and where["subtitle"] is None:
            fit += 10_000  # without a place for the subtitle: only when no layout has both
        roles = {x["role"] for x in layouts.placeholders(lay, prs.slide_width, prs.slide_height)}
        if fit is not None and "picture" in roles:
            # a picture place left empty shows as a grey block (looked at: an index on "1_Agenda C/Imagem", 2 runs in
            # 8); its layout only when none without one fits ("2_Agenda S/Imagem")
            fit += 500
        if fit is not None and (best is None or fit < best[0]):
            best = (fit, lay)
    return best and best[1]


def _layout_for_content(prs, content: dict):
    """The layout content fits: for points, the one with the closest number of boxes (_best_layout); for a title and a
    subtitle alone, the first with a heading, a subtitle and no text boxes (a cover); else the first with a heading."""
    from . import layouts

    points = len([p for p in content.get("points") or [] if any(_point_text(p))])
    if points:
        found = _best_layout(prs, points, bool(content.get("subtitle")))
        if found is not None:
            return found
    plain = []  # a heading and only text: no picture, table, chart or diagram left empty on the slide
    for lay in prs.slide_layouts:
        where = layouts.slots(lay, prs.slide_width, prs.slide_height)
        roles = [x["role"] for x in layouts.placeholders(lay, prs.slide_width, prs.slide_height)]
        if where["heading"] is None or any(r in ("picture", "table", "chart", "diagram", "media") for r in roles):
            continue
        if content.get("subtitle") and where["subtitle"] is not None and not where["items"]:
            found = cover_layout(prs)
            return found if found is not None else lay
        head = next(x for x in layouts.placeholders(lay, prs.slide_width, prs.slide_height) if x["role"] == "heading")
        # a content slide: a heading at the top and a text area (measured: by fewest places alone, the closing message;
        # then a 60 pt statement; then a layout whose text box is 8 pt)
        if head["y"] < 0.2 and head["size"] <= 32 and max([i["room"] for i in where["items"]] or [0]) >= 8:
            plain.append((len(roles), lay))
    return min(plain, key=lambda x: x[0])[1] if plain else prs.slide_layouts[0]


def add_slides(prs, slides: list[dict], layout: str | None = None, after_slide_id: int | None = None, deck_id=None) -> dict:
    """Several new slides, one for each item ({title, subtitle, points, layout?}), in order, each on its layout or the
    one its content fits (measured: "a slide for each of these points" made one slide listing them, 2 runs in 2)."""
    made = []
    after = after_slide_id
    for item in slides:
        name = item.get("layout") or layout
        try:
            lay = _layout(prs, name) if name else _layout_for_content(prs, item)
        except OpError:
            lay = _layout_for_content(prs, item)
        content = {k: item[k] for k in ("title", "subtitle", "points", "sources") if item.get(k)}
        got = add_slide(prs, lay.name, after_slide_id=after, content=content)
        made += got["slides"] if isinstance(got, dict) else got
        after = made[-1]
    return {"slides": made, "new_slide_ids": made}


def cover_layout(prs):
    """A cover: a layout with a heading and a subtitle and no text area, nothing a table, chart or diagram would fill,
    whose heading can be read on its background (layouts.readable); one without a picture place first, else one whose
    photo place is left out (_place_content). None when the template has none."""
    from . import layouts

    W, H = prs.slide_width, prs.slide_height
    found = []
    for lay in prs.slide_layouts:
        where = layouts.slots(lay, W, H)
        roles = {x["role"] for x in layouts.placeholders(lay, W, H)}
        # (a number place: a section divider's, "00" - looked at: the cover put on "2_Separador S/Imagem")
        others = roles & {"table", "chart", "diagram", "media", "number"}
        if where["heading"] is None or where["subtitle"] is None or where["items"] or others:
            continue
        if layouts.readable(lay, W, H):
            found.append(("picture" in roles, lay))
    return min(found, key=lambda x: x[0])[1] if found else None


def layout_for_new(prs, content: dict, first: bool):
    """A new slide's layout from its content (_layout_for_content); a deck's first slide on the cover when its content
    is a cover's - a title, and a subtitle or short points that are its lines (_cover_subtitle) - (measured: on an
    empty deck "a cover ... for the sales team, October 2026" sent with those as points went on "6_Texto", 2 runs in 2)."""
    if first and content.get("title"):
        cover = cover_layout(prs)
        if cover is not None and not _cover_subtitle(prs, cover, content, True).get("points"):
            return cover
    return _layout_for_content(prs, content)


def list_layout(prs):
    """For a generated slide's list (add_outline): the layout, with its heading at the top and nothing but text, whose
    largest text area is wide and tall, the roomiest (looked at: Banco CTT's points spread one in each of "3_Texto"'s
    boxes - a dark banner, a line, two columns - read as fragments; as one list in "12_Texto" they read as a slide)."""
    from . import layouts

    W, H = prs.slide_width, prs.slide_height
    best = None
    for lay in prs.slide_layouts:
        where = layouts.slots(lay, W, H)
        ps = layouts.placeholders(lay, W, H)
        others = {x["role"] for x in ps} & {"picture", "table", "chart", "diagram", "media"}
        if where["heading"] is None or not where["items"] or others:
            continue
        if any(ph.placeholder_format.type is not None and ph._element.ph.get("orient") == "vert" for ph in lay.placeholders):
            continue  # vertical text (looked at: the default template's "Vertical Title and Text" chosen for a list)
        head = next(x for x in ps if x["role"] == "heading")
        big = next(x for x in ps if x["idx"] == where["large"])
        room = max(i["room"] for i in where["items"])
        if head["y"] < 0.2 and big["w"] >= 0.6 and big["h"] >= 0.3 and (best is None or room > best[0]):
            best = (room, lay)
    return best and best[1]


def section_layout(prs):
    """The template's section divider: a layout with a heading and a number place, no text area or picture (Banco
    CTT's "2_Separador S/Imagem"); else the cover-like layout a title and a subtitle fit."""
    from . import layouts

    for lay in prs.slide_layouts:
        where = layouts.slots(lay, prs.slide_width, prs.slide_height)
        roles = {x["role"] for x in layouts.placeholders(lay, prs.slide_width, prs.slide_height)}
        plain = not roles & {"picture", "table", "chart"}
        if where["heading"] is not None and "number" in roles and not where["items"] and plain:
            return lay
    return _layout_for_content(prs, {"title": "-", "subtitle": "-"})


def _form_layout(prs, form: str, n: int = 0):
    """The template's layout for a design's form (agent/artist.py), else None (the caller falls back): figures, a layout
    with n boxes alike each with a number place ("17_Text"); highlight, a heading of 48 pt or more over one text box at
    most ("1_Highlight"); table, a heading and a table place and no text box ("3_Tabela")."""
    from . import layouts

    W, H = prs.slide_width, prs.slide_height
    found = []
    for lay in prs.slide_layouts:
        ps = layouts.placeholders(lay, W, H)
        roles = {x["role"] for x in ps}
        where = layouts.slots(lay, W, H)
        if where["heading"] is None or roles & {"picture", "chart", "diagram", "media"}:
            continue
        head = next(x for x in ps if x["role"] == "heading")
        items = where["items"]
        if form == "figures" and "table" not in roles and len(items) >= n and all(i["number"] is not None for i in items[:n]):
            if _alike(lay, items[:n], W, H):
                found.append((len(items) - n, lay))
        elif form == "highlight" and "table" not in roles and head["size"] >= 48 and len(items) <= 1:
            # (48 pt: Banco CTT's "1_Highlight" is 60; the default template's "Section Header", 40, set it small, in capitals)
            # its heading readable on its background, a place for the line under it first (looked at: on "2_Capa S/Imagem",
            # 48 pt and no text box, the statement was white on white)
            if layouts.readable(lay, W, H):
                found.append((0 if len(items) == 1 else 1, lay))
        elif form == "table" and "table" in roles and not items:
            found.append((0, lay))
    return min(found, key=lambda x: x[0])[1] if found else None


def _draw_table(prs, s, rows: list[list[str]]) -> int:
    """A table on the slide: in its layout's table place when it has one (the template's own table style), else under its
    title. The first row is the header. Returns the table's shape ID."""
    from . import layouts

    rows = [[str(c) for c in r] for r in rows]
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    place = next((ph for ph in s.placeholders if ph.placeholder_format.type is not None
                  and ph.placeholder_format.type.name == "TABLE"), None)  # fmt: skip
    if place is not None:
        frame = place.insert_table(len(rows), cols)
    else:
        W, H = prs.slide_width, prs.slide_height
        head = layouts.heading(s.slide_layout, W, H)
        top = next((ph.top + ph.height for ph in s.placeholders if ph.placeholder_format.idx == head), int(H * 0.2))
        frame = s.shapes.add_table(len(rows), cols, int(W * 0.06), int(top + H * 0.04), int(W * 0.88), int(H * 0.08) * len(rows))
    table = frame.table
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            table.cell(r, c).text = text
    return frame.shape_id


def add_designed(prs, item: dict, after_slide_id: int | None = None, position: int | None = None) -> list[int]:
    """A slide made in the form its design gives (agent/artist.py; contracts/storage/design.schema.json): {title,
    design: {form, ...}, points?}. The application chooses the layout for the form; a form the template has no layout
    for falls back to the nearest one (figures as columns, highlight as a title over its line, table under the title).
    Without a design (or a bullets one), the list as one bulleted text (list_layout). Returns the slides made."""
    title = item.get("title") or ""
    design = item.get("design") or {"form": "bullets", "points": item.get("points") or []}
    form = design.get("form") or "bullets"
    place = {"after_slide_id": after_slide_id, "position": position}

    def made(got) -> list[int]:
        return got["slides"] if isinstance(got, dict) else got

    if form == "columns" and design.get("columns"):
        cols = design["columns"]
        points = [{"heading": c.get("heading") or "", "text": "\n".join(c.get("points") or [])} for c in cols]
        lay = _best_layout(prs, len(points)) or _layout_for_content(prs, {"title": title, "points": points})
        return made(add_slide(prs, lay.name, **place, content={"title": title, "points": points}))
    if form == "figures" and design.get("figures"):
        figs = design["figures"]
        lay = _form_layout(prs, "figures", len(figs))
        if lay is not None:
            content = {"title": title, "points": [{"heading": f["label"]} for f in figs], "numbers": [f["value"] for f in figs]}
            return made(add_slide(prs, lay.name, **place, content=content))
        points = [{"heading": f["value"], "text": f["label"]} for f in figs]  # no number places: each figure a column
        lay = _best_layout(prs, len(points)) or _layout_for_content(prs, {"title": title, "points": points})
        return made(add_slide(prs, lay.name, **place, content={"title": title, "points": points}))
    if form == "highlight" and design.get("highlight"):
        h = design["highlight"]
        lay = _form_layout(prs, "highlight")
        if lay is not None:
            content = {"title": h["statement"], **({"points": [h["detail"]]} if h.get("detail") else {})}
        else:
            # a large title over its subtitle (looked at: the default template's "Section Header" set the statement small,
            # its line above it)
            lay = cover_layout(prs) or section_layout(prs)
            content = {"title": h["statement"], **({"subtitle": h["detail"]} if h.get("detail") else {})}
        return made(add_slide(prs, lay.name, **place, content=content))
    if form == "table" and design.get("table"):
        lay = _form_layout(prs, "table") or _layout_for_content(prs, {"title": title})
        ids = made(add_slide(prs, lay.name, **place, content={"title": title}))
        s = prs.slides.get(ids[0])
        for ph in list(s.placeholders):  # the text place the table goes under, left empty, goes
            if ph.has_text_frame and not ph.text_frame.text.strip():
                ph._element.getparent().remove(ph._element)
        _draw_table(prs, s, design["table"]["rows"])
        return ids
    # a chart or a diagram in the widest text area (looked at: on "8_Texto"'s narrow column a diagram's boxes broke words)
    wide = list_layout(prs) or _layout_for_content(prs, {"title": title})
    if form == "chart" and design.get("chart"):
        lay = wide
        return made(add_slide(prs, lay.name, **place, content={"title": title, "chart": design["chart"]}))
    if form == "diagram" and design.get("diagram"):
        d = design["diagram"]
        figure = {"nodes": [{"text": x} for x in d["nodes"]], "direction": d.get("direction") or "right"}
        lay = wide
        return made(add_slide(prs, lay.name, **place, content={"title": title, "diagram": figure}))
    points = design.get("points") or item.get("points") or []
    content = {"title": title, **({"points": points, "as_list": True} if points else {})}
    lay = (list_layout(prs) if points else None) or _layout_for_content(prs, content)
    return made(add_slide(prs, lay.name, **place, content=content))


def redesign_slide(prs, slide_id: int, design: dict, deck_id=None) -> dict:
    """A slide made again in another form (the Artist's proposal the person chose): at its place, with its title and its
    notes; the old slide goes. Returns {slides: the new ones, removed}."""
    from . import layouts

    s = get_slide(prs, slide_id)
    pos = list(prs.slides).index(s)
    head = layouts.heading(s.slide_layout, prs.slide_width, prs.slide_height)
    title = next((ph.text_frame.text.strip() for ph in s.placeholders
                  if ph.placeholder_format.idx == head and ph.has_text_frame), "")  # fmt: skip
    notes = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
    old = s.slide_id
    ids = add_designed(prs, {"title": title, "design": design}, position=pos)
    delete_slide(prs, old)
    if notes.strip():
        for sid in ids:
            set_notes(prs, sid, notes)
    return {"slides": ids, "new_slide_ids": ids, "removed": [old]}


def add_outline(prs, slides: list[dict], cover: dict | None = None, after_slide_id: int | None = None, deck_id=None) -> dict:
    """A generated deck's slides (spec NL-12; domain/generations.py): a cover ({title, subtitle}), then each slide
    ({role, title, points, notes}) on the layout its role and content fit - a "section" on the template's divider,
    its first point as the subtitle - with its notes; a list too long for one slide goes on over the next ones
    (add_slide). Returns {slides, cover}."""
    made, after, first = [], after_slide_id, None
    if cover and cover.get("title"):
        content = {k: cover[k] for k in ("title", "subtitle") if cover.get(k)}
        # a cover's layout even with its title alone (measured: chosen for the title only, the cover went on "Title and
        # Content", a small title over an empty page); a subtitle place left empty is removed as any
        lay = cover_layout(prs) or _layout_for_content(prs, {"title": content["title"], "subtitle": "-"})
        got = add_slide(prs, lay.name, after_slide_id=after, content=content)
        made += got["slides"] if isinstance(got, dict) else got
        first, after = made[0], made[-1]
    for item in slides:
        if item.get("role") == "section":
            content = {"title": item["title"], **({"subtitle": item["points"][0]} if item.get("points") else {})}
            lay = section_layout(prs)
        else:
            lay = None  # its design's form chooses (add_designed; agent/artist.py)
        if lay is not None:
            got = add_slide(prs, lay.name, after_slide_id=after, content=content)
            ids = got["slides"] if isinstance(got, dict) else got
        else:
            ids = add_designed(prs, item, after_slide_id=after)
        if item.get("notes"):
            for sid in ids:  # a slide continued on the next: its notes on each
                set_notes(prs, sid, item["notes"])
        made += ids
        after = made[-1]
    return {"slides": made, "new_slide_ids": made, "cover": first}


def fill_slide(prs, slide_id: int, content: dict, layout: str | None = None, deck_id=None) -> dict:
    """A slide's content put in its layout's places (_place_content); the text it had there is replaced. On `layout`
    when given; when its layout has no place for the points, on the layout that fits them best (measured: told the
    layouts that fit, the model called fill_slide again unchanged, or wrote the title only, and said it was done)."""
    from . import layouts

    s = get_slide(prs, slide_id)
    moved = None
    if not content.get("title"):  # no new title: the slide's own stays, even on another layout (measured: points
        # alone sent for an index, its slide went without a heading)
        head = layouts.slots(s.slide_layout, prs.slide_width, prs.slide_height)["heading"]
        own = next((ph.text_frame.text.strip() for ph in s.placeholders
                    if ph.placeholder_format.idx == head and ph.has_text_frame), "")  # fmt: skip
        if own:
            content = {**content, "title": own}
    try:
        target = _layout(prs, layout) if layout else s.slide_layout
    except OpError:
        target = s.slide_layout
    sent_subtitle = " ".join(str(content.get("subtitle") or "").split())
    before = content
    content = _cover_subtitle(prs, target, content, list(prs.slides).index(s) == 0)
    folded = content is not before
    points = len([p for p in content.get("points") or [] if any(_point_text(p))])
    if layout:
        try:
            lay = _layout(prs, layout)
        except OpError:  # measured: "Layouts of this deck" (a heading of the context) sent as the layout
            lay = _layout_for_content(prs, content)
        if points and not layouts.slots(lay, prs.slide_width, prs.slide_height)["items"]:
            # a layout named with no place for the points: the one they fit (measured: an index for an empty cover,
            # sent with the cover's own layout named, refused as NO_PLACE, and the title alone written, 2 runs in 3)
            lay = _best_layout(prs, points, bool(content.get("subtitle"))) or lay
        if lay.name != s.slide_layout.name:
            _relayout(s, lay)
            moved = lay.name
    elif points and not layouts.slots(s.slide_layout, prs.slide_width, prs.slide_height)["items"]:
        lay = _best_layout(prs, points, bool(content.get("subtitle")))
        if lay is not None:
            _relayout(s, lay)
            moved = lay.name
    where = layouts.slots(s.slide_layout, prs.slide_width, prs.slide_height)
    places = {where["heading"], where["subtitle"]} | {i[k] for i in where["items"] for k in ("body", "header", "number")}
    have = {ph.placeholder_format.idx for ph in s.placeholders}
    for lp in s.slide_layout.placeholders:  # the places an earlier placement removed, back from the layout
        if lp.placeholder_format.idx in places - have:
            s.shapes.clone_placeholder(lp)
    keep = {where["heading"]} if not content.get("title") else set()  # no new title: the slide's own stays
    for ph in s.placeholders:  # what the slide said in those places goes: the content is the new content
        if ph.placeholder_format.idx in places - keep and ph.has_text_frame:
            _set_paragraphs(ph.text_frame, [{"runs": [{"text": ""}]}])
    left_out = _place_content(prs, s, content)
    out = {"slides": [s.slide_id], **({"layout": moved} if moved else {}), **({"left_out": left_out} if left_out else {})}
    if folded and sent_subtitle and _overflowing(prs, s.slide_id):  # as add_slide: the cover's lines first
        lean = {k: v for k, v in content.items() if k != "subtitle"}
        lean["subtitle"] = "\n".join(x for x in content["subtitle"].split("\n") if x != sent_subtitle) or ""
        if not lean["subtitle"]:
            lean.pop("subtitle")
        for ph in s.placeholders:
            if ph.placeholder_format.idx in places and ph.has_text_frame:
                _set_paragraphs(ph.text_frame, [{"runs": [{"text": ""}]}])
        for lp in s.slide_layout.placeholders:  # places the first placement removed, back
            if lp.placeholder_format.idx in places - {ph.placeholder_format.idx for ph in s.placeholders}:
                s.shapes.clone_placeholder(lp)
        _place_content(prs, s, lean)
        _subtitle_to_notes(prs, s.slide_id, sent_subtitle)
        out["moved_to_notes"] = "subtitle"
    return out


def delete_slide(prs, slide_id: int, deck_id=None) -> list[int]:
    target = get_slide(prs, slide_id).slide_id  # read once: the slide cannot answer after its link is dropped
    ids = prs.slides._sldIdLst
    for e in list(ids):
        if int(e.get("id")) == target:
            prs.part.drop_rel(e.rId)
            ids.remove(e)
            break
    return [target]


def move_slide(
    prs,
    slide_id: int,
    position: int | None = None,
    after_slide_id: int | None = None,
    before_slide_id: int | None = None,
    deck_id=None,
) -> list[int]:
    s = get_slide(prs, slide_id)
    if position is None and after_slide_id is None and before_slide_id is None:
        raise OpError("BAD_ARGUMENTS", "Say where the slide goes.", "Give after_slide_id, before_slide_id or position.")
    _move_to(prs, s, _place(prs, s, position, after_slide_id, before_slide_id, default=0))
    return [s.slide_id]


def _copy_part(part, package, cache: dict):
    """A copy of a content part (a chart, an embedded workbook, SmartArt's parts) with its own relationships copied
    too, under a new part name; images and media are shared, not copied (a package may reference one part twice)."""
    if part.partname in cache:
        return cache[part.partname]
    if part.content_type.startswith(("image/", "video/", "audio/")) or "media" in str(part.partname):
        return part
    base = str(part.partname)
    stem, ext = base.rsplit(".", 1)
    digits = len(stem) - len(stem.rstrip("0123456789"))
    tmpl = (stem[:-digits] if digits else stem) + "%d." + ext
    new = Part.load(package.next_partname(tmpl), part.content_type, package, part.blob)
    cache[part.partname] = new
    # the copy's XML (its blob, unchanged) refers to its relationships by id: each keeps the original's rId
    for rid, rel in part.rels.items():
        target = rel.target_ref if rel.is_external else _copy_part(rel.target_part, package, cache)
        new.rels._rels[rid] = _Relationship(
            new.rels._base_uri, rid, rel.reltype, RTM.EXTERNAL if rel.is_external else RTM.INTERNAL, target
        )
    return new


def _copy_shapes_into(src_slide, dst_slide, *, skip_placeholders: bool = False) -> list[str]:
    """Deep-copy src's shape tree into dst with every content relationship recreated (new rIds rewritten in the XML).
    Returns the names of shapes it could not carry."""
    package = dst_slide.part.package
    cache: dict = {}
    rid_map: dict[str, str] = {}
    for rid, rel in src_slide.part.rels.items():
        if rel.reltype not in CONTENT_RELS:
            continue
        if rel.is_external:
            rid_map[rid] = dst_slide.part.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref)
        else:
            target = _copy_part(rel.target_part, package, cache) if src_slide.part.package is package else rel.target_part
            rid_map[rid] = dst_slide.part.relate_to(target, rel.reltype)
    tree = dst_slide.shapes._spTree
    for el in src_slide.shapes._spTree.iterchildren():
        if el.tag in (qn("p:nvGrpSpPr"), qn("p:grpSpPr")):
            continue
        if skip_placeholders and el.find(f".//{qn('p:ph')}") is not None:
            continue
        clone = copy.deepcopy(el)
        for node in clone.iter():
            for attr, value in list(node.attrib.items()):
                if attr.startswith("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}") and value in rid_map:
                    node.set(attr, rid_map[value])
        tree.append(clone)
    return []


# ── slides from another deck (spec PJ-6, PJ-7) ──────────────────────
def _foreign_part(part, package, cache: dict):
    """A part of another deck copied into `package` under a new name, with its own relationships copied too - media
    included: a part is never shared between two packages (its name could be taken in the other one)."""
    if id(part) in cache:
        return cache[id(part)]
    stem, ext = str(part.partname).rsplit(".", 1)
    digits = len(stem) - len(stem.rstrip("0123456789"))
    new = Part.load(
        package.next_partname((stem[:-digits] if digits else stem) + "%d." + ext), part.content_type, package, part.blob
    )
    cache[id(part)] = new
    for rid, rel in part.rels.items():
        target = rel.target_ref if rel.is_external else _foreign_part(rel.target_part, package, cache)
        new.rels._rels[rid] = _Relationship(
            new.rels._base_uri, rid, rel.reltype, RTM.EXTERNAL if rel.is_external else RTM.INTERNAL, target
        )
    return new


def _ph_kind(ph) -> str | None:
    """A placeholder's role, as two templates share them: title, subtitle, body, picture; None for the footer ones."""
    t = ph.placeholder_format.type
    name = t.name.lower() if t is not None else "body"
    if name in ("title", "center_title", "vertical_title"):
        return "title"
    if name in ("date", "footer", "slide_number", "header"):
        return None
    if name in ("body", "object", "vertical_body", "vertical_object"):
        return "body"
    return name


def _kinds(layout) -> list[str]:
    return [k for k in (_ph_kind(ph) for ph in layout.placeholders) if k]


def _layout_for(prs: Presentation, source_layout):
    """The target deck's layout for a slide of another deck: the one of the same name, else the one whose
    placeholders (title, body, picture...) differ least from the source's."""
    layouts = [lay for m in prs.slide_masters for lay in m.slide_layouts]
    plain = " ".join(source_layout.name.split()).casefold()
    for lay in layouts:
        if " ".join(lay.name.split()).casefold() == plain:
            return lay
    want = _kinds(source_layout)

    def distance(lay) -> tuple[int, int]:
        have = _kinds(lay)
        missing = sum(max(want.count(k) - have.count(k), 0) for k in set(want))
        extra = sum(max(have.count(k) - want.count(k), 0) for k in set(have))
        return (missing * 2 + extra, len(have))

    return min(layouts, key=distance)


def _carry(clone, src_part, dst_part, cache: dict) -> bool:
    """Re-point a copied element's relationships (r:embed, r:id, r:link) to copies in the target deck. A link to
    another slide cannot come along: the hyperlink holding it is dropped. False when something could not be carried."""
    ok = True
    r_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    for node in list(clone.iter()):
        for attr, rid in list(node.attrib.items()):
            if not attr.startswith(r_ns) or rid not in src_part.rels:
                continue
            rel = src_part.rels[rid]
            if rel.is_external:
                node.set(attr, dst_part.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref))
            elif rel.reltype in CONTENT_RELS:
                node.set(attr, dst_part.relate_to(_foreign_part(rel.target_part, dst_part.package, cache), rel.reltype))
            elif node.tag in (qn("a:hlinkClick"), qn("a:hlinkHover")) and node.getparent() is not None:
                node.getparent().remove(node)  # a link to a slide of the other deck
            else:
                ok = False
    return ok


def _scaled(clone, sx: float, sy: float) -> None:
    if sx == 1 and sy == 1:
        return
    for xfrm in clone.iter(qn("a:off"), qn("a:ext"), qn("a:chOff"), qn("a:chExt")):
        for attr, f in (("x", sx), ("cx", sx), ("y", sy), ("cy", sy)):
            if xfrm.get(attr) is not None:
                xfrm.set(attr, str(int(int(xfrm.get(attr)) * f)))
    # a table's columns and rows too: its frame alone, scaled, left the grid wider than the slide (seen rendered)
    for col in clone.iter(qn("a:gridCol")):
        col.set("w", str(int(int(col.get("w", 0)) * sx)))
    for row in clone.iter(qn("a:tr")):
        row.set("h", str(int(int(row.get("h", 0)) * sy)))


def copy_slides(
    prs,
    source: bytes,
    slide_ids: list[int],
    from_deck_id=None,
    from_version=None,
    position: int | None = None,
    after_slide_id: int | None = None,
    before_slide_id: int | None = None,
    deck_id=None,
) -> dict:
    """Slides of another deck (`source`, its bytes) added to this one, on this deck's layouts and theme (spec PJ-7):
    the text of each placeholder goes to the matching placeholder of the target layout (title to title, the n-th body
    to the n-th body), so it takes this template's styles; text with no such place becomes a text box where it was,
    and is reported; pictures, tables, groups, charts and other shapes are copied with their parts. Speaker notes come
    along; animations do not (they name shapes by IDs that change). Returns {slides, unmatched}."""
    src = Presentation(io.BytesIO(source))
    sx, sy = prs.slide_width / src.slide_width, prs.slide_height / src.slide_height
    cache: dict = {}
    made, unmatched = [], []
    for n, sid in enumerate(slide_ids, 1):
        s = get_slide(src, int(sid))
        new = prs.slides.add_slide(_layout_for(prs, s.slide_layout))
        free = {}
        for ph in new.placeholders:
            if _ph_kind(ph):
                free.setdefault(_ph_kind(ph), []).append(ph)
        used = []
        for sh in s.shapes:
            if sh.is_placeholder:
                kind = _ph_kind(sh)
                text = sh.text_frame.text.strip() if getattr(sh, "has_text_frame", False) and sh.has_text_frame else ""
                if not kind or not text:
                    continue
                target = (free.get(kind) or [None])[0]
                if target is not None and getattr(target, "has_text_frame", False) and target.has_text_frame:
                    free[kind].pop(0)
                    used.append(target)
                    body = target.text_frame._txBody
                    for p in body.findall(qn("a:p")):
                        body.remove(p)
                    for p in sh.text_frame._txBody.findall(qn("a:p")):
                        body.append(copy.deepcopy(p))
                    continue
                box = new.shapes.add_textbox(int(sh.left * sx), int(sh.top * sy), int(sh.width * sx), int(sh.height * sy))
                body = box.text_frame._txBody
                for p in body.findall(qn("a:p")):
                    body.remove(p)
                for p in sh.text_frame._txBody.findall(qn("a:p")):
                    body.append(copy.deepcopy(p))
                unmatched.append(
                    f'slide {n}: "{text[:40]}" has no place in the layout "{new.slide_layout.name}": kept as a text box'
                )
                continue
            clone = copy.deepcopy(sh._element)
            if not _carry(clone, s.part, new.part, cache):
                unmatched.append(f'slide {n}: "{sh.name}" could not be copied (it refers to something only its deck has)')
                continue
            _scaled(clone, sx, sy)
            new.shapes._spTree.append(clone)
        for ph in list(new.placeholders):  # the layout's placeholders nothing went into
            if ph not in used and _ph_kind(ph) is not None:
                ph._element.getparent().remove(ph._element)
        if s._element.get("show") is not None:
            new._element.set("show", s._element.get("show"))
        _copy_notes(s, new)
        made.append(new)
    if not made:
        raise OpError("BAD_ARGUMENTS", "Name at least one slide to copy.", "")
    at = _place(prs, made[0], position, after_slide_id, before_slide_id, default=len(prs.slides) - len(made))
    for i, new in enumerate(made):
        _move_to(prs, new, at + i)
    return {"slides": [x.slide_id for x in made], "unmatched": unmatched}


def change_template(prs, template: bytes, template_ref=None, deck_id=None) -> dict:
    """The deck on another template (spec PM-10): a deck made from `template` (its slides removed), and every slide
    copied onto its layouts and theme as copy_slides does (layouts by kind, placeholders by type, what has no place
    reported). The slides keep their IDs, so the review shows each one changed. Returns {slides, unmatched}, and the
    new deck for apply() to save."""
    out = Presentation(io.BytesIO(template))
    for sld in list(out.slides._sldIdLst):  # a template's own sample slides
        out.part.drop_rel(sld.get(qn("r:id")))
        out.slides._sldIdLst.remove(sld)
    ids = [s.slide_id for s in prs.slides]
    buf = io.BytesIO()
    prs.save(buf)
    result = copy_slides(out, buf.getvalue(), ids)
    for el, old in zip(list(out.slides._sldIdLst), ids, strict=True):
        el.set("id", str(old))  # the same slides, on the new template
    return {"slides": ids, "unmatched": result["unmatched"], "_replace": out}


def _copy_notes(src, dst) -> None:
    if src.has_notes_slide and src.notes_slide.notes_text_frame is not None:
        text = src.notes_slide.notes_text_frame.text
        if text:
            dst.notes_slide.notes_text_frame.text = text


def duplicate_slide(
    prs,
    slide_id: int,
    position: int | None = None,
    after_slide_id: int | None = None,
    before_slide_id: int | None = None,
    deck_id=None,
) -> list[int]:
    src = get_slide(prs, slide_id)
    dst = prs.slides.add_slide(src.slide_layout)
    for ph in list(dst.placeholders):  # the layout's empty placeholders: the copy brings its own
        ph._element.getparent().remove(ph._element)
    _copy_shapes_into(src, dst)
    for attr in ("show",):
        if src._element.get(attr) is not None:
            dst._element.set(attr, src._element.get(attr))
    for child in (qn("p:transition"), qn("p:timing")):
        el = src._element.find(child)
        if el is not None:
            dst._element.append(copy.deepcopy(el))
    _copy_notes(src, dst)
    index = list(prs.slides).index(src)
    _move_to(prs, dst, _place(prs, dst, position, after_slide_id, before_slide_id, default=index + 1))
    return [dst.slide_id]


def change_layout(prs, slide_id: int, layout: str, deck_id=None) -> dict:
    """Re-map the slide's content onto another layout: a new slide with that layout at the same position, its
    placeholders filled from the old ones matched by type then index, the other shapes kept where they were, notes
    kept. Text with no matching placeholder is kept as a text box where it was (never dropped) and reported in
    `unmatched`. Returns {slides, unmatched}."""
    old = get_slide(prs, slide_id)
    lay = _layout(prs, layout)
    new = prs.slides.add_slide(lay)
    index = list(prs.slides).index(old)
    unmatched = []
    free = list(new.placeholders)

    def kind(ph):
        t = ph.placeholder_format.type
        name = t.name if t is not None else "BODY"
        return {"CENTER_TITLE": "TITLE", "OBJECT": "BODY", "SUBTITLE": "BODY"}.get(name, name)

    for ph in list(old.placeholders):
        if not ph.has_text_frame:
            unmatched.append(ph.name)
            continue
        if not ph.text_frame.text.strip():
            continue
        match = next(
            (f for f in free if kind(f) == kind(ph) and f.placeholder_format.idx == ph.placeholder_format.idx), None
        ) or next((f for f in free if kind(f) == kind(ph)), None)
        if match is None:
            # no place for it in the new layout: kept as a text box where it was, never lost; reported
            box = new.shapes.add_textbox(ph.left, ph.top, ph.width, ph.height)
            body = box.text_frame._txBody
            for p in body.findall(qn("a:p")):
                body.remove(p)
            for p in ph.text_frame._txBody.findall(qn("a:p")):
                body.append(copy.deepcopy(p))
            box.text_frame.word_wrap = True
            unmatched.append(ph.name)
            continue
        free.remove(match)
        body = match.text_frame._txBody
        for p in body.findall(qn("a:p")):
            body.remove(p)
        for p in ph.text_frame._txBody.findall(qn("a:p")):
            body.append(copy.deepcopy(p))
    _copy_shapes_into(old, new, skip_placeholders=True)
    for child in (qn("p:transition"), qn("p:timing")):
        el = old._element.find(child)
        if el is not None:
            new._element.append(copy.deepcopy(el))
    _copy_notes(old, new)
    if old._element.get("show") == "0":
        new._element.set("show", "0")
    delete_slide(prs, old.slide_id)
    _move_to(prs, new, index)
    return {"slides": [new.slide_id], "unmatched": unmatched}


# ── shapes ───────────────────────────────────────────────────────────
def _box_emu(prs, box: dict) -> tuple[int, int, int, int]:
    x, y, w, h = (float(box[k]) for k in ("x", "y", "w", "h"))
    if not (0 <= x and 0 <= y and w > 0 and h > 0 and x + w <= 1.0001 and y + h <= 1.0001):
        raise OpError("OUT_OF_BOUNDS", "The box must lie within the slide: x, y, w, h are fractions of its size (0 to 1).", "")
    W, H = int(prs.slide_width), int(prs.slide_height)
    return round(x * W), round(y * H), round(w * W), round(h * H)


def add_shape(prs, slide_id: int, kind: str, box: dict, paragraphs: list[dict] | None = None, deck_id=None) -> dict:
    """kind: text_box | rectangle | rounded_rectangle | oval. Returns {slides, shape_id}."""
    s = get_slide(prs, slide_id)
    x, y, w, h = (Emu(v) for v in _box_emu(prs, box))
    if kind == "text_box":
        sh = s.shapes.add_textbox(x, y, w, h)
        sh.text_frame.word_wrap = True
    else:
        shapes = {"rectangle": MSO_SHAPE.RECTANGLE, "rounded_rectangle": MSO_SHAPE.ROUNDED_RECTANGLE, "oval": MSO_SHAPE.OVAL}
        if kind not in shapes:
            raise OpError("BAD_KIND", f'Unknown shape kind "{kind}".', "Use text_box, rectangle, rounded_rectangle or oval.")
        sh = s.shapes.add_shape(shapes[kind], x, y, w, h)  # its fill and line come from the theme's shape style
    if paragraphs:
        _set_paragraphs(sh.text_frame, paragraphs)
    return {"slides": [s.slide_id], "shape_id": sh.shape_id}


# ── text that does not fit ───────────────────────────────────────────
MIN_BODY_PT = 14  # body text is never set smaller (the system prompt's rule)


def fit_text(prs, slide_id: int, shape_id: int, deck_id=None) -> dict:
    """Shrink a shape's text to fit its box, as PowerPoint's "shrink text on overflow" does (normAutofit with a font
    scale): the largest scale at which it fits (textfit.py), never below 14 pt; failing that, grow the box down into
    free space, as "resize shape to fit text" does. Returns {slides, scale, grown_pt?}; CANNOT_FIT when neither can
    (then the text must be shortened or split)."""
    from . import textfit

    s = get_slide(prs, slide_id)
    sh = get_shape(s, shape_id)
    if not getattr(sh, "has_text_frame", False) or not sh.has_text_frame:
        raise OpError("NO_TEXT", f"Shape {shape_id} holds no text.", "")
    body = sh.text_frame._txBody.find(qn("a:bodyPr"))
    for tag in ("a:spAutoFit", "a:noAutofit", "a:normAutofit"):
        for x in body.findall(qn(tag)):
            body.remove(x)
    fit = etree.SubElement(body, qn("a:normAutofit"))
    smallest = textfit.smallest_size(sh) or MIN_BODY_PT
    floor = min(1.0, MIN_BODY_PT / smallest) if smallest > MIN_BODY_PT else 1.0
    # a word wider than the box at every size down to the floor: its height still fitted (measured: a 210-character
    # string with no space left the list at full size, past its box, and spread over another slide)
    for words in (True, False):
        scale = 1.0
        while True:  # the scale written at every step: measured at it, not taken on trust
            fit.set("fontScale", str(round(scale * 100000)))
            if textfit.overflows(sh, words=words) is False:
                if words and scale < 1:
                    # made smaller for a word's width alone (its height fits at full size): the size written into its
                    # runs, as every renderer then shows it (textfit.write_sizes)
                    fit.set("fontScale", "100000")
                    width_only = textfit.overflows(sh, words=False) is False
                    fit.set("fontScale", str(round(scale * 100000)))
                    if width_only:
                        textfit.write_sizes(sh)
                return {"slides": [s.slide_id], "scale": round(scale, 3)}
            if scale - 0.025 < floor - 1e-9:
                break
            scale -= 0.025
    body.remove(fit)
    # not by shrinking (the 14 pt floor): the box grown down into free space, as PowerPoint's "resize shape to fit
    # text" (measured: an 11th item in a 12 pt list, refused shrinking, and the turn ended with it 49 pt too long)
    m = textfit.measure(sh)
    if m is not None:
        # the text's lines, whole, and the insets (anchored in the middle or at the bottom, it runs out above too);
        # measured: to its glyphs' baseline only, the last line's descenders crossed the box's border
        need = int(m["extent"] * textfit.EMU_PT) + m["tIns"] + m["bIns"] - sh.height
        if need > 0 and sh.top + sh.height + need <= prs.slide_height:
            below = (sh.left, sh.top + sh.height, sh.width, need)
            if not _overlapping(below, _boxes(prs, s, {sh.shape_id})):
                sh.height = sh.height + need
                if textfit.overflows(sh) is False:
                    return {"slides": [s.slide_id], "scale": 1.0, "grown_pt": round(need / textfit.EMU_PT, 1)}
                sh.height = sh.height - need
    raise OpError(
        "CANNOT_FIT",
        f"Shape {shape_id}'s text does not fit its box even at {MIN_BODY_PT} pt.",
        "Make the box larger (move_resize_shape), shorten the text, or split it over two slides.",
    )


# ── diagrams made of shapes (technical design M7) ─────────────────────
def _top_level(slide, sh, what: str) -> None:
    """A shape in a group is placed in the group's own coordinates: copied or connected as if on the slide, it would
    land elsewhere."""
    if sh._element.getparent() is not slide.shapes._spTree:
        message = f"Shape {sh.shape_id} is inside a group: it cannot be {what} on its own."
        raise OpError("IN_GROUP", message, "Use shapes outside groups.")


def _boxes(prs, slide, but: set[int]) -> list[tuple[int, int, int, int, int]]:
    """The slide's own shapes as (id, x, y, w, h), backgrounds and connectors aside (a shape over half the slide is
    behind the diagram, unless it is a text placeholder with text: a slide's list is content, however large its box -
    measured: a chart drawn over a bullet in "Title and Content" was not reported; a connector's box is far larger than
    its line)."""
    area = prs.slide_width * prs.slide_height
    out = []
    for sh in slide.shapes:
        if sh.shape_id in but or sh.left is None or sh.width is None:
            continue
        text = sh.is_placeholder and sh.has_text_frame and sh.text_frame.text.strip()
        if sh.width * sh.height > area / 2 and not text:
            continue
        if sh._element.tag == qn("p:cxnSp"):
            continue
        if sh.is_placeholder and sh.has_text_frame and not sh.text_frame.text.strip():
            continue  # an empty placeholder: a diagram is often drawn where it is
        out.append((sh.shape_id, sh.left, sh.top, sh.width, sh.height))
    return out


def _overlapping(box: tuple[int, int, int, int], others) -> list[int]:
    x, y, w, h = box
    return [i for i, ox, oy, ow, oh in others if x < ox + ow and ox < x + w and y < oy + oh and oy < y + h]


def _free_place(prs, slide, src, others, near: tuple[int, int] | None = None) -> tuple[int, int]:
    """The nearest place beside `src` where a copy of its size touches no other shape: right, below, left, above,
    then a step further out each way; else right of it, as before (measured: placed by the model, a new box of a
    diagram covered another, and with no place given, its default spot did too)."""
    w, h = src.width, src.height
    gap_x, gap_y = max(w // 4, 1), max(h // 3, 1)
    cx, cy = near or (src.left, src.top)  # the place it should be nearest to: the original, or the one asked for

    def clear(x, y) -> bool:  # free with room around it (measured: placed touching two boxes, its arrow had no length)
        return not _overlapping((x - gap_x, y - gap_y, w + 2 * gap_x, h + 2 * gap_y), others)

    for step in (1, 2, 3) if near is None else ():
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            x = src.left + dx * step * (w + gap_x)
            y = src.top + dy * step * (h + gap_y)
            inside = 0 <= x and 0 <= y and x + w <= prs.slide_width and y + h <= prs.slide_height
            if inside and clear(x, y):
                return x, y
    # nothing free beside it: the free place nearest to it anywhere on the slide (a grid of half its size)
    best = None
    for gy in range(0, prs.slide_height - h + 1, max(h // 2, 1)):
        for gx in range(0, prs.slide_width - w + 1, max(w // 2, 1)):
            if clear(gx, gy):
                d = (gx - cx) ** 2 + (gy - cy) ** 2
                if best is None or d < best[0]:
                    best = (d, gx, gy)
    if best:
        return best[1], best[2]
    return max(0, min(src.left + int(w * 1.1), prs.slide_width - w)), src.top


def _next_shape_id(slide) -> int:
    used = [int(x.get("id")) for x in slide.shapes._spTree.iter(qn("p:cNvPr")) if (x.get("id") or "").isdigit()]
    return max(used, default=1) + 1


def duplicate_shape(
    prs, slide_id: int, shape_id: int, box: dict | None = None, paragraphs: list[dict] | None = None, deck_id=None
) -> dict:
    """A copy of a shape - its geometry, outline, fill and text styling - under a new ID, at `box` (fractions of the
    slide; w and h left out: the original's size) or just right of the original; with `paragraphs`, its text (the
    first run's styling kept). A diagram grows with boxes like its own (measured on a real diagram: add_shape's boxes
    came in the theme's style, not the diagram's). Returns {slides, shape_id}."""
    s = get_slide(prs, slide_id)
    src = get_shape(s, shape_id, editable=False)  # copied, not changed
    _top_level(s, src, "copied")
    if src.is_placeholder:
        raise OpError("PLACEHOLDER", "A placeholder cannot be copied.", "Copy a shape or a text box.")
    el = copy.deepcopy(src._element)
    new_id = _next_shape_id(s)
    c_nv = el.find(".//" + qn("p:cNvPr"))
    c_nv.set("id", str(new_id))
    c_nv.set("name", f"{c_nv.get('name', 'Shape')} {new_id}")
    for ext in c_nv.findall(qn("a:extLst")):  # PowerPoint's creation ID: a copy has none (it would repeat)
        c_nv.remove(ext)
    for tag in ("a:stCxn", "a:endCxn"):  # a copied connector is not attached to the original's shapes
        for x in el.iter(qn(tag)):
            x.getparent().remove(x)
    xfrm = el.find(".//" + qn("a:xfrm"))
    if xfrm is None:
        raise OpError("NOT_PLACED", f"Shape {shape_id} has no position of its own.", "Copy another shape.")
    off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
    if box:  # w and h left out: the original's size
        w = box.get("w") or int(ext.get("cx")) / prs.slide_width
        h = box.get("h") or int(ext.get("cy")) / prs.slide_height
        x, y, w, h = _box_emu(prs, {"x": box["x"], "y": box["y"], "w": w, "h": h})
        off.set("x", str(int(x)))
        off.set("y", str(int(y)))
        ext.set("cx", str(int(w)))
        ext.set("cy", str(int(h)))
    else:  # the nearest free place beside the original
        x, y = _free_place(prs, s, src, _boxes(prs, s, set()))  # the original too: the copy is not put on it
        off.set("x", str(int(x)))
        off.set("y", str(int(y)))
    covered = _overlapping(
        (int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))), _boxes(prs, s, set())
    )
    moved = False
    if box and covered:  # the place asked for is taken: the nearest free one to it (measured: told it covered two
        # boxes, the model left it there)
        size = SimpleNamespace(width=int(ext.get("cx")), height=int(ext.get("cy")), left=int(off.get("x")), top=int(off.get("y")))
        x, y = _free_place(prs, s, size, _boxes(prs, s, set()), near=(size.left, size.top))
        off.set("x", str(int(x)))
        off.set("y", str(int(y)))
        covered = _overlapping((int(x), int(y), size.width, size.height), _boxes(prs, s, set()))
        moved = True
    src._element.addnext(el)
    if paragraphs is not None:
        made = get_shape(s, new_id)
        if not made.has_text_frame:
            raise OpError("NO_TEXT", f"Shape {shape_id} holds no text.", "Copy it without paragraphs.")
        _set_paragraphs(made.text_frame, paragraphs)
    return {"slides": [s.slide_id], "shape_id": new_id, "covers": covered, "moved": moved}


SIDES = {"top": 0, "left": 1, "bottom": 2, "right": 3}  # a rectangle's connection sites, as PowerPoint numbers them


def connect_shapes(
    prs,
    slide_id: int,
    from_shape_id: int,
    to_shape_id: int,
    like_connector_id: int | None = None,
    kind: str | None = None,
    arrow: str = "end",
    deck_id=None,
) -> dict:
    """A connector from one shape to another, attached to both (PowerPoint keeps it on them when they move), between
    the sides that face each other; straight when they are in line, else an elbow (or as `kind`); its line like
    connector `like_connector_id`'s (colour, width, dash: the diagram's own), else the theme's. Returns {slides,
    shape_id}."""
    s = get_slide(prs, slide_id)
    a, b = get_shape(s, from_shape_id, editable=False), get_shape(s, to_shape_id, editable=False)  # only read
    _top_level(s, a, "connected")
    _top_level(s, b, "connected")
    if a.shape_id == b.shape_id:
        raise OpError("SAME_SHAPE", "A connector needs two different shapes.", "")
    like = None
    if like_connector_id is None:  # the diagram's own arrows: the line most of the slide's connectors share
        lines = [c for c in s.shapes._spTree.iter(qn("p:cxnSp")) if c.find(".//" + qn("a:ln")) is not None]
        if lines:
            counts: dict[bytes, list] = {}
            for c in lines:
                counts.setdefault(etree.tostring(c.find(".//" + qn("a:ln"))), []).append(c)
            like = max(counts.values(), key=len)[0]
    if like_connector_id is not None:
        like = get_shape(s, like_connector_id, editable=False)._element
        if like.tag != qn("p:cxnSp"):
            hint = "Name one of the diagram's connectors, or leave it out."
            raise OpError("NOT_A_CONNECTOR", f"Shape {like_connector_id} is not a connector.", hint)
    dx = (b.left + b.width // 2) - (a.left + a.width // 2)
    dy = (b.top + b.height // 2) - (a.top + a.height // 2)
    if abs(dx) >= abs(dy):
        start, end = ("right", "left") if dx >= 0 else ("left", "right")
    else:
        start, end = ("bottom", "top") if dy >= 0 else ("top", "bottom")

    def point(sh, side):
        x, y, w, h = sh.left, sh.top, sh.width, sh.height
        sides = {"top": (x + w // 2, y), "bottom": (x + w // 2, y + h), "left": (x, y + h // 2), "right": (x + w, y + h // 2)}
        return sides[side]

    (x1, y1), (x2, y2) = point(a, start), point(b, end)
    in_line = x1 == x2 or y1 == y2
    geom = {"straight": "straightConnector1", "elbow": "bentConnector3"}.get(kind or "")
    if geom is None:  # in line: straight; else an elbow (the connector it looks like gives its line, not its shape:
        # measured, a straight one copied joined two boxes by a diagonal)
        geom = "straightConnector1" if in_line else "bentConnector3"
    new_id = _next_shape_id(s)
    flips = (' flipH="1"' if x2 < x1 else "") + (' flipV="1"' if y2 < y1 else "")
    el = etree.fromstring(
        f"<p:cxnSp {nsdecls('p', 'a')}>"
        f'<p:nvCxnSpPr><p:cNvPr id="{new_id}" name="Connector {new_id}"/><p:cNvCxnSpPr>'
        f'<a:stCxn id="{a.shape_id}" idx="{SIDES[start]}"/><a:endCxn id="{b.shape_id}" idx="{SIDES[end]}"/>'
        f"</p:cNvCxnSpPr><p:nvPr/></p:nvCxnSpPr><p:spPr><a:xfrm{flips}>"
        f'<a:off x="{min(x1, x2)}" y="{min(y1, y2)}"/><a:ext cx="{abs(x2 - x1)}" cy="{abs(y2 - y1)}"/></a:xfrm>'
        f'<a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom></p:spPr></p:cxnSp>'
    )
    sppr = el.find(qn("p:spPr"))
    if like is not None:  # the diagram's line, copied whole, and its style reference
        line = like.find(".//" + qn("a:ln"))
        sppr.append(copy.deepcopy(line) if line is not None else etree.Element(qn("a:ln")))
        style = like.find(qn("p:style"))
        if style is not None:
            el.append(copy.deepcopy(style))
    else:  # the theme's first line style, in the text colour
        etree.SubElement(sppr, qn("a:ln"), w="19050")
        style = etree.SubElement(el, qn("p:style"))
        for tag, idx in (("a:lnRef", "1"), ("a:fillRef", "0"), ("a:effectRef", "0")):
            ref = etree.SubElement(style, qn(tag), idx=idx)
            etree.SubElement(ref, qn("a:schemeClr"), val="tx1")
        ref = etree.SubElement(style, qn("a:fontRef"), idx="minor")
        etree.SubElement(ref, qn("a:schemeClr"), val="tx1")
    line = sppr.find(qn("a:ln"))
    for tag in ("a:headEnd", "a:tailEnd"):  # the arrowheads, as asked
        for x in line.findall(qn(tag)):
            line.remove(x)
    after = line.find(qn("a:extLst"))
    for tag, wanted in (("a:headEnd", arrow == "both"), ("a:tailEnd", arrow in ("end", "both"))):
        if wanted:
            head = etree.Element(qn(tag), type="triangle")
            (after.addprevious if after is not None else line.append)(head)
    s.shapes._spTree.append(el)
    return {"slides": [s.slide_id], "shape_id": new_id}


def move_resize_shape(prs, slide_id: int, shape_id: int, box: dict, deck_id=None) -> list[int]:
    s = get_slide(prs, slide_id)
    sh = get_shape(s, shape_id, editable=False)  # moving a chart or a diagram as a whole is safe
    sh.left, sh.top, sh.width, sh.height = (Emu(v) for v in _box_emu(prs, box))
    return [s.slide_id]


def delete_shape(prs, slide_id: int, shape_id: int, deck_id=None) -> list[int]:
    s = get_slide(prs, slide_id)
    sh = get_shape(s, shape_id, editable=False)
    sh._element.getparent().remove(sh._element)
    return [s.slide_id]


def set_alt_text(prs, slide_id: int, shape_id: int, text: str, deck_id=None) -> list[int]:
    s = get_slide(prs, slide_id)
    sh = get_shape(s, shape_id, editable=False)  # alt text is safe on any shape
    nv = sh._element.find(f".//{qn('p:cNvPr')}")
    nv.set("descr", text)
    return [s.slide_id]


def set_notes(prs, slide_id: int, text: str, deck_id=None) -> list[int]:
    s = get_slide(prs, slide_id)
    s.notes_slide.notes_text_frame.text = text
    return [s.slide_id]


# ── diagrams from a description (M8) ─────────────────────────────────
def _look(sh) -> str:
    """What a shape looks like: its geometry, fill and outline, as XML (shapes that look alike draw the same)."""
    sp_pr = sh._element.find(qn("p:spPr"))
    if sp_pr is None:
        return ""
    parts = [sp_pr.find(qn(t)) for t in ("a:prstGeom", "a:solidFill", "a:noFill", "a:gradFill", "a:ln")]
    style = sh._element.find(qn("p:style"))
    return "".join(etree.tostring(x).decode() for x in [*parts, style] if x is not None)


def _diagram_boxes(sl) -> list:
    """A slide's diagram boxes: its free shapes with text that share the most repeated look (two or more); [] if none
    (measured: a real diagram's arrows were free lines, attached to nothing, so its boxes are found by their look)."""
    groups: dict[str, list] = {}
    for sh in sl.shapes:
        if (sh.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and not sh.is_placeholder and sh.has_text_frame
                and sh.text_frame.text.strip() and sh._element.find(".//" + qn("a:blipFill")) is None):  # fmt: skip
            groups.setdefault(_look(sh), []).append(sh)
    best = max(groups.values(), key=len, default=[])
    return best if len(best) >= 2 else []


def _box_style(prs, slide, like: int | None):
    """The shape a new diagram's boxes copy: `like`; else one of the diagram boxes of this slide, else of the slide
    with the most (measured: the first shape with text on the Squad Model's slide was a borderless description);
    None: the theme's (add_shape)."""
    if like is not None:
        return get_shape(slide, like, editable=False)
    order = list(prs.slides)
    here = next(i for i, x in enumerate(order) if x.slide_id == slide.slide_id)
    # a diagram: look-alike boxes and connector lines on one slide; the nearest such slide (measured: by most boxes,
    # a slide of grey table-like boxes won over the workflow diagram next to the new slide)
    for sl in sorted(order, key=lambda x: abs(order.index(x) - here)):
        boxes = _diagram_boxes(sl)
        if boxes and any(sh._element.tag == qn("p:cxnSp") for sh in sl.shapes):
            return boxes[0]
    return None


def _example_connector(prs, slide, style=None):
    """The line of the deck's own arrows: the most common connector line on the slide the boxes come from (or this
    one), else any slide's."""
    slides = [slide, *[x for x in prs.slides if x.slide_id != slide.slide_id]]
    if style is not None:
        home = style.part.slide if hasattr(style.part, "slide") else None
        if home is not None:
            slides.insert(0, home)
    for sl in slides:
        lines: dict[str, list] = {}
        for sh in sl.shapes:
            ln = sh._element.find(".//" + qn("a:ln")) if sh._element.tag == qn("p:cxnSp") else None
            if ln is not None:
                lines.setdefault(etree.tostring(ln).decode(), []).append(sh)
        if lines:
            return max(lines.values(), key=len)[0]
    return None


def _ranks(n: int, edges: list[tuple[int, int]]) -> list[int]:
    """Each node's step: its longest path from a node with no arrow into it (a cycle stops at n steps)."""
    rank = [0] * n
    for _ in range(n):
        changed = False
        for a, b in edges:
            if rank[b] < rank[a] + 1 and rank[a] + 1 < n:
                rank[b] = rank[a] + 1
                changed = True
        if not changed:
            break
    return rank


ROW_STEPS = 4  # the most steps of a chain in one row


def draw_diagram(
    prs, slide_id: int, nodes: list[dict], edges: list[dict] | None = None, direction: str = "right",
    like_shape_id: int | None = None, box: dict | None = None, deck_id=None,
) -> dict:  # fmt: skip
    """A diagram from a description: its boxes laid out in steps (the arrows' order: left to right, or top to bottom),
    in the space under the slide's title (or `box`), each a copy of the deck's own diagram boxes (their shape, fill,
    line and text style; else the theme's), joined by connectors attached to both, with the line of the deck's own
    connectors. Returns {slides, shape_ids (in the nodes' order), connector_ids, styled_from}."""
    s = get_slide(prs, slide_id)
    if not 1 < len(nodes) <= 20:
        raise OpError("BAD_DIAGRAM", "A diagram has 2 to 20 boxes.", "")
    if edges is None:  # left out: a process, each box to the next (measured: "a diagram of the process: A, B, C, D" came
        # with no arrows, and four boxes stood stacked in one column, joined by nothing)
        edges = [{"from": i, "to": i + 1} for i in range(len(nodes) - 1)]
    pairs = []
    for e in edges:
        a, b = int(e["from"]), int(e["to"])
        if not (0 <= a < len(nodes) and 0 <= b < len(nodes)) or a == b:
            raise OpError("BAD_DIAGRAM", f"An arrow from {a} to {b}: nodes are numbered 0 to {len(nodes) - 1}.", "")
        pairs.append((a, b))
    rank = _ranks(len(nodes), pairs)
    steps = max(rank) + 1
    per = [[i for i in range(len(nodes)) if rank[i] == r] for r in range(steps)]
    W, H = int(prs.slide_width), int(prs.slide_height)
    area = _box_emu(prs, box or {"x": 0.06, "y": 0.22, "w": 0.88, "h": 0.68})
    ax, ay, aw, ah = area
    across = max(len(p) for p in per)  # boxes side by side in the busiest step
    # a chain of more than ROW_STEPS steps, left to right, goes on in rows (looked at: seven steps in one row, boxes
    # so narrow that "Elegibilidade" and "Avaliação" broke mid-word)
    rows = -(-steps // ROW_STEPS) if direction != "down" and across == 1 and steps > ROW_STEPS else 1
    cols = -(-steps // rows)
    if direction == "down":
        cell_w, cell_h = aw / across, ah / steps
    elif rows > 1:
        cell_w, cell_h = aw / cols, ah / rows
    else:
        cell_w, cell_h = aw / steps, ah / across
    # (looked at: two steps of a generated slide in boxes of 22% of the slide, their text crammed, the rest empty)
    bw, bh = int(min(cell_w * (0.8 if rows > 1 else 0.7), W * 0.28)), int(min(cell_h * 0.6, H * 0.2))
    style = _box_style(prs, s, like_shape_id)
    ids = [0] * len(nodes)
    for r, members in enumerate(per):
        for k, i in enumerate(members):
            if direction == "down":
                cx = ax + (k + 0.5) * aw / len(members)
                cy = ay + (r + 0.5) * cell_h
            elif rows > 1:  # back and forth, so each arrow goes to the box beside or under it (looked at: rows all
                # left to right, the arrow from a row's end to the next row's start crossed the boxes between)
                col = r % cols if (r // cols) % 2 == 0 else cols - 1 - r % cols
                cx = ax + (col + 0.5) * cell_w
                cy = ay + (r // cols + 0.5) * cell_h
            else:
                cx = ax + (r + 0.5) * cell_w
                cy = ay + (k + 0.5) * ah / len(members)
            x, y = int(cx - bw / 2), int(cy - bh / 2)
            text = [{"runs": [{"text": str(nodes[i].get("text") or "").strip()}]}]
            if style is not None:
                el = copy.deepcopy(style._element)
                new_id = _next_shape_id(s)
                c_nv = el.find(".//" + qn("p:cNvPr"))
                c_nv.set("id", str(new_id))
                c_nv.set("name", f"Diagram box {new_id}")
                for ext in c_nv.findall(qn("a:extLst")):
                    c_nv.remove(ext)
                for link in [*el.iter(qn("a:hlinkClick")), *el.iter(qn("a:hlinkHover"))]:  # its slide's links stay there
                    link.getparent().remove(link)
                xfrm = el.find(".//" + qn("a:xfrm"))
                xfrm.find(qn("a:off")).set("x", str(x))
                xfrm.find(qn("a:off")).set("y", str(y))
                xfrm.find(qn("a:ext")).set("cx", str(bw))
                xfrm.find(qn("a:ext")).set("cy", str(bh))
                s.shapes._spTree.append(el)
                _set_paragraphs(get_shape(s, new_id).text_frame, text)
            else:
                new_id = add_shape(prs, s.slide_id, "rounded_rectangle",
                                   {"x": x / W, "y": y / H, "w": bw / W, "h": bh / H}, text)["shape_id"]  # fmt: skip
            ids[i] = new_id
    for sid_ in ids:  # each box's text fitted to it, as fit_text does
        sh = get_shape(s, sid_)
        from . import textfit

        if textfit.overflows(sh):
            try:
                fit_text(prs, s.slide_id, sid_)
            except OpError:
                pass
    # the boxes' text at one size, the smallest any was fitted to, written into their runs (looked at: "Processamento"
    # fitted to 15.3 pt between boxes of 18 and 17.1 pt), as a row's numbers are (_add_one)
    from . import textfit

    boxes = [get_shape(s, sid_) for sid_ in ids]
    sizes = [textfit.smallest_size(sh) for sh in boxes]
    if len(boxes) > 1 and all(sizes) and min(sizes) < max(sizes):
        for sh, size in zip(boxes, sizes, strict=True):
            if size > min(sizes):
                body = sh.text_frame._txBody.find(qn("a:bodyPr"))
                fit = body.find(qn("a:normAutofit"))
                if fit is None:
                    fit = etree.SubElement(body, qn("a:normAutofit"))
                fit.set("fontScale", str(round(min(sizes) / size * textfit._body(sh)["font_scale"] * 100000)))
                textfit.write_sizes(sh)
    example = _example_connector(prs, s, style)
    connectors = []
    for a, b in pairs:
        made = connect_shapes(prs, s.slide_id, ids[a], ids[b])
        connectors.append(made["shape_id"])
        if example is not None and example._element.getparent() is not None:
            ln = example._element.find(".//" + qn("a:ln"))
            mine = get_shape(s, made["shape_id"], editable=False)._element
            sp_pr = mine.find(qn("p:spPr"))
            old = sp_pr.find(qn("a:ln"))
            if old is not None:
                sp_pr.remove(old)
            sp_pr.append(copy.deepcopy(ln))
    for ph in list(s.placeholders):  # an empty text box under the diagram goes, as under a chart (its prompt would show)
        if ph.has_text_frame and not ph.text_frame.text.strip() and ph.left is not None:
            if _overlapping((int(ax), int(ay), int(aw), int(ah)), [(ph.shape_id, ph.left, ph.top, ph.width, ph.height)]):
                ph._element.getparent().remove(ph._element)
    styled = f"shape {style.shape_id}" if style is not None else "the theme"
    # what its boxes cover, as add_chart says (looked at: a diagram drawn by the editor's control over a chart and a
    # list, and the person told nothing)
    drawn = {sh.shape_id: sh for sh in s.shapes if sh.shape_id in ids}
    others = _boxes(prs, s, set(ids) | set(connectors))
    covers = sorted({c for sh in drawn.values() for c in _overlapping((sh.left, sh.top, sh.width, sh.height), others)})
    return {"slides": [s.slide_id], "shape_ids": ids, "connector_ids": connectors, "styled_from": styled, "covers": covers}


def blank_layout(prs):
    """The layout with no place to fill (a slide for a figure that has no title): the first with no heading, text,
    picture, table or chart placeholder; else the one content fits with a title alone."""
    from . import layouts

    for lay in prs.slide_layouts:
        roles = {x["role"] for x in layouts.placeholders(lay, prs.slide_width, prs.slide_height)}
        if not roles - {"number"}:
            return lay
    return _layout_for_content(prs, {"title": "-"})


# ── charts (spec NL-5) ───────────────────────────────────────────────
CHART_KINDS = {"column": "COLUMN_CLUSTERED", "bar": "BAR_CLUSTERED", "line": "LINE_MARKERS", "pie": "PIE"}


def _chart_data(categories: list[str], series: list[dict], number_format: str | None = None):
    from pptx.chart.data import CategoryChartData

    if not categories or not series:
        raise OpError("BAD_CHART", "A chart needs categories and at least one series.", "")
    for one in series:
        if len(one["values"]) != len(categories):
            raise OpError(
                "BAD_CHART",
                f"Series {one['name']!r} has {len(one['values'])} values for {len(categories)} categories.",
                "Give one value per category, in the categories' order.",
            )
    data = CategoryChartData(number_format=number_format) if number_format else CategoryChartData()
    data.categories = [str(c) for c in categories]
    for one in series:
        data.add_series(str(one["name"]), [float(v) for v in one["values"]])
    return data


def _not_the_heading(s, title: str | None) -> str | None:
    """A chart's title, unless it is its slide's title: said once, by the slide (measured: the model sends the chart
    whole to edit_chart, with the slide's title as the chart's, and the slide showed it twice)."""
    from . import layouts

    idx = layouts.slots(s.slide_layout, s.part.package.presentation_part.presentation.slide_width,
                        s.part.package.presentation_part.presentation.slide_height)["heading"]  # fmt: skip
    head = next((ph for ph in s.placeholders if ph.placeholder_format.idx == idx), None) or s.shapes.title
    said = " ".join(head.text_frame.text.split()).lower() if head is not None and head.has_text_frame else ""
    return None if title and said and " ".join(title.split()).lower() == said else title


def _style_chart(chart, kind: str, title: str | None, series: list[dict]) -> None:
    from pptx.enum.chart import XL_LEGEND_POSITION

    if title:
        chart.has_title = True
        chart.chart_title.text_frame.text = title
    else:
        chart.has_title = False
    chart.has_legend = kind == "pie" or len(series) > 1  # one series: its name is the title's job
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
    if kind == "pie":
        plot = chart.plots[0]
        plot.has_data_labels = True
        plot.data_labels.show_percentage = True
        plot.data_labels.show_value = False


def add_chart(
    prs, slide_id: int, kind: str, categories: list[str], series: list[dict], title: str | None = None,
    number_format: str | None = None, box: dict | None = None, deck_id=None,
) -> dict:  # fmt: skip
    """A native chart (its data in an embedded workbook, editable in PowerPoint): in the slide's empty chart
    placeholder when it has one, else at `box`, else in the space under the slide's title. Colours and fonts are the
    theme's (PowerPoint's chart style follows the deck's accents)."""
    from pptx.enum.chart import XL_CHART_TYPE

    if kind == "pie" and len(series) != 1:
        raise OpError("BAD_CHART", "A pie chart has one series.", "Give one series, or choose column, bar or line.")
    s = get_slide(prs, slide_id)
    data = _chart_data(categories, series, number_format)
    chart_type = getattr(XL_CHART_TYPE, CHART_KINDS[kind])
    holder = next(
        (ph for ph in s.placeholders if ph.placeholder_format.type is not None
         and ph.placeholder_format.type.name in ("CHART", "OBJECT") and not (ph.has_text_frame and ph.text_frame.text.strip())),
        None,
    ) if box is None else None  # fmt: skip
    in_place = holder is not None and holder.placeholder_format.type.name == "CHART"
    if in_place:  # (the placeholder is replaced by the chart: read it before)
        frame = holder.insert_chart(chart_type, data)
    else:
        sw, sh_ = prs.slide_width, prs.slide_height
        b = box or {"x": 0.08, "y": 0.22, "w": 0.84, "h": 0.66}
        frame = s.shapes.add_chart(chart_type, int(b["x"] * sw), int(b["y"] * sh_), int(b["w"] * sw), int(b["h"] * sh_), data)
    _style_chart(frame.chart, kind, _not_the_heading(s, title), series)
    covers = []
    if not in_place:
        mine = (frame.left, frame.top, frame.width, frame.height)
        for ph in list(s.placeholders):  # an empty text box under the chart goes (its prompt would show beneath)
            if ph.has_text_frame and not ph.text_frame.text.strip():
                if _overlapping(mine, [(ph.shape_id, ph.left, ph.top, ph.width, ph.height)]):
                    ph._element.getparent().remove(ph._element)
        covers = _overlapping(mine, _boxes(prs, s, {frame.shape_id}))
    return {"slides": [s.slide_id], "shape_id": frame.shape_id, "covers": covers}


def edit_chart(
    prs, slide_id: int, shape_id: int, title: str | None = None, categories: list[str] | None = None,
    series: list[dict] | None = None, kind: str | None = None, deck_id=None,
) -> dict:  # fmt: skip
    """A chart's data replaced (categories and series together), its title changed or removed, its kind changed; its
    place kept. The model sends the chart whole, as add_chart takes it (measured: 2 runs in 2 named its kind, unchanged):
    the same kind changes nothing; another is drawn anew in the same frame, with the data and title it has."""
    from pptx.chart.xmlwriter import ChartXmlWriter
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.oxml import parse_xml

    s = get_slide(prs, slide_id)
    sh = get_shape(s, shape_id, editable=False)  # a chart is locked to the other tools; this one changes its data
    if not getattr(sh, "has_chart", False):
        raise OpError("NOT_A_CHART", f"Shape {shape_id} is not a chart.", "Use the chart's shape ID from the deck map.")
    chart = sh.chart
    if (categories is None) != (series is None):
        raise OpError("BAD_CHART", "Give the categories and the series together.", "")
    now = read.chart_data(sh)
    if kind is not None and now is not None and kind != now["kind"]:
        cats = categories if categories is not None else now["categories"]
        rows = series if series is not None else now["series"]
        if kind == "pie" and len(rows) != 1:
            raise OpError("BAD_CHART", "A pie chart has one series.", "Give one series, or choose column, bar or line.")
        data = _chart_data(cats, rows)
        part = sh.chart_part
        fresh = parse_xml(ChartXmlWriter(getattr(XL_CHART_TYPE, CHART_KINDS[kind]), data).xml.encode())
        link = part._element.find(qn("c:externalData"))  # the link to its workbook (PowerPoint's Edit Data): kept
        if link is not None:
            fresh._insert_externalData(copy.deepcopy(link))
        part._element = fresh
        part.chart_workbook.update_from_xlsx_blob(data.xlsx_blob)
        part.__dict__.pop("chart", None)  # (python-pptx keeps the Chart it made of the old XML)
        keep = now["title"] if title is None else title.strip()
        _style_chart(sh.chart, kind, _not_the_heading(s, keep or None), rows)
        return {"slides": [s.slide_id], "shape_id": shape_id}
    if categories is not None:
        chart.replace_data(_chart_data(categories, series))
        pie = chart.chart_type.name == "PIE"
        chart.has_legend = pie or len(series) > 1  # as add_chart sets it (measured: one series left, its legend stayed)
    if title is not None:
        title = _not_the_heading(s, title.strip()) or ""
        if title:
            chart.has_title = True
            chart.chart_title.text_frame.text = title.strip()
        else:
            chart.has_title = False
    return {"slides": [s.slide_id], "shape_id": shape_id}


# ── images ───────────────────────────────────────────────────────────
def _png_or_jpeg(data: bytes) -> tuple[bytes, int, int]:
    """PNG and JPEG as they are; WebP and others converted to PNG (spec IM-1); SVG is converted by the caller."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001 - Pillow raises many kinds for what is not an image
        raise OpError("BAD_IMAGE", "This file is not an image the deck can hold.", "Use a PNG, JPEG or WebP image.") from None
    if img.format in ("PNG", "JPEG"):
        return data, img.width, img.height
    out = io.BytesIO()
    img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB").save(out, "PNG")
    return out.getvalue(), img.width, img.height


def _fit(frame_w: int, frame_h: int, img_w: int, img_h: int) -> tuple[int, int]:
    """The largest size of the image's proportions inside the frame."""
    scale = min(frame_w / img_w, frame_h / img_h)
    return round(img_w * scale), round(img_h * scale)


def insert_image(prs, slide_id: int, image: bytes, target: dict, fit: str = "contain", deck_id=None) -> dict:
    """target: {placeholder_idx} (a picture placeholder: the image fills it, cropped to its shape) or {box} (the image
    inside the box, its proportions kept). Returns {slides, shape_id}."""
    s = get_slide(prs, slide_id)
    data, iw, ih = _png_or_jpeg(image)
    if "placeholder_idx" in target:
        ph = next((p for p in s.placeholders if p.placeholder_format.idx == int(target["placeholder_idx"])), None)
        if ph is None or not hasattr(ph, "insert_picture"):
            raise OpError(
                "NO_PICTURE_PLACEHOLDER",
                "That placeholder cannot hold a picture.",
                "Give a box instead, or use a layout with a picture placeholder (list_layouts).",
            )
        pic = ph.insert_picture(io.BytesIO(data))
        return {"slides": [s.slide_id], "shape_id": pic.shape_id}
    x, y, w, h = _box_emu(prs, target["box"])
    fw, fh = _fit(w, h, iw, ih) if fit == "contain" else (w, h)
    pic = s.shapes.add_picture(io.BytesIO(data), Emu(x + (w - fw) // 2), Emu(y + (h - fh) // 2), Emu(fw), Emu(fh))
    return {"slides": [s.slide_id], "shape_id": pic.shape_id}


def replace_image(prs, slide_id: int, shape_id: int, image: bytes, deck_id=None) -> list[int]:
    """Swap a picture keeping its place, size and alt text (spec IM-2): the new image fills the frame without
    distortion, cropped at its centre to the frame's proportions."""
    s = get_slide(prs, slide_id)
    sh = get_shape(s, shape_id)
    if sh.shape_type != MSO_SHAPE_TYPE.PICTURE and not (sh.is_placeholder and sh._element.tag.endswith("}pic")):
        raise OpError("NOT_A_PICTURE", f"Shape {shape_id} is not a picture.", "Use insert_image to add one.")
    data, iw, ih = _png_or_jpeg(image)
    _, rid = s.part.get_or_add_image_part(io.BytesIO(data))
    blip = sh._element.find(f".//{qn('a:blip')}")
    blip.set(qn("r:embed"), rid)
    frame = int(sh.width) / int(sh.height)
    pic = iw / ih
    sh.crop_left = sh.crop_right = sh.crop_top = sh.crop_bottom = 0.0
    if pic > frame:  # wider: crop the sides
        cut = (1 - frame / pic) / 2
        sh.crop_left = sh.crop_right = cut
    elif pic < frame:  # taller: crop top and bottom
        cut = (1 - pic / frame) / 2
        sh.crop_top = sh.crop_bottom = cut
    return [s.slide_id]


# ── tables ───────────────────────────────────────────────────────────
def _cell_text(cell, text: str) -> None:
    _set_paragraphs(cell.text_frame, [{"runs": [{"text": line}]} for line in str(text).split("\n")])


def edit_table(prs, slide_id: int, shape_id: int, operations: list[dict], deck_id=None) -> list[int]:
    """operations, in order: {op: set_cell, row, col, text} | {op: add_row, at, cells} | {op: delete_row, row} |
    {op: add_column, at, cells} | {op: delete_column, col}. A new row or column copies its neighbour's formatting;
    its cells, when given, are written in the same step (measured: given only an empty add_row, the model stopped
    there, and a table gained a blank row instead of the tier it was asked for)."""
    s = get_slide(prs, slide_id)
    sh = get_shape(s, shape_id)
    if not getattr(sh, "has_table", False) or not sh.has_table:
        raise OpError("NOT_A_TABLE", f"Shape {shape_id} is not a table.", "")
    tbl = sh.table._tbl
    needs = {"set_cell": ("row", "col", "text"), "delete_row": ("row",), "delete_column": ("col",)}
    for op in operations:
        missing = [k for k in needs.get(op.get("op"), ()) if op.get(k) is None]
        if missing:
            hint = "Rows and columns are counted from 0."
            raise OpError("BAD_ARGUMENTS", f"{op.get('op')} needs {', '.join(missing)}.", hint)
        rows = tbl.findall(qn("a:tr"))
        grid = tbl.find(qn("a:tblGrid"))
        cols = grid.findall(qn("a:gridCol"))
        kind = op.get("op")
        if kind == "set_cell":
            r, c = int(op["row"]), int(op["col"])
            if not (0 <= r < len(rows) and 0 <= c < len(cols)):
                raise OpError("BAD_CELL", f"The table has rows 0-{len(rows) - 1} and columns 0-{len(cols) - 1}.", "")
            _cell_text(sh.table.cell(r, c), op.get("text", ""))
        elif kind == "add_row":
            at = int(op.get("at", len(rows)))
            src = rows[min(max(at - 1, 0), len(rows) - 1)]
            new = copy.deepcopy(src)
            for tc in new.findall(qn("a:tc")):
                body = tc.find(qn("a:txBody"))
                for p in body.findall(qn("a:p"))[1:]:
                    body.remove(p)
                for r in body.find(qn("a:p")).findall(qn("a:r")):
                    r.getparent().remove(r)
            if at >= len(rows):
                rows[-1].addnext(new)
            else:
                rows[at].addprevious(new)
            for c, text in enumerate((op.get("cells") or [])[: len(cols)]):
                _cell_text(sh.table.cell(min(at, len(rows)), c), text)
        elif kind == "delete_row":
            r = int(op["row"])
            if not 0 <= r < len(rows) or len(rows) == 1:
                raise OpError("BAD_CELL", "That row cannot be deleted.", "")
            tbl.remove(rows[r])
        elif kind == "add_column":
            at = int(op.get("at", len(cols)))
            src_i = min(max(at - 1, 0), len(cols) - 1)
            width = int(cols[src_i].get("w"))
            new_col = copy.deepcopy(cols[src_i])
            (cols[at].addprevious if at < len(cols) else cols[-1].addnext)(new_col)
            for tr in rows:
                tcs = tr.findall(qn("a:tc"))
                new = copy.deepcopy(tcs[src_i])
                body = new.find(qn("a:txBody"))
                for p in body.findall(qn("a:p"))[1:]:
                    body.remove(p)
                for r in body.find(qn("a:p")).findall(qn("a:r")):
                    r.getparent().remove(r)
                (tcs[at].addprevious if at < len(tcs) else tcs[-1].addnext)(new)
            for r, text in enumerate((op.get("cells") or [])[: len(rows)]):
                _cell_text(sh.table.cell(r, min(at, len(cols))), text)
            # the table keeps its width: every column narrows in proportion
            total = sum(int(c.get("w")) for c in cols)
            for c in grid.findall(qn("a:gridCol")):
                c.set("w", str(round(int(c.get("w")) * total / (total + width))))
        elif kind == "delete_column":
            c = int(op["col"])
            if not 0 <= c < len(cols) or len(cols) == 1:
                raise OpError("BAD_CELL", "That column cannot be deleted.", "")
            grid.remove(cols[c])
            for tr in rows:
                tr.remove(tr.findall(qn("a:tc"))[c])
        else:
            raise OpError(
                "BAD_OPERATION",
                f'Unknown table operation "{kind}".',
                "Use set_cell, add_row, delete_row, add_column or delete_column.",
            )
    return [s.slide_id]


# ── the whole: apply, save, reopen ───────────────────────────────────
OPERATIONS = {
    "redesign_slide": redesign_slide,
    "update_text": update_text,
    "change_template": change_template,
    "copy_slides": copy_slides,
    "edit_paragraphs": edit_paragraphs,
    "set_texts": set_texts,  # the editor's in-place text (not an assistant tool)
    "format_text": format_text,
    "add_slide": add_slide,
    "fill_slide": fill_slide,
    "add_slides": add_slides,
    "add_outline": add_outline,  # a generated deck (domain/generations.py: not an assistant tool)
    "add_chart": add_chart,
    "draw_diagram": draw_diagram,
    "edit_chart": edit_chart,
    "duplicate_shape": duplicate_shape,
    "fit_text": fit_text,
    "connect_shapes": connect_shapes,
    "delete_slide": delete_slide,
    "move_slide": move_slide,
    "duplicate_slide": duplicate_slide,
    "change_layout": change_layout,
    "add_shape": add_shape,
    "move_resize_shape": move_resize_shape,
    "delete_shape": delete_shape,
    "set_alt_text": set_alt_text,
    "set_notes": set_notes,
    "insert_image": insert_image,
    "replace_image": replace_image,
    "edit_table": edit_table,
}


def save(prs: Presentation) -> bytes:
    """The deck's bytes, checked by reopening them (spec section 6): a file that does not reopen is never kept."""
    out = io.BytesIO()
    prs.save(out)
    data = out.getvalue()
    try:
        Presentation(io.BytesIO(data))
    except Exception as e:
        raise OpError("INVALID_RESULT", f"The change would make a file that does not open ({type(e).__name__}).", "") from e
    return data


def apply(data: bytes, name: str, args: dict) -> tuple[bytes, dict]:
    """One operation on a deck's bytes: the new bytes and its result ({slides, ...})."""
    if name not in OPERATIONS:
        raise OpError("UNKNOWN_OPERATION", f'Unknown operation "{name}".', "")
    prs = Presentation(io.BytesIO(data))
    try:
        result = OPERATIONS[name](prs, **args)
    except TypeError as e:
        raise OpError("BAD_ARGUMENTS", f"{name}: {e}", "Check the tool's arguments against its schema.") from None
    if isinstance(result, list):
        result = {"slides": result}
    out = result.pop("_replace", prs) if isinstance(result, dict) else prs  # an operation that made a new deck
    return save(out), result


__all__ = ["OPERATIONS", "OpError", "PackURI", "apply", "save"]
