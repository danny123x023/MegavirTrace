"""A small synthetic store for software tests (kind='synthetic', always labelled as made up).

Every variable gets a 0.5° (or its own grid) window around the test box with a seasonal cycle,
AR(1) year-to-year noise and a known trend that changes sign across the window, so tests can
check that the engine finds what was put in.
"""

from __future__ import annotations

import numpy as np

from megavir.catalog import DATASETS, VARIABLES
from megavir.store import GridSpec, write_version

from .pipeline import TEST_BOX

# (mean, seasonal amplitude, noise sd, trend per year at the window's west edge)
PARAMS = {
    "air_temp": (20.0, 8.0, 0.4, 0.03),
    "daily_high": (26.0, 8.0, 0.5, 0.035),
    "nightly_low": (14.0, 7.0, 0.5, 0.045),
    "ground_temp": (22.0, 10.0, 0.6, 0.04),
    "temp_change": (0.5, 0.2, 0.3, 0.025),
    "rainfall": (110.0, 30.0, 25.0, 0.4),
    "downpour": (1.5, 0.5, 0.2, 0.01),
    "evapotranspiration": (70.0, 40.0, 6.0, 0.3),
    "topsoil_moisture": (25.0, 3.0, 2.0, -0.05),
    "soil_moisture": (300.0, 20.0, 15.0, -0.8),
    "land_water": (0.0, 5.0, 3.0, -0.3),
    "no2": (3.0, 1.0, 0.3, -0.06),
    "fire_carbon": (2.0, 2.0, 1.0, 0.0),
    "ndvi": (0.55, 0.15, 0.03, 0.002),
    "sea_level": (0.0, 40.0, 20.0, 5.0),
    "sea_surface_temp": (26.0, 3.0, 0.3, 0.02),
    "land_surface_temp": (24.0, 10.0, 0.6, 0.04),
    "snow_cover": (20.0, 15.0, 4.0, -0.3),
    "aerosols": (0.2, 0.05, 0.02, -0.002),
    "energy_budget": (10.0, 60.0, 2.0, 0.05),
    "sea_ice": (30.0, 20.0, 5.0, -0.5),
    "co2": (405.0, 3.0, 0.3, 2.3),
}


def synthetic_cube(
    var: str, spec: GridSpec, first_year: int, years: int, rng: np.random.Generator
) -> np.ndarray:
    mean, amp, sd, trend = PARAMS[var]
    n = 12 * years
    t = np.arange(n) / 12.0
    season = amp * np.sin(2 * np.pi * (np.arange(n) % 12 - 3) / 12)
    # trend varies from +trend (west) to -trend/2 (east): opposite trends exist inside the window
    xfrac = np.linspace(0, 1, spec.nx)[None, :]
    trend_map = trend * (1 - 1.5 * xfrac) * np.ones((spec.ny, 1))
    # shared AR(1) noise (regions move together) plus a little cell noise
    phi = 0.5
    e = rng.standard_normal(n)
    shared = np.empty(n)
    shared[0] = e[0]
    for k in range(1, n):
        shared[k] = phi * shared[k - 1] + e[k] * np.sqrt(1 - phi**2)
    cube = (
        mean
        + season[:, None, None]
        + trend_map[None] * t[:, None, None]
        + sd * shared[:, None, None]
        + 0.3 * sd * rng.standard_normal((n, spec.ny, spec.nx))
    )
    if var in ("rainfall", "fire_carbon", "evapotranspiration", "downpour", "no2", "aerosols"):
        cube = np.clip(cube, 0, None)
    if var in ("snow_cover", "sea_ice"):
        cube = np.clip(cube, 0, 100)
    return cube.astype(np.float32)


def build_synthetic(
    conn, years: int = 24, first_year: int = 2001, pad: float = 5.0, seed: int = 2026
) -> dict:
    rng = np.random.default_rng(seed)
    w, s, e, n = TEST_BOX
    out = {}
    for var, meta in VARIABLES.items():
        res = DATASETS[meta.dataset].stored_grid_deg
        spec = GridSpec.global_grid(res).window(s - pad, n + pad, w - pad, e + pad)
        cube = synthetic_cube(var, spec, first_year, years, rng)
        vid = write_version(
            conn,
            var,
            "synthetic",
            spec,
            first_year * 12,
            cube,
            meta.units,
            {"product": "SYNTHETIC", "note": "made-up data for software tests"},
            {"months": int(cube.shape[0]), "synthetic": True},
            activate=True,
        )
        out[var] = vid
    conn.commit()
    return out
