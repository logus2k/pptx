"""The Artist (agent/artist.py; the user, 2026-10-08): each slide's form - bullets, columns, key figures, a highlight, a
table, a chart, a diagram - proposed by the model, checked by the application (nothing it shows that the slide does not
say), laid out on the template's layout for the form (ops.add_designed); its ideas asked for at any time - in the
outline review, in the editor, in the chat - and the chosen one applied as a reviewed change or a manual version."""

from __future__ import annotations

import time

import requests

from app.agent import artist
from app.docengine import ops, read

from .conftest import REPO
from .test_agent import Chat, deck_bytes, h, outline, setup

SLIDE = {"title": "Limites", "points": ["Um mutuário: até 80.000 €.", "Dois mutuários: até 160.000 €.", "Idade: 18 a 35 anos."],
         "notes": "O limite segue o 8.º escalão do IRS."}  # fmt: skip


def test_a_proposal_showing_what_the_slide_does_not_say_becomes_its_list():
    ok = {"form": "figures", "figures": [{"value": "80.000 €", "label": "um mutuário"}, {"value": "160.000 €", "label": "dois"},
                                         {"value": "18 a 35", "label": "anos de idade"}]}  # fmt: skip
    assert artist.checked(ok, SLIDE)["form"] == "figures"
    left_out = {"form": "figures", "figures": ok["figures"][:2]}  # the age left out: the list, which has it all
    assert artist.checked(left_out, SLIDE)["form"] == "bullets"
    invented = {"form": "figures", "figures": [{"value": "90.000 €", "label": "um"}, {"value": "160.000 €", "label": "dois"},
                                               {"value": "18 a 35", "label": "anos"}]}  # fmt: skip
    assert artist.checked(invented, SLIDE) == {"form": "bullets", "points": SLIDE["points"]}
    chart = {
        "form": "chart",
        "chart": {"kind": "column", "categories": ["Um", "Dois"], "series": [{"name": "Limite", "values": [80000, 160000]}]},
    }
    assert artist.checked(chart, SLIDE)["form"] == "chart"
    wrong = {
        "form": "chart",
        "chart": {"kind": "column", "categories": ["Um", "Dois"], "series": [{"name": "L", "values": [80000, 170000]}]},
    }
    assert artist.checked(wrong, SLIDE)["form"] == "bullets"
    assert artist.checked({"form": "columns"}, SLIDE)["form"] == "bullets"  # a form without its content
    assert artist.checked({"form": "poster"}, SLIDE)["form"] == "bullets"
    assert artist.checked(None, SLIDE)["form"] == "bullets"


def test_each_form_goes_on_the_templates_layout_for_it():
    ctt = read.open_deck((REPO / "templates" / "bancoctt.pptx").read_bytes())
    designs = {
        "columns": {"form": "columns", "columns": [{"heading": "Geral", "points": ["Obras"]},
                                                   {"heading": "Hipotecário", "points": ["Isolado"]}]},
        "figures": {"form": "figures", "figures": [{"value": "35", "label": "anos"}, {"value": "100%", "label": "financiado"}]},
        "highlight": {"form": "highlight", "highlight": {"statement": "Até 100% financiado", "detail": "Com o Estado."}},
        "table": {"form": "table", "table": {"rows": [["Mutuários", "Limite"], ["Um", "80.000 €"]]}},
        "diagram": {"form": "diagram", "diagram": {"nodes": ["Proposta", "Enquadramento", "Formalização"]}},
    }  # fmt: skip
    layouts = {}
    for name, d in designs.items():
        sid = ops.add_designed(ctt, {"title": name.title(), "design": d})[0]
        s = read.slide(ctt, sid)
        layouts[name] = s["layout"]
        texts = [" ".join("".join(r["text"] for r in p["runs"]) for p in sh.get("paragraphs") or []) for sh in s["shapes"]]
        if name == "figures":
            assert "35" in texts and "100%" in texts and texts.count("anos") == 1  # each value in its number place, once
        if name == "table":
            cells = next(sh for sh in s["shapes"] if sh["type"] == "table")["table"]["cells"]
            assert cells == [["Mutuários", "Limite"], ["Um", "80.000 €"]]
        if name == "diagram":
            assert {"Proposta", "Enquadramento", "Formalização"} <= set(texts)
    assert layouts == {"columns": "4_Texto", "figures": "17_Text", "highlight": "1_Highlight", "table": "3_Tabela",
                       "diagram": "12_Texto"}  # fmt: skip


