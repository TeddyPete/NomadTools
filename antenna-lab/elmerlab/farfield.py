"""Far-field pattern from segment currents, with real-ground reflections.

Used for the MININEC-style ground (currents solved over perfect ground, then
the pattern over real ground), which is how EZNEC models ground-mounted
verticals whose buried radials NEC2 cannot. Port of Ask Elmer's farfield.ts,
vectorised with numpy.
"""
from __future__ import annotations

import math

import numpy as np

from .nec import C0

ETA = 376.730313


def segments(model, segs: list, currents: list):
    """(positions N x 3, segment vectors N x 3, complex currents N)."""
    by_tag: dict[int, list] = {}
    for c in currents:
        by_tag.setdefault(c["tag"], []).append(c)
    pos, dl, cur = [], [], []
    for i, w in enumerate(model.wires):
        lst = by_tag.get(i + 1, [])
        n = segs[i]
        d = [(w.b[k] - w.a[k]) / n for k in range(3)]
        for k in range(n):
            if k >= len(lst):
                break
            c = lst[k]
            pos.append([w.a[j] + d[j] * (k + 0.5) for j in range(3)])
            dl.append(d)
            cur.append(c["mag"] * complex(math.cos(math.radians(c["phase"])), math.sin(math.radians(c["phase"]))))
    return np.array(pos, float), np.array(dl, float), np.array(cur, complex)


def compute_pattern(pos, dl, cur, mhz: float, input_w: float, ground, theta_step: float, phi_step: float):
    """ground: None (free space), "perfect", or (er, sigma). Returns (points, average_gain);
    points are (theta, phi, vert_db, horiz_db, total_db) like NEC's RP table."""
    lam = C0 / mhz
    k = 2 * math.pi / lam
    tmax = 90 if ground else 180
    thetas = np.arange(0, tmax + 1e-9, theta_step)
    phis = np.arange(0, 360 - 1e-9, phi_step)
    T, P = np.meshgrid(np.radians(thetas), np.radians(phis))   # phi rows, theta fastest
    st, ct, sp, cp = np.sin(T), np.cos(T), np.sin(P), np.cos(P)
    rhat = np.stack([st * cp, st * sp, ct], -1)
    thhat = np.stack([ct * cp, ct * sp, -st], -1)
    phhat = np.stack([-sp, cp, np.zeros_like(sp)], -1)

    def field(p, d, refl_v=1, refl_h=1):
        phase = np.exp(1j * k * np.tensordot(rhat, p, axes=([2], [1])))   # (phi, theta, N)
        a = phase * cur
        eth = (a * np.tensordot(thhat, d, axes=([2], [1]))).sum(-1)
        eph = (a * np.tensordot(phhat, d, axes=([2], [1]))).sum(-1)
        return eth * refl_v, eph * refl_h

    eth, eph = field(pos, dl)
    if ground:
        rv = rh = np.ones_like(T, complex)
        if ground != "perfect":
            er, sig = ground
            ec = complex(er, -60 * lam * sig)
            sin_psi = ct
            root = np.sqrt(ec - st * st + 0j)
            es = ec * sin_psi
            rv = (es - root) / (es + root)
            rh = -((sin_psi - root) / (sin_psi + root))
        ipos = pos * np.array([1, 1, -1])
        idl = dl * np.array([-1, -1, 1])
        ith, iph = field(ipos, idl, rv, rh)
        eth, eph = eth + ith, eph + iph
    c = ETA * k * k / (8 * math.pi * max(input_w, 1e-30))
    gv, gh = c * np.abs(eth) ** 2, c * np.abs(eph) ** 2
    g = gv + gh

    def db(x):
        return np.where(x > 1e-30, 10 * np.log10(np.maximum(x, 1e-30)), -999.99)

    dv, dh, dt = db(gv), db(gh), db(g)
    w = np.maximum(st, 1e-6) * np.where((np.abs(T) < 1e-9) | (np.abs(np.degrees(T) - tmax) < 1e-9), 0.5, 1)
    avg = float((g * w).sum() / w.sum())
    pts = []
    for i, ph in enumerate(phis):
        for j, th in enumerate(thetas):
            pts.append((float(th), float(ph), float(dv[i, j]), float(dh[i, j]), float(dt[i, j])))
    return pts, avg
