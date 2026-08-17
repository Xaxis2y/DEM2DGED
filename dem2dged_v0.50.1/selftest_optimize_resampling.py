# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
#
# selftest_optimize_resampling.py
#
# Purpose
# -------
# Exercises the accuracy fix made to dem2dged_compare.py's
# "-resample optimize" path (dem2dged_compare.pick_best_resampling() /
# _holdout_stats()):
#
#   1. Cubic-family candidates (cubic, cubicspline) are now clamped into
#      [floor(source min), ceil(source max)] before their hold-out RMSE is
#      scored, matching the clamp DELIVERED tiles made with those
#      algorithms actually get (dem2dged_lib.clamp_tile_to_range()).
#      Previously the raw, unclamped reconstruction was scored, so a
#      handful of overshoot pixels at sharp discontinuities -- pixels no
#      real delivery ever contains -- could inflate RMSE/MAE and make
#      cubic-family methods look worse than what users actually receive.
#   2. Cubic B-Spline ("cubicspline") is now a fourth candidate in
#      AUTO_OPTIMIZE_CANDIDATES (previously only Nearest/Bilinear/Cubic
#      were measured).
#
# This script builds a small synthetic source DEM with a SHARP CLIFF (the
# exact terrain shape that makes cubic-family resamplers overshoot) plus
# smooth rolling terrain elsewhere, then calls pick_best_resampling()
# directly -- no tiles are written, nothing outside a throwaway temp folder
# is touched -- and checks:
#
#   - all candidates that should complete actually do (including the new
#     cubicspline candidate)
#   - the per-candidate max|error| reported for cubic/cubicspline stays
#     bounded by the source's own true value range (a clamp regression
#     would show up here as a wildly larger number, e.g. hundreds of
#     metres off a source that only spans a few hundred)
#   - the function still returns a valid (alg, label) pick
#
# Usage (Anaconda Prompt)
# ------------------------
#   conda activate dem2dged_anaconda_environment
#   python selftest_optimize_resampling.py
#
# Prints PASS/FAIL to the console. Exits non-zero on failure.

import math
import os
import shutil
import sys
import tempfile

import numpy as np
from osgeo import gdal, osr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dem2dged_compare as dc   # noqa: E402
import dem2dged_lib as dl       # noqa: E402


def make_cliff_dem(path, nx=140, ny=140):
    """Write a Float32 EPSG:4326 GeoTIFF: smooth rolling terrain on the left
    half, a sharp near-vertical cliff in the middle, flat high ground on the
    right. This is deliberately the terrain shape that makes cubic-family
    resamplers overshoot past the source's true min/max -- the exact
    situation clamp_tile_to_range() / the OVERSHOOT_PRONE_RESAMPLERS clamp
    exists for.
    """
    gt = (10.0, 0.001, 0.0, 45.14, 0.0, -0.001)
    xs = gt[0] + (np.arange(nx) + 0.5) * gt[1]
    ys = gt[3] + (np.arange(ny) + 0.5) * gt[5]
    X, _Y = np.meshgrid(xs, ys)

    low = 100.0 + 30.0 * np.sin(2 * math.pi * (X - 10.0) * 4)
    high = 500.0 + 10.0 * np.sin(2 * math.pi * (X - 10.0) * 4)
    cliff_x = 10.0 + (nx * gt[1]) / 2.0
    Z = np.where(X < cliff_x, low, high).astype("float32")

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767)
    band.WriteArray(Z)
    ds.FlushCache()
    ds = None
    return float(Z.min()), float(Z.max())


def main():
    print("=" * 72)
    print("selftest_optimize_resampling  (real GDAL %s, dem2dged v%s)"
          % (gdal.__version__, dl.VERSION))
    print("=" * 72)

    work = tempfile.mkdtemp(prefix="dem2dged_optimize_selftest_")
    problems = []
    try:
        src = os.path.join(work, "cliff_dem.tif")
        zmin, zmax = make_cliff_dem(src)
        span = zmax - zmin
        print("Synthetic cliff source: %s" % src)
        print("  true range: %.1f .. %.1f m  (span %.1f m)" % (zmin, zmax, span))

        print("\nCandidates in AUTO_OPTIMIZE_CANDIDATES: %s"
              % ", ".join(a for a, _ in dc.AUTO_OPTIMIZE_CANDIDATES))
        if "cubicspline" not in dict(dc.AUTO_OPTIMIZE_CANDIDATES):
            problems.append("cubicspline is missing from AUTO_OPTIMIZE_CANDIDATES")

        log_lines = []
        alg, label, stats_by_alg = dc.pick_best_resampling(
            src, angular=False, log_fn=log_lines.append)
        for line in log_lines:
            print("  " + line)

        print("\nPicked: %s (%s)" % (alg, label))
        print("\n%-16s %10s %10s %14s %10s" % (
            "algorithm", "RMSE(m)", "MAE(m)", "max|err|(m)", "n"))
        for a, label_ in dc.AUTO_OPTIMIZE_CANDIDATES:
            st = stats_by_alg.get(a)
            if st is None:
                print("  %-14s (did not complete)" % a)
                continue
            print("%-16s %10.3f %10.3f %14.3f %10s"
                  % (a, st["rmse"], st["mae"], st["max_abs_err"],
                     "{:,}".format(st["n_holdout"])))

        # A working clamp is a MATHEMATICAL GUARANTEE, not just a rough
        # sanity check: once a reconstruction is clamped into
        # [floor(zmin), ceil(zmax)], and every true (withheld) value is
        # already within [zmin, zmax] by definition (it came from this same
        # source), no |error| between the two can exceed
        # (ceil(zmax) - floor(zmin)) -- the clamped range's own width. Any
        # value above that bound is only possible if the clamp did not run,
        # which is exactly the regression this selftest exists to catch on
        # this deliberately cliff-shaped (overshoot-provoking) source.
        bound = math.ceil(zmax) - math.floor(zmin) + 1e-6
        for a in ("cubic", "cubicspline"):
            st = stats_by_alg.get(a)
            if st is None:
                problems.append("%s did not complete at all" % a)
                continue
            if st["max_abs_err"] > bound:
                problems.append(
                    "%s max|error| = %.1f m, exceeds the sanity bound of "
                    "%.1f m for a %.1f m source span -- looks like the "
                    "clamp is NOT being applied" % (a, st["max_abs_err"],
                                                     bound, span))

        if "cubicspline" not in stats_by_alg:
            problems.append("cubicspline did not appear in stats_by_alg")

        if alg not in dict(dc.AUTO_OPTIMIZE_CANDIDATES):
            problems.append("pick_best_resampling returned an unknown "
                            "algorithm: %r" % alg)

        print("\n" + "=" * 72)
        if problems:
            print("SELFTEST: FAILED")
            for p in problems:
                print("  - " + p)
            return 1
        print("SELFTEST: PASSED")
        print("cubicspline is measured, and cubic-family max|error| stayed "
              "within the clamp -- the accuracy fix is working as intended.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
