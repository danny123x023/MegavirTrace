"""Tabulate the exact AR(1) variance ratio of the Mann–Kendall S.

The ratio Var_AR1(S) / Var_iid(S) is computed exactly (see megavir.engine.stats._ar1_var_sum)
on a grid of record lengths n and lag-1 autocorrelations phi, for the ordinary test (one
value per year) and the seasonal test (12 calendar months).  The engine interpolates this
table linearly in phi and in 1/n, where the ratio is very nearly linear.

Run:  .venv/bin/python scripts/build_ar1_table.py
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from megavir.engine.stats import _ar1_var_sum  # noqa: E402

PHI = np.round(np.arange(0.0, 0.951, 0.01), 2)
N_ANNUAL = list(range(3, 41)) + [45, 50, 60, 70, 80, 100, 120, 150]
N_MONTHLY = list(range(3, 31)) + [35, 40, 45, 50, 60]


def ratio_row(args: tuple[int, int]) -> tuple[int, int, np.ndarray]:
    n, m = args
    base = _ar1_var_sum(n, 0.0, m)
    row = np.array([1.0 if phi == 0 else _ar1_var_sum(n, float(phi), m) / base for phi in PHI])
    return n, m, row


def main() -> None:
    t0 = time.time()
    jobs = [(n, 1) for n in N_ANNUAL] + [(n, 12) for n in N_MONTHLY]
    jobs.sort(key=lambda j: -(j[0] ** 3) * (23 if j[1] == 12 else 1))  # longest first
    out = {1: {}, 12: {}}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for n, m, row in pool.map(ratio_row, jobs):
            out[m][n] = row
            print(f"n={n:4d} m={m:2d} ratio(0.5)={row[50]:.4f}  {time.time() - t0:6.1f}s", flush=True)
    dest = ROOT / "src" / "megavir" / "engine" / "data" / "ar1_ratio.npz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        dest,
        phi=PHI,
        n_annual=np.array(N_ANNUAL),
        annual=np.array([out[1][n] for n in N_ANNUAL]),
        n_monthly=np.array(N_MONTHLY),
        monthly=np.array([out[12][n] for n in N_MONTHLY]),
    )
    print("wrote", dest, f"in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
