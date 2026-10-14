# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# DIAG_dem2dged_v0.56.0.py
# Diagnostic Script Version: 0.03
# Target project version: dem2dged 0.56.0
#
# CHANGELOG
#   0.03  Retargeted at v0.56.0, where every defect these checks were written
#         to DETECT has been fixed. The polarity is therefore inverted in
#         meaning, not in code: a FAIL here is now a REGRESSION, not a
#         discovery. CHECK 14 no longer merely warns about inspect_source()
#         reading whole rasters -- it asserts the streamed/cached fix.
#   0.02  CHECK 08 logged repr(UnicodeEncodeError), and that exception's repr
#         embeds THE ENTIRE STRING it failed to encode -- so one finding wrote
#         ~20 KB of XML template into the log and buried everything around it.
#         Now summarised as codec / position / offending character, with the
#         full object available only in the JSON. Added _short_exc() and used
#         it in CHECK 11 as well.
#   0.01  First cut: 16 checks, one per finding of the v0.55.0 review.
#
# ============================================================================
# WHAT THIS IS
# ============================================================================
# A read-only diagnostic harness for the dem2dged v0.55.0 project. It does
# NOT modify any project file. Everything it writes goes into a single
# subfolder:
#
#     <project folder>/diagnostics/
#         dem2dged_diag_<YYYYmmdd_HHMMSS>.log      full human-readable log
#         dem2dged_diag_<YYYYmmdd_HHMMSS>.json     machine-readable summary
#         scratch/                                  synthetic test rasters
#
# Each CHECK is independent and wrapped so that a failure in one never stops
# the others. Every check prints, and logs, exactly what it measured, so the
# log alone is enough to confirm or refute a finding without re-running.
#
# ============================================================================
# HOW TO RUN  (Anaconda Prompt -- NEVER the base environment)
# ============================================================================
#     (base) C:\> conda activate DGED
#     (DGED) C:\> cd C:\Users\Son\Documents\ChatGPT\dem2dged\dem2dged_v0.55.0
#     (DGED) C:\...\dem2dged_v0.55.0> python DIAG_dem2dged_v0.55.0.py
#
# IMPORTANT: type `python DIAG_dem2dged_v0.55.0.py`, NOT
# `DIAG_dem2dged_v0.55.0.py`. Typing the bare script name makes Windows use
# the .py file association, which is usually a DIFFERENT interpreter from the
# activated conda environment -- exactly the failure dem2dged_env.py exists to
# explain.
#
# If the DGED environment does not exist yet:
#     conda create -n DGED python=3.11 -c conda-forge
#     conda activate DGED
#     conda install -c conda-forge gdal numpy pytest
#
# Optional flags:
#     --skip-pytest     do not run the pytest suite (much faster)
#     --skip-gui        do not run the GUI-vs-CLI comparison (needs tkinter)
#     --quick           equivalent to --skip-pytest --skip-gui
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
import shutil
import subprocess
import sys
import traceback

DIAG_VERSION = "0.03"
TARGET_PROJECT_VERSION = "0.56.0"

HERE = os.path.dirname(os.path.abspath(__file__))
DIAG_DIR = os.path.join(HERE, "diagnostics")
SCRATCH_DIR = os.path.join(DIAG_DIR, "scratch")

_STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = os.path.join(DIAG_DIR, "dem2dged_diag_%s.log" % _STAMP)
JSON_PATH = os.path.join(DIAG_DIR, "dem2dged_diag_%s.json" % _STAMP)

RESULTS = []          # list of dicts, one per check
_LOG_HANDLE = None


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------

def log(msg=""):
    """Write one line to both the console and the log file, never raising.

    Uses the same defensive encoding strategy as dem2dged_lib.safe_print():
    a legacy console code page (cp949, cp932, cp1252, ...) must never turn a
    diagnostic message into a crash.
    """
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


def _short_exc(exc, limit=220):
    """A one-line, log-safe summary of an exception (v0.02).

    UnicodeEncodeError / UnicodeDecodeError carry the ENTIRE offending string
    in .object, and repr() prints all of it -- in v0.01 that dumped a 20 KB
    XML template into the middle of CHECK 08's finding. Report the codec, the
    byte/character position and the single character that actually failed;
    the caller can still put the full repr in the JSON payload if it wants.
    """
    if isinstance(exc, (UnicodeEncodeError, UnicodeDecodeError)):
        obj = exc.object
        try:
            piece = obj[exc.start:exc.end]
        except Exception:
            piece = "?"
        if isinstance(piece, bytes):
            shown = " ".join("%02X" % b for b in piece)
        else:
            shown = "".join("U+%04X (%s)" % (ord(c), c) for c in piece[:4])
        return ("%s: %s codec failed at position %d of %d -- %s (%s)"
                % (type(exc).__name__, exc.encoding, exc.start, len(obj),
                   shown, exc.reason))
    text = repr(exc)
    if len(text) > limit:
        text = text[:limit] + " ... [%d chars truncated]" % (len(text) - limit)
    return text


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
    log("  cwd                       : %s" % os.getcwd())
    log("  stdout encoding           : %s" % getattr(sys.stdout, "encoding", "?"))
    log("  filesystem encoding       : %s" % sys.getfilesystemencoding())
    log("  locale preferred encoding : %s" % __import__("locale").getpreferredencoding(False))
    log("  CONDA_DEFAULT_ENV         : %s" % os.environ.get("CONDA_DEFAULT_ENV", "<unset>"))
    log("  CONDA_PREFIX              : %s" % os.environ.get("CONDA_PREFIX", "<unset>"))
    log("  GDAL_DATA                 : %s" % os.environ.get("GDAL_DATA", "<unset>"))
    log("  PROJ_LIB                  : %s" % os.environ.get("PROJ_LIB", "<unset>"))
    log("  PROJ_DATA                 : %s" % os.environ.get("PROJ_DATA", "<unset>"))

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

    warp = shutil.which("gdalwarp")
    log("  gdalwarp on PATH          : %s" % (warp or "NOT FOUND"))
    data["gdalwarp"] = warp
    if not warp:
        ok = False

    try:
        import tkinter
        log("  tkinter                   : available")
        data["tkinter"] = True
    except Exception as e:
        log("  tkinter                   : NOT AVAILABLE (%s)" % e)
        data["tkinter"] = False

    record("CHECK 01 -- environment and interpreter",
           "PASS" if ok else "FAIL",
           "" if ok else "GDAL, numpy or gdalwarp is missing. Activate the "
                         "DGED environment and re-run; every raster check "
                         "below will be skipped or wrong without them.",
           data)
    return ok


# ---------------------------------------------------------------------------
# CHECK 02 -- import every module
# ---------------------------------------------------------------------------

