# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# RELEASE_GATE_v0.56.0.py
# Release Gate Version: 0.01
# Target project version: dem2dged 0.56.0
#
# ============================================================================
# WHAT THIS IS
# ============================================================================
# One command that answers "can I ship this?". It runs, in dependency order,
# and stops for nothing -- every stage runs even if an earlier one failed, so
# a single log shows the whole picture rather than the first problem only:
#
#   01  environment            interpreter, GDAL, gdalwarp, numpy, pytest
#   02  byte-compile           every .py in the project
#   03  audit_pure             the project's own version-consistency audit
#   04  pytest                 the full suite, including the v0.56 regressions
#   05  regression harness     DIAG_dem2dged_v0.56.0.py -- one check per
#                              v0.55.0 finding; a FAIL here is a REGRESSION
#   06  end-to-end GEO         real conversion + validation on a synthetic DEM
#   07  end-to-end UTM         real conversion + validation
#   08  pre-filter             CLI and GUI, proving the v0.56 GUI wiring works
#   09  resume + failure       re-run skips existing tiles; a missing tile is
#                              regenerated (finding B5)
#   10  packaging              dem2dged_package.py for real, into a temp dir
#
# Everything it writes goes into release_gate/ next to this script. It does
# NOT modify any project file.
#
# ============================================================================
# HOW TO RUN  (Anaconda Prompt -- dedicated environment, never base)
# ============================================================================
#     (base) C:\> conda activate DGED
#     (DGED) C:\> conda install -c conda-forge pytest      :: if missing
#     (DGED) C:\> cd C:\Users\Son\Documents\ChatGPT\dem2dged\dem2dged_v0.55.0
#     (DGED) C:\...> python RELEASE_GATE_v0.56.0.py
#
# Type `python RELEASE_GATE_v0.56.0.py`, not the bare filename -- the bare
# form resolves the Windows .py association and may run a different
# interpreter from the activated environment.
#
# Exit code 0 means every stage passed. Send back
# release_gate/release_gate_<timestamp>.log either way.
# ============================================================================

from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import traceback

GATE_VERSION = "0.01"
PROJECT_VERSION = "0.56.0"

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_DIR = os.path.join(HERE, "release_gate")
WORK_DIR = os.path.join(GATE_DIR, "work")

_STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = os.path.join(GATE_DIR, "release_gate_%s.log" % _STAMP)
JSON_PATH = os.path.join(GATE_DIR, "release_gate_%s.json" % _STAMP)

STAGES = []
_LOG = None


# ── logging ──────────────────────────────────────────────────────────────────

def log(msg=""):
    text = str(msg)
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        sys.stdout.write(text.encode(enc, "replace").decode(enc, "replace") + "\n")
    if _LOG is not None:
        try:
            _LOG.write(text + "\n")
            _LOG.flush()
        except Exception:
            pass


def head(title):
    log("")
    log("=" * 78)
    log(title)
    log("=" * 78)


def record(name, status, detail="", data=None):
    STAGES.append({"stage": name, "status": status, "detail": detail,
                   "data": data or {}})
    log("  [%-4s] %s" % (status, name))
    for line in str(detail).splitlines():
        if line.strip():
            log("         %s" % line)


def stage(name):
    def deco(fn):
        def wrapper(*a, **kw):
            head(name)
            try:
                return fn(*a, **kw)
            except Exception:
                record(name, "FAIL",
                       "the stage itself raised:\n" + traceback.format_exc())
                return False
        return wrapper
    return deco


def run(cmd, cwd=None, timeout=5400, tail=60, env=None):
    """Run a subprocess, log its tail, return (returncode, output)."""
    log("  $ %s" % " ".join(cmd))
    try:
        proc = subprocess.run(cmd, cwd=cwd or HERE, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env)
    except Exception as exc:
        log("    could not run: %r" % (exc,))
        return 1, repr(exc)
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = out.splitlines()
    if len(lines) > tail:
        log("    ... %d earlier line(s) omitted ..." % (len(lines) - tail))
    for line in lines[-tail:]:
        log("    | %s" % line)
    log("    exit code: %s" % proc.returncode)
    return proc.returncode, out


def scratch(name):
    os.makedirs(WORK_DIR, exist_ok=True)
    return os.path.join(WORK_DIR, name)


def fresh_dir(name):
    d = scratch(name)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


