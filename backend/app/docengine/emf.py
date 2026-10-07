"""EMF pictures as PowerPoint draws them, for LibreOffice's previews and PDFs (never for the deck people download).

Two things in real templates' EMF pictures made LibreOffice draw them unlike PowerPoint (measured on Banco CTT's logo,
an EMF on the Squad Model deck's master):
- an alternative copy of the picture in a "multi-format" comment (EMR_COMMENT_MULTIFORMATS, here a PDF): LibreOffice
  drew it as a low-resolution bitmap, jagged at every zoom; PowerPoint on Windows draws the EMF's own vector records.
  The comment is made private, so the records are drawn.
- outlines past the picture's declared frame (the logo's letters reached y 315 in a window of 0-307): LibreOffice clips
  at the frame - the bottom of "ctt" was cut - where PowerPoint draws them. The frame is widened to the outlines, and
  the caller grows the picture's box by the same proportions (normalised()), so nothing is shrunk.

Read with struct over the documented record layouts ([MS-EMF]); a picture this does not understand is left as it is."""

from __future__ import annotations

import io
import struct

from lxml import etree

EMF_SIGNATURE = 0x464D4520  # " EMF"
MULTIFORMATS = 0x40000004
POINTS16 = (0x55, 0x56, 0x57, 0x58, 0x59)  # POLYBEZIER16, POLYGON16, POLYLINE16, POLYBEZIERTO16, POLYLINETO16
POLYPOINTS16 = (0x5A, 0x5B)  # POLYPOLYLINE16, POLYPOLYGON16
POINTS32 = (0x02, 0x03, 0x04, 0x05, 0x06)  # POLYBEZIER, POLYGON, POLYLINE, POLYBEZIERTO, POLYLINETO
POLYPOINTS32 = (0x07, 0x08)  # POLYPOLYLINE, POLYPOLYGON
MOVE_LINE = (0x1B, 0x36)  # MOVETOEX, LINETO
TRANSFORMS = (0x23, 0x24)  # SETWORLDTRANSFORM, MODIFYWORLDTRANSFORM: logical units no longer map simply
MARGIN = 2  # logical units around the outlines


def is_emf(data: bytes) -> bool:
    if len(data) < 88:
        return False
    return struct.unpack_from("<I", data, 0)[0] == 1 and struct.unpack_from("<I", data, 40)[0] == EMF_SIGNATURE


