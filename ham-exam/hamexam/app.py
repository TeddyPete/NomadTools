"""Ask Elmer Ham Exam: the app. Screens on the LCD, input from the keyboard."""
from __future__ import annotations

import time

import pygame

from . import __version__
from . import bank as B
from . import lcd as L
from . import nomadui as T
from .keys import Keyboard
from .ui import BACK, DOWN, SELECT, UP, Confirm, Menu, Message, Screen, nav_key

APP_TITLE = "Ask Elmer"
LEARN = "Learn why at askelmer.com"
T.set_about("Ask Elmer Ham Exam", __version__, extra=LEARN)

HELP_MAIN = ("Ask Elmer Ham Exam drills the official NCVEC question pools for the US Technician, General "
             "and Amateur Extra licenses. Practice exam: a real draw, one question from each group, scored "
             "like the test. Study a topic: one subelement or group with the answer after each question. "
             "Quick 10: your ten weakest questions. Missed: the ones you got wrong last time. A question "
             "counts as mastered after two right in a row. From Ask Elmer, askelmer.com.")
HELP_Q = ("Read the question, Down picks an answer (A to D), OK answers. Up at the top scrolls back to the "
          "question. Fig shows the diagram when the question has one.")
HELP_EXAM = ("A practice exam drawn like the real one. No answers are shown until you finish. "
             "4 Back and 6 Next move between questions; you can change an answer. 8 Finish scores it.")
HELP_FB = "The correct answer and the rule it comes from. OK or 4 goes to the next question."
HELP_FIG = "4 zooms in and out. Arrows move around a zoomed diagram."

LINE_H = 17
GOOD = T.OK
RIGHT_BG = (0x1B, 0x3D, 0x2E)   # Ask Elmer green tint


def pct(a, b) -> str:
    if not b:
        return "-"
    v = 100 * a / b
    return "<1%" if 0 < v < 0.5 else ">99%" if 99.5 <= v < 100 else f"{round(v)}%"


class App:
    def __init__(self, panel: L.Panel, kb: Keyboard | None):
        self.panel, self.kb = panel, kb
        self.prog = B.Progress()
        self.stack: list[Screen] = []
        self.helpview = None
        self.dirty = True
        self.quit = False

    @property
    def pool(self) -> B.Pool:
        return B.pool_for(self.prog.exam)

    def push(self, s):
        self.stack.append(s)
        self.dirty = True

    def pop(self, s=None):
        if s is None:
            if len(self.stack) > 1:
                self.stack.pop()
            else:
                self.quit = True
        elif s in self.stack:
            self.stack.remove(s)
        self.dirty = True

    def open_about(self):
        """The About screen (shown like Fn+H help, ESC closes it)."""
        self.helpview = T.AboutView()
        self.dirty = True

    def wake(self):
        self.dirty = True

    def run(self):
        self.push(Home(self))
        last = 0.0
        while not self.quit:
            keys = self.kb.poll(0.1) if self.kb else (time.sleep(0.1) or [])
            for k in keys:
                if self.stack:
                    self.dispatch(k)
                self.dirty = True
            now = time.monotonic()
            if self.dirty or now - last > 1.0:
                self.draw()
                last = now
                self.dirty = False
        self.prog.save()

    def dispatch(self, k):
        top = self.stack[-1]
        if self.helpview is not None:
            if self.helpview.handle(k) == "close":
                self.helpview = None
            return
        if k.name == "help":
            self.helpview = T.HelpView(top.title, top.help or HELP_MAIN, top.keybar())
            return
        if top.soft(k):
            return
        top.key(nav_key(k))

    def draw(self):
        if not self.stack:
            return
        surf = self.panel.surf
        if self.helpview is not None:
            self.helpview.render(surf, self.panel.fonts)
            self.panel.flush()
            return
        s = self.stack[-1]
        rows, sel = s.rows()
        T.render(surf, s.title, rows, s.hint, sel, s.right(), self.panel.fonts, s.keybar())
        paint = getattr(s, "paint", None)
        if paint:
            paint(surf, self.panel.fonts)
        self.panel.flush()


# ---- menus ---------------------------------------------------------------------------

