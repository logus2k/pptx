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


def test_a_picture_is_generated_into_the_project_only_when_a_service_is_configured(tmp_path):
    """Spec IM-6, against a stand-in for tti_server's API (generate, events, image): the client reads the events to
    "done" and fetches the PNG; a "failed" event is an error with the service's words; none configured: unavailable."""
    import io as io_
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from PIL import Image

    from app.imagegen import ImageGenerator, ImageGenError

    png = io_.BytesIO()
    Image.new("RGB", (64, 36), (10, 120, 200)).save(png, "PNG")
    seen = {}

    class Tti(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"id": "fail" if "fail" in seen["body"]["prompt"] else "j1"}).encode()
            self.send_response(200), self.send_header("Content-Type", "application/json"), self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            if self.path.startswith("/api/stream/"):
                self.send_response(200), self.send_header("Content-Type", "text/event-stream"), self.end_headers()
                if self.path.endswith("fail"):
                    self.wfile.write(b'event: failed\ndata: {"message": "out of memory"}\n\n')
                else:
                    done = b'event: done\ndata: {"image_url": "api/image/j1"}\n\n'
                    self.wfile.write(b'event: progress\ndata: {"pct": 50}\n\n' + done)
            else:
                self.send_response(200), self.send_header("Content-Type", "image/png"), self.end_headers()
                self.wfile.write(png.getvalue())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Tti)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        gen = ImageGenerator(f"http://127.0.0.1:{server.server_port}/")
        assert gen.available and gen.generate("a lighthouse at dawn", "wide") == png.getvalue()
        assert (seen["body"]["width"], seen["body"]["height"]) == (1344, 768)
        try:
            gen.generate("please fail")
            raise AssertionError("a failed generation must raise")
        except ImageGenError as e:
            assert "out of memory" in str(e)
    finally:
        server.shutdown()
    assert not ImageGenerator(None).available


def test_generate_image_is_offered_only_when_configured_and_makes_an_image_asset(server, fake_model, fake_imagegen):
    from .test_agent import setup

    pid, _, cid = setup(server)
    fake_model.script = [{"tools": [["generate_image", {"prompt": "a lighthouse at dawn"}]]}, {"text": "Feito."}]
    chat = Chat(server, pid, cid)
    try:
        chat.send("faz uma imagem de um farol")
        assert "generate_image" not in fake_model.offered[-1]  # no service configured: not offered
        assert tool_results(fake_model, "generate_image")[-1]["error"]["code"] == "IMAGE_GENERATION_FAILED"  # called anyway
        fake_imagegen.available = True
        fake_model.script = [{"tools": [["generate_image", {"prompt": "a lighthouse at dawn", "shape": "square"}]]},
                             {"text": "Feito."}]  # fmt: skip
        chat.send("faz uma imagem de um farol")
    finally:
        chat.close()
    assert "generate_image" in fake_model.offered[-1] and fake_imagegen.prompts == [("a lighthouse at dawn", "square")]
    made = tool_results(fake_model, "generate_image")[-1]
    assets = requests.get(f"{server}/api/projects/{pid}/assets", headers=h(), timeout=10).json()["assets"]
    assert any(a["id"] == made["asset_id"] and a["kind"] == "image" for a in assets)


