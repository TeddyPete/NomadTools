import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hamexam import bank as B  # noqa: E402


def test_pools_load_and_keep_pool_id():
    for e in B.exams():
        p = B.pool_for(e["exam_id"])
        assert p.pool_id == e["pool_id"]
        assert all(q.pool_id == p.pool_id for q in p.questions.values())
        assert all(q.answer in [k for k, _ in q.choices] for q in p.questions.values())
        assert sum(s.exam_questions for s in p.subs) == p.per_exam


def test_questions_match_source_word_for_word():
    src = os.environ.get("ASKELMER", os.path.join(os.path.dirname(__file__), "..", "..", "..", "askelmer"))
    pack = os.path.join(src, "packs", "ham-radio")
    if not os.path.isdir(pack):
        return
    for e in B.exams():
        p = B.pool_for(e["exam_id"])
        q = json.load(open(os.path.join(pack, "pools", p.pool_id, "questions.json")))
        for s in q["questions"]:
            if s["status"] != "active":
                assert s["id"] not in p.questions
                continue
            m = p.questions[s["id"]]
            assert m.stem == s["stem"] and m.answer == s["answer"] and m.refs == (s["references"] or "")
            assert m.choices == [(c["key"], c["text"]) for c in s["choices"]]


def test_exam_draw_is_one_per_group():
    p = B.pool_for("technician")
    qs = p.draw_exam(random.Random(1))
    assert len(qs) == p.per_exam == 35
    assert len({q.group for q in qs}) == 35
    pe = B.pool_for("extra")
    assert len(pe.draw_exam()) == 50


def test_progress_and_drill(tmp_path):
    pr = B.Progress(str(tmp_path / "s.json"))
    p = B.pool_for("technician")
    g = p.groups["T1A"].questions
    d = B.Drill(pr, g, limit=5, rng=random.Random(2))
    q = d.next()
    d.answer(q, False)
    assert pr.missed(q)
    nxt = d.next()
    assert nxt.group == q.group and nxt is not q          # fresh question, same group
    assert q in d.queue                                   # missed one comes back
    pr.answer(q, True)
    pr.answer(q, True)
    assert pr.mastered(q) and not pr.missed(q)
    assert 0 <= pr.pass_chance(p) < 0.01
    pr2 = B.Progress(str(tmp_path / "s.json"))
    assert pr2.records[p.pool_id][q.id][2] == 2