class Home(Menu):
    help = HELP_MAIN

    def __init__(self, app):
        self.app = app
        items = [
            ("Practice exam", self.exam, lambda: f"{app.pool.per_exam} Q"),
            ("Study a topic", lambda: app.push(Topics(app))),
            ("Quick 10", self.quick, "weakest"),
            ("Missed questions", self.missed, lambda: str(self.n_missed())),
            ("Progress", lambda: app.push(ProgressView(app)),
             lambda: f"pass {pct(app.prog.pass_chance(app.pool), 1)}"),
            ("Exam class", lambda: app.push(ExamPick(app)), lambda: app.pool.short, L.OK),
            ("Question pool", lambda: app.push(Message(app, "Question pool", self.about()))),
            ("About", lambda: app.open_about()),
        ]
        super().__init__(app, APP_TITLE, items, "↑↓ move  OK open  ESC quit")

    def about(self):
        p = self.app.pool
        return (f"{HELP_MAIN}\n\nPool: {p.name} (FCC Element {p.element}), {len(p.questions)} questions, "
                f"valid {p.effective_from} to {p.effective_to}. Questions are the public domain NCVEC "
                f"pool, word for word.")

    def n_missed(self):
        p = self.app.pool
        return sum(1 for q in p.questions.values() if self.app.prog.missed(q))

    def exam(self):
        self.app.push(ExamQ(self.app, self.app.pool.draw_exam()))

    def quick(self):
        start_drill(self.app, "Quick 10", list(self.app.pool.questions.values()), limit=10)

    def missed(self):
        p = self.app.pool
        qs = [q for q in p.questions.values() if self.app.prog.missed(q)]
        if not qs:
            self.app.push(Message(self.app, "Missed", "No missed questions. Nice work."))
            return
        start_drill(self.app, "Missed", qs)


class ExamPick(Menu):
    def __init__(self, app):
        items = []
        for e in B.exams():
            items.append((e["name"], (lambda e=e: self.pick(e["exam_id"])),
                          "now" if e["exam_id"] == app.prog.exam else ""))
        super().__init__(app, "Exam class", items)

    def pick(self, eid):
        self.app.prog.exam = eid
        self.app.prog.save()
        self.app.pop(self)


class Topics(Menu):
    help = "Pick a subelement. The number is how much of it you have mastered (two right in a row)."

    def __init__(self, app):
        p = app.pool
        items = []
        for s in p.subs:
            qs = [q for g in s.groups for q in g.questions]
            items.append((f"{s.id} {s.title}", (lambda s=s: app.push(Groups(app, s))),
                          (lambda qs=qs: self.pc(qs))))
        super().__init__(app, "Study a topic", items)

    def pc(self, qs):
        _, m, n = self.app.prog.counts(qs)
        return pct(m, n)


class Groups(Menu):
    def __init__(self, app, sub):
        qs = [q for g in sub.groups for q in g.questions]
        items = [(f"All of {sub.id}", lambda: start_drill(app, sub.id, qs), lambda: self.pc(qs), L.OK)]
        for g in sub.groups:
            items.append((f"{g.id} {g.topics}", (lambda g=g: start_drill(app, g.id, g.questions)),
                          (lambda g=g: self.pc(g.questions))))
        super().__init__(app, f"{sub.id} {sub.title}", items)

    def pc(self, qs):
        _, m, n = self.app.prog.counts(qs)
        return pct(m, n)


def start_drill(app, name, qs, limit=None):
    d = B.Drill(app.prog, qs, limit)
    q = d.next()
    if q:
        app.push(DrillQ(app, name, d, q))


# ---- the question view -------------------------------------------------------------

