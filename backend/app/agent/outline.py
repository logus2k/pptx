"""An outline of slides from a source (spec NL-12): a project's reference document, a knowledge-base document, or
what the knowledge base holds on a topic; for a corporate presentation or a training. The application reads the whole
source - in parts that fit the model's window, never a part of it left unread - asks the model for each part's key
points (prompts/points.md, with where each comes from), then for an outline of the kind asked for
(prompts/outline.md, with the kind's structure below). The outline is shown to the person, who may edit it, before the
slides are made (domain/generations.py).

A 4B model with a 32K window cannot read a document and plan slides in one answer; read in parts, each answer is
small and checkable. A document too large to read in MAX_PARTS parts is refused with its size: the person narrows it
(a section, a focus), rather than having slides made from a part of it. Points too many for one outline request are
condensed by the same reading, again in parts (never cut)."""

from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("slides.outline")

PART_TOKENS = 6000  # a part's passages: what a 4B model reads well at once
MAX_PARTS = 30  # a document: about 180 000 tokens, some 150 pages
TOPIC_PASSAGES = 20  # the knowledge base's search answers at most 20
TOPIC_DOCUMENTS = 8  # a topic: the documents its best passages come from, read whole, while they fit TOPIC_PARTS
# (measured: a training on "crédito à habitação" read 3 of the 6 documents its passages came from - 75 passages, 5 parts,
# 21 s - and the process's phases, its costs and its servicing were one passage each)
TOPIC_PARTS = 12
POINTS_TOKENS = 1500
PLAN_TOKENS = 10000  # the goals and storyboard (titles, tasks, key point numbers), after its thinking
WRITE_TOKENS = 6000  # one slide's bullets and notes, after its thinking

# what each kind of deck is (the person's choice; spec NL-12 and the user's two cases, 2026-10-07): its structure, for
# the Planner, and how each role's slide is written, for the Writer
KINDS = {
    "corporate": {
        "slides": (4, 12, 8),  # at least, at most, by default
        "structure": (
            "A corporate presentation{audience}: its modules are its parts, in the order a presentation flows - the "
            "situation first, conclusions or next steps last; each slide's title is its key message."
        ),
        "write": {
            "content": "3 to 5 bullets, at most 12 words each, that support the slide's message. Notes: two or three "
                       "sentences the presenter says about the slide.",
        },
    },
    "training": {
        "slides": (8, 24, 14),
        "structure": (
            "A training{audience} that a trainer will deliver: opened by its goals, then its modules - each opened by a "
            "slide that names it and says its aim - then questions that check the goals, and a summary."
        ),
        "write": {
            "objectives": "Its bullets are the goals, as given. Notes: what the trainer says to open the training, two or "
                          "three sentences.",
            "section": "One bullet: what the audience will learn in this module, said to them in one sentence (never an "
                       "instruction such as \"Introduzir o módulo\"). Notes: one or two sentences the trainer says to open "
                       "the module.",
            "content": "3 to 5 bullets, at most 15 words each, with the rules, figures, steps and examples its key points "
                       "give; a process or a sequence: one bullet a step, every step, in order, each as its key points "
                       "describe it - when they only name it, its name alone, never a description of your own. Notes: what "
                       "the trainer says, 3 to 6 sentences explaining the slide, from its key points.",
            "questions": "One question for each goal, in the goals' order, each answered by what the slides before it "
                         "say. Answer with {\"points\": [the questions], \"answers\": [the answer to each, from those "
                         "slides, in the same order]}.",
            "summary": "One takeaway for each goal, from what the slides before it say, at most 15 words each. Notes: "
                       "what the trainer says to close, two or three sentences.",
        },
    },
}
ROLES = ("content", "objectives", "section", "questions", "summary")


class SourceTooLarge(Exception):
    pass


class SourceEmpty(Exception):
    pass


async def _kb_document(app, email: str, domain: str, path: str) -> tuple[str, list[dict]]:
    out, after, title = [], 0, path
    while True:
        r = await asyncio.to_thread(app.kb.document_passages, email, domain, path, after, 200)
        title = r.get("title") or title
        got = r.get("passages") or []
        for p in got:
            where = p.get("section") or (f"p. {p['page']}" if p.get("page") else "")
            out.append({"text": p.get("text", ""), "where": where, "document": title, "link": p.get("link")})
        if not got or r.get("next") is None:
            return title, out
        after = r["next"]


