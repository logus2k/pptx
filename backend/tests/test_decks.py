"""M1 through the real server: projects, decks (upload, from a template), templates, versions and restore, download,
slide images, membership, refusals, the audit trail (technical design section 13, M1)."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest
import requests
from PIL import Image

from .conftest import REPO, SECRET

DECKS = REPO / "fixtures" / "decks"
ANA, RUI = "ana@example.com", "rui@example.com"
# LibreOffice with Impress (the container has it; a host with only LibreOffice's core cannot open presentations)
RENDERS = shutil.which("soffice") is not None and Path("/usr/lib/libreoffice/share/registry/impress.xcd").exists()


def h(email: str) -> dict:
    return {"X-Slides-Proxy-Secret": SECRET, "X-Auth-Request-Email": email}


def new_project(server, email=ANA, name="Client X proposal") -> dict:
    r = requests.post(f"{server}/api/projects", json={"name": name}, headers=h(email), timeout=10)
    assert r.status_code == 201, r.text
    return r.json()


def upload(server, pid, name, email=ANA):
    with open(DECKS / name, "rb") as f:
        return requests.post(f"{server}/api/projects/{pid}/decks", files={"file": (name, f)}, headers=h(email), timeout=60)


def test_projects_are_private_to_their_members(server):
    p = new_project(server)
    assert [x["id"] for x in requests.get(f"{server}/api/projects", headers=h(ANA), timeout=5).json()["projects"]] == [p["id"]]
    assert requests.get(f"{server}/api/projects", headers=h(RUI), timeout=5).json()["projects"] == []
    assert requests.get(f"{server}/api/projects/{p['id']}", headers=h(RUI), timeout=5).status_code == 404
    assert upload(server, p["id"], "simple.pptx", email=RUI).status_code == 404
    assert requests.get(f"{server}/api/projects/not-an-id", headers=h(ANA), timeout=5).status_code == 404


def test_upload_lists_slides_and_downloads_the_same_file(server):
    p = new_project(server)
    r = upload(server, p["id"], "simple.pptx")
    assert r.status_code == 201, r.text
    deck = r.json()
    assert deck["title"] == "simple" and deck["template"] is None and deck["current_version"] == 1
    info = requests.get(f"{server}/api/projects/{p['id']}/decks/{deck['id']}", headers=h(ANA), timeout=30).json()
    assert [s["title"] for s in info["slides"]] == ["Proposta para o Cliente X", "Agenda", "Antes e depois"]
    assert all(len(s["key"]) == 64 for s in info["slides"])
    got = requests.get(f"{server}/api/projects/{p['id']}/decks/{deck['id']}/download", headers=h(ANA), timeout=30)
    assert got.status_code == 200
    assert hashlib.sha256(got.content).hexdigest() == hashlib.sha256((DECKS / "simple.pptx").read_bytes()).hexdigest()
    assert 'filename="simple.pptx"' in got.headers["content-disposition"]


@pytest.mark.parametrize(
    ("name", "code"),
    [("macro.pptm", "macros"), ("encrypted.pptx", "encrypted"), ("zip-bomb.pptx", "too_large"), ("not-a-deck.pptx", "not_pptx")],
)
def test_refused_uploads_say_why(server, name, code):
    p = new_project(server)
    r = upload(server, p["id"], name)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == code
    assert requests.get(f"{server}/api/projects/{p['id']}/decks", headers=h(ANA), timeout=5).json()["decks"] == []


def test_two_decks_with_different_templates(server):
    p = new_project(server)
    pid = p["id"]
    with open(DECKS / "template.potx", "rb") as f:
        r = requests.post(
            f"{server}/api/projects/{pid}/assets",
            data={"kind": "template"},
            files={"file": ("Our template.potx", f)},
            headers=h(ANA),
            timeout=30,
        )
    assert r.status_code == 201, r.text
    asset = r.json()
    assert asset["kind"] == "template" and "Title Slide" in asset["layouts"]
    listing = requests.get(f"{server}/api/templates", params={"project": pid}, headers=h(ANA), timeout=5).json()
    assert {(t["kind"], t["id"]) for t in listing["templates"]} == {("admin", "default"), ("asset", asset["id"])}
    decks = f"{server}/api/projects/{pid}/decks"
    plain, ours = {"kind": "admin", "id": "default"}, {"kind": "asset", "id": asset["id"]}
    a = requests.post(decks, json={"title": "Plain", "template": plain}, headers=h(ANA), timeout=30).json()
    b = requests.post(decks, json={"title": "Ours", "template": ours}, headers=h(ANA), timeout=30).json()
    assert a["template"] == {"kind": "admin", "id": "default"}
    assert b["template"] == {"kind": "asset", "id": asset["id"]}
    for d in (a, b):
        assert d["versions"][0]["slide_count"] == 0 and d["versions"][0]["source"] == "template"
    # another project cannot use this project's template
    other = new_project(server, name="Other")
    r = requests.post(
        f"{server}/api/projects/{other['id']}/decks",
        json={"title": "X", "template": {"kind": "asset", "id": asset["id"]}},
        headers=h(ANA),
        timeout=30,
    )
    assert r.status_code == 404


def test_restore_makes_a_new_version_and_never_rewrites(server):
    p = new_project(server)
    deck = upload(server, p["id"], "simple.pptx").json()
    base = f"{server}/api/projects/{p['id']}/decks/{deck['id']}"
    r = requests.post(f"{base}/versions/1/restore", headers=h(ANA), timeout=30)
    assert r.status_code == 200, r.text
    versions = requests.get(f"{base}/versions", headers=h(ANA), timeout=5).json()
    assert versions["current_version"] == 2
    history = [(v["number"], v["source"], v.get("restored_from")) for v in versions["versions"]]
    assert history == [(2, "restore", 1), (1, "upload", None)]
    v1 = requests.get(f"{base}/download", params={"version": 1}, headers=h(ANA), timeout=30).content
    v2 = requests.get(f"{base}/download", headers=h(ANA), timeout=30).content
    assert v1 == v2
    assert requests.post(f"{base}/versions/9/restore", headers=h(ANA), timeout=30).status_code == 404


def test_audit_trail_records_changes_by_identifiers(server, tmp_path):
    p = new_project(server)
    deck = upload(server, p["id"], "simple.pptx").json()
    requests.patch(f"{server}/api/projects/{p['id']}/decks/{deck['id']}", json={"title": "Renamed"}, headers=h(ANA), timeout=10)
    requests.get(f"{server}/api/projects", headers=h(ANA), timeout=5)  # a read: not recorded
    lines = [json.loads(x) for x in (tmp_path / "data" / "audit.jsonl").read_text().splitlines()]
    assert [(x["action"], x.get("label")) for x in lines] == [
        ("POST /api/projects", "created a project"),
        ("POST /api/projects/{pid}/decks", "added a deck"),
        ("PATCH /api/projects/{pid}/decks/{did}", "renamed a deck"),
    ]
    assert all(x["user"] == ANA for x in lines)
    assert lines[1]["target"] == {"pid": p["id"], "did": deck["id"]}
    assert "Renamed" not in (tmp_path / "data" / "audit.jsonl").read_text()  # never the change itself


@pytest.mark.skipif(not RENDERS, reason="LibreOffice Impress is not installed here (run make check: it tests in the container)")
def test_slide_images_are_real_renders(server):
    p = new_project(server)
    deck = upload(server, p["id"], "features.pptx").json()
    info = requests.get(f"{server}/api/projects/{p['id']}/decks/{deck['id']}", headers=h(ANA), timeout=30).json()
    hidden = info["slides"][3]
    assert hidden["hidden"] is True
    from app.docengine import render

    for s, size, width in ((info["slides"][1], "preview", render.PREVIEW_WIDTH), (hidden, "thumb", render.THUMB_WIDTH)):
        r = requests.get(
            f"{server}/api/projects/{p['id']}/decks/{deck['id']}/slides/{s['id']}/image",
            params={"size": size, "version": 1},
            headers=h(ANA),
            timeout=180,
        )
        assert r.status_code == 200, r.text
        assert "immutable" in r.headers["cache-control"]
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        assert img.width == width and abs(img.width / img.height - 16 / 9) < 0.02
        colours = img.getcolors(maxcolors=1_000_000) or []
        assert len(colours) > 20, "a blank image"  # a real render has text and anti-aliasing
    # the picture slide shows the red disc drawn into the fixture's picture
    preview = Image.open(
        io.BytesIO(
            requests.get(
                f"{server}/api/projects/{p['id']}/decks/{deck['id']}/slides/{info['slides'][1]['id']}/image",
                params={"size": "preview", "version": 1},
                headers=h(ANA),
                timeout=60,
            ).content
        )
    ).convert("RGB")
    reds = sum(1 for px in preview.get_flattened_data() if px[0] > 200 and px[1] < 40 and px[2] < 70)
    assert reds > 1000


@pytest.mark.skipif(not RENDERS, reason="LibreOffice Impress is not installed here (run make check: it tests in the container)")
def test_two_requests_for_the_same_slides_share_one_render(tmp_path, monkeypatch):
    """A proposal's draft and the version it started from share their unchanged slides: asked for at once, they are
    rendered once, and neither request fails (measured 2026-10-06: both rendered, one rename found its file gone)."""
    import asyncio

    from app.docengine import render

    conversions = []
    real = render._convert
    monkeypatch.setattr(render, "_convert", lambda data, n: conversions.append(n) or real(data, n))
    data = (REPO / "fixtures" / "decks" / "simple.pptx").read_bytes()

    async def both():
        return await asyncio.gather(render.ensure(data, tmp_path), render.ensure(data, tmp_path), return_exceptions=True)

    results = asyncio.run(both())
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert len(conversions) == 1
    keys = results[0]
    assert all((tmp_path / k["key"] / "preview.png").exists() and (tmp_path / k["key"] / "thumb.png").exists() for k in keys)
    assert not list(tmp_path.rglob("*.tmp"))


SVG = (
    b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
    b'<rect width="200" height="100" fill="#E00024"/><circle cx="100" cy="50" r="30" fill="white"/></svg>'
)


@pytest.mark.skipif(not RENDERS, reason="LibreOffice Impress is not installed here (run make check: it tests in the container)")
def test_an_svg_image_becomes_a_png_and_one_naming_outside_files_is_refused(server):
    """Spec IM-1: SVG converted to PNG (by LibreOffice). An SVG that names a file or an address, or declares
    entities, is refused before anything reads it."""
    p = new_project(server)
    r = requests.post(
        f"{server}/api/projects/{p['id']}/assets",
        data={"kind": "image"},
        files={"file": ("logo.svg", SVG)},
        headers=h(ANA),
        timeout=60,
    )
    assert r.status_code == 201, r.text
    asset = r.json()
    assert asset["name"] == "logo.png" and asset["file"].endswith(".png")
    stored = requests.get(f"{server}/api/projects/{p['id']}/assets/{asset['id']}/file", headers=h(ANA), timeout=10)
    assert stored.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(stored.content))
    assert img.getpixel((5, 5))[:3] == (224, 0, 36) and img.getpixel((100, 50))[:3] == (255, 255, 255)
    for hostile in (
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>',
        b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
        b"<svg xmlns:xlink=\"http://www.w3.org/1999/xlink\"><use xlink:href = 'http://169.254.169.254/'/></svg>",
    ):
        r = requests.post(
            f"{server}/api/projects/{p['id']}/assets",
            data={"kind": "image"},
            files={"file": ("x.svg", hostile)},
            headers=h(ANA),
            timeout=60,
        )
        assert r.status_code == 422, hostile


@pytest.mark.skipif(not RENDERS, reason="LibreOffice Impress is not installed here (run make check: it tests in the container)")
def test_a_version_downloads_as_pdf(server):
    """Spec PM-5: one PDF page per slide, the version's text in it; the second request is served from the cache."""
    import pypdfium2 as pdfium

    p = new_project(server)
    deck = upload(server, p["id"], "simple.pptx").json()
    r = requests.get(f"{server}/api/projects/{p['id']}/decks/{deck['id']}/pdf", headers=h(ANA), timeout=120)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert 'filename="simple.pdf"' in r.headers["content-disposition"]
    pdf = pdfium.PdfDocument(r.content)
    assert len(pdf) == 3 and "Agenda" in pdf[1].get_textpage().get_text_range()
    again = requests.get(f"{server}/api/projects/{p['id']}/decks/{deck['id']}/pdf", headers=h(ANA), timeout=10)
    assert again.content == r.content
    assert (
        requests.get(f"{server}/api/projects/{p['id']}/decks/{deck['id']}/pdf?version=9", headers=h(ANA), timeout=10).status_code
        == 404
    )


