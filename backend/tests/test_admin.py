"""M8's administration through the real server (spec AD-4, AD-5, AD-6): templates managed without touching the server,
the usage per period built from the audit log, the audit log listed, filtered and exported; administrators only."""

from __future__ import annotations

import csv
import io
import json
import shutil

import requests

from app.domain.templates import AdminTemplates

from .conftest import ADMIN, REPO
from .test_agent import ANA, DECKS, Chat, deck_bytes, h, outline, setup

RUI = "rui@example.com"


def test_only_administrators_reach_the_administration(server):
    for method, path in [("get", "admin/templates"), ("post", "admin/templates"), ("patch", "admin/templates/default"),
                         ("get", "audit"), ("get", "audit.csv"), ("get", "usage")]:  # fmt: skip
        r = requests.request(method, f"{server}/api/{path}", headers=h(ANA), timeout=10)
        assert r.status_code == 403, (path, r.status_code)
    assert requests.get(f"{server}/api/audit", headers=h(ADMIN), timeout=10).status_code == 200


def test_templates_are_uploaded_renamed_made_default_and_retired(server, tmp_path):
    with open(DECKS / "simple.pptx", "rb") as f:
        r = requests.post(f"{server}/api/admin/templates", data={"name": "Banco CTT", "description": "Corporate"},
                          files={"file": ("ctt.pptx", f)}, headers=h(ADMIN), timeout=60)  # fmt: skip
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["layouts"] and not r.json()["default"] and not r.json()["retired"]
    # a file that is not a presentation is refused, saying why
    bad = requests.post(f"{server}/api/admin/templates", data={"name": "x"}, files={"file": ("x.pptx", b"not a zip")},
                        headers=h(ADMIN), timeout=10)  # fmt: skip
    assert bad.status_code == 422 and bad.json()["detail"]["code"]
    offered = requests.get(f"{server}/api/templates", headers=h(ANA), timeout=10).json()
    assert {t["id"] for t in offered["templates"]} == {"default", tid} and offered["default"] == "default"

    # renamed; the default is never retired; made the default, the old one can be
    r = requests.patch(f"{server}/api/admin/templates/{tid}", json={"name": "Banco CTT 2026"}, headers=h(ADMIN), timeout=10)
    assert r.json()["name"] == {"pt": "Banco CTT 2026", "en": "Banco CTT 2026"}
    r = requests.patch(f"{server}/api/admin/templates/default", json={"retired": True}, headers=h(ADMIN), timeout=10)
    assert r.status_code == 400
    assert requests.patch(f"{server}/api/admin/templates/{tid}", json={"default": True}, headers=h(ADMIN), timeout=60).ok
    pid = requests.post(f"{server}/api/projects", json={"name": "P"}, headers=h(ANA), timeout=10).json()["id"]
    plain = {"kind": "admin", "id": "default"}
    decks = f"{server}/api/projects/{pid}/decks"
    old = requests.post(decks, json={"title": "Old", "template": plain}, headers=h(ANA), timeout=60).json()
    r = requests.patch(f"{server}/api/admin/templates/default", json={"retired": True}, headers=h(ADMIN), timeout=60)
    assert r.status_code == 200 and r.json()["retired"]

    # retired: no longer offered nor usable for a new deck; the deck made from it still opens and downloads
    offered = requests.get(f"{server}/api/templates", headers=h(ANA), timeout=10).json()
    assert [t["id"] for t in offered["templates"]] == [tid] and offered["default"] == tid
    r = requests.post(decks, json={"title": "New", "template": plain}, headers=h(ANA), timeout=60)
    assert r.status_code == 400
    kept = requests.get(f"{decks}/{old['id']}/download", headers=h(ANA), timeout=30)
    assert kept.status_code == 200 and kept.content[:2] == b"PK"
    every = requests.get(f"{server}/api/admin/templates", headers=h(ADMIN), timeout=10).json()["templates"]
    assert {t["id"]: t["retired"] for t in every} == {"default": True, tid: False}

    # kept in DATA_DIR (the configured folder is left as it was), and the changes are in the audit log by id only
    stored = json.loads((tmp_path / "data" / "templates" / "templates.json").read_text())
    assert [t["id"] for t in stored["templates"]] == ["default", tid]
    assert [t["id"] for t in json.loads((tmp_path / "templates" / "templates.json").read_text())["templates"]] == ["default"]
    log = (tmp_path / "data" / "audit.jsonl").read_text()
    assert "added a template" in log and "changed a template" in log and "Banco CTT" not in log


