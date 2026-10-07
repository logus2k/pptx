"""The document engine (M2): the read model and every single-deck operation on the fixture decks. Each operation is
checked for its effect (through the read model, as the assistant sees it) and for fidelity (spec section 6): every
part of the package it did not target is unchanged in content (XML compared in canonical form, binaries by bytes),
and what it targets keeps what it does not change (animations, extensions)."""

from __future__ import annotations

import io
import shutil
import struct
import json
import zipfile
from pathlib import Path

import jsonschema
import pytest
from lxml import etree
from PIL import Image

from app.docengine import ops, read

from .conftest import REPO

DECKS = REPO / "fixtures" / "decks"
SCHEMA = json.loads((REPO / "contracts" / "slide.schema.json").read_text())


def deck(name: str) -> bytes:
    return (DECKS / name).read_bytes()


def parts(data: bytes) -> dict[str, bytes]:
    """Each part in comparable form: XML canonicalised (attribute order, namespace prefixes), binaries as they are."""
    z = zipfile.ZipFile(io.BytesIO(data))
    out = {}
    for name in z.namelist():
        blob = z.read(name)
        if name.endswith((".xml", ".rels")):
            out[name] = etree.tostring(etree.fromstring(blob), method="c14n")
        else:
            out[name] = blob
    return out


def unchanged_except(before: bytes, after: bytes, touched: set[str], allowed_new: tuple[str, ...] = ()) -> None:
    """Every part of `before` not in `touched` is in `after`, unchanged; `after` adds only parts starting with
    `allowed_new`. [Content_Types].xml and presentation.xml(.rels) may change when slides or media come and go."""
    a, b = parts(before), parts(after)
    for name, blob in a.items():
        if name in touched:
            continue
        assert name in b, f"{name} disappeared"
        assert b[name] == blob, f"{name} changed"
    for name in set(b) - set(a):
        assert name.startswith(allowed_new), f"unexpected new part {name}"


def slide_part(data: bytes, slide_id: int) -> str:
    """The package path of a slide, by its ID."""
    prs = read.open_deck(data)
    return str(prs.slides.get(slide_id).part.partname).lstrip("/")


def first_slide(data: bytes, index: int = 0) -> int:
    return read.outline(read.open_deck(data))[index]["slide_id"]


def get(data: bytes, slide_id: int) -> dict:
    s = read.slide(read.open_deck(data), slide_id)
    jsonschema.validate(s, SCHEMA)
    return s


def text_of(shape: dict) -> list[str]:
    return ["".join(r["text"] for r in p["runs"]) for p in shape.get("paragraphs", [])]


# ── the read model ───────────────────────────────────────────────────
def test_read_model_on_every_fixture_slide_matches_the_contract():
    for name in ("simple.pptx", "features.pptx", "fidelity.pptx"):
        prs = read.open_deck(deck(name))
        for o in read.outline(prs):
            jsonschema.validate(read.slide(prs, o["slide_id"]), SCHEMA)


def test_read_model_marks_what_it_cannot_edit():
    data = deck("fidelity.pptx")
    chart_slide = get(data, first_slide(data, 0))
    chart = next(s for s in chart_slide["shapes"] if s["type"] == "chart")
    assert chart["locked"] is True and "paragraphs" not in chart
    features = deck("features.pptx")
    group = next(s for s in get(features, first_slide(features, 2))["shapes"] if s["type"] == "group")
    assert [text_of(c) for c in group["shapes"]] == [["Componente 1"], ["Componente 2"], ["Componente 3"]]
    assert get(features, first_slide(features, 3))["hidden"] is True


def test_line_breaks_and_levels_are_read():
    data = deck("simple.pptx")
    body = next(s for s in get(data, first_slide(data, 1))["shapes"] if s.get("placeholder", {}).get("idx") == 1)
    assert [(p["level"], "".join(r["text"] for r in p["runs"])) for p in body["paragraphs"]] == [
        (0, "Contexto e objetivos"),
        (0, "Solução proposta"),
        (1, "Arquitetura"),
        (1, "Calendário"),
        (0, "Preços e condições"),
    ]


# ── text ─────────────────────────────────────────────────────────────
def test_update_text_changes_only_that_shape_and_keeps_the_animation():
    data = deck("fidelity.pptx")
    sid = first_slide(data, 1)
    body = next(s for s in get(data, sid)["shapes"] if s.get("placeholder", {}).get("idx") == 1)
    new, result = ops.apply(
        data,
        "update_text",
        {
            "slide_id": sid,
            "shape_id": body["shape_id"],
            "paragraphs": [
                {"runs": [{"text": "Ponto revisto "}, {"text": "importante", "bold": True}]},
                {"level": 1, "runs": [{"text": "linha um\nlinha dois"}]},
            ],
        },
    )
    assert result["slides"] == [sid]
    after = next(s for s in get(new, sid)["shapes"] if s["shape_id"] == body["shape_id"])
    assert text_of(after) == ["Ponto revisto importante", "linha um\nlinha dois"]
    assert after["paragraphs"][0]["runs"][1]["bold"] is True and after["paragraphs"][1]["level"] == 1
    xml = zipfile.ZipFile(io.BytesIO(new)).read(slide_part(new, sid))
    assert b"p:timing" in xml and b"p14:creationId" in xml and b"p:transition" in xml
    unchanged_except(data, new, {slide_part(data, sid)})


def test_format_text_and_the_minimum_size():
    data = deck("simple.pptx")
    sid = first_slide(data, 1)
    body = next(s for s in get(data, sid)["shapes"] if s.get("placeholder", {}).get("idx") == 1)
    with pytest.raises(ops.OpError) as e:
        ops.apply(data, "format_text", {"slide_id": sid, "shape_id": body["shape_id"], "style": {"size_pt": 10}})
    assert e.value.code == "TEXT_TOO_SMALL"
    new, _ = ops.apply(
        data,
        "format_text",
        {
            "slide_id": sid,
            "shape_id": body["shape_id"],
            "style": {"size_pt": 20, "italic": True, "theme_color": "accent1"},
            "range": {"first_paragraph": 0, "last_paragraph": 0},
        },
    )
    p = next(s for s in get(new, sid)["shapes"] if s["shape_id"] == body["shape_id"])["paragraphs"]
    assert p[0]["runs"][0] == {"text": "Contexto e objetivos", "italic": True, "size_pt": 20.0, "theme_color": "accent1"}
    assert "size_pt" not in p[1]["runs"][0]
    unchanged_except(data, new, {slide_part(data, sid)})


