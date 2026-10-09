"""The Planner (agent/outline.plan; the user, 2026-10-09: "the planning must create a coherent storyboard based on clearly
defined goals and identify tasks before giving it for the Artist to execute its art"): the goals and modules, then each
module's slides, each step checked by the application and asked again with what is wrong; the deck assembled around them
at the size asked; each slide written from its plan; the Artist told each slide's task and goal. Never the real model."""

from __future__ import annotations

import asyncio
import json

from app.agent import artist, outline

GOALS = ["Identificar os requisitos", "Explicar as fases do processo", "Calcular os custos"]
TOPICS = [[1], [2], [3]]  # each goal's topics
MODULES = [{"title": "Requisitos", "aim": "Vai saber quem pode pedir.", "goals": [1]},
           {"title": "Processo e custos", "aim": "Vai conhecer as fases e os custos.", "goals": [2, 3]}]  # fmt: skip


def _slide(role, title, goal=0, task="Mostrar.", refs=()):
    return {"role": role, "title": title, "goal": goal, "task": task, "refs": list(refs)}


def _module2():  # the second module's slides, its key points numbered P1 to P4
    return [_slide("content", "As sete fases", 2, refs=[1, 2]), _slide("content", "Custos", 3, refs=[3, 4])]


def _good():  # a training as the writer is given it
    return [_slide("objectives", "Objetivos"), _slide("section", "Requisitos", task="Saber quem pode pedir."),
            _slide("content", "Idade e rendimento", 1, refs=[1, 2]), _slide("section", "Processo"),
            _slide("content", "As sete fases", 2, refs=[3]), _slide("content", "Custos", 3, refs=[4, 5]),
            _slide("questions", "Perguntas"), _slide("summary", "Conclusões")]  # fmt: skip


def test_the_deck_is_divided_into_modules_and_content_slides_by_the_application():
    # (measured: 12 slides as 3 modules left 6 content slides for 5 goals, and the modules each joined two subjects)
    assert outline.modules_of("training", 12) == (2, 7) and outline.shares(7, 2) == [4, 3]
    assert outline.modules_of("training", 14) == (3, 8) and outline.shares(8, 3) == [3, 3, 2]
    assert outline.modules_of("training", 8) == (2, 3) and outline.modules_of("corporate", 8) == (3, 8)
    assert [outline.goals_for(n) for n in (3, 7, 8, 10, 11)] == [3, 3, 4, 4, 5]
    # in proportion to what each module has to teach, one each at least (measured: shared evenly, a module of 59 key
    # points had 3 slides, its seven phases one overview line)
    assert outline.shares(7, 2, [30, 90]) == [2, 5] and outline.shares(3, 3, [1, 50, 1]) == [1, 1, 1]
    assert sum(outline.shares(11, 4, [5, 17, 40, 2])) == 11 and outline.shares(7, 2, [0, 0]) == [4, 3]


def test_key_points_are_grouped_into_topics_by_document_or_by_section():
    """A topic is a source document when the source has several; a single document's top sections otherwise (one topic
    would make one goal). A key point's topic is the one its "where" names."""
    several = {"document": "11 - Crédito Habitação Jovem", "where": "Requisitos > Idade"}
    assert outline.topic_of(several, False) == ("11 - Crédito Habitação Jovem", "11 - Crédito Habitação Jovem")
    assert outline.topic_of(several, True) == ("11 - Crédito Habitação Jovem · Requisitos", "Requisitos")
    part = [("01 - Oferta", "01 - Oferta"), ("11 - Crédito Habitação Jovem", "11 - Crédito Habitação Jovem")]
    assert outline.topic_from("11 - Crédito Habitação Jovem · Requisitos", part) == "11 - Crédito Habitação Jovem"
    assert outline.topic_from("uma secção sem nome", part) == "01 - Oferta"
    points = [{"point": "a", "topic": "B"}, {"point": "b", "topic": "A"}, {"point": "c", "topic": "B"}, {"point": "d"}]
    assert outline.topics_of(points, "Fonte") == ["B", "A", "Fonte"]


