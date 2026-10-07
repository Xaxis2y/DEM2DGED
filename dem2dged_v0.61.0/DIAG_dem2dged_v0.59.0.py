#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.58.1
#
# DIAG_dem2dged_v0.59.0.py -- local verification harness for v0.59.0, the
# mountainous-terrain resampler-selection fix.
#
# WHY RUN THIS
# ------------
# v0.59.0 was verified in a Linux sandbox on GDAL 3.8.4 / Python 3.12. That is
# not your machine, and the whole point of this release is a numeric claim
# about how GDAL's resamplers behave -- which is exactly the kind of thing
# that can differ between GDAL builds. This script re-runs every check in YOUR
# Anaconda DGED environment (GDAL 3.13.3 last time) and writes a single log
# you can hand back for review, instead of anyone guessing.
#
#   conda activate DGED
#   cd C:\path\to\dem2dged_v0.58.0
#   python DIAG_dem2dged_v0.59.0.py
#
# Note the command: `python DIAG_...py`, NOT `DIAG_...py`. Typed the second
# way Windows resolves the .py file association and runs a DIFFERENT
# interpreter from the activated environment -- the prompt still says (DGED)
# and nothing looks wrong until numpy or osgeo "goes missing".
#
# Writes DIAG_dem2dged_v0.59.0_log.txt in the current folder.
#
# Each check is one former defect or one v0.59.0 claim, so a FAIL here is a
# regression or an unsupported claim, not a style opinion.

import hashlib
import os
import re
import subprocess
import sys
import datetime

SRC = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(os.getcwd(), "DIAG_dem2dged_v0.59.0_log.txt")
EXPECTED_VERSION = "0.59.0"

_lines = []
_results = []


def log(msg=""):
    print(msg)
    _lines.append(str(msg))


def check(name, ok, detail=""):
    _results.append((name, bool(ok)))
    log("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  -- " + detail) if detail else ""))


def section(title):
    log("")
    log("=" * 78)
    log(title)
    log("=" * 78)


def read(rel, limit=None):
    path = os.path.join(SRC, rel)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read() if limit is None else fh.read(limit)