def prepare(data: bytes) -> tuple[bytes, tuple[float, float, float, float]]:
    """The EMF drawn from its own records and not clipped by its frame, and how much its frame grew on each side, as
    fractions of the original (left, top, right, bottom); (data, zeros) for an EMF this cannot change safely."""
    if not is_emf(data):
        return data, (0.0, 0.0, 0.0, 0.0)
    d = bytearray(data)
    p, window, origin, viewport, mapmode, transformed = 0, None, None, None, None, False
    xs: list[int] = []
    ys: list[int] = []
    while p + 8 <= len(d):
        kind, size = struct.unpack_from("<II", d, p)
        if size < 8 or p + size > len(d):
            return data, (0.0, 0.0, 0.0, 0.0)
        multiformats = kind == 0x46 and size >= 20 and d[p + 12 : p + 16] == b"GDIC"
        if multiformats and struct.unpack_from("<I", d, p + 16)[0] == MULTIFORMATS:
            d[p + 12 : p + 16] = b"SLID"  # a private comment now: renderers skip it and draw the records
        elif kind == 0x09 and window is None:
            window = (p, *struct.unpack_from("<ii", d, p + 8))
        elif kind == 0x0A and origin is None:
            origin = (p, *struct.unpack_from("<ii", d, p + 8))
        elif kind == 0x0B and viewport is None:
            viewport = (p, *struct.unpack_from("<ii", d, p + 8))
        elif kind == 0x11:
            mapmode = struct.unpack_from("<I", d, p + 8)[0]
        elif kind in TRANSFORMS:
            transformed = True
        elif kind in POINTS16 and size >= 28:
            n = struct.unpack_from("<I", d, p + 24)[0]
            pts = struct.unpack_from(f"<{2 * n}h", d, p + 28) if 28 + 4 * n <= size else ()
            xs += pts[0::2]
            ys += pts[1::2]
        elif kind in POLYPOINTS16 and size >= 32:
            polys, n = struct.unpack_from("<II", d, p + 24)
            at = 32 + 4 * polys
            pts = struct.unpack_from(f"<{2 * n}h", d, p + at) if at + 4 * n <= size else ()
            xs += pts[0::2]
            ys += pts[1::2]
        elif kind in POINTS32 and size >= 28:
            n = struct.unpack_from("<I", d, p + 24)[0]
            pts = struct.unpack_from(f"<{2 * n}i", d, p + 28) if 28 + 8 * n <= size else ()
            xs += pts[0::2]
            ys += pts[1::2]
        elif kind in POLYPOINTS32 and size >= 32:
            polys, n = struct.unpack_from("<II", d, p + 24)
            at = 32 + 4 * polys
            pts = struct.unpack_from(f"<{2 * n}i", d, p + at) if at + 8 * n <= size else ()
            xs += pts[0::2]
            ys += pts[1::2]
        elif kind in MOVE_LINE:
            x, y = struct.unpack_from("<ii", d, p + 8)
            xs.append(x)
            ys.append(y)
        p += size
    grown = (0.0, 0.0, 0.0, 0.0)
    anisotropic = mapmode in (7, 8)  # MM_ISOTROPIC, MM_ANISOTROPIC: the window and viewport define the scale
    if xs and window and viewport and anisotropic and not transformed:
        wp, wx, wy = window
        op, ox, oy = origin or (None, 0, 0)
        vp, vx, vy = viewport
        x0, y0 = min(ox, min(xs) - MARGIN), min(oy, min(ys) - MARGIN)
        x1, y1 = max(ox + wx, max(xs) + MARGIN), max(oy + wy, max(ys) + MARGIN)
        if wx > 0 and wy > 0 and (x0, y0, x1, y1) != (ox, oy, ox + wx, oy + wy) and origin is not None:
            sx, sy = (x1 - x0) / wx, (y1 - y0) / wy
            struct.pack_into("<ii", d, op + 8, x0, y0)
            struct.pack_into("<ii", d, wp + 8, x1 - x0, y1 - y0)
            struct.pack_into("<ii", d, vp + 8, round(vx * sx), round(vy * sy))
            bl, bt, br, bb = struct.unpack_from("<iiii", d, 8)  # rclBounds (device pixels)
            fl, ft, fr, fb = struct.unpack_from("<iiii", d, 24)  # rclFrame (0.01 mm)
            struct.pack_into("<iiii", d, 8, bl, bt, bl + round((br - bl) * sx) + 1, bt + round((bb - bt) * sy) + 1)
            struct.pack_into("<iiii", d, 24, fl, ft, fl + round((fr - fl) * sx), ft + round((fb - ft) * sy))
            grown = ((ox - x0) / wx, (oy - y0) / wy, (x1 - ox - wx) / wx, (y1 - oy - wy) / wy)
    return bytes(d), grown


P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def normalised(pptx: bytes) -> bytes:
    """The deck with every EMF picture prepared (prepare()) and each picture showing one grown by the same proportions,
    so its drawing keeps its size and place. For rendering only."""
    from pptx import Presentation

    prs = Presentation(io.BytesIO(pptx))
    growth: dict[str, tuple[float, float, float, float]] = {}
    for part in prs.part.package.iter_parts():
        name = str(part.partname)
        if name.startswith("/ppt/media/") and is_emf(part.blob):
            new, grown = prepare(part.blob)
            if new != part.blob:
                part._blob = new
            if any(grown):
                growth[name] = grown
    if growth:
        for part in prs.part.package.iter_parts():
            name = str(part.partname)
            if not name.startswith(("/ppt/slides/", "/ppt/slideLayouts/", "/ppt/slideMasters/")) or not name.endswith(".xml"):
                continue
            root = part._element if hasattr(part, "_element") else None
            if root is None:
                continue
            changed = False
            for pic in root.iter(f"{P}pic"):
                blip = pic.find(f".//{A}blip")
                rid = blip.get(f"{R}embed") if blip is not None else None
                if not rid or rid not in part.rels:
                    continue
                target = str(part.rels[rid].target_part.partname)
                if target not in growth:
                    continue
                left, top, right, bottom = growth[target]
                xfrm = pic.find(f"{P}spPr/{A}xfrm")
                off, ext = (xfrm.find(f"{A}off"), xfrm.find(f"{A}ext")) if xfrm is not None else (None, None)
                if off is None or ext is None:
                    continue
                cx, cy = int(ext.get("cx")), int(ext.get("cy"))
                off.set("x", str(int(off.get("x")) - round(cx * left)))
                off.set("y", str(int(off.get("y")) - round(cy * top)))
                ext.set("cx", str(round(cx * (1 + left + right))))
                ext.set("cy", str(round(cy * (1 + top + bottom))))
                changed = True
            if changed:
                etree.cleanup_namespaces(root)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
