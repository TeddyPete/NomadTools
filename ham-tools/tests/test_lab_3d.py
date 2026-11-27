import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hamtools.lab import lab, nec, templates as TP  # noqa: E402


def test_pattern3d_grid_and_wires():
    t = TP.by_id("dipole")
    p = t.defaults(14.2)
    r = lab.run_design(t, p, 14.2, nec.ground_of("average"), "copper", t.device)
    assert r.wires and len(r.wires[0]) == 2
    assert len(r.pattern3d) == 16 * 36            # theta 0..90 step 6, phi step 10
    assert max(g for _t, _p, g in r.pattern3d) <= r.gain + 1e-6


def test_ground_plane_defaults_clear_the_ground():
    t = TP.by_id("ground-plane")
    for mhz in (7.15, 14.2, 28.4):
        r = lab.run_design(t, t.defaults(mhz), mhz, nec.ground_of("average"), "copper", t.device)
        assert r.gain is not None and not r.errors


def test_3d_screen_draws():
    from hamtools import lcd as L
    from hamtools.app import App
    from hamtools.lab.screens import Design, Pattern3D, context
    main = App(L.Panel(headless=True), None)
    app = context(main)
    t = TP.by_id("moxon")
    d = Design(app, t)
    d.result = lab.run_design(t, d.p, d.mhz, nec.ground_of("average"), "copper", d.device)
    app.push(d)
    s = Pattern3D(app, d)
    app.push(s)
    for _ in range(3):
        s.toggle_spin()
        s.yaw += 30
        app.draw()


def test_lab_context_and_band_check_link(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from hamtools import lcd as L
    from hamtools.app import App, BandCheck, Home
    from hamtools.lab import screens as S
    main = App(L.Panel(headless=True), None)
    main.push(Home(main))
    bc = BandCheck(main)
    bc.values["MHz"] = "14.2"
    bc.build()
    main.push(bc)
    bc.antenna()                                   # key 8: Antenna Lab at 14.2 MHz
    top = main.stack[-1]
    assert isinstance(top, S.Design) and abs(top.mhz - 14.2) < 1e-9
    assert isinstance(main.stack[-2], S.Home)
    ctx = top.app
    ctx.dirty = True                              # writes go to the main app
    assert main.dirty and ctx.st is not main.st
    ctx.st.units = "m"
    ctx.st.save()
    assert (tmp_path / "askelmer-ham-tools" / "antenna.json").exists()
    main.draw()


def test_migrate_copies_old_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import hamtools
    (tmp_path / "askelmer-shack-tools").mkdir()
    (tmp_path / "askelmer-shack-tools" / "state.json").write_text('{"license": "Extra"}')
    (tmp_path / "askelmer-antenna-lab").mkdir()
    (tmp_path / "askelmer-antenna-lab" / "state.json").write_text('{"units": "m"}')
    hamtools.migrate()
    new = tmp_path / "askelmer-ham-tools"
    assert (new / "state.json").read_text() == '{"license": "Extra"}'
    assert (new / "antenna.json").read_text() == '{"units": "m"}'
