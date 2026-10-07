# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.61.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

import os
import math
import shutil
import tempfile
import datetime

import numpy as np
from osgeo import gdal, osr

try:
    from dem2dged_lib import (VERSION, gdal_open, OVERSHOOT_PRONE_RESAMPLERS,
                              meters_per_degree_latitude,
                              source_gsd_meters)
except Exception:
    # fallback; keep in sync with dem2dged_lib.VERSION.
    # v0.58.1: this fallback had been stuck at "0.45" since v0.45 --
    # every bump script listed dem2dged_lib.py but not this file, so a
    # run where the dem2dged_lib import failed would stamp a v0.45
    # banner on a comparison report produced by the current build.
    # BUMP_VERSION.py now covers this file.
    VERSION = "0.61.0"

    # fallback; keep in sync with dem2dged_lib.OVERSHOOT_PRONE_RESAMPLERS
    OVERSHOOT_PRONE_RESAMPLERS = frozenset({"cubic", "cubicspline", "lanczos"})

    def meters_per_degree_latitude(latitude_deg):
        """Fallback latitude conversion used if the shared library is absent."""
        latitude = max(-90.0, min(90.0, float(latitude_deg)))
        phi = math.radians(latitude)
        return (111132.92 - 559.82 * math.cos(2.0 * phi)
                + 1.175 * math.cos(4.0 * phi)
                - 0.0023 * math.cos(6.0 * phi))

    def source_gsd_meters(path):
        """Fallback source GSD helper used only when the library import fails."""
        ds = gdal.Open(path, gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError("GDAL cannot open source: %s" % path)
        gt = ds.GetGeoTransform()
        return abs(float(gt[5]))

    def gdal_open(path, mode=gdal.GA_ReadOnly):
        """Fallback shim (v0.41) mirroring dem2dged_lib.gdal_open().

        Only reached if dem2dged_lib could not be imported at all -- in
        which case gdal.UseExceptions() has not been called either, so
        gdal.Open already returns None. The try/except keeps the contract
        identical if that ever changes (GDAL 4.0 enables exceptions by
        default).
        """
        try:
            return gdal.Open(path, mode)
        except RuntimeError:
            return None

# (test_number, gdalwarp_alg, display_label, test_folder_name)
# The folder names are the "test folder 1 / 2 / 3" layout requested for
# side-by-side comparison runs.
COMPARISON_METHODS = [
    ("1", "near",     "Nearest Neighbor",       "test_1_nearest_neighbor"),
    ("2", "bilinear", "Bilinear Interpolation", "test_2_bilinear_interpolation"),
    ("3", "cubic",    "Cubic Convolution",      "test_3_cubic_convolution"),
]

# Safety cap: analysis runs on the source grid; sources larger than this
# many posts are compared on an evenly decimated sub-grid (identical for
# every method, so the ranking is unaffected).
MAX_COMPARE_PIXELS = 64_000_000

REPORT_FILENAME = "DGED_Resampling_Comparison_Report.html"


def _list_tiles(folder):
    """Return the sorted .tif tile paths inside a method test folder."""
    if not os.path.isdir(folder):
        raise RuntimeError("Comparison folder does not exist: %s" % folder)
    tifs = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
            if f.lower().endswith(".tif")]
    if not tifs:
        raise RuntimeError("No .tif tiles found in: %s" % folder)
    return tifs


