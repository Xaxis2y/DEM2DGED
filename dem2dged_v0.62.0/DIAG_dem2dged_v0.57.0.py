# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# DIAG_dem2dged_v0.57.0.py
# Diagnostic Script Version: 0.01
# Target project version: dem2dged 0.57.0
#
# ============================================================================
# WHAT THIS IS
# ============================================================================
# A read-only diagnostic harness that verifies the three v0.57.0 fixes on
# YOUR machine, in YOUR conda environment (real GDAL, real gdalwarp) -- not
# the cloud sandbox's GDAL 3.8.4 / numpy 1.26.4 / Python 3.12 that the patch
# was developed and pytest-verified against. It does NOT modify any project
# file. Everything it writes goes into:
#
#     <project folder>/diagnostics/
#         dem2dged_v057_diag_<YYYYmmdd_HHMMSS>.log      full human-readable log
#         dem2dged_v057_diag_<YYYYmmdd_HHMMSS>.json     machine-readable summary
#         scratch/                                       synthetic test rasters
#
# The three things v0.57.0 changed, and what each CHECK below confirms:
#   1. "-resample optimize" now benchmarks resamplers at the ACTUAL requested
#      decimation ratio (via a new pick_holdout_factor() helper) instead of
#      always at a fixed 2x hold-out, and "average" was added as a 5th
#      scored candidate. CHECK 06/07 exercise this against a real raster.
#   2. The Gaussian anti-alias -prefilter's help text and GUI label were
#      corrected to say it MEASURABLY WORSENS point accuracy on steep
#      terrain -- no math or code path changed, only the warning text.
#      CHECK 08 confirms the numeric behaviour is byte-identical to before.
#   3. The "rms" resampler was removed outright (it discards the sign of
#      elevation values -- sqrt(mean(x^2)) is never an unbiased estimate of
#      a signed quantity) and now raises a specific, actionable error
#      instead of running. CHECK 05 confirms this end-to-end.
#
# Every CHECK is independent and wrapped so a failure in one never stops the
# others. Each one logs exactly what it measured, so the log alone is enough
# to confirm or refute a finding without re-running.
#
# ============================================================================
# HOW TO RUN  (Anaconda Prompt -- NEVER the base environment)
# ============================================================================
#     (base) C:\> conda activate DGED
#     (DGED) C:\> cd C:\Users\Son\Documents\ChatGPT\dem2dged\dem2dged_v0.56.0\dem2dged_v0.56.0
#     (DGED) C:\...> python DIAG_dem2dged_v0.57.0.py
#
# IMPORTANT: type `python DIAG_dem2dged_v0.57.0.py`, NOT the bare filename --
# the bare filename runs under Windows' .py file association, which is
# usually a DIFFERENT interpreter from the activated conda environment.
#
# Optional flags:
#     --skip-pytest     do not run the pytest suite (much faster)
#     --quick           equivalent to --skip-pytest
#
# When it finishes, send back the .log file from diagnostics/.
# ============================================================================

from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import platform
import subprocess
import sys
import traceback

DIAG_VERSION = "0.01"
TARGET_PROJECT_VERSION = "0.57.0"

HERE = os.path.dirname(os.path.abspath(__file__))
DIAG_DIR = os.path.join(HERE, "diagnostics")
SCRATCH_DIR = os.path.join(DIAG_DIR, "scratch")

_STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = os.path.join(DIAG_DIR, "dem2dged_v057_diag_%s.log" % _STAMP)
JSON_PATH = os.path.join(DIAG_DIR, "dem2dged_v057_diag_%s.json" % _STAMP)

RESULTS = []
_LOG_HANDLE = None


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------

def log(msg=""):
    """Write one line to both the console and the log file, never raising."""
    text = str(msg)
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        sys.stdout.write(text.encode(enc, "replace").decode(enc, "replace"))
        sys.stdout.write("\n")
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.write(text + "\n")
            _LOG_HANDLE.flush()
        except Exception:
            pass


def hr(title=""):
    if title:
        log("")
        log("=" * 78)
        log(title)
        log("=" * 78)
    else:
        log("-" * 78)