@check("CHECK 02 -- every project module imports")
def check_imports():
    mods = ["dem2dged_lib", "dem2dged_geo", "dem2dged_utm", "dem2dged_terrain",
            "dem2dged_compliance", "dem2dged_compare", "dem2dged_validate",
            "dem2dged_env", "dem2dged_logging", "dem2dged_package",
            "dem2dged_validate_package"]
    failed = {}
    versions = {}
    exits = {}

    # NOTE: BaseException, not Exception, on purpose. dem2dged_validate.py
    # calls sys.exit() at MODULE SCOPE (lines ~278 and ~305) when osgeo or
    # dem2dged_lib cannot be imported. sys.exit() raises SystemExit, which
    # derives from BaseException and is therefore NOT caught by the
    # `except Exception` guards in dem2dged.py::_run_auto_validation() or in
    # dem2dged_gui.py's module header -- so the importing PROCESS dies
    # instead of degrading. See CHECK 02's verdict below.
    for m in mods:
        try:
            mod = __import__(m)
            v = getattr(mod, "VERSION", None)
            versions[m] = v
            log("  %-28s OK   (VERSION=%s)" % (m, v))
        except SystemExit as e:
            exits[m] = "SystemExit(%r)" % (e.code,)
            failed[m] = exits[m]
            log("  %-28s FAIL -- module-scope sys.exit(%r)" % (m, e.code))
        except Exception as e:
            failed[m] = repr(e)
            log("  %-28s FAIL (%s)" % (m, e))

    # dem2dged_gui imports tkinter at module level; try it separately.
    try:
        import dem2dged_gui  # noqa: F401
        log("  %-28s OK" % "dem2dged_gui")
    except SystemExit as e:
        exits["dem2dged_gui"] = "SystemExit(%r)" % (e.code,)
        failed["dem2dged_gui"] = exits["dem2dged_gui"]
        log("  %-28s FAIL -- module-scope sys.exit(%r)" % ("dem2dged_gui", e.code))
    except Exception as e:
        failed["dem2dged_gui"] = repr(e)
        log("  %-28s FAIL (%s)" % ("dem2dged_gui", e))

    if exits:
        log("")
        log("  MODULE-SCOPE sys.exit() DETECTED in: %s" % ", ".join(sorted(exits)))
        log("  This is a real defect independent of whether GDAL is present:")
        log("    * dem2dged.py::_run_auto_validation() guards the import with")
        log("      `except Exception`, which does NOT catch SystemExit, so a")
        log("      validator that cannot import kills the CLI process AFTER a")
        log("      successful conversion instead of logging the documented")
        log("      'auto-validation SKIPPED' warning.")
        log("    * dem2dged_gui.py's module header does the same thing to set")
        log("      _VALIDATE_AVAILABLE=False; a SystemExit there terminates the")
        log("      GUI at startup instead of just disabling the checkbox.")
        log("  Fix: replace the two module-scope sys.exit() calls in")
        log("  dem2dged_validate.py with `raise ImportError(...)`, and keep the")
        log("  sys.exit() inside main() where a CLI exit code is what is wanted.")

    detail = ""
    if failed:
        detail = json.dumps(failed, indent=2)
    if exits:
        detail = ("MODULE-SCOPE sys.exit() in %s -- see the log for why this "
                  "defeats every caller's `except Exception` guard.\n%s"
                  % (", ".join(sorted(exits)), detail))

    record("CHECK 02 -- every project module imports",
           "PASS" if not failed else "FAIL", detail,
           {"versions": versions, "failed": failed, "module_scope_exits": exits})
    return not failed


# ---------------------------------------------------------------------------
# CHECK 03 -- pytest suite
# ---------------------------------------------------------------------------

@check("CHECK 03 -- pytest suite")
def check_pytest(skip=False):
    if skip:
        record("CHECK 03 -- pytest suite", "SKIP", "--skip-pytest was given")
        return None
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p",
           "no:cacheprovider"]
    log("  running: %s" % " ".join(cmd))
    log("  (this takes a few minutes -- 380+ tests, many of them real warps)")
    try:
        proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=3600)
    except Exception as e:
        record("CHECK 03 -- pytest suite", "ERROR", "could not run pytest: %s" % e)
        return None

    out = (proc.stdout or "") + (proc.stderr or "")
    log("  --- pytest output (last 80 lines) ---")
    for line in out.splitlines()[-80:]:
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
# CHECK 04 -- audit_pure.py
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
# raster helpers used by the remaining checks
# ---------------------------------------------------------------------------

def _make_raster(path, gt, nx, ny, values=None, epsg=4326, dtype=None,
                 nodata=None, area_or_point=None):
    """Create a single-band GeoTIFF with a fully controlled geotransform."""
    import numpy as np
    from osgeo import gdal, osr

    if dtype is None:
        dtype = gdal.GDT_Float32
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, nx, ny, 1, dtype)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(int(epsg))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(float(nodata))
    if values is None:
        yy, xx = np.mgrid[0:ny, 0:nx]
        values = (100.0 + xx * 1.0 + yy * 3.0).astype("float32")
    band.WriteArray(np.asarray(values))
    if area_or_point is not None:
        ds.SetMetadataItem("AREA_OR_POINT", area_or_point)
    band.FlushCache()
    ds.FlushCache()
    ds = None
    return path


def _scratch(name):
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    return os.path.join(SCRATCH_DIR, name)


# ---------------------------------------------------------------------------
# CHECK 05 -- PixelIsPoint geotransform convention
# ---------------------------------------------------------------------------

@check("CHECK 05 -- AREA_OR_POINT=Point geotransform round trip")
def check_point_geotransform():
    """Does GDAL give back the geotransform we set on a point-registered TIFF?

    This is the premise of CHECK 06. GDAL normalises a PixelIsPoint GeoTIFF
    to the pixel-CORNER convention on read (it subtracts half a pixel from
    the stored tiepoint), and adds it back on write, so a set/get round trip
    should be exact. If that holds, then for a point-registered raster whose
    first POST is at X0, GetGeoTransform()[0] == X0 - xres/2, NOT X0.
    """
    from osgeo import gdal

    xres = 0.001
    first_post_x, first_post_y = 10.0, 50.0
    gt_set = (first_post_x - xres / 2.0, xres, 0.0,
              first_post_y + xres / 2.0, 0.0, -xres)
    p = _scratch("point_registered.tif")
    _make_raster(p, gt_set, 20, 20, area_or_point="Point")

    ds = gdal.Open(p)
    gt_get = ds.GetGeoTransform()
    aop = ds.GetMetadataItem("AREA_OR_POINT")
    ds = None

    log("  geotransform SET  : %s" % (gt_set,))
    log("  geotransform READ : %s" % (gt_get,))
    log("  AREA_OR_POINT     : %s" % aop)
    log("  first post X (intended) : %.9f" % first_post_x)
    log("  gt[0] read              : %.9f" % gt_get[0])
    log("  gt[0] + xres/2          : %.9f   <-- should equal the first post"
        % (gt_get[0] + xres / 2.0))

    round_trip_ok = all(abs(a - b) < 1e-12 for a, b in zip(gt_set, gt_get))
    corner_convention = abs((gt_get[0] + xres / 2.0) - first_post_x) < 1e-9

    if round_trip_ok and corner_convention:
        status, detail = "PASS", (
            "GDAL reports the CORNER-based geotransform for a point-"
            "registered raster, as expected. A source post therefore sits at "
            "gt[0] + (col + 0.5) * gt[1], NOT at gt[0] + col * gt[1].")
    else:
        status, detail = "WARN", (
            "round_trip_ok=%s corner_convention=%s -- the premise of CHECK 06 "
            "does not hold on this GDAL build; read CHECK 06's numbers "
            "directly instead of its verdict." % (round_trip_ok, corner_convention))

    record("CHECK 05 -- AREA_OR_POINT=Point geotransform round trip",
           status, detail,
           {"gt_set": list(gt_set), "gt_get": list(gt_get),
            "area_or_point": aop, "round_trip_ok": round_trip_ok,
            "corner_convention": corner_convention})
    return corner_convention


