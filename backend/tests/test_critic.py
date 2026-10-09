"""The Critic (agent/critic.py; the user, 2026-10-09: "a Critic Agent that will look at each slide from a trainee
perspective also considering UX aspects and starts a refinement loop", and "the Critic must clearly state the issues
observed and suggest how to fix those"): a generated outline's slides rendered and judged, a slide it would revise
written again from what it said and judged again; its last word kept on each slide. The scripted model only."""

from __future__ import annotations

import asyncio

import requests

from app.agent import critic

from .test_generations import _project, _ready
from .test_agent import h

ISSUE = {"kind": "task", "what": "Diz que o processo tem fases, mas não as mostra.",
         "fix": "Escrever cada fase como um ponto, com o que as notas dizem dela."}  # fmt: skip


def test_a_slide_the_critic_would_revise_is_written_again_from_what_it_said_and_judged_again(server, fake_model, fake_kb):
    fake_model._vision = True
    fake_model.critic_answers = [{"verdict": "good", "issues": []},  # the objectives
                                 {"verdict": "revise", "issues": [ISSUE]}]  # the first content slide; then all good
    pid = _project(server)
    body = {"kind": "training", "source": {"kind": "kb_topic", "query": "garantia"}, "slides": 8}
    gid = requests.post(f"{server}/api/projects/{pid}/generations", json=body, headers=h(), timeout=10).json()["id"]
    g = _ready(server, pid, gid, timeout=120)
    assert g["status"] == "ready", g
    slides = g["outline"]["slides"]
    reviewed = [s for s in slides if s["role"] in critic.REVIEWED_ROLES]
    assert reviewed and all(s["review"]["verdict"] == "good" for s in reviewed)  # the revised slide judged good after
    assert all("review" not in s for s in slides if s["role"] == "section")
    # each judged on its image, with its goal, task and text
    first = fake_model.critic_asks[0]
    assert first[1]["type"] == "image_url" and first[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "Its task:" in first[0]["text"] and "The goal it serves:" in first[0]["text"]
    # the Writer told what the Critic saw and how to fix it, to write the slide again from its own text and notes
    rewrite = next(a for a in fake_model.writer_asks if "A reviewer looked at the slide" in a)
    assert ISSUE["what"] in rewrite and ISSUE["fix"] in rewrite and "Its notes (what it is written from):" in rewrite
    assert len(fake_model.critic_asks) == len(reviewed) + 1  # the revised slide judged twice


def test_an_issue_without_its_fix_is_asked_for_again_and_a_blind_model_skips_the_review():
    class Models:
        def __init__(self):
            self.answers = ['{"verdict": "revise", "issues": [{"kind": "task", "what": "Vazio.", "fix": ""}]}',
                            '{"verdict": "revise", "issues": [{"kind": "task", "what": "Vazio.", "fix": "Mais texto."}]}']
            self.asked = []

        async def stream(self, model, preset, messages, tools, max_tokens):
            self.asked.append(messages)
            yield {"choices": [{"delta": {"content": self.answers.pop(0)}}]}

    class App:
        models = Models()

    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (64, 36), "white").save(buf, "PNG")
    got = asyncio.run(critic.judge(App, {}, buf.getvalue(), {"title": "T", "points": ["a"], "task": "x"}, "g"))
    assert got == {"verdict": "revise", "issues": [{"kind": "task", "severity": "must", "what": "Vazio.", "fix": "Mais texto."}]}
    # space, form and finish are the layout's and the Artist's: from the Critic, suggestions (measured: "must" for "add
    # an icon", every slide revised twice)
    App.models.answers = ['{"verdict": "revise", "issues": [{"kind": "space", "severity": "must", "what": "Vazio.", '
                          '"fix": "Um ícone."}]}']
    assert asyncio.run(critic.judge(App, {}, buf.getvalue(), {"title": "T", "points": ["a"]}, "g"))["verdict"] == "good"
    assert "how to fix it (fix)" in App.models.asked[1][2]["content"]
    # suggestions alone leave the slide as it is (measured: asked for any issue, it asked to revise every slide, every
    # round), and it is told the slide's language
    App.models.answers = ['{"verdict": "revise", "issues": [{"kind": "form", "severity": "could", "what": "Podia ser '
                          'uma tabela.", "fix": "Uma tabela."}]}']
    got = asyncio.run(critic.judge(App, {}, buf.getvalue(), {"title": "T", "points": ["a"], "role": "questions"}, "g",
                                   "European Portuguese", "One question for each goal."))  # fmt: skip
    # judged for what its role is for (measured: told its task alone, it asked to revise a questions slide for "looking
    # like a test")
    assert "Its role: questions - One question for each goal." in App.models.asked[-1][0]["content"][0]["text"]
    assert got["verdict"] == "good" and got["issues"][0]["severity"] == "could"
    assert App.models.asked[-1][0]["content"][0]["text"].startswith("Write in European Portuguese.")


def test_a_model_that_cannot_see_leaves_the_slides_unreviewed(server, fake_model, fake_kb):
    pid = _project(server)
    body = {"kind": "training", "source": {"kind": "kb_topic", "query": "garantia"}, "slides": 8}
    gid = requests.post(f"{server}/api/projects/{pid}/generations", json=body, headers=h(), timeout=10).json()["id"]
    g = _ready(server, pid, gid, timeout=60)
    assert g["status"] == "ready" and not any("review" in s for s in g["outline"]["slides"])
    assert fake_model.critic_asks == []


def test_a_slide_written_again_keeps_its_roles_rule_and_a_questions_slide_its_answers():
    """Measured: asked for "3 to 5 bullets", a questions slide was written again as statements."""

    class Models:
        def __init__(self):
            self.asked = []

        async def stream(self, model, preset, messages, tools, max_tokens):
            self.asked.append(messages[0]["content"])
            answer = '<think>...</think>{"points": ["Que idade?"], "answers": ["Até 35 anos."]}'
            yield {"choices": [{"delta": {"content": answer}}]}

    class App:
        models = Models()

    from app.agent import outline

    slide = {"role": "questions", "title": "Perguntas", "points": ["Idade"], "notes": "-", "task": "x"}
    rule = outline.KINDS["training"]["write"]["questions"]
    got = asyncio.run(critic._rewrite(App, {}, slide, [{"what": "Não são perguntas.", "fix": "Perguntas."}], "pt", "g", rule))
    assert got["points"] == ["Que idade?"] and got["notes"] == "Respostas:\n1. Até 35 anos."
    assert rule in App.models.asked[0] and "3 to 5 bullets" not in App.models.asked[0]
    # its subject's unused key points offered, to do its task (and nothing else)
    spare = {**slide, "role": "content", "_spare": ["Fase 6 - Formalização (02)", "Fase 7 - Arquivo (02)"]}
    asyncio.run(critic._rewrite(App, {}, spare, [{"what": "Faltam fases.", "fix": "Todas."}], "pt", "g", "rule"))
    assert "Key points of its subject no other slide uses" in App.models.asked[-1]
    assert "- Fase 7 - Arquivo (02)" in App.models.asked[-1]