def test_locked_and_missing_targets_are_refused_with_a_hint():
    data = deck("fidelity.pptx")
    sid = first_slide(data, 0)
    chart = next(s for s in get(data, sid)["shapes"] if s["type"] == "chart")
    for args, code in (
        ({"slide_id": sid, "shape_id": chart["shape_id"], "paragraphs": [{"runs": [{"text": "x"}]}]}, "LOCKED_ELEMENT"),
        ({"slide_id": sid, "shape_id": 999, "paragraphs": [{"runs": [{"text": "x"}]}]}, "SHAPE_NOT_FOUND"),
        ({"slide_id": 1, "shape_id": 2, "paragraphs": [{"runs": [{"text": "x"}]}]}, "SLIDE_NOT_FOUND"),
    ):
        with pytest.raises(ops.OpError) as e:
            ops.apply(data, "update_text", args)
        assert e.value.code == code and e.value.hint


# ── slides ───────────────────────────────────────────────────────────
def test_add_slide_at_a_position_with_placeholders():
    data = deck("simple.pptx")
    new, result = ops.apply(
        data,
        "add_slide",
        {
            "layout": "Title and Content",
            "position": 1,
            "placeholders": [
                {"type": "title", "text": "Garantia 2026"},
                {"idx": 1, "paragraphs": [{"runs": [{"text": "Cobertura de 2 anos"}]}]},
            ],
        },
    )
    outline = read.outline(read.open_deck(new))
    assert [o["title"] for o in outline] == ["Proposta para o Cliente X", "Garantia 2026", "Agenda", "Antes e depois"]
    assert outline[1]["slide_id"] == result["slides"][0] and outline[1]["summary"] == "Cobertura de 2 anos"
    with pytest.raises(ops.OpError) as e:
        ops.apply(data, "add_slide", {"layout": "Nope", "position": 0})
    assert e.value.code == "LAYOUT_NOT_FOUND" and "Title and Content" in e.value.hint
    unchanged_except(
        data,
        new,
        {"[Content_Types].xml", "ppt/presentation.xml", "ppt/_rels/presentation.xml.rels"},
        allowed_new=("ppt/slides/",),
    )


def test_delete_and_move_slides():
    data = deck("simple.pptx")
    ids = [o["slide_id"] for o in read.outline(read.open_deck(data))]
    moved, _ = ops.apply(data, "move_slide", {"slide_id": ids[2], "position": 0})
    assert [o["slide_id"] for o in read.outline(read.open_deck(moved))] == [ids[2], ids[0], ids[1]]
    gone, _ = ops.apply(data, "delete_slide", {"slide_id": ids[1]})
    assert [o["slide_id"] for o in read.outline(read.open_deck(gone))] == [ids[0], ids[2]]
    assert not any(n.endswith("slide2.xml") for n in zipfile.ZipFile(io.BytesIO(gone)).namelist()), "the slide's part is dropped"


def test_duplicate_slide_copies_chart_parts_and_animations():
    data = deck("fidelity.pptx")
    ids = [o["slide_id"] for o in read.outline(read.open_deck(data))]
    new, result = ops.apply(data, "duplicate_slide", {"slide_id": ids[0]})
    dup = result["slides"][0]
    assert [o["slide_id"] for o in read.outline(read.open_deck(new))] == [ids[0], dup, ids[1]]
    names = zipfile.ZipFile(io.BytesIO(new)).namelist()
    charts = [n for n in names if n.startswith("ppt/charts/chart") and n.endswith(".xml")]
    workbooks = [n for n in names if n.startswith("ppt/embeddings/")]
    assert len(charts) == 2 and len(workbooks) == 2, (charts, workbooks)  # its own chart and workbook, not shared
    prs = read.open_deck(new)
    rels = {r.reltype.rsplit("/", 1)[-1]: r.target_part.partname for r in prs.slides.get(dup).part.rels.values()}
    assert str(rels["chart"]) != str(
        {r.reltype.rsplit("/", 1)[-1]: r.target_part.partname for r in prs.slides.get(ids[0]).part.rels.values()}["chart"]
    )
    chart = next(s for s in get(new, dup)["shapes"] if s["type"] == "chart")
    assert chart["locked"] is True
    # the copied chart still finds its own workbook by the rId written in its XML
    z = zipfile.ZipFile(io.BytesIO(new))
    for c in charts:
        xml = etree.fromstring(z.read(c))
        ext = xml.find("{http://schemas.openxmlformats.org/drawingml/2006/chart}externalData")
        rid = ext.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rels = etree.fromstring(z.read(c.replace("charts/", "charts/_rels/") + ".rels"))
        target = next(r.get("Target") for r in rels if r.get("Id") == rid)
        assert target.startswith("../embeddings/")
    assert len({etree.fromstring(z.read(c.replace("charts/", "charts/_rels/") + ".rels"))[0].get("Target") for c in charts}) == 2
    new2, r2 = ops.apply(data, "duplicate_slide", {"slide_id": ids[1]})
    xml = zipfile.ZipFile(io.BytesIO(new2)).read(slide_part(new2, r2["slides"][0]))
    assert b"p:timing" in xml and b"p:transition" in xml
    unchanged_except(
        data,
        new,
        {"[Content_Types].xml", "ppt/presentation.xml", "ppt/_rels/presentation.xml.rels"},
        allowed_new=("ppt/slides/", "ppt/charts/", "ppt/embeddings/"),
    )


def test_change_layout_keeps_content_and_reports_what_it_could_not_place():
    data = deck("simple.pptx")
    sid = first_slide(data, 2)  # Two Content: a title and two columns
    new, result = ops.apply(data, "change_layout", {"slide_id": sid, "layout": "Title and Content"})
    nid = result["slides"][0]
    outline = read.outline(read.open_deck(new))
    assert (
        outline[2]["slide_id"] == nid and outline[2]["layout"] == "Title and Content" and outline[2]["title"] == "Antes e depois"
    )
    texts = [t for s in get(new, nid)["shapes"] for t in text_of(s)]
    assert "Processos manuais" in texts  # the first column moved into the body
    assert result["unmatched"] == ["Content Placeholder 3"]  # the second column had no place: reported...
    assert "Fluxo único" in texts and "Um só sistema" in texts  # ...and kept on the slide as a text box, never dropped
    back, _ = ops.apply(data, "change_layout", {"slide_id": first_slide(data, 1), "layout": "Title Only"})
    assert ops.apply(data, "set_notes", {"slide_id": first_slide(data, 1), "text": "x"})  # sanity: notes still writable
    notes = read.slide(read.open_deck(back), read.outline(read.open_deck(back))[1]["slide_id"])["notes"]
    assert notes.startswith("Falar primeiro do contexto")  # the notes travel with the slide