def test_goals_and_modules_that_hold_have_no_problems_and_each_fault_is_named():
    assert outline.frame_problems(GOALS, TOPICS, MODULES, 2, 3, 4) == []
    said = outline.frame_problems(GOALS, [[1], [1, 2], [9]], MODULES, 2, 3, 4)
    # a topic may teach more than one goal (measured: one large document held most of a subject)
    assert said == ["Goal 3 («Calcular os custos»): give the topics that teach it (T1 to T4)."]
    wrong = [{"title": "Requisitos", "aim": "", "goals": [1, 7]}, {"title": "Requisitos", "aim": "x", "goals": [1]}]
    said = outline.frame_problems(GOALS[:2], [[1], [2]], wrong, 3, 3, 4)
    assert "There are 2 goals: give exactly 3." in said and "There are 2 modules: make exactly 3." in said
    assert "Module 1 («Requisitos»): say its aim." in said
    assert "Module 1 («Requisitos»): its goals must be numbers of the goals (1 to 2)." in said
    assert "Goal 1 is in modules 1 and 2: a goal is served by one module." in said
    assert "Goal 2 («Explicar as fases do processo») is served by no module." in said
    assert "Two modules have the title «requisitos»: each its own." in said


def test_each_incoherence_of_a_modules_slides_is_named_for_the_planner_to_correct():
    assert outline.problems(MODULES[1], _module2(), 2, 4) == []
    slides = [_slide("content", "As sete fases", 2, refs=[1, 9]), _slide("content", "Processo e custos: visão geral", 1,
              task="", refs=[1])]  # fmt: skip
    said = outline.problems(MODULES[1], [*slides, _slide("content", "As sete fases", 2, refs=[])], 2, 4)
    assert "There are 3 slides: give exactly 2." in said
    assert "Slide 1 («As sete fases»): there are key points P1 to P4 only." in said
    assert "Slide 2 («Processo e custos: visão geral»): its goal must be one of this module's goals (2, 3)." in said
    assert ("Slide 2 («Processo e custos: visão geral») is about the module itself: the module's opening slide says its "
            "aim; give this slide one idea from the key points.") in said  # fmt: skip
    assert "Slide 2 («Processo e custos: visão geral»): say its task." in said
    assert "P1 is on slides 1 and 2: keep it on one." in said
    assert "Slide 3 («As sete fases»): give the numbers of the key points it uses." in said
    assert "Two slides have the title «as sete fases»: each slide its own." in said
    assert outline.problems(MODULES[1], [*_module2()[:1], _slide("content", "Fases", 2, refs=[3])], 2, 4) == [
        "Goal 3 has no slide: give it one."]


def test_what_the_planner_leaves_wrong_is_put_right_where_it_can_be():
    slides = [_slide("content", "A", 1, refs=[1, 2]), _slide("content", "B", 1, refs=[2, 3, 9]),
              _slide("content", "C", 1, refs=[1])]
    fixed = outline._repair(slides, 4)
    assert [s["title"] for s in fixed] == ["A", "B"] and fixed[1]["refs"] == [3]


class _Models:
    """Answers each preset from a queue; records what was asked."""

    def __init__(self, answers: dict[str, list]):
        self.answers = answers
        self.asked: list[tuple[str, list[dict]]] = []

    async def stream(self, model, preset, messages, tools, max_tokens):
        self.asked.append((preset, messages))
        answer = self.answers[preset].pop(0)
        yield {"choices": [{"delta": {"content": answer if isinstance(answer, str) else json.dumps(answer)}}]}


class _App:
    def __init__(self, answers):
        self.models = _Models(answers)


async def _noop(*_a):
    return None


