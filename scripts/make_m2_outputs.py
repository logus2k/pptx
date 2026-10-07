"""Writes fixtures/out/m2-*.pptx: ten decks edited by the engine, one operation (or a few) each, for M2's manual check
(technical design section 13): open each in PowerPoint and confirm it opens without a repair prompt and shows the
change described in its name. Run: .venv/bin/python scripts/make_m2_outputs.py"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.docengine import ops, read  # noqa: E402

D = ROOT / "fixtures" / "decks"
OUT = ROOT / "fixtures" / "out"


def ids(data: bytes) -> list[int]:
    return [o["slide_id"] for o in read.outline(read.open_deck(data))]


def shape_of(data: bytes, sid: int, kind: str) -> int:
    return next(s["shape_id"] for s in read.slide(read.open_deck(data), sid)["shapes"] if s["type"] == kind)


def body_of(data: bytes, sid: int) -> int:
    return next(
        s["shape_id"] for s in read.slide(read.open_deck(data), sid)["shapes"] if s.get("placeholder", {}).get("idx") == 1
    )


def png(colour) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (900, 600), colour).save(b, "PNG")
    return b.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    simple, features, fidelity = (
        (D / "simple.pptx").read_bytes(),
        (D / "features.pptx").read_bytes(),
        (D / "fidelity.pptx").read_bytes(),
    )
    s = ids(simple)
    f = ids(features)
    x = ids(fidelity)
    jobs = {
        "01-update-text-on-animated-slide": (
            fidelity,
            [
                (
                    "update_text",
                    {
                        "slide_id": x[1],
                        "shape_id": body_of(fidelity, x[1]),
                        "paragraphs": [
                            {"runs": [{"text": "Texto revisto "}, {"text": "em negrito", "bold": True}]},
                            {"level": 1, "runs": [{"text": "subponto"}]},
                        ],
                    },
                )
            ],
        ),
        "02-format-text-size-colour": (
            simple,
            [
                (
                    "format_text",
                    {
                        "slide_id": s[1],
                        "shape_id": body_of(simple, s[1]),
                        "style": {"size_pt": 24, "theme_color": "accent2", "bold": True},
                    },
                )
            ],
        ),
        "03-add-slide-at-position-2": (
            simple,
            [
                (
                    "add_slide",
                    {
                        "layout": "Title and Content",
                        "position": 1,
                        "placeholders": [
                            {"type": "title", "text": "Garantia 2026"},
                            {"idx": 1, "text": "Cobertura de 2 anos\nAssistência no local"},
                        ],
                    },
                )
            ],
        ),
        "04-duplicate-chart-slide": (fidelity, [("duplicate_slide", {"slide_id": x[0]})]),
        "05-delete-and-move-slides": (
            simple,
            [("delete_slide", {"slide_id": s[0]}), ("move_slide", {"slide_id": s[2], "position": 0})],
        ),
        "06-change-layout-two-content-to-title-content": (
            simple,
            [("change_layout", {"slide_id": s[2], "layout": "Title and Content"})],
        ),
        "07-add-shapes-and-move": (
            simple,
            [
                (
                    "add_shape",
                    {
                        "slide_id": s[1],
                        "kind": "rounded_rectangle",
                        "box": {"x": 0.6, "y": 0.7, "w": 0.3, "h": 0.15},
                        "paragraphs": [{"runs": [{"text": "Nota"}]}],
                    },
                )
            ],
        ),
        "08-insert-and-replace-image": (
            features,
            [
                (
                    "insert_image",
                    {"slide_id": f[2], "image": png((20, 160, 90)), "target": {"box": {"x": 0.55, "y": 0.4, "w": 0.4, "h": 0.5}}},
                ),
                (
                    "replace_image",
                    {"slide_id": f[1], "shape_id": shape_of(features, f[1], "picture"), "image": png((200, 40, 40))},
                ),
            ],
        ),
        "09-edit-table-row-column": (
            features,
            [
                (
                    "edit_table",
                    {
                        "slide_id": f[0],
                        "shape_id": shape_of(features, f[0], "table"),
                        "operations": [
                            {"op": "add_column", "at": 3},
                            {"op": "set_cell", "row": 0, "col": 3, "text": "Suporte"},
                            {"op": "add_row", "at": 4},
                            {"op": "set_cell", "row": 4, "col": 0, "text": "Público"},
                            {"op": "delete_row", "row": 2},
                        ],
                    },
                )
            ],
        ),
        "10-notes-and-alt-text": (
            features,
            [
                ("set_notes", {"slide_id": f[0], "text": "Fonte: tabela de preços 2026."}),
                ("set_alt_text", {"slide_id": f[1], "shape_id": shape_of(features, f[1], "picture"), "text": "Linha de triagem"}),
            ],
        ),
    }
    for name, (data, steps) in jobs.items():
        for op, args in steps:
            data, _ = ops.apply(data, op, args)
        (OUT / f"m2-{name}.pptx").write_bytes(data)
        print(f"m2-{name}.pptx")


if __name__ == "__main__":
    main()