def test_manual_edits_make_versions_undo_takes_back_and_stale_ones_are_refused(server, tmp_path):
    p = new_project(server)
    deck = upload(server, p["id"], "simple.pptx").json()
    base = f"{server}/api/projects/{p['id']}/decks/{deck['id']}"
    slides = requests.get(base, headers=h(ANA), timeout=30).json()["slides"]
    first, second = slides[0]["id"], slides[1]["id"]

    def shapes(sid):
        return requests.get(f"{base}/slides/{sid}", headers=h(ANA), timeout=30).json()["shapes"]

    def order():
        return [s["id"] for s in requests.get(base, headers=h(ANA), timeout=30).json()["slides"]]

    def edit(body, version, who=ANA):
        return requests.post(f"{base}/edits", json={"base_version": version, **body}, headers=h(who), timeout=60)

    title = next(s for s in shapes(first) if s.get("paragraphs"))
    r = edit({"op": "text", "slide_id": first, "shape_id": title["shape_id"], "paragraphs": ["Título novo"]}, 1)
    assert r.status_code == 200, r.text
    shape = next(s for s in shapes(first) if s["shape_id"] == title["shape_id"])
    assert ["".join(x["text"] for x in q["runs"]) for q in shape["paragraphs"]] == ["Título novo"]
    assert edit({"op": "move", "slide_id": second, "position": 0}, 2).status_code == 200
    assert order()[:2] == [second, first]
    assert edit({"op": "delete", "slide_id": second}, 3).status_code == 200
    assert second not in order()
    stale = edit({"op": "delete", "slide_id": first}, 3)  # the page still showed version 3
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "moved_on"
    assert edit({"op": "text", "slide_id": first, "shape_id": 999, "paragraphs": ["x"]}, 4).status_code == 422
    assert edit({"op": "move", "slide_id": first}, 4).status_code == 422
    assert edit({"op": "delete", "slide_id": first}, 4, who=RUI).status_code == 404  # not a member
    versions = requests.get(f"{base}/versions", headers=h(ANA), timeout=5).json()
    assert [v["source"] for v in versions["versions"]] == ["manual", "manual", "manual", "upload"]
    assert requests.post(f"{base}/undo", headers=h(ANA), timeout=30).status_code == 200  # the deletion taken back
    assert second in order()
    audit = (tmp_path / "data" / "audit.jsonl").read_text()
    assert audit.count('"edited a deck by hand"') == 3 and "Título novo" not in audit