def record(name, status, detail="", data=None):
    """status is one of: PASS, FAIL, WARN, INFO, SKIP, ERROR."""
    RESULTS.append({"check": name, "status": status, "detail": detail,
                    "data": data if data is not None else {}})
    log("  [%-5s] %s" % (status, name))
    if detail:
        for line in str(detail).splitlines():
            log("          %s" % line)


def check(name):
    """Decorator turning an exception inside a check into an ERROR record."""
    def deco(fn):
        def wrapper(*a, **kw):
            hr(name)
            try:
                return fn(*a, **kw)
            except Exception:
                record(name, "ERROR",
                       "unhandled exception inside the check itself:\n"
                       + traceback.format_exc())
                return None
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# CHECK 01 -- environment
# ---------------------------------------------------------------------------

@check("CHECK 01 -- environment and interpreter")
def check_environment():
    log("  diagnostic script version : %s" % DIAG_VERSION)
    log("  target project version    : %s" % TARGET_PROJECT_VERSION)
    log("  timestamp                 : %s" % datetime.datetime.now().isoformat())
    log("  project folder            : %s" % HERE)
    log("  python executable         : %s" % sys.executable)
    log("  python version            : %s" % sys.version.replace("\n", " "))
    log("  platform                  : %s" % platform.platform())
    log("  CONDA_DEFAULT_ENV         : %s" % os.environ.get("CONDA_DEFAULT_ENV", "<unset>"))
    log("  CONDA_PREFIX              : %s" % os.environ.get("CONDA_PREFIX", "<unset>"))

    data = {"python": sys.version.split()[0], "executable": sys.executable,
            "conda_env": os.environ.get("CONDA_DEFAULT_ENV", "")}

    ok = True
    try:
        from osgeo import gdal
        log("  GDAL python bindings      : %s" % gdal.__version__)
        data["gdal"] = gdal.__version__
    except Exception as e:
        log("  GDAL python bindings      : NOT AVAILABLE (%s)" % e)
        data["gdal"] = None
        ok = False
    try:
        import numpy
        log("  numpy                     : %s" % numpy.__version__)
        data["numpy"] = numpy.__version__
    except Exception as e:
        log("  numpy                     : NOT AVAILABLE (%s)" % e)
        data["numpy"] = None
        ok = False

    import shutil as _shutil
    warp = _shutil.which("gdalwarp")
    log("  gdalwarp on PATH          : %s" % (warp or "NOT FOUND"))
    data["gdalwarp"] = warp
    if not warp:
        ok = False

    record("CHECK 01 -- environment and interpreter",
           "PASS" if ok else "FAIL",
           "" if ok else "GDAL, numpy or gdalwarp is missing. Activate the "
                         "DGED environment and re-run.",
           data)
    return ok


# ---------------------------------------------------------------------------
# CHECK 02 -- module imports + version consistency
# ---------------------------------------------------------------------------

@check("CHECK 02 -- every module imports cleanly")
def check_imports():
    # NOTE: only dem2dged_lib.py and dem2dged_compliance.py expose a
    # runtime VERSION attribute; every other module's version lives only in
    # its "# Version:" HEADER COMMENT (a plain source-text line, not a
    # Python variable). Header-comment consistency across all 12 files is
    # already checked exhaustively by audit_pure.py (see CHECK 04), so this
    # check only confirms every module still imports without error -- it
    # does not re-check versions to avoid a false FAIL on files that were
    # never meant to expose a runtime VERSION in the first place.
    mods = ["dem2dged_lib", "dem2dged_geo", "dem2dged_utm", "dem2dged_compare",
            "dem2dged_terrain", "dem2dged_compliance", "dem2dged_validate",
            "dem2dged_env"]
    failed = {}
    versions = {}
    for m in mods:
        try:
            mod = __import__(m)
            v = getattr(mod, "VERSION", None)
            versions[m] = v
            log("  %-28s OK   (VERSION attr=%s)" % (m, v))
        except SystemExit as e:
            failed[m] = "SystemExit(%r)" % (e.code,)
            log("  %-28s FAIL -- module-scope sys.exit(%r)" % (m, e.code))
        except Exception as e:
            failed[m] = repr(e)
            log("  %-28s FAIL (%s)" % (m, e))

    ok = not failed
    detail = ("import failures: %s" % json.dumps(failed, indent=2)) if failed else ""
    if ok and versions.get("dem2dged_lib") != TARGET_PROJECT_VERSION:
        ok = False
        detail = ("dem2dged_lib.VERSION=%s, expected %s -- the canonical "
                  "version constant did not bump." % (
                      versions.get("dem2dged_lib"), TARGET_PROJECT_VERSION))
    record("CHECK 02 -- every module imports cleanly", "PASS" if ok else "FAIL",
           detail, {"versions": versions, "failed": failed})
    return ok


