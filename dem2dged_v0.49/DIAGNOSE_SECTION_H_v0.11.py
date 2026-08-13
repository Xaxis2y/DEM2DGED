# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.11
#
# DIAGNOSE_SECTION_H_v0.11.py
#
# Purpose
# -------
# Section H of dem2dged_validate.py compares SUMMARY STATISTICS (min / max /
# mean) of the delivered tiles against the source DEM, and reports a FAIL when
# they differ by more than a tolerance. Two structural properties of that
# comparison make its result hard to interpret:
#
#   1. The TILE side is measured at FULL resolution (check_tile ->
#      read_band -> v.min()/v.max()/v.mean() over every valid post).
#      The SOURCE side is measured from a DECIMATED warp:
#          scale = max(1, int(max(mosaicX, mosaicY) / 2000))
#      so the source is subsampled to roughly 2000 px on its long edge.
#      Subsampling can only LOSE extreme values, never create them, so the
#      "source max" is biased low and the "source min" biased high relative
#      to the tiles -- purely as a measurement artifact.
#
#   2. The two means are computed over two SEPARATE pixel populations and
#      compared as a difference-of-means (unpaired). A difference therefore
#      does not distinguish "the elevations are shifted" from "the two sides
#      are averaging different pixels".
#
# This script measures both sides the SAME way, several different ways, and
# prints every number to a log file. It changes nothing and writes no tiles.
# It is read-only with respect to your data (--selftest is the one exception:
# it writes small synthetic files of its own into a throwaway temp folder).
#
# What changed in v0.11 (v0.46 parity update)
# --------------------------------------------
# v0.10 was written against dem2dged_validate.py's check_source()/H2 logic as
# it stood a few releases ago. Two things in that function have since changed
# and v0.10 did not track them, so its numbers could disagree with what the
# real validator reports even though the script "ran fine":
#
#   (a) v0.46 changed the default H2 tolerance (``max_diff``) from a fixed
#       5.0 m to 10.0 m (README v0.46 changelog: steep-terrain Bilinear/Cubic
#       runs were producing 6-10 m sample-window errors that are real
#       resampling behaviour, not defects). v0.10 never took a tolerance
#       argument at all and never printed a PASS/FAIL verdict -- it only
#       dumped raw numbers and left the reader to eyeball them. v0.11 adds
#       --max-diff (default 10.0, matching the current dem2dged_validate.py
#       default) and prints the SAME PASS/FAIL verdicts check_source() would,
#       using the SAME thresholds: min/max at max_diff*2, mean at max_diff
#       (dem2dged_validate.py check_source(), the three-way loop just above
#       the "H2. Sample-window pixel difference" section header).
#
#   (b) check_source() clamps its internal source re-warp into the source's
#       own [floor(min), ceil(max)] range (dem2dged_lib.compute_tile_stats())
#       whenever --resample is one of the OVERSHOOT_PRONE_RESAMPLERS (cubic /
#       cubicspline / lanczos), because the DELIVERED tiles are clamped the
#       same way at conversion time (dem2dged_lib.clamp_tile_to_range()).
#       v0.10 never applied this clamp, so on a cubic/cubicspline/lanczos run
#       it could report an "overshoot" or a min/max gap that the real v0.46
#       validator does not see, because the real comparison baseline is
#       clamped and v0.10's was not. v0.11 replicates the clamp for both the
#       decimated-source comparison in [3] and the paired grid in [6].
#
# Everything else (sections [1], [2], [4], [5], the per-tile scan, the paired
# diff/RMSE/percentiles in [6]) is unchanged from v0.10.
#
# New in v0.11: --selftest
# -------------------------
# This script cannot be exercised in an environment without GDAL/osgeo
# importable, and normally needs a real source DEM plus a real tile folder.
# --selftest removes both requirements: it builds a small synthetic source
# DEM and a matching set of tiles (warped FROM that exact source, so they
# cannot legitimately fail H/H2) in a throwaway temp folder, runs the full
# diagnosis against them, checks that the verdicts come back OK, and deletes
# the temp folder afterwards. Use it to confirm the script itself works in
# your Anaconda environment before pointing it at real project data:
#
#   conda activate dem2dged_anaconda_environment
#   python DIAGNOSE_SECTION_H_v0.11.py --selftest --log selftest_log.txt
#
# Send back selftest_log.txt if it reports anything other than
# "SELFTEST: PASSED".
#
# Usage (Anaconda Prompt -- see the note at the bottom of this file)
# ------------------------------------------------------------------
#   conda activate dem2dged_anaconda_environment
#   python DIAGNOSE_SECTION_H_v0.11.py ^
#       --src  "C:\path\to\source_dem.tif" ^
#       --tiles "C:\path\to\tile_folder" ^
#       --resample bilinear ^
#       --max-diff 10.0 ^
#       --log  section_h_diagnosis.txt
#
# Then send back section_h_diagnosis.txt.