# ---------------------------------------------------------------------------
# CHECK 06 -- try_direct_copy_tile half-post alignment
# ---------------------------------------------------------------------------

@check("CHECK 06 -- try_direct_copy_tile() grid alignment")
def check_direct_copy():
    """Two cases, both diagnostic.

    CASE A -- a CORRECTLY point-registered source whose posts land exactly on
    the requested DGED posts. try_direct_copy_tile() should accept it. If it
    returns False, the fast path is unreachable for correct data.

    CASE B -- a source whose pixel CORNERS (not posts) land on the requested
    DGED posts, i.e. every post is half a cell away from where the tile wants
    it. try_direct_copy_tile() should REJECT it. If it accepts, the delivered
    tile is shifted by half a post.
    """
    import numpy as np
    from osgeo import gdal
    import dem2dged_lib as dl

    xres = 0.001
    nx = ny = 20
    first_x, first_y = 10.0, 50.0     # the DGED posts the tile asks for
    w = h = 5

    # deterministic values so a half-post shift is visible in the numbers
    yy, xx = np.mgrid[0:ny, 0:nx]
    vals = (1000.0 + xx * 1.0 + yy * 100.0).astype("float32")

    # ---- CASE A: posts exactly on the DGED grid ----------------------------
    gt_a = (first_x - xres / 2.0, xres, 0.0, first_y + xres / 2.0, 0.0, -xres)
    src_a = _scratch("direct_copy_case_a_src.tif")
    _make_raster(src_a, gt_a, nx, ny, values=vals, area_or_point="Point")
    dst_a = _scratch("direct_copy_case_a_dst.tif")
    if os.path.isfile(dst_a):
        os.remove(dst_a)
    ok_a = dl.try_direct_copy_tile(src_a, dst_a, first_x=first_x,
                                   first_y=first_y, width=w, height=h,
                                   xres=xres, yres=xres,
                                   dst_srs="EPSG:4326", out_type="Float32")
    log("  CASE A (source posts land exactly on the requested DGED posts)")
    log("    source gt[0]=%.9f  first source post X = %.9f"
        % (gt_a[0], gt_a[0] + xres / 2.0))
    log("    requested first post X = %.9f" % first_x)
    log("    try_direct_copy_tile() returned: %s" % ok_a)
    log("    EXPECTED: True (this is a genuine grid match)")

    val_a = None
    if ok_a and os.path.isfile(dst_a):
        d = gdal.Open(dst_a)
        val_a = float(d.GetRasterBand(1).ReadAsArray(0, 0, 1, 1)[0][0])
        d = None
        log("    copied first value = %.3f  (source post (0,0) value = %.3f)"
            % (val_a, float(vals[0][0])))

    # ---- CASE B: source posts are half a cell off the DGED grid ------------
    gt_b = (first_x, xres, 0.0, first_y, 0.0, -xres)
    src_b = _scratch("direct_copy_case_b_src.tif")
    _make_raster(src_b, gt_b, nx, ny, values=vals, area_or_point="Point")
    dst_b = _scratch("direct_copy_case_b_dst.tif")
    if os.path.isfile(dst_b):
        os.remove(dst_b)
    ok_b = dl.try_direct_copy_tile(src_b, dst_b, first_x=first_x,
                                   first_y=first_y, width=w, height=h,
                                   xres=xres, yres=xres,
                                   dst_srs="EPSG:4326", out_type="Float32")
    log("")
    log("  CASE B (source posts sit half a cell off the requested DGED posts)")
    log("    source gt[0]=%.9f  first source post X = %.9f"
        % (gt_b[0], gt_b[0] + xres / 2.0))
    log("    requested first post X = %.9f" % first_x)
    log("    try_direct_copy_tile() returned: %s" % ok_b)
    log("    EXPECTED: False (accepting this ships a half-post shift)")

    if ok_b and os.path.isfile(dst_b):
        d = gdal.Open(dst_b)
        gtd = d.GetGeoTransform()
        vb = float(d.GetRasterBand(1).ReadAsArray(0, 0, 1, 1)[0][0])
        d = None
        log("    written tile gt = %s" % (gtd,))
        log("    tile post (0,0) is labelled X=%.9f but carries the value "
            "of the source post at X=%.9f"
            % (gtd[0] + xres / 2.0, gt_b[0] + xres / 2.0))
        log("    value written = %.3f" % vb)

    # ---- verdict -----------------------------------------------------------
    if ok_a and not ok_b:
        status = "PASS"
        detail = "Direct-copy accepts a real grid match and rejects a half-cell offset."
    elif (not ok_a) and (not ok_b):
        status = "FAIL"
        detail = ("BUG CONFIRMED (dead fast path). try_direct_copy_tile() "
                  "rejects even a perfectly aligned point-registered source, "
                  "so the optimisation can never fire. Cause: the column/row "
                  "index is computed as (first_x - gt[0]) / gt[1], but gt[0] "
                  "is the pixel CORNER (see CHECK 05), so the comparison is "
                  "off by half a cell. It should be "
                  "(first_x - (gt[0] + gt[1]/2)) / gt[1], with the "
                  "verification comparing gt[0] + (col + 0.5) * gt[1].")
    elif ok_b:
        status = "FAIL"
        detail = ("BUG CONFIRMED (half-post shift). try_direct_copy_tile() "
                  "accepted a source whose posts are half a cell away from "
                  "the requested DGED posts, so the delivered tile carries "
                  "each value at the wrong location. Same root cause as "
                  "above: gt[0] is a pixel CORNER, not the first post.")
    else:
        status = "WARN"
        detail = "Unexpected combination; read the numbers above."

    record("CHECK 06 -- try_direct_copy_tile() grid alignment", status, detail,
           {"case_a_accepted": bool(ok_a), "case_b_accepted": bool(ok_b),
            "case_a_first_value": val_a,
            "source_post_00_value": float(vals[0][0])})
    return status == "PASS"


# ---------------------------------------------------------------------------
# CHECK 07 -- XML special characters in sidecar values
# ---------------------------------------------------------------------------