def test_the_storyboard_is_planned_in_steps_each_asked_again_and_the_deck_assembled_at_its_size():
    """Measured: asked for a whole deck's slides at once, the model planned 15 or 14 for 12, three times in three; asked
    to anchor goals and slides to key point numbers out of 80, it gave them the wrong ones. The goals (with their topics)
    and modules first; then each module's slides from its own key points, their number given."""
    points = [{"point": f"ponto {n}", "where": "w", "topic": t} for n, t in
              [(1, "Requisitos"), (2, "Requisitos"), (3, "Fases"), (4, "Fases"), (5, "Custos"), (6, "Custos")]]  # fmt: skip
    goals = [{"goal": g, "topics": [f"T{t[0]}"]} for g, t in zip(GOALS, TOPICS, strict=True)]
    frame = {"title": "Crédito à Habitação", "goals": goals, "modules": MODULES}
    first = [{"title": "Idade", "goal": 1, "task": "Mostrar a idade.", "points": ["P1"]},
             {"title": "Rendimento", "goal": 1, "task": "Mostrar o rendimento.", "points": ["P2"]}]
    second = [{"title": "As sete fases", "goal": 2, "task": "Mostrar.", "points": ["P1", "P2"]},
              {"title": "Custos", "goal": 3, "task": "Mostrar.", "points": ["P3", "P4"]}]
    app = _App({"slides_planner": [{**frame, "modules": MODULES[:1]}, frame],
                "slides_storyboard": [{"slides": first}, {"slides": second[:1]}, "not json", {"slides": second}]})
    got = asyncio.run(outline.plan(app, {}, "training", 9, "«Crédito», in pt.", points, "Crédito", "pt", _noop))
    assert got["goals"] == GOALS and len(got["slides"]) == 9  # objectives, 2 sections, 4 content, questions, summary
    assert [s["role"] for s in got["slides"]] == ["objectives", "section", "content", "content", "section", "content",
                                                  "content", "questions", "summary"]  # fmt: skip
    assert got["slides"][0]["title"] == "Objetivos da formação" and got["slides"][-1]["title"] == "Em resumo"
    assert got["slides"][4]["title"] == "Processo e custos" and got["slides"][4]["task"] == "Vai conhecer as fases e os custos."
    # each module's key point numbers, as the deck's
    assert [s["refs"] for s in got["slides"] if s["role"] == "content"] == [[1], [2], [3, 4], [5, 6]]
    asked = [m for p, m in app.models.asked if p == "slides_planner"]
    assert "Give 3 goals and make 2 modules." in asked[0][0]["content"] and "T2. Fases (2 key points):" in asked[0][0]["content"]
    assert "There are 1 modules: make exactly 2." in asked[1][2]["content"]
    story = [m for p, m in app.models.asked if p == "slides_storyboard"]
    assert "This module: «Requisitos»" in story[0][0]["content"] and "P2. ponto 2 (w)" in story[0][0]["content"]
    assert "ponto 3" not in story[0][0]["content"]  # a module sees its own key points only
    assert "serves goals 2, 3 - 2 slides." in story[1][0]["content"] and "P1. ponto 3 (w)" in story[1][0]["content"]
    assert "Topic «Fases» - 1 slide:" in story[1][0]["content"] and "Topic «Custos» - 1 slide:" in story[1][0]["content"]
    assert "There are 1 slides: give exactly 2." in story[2][2]["content"]
    assert len(story[3]) == 3 and story[3][0] == story[1][0]  # its key points once, then only the last answer and its problems


