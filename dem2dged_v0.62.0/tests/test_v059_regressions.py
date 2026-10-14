# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.59.0
#
# One test per v0.59.0 change. Every test in this file FAILS on v0.58.1 and
# passes here, except where explicitly noted as a guard against re-breaking
# something v0.58.1 already did correctly.
#
# THE DEFECT
# ----------
# Through v0.58.1, "-resample optimize" ranked candidates with a hold-out
# cross-validation that point-sampled the source onto a sparse training grid
# and scored how well each candidate RECONSTRUCTED the full grid from it.
# That is an upsampling measurement used as a proxy for a downsampling
# decision. On steep terrain at 16x it produced an exactly inverted ranking:
# Cubic B-Spline first (true RMSE 56.5 m), Nearest Neighbor last (0.0 m).
#
# v0.59.0 measures each candidate on the real decimation instead. See the
# module note above dem2dged_compare._catmull_rom_weights(), and
# verify_mountain_terrain_v0.59.0.py for the 32-case ground-truth validation
# (correct pick 6/32 -> 28/32; avoidable error +573.62 m -> +0.53 m).

import math
import os

import pytest

import dem2dged_compare as dc
import dem2dged_lib as dl

from conftest import requires_gdal, make_raster

np = pytest.importorskip("numpy")


# ---------------------------------------------------------------------------
# 1. The bicubic truth reference
# ---------------------------------------------------------------------------

class TestSampleBicubic:
    """_sample_bicubic() is the truth reference the whole method rests on.
    If it is wrong, every ranking built on it is wrong."""

    def test_reproduces_grid_nodes_exactly(self):
        rng = np.random.default_rng(5)
        arr = rng.normal(size=(12, 12)) * 50.0
        valid = np.ones(arr.shape, bool)
        rows, cols = np.mgrid[2:10, 2:10]
        got, ok = dc._sample_bicubic(arr, valid,
                                     cols.astype(float), rows.astype(float))
        assert ok.all()
        assert np.allclose(got, arr[rows, cols], atol=1e-9)

    def test_reproduces_a_plane_exactly_between_nodes(self):
        """Catmull-Rom is exact for linear data, so a plane must come back
        exactly at half-pixel offsets -- this is what makes the reference
        unbiased on a constant slope."""
        rows, cols = np.mgrid[0:14, 0:14].astype(float)
        arr = 3.0 * cols - 2.0 * rows + 7.0
        valid = np.ones(arr.shape, bool)
        u = np.array([[4.5, 5.5], [6.25, 7.75]])
        v = np.array([[4.5, 6.5], [8.25, 9.5]])
        got, ok = dc._sample_bicubic(arr, valid, u, v)
        assert ok.all()
        assert np.allclose(got, 3.0 * u - 2.0 * v + 7.0, atol=1e-9)

    def test_marks_out_of_bounds_and_nodata_taps_unusable(self):
        arr = np.zeros((10, 10))
        valid = np.ones(arr.shape, bool)
        valid[5, 5] = False
        # A sample whose 4x4 stencil includes (5, 5) must be rejected.
        got, ok = dc._sample_bicubic(arr, valid,
                                     np.array([[5.5]]), np.array([[5.5]]))
        assert not ok.any()
        # A sample at the very edge borrows from outside the array.
        got, ok = dc._sample_bicubic(arr, valid,
                                     np.array([[0.0]]), np.array([[0.0]]))
        assert not ok.any()


# ---------------------------------------------------------------------------
# 2. Window selection stays at native spacing
# ---------------------------------------------------------------------------

class TestDecimateWindows:
    """Windows must never decimate: decimating the source would shrink the
    very ratio under test, which is the defect v0.57.0 fixed."""

    def test_small_source_is_used_whole(self):
        assert dc._decimate_windows((1000, 1000), 8.0) == [(0, 0, 1000, 1000)]

    def test_large_source_is_windowed_not_decimated(self):
        side = 8000                       # 64 Mpx, four times the budget
        wins = dc._decimate_windows((side, side), 8.0)
        assert 1 <= len(wins) <= dc.MAX_DECIMATE_WINDOWS
        total = sum(h * w for _r, _c, h, w in wins)
        assert total <= dc.MAX_DECIMATE_PIXELS * 1.02
        for row0, col0, h, w in wins:
            assert row0 >= 0 and col0 >= 0
            assert row0 + h <= side and col0 + w <= side
            # Every window must hold enough target posts to rank anything.
            assert min(h, w) >= dc.MIN_DECIMATE_POSTS * 8.0

    def test_a_huge_ratio_still_yields_a_usable_window(self):
        wins = dc._decimate_windows((9000, 9000), 20.0)
        for _r, _c, h, w in wins:
            assert min(h, w) >= dc.MIN_DECIMATE_POSTS * 20.0


