#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.59.0
#
# verify_mountain_terrain_v0.59.0.py
#
# PURPOSE
# -------
# Prove, against KNOWN GROUND TRUTH, that v0.59.0's decimate-and-score test
# picks a better resampler than the hold-out reconstruction test it replaced.
# This is the harness that produced the numbers quoted in VERSION.txt,
# README.md and REQUIREMENTS_COMPLIANCE_V0.59.0.md. Run it and the claim is
# either reproduced on your GDAL build or it is not.
#
# WHY GROUND TRUTH IS POSSIBLE HERE
# ---------------------------------
# On a real DEM nobody knows the true terrain height, so any comparison is
# between two estimates. This harness sidesteps that by generating terrain
# from an ANALYTIC formula: the exact elevation at any coordinate, including
# between source posts, is computable. Every candidate's decimated output can
# therefore be scored against the real answer instead of against a proxy.
#
# WHAT IS COMPARED
# ----------------
# For each case:
#   1. Build a source raster from the analytic surface (optionally + noise).
#   2. ORACLE   -- warp the source down to the target spacing with each
#                  candidate, score against the ANALYTIC surface at each
#                  target post, over the same sub-pixel phases the tool uses.
#                  The lowest-error candidate is the right answer.
#   3. OLD      -- rank with dem2dged_compare._holdout_stats() at
#                  pick_holdout_factor()'s factor: v0.58.1's behaviour.
#   4. NEW      -- rank with dem2dged_compare._decimate_stats(): v0.59.0.
#   5. Report which of OLD / NEW agreed with the ORACLE, and -- the number
#      that actually matters -- the REALISED error each one's choice would
#      have delivered.
#
# A method can be "wrong" and cost almost nothing when the candidates are
# nearly tied. Counting correct picks alone would overstate the fix. The
# headline metric is therefore EXCESS OVER ORACLE: how many metres of
# avoidable error each ranking method's choices added up to.
#
# USAGE (Anaconda Prompt, DGED environment activated -- never base)
# -----------------------------------------------------------------
#   conda activate DGED
#   cd C:\path\to\dem2dged_v0.58.0
#   python verify_mountain_terrain_v0.59.0.py
#   python verify_mountain_terrain_v0.59.0.py --quick     (6 cases, ~1 min)
#
# Writes verify_mountain_terrain_v0.59.0_log.txt next to the current folder.
# Exit code 0 if v0.59.0's excess error is lower than v0.58.1's, 1 if not.

import argparse
import math
import os
import shutil
import sys
import tempfile
import datetime

import numpy as np

try:
    from osgeo import gdal, osr
except Exception as exc:                                   # pragma: no cover
    sys.stderr.write(
        "This harness needs real GDAL. Activate the DGED environment first:\n"
        "    conda activate DGED\n"
        "    python verify_mountain_terrain_v0.59.0.py\n"
        "(import error: %s)\n" % exc)
    raise SystemExit(2)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dem2dged_compare as dc                               # noqa: E402

NODATA = -32767.0
_LOG = []


def log(msg=""):
    print(msg)
    _LOG.append(str(msg))


# ---------------------------------------------------------------------------
#  Analytic terrain -- the true height is defined everywhere, not just at posts
# ---------------------------------------------------------------------------

def surface_alpine(u, v):
    """Steep multi-scale relief. Median slope well above the DGIWG 20%
    'predominantly mountainous' threshold at 1 m posts."""
    return (420.0 * np.sin(u / 47.0) * np.cos(v / 39.0)
            + 150.0 * np.sin(u / 13.0 + v / 11.0)
            + 55.0 * np.cos(u / 5.3) * np.sin(v / 6.1))


def surface_rolling(u, v):
    """Gentle relief -- the control case. A fix that only helps mountains
    must not hurt here."""
    return (60.0 * np.sin(u / 95.0) * np.cos(v / 88.0)
            + 18.0 * np.sin(u / 31.0 + v / 27.0))


def surface_ridged(u, v):
    """Sharp ridge crests and gully floors: the shape real mountains have,
    and the shape smooth interpolants handle worst."""
    a = np.abs(np.sin(u / 29.0) * np.cos(v / 23.0))
    b = np.abs(np.sin(u / 8.5 + v / 7.5))
    return 380.0 * (1.0 - a) + 120.0 * (1.0 - b) + 40.0 * np.sin(u / 3.7)


SURFACES = {"alpine": surface_alpine,
            "ridged": surface_ridged,
            "rolling": surface_rolling}