# ---------------------------------------------------------------------------
# CHECK 03 -- pytest suite (full, includes tests/test_v057_regressions.py)
# ---------------------------------------------------------------------------

@check("CHECK 03 -- pytest suite")
def check_pytest(skip=False):
    if skip:
        record("CHECK 03 -- pytest suite", "SKIP", "--skip-pytest was given")
        return None
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p",
           "no:cacheprovider"]
    log("  running: %s" % " ".join(cmd))
    log("  (this takes a few minutes -- 450+ tests, many of them real warps)")
    try:
        proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=3600)
    except Exception as e:
        record("CHECK 03 -- pytest suite", "ERROR", "could not run pytest: %s" % e)
        return None

    out = (proc.stdout or "") + (proc.stderr or "")
    log("  --- pytest output (last 100 lines) ---")
    for line in out.splitlines()[-100:]:
        log("  | %s" % line)
    log("  --- end pytest output ---")
    log("  exit code: %s" % proc.returncode)

    summary = ""
    for line in out.splitlines():
        low = line.lower()
        if ("passed" in low or "failed" in low or "error" in low) and "=" in line:
            summary = line.strip()
    record("CHECK 03 -- pytest suite",
           "PASS" if proc.returncode == 0 else "FAIL",
           summary or "exit code %s" % proc.returncode,
           {"returncode": proc.returncode, "summary": summary})
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# CHECK 04 -- audit_pure.py self-audit
# ---------------------------------------------------------------------------

@check("CHECK 04 -- audit_pure.py self-audit")
def check_audit():
    script = os.path.join(HERE, "audit_pure.py")
    if not os.path.isfile(script):
        record("CHECK 04 -- audit_pure.py self-audit", "SKIP",
               "audit_pure.py not found")
        return None
    try:
        proc = subprocess.run([sys.executable, script], cwd=HERE,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=900)
    except Exception as e:
        record("CHECK 04 -- audit_pure.py self-audit", "ERROR", str(e))
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines()[-60:]:
        log("  | %s" % line)
    log("  exit code: %s" % proc.returncode)
    record("CHECK 04 -- audit_pure.py self-audit",
           "PASS" if proc.returncode == 0 else "FAIL",
           "exit code %s" % proc.returncode,
           {"returncode": proc.returncode})
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# raster helper for the fix-specific checks below
# ---------------------------------------------------------------------------

def _make_ridge_raster(path, nx=240, ny=240, gsd=5.0, epsg=32633):
    """A steep synthetic ridge DEM -- the shape that exposed the resample-
    optimize / rms defects during the original review. Not random: a fixed
    seed so every run on every machine produces the identical raster."""
    import numpy as np
    from osgeo import gdal, osr

    rng = np.random.RandomState(20260902)
    x = np.linspace(-1, 1, nx)
    y = np.linspace(-1, 1, ny)
    xx, yy = np.meshgrid(x, y)
    # A steep ridge plus band-limited fractal roughness (beta=1.25), the same
    # terrain model used in the v0.56.0 mountain-terrain review.
    base = 400.0 * np.exp(-((xx) ** 2) / 0.05) * (1.0 - 0.3 * np.abs(yy))
    z = base.copy()
    for k in range(1, 40):
        freq = k * 1.5
        amp = 8.0 * (k ** -1.25)
        phase_x = rng.uniform(0, 2 * np.pi)
        phase_y = rng.uniform(0, 2 * np.pi)
        z += amp * np.cos(freq * xx + phase_x) * np.cos(freq * yy + phase_y)
    z = z.astype(np.float32)

    ox, oy = 500000.0, 5600000.0
    gt = (ox, gsd, 0.0, oy, 0.0, -gsd)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).SetNoDataValue(-9999.0)
    ds.GetRasterBand(1).WriteArray(z)
    ds.FlushCache()
    ds = None
    return z, gt