@check("CHECK 07 -- XML escaping of sidecar values")
def check_xml_escaping():
    """write_sidecar_file() substitutes values with a plain str.replace().

    If a value carries &, < or >, the resulting sidecar is not well-formed
    XML. -lineage and -org are free text, and the DEFAULT lineage embeds
    os.path.basename(input_raster) -- so a source file called "DEM_A&B.tif"
    is enough to trigger it with no unusual flags at all.
    """
    import xml.etree.ElementTree as ET
    import dem2dged_lib as dl

    tmpl_path = os.path.join(HERE, "DGED_GEO_TEMPLATE.xml")
    if not os.path.isfile(tmpl_path):
        record("CHECK 07 -- XML escaping of sidecar values", "SKIP",
               "DGED_GEO_TEMPLATE.xml not found")
        return None

    with open(tmpl_path, encoding="utf-8") as f:
        tmpl = f.read()

    hostile = "Derived from 'DEM_A&B <draft>' by dem2dged"
    repl = {
        "BASENAME": "DGEDL5GtD_5530N01212E_A_U_01", "LEVEL": "5",
        "GSD": "2.0", "DATE": "2026-08-26", "EPSG": "4326", "ORG": "R&D",
        "CLASS_WORD": "unclassified",
        "WEST": "12.0", "EAST": "12.1", "SOUTH": "55.5", "NORTH": "55.6",
        "MINZ": "0", "MAXZ": "100", "MISSRATE": "0.0",
        "ABS_HACC": "3.0", "ABS_VACC": "2.0",
        "ABS_HACC_BASIS": "goal", "ABS_VACC_BASIS": "goal",
        "LINEAGE": hostile, "DTYPE": "real",
    }
    out = _scratch("xml_escape_probe.xml")
    dl.write_sidecar_file(tmpl, out, repl)

    with open(out, encoding="utf-8", errors="replace") as f:
        txt = f.read()

    log("  lineage value written : %s" % hostile)
    log("  org value written     : %s" % repl["ORG"])
    try:
        ET.fromstring(txt)
        status = "PASS"
        detail = "Sidecar with &, < and > in its values still parses."
        log("  ET.fromstring() : OK")
    except ET.ParseError as e:
        status = "FAIL"
        detail = ("BUG CONFIRMED. write_sidecar_file() does not XML-escape "
                  "substituted values, so a source filename or -lineage/-org "
                  "text containing & < > produces a sidecar that is not "
                  "well-formed XML: %s\n"
                  "Note dem2dged_lib._xml_escape() already exists and is used "
                  "by write_toc_file() and write_collection_metadata(); "
                  "sidecar_replacements() is the one path that skips it."
                  % e)
        log("  ET.fromstring() : ParseError -- %s" % e)

    record("CHECK 07 -- XML escaping of sidecar values", status, detail,
           {"probe_file": out})
    return status == "PASS"


# ---------------------------------------------------------------------------
# CHECK 08 -- console/locale encoding of the XML writers
# ---------------------------------------------------------------------------

@check("CHECK 08 -- locale encoding of the sidecar / TOC / collection writers")
def check_encoding():
    """dem2dged_lib opens four text files with NO encoding= argument:

        read_sidecar_template()      open(template_fnam)
        write_sidecar_file()         open(fnam, "wt")
        write_toc_file()             open(toc_path, "wt")
        write_collection_metadata()  open(out_path, "wt")

    On Windows that means the ANSI code page (cp1252, cp949 on a Korean
    install, ...), while every file they write DECLARES encoding="UTF-8" and
    dem2dged_validate.py reads them back with encoding="utf-8". The GUI's own
    _load_template() already uses encoding='utf-8', so GUI and CLI disagree.
    """
    import dem2dged_lib as dl

    enc = __import__("locale").getpreferredencoding(False)
    log("  locale preferred encoding : %s" % enc)
    log("  sys.flags.utf8_mode       : %s" % getattr(sys.flags, "utf8_mode", "?"))

    nonascii_lineage = "Source: 서울 DEM / Montréal relevé"
    log("  probe lineage : %s" % nonascii_lineage)

    tmpl_path = os.path.join(HERE, "DGED_GEO_TEMPLATE.xml")
    if not os.path.isfile(tmpl_path):
        record("CHECK 08 -- locale encoding of the sidecar / TOC / collection writers",
               "SKIP", "DGED_GEO_TEMPLATE.xml not found")
        return None
    tmpl = dl.read_sidecar_template(tmpl_path)

    repl = {
        "BASENAME": "DGEDL5GtD_5530N01212E_A_U_01", "LEVEL": "5",
        "GSD": "2.0", "DATE": "2026-08-26", "EPSG": "4326", "ORG": "KOR",
        "CLASS_WORD": "unclassified",
        "WEST": "12.0", "EAST": "12.1", "SOUTH": "55.5", "NORTH": "55.6",
        "MINZ": "0", "MAXZ": "100", "MISSRATE": "0.0",
        "ABS_HACC": "3.0", "ABS_VACC": "2.0",
        "ABS_HACC_BASIS": "goal", "ABS_VACC_BASIS": "goal",
        "LINEAGE": nonascii_lineage, "DTYPE": "real",
    }
    out = _scratch("encoding_probe.xml")

    write_error = None
    write_error_full = None
    try:
        dl.write_sidecar_file(tmpl, out, repl)
    except UnicodeEncodeError as e:
        # v0.02: summarise. repr(UnicodeEncodeError) embeds the whole string
        # it could not encode -- here, the entire XML template.
        write_error = _short_exc(e)
        write_error_full = "%s at %d-%d: %s" % (e.encoding, e.start, e.end,
                                                e.reason)

    if write_error:
        record("CHECK 08 -- locale encoding of the sidecar / TOC / collection writers",
               "FAIL",
               "BUG CONFIRMED (write side). write_sidecar_file() raised "
               "UnicodeEncodeError on a non-ASCII lineage because it calls "
               "open(fnam, \"wt\") with no encoding=. On this console the "
               "conversion would ABORT MID-RUN, after tiles are already "
               "warped:\n  %s\n"
               "Fix: encoding=\"utf-8\" on all four open() calls in "
               "dem2dged_lib.py (lines ~1422, ~1435, ~1994, ~2131)."
               % write_error,
               {"locale_encoding": enc, "error": write_error,
                "error_detail": write_error_full})
        return False

    raw = open(out, "rb").read()
    log("  file written, %d bytes" % len(raw))

    read_error = None
    try:
        raw.decode("utf-8")
        log("  bytes decode as UTF-8 : OK")
    except UnicodeDecodeError as e:
        read_error = repr(e)
        log("  bytes decode as UTF-8 : FAILS -- %s" % e)

    if read_error:
        record("CHECK 08 -- locale encoding of the sidecar / TOC / collection writers",
               "FAIL",
               "BUG CONFIRMED (declared-vs-actual encoding mismatch). The "
               "sidecar declares <?xml ... encoding=\"UTF-8\"?> but was "
               "written in the locale code page (%s), so it is NOT valid "
               "UTF-8. dem2dged_validate.py opens it with encoding=\"utf-8\" "
               "and will raise UnicodeDecodeError -- which check_tile() does "
               "not catch (it only catches ET.ParseError), so the validator "
               "crashes rather than reporting a finding.\n%s\n"
               "Fix: encoding=\"utf-8\" on all four open() calls in "
               "dem2dged_lib.py (lines ~1422, ~1435, ~1994, ~2131)."
               % (enc, read_error),
               {"locale_encoding": enc, "error": read_error})
        return False

    record("CHECK 08 -- locale encoding of the sidecar / TOC / collection writers",
           "PASS",
           "This machine writes UTF-8 by default (locale encoding %s), so the "
           "missing encoding= arguments do not bite HERE. They still make the "
           "output locale-dependent: the same code on a cp949/cp1252 console, "
           "or under a different PYTHONUTF8 setting, produces a sidecar whose "
           "bytes contradict its own XML declaration. Worth fixing anyway."
           % enc,
           {"locale_encoding": enc})
    return True