# ── 01 environment ───────────────────────────────────────────────────────────

@stage("01  environment")
def stage_environment():
    log("  release gate version : %s" % GATE_VERSION)
    log("  target project       : dem2dged %s" % PROJECT_VERSION)
    log("  timestamp            : %s" % datetime.datetime.now().isoformat())
    log("  project folder       : %s" % HERE)
    log("  python               : %s" % sys.executable)
    log("  python version       : %s" % sys.version.replace("\n", " "))
    log("  platform             : %s" % platform.platform())
    log("  locale encoding      : %s"
        % __import__("locale").getpreferredencoding(False))
    log("  CONDA_DEFAULT_ENV    : %s" % os.environ.get("CONDA_DEFAULT_ENV",
                                                       "<unset>"))
    missing = []
    data = {}
    try:
        from osgeo import gdal
        log("  GDAL bindings        : %s" % gdal.__version__)
        data["gdal"] = gdal.__version__
    except Exception as exc:
        log("  GDAL bindings        : MISSING (%s)" % exc)
        missing.append("osgeo/GDAL")
    try:
        import numpy
        log("  numpy                : %s" % numpy.__version__)
        data["numpy"] = numpy.__version__
    except Exception as exc:
        log("  numpy                : MISSING (%s)" % exc)
        missing.append("numpy")
    try:
        import pytest
        log("  pytest               : %s" % pytest.__version__)
        data["pytest"] = pytest.__version__
    except Exception:
        log("  pytest               : MISSING")
        missing.append("pytest  (conda install -c conda-forge pytest)")
    warp = shutil.which("gdalwarp")
    log("  gdalwarp             : %s" % (warp or "NOT ON PATH"))
    data["gdalwarp"] = warp
    if not warp:
        missing.append("gdalwarp on PATH")
    try:
        import tkinter  # noqa: F401
        log("  tkinter              : available")
    except Exception:
        log("  tkinter              : MISSING (the GUI stages will skip)")

    record("01  environment", "PASS" if not missing else "FAIL",
           "" if not missing else "missing: " + ", ".join(missing), data)
    return not missing


# ── 02 byte-compile ──────────────────────────────────────────────────────────