import argparse
import glob
import math
import os
import shutil
import sys
import tempfile

import numpy as np

# GDAL is imported here but the failure is only raised *after* argparse has
# had a chance to run (see main()). v0.10 imported osgeo unconditionally at
# module load time, which meant even "python DIAGNOSE_SECTION_H_v0.10.py -h"
# failed with the GDAL error instead of printing help when run outside the
# conda environment. v0.11 defers the fatal exit until after argument
# parsing so --help always works.
try:
    from osgeo import gdal, osr
    _GDAL_IMPORT_ERROR = None
except ImportError as _e:
    gdal = None
    osr = None
    _GDAL_IMPORT_ERROR = _e

NODATA = -32767.0

# Values commonly used as NoData sentinels that a raster may fail to declare.
SUSPECT_SENTINELS = [-32768.0, -32767.0, -9999.0, -9998.0, -999.0,
                     -32000.0, -1000.0, 0.0]

# Mirrors dem2dged_lib.OVERSHOOT_PRONE_RESAMPLERS exactly (v0.46). Kept as a
# literal copy rather than an import so this script stays a standalone,
# dependency-free diagnostic tool -- if dem2dged_lib.py ever changes this
# set, update it here too.
OVERSHOOT_PRONE_RESAMPLERS = frozenset({"cubic", "cubicspline", "lanczos"})


class Log(object):
    """Write every line to both the console and the log file."""

    def __init__(self, path):
        self.path = path
        self.fh = open(path, "w", encoding="utf-8")

    def __call__(self, msg=""):
        line = str(msg)
        self.fh.write(line + "\n")
        self.fh.flush()
        try:
            print(line)
        except UnicodeEncodeError:
            enc = sys.stdout.encoding or "ascii"
            print(line.encode(enc, errors="replace").decode(enc))

    def section(self, title):
        self("")
        self("=" * 78)
        self(title)
        self("=" * 78)

    def close(self):
        self.fh.close()


def gdal_open(path, mode=None):
    if mode is None:
        mode = gdal.GA_ReadOnly
    try:
        return gdal.Open(path, mode)
    except RuntimeError:
        return None


def describe_srs(wkt, log, label):
    """Print the CRS, and say explicitly whether it carries a vertical part."""
    if not wkt:
        log("  %-22s (none / not set)" % (label + ":"))
        return
    srs = osr.SpatialReference(wkt=wkt)
    is_compound = bool(srs.IsCompound())
    name = srs.GetName() or "(unnamed)"
    log("  %-22s %s" % (label + ":", name))
    log("  %-22s %s" % ("compound (has vertical):", "YES" if is_compound else "no"))
    if is_compound:
        try:
            vert = srs.GetAttrValue("VERT_CS")
        except Exception:
            vert = None
        log("  %-22s %s" % ("vertical CS:", vert or "(could not read)"))
    auth = srs.GetAuthorityCode(None)
    if auth:
        log("  %-22s %s:%s" % ("authority:", srs.GetAuthorityName(None), auth))