def test_each_slide_is_written_from_its_plan():
    """Objectives show the goals and a section its aim, as planned; a content slide is written from its own key points
    with the whole storyboard in view, and cites where they come from; questions from the slides written before."""
    points = [{"point": "Idade até 35 anos", "where": "CH/11 · Requisitos"}, {"point": "Rendimento até ao 8.º escalão",
              "where": "CH/11 · Requisitos"}, {"point": "Sete fases", "where": "CH/02"}, {"point": "Escritura", "where": "CH/06"},
              {"point": "Registo", "where": "CH/06"}]  # fmt: skip
    writes = [{"points": ["x"], "notes": "Abertura."}, {"points": ["y"], "notes": "Módulo."},
              {"points": ["Idade até 35 anos", "Rendimento até ao 8.º escalão"], "notes": "Os requisitos."},
              {"points": ["z"], "notes": "-"}, "not json", "still not json",
              {"points": ["Escritura e registo"], "notes": "Custos."},
              {"points": ["Que idade?", "Quantas fases?", "Que custos?"],
               "answers": ["Até 35 anos.", "Sete.", "Escritura e registo."], "notes": "As respostas estão nos diapositivos."},
              {"points": ["Requisitos claros"], "notes": "Fim."}]  # fmt: skip
    app = _App({"slides_writer": writes})
    out = asyncio.run(outline.write(app, {}, "Crédito à Habitação", "pt", "training", GOALS, _good(), points, _noop))
    assert out[0]["points"] == GOALS and out[1]["points"] == ["Saber quem pode pedir."]  # a section's aim, as planned
    # the questions' answers, given apart, are the trainer's notes (measured: "the answers are on the slides before")
    assert out[6]["points"] == ["Que idade?", "Quantas fases?", "Que custos?"]
    assert out[6]["notes"] == "Respostas:\n1. Até 35 anos.\n2. Sete.\n3. Escritura e registo."
    assert out[2]["points"] == ["Idade até 35 anos", "Rendimento até ao 8.º escalão"]
    assert out[2]["sources"] == ["CH/11 · Requisitos"]
    assert out[2]["task"] == "Mostrar." and out[2]["goal"] == 1
    assert out[4]["points"] == ["Sete fases"]  # no answer twice: its own key points, as the source says them
    ask = app.models.asked[2][1][0]["content"]
    assert "The storyboard:" in ask and "5. content, goal 2: As sete fases" in ask
    assert "- Idade até 35 anos (CH/11 · Requisitos)" in ask
    questions = app.models.asked[-2][1][0]["content"]
    assert "The slides before it:" in questions
    assert "- Idade e rendimento: Idade até 35 anos / Rendimento até ao 8.º escalão" in questions


def test_the_artist_is_told_the_slides_task_and_goal():
    ask = artist._ask({"title": "As sete fases", "points": ["Simulação", "Proposta"], "task": "Mostrar as fases por ordem.",
                       "goal_text": "Explicar as fases do processo"}, [])  # fmt: skip
    assert "The goal this slide serves: Explicar as fases do processo" in ask
    assert "The slide's task: Mostrar as fases por ordem." in ask


def test_a_design_that_leaves_points_out_is_the_slides_list():
    """Measured: four points on refunds' notice periods and fees shown as two columns of one vague line each."""
    slide = {"title": "Serviços", "points": ["Aviso de 7 dias", "Aviso de 10 dias", "Vistoria em 10 dias", "Pedidos nas lojas"]}
    thin = {"form": "columns", "columns": [{"heading": "Serviços", "points": ["Pedidos nas lojas"]},
                                           {"heading": "Prazos", "points": ["Avisos"]}]}  # fmt: skip
    assert artist.checked(thin, slide)["form"] == "bullets"
    whole = {"form": "columns", "columns": [{"heading": "Prazos", "points": slide["points"][:3]},
                                            {"heading": "Onde", "points": slide["points"][3:]}]}  # fmt: skip
    assert artist.checked(whole, slide)["form"] == "columns"


def test_a_thinking_answer_is_read_without_its_thinking():
    """The Planner and the Writer think first (llm.PRESETS): braces in the thinking never reach the JSON read."""
    text = '<think>The plan: {"slides": [] } is wrong; better:</think>```json\n{"slides": [{"title": "A"}]}\n```'
    assert outline._json(text) == {"slides": [{"title": "A"}]} and outline.answer_of("sem pensar") == "sem pensar"


