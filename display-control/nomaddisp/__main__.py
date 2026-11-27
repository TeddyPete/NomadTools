"""Command line for Nomad Display Control (also handy over SSH).

  nomad-display-control                       run the app (LCD + keyboard)
  nomad-display-control --scan [--save]       find displays on this network
  nomad-display-control --list                saved displays
  nomad-display-control --do NAME CMD [ARG]   run a command on one display
        CMD: status on off inputs input <id> vol <+n|-n> mute [on|off]
             avmute [on|off] pictures picture <mode> message <text>
             info pair wol
  nomad-display-control --room ROOM on|off|mute|unmute   (ROOM "all" = every display)
  nomad-display-control --check IP            which control methods answer (changes nothing)
  nomad-display-control --wol MAC             send a Wake-on-LAN packet
  nomad-display-control --add KIND HOST NAME  save a display (KIND pjlink lg samsung sony roku)
  nomad-display-control --screens DIR         render sample LCD screens to PNG
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--save", action="store_true", help="with --scan: save new ones")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--do", nargs="+", metavar="X")
    ap.add_argument("--room", nargs=2, metavar=("ROOM", "CMD"))
    ap.add_argument("--wol", metavar="MAC")
    ap.add_argument("--check", metavar="IP", help="which control methods answer at IP")
    ap.add_argument("--add", nargs=3, metavar=("KIND", "HOST", "NAME"))
    ap.add_argument("--room-name", default="", help="with --add")
    ap.add_argument("--mac", default="", help="with --add")
    ap.add_argument("--secret", default=None, help="with --add (PJLink password, Sony PSK)")
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    from . import ops, store
    from .base import Display, DisplayError
    if a.screens:
        from .demo import render_screens
        render_screens(a.screens)
        return 0
    if a.check:
        from . import check
        r = check.check(a.check)
        for state, text in r["lines"]:
            print(f"{state:6} {text}")
        return 0 if r["kinds"] else 1
    if a.wol:
        from . import wol
        print(wol.wake(a.wol))
        return 0
    if a.scan:
        from . import discover
        found = discover.scan(progress=lambda t: print("..", t, file=sys.stderr))
        saved = store.load()
        new = 0
        for d in found:
            known = any(x.host == d.host and x.kind == d.kind for x in saved)
            print(f"{d.host:15} {d.kind:8} {d.mac or '-':17} {d.name}  {d.model}{'  (saved)' if known else ''}")
            if a.save and not known:
                if d.kind == "lg":
                    from .lgwebos import legacy_key
                    d.secret = d.secret or legacy_key()
                saved.append(d)
                new += 1
        if a.save:
            store.save(saved)
            print(f"saved {new} new")
        print(f"{len(found)} found")
        return 0
    if a.list:
        for d in store.load():
            print(f"{d.id}  {d.host:15} {d.kind:8} {d.room or '-':12} {d.mac or '-':17} {d.name}"
                  f"{'  [key]' if d.secret else ''}")
        return 0
    if a.add:
        kind, host, name = a.add
        ds = store.load()
        d = Display(name, kind, host, mac=a.mac, room=a.room_name)
        if a.secret is not None:
            d.secret = a.secret
        elif kind == "lg":
            from .lgwebos import legacy_key
            d.secret = legacy_key()
        ds.append(d)
        store.save(ds)
        print(f"saved {d.id} {name}")
        return 0
    if a.do:
        ds = store.load()
        d = store.find(ds, a.do[0])
        if not d:
            print(f"no saved display '{a.do[0]}' (see --list)", file=sys.stderr)
            return 2
        cmd = a.do[1] if len(a.do) > 1 else "status"
        arg = " ".join(a.do[2:]) if len(a.do) > 2 else None
        if cmd == "vol" and arg:
            arg = int(arg)
        try:
            r = ops.run(d, cmd, arg)
        except (DisplayError, OSError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if cmd == "pair":
            store.save(ds)
        print(r if isinstance(r, str) else json.dumps(r, indent=1))
        return 0
    if a.room:
        room, cmd = a.room
        ds = store.load()
        members = ds if room.lower() == "all" else [d for d in ds if d.room.strip().lower() == room.lower()]
        arg = None
        if cmd in ("mute", "unmute"):
            cmd, arg = "mute", ("on" if cmd == "mute" else "off")
        res = ops.group(members, cmd, arg)
        for d, ok, t in res:
            print(f"{'OK  ' if ok else 'FAIL'} {d.name}: {t}")
        print(ops.summary(res))
        return 0 if all(ok for _, ok, _ in res) else 1
    from .app import main_ui
    return main_ui()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