# ---------------------------------------------------------------------------
# CHECK 09 -- NaN NoData handling
# ---------------------------------------------------------------------------

@check("CHECK 09 -- NaN NoData handling in compute_tile_stats()")
def check_nan_nodata():
    """compute_tile_stats() detects NoData with abs(arr - nodata) > 0.5.

    With nodata = NaN (common in Float32 DEMs) that comparison is False for
    every pixel, so the whole tile reads as NoData. And a NaN in the DATA
    reaches int(math.floor(nan)), which raises ValueError.
    """
    import numpy as np
    import dem2dged_lib as dl

    findings = []

    # -- case 1: NoData declared as NaN --------------------------------------
    vals = np.full((10, 10), 50.0, dtype="float32")
    vals[0, 0] = np.nan
    p1 = _scratch("nan_nodata.tif")
    _make_raster(p1, (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), 10, 10,
                 values=vals, nodata=float("nan"))
    try:
        r1 = dl.compute_tile_stats(p1)
        log("  NoData = NaN  -> compute_tile_stats() = %s" % (r1,))
        log("    EXPECTED roughly (50, 50, 1.0); 100%% missing means every "
            "valid post was discarded.")
        if r1 == (0, 0, 100.0):
            findings.append(
                "NoData=NaN: every valid post was treated as NoData "
                "(returned (0, 0, 100.0)). The sidecar MINZ/MAXZ would be "
                "0/0 and MISSRATE 100% for a perfectly good tile.")
    except Exception as e:
        log("  NoData = NaN  -> raised %r" % e)
        findings.append("NoData=NaN raised %r" % e)

    # -- case 2: NaN inside the data, NoData = -32767 ------------------------
    vals2 = np.full((10, 10), 50.0, dtype="float32")
    vals2[0, 0] = np.nan
    p2 = _scratch("nan_in_data.tif")
    _make_raster(p2, (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), 10, 10,
                 values=vals2, nodata=-32767.0)
    try:
        r2 = dl.compute_tile_stats(p2)
        log("  NaN in data   -> compute_tile_stats() = %s" % (r2,))
        if any(x != x for x in r2[:2]):
            findings.append("A NaN in the data propagated into MINZ/MAXZ.")
    except Exception as e:
        log("  NaN in data   -> raised %r" % e)
        findings.append(
            "A single NaN pixel in the data makes compute_tile_stats() raise "
            "%r. sidecar_replacements() calls it for every tile, so one NaN "
            "aborts the whole sidecar pass after all tiles are already "
            "warped." % e)

    if findings:
        record("CHECK 09 -- NaN NoData handling in compute_tile_stats()",
               "FAIL",
               "BUG CONFIRMED:\n- " + "\n- ".join(findings) +
               "\nFix: build the valid mask as "
               "np.isfinite(arr) & (nodata is None or ~np.isclose(arr, nodata, "
               "equal_nan=True)), and guard the floor/ceil against a "
               "non-finite result.",
               {"findings": findings})
        return False

    record("CHECK 09 -- NaN NoData handling in compute_tile_stats()", "PASS",
           "NaN NoData and NaN data are both handled.")
    return True


# ---------------------------------------------------------------------------
# CHECK 10 -- Gaussian kernel at sigma 0
# ---------------------------------------------------------------------------

@check("CHECK 10 -- _gaussian_kernel_1d() at sigma = 0")
def check_gaussian_zero():
    """gaussian_sigma_for_ratio() can legitimately return 0 (no downsampling,
    or an explicit -prefilter_sigma 0). Both converters guard with
    `if sigma_px > 0`, so this is currently unreachable from the CLI -- but
    build_prefiltered_source() is a public function with no guard of its own,
    and dividing by 2*sigma*sigma at sigma=0 produces a NaN kernel that would
    silently NaN out an entire source raster.
    """
    import numpy as np
    import dem2dged_lib as dl

    try:
        k = dl._gaussian_kernel_1d(0.0)
        arr = np.asarray(k)
        bad = bool(np.isnan(arr).any() or arr.sum() != arr.sum())
        log("  kernel at sigma=0 : len=%d sum=%s has_nan=%s"
            % (len(arr), arr.sum(), bool(np.isnan(arr).any())))
        if bad:
            record("CHECK 10 -- _gaussian_kernel_1d() at sigma = 0", "WARN",
                   "Latent bug. sigma=0 yields a NaN kernel instead of a "
                   "no-op. Unreachable from today's CLI (both converters "
                   "check `sigma_px > 0` first), but "
                   "build_prefiltered_source() is public and would NaN out a "
                   "whole raster. Add `if sigma <= 0: return np.array([1.0])` "
                   "at the top of _gaussian_kernel_1d(), or refuse sigma<=0 "
                   "in build_prefiltered_source().",
                   {"has_nan": True})
            return False
    except ZeroDivisionError as e:
        record("CHECK 10 -- _gaussian_kernel_1d() at sigma = 0", "WARN",
               "sigma=0 raises %r rather than degrading to a no-op kernel." % e)
        return False

    record("CHECK 10 -- _gaussian_kernel_1d() at sigma = 0", "PASS",
           "sigma=0 produces a usable kernel.")
    return True


# ---------------------------------------------------------------------------
# CHECK 11 -- pre-filter with NaN NoData
# ---------------------------------------------------------------------------

@check("CHECK 11 -- build_prefiltered_source() with NaN NoData")
def check_prefilter_nan():
    """The pre-filter builds its validity mask as (arr != nodata). With
    nodata = NaN that is True everywhere (NaN != NaN), so the NaN enters the
    convolution and spreads across the kernel radius."""
    import numpy as np
    from osgeo import gdal
    import dem2dged_lib as dl

    vals = np.full((40, 40), 100.0, dtype="float32")
    vals[20, 20] = np.nan
    src = _scratch("prefilter_nan_src.tif")
    _make_raster(src, (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), 40, 40,
                 values=vals, nodata=float("nan"))
    out = _scratch("prefilter_nan_out.tif")
    if os.path.isfile(out):
        os.remove(out)
    try:
        dl.build_prefiltered_source(src, 1.0, out_path=out, log_fn=log)
    except Exception as e:
        record("CHECK 11 -- build_prefiltered_source() with NaN NoData",
               "ERROR", "raised %r" % e)
        return False

    d = gdal.Open(out)
    a = d.GetRasterBand(1).ReadAsArray().astype("float64")
    d = None
    n_nan = int(np.isnan(a).sum())
    log("  source had 1 NaN post out of %d" % vals.size)
    log("  filtered output has %d NaN post(s)" % n_nan)

    if n_nan > 1:
        record("CHECK 11 -- build_prefiltered_source() with NaN NoData", "FAIL",
               "BUG CONFIRMED. One NaN post in the source became %d NaN posts "
               "in the pre-filtered raster -- the NaN spread across the whole "
               "kernel footprint. Cause: the validity mask is built as "
               "(arr != float(nodata)), which is True for every pixel when "
               "nodata is NaN, so the normalised-convolution guard never "
               "engages. Fix: valid = np.isfinite(arr) & (arr != nodata) when "
               "nodata is finite, np.isfinite(arr) when it is NaN."
               % n_nan,
               {"source_nan": 1, "output_nan": n_nan})
        return False

    record("CHECK 11 -- build_prefiltered_source() with NaN NoData", "PASS",
           "NaN NoData did not spread.", {"output_nan": n_nan})
    return True