def test_a_reading_part_never_holds_two_documents_and_asks_for_the_decks_language():
    """Measured: a part with the end of one document and the phases of another gave its 12 points to the first; a part of
    a Portuguese document, the language unsaid, came back in English."""
    lines = ["a1", "a2", "b1", "b2", "b3"]
    docs = ["A", "A", "B", "B", "B"]
    assert outline._parts(lines, len, 100, docs) == [["a1", "a2"], ["b1", "b2", "b3"]]
    assert outline._parts(lines, len, 4, docs) == [["a1", "a2"], ["b1", "b2"], ["b3"]]
    app = _App({"slides_points": [{"points": [{"point": "Fase 1 - Simulação", "where": "B · Fase 1"}]}]})
    got = asyncio.run(outline._points(app, {}, "T", [["[B · Fase 1] texto"]], _noop, "reading", [[("B", "B")]],
                                      "European Portuguese"))  # fmt: skip
    assert got == [{"point": "Fase 1 - Simulação", "where": "B · Fase 1", "topic": "B"}]
    assert "Write the points in European Portuguese, at most 12:" in app.models.asked[0][1][0]["content"]


def test_a_fact_said_twice_is_kept_once_in_its_fuller_wording():
    """Measured: a document's summary repeated its sections, and two slides taught the same 0,6% spread. The reranker's
    score both ways at SAME_FACT or more: the same fact; a related but different one stays."""
    same = {("Desconto de 0,6% no spread com domiciliação", "Spread bonificado de 0,6% mediante domiciliação de salário"),
            ("Spread bonificado de 0,6% mediante domiciliação de salário", "Desconto de 0,6% no spread com domiciliação")}

    class Reranker:
        available = True

        def scores(self, query, texts):
            return [0.999 if (query, t) in same else 0.97 for t in texts]

    class App:
        reranker = Reranker()

    points = [{"point": "Desconto de 0,6% no spread com domiciliação", "topic": "A"},
              {"point": "Taxas fixas, mistas e variáveis", "topic": "A"},
              {"point": "Spread bonificado de 0,6% mediante domiciliação de salário", "topic": "A"},
              {"point": "Desconto de 0,6% no spread com domiciliação", "topic": "B"}]  # another topic: kept
    got = asyncio.run(outline._without_repeats(App, points))
    assert [p["point"] for p in got] == ["Spread bonificado de 0,6% mediante domiciliação de salário",
                                         "Taxas fixas, mistas e variáveis", "Desconto de 0,6% no spread com domiciliação"]
    assert asyncio.run(outline._without_repeats(object(), points)) == points  # no reranker: as they are


def test_a_diagram_with_fewer_steps_than_its_slides_points_is_the_list():
    """Looked at: four points drawn as a diagram of two steps."""
    slide = {"title": "Jovem", "points": ["Avaliação de risco", "Enquadramento da proposta", "Crédito Sinal Jovem", "DL 44/2024"]}
    two = {"form": "diagram", "diagram": {"nodes": ["Avaliação de risco", "Enquadramento da proposta"]}}
    assert artist.checked(two, slide)["form"] == "bullets"


def test_a_slides_spare_key_points_are_its_goals_topics_unused_ones():
    """Measured: a slide to show the seven phases was given phases 1 to 5; its revision, from its own points, could not
    add 6 and 7. The key points of its subject no slide uses are what a revision may draw on."""
    points = [{"point": f"Fase {n}", "where": "02", "topic": "Fases"} for n in range(1, 8)] + [
        {"point": "Spread", "where": "01", "topic": "Oferta"}]
    slides = [{"role": "content", "goal": 1, "refs": [1, 2, 3, 4, 5]}, {"role": "content", "goal": 2, "refs": [8]}]
    spare = outline.spare_of(slides, points, [["Fases"], ["Oferta"]], "T")
    assert spare == [["Fase 6 (02)", "Fase 7 (02)"], []]