async def gather(app, email: str, pid: str, source: dict, domains: list[str] | None, count) -> tuple[str, list[dict]]:
    """(the source's title, its passages in reading order: [{text, where, document, link?}])."""
    kind = source.get("kind")
    if kind == "document":
        asset = app.assets.get(pid, source["asset_id"])
        passages = app.assets.passages(pid, source["asset_id"])
        return asset["name"], [{"text": p["text"], "where": p.get("where") or "", "document": asset["name"]} for p in passages]
    if kind == "kb_document":
        return await _kb_document(app, email, source["domain"], source["path"])
    if kind == "kb_topic":
        # the topic's best passages, then the documents they come from read whole while they fit (measured: 20
        # passages are a few paragraphs of one document; a training needs the whole of its rules and steps)
        r = await asyncio.to_thread(app.kb.search, email, source["query"], domains, TOPIC_PASSAGES)
        hits = r.get("passages") or []
        out, seen_docs, size = [], [], 0
        for p in hits:
            key = (p.get("domain"), p.get("document"))
            if p.get("domain") and p.get("document") and key not in seen_docs:
                seen_docs.append(key)
        for domain, path in seen_docs[:TOPIC_DOCUMENTS]:
            _, passages = await _kb_document(app, email, domain, path)
            tokens = sum(count(_line(x)) for x in passages)
            if out and size + tokens > TOPIC_PARTS * PART_TOKENS:
                continue  # a document that would make the topic too long to read: its best passages stand for it
            out += passages
            size += tokens
        read_docs = {x["document"] for x in out}
        for p in hits:  # the passages of the documents not read whole
            document = p.get("title") or p.get("document") or ""
            if document not in read_docs:
                where = p.get("section") or (f"p. {p['page']}" if p.get("page") else "")
                out.append({"text": p.get("text", ""), "where": where, "document": document, "link": p.get("link")})
        return source["query"], out
    raise ValueError(f"unknown source kind {kind!r}")


def _without_repeated_sentences(passages: list[dict]) -> list[dict]:
    """The passages with each document's sentences given once: a sentence (40 characters or more) a document already
    gave, in an earlier passage, left out - a passage left with nothing, left out (measured: a knowledge base's passages
    overlap - 147 sentences of a training's source were in two passages or more - and the same fact came back as two
    key points, then on two slides). Exact text: a lexical fact."""
    seen: dict[str, set[str]] = {}
    out = []
    for p in passages:
        mine = seen.setdefault(p["document"], set())
        kept = []
        for sentence in p["text"].split(". "):
            key = " ".join(sentence.split())
            if len(key) >= 40 and key in mine:
                continue
            mine.add(key)
            kept.append(sentence)
        text = ". ".join(kept)
        if text.strip():
            out.append({**p, "text": text})
    return out


def _line(p: dict) -> str:
    where = " · ".join(x for x in (p.get("document"), p.get("where")) if x)
    return f"[{where}] {' '.join(p['text'].split())}"


def _parts(lines: list[str], count, limit: int = PART_TOKENS, docs: list[str] | None = None) -> list[list[str]]:
    """The lines in parts of at most `limit` tokens, in order; with each line's document (docs), a part never holds two
    documents (measured: a part with the end of one document and the phases of another gave 12 points - its cap - to the
    first, and the second's seven phases went unnamed)."""
    parts, current, size = [], [], 0
    for i, line in enumerate(lines):
        n = count(line)
        if current and (size + n > limit or (docs is not None and docs[i] != docs[i - 1])):
            parts.append(current)
            current, size = [], 0
        current.append(line)
        size += n
    if current:
        parts.append(current)
    return parts


def answer_of(text: str) -> str:
    """A model's answer without its thinking (<think>...</think>, from the presets that think: llm.PRESETS)."""
    return text.split("</think>", 1)[1] if "</think>" in text else text


# LaTeX a model writes for symbols, in the plain characters a slide shows (measured: "EPIC $\\rightarrow$ FEATURE" from
# the Writer, and "$\\ge 60\\%$" earlier, though its rules ask for plain text: a guard on its output, the rule kept)
LATEX = (("\\rightarrow", "→"), ("\\leftarrow", "←"), ("\\Rightarrow", "⇒"), ("\\to", "→"), ("\\geq", "≥"),
         ("\\leq", "≤"), ("\\ge", "≥"), ("\\le", "≤"), ("\\times", "\u00d7"), ("\\cdot", "·"), ("\\approx", "≈"),
         ("\\neq", "≠"), ("\\pm", "±"), ("\\%", "%"), ("\\&", "&"), ("\\euro", "€"))  # fmt: skip


def plain(text: str) -> str:
    """A slide's text with LaTeX symbols as their characters and the $ that wrapped them left out."""
    if "\\" not in text and "$" not in text:
        return text
    for command, char in LATEX:
        text = text.replace(command, char)
    if text.count("$") >= 2:  # math delimiters, not an amount in dollars
        text = text.replace("$", "")
    return " ".join(text.split())


def balanced(text: str) -> str:
    """JSON text with each closing bracket the one its opening needs, outside strings, and closers with nothing open
    dropped (measured: the Artist closed a list of points with "}" and added one more closer, "...cliente."}]}]}" - 9
    of 36 answers; repaired, all 9 parsed with their columns whole, and 56 valid answers came out unchanged)."""
    out, stack, in_str, esc = [], [], False, False
    for c in text:
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if not stack:
                continue  # nothing open to close
            c = stack.pop()
        out.append(c)
    return "".join(out) + "".join(reversed(stack))


def loads(text: str) -> dict | None:
    """The JSON object in a model's answer (its thinking left out), its brackets mended when it is not valid JSON."""
    text = answer_of(text)
    body = text[text.find("{") : text.rfind("}") + 1]
    for candidate in (body, balanced(body)):
        try:
            got = json.loads(candidate)
            return got if isinstance(got, dict) else None
        except ValueError:
            continue
    return None


def _json(text: str) -> dict | None:
    return loads(text)


async def _ask(app, model, preset: str, content: str | list[dict], max_tokens: int) -> str:
    text = ""
    messages = [{"role": "user", "content": content}] if isinstance(content, str) else content
    async for chunk in app.models.stream(model, preset, messages, None, max_tokens):
        text += ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
    return text