class QuestionView(Screen):
    """Stem and choices drawn as one scrolling column; Down/Up move the
    highlight between choices and the view follows it."""
    help = HELP_Q
    top_y = T.TITLE_H + 2
    bot_y = T.H - T.KEYBAR_H - 1

    def __init__(self, app, q: B.Question):
        super().__init__(app)
        self.set_q(q)

    def set_q(self, q, sel=None):
        self.q = q
        self.sel = sel          # index into q.choices, None = still reading
        self.off = 0
        self._lines = None
        self.app.wake()

    @property
    def title(self):
        return self.q.id

    @property
    def view_lines(self):
        return (self.bot_y - self.top_y) // LINE_H

    def lines(self, f):
        """[(text, color, choice_index or None)]."""
        if self._lines is None:
            font = f["small"]
            w = T.W - 14
            out = [(l, T.FG, None) for l in T.wrap_text(font, self.q.stem, w)]
            if self.q.figures:
                out.append((f"(Figure {', '.join(self.q.figures)}: key Fig)", T.WARN, None))
            for i, (k, t) in enumerate(self.q.choices):
                for j, l in enumerate(T.wrap_text(font, f"{k}. {t}", w, "    ")):
                    out.append((l, T.FG, i))
            self._lines = out
        return self._lines

    def follow(self):
        ls = self._lines or []
        if self.sel is None:
            return
        idx = [i for i, l in enumerate(ls) if l[2] == self.sel]
        first, last = idx[0], idx[-1]
        n = self.view_lines
        if last >= self.off + n:
            self.off = last - n + 1
        if first < self.off:
            self.off = first

    def key(self, k):
        ls = self._lines or []
        n = len(self.q.choices)
        maxoff = max(0, len(ls) - self.view_lines)
        if k.name in DOWN:
            if self.sel is None:
                self.sel = 0
            elif self.sel < n - 1:
                self.sel += 1
            else:
                self.off = min(maxoff, self.off + 1)
                return
            self.follow()
        elif k.name in UP:
            if self.sel is None or self.sel == 0:
                self.sel = None if self.off == 0 else self.sel
                self.off = max(0, self.off - 1)
                return
            self.sel -= 1
            self.follow()
        elif k.name in SELECT:
            if self.sel is not None:
                self.choose(self.q.choices[self.sel][0])
        elif k.char and k.char.lower() in "abd" and not k.ctrl:
            # A, B and D pick directly (C is Right on this keyboard)
            i = "abcd".index(k.char.lower())
            if i < n:
                self.sel = i
                self.follow()
        elif k.name in BACK:
            self.leave()

    def choose(self, key):
        pass

    def leave(self):
        self.app.pop(self)

    def marked(self) -> str | None:
        return None

    def figure(self):
        if self.q.figures:
            self.app.push(Figure(self.app, self.q.figures[0]))

    def paint(self, surf, f):
        ls = self.lines(f)
        self.follow()
        surf.fill(T.BG, (0, self.top_y - 1, T.W, self.bot_y - self.top_y + 1))
        font = f["small"]
        mark = self.marked()
        y = self.top_y
        for text, color, ci in ls[self.off:self.off + self.view_lines]:
            if ci is not None and ci == self.sel:
                surf.fill(T.SEL_BG, (0, y, T.W, LINE_H))
                color = T.SEL_FG
            elif ci is not None and mark is not None and self.q.choices[ci][0] == mark:
                surf.fill(T.SOFT_BG, (0, y, T.W, LINE_H))
            surf.blit(font.render(text, True, color), (7, y), (0, 0, T.W - 12, LINE_H))
            y += LINE_H
        if len(ls) > self.view_lines:
            span = self.bot_y - self.top_y
            bh = max(8, span * self.view_lines // len(ls))
            by = self.top_y + (span - bh) * self.off // max(1, len(ls) - self.view_lines)
            surf.fill(T.RULE, (T.W - 3, by, 3, bh))


class DrillQ(QuestionView):
    def __init__(self, app, name, drill: B.Drill, q):
        self.name, self.d = name, drill
        super().__init__(app, q)

    def right(self):
        return f"{self.name}  {self.d.right}/{self.d.done}"

    def softkeys(self):
        return [("Fig", self.figure) if self.q.figures else None, ("Skip", self.skip), None, None,
                ("End", self.end)]

    def skip(self):
        self.d.queue.append(self.q)
        q = self.d.next()
        self.set_q(q)

    def choose(self, key):
        ok = key == self.q.answer
        self.d.answer(self.q, ok)
        self.app.push(Feedback(self.app, self.q, ok, self.after, f"{self.name}  {self.d.right}/{self.d.done}"))

    def after(self):
        q = self.d.next()
        if q is None:
            self.end()
        else:
            self.set_q(q)

    def end(self):
        while self.app.stack and self.app.stack[-1] is not self:
            self.app.pop(self.app.stack[-1])
        self.app.pop(self)
        if self.d.done:
            self.app.push(Message(self.app, "Session done",
                                  f"{self.d.right} of {self.d.done} right ({pct(self.d.right, self.d.done)}).",
                                  L.OK if self.d.right * 4 >= self.d.done * 3 else L.WARN))

    leave = end


class ExamQ(QuestionView):
    help = HELP_EXAM

    def __init__(self, app, qs):
        self.qs, self.i = qs, 0
        self.answers: dict[int, str] = {}
        super().__init__(app, qs[0])

    @property
    def title(self):
        return f"Exam {self.i + 1}/{len(self.qs)}"

    def right(self):
        return self.q.id

    def marked(self):
        return self.answers.get(self.i)

    def softkeys(self):
        return [("Back", lambda: self.go(-1)) if self.i else None, ("Fig", self.figure) if self.q.figures else None,
                ("Next", lambda: self.go(1)) if self.i < len(self.qs) - 1 else None, None,
                (("Finish", L.WARN), self.finish)]

    def go(self, d):
        self.i = max(0, min(len(self.qs) - 1, self.i + d))
        mark = self.answers.get(self.i)
        sel = next((j for j, (k, _) in enumerate(self.qs[self.i].choices) if k == mark), None)
        self.set_q(self.qs[self.i], sel)

    def choose(self, key):
        self.answers[self.i] = key
        if self.i < len(self.qs) - 1:
            self.go(1)
        elif len(self.answers) == len(self.qs):
            self.finish()

    def finish(self):
        left = len(self.qs) - len(self.answers)
        if left:
            self.app.push(Confirm(self.app, "Finish exam?",
                                  f"{left} question{'s' if left > 1 else ''} not answered yet; they count as wrong. "
                                  "Score the exam now?", self.score, "OK score", "ESC keep going"))
        else:
            self.score()

    def score(self):
        p = self.app.pool
        right = 0
        for i, q in enumerate(self.qs):
            ok = self.answers.get(i) == q.answer
            right += ok
            self.app.prog.answer(q, ok, save=False)
        self.app.prog.add_exam(p, right, len(self.qs))
        self.app.pop(self)
        self.app.push(ExamResult(self.app, self.qs, self.answers, right))

    def leave(self):
        self.app.push(Confirm(self.app, "Leave exam?", "This practice exam will not be scored.",
                              lambda: self.app.pop(self), "OK leave", "ESC stay"))


class Feedback(Screen):
    """After an answer: right or not, then the correct answer and its rule.
    Never says anything about the choice that was picked."""
    help = HELP_FB
    top_y = T.TITLE_H + 2
    bot_y = T.H - T.KEYBAR_H - 1

    def __init__(self, app, q: B.Question, ok, then, right_text="", show_stem=False):
        super().__init__(app)
        self.q, self.ok, self.then, self.rt, self.show_stem = q, ok, then, right_text, show_stem
        self.off = 0
        self._lines = None

    @property
    def title(self):
        return self.q.id

    def right(self):
        return self.rt

    def softkeys(self):
        return [("Next", self.next), ("Fig", lambda: self.app.push(Figure(self.app, self.q.figures[0])))
                if self.q.figures else None, None, None, ("End", self.end)]

    def lines(self, f):
        if self._lines is None:
            font = f["small"]
            w = T.W - 14
            out = []
            if self.ok is not None:
                out.append(("Correct!" if self.ok else f"The answer is {self.q.answer}",
                            GOOD if self.ok else T.WARN, False))
            if self.show_stem:
                out += [(l, T.DIM, False) for l in T.wrap_text(font, self.q.stem, w)]
            out += [(l, T.FG, True) for l in T.wrap_text(font, f"{self.q.answer}. {self.q.answer_text()}", w, "    ")]
            ex = self.app.pool.explain(self.q.id)
            if ex:
                if ex.get("method"):
                    out.append(("How to get it", T.WARN, False))
                    for m in ex["method"]:
                        out += [(l, T.FG, False) for l in T.wrap_text(font, f"- {m}", w, "  ")]
                if ex.get("example"):
                    out += [(l, T.DIM, False) for l in T.wrap_text(font, ex["example"], w)]
            if self.q.refs:
                out.append((f"Rule: {self.q.refs}", T.DIM, False))
            if not ex:
                out.append((LEARN, T.AMBER, False))
            self._lines = out
        return self._lines

    @property
    def view_lines(self):
        return (self.bot_y - self.top_y) // LINE_H

    def paint(self, surf, f):
        ls = self.lines(f)
        surf.fill(T.BG, (0, self.top_y - 1, T.W, self.bot_y - self.top_y + 1))
        font = f["small"]
        y = self.top_y
        for text, color, hl in ls[self.off:self.off + self.view_lines]:
            if hl:
                surf.fill(RIGHT_BG, (0, y, T.W, LINE_H))
            surf.blit(font.render(text, True, GOOD if hl else color), (7, y), (0, 0, T.W - 12, LINE_H))
            y += LINE_H

    def key(self, k):
        maxoff = max(0, len(self._lines or []) - self.view_lines)
        if k.name in DOWN:
            self.off = min(maxoff, self.off + 1)
        elif k.name in UP:
            self.off = max(0, self.off - 1)
        elif k.name in SELECT:
            self.next()
        elif k.name in BACK:
            self.end()

    def next(self):
        self.app.pop(self)
        if self.then:
            self.then()

    def end(self):
        self.app.pop(self)
        under = self.app.stack[-1] if self.app.stack else None
        if isinstance(under, DrillQ):
            under.end()
        elif isinstance(under, Review):
            self.app.pop(under)


class ExamResult(Menu):
    help = "Your score, how each subelement went, and a review of the questions you missed."

    def __init__(self, app, qs, answers, right):
        p = app.pool
        self.missed = [q for i, q in enumerate(qs) if answers.get(i) != q.answer]
        passed = right >= p.passing
        items = [((f"PASSED  {right} / {len(qs)}" if passed else f"Not yet  {right} / {len(qs)}"), None,
                  f"need {p.passing}", L.OK if passed else L.BAD)]
        if self.missed:
            items.append((f"Review missed ({len(self.missed)})", self.review, "", L.WARN))
        for s in p.subs:
            n = sum(1 for q in qs if q.sub == s.id)
            r = sum(1 for i, q in enumerate(qs) if q.sub == s.id and answers.get(i) == q.answer)
            items.append((f"{s.id} {s.title}", None, f"{r}/{n}", L.FG if r == n else L.WARN))
        super().__init__(app, "Exam result", items)

    def softkeys(self):
        return [("Review", self.review) if self.missed else None, ("New", self.new), None, None, ("Done", self.app.pop)]

    def review(self):
        if self.missed:
            Review(self.app, self.missed)   # puts itself on the stack

    def new(self):
        self.app.pop(self)
        self.app.push(ExamQ(self.app, self.app.pool.draw_exam()))


class Review(Screen):
    """Walks the missed exam questions: the question, then its correct answer."""

    def __init__(self, app, qs):
        super().__init__(app)
        self.qs, self.i = qs, 0
        app.stack.append(self)
        self.show()

    def show(self):
        q = self.qs[self.i]
        last = self.i == len(self.qs) - 1
        self.app.push(Feedback(self.app, q, None, None if last else self.step,
                               f"{self.i + 1}/{len(self.qs)}", show_stem=True))
        if last:
            fb = self.app.stack[-1]
            fb.then = lambda: self.app.pop(self)

    def step(self):
        self.i += 1
        self.show()


class Figure(Screen):
    help = HELP_FIG
    top_y = T.TITLE_H

    def __init__(self, app, name):
        super().__init__(app)
        self.name = name
        self.zoom = 1
        self.x = self.y = 0
        try:
            self.img = pygame.image.load(B.figure_path(name))
        except (pygame.error, FileNotFoundError):
            self.img = None
        self._cache = {}

    @property
    def title(self):
        return f"Figure {self.name}"

    def softkeys(self):
        return [("Zoom" if self.zoom == 1 else "Fit", self.toggle), None, None, None, ("Close", lambda: self.app.pop(self))]

    def toggle(self):
        self.zoom = 2 if self.zoom == 1 else 1
        self.x = self.y = 0

    def scaled(self):
        if self.zoom not in self._cache:
            w, h = self.img.get_size()
            aw, ah = T.W, T.H - T.TITLE_H - T.KEYBAR_H
            s = min(aw / w, ah / h) * (1 if self.zoom == 1 else 2.6)
            self._cache[self.zoom] = pygame.transform.smoothscale(self.img.convert_alpha(), (int(w * s), int(h * s))) \
                if pygame.display.get_init() and pygame.display.get_surface() else \
                pygame.transform.smoothscale(self.img, (int(w * s), int(h * s)))
        return self._cache[self.zoom]

    def key(self, k):
        step = 40
        if k.name in UP:
            self.y -= step
        elif k.name in DOWN:
            self.y += step
        elif k.name == "left" and self.zoom > 1:
            self.x -= step
        elif k.name == "right":
            self.x += step
        elif k.name == "enter":
            self.toggle()
        elif k.name in BACK:
            self.app.pop(self)

    def paint(self, surf, f):
        aw, ah = T.W, T.H - T.TITLE_H - T.KEYBAR_H
        surf.fill((255, 255, 255), (0, self.top_y, aw, ah))
        if self.img is None:
            surf.blit(f["small"].render("Figure missing", True, T.BAD), (10, 60))
            return
        im = self.scaled()
        w, h = im.get_size()
        self.x = max(0, min(self.x, w - aw))
        self.y = max(0, min(self.y, h - ah))
        ox = (aw - w) // 2 if w < aw else -self.x
        oy = (ah - h) // 2 if h < ah else -self.y
        surf.set_clip((0, self.top_y, aw, ah))
        surf.blit(im, (ox, self.top_y + oy))
        surf.set_clip(None)


class ProgressView(Menu):
    help = ("Chance to pass is an estimate: each exam group counts as right with your record on its "
            "questions (a guess of 1 in 4 for questions you have not seen yet).")

    def __init__(self, app):
        p, pr = app.pool, app.prog
        seen, mast, n = pr.counts(p.questions.values())
        ex = pr.exams_for(p)
        chance = pr.pass_chance(p)
        items = [("Chance to pass now", None, pct(chance, 1), L.OK if chance >= 0.9 else L.WARN if chance >= 0.5 else L.BAD),
                 ("Questions seen", None, f"{seen} / {n}"),
                 ("Mastered", None, f"{mast} / {n}")]
        if ex:
            last = ex[-1]
            items.append(("Practice exams", None, f"{sum(e['passed'] for e in ex)} of {len(ex)} passed"))
            items.append(("Last exam", None, f"{last['score']}/{last['total']}", L.OK if last["passed"] else L.WARN))
        for s in p.subs:
            qs = [q for g in s.groups for q in g.questions]
            _, m, nn = pr.counts(qs)
            items.append((f"{s.id} {s.title}", (lambda s=s: app.push(Groups(app, s))), pct(m, nn)))
        items.append(("Reset progress", self.reset, p.short, L.BAD))
        super().__init__(app, f"Progress: {p.short}", items)

    def reset(self):
        p = self.app.pool

        def yes():
            self.app.prog.records.pop(p.pool_id, None)
            self.app.prog.exams = [e for e in self.app.prog.exams if e.get("pool_id") != p.pool_id]
            self.app.prog.save()
            self.app.pop(self)
        self.app.push(Confirm(self.app, "Reset progress?", f"Clears every answer and exam for the {p.name} "
                              "pool on this device.", yes, "OK reset", "ESC keep"))


def main_ui() -> int:
    panel = L.Panel()
    kb = Keyboard()
    app = App(panel, kb if kb.ok else None)
    try:
        app.run()
    finally:
        if kb:
            kb.close()
    return 0
