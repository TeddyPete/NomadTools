"""Checks that run on a PC (no LCD or keyboard). Capture tests need tcpdump
and capture rights (run as root, or after the package's setcap):

    cd pcap-capture && python3 tests/test_basic.py
"""
import os
import socket
import sys
import tempfile
import threading
import time

TMP = tempfile.mkdtemp()
os.environ.update(TNT_CAPTURE_DIR=os.path.join(TMP, "caps"), XDG_CONFIG_HOME=os.path.join(TMP, "cfg"),
                  XDG_RUNTIME_DIR=os.path.join(TMP, "rt"), SDL_VIDEODRIVER="dummy")
os.makedirs(os.environ["XDG_RUNTIME_DIR"])
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tntcap import app as A  # noqa: E402
from tntcap import capture as C  # noqa: E402
from tntcap import files as F  # noqa: E402
from tntcap import lcd as L  # noqa: E402
from tntcap import pcapread  # noqa: E402
from tntcap.keys import Key  # noqa: E402


def test_filters():
    assert C.build_filter({"preset": "all"}) == ""
    f = C.build_filter({"preset": "ptp", "host": "10.0.0.5", "port": "319"})
    assert f.startswith("((udp and") and f.endswith("and (host 10.0.0.5) and (port 319)")
    for key, *_ in C.PRESETS:
        expr = C.build_filter({"preset": key, "custom": "udp"})
        assert C.check_filter(expr) == "", (key, C.check_filter(expr))
    assert C.check_filter("udp prot 1") != ""
    assert C.seconds_of("15 min") == 900 and C.seconds_of("No limit") == 0
    assert C.mb_of("2 GB") == 2000


def blast(port, seconds):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    end = time.time() + seconds
    while time.time() < end:
        s.sendto(b"x" * 200, ("127.0.0.1", port))
        time.sleep(0.002)


def press(app, *names):
    for n in names:
        k = Key(n, n if len(n) == 1 else "")
        top = app.stack[-1]
        top.key(k if top.text_entry else A.nav_key(k))
        for _ in range(80):              # let Busy screens finish
            app.poll()
            if app.stack:
                app.stack[-1].tick()
            if not app.stack or not isinstance(app.stack[-1], A.Busy):
                break
            time.sleep(0.1)
        app.draw()


def test_ui_capture_flow():
    if os.geteuid() != 0:
        print("skip capture flow (needs root or setcap tcpdump)")
        return
    app = A.App(L.Panel(headless=True), None)
    app.cfg.update(iface="lo", preset="ptp", duration="No limit")
    app.push(A.Home(app))
    app.draw()
    press(app, "enter")                       # Start capture -> Live view
    assert app.capturing, app.state
    assert isinstance(app.stack[-1], A.LiveView)
    t = threading.Thread(target=blast, args=(319, 2))
    t.start()
    t.join()
    time.sleep(1.2)
    app.poll()
    assert app.state["packets"] > 100, app.state
    assert app.follower.protos.get("PTP", 0) > 50, app.follower.protos
    press(app, "enter")                       # stop
    assert not app.capturing
    assert app.state["reason"] == "stopped"
    press(app, "esc")                         # back home
    saved = F.listing()
    assert len(saved) == 1 and saved[0].meta["packets"] > 100
    r = pcapread.summarize(saved[0].path)
    assert r["packets"] == saved[0].meta["packets"], (r, saved[0].meta)
    # Saved captures -> file -> Delete -> confirm
    press(app, *["x"] * 5, "enter")
    assert isinstance(app.stack[-1], A.FilesMenu), app.stack
    press(app, "enter")
    assert isinstance(app.stack[-1], A.FileInfo)
    labels = [it[0] for it in app.stack[-1].items]
    press(app, *["x"] * labels.index("Delete"), "enter", "enter")
    assert F.listing() == []
    # ESC on the main page quits
    while len(app.stack) > 1:
        press(app, "esc")
    press(app, "esc")
    assert app.quit


def test_size_limit():
    if os.geteuid() != 0:
        return
    C.start({"iface": "lo", "preset": "all", "size": "1 MB", "duration": "No limit", "mode": "Stop at limit"})
    blast(5004, 0.2)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    end = time.time() + 10
    while C.running() and time.time() < end:
        s.sendto(b"y" * 1400, ("127.0.0.1", 5004))
    time.sleep(1)
    st = C.read_state()
    assert st["reason"] == "size limit", st
    assert st["bytes"] < 3_000_000


def test_web():
    from urllib.request import urlopen

    from tntcap import web
    sh = web.Share(port=18080)
    assert sh.start()
    html = urlopen(f"http://127.0.0.1:{sh.port}/").read().decode()
    assert "TNT Packet Capture" in html
    try:
        urlopen(f"http://127.0.0.1:{sh.port}/../../etc/passwd")
        raise AssertionError("served a file outside the folder")
    except Exception as e:
        assert "404" in str(e), e
    # delete through the page (POST), never outside the folder
    import urllib.parse
    from urllib.request import Request
    os.makedirs(C.ROOT, exist_ok=True)
    keep = os.path.join(TMP, "outside.pcap")
    open(keep, "wb").write(b"x")
    victim = os.path.join(C.ROOT, "20260101-000000_All_eth0.pcap")
    open(victim, "wb").write(b"\xd4\xc3\xb2\xa1" + b"\0" * 20)
    assert "20260101-000000_All_eth0.pcap" in urlopen(f"http://127.0.0.1:{sh.port}/").read().decode()
    for name in ("../outside.pcap", os.path.basename(victim)):
        body = urllib.parse.urlencode({"name": name}).encode()
        urlopen(Request(f"http://127.0.0.1:{sh.port}/delete", data=body))
    assert not os.path.exists(victim) and os.path.exists(keep)
    sh.stop()


def test_qr():
    from tntcap import qr
    m = qr.matrix("http://192.168.51.24:8080/")
    assert len(m) == 25
    try:
        import cv2
        import numpy as np
    except ImportError:
        return
    n = len(m) + 8
    img = np.full((n * 8, n * 8), 255, np.uint8)
    for r, row in enumerate(m):
        for c, v in enumerate(row):
            if v:
                img[(r + 4) * 8:(r + 5) * 8, (c + 4) * 8:(c + 5) * 8] = 0
    assert cv2.QRCodeDetector().detectAndDecode(img)[0] == "http://192.168.51.24:8080/"


def test_recover_ring_leftovers():
    d = os.path.join(TMP, "rec")
    os.makedirs(d)
    for i in (0, 1, 2):
        open(os.path.join(d, f"20260101-000000_All_eth0.pcap{i}"), "wb").write(b"x")
        time.sleep(0.01)
    F.recover(d)
    assert sorted(os.listdir(d)) == [f"20260101-000000_All_eth0_part0{i}.pcap" for i in (1, 2, 3)]


def test_tap_guards():
    from tntcap import tap
    assert tap.why_not("") != ""
    assert tap.why_not(tap.builtin()) != ""
    for k in ("up", "ports", "builtin", "adapters"):
        assert k in tap.status()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
