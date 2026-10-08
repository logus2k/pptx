"""The editor's controls (the user's rule, 2026-10-07: every change the assistant can make has a control too): each
is one of the assistant's editing tools sent to POST /edits as {op: "tool", tool, args}, checked against the tool's
schema, applied as the assistant's are, and published as a "manual" version that undo takes back."""

from __future__ import annotations

import io

import requests
from PIL import Image

from app.docengine import read

from .test_decks import ANA, RUI, h, new_project, upload


class Deck:
    def __init__(self, server, name="features.pptx"):
        self.server = server
        self.pid = new_project(server)["id"]
        self.did = upload(server, self.pid, name).json()["id"]
        self.base = f"{server}/api/projects/{self.pid}/decks/{self.did}"

    @property
    def version(self) -> int:
        return requests.get(self.base, headers=h(ANA), timeout=30).json()["version"]

    def tool(self, tool, args, who=ANA):
        body = {"base_version": self.version, "op": "tool", "tool": tool, "args": args}
        return requests.post(f"{self.base}/edits", json=body, headers=h(who), timeout=60)

    def ok(self, tool, args) -> dict:
        r = self.tool(tool, args)
        assert r.status_code == 200, (tool, r.status_code, r.text)
        return r.json()

    def order(self) -> list[int]:
        return [s["id"] for s in requests.get(self.base, headers=h(ANA), timeout=30).json()["slides"]]

    def slide(self, sid) -> dict:
        return requests.get(f"{self.base}/slides/{sid}", headers=h(ANA), timeout=30).json()

    def prs(self):
        data = requests.get(f"{self.base}/download", headers=h(ANA), timeout=30).content
        return read.open_deck(data)


def test_slides_are_added_duplicated_relaid_and_given_notes_by_hand(server):
    d = Deck(server)
    first = d.order()[0]
    layouts = requests.get(f"{d.base}/layouts", headers=h(ANA), timeout=30).json()["layouts"]
    names = [x["name"] for x in layouts]
    assert "Title and Content" in names and next(x for x in layouts if x["name"] == "Title and Content")["points"] == 1
    made = d.ok("add_slide", {"after_slide_id": first, "content": {"title": "Novo", "points": ["Um", "Dois"]}})
    new = made["result"]["slides"][0]
    assert d.order()[1] == new  # right after the selected slide, on the layout its content fits
    texts = [p["runs"][0]["text"] for s in d.slide(new)["shapes"] for p in s.get("paragraphs") or [] if p.get("runs")]
    assert texts == ["Novo", "Um", "Dois"]
    copy = d.ok("duplicate_slide", {"slide_id": new})["result"]["slides"][0]
    assert d.order()[2] == copy
    d.ok("change_layout", {"slide_id": copy, "layout": "Title Only"})
    relaid = next(o for o in read.outline(d.prs()) if o["title"] == "Novo" and o["slide_id"] != new)
    assert relaid["layout"] == "Title Only"
    d.ok("set_notes", {"slide_id": new, "text": "O que dizer."})
    assert d.slide(new)["notes"] == "O que dizer."
    versions = requests.get(f"{d.base}/versions", headers=h(ANA), timeout=10).json()["versions"]
    assert [v["source"] for v in versions][:4] == ["manual"] * 4
    assert requests.post(f"{d.base}/undo", headers=h(ANA), timeout=30).status_code == 200
    assert d.slide(new)["notes"] == ""  # undo takes the notes back


def test_charts_diagrams_and_tables_are_made_and_changed_by_hand(server):
    d = Deck(server)
    table, picture, _, content = d.order()
    chart = {"kind": "column", "categories": ["T1", "T2"], "series": [{"name": "2026", "values": [3, 5]}]}
    d.ok("add_chart", {"slide_id": picture, **chart, "title": "Vendas"})
    shape = next(s for s in d.slide(picture)["shapes"] if s["type"] == "chart")
    assert shape["chart"]["categories"] == ["T1", "T2"]
    d.ok("edit_chart", {"slide_id": picture, "shape_id": shape["shape_id"], "kind": "bar",
                        "categories": ["T1", "T2"], "series": [{"name": "2026", "values": [4, 6]}]})  # fmt: skip
    shape = next(s for s in d.slide(picture)["shapes"] if s["type"] == "chart")
    assert shape["chart"]["series"][0]["values"] == [4, 6]
    drawn = d.ok("draw_diagram", {"slide_id": content, "nodes": [{"text": "Pedido"}, {"text": "Análise"}, {"text": "Decisão"}]})
    assert drawn["result"]["covers"], drawn["result"]  # over the slide's list: said, so the editor tells the person
    words = [p["runs"][0]["text"] for s in d.slide(content)["shapes"] for p in s.get("paragraphs") or [] if p.get("runs")]
    assert {"Pedido", "Análise", "Decisão"} <= set(words)
    cells = next(s for s in d.slide(table)["shapes"] if s["type"] == "table")
    d.ok("edit_table", {"slide_id": table, "shape_id": cells["shape_id"],
                        "operations": [{"op": "set_cell", "row": 1, "col": 0, "text": "Mudado"}]})  # fmt: skip
    cells = next(s for s in d.slide(table)["shapes"] if s["type"] == "table")
    assert cells["table"]["cells"][1][0] == "Mudado"