def full_res_stats(path, log=None, sentinel_scan=False):
    """Full-resolution min/max/mean/count over valid posts, read in strips.

    Returns a dict. Never loads the whole raster into memory, so this is safe
    on the largest DGED sources.
    """
    ds = gdal_open(path)
    if ds is None:
        raise RuntimeError("GDAL cannot open: %s" % path)
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    xsize, ysize = ds.RasterXSize, ds.RasterYSize

    # ~8 MB per strip at 8 bytes/px
    strip = max(1, min(ysize, 8 * 1024 * 1024 // max(1, xsize * 8)))

    vmin = None
    vmax = None
    total = 0.0
    n_valid = 0
    n_nodata = 0
    sentinel_counts = dict((s, 0) for s in SUSPECT_SENTINELS)

    y = 0
    while y < ysize:
        rows = min(strip, ysize - y)
        arr = band.ReadAsArray(0, y, xsize, rows)
        y += rows
        if arr is None:
            continue
        arr = arr.astype("float64")

        valid = np.isfinite(arr)
        if nodata is not None:
            valid &= np.abs(arr - nodata) > 0.5
        n_nodata += int((~valid).sum())

        if sentinel_scan:
            for s in SUSPECT_SENTINELS:
                # count only where currently considered VALID -- an undeclared
                # sentinel is precisely one that survives the NoData filter
                sentinel_counts[s] += int((valid & (np.abs(arr - s) < 0.5)).sum())

        if valid.any():
            v = arr[valid]
            smin = float(v.min())
            smax = float(v.max())
            vmin = smin if vmin is None else min(vmin, smin)
            vmax = smax if vmax is None else max(vmax, smax)
            total += float(v.sum())
            n_valid += int(v.size)

    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    dtype = gdal.GetDataTypeName(band.DataType)
    ds = None

    return {
        "min": vmin,
        "max": vmax,
        "mean": (total / n_valid) if n_valid else None,
        "n_valid": n_valid,
        "n_nodata": n_nodata,
        "nodata_declared": nodata,
        "xsize": xsize,
        "ysize": ysize,
        "gt": gt,
        "proj": proj,
        "dtype": dtype,
        "sentinels": sentinel_counts if sentinel_scan else None,
    }


def print_stats(log, title, st):
    log("  %s" % title)
    if st["min"] is None:
        log("    (no valid pixels)")
        return
    log("    min      : %.4f m" % st["min"])
    log("    max      : %.4f m" % st["max"])
    log("    mean     : %.4f m" % st["mean"])
    log("    n valid  : {:,}".format(st["n_valid"]))
    if st.get("n_nodata") is not None:
        log("    n nodata : {:,}".format(st["n_nodata"]))


def list_tiles(folder):
    tifs = sorted(glob.glob(os.path.join(folder, "*.tif")))
    if not tifs:
        raise RuntimeError("No .tif tiles found in: %s" % folder)
    return tifs


def clamp_range_for_resample(resample, src_st):
    """Mirror check_source()'s clamp_range logic (dem2dged_validate.py,
    v0.46) exactly: only overshoot-prone resamplers get clamped, and the
    clamp bounds are floor(source min) / ceil(source max) -- the same
    integer rounding dem2dged_lib.compute_tile_stats() uses, because that is
    what the real converter clamps delivered tiles to
    (dem2dged_lib.clamp_tile_to_range()).
    """
    if resample not in OVERSHOOT_PRONE_RESAMPLERS:
        return None
    if src_st["min"] is None:
        return None
    return (float(math.floor(src_st["min"])), float(math.ceil(src_st["max"])))


def apply_clamp(arr, clamp_range):
    """np.clip wrapper that is a no-op when there is nothing to clamp."""
    if clamp_range is None:
        return arr
    return np.clip(arr, clamp_range[0], clamp_range[1])


def evaluate_h_thresholds(src_min, src_max, src_mean, tile_min, tile_max,
                          tile_mean, max_diff):
    """Reproduce check_source()'s H min/max/mean PASS/FAIL verdicts exactly
    (dem2dged_validate.py, the loop immediately above the "H2." section
    header): min and max are allowed max_diff*2, mean is allowed max_diff.
    Returns a list of (name, source_value, tile_value, tolerance, status).
    """
    results = []
    for name, sv, tv, tol_v in [
            ("min",  src_min,  tile_min,  max_diff * 2),
            ("max",  src_max,  tile_max,  max_diff * 2),
            ("mean", src_mean, tile_mean, max_diff)]:
        status = "FAIL" if abs(sv - tv) > tol_v else "OK"
        results.append((name, sv, tv, tol_v, status))
    return results


def run_diagnosis(src_path, tiles_folder, resample, max_diff, log):
    """Run the full section H/H2 diagnosis against ``src_path`` /
    ``tiles_folder`` and write everything to ``log``. Returns a small dict
    summarising the verdicts, mainly so --selftest can check them without
    re-parsing the log text.
    """
    summary = {"h_verdicts": None, "h2_overall_status": None,
              "inside_range": None}

    log("DIAGNOSE_SECTION_H v0.11")
    log("Source     : %s" % src_path)
    log("Tile folder: %s" % tiles_folder)
    log("Resample   : %s" % resample)
    log("Max diff   : %.3f m  (v0.46 default is 10.0 m; v0.45 and earlier "
        "used a fixed 5.0 m -- pass --max-diff 5.0 to reproduce that)"
        % max_diff)
    log("GDAL       : %s" % gdal.VersionInfo("RELEASE_NAME"))
    log("Python     : %s" % sys.version.split()[0])
    log("Executable : %s" % sys.executable)
    log("CONDA_PREFIX: %s" % os.environ.get("CONDA_PREFIX", "(not set)"))

    # ----------------------------------------------------------------------
    # [1] + [2] + [4]  Source raster
    # ----------------------------------------------------------------------
    log.section("[1] SOURCE RASTER PROPERTIES")
    src_st = full_res_stats(src_path, log, sentinel_scan=True)
    log("  size            : %d x %d" % (src_st["xsize"], src_st["ysize"]))
    log("  data type       : %s" % src_st["dtype"])
    log("  declared NoData : %s" % src_st["nodata_declared"])
    gt = src_st["gt"]
    log("  geotransform    : (%.10f, %.10f, %.10f, %.10f, %.10f, %.10f)" % gt)
    describe_srs(src_st["proj"], log, "source CRS")

    log.section("[2] SOURCE STATISTICS -- FULL RESOLUTION (ground truth)")
    print_stats(log, "source, every valid post:", src_st)
    log("")
    log("  NOTE: these are the source's TRUE extremes. Compare them to the")
    log("        tile statistics in [5]. If the tile range sits INSIDE this")
    log("        range, the tiles did not invent any value and the Section H")
    log("        min/max FAIL is a measurement artifact, not a defect.")

    clamp_range = clamp_range_for_resample(resample, src_st)
    log.section("[4] UNDECLARED NoData SENTINEL SCAN")
    log("  Values below are counted ONLY where the pixel currently passes")
    log("  the declared-NoData filter. A large count for a sentinel-looking")
    log("  value means the source very likely uses it as NoData WITHOUT")
    log("  declaring it -- which drags the comparison baseline's mean and")
    log("  min down while the converter may have excluded it.")
    log("")
    tot_valid = max(1, src_st["n_valid"])
    flagged = False
    for s in SUSPECT_SENTINELS:
        c = src_st["sentinels"].get(s, 0)
        if c:
            pct = 100.0 * c / tot_valid
            mark = "  <-- SUSPICIOUS" if (pct > 0.5 and s < -100) else ""
            if mark:
                flagged = True
            log("    value %-10.1f : %14s px  (%6.3f%% of valid)%s"
                % (s, "{:,}".format(c), pct, mark))
    if not flagged:
        log("    (no strongly suspicious undeclared sentinel found)")

    if clamp_range is not None:
        log("")
        log("  RESAMPLE '%s' is overshoot-prone (cubic/cubicspline/lanczos)." % resample)
        log("  dem2dged_lib.clamp_tile_to_range() clamps delivered tiles into")
        log("  [%.4f, %.4f] (floor/ceil of the source's true min/max) at" % clamp_range)
        log("  conversion time, and dem2dged_validate.py's check_source()")
        log("  applies the SAME clamp to its internal source re-warp for a")
        log("  fair comparison. Sections [3] and [6] below apply it too.")

    # ------------------------------------------------------------------
    # [5] Tile mosaic
    # ------------------------------------------------------------------
    log.section("[5] DELIVERED TILES")
    tifs = list_tiles(tiles_folder)
    log("  tile count : %d" % len(tifs))

    vrt = gdal.BuildVRT("", tifs)
    if vrt is None:
        raise RuntimeError("gdal.BuildVRT returned None")
    v_gt = vrt.GetGeoTransform()
    describe_srs(vrt.GetProjection(), log, "tile CRS")
    log("  mosaic size    : %d x %d" % (vrt.RasterXSize, vrt.RasterYSize))
    log("  mosaic pixel   : %.12f x %.12f" % (v_gt[1], abs(v_gt[5])))

    # Per-tile stats, and the SAME weighted mean Section H builds
    log("")
    log("  Per-tile statistics (full resolution, as check_tile computes them):")
    t_min = None
    t_max = None
    wsum = 0.0
    nsum = 0
    for t in tifs:
        st = full_res_stats(t)
        if st["min"] is None:
            log("    %-46s (entirely NoData)" % os.path.basename(t))
            continue
        t_min = st["min"] if t_min is None else min(t_min, st["min"])
        t_max = st["max"] if t_max is None else max(t_max, st["max"])
        wsum += st["mean"] * st["n_valid"]
        nsum += st["n_valid"]
        log("    %-46s min=%10.3f  max=%10.3f  mean=%10.3f  n=%s"
            % (os.path.basename(t), st["min"], st["max"], st["mean"],
               "{:,}".format(st["n_valid"])))

    log("")
    t_mean = (wsum / nsum) if nsum else None
    if nsum:
        log("  AGGREGATE over tiles (this is what Section H calls 'tiles'):")
        log("    min      : %.4f m" % t_min)
        log("    max      : %.4f m" % t_max)
        log("    mean     : %.4f m   (n-weighted)" % t_mean)
        log("    n valid  : {:,}".format(nsum))
        log("")
        log("  NOTE: n valid SUMS the one-post overlap DGED tiles share with")
        log("        their neighbours, so it slightly exceeds the number of")
        log("        distinct posts. Too small to explain a large mean gap.")
    else:
        log("  (no tile produced valid statistics)")

    # ------------------------------------------------------------------
    # [3] Reproduce Section H's decimated source measurement
    # ------------------------------------------------------------------
    log.section("[3] SOURCE AS SECTION H MEASURES IT (decimated)")
    scale = max(1, int(max(vrt.RasterXSize, vrt.RasterYSize) / 2000))
    log("  Section H decimation factor 'scale' = %d" % scale)
    log("  (scale = max(1, int(max(mosaicX, mosaicY) / 2000)))")

    vminx, vmaxy = v_gt[0], v_gt[3]
    vmaxx = vminx + vrt.RasterXSize * v_gt[1]
    vminy = vmaxy + vrt.RasterYSize * v_gt[5]

    cmp_srs = osr.SpatialReference(wkt=vrt.GetProjection())
    try:
        cmp_srs.StripVertical()
    except AttributeError:
        pass
    cmp_wkt = cmp_srs.ExportToWkt() or vrt.GetProjection()

    src_ds = gdal_open(src_path)
    warp = gdal.Warp("", src_ds, format="MEM", dstSRS=cmp_wkt,
                     outputBounds=[vminx, vminy, vmaxx, vmaxy],
                     xRes=v_gt[1] * scale, yRes=abs(v_gt[5]) * scale,
                     resampleAlg=resample, dstNodata=NODATA,
                     outputType=gdal.GDT_Float32)
    if warp is None:
        raise RuntimeError("decimated source warp failed")
    w_arr = warp.GetRasterBand(1).ReadAsArray().astype("float64")
    w_mask = np.isfinite(w_arr) & (np.abs(w_arr - NODATA) > 0.5)
    if clamp_range is not None:
        w_arr = apply_clamp(w_arr, clamp_range)

    if w_mask.any():
        wv = w_arr[w_mask]
        log("")
        log("  decimated source min  : %.4f m" % float(wv.min()))
        log("  decimated source max  : %.4f m" % float(wv.max()))
        log("  decimated source mean : %.4f m" % float(wv.mean()))
        log("  decimated n valid     : {:,}".format(int(wv.size)))
        log("")
        log("  DECIMATION LOSS (full-resolution truth minus this sample):")
        log("    max lost : %.4f m   (true %.4f  ->  sampled %.4f)"
            % (src_st["max"] - float(wv.max()), src_st["max"], float(wv.max())))
        log("    min lost : %.4f m   (true %.4f  ->  sampled %.4f)"
            % (float(wv.min()) - src_st["min"], src_st["min"], float(wv.min())))
        log("    mean shift: %.4f m  (true %.4f  ->  sampled %.4f)"
            % (float(wv.mean()) - src_st["mean"], src_st["mean"],
               float(wv.mean())))
        log("")
        log("  INTERPRETATION: 'max lost' and 'min lost' are pure measurement")
        log("  artifact -- subsampling cannot preserve isolated extremes. If")
        log("  they account for the Section H max/min FAIL, the tiles are fine.")
        log("  'mean shift' should be near zero; subsampling is unbiased for a")
        log("  mean. If it is NOT near zero, the source's valid-pixel mask")
        log("  differs between the two reads (see [4]).")

        if nsum:
            log("")
            log("  SECTION H VERDICT (same thresholds check_source() uses):")
            verdicts = evaluate_h_thresholds(
                float(wv.min()), float(wv.max()), float(wv.mean()),
                t_min, t_max, t_mean, max_diff)
            summary["h_verdicts"] = verdicts
            for name, sv, tv, tol_v, status in verdicts:
                log("    %-4s: source %.2f m vs tiles %.2f m  (|delta|=%.2f, "
                    "tolerance %.2f)  -> %s"
                    % (name, sv, tv, abs(sv - tv), tol_v, status))
    else:
        log("  (decimated warp produced no valid pixels)")

    # ------------------------------------------------------------------
    # [6] PAIRED comparison on one common grid
    # ------------------------------------------------------------------
    log.section("[6] PAIRED COMPARISON (same grid, pixel by pixel)")
    log("  Section H compares a DIFFERENCE OF MEANS over two separate pixel")
    log("  populations. That cannot separate 'values are shifted' from 'the")
    log("  two sides averaged different pixels'. The paired difference below")
    log("  can. This uses the WHOLE decimated grid, not H2's three 512x512")
    log("  windows specifically -- treat it as a broader version of the same")
    log("  idea, not a literal re-run of H2's exact window placement.")
    log("")

    tile_dec = gdal.Warp("", vrt, format="MEM",
                         outputBounds=[vminx, vminy, vmaxx, vmaxy],
                         xRes=v_gt[1] * scale, yRes=abs(v_gt[5]) * scale,
                         resampleAlg="near", dstNodata=NODATA,
                         outputType=gdal.GDT_Float32)
    if tile_dec is None:
        raise RuntimeError("tile decimation warp failed")
    t_arr = tile_dec.GetRasterBand(1).ReadAsArray().astype("float64")
    t_mask = np.isfinite(t_arr) & (np.abs(t_arr - NODATA) > 0.5)

    both = t_mask & w_mask
    log("  pixels valid in SOURCE only : {:,}".format(int((w_mask & ~t_mask).sum())))
    log("  pixels valid in TILES  only : {:,}".format(int((t_mask & ~w_mask).sum())))
    log("  pixels valid in BOTH        : {:,}".format(int(both.sum())))
    log("")

    if both.sum() == 0:
        log("  (no overlapping valid pixels -- the two grids do not align)")
    else:
        d = t_arr[both] - w_arr[both]
        overall_max = float(np.abs(d).max())
        log("  bias  mean(tile - source) : %+.4f m" % float(d.mean()))
        log("  median(tile - source)     : %+.4f m" % float(np.median(d)))
        log("  stddev of difference      : %.4f m" % float(d.std()))
        log("  RMSE                      : %.4f m"
            % float(np.sqrt(np.mean(d * d))))
        log("  max |difference|          : %.4f m" % overall_max)
        log("")
        for q in (1, 5, 25, 50, 75, 95, 99):
            log("    p%-3d of (tile - source) : %+.4f m"
                % (q, float(np.percentile(d, q))))
        log("")
        log("  Also, means restricted to the SAME pixels (paired):")
        log("    source mean (paired) : %.4f m" % float(w_arr[both].mean()))
        log("    tiles  mean (paired) : %.4f m" % float(t_arr[both].mean()))
        log("")
        h2_status = "FAIL" if overall_max > max_diff else "OK"
        summary["h2_overall_status"] = h2_status
        log("  H2-STYLE VERDICT (same tolerance check_source() uses for its")
        log("  per-window max|diff|, applied here to this whole-grid paired")
        log("  comparison): max|diff| %.3f m vs tolerance %.2f m -> %s"
            % (overall_max, max_diff, h2_status))
        log("")
        log("  HOW TO READ THIS:")
        log("   * bias ~= a large constant AND stddev small")
        log("       -> systematic vertical shift (geoid / -source_vertical")
        log("          applied to the tiles but not to the baseline).")
        log("   * bias ~= 0 AND stddev large")
        log("       -> ordinary resampling difference; the Section H mean gap")
        log("          then comes from the POPULATION difference, not values.")
        log("   * paired means agree here but Section H's unpaired means did")
        log("     not -> the mask/footprint differs; see the 'valid in X only'")
        log("     counts above and the sentinel scan in [4].")

    log.section("SUMMARY OF THE NUMBERS THAT MATTER")
    log("  source TRUE min/max (full res) : %.4f .. %.4f m"
        % (src_st["min"], src_st["max"]))
    if nsum:
        log("  tiles      min/max (full res) : %.4f .. %.4f m" % (t_min, t_max))
        inside = (t_min >= src_st["min"] - 0.5) and (t_max <= src_st["max"] + 0.5)
        summary["inside_range"] = inside
        log("  tiles inside source range?     : %s"
            % ("YES -- no invented values; a Section H min/max FAIL is an "
               "artifact" if inside else
               "NO -- tiles exceed the source's true range (real overshoot)"))
    if summary["h_verdicts"] is not None:
        overall = "OK" if all(v[4] == "OK" for v in summary["h_verdicts"]) else "FAIL"
        log("  Section H  (min/max/mean)      : %s" % overall)
    if summary["h2_overall_status"] is not None:
        log("  Section H2 (paired, whole grid): %s" % summary["h2_overall_status"])
    log("")
    log("Log written to: %s" % os.path.abspath(log.path))
    return summary


# ---------------------------------------------------------------------------
# --selftest: build a tiny synthetic source + tiles, run the real pipeline
# against them, and check the verdicts come back clean. GDAL is required
# (same as everything else in this script) but no project data is needed.
# ---------------------------------------------------------------------------

def _make_synthetic_source(path, nx=80, ny=80):
    """Write a small Float32 EPSG:4326 GeoTIFF with smooth terrain, an
    undeclared -9999 sentinel patch, and a declared NoData border."""
    gt = (10.0, 0.001, 0.0, 45.08, 0.0, -0.001)
    xs = gt[0] + (np.arange(nx) + 0.5) * gt[1]
    ys = gt[3] + (np.arange(ny) + 0.5) * gt[5]
    X, Y = np.meshgrid(xs, ys)
    Z = (500.0
         + 250.0 * np.sin(2 * math.pi * (X - 10.0) * 2.5)
                 * np.cos(2 * math.pi * (Y - 45.0) * 2.0)
         + 120.0 * np.exp(-(((X - 10.05) / 0.02) ** 2
                            + ((Y - 45.05) / 0.02) ** 2)))
    Z = Z.astype("float32")
    # a small undeclared-sentinel patch, purely so section [4] has something
    # to report during --selftest
    Z[2:5, 2:5] = -9999.0

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


def _make_synthetic_tiles(src_path, out_dir, resample):
    """Warp the synthetic source into a 2x2 grid of tiles, exactly the way
    dem2dged's converters would (minus the DGED filename/metadata rules,
    which this diagnostic script never reads anyway)."""
    src = gdal_open(src_path)
    gt = src.GetGeoTransform()
    xsize, ysize = src.RasterXSize, src.RasterYSize
    minx, maxy = gt[0], gt[3]
    maxx = minx + xsize * gt[1]
    miny = maxy + ysize * gt[5]
    midx = (minx + maxx) / 2.0
    midy = (miny + maxy) / 2.0

    quads = [
        ("00", minx, midy, midx, maxy),
        ("01", midx, midy, maxx, maxy),
        ("10", minx, miny, midx, midy),
        ("11", midx, miny, maxx, midy),
    ]
    paths = []
    for name, x0, y0, x1, y1 in quads:
        out = os.path.join(out_dir, "synth_tile_%s.tif" % name)
        gdal.Warp(out, src, format="GTiff",
                 outputBounds=[x0, y0, x1, y1],
                 xRes=gt[1], yRes=abs(gt[5]),
                 resampleAlg=resample, dstNodata=NODATA,
                 outputType=gdal.GDT_Float32)
        paths.append(out)
    src = None
    return paths


def run_selftest(resample, max_diff, log):
    log("SELFTEST MODE: building a synthetic source DEM and matching tiles")
    log("in a throwaway temp folder -- no project data is read or written.")
    work = tempfile.mkdtemp(prefix="diagnose_section_h_selftest_")
    try:
        src_path = os.path.join(work, "synthetic_source.tif")
        tiles_dir = os.path.join(work, "synthetic_tiles")
        os.makedirs(tiles_dir, exist_ok=True)
        _make_synthetic_source(src_path)
        _make_synthetic_tiles(src_path, tiles_dir, resample)
        log("  synthetic source: %s" % src_path)
        log("  synthetic tiles : %s (4 tiles)" % tiles_dir)

        summary = run_diagnosis(src_path, tiles_dir, resample, max_diff, log)

        problems = []
        if summary["inside_range"] is not True:
            problems.append("tiles were not reported as inside the source range")
        if summary["h_verdicts"] is not None:
            for name, sv, tv, tol_v, status in summary["h_verdicts"]:
                if status != "OK":
                    problems.append("Section H %s came back %s" % (name, status))
        if summary["h2_overall_status"] not in (None, "OK"):
            problems.append("Section H2-style verdict came back %s"
                            % summary["h2_overall_status"])

        log.section("SELFTEST RESULT")
        if problems:
            log("SELFTEST: FAILED")
            for p in problems:
                log("  - %s" % p)
            log("")
            log("The synthetic tiles were warped directly from the synthetic")
            log("source, so every verdict above should have come back OK/YES.")
            log("A FAILED selftest most likely means either this GDAL build")
            log("behaves differently than expected, or there is a real bug in")
            log("this script -- send this log back rather than trusting the")
            log("script's output on real project data yet.")
            return 1
        log("SELFTEST: PASSED")
        log("The script ran end-to-end against known-good synthetic data and")
        log("every verdict came back as expected. It should be safe to run")
        log("against your real --src / --tiles now.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="DIAGNOSE_SECTION_H_v0.11",
        description="Diagnose why dem2dged_validate Section H reports a "
                    "min/max/mean mismatch between tiles and source.")
    p.add_argument("--src",
                   help="Original source DEM (the -src you passed to the "
                        "validator). Required unless --selftest is given.")
    p.add_argument("--tiles",
                   help="Folder containing the delivered .tif tiles. "
                        "Required unless --selftest is given.")
    p.add_argument("--resample", default="bilinear",
                   help="Resampling algorithm the tiles were produced with "
                        "(near|bilinear|cubic|cubicspline|lanczos|...). "
                        "Default: bilinear")
    p.add_argument("--max-diff", dest="max_diff", type=float, default=10.0,
                   help="Tolerance in metres, matching dem2dged_validate.py's "
                        "-max-diff. v0.46 default is 10.0; pass 5.0 to check "
                        "against the v0.45-and-earlier stricter default.")
    p.add_argument("--log", default="section_h_diagnosis.txt",
                   help="Log file to write (default: section_h_diagnosis.txt)")
    p.add_argument("--selftest", action="store_true",
                   help="Ignore --src/--tiles and run against a small "
                        "synthetic source + tiles built on the fly, to "
                        "verify the script itself works in this environment.")
    args = p.parse_args(argv)

    if not args.selftest and (not args.src or not args.tiles):
        p.error("--src and --tiles are required unless --selftest is given")

    if _GDAL_IMPORT_ERROR is not None:
        sys.exit(
            "ERROR: GDAL/osgeo is not importable in this Python environment (%s).\n"
            "Activate the dedicated environment first, e.g.:\n"
            "    conda activate dem2dged_anaconda_environment\n"
            "and run this script as 'python DIAGNOSE_SECTION_H_v0.11.py ...'\n"
            "(running it as 'DIAGNOSE_SECTION_H_v0.11.py ...' can launch a\n"
            " different interpreter via the Windows .py file association)."
            % _GDAL_IMPORT_ERROR
        )

    log = Log(args.log)
    try:
        if args.selftest:
            return run_selftest(args.resample, args.max_diff, log)
        run_diagnosis(args.src, args.tiles, args.resample, args.max_diff, log)
        return 0
    except Exception as ex:
        log("")
        log("ERROR: %s" % ex)
        import traceback
        log(traceback.format_exc())
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
