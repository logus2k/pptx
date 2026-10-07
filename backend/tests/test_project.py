"""M6 through the real server and the scripted model: spec scenarios S8 (a new deck from slides of another one) and
S9 (decisions recalled days later, from the project's memory and its conversations), the memory's page routes,
reference documents and their search."""

from __future__ import annotations

import io
import json
import zipfile

import requests

from .test_agent import ANA, DECKS, Chat, deck_bytes, h, outline
from .test_kb import tool_results


def project(server, name="Client X proposal") -> str:
    return requests.post(f"{server}/api/projects", json={"name": name}, headers=h(), timeout=10).json()["id"]


def upload(server, pid, path, name) -> str:
    with open(path, "rb") as f:
        return requests.post(f"{server}/api/projects/{pid}/decks", files={"file": (name, f)}, headers=h(), timeout=60).json()[
            "id"
        ]


def conversation(server, pid, did=None) -> str:
    return requests.post(f"{server}/api/projects/{pid}/conversations", json={"deck_id": did}, headers=h(), timeout=10).json()[
        "id"
    ]


def test_s8_a_new_deck_from_the_case_study_slides_of_another(server, fake_model):
    """S8: two decks uploaded; "build a new proposal deck reusing the case-study slides from the capabilities deck":
    a third deck is made, the slides are copied onto its template after the person approves, the source untouched."""
    pid = project(server)
    upload(server, pid, DECKS / "simple.pptx", "proposta 2025.pptx")
    capabilities = upload(server, pid, DECKS / "features.pptx", "capacidades.pptx")
    cid = conversation(server, pid)
    fake_model.script = [
        {"tools": [["create_deck", {"title": "Proposta 2026"}]]},
        {"tools": [["copy_slides", {"from_deck_id": capabilities, "slide_ids": [1, 2]}]]},
    ]
    chat = Chat(server, pid, cid)
    try:
        assert (
            chat.send("build a new proposal deck reusing the case-study slides from the capabilities deck")["status"] == "waiting"
        )
        plan = chat.last("plan")
        assert plan["steps"] == ["Copiar os diapositivos 1, 2 de «capacidades» para «Proposta 2026»"]  # the app's plan (NL-8)
        fake_model.script = [{"text": "Criei a **Proposta 2026** com os dois casos de estudo."}]
        assert chat.answer(approve=True)["status"] == "done"
        proposal = chat.last("proposal_updated")
        new = next(
            d
            for d in requests.get(f"{server}/api/projects/{pid}/decks", headers=h(), timeout=10).json()["decks"]
            if d["title"] == "Proposta 2026"
        )
        assert [s["state"] for s in proposal["decks"][new["id"]]["slides"]] == ["added", "added"]
        chat.decide(proposal["id"], True)
    finally:
        chat.close()
    titles = [o["title"] for o in outline(deck_bytes(server, pid, new["id"]))]
    assert titles == ["Preços por escalão", "Fotografia da linha de triagem"]
    assert len(outline(deck_bytes(server, pid, capabilities))) == 4  # copied, not moved


def test_a_move_takes_the_slides_out_of_the_source_deck(server, fake_model):
    pid = project(server, "Move")
    target = upload(server, pid, DECKS / "simple.pptx", "a.pptx")
    source = upload(server, pid, DECKS / "features.pptx", "b.pptx")
    cid = conversation(server, pid, target)
    fake_model.script = [{"tools": [["copy_slides", {"from_deck_id": source, "slide_ids": [4], "move": True}]]}]
    chat = Chat(server, pid, cid)
    try:
        assert chat.send("move the hidden slide of b here")["status"] == "waiting"
        assert chat.last("plan")["steps"][0].startswith("Mover os diapositivos 4 de «b»")
        fake_model.script = [{"text": "Movido."}]
        chat.answer(approve=True)
        proposal = chat.last("proposal_updated")
        assert set(proposal["decks"]) == {target, source}  # one proposal, both decks
        chat.decide(proposal["id"], True)
    finally:
        chat.close()
    assert [o["title"] for o in outline(deck_bytes(server, pid, target))][-1] == "Diapositivo oculto"
    assert len(outline(deck_bytes(server, pid, source))) == 3