# ---------------------------------------------------------------------------
# CHECK 12 -- corner-only reprojection of the source extent
# ---------------------------------------------------------------------------

@check("CHECK 12 -- get_bbox_of_output() edge densification")
def check_bbox_densify():
    """get_bbox_of_output() transforms only the FOUR CORNERS of the source
    extent. The image of a lat/lon rectangle in UTM is curved, so the true
    extent can lie outside the corner hull. GDAL's own SuggestedWarpOutput
    densifies each edge (21 points) for exactly this reason. Any shortfall
    means edge tiles that should exist are never generated.
    """
    from osgeo import ogr, osr
    import dem2dged_lib as dl

    # A wide, high-latitude geographic extent -- the worst realistic case.
    minlat, maxlat = 55.0, 60.0
    minlon, maxlon = 6.0, 12.0
    target_epsg = 32632          # UTM 32N
    ext = (maxlat, minlon, minlat, maxlon, "4326")   # as the lib builds it

    corner_box = dl.get_bbox_of_output(ext, target_epsg)   # minx maxx miny maxy

    src = osr.SpatialReference(); src.ImportFromEPSG(4326)
    dst = osr.SpatialReference(); dst.ImportFromEPSG(target_epsg)
    dl.set_authority_axis_order(src, dst)
    xf = osr.CoordinateTransformation(src, dst)

    N = 200
    xs, ys = [], []
    for i in range(N + 1):
        t = i / float(N)
        lat = minlat + t * (maxlat - minlat)
        lon = minlon + t * (maxlon - minlon)
        for (a, b) in ((lat, minlon), (lat, maxlon),
                       (minlat, lon), (maxlat, lon)):
            p = ogr.CreateGeometryFromWkt("POINT (%s %s)" % (a, b))
            p.Transform(xf)
            xs.append(p.GetX()); ys.append(p.GetY())
    dense_box = (min(xs), max(xs), min(ys), max(ys))

    log("  corner-only bbox (minx, maxx, miny, maxy):")
    log("    %s" % (tuple(round(v, 3) for v in corner_box),))
    log("  densified  bbox (%d points per edge):" % N)
    log("    %s" % (tuple(round(v, 3) for v in dense_box),))

    short_minx = corner_box[0] - dense_box[0]     # >0 means corner box misses west
    short_maxx = dense_box[1] - corner_box[1]
    short_miny = corner_box[2] - dense_box[2]
    short_maxy = dense_box[3] - corner_box[3]
    worst = max(short_minx, short_maxx, short_miny, short_maxy)

    log("  shortfall (metres of real data OUTSIDE the corner-only box):")
    log("    west  %.3f   east  %.3f   south %.3f   north %.3f"
        % (short_minx, short_maxx, short_miny, short_maxy))
    log("  worst shortfall: %.3f m" % worst)

    # translate into tiles at a few levels
    for lvl, gsd, posts in (("5", 2, 5001), ("6", 1, 5001), ("4", 4, 6251)):
        tiledim = (posts - 1) * gsd
        log("    level %-2s tile = %6d m  -> %.4f tile(s) of data lost"
            % (lvl, tiledim, worst / tiledim))

    if worst > 1.0:
        status = "FAIL"
        detail = ("BUG CONFIRMED. %.1f m of real source coverage falls "
                  "OUTSIDE the corner-only bounding box, so any tile that "
                  "would only be reached by that strip is never generated. "
                  "Fix: densify each edge (GDAL uses 21 points per edge in "
                  "SuggestedWarpOutput) before taking min/max, in BOTH "
                  "get_bbox_of_output() and bbox_to_wgs84() -- the latter "
                  "feeds the sidecar and collection bounding boxes."
                  % worst)
    elif worst > 0.0:
        status = "WARN"
        detail = ("Shortfall is only %.3f m for this extent, but it grows "
                  "with extent width and latitude. Densifying the edges "
                  "removes the class of error entirely." % worst)
    else:
        status = "PASS"
        detail = "Corner-only transform captured the full extent for this case."

    record("CHECK 12 -- get_bbox_of_output() edge densification", status, detail,
           {"corner_box": list(corner_box), "dense_box": list(dense_box),
            "worst_shortfall_m": worst})
    return status == "PASS"


# ---------------------------------------------------------------------------
# CHECK 13 -- Svalbard / Norway UTM auto-detect
# ---------------------------------------------------------------------------

@check("CHECK 13 -- autodetect_utm() special zones")
def check_svalbard():
    """Svalbard uses four wide zones: 31X (0-9E), 33X (9-21E), 35X (21-33E),
    37X (33-42E). dem2dged_utm.autodetect_utm() branches on -6 / 6 / 18
    instead of 0 / 9 / 21 / 33.

    The Norway branch (60-74N, 3-12E) is byte-for-byte identical to the
    generic else branch, so it applies no special handling at all -- and its
    warning goes through dl.dp(), which prints only under -verbose.
    """
    import inspect as _inspect
    import dem2dged_utm as du

    # Spec zone for each Svalbard longitude: 31X = 0-9E, 33X = 9-21E,
    # 35X = 21-33E, 37X = 33-42E.
    expected = {0.5: 31, 5.0: 31, 10.0: 33, 15.0: 33, 20.0: 33,
                22.0: 35, 30.0: 35, 35.0: 37, 40.0: 37}

    # autodetect_utm() takes the tuple get_extent_and_srs_of_input_raster()
    # returns for a geographic source: (maxlat, minlon, minlat, maxlon, epsg).
    # A degenerate point extent is enough to exercise the zone logic.
    lat = 78.0            # inside the 74-81N Svalbard band
    got = {}
    for lon in sorted(expected):
        try:
            _epsg, zone = du.autodetect_utm((lat, lon, lat, lon, "4326"))
            got[lon] = int(zone)
        except Exception as e:
            log("    lon %5.1fE  -> autodetect_utm raised %r" % (lon, e))
            got[lon] = None

    wrong = {lon: (got[lon], expected[lon]) for lon in expected
             if got[lon] != expected[lon]}

    log("  Svalbard band (lat 78N) -- autodetect_utm() zone per longitude:")
    for lon in sorted(expected):
        mark = ("  <-- WRONG (spec zone %dX)" % expected[lon]
                if got[lon] != expected[lon] else "")
        log("    lon %5.1fE  -> zone %s%s" % (lon, got[lon], mark))

    # The Norway branch: is it actually different from the generic branch?
    src = _inspect.getsource(du.autodetect_utm)
    norway_zone_lines = src.count("zone = math.floor((lon + 180) / 6) + 1")
    log("")
    log("  Norway branch (60-74N, 3-12E):")
    log("    'zone = math.floor((lon + 180) / 6) + 1' appears %d time(s) in "
        "autodetect_utm()" % norway_zone_lines)
    norway_probe = {}
    for lon in (3.5, 5.0, 8.0, 11.5):
        try:
            _e, z = du.autodetect_utm((65.0, lon, 65.0, lon, "4326"))
            norway_probe[lon] = int(z)
        except Exception:
            norway_probe[lon] = None
    log("    lon -> zone at lat 65N: %s" % norway_probe)
    log("    (32V should cover 3-12E at 56-64N and 32W 0-9E at 72-84N; the "
        "branch applies the generic formula, so no special zone is ever used)")

    if wrong:
        record("CHECK 13 -- autodetect_utm() special zones", "FAIL",
               "BUG CONFIRMED. The Svalbard thresholds (-6 / 6 / 18) do not "
               "match the spec zone boundaries (0 / 9 / 21 / 33), so %d of "
               "the %d probe longitudes resolve to the wrong zone: %s\n"
               "Separately: the Norway 32V/32W branch is identical to the "
               "generic branch, so it changes nothing, and its warning is "
               "emitted through dl.dp() -- invisible unless -verbose is set. "
               "Both warnings should use print()."
               % (len(wrong), len(expected), wrong),
               {"wrong": {str(k): v for k, v in wrong.items()},
                "norway_probe": {str(k): v for k, v in norway_probe.items()}})
        return False

    record("CHECK 13 -- autodetect_utm() special zones", "PASS", "")
    return True


