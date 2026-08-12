# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.10
#
# DIAGNOSE_SECTION_H_v0.10.py
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
# It is read-only with respect to your data.
#
# What it reports
# ---------------
#   [1] Source raster: CRS (incl. vertical/compound), declared NoData,
#       data type, size, geotransform.
#   [2] Source statistics at FULL resolution (strip-read, memory safe).
#   [3] Source statistics at the SAME decimation Section H uses -- this
#       reproduces the number Section H called "source", so you can see
#       directly how much of the gap is decimation.
#   [4] Suspicious undeclared NoData sentinels (-9999, -32768, 0, ...) and
#       how much of the source they occupy.
#   [5] Tile mosaic: CRS, count, full-resolution statistics, and the same
#       weighted mean Section H builds from per-tile stats.
#   [6] PAIRED comparison on one common grid: bias = mean(tile - source),
#       stddev, RMSE, and percentiles of the difference. A near-constant
#       bias points at a vertical-datum / systematic shift; a bias near
#       zero with a large spread points at resampling; a bias that appears
#       only in the means but not in the paired diff points at a
#       population/mask mismatch.
#
# Usage (Anaconda Prompt -- see the note at the bottom of this file)
# ------------------------------------------------------------------
#   conda activate dem2dged_anaconda_environment
#   python DIAGNOSE_SECTION_H_v0.10.py ^
#       --src  "C:\path\to\source_dem.tif" ^
#       --tiles "C:\path\to\tile_folder" ^
#       --resample bilinear ^
#       --log  section_h_diagnosis.txt
#
# Then send back section_h_diagnosis.txt.

import argparse
import glob
import math
import os
import sys

import numpy as np

try:
    from osgeo import gdal, osr
except ImportError as _e:
    sys.exit(
        "ERROR: GDAL/osgeo is not importable in this Python environment (%s).\n"
        "Activate the dedicated environment first, e.g.:\n"
        "    conda activate dem2dged_anaconda_environment\n"
        "and run this script as 'python DIAGNOSE_SECTION_H_v0.10.py ...'\n"
        "(running it as 'DIAGNOSE_SECTION_H_v0.10.py ...' can launch a\n"
        " different interpreter via the Windows .py file association)." % _e
    )

NODATA = -32767.0

# Values commonly used as NoData sentinels that a raster may fail to declare.
SUSPECT_SENTINELS = [-32768.0, -32767.0, -9999.0, -9998.0, -999.0,
                     -32000.0, -1000.0, 0.0]


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


def gdal_open(path, mode=gdal.GA_ReadOnly):
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


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="DIAGNOSE_SECTION_H_v0.10",
        description="Diagnose why dem2dged_validate Section H reports a "
                    "min/max/mean mismatch between tiles and source.")
    p.add_argument("--src", required=True,
                   help="Original source DEM (the -src you passed to the validator)")
    p.add_argument("--tiles", required=True,
                   help="Folder containing the delivered .tif tiles")
    p.add_argument("--resample", default="bilinear",
                   help="Resampling algorithm the tiles were produced with "
                        "(near|bilinear|cubic|...). Default: bilinear")
    p.add_argument("--log", default="section_h_diagnosis.txt",
                   help="Log file to write (default: section_h_diagnosis.txt)")
    args = p.parse_args(argv)

    log = Log(args.log)

    try:
        log("DIAGNOSE_SECTION_H v0.10")
        log("Source     : %s" % args.src)
        log("Tile folder: %s" % args.tiles)
        log("Resample   : %s" % args.resample)
        log("GDAL       : %s" % gdal.VersionInfo("RELEASE_NAME"))
        log("Python     : %s" % sys.version.split()[0])
        log("Executable : %s" % sys.executable)
        log("CONDA_PREFIX: %s" % os.environ.get("CONDA_PREFIX", "(not set)"))

        # ------------------------------------------------------------------
        # [1] + [2] + [4]  Source raster
        # ------------------------------------------------------------------
        log.section("[1] SOURCE RASTER PROPERTIES")
        src_st = full_res_stats(args.src, log, sentinel_scan=True)
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
                log("    value %-10.1f : {:>14,} px  ({:6.3f}% of valid){}"
                    .format(c, pct, mark).format(c, pct) if False else
                    "    value %-10.1f : %14s px  (%6.3f%% of valid)%s"
                    % (s, "{:,}".format(c), pct, mark))
        if not flagged:
            log("    (no strongly suspicious undeclared sentinel found)")

        # ------------------------------------------------------------------
        # [5] Tile mosaic
        # ------------------------------------------------------------------
        log.section("[5] DELIVERED TILES")
        tifs = list_tiles(args.tiles)
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
        if nsum:
            log("  AGGREGATE over tiles (this is what Section H calls 'tiles'):")
            log("    min      : %.4f m" % t_min)
            log("    max      : %.4f m" % t_max)
            log("    mean     : %.4f m   (n-weighted)" % (wsum / nsum))
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

        src_ds = gdal_open(args.src)
        warp = gdal.Warp("", src_ds, format="MEM", dstSRS=cmp_wkt,
                         outputBounds=[vminx, vminy, vmaxx, vmaxy],
                         xRes=v_gt[1] * scale, yRes=abs(v_gt[5]) * scale,
                         resampleAlg=args.resample, dstNodata=NODATA,
                         outputType=gdal.GDT_Float32)
        if warp is None:
            raise RuntimeError("decimated source warp failed")
        w_arr = warp.GetRasterBand(1).ReadAsArray().astype("float64")
        w_mask = np.isfinite(w_arr) & (np.abs(w_arr - NODATA) > 0.5)

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
        else:
            log("  (decimated warp produced no valid pixels)")

        # ------------------------------------------------------------------
        # [6] PAIRED comparison on one common grid
        # ------------------------------------------------------------------
        log.section("[6] PAIRED COMPARISON (same grid, pixel by pixel)")
        log("  Section H compares a DIFFERENCE OF MEANS over two separate pixel")
        log("  populations. That cannot separate 'values are shifted' from 'the")
        log("  two sides averaged different pixels'. The paired difference below")
        log("  can.")
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
            log("  bias  mean(tile - source) : %+.4f m" % float(d.mean()))
            log("  median(tile - source)     : %+.4f m" % float(np.median(d)))
            log("  stddev of difference      : %.4f m" % float(d.std()))
            log("  RMSE                      : %.4f m"
                % float(np.sqrt(np.mean(d * d))))
            log("  max |difference|          : %.4f m" % float(np.abs(d).max()))
            log("")
            for q in (1, 5, 25, 50, 75, 95, 99):
                log("    p%-3d of (tile - source) : %+.4f m"
                    % (q, float(np.percentile(d, q))))
            log("")
            log("  Also, means restricted to the SAME pixels (paired):")
            log("    source mean (paired) : %.4f m" % float(w_arr[both].mean()))
            log("    tiles  mean (paired) : %.4f m" % float(t_arr[both].mean()))
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
            log("  tiles inside source range?     : %s"
                % ("YES -- no invented values; a Section H min/max FAIL is an "
                   "artifact" if inside else
                   "NO -- tiles exceed the source's true range (real overshoot)"))
        log("")
        log("Log written to: %s" % os.path.abspath(args.log))
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
