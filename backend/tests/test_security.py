"""Security review findings (2026-10-07), each reproduced through the real server before it was fixed: L1 a
proposal reached through another project's folder, L2 a turn cancelled by someone outside its project, L7 a plan
answered by a viewer."""

from __future__ import annotations

import requests
import socketio

from .test_agent import ANA, DECKS, Chat, body_id, deck_bytes, h, outline, setup

RUI = "rui@example.com"
BEA = "bea@example.com"


def _pending_proposal(server, fake_model, email):
    """A project of `email` with a conversation whose proposal waits for a decision: (pid, did, cid, proposal id)."""
    pid = requests.post(f"{server}/api/projects", json={"name": "B"}, headers=h(email), timeout=10).json()["id"]
    with open(DECKS / "simple.pptx", "rb") as f:
        did = requests.post(f"{server}/api/projects/{pid}/decks", files={"file": ("simple.pptx", f)}, headers=h(email),
                            timeout=60).json()["id"]  # fmt: skip
    cid = requests.post(f"{server}/api/projects/{pid}/conversations", json={"deck_id": did}, headers=h(email),
                        timeout=10).json()["id"]  # fmt: skip
    data = deck_bytes_as(server, pid, did, email)
    sid = outline(data)[1]["slide_id"]
    edit = {"slide_id": sid, "shape_id": body_id(data, sid), "paragraphs": [{"runs": [{"text": "Mudado"}]}]}
    fake_model.script = [{"tools": [("update_text", edit)]}, {"text": "Mudei."}]
    chat = Chat(server, pid, cid, email)
    chat.send("muda o texto do segundo diapositivo")
    prid = chat.last("proposal_updated")["id"]
    chat.close()
    return pid, did, cid, prid


def deck_bytes_as(server, pid, did, email) -> bytes:
    return requests.get(f"{server}/api/projects/{pid}/decks/{did}/download", headers=h(email), timeout=30).content


def _client(server, email):
    sio = socketio.Client()
    sio.connect(server, headers=h(email), transports=["websocket"])
    return sio


def test_a_proposal_of_another_project_is_not_reached_through_a_conversation_path(server, fake_model):
    """L1: Ana, owner of her own project, named Rui's proposal by a conversation id climbing out of her project."""
    rpid, _, rcid, prid = _pending_proposal(server, fake_model, RUI)
    apid, _, _ = setup(server)
    sio = _client(server, ANA)
    try:
        sneaky = f"../../{rpid}/conversations/{rcid}"
        r = sio.call("proposal_decision", {"project_id": apid, "conversation_id": sneaky, "proposal_id": prid,
                                           "accept": False}, timeout=30)  # fmt: skip
        assert not r["ok"], r
    finally:
        sio.disconnect()
    status = requests.get(f"{server}/api/projects/{rpid}/conversations/{rcid}/proposals/{prid}", headers=h(RUI), timeout=10)
    assert status.status_code != 200 or status.json()["status"] == "pending"
    chat = Chat(server, rpid, rcid, RUI)  # still Rui's to decide
    try:
        assert chat.decide(prid, False)["status"] == "rejected"
    finally:
        chat.close()


def test_a_turn_is_cancelled_only_by_a_member_of_its_project(server, fake_model):
    """L2: cancel_turn took any conversation id from anyone signed in."""
    rpid, _, rcid, _ = _pending_proposal(server, fake_model, RUI)
    sio = _client(server, ANA)
    try:
        r = sio.call("cancel_turn", {"project_id": rpid, "conversation_id": rcid}, timeout=10)
        assert not r["ok"], r
    finally:
        sio.disconnect()


def test_a_viewer_cannot_answer_a_plan(server, fake_model):
    """L7: a viewer approved the plan an editor's turn waited on, and the change went ahead."""
    pid, did, cid = setup(server)
    requests.put(f"{server}/api/projects/{pid}/members", json={"email": BEA, "role": "viewer"}, headers=h(), timeout=10)
    fake_model.script = [{"tools": [("propose_plan", {"steps": ["Tighten slide 2"]})]}]
    chat = Chat(server, pid, cid)
    assert chat.send("tighten slide 2")["status"] == "waiting"
    sio = _client(server, BEA)
    try:
        sio.call("join_conversation", {"project_id": pid, "conversation_id": cid}, timeout=10)
        r = sio.call("answer", {"project_id": pid, "conversation_id": cid, "approve": True}, timeout=10)
        assert not r["ok"] and "owners and editors" in r["error"], r
    finally:
        sio.disconnect()
    conv = requests.get(f"{server}/api/projects/{pid}/conversations/{cid}", headers=h(), timeout=10).json()
    assert (conv.get("conversation") or conv)["pending"], "the plan still waits for an editor"
    fake_model.script = [{"text": "Feito."}]
    assert chat.answer(approve=True)["status"] == "done"  # the editor still can
    chat.close()
    assert deck_bytes(server, pid, did)


