# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.42
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

import os
import shutil
import tempfile
import datetime

import numpy as np
from osgeo import gdal

try:
    from dem2dged_lib import VERSION, gdal_open
except Exception:
    VERSION = "0.42"   # fallback; keep in sync with dem2dged_lib.VERSION

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


def _holdout_stats(arr, valid, cgt, proj, nodata, alg):
    """Hold-out cross-validation of one resampling algorithm.

    Every other post (2x decimation, offset 0) forms the training raster;
    the algorithm reconstructs the full grid from it; the reconstruction is
    scored ONLY at the withheld posts (those not in the training set).

    v0.34: the training raster is written to a PRIVATE temporary directory,
    removed in a finally block. It used to be written straight into the DGED
    delivery folder as "_dged_holdout_train.tif" and deleted only on the
    success path -- so if the warp below failed, that scratch file stayed
    behind in the tile folder, and in comparison mode the GUI then ran the
    validator over that same folder and reported "filename does not match
    DGED naming convention" plus "missing .xml sidecar". One warp hiccup
    became a bogus FAIL badge in the comparison report, on a folder whose
    actual tiles were fine.
    """
    nod = -32767.0 if nodata is None else float(nodata)
    ny, nx = arr.shape
    train = arr[::2, ::2].copy()
    tvalid = valid[::2, ::2]
    train[~tvalid] = nod
    tgt = (cgt[0], cgt[1] * 2, cgt[2], cgt[3], cgt[4], cgt[5] * 2)

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

    # Withheld posts = every post NOT on the (even, even) training lattice.
    withheld = np.ones(arr.shape, bool)
    withheld[::2, ::2] = False
    m = withheld & valid & np.isfinite(rec) & (np.abs(rec - nod) > 0.5)
    if not m.any():
        raise RuntimeError("Hold-out test found no comparable posts")
    err = rec[m] - arr[m]
    return {
        "rmse":        float(np.sqrt(np.mean(err * err))),
        "mae":         float(np.mean(np.abs(err))),
        "max_abs_err": float(np.max(np.abs(err))),
        "n_holdout":   int(err.size),
    }


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
      rmse / mae / max_abs_err / n_holdout        - hold-out cross-validation
                                                    (primary ranking metrics)
      rt_rmse / rt_mae / rt_bias / rt_stddev /
      rt_max_abs_err / n_compared                 - tile round-trip residual
      src_min / src_max / out_min / out_max /
      overshoot                                   - value-range preservation
      n_tiles, decimation
    """
    tifs = _list_tiles(method_folder)
    arr, valid, cgt, proj, nodata, dec = _read_source(src_path)

    stats = {}
    stats.update(_holdout_stats(arr, valid, cgt, proj, nodata, alg))
    stats.update(_roundtrip_stats(tifs, arr, valid, cgt, proj))
    stats["n_tiles"] = len(tifs)
    stats["decimation"] = dec
    return stats


# ---------------------------------------------------------------------------
#  Auto-optimize: pick the most accurate method without writing any tiles
# ---------------------------------------------------------------------------

# (gdalwarp alg, display label) -- same three candidates COMPARISON_METHODS
# offers as a manual side-by-side test, reused here for the automatic pick.
AUTO_OPTIMIZE_CANDIDATES = [
    ("near",     "Nearest Neighbor"),
    ("bilinear", "Bilinear Interpolation"),
    ("cubic",    "Cubic Convolution"),
]


def pick_best_resampling(src_path, angular=False, log_fn=None):
    """Pick the resampling algorithm that reconstructs `src_path` most
    accurately, without writing any DGED tiles or an HTML report.

    New in v0.36, for the "-resample optimize" / GUI "Optimize" option
    (see dem2dged_lib.resolve_resampler(), the caller of this function).
    Reuses the exact same hold-out cross-validation as the Resampling
    Comparison Test above (_read_source() + _holdout_stats()): every other
    source post is withheld, the rest are resampled back onto the full
    grid, and the reconstruction is scored ONLY at the withheld posts --
    real measured elevations the algorithm never saw. Unlike a full
    comparison run, nothing is written to disk except one small temp file
    per candidate (cleaned up inside _holdout_stats()) -- no tile sets, no
    report -- so this is cheap enough to run automatically before every
    conversion.

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

    _log("Auto-optimize: running hold-out accuracy comparison "
         "(Nearest / Bilinear / Cubic) against the source DEM...")
    arr, valid, cgt, proj, nodata, _dec = _read_source(src_path)

    stats_by_alg = {}
    for alg, label in AUTO_OPTIMIZE_CANDIDATES:
        try:
            st = _holdout_stats(arr, valid, cgt, proj, nodata, alg)
            stats_by_alg[alg] = st
            _log("  %-20s RMSE=%.4f m  MAE=%.4f m  (n=%s withheld posts)"
                 % (label, st["rmse"], st["mae"],
                    "{:,}".format(st["n_holdout"])))
        except Exception as ex:
            _log("  %-20s FAILED: %s" % (label, ex))

    if not stats_by_alg:
        _log("Auto-optimize: every candidate method failed -- falling "
             "back to Bilinear (the tool's long-standing default).")
        return "bilinear", "Bilinear Interpolation", stats_by_alg

    best_alg = min(stats_by_alg, key=lambda a: stats_by_alg[a]["rmse"])
    best_label = dict(AUTO_OPTIMIZE_CANDIDATES)[best_alg]
    _log("Auto-optimize: selected %s (lowest hold-out RMSE = %.4f m)"
         % (best_label, stats_by_alg[best_alg]["rmse"]))
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
    The method with the lowest hold-out RMSE per file is marked
    "Most Accurate" (ties broken by round-trip RMSE).
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
    tr.best td.method::after { content:"  \\2605  Most Accurate";
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

        parts.append(
            "<table>"
            "<tr>"
            "<th rowspan='2'>#</th><th rowspan='2'>Resampling Method</th>"
            "<th colspan='3' class='grp'>HOLD-OUT ACCURACY (primary)</th>"
            "<th colspan='3' class='grp'>TILE ROUND-TRIP (secondary)</th>"
            "<th colspan='3' class='grp'>VALUE RANGE</th>"
            "<th rowspan='2'>Tiles</th><th rowspan='2'>Time (s)</th>"
            "<th rowspan='2'>Validation</th><th rowspan='2'>Rank</th>"
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
                    "<td colspan='13'>ERROR: %s</td></tr>"
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
                "<td>%s</td><td>%s</td><td>%s</td>"
                "<td>%s .. %s</td><td>%s .. %s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (cls, _esc(m["num"]), _esc(m["label"]),
                   _fmt(st["rmse"]), _fmt(st["mae"]),
                   _fmt(st["max_abs_err"], 3),
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
                "<div class='summary'>Most accurate for this input: "
                "<b>%s</b> &nbsp;(lowest hold-out RMSE = %s m over "
                "%s withheld check posts)</div>"
                % (_esc(best["label"]), _fmt(best["stats"]["rmse"]),
                   "{:,}".format(best["stats"].get("n_holdout", 0))))

    parts.append(
        "<div class='note'><b>How to read this report</b><br>"
        "<b>Terms:</b> RMSE = Root Mean Square Error (squares each error "
        "before averaging, so large errors count more &mdash; the primary "
        "ranking metric). MAE = Mean Absolute Error (average error "
        "magnitude, unsquared, so a few large outliers don't skew it the "
        "way RMSE does). Bias = mean signed error &mdash; positive means "
        "the method tends to overestimate elevation, negative means it "
        "underestimates. Max |Err| = the single largest absolute error "
        "found. Overshoot = how far the output's min/max exceeds the "
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

    parts.append("</body></html>")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return html_path

# end of dem2dged_compare.py
