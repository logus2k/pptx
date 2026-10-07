"""User flows end to end (spec section 10): each scenario is what a person does, turn after turn, through the same HTTP
API and socket.io events the page uses, against the real app and the real configured model and knowledge base. The
runner plays the person: it approves plans, answers questions (with the scenario's answers, else "Decide tu."),
accepts the proposals the assistant leaves (as Review > Accept does). Judged on what is in the deck at the end of each
turn and at the end (read model; slides rendered to PNG to be looked at), never on what the assistant says it did.

Run in the test image on the services' network, with .env (the model, the knowledge base's key):
  docker run --rm --network logus2k_network --env-file .env -u $(id -u):$(id -g) -e HOME=/tmp \
    -v $PWD:/src -w /src -v $PWD/fonts:/usr/share/fonts/slides:ro slides-test python tests/scenarios/run.py [ids...]
(connected to cortex-kb as well for the knowledge base). The app is started from the code on disk, with its own
throwaway data folder; tests/scenarios/out/<time>/ gets each scenario's turns (report.json) and slides (PNG)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import requests
import socketio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.docengine import read, render  # noqa: E402

PORT = 2731
URL = f"http://127.0.0.1:{PORT}"
SECRET = "scenario-secret"
EMAIL = os.environ.get("EVAL_EMAIL", "antonio.s.cruz@bancoctt.pt")  # the knowledge base answers with this person's access
TURN_SECONDS = 600  # a turn's longest wait (a local 4B model, many steps)
H = {"X-Slides-Proxy-Secret": SECRET, "X-Auth-Request-Email": EMAIL}


def start_app(data_dir: Path) -> subprocess.Popen:
    env = {
        **os.environ,
        "SLIDES_PORT": str(PORT),
        "SLIDES_DATA_DIR": str(data_dir),
        "SLIDES_PROXY_SECRET": SECRET,
        "SLIDES_CONFIG_FILE": str(ROOT / "config" / "config.json"),
        "SLIDES_FRONTEND_DIR": str(ROOT / "frontend"),
        "PYTHONPATH": str(ROOT / "backend"),
        "SCENARIO_CALLS": str(data_dir.parent / "calls.jsonl"),
    }
    log = open(data_dir.parent / "app.log", "w")  # noqa: SIM115 - open for the app's lifetime
    app = subprocess.Popen([sys.executable, str(Path(__file__).parent / "serve.py")], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)  # noqa: S603
    for _ in range(120):
        try:
            if requests.get(f"{URL}/api/health", timeout=2).ok:
                return app
        except requests.RequestException:
            pass
        if app.poll() is not None:
            raise SystemExit(f"the app stopped: see {data_dir.parent / 'app.log'}")
        time.sleep(1)
    raise SystemExit("the app did not start in 2 minutes")


class Person:
    """One conversation, as the page drives it."""

    def __init__(self, pid: str, cid: str) -> None:
        self.pid, self.cid = pid, cid
        self.events: list[tuple[str, dict]] = []
        self.ended = threading.Event()
        self.sio = socketio.Client()
        for name in ("assistant_message", "tool_progress", "question", "plan", "instructions_proposed", "proposal_updated",
                     "turn_started", "turn_ended", "assistant_error"):  # fmt: skip
            self.sio.on(name, self._on(name))
        self.sio.connect(URL, headers=H, transports=["websocket"])
        joined = self.sio.call("join_conversation", {"project_id": pid, "conversation_id": cid}, timeout=10)
        assert joined["ok"], joined

    def _on(self, name):
        def on(data):
            self.events.append((name, data))
            if name == "turn_ended":
                self.ended.set()

        return on

    def _wait(self) -> str:
        if not self.ended.wait(TURN_SECONDS):
            return "timeout"
        return next(d for n, d in reversed(self.events) if n == "turn_ended")["status"]

    def say(self, text: str) -> str:
        self.ended.clear()
        r = self.sio.call("user_message", {"project_id": self.pid, "conversation_id": self.cid, "text": text}, timeout=30)
        assert r["ok"], r
        return self._wait()

    def respond(self, decision: dict) -> str:
        self.ended.clear()
        r = self.sio.call("answer", {"project_id": self.pid, "conversation_id": self.cid, **decision}, timeout=30)
        assert r["ok"], r
        return self._wait()

    def accept(self, proposal_id: str) -> dict:
        return self.sio.call(
            "proposal_decision",
            {"project_id": self.pid, "conversation_id": self.cid, "proposal_id": proposal_id, "accept": True, "slides": None},
            timeout=60,
        )

    def close(self) -> None:
        self.sio.disconnect()


# ── the deck, as it is ────────────────────────────────────────────────
def deck_bytes(pid: str, did: str) -> bytes:
    return requests.get(f"{URL}/api/projects/{pid}/decks/{did}/download", headers=H, timeout=60).content


def slides_of(data: bytes) -> list[dict]:
    """Each slide: its layout, its text by shape (placeholders named by type), its empty placeholders, overflow."""
    prs = read.open_deck(data)
    out = []
    for o in read.outline(prs):
        s = read.slide(prs, o["slide_id"])
        shapes, empty, over = [], [], []
        for sh in _flat(s["shapes"]):
            lines = [" ".join(r.get("text", "") for r in p.get("runs") or []).strip() for p in sh.get("paragraphs") or []]
            lines = [x for x in lines if x]
            ph = sh.get("placeholder") or {}
            if lines:
                shapes.append({"shape_id": sh["shape_id"], "kind": ph.get("type") or sh.get("type"), "lines": lines})
            elif ph and ph.get("type") not in ("date", "footer", "slide_number", "picture"):
                empty.append(ph.get("type"))  # shows its prompt text in the editor ("Click to add text")
            if sh.get("overflow"):
                over.append(sh["shape_id"])
        out.append({"slide_id": o["slide_id"], "layout": s.get("layout"), "shapes": shapes, "empty_placeholders": empty,
                    "overflowing": over, "notes": s.get("notes")})  # fmt: skip
    return out


def _flat(shapes):
    for sh in shapes:
        yield sh
        yield from _flat(sh.get("shapes") or [])


def text_of(slide: dict) -> str:
    return "\n".join(x for sh in slide["shapes"] for x in sh["lines"])


# ── a scenario ────────────────────────────────────────────────────────
CALLS: Path | None = None  # the model's requests, one JSON line each (serve.py)


def calls_since(mark: int) -> tuple[list[dict], int]:
    lines = CALLS.read_text(encoding="utf-8").splitlines() if CALLS and CALLS.exists() else []
    return [json.loads(x) for x in lines[mark:]], len(lines)


def run_scenario(sc: dict, out: Path) -> dict:
    pid = requests.post(f"{URL}/api/projects", json={"name": sc.get("project", sc["id"])}, headers=H, timeout=10).json()["id"]
    start = sc.get("deck") or {"template": {"kind": "admin", "id": "bancoctt"}, "title": "Apresentação"}
    if "upload" in start:
        with open(ROOT / start["upload"], "rb") as f:
            deck = requests.post(f"{URL}/api/projects/{pid}/decks", files={"file": (Path(start["upload"]).name, f)}, headers=H, timeout=120)
    else:
        deck = requests.post(f"{URL}/api/projects/{pid}/decks", json=start, headers=H, timeout=60)
    assert deck.status_code == 201, deck.text
    did = deck.json()["id"]
    cid = requests.post(f"{URL}/api/projects/{pid}/conversations", json={"deck_id": did}, headers=H, timeout=10).json()["id"]
    person = Person(pid, cid)
    answers = list(sc.get("answers") or [])
    turns, checks = [], []
    try:
        for i, turn in enumerate(sc["turns"]):
            mark = len(person.events)
            _, calls_mark = calls_since(0)
            t0 = time.monotonic()
            status = person.say(turn["say"])
            waits = []
            while status == "waiting" and len(waits) < 6:
                kind, payload = next((n, d) for n, d in reversed(person.events) if n in ("question", "plan", "instructions_proposed"))
                if kind == "plan":
                    decision = {"approve": True}
                elif kind == "question":
                    decision = {"answer": answers.pop(0) if answers else "Decide tu."}
                else:
                    decision = {"accept": True}
                waits.append({"kind": kind, "asked": payload, "answered": decision})
                status = person.respond(decision)
            seen = person.events[mark:]
            proposal = next((d for n, d in reversed(seen) if n == "proposal_updated"), None)
            accepted = None
            if proposal and proposal.get("status") == "pending":
                accepted = person.accept(proposal["id"])
            after = slides_of(deck_bytes(pid, did))
            record = {
                "say": turn["say"], "status": status, "seconds": round(time.monotonic() - t0, 1), "waits": waits,
                "replies": [d.get("content") for n, d in seen if n == "assistant_message"],
                "tools": [d.get("tool") for n, d in seen if n == "tool_progress"],
                "errors": [d for n, d in seen if n == "assistant_error"],
                "proposal": proposal and {"status": proposal.get("status"), "accepted": bool(accepted and accepted.get("ok"))},
                "deck": after,
                "calls": calls_since(calls_mark)[0],
            }  # fmt: skip
            turns.append(record)
            checks += [{"turn": i + 1, **c} for c in judge(turn.get("expect") or {}, record, after)]
    finally:
        person.close()
    final = deck_bytes(pid, did)
    name = sc["id"] if not (out / f"{sc['id']}.pptx").exists() else f"{sc['id']}-{len(list(out.glob(sc['id'] + '*.pptx'))) + 1}"
    (out / f"{name}.pptx").write_bytes(final)
    pictures(final, out, name)
    checks += [{"turn": "end", **c} for c in judge(sc.get("expect") or {}, turns[-1] if turns else {}, slides_of(final))]
    report = {"id": sc["id"], "about": sc.get("about"), "turns": turns, "checks": checks, "passed": all(c["ok"] for c in checks)}
    (out / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return report


def judge(expect: dict, record: dict, slides: list[dict]) -> list[dict]:
    """The checks a scenario names, on the deck as it is (each can fail: none is a check of the plumbing)."""
    out = []

    def check(ok: bool, what: str) -> None:
        out.append({"ok": bool(ok), "check": what})

    if "status" in expect:
        check(record.get("status") == expect["status"], f"the turn ended {expect['status']} ({record.get('status')})")
    if "slides" in expect:
        check(len(slides) == expect["slides"], f"the deck has {expect['slides']} slides ({len(slides)})")
    if "min_slides" in expect:
        check(len(slides) >= expect["min_slides"], f"the deck has at least {expect['min_slides']} slides ({len(slides)})")
    if expect.get("no_empty_placeholders"):
        bad = [(n + 1, s["empty_placeholders"]) for n, s in enumerate(slides) if s["empty_placeholders"]]
        check(slides and not bad, f"no slide left with empty placeholders (prompt text on show) {bad}")
    if expect.get("no_overflow"):
        bad = [(n + 1, s["overflowing"]) for n, s in enumerate(slides) if s["overflowing"]]
        check(slides and not bad, f"no text past its box {bad}")
    for want in expect.get("slide_text") or []:  # {slide: n (1-based, -1 = last), min_lines, any: [...], all: [...]}
        n = want["slide"]
        s = slides[n - 1] if 0 < n <= len(slides) else (slides[n] if n < 0 and -n <= len(slides) else None)
        if s is None:
            check(False, f"slide {n} exists")
            continue
        text = text_of(s)
        low = text.lower()
        lines = [x for x in text.split("\n") if x.strip()]
        if "min_lines" in want:
            check(len(lines) >= want["min_lines"], f"slide {n} has at least {want['min_lines']} lines of text ({len(lines)})")
        if want.get("any"):
            check(any(w.lower() in low for w in want["any"]), f"slide {n} mentions one of {want['any']}")
        for w in want.get("all") or []:
            check(w.lower() in low, f"slide {n} mentions {w!r}")
        if want.get("title"):
            check(any(sh["kind"] in ("title", "center_title") for sh in s["shapes"]), f"slide {n} has a title")
    for tool in expect.get("used") or []:
        check(tool in (record.get("tools") or []), f"the assistant used {tool} ({sorted(set(record.get('tools') or []))})")
    if expect.get("changed") is not None:
        changed = bool(record.get("proposal")) and bool(record["proposal"].get("accepted"))
        check(changed == expect["changed"], f"the turn {'changed' if expect['changed'] else 'did not change'} the deck")
    return out


def pictures(data: bytes, out: Path, name: str) -> None:
    """Each slide as LibreOffice draws it, to be looked at."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(render._convert(data, len(read.open_deck(data).slides)))
    except Exception as e:  # noqa: BLE001 - a render that fails is reported, the scenario's checks still stand
        (out / f"{name}-render-error.txt").write_text(str(e))
        return
    for i in range(len(pdf)):
        pdf[i].render(scale=1).to_pil().save(out / f"{name}-slide{i + 1}.png")