def test_s9_decisions_are_kept_and_recalled_in_a_later_conversation(server, fake_model, fake_reranker):
    """S9: decisions stated in one conversation ("prices in EUR, no discounts shown") are kept, announced, in the
    project's memory; days later, in a new conversation, they are in the model's context and the earlier discussion
    is found by search_conversations, cited by its conversation and date."""
    pid = project(server)
    did = upload(server, pid, DECKS / "simple.pptx", "proposta.pptx")
    first = conversation(server, pid, did)
    fake_model.script = [
        {"tools": [["remember", {"text": "Preços sempre em EUR, sem descontos visíveis."}]]},
        {"text": "Combinado: vou lembrar-me de que os preços são em EUR e sem descontos."},
    ]
    chat = Chat(server, pid, first)
    try:
        chat.send("na secção de preços: tudo em euros e não mostramos descontos ao cliente")
    finally:
        chat.close()
    items = requests.get(f"{server}/api/projects/{pid}/memory", headers=h(), timeout=10).json()["items"]
    assert [(m["text"], m["conversation_id"], m["author"]) for m in items] == [
        ("Preços sempre em EUR, sem descontos visíveis.", first, ANA)
    ]
    later = conversation(server, pid, did)
    fake_model.script = [
        {"tools": [["search_conversations", {"query": "secção de preços euros descontos"}]]},
        {"text": "Continuo."},
    ]
    chat = Chat(server, pid, later)
    try:
        chat.send("continua com a secção de preços que discutimos")
    finally:
        chat.close()
    context = fake_model.sent[-1][0]["content"]
    assert "Project memory" in context and "Preços sempre em EUR, sem descontos visíveis." in context
    found = tool_results(fake_model, "search_conversations")[-1]["passages"]
    assert found[0]["conversation_id"] == first and found[0]["date"] and "euros" in found[0]["text"]
    assert found[0]["text"].startswith("<data>")
    assert fake_reranker.calls and fake_reranker.calls[-1][0] == "secção de preços euros descontos"


def test_people_see_edit_and_delete_the_memory(server):
    pid = project(server, "Memory")
    item = requests.post(
        f"{server}/api/projects/{pid}/memory", json={"text": "  O cliente prefere  menos marcadores. "}, headers=h(), timeout=10
    ).json()
    assert item["text"] == "O cliente prefere menos marcadores." and item["conversation_id"] is None
    again = requests.post(
        f"{server}/api/projects/{pid}/memory", json={"text": "o cliente prefere menos marcadores."}, headers=h(), timeout=10
    ).json()
    assert again["id"] == item["id"]  # kept once
    r = requests.patch(
        f"{server}/api/projects/{pid}/memory/{item['id']}", json={"text": "Máximo de 4 marcadores."}, headers=h(), timeout=10
    )
    assert r.json()["text"] == "Máximo de 4 marcadores."
    assert requests.delete(f"{server}/api/projects/{pid}/memory/{item['id']}", headers=h(), timeout=10).status_code == 204
    assert requests.get(f"{server}/api/projects/{pid}/memory", headers=h(), timeout=10).json()["items"] == []
    other = "rui@example.com"
    assert requests.get(f"{server}/api/projects/{pid}/memory", headers=h(other), timeout=10).status_code == 404  # not theirs


def _docx(paragraphs: list[tuple[str, str]]) -> bytes:
    """A minimal Word file: (style, text) paragraphs."""
    body = "".join(
        f"<w:p>{f"<w:pPr><w:pStyle w:val='{style}'/></w:pPr>" if style else ''}<w:r><w:t>{text}</w:t></w:r></w:p>"
        for style, text in paragraphs
    )
    xml = f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        z.writestr("word/document.xml", xml)
    return out.getvalue()


def test_reference_documents_are_searched_and_cited(server, fake_model):
    pid = project(server, "Docs")
    cid = conversation(server, pid)
    word = _docx(
        [
            ("Heading1", "Preçário 2026"),
            ("", "A conta base custa 4 euros por mês."),
            ("Ttulo1", "Garantias"),
            ("", "Dois anos de garantia."),
        ]
    )
    r = requests.post(
        f"{server}/api/projects/{pid}/assets",
        data={"kind": "document"},
        files={"file": ("precos.docx", word)},
        headers=h(),
        timeout=30,
    )
    assert r.status_code == 201 and r.json()["passages"] == 2, r.text
    r = requests.post(
        f"{server}/api/projects/{pid}/assets",
        data={"kind": "document"},
        files={"file": ("x.bin", b"\x00\x01\x02")},
        headers=h(),
        timeout=30,
    )
    assert r.status_code == 422 and "not text" in r.text  # refused like any unusable upload
    fake_model.script = [{"tools": [["search_project", {"query": "quanto custa a conta base por mês"}]]}, {"text": "4 euros."}]
    chat = Chat(server, pid, cid)
    try:
        chat.send("quanto custa a conta base?")
    finally:
        chat.close()
    best = tool_results(fake_model, "search_project")[-1]["passages"][0]
    assert (best["document"], best["where"]) == ("precos.docx", "Preçário 2026") and "4 euros" in best["text"]
    assets = json.dumps(fake_model.sent[-1][0]["content"])
    assert "precos.docx" in assets  # the context names the project's documents


