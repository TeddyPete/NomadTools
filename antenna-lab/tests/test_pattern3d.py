import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from elmerlab import lab, nec, templates as TP  # noqa: E402


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
    from elmerlab import lcd as L
    from elmerlab.app import App, Design, Pattern3D
    app = App(L.Panel(headless=True), None)
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