def test_pictures_get_alt_text_and_are_replaced_and_inserted_from_an_upload(server):
    d = Deck(server)
    _, picture, _, content = d.order()
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(out, "PNG")
    asset = requests.post(f"{server}/api/projects/{d.pid}/assets", data={"kind": "image"},
                          files={"file": ("red.png", out.getvalue())}, headers=h(ANA), timeout=30).json()  # fmt: skip
    shape = next(s for s in d.slide(picture)["shapes"] if s["type"] == "picture")
    d.ok("set_alt_text", {"slide_id": picture, "shape_id": shape["shape_id"], "text": "Um gráfico de barras"})
    assert next(s for s in d.slide(picture)["shapes"] if s["type"] == "picture")["alt_text"] == "Um gráfico de barras"
    d.ok("replace_image", {"slide_id": picture, "shape_id": shape["shape_id"], "image": {"asset_id": asset["id"]}})
    box = {"x": 0.1, "y": 0.3, "w": 0.3, "h": 0.3}
    d.ok("insert_image", {"slide_id": content, "image": {"asset_id": asset["id"]}, "target": {"box": box}})
    assert any(s["type"] == "picture" for s in d.slide(content)["shapes"])


def test_text_is_formatted_and_fitted_by_hand(server):
    d = Deck(server)
    content = d.order()[3]
    body = next(s for s in d.slide(content)["shapes"] if s.get("placeholder", {}).get("idx") == 1)
    d.ok("format_text", {"slide_id": content, "shape_id": body["shape_id"], "style": {"bold": True, "size_pt": 20}})
    runs = [r for p in next(s for s in d.slide(content)["shapes"] if s["shape_id"] == body["shape_id"])["paragraphs"]
            for r in p.get("runs") or []]  # fmt: skip
    assert runs and all(r.get("bold") for r in runs)
    long = [f"Ponto {n}: o colaborador confirma o documento do cliente e regista o passo no sistema." for n in range(14)]
    r = requests.post(f"{d.base}/edits", json={"base_version": d.version, "op": "text", "slide_id": content,
                                               "shape_id": body["shape_id"], "paragraphs": long}, headers=h(ANA), timeout=60)
    assert r.status_code == 200, r.text
    fitted = d.ok("fit_text", {"slide_id": content, "shape_id": body["shape_id"]})  # the text past its box, fitted
    assert fitted["current_version"] == d.version


def test_slides_are_copied_from_another_deck_and_a_deck_changes_template(server):
    d = Deck(server)
    other = upload(server, d.pid, "simple.pptx").json()["id"]
    before = len(d.order())
    d.ok("copy_slides", {"from_deck_id": other, "slide_ids": [1, 2]})
    assert len(d.order()) == before + 2
    listing = requests.get(f"{server}/api/templates?project={d.pid}", headers=h(ANA), timeout=10).json()
    tid = listing["default"]
    d.ok("change_template", {"template": {"kind": "admin", "id": tid}})
    record = requests.get(d.base, headers=h(ANA), timeout=10).json()["record"]
    assert record["template"] == {"kind": "admin", "id": tid}


def test_what_is_not_an_editor_control_or_breaks_its_schema_is_refused(server):
    d = Deck(server)
    first = d.order()[0]
    assert d.tool("kb_search", {"query": "x"}).status_code == 422  # not an edit
    assert d.tool("generate_deck", {"source": {"kind": "kb_topic", "query": "x"}}).status_code == 422
    bad = d.tool("add_chart", {"slide_id": first, "kind": "radar", "categories": ["a"], "series": []})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "BAD_ARGUMENTS"
    assert d.tool("set_notes", {"slide_id": first, "text": "x"}, who=RUI).status_code == 404  # not a member
    versions = requests.get(f"{d.base}/versions", headers=h(ANA), timeout=10).json()["versions"]
    assert [v["source"] for v in versions] == ["upload"]  # nothing changed