@stage("02  byte-compile every module")
def stage_compile():
    import py_compile
    bad = []
    n = 0
    # cfile=os.devnull looks like the obvious way to byte-compile without
    # littering the tree with .pyc files, but on Windows os.devnull is the
    # special device name "nul", and CPython's own bytecode writer refuses
    # to treat it as a normal output file -- every single compile raises
    # "nul is a non-regular file ..." before the source is even parsed, so
    # this would "fail" on syntax-perfect files 100% of the time on Windows.
    # A throwaway file in a real temp directory compiles the same source,
    # catches the same SyntaxError-class problems, and is a regular file on
    # every platform, so it never hits that quirk.
    with tempfile.TemporaryDirectory(prefix="dem2dged_gate_compile_") as tmpdir:
        cfile = os.path.join(tmpdir, "_gate.pyc")
        for root, dirs, files in os.walk(HERE):
            dirs[:] = [d for d in dirs
                       if d not in ("__pycache__", "build", "dist", "release_gate",
                                    "diagnostics", ".pytest_cache")
                       and not d.startswith("_backup")
                       and not d.startswith(".pytest_tmp")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(root, f)
                n += 1
                try:
                    py_compile.compile(path, doraise=True, cfile=cfile)
                except Exception as exc:
                    bad.append("%s: %s" % (os.path.relpath(path, HERE), exc))
    log("  compiled %d file(s)" % n)
    record("02  byte-compile every module", "PASS" if not bad else "FAIL",
           "\n".join(bad), {"files": n, "failures": bad})
    return not bad


# ── 03 audit_pure ────────────────────────────────────────────────────────────

@stage("03  audit_pure self-audit")
def stage_audit():
    script = os.path.join(HERE, "audit_pure.py")
    if not os.path.isfile(script):
        record("03  audit_pure self-audit", "SKIP", "audit_pure.py not present")
        return True
    rc, _out = run([sys.executable, script], tail=40)
    record("03  audit_pure self-audit", "PASS" if rc == 0 else "FAIL",
           "exit code %s" % rc)
    return rc == 0


# ── 04 pytest ────────────────────────────────────────────────────────────────

@stage("04  pytest suite")
def stage_pytest():
    try:
        import pytest  # noqa: F401
    except Exception:
        record("04  pytest suite", "FAIL",
               "pytest is not installed in this environment. "
               "conda install -c conda-forge pytest")
        return False
    rc, out = run([sys.executable, "-m", "pytest", "-q", "--no-header",
                   "-p", "no:cacheprovider"], tail=50)
    summary = ""
    for line in out.splitlines():
        low = line.lower()
        if ("passed" in low or "failed" in low or "error" in low) and "=" in line:
            summary = line.strip()
    record("04  pytest suite", "PASS" if rc == 0 else "FAIL",
           summary or "exit code %s" % rc, {"summary": summary})
    return rc == 0


# ── 05 regression harness ────────────────────────────────────────────────────

@stage("05  v0.55.0 regression harness")
def stage_diag():
    script = os.path.join(HERE, "DIAG_dem2dged_v%s.py" % PROJECT_VERSION)
    if not os.path.isfile(script):
        record("05  v0.55.0 regression harness", "SKIP",
               "%s not present" % os.path.basename(script))
        return True
    rc, out = run([sys.executable, script, "--skip-pytest"], tail=40)
    fails = [line.strip() for line in out.splitlines()
             if line.strip().startswith("[FAIL")]
    record("05  v0.55.0 regression harness", "PASS" if rc == 0 else "FAIL",
           ("every check passed -- no v0.55.0 defect has returned"
            if rc == 0 else
            "REGRESSION -- these checks failed:\n" + "\n".join(fails)),
           {"failed_checks": fails})
    return rc == 0


# ── shared: build a synthetic source ─────────────────────────────────────────

def _make_source(path, epsg, gt, nx, ny):
    import numpy as np
    from osgeo import gdal, osr
    yy, xx = np.mgrid[0:ny, 0:nx]
    vals = (200.0 + 40.0 * np.sin(xx / 11.0) + 25.0 * np.cos(yy / 8.0)
            + 0.05 * xx).astype("float32")
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference(); srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767.0)
    band.WriteArray(vals)
    ds.SetMetadataItem("AREA_OR_POINT", "Point")
    band.FlushCache(); ds.FlushCache(); ds = None
    return path


def _validate(folder, src):
    """Run the validator over a delivery, return (status, pass, warn, fail)."""
    import dem2dged_validate as dv
    rep, _tiles = dv.run_validation(folder, src=src)
    status = dv.overall_result(rep.n_pass, rep.n_warn, rep.n_fail)
    return status, rep.n_pass, rep.n_warn, rep.n_fail, rep


# ── 06 / 07 end-to-end ───────────────────────────────────────────────────────

def _end_to_end(label, module_name, argv, src, out_dir, expect_min_tiles):
    import importlib
    mod = importlib.import_module(module_name)
    log("  %s conversion via %s.main()" % (label, module_name))
    resamp = mod.main(argv)
    tifs = sorted(f for f in os.listdir(out_dir) if f.lower().endswith(".tif"))
    xmls = sorted(f for f in os.listdir(out_dir)
                  if f.lower().endswith(".xml")
                  and not f.upper().startswith("TABLE_OF_CONTENTS")
                  and not f.upper().endswith("_COLLECTION.XML"))
    log("  resampler used : %s" % resamp)
    log("  tiles          : %d  %s" % (len(tifs), tifs[:4]))
    log("  sidecars       : %d" % len(xmls))
    log("  TOC written    : %s"
        % os.path.isfile(os.path.join(out_dir, "TABLE_OF_CONTENTS.xml")))

    problems = []
    if len(tifs) < expect_min_tiles:
        problems.append("expected at least %d tile(s), got %d"
                        % (expect_min_tiles, len(tifs)))
    if len(tifs) != len(xmls):
        problems.append("%d tile(s) but %d sidecar(s)" % (len(tifs), len(xmls)))

    # every sidecar must be well-formed UTF-8 XML (findings A2 / A3)
    import xml.etree.ElementTree as ET
    for name in xmls:
        p = os.path.join(out_dir, name)
        try:
            raw = io.open(p, "rb").read()
            ET.fromstring(raw.decode("utf-8"))
        except Exception as exc:
            problems.append("%s: %s" % (name, exc))
    log("  sidecars parse as UTF-8 XML : %s"
        % ("yes" if not problems else "NO"))

    status, npass, nwarn, nfail, _rep = _validate(out_dir, src)
    log("  validator      : PASS=%d WARN=%d FAIL=%d -> %s"
        % (npass, nwarn, nfail, status))
    if nfail:
        problems.append("validator reported %d FAIL(s)" % nfail)

    return problems, {"tiles": len(tifs), "resampler": str(resamp),
                      "validator": status, "pass": npass, "warn": nwarn,
                      "fail": nfail}