def test_the_template_store_is_seeded_once_and_survives_a_restart(tmp_path):
    folder, store = tmp_path / "config", tmp_path / "data" / "templates"
    folder.mkdir()
    shutil.copy(REPO / "templates" / "default.pptx", folder / "default.pptx")
    listing = json.loads((REPO / "templates" / "templates.json").read_text(encoding="utf-8"))
    plain = [{**t, "default": True} for t in listing["templates"] if t["id"] == "default"]
    (folder / "templates.json").write_text(json.dumps({**listing, "templates": plain}), encoding="utf-8")
    first = AdminTemplates(folder, store)
    tid = first.add("Mine", (DECKS / "simple.pptx").read_bytes())["id"]
    first.change(tid, default=True)
    again = AdminTemplates(folder, store)  # a restart: the store is not seeded again over the changes
    assert again.default_id == tid and set(again.items) == {"default", tid}
    assert again.data[tid] == first.data[tid]


def _audit(server, **params):
    r = requests.get(f"{server}/api/audit", params=params, headers=h(ADMIN), timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_audit_log_is_filtered_paged_and_exported(server):
    a = requests.post(f"{server}/api/projects", json={"name": "Ana's"}, headers=h(ANA), timeout=10).json()["id"]
    r = requests.post(f"{server}/api/projects", json={"name": "Rui's"}, headers=h(RUI), timeout=10).json()["id"]
    requests.patch(f"{server}/api/projects/{a}", json={"name": "Ana's, renamed"}, headers=h(ANA), timeout=10)
    requests.delete(f"{server}/api/projects/{r}", headers=h(RUI), timeout=10)

    every = _audit(server)
    assert [(e["user"], e["label"]) for e in every["entries"]] == [
        (RUI, "deleted a project"), (ANA, "changed a project"), (RUI, "created a project"), (ANA, "created a project"),
    ]  # fmt: skip
    assert every["users"] == [ANA, RUI] and not every["more"]
    assert [e["label"] for e in _audit(server, user=RUI)["entries"]] == ["deleted a project", "created a project"]
    assert [e["target"]["pid"] for e in _audit(server, q="deleted")["entries"]] == [r]
    assert [e["user"] for e in _audit(server, q=a)["entries"]] == [ANA, ANA]  # by the data's identifier
    # a period: nothing before the first change, everything up to now
    first = every["entries"][-1]["at"]
    assert _audit(server, until="2000-01-01T00:00:00Z")["entries"] == []
    assert len(_audit(server, since=first)["entries"]) == 4
    # pages: newest first, then the rest from where the page ended
    page = _audit(server, limit=3)
    assert len(page["entries"]) == 3 and page["more"]
    rest = _audit(server, limit=3, before=page["entries"][-1]["id"])
    assert [e["label"] for e in rest["entries"]] == ["created a project"] and not rest["more"]

    csv_r = requests.get(f"{server}/api/audit.csv", params={"user": ANA}, headers=h(ADMIN), timeout=10)
    assert csv_r.headers["content-type"].startswith("text/csv") and "attachment" in csv_r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(csv_r.text)))
    assert rows[0] == ["when (UTC)", "user", "what", "action", "which data"]
    assert [(x[1], x[2]) for x in rows[1:]] == [(ANA, "changed a project"), (ANA, "created a project")]
    assert json.loads(rows[1][4]) == {"pid": a}
    assert "renamed" not in csv_r.text  # never the change itself


def test_usage_counts_people_projects_turns_decisions_and_failures(server, fake_model):
    pid, did, cid = setup(server)
    other = requests.post(f"{server}/api/projects", json={"name": "Q"}, headers=h(RUI), timeout=10).json()["id"]
    chat = Chat(server, pid, cid)
    try:
        for accept in (True, False):  # a deletion: the application's plan, approved, then the proposal decided
            sid = outline(deck_bytes(server, pid, did))[1]["slide_id"]
            fake_model.script = [{"tools": [("delete_slide", {"slide_id": sid})]}]
            assert chat.send("apaga o slide 2")["status"] == "waiting"
            fake_model.script = [{"text": "Apaguei o slide 2."}]
            chat.answer(approve=True)
            chat.decide(chat.last("proposal_updated")["id"], accept)
        fake_model.script = [{"fail": "the model service is down"}]
        assert chat.send("olá")["status"] == "failed"
    finally:
        chat.close()
    for by in ("day", "week", "month"):
        u = requests.get(f"{server}/api/usage", params={"by": by}, headers=h(ADMIN), timeout=10).json()
        assert len(u["periods"]) == 1, u
        row = u["periods"][0]
        assert {k: row[k] for k in ("people", "projects", "turns", "accepted", "rejected", "errors")} == {
            "people": 2, "projects": 2, "turns": 3, "accepted": 1, "rejected": 1, "errors": 1,
        }, (by, row)  # fmt: skip
    assert other
    old = requests.get(f"{server}/api/usage", params={"until": "2000-01-01"}, headers=h(ADMIN), timeout=10).json()
    assert old["periods"] == []
