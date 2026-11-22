"""Tabulate the small-sample bias of the engine's lag-1 autocorrelation estimate.

The engine estimates r1 as the lag-1 sample autocorrelation of least-squares trend residuals
(megavir.engine.stats.lag1_autocorrelation).  For short records this estimate is biased low,
and more so than the textbook (2 + 4 r1)/n of the least-squares AR(1) estimator: at r1 = 0.9
and n = 25 it averages 0.56.  This script simulates Gaussian AR(1) series with a fitted
straight line removed and stores the mean estimate E[r1_hat | r1, n] on a grid, which the
engine inverts (correct_r1_for_trend).

The arrays are added to src/megavir/engine/data/ar1_ratio.npz (keys r1_phi, r1_n, r1_mean);
the Mann-Kendall variance-ratio arrays already in that file are kept unchanged.

Run:  .venv/bin/python scripts/build_r1_bias_table.py
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src" / "megavir" / "engine" / "data" / "ar1_ratio.npz"

PHI = np.round(np.arange(-0.5, 0.991, 0.01), 2)
N = list(range(6, 41)) + [45, 50, 60, 70, 80, 100, 120, 150, 200]
REPS = 20_000
SEED = 20261115


def mean_r1_hat(rng: np.random.Generator, n: int, phi: float, reps: int) -> float:
    e = rng.standard_normal((reps, n))
    x = np.empty_like(e)
    x[:, 0] = e[:, 0] / np.sqrt(1.0 - phi * phi)
    for k in range(1, n):
        x[:, k] = phi * x[:, k - 1] + e[:, k]
    t = np.arange(n, dtype=float)
    tm = t - t.mean()
    xm = x - x.mean(axis=1, keepdims=True)
    resid = xm - ((xm @ tm) / (tm @ tm))[:, None] * tm[None, :]
    r = (resid[:, :-1] * resid[:, 1:]).sum(axis=1) / (resid * resid).sum(axis=1)
    return float(r.mean())


def main() -> None:
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    table = np.empty((len(N), PHI.size))
    for i, n in enumerate(N):
        for j, phi in enumerate(PHI):
            table[i, j] = mean_r1_hat(rng, n, float(phi), REPS)
        print(
            f"n={n:4d}  E[r1_hat | 0.5]={table[i, list(PHI).index(0.5)]:.3f}  {time.time() - t0:6.1f}s",
            flush=True,
        )
    # the mean estimate rises with r1; remove Monte Carlo wiggles so the inverse is unique
    table = np.maximum.accumulate(table, axis=1)
    with np.load(DEST) as z:
        keep = {k: z[k] for k in z.files if not k.startswith("r1_")}
    np.savez_compressed(DEST, **keep, r1_phi=PHI, r1_n=np.array(N), r1_mean=table)
    print("wrote", DEST, f"in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