def test_a_font_name_from_a_deck_is_never_an_option_of_fc_match():
    """L6: the deck's font name went to fc-match before its options; "-V" printed fontconfig's version."""
    from pathlib import Path

    from app.docengine import textfit

    textfit.font_file.cache_clear()
    got = textfit.font_file("-V", False, False)
    assert got and Path(got).is_file()  # a font file (the fallback), not "fontconfig version ..."


def test_an_error_s_text_does_not_reach_the_log(caplog):
    """L5: exception text went into log lines ("search by words only: <the error>"); an error may quote content."""
    import logging

    from app import search
    from app.telemetry import fields

    class Failing:
        def scores(self, query, texts):
            raise search.SearchUnavailable("A cláusula 7.2 do contrato de Ana")

    with caplog.at_level(logging.WARNING, logger="slides"):
        ranked, note = search.rank(Failing(), "garantia", [{"text": "a garantia do Estado"}], 3)
    assert ranked and note
    lines = [str(fields(r)) for r in caplog.records]
    assert lines and not [x for x in lines if "cláusula" in x]


def _docx(document_xml: bytes) -> bytes:
    import io
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", document_xml)
    return out.getvalue()


def test_a_word_document_that_unpacks_to_far_more_than_it_weighs_is_refused(server):
    """M3: word/document.xml was read whole, whatever it unpacks to (here 60 MB from about 60 KB)."""
    pid, _, _ = setup(server, deck=None)
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>Olá</w:t></w:r></w:p>'.encode() + b" " * 60_000_000
    bomb = _docx(body + b"</w:body></w:document>")
    assert len(bomb) < 200_000
    r = requests.post(f"{server}/api/projects/{pid}/assets", data={"kind": "document"},
                      files={"file": ("bomb.docx", bomb)}, headers=h(), timeout=60)  # fmt: skip
    assert r.status_code == 422 and "unpacks to far more data" in r.text, r.text  # as every refused file


def test_a_word_document_with_broken_xml_is_refused_not_a_server_error(server):
    """M3: lxml's XMLSyntaxError was not caught: 500."""
    pid, _, _ = setup(server, deck=None)
    r = requests.post(f"{server}/api/projects/{pid}/assets", data={"kind": "document"},
                      files={"file": ("broken.docx", _docx(b"<w:document><unclosed>"))}, headers=h(), timeout=60)  # fmt: skip
    assert r.status_code == 422 and "may be damaged" in r.text, (r.status_code, r.text)


def test_the_assistants_work_is_in_the_projects_audit_trail(server, fake_model, tmp_path):
    """M4: the project's audit.jsonl (each tool call, its arguments, the model, the resulting version) was never
    written; the conversation's messages were the only trace."""
    import json

    pid, did, cid, prid = _pending_proposal(server, fake_model, ANA)
    chat = Chat(server, pid, cid)
    try:
        chat.decide(prid, True)
    finally:
        chat.close()
    lines = [json.loads(x) for x in (tmp_path / "data" / "projects" / pid / "audit.jsonl").read_text().splitlines()]
    call = next(x for x in lines if x["event"] == "tool_call" and x["tool"] == "update_text")
    assert call["user"] == ANA and call["conversation_id"] == cid and call["ok"] and call["proposal_id"] == prid
    assert call["arguments"]["paragraphs"][0]["runs"][0]["text"] == "Mudado" and call["model"] != "application"
    accepted = next(x for x in lines if x["event"] == "proposal_accepted")
    versions = requests.get(f"{server}/api/projects/{pid}/decks/{did}/versions", headers=h(), timeout=10).json()
    assert accepted["proposal_id"] == prid and accepted["versions"] == {did: versions["current_version"]}


def test_a_project_the_assistant_worked_in_is_exported_and_imported(server, fake_model):
    """The project's audit trail is its own record: left out of the archive (an imported project starts its own)."""
    import io
    import zipfile

    pid, _, _, _ = _pending_proposal(server, fake_model, ANA)
    data = requests.get(f"{server}/api/projects/{pid}/export", headers=h(), timeout=30).content
    assert "data/audit.jsonl" not in zipfile.ZipFile(io.BytesIO(data)).namelist()
    r = requests.post(f"{server}/api/projects/import", files={"file": ("p.zip", data)}, headers=h(), timeout=60)
    assert r.status_code == 201, r.text