def test_columns_are_shaped_to_what_they_hold():
    """Looked at: "4_Texto"'s two cards 4.7 inches tall for three short lines, no bullets; "10_Texto"'s four places for
    three columns, the last quarter empty, an inch between each heading and its text. Now: equal cards as tall as the
    longest text (never past the layout's), bulleted, the row's width shared, each text under its heading; a single
    line is not bulleted, and the text fits its box."""
    from app.docengine import textfit

    ctt = read.open_deck((REPO / "templates" / "bancoctt.pptx").read_bytes())
    two = {"form": "columns", "columns": [{"heading": "Geral", "points": ["Aquisição", "Obras", "Construção"]},
                                          {"heading": "Hipotecário", "points": ["Isolado"]}]}  # fmt: skip
    three = {"form": "columns", "columns": [{"heading": h, "points": [p]} for h, p in
                                            [("HPP", "Permanente"), ("HPS", "Secundária"), ("HA", "Arrendamento")]]}  # fmt: skip
    first = ctt.slides.get(ops.add_designed(ctt, {"title": "Dois", "design": two})[0])
    second = ctt.slides.get(ops.add_designed(ctt, {"title": "Três", "design": three})[0])
    assert first.slide_layout.name == "4_Texto" and second.slide_layout.name == "10_Texto"
    lay = {ph.placeholder_format.idx: ph for ph in first.slide_layout.placeholders}

    def box(s, text):
        return next(sh for sh in s.placeholders if sh.text_frame.text.startswith(text))

    a, b = box(first, "Aquisição"), box(first, "Isolado")
    assert a.height == b.height < lay[a.placeholder_format.idx].height / 2
    assert not textfit.overflows(a) and not textfit.overflows(b)
    bullets = lambda sh: [p._p.find(".//" + qn_a("buChar")) is not None for p in sh.text_frame.paragraphs]  # noqa: E731
    assert bullets(a) == [True, True, True] and bullets(b) == [False]
    heads = [box(second, x) for x in ("HPP", "HPS", "HA")]
    bodies = [box(second, x) for x in ("Permanente", "Secundária", "Arrendamento")]
    four = sorted((ph for ph in second.slide_layout.placeholders if ph.top == heads[0].top), key=lambda ph: ph.left)
    assert len(four) == 4 and abs(heads[-1].left + heads[-1].width - four[-1].left - four[-1].width) <= 1  # the row's width
    for head, body in zip(heads, bodies, strict=True):
        assert body.left == head.left and 0 < body.top - (head.top + head.height) < head.height


def qn_a(tag: str) -> str:
    return "{http://schemas.openxmlformats.org/drawingml/2006/main}" + tag


def _ready(server, pid, gid):
    for _ in range(150):
        g = requests.get(f"{server}/api/projects/{pid}/generations/{gid}", headers=h(), timeout=10).json()
        if g["status"] != "reading":
            return g
        time.sleep(0.2)
    raise AssertionError("not ready")


def test_a_generated_deck_takes_each_slides_design_and_a_design_sent_back_is_checked(server, fake_model, fake_kb):
    pid = requests.post(f"{server}/api/projects", json={"name": "G"}, headers=h(), timeout=10).json()["id"]
    requests.patch(f"{server}/api/projects/{pid}", json={"settings": {"kb_domains": ["produtos"]}}, headers=h(), timeout=10)
    fake_model.artist_answers = [
        {"form": "columns", "columns": [{"heading": "A", "points": ["x"]}, {"heading": "B", "points": ["y"]}]}
    ]
    body = {"kind": "corporate", "source": {"kind": "kb_topic", "query": "garantia"}, "slides": 4}
    gid = requests.post(f"{server}/api/projects/{pid}/generations", json=body, headers=h(), timeout=10).json()["id"]
    g = _ready(server, pid, gid)
    forms = [s["design"]["form"] for s in g["outline"]["slides"]]
    assert forms[0] == "columns" and set(forms[1:]) == {"bullets"}
    asked = fake_model.artist_asked[0][0]["content"]
    assert asked.startswith("The presentation's goal: A corporate presentation")  # the goal, for a relevant form
    slides = g["outline"]["slides"]
    slides[1]["design"] = {"form": "highlight", "highlight": {"statement": "Até 99.999 €"}}  # a figure the slide does not say
    r = requests.put(
        f"{server}/api/projects/{pid}/generations/{gid}/outline", json={"title": "T", "slides": slides}, headers=h(), timeout=10
    )
    assert r.status_code == 200 and r.json()["outline"]["slides"][1]["design"]["form"] == "bullets"
    ideas = requests.post(
        f"{server}/api/projects/{pid}/generations/{gid}/slides/2/ideas", json={"wish": ""}, headers=h(), timeout=30
    ).json()
    assert len({i["form"] for i in ideas["ideas"]}) == len(ideas["ideas"]) >= 2  # each idea another form
    built = requests.post(f"{server}/api/projects/{pid}/generations/{gid}/build", headers=h(), timeout=60).json()
    prs = read.open_deck(deck_bytes(server, pid, built["deck_id"]))
    assert read.outline(prs)[1]["layout"] != read.outline(prs)[2]["layout"]  # the columns slide, then a list