def test_an_answer_with_mismatched_brackets_is_mended_and_a_valid_one_left_as_it_is():
    """Measured: the Artist closed a list with "}" and added a closer - 9 of 36 answers lost; all 9 mended whole."""
    broken = '{"columns": [{"heading": "Limites", "points": ["40 anos.", "75 anos."}]}]}'
    assert outline.loads(broken) == {"columns": [{"heading": "Limites", "points": ["40 anos.", "75 anos."]}]}
    assert outline.loads('{"a": "x}]", "b": [1, {"c": 2}]}') == {"a": "x}]", "b": [1, {"c": 2}]}  # brackets in strings
    assert outline.loads("sem JSON") is None


def test_a_sentence_a_document_already_gave_is_read_once():
    """Measured: a knowledge base's passages overlap - 147 sentences in two passages or more - and the same fact came
    back as two key points. Another document's same sentence is its own."""
    long = "O Crédito Habitação Jovem é para jovens até 35 anos, criado pelo DL n.º 44/2024"
    passages = [{"document": "A", "text": f"Início. {long}. Mais"}, {"document": "A", "text": f"{long}. Novo facto dito aqui"},
                {"document": "A", "text": long}, {"document": "B", "text": long}]
    got = outline._without_repeated_sentences(passages)
    assert [p["text"] for p in got] == [f"Início. {long}. Mais", "Novo facto dito aqui", long]
    assert [p["document"] for p in got] == ["A", "A", "B"]


def test_a_modules_slides_follow_its_topics():
    """Measured: one slide drew on two documents - CH Jovem with works and construction - and CH Jovem's facts did not
    fit. Its slides shared across its topics; a slide that mixes them, or a topic with another number, is named."""
    of = {1: 0, 2: 0, 3: 1, 4: 1}
    good = [_slide("content", "Jovem", 1, refs=[1, 2]), _slide("content", "Obras", 1, refs=[3, 4])]
    assert outline.topic_problems(good, [1, 1], of, ["Jovem", "Obras"]) == []
    mixed = [_slide("content", "Jovem e Obras", 1, refs=[1, 3]), _slide("content", "Jovem", 1, refs=[2])]
    said = outline.topic_problems(mixed, [1, 1], of, ["Jovem", "Obras"])
    assert said == ["Slide 1 («Jovem e Obras») takes key points from «Jovem» and «Obras»: a slide takes them from one topic.",
                    "Topic «Jovem» has 2 slides: give it exactly 1.", "Topic «Obras» has 0 slides: give it exactly 1."]
    assert outline.topic_problems(mixed, None, of, ["Jovem", "Obras"]) == []  # fewer slides than topics: not shared


def test_a_topic_two_goals_share_is_taught_once():
    """A large document may serve two goals; the second module is not shown the key points the first one used."""
    points = [{"point": f"ponto {n}", "where": "w", "topic": "Guia"} for n in range(1, 5)]
    goals = [{"goal": "Conhecer a estrutura", "topics": ["T1"]}, {"goal": "Seguir o ciclo de vida", "topics": ["T1"]},
             {"goal": "Avaliar", "topics": ["T1"]}]
    modules = [{"title": "Estrutura", "aim": "Vai conhecer.", "goals": [1]},
               {"title": "Ciclo", "aim": "Vai seguir.", "goals": [2, 3]}]
    # 3 content slides shared 2 and 1 (the modules' key points weigh the same)
    first = {"slides": [{"title": "Hierarquia", "goal": 1, "task": "Mostrar.", "points": ["P1", "P2"]},
                        {"title": "Papéis", "goal": 1, "task": "Mostrar.", "points": ["P3"]}]}
    second = {"slides": [{"title": "Estados", "goal": 2, "task": "Mostrar.", "points": ["P1"]}]}
    app = _App({"slides_planner": [{"title": "Guia", "goals": goals, "modules": modules}], "slides_storyboard": [first, second]})
    got = asyncio.run(outline.plan(app, {}, "training", 8, "«Guia», in pt.", points, "Guia", "pt", _noop))
    story = [m for p, m in app.models.asked if p == "slides_storyboard"]
    assert "ponto 3" not in story[1][0]["content"] and "P1. ponto 4 (w)" in story[1][0]["content"]
    assert "do not teach their subjects again):\n- Hierarquia: Mostrar.\n- Papéis: Mostrar." in story[1][0]["content"]
    assert [s["refs"] for s in got["slides"] if s["role"] == "content"] == [[1, 2], [3], [4]]