# ---------------------------------------------------------------------------
# CHECK 14 -- inspect_source() memory behaviour
# ---------------------------------------------------------------------------

@check("CHECK 14 -- inspect_source() streams its statistics and caches")
def check_inspect_memory():
    """v0.55.0 called band.ReadAsArray() with no window and cast to float64 --
    4x an Int16 source in RAM for a min and a max -- and ran twice per CLI
    conversion. v0.56.0 uses GDAL's streamed ComputeRasterMinMax and caches
    on (path, mtime, size). Both properties are asserted here, plus the
    value range itself, because a faster wrong answer is not an improvement.
    """
    import time
    import numpy as np
    from osgeo import gdal
    import dem2dged_terrain as dt

    n = 2000
    vals = (np.arange(n * n, dtype="int16").reshape(n, n) % 3000)
    p = _scratch("inspect_probe.tif")
    _make_raster(p, (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), n, n,
                 values=vals, dtype=gdal.GDT_Int16, nodata=-32767.0)

    t0 = time.time()
    first = dt.inspect_source(p)
    t_first = time.time() - t0
    t1 = time.time()
    second = dt.inspect_source(p)
    t_second = time.time() - t1
    fresh = dt.inspect_source(p, use_cache=False)

    src = open(os.path.join(HERE, "dem2dged_terrain.py"),
               encoding="utf-8").read()
    streams = "ComputeRasterMinMax(False)" in src
    whole_read = "arr = band.ReadAsArray()" in src

    log("  probe raster          : %d x %d Int16 (%.1f MB on disk)"
        % (n, n, os.path.getsize(p) / 1e6))
    log("  first inspect         : %.3f s" % t_first)
    log("  second inspect        : %.4f s  (cache hit: %s)"
        % (t_second, second is first))
    log("  use_cache=False       : fresh object: %s" % (fresh is not first))
    log("  streamed min/max      : %s" % streams)
    log("  whole-raster read gone: %s" % (not whole_read))
    log("  valid_range           : %s" % (first.valid_range,))

    problems = []
    if second is not first:
        problems.append("the second inspect_source() call was not served "
                        "from the cache")
    if fresh is first:
        problems.append("use_cache=False still returned the cached object")
    if not streams:
        problems.append("ComputeRasterMinMax(False) is not used")
    if whole_read:
        problems.append("band.ReadAsArray() with no window is still present")
    if first.valid_range is None:
        problems.append("valid_range is None for a raster with valid data")

    record("CHECK 14 -- inspect_source() streams its statistics and caches",
           "PASS" if not problems else "FAIL",
           "" if not problems else "REGRESSION:\n- " + "\n- ".join(problems),
           {"seconds_first": t_first, "seconds_cached": t_second,
            "streams": streams, "whole_read_present": whole_read})
    return not problems


# ---------------------------------------------------------------------------
# CHECK 15 -- GUI vs CLI conversion equivalence
# ---------------------------------------------------------------------------