def test_in_the_editor_the_artists_idea_remakes_the_slide_keeping_its_title_and_notes(server, fake_model):
    pid, did, _ = setup(server)
    base = f"{server}/api/projects/{pid}/decks/{did}"
    sid = outline(deck_bytes(server, pid, did))[1]["slide_id"]
    v = requests.get(base, headers=h(), timeout=30).json()["version"]
    notes = {"base_version": v, "op": "tool", "tool": "set_notes", "args": {"slide_id": sid, "text": "Dizer isto."}}
    requests.post(f"{base}/edits", json=notes, headers=h(), timeout=30)
    got = requests.post(f"{base}/slides/{sid}/ideas", json={"wish": ""}, headers=h(), timeout=30).json()
    title = got["slide"]["title"]
    columns = next(i for i in got["ideas"] if i["form"] == "columns")
    v = requests.get(base, headers=h(), timeout=30).json()["version"]
    r = requests.post(f"{base}/edits", json={"base_version": v, "op": "tool", "tool": "redesign_slide",
                                             "args": {"slide_id": sid, "design": columns}}, headers=h(), timeout=60)  # fmt: skip
    assert r.status_code == 200, r.text
    new = r.json()["result"]["slides"][0]
    prs = read.open_deck(deck_bytes(server, pid, did))
    order = [o["slide_id"] for o in read.outline(prs)]
    assert sid not in order and order[1] == new  # at its place
    one = read.slide(prs, new)
    texts = ["".join(r["text"] for r in p["runs"]) for sh in one["shapes"] for p in sh.get("paragraphs") or []]
    assert title in texts and "Primeiro" in texts and one["notes"] == "Dizer isto."
    assert requests.post(f"{base}/undo", headers=h(), timeout=30).status_code == 200
    assert sid in [o["slide_id"] for o in read.outline(read.open_deck(deck_bytes(server, pid, did)))]  # undo brings it back


def test_asked_for_ideas_the_application_asks_the_artist_and_applies_the_one_chosen(server, fake_model):
    """Measured (artist-ideas-in-chat, 3 runs in 3): offered ask_artist, the model wrote ideas of its own and called
    nothing; told "use the first idea", it rewrote the slide with fill_slide. The router reads "ideas" and the number
    chosen; the application makes the calls."""
    pid, did, cid = setup(server)
    from .test_kb import tool_results

    fake_model.routes = [{"intent": "Ideas for slide 3", "where": "3", "kind": "ideas", "groups": []}]
    fake_model.script = [{"text": "Ideias: 1. Lista 2. Colunas 3. Destaque. Qual prefere?"}]
    chat = Chat(server, pid, cid)
    try:
        assert chat.send("dá-me ideias para o diapositivo 3")["status"] == "done"
        ideas = tool_results(fake_model, "ask_artist")
        assert ideas and ideas[0]["ok"] and len(ideas[0]["ideas"]) == 3  # the application asked
        assert fake_model.offered[-1] == []  # the model only says them: no editing tool
        assert deck_bytes(server, pid, did) == deck_bytes(server, pid, did, 1)
        router_saw = [m[0]["content"] for m in fake_model.sent if m and "The person's request" in m[0]["content"]]
        fake_model.routes = [{"intent": "The second idea", "kind": "change", "groups": ["structure"], "idea": 2}]
        fake_model.script = [{"text": "Usei a segunda ideia no diapositivo 3."}]
        chat.send("usa a segunda")
        assert (
            "The Artist's last ideas in this conversation, for slide 3:"
            in [m[0]["content"] for m in fake_model.sent if m and "The person's request" in m[0]["content"]][-1]
        )
        made = tool_results(fake_model, "redesign_slide")
        assert made and made[-1].get("ok"), made
        chat.decide(chat.last("proposal_updated")["id"], True)
    finally:
        chat.close()
    assert router_saw  # the first request was routed
    third = read.slide(read.open_deck(deck_bytes(server, pid, did)), outline(deck_bytes(server, pid, did))[2]["slide_id"])
    texts = ["".join(r["text"] for r in p["runs"]) for sh in third["shapes"] for p in sh.get("paragraphs") or []]
    assert "Primeiro" in texts and "Segundo" in texts  # the columns idea