# ---------------------------------------------------------------------------
# 3. Dispatch: a decimation must not be ranked by the hold-out test
# ---------------------------------------------------------------------------

class TestOptimizeDispatch:

    def _patch(self, monkeypatch, seen):
        class _Arr:
            shape = (400, 400)
        cgt = (500000.0, 5.0, 0.0, 5600000.0, 0.0, -5.0)
        monkeypatch.setattr(dc, "_read_source",
                            lambda src: (_Arr(), "V", cgt, "P", None, 1))

        def fake_prepare(arr, valid, cgt_, proj, nodata, ratio):
            seen["ratio"] = float(ratio)
            return {"ratio": float(ratio), "n_windows": 2, "n_phases": 12}

        monkeypatch.setattr(dc, "_prepare_decimate_test", fake_prepare)
        monkeypatch.setattr(dc, "_cleanup_decimate_test",
                            lambda prep: seen.__setitem__("cleaned", True))
        monkeypatch.setattr(dc, "_decimate_stats", lambda prep, alg: {
            "rmse": seen["rmse"][alg], "mae": seen["rmse"][alg],
            "max_abs_err": seen["rmse"][alg], "n_scored": 900,
            "ratio": prep["ratio"], "n_windows": 2, "n_phases": 12,
            "method": "decimate"})

        def forbidden(*a, **k):
            raise AssertionError(
                "a decimation must not be ranked by _holdout_stats in v0.59.0")
        monkeypatch.setattr(dc, "_holdout_stats", forbidden)

    def test_decimation_uses_decimate_and_score_with_the_real_ratio(
            self, monkeypatch):
        seen = {"rmse": {"near": 0.5, "bilinear": 2.0, "cubic": 3.0,
                         "cubicspline": 4.0, "average": 5.0, "lanczos": 6.0}}
        self._patch(monkeypatch, seen)
        alg, label, stats = dc.pick_best_resampling(
            "dem.tif", angular=False, dst_gsd_m=40.0)
        assert alg == "near"
        assert seen["ratio"] == 8.0          # 40 m target / 5 m source
        assert seen.get("cleaned") is True   # scratch rasters removed
        assert set(stats) == set(dict(dc.AUTO_OPTIMIZE_CANDIDATES))
        assert all(st["method"] == "decimate" for st in stats.values())

    def test_upsampling_still_uses_the_holdout_reconstruction_test(
            self, monkeypatch):
        """Where there is no decimation, the hold-out test is the CORRECT
        measure and must be kept -- this is not a fallback, it is the right
        tool for that case."""
        class _Arr:
            shape = (400, 400)
        cgt = (500000.0, 20.0, 0.0, 5600000.0, 0.0, -20.0)
        monkeypatch.setattr(dc, "_read_source",
                            lambda src: (_Arr(), "V", cgt, "P", None, 1))

        def forbidden(*a, **k):
            raise AssertionError("upsampling must not use the decimate test")
        monkeypatch.setattr(dc, "_prepare_decimate_test", forbidden)
        monkeypatch.setattr(dc, "_holdout_stats",
                            lambda arr, valid, cgt_, proj, nodata, alg,
                            holdout_factor=2: {
                                "rmse": 1.0, "mae": 1.0, "max_abs_err": 1.0,
                                "n_holdout": 10,
                                "holdout_factor": holdout_factor})
        # 5 m target from a 20 m source is a 0.25x ratio: upsampling.
        alg, label, stats = dc.pick_best_resampling(
            "dem.tif", angular=False, dst_gsd_m=5.0)
        assert all("holdout_factor" in st for st in stats.values())

    def test_a_failed_decimate_setup_falls_back_instead_of_crashing(
            self, monkeypatch):
        class _Arr:
            shape = (400, 400)
        cgt = (500000.0, 5.0, 0.0, 5600000.0, 0.0, -5.0)
        monkeypatch.setattr(dc, "_read_source",
                            lambda src: (_Arr(), "V", cgt, "P", None, 1))

        def boom(*a, **k):
            raise RuntimeError("source too small for this ratio")
        monkeypatch.setattr(dc, "_prepare_decimate_test", boom)
        monkeypatch.setattr(dc, "_holdout_stats",
                            lambda arr, valid, cgt_, proj, nodata, alg,
                            holdout_factor=2: {
                                "rmse": 1.0, "mae": 1.0, "max_abs_err": 1.0,
                                "n_holdout": 10,
                                "holdout_factor": holdout_factor})
        logged = []
        alg, label, stats = dc.pick_best_resampling(
            "dem.tif", angular=False, dst_gsd_m=40.0, log_fn=logged.append)
        assert alg in dict(dc.AUTO_OPTIMIZE_CANDIDATES)
        assert any("falling back" in m for m in logged)
        # ...and the high-ratio warning must reappear, because on the
        # fallback path the ranking really is unreliable again.
        assert any("WARNING" in m for m in logged)

    def test_no_high_ratio_warning_on_the_normal_decimate_path(self,
                                                               monkeypatch):
        seen = {"rmse": {a: 1.0 + i for i, (a, _l)
                         in enumerate(dc.AUTO_OPTIMIZE_CANDIDATES)}}
        self._patch(monkeypatch, seen)
        logged = []
        dc.pick_best_resampling("dem.tif", angular=False, dst_gsd_m=200.0,
                                log_fn=logged.append)
        assert not any("WARNING" in m for m in logged)