def topic_of(passage: dict, by_section: bool) -> tuple[str, str]:
    """A passage's topic, and the words that name it in a key point's "where": its document, when the source has
    several; else its document's top section (a single document read whole: one topic would make one goal)."""
    if not by_section:
        return passage["document"], passage["document"]
    head = str(passage.get("where") or "").split(" > ")[0].strip()
    return (f"{passage['document']} · {head}" if head else passage["document"]), (head or passage["document"])


def topic_from(where: str, candidates: list[tuple[str, str]]) -> str:
    """The topic a key point comes from: the one of its part's topics its "where" names (the longest name that is in it:
    a lexical fact), else the part's first."""
    named = [t for t, needle in sorted(candidates, key=lambda c: len(c[1]), reverse=True) if needle and needle in (where or "")]
    return named[0] if named else (candidates[0][0] if candidates else "")


async def _points(app, model, title: str, parts: list[list[str]], progress, stage: str,
                  topics: list[list[tuple[str, str]]], lang: str) -> list[dict]:  # fmt: skip
    """Each part's key points, each with the topic it comes from (topics: each part's topics, topic_of)."""
    points: list[dict] = []
    for i, part in enumerate(parts):
        await progress(stage, i, len(parts))
        # the language said (measured: a part of a Portuguese document, its points all in English, the instructions being
        # in English)
        # its points' cap by its size: a passage a point, 12 to 24 (measured: a document's 15 passages with 7 phases,
        # read under a fixed cap of 12, ran out at phase 6 once in 4)
        most = max(12, min(24, len(part)))
        ask = f"Part {i + 1} of {len(parts)} of «{title}». Write the points in {lang}, at most {most}:\n" + "\n".join(part)
        got = _json(await _ask(app, model, "slides_points", ask, POINTS_TOKENS)) or {}
        for x in got.get("points") or []:
            if isinstance(x, dict) and str(x.get("point") or "").strip():
                points.append({**x, "topic": topic_from(str(x.get("where") or ""), topics[i])})
    await progress(stage, len(parts), len(parts))
    return points


SAME_FACT = 0.998  # the reranker's score, both ways, at which two key points say the same thing (measured: the same
# fact reworded scored 0.982-1.000 both ways and two different facts up to 0.979 in one training, 0.9957 in another - a
# fact repeated is better than a fact lost, so only near-identical points are merged; most repeats are now removed at
# reading: _without_repeated_sentences)


async def _without_repeats(app, points: list[dict]) -> list[dict]:
    """The key points, each fact once: a point the reranker scores as saying what an earlier point of its topic says
    (both ways, SAME_FACT) merged into it, the fuller wording kept (measured: a document's own summary repeated its
    sections, and two slides taught the same 0,6% spread). Without the reranker, as they are."""
    reranker = getattr(app, "reranker", None)
    if reranker is None or not reranker.available:
        log.info("no reranker: key points not checked for repeats")
        return points
    from ..search import SearchUnavailable

    kept: list[dict] = []
    try:
        for p in points:
            mine = [k for k, q in enumerate(kept) if q.get("topic") == p.get("topic")]
            if mine:
                ahead = await asyncio.to_thread(reranker.scores, p["point"], [kept[k]["point"] for k in mine])
                best = max(range(len(mine)), key=lambda i: ahead[i])
                if ahead[best] >= SAME_FACT:
                    k = mine[best]
                    back = (await asyncio.to_thread(reranker.scores, kept[k]["point"], [p["point"]]))[0]
                    if back >= SAME_FACT:
                        if len(p["point"]) > len(kept[k]["point"]):
                            kept[k] = p
                        continue
            kept.append(p)
    except SearchUnavailable:
        log.warning("the reranker did not answer: key points not checked for repeats")
        return points
    if len(kept) < len(points):
        log.info("key points said twice merged", extra={"pointCount": len(points), "keptCount": len(kept)})
    return kept


def _numbers(refs) -> list[int]:
    """Key point numbers as the Planner wrote them ("P3", "3", 3), in order, each once."""
    out: list[int] = []
    for r in refs if isinstance(refs, list) else []:
        text = str(r).strip().upper().removeprefix("P")
        if text.isdigit() and int(text) not in out:
            out.append(int(text))
    return out


def modules_of(kind: str, wanted: int) -> tuple[int, int]:
    """(how many modules, how many content slides) for a deck of `wanted` slides: a training's objectives, questions
    and summary and a section slide a module around its content slides; a corporate deck all content, in parts."""
    # (measured: 12 slides as 3 modules left 6 content slides for 5 goals, and the modules each joined two subjects)
    if kind != "training":
        return (2 if wanted <= 6 else 3), wanted
    modules = 2 if wanted <= 12 else 3 if wanted <= 18 else 4
    return modules, wanted - 3 - modules


def goals_for(content: int) -> int:
    """How many goals a deck of `content` content slides can teach well: two slides or so each."""
    return 3 if content <= 7 else 4 if content <= 10 else 5


