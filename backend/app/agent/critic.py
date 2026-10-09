"""The Critic (the user, 2026-10-09: "a Critic Agent that will look at each slide from a trainee perspective also
considering UX aspects and starts a refinement loop with slides production when he feels some changes are required").

A generated outline, once written (agent/outline.py) and designed (agent/artist.py), is made into a draft deck in memory
on its template and each slide rendered (docengine/render.py, the editor's renderer); the model, which sees images (llm
.Models.vision), judges each as its audience would (preset slides_critic: readable, using its space, doing its task,
accurate, its form fitting, finished). A slide it would revise goes back - to the Artist for its form or accuracy, with
the Critic's fix as the wish; to the Writer for its task, substance, crowding or emptiness, from the slide's own text and
notes (no new facts), then to the Artist again - and is rendered and judged again, at most ROUNDS times. Each slide
keeps its version with the fewest issues, and the Critic's last word on it (shown in the outline review).

Measured before it was built (the model on rendered slides of a generated deck): it found small text and empty
slides, and a task the slide did not do; it said "good" to readable, full slides, "revise" to a sparse one; it missed
an invented column and invented diagram steps (those are the Artist's checks: agent/artist.checked)."""

from __future__ import annotations

import asyncio
import base64
import io
import logging

from ..docengine import ops, read, render
from . import artist, outline

log = logging.getLogger("slides.critic")

REVIEWED_ROLES = ("objectives", "content", "questions", "summary")
ROUNDS = 2  # revisions a slide gets; each judged again
CRITIC_TOKENS = 900
TO_ARTIST = ("form", "accuracy")  # issues the Artist answers; the others the Writer
# issues that can make a slide be revised: what the Writer and the Artist can put right from the slide's text. Its
# space, form and finish are the layout's and the Artist's, with their own checks: from the Critic, suggestions
# (measured: "must" for "too empty", "add an icon", "use boxes", every slide revised twice, its text padded)
MUST_KINDS = ("task", "accuracy", "readability")


def _json(text: str) -> dict | None:
    from .outline import loads

    return loads(text)


async def _ask(app, model: dict, preset: str, messages: list[dict], max_tokens: int) -> str:
    text = ""
    async for chunk in app.models.stream(model, preset, messages, None, max_tokens):
        text += ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
    return text


def _jpeg(png: bytes) -> str:
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _brief(slide: dict, goal: str, lang: str, rule: str = "") -> str:
    # its role and the rule its text was written to (measured: told its task alone, the Critic asked to revise a
    # questions slide because "a list of questions can look like a test", and a summary's takeaways for being facts)
    lines = [f"Write in {lang}.", f"Its role: {slide.get('role') or 'content'}" + (f" - {rule}" if rule else ""),
             f"The goal it serves: {goal or '(the presentation goals)'}", f"Its task: {slide.get('task') or '-'}",
             f"Its title: {slide.get('title') or ''}", "Its text:"]  # fmt: skip
    lines += [f"- {p}" for p in slide.get("points") or []] or ["(none)"]
    return "\n".join(lines)


async def judge(app, model: dict, png: bytes, slide: dict, goal: str, lang: str = "English", rule: str = "") -> dict | None:
    """The Critic's word on one rendered slide: {verdict, issues: [{kind, what, fix}]}, every issue saying what is wrong
    and how to fix it (the user, 2026-10-09: "the Critic must clearly state the issues observed and suggest how to fix
    those") - asked once more when one does not; or None when it did not answer. "revise" only for an issue that must
    be fixed (measured: asked for any issue, it asked to revise every slide in every round, often for the opposite of
    the last round's advice); the others ("could") kept as suggestions."""
    content = [{"type": "text", "text": _brief(slide, goal, lang, rule)}, {"type": "image_url", "image_url": {"url": _jpeg(png)}}]
    messages = [{"role": "user", "content": content}]
    for _ in range(2):
        try:
            text = await _ask(app, model, "slides_critic", messages, CRITIC_TOKENS)
        except Exception as e:  # noqa: BLE001 - no word: the slide stays as it is
            log.warning("the Critic did not answer", extra={"err.type": type(e).__name__})
            return None
        got = _json(text)
        if got is None or got.get("verdict") not in ("good", "revise"):
            return None
        issues = [{k: " ".join(str(i.get(k) or "").split()) for k in ("kind", "severity", "what", "fix")}
                  for i in got.get("issues") or [] if isinstance(i, dict)]  # fmt: skip
        for i in issues:
            i["severity"] = "must" if i["severity"] != "could" and i["kind"] in MUST_KINDS else "could"
        if all(i["what"] and i["fix"] for i in issues):
            must = any(i["severity"] == "must" for i in issues)
            return {"verdict": "revise" if got["verdict"] == "revise" and must else "good", "issues": issues}
        messages = [messages[0], {"role": "assistant", "content": text},
                    {"role": "user", "content": "Every issue must say what is wrong on this slide (what) and how to fix it "
                                                "(fix). Answer with the whole JSON again."}]  # fmt: skip
    kept = [i for i in issues if i["what"] and i["fix"]]
    must = any(i["severity"] == "must" for i in kept)
    return {"verdict": "revise" if got["verdict"] == "revise" and must else "good", "issues": kept}