def _read_source(src_path):
    """Open the source and read a (possibly decimated) analysis grid.

    Returns (array float64, valid_mask, geotransform of the analysis grid,
    projection wkt, nodata, decimation factor).
    """
    src_ds = gdal_open(src_path)
    if src_ds is None:
        raise RuntimeError("GDAL cannot open source: %s" % src_path)
    band   = src_ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    gt     = src_ds.GetGeoTransform()
    xsize, ysize = src_ds.RasterXSize, src_ds.RasterYSize

    dec = 1
    while (xsize // dec) * (ysize // dec) > MAX_COMPARE_PIXELS:
        dec += 1
    cx, cy = xsize // dec, ysize // dec
    arr = band.ReadAsArray(0, 0, xsize, ysize, buf_xsize=cx, buf_ysize=cy)
    if arr is None:
        raise RuntimeError("Could not read source raster: %s" % src_path)
    arr = arr.astype("float64")
    valid = np.isfinite(arr)
    if nodata is not None:
        valid &= np.abs(arr - nodata) > 0.5
    cgt = (gt[0], gt[1] * dec, gt[2], gt[3], gt[4], gt[5] * dec)
    proj = src_ds.GetProjection()
    src_ds = None
    return arr, valid, cgt, proj, nodata, dec


def _native_source_windows(src_path, ratio):
    """Read bounded windows directly from the native source grid.

    The previous implementation reduced oversized rasters before selecting
    windows. That changed the source spacing and therefore changed the ratio
    being measured. This helper keeps the source pixel spacing intact and only
    limits the number of native pixels examined.
    """
    src_ds = gdal_open(src_path)
    if src_ds is None:
        raise RuntimeError("GDAL cannot open source: %s" % src_path)
    band = src_ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    gt = src_ds.GetGeoTransform()
    proj = src_ds.GetProjection()
    shape = (int(src_ds.RasterYSize), int(src_ds.RasterXSize))
    windows = []
    for row0, col0, height, width in _decimate_windows(shape, float(ratio)):
        arr = band.ReadAsArray(col0, row0, width, height)
        if arr is None:
            continue
        arr = arr.astype("float64")
        valid = np.isfinite(arr)
        if nodata is not None:
            if np.isfinite(float(nodata)):
                valid &= np.abs(arr - float(nodata)) > 0.5
        wgt = (gt[0] + col0 * gt[1], gt[1], gt[2],
               gt[3] + row0 * gt[5], gt[4], gt[5])
        windows.append((arr, valid, wgt))
    src_ds = None
    if not windows:
        raise RuntimeError("source has no readable native analysis windows")
    return windows, proj, nodata


def _exact_source_range(src_path, arr, valid):
    """Return the exact source range used by production tile clamping."""
    if src_path:
        ds = gdal_open(src_path)
        if ds is not None:
            band = ds.GetRasterBand(1)
            try:
                lo, hi = band.ComputeRasterMinMax(False)
                if np.isfinite(lo) and np.isfinite(hi):
                    ds = None
                    return float(lo), float(hi)
            finally:
                ds = None
    if not valid.any():
        raise RuntimeError("source has no valid posts to determine its range")
    return float(arr[valid].min()), float(arr[valid].max())


def _gsd_meters_from_geotransform(gt, projection):
    """Return the north-south post spacing in metres for a GDAL grid."""
    spacing = abs(float(gt[5]))
    if not projection:
        return spacing
    try:
        srs = osr.SpatialReference(wkt=projection)
        if srs.IsGeographic():
            return spacing * meters_per_degree_latitude(gt[3])
    except Exception:
        pass
    return spacing


# v0.57: the hold-out test used to always decimate by a fixed factor of 2,
# regardless of what ratio the conversion actually requested. Which
# resampling algorithm reconstructs terrain most accurately is
# RATIO-DEPENDENT -- a controlled measurement against known ground truth
# (synthetic terrain with realistic mountain slope statistics, exact
# elevation known at every post) found that a fixed 2x test reliably favours
# Cubic, but at the 8x-16x ratios steep terrain is often actually delivered
# at, Nearest Neighbor reconstructed up to 3x more accurately -- see
# dem2dged_v0.56.0_mountain_terrain_review.md. pick_holdout_factor() below
# lets callers that know the real ratio (pick_best_resampling(),
# compute_method_stats()) test at something close to it instead.
# v0.58.1: decimation ratio at or above which pick_best_resampling() emits an
# advisory about the hold-out test's known limitation. Advisory only -- it does
# not gate or alter the selection. 8x is where the reconstruction-vs-decimation
# divergence became clearly visible in the ground-truth measurements recorded in
# dem2dged_v0.57.1_mountain_terrain_recheck.md.
HIGH_RATIO_ADVISORY = 8.0

MIN_HOLDOUT_TRAINING_SIDE = 8   # smallest usable training-grid side, in posts
MAX_HOLDOUT_FACTOR = 20         # cap: keep the test fast and keep enough
                                 # withheld posts to measure anything at all


def pick_holdout_factor(ratio, shape):
    """Choose the _holdout_stats() decimation factor for one comparison.

    ``ratio``: the ACTUAL src/dst GSD ratio the conversion is decimating by
    (target post spacing / source pixel spacing), or None/<=1 to keep the
    pre-v0.57 fixed 2x test (the safe fallback for a caller that doesn't
    know the real ratio, or for upsampling, where there is no "decimation
    ratio" to test at all).

    ``shape``: the analysis grid's (ny, nx). A small source, or a very
    large ratio, would otherwise leave too few training or withheld posts
    to measure anything meaningful (or fail outright); the factor is pulled
    back down until the training grid's shorter side has at least
    MIN_HOLDOUT_TRAINING_SIDE posts, without going below 2.

    Returns an integer >= 2.
    """
    if not ratio or ratio <= 1:
        factor = 2
    else:
        factor = max(2, min(MAX_HOLDOUT_FACTOR, int(round(ratio))))
    ny, nx = shape
    while factor > 2 and min(ny, nx) // factor < MIN_HOLDOUT_TRAINING_SIDE:
        factor -= 1
    return factor


# ---------------------------------------------------------------------------
#  v0.59.0 -- DECIMATE-AND-SCORE: measuring the operation we actually perform
# ---------------------------------------------------------------------------
#
# THE DEFECT THIS REPLACES
# ------------------------
# _holdout_stats() below builds its training grid by POINT-SAMPLING the
# source (arr[::hf, ::hf]) and then scores how accurately each candidate
# RECONSTRUCTS the full grid from it. That is an UPSAMPLING measurement being
# used as a proxy for DOWNSAMPLING accuracy, and the two diverge sharply once
# the decimation ratio gets large:
#
#   * A resampler that interpolates smoothly between sparse posts wins the
#     reconstruction test. A resampler that preserves the true value AT a post
#     wins the real decimation. Those are different jobs.
#   * GDAL's "average" degenerates to point sampling when it UPSAMPLES, so
#     "near" and "average" score bit-identically in the hold-out test -- two
#     of the five candidates were never actually distinguished.
#
# Measured on ES's own DGED environment (GDAL 3.13.3), steep synthetic terrain
# at 16x: the hold-out test ranked Cubic B-Spline first (true RMSE 56.5 m) and
# Nearest Neighbor last (true RMSE 0.0 m) -- an exactly inverted ranking. See
# dem2dged_v0.57.1_mountain_terrain_recheck.md and
# DIAG_dem2dged_v0.58.1_log.txt.
#
# WHAT THIS DOES INSTEAD
# ----------------------
# For each candidate we run the REAL production operation -- gdal.Warp() from
# the source down to the target post spacing, with the same resampleAlg and
# the same source-range clamp a delivered cubic-family tile gets -- and score
# the result against the best available estimate of the true terrain height AT
# each target post.
#
# THE TRUTH REFERENCE, and why it is not circular
# -----------------------------------------------
# A DGED post carries the elevation AT a point, not an area average. The best
# available estimate of that from the source is a NARROW interpolation of the
# source at that exact location: a Catmull-Rom bicubic over the 4x4 source
# neighbourhood (_sample_bicubic()). This is deliberately NOT any candidate's
# own operation -- GDAL scales its resampling kernel with the downsampling
# factor, so a candidate warping 16x averages over a 16-pixel-wide footprint,
# while the truth reference always uses a 4-pixel one at native spacing.
#
# PHASE AVERAGING, and why it matters
# ------------------------------------
# If the target post happened to land exactly on a source post, Nearest
# Neighbor would be trivially exact and would always win. In a real delivery
# the DGED grid is snapped to its own global lattice, so posts land at every
# sub-pixel phase relative to the source. Each candidate is therefore scored
# over DECIMATE_PHASES sub-pixel offsets of the target grid and the errors are
# pooled. That charges Nearest Neighbor its real expected offset error and
# charges the smoothing methods their real curvature bias, instead of letting
# a knife-edge grid alignment decide the ranking.
#
# GROUND-TRUTH VALIDATION (verify_mountain_terrain_v0.59.0.py)
# ------------------------------------------------------------
# 32 controlled cases -- alpine / ridged / rolling terrain, integer and
# non-integer ratios from 2x to 16x, clean and noisy sources, two seeds --
# with every candidate scored against the ANALYTIC surface the source was
# generated from, so the right answer is known rather than estimated:
#
#   correct candidate chosen : hold-out  6/32       decimate-and-score 28/32
#   excess RMSE over oracle  : hold-out +573.62 m   decimate-and-score +0.53 m
#
# Excess over oracle -- the avoidable error each ranking method's choices
# added up to -- is the metric that matters, because a wrong pick between
# near-tied candidates costs almost nothing. 99.9% of it is removed.
#
# The four remaining mis-picks are all low-ratio (<=4x) NOISY cases where the
# candidates sit within a quarter of a metre of each other. Every case where
# the choice was worth metres is now decided correctly. The residual cause is
# known and documented: the truth reference is interpolated from the source,
# so it carries the source's own noise, which slightly under-penalises a
# candidate that does not smooth. At high ratios the curvature bias dwarfs
# that term; at low ratios it does not.
#
# COST
# ----
# Roughly 3-5x the hold-out test's warp count, bounded by MAX_DECIMATE_PIXELS
# (large sources are sampled with up to MAX_DECIMATE_WINDOWS native-spacing
# windows rather than decimated, because decimating the source would change
# the very ratio being tested).

# Sub-pixel offsets of the target grid, in fractions of one TARGET post, at
# which every candidate is scored. Chosen to cover the corners, the edge
# midpoints and two off-lattice points of the unit cell.
DECIMATE_PHASES = ((0.0, 0.0), (0.5, 0.0), (0.0, 0.5),
                   (0.5, 0.5), (0.25, 0.75), (0.75, 0.25))

# Analysis budget for the decimate test. A source larger than this is sampled
# with windows at NATIVE spacing (see _decimate_windows) -- never decimated,
# which would silently shrink the ratio under test.
MAX_DECIMATE_PIXELS = 16_000_000
MAX_DECIMATE_WINDOWS = 4

# A phase is only scored if its target grid is at least this many posts on
# each side; below that the RMSE is too noisy to rank anything.
MIN_DECIMATE_POSTS = 8

# Below this ratio the conversion is not decimation at all (equal spacing or
# upsampling), where the hold-out reconstruction test is the CORRECT measure
# and this one is meaningless. pick_best_resampling() switches on this.
MIN_DECIMATE_RATIO = 1.0


def _catmull_rom_weights(frac):
    """Catmull-Rom cubic weights for the four taps around ``frac`` in [0, 1)."""
    f2 = frac * frac
    f3 = f2 * frac
    return (-0.5 * f3 + f2 - 0.5 * frac,
            1.5 * f3 - 2.5 * f2 + 1.0,
            -1.5 * f3 + 2.0 * f2 + 0.5 * frac,
            0.5 * f3 - 0.5 * f2)


def _sample_bicubic(arr, valid, u, v):
    """Catmull-Rom bicubic sample of ``arr`` at fractional indices (u, v).

    ``u`` is the fractional COLUMN index and ``v`` the fractional ROW index,
    both measured in source pixels from the array's own (0, 0) pixel centre.
    Returns (values, ok) where ``ok`` is False wherever any of the 16 taps
    fell outside the array or on a NoData post -- an interpolated value that
    borrowed from a void is not evidence about anything.
    """
    ny, nx = arr.shape
    u0 = np.floor(u).astype(np.int64)
    v0 = np.floor(v).astype(np.int64)
    wu = _catmull_rom_weights(u - u0)
    wv = _catmull_rom_weights(v - v0)

    out = np.zeros(u.shape, dtype="float64")
    ok = np.ones(u.shape, dtype=bool)
    for j in range(4):
        rows_raw = v0 - 1 + j
        rows = np.clip(rows_raw, 0, ny - 1)
        in_row = (rows_raw >= 0) & (rows_raw < ny)
        acc = np.zeros(u.shape, dtype="float64")
        for i in range(4):
            cols_raw = u0 - 1 + i
            cols = np.clip(cols_raw, 0, nx - 1)
            in_col = (cols_raw >= 0) & (cols_raw < nx)
            acc += wu[i] * arr[rows, cols]
            ok &= valid[rows, cols] & in_row & in_col
        out += wv[j] * acc
    return out, ok


def _decimate_windows(shape, ratio):
    """Return [(row0, col0, height, width)] analysis windows at NATIVE spacing.

    A source within MAX_DECIMATE_PIXELS is used whole. A larger one is sampled
    with up to MAX_DECIMATE_WINDOWS windows placed at the quarter positions,
    which keeps the cost bounded while still sampling terrain from four parts
    of the raster instead of one. The windows are NOT decimated: decimating
    would change the source post spacing and therefore the decimation ratio
    under test, which is the exact defect v0.57.0 fixed.
    """
    ny, nx = shape
    if ny * nx <= MAX_DECIMATE_PIXELS:
        return [(0, 0, ny, nx)]

    side = int(math.sqrt(MAX_DECIMATE_PIXELS / float(MAX_DECIMATE_WINDOWS)))
    # A window must hold enough target posts to be worth scoring.
    side = max(side, int(math.ceil(MIN_DECIMATE_POSTS * max(1.0, ratio))) + 4)
    side = min(side, ny, nx)

    if 2 * side >= min(ny, nx):
        row0 = max(0, (ny - side) // 2)
        col0 = max(0, (nx - side) // 2)
        return [(row0, col0, min(side, ny), min(side, nx))]

    windows = []
    for frow in (0.25, 0.75):
        for fcol in (0.25, 0.75):
            row0 = int(frow * ny) - side // 2
            col0 = int(fcol * nx) - side // 2
            row0 = max(0, min(ny - side, row0))
            col0 = max(0, min(nx - side, col0))
            windows.append((row0, col0, side, side))
    return windows


def _prepare_decimate_test(arr, valid, cgt, proj, nodata, ratio,
                           source_path=None):
    """Build everything the candidates share: windows, and the truth per phase.

    The truth reference and the target grids do not depend on the resampling
    algorithm, so they are computed ONCE here and reused by every candidate.
    Returns an opaque dict for _decimate_stats(); the caller must pass it to
    _cleanup_decimate_test() when finished.
    """
    if not ratio or ratio < MIN_DECIMATE_RATIO:
        raise ValueError("decimate test needs a decimation ratio >= %g, got %r"
                         % (MIN_DECIMATE_RATIO, ratio))
    if not valid.any() and not source_path:
        raise RuntimeError("source has no valid posts to score against")

    nod = -32767.0 if nodata is None else float(nodata)
    spx, spy = abs(cgt[1]), abs(cgt[5])
    if spx <= 0 or spy <= 0:
        raise RuntimeError("source geotransform has a non-positive pixel size")
    dpx, dpy = spx * float(ratio), spy * float(ratio)

    # The same exact clamp a delivered cubic-family tile gets
    # (dem2dged_lib.clamp_tile_to_range()). Do not round the limits: production
    # uses the source's floating-point range, and rounding here can change the
    # candidate ranking near the source extrema.
    clamp_lo, clamp_hi = _exact_source_range(source_path, arr, valid)

    tmp_dir = tempfile.mkdtemp(prefix="dged_decimate_")
    drv = gdal.GetDriverByName("GTiff")
    windows = []
    try:
        if source_path:
            native_windows, native_proj, _native_nodata = \
                _native_source_windows(source_path, ratio)
            window_inputs = [
                (sub, sub_valid, wgt, native_proj)
                for sub, sub_valid, wgt in native_windows
            ]
        else:
            window_inputs = []
            for row0, col0, height, width in _decimate_windows(
                    arr.shape, float(ratio)):
                sub = arr[row0:row0 + height, col0:col0 + width]
                sub_valid = valid[row0:row0 + height, col0:col0 + width]
                wgt = (cgt[0] + col0 * cgt[1], cgt[1], cgt[2],
                       cgt[3] + row0 * cgt[5], cgt[4], cgt[5])
                window_inputs.append((sub, sub_valid, wgt, proj))

        for index, (sub, sub_valid, wgt, window_proj) in \
                enumerate(window_inputs):
            if sub_valid.sum() < 16:
                continue

            height, width = sub.shape
            path = os.path.join(tmp_dir, "decimate_src_%d.tif" % index)
            ds = drv.Create(path, width, height, 1, gdal.GDT_Float32)
            ds.SetGeoTransform(wgt)
            if window_proj:
                ds.SetProjection(window_proj)
            band = ds.GetRasterBand(1)
            band.SetNoDataValue(nod)
            payload = np.array(sub, dtype="float64", copy=True)
            payload[~sub_valid] = nod
            band.WriteArray(payload.astype("float32"))
            ds.FlushCache()
            ds = None

            x0, y0 = wgt[0], wgt[3]
            phases = []
            for fx, fy in DECIMATE_PHASES:
                ox = x0 + fx * dpx
                oy = y0 - fy * dpy
                n_cols = int((x0 + width * spx - ox) // dpx)
                n_rows = int((oy - (y0 - height * spy)) // dpy)
                if n_cols < MIN_DECIMATE_POSTS or n_rows < MIN_DECIMATE_POSTS:
                    continue
                # Post centres, then their fractional index into `sub`.
                cx = ox + (np.arange(n_cols) + 0.5) * dpx
                cy = oy - (np.arange(n_rows) + 0.5) * dpy
                uu, vv = np.meshgrid((cx - x0) / spx - 0.5,
                                     (y0 - cy) / spy - 0.5)
                truth, ok = _sample_bicubic(sub, sub_valid, uu, vv)
                if not ok.any():
                    continue
                phases.append({
                    "bounds": (ox, oy - n_rows * dpy, ox + n_cols * dpx, oy),
                    "truth": truth,
                    "ok": ok,
                })
            if phases:
                windows.append({"path": path, "phases": phases})
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    if not windows:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(
            "the decimation test could not build a target grid with at least "
            "%d posts per side at %.2fx -- the source is too small for this "
            "ratio" % (MIN_DECIMATE_POSTS, ratio))

    return {
        "tmp_dir": tmp_dir,
        "windows": windows,
        "nodata": nod,
        "dpx": dpx,
        "dpy": dpy,
        "clamp": (clamp_lo, clamp_hi),
        "ratio": float(ratio),
        "n_windows": len(windows),
        "n_phases": sum(len(w["phases"]) for w in windows),
    }


def _cleanup_decimate_test(prep):
    """Remove the scratch rasters _prepare_decimate_test() wrote."""
    if prep:
        shutil.rmtree(prep.get("tmp_dir", ""), ignore_errors=True)


def _error_stats(err):
    """Return primary absolute-error metrics for a one-dimensional array.

    RMSE remains the candidate-ranking metric for continuity with the prior
    releases.  P90 and the maximum are reported as tail-error diagnostics so
    a low average error cannot hide a localized high-relief failure.
    """
    err = np.asarray(err, dtype="float64")
    if err.size == 0:
        raise RuntimeError("Accuracy test found no comparable errors")
    abs_err = np.abs(err)
    return {
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(abs_err)),
        "p90_abs_err": float(np.percentile(abs_err, 90)),
        "max_abs_err": float(np.max(abs_err)),
    }


def _decimate_stats(prep, alg):
    """Score one candidate on the ACTUAL decimation, against post truth.

    See the module note above _catmull_rom_weights() for the method and the
    ground-truth validation behind it. Returns the same metric keys
    _holdout_stats() returns, so callers and reports can use either.
    """
    nod = prep["nodata"]
    clamp_lo, clamp_hi = prep["clamp"]
    errors = []
    for window in prep["windows"]:
        for phase in window["phases"]:
            out_ds = gdal.Warp(
                "", window["path"],
                format="MEM",
                outputBounds=phase["bounds"],
                xRes=prep["dpx"], yRes=prep["dpy"],
                resampleAlg=alg,
                dstNodata=nod,
                outputType=gdal.GDT_Float32,
                multithread=True,
            )
            if out_ds is None:
                raise RuntimeError("Decimation warp failed (alg=%s)" % alg)
            got = out_ds.GetRasterBand(1).ReadAsArray().astype("float64")
            out_ds = None

            truth = phase["truth"]
            ok = phase["ok"]
            if got.shape != truth.shape:
                # GDAL can land one row/column off on a fractional ratio.
                rows = min(got.shape[0], truth.shape[0])
                cols = min(got.shape[1], truth.shape[1])
                got = got[:rows, :cols]
                truth = truth[:rows, :cols]
                ok = ok[:rows, :cols]

            if alg in OVERSHOOT_PRONE_RESAMPLERS:
                # Identical to the clamp a delivered tile made with this
                # resampler actually receives, so the comparison is fair --
                # see _holdout_stats()'s docstring for the full reasoning.
                got_valid = np.isfinite(got) & (np.abs(got - nod) > 0.5)
                got[got_valid] = np.clip(got[got_valid], clamp_lo, clamp_hi)

            usable = ok & np.isfinite(got) & (np.abs(got - nod) > 0.5)
            if usable.any():
                errors.append(got[usable] - truth[usable])

    if not errors:
        raise RuntimeError("Decimation test found no comparable posts")
    err = np.concatenate(errors)
    stats = _error_stats(err)
    stats.update({
        "n_scored":     int(err.size),
        "ratio":        prep["ratio"],
        "n_windows":    prep["n_windows"],
        "n_phases":     prep["n_phases"],
        "method":       "decimate",
    })
    return stats


def _holdout_stats(arr, valid, cgt, proj, nodata, alg, holdout_factor=2):
    """Hold-out cross-validation of one resampling algorithm.

    Every ``holdout_factor``-th post (offset 0, in both directions) forms
    the training raster; the algorithm reconstructs the full grid from it;
    the reconstruction is scored ONLY at the withheld posts (those not in
    the training set). ``holdout_factor`` defaults to 2 (the original,
    ratio-agnostic behaviour); pass pick_holdout_factor(ratio, arr.shape)
    to test at (approximately) the actual requested decimation ratio
    instead -- see the module-level v0.57 note above pick_holdout_factor().

    v0.34: the training raster is written to a PRIVATE temporary directory,
    removed in a finally block. It used to be written straight into the DGED
    delivery folder as "_dged_holdout_train.tif" and deleted only on the
    success path -- so if the warp below failed, that scratch file stayed
    behind in the tile folder, and in comparison mode the GUI then ran the
    validator over that same folder and reported "filename does not match
    DGED naming convention" plus "missing .xml sidecar". One warp hiccup
    became a bogus FAIL badge in the comparison report, on a folder whose
    actual tiles were fine.

    Accuracy fix (post-v0.46): for OVERSHOOT_PRONE_RESAMPLERS (cubic /
    cubicspline / lanczos), the reconstruction is now clamped into
    [floor(source min), ceil(source max)] before scoring -- the exact same
    clamp dem2dged_lib.clamp_tile_to_range() applies to DELIVERED tiles made
    with these algorithms (mirrored by dem2dged_validate.check_source()'s
    own clamp_range for its Section H/H2 comparison). Previously this
    function scored the RAW, unclamped warp, so a handful of overshoot
    pixels at sharp discontinuities -- pixels no real delivery ever actually
    contains, because they get clamped before the tile is written -- could
    dominate RMSE/MAE (squared error weights outliers heavily) and make a
    cubic-family method look far less accurate than what a user would
    actually receive. That systematically biased "-resample optimize" away
    from cubic-family methods even on sources where they reconstruct most
    posts more accurately than Bilinear. Scoring the same clamped values
    that would actually ship makes the comparison fair.
    """
    hf = int(holdout_factor)
    if hf < 2:
        raise ValueError("holdout_factor must be >= 2, got %r" % holdout_factor)
    nod = -32767.0 if nodata is None else float(nodata)
    ny, nx = arr.shape
    train = arr[::hf, ::hf].copy()
    tvalid = valid[::hf, ::hf]
    train[~tvalid] = nod
    tgt = (cgt[0], cgt[1] * hf, cgt[2], cgt[3], cgt[4], cgt[5] * hf)

    tmp_dir = tempfile.mkdtemp(prefix="dged_holdout_")
    try:
        drv = gdal.GetDriverByName("GTiff")
        tmp_path = os.path.join(tmp_dir, "holdout_train.tif")
        tds = drv.Create(tmp_path, train.shape[1], train.shape[0], 1,
                         gdal.GDT_Float32)
        tds.SetGeoTransform(tgt)
        if proj:
            tds.SetProjection(proj)
        tb = tds.GetRasterBand(1)
        tb.SetNoDataValue(nod)
        tb.WriteArray(train.astype("float32"))
        tds.FlushCache()
        tds = None

        # Reconstruct the FULL analysis grid from the training grid.
        xmin = cgt[0]
        ymax = cgt[3]
        xmax = xmin + nx * cgt[1]
        ymin = ymax + ny * cgt[5]
        rec_ds = gdal.Warp(
            "", tmp_path,
            format="MEM",
            outputBounds=(xmin, min(ymin, ymax), xmax, max(ymin, ymax)),
            xRes=abs(cgt[1]), yRes=abs(cgt[5]),
            resampleAlg=alg,
            dstNodata=nod,
            outputType=gdal.GDT_Float32,
            multithread=True,
        )
        if rec_ds is None:
            raise RuntimeError("Hold-out warp failed (alg=%s)" % alg)
        rec = rec_ds.GetRasterBand(1).ReadAsArray().astype("float64")
        rec_ds = None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if alg in OVERSHOOT_PRONE_RESAMPLERS and valid.any():
        # Same clamp production applies to delivered tiles (see docstring
        # above) -- computed from the FULL analysis grid's true valid range,
        # matching dem2dged_lib.compute_tile_stats()'s floor/ceil rounding.
        # NoData pixels must be left untouched, exactly like
        # clamp_tile_to_range() does, or a clamp floor below -32767 would
        # silently turn "no data" into a fake valid elevation.
        clamp_lo = math.floor(float(arr[valid].min()))
        clamp_hi = math.ceil(float(arr[valid].max()))
        rec_valid = np.isfinite(rec) & (np.abs(rec - nod) > 0.5)
        rec[rec_valid] = np.clip(rec[rec_valid], clamp_lo, clamp_hi)

    # Withheld posts = every post NOT on the training lattice.
    withheld = np.ones(arr.shape, bool)
    withheld[::hf, ::hf] = False
    m = withheld & valid & np.isfinite(rec) & (np.abs(rec - nod) > 0.5)
    if not m.any():
        raise RuntimeError("Hold-out test found no comparable posts")
    err = rec[m] - arr[m]
    stats = _error_stats(err)
    stats.update({
        "n_holdout":       int(err.size),
        "holdout_factor":  hf,
    })
    return stats


def _roundtrip_stats(tifs, arr, valid, cgt, proj):
    """Round-trip residual of the delivered tiles against the source.

    v0.34: dropped the unused src_path and nodata parameters -- the source
    values are already in `arr`/`valid`, read once by _read_source().
    """
    nod = -32767.0
    ny, nx = arr.shape
    vrt = gdal.BuildVRT("", tifs)
    if vrt is None:
        raise RuntimeError("Could not build VRT mosaic")

    xmin = cgt[0]
    ymax = cgt[3]
    xmax = xmin + nx * cgt[1]
    ymin = ymax + ny * cgt[5]
    warped = gdal.Warp(
        "", vrt,
        format="MEM",
        dstSRS=proj if proj else None,
        outputBounds=(xmin, min(ymin, ymax), xmax, max(ymin, ymax)),
        xRes=abs(cgt[1]), yRes=abs(cgt[5]),
        resampleAlg="bilinear",
        dstNodata=nod,
        outputType=gdal.GDT_Float32,
        multithread=True,
    )
    if warped is None:
        raise RuntimeError("Back-warp failed")
    out = warped.GetRasterBand(1).ReadAsArray().astype("float64")
    warped = None
    vrt = None

    m = valid & np.isfinite(out) & (np.abs(out - nod) > 0.5)
    if not m.any():
        raise RuntimeError("No overlapping valid posts between source and output")
    sv, ov = arr[m], out[m]
    err = ov - sv
    bias = float(np.mean(err))
    return {
        "rt_rmse":        float(np.sqrt(np.mean(err * err))),
        "rt_mae":         float(np.mean(np.abs(err))),
        "rt_bias":        bias,
        "rt_stddev":      float(np.std(err)),
        "rt_max_abs_err": float(np.max(np.abs(err))),
        "src_min":        float(sv.min()),
        "src_max":        float(sv.max()),
        "out_min":        float(ov.min()),
        "out_max":        float(ov.max()),
        "overshoot":      max(0.0, float(ov.max()) - float(sv.max()))
                          + max(0.0, float(sv.min()) - float(ov.min())),
        "n_compared":     int(err.size),
    }


def compute_method_stats(src_path, method_folder, alg="bilinear"):
    """Compare one method's DGED tiles against the original source DEM.

    Returns a dict of metrics (all elevation units are metres):
      rmse / mae / p90_abs_err / max_abs_err / n_holdout /
      holdout_factor                               - hold-out cross-validation
                                                     (primary ranking metrics)
      rt_rmse / rt_mae / rt_bias / rt_stddev /
      rt_max_abs_err / n_compared                  - tile round-trip residual
      src_min / src_max / out_min / out_max /
      overshoot                                    - value-range preservation
      n_tiles, decimation

    v0.57: the hold-out test now runs at (approximately) the ratio this
    method's OWN tiles were actually delivered at -- read from the first
    tile's pixel size vs. the source's -- instead of a fixed 2x; see
    pick_holdout_factor()'s docstring. If the tile can't be opened or its
    pixel size can't be read, this falls back to the original 2x test
    rather than failing the whole comparison.
    """
    tifs = _list_tiles(method_folder)
    arr, valid, cgt, proj, nodata, dec = _read_source(src_path)

    ratio = None
    try:
        tile_ds = gdal_open(tifs[0])
        if tile_ds is not None:
            tile_gt = tile_ds.GetGeoTransform()
            src_gsd_m = source_gsd_meters(src_path)
            tile_gsd_m = _gsd_meters_from_geotransform(
                tile_gt, tile_ds.GetProjection())
            if src_gsd_m > 0 and tile_gsd_m > 0:
                ratio = tile_gsd_m / src_gsd_m
        tile_ds = None
    except Exception:
        ratio = None
    holdout_factor = pick_holdout_factor(ratio, arr.shape)

    stats = {}
    # The hold-out reconstruction metrics are kept for continuity of the
    # report's existing columns, but they are NO LONGER the ranking metric --
    # see the decimate-and-score note above _catmull_rom_weights().
    holdout = _holdout_stats(arr, valid, cgt, proj, nodata, alg,
                             holdout_factor=holdout_factor)
    stats.update(holdout)
    stats["holdout_rmse"] = holdout["rmse"]
    stats["holdout_mae"] = holdout["mae"]
    stats["holdout_p90_abs_err"] = holdout["p90_abs_err"]
    stats["holdout_max_abs_err"] = holdout["max_abs_err"]
    stats["method"] = "holdout"

    # v0.59.0: when this method's tiles were genuinely decimated from the
    # source, rank on the decimation measurement instead. rmse/mae/
    # max_abs_err are what write_comparison_report() sorts and prints, so
    # overwriting them here is what makes the report agree with
    # "-resample optimize".
    if ratio and ratio >= MIN_DECIMATE_RATIO:
        prep = None
        try:
            prep = _prepare_decimate_test(
                arr, valid, cgt, proj, nodata, ratio, source_path=src_path)
            decimated = _decimate_stats(prep, alg)
            stats.update(decimated)
        except Exception as exc:
            # Keep the hold-out numbers rather than failing the whole
            # comparison, but identify the fallback explicitly in the report.
            stats["method"] = "holdout_fallback"
            stats["fallback_reason"] = str(exc)
            pass
        finally:
            _cleanup_decimate_test(prep)

    stats.update(_roundtrip_stats(tifs, arr, valid, cgt, proj))
    stats["n_tiles"] = len(tifs)
    stats["decimation"] = dec
    return stats


# ---------------------------------------------------------------------------
#  Auto-optimize: pick the most accurate method without writing any tiles
# ---------------------------------------------------------------------------

# (gdalwarp alg, display label) -- the first three match COMPARISON_METHODS'
# manual side-by-side test; "optimize" (this list) additionally tries
# Cubic B-Spline. It was left out of COMPARISON_METHODS/the manual GUI
# comparison to avoid changing that feature's fixed 3-test-folder layout,
# but "optimize" only ever returns a single winning algorithm name, so
# adding a candidate here is safe and changes nothing else.
#
# Accuracy fix (post-v0.46): cubicspline was not previously scored at all.
# It is a smoother, higher-order interpolant than plain Cubic Convolution
# and is a well-regarded choice for continuous elevation surfaces, but like
# Cubic it can overshoot near sharp discontinuities -- which is exactly why
# it lives in dem2dged_lib.OVERSHOOT_PRONE_RESAMPLERS and gets the same
# clamp-to-source-range treatment as Cubic both at delivery time
# (clamp_tile_to_range()) and now in _holdout_stats()'s scoring above. With
# that clamp in place, adding it here as a fourth measured candidate can
# only help -resample optimize find a more accurate reconstruction; it can
# never make the pick worse, because it is only chosen when it measures a
# LOWER hold-out RMSE than Nearest/Bilinear/Cubic on that specific source.
#
# v0.57: "average" added as a fifth candidate. It is what -resample auto
# already picks for downsampling, and a controlled measurement found it the
# most noise-robust option short of Cubic across a range of source-DEM
# vertical-noise levels -- but until now "optimize" had never actually
# scored it against the others, so it could never be the pick even on a
# source where it genuinely reconstructs better. Never overshoots (it is a
# footprint mean), so it is not in OVERSHOOT_PRONE_RESAMPLERS and needs no
# clamp.
# v0.59.0: "lanczos" added as a sixth candidate. It was never scored before
# because the hold-out reconstruction test could not be trusted to rank
# candidates honestly (see the decimate-and-score note above), so adding
# candidates to it only widened the blast radius of a bad ranking. Now that
# every candidate is measured on the operation it will actually perform,
# adding one can only help: it is returned solely when it measures a strictly
# lower error than the other five on THAT source. Like the cubic family it
# can overshoot, and it is already in dem2dged_lib.OVERSHOOT_PRONE_RESAMPLERS,
# so it is scored on the same source-range clamp its delivered tiles get.
# In the 28-case ground-truth validation it never won -- which is the point:
# it costs one more warp and cannot make the pick worse.
AUTO_OPTIMIZE_CANDIDATES = [
    ("near",        "Nearest Neighbor"),
    ("bilinear",    "Bilinear Interpolation"),
    ("cubic",       "Cubic Convolution"),
    ("cubicspline", "Cubic B-Spline"),
    ("lanczos",     "Lanczos Windowed Sinc"),
    ("average",     "Average (Box Filter)"),
]


def pick_best_resampling(src_path, angular=False, log_fn=None, dst_gsd_m=None,
                         src_gsd_m=None):
    """Pick the resampling algorithm that reconstructs `src_path` most
    accurately, without writing any DGED tiles or an HTML report.

    New in v0.36, for the "-resample optimize" / GUI "Optimize" option
    (see dem2dged_lib.resolve_resampler(), the caller of this function).
    Reuses the exact same hold-out cross-validation as the Resampling
    Comparison Test above (_read_source() + _holdout_stats()): a subset of
    source posts is withheld, the rest are resampled back onto the full
    grid, and the reconstruction is scored ONLY at the withheld posts --
    real measured elevations the algorithm never saw. Unlike a full
    comparison run, nothing is written to disk except one small temp file
    per candidate (cleaned up inside _holdout_stats()) -- no tile sets, no
    report -- so this is cheap enough to run automatically before every
    conversion.

    ``dst_gsd_m`` (v0.57): the target DGED post spacing for THIS conversion,
    if known. ``src_gsd_m`` is the source spacing in metres. If it is omitted,
    this function calculates it from the source CRS. The ratio is never
    calculated from raw geotransform units, because geographic sources store
    degrees while ``dst_gsd_m`` is in metres. This matters because which
    algorithm reconstructs terrain most accurately is RATIO-DEPENDENT: a
    controlled measurement
    against known ground truth found the fixed 2x test reliably favours
    Cubic, but at the 8x-16x ratios steep terrain is often actually
    delivered at, Nearest Neighbor reconstructed up to 3x more accurately
    (only when the source is comparatively low-noise -- see
    dem2dged_v0.56.0_mountain_terrain_review.md for the full measurement,
    including where that stops being true). Pass None to keep the old fixed
    2x behaviour, e.g. for a caller with no target resolution to hand.

    ``angular``: pass dem2dged_lib.looks_like_angular_data(src_path) (or
    equivalent). When True, this function does NOT run the RMSE comparison
    at all and returns Nearest Neighbor directly. This matters because
    hold-out RMSE is only a valid accuracy measure for data where nearby
    numeric values mean nearby real-world values -- true for elevation, but
    NOT true for a circular quantity like compass aspect: a true value of 1
    degree and a reconstructed value of 359 degrees are two degrees apart
    on a compass, but the naive numeric error is 358, and averaging the two
    (which is what Bilinear and Cubic do across the withheld posts near the
    0/360 seam) gives 180 -- a direction that points the opposite way from
    both real values. RMSE computed that way does not measure
    reconstruction accuracy, it measures how often a tile happens to
    straddle the wraparound seam, so it cannot be used to rank the methods.
    Nearest Neighbor is the one candidate immune to this: it always copies
    an existing source value rather than blending two, so it is returned
    directly without spending time on a comparison that would not mean
    anything.

    ``log_fn``: optional callable(str) for progress/result lines, e.g.
    dem2dged_gui.py's thread-safe log_fn, or plain print() for the CLI.
    Called with human-readable lines but never relied on for control flow.

    Returns (alg, label, stats_by_alg):
      alg          - gdalwarp resampling algorithm name, e.g. "bilinear"
      label        - display label, e.g. "Bilinear Interpolation"
      stats_by_alg - {alg: stats dict from _holdout_stats()} for every
                      candidate that completed successfully; {} when
                      ``angular`` short-circuited the comparison, or when
                      every candidate failed (see the fallback below).
    """
    def _log(msg):
        if log_fn:
            log_fn(msg)

    if angular:
        _log("Auto-optimize: source looks like angular/circular data (e.g. "
             "compass aspect or flow direction) -- RMSE is not meaningful "
             "across the 0/360 wraparound seam, so the accuracy comparison "
             "is skipped and Nearest Neighbor is used (the only method "
             "that can't blend across the seam).")
        return "near", "Nearest Neighbor", {}

    arr, valid, cgt, proj, nodata, _dec = _read_source(src_path)

    ratio = None
    if dst_gsd_m:
        if src_gsd_m is None:
            # Production callers normally pass the original-source spacing.
            # Keep the comparison testable with lightweight source readers
            # that do not implement GDAL dataset reopening, while retaining a
            # geotransform-derived fallback for that case.
            try:
                src_gsd_m = source_gsd_meters(src_path)
            except Exception:
                src_gsd_m = _gsd_meters_from_geotransform(cgt, proj)
        if src_gsd_m and float(src_gsd_m) > 0:
            ratio = float(dst_gsd_m) / float(src_gsd_m)
    holdout_factor = pick_holdout_factor(ratio, arr.shape)

    names = " / ".join(label for _alg, label in AUTO_OPTIMIZE_CANDIDATES)

    # v0.59.0: when the conversion really is a decimation, measure each
    # candidate on THAT operation (decimate-and-score) instead of on the
    # inverse one. The hold-out reconstruction test is kept for the cases
    # where it is the correct measure -- equal spacing or upsampling, where
    # there is no decimation to score -- and as the fallback if the decimate
    # test cannot be set up (source too small for this ratio, warp failure).
    prep = None
    use_decimate = bool(ratio) and ratio >= MIN_DECIMATE_RATIO
    if use_decimate:
        try:
            prep = _prepare_decimate_test(
                arr, valid, cgt, proj, nodata, ratio, source_path=src_path)
        except Exception as ex:
            use_decimate = False
            _log("Auto-optimize: could not set up the decimation test (%s) "
                 "-- falling back to the hold-out reconstruction test, whose "
                 "ranking is unreliable at high ratios on steep terrain."
                 % ex)

    stats_by_alg = {}
    try:
        if use_decimate:
            _log("Auto-optimize: measuring each candidate on the ACTUAL "
                 "decimation (%s) -- source warped to the requested %.2fx "
                 "post spacing and scored against the true terrain height at "
                 "each post, over %d sub-pixel grid phases in %d analysis "
                 "window(s)..."
                 % (names, prep["ratio"], len(DECIMATE_PHASES),
                    prep["n_windows"]))
            for alg, label in AUTO_OPTIMIZE_CANDIDATES:
                try:
                    st = _decimate_stats(prep, alg)
                    stats_by_alg[alg] = st
                    _log("  %-22s RMSE=%.4f m  MAE=%.4f m  P90=%.4f m  "
                         "Max=%.4f m  (n=%s scored posts)"
                         % (label, st["rmse"], st["mae"],
                            st["p90_abs_err"], st["max_abs_err"],
                            "{:,}".format(st["n_scored"])))
                except Exception as ex:
                    _log("  %-22s FAILED: %s" % (label, ex))
        else:
            if ratio and holdout_factor != 2:
                _log("Auto-optimize: running hold-out accuracy comparison "
                     "(%s) against the source DEM, held out at %dx (the "
                     "actual requested decimation is ~%.1fx)..."
                     % (names, holdout_factor, ratio))
            else:
                _log("Auto-optimize: running hold-out accuracy comparison "
                     "(%s) against the source DEM, held out at the standard "
                     "2x test..." % names)
            for alg, label in AUTO_OPTIMIZE_CANDIDATES:
                try:
                    st = _holdout_stats(arr, valid, cgt, proj, nodata, alg,
                                        holdout_factor=holdout_factor)
                    stats_by_alg[alg] = st
                    _log("  %-22s RMSE=%.4f m  MAE=%.4f m  P90=%.4f m  "
                         "Max=%.4f m  (n=%s withheld posts)"
                         % (label, st["rmse"], st["mae"],
                            st["p90_abs_err"], st["max_abs_err"],
                            "{:,}".format(st["n_holdout"])))
                except Exception as ex:
                    _log("  %-22s FAILED: %s" % (label, ex))
    finally:
        _cleanup_decimate_test(prep)

    if not stats_by_alg:
        _log("Auto-optimize: every candidate method failed -- falling "
             "back to Bilinear (the tool's long-standing default).")
        return "bilinear", "Bilinear Interpolation", stats_by_alg

    best_alg = min(stats_by_alg, key=lambda a: stats_by_alg[a]["rmse"])
    best_label = dict(AUTO_OPTIMIZE_CANDIDATES)[best_alg]
    measured_on = ("the actual decimation, scored against the true terrain "
                   "height at each post"
                   if stats_by_alg[best_alg].get("method") == "decimate"
                   else "the fallback hold-out reconstruction test")
    _log("Auto-optimize: selected %s (lowest RMSE = %.4f m, measured on %s)"
         % (best_label, stats_by_alg[best_alg]["rmse"], measured_on))

    # v0.59.0: the advisory below now fires ONLY when the ranking came from
    # the hold-out reconstruction test -- i.e. when the decimation test could
    # not be set up. On the normal path each candidate was measured on the
    # real decimation, so there is nothing to warn about.
    #
    # v0.58.1 shipped this advisory on every high-ratio run, because back then
    # the hold-out test WAS the ranking. Ground-truth validation of the
    # replacement is in verify_mountain_terrain_v0.59.0.py.
    used_holdout = any(st.get("method") != "decimate"
                       for st in stats_by_alg.values())
    if used_holdout and ratio and ratio >= HIGH_RATIO_ADVISORY:
        near_stats = stats_by_alg.get("near")
        avg_stats = stats_by_alg.get("average")
        degenerate = (near_stats is not None and avg_stats is not None
                      and abs(near_stats["rmse"] - avg_stats["rmse"]) < 1e-9)
        _log("Auto-optimize: WARNING -- this ranking came from the FALLBACK "
             "hold-out reconstruction test, not the decimation test, and the "
             "requested decimation is ~%.1fx, at or above the %gx point where "
             "that fallback is known to be unreliable on steep terrain. It "
             "measures how well each candidate RECONSTRUCTS the source, which "
             "is not how accurately it DECIMATES. Treat the selection above "
             "as a hint: convert with an explicit -resample as well and "
             "compare with dem2dged_validate.py --terrain-qa mountain."
             % (ratio, HIGH_RATIO_ADVISORY))
        if degenerate:
            _log("Auto-optimize: WARNING -- Nearest Neighbor and Average "
                 "scored identically, the signature of that fallback's "
                 "limitation (GDAL's 'average' point-samples when "
                 "upsampling, so the two are the same operation inside it).")

    return best_alg, best_label, stats_by_alg


# ---------------------------------------------------------------------------
#  HTML report
# ---------------------------------------------------------------------------

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _fmt(v, digits=4):
    if v is None:
        return "&ndash;"
    if isinstance(v, float):
        return ("%%.%df" % digits) % v
    return _esc(v)


def write_comparison_report(entries, html_path):
    """Render the Resampling Comparison Report.

    ``entries`` is a list with one dict per converted input file:
        {
          "name":    input file display name,
          "src":     source path,
          "level":   product level string,
          "mode":    "GEO" | "UTM",
          "methods": [ { "num", "label", "alg", "folder",
                         "elapsed" (s), "stats" (dict from
                         compute_method_stats) or "error" (str),
                         "validation" (optional "PASS"/"FAIL"/"WARN" str) } ]
        }
    The method with the lowest primary accuracy RMSE per file is marked
    "Most Accurate" (ties broken by round-trip RMSE). The primary method is
    shown explicitly so a hold-out fallback cannot be mistaken for a real
    decimation measurement.
    """
    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    css = """
    body { font-family: 'Segoe UI', Arial, sans-serif; background:#f4f6f9;
           color:#1a1a2e; margin:0; padding:24px; }
    h1 { margin:0 0 4px 0; } .sub { color:#666; margin-bottom:20px; }
    h2 { margin-top:32px; border-bottom:2px solid #e94560; padding-bottom:4px; }
    table { border-collapse: collapse; width:100%; background:#fff;
            box-shadow:0 1px 4px rgba(0,0,0,.08); margin-top:10px; }
    th, td { border:1px solid #d8dce2; padding:8px 10px; text-align:right;
             font-size:13px; white-space:nowrap; }
    th { background:#16213e; color:#fff; text-align:center; }
    th.grp { background:#0f1830; font-size:11px; letter-spacing:.4px; }
    td.method { text-align:left; font-weight:bold; }
    tr.best { background:#e8f8ef; }
    tr.best td.method::after { content:"  \\2605  Best Measured";
             color:#27ae60; font-weight:bold; }
    tr.err td { color:#c0392b; text-align:left; }
    .badge-pass { color:#27ae60; font-weight:bold; }
    .badge-fail { color:#c0392b; font-weight:bold; }
    .badge-warn { color:#f39c12; font-weight:bold; }
    .note { background:#fff; border-left:4px solid #e94560; padding:12px 16px;
            margin-top:24px; font-size:13px; line-height:1.6;
            box-shadow:0 1px 4px rgba(0,0,0,.08); }
    .summary { background:#16213e; color:#fff; padding:14px 18px;
               border-radius:6px; margin-top:14px; font-size:14px; }
    .summary b { color:#7bed9f; }
    """

    def _sort_key(m):
        return (m["stats"]["rmse"], m["stats"].get("rt_rmse", 0.0))

    parts = []
    parts.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    parts.append("<title>DGED Resampling Comparison Report</title>")
    parts.append("<style>%s</style></head><body>" % css)
    parts.append("<h1>DGED Resampling Comparison Report</h1>")
    parts.append("<div class='sub'>dem2dged v%s &nbsp;&middot;&nbsp; "
                 "generated %s</div>" % (_esc(VERSION), _esc(today)))

    for e in entries:
        parts.append("<h2>Input: %s</h2>" % _esc(e["name"]))
        parts.append("<div class='sub'>Source: %s &nbsp;&middot;&nbsp; "
                     "Mode: %s &nbsp;&middot;&nbsp; Level: %s</div>"
                     % (_esc(e.get("src", "")), _esc(e.get("mode", "")),
                        _esc(e.get("level", ""))))

        ok = [m for m in e["methods"] if m.get("stats")]
        best = min(ok, key=_sort_key) if ok else None
        ranked = sorted(ok, key=_sort_key)
        rank_of = {id(m): i + 1 for i, m in enumerate(ranked)}
        methods_used = {str(m["stats"].get("method", "unknown")) for m in ok}
        if methods_used == {"decimate"}:
            primary_label = "DECIMATE-AND-SCORE"
        elif methods_used and methods_used.issubset({"holdout"}):
            primary_label = "HOLD-OUT"
        else:
            primary_label = "METHOD-SPECIFIC / FALLBACK"
        parts.append("<div class='sub'>Primary accuracy metric: <b>%s</b>. "
                     "Fallback rankings are not equivalent to native "
                     "decimation measurements.</div>" % primary_label)

        parts.append(
            "<table>"
            "<tr>"
            "<th rowspan='2'>#</th><th rowspan='2'>Resampling Method</th>"
            "<th colspan='4' class='grp'>PRIMARY ACCURACY</th>"
            "<th colspan='3' class='grp'>TILE ROUND-TRIP (secondary)</th>"
            "<th colspan='3' class='grp'>VALUE RANGE</th>"
            "<th rowspan='2'>Tiles</th><th rowspan='2'>Time (s)</th>"
            "<th rowspan='2'>Validation</th><th rowspan='2'>Primary Rank</th>"
            "</tr>"
            "<tr>"
            "<th title=\"Root Mean Square Error over the withheld hold-out "
            "posts -- squares each error before averaging, so large errors "
            "count more; the primary ranking metric\">RMSE (m)</th>"
            "<th title=\"Mean Absolute Error over the withheld hold-out "
            "posts -- average error magnitude, unsquared, so a few large "
            "outliers don't skew it the way RMSE does\">MAE (m)</th>"
            "<th title=\"Largest single absolute error found among the "
            "withheld hold-out posts\">Max |Err| (m)</th>"
            "<th title=\"90th percentile of absolute error among the "
            "scored primary posts; 90 percent of errors are at or below "
            "this value\">P90 |Err| (m)</th>"
            "<th title=\"Root Mean Square Error on the tile round-trip "
            "check (mosaicked tiles warped back onto the source grid)\">"
            "RMSE (m)</th>"
            "<th title=\"Mean signed error on the round-trip check -- "
            "positive means the method tends to overestimate elevation, "
            "negative means it underestimates\">Bias (m)</th>"
            "<th title=\"Largest single absolute error found on the "
            "round-trip check\">Max |Err| (m)</th>"
            "<th title=\"Minimum .. maximum elevation in the resampled "
            "output\">Output (m)</th>"
            "<th title=\"Minimum .. maximum elevation in the original "
            "source DEM\">Source (m)</th>"
            "<th title=\"How far the output's min/max exceeds the "
            "source's true min/max -- the signature of resampling "
            "&#39;ringing&#39; past real terrain extremes\">Overshoot (m)</th>"
            "</tr>")

        for m in e["methods"]:
            st = m.get("stats")
            if not st:
                parts.append(
                    "<tr class='err'><td>%s</td><td class='method'>%s</td>"
                    "<td colspan='14'>ERROR: %s</td></tr>"
                    % (_esc(m["num"]), _esc(m["label"]),
                       _esc(m.get("error", "unknown"))))
                continue
            cls = " class='best'" if m is best else ""
            val = m.get("validation")
            if val:
                badge = ("pass" if val.startswith("PASS")
                         else "fail" if val.startswith("FAIL") else "warn")
                val_html = "<span class='badge-%s'>%s</span>" % (badge, _esc(val))
            else:
                val_html = "&ndash;"
            parts.append(
                "<tr%s><td>%s</td><td class='method'>%s</td>"
                "<td><b>%s</b></td><td>%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                "<td>%s .. %s</td><td>%s .. %s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (cls, _esc(m["num"]), _esc(m["label"]),
                   _fmt(st["rmse"]), _fmt(st["mae"]),
                   _fmt(st["max_abs_err"], 3),
                   _fmt(st.get("p90_abs_err"), 3),
                   _fmt(st["rt_rmse"]), _fmt(st["rt_bias"]),
                   _fmt(st["rt_max_abs_err"], 3),
                   _fmt(st["out_min"], 2), _fmt(st["out_max"], 2),
                   _fmt(st["src_min"], 2), _fmt(st["src_max"], 2),
                   _fmt(st["overshoot"], 3),
                   st["n_tiles"], _fmt(m.get("elapsed"), 1), val_html,
                   rank_of.get(id(m), "&ndash;")))
        parts.append("</table>")

        if best:
            parts.append(
                "<div class='summary'>Best measured accuracy: "
                "<b>%s</b> &nbsp;(lowest RMSE = %s m; P90 |Err| = %s m; "
                "maximum |Err| = %s m over %s scored posts, "
                "measured on %s)</div>"
                % (_esc(best["label"]), _fmt(best["stats"]["rmse"]),
                   _fmt(best["stats"].get("p90_abs_err"), 3),
                   _fmt(best["stats"].get("max_abs_err"), 3),
                   "{:,}".format(best["stats"].get(
                       "n_scored", best["stats"].get("n_holdout", 0))),
                   ("the actual decimation, against the true terrain height "
                    "at each post (v0.59.0)"
                    if best["stats"].get("method") == "decimate"
                    else "the fallback hold-out reconstruction test")))

        eligible = [m for m in ok
                    if str(m.get("validation", "")).upper() in ("PASS", "WARN")]
        recommended = min(eligible, key=_sort_key) if eligible else None
        if recommended:
            validation = recommended.get("validation") or "not recorded"
            parts.append(
                "<div class='summary'>Recommended for delivery: "
                "<b>%s</b> &nbsp;(validation: %s; no validation FAIL). "
                "A validation FAIL applies only to its named method and "
                "must not be treated as a failure of the other methods.</div>"
                % (_esc(recommended["label"]), _esc(validation)))
        elif ok:
            validation_was_recorded = any(m.get("validation") for m in ok)
            reason = ("no method completed validation"
                      if not validation_was_recorded
                      else "every measured method has a validation FAIL")
            parts.append(
                "<div class='note'><b>No delivery recommendation:</b> %s. "
                "Correct the reported failure or run validation before "
                "distributing any comparison candidate.</div>" % _esc(reason))

    parts.append(
        "<div class='note'><b>How to read this report</b><br>"
        "<b>Terms:</b> RMSE = Root Mean Square Error (squares each error "
        "before averaging, so large errors count more &mdash; the primary "
        "ranking metric). MAE = Mean Absolute Error (average error "
        "magnitude, unsquared, so a few large outliers don't skew it the "
        "way RMSE does). Bias = mean signed error &mdash; positive means "
        "the method tends to overestimate elevation, negative means it "
        "underestimates. P90 |Err| = the absolute-error value at the 90th "
        "percentile, a tail-error indicator. Max |Err| = the single largest "
        "absolute error found. Overshoot = how far the output's min/max exceeds the "
        "source's true min/max, the signature of resampling 'ringing'.<br>"
        "<br>"
        "<b>Hold-out accuracy (primary ranking):</b> every other source "
        "post is withheld, the remaining posts are resampled with the "
        "method's algorithm, and the reconstruction is scored at the "
        "withheld posts &mdash; real measured elevations the algorithm "
        "never saw. Lower RMSE = the algorithm reconstructs true terrain "
        "between posts more accurately, which is exactly what it does when "
        "producing DGED posts. This test cannot be gamed by simply copying "
        "input values.<br>"
        "<b>Tile round-trip (secondary):</b> the delivered tiles are "
        "mosaicked and warped back onto the source grid (identical "
        "bilinear back-warp for every method), then differenced against "
        "the original values &mdash; an end-to-end check of the actual "
        "product (tiling, NoData, data type). Note that Nearest Neighbor "
        "scores near-zero here by construction when upsampling (it copies "
        "source values), which is why it is not the ranking metric.<br>"
        "<b>Overshoot</b> is how far the output exceeds the source's true "
        "min/max &mdash; non-zero values are the fingerprint of Cubic "
        "Convolution 'ringing' at sharp terrain breaks. As a rule of "
        "thumb: Nearest preserves original values but shifts features by "
        "up to half a post; Bilinear is smooth and never overshoots; Cubic "
        "keeps terrain shape crisper but may ring past true extremes.</div>")

    parts.append(
        "<div class='note'><b>Delivery decision:</b> A method's hold-out rank "
        "measures reconstruction quality, while its Validation status checks "
        "the generated DGED delivery. Do not distribute a row marked FAIL. "
        "A FAIL belongs only to that named resampling method; inspect the "
        "separately validated Bilinear, Cubic, or other rows independently.</div>")

    parts.append("</body></html>")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return html_path

# end of dem2dged_compare.py