def test_a_project_is_shared_and_a_deck_open_in_the_editor_is_held_for_whoever_opened_it(server, tmp_path):
    """Spec PJ-13: owners share a project as editor or viewer; while a member has a deck open (its lease), the others
    can view it and not change it - by hand, by undo, nor by accepting the assistant's changes; released, they can."""
    EVA = "eva@example.com"
    p = new_project(server)
    pid = p["id"]
    deck = upload(server, pid, "simple.pptx").json()
    base = f"{server}/api/projects/{pid}/decks/{deck['id']}"
    members = f"{server}/api/projects/{pid}/members"
    assert requests.get(f"{server}/api/projects/{pid}", headers=h(RUI), timeout=10).status_code == 404  # not yet
    r = requests.put(members, json={"email": " Rui@Example.com ", "role": "editor"}, headers=h(ANA), timeout=10)
    assert r.status_code == 200 and {"email": RUI, "role": "editor"} in r.json()["members"]
    assert requests.put(members, json={"email": EVA, "role": "viewer"}, headers=h(ANA), timeout=10).status_code == 200
    assert requests.put(members, json={"email": EVA, "role": "owner"}, headers=h(RUI), timeout=10).status_code == 404  # an editor
    assert requests.put(members, json={"email": "rui.example", "role": "editor"}, headers=h(ANA), timeout=10).status_code == 400
    last_owner = requests.put(members, json={"email": ANA, "role": "editor"}, headers=h(ANA), timeout=10)
    assert last_owner.status_code == 400
    listed = requests.get(f"{server}/api/projects", headers=h(RUI), timeout=10).json()["projects"]
    assert [(x["id"], x["role"]) for x in listed] == [(pid, "editor")]
    assert requests.post(f"{base}/lease", headers=h(EVA), timeout=10).status_code == 404  # a viewer does not edit

    slides = requests.get(base, headers=h(ANA), timeout=30).json()["slides"]
    first = slides[0]["id"]
    shapes = requests.get(f"{base}/slides/{first}", headers=h(ANA), timeout=30).json()["shapes"]
    title = next(s for s in shapes if s.get("paragraphs"))
    text = {"op": "text", "slide_id": first, "shape_id": title["shape_id"], "paragraphs": ["Da Ana"]}
    assert requests.post(f"{base}/lease", headers=h(ANA), timeout=10).json()["holder"] == ANA
    held = requests.post(f"{base}/lease", headers=h(RUI), timeout=10)
    assert held.status_code == 409
    assert held.json()["detail"] == {"code": "leased", "holder": ANA, "message": f"The deck is being edited by {ANA}."}
    assert requests.get(base, headers=h(RUI), timeout=30).json()["lease"]["holder"] == ANA  # shown to the others
    refused = requests.post(f"{base}/edits", json={"base_version": 1, **text}, headers=h(RUI), timeout=60)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "leased"
    assert requests.post(f"{base}/edits", json={"base_version": 1, **text}, headers=h(ANA), timeout=60).status_code == 200
    assert requests.post(f"{base}/undo", headers=h(RUI), timeout=30).status_code == 409
    assert requests.patch(base, json={"title": "Outro"}, headers=h(RUI), timeout=10).status_code == 409
    assert requests.delete(f"{base}/lease", headers=h(RUI), timeout=10).status_code == 204  # not theirs: nothing happens
    assert requests.get(base, headers=h(RUI), timeout=30).json()["lease"]["holder"] == ANA
    assert requests.delete(f"{base}/lease", headers=h(ANA), timeout=10).status_code == 204
    assert requests.get(base, headers=h(RUI), timeout=30).json()["lease"] is None
    assert requests.post(f"{base}/undo", headers=h(RUI), timeout=30).status_code == 200  # free: the editor can
    assert requests.delete(f"{members}/{RUI}", headers=h(RUI), timeout=10).status_code == 200  # leaving
    assert requests.get(f"{server}/api/projects/{pid}", headers=h(RUI), timeout=10).status_code == 404
    audit = (tmp_path / "data" / "audit.jsonl").read_text()
    assert audit.count('"shared a project"') == 2 and audit.count('"removed a project member"') == 1 and "/lease" not in audit


def test_the_lease_expires_when_its_holder_goes_idle():
    import time

    from app.domain.leases import Leased, Leases

    leases = Leases(minutes=0.01)  # 0.6 s
    leases.take("d1", "ana@example.com")
    with pytest.raises(Leased):
        leases.check("d1", "rui@example.com")
    time.sleep(0.7)
    leases.check("d1", "rui@example.com")  # idle past its time: free
    assert leases.take("d1", "rui@example.com")["holder"] == "rui@example.com"