def test_a_column_item_the_slide_does_not_say_is_the_list_and_a_long_aim_is_sent_back():
    """Looked at: "Foco específico" under a column heading, in no point or note; a 20-word aim squeezed on its divider."""
    slide = {"title": "Tipos", "points": ["Crédito Geral: aquisição e obras", "Crédito Hipotecário: complementar isolado"]}
    invented = {"form": "columns", "columns": [{"heading": "Geral", "points": ["Aquisição e obras"]},
                                               {"heading": "Hipotecário", "points": ["Foco específico"]}]}  # fmt: skip
    assert artist.checked(invented, slide)["form"] == "bullets"
    said = {"form": "columns", "columns": [{"heading": "Geral", "points": ["Aquisição e obras"]},
                                           {"heading": "Hipotecário", "points": ["Complementar isolado"]}]}  # fmt: skip
    assert artist.checked(said, slide)["form"] == "columns"
    long = [{**MODULES[0], "aim": " ".join(["palavra"] * 20)}, MODULES[1]]
    assert "Module 1 («Requisitos»): its aim has 20 words: say it in at most 15." in outline.frame_problems(
        GOALS, TOPICS, long, 2, 3, 4)


def test_latex_a_model_writes_becomes_the_symbols_a_slide_shows():
    """Measured: "EPIC $\\rightarrow$ FEATURE" from the Writer, "$\\ge 60\\%$" earlier, though its rules ask for plain text."""
    assert outline.plain("EPIC $\\rightarrow$ FEATURE $\\rightarrow$ PBI") == "EPIC → FEATURE → PBI"
    assert outline.plain("incapacidade $\\ge 60\\%$") == "incapacidade ≥ 60%"
    assert outline.plain("custa 10 $ por mês") == "custa 10 $ por mês" and outline.plain("sem nada") == "sem nada"


def test_a_slide_about_its_module_still_there_after_the_tries_is_left_out():
    """Measured: "Objetivos da Formação: <the module's title>" kept by the best of three storyboard answers."""
    points = [{"point": f"ponto {n}", "where": "w", "topic": "Guia"} for n in range(1, 5)]
    goals = [{"goal": g, "topics": ["T1"]} for g in ("Conhecer", "Seguir", "Avaliar")]
    modules = [{"title": "Fundamentos", "aim": "Vai conhecer.", "goals": [1, 2]}, {"title": "Prática", "aim": "Vai seguir.",
                                                                                   "goals": [3]}]  # fmt: skip
    meta = {"slides": [{"title": "Objetivos da Formação: Fundamentos", "goal": 1, "task": "Apresentar.", "points": ["P1"]},
                       {"title": "Hierarquia", "goal": 2, "task": "Mostrar.", "points": ["P2"]}]}  # fmt: skip
    last = {"slides": [{"title": "Avaliação", "goal": 3, "task": "Mostrar.", "points": ["P1"]}]}
    app = _App({"slides_planner": [{"title": "Guia", "goals": goals, "modules": modules}],
                "slides_storyboard": [meta, meta, meta, last]})
    got = asyncio.run(outline.plan(app, {}, "training", 8, "«Guia», in pt.", points, "Guia", "pt", _noop))
    assert [s["title"] for s in got["slides"] if s["role"] == "content"] == ["Hierarquia", "Avaliação"]