def test_changing_a_decks_template_waits_for_approval_and_records_the_template(server, fake_model):
    """PM-10: the deck put on a template the person uploaded: a plan first (every slide changes), then a proposal of
    the same slides; accepted, the deck is on the new template and says so."""
    from pptx import Presentation

    pid = project(server, "Template")
    did = upload(server, pid, DECKS / "simple.pptx", "proposta.pptx")
    buf = io.BytesIO()
    Presentation().save(buf)
    asset = requests.post(
        f"{server}/api/projects/{pid}/assets",
        data={"kind": "template"},
        files={"file": ("office.pptx", buf.getvalue())},
        headers=h(),
        timeout=30,
    ).json()
    cid = conversation(server, pid, did)
    fake_model.script = [{"tools": [["change_template", {"template": {"kind": "asset", "id": asset["id"]}}]]}]
    chat = Chat(server, pid, cid)
    try:
        assert chat.send("põe esta apresentação no modelo office")["status"] == "waiting"
        assert chat.last("plan")["steps"] == ["Mudar o modelo da apresentação para «office.pptx»"]
        fake_model.script = [{"text": "Mudei o modelo."}]
        chat.answer(approve=True)
        proposal = chat.last("proposal_updated")
        assert [s["state"] for s in proposal["decks"][did]["slides"]] == ["changed", "changed", "changed"]
        chat.decide(proposal["id"], True)
    finally:
        chat.close()
    deck = requests.get(f"{server}/api/projects/{pid}/decks/{did}", headers=h(), timeout=10).json()
    assert deck["deck"]["template"] == {"kind": "asset", "id": asset["id"]}
    from app.docengine import read

    prs = read.open_deck(deck_bytes(server, pid, did))
    assert prs.slide_width == 9144000 and [o["title"] for o in read.outline(prs)] == [
        "Proposta para o Cliente X",
        "Agenda",
        "Antes e depois",
    ]


def test_changes_in_review_are_accepted_or_rejected_in_words(server, fake_model):
    """Spec VO-6: "apply only slide 2" does what the review's buttons do: slide 2 saved, slide 3 left as it was;
    the context told the model what was waiting."""
    from .test_agent import body_id

    pid = project(server, "Words")
    did = upload(server, pid, DECKS / "simple.pptx", "proposta.pptx")
    cid = conversation(server, pid, did)
    data = deck_bytes(server, pid, did)
    s2, s3 = (o["slide_id"] for o in outline(data)[1:3])
    fake_model.script = [
        {"tools": [["update_text", {"slide_id": s2, "shape_id": body_id(data, s2), "paragraphs": [{"text": "Curto"}]}]]},
        {"tools": [["update_text", {"slide_id": s3, "shape_id": body_id(data, s3), "paragraphs": [{"text": "Também curto"}]}]]},
        {"text": "Encurtei os diapositivos 2 e 3."},
    ]
    chat = Chat(server, pid, cid)
    try:
        chat.send("encurta os diapositivos 2 e 3")
        assert chat.last("proposal_updated")["status"] == "pending"
        fake_model.script = [
            {"tools": [["decide_changes", {"decision": "accept_only", "slides": [2]}]]},
            {"text": "Apliquei só o 2."},
        ]
        chat.send("aplica só o diapositivo 2")
        assert "Changes waiting for the person's decision" in fake_model.sent[-2][0]["content"]
    finally:
        chat.close()
    after = deck_bytes(server, pid, did)
    from app.docengine import read

    def text(sid):
        return " / ".join(
            "".join(r["text"] for r in p["runs"])
            for p in next(s for s in read.slide(read.open_deck(after), sid)["shapes"] if s["shape_id"] == body_id(data, sid))[
                "paragraphs"
            ]
        )

    assert text(s2) == "Curto" and text(s3).startswith("Processos manuais")
    assert chat.last("proposal_updated")["status"] == "partially_accepted"


def test_what_a_picture_shows_is_found_by_the_model(server, fake_model):
    """Spec IM-4: after a deck is uploaded, its pictures are described once in the background; the deck map then says
    what each one shows, so "the slide with the photo of..." can be found."""
    import time

    fake_model._vision = True
    pid = project(server, "Pictures")
    did = upload(server, pid, DECKS / "features.pptx", "f.pptx")
    for _ in range(50):  # the describer works after the upload, in the background
        found = requests.get(f"{server}/api/projects/{pid}/decks/{did}", headers=h(), timeout=10)
        sent = [m for m in fake_model.sent if m[0]["content"] and isinstance(m[0]["content"], list)]
        if sent:
            break
        time.sleep(0.1)
    assert sent, "the picture was not described"
    time.sleep(0.3)
    cid = conversation(server, pid, did)
    fake_model.script = [{"text": "É o diapositivo 2."}]
    chat = Chat(server, pid, cid)
    try:
        chat.send("qual é o diapositivo com a fotografia?")
    finally:
        chat.close()
    context = next(m for m in reversed(fake_model.sent) if isinstance(m[0]["content"], str))[0]["content"]
    assert "(picture): alt text: image.png; it shows: Uma fotografia de teste." in context
    assert found.status_code == 200
