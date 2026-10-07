"""Does a shape's text fit its box? Measured with the deck's own fonts (fontconfig finds the installed file for each
typeface, Pillow gives each word's advance width), the paragraph and box properties resolved as PowerPoint inherits
them (the run, the shape's list style, the layout's and master's placeholder, the master's text styles, the
presentation's defaults, the theme's fonts), and words wrapped line by line as PowerPoint does.

It predicts where the glyphs land - what a person sees - not the lines' boxes: measured against LibreOffice's renders
of real decks (tests/eval: Banco CTT's Dev.AI and Squad Model, with their fonts), a character-count estimate raised
185 false alarms in 825 shapes, among them every agenda number that sat inside its box (a 36 pt "01" in a 40 pt box).
PITCH and INK are fitted to those renders (docs/decisions.md)."""

from __future__ import annotations

import functools
import subprocess
import weakref

from PIL import ImageFont

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
EMU_PT = 12700
# fitted to LibreOffice's renders of 876 text shapes (Dev.AI, Squad Model and the fixtures, with their fonts): 9 wrong
# (7 false alarms, 2 missed) where a character count was wrong 186 times; fitted on Dev.AI alone, the same values,
# which on the Squad Model gave 0 false alarms (it had given 134)
PITCH = 1.15  # a line's pitch in ems at 100% line spacing
INK = 0.8  # the glyphs' height in ems, from the top of the tallest to the bottom of the lowest
TOP = 0.05  # ems between the top of a line's box and the top of its glyphs
TOL_PT = 2.0  # what a person does not see as outside the box
DEFAULT_INS = {"lIns": 91440, "tIns": 45720, "rIns": 91440, "bIns": 45720}


@functools.lru_cache(maxsize=256)
def font_file(family: str, bold: bool, italic: bool) -> str | None:
    """The installed file fontconfig picks for a typeface, as LibreOffice does (the decks' fonts are in fonts/)."""
    style = (":weight=bold" if bold else "") + (":slant=italic" if italic else "")
    try:
        run = subprocess.run(["fc-match", f"{family}{style}", "--format=%{file}"], capture_output=True, timeout=10, check=False)  # noqa: S603, S607
    except (OSError, subprocess.TimeoutExpired):
        return None
    return run.stdout.decode("utf-8", "replace").strip() or None


@functools.lru_cache(maxsize=512)
def _font(path: str, size_tenths: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size_tenths)  # in tenths of a point: widths precise to 0.1 pt


def width_pt(text: str, family: str, size: float, bold: bool = False, italic: bool = False) -> float | None:
    path = font_file(family, bold, italic)
    if not path:
        return None
    try:
        return _font(path, max(1, round(size * 10))).getlength(text) / 10
    except OSError:
        return None


# ── what a paragraph inherits ────────────────────────────────────────
# what a layout's and master's placeholders and text styles give, kept per layout part while its deck is open (a
# deck's layouts do not change while it is read; the shape's own XML is always read anew)
_inherited: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _memo(part, key, make):
    found = _inherited.setdefault(part, {})
    if key not in found:
        found[key] = make()
    return found[key]

def _lvl(lst, level: int):
    return lst.find(f"{A}lvl{level + 1}pPr") if lst is not None else None


def _chain(sh, level: int) -> list:
    """The pPr nodes a paragraph of this level inherits from, nearest first: the shape's list style, the layout's and
    master's placeholder, the master's text style (title, body or other), the presentation's default."""
    own = _lvl(sh._element.find(f".//{A}lstStyle"), level)
    try:
        layout_part = sh.part.slide.slide_layout.part
    except AttributeError:
        return [own] if own is not None else []
    pf = sh.placeholder_format if sh.is_placeholder else None
    key = ("chain", level, pf.idx if pf else None, pf.type if pf else None)
    return ([own] if own is not None else []) + _memo(layout_part, key, lambda: _layout_chain(sh, level))


