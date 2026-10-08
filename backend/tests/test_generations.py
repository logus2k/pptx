"""Decks generated from a source (spec NL-12; domain/generations.py, agent/outline.py) through the real server and the
scripted model: a corporate presentation from what the knowledge base holds on a topic, a training from a project's
document, the outline edited before the slides are made, the slides' layouts and notes, and the refusals."""

from __future__ import annotations

import time

import requests

from app.docengine import read

from .test_agent import ANA, deck_bytes, h


def _project(server, kb=True) -> str:
    pid = requests.post(f"{server}/api/projects", json={"name": "Gerar"}, headers=h(), timeout=10).json()["id"]
    if kb:
        requests.patch(f"{server}/api/projects/{pid}", json={"settings": {"kb_domains": ["produtos"]}}, headers=h(), timeout=10)
    return pid


def _ready(server, pid, gid, timeout=30) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        g = requests.get(f"{server}/api/projects/{pid}/generations/{gid}", headers=h(), timeout=10).json()
        if g["status"] != "reading":
            return g
        time.sleep(0.2)
    raise AssertionError("the generation did not finish")


def test_a_corporate_deck_from_a_knowledge_base_topic_with_its_sources_in_the_notes(server, fake_model, fake_kb):
    pid = _project(server)
    body = {"kind": "corporate", "source": {"kind": "kb_topic", "query": "garantia"}, "slides": 5, "audience": "clientes"}
    r = requests.post(f"{server}/api/projects/{pid}/generations", json=body, headers=h(), timeout=10)
    assert r.status_code == 201, r.text
    g = _ready(server, pid, r.json()["id"])
    assert g["status"] == "ready", g
    assert [s["role"] for s in g["outline"]["slides"]] == ["content"] * 5
    # the whole document the topic's passages come from was read (outline.py: TOPIC_DOCUMENTS), each part asked once
    asked = [m[0]["content"] for m in fake_model.sent if m and "Part 1 of" in m[0]["content"]]
    assert asked and "Ficam excluídos danos" in asked[0]
    plan = next(m[0]["content"] for m in fake_model.sent if m and m[0]["content"].startswith("Make 5 slides"))
    assert "A corporate presentation for clientes" in plan and "European Portuguese" in plan
    built = requests.post(f"{server}/api/projects/{pid}/generations/{g['id']}/build", headers=h(), timeout=60)
    assert built.status_code == 200, built.text
    g = built.json()
    assert g["status"] == "built" and len(g["slide_ids"]) == 6  # the cover and five
    prs = read.open_deck(deck_bytes(server, pid, g["deck_id"]))
    cover = read.slide(prs, g["slide_ids"][0])
    texts = [p["runs"][0]["text"] for sh in cover["shapes"] for p in sh.get("paragraphs") or [] if p.get("runs")]
    assert "Apresentação gerada" in texts and "clientes" in texts
    second = read.slide(prs, g["slide_ids"][1])
    assert "Fonte: Política de garantia 2026" in second["notes"] and "https://" in second["notes"]
    again = requests.post(f"{server}/api/projects/{pid}/generations/{g['id']}/build", headers=h(), timeout=10)
    assert again.status_code == 400  # made once


def test_a_training_from_a_project_document_into_an_existing_deck_after_its_outline_is_edited(server, fake_model):
    pid = _project(server, kb=False)
    manual = "\n\n".join(
        f"## Passo {n}\n\nO colaborador confirma o documento de identificação do cliente e regista o passo {n} no sistema."
        for n in range(1, 9)
    ).encode()
    asset = requests.post(f"{server}/api/projects/{pid}/assets", data={"kind": "document"}, files={"file": ("manual.md", manual)},
                          headers=h(), timeout=30).json()  # fmt: skip
    assert asset.get("kind") == "document", asset
    tpl = {"title": "Formação", "template": {"kind": "admin", "id": "default"}}
    did = requests.post(f"{server}/api/projects/{pid}/decks", json=tpl, headers=h(), timeout=60).json()["id"]
    body = {"kind": "training", "source": {"kind": "document", "asset_id": asset["id"]}, "slides": 9,
            "target": {"kind": "deck", "deck_id": did}}  # fmt: skip
    gid = requests.post(f"{server}/api/projects/{pid}/generations", json=body, headers=h(), timeout=10).json()["id"]
    g = _ready(server, pid, gid)
    roles = [s["role"] for s in g["outline"]["slides"]]
    assert roles[0] == "objectives" and "section" in roles and roles[-2:] == ["questions", "summary"]
    plan = next(m[0]["content"] for m in fake_model.sent if m and m[0]["content"].startswith("Make 9 slides"))
    assert "A training that a trainer will deliver" in plan
    # the person edits the outline: a title changed, a slide removed
    slides = g["outline"]["slides"]
    slides[2]["title"] = "Como abrir uma conta"
    del slides[3]
    edit = {"title": "Formação de balcão", "slides": slides}
    r = requests.put(f"{server}/api/projects/{pid}/generations/{gid}/outline", json=edit, headers=h(), timeout=10)
    assert r.status_code == 200, r.text
    g = requests.post(f"{server}/api/projects/{pid}/generations/{gid}/build", headers=h(), timeout=60).json()
    prs = read.open_deck(deck_bytes(server, pid, did))
    assert len(prs.slides) >= len(slides) + 1 and g["deck_id"] == did  # into the deck: a cover (it was empty), then each
    titles = [o["title"] for o in read.outline(prs)]
    assert titles[0] == "Formação de balcão" and "Como abrir uma conta" in titles
    trainer = read.slide(prs, g["slide_ids"][2])
    assert "O formador explica" in trainer["notes"]
    versions = requests.get(f"{server}/api/projects/{pid}/decks/{did}/versions", headers=h(), timeout=10).json()
    newest = max(versions["versions"], key=lambda v: v["number"])
    assert newest["source"] == "generated"  # one new version: undo takes it back