# ---------------------------------------------------------------------------
# 4. Lanczos joined the candidate list
# ---------------------------------------------------------------------------

def test_lanczos_is_a_scored_candidate_and_is_clamped():
    algs = dict(dc.AUTO_OPTIMIZE_CANDIDATES)
    assert "lanczos" in algs
    assert len(algs) == 6
    # It can overshoot, so it must receive the same source-range clamp the
    # cubic family gets, both at delivery and while being scored.
    assert "lanczos" in dl.OVERSHOOT_PRONE_RESAMPLERS


# ---------------------------------------------------------------------------
# 5. The whole thing, against real GDAL and known ground truth
# ---------------------------------------------------------------------------

def _mountain(path, n=384, gsd=1.0):
    """Steep analytic terrain whose true height is known at every point."""
    rows, cols = np.mgrid[0:n, 0:n].astype("float64")
    z = (420.0 * np.sin(cols / 47.0) * np.cos(rows / 39.0)
         + 150.0 * np.sin(cols / 13.0 + rows / 11.0)
         + 55.0 * np.cos(cols / 5.3) * np.sin(rows / 6.1))
    make_raster(path, 32633, (500000.0, gsd, 0.0, 5600000.0, 0.0, -gsd),
                n, n, relief=0.0, array=z)
    return z


def _true_surface(u, v):
    return (420.0 * np.sin(u / 47.0) * np.cos(v / 39.0)
            + 150.0 * np.sin(u / 13.0 + v / 11.0)
            + 55.0 * np.cos(u / 5.3) * np.sin(v / 6.1))


