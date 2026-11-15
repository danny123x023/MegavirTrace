"""Cell maps of big regions: merged into blocks for the whole region, full detail for a view."""

from __future__ import annotations

import numpy as np
import pytest

from megavir.api import service
from megavir.engine.aggregate import region_mean
from megavir.engine.cellmap import block_size, merge_blocks
from tests.conftest import ORIGIN


def _grid(n: int):
    ii, jj = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    return ii.ravel(), jj.ravel()


def test_block_size_is_the_smallest_that_fits():
    ii, jj = _grid(8)  # 64 cells
    assert block_size(ii, jj, 64) == 1
    assert block_size(ii, jj, 16) == 2
    assert block_size(ii, jj, 9) == 3  # 8 rows in blocks of 3 -> 3 x 3
    assert block_size(ii, jj, 1) == 8


def test_merge_blocks_is_a_weighted_mean_that_skips_missing_cells():
    ii, jj = _grid(4)
    cube = np.tile(np.arange(16, dtype=float), (3, 1))
    cube[1, 0] = np.nan
    w = np.ones(16)
    w[1] = 3.0
    r = merge_blocks(cube, ii, jj, w, np.ones(16), 2)
    assert list(r["bi"]) == [0, 0, 1, 1] and list(r["bj"]) == [0, 1, 0, 1]
    # block (0, 0) holds cells 0, 1, 4, 5 with weights 1, 3, 1, 1
    assert r["cube"][0, 0] == pytest.approx((0 + 3 + 4 + 5) / 6)
    assert r["cube"][1, 0] == pytest.approx((3 + 4 + 5) / 5)  # cell 0 missing that month
    assert r["cube"][0, 3] == pytest.approx((10 + 11 + 14 + 15) / 4)
    # less than half of a block's weight with data: missing
    cube[2, [1, 4]] = np.nan  # weights 3 + 1 of 6 gone
    assert np.isnan(merge_blocks(cube, ii, jj, w, np.ones(16), 2)["cube"][2, 0])


def test_chunked_region_mean_matches_the_direct_formula():
    rng = np.random.default_rng(3)
    cube = rng.normal(size=(30, 500)).astype(np.float32)
    cube[rng.random(cube.shape) < 0.2] = np.nan
    w = rng.random(500)
    mean, cov = region_mean(cube, w)
    ok = np.isfinite(cube)
    want = np.where(ok, cube, 0) @ w / (ok @ w)
    assert np.allclose(mean, want) and np.allclose(cov, (ok @ w) / w.sum())


@pytest.mark.db
def test_big_region_is_merged_and_a_view_gets_full_detail(client, monkeypatch):
    monkeypatch.setattr(service, "MAX_MAP_CELLS", 20)
    monkeypatch.setattr(service, "MAP_TARGET_CELLS", 12)
    # a request no other test makes, so the result is computed here with the small limits
    body = {
        "variable": "air_temp",
        "region": {"place": "country:TST"},
        "cell_map": True,
        "mode": "season",
        "season": "SON",
    }
    cm = client.post("/analysis/trend", json=body, headers=ORIGIN).json()["cell_map"]
    assert cm["block"] > 1 and cm["res"] == pytest.approx(cm["native_res"] * cm["block"])
    assert 2 <= cm["n_cells"] <= 12 and cm["scope"] == "region"
    view = {**body, "view": [-95, 28, -91, 31]}
    v = client.post("/analysis/cells", json=view, headers=ORIGIN).json()
    assert v["scope"] == "view" and v["view"] == [-95, 28, -91, 31]
    d = v[
        "res"
    ]  # cells of the view (merged too here, with these tiny limits) lie in it, give or take a block
    assert all(-95 - d <= x <= -91 + d for x in v["lon"]) and all(28 - d <= y <= 31 + d for y in v["lat"])
    assert v["n_cells"] <= cm["n_cells"] * 4
    assert "area in view" in v["caveat"]
    away = client.post("/analysis/cells", json={**body, "view": [10, 10, 20, 20]}, headers=ORIGIN).json()
    assert away["skipped"] == "no cells of the region in view"
    assert client.post("/analysis/cells", json={**body, "view": [1, 2, 3]}, headers=ORIGIN).status_code == 422