def test_what_cannot_be_generated_is_refused_and_said(server, fake_model):
    pid = _project(server, kb=False)
    post = lambda body: requests.post(f"{server}/api/projects/{pid}/generations", json=body, headers=h(), timeout=10)  # noqa: E731
    assert post({"kind": "corporate", "source": {"kind": "kb_topic", "query": ""}}).status_code == 400
    assert post({"kind": "corporate", "source": {"kind": "document", "asset_id": "0123456789abcdef"}}).status_code == 404
    assert post({"kind": "poster", "source": {"kind": "kb_topic", "query": "x"}}).status_code == 422
    viewer = "rui@example.com"
    requests.put(f"{server}/api/projects/{pid}/members", json={"email": viewer, "role": "viewer"}, headers=h(), timeout=10)
    r = requests.post(f"{server}/api/projects/{pid}/generations", json={"source": {"kind": "kb_topic", "query": "garantia"}},
                      headers=h(viewer), timeout=10)  # fmt: skip
    assert r.status_code == 404  # a viewer makes nothing (as the other writes: not found for that role)
    other = requests.get(f"{server}/api/projects/{pid}/generations/0123456789abcdef", headers=h(), timeout=10)
    assert other.status_code == 404


def test_a_generation_is_a_draft_left_out_of_the_projects_archive(server, fake_model, fake_kb):
    import io
    import zipfile

    pid = _project(server)
    gid = requests.post(f"{server}/api/projects/{pid}/generations", json={"source": {"kind": "kb_topic", "query": "garantia"}},
                        headers=h(), timeout=10).json()["id"]  # fmt: skip
    _ready(server, pid, gid)
    data = requests.get(f"{server}/api/projects/{pid}/export", headers=h(), timeout=30).content
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert not [n for n in names if "generations/" in n]
    r = requests.post(f"{server}/api/projects/import", files={"file": ("p.zip", data)}, headers=h(ANA), timeout=60)
    assert r.status_code == 201, r.text


def test_asked_in_the_chat_the_outline_is_the_plan_and_approved_the_deck_is_made(server, fake_model, fake_kb):
    """The assistant's path (both paths: the user's rule): one generate_deck call; the reading's progress in the panel;
    the outline as the plan; approved, the application makes the deck, which becomes the open one."""
    from .test_agent import Chat

    pid = _project(server)
    cid = requests.post(f"{server}/api/projects/{pid}/conversations", json={}, headers=h(), timeout=10).json()["id"]
    fake_model.routes = [{"intent": "A training on the warranty", "kind": "change", "groups": ["decks", "knowledge"]}]
    call = {"kind": "training", "source": {"kind": "kb_topic", "query": "garantia"}, "slides": 8, "language": "pt"}
    fake_model.script = [{"tools": [("generate_deck", call)]}]
    chat = Chat(server, pid, cid)
    try:
        assert chat.send("Cria uma formação sobre a garantia a partir da base de conhecimento")["status"] == "waiting"
        details = [d.get("detail") for n, d in chat.events if n == "tool_progress" and d.get("tool") == "generate_deck"]
        assert "Reading part 1 of 1" in details and "Planning the slides" in details
        plan = chat.last("plan")
        record = requests.get(f"{server}/api/projects/{pid}/generations/{plan['generation_id']}", headers=h(), timeout=10).json()
        assert plan["steps"] == ["Capa: «Apresentação gerada»"] + [x["title"] for x in record["outline"]["slides"]]
        fake_model.script = [{"text": "Fiz a formação."}]
        assert chat.answer(approve=True)["status"] == "done"
    finally:
        chat.close()
    g = requests.get(f"{server}/api/projects/{pid}/generations/{plan['generation_id']}", headers=h(), timeout=10).json()
    assert g["status"] == "built"
    conv = requests.get(f"{server}/api/projects/{pid}/conversations/{cid}", headers=h(), timeout=10).json()
    assert (conv.get("conversation") or conv)["active_deck"] == g["deck_id"]
    prs = read.open_deck(deck_bytes(server, pid, g["deck_id"]))
    assert len(prs.slides) == len(plan["steps"]) and read.outline(prs)[1]["title"] == "Diapositivo 1"
    assert read.outline(prs)[0]["layout"] == "Title Slide"  # the cover's layout, its title alone (no audience given)


def test_a_source_that_cannot_be_read_is_said_to_the_model(server, fake_model):
    from .test_agent import Chat

    pid = _project(server, kb=False)
    cid = requests.post(f"{server}/api/projects/{pid}/conversations", json={}, headers=h(), timeout=10).json()["id"]
    fake_model.routes = [{"intent": "A deck from a document", "kind": "change", "groups": ["decks"]}]
    call = {"kind": "corporate", "source": {"kind": "document", "asset_id": "0123456789abcdef"}}
    fake_model.script = [{"tools": [("generate_deck", call)]}, {"text": "Esse documento não existe no projeto."}]
    chat = Chat(server, pid, cid)
    try:
        chat.send("Faz uma apresentação a partir do manual")
    finally:
        chat.close()
    from .test_kb import tool_results

    assert tool_results(fake_model, "generate_deck")[-1]["error"]["code"] == "NOT_FOUND"