def test_in_the_chat_the_artists_ideas_are_told_and_the_one_chosen_is_applied(server, fake_model):
    pid, did, cid = setup(server)
    from .test_kb import tool_results

    fake_model.routes = [{"intent": "Ideas", "kind": "change", "groups": ["structure"]},
                         {"intent": "The second idea", "kind": "change", "groups": ["structure"]}]  # fmt: skip
    fake_model.script = [{"tools": [("ask_artist", {"slide_id": 2})]}, {"text": "1. Lista 2. Colunas 3. Destaque"}]
    chat = Chat(server, pid, cid)
    try:
        chat.send("dá-me ideias para o diapositivo 2")
        ideas = tool_results(fake_model, "ask_artist")[0]
        assert ideas["ok"] and len(ideas["ideas"]) == 3 and ideas["ideas"][1].startswith("2. columns")
        assert deck_bytes(server, pid, did) == deck_bytes(server, pid, did, 1)  # nothing changed
        fake_model.script = [{"tools": [("redesign_slide", {"slide_id": 2, "idea": 2})]}, {"text": "Refiz o diapositivo 2."}]
        chat.send("a segunda")
        made = tool_results(fake_model, "redesign_slide")[-1]
        assert made.get("ok"), made
        chat.decide(chat.last("proposal_updated")["id"], True)
        fake_model.script = [{"tools": [("redesign_slide", {"slide_id": 1, "idea": 3})]}, {"text": "?"}]
        chat.send("usa a terceira no primeiro")
        assert tool_results(fake_model, "redesign_slide")[-1]["error"]["code"] == "NO_SUCH_IDEA"  # ideas were for slide 2
    finally:
        chat.close()
    second = read.slide(read.open_deck(deck_bytes(server, pid, did)), outline(deck_bytes(server, pid, did))[1]["slide_id"])
    texts = ["".join(r["text"] for r in p["runs"]) for sh in second["shapes"] for p in sh.get("paragraphs") or []]
    assert "Primeiro" in texts and "Segundo" in texts  # the columns idea


def test_a_highlight_never_goes_on_a_layout_whose_heading_cannot_be_read():
    """Looked at (the editor's Ideas, a highlight chosen): on "2_Capa S/Imagem" (48 pt, white on the white page) the
    remade slide was blank."""
    from app.docengine import layouts

    ctt = read.open_deck((REPO / "templates" / "bancoctt.pptx").read_bytes())
    lay = ops._form_layout(ctt, "highlight")
    assert lay.name == "1_Highlight" and layouts.readable(lay, ctt.slide_width, ctt.slide_height)


def test_ideas_asked_for_no_slide_in_particular_are_asked_about_in_the_panel(server, fake_model):
    """Measured (squad-11): "Melhora isto." with nothing selected, read as ideas: the model asked in its reply's words,
    which is no question the person answers in the panel. Unclear: only ask_user offered."""
    pid, _, cid = setup(server)
    fake_model.routes = [{"intent": "Improve it", "kind": "ideas", "groups": []}]
    fake_model.script = [{"tools": [("ask_user", {"question": "Que diapositivo quer melhorar?"})]}]
    chat = Chat(server, pid, cid)
    try:
        assert chat.send("Melhora isto.")["status"] == "waiting"
    finally:
        chat.close()
    assert fake_model.offered[-1] == ["ask_user"] and not getattr(fake_model, "artist_asked", [])


def test_a_long_divider_title_stays_above_its_subtitle_and_a_rows_figures_share_one_size():
    """Looked at: a divider layout's title box reaches into its subtitle's, and a four-line title ran into the subtitle;
    "450 000 €" was fitted smaller than the figures beside it, and sat higher."""
    from app.docengine import textfit

    ctt = read.open_deck((REPO / "templates" / "bancoctt.pptx").read_bytes())
    ops.add_outline(ctt, [{"role": "section", "title": "O Processo de Concessão do Crédito Habitação",
                           "points": ["Vai conhecer as sete fases do processo e quem intervém em cada uma."]}])  # fmt: skip
    divider = ctt.slides[0]
    texts = sorted((ph for ph in divider.placeholders if ph.text_frame.text.strip()), key=lambda ph: ph.top)
    title, subtitle = texts[0], texts[-1]
    assert title.top + textfit.measure(title)["bottom"] * textfit.EMU_PT <= subtitle.top
    figures = {"form": "figures", "figures": [{"value": "35", "label": "anos"}, {"value": "450 000 €", "label": "valor máximo"},
                                              {"value": "100%", "label": "financiamento"}]}  # fmt: skip
    s = ctt.slides.get(ops.add_designed(ctt, {"title": "Limites", "design": figures})[0])
    numbers = [ph for ph in s.placeholders if ph.text_frame.text in ("35", "450 000 €", "100%")]
    assert len(numbers) == 3 and len({textfit.measure(ph)["font_scale"] for ph in numbers}) == 1
