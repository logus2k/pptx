"""What a layout's placeholders are for, read from the layout itself: where each sits, how large its text is set, and
the prompt its designer wrote. Templates such as Banco CTT's type almost every placeholder "body" (a slide's heading
included: no layout of its text family has a title placeholder), so the type alone says nothing a model can choose
by (measured: an empty deck from it, the model picked "10_Texto", four columns under a heading, for "create a slide",
and wrote nothing into it). The roles here - heading, subtitle, tag, then rows of text, numbers, pictures, tables - are
what a person sees when the layout is drawn (looked at: each of the 57 layouts rendered with its placeholders named).

`describe` gives one line a layout for the model; `heading` and `subtitle` the placeholders "title" and "subtitle"
mean on a layout that has no placeholder of that type."""

from __future__ import annotations

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
SKIP = ("date", "footer", "slide_number")
GENERIC = ("click to edit", "clique para editar", "clique para")  # a layout's default prompt, not its designer's hint


def _size(ph, master_body: float) -> tuple[float, bool]:
    """The placeholder's text size (points) and weight: its own text, list style, else the master's body style."""
    for r in ph._element.iter(f"{A}rPr", f"{A}defRPr", f"{A}endParaRPr"):
        if r.get("sz"):
            return int(r.get("sz")) / 100, r.get("b") in ("1", "true")
    return master_body, False


def _master_body(layout) -> float:
    styles = layout.slide_master._element.find(f"{P}txStyles")
    lvl = styles.find(f"{P}bodyStyle/{A}lvl1pPr/{A}defRPr") if styles is not None else None
    return int(lvl.get("sz")) / 100 if lvl is not None and lvl.get("sz") else 18.0


def placeholders(layout, width: int, height: int) -> list[dict]:
    """The layout's placeholders (not date, footer, number), top to bottom then left to right, each with its role:
    heading, subtitle, tag, text, number (a prompt like "00"), picture, table, chart, diagram, media."""
    body = _master_body(layout)
    found = []
    for ph in layout.placeholders:
        kind = ph.placeholder_format.type.name.lower() if ph.placeholder_format.type is not None else "body"
        if kind in SKIP:
            continue
        size, bold = _size(ph, body)
        prompt = " ".join((ph.text_frame.text if ph.has_text_frame else "").split())
        found.append({
            "idx": ph.placeholder_format.idx, "kind": kind, "size": size, "bold": bold,
            "prompt": "" if not prompt or prompt.lower().startswith(GENERIC) else prompt[:20],
            "x": (ph.left or 0) / width, "y": (ph.top or 0) / height,
            "w": (ph.width or 0) / width, "h": (ph.height or 0) / height,
        })  # fmt: skip
    found.sort(key=lambda p: (round(p["y"], 2), p["x"]))
    texts = [p for p in found if p["kind"] in ("body", "object", "subtitle", "title", "center_title")]
    for p in found:
        p["role"] = {"pic": "picture", "picture": "picture", "table": "table", "chart": "chart", "org_chart": "diagram",
                     "media": "media", "clip_art": "picture", "bitmap": "picture"}.get(p["kind"], "text")  # fmt: skip
    titles = [p for p in texts if p["kind"] in ("title", "center_title")]
    large = [p for p in texts if p["size"] >= 20 and not p["prompt"]]
    head = titles[0] if titles else (max(large, key=lambda p: (p["size"], -p["y"])) if large else None)
    if head:
        head["role"] = "heading"
        under = [
            p for p in texts
            if p is not head and abs(p["x"] - head["x"]) < 0.03 and head["y"] < p["y"] <= head["y"] + head["h"] + 0.08
            and p["size"] < head["size"] and not p["prompt"] and p["h"] <= 0.2 and p["w"] >= 0.6 * head["w"]
        ]  # fmt: skip
        if under:
            min(under, key=lambda p: p["y"])["role"] = "subtitle"
    for p in texts:
        if p["role"] != "text":
            continue
        if p["prompt"]:
            p["role"] = "number" if p["prompt"].strip("0") == "" else "text"
        elif p["y"] < 0.1 and p["x"] > 0.7 and p["w"] < 0.3:
            p["role"] = "tag"
    return found