def run(cmd, timeout=1800):
    """Run a subprocess with THIS interpreter, return (rc, combined output)."""
    try:
        proc = subprocess.run(cmd, cwd=SRC, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
        return proc.returncode, proc.stdout.decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001
        return 999, "could not run %r: %s" % (cmd, exc)


def md5(rel):
    with open(os.path.join(SRC, rel), "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
section("0) Environment")
# ---------------------------------------------------------------------------
log("  timestamp        : %s" % datetime.datetime.now().isoformat(" ", "seconds"))
log("  folder           : %s" % SRC)
log("  sys.executable   : %s" % sys.executable)
log("  python           : %s" % sys.version.replace("\n", " "))
log("  CONDA_PREFIX     : %s" % os.environ.get("CONDA_PREFIX", "(not set)"))

try:
    import numpy
    log("  numpy            : %s" % numpy.__version__)
except Exception as exc:                           # noqa: BLE001
    log("  numpy            : NOT IMPORTABLE (%s)" % exc)

try:
    from osgeo import gdal
    log("  GDAL (python)    : %s" % gdal.__version__)
    HAVE_GDAL = True
except Exception as exc:                           # noqa: BLE001
    log("  GDAL (python)    : NOT IMPORTABLE (%s)" % exc)
    HAVE_GDAL = False

warp = None
for d in os.environ.get("PATH", "").split(os.pathsep):
    for name in ("gdalwarp.exe", "gdalwarp"):
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            warp = cand
            break
    if warp:
        break
log("  gdalwarp on PATH : %s" % (warp or "NO -- integration tests will SKIP"))

# ---------------------------------------------------------------------------
section("1) Byte-compile every module, test and toolbox")
# ---------------------------------------------------------------------------
targets = []
for folder, pattern in ((".", ".py"), ("tests", ".py"), ("DGED_Loader", ".py")):
    base = os.path.join(SRC, folder)
    if os.path.isdir(base):
        targets += [os.path.join(folder, f) for f in sorted(os.listdir(base))
                    if f.endswith(pattern)]
targets += ["DGED_Loader.pyt", os.path.join("DGED_Loader", "DGED_Loader.pyt")]

import py_compile
bad = []
for rel in targets:
    path = os.path.join(SRC, rel)
    if not os.path.isfile(path):
        continue
    try:
        py_compile.compile(path, cfile=os.path.join(
            SRC, "__pycache__", "diag_%s.pyc" % re.sub(r"\W", "_", rel)),
            doraise=True)
    except Exception as exc:                       # noqa: BLE001
        bad.append("%s: %s" % (rel, exc))
check("all %d Python/.pyt files byte-compile" % len(targets), not bad,
      "; ".join(bad[:3]))

# ---------------------------------------------------------------------------
section("2) Version consistency")
# ---------------------------------------------------------------------------
rc, out = run([sys.executable, "BUMP_VERSION.py", "--check", EXPECTED_VERSION])
log(out.rstrip())
check("BUMP_VERSION.py --check %s reports 0 stale" % EXPECTED_VERSION, rc == 0)

rc, out = run([sys.executable, "audit_pure.py"])
log(out.strip().splitlines()[-3] if out.strip() else "(no output)")
check("audit_pure.py reports 0 problems",
      rc == 0 and "RESULT: 0 problem(s)" in out)

# v0.58.1 fix: dem2dged_compare.py's import fallback had been stuck at 0.45.
m = re.search(r'VERSION\s*=\s*"([^"]+)"', read("dem2dged_compare.py", 4000))
check("dem2dged_compare.py import-fallback VERSION is %s (was stuck at 0.45)"
      % EXPECTED_VERSION, bool(m) and m.group(1) == EXPECTED_VERSION,
      "found %r" % (m.group(1) if m else None))

# ---------------------------------------------------------------------------
section("3) v0.58.1 regression checks (must still hold)")
# ---------------------------------------------------------------------------
# (a) The root README must NOT be a copy of the loader README. That is exactly
#     what shipped in v0.58.0.
same = md5("README.md") == md5(os.path.join("DGED_Loader", "README.md"))
check("README.md is the project reference, not a copy of DGED_Loader/README.md",
      not same, "both files hash to %s" % md5("README.md") if same else "")
readme = read("README.md", 20000)
check("README.md opens as the dem2dged project reference",
      readme.lstrip().startswith("# dem2dged"))

# (b) The root .pyt convenience copy must stay in sync with the real one.
check("DGED_Loader.pyt matches DGED_Loader/DGED_Loader.pyt",
      md5("DGED_Loader.pyt") == md5(os.path.join("DGED_Loader",
                                                 "DGED_Loader.pyt")))

# (c) The retired one-shot bumper must refuse to run rather than corrupt
#     VERSION.txt.
rc, out = run([sys.executable, "UPDATE_VERSIONS.py"])
check("UPDATE_VERSIONS.py refuses to run (exit != 0)", rc != 0,
      "exit=%d" % rc)
check("VERSION.txt has exactly one 'Changes in v%s:' section" % EXPECTED_VERSION,
      read("VERSION.txt").count("Changes in v%s:" % EXPECTED_VERSION) == 1)

# (d) BUMP_VERSION.py must be idempotent: a second bump finds nothing.
rc, out = run([sys.executable, "BUMP_VERSION.py",
               "--from", "0.58.0", "--to", EXPECTED_VERSION])
check("BUMP_VERSION.py dry run 0.58.0 -> %s now changes 0 files (idempotent)"
      % EXPECTED_VERSION,
      rc == 0 and "0 file(s) would change" in out)

# (e) The retracted pre-filter recommendation must be gone from every document
#     and the correction present.
for rel, must_not, must in (
        ("DEM2DGED_User_Manual.md",
         "can improve rough mountainous terrain while harming near-planar",
         "not recommended"),
        ("README.md",
         "Consider `--prefilter gaussian` when you are downsampling a "
         "high-relief source",
         "44"),
        ("QUICKSTART.html", "", "44% to 102%")):
    body = read(rel)
    ok = (must_not not in body if must_not else True) and (must in body)
    check("%s carries the v0.57.0 pre-filter correction" % rel, ok)

body = read("selftest_prefilter.py")
check("selftest_prefilter.py states it measures aliasing, not point accuracy",
      "NOT a point-accuracy measurement" in body
      or "does NOT measure POINT ACCURACY" in body)

# (f) The optimize advisory must exist and be advisory only.
import importlib
sys.path.insert(0, SRC)
advisory_ok = False
try:
    cmp_mod = importlib.import_module("dem2dged_compare")
    advisory_ok = getattr(cmp_mod, "HIGH_RATIO_ADVISORY", None) == 8.0
except Exception as exc:                           # noqa: BLE001
    log("  (could not import dem2dged_compare: %s)" % exc)
check("dem2dged_compare.HIGH_RATIO_ADVISORY == 8.0", advisory_ok)

# ---------------------------------------------------------------------------
section("4) v0.59.0 -- the resampler-selection fix, against real GDAL")
# ---------------------------------------------------------------------------
if not HAVE_GDAL:
    log("  SKIPPED -- osgeo not importable in this interpreter.")
else:
    import tempfile
    import numpy as np
    from osgeo import osr

    check("lanczos is a scored candidate (v0.59.0 added it)",
          "lanczos" in dict(cmp_mod.AUTO_OPTIMIZE_CANDIDATES))
    check("six candidates are scored",
          len(cmp_mod.AUTO_OPTIMIZE_CANDIDATES) == 6,
          "%d" % len(cmp_mod.AUTO_OPTIMIZE_CANDIDATES))
    check("the decimate test scores several sub-pixel grid phases",
          len(cmp_mod.DECIMATE_PHASES) >= 4,
          "%d phases" % len(cmp_mod.DECIMATE_PHASES))

    def _surface(xx, yy):
        return (420.0 * np.sin(xx / 47.0) * np.cos(yy / 39.0)
                + 150.0 * np.sin(xx / 13.0 + yy / 11.0)
                + 55.0 * np.cos(xx / 5.3) * np.sin(yy / 6.1))

    n, factor = 384, 16
    yy, xx = np.mgrid[0:n, 0:n].astype("float64")
    z = _surface(xx, yy)
    tmp = tempfile.mkdtemp(prefix="dem2dged_diag_")
    src = os.path.join(tmp, "steep.tif")
    ds = gdal.GetDriverByName("GTiff").Create(src, n, n, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((500000.0, 1.0, 0, 5000000.0, 0, -1.0))
    sr = osr.SpatialReference()
    sr.ImportFromEPSG(32633)
    ds.SetProjection(sr.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767.0)
    band.WriteArray(z.astype("float32"))
    ds.FlushCache()
    ds = None

    # --- the fix itself ----------------------------------------------------
    lines = []
    picked, _label, stats = cmp_mod.pick_best_resampling(
        src, angular=False, log_fn=lines.append, dst_gsd_m=float(factor))
    check("optimize measured the DECIMATION, not a reconstruction",
          all(st.get("method") == "decimate" for st in stats.values()),
          "%r" % {a: st.get("method") for a, st in stats.items()})
    check("the ACTUAL 16x ratio reached the measurement",
          all(st.get("ratio") == float(factor) for st in stats.values()))
    check("no high-ratio warning on the fixed path",
          not any("WARNING" in ln for ln in lines))
    check("Nearest and Average are no longer degenerate",
          abs(stats["near"]["rmse"] - stats["average"]["rmse"]) > 1e-6,
          "near=%.6f average=%.6f" % (stats["near"]["rmse"],
                                      stats["average"]["rmse"]))

    # --- and does it actually pick the best one? ---------------------------
    true_rmse = {}
    for alg, _lbl in cmp_mod.AUTO_OPTIMIZE_CANDIDATES:
        errs = []
        for fx, fy in cmp_mod.DECIMATE_PHASES:
            ox = 500000.0 + fx * factor
            oy = 5000000.0 - fy * factor
            n_cols = int((500000.0 + n - ox) // factor)
            n_rows = int((oy - (5000000.0 - n)) // factor)
            out_ds = gdal.Warp("", src, format="MEM", resampleAlg=alg,
                               outputBounds=(ox, oy - n_rows * factor,
                                             ox + n_cols * factor, oy),
                               xRes=factor, yRes=factor,
                               outputType=gdal.GDT_Float32,
                               dstNodata=-32767.0)
            arr = out_ds.GetRasterBand(1).ReadAsArray().astype("float64")
            out_ds = None
            cx = ox + (np.arange(n_cols) + 0.5) * factor
            cy = oy - (np.arange(n_rows) + 0.5) * factor
            uu, vv = np.meshgrid((cx - 500000.0) - 0.5, (5000000.0 - cy) - 0.5)
            errs.append((arr - _surface(uu, vv)).ravel())
        e = np.concatenate(errs)
        true_rmse[alg] = float(np.sqrt(np.mean(e * e)))

    best_true = min(true_rmse, key=true_rmse.get)
    log("")
    log("  TRUE point accuracy at %dx (vs. the analytic surface):" % factor)
    for alg, val in sorted(true_rmse.items(), key=lambda kv: kv[1]):
        log("    %-14s RMSE %9.3f m" % (alg, val))
    log("  v0.59.0 decimate-and-score ranking:")
    for alg, st in sorted(stats.items(), key=lambda kv: kv[1]["rmse"]):
        log("    %-14s RMSE %9.3f m" % (alg, st["rmse"]))
    log("  optimize picked %r; true best is %r." % (picked, best_true))
    check("optimize now picks the genuinely most accurate candidate",
          picked == best_true,
          "picked %s (true RMSE %.3f m), best is %s (%.3f m)"
          % (picked, true_rmse[picked], best_true, true_rmse[best_true]))

    # --- and what would v0.58.1 have picked on the same source? ------------
    arr, valid, cgt, proj, nodata, _dec = cmp_mod._read_source(src)
    old_factor = cmp_mod.pick_holdout_factor(float(factor), arr.shape)
    old_scores = {}
    for alg, _lbl in cmp_mod.AUTO_OPTIMIZE_CANDIDATES:
        try:
            old_scores[alg] = cmp_mod._holdout_stats(
                arr, valid, cgt, proj, nodata, alg,
                holdout_factor=old_factor)["rmse"]
        except Exception as exc:                       # noqa: BLE001
            log("    (old test failed for %s: %s)" % (alg, exc))
    if old_scores:
        old_pick = min(old_scores, key=old_scores.get)
        log("")
        log("  For contrast, the v0.58.1 hold-out test on the same source:")
        for alg, val in sorted(old_scores.items(), key=lambda kv: kv[1]):
            log("    %-14s RMSE %9.3f m" % (alg, val))
        log("  v0.58.1 would have picked %r -- true RMSE %.3f m."
            % (old_pick, true_rmse[old_pick]))
        log("  v0.59.0 picked %r -- true RMSE %.3f m."
            % (picked, true_rmse[picked]))
        log("  Avoidable error removed on this one case: %.3f m."
            % (true_rmse[old_pick] - true_rmse[picked]))
        check("v0.59.0's pick is at least as accurate as v0.58.1's",
              true_rmse[picked] <= true_rmse[old_pick] + 1e-9)

    # --- upsampling must still use the hold-out test -----------------------
    up_lines = []
    _p, _l, up_stats = cmp_mod.pick_best_resampling(
        src, angular=False, log_fn=up_lines.append, dst_gsd_m=0.5)
    check("upsampling still uses the hold-out reconstruction test "
          "(the correct measure there)",
          all("holdout_factor" in st for st in up_stats.values()))

section("5) Offline ArcGIS toolbox harness")
# ---------------------------------------------------------------------------
rc, out = run([sys.executable,
               os.path.join("DGED_Loader", "test_dged_loader.py")])
tail = out.strip().splitlines()[-1] if out.strip() else "(no output)"
log("  last line: %s" % tail)
check("DGED_Loader/test_dged_loader.py passes",
      rc == 0 and "ALL TESTS PASSED" in out)

section("6) Ground-truth sweep -- the number the release notes quote")
# ---------------------------------------------------------------------------
harness = os.path.join(SRC, "verify_mountain_terrain_v0.59.0.py")
if not os.path.isfile(harness):
    check("verify_mountain_terrain_v0.59.0.py is present", False)
elif not HAVE_GDAL:
    log("  SKIPPED -- needs real GDAL.")
else:
    rc, out = run([sys.executable, harness, "--quick"], timeout=2400)
    for line in out.strip().splitlines():
        if any(k in line for k in ("correct candidate", "EXCESS OVER",
                                   "realised RMSE", "VERDICT", "avoidable")):
            log("  " + line.strip())
    check("the ground-truth sweep confirms v0.59.0 beats v0.58.1 here",
          rc == 0 and "IMPROVES ON" in out)

# ---------------------------------------------------------------------------
section("7) Full pytest suite")
# ---------------------------------------------------------------------------
rc, out = run([sys.executable, "-m", "pytest", "-q"])
tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:]
log("  %s" % (tail[0] if tail else "(no output)"))
if "No module named pytest" in out:
    check("pytest suite passes", False,
          "pytest is not installed in this environment: "
          "conda install -n <env> pytest")
else:
    check("pytest suite passes", rc == 0 and " failed" not in out)
    if warp is None:
        log("  NOTE: gdalwarp was not on PATH, so the integration tests")
        log("  SKIPPED. A skip is an environment gap, not a pass -- put the")
        log("  environment's Library\\bin on PATH and re-run for full cover.")

# ---------------------------------------------------------------------------
section("RESULT")
# ---------------------------------------------------------------------------
failed = [n for n, ok in _results if not ok]
log("  %d check(s) run, %d failed." % (len(_results), len(failed)))
for name in failed:
    log("    FAILED: %s" % name)
log("")
log("  Log written to: %s" % LOG_PATH)

with open(LOG_PATH, "w", encoding="utf-8") as fh:
    fh.write("\n".join(_lines) + "\n")

sys.exit(1 if failed else 0)