def test_a_project_exported_and_imported_loses_nothing_and_its_archive_is_not_trusted(server, fake_model, tmp_path):
    """Spec PJ-14 and M8's "done when": a project's archive imported as a new project is the same project (every deck
    version, conversation, memory item, instruction, asset and passage); an archive is the person's file: its members
    are not given access, and a path or a deck a project cannot have is refused."""
    import zipfile

    pid = project(server, "Arquivo")
    did = upload(server, pid, DECKS / "simple.pptx", "proposta.pptx")
    cid = conversation(server, pid, did)
    requests.patch(f"{server}/api/projects/{pid}", json={"instructions": "Preços em EUR."}, headers=h(), timeout=10)
    memory_item = {"text": "O cliente prefere gráficos simples."}
    requests.post(f"{server}/api/projects/{pid}/memory", json=memory_item, headers=h(), timeout=10)
    doc = _docx([("Heading1", "Preços"), ("", "A conta custa 4 euros.")])
    assets = f"{server}/api/projects/{pid}/assets"
    requests.post(assets, data={"kind": "document"}, files={"file": ("precos.docx", doc)}, headers=h(), timeout=30)
    png = io.BytesIO()
    __import__("PIL.Image", fromlist=["Image"]).new("RGB", (40, 30), (1, 2, 3)).save(png, "PNG")
    requests.post(assets, data={"kind": "image"}, files={"file": ("foto.png", png.getvalue())}, headers=h(), timeout=30)
    data = deck_bytes(server, pid, did)
    first = outline(data)[0]["slide_id"]
    requests.post(f"{server}/api/projects/{pid}/decks/{did}/edits",
                  json={"base_version": 1, "op": "move", "slide_id": first, "position": 1}, headers=h(), timeout=60)  # fmt: skip
    fake_model.script = [{"text": "Olá."}, {"text": "Olá."}]
    chat = Chat(server, pid, cid)
    chat.send("olá")
    chat.close()
    eva = {"email": "eva@example.com", "role": "editor"}
    requests.put(f"{server}/api/projects/{pid}/members", json=eva, headers=h(), timeout=10)

    exported = requests.get(f"{server}/api/projects/{pid}/export", headers=h(), timeout=60)
    assert exported.status_code == 200 and exported.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as z:
        names = z.namelist()
        assert "readable/decks/proposta.pptx" in names and "readable/instructions.json" in names
        assert any(n.startswith("readable/conversations/") and n.endswith(".md") for n in names)
        assert not any("/renders/" in n for n in names)
    bob = "bob@example.com"
    made = requests.post(f"{server}/api/projects/import", files={"file": ("a.zip", exported.content)}, headers=h(bob), timeout=60)
    assert made.status_code == 201, made.text
    new = made.json()["id"]
    assert new != pid
    imported = requests.get(f"{server}/api/projects/{new}", headers=h(bob), timeout=10).json()
    assert imported["members"] == [{"email": bob, "role": "owner"}] and imported["instructions"] == "Preços em EUR."
    assert requests.get(f"{server}/api/projects/{new}", headers=h("eva@example.com"), timeout=10).status_code == 404
    mine = requests.get(f"{server}/api/projects/{new}/decks/{did}/download", headers=h(bob), timeout=30).content
    assert mine == deck_bytes(server, pid, did)  # the current version, byte for byte
    again = requests.get(f"{server}/api/projects/{new}/export", headers=h(bob), timeout=60).content

    def contents(raw):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            out = {n: z.read(n) for n in z.namelist() if n.startswith("data/") and n != "data/project.json"}
            project_ = json.loads(z.read("data/project.json"))
        for k in ("id", "owner", "members", "created_at", "updated_at"):
            project_.pop(k)
        return out, project_

    first_data, first_project = contents(exported.content)
    second_data, second_project = contents(again)
    assert first_data == second_data and first_project == second_project  # nothing lost, nothing changed
    assert any(n.startswith("data/decks/") and n.endswith("/versions/2.pptx") for n in first_data)  # every version

    def tampered(rel, payload):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(exported.content)) as z, zipfile.ZipFile(out, "w") as w:
            for n in z.namelist():
                w.writestr(n, payload if n == rel else z.read(n))
            if rel not in z.namelist():
                w.writestr(rel, payload)
        sent = {"file": ("a.zip", out.getvalue())}
        return requests.post(f"{server}/api/projects/import", files=sent, headers=h(bob), timeout=60)

    bad = tampered("data/../../evil.txt", b"x")
    assert bad.status_code == 422 and "does not have" in bad.json()["detail"]["message"]
    version = next(n for n in first_data if n.endswith("/versions/1.pptx"))
    assert tampered(version, b"not a deck").status_code == 422
    garbage = requests.post(f"{server}/api/projects/import", files={"file": ("a.zip", b"PK nope")}, headers=h(bob), timeout=10)
    assert garbage.status_code == 422