def heading(layout, width: int, height: int) -> int | None:
    return next((p["idx"] for p in placeholders(layout, width, height) if p["role"] == "heading"), None)


def subtitle(layout, width: int, height: int) -> int | None:
    return next((p["idx"] for p in placeholders(layout, width, height) if p["role"] == "subtitle"), None)


def describe(layout, width: int, height: int) -> str:
    """One line: "heading [19] (24 pt); subtitle [20]; 4 side by side, 18 pt bold: [30] [32] [34] [36]; ..."."""
    parts, row = [], []

    def flush():
        if not row:
            return
        p = row[0]
        what = {"text": "text", "number": "number", "picture": "picture", "table": "table", "chart": "chart",
                "diagram": "diagram", "media": "media"}[p["role"]]  # fmt: skip
        style = f", {p['size']:g} pt{' bold' if p['bold'] else ''}" if what in ("text", "number") else ""
        big = " large" if what == "text" and p["h"] >= 0.3 else ""
        ids = " ".join(f"[{x['idx']}]" for x in row)
        count = f"{len(row)} side by side, " if len(row) > 1 else ""
        parts.append(f"{count}{what}{big}{style}: {ids}")
        row.clear()

    for p in placeholders(layout, width, height):
        if p["role"] in ("heading", "subtitle", "tag"):
            flush()
            parts.append(f"{p['role']} [{p['idx']}]" + (f" ({p['size']:g} pt)" if p["role"] == "heading" else ""))
            continue
        if row and (abs(p["y"] - row[0]["y"]) > 0.03 or p["role"] != row[0]["role"] or p["size"] != row[0]["size"]):
            flush()
        row.append(p)
    flush()
    return "; ".join(parts) or "no placeholders (shapes only)"


def _column(a: dict, b: dict) -> bool:
    """Do the two boxes share a column (their widths overlap by half the narrower)?"""
    overlap = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    return overlap >= 0.5 * min(a["w"], b["w"])


def slots(layout, width: int, height: int) -> dict:
    """Where a slide's content goes on this layout: {heading, subtitle, items: [{body, header, number}], large} - each
    item a text box, with the bold one-line box over it in its column (a column's heading) and the number box over
    it or beside it ("00": an agenda's), in reading order; large, the text box with the most room (for a list that has
    more points than the layout has boxes)."""
    ps = placeholders(layout, width, height)
    head = next((p for p in ps if p["role"] == "heading"), None)
    sub = next((p for p in ps if p["role"] == "subtitle"), None)
    texts = [p for p in ps if p["role"] == "text"]
    numbers = [p for p in ps if p["role"] == "number"]
    height_pt = height / 12700

    def room(p):
        return p["h"] * height_pt / (p["size"] * 1.2)

    # a column's heading: bold, one line, with a text box under it in its column
    def has_body_under(p):
        return any(q is not p and not q["bold"] and _column(p, q) and 0 < q["y"] - p["y"] <= 0.3 for q in texts)

    headers = {id(p) for p in texts if p["bold"] and room(p) < 2.5 and has_body_under(p)}
    bodies = [p for p in texts if id(p) not in headers]
    items, used = [], set()
    for b in bodies:
        above = [h for h in texts if id(h) in headers and id(h) not in used and _column(h, b) and 0 < b["y"] - h["y"] <= 0.3]
        header = min(above, key=lambda h: b["y"] - h["y"]) if above else None
        def numbers_it(n, b=b):
            over = _column(n, b) and 0 < b["y"] - n["y"] <= 0.25
            beside = abs(n["y"] - b["y"]) < 0.05 and 0 < b["x"] - n["x"] <= 0.25
            return id(n) not in used and (over or beside)

        near = [n for n in numbers if numbers_it(n)]
        number = min(near, key=lambda n: abs(b["y"] - n["y"]) + abs(b["x"] - n["x"])) if near else None
        for x in (header, number):
            if x is not None:
                used.add(id(x))
        item = {"body": b["idx"], "header": header and header["idx"], "number": number and number["idx"], "room": room(b)}
        items.append(item)
    large = max(items, key=lambda i: i["room"])["body"] if items else None
    return {"heading": head and head["idx"], "subtitle": sub and sub["idx"], "items": items, "large": large}