def _layout_chain(sh, level: int) -> list:
    out = []
    kind = "other"
    if sh.is_placeholder:
        pf = sh.placeholder_format
        t = pf.type.name.lower() if pf.type is not None else "body"
        kind = "title" if "title" in t and "sub" not in t else "body"
        try:
            layout = sh.part.slide.slide_layout
        except AttributeError:
            layout = None
        if layout is not None:
            for ph in [p for p in layout.placeholders if p.placeholder_format.idx == pf.idx][:1]:
                out.append(_lvl(ph._element.find(f".//{A}lstStyle"), level))
            for ph in [p for p in layout.slide_master.placeholders if p.placeholder_format.type == pf.type][:1]:
                out.append(_lvl(ph._element.find(f".//{A}lstStyle"), level))
    try:
        master = sh.part.slide.slide_layout.slide_master
        styles = master._element.find(f"{P}txStyles")
        if styles is not None:
            out.append(_lvl(styles.find(f"{P}{kind}Style"), level))
        default = sh.part.package.presentation_part.presentation._element.find(f"{P}defaultTextStyle")
        out.append(_lvl(default, level))
    except AttributeError:
        pass
    return [x for x in out if x is not None]


def _theme_fonts(sh) -> tuple[str, str]:
    """The theme's major (headings) and minor (body) Latin typefaces."""
    try:
        return _memo(sh.part.slide.slide_layout.part, "theme", lambda: _read_theme_fonts(sh))
    except AttributeError:
        return _read_theme_fonts(sh)


def _read_theme_fonts(sh) -> tuple[str, str]:
    try:
        master = sh.part.slide.slide_layout.slide_master
        for rel in master.part.rels.values():
            if rel.reltype.endswith("/theme"):
                root = rel.target_part.blob
                from lxml import etree

                theme = etree.fromstring(root)
                major = theme.find(f".//{A}majorFont/{A}latin").get("typeface")
                minor = theme.find(f".//{A}minorFont/{A}latin").get("typeface")
                return major, minor
    except (AttributeError, KeyError):
        pass
    return "Calibri Light", "Calibri"


def _first(chain, path: str, attr: str):
    for node in chain:
        x = node.find(path) if path else node
        if x is not None and x.get(attr) is not None:
            return x.get(attr)
    return None


def _body(sh) -> dict:
    """The box's insets, anchor and wrapping: its own bodyPr, then its layout's and master's placeholder's."""
    nodes = [sh._element.find(f".//{A}bodyPr")]
    if sh.is_placeholder:
        pf = sh.placeholder_format

        def inherited():
            layout = sh.part.slide.slide_layout
            same = [p for p in layout.placeholders if p.placeholder_format.idx == pf.idx][:1]
            same += [p for p in layout.slide_master.placeholders if p.placeholder_format.type == pf.type][:1]
            return [p._element.find(f".//{A}bodyPr") for p in same]

        try:
            nodes += _memo(sh.part.slide.slide_layout.part, ("body", pf.idx, pf.type), inherited)
        except AttributeError:
            pass
    nodes = [n for n in nodes if n is not None]
    out = {k: int(_first(nodes, "", k) or v) for k, v in DEFAULT_INS.items()}
    out["anchor"] = _first(nodes, "", "anchor") or "t"
    out["wrap"] = _first(nodes, "", "wrap") or "square"
    out["grows"] = any(n.find(f"{A}spAutoFit") is not None for n in nodes)  # the box grows with its text
    scale = next((n.find(f"{A}normAutofit").get("fontScale") for n in nodes if n.find(f"{A}normAutofit") is not None), None)
    out["shrinks"] = any(n.find(f"{A}normAutofit") is not None for n in nodes)
    out["font_scale"] = int(scale) / 100000 if scale else 1.0
    return out


def _spacing(value_node, size: float) -> float:
    """lnSpc / spcBef / spcAft in points: spcPct (of a single line) or spcPts."""
    if value_node is None:
        return 0.0
    pct = value_node.find(f"{A}spcPct")
    pts = value_node.find(f"{A}spcPts")
    if pct is not None:
        return int(pct.get("val")) / 100000 * PITCH * size
    if pts is not None:
        return int(pts.get("val")) / 100
    return 0.0