@stage("06  end-to-end GEO conversion + validation")
def stage_geo():
    src = _make_source(scratch("geo_src.tif"), 4326,
                       (12.0, 1 / 240.0, 0.0, 56.0, 0.0, -1 / 240.0), 240, 240)
    out = fresh_dir("geo_out")
    problems, data = _end_to_end(
        "GEO", "dem2dged_geo",
        ["dem2dged_geo.py", src, out, "-product_level", "0",
         "-xml_template", os.path.join(HERE, "DGED_GEO_TEMPLATE.xml")],
        src, out, expect_min_tiles=1)
    record("06  end-to-end GEO conversion + validation",
           "PASS" if not problems else "FAIL", "\n".join(problems), data)
    return not problems


@stage("07  end-to-end UTM conversion + validation")
def stage_utm():
    src = _make_source(scratch("utm_src.tif"), 32632,
                       (500000.0, 10.0, 0.0, 6150000.0, 0.0, -10.0), 1200, 300)
    out = fresh_dir("utm_out")
    problems, data = _end_to_end(
        "UTM", "dem2dged_utm",
        ["dem2dged_utm.py", src, out, "-product_level", "5",
         "-utm_zone", "32N",
         "-xml_template", os.path.join(HERE, "DGED_UTM_TEMPLATE.xml")],
        src, out, expect_min_tiles=2)
    record("07  end-to-end UTM conversion + validation",
           "PASS" if not problems else "FAIL", "\n".join(problems), data)
    return not problems


# ── 08 pre-filter, CLI and GUI ───────────────────────────────────────────────

@stage("08  anti-alias pre-filter, CLI and GUI")
def stage_prefilter():
    import numpy as np
    from osgeo import gdal
    import dem2dged_geo as dgeo

    problems = []
    data = {}

    # A source much finer than the target, so there is real aliasing to
    # suppress and the sigma is non-zero.
    src = _make_source(scratch("pf_src.tif"), 4326,
                       (12.0, 1 / 3600.0, 0.0, 56.0, 0.0, -1 / 3600.0),
                       400, 400)

    plain = fresh_dir("pf_plain")
    smooth = fresh_dir("pf_smooth")
    tmpl = os.path.join(HERE, "DGED_GEO_TEMPLATE.xml")

    dgeo.main(["dem2dged_geo.py", src, plain, "-product_level", "0",
               "-xml_template", tmpl])
    dgeo.main(["dem2dged_geo.py", src, smooth, "-product_level", "0",
               "-prefilter", "gaussian", "-xml_template", tmpl])

    a_tifs = sorted(f for f in os.listdir(plain) if f.endswith(".tif"))
    b_tifs = sorted(f for f in os.listdir(smooth) if f.endswith(".tif"))
    log("  CLI plain tiles  : %s" % a_tifs)
    log("  CLI smooth tiles : %s" % b_tifs)
    if a_tifs != b_tifs:
        problems.append("pre-filter changed which tiles are produced")
    for name in set(a_tifs) & set(b_tifs):
        da = gdal.Open(os.path.join(plain, name)).ReadAsArray().astype("float64")
        db = gdal.Open(os.path.join(smooth, name)).ReadAsArray().astype("float64")
        diff = float(np.nanmax(np.abs(da - db)))
        log("  %s: max |plain - smoothed| = %.4f m" % (name, diff))
        data["cli_max_diff_m"] = diff
        if diff <= 0.0:
            problems.append("%s: the pre-filter changed nothing -- it is "
                            "not reaching the warp input" % name)

    # the lineage must say so, or a consumer cannot tell the two apart
    for name in os.listdir(smooth):
        if name.endswith(".xml") and not name.upper().startswith("TABLE"):
            txt = io.open(os.path.join(smooth, name), encoding="utf-8").read()
            if "pre-filter" not in txt.lower():
                problems.append("%s: lineage does not mention the pre-filter"
                                % name)
            break

    # GUI path (finding B1)
    try:
        import dem2dged_gui as gui
    except Exception as exc:
        log("  GUI not importable (%s) -- GUI half skipped" % exc)
        record("08  anti-alias pre-filter, CLI and GUI",
               "PASS" if not problems else "FAIL",
               "\n".join(problems) or "CLI half only (no tkinter)", data)
        return not problems

    import inspect
    for fn in (gui.convert_geo, gui.convert_utm):
        params = inspect.signature(fn).parameters
        if "prefilter" not in params:
            problems.append("gui.%s has no prefilter parameter" % fn.__name__)

    gui_out = fresh_dir("pf_gui")

    class _Never:
        def is_set(self):
            return False

    gui.convert_geo(src, gui_out, "0", "A", "U", "01",
                    log_fn=lambda m: None, progress_fn=lambda p: None,
                    stop_event=_Never(), prefilter="gaussian")
    g_tifs = sorted(f for f in os.listdir(gui_out) if f.endswith(".tif"))
    log("  GUI smooth tiles : %s" % g_tifs)
    if g_tifs != b_tifs:
        problems.append("GUI and CLI pre-filter runs produced different tiles")
    for name in set(g_tifs) & set(b_tifs):
        dg = gdal.Open(os.path.join(gui_out, name)).ReadAsArray().astype("float64")
        db = gdal.Open(os.path.join(smooth, name)).ReadAsArray().astype("float64")
        d = float(np.nanmax(np.abs(dg - db)))
        log("  %s: max |GUI - CLI| with pre-filter = %.6g m" % (name, d))
        data["gui_vs_cli_max_diff_m"] = d
        if d > 1e-6:
            problems.append("%s: GUI and CLI pre-filtered tiles differ by "
                            "%.6g m" % (name, d))

    record("08  anti-alias pre-filter, CLI and GUI",
           "PASS" if not problems else "FAIL", "\n".join(problems), data)
    return not problems