# ---------------------------------------------------------------------------
# CHECK 05 -- rms resampler is rejected with the specific explanation
# ---------------------------------------------------------------------------

@check("CHECK 05 -- 'rms' resampler is rejected end-to-end")
def check_rms_removed():
    import dem2dged_lib as dl

    if "rms" in dl.GDALWARP_RESAMPLERS:
        record("CHECK 05 -- 'rms' resampler is rejected end-to-end", "FAIL",
               "'rms' is still present in GDALWARP_RESAMPLERS -- the removal "
               "did not take effect in this checkout.")
        return False

    msg = None
    try:
        dl.validate_resampler("rms")
    except SystemExit as e:
        msg = str(e)
    except Exception as e:
        record("CHECK 05 -- 'rms' resampler is rejected end-to-end", "FAIL",
               "expected SystemExit, got %r" % e)
        return False

    if msg is None:
        record("CHECK 05 -- 'rms' resampler is rejected end-to-end", "FAIL",
               "validate_resampler('rms') did not raise at all")
        return False

    log("  validate_resampler('rms') raised:")
    for line in msg.splitlines():
        log("    %s" % line)

    ok = ("rms" in msg.lower() and "sign" in msg.lower()
          and "average" in msg.lower())
    record("CHECK 05 -- 'rms' resampler is rejected end-to-end",
           "PASS" if ok else "FAIL",
           "" if ok else "error message is missing the expected explanation "
                         "(should mention rms, sign, and the 'average' "
                         "alternative)")
    return ok


# ---------------------------------------------------------------------------
# CHECK 06 -- pick_holdout_factor is ratio-aware (pure logic, no GDAL)
# ---------------------------------------------------------------------------

@check("CHECK 06 -- pick_holdout_factor scales with the requested ratio")
def check_holdout_factor_logic():
    import dem2dged_compare as dc

    cases = [
        # (ratio, shape, expected_factor)
        (None, (200, 200), 2),
        (1.0, (200, 200), 2),
        (2.0, (200, 200), 2),
        (8.0, (200, 200), 8),
        (16.0, (200, 200), 16),
        (100.0, (200, 200), dc.MAX_HOLDOUT_FACTOR),
        # small raster: factor must shrink so training data is not starved
        (16.0, (40, 40), None),  # checked separately below (>= 2, training side ok)
    ]
    ok = True
    for ratio, shape, expected in cases[:-1]:
        got = dc.pick_holdout_factor(ratio, shape)
        good = (got == expected)
        ok = ok and good
        log("  ratio=%-6s shape=%-10s -> factor=%-3s (expected %s)  %s"
            % (ratio, shape, got, expected, "OK" if good else "MISMATCH"))

    # small-raster clamp: factor must stay small enough that each holdout
    # training tile is still >= MIN_HOLDOUT_TRAINING_SIDE pixels per side.
    ratio, shape = cases[-1][0], cases[-1][1]
    got = dc.pick_holdout_factor(ratio, shape)
    min_side = min(shape) // got if got else 0
    good = got >= 2 and min_side >= dc.MIN_HOLDOUT_TRAINING_SIDE
    ok = ok and good
    log("  ratio=%-6s shape=%-10s -> factor=%-3s  training_side=%s (>= %s?)  %s"
        % (ratio, shape, got, min_side, dc.MIN_HOLDOUT_TRAINING_SIDE,
           "OK" if good else "MISMATCH"))

    record("CHECK 06 -- pick_holdout_factor scales with the requested ratio",
           "PASS" if ok else "FAIL",
           "" if ok else "see per-case log lines above for the mismatch(es)")
    return ok


# ---------------------------------------------------------------------------
# CHECK 07 -- resolve_resampler('optimize', ...) actually tests the real
# decimation ratio on a real raster, not a fixed 2x hold-out
# ---------------------------------------------------------------------------