def write_source(path, surface, n, gsd, noise, seed):
    rows, cols = np.mgrid[0:n, 0:n].astype("float64")
    z = surface(cols, rows)
    if noise:
        z = z + noise * np.random.default_rng(seed).standard_normal(z.shape)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, n, n, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((500000.0, gsd, 0.0, 5600000.0, 0.0, -gsd))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(NODATA)
    band.WriteArray(z.astype("float32"))
    ds.FlushCache()
    ds = None
    slope = np.hypot(*np.gradient(surface(cols, rows)))
    return z, float(np.median(slope) * 100.0 / gsd)


def oracle_scores(src_path, surface, n, gsd, ratio):
    """True RMSE of each candidate's real decimation, against the analytic
    surface, pooled over the same sub-pixel phases the tool scores on."""
    dst = gsd * ratio
    x0, y0 = 500000.0, 5600000.0
    out = {}
    for alg, _label in dc.AUTO_OPTIMIZE_CANDIDATES:
        errs = []
        for fx, fy in dc.DECIMATE_PHASES:
            ox = x0 + fx * dst
            oy = y0 - fy * dst
            n_cols = int((x0 + n * gsd - ox) // dst)
            n_rows = int((oy - (y0 - n * gsd)) // dst)
            if n_cols < 2 or n_rows < 2:
                continue
            ds = gdal.Warp("", src_path, format="MEM", resampleAlg=alg,
                           outputBounds=(ox, oy - n_rows * dst,
                                         ox + n_cols * dst, oy),
                           xRes=dst, yRes=dst, outputType=gdal.GDT_Float32,
                           dstNodata=NODATA, multithread=True)
            got = ds.GetRasterBand(1).ReadAsArray().astype("float64")
            ds = None
            cx = ox + (np.arange(n_cols) + 0.5) * dst
            cy = oy - (np.arange(n_rows) + 0.5) * dst
            uu, vv = np.meshgrid((cx - x0) / gsd - 0.5, (y0 - cy) / gsd - 0.5)
            errs.append((got - surface(uu, vv)).ravel())
        e = np.concatenate(errs)
        out[alg] = float(np.sqrt(np.mean(e * e)))
    return out


def rank_old(arr, valid, cgt, proj, ratio):
    factor = dc.pick_holdout_factor(ratio, arr.shape)
    scores = {}
    for alg, _label in dc.AUTO_OPTIMIZE_CANDIDATES:
        try:
            scores[alg] = dc._holdout_stats(arr, valid, cgt, proj, NODATA,
                                            alg, holdout_factor=factor)["rmse"]
        except Exception:
            pass
    return scores


def rank_new(arr, valid, cgt, proj, ratio):
    prep = dc._prepare_decimate_test(arr, valid, cgt, proj, NODATA, ratio)
    try:
        scores = {}
        for alg, _label in dc.AUTO_OPTIMIZE_CANDIDATES:
            try:
                scores[alg] = dc._decimate_stats(prep, alg)["rmse"]
            except Exception:
                pass
        return scores
    finally:
        dc._cleanup_decimate_test(prep)


CASES = [
    # (terrain, ratio, source noise m, seed)
    ("alpine",  16.0, 0.0, 3), ("alpine",  16.0, 2.0, 3),
    ("alpine",  12.5, 0.0, 3), ("alpine",   8.0, 0.0, 3),
    ("alpine",   8.0, 2.0, 3), ("alpine",   5.5, 0.0, 3),
    ("alpine",   4.0, 0.0, 3), ("alpine",   2.0, 0.0, 3),
    ("ridged",  16.0, 0.0, 3), ("ridged",  10.3, 0.0, 3),
    ("ridged",   8.0, 1.0, 3), ("ridged",   4.0, 0.0, 3),
    ("ridged",   2.0, 0.0, 3),
    ("rolling",  8.0, 0.0, 3), ("rolling",  4.0, 1.0, 3),
    ("rolling",  2.0, 1.0, 3),
]
QUICK = [c for c in CASES if c[1] in (16.0, 8.0, 2.0)][:6]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Ground-truth check of the v0.59.0 resampler-selection fix.")
    ap.add_argument("--quick", action="store_true",
                    help="run a 6-case subset instead of the full sweep")
    ap.add_argument("--size", type=int, default=384,
                    help="source raster side in posts (default 384)")
    ap.add_argument("--log", default="verify_mountain_terrain_v0.59.0_log.txt")
    args = ap.parse_args(argv)

    cases = QUICK if args.quick else CASES
    seeds = (3,) if args.quick else (3, 21)

    log("verify_mountain_terrain_v0.59.0")
    log("=" * 78)
    log("timestamp      : %s"
        % datetime.datetime.now().isoformat(" ", "seconds"))
    log("python         : %s" % sys.version.replace("\n", " "))
    log("GDAL           : %s" % gdal.__version__)
    log("numpy          : %s" % np.__version__)
    log("dem2dged       : %s" % getattr(dc, "VERSION", "unknown"))
    log("candidates     : %s"
        % ", ".join(a for a, _l in dc.AUTO_OPTIMIZE_CANDIDATES))
    log("phases scored  : %d" % len(dc.DECIMATE_PHASES))
    log("source size    : %d x %d posts" % (args.size, args.size))
    log("")
    log("OLD = hold-out reconstruction test (v0.58.1 and earlier)")
    log("NEW = decimate-and-score           (v0.59.0)")
    log("Both are ranked against an ORACLE that scores each candidate's real")
    log("decimation against the analytic surface it was generated from.")
    log("")
    log("%-8s %6s %6s %5s | %-12s %-12s %-12s | %8s %8s %8s"
        % ("terrain", "ratio", "noise", "seed", "ORACLE best", "OLD pick",
           "NEW pick", "e_oracle", "e_OLD", "e_NEW"))
    log("-" * 104)

    totals = {"oracle": 0.0, "old": 0.0, "new": 0.0}
    correct = {"old": 0, "new": 0}
    n_cases = 0
    workdir = tempfile.mkdtemp(prefix="verify_v059_")
    try:
        for seed in seeds:
            for kind, ratio, noise, _s in cases:
                surface = SURFACES[kind]
                src = os.path.join(workdir, "src_%s_%s_%s_%s.tif"
                                   % (kind, ratio, noise, seed))
                _z, slope_pct = write_source(src, surface, args.size, 1.0,
                                             noise, seed)
                arr, valid, cgt, proj, _nod, _dec = dc._read_source(src)

                oracle = oracle_scores(src, surface, args.size, 1.0, ratio)
                old = rank_old(arr, valid, cgt, proj, ratio)
                new = rank_new(arr, valid, cgt, proj, ratio)
                if not old or not new:
                    log("%-8s %6.1f  SKIPPED (a ranking produced no scores)"
                        % (kind, ratio))
                    continue

                best = min(oracle, key=oracle.get)
                p_old = min(old, key=old.get)
                p_new = min(new, key=new.get)
                totals["oracle"] += oracle[best]
                totals["old"] += oracle[p_old]
                totals["new"] += oracle[p_new]
                correct["old"] += (p_old == best)
                correct["new"] += (p_new == best)
                n_cases += 1
                log("%-8s %6.1f %6.1f %5d | %-12s %-12s %-12s | "
                    "%8.3f %8.3f %8.3f"
                    % (kind, ratio, noise, seed, best, p_old, p_new,
                       oracle[best], oracle[p_old], oracle[p_new]))
                try:
                    os.remove(src)
                except OSError:
                    pass
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    log("-" * 104)
    if not n_cases:
        log("No case completed -- nothing to conclude.")
        return 1

    excess_old = totals["old"] - totals["oracle"]
    excess_new = totals["new"] - totals["oracle"]
    log("cases                    : %d" % n_cases)
    log("correct candidate chosen : OLD %d/%d      NEW %d/%d"
        % (correct["old"], n_cases, correct["new"], n_cases))
    log("realised RMSE, summed    : ORACLE %7.2f m   OLD %7.2f m   NEW %7.2f m"
        % (totals["oracle"], totals["old"], totals["new"]))
    log("EXCESS OVER ORACLE       : OLD %+7.2f m   NEW %+7.2f m"
        % (excess_old, excess_new))
    if excess_old > 0:
        log("                           -> %.1f%% of the avoidable error removed"
            % (100.0 * (1.0 - excess_new / excess_old)))
    log("")
    log("Excess over oracle is the metric that matters: how many metres of")
    log("AVOIDABLE error each ranking method's choices added up to. Counting")
    log("correct picks alone would overstate the fix, because a wrong pick")
    log("between near-tied candidates costs almost nothing.")
    log("")
    verdict = excess_new <= excess_old
    log("VERDICT: v0.59.0 %s v0.58.1 on this GDAL build."
        % ("IMPROVES ON" if verdict else "DID NOT IMPROVE ON"))

    out_path = os.path.abspath(args.log)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_LOG) + "\n")
    log("")
    log("Log written to: %s" % out_path)
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