async def _rewrite(app, model: dict, slide: dict, issues: list[dict], lang: str, goal: str, rule: str) -> dict:
    """The slide's points and notes written again by the Writer to answer the Critic, from the slide's own text and
    notes (nothing they do not say), by its role's rule (outline.KINDS; measured: asked for "3 to 5 bullets", a questions
    slide was written again as statements)."""
    ask = (f"In {lang}. Write this slide again: {slide['role']}, «{slide['title']}», serving {goal or 'the presentation goals'}. "
           f"Its task: {slide.get('task') or '-'}\nIts points now:\n" + "\n".join(f"- {p}" for p in slide.get("points") or [])
           + f"\nIts notes (what it is written from): {slide.get('notes') or '-'}\n"
           "A reviewer looked at the slide as its audience will see it, and said:\n"
           + "\n".join(f"- {i['what']} Fix: {i['fix']}" for i in issues)
           + (("\nKey points of its subject no other slide uses - take from them what its task needs, nothing else:\n"
               + "\n".join(f"- {x}" for x in slide["_spare"])) if slide.get("_spare") else "")
           + f"\nWrite it again to fix that, with only what its points, its notes and those key points say. {rule}")  # fmt: skip
    got = _json(await _ask(app, model, "slides_writer", [{"role": "user", "content": ask}], 6000)) or {}
    bullets = outline.bullets_of(got.get("points"))
    if not bullets:
        return slide
    notes = str(got.get("notes") or "").strip()
    answers = [" ".join(str(a).split()) for a in got.get("answers") or [] if str(a).strip()]
    if slide.get("role") == "questions" and answers:
        notes = "Respostas:\n" + "\n".join(f"{n}. {a}" for n, a in enumerate(answers, start=1))
    out = {**slide, "points": bullets, **({"notes": notes} if notes else {})}
    return {k: v for k, v in out.items() if k != "design"}


async def _revise(app, model: dict, slide: dict, review: dict, lang: str, goal: str, goal_kind: str, before: list[str],
                  rule: str) -> dict:  # fmt: skip
    """A slide changed as the Critic asked: its form by the Artist (the fix as its wish), or its text by the Writer and
    then its form again."""
    planned = {**slide, "goal_text": goal} if goal else slide
    issues = [i for i in review["issues"] if i["severity"] == "must"]  # the suggestions are the person's to take
    for_artist = [i for i in issues if i["kind"] in TO_ARTIST]
    if slide.get("role") in artist.DESIGNED_ROLES and for_artist and len(for_artist) == len(issues):
        wish = " ".join(i["fix"] for i in for_artist)
        return {**slide, "design": await artist.design(app, model, planned, before, wish=wish, kind=goal_kind)}
    rewritten = await _rewrite(app, model, slide, issues, lang, goal, rule)
    if rewritten is not slide and slide.get("role") in artist.DESIGNED_ROLES:
        rewritten["design"] = await artist.design(app, model, {**rewritten, "goal_text": goal}, before, kind=goal_kind)
    return rewritten


async def _render(app, blank: bytes, slides: list[dict], cache) -> dict[int, bytes]:
    """The draft deck made on its template, slide by slide; the image of each outline slide's first slide, by index."""

    def make() -> tuple[bytes, list[int]]:
        prs = read.open_deck(blank)
        first, after = [], None
        for item in slides:
            got = ops.add_outline(prs, [item], after_slide_id=after)
            first.append(got["slides"][0] if got["slides"] else 0)
            after = got["slides"][-1] if got["slides"] else after
        buf = io.BytesIO()
        prs.save(buf)
        return buf.getvalue(), first

    data, first = await asyncio.to_thread(make)
    keys = await render.ensure(data, cache, only={x for x in first if x})
    key_of = {k["id"]: k["key"] for k in keys}
    out = {}
    for i, sid in enumerate(first):
        path = cache / key_of[sid] / "preview.png" if sid in key_of else None
        if path is not None and path.exists():
            out[i] = path.read_bytes()
    return out


async def refine(app, model: dict, blank: bytes, slides: list[dict], goals: list[str], goal_kind: str, lang: str,
                 cache, progress, kind: str = "training") -> list[dict]:  # fmt: skip
    """The outline's slides, each judged as rendered and revised while the Critic asks, at most ROUNDS times; each the
    version with the fewest issues, with the Critic's last word on it ("review")."""
    current = list(slides)
    todo = [i for i, s in enumerate(slides) if s.get("role") in REVIEWED_ROLES]
    best: dict[int, tuple[int, dict, dict]] = {}
    judged = 0
    for round_ in range(ROUNDS + 1):
        images = await _render(app, blank, current, cache)
        again = []
        for n, i in enumerate(todo):
            await progress("reviewing", n, len(todo))
            judged += 1
            if i not in images:
                continue
            goal = goals[current[i]["goal"] - 1] if 1 <= (current[i].get("goal") or 0) <= len(goals) else ""
            rules = outline.KINDS[kind]["write"]
            rule = rules.get(current[i].get("role"), rules["content"])
            review = await judge(app, model, images[i], current[i], goal, lang, rule)
            if review is None:
                continue
            count = sum(x["severity"] == "must" for x in review["issues"]) if review["verdict"] == "revise" else 0
            if i not in best or count < best[i][0]:
                best[i] = (count, current[i], review)
            if count and round_ < ROUNDS:
                before = [s["design"]["form"] for s in current[max(0, i - 2) : i] if s.get("design")]
                try:
                    current[i] = await _revise(app, model, current[i], review, lang, goal, goal_kind, before, rule)
                except Exception as e:  # noqa: BLE001 - a revision that fails leaves the slide as it was, the rest made
                    log.warning("a slide could not be revised", extra={"err.type": type(e).__name__})
                    continue
                again.append(i)
        log.info("slides reviewed", extra={"round": round_, "slideCount": len(todo), "revisedCount": len(again)})
        todo = again
        if not todo:
            break
    await progress("reviewing", 1, 1)
    log.info("deck reviewed", extra={"judgedCount": judged})
    out = []
    for i, s in enumerate(slides):
        if i in best:
            _, kept, review = best[i]
            out.append({**kept, "review": review})
        else:
            out.append(s)
    return out