def measure(sh) -> dict | None:
    """The text's glyphs, as laid out: {lines, top, bottom} in points from the box's top, and the box's height;
    None for a shape without text or size, or with a typeface not installed."""
    try:
        if not sh.has_text_frame or not sh.width or not sh.height:
            return None
    except AttributeError:
        return None
    body = _body(sh)
    major, minor = _theme_fonts(sh)
    width = sh.width / EMU_PT - (body["lIns"] + body["rIns"]) / EMU_PT
    y, top_ink, bottom_ink, lines_total = 0.0, None, None, 0
    paras = sh.text_frame._txBody.findall(f"{A}p")
    for i, p in enumerate(paras):
        ppr = p.find(f"{A}pPr")
        level = int(ppr.get("lvl", 0)) if ppr is not None else 0
        chain = ([ppr] if ppr is not None else []) + _chain(sh, level)
        runs = [r for r in p if r.tag in (f"{A}r", f"{A}fld", f"{A}br")]
        defaults = [c.find(f"{A}defRPr") for c in chain if c.find(f"{A}defRPr") is not None]
        size = float(_first(defaults, "", "sz") or 1800) / 100
        bold = (_first(defaults, "", "b") or "0") in ("1", "true")
        face = _first(defaults, f"{A}latin", "typeface") or "+mn-lt"
        pieces: list[tuple[str, float, str, bool]] = []
        for r in runs:
            if r.tag == f"{A}br":
                pieces.append(("\n", size, face, bold))
                continue
            rpr = r.find(f"{A}rPr")
            s = float(rpr.get("sz")) / 100 if rpr is not None and rpr.get("sz") else size
            b = (rpr.get("b") in ("1", "true")) if rpr is not None and rpr.get("b") is not None else bold
            f = rpr.find(f"{A}latin").get("typeface") if rpr is not None and rpr.find(f"{A}latin") is not None else face
            pieces.append(("".join(t.text or "" for t in r.findall(f"{A}t")), s, f, b))
        text = "".join(t for t, *_ in pieces)
        big = max((s for t, s, *_ in pieces if t.strip()), default=size) * body["font_scale"]
        before = _spacing(_first_node(chain, "spcBef"), big) if i else 0.0
        after = _spacing(_first_node(chain, "spcAft"), big)
        line_spc = _first_node(chain, "lnSpc")
        pitch = _spacing(line_spc, big) if line_spc is not None else PITCH * big
        indent = sum(int(_first(chain, "", k) or 0) for k in ("marL",)) / EMU_PT
        room = max(width - indent, 1.0)
        n = 0
        for part in text.split("\n"):
            n += _lines(part, pieces, room, body["wrap"] != "none", major, minor)
        n = max(n, 1)
        y += before
        if text.strip():
            first_top = y + TOP * big
            last_bottom = y + (n - 1) * pitch + (TOP + INK) * big
            top_ink = first_top if top_ink is None else min(top_ink, first_top)
            bottom_ink = last_bottom if bottom_ink is None else max(bottom_ink, last_bottom)
        y += n * pitch + after
        lines_total += n
    if top_ink is None:
        return None
    box_h = sh.height / EMU_PT
    room_h = box_h - (body["tIns"] + body["bIns"]) / EMU_PT
    shift = body["tIns"] / EMU_PT  # anchored at the top
    if body["anchor"] == "ctr":
        shift += (room_h - y) / 2
    elif body["anchor"] == "b":
        shift += room_h - y
    return {"lines": lines_total, "top": shift + top_ink, "bottom": shift + bottom_ink, "box_h": box_h, **body}


def _first_node(chain, name: str):
    for node in chain:
        x = node.find(f"{A}{name}")
        if x is not None:
            return x
    return None


def _resolve(face: str, major: str, minor: str) -> str:
    return major if face.startswith("+mj") else minor if face.startswith("+mn") else face


def _lines(text: str, pieces, room: float, wraps: bool, major: str, minor: str) -> int:
    """How many lines `text` takes in `room` points, wrapped between words as PowerPoint does; measured in the
    paragraph's first run's face and size (a paragraph's runs rarely change size mid-line)."""
    if not text.strip():
        return 1
    _, size, face, bold = next(((t, s, f, b) for t, s, f, b in pieces if t.strip()), pieces[0])
    family = _resolve(face, major, minor)
    if not wraps:
        return 1
    space = width_pt(" ", family, size, bold) or size * 0.25
    lines, used = 1, 0.0
    for word in text.split(" "):
        w = width_pt(word, family, size, bold)
        if w is None:
            w = len(word) * 0.5 * size
        if used and used + space + w > room:
            lines, used = lines + 1, w
        else:
            used = used + (space if used else 0) + w
    return lines


def overflows(sh) -> bool | None:
    """Do the glyphs go past the box (beyond what a person sees)? None when it cannot be measured."""
    m = measure(sh)
    if m is None:
        return None
    if m["grows"]:
        return False  # the box grows with its text
    if m["shrinks"]:  # text that shrinks to fit overflows when it would have to shrink below 70%
        return m["bottom"] - m["top"] > (m["box_h"] - (m["tIns"] + m["bIns"]) / EMU_PT) / 0.7
    return m["top"] < -TOL_PT or m["bottom"] > m["box_h"] + TOL_PT
