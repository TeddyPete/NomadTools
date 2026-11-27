"""Question pools, practice exam draws, learner progress and readiness.

Pools come from data/<pool_id>.json (copied from Ask Elmer by
scripts/import_pools.py). Question text, answer keys and rule references are
the official NCVEC ones and are never changed here. Every learner record
carries its pool_id.
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PKG = "askelmer-ham-exam"


@dataclass
class Question:
    id: str
    pool_id: str
    sub: str
    group: str
    stem: str
    choices: list          # [(key, text)]
    answer: str
    refs: str
    figures: list

    def answer_text(self) -> str:
        return next((t for k, t in self.choices if k == self.answer), "")


@dataclass
class Group:
    id: str
    topics: str
    questions: list = field(default_factory=list)


@dataclass
class Sub:
    id: str
    title: str
    exam_questions: int
    groups: list


class Pool:
    def __init__(self, path: str):
        d = json.load(open(path, encoding="utf-8"))
        self.pool_id = d["pool_id"]
        self.exam_id, self.name, self.short = d["exam_id"], d["name"], d["short"]
        self.per_exam, self.passing = d["questions_per_exam"], d["passing_score"]
        self.effective_from, self.effective_to = d["effective_from"], d["effective_to"]
        self.element = d["element"]
        self.questions: dict[str, Question] = {}
        for q in d["questions"]:
            if q["status"] != "active" or not q["choices"]:
                continue
            self.questions[q["id"]] = Question(q["id"], self.pool_id, q["subelement"], q["group"], q["stem"],
                                               [(c["key"], c["text"]) for c in q["choices"]], q["answer"],
                                               q.get("references") or "", q.get("figures") or [])
        self.subs: list[Sub] = []
        self.groups: dict[str, Group] = {}
        for s in d["subelements"]:
            gs = []
            for g in s["groups"]:
                grp = Group(g["id"], g["topics"], [q for q in self.questions.values() if q.group == g["id"]])
                self.groups[g["id"]] = grp
                gs.append(grp)
            self.subs.append(Sub(s["id"], s["title"], s["exam_questions"], gs))
        self._explain = None

    def sub(self, sid: str) -> Sub | None:
        return next((s for s in self.subs if s.id == sid), None)

    def explain(self, qid: str) -> dict | None:
        """Ask Elmer's method for a question, when the explanations are bundled."""
        if self._explain is None:
            p = os.path.join(DATA, f"{self.pool_id}.explain.json")
            try:
                d = json.load(open(p, encoding="utf-8"))
                self._explain = d["questions"] if d.get("pool_id") == self.pool_id else {}
            except (OSError, ValueError, KeyError):
                self._explain = {}
        return self._explain.get(qid)

    def draw_exam(self, rng: random.Random | None = None) -> list[Question]:
        """One question from each group, in syllabus order (the NCVEC draw)."""
        rng = rng or random.Random()
        out = []
        for s in self.subs:
            for g in s.groups:
                if g.questions:
                    out.append(rng.choice(g.questions))
        return out


def exams() -> list[dict]:
    try:
        return json.load(open(os.path.join(DATA, "index.json")))["exams"]
    except (OSError, ValueError, KeyError):
        return []


_pools: dict[str, Pool] = {}


def pool_for(exam_id: str) -> Pool:
    ex = next((e for e in exams() if e["exam_id"] == exam_id), None) or exams()[0]
    pid = ex["pool_id"]
    if pid not in _pools:
        _pools[pid] = Pool(os.path.join(DATA, f"{pid}.json"))
    return _pools[pid]


def figure_path(name: str) -> str:
    return os.path.join(DATA, "figures", f"{name}.png")


# ---- learner progress ------------------------------------------------------------

def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, PKG)


MASTERED = 2    # right this many times in a row