# ── shapes, images, tables, notes ────────────────────────────────────
def test_add_move_delete_shape_and_bounds():
    data = deck("simple.pptx")
    sid = first_slide(data, 1)
    new, r = ops.apply(
        data,
        "add_shape",
        {
            "slide_id": sid,
            "kind": "text_box",
            "box": {"x": 0.6, "y": 0.8, "w": 0.3, "h": 0.1},
            "paragraphs": [{"runs": [{"text": "Nota"}]}],
        },
    )
    added = next(s for s in get(new, sid)["shapes"] if s["shape_id"] == r["shape_id"])
    assert added["type"] == "text_box" and text_of(added) == ["Nota"] and added["box"]["x"] == 0.6
    moved, _ = ops.apply(
        new, "move_resize_shape", {"slide_id": sid, "shape_id": r["shape_id"], "box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}}
    )
    assert next(s for s in get(moved, sid)["shapes"] if s["shape_id"] == r["shape_id"])["box"] == {
        "x": 0.1,
        "y": 0.1,
        "w": 0.2,
        "h": 0.1,
    }
    gone, _ = ops.apply(moved, "delete_shape", {"slide_id": sid, "shape_id": r["shape_id"]})
    assert all(s["shape_id"] != r["shape_id"] for s in get(gone, sid)["shapes"])
    with pytest.raises(ops.OpError) as e:
        ops.apply(data, "add_shape", {"slide_id": sid, "kind": "text_box", "box": {"x": 0.9, "y": 0.1, "w": 0.3, "h": 0.1}})
    assert e.value.code == "OUT_OF_BOUNDS"


def _png(w: int, h: int, colour=(0, 128, 255)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(b, "PNG")
    return b.getvalue()


def test_insert_image_in_a_box_keeps_proportions_and_webp_becomes_png():
    data = deck("simple.pptx")
    sid = first_slide(data, 1)
    webp = io.BytesIO()
    Image.new("RGB", (400, 200), (10, 200, 30)).save(webp, "WEBP")
    new, r = ops.apply(
        data,
        "insert_image",
        {"slide_id": sid, "image": webp.getvalue(), "target": {"box": {"x": 0.5, "y": 0.2, "w": 0.4, "h": 0.6}}},
    )
    pic = next(s for s in get(new, sid)["shapes"] if s["shape_id"] == r["shape_id"])
    W, H = 12192000, 6858000
    assert pic["type"] == "picture"
    assert abs((pic["emu"]["w"] / pic["emu"]["h"]) - 2.0) < 0.01  # the image's 2:1, not the box's
    assert pic["emu"]["w"] == round(0.4 * W) and pic["emu"]["y"] > round(0.2 * H)  # full width, centred vertically
    media = [n for n in zipfile.ZipFile(io.BytesIO(new)).namelist() if n.startswith("ppt/media/")]
    assert any(n.endswith(".png") for n in media)
    with pytest.raises(ops.OpError) as e:
        ops.apply(
            data,
            "insert_image",
            {"slide_id": sid, "image": b"not an image", "target": {"box": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}},
        )
    assert e.value.code == "BAD_IMAGE"
    with pytest.raises(ops.OpError) as e:
        ops.apply(data, "insert_image", {"slide_id": sid, "image": _png(10, 10), "target": {"placeholder_idx": 1}})
    assert e.value.code == "NO_PICTURE_PLACEHOLDER"


def test_replace_image_keeps_the_frame_and_alt_text():
    data = deck("features.pptx")
    sid = first_slide(data, 1)
    pic = next(s for s in get(data, sid)["shapes"] if s["type"] == "picture")
    with_alt, _ = ops.apply(data, "set_alt_text", {"slide_id": sid, "shape_id": pic["shape_id"], "text": "Linha de triagem"})
    new, _ = ops.apply(with_alt, "replace_image", {"slide_id": sid, "shape_id": pic["shape_id"], "image": _png(1000, 1000)})
    after = next(s for s in get(new, sid)["shapes"] if s["shape_id"] == pic["shape_id"])
    assert after["emu"] == pic["emu"] and after["alt_text"] == "Linha de triagem"
    prs = read.open_deck(new)
    sh = next(x for x in prs.slides.get(sid).shapes if x.shape_id == pic["shape_id"])
    frame = sh.width / sh.height  # 6:3.75 = 1.6; a square image: crop top and bottom
    assert sh.crop_left == 0 and sh.crop_top > 0 and abs(sh.crop_top - sh.crop_bottom) < 1e-6
    assert abs((1 - sh.crop_top - sh.crop_bottom) - 1 / frame) < 0.01


def test_edit_table_rows_columns_and_cells():
    data = deck("features.pptx")
    sid = first_slide(data, 0)
    table = next(s for s in get(data, sid)["shapes"] if s["type"] == "table")
    new, _ = ops.apply(
        data,
        "edit_table",
        {
            "slide_id": sid,
            "shape_id": table["shape_id"],
            "operations": [
                {"op": "set_cell", "row": 1, "col": 2, "text": "€ 450"},
                {"op": "add_row", "at": 4},
                {"op": "set_cell", "row": 4, "col": 0, "text": "Público"},
                {"op": "add_column", "at": 3},
                {"op": "set_cell", "row": 0, "col": 3, "text": "Suporte"},
                {"op": "delete_row", "row": 2},
            ],
        },
    )
    t = next(s for s in get(new, sid)["shapes"] if s["shape_id"] == table["shape_id"])["table"]
    assert (t["rows"], t["cols"]) == (4, 4)
    assert [row[0] for row in t["cells"]] == ["Escalão", "Base", "Empresa", "Público"]
    assert t["cells"][1][2] == "€ 450" and t["cells"][0][3] == "Suporte" and t["cells"][3][1] == ""
    prs = read.open_deck(new)
    sh = next(x for x in prs.slides.get(sid).shapes if x.shape_id == table["shape_id"])
    assert abs(sum(c.width for c in sh.table.columns) - sh.width) < 10  # the table keeps its width



def test_edit_table_new_row_and_column_with_their_cells():
    data = deck("features.pptx")
    sid = first_slide(data, 0)
    table = next(s for s in get(data, sid)["shapes"] if s["type"] == "table")
    before = table["table"]
    new, _ = ops.apply(
        data,
        "edit_table",
        {
            "slide_id": sid,
            "shape_id": table["shape_id"],
            "operations": [
                {"op": "add_row", "cells": ["Start", "até 10", "€ 100"]},  # at the end
                {"op": "add_row", "at": 1, "cells": ["Mini"]},  # fewer cells than columns: the rest stay empty
                {"op": "add_column", "at": 1, "cells": ["Nota"] + ["-"] * 99},  # more than rows: the extra ignored
            ],
        },
    )
    t = next(s for s in get(new, sid)["shapes"] if s["shape_id"] == table["shape_id"])["table"]
    assert (t["rows"], t["cols"]) == (before["rows"] + 2, before["cols"] + 1)
    assert t["cells"][-1][0] == "Start" and t["cells"][-1][2:4] == ["até 10", "€ 100"]
    assert t["cells"][1][0] == "Mini" and t["cells"][1][2] == ""
    assert [row[1] for row in t["cells"]] == ["Nota"] + ["-"] * (t["rows"] - 1)
    assert [row[0] for row in t["cells"]][2:-1] == [row[0] for row in before["cells"]][1:]

def test_set_notes():
    data = deck("simple.pptx")
    sid = first_slide(data, 0)
    new, _ = ops.apply(data, "set_notes", {"slide_id": sid, "text": "Fonte: KB 'Política de garantia' (WP-4)."})
    assert get(new, sid)["notes"] == "Fonte: KB 'Política de garantia' (WP-4)."


def test_the_outline_says_what_each_slide_holds_beyond_its_text():
    """A slide whose content is a table, a picture or a group is not blank in the outline: the model learns there is
    a price table on slide 1 without reading every slide."""
    rows = {o["index"] + 1: o["summary"] for o in read.outline(read.open_deck(deck("features.pptx")))}
    assert rows[1] == "table, 4 rows by 3 columns: Escalão, Utilizadores, Preço mensal"
    assert rows[2].startswith("picture")
    assert rows[3] == "Componente 1 · Componente 2 · Componente 3"
    agenda = {o["index"] + 1: o["summary"] for o in read.outline(read.open_deck(deck("simple.pptx")))}[2]
    assert agenda == "Contexto e objetivos / Solução proposta / Arquitetura / Calendário / Preços e condições"
    report = read.open_deck((REPO / "fixtures" / "eval" / "report.pptx").read_bytes())
    longest = max((o["summary"] for o in read.outline(report)), key=len)
    assert len(longest) == 200 and longest.endswith("…")


def test_slides_are_placed_next_to_another_slide_by_its_id():
    """after_slide_id / before_slide_id: no counting (measured: gemma-4 put "before the agenda" at position 0)."""
    data = deck("simple.pptx")
    a, b, c = [o["slide_id"] for o in read.outline(read.open_deck(data))]
    order = lambda d: [o["slide_id"] for o in read.outline(read.open_deck(d))]  # noqa: E731
    moved, _ = ops.apply(data, "move_slide", {"slide_id": c, "before_slide_id": b})
    assert order(moved) == [a, c, b]
    moved, _ = ops.apply(data, "move_slide", {"slide_id": a, "after_slide_id": c})
    assert order(moved) == [b, c, a]
    added, result = ops.apply(
        data,
        "add_slide",
        {
            "layout": "Title and Content",
            "after_slide_id": a,
            "placeholders": [{"type": "title", "text": "Nova"}, {"type": "body", "text": "Corpo"}],
        },
    )
    new = result["slides"][0]
    assert order(added) == [a, new, b, c]
    texts = [text_of(s) for s in get(added, new)["shapes"]]
    assert ["Nova"] in texts and ["Corpo"] in texts  # "body": the layout's content placeholder
    added, result = ops.apply(data, "add_slide", {"layout": "Title Slide", "placeholders": [{"type": "title", "text": "Fim"}]})
    assert order(added)[-1] == result["slides"][0]  # no place given: at the end
    assert ["Fim"] in [text_of(s) for s in get(added, result["slides"][0])["shapes"]]  # a title slide's centred title
    dup, result = ops.apply(data, "duplicate_slide", {"slide_id": a, "before_slide_id": c})
    assert order(dup) == [a, b, result["slides"][0], c]
    with pytest.raises(ops.OpError) as e:
        ops.apply(data, "move_slide", {"slide_id": a, "after_slide_id": a})
    assert e.value.code == "SLIDE_NOT_FOUND"
    with pytest.raises(ops.OpError):
        ops.apply(data, "move_slide", {"slide_id": a})


def test_a_table_cell_without_its_column_is_refused_not_a_crash():
    data = deck("features.pptx")
    sid = first_slide(data)
    with pytest.raises(ops.OpError) as e:
        ops.apply(data, "edit_table", {"slide_id": sid, "shape_id": 3, "operations": [{"op": "set_cell", "row": 2, "text": "x"}]})
    assert e.value.code == "BAD_ARGUMENTS" and "col" in str(e.value)


def test_the_executor_takes_nulls_as_left_out_and_enum_values_in_any_case():
    from app.agent.tools import Executor, ToolError

    ex = Executor.__new__(Executor)
    from app.agent.tools import load_schemas

    ex.schemas = load_schemas()
    args = ex.parse(
        "update_text",
        {"slide_id": 256, "shape_id": 2, "paragraphs": [{"runs": [{"text": "x", "theme_color": None, "bold": None}]}]},
    )
    assert args["paragraphs"][0]["runs"][0] == {"text": "x"}
    assert (
        ex.parse("add_shape", {"slide_id": 256, "kind": "TEXT_BOX", "box": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}})["kind"]
        == "text_box"
    )
    with pytest.raises(ToolError) as e:
        ex.parse(
            "edit_table", {"slide_id": 1, "shape_id": 3, "operations": [{"op": "set_text", "row": 0, "col": 0, "text": "x"}]}
        )
    assert e.value.code == "BAD_ARGUMENTS"  # not a case away from a listed value: refused
    with pytest.raises(ToolError) as e:
        ex.parse("update_text", {"slide_id": None, "shape_id": 2, "paragraphs": [{"runs": [{"text": "x"}]}]})
    assert "slide_id" in str(e.value)  # a required field sent as null: refused by name


def test_edit_paragraphs_changes_only_the_named_ones():
    """A bullet added, changed or removed by its index; every other paragraph's XML is untouched (measured: rewriting
    the whole list with update_text, gemma-4 dropped bullets and flattened levels)."""
    data = deck("simple.pptx")
    agenda = first_slide(data, 1)
    before = [etree.tostring(p) for p in _paragraph_elements(data, agenda, 3)]
    new, _ = ops.apply(
        data,
        "edit_paragraphs",
        {
            "slide_id": agenda,
            "shape_id": 3,
            "operations": [
                {"op": "insert", "after": 3, "text": "Garantia"},  # after Calendário (level 1): its level
                {"op": "insert", "text": "Perguntas", "level": 0},  # at the end
                {"op": "insert", "after": -1, "text": "Abertura"},  # first
                {"op": "set", "index": 1, "text": "A solução"},
                {"op": "delete", "index": 2},  # Arquitetura
            ],
        },
    )
    shape = next(x for x in get(new, agenda)["shapes"] if x["shape_id"] == 3)
    rows = [("".join(r["text"] for r in p["runs"]), p.get("level", 0)) for p in shape["paragraphs"]]
    assert rows == [
        ("Abertura", 0),
        ("Contexto e objetivos", 0),
        ("A solução", 0),
        ("Calendário", 1),
        ("Garantia", 1),
        ("Preços e condições", 0),
        ("Perguntas", 0),
    ]
    after = [etree.tostring(p) for p in _paragraph_elements(new, agenda, 3)]
    assert after[1] == before[0] and after[3] == before[3] and after[5] == before[4]  # untouched: the same XML
    unchanged_except(data, new, {slide_part(data, agenda)})
    lines, _ = ops.apply(
        data,
        "edit_paragraphs",
        {"slide_id": agenda, "shape_id": 3, "operations": [{"op": "set", "index": 4, "text": "Preços\nCondições"}]},
    )
    assert text_of(next(x for x in get(lines, agenda)["shapes"] if x["shape_id"] == 3))[-2:] == ["Preços", "Condições"]
    with pytest.raises(ops.OpError) as e:
        ops.apply(data, "edit_paragraphs", {"slide_id": agenda, "shape_id": 3, "operations": [{"op": "delete", "index": 9}]})
    assert e.value.code == "BAD_PARAGRAPH" and "0-4" in str(e.value)


def _paragraph_elements(data: bytes, slide_id: int, shape_id: int):
    prs = read.open_deck(data)
    s = next(x for x in prs.slides if x.slide_id == slide_id)
    sh = next(x for x in s.shapes if x.shape_id == shape_id)
    return sh.text_frame._txBody.findall("{http://schemas.openxmlformats.org/drawingml/2006/main}p")


def test_a_plain_paragraph_with_line_breaks_is_several_paragraphs():
    """{"text": "a\\nb"}: two paragraphs (measured: gemma-4 sent a four-bullet list that way)."""
    from app.agent.tools import Executor, load_schemas

    ex = Executor.__new__(Executor)
    ex.schemas = load_schemas()
    args = ex.parse(
        "update_text",
        {"slide_id": 1, "shape_id": 3, "paragraphs": [{"text": "Instagram\nTikTok", "level": 1}, {"text": "Podcasts"}]},
    )
    assert args["paragraphs"] == [
        {"level": 1, "runs": [{"text": "Instagram"}]},
        {"level": 1, "runs": [{"text": "TikTok"}]},
        {"runs": [{"text": "Podcasts"}]},
    ]
    keep = ex.parse("update_text", {"slide_id": 1, "shape_id": 3, "paragraphs": [{"runs": [{"text": "line\nbreak"}]}]})
    assert keep["paragraphs"] == [{"runs": [{"text": "line\nbreak"}]}]  # inside runs: a line break, as before


def test_reading_a_deck_never_changes_it():
    """The read model only reads: every slide of every fixture deck, read, serialises exactly as before (measured: a
    run's colour read through python-pptx wrote an empty <a:solidFill/> into it, and edits saved them)."""
    for name in ("simple.pptx", "features.pptx", "fidelity.pptx"):
        prs = read.open_deck(deck(name))
        before = [etree.tostring(s._element) for s in prs.slides]
        for o in read.outline(prs):
            read.slide(prs, o["slide_id"])
        assert [etree.tostring(s._element) for s in prs.slides] == before, name


def test_an_edit_leaves_the_other_runs_of_its_shape_as_they_were():
    data = deck("simple.pptx")
    agenda = first_slide(data, 1)
    before = [etree.tostring(p) for p in _paragraph_elements(data, agenda, 3)]
    new, _ = ops.apply(
        data, "edit_paragraphs", {"slide_id": agenda, "shape_id": 3, "operations": [{"op": "set", "index": 0, "text": "X"}]}
    )
    after = [etree.tostring(p) for p in _paragraph_elements(new, agenda, 3)]
    assert after[1:] == before[1:]
    assert b"solidFill" not in b"".join(after)


def test_a_slide_by_its_number_and_a_layout_by_its_name_written_another_way():
    """Slide numbers (1 to 255: never an ID, ECMA-376 starts IDs at 256) are positions in the deck as it is now; the
    recorded call holds the ID. A layout named "title_and_content" is "Title and Content"."""
    from app.agent.tools import Executor

    data = deck("simple.pptx")
    ids = [o["slide_id"] for o in read.outline(read.open_deck(data))]
    assert Executor._positions({"slide_id": 3, "after_slide_id": 1, "shape_id": 2}, data) == {
        "slide_id": ids[2],
        "after_slide_id": ids[0],
        "shape_id": 2,
    }
    assert Executor._positions({"slide_id": ids[1]}, data) == {"slide_id": ids[1]}  # an ID stays
    from app.agent.tools import ToolError

    with pytest.raises(ToolError) as e:
        Executor._positions({"slide_id": 9}, data)
    assert "1 to 3" in str(e.value)
    new, result = ops.apply(data, "add_slide", {"layout": "title_and_content", "placeholders": [{"type": "title", "text": "T"}]})
    assert get(new, result["slides"][0])["layout"] == "Title and Content"


# ── slides from another deck (spec PJ-6, PJ-7) ──────────────────────
def _names(data: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_slides_copied_from_another_deck_bring_their_content_and_parts():
    target, source = deck("simple.pptx"), deck("features.pptx")
    src_ids = [o["slide_id"] for o in read.outline(read.open_deck(source))]
    new, result = ops.apply(
        target,
        "copy_slides",
        {"source": source, "from_deck_id": "x", "slide_ids": src_ids, "after_slide_id": first_slide(target)},
    )
    names = _names(new)
    assert len(names) == len(set(names)), "no part name twice"
    order = [o["slide_id"] for o in read.outline(read.open_deck(new))]
    assert order[1:5] == result["slides"] and len(order) == 7  # after the first slide, in their order
    table, picture, group, hidden = (get(new, sid) for sid in result["slides"])
    assert next(s for s in table["shapes"] if s["type"] == "table")["table"]["cells"][2] == ["Pro", "até 500", "€ 2 500"]
    assert any(s["type"] == "picture" for s in picture["shapes"]) and picture["notes"] == "Imagem de exemplo."
    assert [text_of(x) for x in next(s for s in group["shapes"] if s["type"] == "group")["shapes"]] == [
        ["Componente 1"],
        ["Componente 2"],
        ["Componente 3"],
    ]
    assert hidden["hidden"] and text_of(next(s for s in hidden["shapes"] if s["shape_id"] != 2)) == [
        "Não aparece na apresentação"
    ]
    assert table["layout"] == "Title Only" and text_of(
        next(s for s in table["shapes"] if s.get("placeholder", {}).get("type") == "title")
    ) == ["Preços por escalão"]
    # the picture's bytes travelled: an image part in the target that the source's picture had
    src_media = {n: zipfile.ZipFile(io.BytesIO(source)).read(n) for n in _names(source) if n.startswith("ppt/media/")}
    new_media = [zipfile.ZipFile(io.BytesIO(new)).read(n) for n in names if n.startswith("ppt/media/")]
    assert any(b in new_media for b in src_media.values())
    assert result["unmatched"] == []


def test_a_copied_chart_brings_its_own_chart_and_workbook():
    target, source = deck("simple.pptx"), deck("fidelity.pptx")
    chart_slide = read.outline(read.open_deck(source))[0]["slide_id"]
    new, result = ops.apply(target, "copy_slides", {"source": source, "slide_ids": [chart_slide]})
    names = _names(new)
    assert len(names) == len(set(names))
    assert any(n.startswith("ppt/charts/chart") for n in names) and any(n.startswith("ppt/embeddings/") for n in names)
    assert any(s["type"] == "chart" for s in get(new, result["slides"][0])["shapes"])


def test_text_with_no_place_in_the_target_layouts_is_kept_and_reported():
    source = deck("simple.pptx")
    prs = read.open_deck((REPO / "templates" / "default.pptx").read_bytes())  # no slides yet
    master = prs.slide_masters[0]
    # a template with no layout of two bodies ("Content with Caption" would take both columns: an exact match)
    for layout in [lay for lay in master.slide_layouts if lay.name in ("Two Content", "Comparison", "Content with Caption")]:
        master.slide_layouts.remove(layout)
    prs.slides.add_slide(master.slide_layouts[0])
    buf = io.BytesIO()
    prs.save(buf)
    target = buf.getvalue()
    two_columns = read.outline(read.open_deck(source))[2]["slide_id"]
    new, result = ops.apply(target, "copy_slides", {"source": source, "slide_ids": [two_columns]})
    slide = get(new, result["slides"][0])
    assert slide["layout"] == "Title and Content"  # the nearest: a title and one body
    texts = [text_of(s) for s in slide["shapes"]]
    assert ["Processos manuais", "Vários sistemas"] in texts and ["Fluxo único", "Um só sistema"] in texts
    assert len(result["unmatched"]) == 1 and "Fluxo único" in result["unmatched"][0] and "text box" in result["unmatched"][0]


@pytest.mark.skipif(
    shutil.which("soffice") is None or not Path("/usr/lib/libreoffice/share/registry/impress.xcd").exists(),
    reason="LibreOffice Impress is not installed here (run make check)",
)
def test_a_deck_with_copied_slides_renders():
    import asyncio
    import tempfile

    from app.docengine import render

    new, _ = ops.apply(deck("simple.pptx"), "copy_slides", {"source": deck("features.pptx"), "slide_ids": [256, 257, 258]})
    cache = Path(tempfile.mkdtemp())
    keys = asyncio.run(render.ensure(new, cache))
    assert len(keys) == 6 and all((cache / k["key"] / "preview.png").exists() for k in keys)


def _other_template() -> bytes:
    """python-pptx's own default: 4:3 and the Office theme - unlike the 16:9 default template here."""
    from pptx import Presentation

    buf = io.BytesIO()
    Presentation().save(buf)
    return buf.getvalue()


def test_a_deck_on_another_template_keeps_its_slides_and_their_content():
    data = deck("features.pptx")
    before = read.outline(read.open_deck(data))
    new, result = ops.apply(data, "change_template", {"template": _other_template()})
    prs = read.open_deck(new)
    assert (prs.slide_width, prs.slide_height) == (9144000, 6858000)  # the template's 4:3
    after = read.outline(prs)
    assert [o["slide_id"] for o in after] == [o["slide_id"] for o in before] == result["slides"]  # the same slides
    assert [o["title"] for o in after] == [o["title"] for o in before]
    assert after[3]["hidden"]
    table = next(s for s in get(new, before[0]["slide_id"])["shapes"] if s["type"] == "table")
    assert table["table"]["cells"][2] == ["Pro", "até 500", "€ 2 500"]
    assert table["box"]["x"] >= 0 and table["box"]["x"] + table["box"]["w"] <= 1.001  # scaled into the narrower slide
    frame = next(sh for sh in next(x for x in prs.slides if x.slide_id == before[0]["slide_id"]).shapes if sh.has_table)
    assert sum(c.width for c in frame.table.columns) <= frame.width + 10  # its columns too (seen: wider than the slide)
    assert result["unmatched"] == []
    names = _names(new)
    assert len(names) == len(set(names))


def test_the_overflow_estimate_agrees_with_what_libreoffice_draws():
    """Calibrated on rendered slides (looked at, 2026-10-06): the report's results slide as it is fits; seven
    one-line bullets fit; nine pass the bottom of the box; fourteen two-line bullets overflow by far."""
    data = (REPO / "fixtures" / "eval" / "report.pptx").read_bytes()

    def body(n: int, words: str) -> bool:
        new, _ = ops.apply(
            data,
            "update_text",
            {"slide_id": 258, "shape_id": 3, "paragraphs": [{"runs": [{"text": f"Ponto {i + 1}: {words}"}]} for i in range(n)]},
        )
        return next(s for s in get(new, 258)["shapes"] if s["shape_id"] == 3)["overflow"]

    assert next(s for s in get(data, 258)["shapes"] if s["shape_id"] == 3)["overflow"] is False
    assert body(7, "uma frase longa sobre os resultados do trimestre") is False
    assert body(9, "uma frase longa sobre os resultados do trimestre") is True
    assert body(14, "uma frase longa sobre os resultados do trimestre com bastante detalhe") is True


def test_set_texts_keeps_untouched_paragraphs_exactly():
    data = deck("simple.pptx")
    sid = first_slide(data, 1)  # the agenda: five paragraphs
    body = next(s for s in get(data, sid)["shapes"] if len(s.get("paragraphs") or []) >= 5)
    old = text_of(body)
    lines = [old[0], "Novo ponto", old[1].upper(), *old[3:]]  # one inserted, one changed, one deleted (old[2])

    def xml_of(d: bytes) -> list[bytes]:
        sh = next(x for x in read.open_deck(d).slides.get(sid).shapes if x.shape_id == body["shape_id"])
        return [etree.tostring(p) for p in sh.text_frame._txBody.findall("{http://schemas.openxmlformats.org/drawingml/2006/main}p")]

    new, _ = ops.apply(data, "set_texts", {"slide_id": sid, "shape_id": body["shape_id"], "texts": lines})
    assert text_of(next(s for s in get(new, sid)["shapes"] if s["shape_id"] == body["shape_id"])) == lines
    before, after = xml_of(data), xml_of(new)
    assert after[0] == before[0] and after[3:] == before[3:]  # untouched: byte for byte
    same, _ = ops.apply(data, "set_texts", {"slide_id": sid, "shape_id": body["shape_id"], "texts": old})
    assert xml_of(same) == before  # nothing typed differently: nothing changes
    with pytest.raises(ops.OpError):
        ops.apply(data, "set_texts", {"slide_id": 9999, "shape_id": body["shape_id"], "texts": ["x"]})


def test_a_slide_s_render_key_follows_the_installed_fonts(monkeypatch):
    from app.docengine import render

    data = deck("simple.pptx")
    monkeypatch.setattr(render, "_fonts", "a stand-in font")
    before = [k["key"] for k in render.keys(data)]
    monkeypatch.setattr(render, "_fonts", "the template's own font")
    after = [k["key"] for k in render.keys(data)]
    assert len(before) == len(after) and not set(before) & set(after)  # every slide is rendered again
    assert [k["key"] for k in render.keys(data)] == after  # and the same fonts give the same keys


def test_add_slide_idx_0_and_1_mean_title_and_body_on_a_layout_numbered_otherwise():
    data = deck("simple.pptx")
    prs = read.open_deck(data)
    layout = next(lo for m in prs.slide_masters for lo in m.slide_layouts if lo.name == "Title and Content")
    body = next(ph for ph in layout.placeholders if ph.placeholder_format.idx == 1)
    body.element.nvSpPr.nvPr.find(qn_ph()).set("idx", "16")  # as a template numbers its body (Banco CTT's: 16)
    renumbered = io.BytesIO()
    prs.save(renumbered)
    new, result = ops.apply(
        renumbered.getvalue(),
        "add_slide",
        {
            "layout": "Title and Content",
            "placeholders": [{"idx": 0, "text": "Boas práticas"}, {"idx": 1, "text": "Primeira\nSegunda"}],
        },
    )
    s = get(new, result["slides"][0])
    texts = {sh["placeholder"]["idx"]: text_of(sh) for sh in s["shapes"] if sh.get("placeholder")}
    assert texts[0] == ["Boas práticas"] and texts[16] == ["Primeira", "Segunda"]


def qn_ph():
    from pptx.oxml.ns import qn

    return qn("p:ph")


def _emf(*records: bytes) -> bytes:
    """A small EMF: its header, the records, its end (MS-EMF layouts)."""
    body = b"".join(records) + struct.pack("<IIIII", 14, 20, 0, 16, 20)
    header = bytearray(108)
    struct.pack_into("<II", header, 0, 1, 108)
    struct.pack_into("<iiii", header, 8, 0, 0, 100, 20)  # rclBounds (px)
    struct.pack_into("<iiii", header, 24, 0, 0, 2600, 520)  # rclFrame (0.01 mm)
    struct.pack_into("<I", header, 40, 0x464D4520)  # " EMF"
    struct.pack_into("<I", header, 48, 108 + len(body))
    return bytes(header) + body


def test_emf_pictures_are_drawn_from_their_records_and_not_clipped_at_their_frame():
    from app.docengine import emf

    comment = b"GDIC" + struct.pack("<I", emf.MULTIFORMATS) + b"\0" * 24  # an alternative copy (a PDF, in Banco CTT's logo)
    raw = _emf(
        struct.pack("<III", 0x11, 12, 8),  # SETMAPMODE anisotropic
        struct.pack("<IIii", 0x0A, 16, 0, 0),  # SETWINDOWORGEX
        struct.pack("<IIii", 0x09, 16, 1000, 200),  # SETWINDOWEXTEX: the declared window 0-1000 x 0-200
        struct.pack("<IIii", 0x0B, 16, 100, 20),  # SETVIEWPORTEXTEX
        struct.pack("<III", 0x46, 12 + len(comment), len(comment)) + comment,
        struct.pack("<II4iI4h", 0x57, 36, 0, 0, 0, 0, 2, 0, 0, 1000, 210),  # POLYLINE16 down to y 210: past the window
    )
    assert emf.is_emf(raw)
    out, (left, top, right, bottom) = emf.prepare(raw)
    assert b"GDIC" not in out and b"SLID" in out  # the alternative copy is skipped: the records are drawn
    assert (left, top) == (2 / 1000, 2 / 200) and right == 2 / 1000 and bottom == 12 / 200  # grown to the line + 2
    frame = struct.unpack_from("<iiii", out, 24)
    assert frame[3] == round(520 * (1 + top + bottom)) and frame[2] == round(2600 * (1 + left + right))
    plain = _emf(struct.pack("<III", 0x11, 12, 1))  # MM_TEXT, no window: nothing to grow
    assert emf.prepare(plain) == (plain, (0.0, 0.0, 0.0, 0.0))
    assert emf.prepare(b"\x89PNG not an emf") == (b"\x89PNG not an emf", (0.0, 0.0, 0.0, 0.0))


def test_a_diagram_grows_with_copies_of_its_boxes_and_arrows_attached_to_them():
    data, blank = ops.apply(deck("simple.pptx"), "add_slide", {"layout": "Title Only"})  # a diagram's slide
    sid = blank["slides"][0]
    first = {"x": 0.1, "y": 0.7, "w": 0.2, "h": 0.1}
    args = {"slide_id": sid, "kind": "rounded_rectangle", "box": first, "paragraphs": [{"runs": [{"text": "NEW"}]}]}
    data, made = ops.apply(data, "add_shape", args)
    box = made["shape_id"]
    data, copy_ = ops.apply(data, "duplicate_shape", {"slide_id": sid, "shape_id": box, "box": {"x": 0.6, "y": 0.7},
                                                      "paragraphs": [{"runs": [{"text": "DONE"}]}]})  # fmt: skip
    new = copy_["shape_id"]
    prs = read.open_deck(data)
    s = prs.slides.get(sid)
    a, b = (next(x for x in s.shapes if x.shape_id == i) for i in (box, new))
    strip = lambda el: etree.tostring(el.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}spPr/{http://schemas.openxmlformats.org/drawingml/2006/main}prstGeom"))  # noqa: E731
    assert strip(a._element) == strip(b._element) and (b.width, b.height) == (a.width, a.height)  # same box, same size
    assert abs(b.left / prs.slide_width - 0.6) < 0.001 and b.text_frame.text == "DONE" and a.text_frame.text == "NEW"
    data, line = ops.apply(data, "connect_shapes", {"slide_id": sid, "from_shape_id": box, "to_shape_id": new})
    data, styled = ops.apply(data, "connect_shapes", {"slide_id": sid, "from_shape_id": new, "to_shape_id": box,
                                                      "like_connector_id": line["shape_id"], "arrow": "both"})  # fmt: skip
    shapes = {x["shape_id"]: x for x in get(data, sid)["shapes"]}
    assert shapes[line["shape_id"]]["type"] == "connector" and shapes[line["shape_id"]]["connects"] == [box, new]
    assert shapes[styled["shape_id"]]["connects"] == [new, box]
    el = next(x for x in read.open_deck(data).slides.get(sid).shapes if x.shape_id == line["shape_id"])._element
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    assert el.find(f".//{a_}stCxn").get("idx") == "3" and el.find(f".//{a_}endCxn").get("idx") == "1"  # right -> left
    assert el.find(f".//{a_}prstGeom").get("prst") == "straightConnector1"  # in line: straight
    assert el.find(f".//{a_}tailEnd") is not None and el.find(f".//{a_}headEnd") is None
    back = next(x for x in read.open_deck(data).slides.get(sid).shapes if x.shape_id == styled["shape_id"])._element
    assert back.find(f".//{a_}xfrm").get("flipH") == "1" and back.find(f".//{a_}headEnd") is not None  # leftwards, both
    with pytest.raises(ops.OpError):
        ops.apply(data, "connect_shapes", {"slide_id": sid, "from_shape_id": box, "to_shape_id": box})
    title = next(x for x in get(data, sid)["shapes"] if (x.get("placeholder") or {}).get("idx") == 0)["shape_id"]
    with pytest.raises(ops.OpError):  # a placeholder is not copied
        ops.apply(data, "duplicate_shape", {"slide_id": sid, "shape_id": title})


def test_shapes_inside_a_group_are_not_copied_or_connected_on_their_own():
    data = deck("features.pptx")
    sid = first_slide(data, 2)
    group = next(s for s in get(data, sid)["shapes"] if s["type"] == "group")
    member = group["shapes"][0]["shape_id"]
    with pytest.raises(ops.OpError) as e:
        ops.apply(data, "duplicate_shape", {"slide_id": sid, "shape_id": member})
    assert e.value.code == "IN_GROUP"


def test_a_copy_goes_where_it_covers_nothing_and_an_arrow_looks_like_the_diagram_s():
    data, blank = ops.apply(deck("simple.pptx"), "add_slide", {"layout": "Blank"})  # a diagram's slide
    sid = blank["slides"][0]
    boxes = []
    for x in (0.1, 0.35):  # two boxes in a row: the copy of the first must not land on the second
        args = {"slide_id": sid, "kind": "rectangle", "box": {"x": x, "y": 0.75, "w": 0.2, "h": 0.1}}
        data, made = ops.apply(data, "add_shape", args)
        boxes.append(made["shape_id"])
    data, copy_ = ops.apply(data, "duplicate_shape", {"slide_id": sid, "shape_id": boxes[0]})
    assert copy_["covers"] == []
    prs = read.open_deck(data)
    s = prs.slides.get(sid)
    others = [(x.shape_id, x.left, x.top, x.width, x.height) for x in s.shapes if x.shape_id != copy_["shape_id"]]
    new = next(x for x in s.shapes if x.shape_id == copy_["shape_id"])
    assert ops._overlapping((new.left, new.top, new.width, new.height), others) == []
    data, over = ops.apply(data, "duplicate_shape", {"slide_id": sid, "shape_id": boxes[0], "box": {"x": 0.35, "y": 0.75}})
    assert over["moved"] and over["covers"] == []  # asked to go on the second box: put at the nearest free place
    moved = next(x for x in read.open_deck(data).slides.get(sid).shapes if x.shape_id == over["shape_id"])
    assert abs(moved.top / read.open_deck(data).slide_height - 0.75) < 0.35  # near where it was asked for
    link = {"slide_id": sid, "from_shape_id": boxes[0], "to_shape_id": boxes[1], "kind": "elbow"}
    data, first = ops.apply(data, "connect_shapes", link)
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    el = lambda d, i: next(x for x in read.open_deck(d).slides.get(sid).shapes if x.shape_id == i)._element  # noqa: E731
    prs = read.open_deck(data)  # the diagram's own line, as a template has it: 2.5 pt
    target = next(x for x in prs.slides.get(sid).shapes if x.shape_id == first["shape_id"])._element
    target.find(f".//{a_}ln").set("w", "31750")
    edited = io.BytesIO()
    prs.save(edited)
    link = {"slide_id": sid, "from_shape_id": boxes[1], "to_shape_id": copy_["shape_id"]}
    data, second = ops.apply(edited.getvalue(), "connect_shapes", link)
    assert el(data, second["shape_id"]).find(f".//{a_}ln").get("w") == "31750"  # like the slide's connectors