@requires_gdal
class TestAgainstGroundTruth:

    def test_the_decimate_test_ranks_near_first_on_steep_terrain_at_16x(
            self, scratch_dir):
        """This is the headline regression. On v0.58.1 the same source ranks
        Cubic B-Spline first and Nearest Neighbor last."""
        src = os.path.join(scratch_dir, "steep.tif")
        _mountain(src, n=384, gsd=1.0)
        arr, valid, cgt, proj, nodata, _dec = dc._read_source(src)
        prep = dc._prepare_decimate_test(arr, valid, cgt, proj, nodata, 16.0)
        try:
            scored = {alg: dc._decimate_stats(prep, alg)["rmse"]
                      for alg, _label in dc.AUTO_OPTIMIZE_CANDIDATES}
        finally:
            dc._cleanup_decimate_test(prep)
        ranked = sorted(scored, key=scored.get)
        assert ranked[0] == "near", scored
        assert scored["cubicspline"] > scored["near"], scored

    def test_optimize_end_to_end_picks_near_on_steep_terrain_at_16x(
            self, scratch_dir):
        src = os.path.join(scratch_dir, "steep2.tif")
        _mountain(src, n=384, gsd=1.0)
        alg, label, stats = dc.pick_best_resampling(
            src, angular=False, dst_gsd_m=16.0)
        assert alg == "near", {a: s["rmse"] for a, s in stats.items()}
        assert all(s["method"] == "decimate" for s in stats.values())
        assert all(s["ratio"] == 16.0 for s in stats.values())

    def test_near_and_average_are_no_longer_degenerate(self, scratch_dir):
        """In the old hold-out test these two scored bit-identically at every
        ratio, because GDAL's 'average' point-samples when upsampling. Under
        the decimation test they measure genuinely different operations."""
        src = os.path.join(scratch_dir, "steep3.tif")
        _mountain(src, n=384, gsd=1.0)
        alg, label, stats = dc.pick_best_resampling(
            src, angular=False, dst_gsd_m=16.0)
        assert abs(stats["near"]["rmse"] - stats["average"]["rmse"]) > 1e-6

    def test_the_chosen_candidate_really_is_the_most_accurate(
            self, scratch_dir):
        """Scores the pick against the ANALYTIC surface, not against the
        tool's own metric -- the check that the measurement is not merely
        self-consistent."""
        from osgeo import gdal
        src = os.path.join(scratch_dir, "steep4.tif")
        _mountain(src, n=384, gsd=1.0)
        ratio = 16.0
        alg, _label, _stats = dc.pick_best_resampling(
            src, angular=False, dst_gsd_m=ratio)

        true_rmse = {}
        for cand, _label2 in dc.AUTO_OPTIMIZE_CANDIDATES:
            errs = []
            for fx, fy in dc.DECIMATE_PHASES:
                ox = 500000.0 + fx * ratio
                oy = 5600000.0 - fy * ratio
                n_cols = int((500000.0 + 384 - ox) // ratio)
                n_rows = int((oy - (5600000.0 - 384)) // ratio)
                ds = gdal.Warp("", src, format="MEM", resampleAlg=cand,
                               outputBounds=(ox, oy - n_rows * ratio,
                                             ox + n_cols * ratio, oy),
                               xRes=ratio, yRes=ratio,
                               outputType=gdal.GDT_Float32,
                               dstNodata=-32767.0)
                got = ds.GetRasterBand(1).ReadAsArray().astype("float64")
                ds = None
                cx = ox + (np.arange(n_cols) + 0.5) * ratio
                cy = oy - (np.arange(n_rows) + 0.5) * ratio
                uu, vv = np.meshgrid((cx - 500000.0) - 0.5,
                                     (5600000.0 - cy) - 0.5)
                errs.append(got - _true_surface(uu, vv))
            e = np.concatenate([x.ravel() for x in errs])
            true_rmse[cand] = float(np.sqrt(np.mean(e * e)))

        best_true = min(true_rmse, key=true_rmse.get)
        assert alg == best_true, (alg, best_true, true_rmse)

    def test_a_source_too_small_for_the_ratio_falls_back_cleanly(
            self, scratch_dir):
        src = os.path.join(scratch_dir, "tiny.tif")
        _mountain(src, n=40, gsd=1.0)
        arr, valid, cgt, proj, nodata, _dec = dc._read_source(src)
        with pytest.raises(RuntimeError):
            dc._prepare_decimate_test(arr, valid, cgt, proj, nodata, 30.0)
        # ...and pick_best_resampling must survive it, not propagate it.
        logged = []
        alg, _label, stats = dc.pick_best_resampling(
            src, angular=False, dst_gsd_m=30.0, log_fn=logged.append)
        assert alg in dict(dc.AUTO_OPTIMIZE_CANDIDATES)

    def test_scratch_rasters_are_always_removed(self, scratch_dir):
        src = os.path.join(scratch_dir, "steep5.tif")
        _mountain(src, n=200, gsd=1.0)
        arr, valid, cgt, proj, nodata, _dec = dc._read_source(src)
        prep = dc._prepare_decimate_test(arr, valid, cgt, proj, nodata, 8.0)
        tmp_dir = prep["tmp_dir"]
        assert os.path.isdir(tmp_dir)
        dc._cleanup_decimate_test(prep)
        assert not os.path.isdir(tmp_dir)

    def test_nodata_posts_never_enter_the_score(self, scratch_dir):
        src = os.path.join(scratch_dir, "voids.tif")
        n = 240
        rows, cols = np.mgrid[0:n, 0:n].astype("float64")
        z = 300.0 * np.sin(cols / 21.0) * np.cos(rows / 17.0)
        z[80:160, 80:160] = -32767.0
        make_raster(src, 32633, (500000.0, 1.0, 0.0, 5600000.0, 0.0, -1.0),
                    n, n, relief=0.0, array=z)
        arr, valid, cgt, proj, nodata, _dec = dc._read_source(src)
        prep = dc._prepare_decimate_test(arr, valid, cgt, proj, nodata, 8.0)
        try:
            st = dc._decimate_stats(prep, "bilinear")
        finally:
            dc._cleanup_decimate_test(prep)
        # The void is ~11% of the raster; a score that swallowed -32767 would
        # be astronomically large rather than merely terrain-sized.
        assert st["max_abs_err"] < 5000.0
        assert st["n_scored"] > 0