def shares(content: int, modules: int, weights: list[int] | None = None) -> list[int]:
    """Content slides a module: in proportion to how much each has to teach (weights: its key points), one at least,
    the largest remainders taking what is left (measured: shared evenly, a module of 59 key points - the process's
    seven phases, servicing, works, costs - had 3 slides, and its phases became one overview line); without weights,
    as even as they divide."""
    if not weights or len(weights) != modules or sum(weights) <= 0 or content < modules:
        return [content // modules + (1 if m < content % modules else 0) for m in range(modules)]
    rest = content - modules  # one each, then the rest by weight
    exact = [rest * w / sum(weights) for w in weights]
    out = [1 + int(x) for x in exact]
    for m in sorted(range(modules), key=lambda m: exact[m] - int(exact[m]), reverse=True)[: content - sum(out)]:
        out[m] += 1
    return out


def _frame(got: dict) -> tuple[list[str], list[list[int]], list[dict]]:
    """(the goals, each goal's topics (numbers), the modules: [{title, aim, goals}]) as the Planner answered."""
    goals, topics = [], []
    for g in got.get("goals") or []:
        text = g.get("goal") if isinstance(g, dict) else g
        if str(text or "").strip():
            goals.append(" ".join(str(text).split()))
            topics.append(_numbers([str(t).strip().upper().removeprefix("T") for t in g.get("topics") or []])
                          if isinstance(g, dict) else [])  # fmt: skip
    modules = []
    for m in got.get("modules") or []:
        if isinstance(m, dict) and str(m.get("title") or "").strip():
            modules.append({"title": " ".join(str(m["title"]).split()), "aim": " ".join(str(m.get("aim") or "").split()),
                            "goals": _numbers(m.get("goals"))})  # fmt: skip
    return goals, topics, modules


def frame_problems(goals: list[str], topics: list[list[int]], modules: list[dict], wanted: int, n_goals: int,
                   n_topics: int) -> list[str]:  # fmt: skip
    """What the goals and modules get wrong, said so the Planner can correct it: each goal anchored to the topics -
    the source's documents - that teach it, so it is taught from their key points (measured: asked to anchor goals to
    key point numbers out of 80, the model gave a goal on the Crédito Habitação Jovem the documentation's points, and
    no slide taught it)."""
    out = []
    if len(goals) != n_goals:
        out.append(f"There are {len(goals)} goals: give exactly {n_goals}.")
    # a topic may teach more than one goal (measured: one large document held most of a training's subject; tied to one
    # goal, another goal was tied to a thin document, and its slide was "follow the guidelines"); a key point is still
    # taught once: a module does not see those an earlier one used
    for g, (goal, mine) in enumerate(zip(goals, topics, strict=True), start=1):
        if not [t for t in mine if 1 <= t <= n_topics]:
            out.append(f"Goal {g} («{goal}»): give the topics that teach it (T1 to T{n_topics}).")
    if len(modules) != wanted:
        out.append(f"There are {len(modules)} modules: make exactly {wanted}.")
    for n, m in enumerate(modules, start=1):
        if not m["aim"]:
            out.append(f"Module {n} («{m['title']}»): say its aim.")
        elif len(m["aim"].split()) > 18:  # (looked at: a 20-word aim set small and squeezed on its divider)
            out.append(f"Module {n} («{m['title']}»): its aim has {len(m['aim'].split())} words: say it in at most 15.")
        if not m["goals"] or any(not 1 <= g <= len(goals) for g in m["goals"]):
            out.append(f"Module {n} («{m['title']}»): its goals must be numbers of the goals (1 to {len(goals)}).")
    served: dict[int, int] = {}
    for n, m in enumerate(modules, start=1):
        for g in m["goals"]:
            if g in served:
                out.append(f"Goal {g} is in modules {served[g]} and {n}: a goal is served by one module.")
            served.setdefault(g, n)
    out += [f"Goal {g} («{goal}») is served by no module." for g, goal in enumerate(goals, start=1) if g not in served]
    titles = [m["title"].casefold() for m in modules]
    out += [f"Two modules have the title «{t}»: each its own." for t in sorted({t for t in titles if titles.count(t) > 1})]
    return out


def _content(got: dict) -> list[dict]:
    """A module's slides as the Planner answered them: [{role, title, goal, task, refs}] (refs: the module's numbers)."""
    out = []
    for s in got.get("slides") or []:
        if not isinstance(s, dict) or not str(s.get("title") or "").strip():
            continue
        try:
            goal = int(s.get("goal") or 0)
        except (TypeError, ValueError):
            goal = 0
        out.append({"role": "content", "title": " ".join(str(s["title"]).split()), "goal": goal,
                    "task": " ".join(str(s.get("task") or "").split()), "refs": _numbers(s.get("points"))})  # fmt: skip
    return out


def problems(module: dict, slides: list[dict], want: int, count: int) -> list[str]:
    """What a module's slides get wrong, each said so the Planner can correct it (the user, 2026-10-09: "a coherent
    storyboard based on clearly defined goals"): its number of slides, each slide one of its goals, a task and its own
    key points, every goal of the module taught."""
    if not slides:
        return ["There are no slides: answer with the JSON asked for."]
    out = []
    if len(slides) != want:
        out.append(f"There are {len(slides)} slides: give exactly {want}.")
    seen: dict[int, int] = {}
    for n, s in enumerate(slides, start=1):
        name = f"Slide {n} («{s['title']}»)"
        if s["goal"] not in module["goals"]:
            out.append(f"{name}: its goal must be one of this module's goals ({', '.join(map(str, module['goals']))}).")
        if module["title"].casefold() in s["title"].casefold():
            # (looked at: a module and its first slide both «Tipos de Crédito e Condições Gerais», one after the other;
            # «Objetivo do Módulo: Do Pedido à Gestão do Crédito», a slide about the module, its points what it covers)
            out.append(f"{name} is about the module itself: the module's opening slide says its aim; give this slide one "
                       "idea from the key points.")
        if not s["task"]:
            out.append(f"{name}: say its task.")
        refs = [r for r in s["refs"] if 1 <= r <= count]
        if len(refs) < len(s["refs"]):
            out.append(f"{name}: there are key points P1 to P{count} only.")
        if not refs:
            out.append(f"{name}: give the numbers of the key points it uses.")
        for r in refs:
            if r in seen:
                out.append(f"P{r} is on slides {seen[r]} and {n}: keep it on one.")
            else:
                seen[r] = n
    if len(slides) >= len(module["goals"]):
        served = {s["goal"] for s in slides}
        out += [f"Goal {g} has no slide: give it one." for g in module["goals"] if g not in served]
    titles = [s["title"].casefold() for s in slides]
    out += [f"Two slides have the title «{t}»: each slide its own." for t in sorted({t for t in titles if titles.count(t) > 1})]
    return out


def topic_problems(slides: list[dict], per: list[int] | None, of: dict[int, int], order: list[str]) -> list[str]:
    """With the module's slides shared across its topics (per), what the slides get wrong: a slide drawing on two topics,
    a topic with more or fewer slides than its share. A slide's topic is the one most of its key points come from."""
    if per is None:
        return []
    out, count = [], [0] * len(order)
    for n, s in enumerate(slides, start=1):
        mine = [of[r] for r in s["refs"] if r in of]
        if not mine:
            continue
        if len(set(mine)) > 1:
            names = " and ".join(f"«{order[t]}»" for t in sorted(set(mine)))
            out.append(f"Slide {n} («{s['title']}») takes key points from {names}: a slide takes them from one topic.")
        count[max(set(mine), key=mine.count)] += 1
    for t, (have, want) in enumerate(zip(count, per, strict=True)):
        if have != want:
            out.append(f"Topic «{order[t]}» has {have} slides: give it exactly {want}.")
    return out


def _repair(slides: list[dict], count: int) -> list[dict]:
    """What the Planner left wrong after being asked again, put right where the application can: key point numbers that
    do not exist dropped, a key point on two slides kept on the first, a slide left with no key points removed."""
    seen: set[int] = set()
    out = []
    for s in slides:
        refs = [r for r in s["refs"] if 1 <= r <= count and r not in seen]
        seen.update(refs)
        if refs:
            out.append({**s, "refs": refs})
    return out


PLAN_TRIES = 3
FRAME = {  # the slides the application adds around the planned ones, in the deck's language
    "pt": {"objectives": "Objetivos da formação", "questions": "Verifique o que aprendeu", "summary": "Em resumo"},
    "en": {"objectives": "Objectives", "questions": "Check what you learnt", "summary": "In summary"},
}
FRAME_TASKS = {"objectives": "Open the training with its goals.", "questions": "Check each goal with one question.",
               "summary": "Close with one takeaway for each goal."}  # fmt: skip


async def _asked(app, model, preset: str, first: str, check, stage: str):
    """The Planner's answer to one request, checked (check(answer) -> (parsed, problems)) and asked again with its
    last answer and what is wrong in it - never the earlier ones, so the request stays the size it was measured for -
    at most PLAN_TRIES times; the answer with the fewest problems."""
    messages = [{"role": "user", "content": first}]
    best = None
    for attempt in range(1, PLAN_TRIES + 1):
        text = await _ask(app, model, preset, messages, PLAN_TOKENS)
        parsed, wrong = check(_json(text) or {})
        log.info("plan checked", extra={"step": stage, "attempt": attempt, "problemCount": len(wrong)})
        if best is None or len(wrong) < best[0]:
            best = (len(wrong), parsed)
        if not wrong:
            break
        again = "Correct these and answer with the whole JSON again:\n- " + "\n- ".join(wrong)
        messages = [messages[0], {"role": "assistant", "content": answer_of(text)}, {"role": "user", "content": again}]
    return best[1]


def topics_of(points: list[dict], title: str) -> list[str]:
    """The source's topics (topic_of) its key points come from, in reading order."""
    out: list[str] = []
    for p in points:
        name = p.get("topic") or title
        if name not in out:
            out.append(name)
    return out


async def plan(app, model: dict, kind: str, wanted: int, intro: str, points: list[dict], title: str, language: str,
               progress) -> dict:  # fmt: skip
    """The Planner's storyboard, in steps it does well, the bookkeeping the application's (measured: asked for a whole
    deck's slides at once, it planned 15 or 14 for 12, three times in three; asked to give goals and slides key point
    numbers out of 80, it gave them the wrong ones): the goals, each with the topics - the source's documents - that
    teach it, and the modules; then each module's slides from its goals' key points only, their number given. Each
    step checked and asked again; the application then adds the slides around them - a training's objectives, a
    section slide a module, its questions and summary. {title, goals, modules, slides: [{role, title, goal, task,
    refs}]} (refs: indices + 1 into points)."""
    n_modules, n_content = modules_of(kind, wanted)
    slides_intro = intro.split("\n", 1)[0] + "\nThe application opens each module with a slide of its own: plan the "  \
        "slides that teach it."  # fmt: skip
    topics = topics_of(points, title)
    n_goals = goals_for(n_content)  # (topics may serve more than one goal: one large document can teach several)
    lines = []
    for t, name in enumerate(topics, start=1):
        mine = [p for p in points if (p.get("topic") or title) == name]
        lines.append(f"T{t}. {name} ({len(mine)} key points):")
        lines += [f"  - {p['point']}" for p in mine]
    await progress("planning", 0, n_modules + 1)

    def frame_check(got):
        goals, gtopics, modules = _frame(got)
        wrong = frame_problems(goals, gtopics, modules, n_modules, n_goals, len(topics))
        return (str(got.get("title") or ""), goals, gtopics, modules), wrong

    first = f"{intro}\nGive {n_goals} goals and make {n_modules} modules.\nThe topics:\n" + "\n".join(lines)
    deck_title, goals, gtopics, modules = await _asked(app, model, "slides_planner", first, frame_check, "frame")
    modules = [m for m in modules if m["goals"]][:n_modules] or [
        {"title": deck_title or title, "aim": "", "goals": list(range(1, len(goals) + 1))}]  # none usable: one of all goals
    weight = []
    for module in modules:
        names = {topics[t - 1] for g in module["goals"] if 1 <= g <= len(goals) for t in gtopics[g - 1] if 1 <= t <= len(topics)}
        weight.append(sum(1 for p in points if (p.get("topic") or title) in names))
    share = shares(n_content, len(modules), weight)
    goal_lines = ["The goals:"] + [f"{g}. {x}" for g, x in enumerate(goals, start=1)]
    planned: list[list[dict]] = []
    for m, module in enumerate(modules, start=1):
        await progress("planning", m, len(modules) + 1)
        names = {topics[t - 1] for g in module["goals"] if 1 <= g <= len(goals) for t in gtopics[g - 1] if 1 <= t <= len(topics)}
        taken = {r - 1 for slides in planned for s in slides for r in s["refs"]}  # an earlier module's key points
        order = [t for t in topics if t in names and any((p.get("topic") or title) == t and i not in taken
                                                         for i, p in enumerate(points))]  # its topics, in reading order
        mine = [i for t in order for i, p in enumerate(points) if (p.get("topic") or title) == t and i not in taken]
        want = min(share[m - 1], len(mine))
        if not mine or not want:
            planned.append([])
            continue
        # its slides shared across its topics too, in proportion to their key points, when there are slides enough for
        # one each (measured: two documents in one goal, one slide drew on both - CH Jovem with works and construction
        # - and CH Jovem's key facts did not fit)
        sizes = [sum(1 for i in mine if (points[i].get("topic") or title) == t) for t in order]
        per = shares(want, len(order), sizes) if len(order) > 1 and want >= len(order) else None
        of = {k: order.index(points[i].get("topic") or title) for k, i in enumerate(mine, start=1)}  # P number -> topic
        listed, k = [], 1
        for n, t in enumerate(order):
            if per is not None:
                listed.append(f"Topic «{t}» - {per[n]} slide{'s' if per[n] > 1 else ''}:")
            for i in mine[k - 1 : k - 1 + sizes[n]]:
                listed.append(f"P{k}. {points[i]['point']} ({points[i].get('where') or title})")
                k += 1
        # its aim not given: the module's opening slide says it (measured: given it, the model made the module's first
        # slide "Objetivo do Módulo: ...", its points the aim again, in 2 modules of 2)
        # the deck's structure not given either: it says a module is "opened by a slide that names it and says its
        # aim", and the model planned that slide itself, as the module's first (measured: 2 modules of 2), though the
        # application adds it
        # the slides earlier modules have, so a topic two modules share is not taught twice in other words (measured:
        # DoR and DoD, a slide in each of two modules)
        before = [f"- {s['title']}: {s['task']}" for slides in planned for s in slides]
        ask = (f"{slides_intro}\n" + "\n".join(goal_lines)
               + ("\nThe slides of the modules before this one (do not teach their subjects again):\n" + "\n".join(before)
                  if before else "")
               + f"\nThis module: «{module['title']}» - it serves goals {', '.join(map(str, module['goals']))} - {want} "
               f"slides.\nIts key points:\n" + "\n".join(listed))

        def check(got, module=module, want=want, k=len(mine), per=per, of=of, order=order):
            slides = _content(got)
            return slides, problems(module, slides, want, k) + topic_problems(slides, per, of, order)

        local = _repair(await _asked(app, model, "slides_storyboard", ask, check, f"module {m}"), len(mine))
        # a slide about the module itself, still there after the tries, left out: the module's opening slide says its
        # aim (measured: "Objetivos da Formação: <the module's title>" kept by the best of three answers)
        local = [s for s in local if module["title"].casefold() not in s["title"].casefold()]
        planned.append([{**s, "refs": [mine[r - 1] + 1 for r in s["refs"]]} for s in local])
    await progress("planning", len(modules) + 1, len(modules) + 1)
    words = FRAME.get(language, FRAME["en"])
    if kind != "training":
        out = [s for slides in planned for s in slides]
    else:
        out = [{"role": "objectives", "title": words["objectives"], "goal": 0, "task": FRAME_TASKS["objectives"], "refs": []}]
        for module, slides in zip(modules, planned, strict=True):
            if slides:  # a module left with no slides is not opened
                out.append({"role": "section", "title": module["title"], "goal": 0, "task": module["aim"], "refs": []})
                out += slides
        out += [{"role": r, "title": words[r], "goal": 0, "task": FRAME_TASKS[r], "refs": []} for r in ("questions", "summary")]
    log.info("storyboard planned", extra={"slideCount": len(out), "goalCount": len(goals), "moduleCount": len(modules),
                                          "topicCount": len(topics)})  # fmt: skip
    # each goal's topics by name: the key points a slide's subject has (the Critic's revisions may draw on those no
    # slide uses: spare_of)
    taught = [[topics[t - 1] for t in mine if 1 <= t <= len(topics)] for mine in gtopics]
    return {"title": " ".join(deck_title.split()), "goals": goals, "modules": modules, "slides": out, "taught": taught}


def spare_of(slides: list[dict], points: list[dict], taught: list[list[str]], title: str) -> list[list[str]]:
    """For each slide, the key points of its goal's topics that no slide uses, as the Writer reads them ("point
    (where)"): what a revision may add when the Critic finds the slide's task undone (measured: a slide to show the
    seven phases was given phases 1 to 5; the Critic saw it, and its revision, from the slide's own points, could not)."""
    used = {r for s in slides for r in s.get("refs") or []}
    out = []
    for s in slides:
        names = set(taught[s["goal"] - 1]) if 1 <= (s.get("goal") or 0) <= len(taught) else set()
        out.append([f"{p['point']} ({p.get('where') or title})" for i, p in enumerate(points)
                    if (p.get("topic") or title) in names and i + 1 not in used])  # fmt: skip
    return out


def _board(goals: list[str], slides: list[dict]) -> str:
    lines = ["The goals:"] + [f"{g}. {x}" for g, x in enumerate(goals, start=1)] + ["The storyboard:"]
    for n, s in enumerate(slides, start=1):
        goal = f", goal {s['goal']}" if s.get("goal") else ""
        lines.append(f"{n}. {s['role']}{goal}: {s['title']} - {s.get('task') or ''}")
    return "\n".join(lines)


async def write(app, model: dict, title: str, lang: str, kind: str, goals: list[str], slides: list[dict],
                points: list[dict], progress) -> list[dict]:  # fmt: skip
    """Each slide of the storyboard written by the Writer (preset slides_writer), in order, with the whole storyboard in
    view: a content slide from its own key points; questions and a summary from the slides written before them. The
    objectives' bullets are the goals and a section's its aim, as planned. [{role, title, points, notes, sources,
    task, goal}]."""
    spec = KINDS[kind]["write"]
    board = _board(goals, slides)
    out: list[dict] = []
    for n, s in enumerate(slides, start=1):
        await progress("writing", n - 1, len(slides))
        refs = [points[r - 1] for r in s["refs"]]
        if s["role"] in ("questions", "summary"):
            given = ["The slides before it:"] + [f"- {x['title']}: {' / '.join(x['points'])}" for x in out
                                                 if x["role"] == "content"]  # fmt: skip
        elif refs:
            given = ["Its key points:"] + [f"- {p['point']} ({p.get('where') or title})" for p in refs]
        else:
            given = []
        goal = f"goal {s['goal']} ({goals[s['goal'] - 1]})" if 1 <= s["goal"] <= len(goals) else "the goals"
        ask = (f"«{title}», in {lang}.\n{board}\n\nWrite slide {n}: {s['role']}, «{s['title']}», serving {goal}. "
               f"Its task: {s.get('task') or '-'}\n{spec.get(s['role'], spec.get('content'))}\n" + "\n".join(given))  # fmt: skip
        got = {}
        for _ in range(2):  # once more when it is not JSON, or a questions slide without a question a goal
            got = _json(await _ask(app, model, "slides_writer", ask, WRITE_TOKENS)) or {}
            asked = [str(q).strip() for q in got.get("points") or []]
            if asked and (s["role"] != "questions" or (len(asked) == len(goals) and all(q.endswith("?") for q in asked))):
                break
            if s["role"] == "questions" and asked:  # (measured: seven questions for three goals; statements, not questions)
                ask += f"\nExactly {len(goals)} questions, each ending with \"?\": one for each goal, in the goals' order."
        bullets = [plain(" ".join(str(x).split())) for x in got.get("points") or [] if str(x).strip()]
        notes = plain(str(got.get("notes") or "").strip())
        if s["role"] == "objectives":
            bullets = list(goals)
        elif s["role"] == "section":  # its aim, as planned, said to the audience
            bullets = [s["task"]] if s.get("task") else bullets[:1]
        elif s["role"] == "questions":
            # the answers given apart, so the trainer has them (measured: asked for "the answers in its notes", the notes
            # said "the answers are on the slides before")
            answers = [" ".join(str(a).split()) for a in got.get("answers") or [] if str(a).strip()]
            if answers:
                notes = "Respostas:\n" + "\n".join(f"{n}. {a}" for n, a in enumerate(answers, start=1))
        elif not bullets:  # no answer: the slide's own key points, as the source says them
            bullets = [p["point"] for p in refs]
        sources = []
        for p in refs:
            where = str(p.get("where") or "").strip().strip("[]").strip()  # as the reading wrote it, without its brackets
            if where and where not in sources:
                sources.append(where)
        out.append({"role": s["role"], "title": s["title"], "points": bullets, "notes": notes,
                    "sources": sources, "task": s.get("task") or "", "goal": s["goal"]})  # fmt: skip
    await progress("writing", len(slides), len(slides))
    return out


async def _noop(*_args) -> None:
    return None


async def draft(app, model: dict, email: str, pid: str, source: dict, *, kind: str = "corporate", slides: int | None = None,
                focus: str = "", audience: str = "", language: str = "pt", domains: list[str] | None = None,
                progress=_noop) -> dict:  # fmt: skip
    """{title, kind, goals, slides: [{role, title, points, notes, sources, task, goal}], sources: [{document, link?}],
    read: {...}}. The source read in parts into key points; the Planner's goals and storyboard from them (checked); each
    slide written from its plan. progress(stage, done, total): "reading", "condensing", "planning", "writing"."""
    spec = KINDS[kind]
    count = lambda s: app.models.count(s, model)  # noqa: E731
    title, passages = await gather(app, email, pid, source, domains, count)
    passages = _without_repeated_sentences([p for p in passages if p["text"].strip()])
    if not passages:
        raise SourceEmpty("the source has no text")
    lines = [_line(p) for p in passages]
    parts = await asyncio.to_thread(_parts, lines, count, PART_TOKENS, [p["document"] for p in passages])
    if len(parts) > MAX_PARTS:
        raise SourceTooLarge(f"{len(passages)} passages, {len(parts)} parts of {PART_TOKENS} tokens (at most {MAX_PARTS})")
    by_section = len({p["document"] for p in passages}) < 3
    named, at = [], 0  # each part's topics, in order
    for part in parts:
        named.append(list(dict.fromkeys(topic_of(p, by_section) for p in passages[at : at + len(part)])))
        at += len(part)
    lang = "European Portuguese (Portugal: diapositivo, ecrã; a training is a formação)" if language == "pt" else "English"
    points = await _points(app, model, title, parts, progress, "reading", named, lang)
    log.info("source read", extra={"passageCount": len(passages), "partCount": len(parts), "pointCount": len(points)})
    low, high, default = spec["slides"]
    wanted = max(low, min(int(slides or default), high))
    structure = spec["structure"].format(audience=f" for {audience}" if audience.strip() else "")
    intro = (f"«{title}», in {lang}.\n{structure}" + (f"\nThe person asked for: {focus}" if focus.strip() else ""))
    # the key points' room: the window less the Planner's longer prompt, its answer, and - asked again - its last answer
    # with what is wrong in it, and the goals and module the second step is given
    prompt = max(count(llm_prompt("slides_planner")), count(llm_prompt("slides_storyboard")))
    room = app.models.window(model) - 2 * PLAN_TOKENS - prompt - count(intro) - 1536
    rounds, every = 0, list(dict.fromkeys(topic_of(p, by_section) for p in passages))
    while True:
        listed = [f"  - {x['point']}" for x in points] + [f"T{n}. {d}" for n, d in enumerate(topics_of(points, title), 1)]
        if count("\n".join(listed)) <= room or rounds >= 3 or len(points) < 2:
            break
        # too many points for one request: condensed the way the source was read, in parts (never cut), each point
        # still knowing its document
        rounds += 1
        plain = [f"- {x['point']} ({x.get('topic') or ''} · {x.get('where') or title})" for x in points]
        chunks = _parts(plain, count)
        points = await _points(app, model, f"key points of {title}", chunks, progress, "condensing", [every] * len(chunks), lang)
        log.info("points condensed", extra={"round": rounds, "pointCount": len(points)})
    points = await _without_repeats(app, points)
    # a content slide needs a key point of its own: a source with fewer points than content slides gets fewer slides,
    # never one point spread over several (measured: 3 points, 5 slides asked: the storyboard could not hold both rules)
    while wanted > 1 and modules_of(kind, wanted)[1] > len(points):
        wanted -= 1
    planned = await plan(app, model, kind, wanted, intro, points, title, language, progress)
    deck_title = planned["title"] or title
    made = await write(app, model, deck_title, lang, kind, planned["goals"], planned["slides"], points, progress)
    for slide, spare in zip(made, spare_of(planned["slides"], points, planned["taught"], title), strict=True):
        if spare and slide["role"] == "content":
            slide["_spare"] = spare  # the Critic's, never saved (domain/generations.py)
    seen, sources = set(), []
    for p in passages:
        if p["document"] not in seen:
            seen.add(p["document"])
            sources.append({k: p[k] for k in ("document", "link") if p.get(k)})
    return {"title": deck_title, "kind": kind, "goals": planned["goals"], "slides": made, "sources": sources,
            "read": {"passages": len(passages), "parts": len(parts), "points": len(points)}}  # fmt: skip


def llm_prompt(preset: str) -> str:
    from . import llm

    return llm.prompt(preset)