# ── 09 resume behaviour ──────────────────────────────────────────────────────

@stage("09  resume: existing tiles skipped, a deleted tile regenerated")
def stage_resume():
    import dem2dged_geo as dgeo

    problems = []
    src = _make_source(scratch("resume_src.tif"), 4326,
                       (12.0, 1 / 240.0, 0.0, 56.0, 0.0, -1 / 240.0), 240, 240)
    out = fresh_dir("resume_out")
    tmpl = os.path.join(HERE, "DGED_GEO_TEMPLATE.xml")
    argv = ["dem2dged_geo.py", src, out, "-product_level", "0",
            "-xml_template", tmpl]

    dgeo.main(argv)
    tifs = sorted(f for f in os.listdir(out) if f.endswith(".tif"))
    if not tifs:
        record("09  resume: existing tiles skipped, a deleted tile regenerated",
               "FAIL", "first run produced no tiles")
        return False
    victim = os.path.join(out, tifs[0])
    stamp_before = os.path.getmtime(victim)
    log("  first run tiles : %s" % tifs)

    # 1. an untouched re-run must not rewrite anything
    dgeo.main(argv)
    if os.path.getmtime(victim) != stamp_before:
        problems.append("a plain re-run rewrote an existing tile")
    log("  plain re-run left the tile alone : %s"
        % (os.path.getmtime(victim) == stamp_before))

    # 2. delete the .tif, leave the .xml -- finding B5. v0.55.0 saw the
    #    surviving sidecar and declared the tile "already done" forever.
    os.remove(victim)
    dgeo.main(argv)
    regenerated = os.path.isfile(victim)
    log("  deleted tile regenerated on re-run : %s" % regenerated)
    if not regenerated:
        problems.append("a deleted tile was NOT regenerated -- the resume "
                        "check is keying on the sidecar alone again (B5)")

    record("09  resume: existing tiles skipped, a deleted tile regenerated",
           "PASS" if not problems else "FAIL", "\n".join(problems),
           {"tiles": len(tifs)})
    return not problems


# ── 10 packaging ─────────────────────────────────────────────────────────────