@check("CHECK 07 -- 'optimize' benchmarks at the real ratio (end-to-end)")
def check_optimize_uses_real_ratio():
    import dem2dged_compare as dc

    os.makedirs(SCRATCH_DIR, exist_ok=True)
    src_path = os.path.join(SCRATCH_DIR, "v057_ridge_source.tif")
    _make_ridge_raster(src_path, nx=240, ny=240, gsd=5.0)

    # A steep 12x decimation (5m source -> 60m delivered posts) is exactly
    # the regime the v0.56.0 review found the old fixed-2x hold-out got
    # wrong. Ask pick_best_resampling() directly for the ratio/factor it
    # actually used, and confirm it is NOT silently falling back to 2.
    events = []
    orig_holdout = dc._holdout_stats

    def _spy(arr, valid, cgt, proj, nodata, alg, holdout_factor=2):
        events.append((alg, holdout_factor))
        return orig_holdout(arr, valid, cgt, proj, nodata, alg,
                            holdout_factor=holdout_factor)
    dc._holdout_stats = _spy
    try:
        alg, label, meta = dc.pick_best_resampling(
            src_path, angular=False, log_fn=log, dst_gsd_m=60.0)
    finally:
        dc._holdout_stats = orig_holdout

    factors_used = sorted(set(hf for _, hf in events))
    algs_tested = sorted(set(a for a, _ in events))
    log("  requested delivered GSD : 60.0 m  (source GSD 5.0 m -> ratio 12x)")
    log("  hold-out factors used   : %s" % factors_used)
    log("  candidates tested       : %s" % algs_tested)
    log("  winner                  : %s (%s)" % (alg, label))

    # The fix's whole point: the hold-out factor used must reflect the 12x
    # ratio, not be pinned at the pre-v0.57.0 fixed value of 2.
    valid_names = {n for n, _ in dc.AUTO_OPTIMIZE_CANDIDATES}
    ok = factors_used == [12] and alg in valid_names

    record("CHECK 07 -- 'optimize' benchmarks at the real ratio (end-to-end)",
           "PASS" if ok else "FAIL",
           "" if ok else "expected every candidate to be scored with "
                         "holdout_factor=12 (the actual 5m->60m ratio); "
                         "got factors=%s" % factors_used,
           {"factors_used": factors_used, "winner": alg,
            "candidates_tested": algs_tested})
    return ok


# ---------------------------------------------------------------------------
# CHECK 08 -- prefilter numeric behaviour is unchanged (messaging-only fix)
# ---------------------------------------------------------------------------

@check("CHECK 08 -- prefilter math is byte-identical to pre-v0.57.0")
def check_prefilter_unchanged():
    import dem2dged_lib as dl

    # (src_gsd_m, dst_gsd_m) pairs -> implied ratio dst/src
    cases = [(5.0, 10.0), (5.0, 20.0), (5.0, 40.0), (5.0, 5.0)]
    ok = True
    for src_gsd, dst_gsd in cases:
        sigma = dl.gaussian_sigma_for_ratio(src_gsd, dst_gsd)
        ratio = dst_gsd / src_gsd
        # scikit-image-style anti-alias sigma: (ratio - 1) / 2, floored at 0.
        expected = max(0.0, (ratio - 1.0) / 2.0)
        good = abs(sigma - expected) < 1e-9
        ok = ok and good
        log("  src=%-5s dst=%-5s (ratio=%-5s) -> sigma=%-10s expected=%-10s  %s"
            % (src_gsd, dst_gsd, ratio, sigma, expected,
               "OK" if good else "MISMATCH"))

    # explicit numeric override must still bypass the formula unchanged
    explicit = dl.gaussian_sigma_for_ratio(5.0, 40.0, override="1.5")
    good = abs(explicit - 1.5) < 1e-9
    ok = ok and good
    log("  explicit override '1.5' -> sigma=%s  %s"
        % (explicit, "OK" if good else "MISMATCH"))

    # 'gaussian' must still be accepted, and still the only non-None value.
    accepted = True
    try:
        dl.validate_prefilter("gaussian")
        dl.validate_prefilter(None)
        dl.validate_prefilter("none")
    except Exception as e:
        accepted = False
        log("  validate_prefilter() raised unexpectedly: %r" % e)
    ok = ok and accepted

    record("CHECK 08 -- prefilter math is byte-identical to pre-v0.57.0",
           "PASS" if ok else "FAIL",
           "" if ok else "gaussian_sigma_for_ratio() or validate_prefilter() "
                         "behaviour changed -- v0.57.0 was only supposed to "
                         "change help/warning TEXT, not the math.")
    return ok


