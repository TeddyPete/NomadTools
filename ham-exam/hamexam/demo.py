"""Render sample screens to PNG (store screenshots, and checking layouts without a device)."""
from __future__ import annotations

import os
import random


def render_screens(out_dir: str) -> list:
    os.environ.setdefault("XDG_CONFIG_HOME", os.path.join(out_dir, ".cfg"))
    from . import bank as B
    from . import lcd as L
    from .app import App, ExamQ, ExamResult, Feedback, Figure, Groups, Home, ProgressView, start_drill
    from .keys import Key
    os.makedirs(out_dir, exist_ok=True)
    panel = L.Panel(headless=True)
    app = App(panel, None)
    app.prog = B.Progress(os.path.join(out_dir, ".cfg", "demo-state.json"))
    app.prog.records, app.prog.exams = {}, []
    p = app.pool
    rng = random.Random(7)
    for q in rng.sample(list(p.questions.values()), 370):     # some history for the progress screens
        for _ in range(rng.randint(1, 3)):
            app.prog.answer(q, rng.random() < 0.9, save=False)
    files = []

    def shot(name):
        app.draw()
        path = os.path.join(out_dir, f"{name}.png")
        panel.save(path)
        files.append(path)

    app.push(Home(app))
    shot("lcd_0_home")
    app.push(Groups(app, p.sub("T5")))
    shot("lcd_1_topic")
    start_drill(app, "T5A", p.groups["T5A"].questions)
    dq = app.stack[-1]
    dq.set_q(p.questions["T5A05"])
    app.draw()
    dq.key(Key("down"))
    dq.key(Key("down"))
    shot("lcd_2_question")
    app.push(Feedback(app, dq.q, False, None, "T5A  3/4"))
    shot("lcd_3_answer")
    app.stack = app.stack[:1]
    qs = p.draw_exam(random.Random(3))
    ex = ExamQ(app, qs)
    ex.go(10)
    app.push(ex)
    app.draw()
    ex.key(Key("down"))
    shot("lcd_x_exam")
    answers = {i: (q.answer if i % 6 else "A") for i, q in enumerate(qs)}
    app.stack = app.stack[:1]
    app.push(ExamResult(app, qs, answers, sum(answers[i] == q.answer for i, q in enumerate(qs))))
    shot("lcd_4_result")
    app.stack = app.stack[:1]
    app.push(ProgressView(app))
    shot("lcd_5_progress")
    app.push(Figure(app, "T-1"))
    shot("lcd_x_figure")
    return files
