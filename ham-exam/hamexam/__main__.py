"""Command line for Ask Elmer Ham Exam (also handy over SSH).

  askelmer-ham-exam                       run the app (LCD + keyboard)
  askelmer-ham-exam --exams               the pools in this build
  askelmer-ham-exam --draw technician     print a practice exam draw (ids)
  askelmer-ham-exam --screens DIR         render sample LCD screens to PNG
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exams", action="store_true")
    ap.add_argument("--draw", metavar="EXAM")
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    from . import bank as B
    if a.exams:
        for e in B.exams():
            p = B.pool_for(e["exam_id"])
            print(f"{e['exam_id']:11} {p.pool_id:22} {len(p.questions)} questions, "
                  f"{p.per_exam} per exam, pass {p.passing}")
        return 0
    if a.draw:
        p = B.pool_for(a.draw)
        print(" ".join(q.id for q in p.draw_exam()))
        return 0
    if a.screens:
        from .demo import render_screens
        for f in render_screens(a.screens):
            print(f)
        return 0
    from .app import main_ui
    return main_ui()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