@stage("10  packaging")
def stage_package():
    script = os.path.join(HERE, "dem2dged_package.py")
    if not os.path.isfile(script):
        record("10  packaging", "SKIP", "dem2dged_package.py not present")
        return True
    out_dir = fresh_dir("package_out")
    env = dict(os.environ)
    env["DEM2DGED_PACKAGE_OUTPUT_DIR"] = out_dir
    # PYTHONIOENCODING=ascii reproduces the legacy-console case the v0.44
    # safe_print() work exists for: a decorative glyph must not kill a
    # release build.
    env["PYTHONIOENCODING"] = "ascii"
    rc, _out = run([sys.executable, script], tail=30, env=env)
    zips = [f for f in os.listdir(out_dir) if f.endswith(".zip")]
    log("  archives written : %s" % zips)
    problems = []
    if rc != 0:
        problems.append("packaging exited %s" % rc)
    if not zips:
        problems.append("no .zip was produced")
    else:
        import zipfile
        z = zipfile.ZipFile(os.path.join(out_dir, zips[0]))
        names = z.namelist()
        log("  archive entries  : %d" % len(names))
        for needed in ("dem2dged_lib.py", "dem2dged_validate.py",
                       "DGED_GEO_TEMPLATE.xml"):
            if not any(n.endswith(needed) for n in names):
                problems.append("archive is missing %s" % needed)
        if not any("tests/" in n or "tests\\" in n for n in names):
            problems.append("archive is missing the tests/ directory "
                            "(this was the v0.42 blocker)")
        if not any(n.endswith("test_v056_regressions.py") for n in names):
            problems.append("archive is missing the v0.56 regression tests")
    record("10  packaging", "PASS" if not problems else "FAIL",
           "\n".join(problems), {"zips": zips})
    return not problems


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    global _LOG
    ap = argparse.ArgumentParser(
        description="Release gate for dem2dged v%s (gate v%s)."
                    % (PROJECT_VERSION, GATE_VERSION))
    ap.add_argument("--skip-pytest", action="store_true")
    ap.add_argument("--fast", action="store_true",
                    help="skip pytest and the regression harness")
    args = ap.parse_args()

    os.makedirs(GATE_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)
    _LOG = io.open(LOG_PATH, "w", encoding="utf-8", newline="\n")

    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    head("dem2dged RELEASE GATE  v%s   (project v%s)"
         % (GATE_VERSION, PROJECT_VERSION))
    log("  log  : %s" % LOG_PATH)
    log("  work : %s" % WORK_DIR)

    env_ok = stage_environment()
    stage_compile()
    stage_audit()
    if args.fast or args.skip_pytest:
        record("04  pytest suite", "SKIP", "--skip-pytest/--fast given")
    else:
        stage_pytest()
    if args.fast:
        record("05  v0.55.0 regression harness", "SKIP", "--fast given")
    else:
        stage_diag()

    if env_ok:
        stage_geo()
        stage_utm()
        stage_prefilter()
        stage_resume()
        stage_package()
    else:
        for name in ("06  end-to-end GEO conversion + validation",
                     "07  end-to-end UTM conversion + validation",
                     "08  anti-alias pre-filter, CLI and GUI",
                     "09  resume: existing tiles skipped, a deleted tile "
                     "regenerated",
                     "10  packaging"):
            STAGES.append({"stage": name, "status": "SKIP",
                           "detail": "environment incomplete", "data": {}})

    head("SUMMARY")
    counts = {}
    for s in STAGES:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
        log("  %-4s  %s" % (s["status"], s["stage"]))
    log("")
    log("  " + "  ".join("%s=%d" % (k, counts[k]) for k in sorted(counts)))

    blocking = counts.get("FAIL", 0)
    log("")
    if blocking:
        log("  RESULT: NOT READY TO RELEASE -- %d stage(s) failed." % blocking)
    elif counts.get("SKIP"):
        log("  RESULT: no failures, but %d stage(s) were skipped. Install "
            "what is missing and re-run before releasing."
            % counts.get("SKIP"))
    else:
        log("  RESULT: every stage passed. Ready to release v%s."
            % PROJECT_VERSION)
    log("")
    log("  Log  : %s" % LOG_PATH)
    log("  JSON : %s" % JSON_PATH)

    with io.open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump({"gate_version": GATE_VERSION,
                   "project_version": PROJECT_VERSION,
                   "timestamp": datetime.datetime.now().isoformat(),
                   "python": sys.version, "platform": platform.platform(),
                   "counts": counts, "stages": STAGES},
                  f, indent=2, ensure_ascii=False)

    _LOG.close()
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