class Progress:
    """records[pool_id][qid] = [seen, right, streak, last_time, last_right]."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config_dir(), "state.json")
        self.exam = "technician"
        self.records: dict[str, dict[str, list]] = {}
        self.exams: list[dict] = []
        try:
            d = json.load(open(self.path))
            self.exam = d.get("exam", self.exam)
            self.records = d.get("records", {})
            self.exams = d.get("exams", [])
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"exam": self.exam, "records": self.records, "exams": self.exams[-50:]}, fh,
                          separators=(",", ":"))
            os.replace(tmp, self.path)
        except OSError:
            pass

    def rec(self, q: Question) -> list | None:
        return self.records.get(q.pool_id, {}).get(q.id)

    def answer(self, q: Question, right: bool, save: bool = True) -> None:
        r = self.records.setdefault(q.pool_id, {}).setdefault(q.id, [0, 0, 0, 0, 0])
        r[0] += 1
        r[1] += 1 if right else 0
        r[2] = r[2] + 1 if right else 0
        r[3] = int(time.time())
        r[4] = 1 if right else 0
        if save:
            self.save()

    def add_exam(self, pool: Pool, score: int, total: int) -> None:
        self.exams.append({"pool_id": pool.pool_id, "t": int(time.time()), "score": score, "total": total,
                           "passed": score >= pool.passing})
        self.save()

    def exams_for(self, pool: Pool) -> list[dict]:
        return [e for e in self.exams if e.get("pool_id") == pool.pool_id]

    # status of one question
    def mastered(self, q: Question) -> bool:
        r = self.rec(q)
        return bool(r and r[2] >= MASTERED)

    def missed(self, q: Question) -> bool:
        r = self.rec(q)
        return bool(r and r[0] and not r[4])

    def p_right(self, q: Question) -> float:
        """Rough chance of answering right now: a guess for unseen questions,
        smoothed history otherwise, high once mastered."""
        r = self.rec(q)
        if not r or not r[0]:
            return 0.25
        if r[2] >= MASTERED:
            return 0.95
        p = (r[1] + 0.25) / (r[0] + 1)
        return min(0.9, p * (0.7 if not r[4] else 1.0) + (0.15 if r[4] else 0))

    def counts(self, qs) -> tuple[int, int, int]:
        """(seen, mastered, total)."""
        seen = mastered = n = 0
        for q in qs:
            n += 1
            r = self.rec(q)
            if r and r[0]:
                seen += 1
                if r[2] >= MASTERED:
                    mastered += 1
        return seen, mastered, n

    def pass_chance(self, pool: Pool) -> float:
        """Chance of passing a fresh exam now: each group's draw is right with
        that group's average p_right; the number right is a sum of those."""
        ps = []
        for s in pool.subs:
            for g in s.groups:
                if g.questions:
                    ps.append(sum(self.p_right(q) for q in g.questions) / len(g.questions))
        dist = [1.0]
        for p in ps:
            nd = [0.0] * (len(dist) + 1)
            for k, v in enumerate(dist):
                nd[k] += v * (1 - p)
                nd[k + 1] += v * p
            dist = nd
        return sum(dist[pool.passing:])

    # choosing what to study
    def order(self, qs, rng: random.Random | None = None) -> list[Question]:
        """Missed first, then unseen, then not yet mastered, then mastered
        (oldest first), shuffled within each tier."""
        rng = rng or random.Random()
        tiers: list[list] = [[], [], [], []]
        for q in qs:
            r = self.rec(q)
            if not r or not r[0]:
                tiers[1].append(q)
            elif not r[4]:
                tiers[0].append(q)
            elif r[2] < MASTERED:
                tiers[2].append(q)
            else:
                tiers[3].append(q)
        for t in tiers[:3]:
            rng.shuffle(t)
        tiers[3].sort(key=lambda q: self.rec(q)[3])
        return [q for t in tiers for q in t]


class Drill:
    """A study session: immediate feedback; after a miss the next question is
    a fresh one from the same group, and the missed one comes back later."""

    def __init__(self, prog: Progress, qs, limit: int | None = None, rng: random.Random | None = None):
        self.prog = prog
        self.rng = rng or random.Random()
        self.queue = prog.order(qs, self.rng)
        if limit:
            self.queue = self.queue[:limit]
        self.pool_qs = list(qs)
        self.done = 0
        self.right = 0
        self.requeued: set = set()

    def next(self) -> Question | None:
        return self.queue.pop(0) if self.queue else None

    def answer(self, q: Question, right: bool) -> None:
        self.prog.answer(q, right)
        self.done += 1
        self.right += 1 if right else 0
        if right:
            return
        same = [x for x in self.pool_qs if x.group == q.group and x is not q]
        if same:
            fresh = sorted(same, key=lambda x: (self.prog.mastered(x), x in self.queue, self.rng.random()))[0]
            if fresh in self.queue:
                self.queue.remove(fresh)
            self.queue.insert(0, fresh)
        if q.id not in self.requeued:
            self.requeued.add(q.id)
            self.queue.insert(min(len(self.queue), 4), q)