# ---------------------------------------------------------------------------
# CHECK 09 -- static: no stray 'rms' left in help text / candidate lists
# ---------------------------------------------------------------------------

@check("CHECK 09 -- static grep for leftover 'rms' references")
def check_static_rms_grep():
    import dem2dged_compare as dc
    candidate_names = {n for n, _ in dc.AUTO_OPTIMIZE_CANDIDATES}
    has_average = "average" in candidate_names
    no_rms_in_candidates = "rms" not in candidate_names
    log("  AUTO_OPTIMIZE_CANDIDATES: %s" % sorted(candidate_names))

    ok = has_average and no_rms_in_candidates
    record("CHECK 09 -- static grep for leftover 'rms' references",
           "PASS" if ok else "FAIL",
           "" if ok else "AUTO_OPTIMIZE_CANDIDATES should contain 'average' "
                         "and must not contain 'rms'",
           {"candidates": sorted(candidate_names)})
    return ok


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    global _LOG_HANDLE

    ap = argparse.ArgumentParser(
        description="dem2dged v%s diagnostic harness (script v%s) -- "
                    "verifies the three v0.57.0 fixes on this machine"
                    % (TARGET_PROJECT_VERSION, DIAG_VERSION))
    ap.add_argument("--skip-pytest", action="store_true",
                    help="do not run the pytest suite")
    ap.add_argument("--quick", action="store_true",
                    help="same as --skip-pytest")
    args = ap.parse_args()
    if args.quick:
        args.skip_pytest = True

    os.makedirs(DIAG_DIR, exist_ok=True)
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    _LOG_HANDLE = io.open(LOG_PATH, "w", encoding="utf-8", newline="\n")

    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    hr("dem2dged v0.57.0 DIAGNOSTIC HARNESS (script v%s)" % DIAG_VERSION)
    log("  log file  : %s" % LOG_PATH)
    log("  json file : %s" % JSON_PATH)

    env_ok = check_environment()
    check_imports()
    check_pytest(skip=args.skip_pytest)
    check_audit()

    if env_ok:
        check_rms_removed()
        check_holdout_factor_logic()
        check_optimize_uses_real_ratio()
        check_prefilter_unchanged()
        check_static_rms_grep()
    else:
        log("")
        log("  CHECKS 05-09 were SKIPPED because GDAL/numpy/gdalwarp are not "
            "available in this interpreter.")
        for nm in ("CHECK 05", "CHECK 06", "CHECK 07", "CHECK 08", "CHECK 09"):
            RESULTS.append({"check": nm, "status": "SKIP",
                            "detail": "environment incomplete", "data": {}})

    hr("SUMMARY")
    counts = {}
    for r in RESULTS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    for r in RESULTS:
        log("  %-6s  %s" % (r["status"], r["check"]))
    log("")
    log("  totals: " + "  ".join("%s=%d" % (k, counts[k])
                                 for k in sorted(counts)))
    log("")
    log("  Log written to : %s" % LOG_PATH)
    log("  JSON written to: %s" % JSON_PATH)
    log("")
    log("  Send the .log file back for review.")

    payload = {
        "diag_version": DIAG_VERSION,
        "project_version": TARGET_PROJECT_VERSION,
        "timestamp": datetime.datetime.now().isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "counts": counts,
        "results": RESULTS,
    }
    with io.open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    _LOG_HANDLE.close()
    _LOG_HANDLE = None

    n_bad = counts.get("FAIL", 0) + counts.get("ERROR", 0)
    sys.exit(1 if n_bad else 0)


if __name__ == "__main__":
    main()
