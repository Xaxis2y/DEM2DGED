# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.57.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Regression tests for the v0.57.0 mountain-terrain-accuracy patch.

Three independent fixes, each driven by a controlled measurement against
known ground truth (synthetic terrain with realistic mountain slope
statistics, exact elevation known at every DGED post -- see
dem2dged_v0.56.0_mountain_terrain_review.md for the full experiment):

  1. "-resample optimize" (dem2dged_compare.pick_best_resampling()) used to
     always hold out at a fixed 2x decimation regardless of the actual
     requested ratio, which reliably favoured Cubic even where Nearest
     Neighbor reconstructed steep terrain up to 3x more accurately at the
     8x-16x ratios such terrain is often actually delivered at. It now
     holds out at (approximately) the real ratio via pick_holdout_factor(),
     and "average" was added as a fifth candidate.
  2. The v0.49 Gaussian anti-alias pre-filter was documented as an accuracy
     improvement for high-relief downsampling; measured to increase net
     point-accuracy error at every ratio/resampler tested instead. The
     feature and its sigma formula are UNCHANGED (this file does not
     re-test gaussian_sigma_for_ratio()/build_prefiltered_source(), which
     tests/test_v056_regressions.py and selftest_prefilter*.py already
     cover) -- only the CLI/GUI/library messaging changed, so the checks
     here are limited to the messaging.
  3. -resample rms is mathematically unsound for signed elevation data
     (discards sign; MEASURED wrong by 150 m and the wrong sign on a tiny
     footprint) and has been removed, with a specific explanation instead
     of the generic "unknown resampling method" error.