@check("CHECK 15 -- GUI convert_geo() vs CLI dem2dged_geo.main()")
def check_gui_vs_cli(skip=False):
    """The GUI does NOT call the CLI converters -- dem2dged_gui.convert_geo()
    / convert_utm() are a second, parallel implementation using the gdal.Warp
    Python API instead of the gdalwarp subprocess. Nothing in tests/ exercises
    them. This runs the same tiny level-0 job through both and compares.
    """
    if skip:
        record("CHECK 15 -- GUI convert_geo() vs CLI dem2dged_geo.main()",
               "SKIP", "--skip-gui was given")
        return None

    import numpy as np
    from osgeo import gdal

    try:
        import dem2dged_gui as gui
    except Exception as e:
        record("CHECK 15 -- GUI convert_geo() vs CLI dem2dged_geo.main()",
               "SKIP", "dem2dged_gui could not be imported (%s)" % e)
        return None
    import dem2dged_geo as dgeo

    # A small source covering one whole degree, coarse enough to stay fast.
    n = 240
    step = 1.0 / n
    yy, xx = np.mgrid[0:n, 0:n]
    vals = (200.0 + 40.0 * np.sin(xx / 12.0) + 25.0 * np.cos(yy / 9.0)
            ).astype("float32")
    src = _scratch("gui_vs_cli_src.tif")
    _make_raster(src, (12.0, step, 0.0, 56.0, 0.0, -step), n, n, values=vals)

    out_cli = _scratch("out_cli")
    out_gui = _scratch("out_gui")
    for d in (out_cli, out_gui):
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)

    log("  running CLI dem2dged_geo.main() at level 0 ...")
    cli_resamp = dgeo.main(["dem2dged_geo.py", src, out_cli,
                            "-product_level", "0",
                            "-xml_template",
                            os.path.join(HERE, "DGED_GEO_TEMPLATE.xml")])
    log("  CLI resampler: %s" % cli_resamp)

    log("  running GUI convert_geo() at level 0 ...")

    class _Ev:
        def is_set(self):
            return False

    gui_resamp = gui.convert_geo(src, out_gui, "0", "A", "U", "01",
                                 log_fn=lambda m: log("    gui| %s" % m),
                                 progress_fn=lambda p: None,
                                 stop_event=_Ev())
    log("  GUI resampler: %s" % gui_resamp)

    cli_tifs = sorted(f for f in os.listdir(out_cli) if f.lower().endswith(".tif"))
    gui_tifs = sorted(f for f in os.listdir(out_gui) if f.lower().endswith(".tif"))
    log("  CLI tiles: %s" % cli_tifs)
    log("  GUI tiles: %s" % gui_tifs)

    problems = []
    if cli_tifs != gui_tifs:
        problems.append("tile name sets differ: CLI=%s GUI=%s"
                        % (cli_tifs, gui_tifs))
    if str(cli_resamp) != str(gui_resamp):
        problems.append("resampler differs: CLI=%s GUI=%s"
                        % (cli_resamp, gui_resamp))

    for name in sorted(set(cli_tifs) & set(gui_tifs)):
        a = gdal.Open(os.path.join(out_cli, name))
        b = gdal.Open(os.path.join(out_gui, name))
        ga, gb = a.GetGeoTransform(), b.GetGeoTransform()
        da = a.GetRasterBand(1).ReadAsArray().astype("float64")
        db = b.GetRasterBand(1).ReadAsArray().astype("float64")
        ta = gdal.GetDataTypeName(a.GetRasterBand(1).DataType)
        tb = gdal.GetDataTypeName(b.GetRasterBand(1).DataType)
        pa = a.GetMetadataItem("AREA_OR_POINT")
        pb = b.GetMetadataItem("AREA_OR_POINT")
        a = b = None

        log("  --- %s ---" % name)
        log("    size   CLI=%s GUI=%s" % (da.shape, db.shape))
        log("    dtype  CLI=%s GUI=%s" % (ta, tb))
        log("    AOP    CLI=%s GUI=%s" % (pa, pb))
        log("    gt     CLI=%s" % (tuple(round(v, 10) for v in ga),))
        log("           GUI=%s" % (tuple(round(v, 10) for v in gb),))
        if da.shape != db.shape:
            problems.append("%s: raster size differs" % name)
            continue
        gt_max = max(abs(x - y) for x, y in zip(ga, gb))
        dmax = float(np.nanmax(np.abs(da - db)))
        n_diff = int((da != db).sum())
        log("    max |gt difference| : %.12g" % gt_max)
        log("    max |value diff|    : %.6g  over %d differing post(s) of %d"
            % (dmax, n_diff, da.size))
        if ta != tb:
            problems.append("%s: data type differs (%s vs %s)" % (name, ta, tb))
        if gt_max > 1e-9:
            problems.append("%s: geotransform differs by %.12g" % (name, gt_max))
        if dmax > 0.0:
            problems.append("%s: %d post(s) differ, max %.6g m"
                            % (name, n_diff, dmax))

    for extra in ("TABLE_OF_CONTENTS.xml",):
        ca = os.path.isfile(os.path.join(out_cli, extra))
        gb2 = os.path.isfile(os.path.join(out_gui, extra))
        log("  %s present: CLI=%s GUI=%s" % (extra, ca, gb2))
        if ca != gb2:
            problems.append("%s written by only one path" % extra)

    if problems:
        record("CHECK 15 -- GUI convert_geo() vs CLI dem2dged_geo.main()",
               "WARN",
               "The two conversion paths do not agree:\n- "
               + "\n- ".join(problems)
               + "\nThe GUI is a second implementation (gdal.Warp API) with "
                 "no test coverage. Known gaps vs the CLI: no -prefilter "
                 "support at all (the headline v0.49 feature), no "
                 "try_direct_copy_tile fast path, no per-tile failure "
                 "tolerance (a single failed warp raises RuntimeError and "
                 "aborts the whole file, so TOC and collection metadata are "
                 "never written), and no 'no tiles produced' hard error.",
               {"problems": problems})
        return False

    record("CHECK 15 -- GUI convert_geo() vs CLI dem2dged_geo.main()", "PASS",
           "Both paths produced identical tiles for this job. They remain two "
           "separate implementations: the GUI still has no -prefilter, no "
           "direct-copy path and no per-tile failure tolerance.")
    return True


# ---------------------------------------------------------------------------
# CHECK 16 -- reserved: static hygiene summary
# ---------------------------------------------------------------------------

@check("CHECK 16 -- static hygiene")
def check_static():
    """Re-checks the two cheap static facts so the log is self-contained."""
    import re
    findings = []

    lib = os.path.join(HERE, "dem2dged_lib.py")
    if os.path.isfile(lib):
        with open(lib, encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if re.match(r"^with open\(", s) and "encoding=" not in s \
                    and '"rb"' not in s and "'rb'" not in s \
                    and '"wb"' not in s and "'wb'" not in s:
                findings.append("dem2dged_lib.py:%d  %s" % (i, s))

    log("  text-mode open() calls in dem2dged_lib.py with no encoding=:")
    for f_ in findings:
        log("    %s" % f_)
    if not findings:
        log("    (none)")

    record("CHECK 16 -- static hygiene",
           "WARN" if findings else "PASS",
           ("%d text-mode open() call(s) in dem2dged_lib.py rely on the "
            "locale code page. See CHECK 08." % len(findings))
           if findings else "No locale-dependent text open() calls found.",
           {"open_without_encoding": findings})
    return not findings


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    global _LOG_HANDLE

    ap = argparse.ArgumentParser(
        description="dem2dged v%s diagnostic harness (script v%s)"
                    % (TARGET_PROJECT_VERSION, DIAG_VERSION))
    ap.add_argument("--skip-pytest", action="store_true",
                    help="do not run the pytest suite")
    ap.add_argument("--skip-gui", action="store_true",
                    help="do not run the GUI-vs-CLI comparison")
    ap.add_argument("--quick", action="store_true",
                    help="same as --skip-pytest --skip-gui")
    args = ap.parse_args()
    if args.quick:
        args.skip_pytest = True
        args.skip_gui = True

    os.makedirs(DIAG_DIR, exist_ok=True)
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    _LOG_HANDLE = io.open(LOG_PATH, "w", encoding="utf-8", newline="\n")

    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    hr("dem2dged DIAGNOSTIC HARNESS  (script v%s, target project v%s)"
       % (DIAG_VERSION, TARGET_PROJECT_VERSION))
    log("  log file  : %s" % LOG_PATH)
    log("  json file : %s" % JSON_PATH)

    env_ok = check_environment()
    check_imports()
    check_pytest(skip=args.skip_pytest)
    check_audit()

    if env_ok:
        check_point_geotransform()
        check_direct_copy()
        check_xml_escaping()
        check_encoding()
        check_nan_nodata()
        check_gaussian_zero()
        check_prefilter_nan()
        check_bbox_densify()
        check_svalbard()
        check_inspect_memory()
        check_gui_vs_cli(skip=args.skip_gui)
    else:
        log("")
        log("  Raster checks 05-15 were SKIPPED because GDAL/numpy/gdalwarp "
            "are not available in this interpreter.")
        for nm in ("CHECK 05", "CHECK 06", "CHECK 07", "CHECK 08", "CHECK 09",
                   "CHECK 10", "CHECK 11", "CHECK 12", "CHECK 13", "CHECK 14",
                   "CHECK 15"):
            RESULTS.append({"check": nm, "status": "SKIP",
                            "detail": "environment incomplete", "data": {}})

    check_static()

    # ---- summary -----------------------------------------------------------
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