def main(ids: list[str]) -> int:
    scenarios = json.loads((Path(__file__).parent / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    if ids:
        scenarios = [s for s in scenarios if s["id"] in ids]
    scenarios = scenarios * int(os.environ.get("SCENARIO_REPEAT", "1"))  # a model's choices vary: each run is judged
    out = Path(__file__).parent / "out" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="slides-scenarios-"))
    (work / "data").mkdir()
    global CALLS
    CALLS = work / "calls.jsonl"
    app = start_app(work / "data")
    results = []
    try:
        for sc in scenarios:
            try:
                r = run_scenario(sc, out)
            except Exception as e:  # noqa: BLE001 - one scenario's crash is its failure, the others still run
                r = {"id": sc["id"], "passed": False, "checks": [{"ok": False, "check": f"the scenario ran ({type(e).__name__}: {e})"}]}
            results.append(r)
            print(f"{'PASS' if r['passed'] else 'FAIL'} {sc['id']}")
            for c in r["checks"]:
                print(f"   {'ok  ' if c['ok'] else 'FAIL'} [{c['turn'] if 'turn' in c else ''}] {c['check']}")
    finally:
        app.terminate()
        app.wait(30)
        (out / "app.log").write_bytes((work / "app.log").read_bytes())
    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} scenarios passed; {out}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