"""

import os

import numpy as np
import pytest

import dem2dged_lib as dl
from conftest import requires_gdal, make_raster

dc = pytest.importorskip("dem2dged_compare")


# =============================================================================
# Fix 3: -resample rms removed
# =============================================================================

def test_rms_is_no_longer_a_valid_resampler():
    assert "rms" not in dl.VALID_RESAMPLERS
    assert "rms" not in dl.GDALWARP_RESAMPLERS


def test_rms_gets_a_specific_explanation_not_the_generic_unknown_value_error():
    with pytest.raises(SystemExit) as exc:
        dl.validate_resampler("rms")
    msg = str(exc.value)
    assert "not offered" in msg
    # the reason (sign is discarded), not just "unknown value, pick one of..."
    assert "sign" in msg.lower()
    assert "average" in msg.lower()  # the suggested replacement


def test_rms_is_case_and_whitespace_insensitive_like_every_other_value():
    with pytest.raises(SystemExit) as exc:
        dl.validate_resampler("  RMS  ")
    assert "not offered" in str(exc.value)


def test_unrelated_unknown_values_still_get_the_generic_error():
    """REMOVED_RESAMPLERS must not swallow ordinary typos."""
    with pytest.raises(SystemExit) as exc:
        dl.validate_resampler("bilnear")
    msg = str(exc.value)
    assert "unknown resampling method" in msg
    assert "not offered" not in msg


def test_rms_quadratic_mean_defect_is_real_not_hypothetical():
    """Standalone numeric confirmation of WHY rms was removed, independent
    of dem2dged: a footprint with true mean -50.0 has quadratic mean
    +100.0 -- the wrong magnitude AND the wrong sign. This is what
    motivated the removal in test_rms_is_no_longer_a_valid_resampler()."""
    footprint = np.array([-100., -100., -100., -100.,
                          -100., 100., 100., -100.,
                          -100., 100., 100., -100.,
                          -100., -100., -100., -100.])
    true_mean = float(footprint.mean())
    quadratic_mean = float(np.sqrt((footprint ** 2).mean()))
    assert true_mean == pytest.approx(-50.0)
    assert quadratic_mean == pytest.approx(100.0)
    assert quadratic_mean >= abs(true_mean)  # the general property, not a fluke
    assert (quadratic_mean > 0) != (true_mean > 0)  # wrong sign in this case


# =============================================================================
# Fix 2: pre-filter messaging no longer claims an accuracy improvement
# =============================================================================

def test_prefilter_still_works_exactly_as_before_only_messaging_changed():
    assert dl.validate_prefilter("none") == "none"
    assert dl.validate_prefilter("gaussian") == "gaussian"
    assert dl.validate_prefilter(None) == "none"
    # sigma formula itself is untouched by this patch
    assert dl.gaussian_sigma_for_ratio(5.0, 5.0, "auto") == 0.0
    assert dl.gaussian_sigma_for_ratio(5.0, 20.0, "auto") == pytest.approx(1.5)


def test_prefilter_unknown_value_error_no_longer_claims_it_suppresses_error():
    with pytest.raises(SystemExit) as exc:
        dl.validate_prefilter("median")
    msg = str(exc.value)
    # the old wording ("to suppress aliasing ... high-relief terrain") read
    # as an unqualified accuracy claim; the new wording must not repeat it
    # without the accuracy caveat this patch adds.
    assert "MEASURED" in msg or "measured" in msg.lower()


def test_gui_prefilter_dropdown_no_longer_bare_claims_accuracy_benefit():
    import dem2dged_gui as gui
    labels = dict(gui.PREFILTER_OPTIONS)
    gaussian_label = labels["gaussian"]
    assert "high-relief downsampling" not in gaussian_label, (
        "GUI dropdown still frames the pre-filter as a high-relief accuracy "
        "win; the v0.57 measurement found the opposite")


# =============================================================================
# Fix 1: "-resample optimize" holds out at the actual requested ratio
# =============================================================================

class TestPickHoldoutFactor:
    """Pure-logic tests for dem2dged_compare.pick_holdout_factor() -- no
    GDAL/raster I/O, so these run even where gdalwarp is unavailable."""

    def test_no_ratio_keeps_the_original_fixed_2x_behaviour(self):
        assert dc.pick_holdout_factor(None, (1000, 1000)) == 2
        assert dc.pick_holdout_factor(0, (1000, 1000)) == 2
        assert dc.pick_holdout_factor(-3, (1000, 1000)) == 2
        assert dc.pick_holdout_factor(1.0, (1000, 1000)) == 2  # no decimation

    def test_ratio_is_rounded_and_used_directly_on_a_large_grid(self):
        assert dc.pick_holdout_factor(8.0, (1000, 1000)) == 8
        assert dc.pick_holdout_factor(7.6, (1000, 1000)) == 8  # rounds
        assert dc.pick_holdout_factor(4.4, (1000, 1000)) == 4

    def test_ratio_is_capped_so_a_huge_ratio_does_not_starve_the_test(self):
        assert dc.pick_holdout_factor(500.0, (5000, 5000)) == dc.MAX_HOLDOUT_FACTOR

    def test_factor_is_pulled_back_down_on_a_small_grid(self):
        # 40 // 8 == 5 < MIN_HOLDOUT_TRAINING_SIDE(8), so it must back off;
        # 40 // 5 == 8, which is exactly the minimum -- stops there.
        factor = dc.pick_holdout_factor(8.0, (40, 40))
        assert factor == 5
        assert min(40, 40) // factor >= dc.MIN_HOLDOUT_TRAINING_SIDE

    def test_never_backs_off_below_two(self):
        factor = dc.pick_holdout_factor(8.0, (10, 10))
        assert factor == 2


def test_average_is_now_a_scored_optimize_candidate():
    codes = [alg for alg, _label in dc.AUTO_OPTIMIZE_CANDIDATES]
    assert "average" in codes
    # every candidate must be an alg dem2dged_lib actually accepts, so a
    # future rename of one can't silently desync the two modules
    for alg in codes:
        assert dl.validate_resampler(alg) == alg


@requires_gdal
class TestHoldoutStatsCustomFactor:
    """_holdout_stats() with an explicit holdout_factor, using the same
    make_raster() fixture helper the rest of the suite uses."""

    def _source(self, scratch_dir, n=120):
        path = os.path.join(scratch_dir, "source.tif")
        # 5 m posts, real relief (see make_raster docstring) so the
        # hold-out reconstruction is a genuine (non-degenerate) test.
        make_raster(path, 32633, (500000.0, 5.0, 0.0, 5600000.0, 0.0, -5.0),
                   n, n, relief=40.0)
        return path

    def test_factor_of_one_is_rejected(self, scratch_dir):
        src = self._source(scratch_dir)
        arr, valid, cgt, proj, nodata, _dec = dc._read_source(src)
        with pytest.raises(ValueError):
            dc._holdout_stats(arr, valid, cgt, proj, nodata, "bilinear",
                              holdout_factor=1)

    def test_larger_factor_withholds_more_posts_and_reports_itself(self,
                                                                    scratch_dir):
        src = self._source(scratch_dir)
        arr, valid, cgt, proj, nodata, _dec = dc._read_source(src)
        st2 = dc._holdout_stats(arr, valid, cgt, proj, nodata, "bilinear",
                                holdout_factor=2)
        st8 = dc._holdout_stats(arr, valid, cgt, proj, nodata, "bilinear",
                                holdout_factor=8)
        assert st2["holdout_factor"] == 2
        assert st8["holdout_factor"] == 8
        # a coarser training lattice withholds a LARGER fraction of posts
        assert st8["n_holdout"] > st2["n_holdout"]


@requires_gdal
class TestPickBestResamplingUsesTheRequestedRatio:

    def _source(self, scratch_dir, n=200):
        path = os.path.join(scratch_dir, "source.tif")
        make_raster(path, 32633, (500000.0, 5.0, 0.0, 5600000.0, 0.0, -5.0),
                   n, n, relief=40.0)
        return path

    def test_no_dst_gsd_m_keeps_the_pre_v057_fixed_2x_test(self, scratch_dir):
        """Backward compatibility: an existing caller that doesn't pass
        dst_gsd_m (there is none left in this project after this patch, but
        a third-party script might still call the function directly) must
        see the original behaviour, not an error."""
        src = self._source(scratch_dir)
        alg, label, stats_by_alg = dc.pick_best_resampling(src)
        assert alg in dict(dc.AUTO_OPTIMIZE_CANDIDATES)
        assert stats_by_alg  # at least one candidate succeeded
        for st in stats_by_alg.values():
            assert st["holdout_factor"] == 2

    def test_dst_gsd_m_is_threaded_through_to_the_holdout_ratio(self,
                                                                 scratch_dir):
        src = self._source(scratch_dir)
        # source is 5 m posts -> requesting 40 m posts is an 8x decimation
        alg, label, stats_by_alg = dc.pick_best_resampling(
            src, dst_gsd_m=40.0)
        assert alg in dict(dc.AUTO_OPTIMIZE_CANDIDATES)
        assert stats_by_alg
        for st in stats_by_alg.values():
            assert st["holdout_factor"] == 8

    def test_angular_short_circuit_is_unaffected_by_dst_gsd_m(self, scratch_dir):
        src = self._source(scratch_dir)
        alg, label, stats_by_alg = dc.pick_best_resampling(
            src, angular=True, dst_gsd_m=40.0)
        assert alg == "near"
        assert stats_by_alg == {}


@requires_gdal
def test_resolve_resampler_passes_dst_gsd_m_to_pick_best_resampling(
        scratch_dir, monkeypatch):
    """dl.resolve_resampler() is the CLI/GUI entry point for "-resample
    optimize"; this is the one place a regression could silently drop the
    ratio and revert every conversion to the old fixed-2x behaviour without
    any test noticing, so it's checked directly rather than only through
    pick_best_resampling() itself."""
    src = os.path.join(scratch_dir, "source.tif")
    make_raster(src, 32633, (500000.0, 5.0, 0.0, 5600000.0, 0.0, -5.0),
               80, 80, relief=20.0)

    captured = {}

    def fake_pick_best_resampling(input_path, angular=False, log_fn=None,
                                  dst_gsd_m=None):
        captured["dst_gsd_m"] = dst_gsd_m
        captured["input_path"] = input_path
        return "cubic", "Cubic Convolution", {}

    monkeypatch.setattr(dc, "pick_best_resampling", fake_pick_best_resampling)

    alg = dl.resolve_resampler(src, src_gsd_m=5.0, dst_gsd_m=40.0,
                               override="optimize")
    assert alg == "cubic"
    assert captured["dst_gsd_m"] == 40.0
    assert captured["input_path"] == src


@requires_gdal
def test_compute_method_stats_auto_detects_the_delivered_ratio(scratch_dir):
    """The manual Resampling Comparison Test (compute_method_stats(), used
    by the GUI's side-by-side comparison and selftest_resampling_
    comparison.py) has no explicit target-ratio parameter -- it infers the
    ratio from the pixel size of the tiles it is handed vs. the source."""
    src = os.path.join(scratch_dir, "source.tif")
    make_raster(src, 32633, (500000.0, 5.0, 0.0, 5600000.0, 0.0, -5.0),
               240, 240, relief=40.0)

    # a "delivered" 4x-coarser tile, well inside the source extent
    method_dir = os.path.join(scratch_dir, "method_1")
    os.makedirs(method_dir, exist_ok=True)
    tile = os.path.join(method_dir, "tile.tif")
    make_raster(tile, 32633, (500100.0, 20.0, 0.0, 5599900.0, 0.0, -20.0),
               40, 40, relief=40.0)

    stats = dc.compute_method_stats(src, method_dir, alg="bilinear")
    assert stats["holdout_factor"] == 4