# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.50
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

r"""Release gate for dem2dged v0.50 -- run this locally, return the logs.

WHY THIS EXISTS
---------------
Everything in this script that does NOT need GDAL has already been run and
passes. What cannot be verified without a real GDAL is the other half: the
actual gdalwarp calls, the geoid transforms, the tile geometry on disk, and
the validator running against tiles it did not fabricate. This script
exercises that half and writes a detailed log for every step, so the result
can be reviewed without anyone having to guess.

HOW TO RUN IT  (Anaconda Prompt -- not PowerShell, not cmd, not base)
---------------------------------------------------------------------
    conda activate DGED
    cd /d C:\Users\xaxis\Documents\ES_Project\dem2dged_v0.50
    python RELEASE_CHECK_v0.50.py

Add --skip-exe to skip the two PyInstaller builds (step 12), which take
several minutes each. Do that while iterating; never for a release that
ships executables.

If the DGED environment does not exist yet, create a DEDICATED one first --
never install GDAL into `base`, it is the most reliable way to produce
dependency conflicts that are then very hard to unpick:

    conda create -n DGED python=3.11 -c conda-forge
    conda activate DGED
    conda install -c conda-forge gdal numpy pytest pyflakes pyinstaller

Everything lands in _release_check_logs\ :

    00_environment.txt      python / GDAL / PROJ / package versions
    00b_gdal_flags.txt      measured gdal/ogr/osr exception-flag behaviour
    01_compile.txt          byte-compilation of every module
    01b_pyflakes.txt        unused imports / undefined names, whole project
    01c_legacy_console.txt  every console script re-run under a NON-UTF-8
                            code page (ascii:strict), incl. the packagers
    02_audit_pure.txt       the GDAL-free self-audit
    03_pytest.txt           the full pytest suite, with the skip breakdown
    04_cli_help.txt         every CLI entry point's --help / --version
    04b_preflight.txt       the v0.46 guards, exercised through the real CLI
    05_geo_convert.txt      a real GEO conversion end to end
    06_geo_validate.txt     the validator against those real tiles
    07_utm_convert.txt      a real UTM conversion end to end
    08_utm_validate.txt     the validator against those real tiles
    08b_grid_convert.txt    a 2 x 2 level-0 tile grid (Int16, short-form
    08c_grid_validate.txt   names) so step 09b can measure a ROW seam too
    09_tile_inspection.txt  gdalinfo-level inspection of the tiles produced
    09b_edge_seams.txt      measured max |diff| on every shared tile edge
    10_run_verification.txt the 19-step harness (only if DEM\ has rasters)
    11_package_manifest.txt what the release zip would actually contain
    12_pyinstaller.txt      both .exe builds + a real run of the frozen
                            validator against the tiles from step 05/07
    SUMMARY.txt             one PASS/FAIL line per step  <-- send this first

WHAT COUNTS AS A PASS
---------------------
SUMMARY.txt ending in "ALL STEPS PASSED", with:

  * step 03 reporting 0 skipped -- a skip there means gdalwarp was not on
    PATH and no real conversion happened, which is not evidence of anything;
  * step 09b reporting BOTH row and column seams -- one of the two
    reconciliation passes running twice is not the same as both running;
  * step 12 either PASS (executables verified) or an explicit SKIP you
    intended.

The one WARN that is expected and cannot be automated away is 12b: the GUI
exe has no command line, so it has to be launched by hand once.

Send SUMMARY.txt first, plus any log whose line reads FAIL.
"""

import datetime
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "_release_check_logs")
SUMMARY = []

# v0.46: the two PyInstaller builds (step 12) take several minutes each.
# Skipping them is reasonable while iterating on the source and is NOT
# reasonable for a release that ships executables, so it is opt-OUT.
SKIP_EXE = "--skip-exe" in sys.argv


def stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(name, text):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, name)
    with open(path, "w", encoding="utf-8", errors="replace") as f:
        f.write(text if isinstance(text, str) else str(text))
    return path


def summ(status, step, detail=""):
    line = "%-6s %-28s %s" % (status, step, detail)
    SUMMARY.append(line)
    print(line)


def run(cmd, cwd=None, env=None, timeout=1800):
    """Run a command, capture everything, never raise."""
    try:
        p = subprocess.run(cmd, cwd=cwd or HERE, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    except Exception as e:                                # pragma: no cover
        return 999, "COULD NOT RUN %r: %s" % (cmd, e)


# ---------------------------------------------------------------------------
# 00 environment
# ---------------------------------------------------------------------------
def step_environment():
    lines = ["dem2dged release check  -  %s" % stamp(),
             "Project folder: %s" % HERE,
             "Executable:     %s" % sys.executable,
             "Python:         %s" % sys.version.replace("\n", " "),
             "CONDA_PREFIX:   %s" % os.environ.get("CONDA_PREFIX", "(not set)"),
             "CONDA_DEFAULT_ENV: %s"
             % os.environ.get("CONDA_DEFAULT_ENV", "(not set)"),
             "GDAL_DATA:      %s" % os.environ.get("GDAL_DATA", "(not set)"),
             "PROJ_LIB:       %s" % os.environ.get("PROJ_LIB", "(not set)"),
             ""]

    env_name = os.environ.get("CONDA_DEFAULT_ENV", "")
    if env_name == "base":
        lines.append("!! You are in the conda BASE environment. Everything "
                     "below may still work,")
        lines.append("!! but installing GDAL into base is how dependency "
                     "conflicts start. Use a")
        lines.append("!! dedicated environment (see this script's docstring).")
        lines.append("")

    ok = True
    try:
        from osgeo import gdal, osr
        lines.append("osgeo.gdal version: %s" % gdal.__version__)
        lines.append("gdal data dir:      %s" % gdal.GetConfigOption("GDAL_DATA"))
        try:
            lines.append("PROJ version:       %d.%d.%d"
                         % (osr.GetPROJVersionMajor(), osr.GetPROJVersionMinor(),
                            osr.GetPROJVersionMicro()))
        except Exception as e:
            lines.append("PROJ version:       (unavailable: %s)" % e)
    except Exception as e:
        ok = False
        lines.append("FATAL: cannot import osgeo -- %s" % e)
        # v0.46: this used to assert "You are almost certainly not in the
        # DGED environment", which was reported as wrong from a prompt that
        # said (DGED). Show what is actually running and let the reader see
        # for themselves.
        try:
            import dem2dged_env
            lines.append("")
            lines.append(dem2dged_env.missing_module_message(
                "osgeo", script=os.path.basename(__file__),
                install_hint="conda install -c conda-forge gdal"))
        except Exception:
            lines.append("Interpreter: %s" % sys.executable)
        lines.append("Use 'python RELEASE_CHECK_v0.50.py', not "
                     "'RELEASE_CHECK_v0.50.py'.")

    for mod in ("numpy", "pytest", "pyflakes", "PyInstaller"):
        try:
            m = __import__(mod)
            lines.append("%-12s %s" % (mod, getattr(m, "__version__", "?")))
        except Exception as e:
            lines.append("%-12s MISSING (%s)" % (mod, e))

    lines.append("")
    missing_exe = []
    for exe in ("gdalwarp", "gdalinfo", "gdal_translate", "gdal_edit.py"):
        path = shutil.which(exe)
        lines.append("%-16s %s" % (exe, path or "NOT ON PATH"))
        if exe in ("gdalwarp", "gdalinfo") and not path:
            missing_exe.append(exe)
    if missing_exe:
        ok = False
        lines.append("")
        lines.append("FATAL: %s not on PATH. dem2dged shells out to the GDAL "
                     "command-line tools" % ", ".join(missing_exe))
        lines.append("for every tile, so no conversion step below can run.")

    lines.append("")
    lines.append("-- conda list (filtered) --")
    # v0.46: on Windows `conda` is a .bat shim, so subprocess with
    # shell=False cannot execute it -- the v0.42 run logged
    # "(conda list unavailable: rc=999)" for that reason alone. Try the
    # documented forms in order rather than reporting a non-problem.
    rc, out = 999, ""
    for candidate in (["conda", "list"],
                      ["conda.bat", "list"],
                      [sys.executable, "-m", "conda", "list"]):
        rc, out = run(candidate, timeout=300)
        if rc == 0:
            lines.append("(via %s)" % " ".join(candidate))
            break
    if rc == 0:
        for l in out.splitlines():
            if any(k in l.lower() for k in ("gdal", "proj", "numpy", "python ",
                                            "libgdal", "pytest", "pyinstaller",
                                            "pyflakes")):
                lines.append(l)
    else:
        lines.append("(conda list unavailable: rc=%s)" % rc)

    log("00_environment.txt", "\n".join(lines))
    summ("PASS" if ok else "FAIL", "00 environment",
         "GDAL importable + CLI tools present" if ok
         else "environment incomplete -- read the log and stop here")
    return ok


# ---------------------------------------------------------------------------
# 00b GDAL exception-flag behaviour (measured, not assumed)
# ---------------------------------------------------------------------------
def step_gdal_flags():
    """Record what THIS GDAL build actually does with the exception flags.

    v0.41 discovered by measurement that gdal/ogr/osr share ONE global flag
    on GDAL 3.13.2 -- "gdal on, osr off" silently collapsed to "all off",
    and the first attempt at the fix looked correct while having reverted
    to the old behaviour. dem2dged_lib.py's whole error-handling contract
    depends on this, so it is measured per environment rather than trusted
    to a comment.
    """
    code = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "from osgeo import gdal, ogr, osr\n"
        "print('after import, before dem2dged_lib:')\n"
        "print('  gdal=%%s ogr=%%s osr=%%s' %% (gdal.GetUseExceptions(),"
        " ogr.GetUseExceptions(), osr.GetUseExceptions()))\n"
        "gdal.UseExceptions()\n"
        "print('after gdal.UseExceptions():')\n"
        "print('  gdal=%%s ogr=%%s osr=%%s' %% (gdal.GetUseExceptions(),"
        " ogr.GetUseExceptions(), osr.GetUseExceptions()))\n"
        "osr.DontUseExceptions()\n"
        "print('after osr.DontUseExceptions():')\n"
        "print('  gdal=%%s ogr=%%s osr=%%s' %% (gdal.GetUseExceptions(),"
        " ogr.GetUseExceptions(), osr.GetUseExceptions()))\n"
        "shared = gdal.GetUseExceptions() == 0\n"
        "print('SHARED_FLAG=%%s' %% shared)\n"
        "import dem2dged_lib as dl\n"
        "print('after importing dem2dged_lib (what the tool runs as):')\n"
        "print('  gdal=%%s ogr=%%s osr=%%s' %% (gdal.GetUseExceptions(),"
        " ogr.GetUseExceptions(), osr.GetUseExceptions()))\n"
        "print('gdal_open on a bad path ->', dl.gdal_open('does_not_exist.tif'))\n"
        "print('quick_raster_range on a bad path ->',"
        " dl.quick_raster_range('does_not_exist.tif'))\n"
        "print('clamp_tile_to_range on a bad path ->',"
        " dl.clamp_tile_to_range('does_not_exist.tif', 0.0, 1.0))\n"
    ) % HERE
    # -W error::FutureWarning turns GDAL's "neither UseExceptions nor
    # DontUseExceptions has been called" warning into a hard failure, which
    # is how v0.41 finding 10 was caught in the first place.
    rc, out = run([sys.executable, "-W", "error::FutureWarning", "-c", code])
    log("00b_gdal_flags.txt", out)
    ok = (rc == 0
          and "gdal_open on a bad path -> None" in out
          and "quick_raster_range on a bad path -> None" in out
          and "clamp_tile_to_range on a bad path -> 0" in out)
    shared = "SHARED_FLAG=True" in out
    summ("PASS" if ok else "FAIL", "00b GDAL flag behaviour",
         "shared flag=%s, degrade-to-None contract holds=%s" % (shared, ok))
    return ok


# ---------------------------------------------------------------------------
# 01 byte-compile
# ---------------------------------------------------------------------------
def step_compile():
    import py_compile

    lines, bad = [], []
    targets = sorted(glob.glob(os.path.join(HERE, "*.py"))
                     + glob.glob(os.path.join(HERE, "tests", "*.py"))
                     + glob.glob(os.path.join(HERE, "dem2dged_validate_v*",
                                              "*.py")))
    for f in targets:
        rel = os.path.relpath(f, HERE)
        try:
            py_compile.compile(f, doraise=True)
            lines.append("OK   %s" % rel)
        except Exception as e:
            bad.append(rel)
            lines.append("FAIL %s\n     %s" % (rel, e))
    lines.insert(0, "%d module(s) checked, %d failed\n" % (len(targets), len(bad)))
    log("01_compile.txt", "\n".join(lines))
    summ("PASS" if not bad else "FAIL", "01 byte-compile",
         "%d modules" % len(targets) if not bad else "broken: %s" % bad)
    return not bad


# ---------------------------------------------------------------------------
# 01b pyflakes
# ---------------------------------------------------------------------------
def step_pyflakes():
    """Unused imports and, more usefully, UNDEFINED NAMES -- the class of
    bug that only shows up on the error path a test never reaches."""
    targets = (sorted(glob.glob(os.path.join(HERE, "*.py")))
               + sorted(glob.glob(os.path.join(HERE, "tests", "*.py"))))
    rc, out = run([sys.executable, "-m", "pyflakes"] + targets)
    if rc == 999 or "No module named" in out:
        log("01b_pyflakes.txt",
            "SKIPPED -- pyflakes is not installed in this environment.\n"
            "  conda install -c conda-forge pyflakes\n\n" + out)
        summ("SKIP", "01b pyflakes", "pyflakes not installed")
        return True

    # "f-string is missing placeholders" is cosmetic and pre-existing; an
    # undefined name is not.
    real = [l for l in out.splitlines()
            if l.strip() and "f-string is missing placeholders" not in l]
    log("01b_pyflakes.txt",
        "%d line(s) after filtering out the cosmetic f-string notes\n"
        "(full output below)\n%s\n\n%s"
        % (len(real), "=" * 74, out))
    undefined = [l for l in real if "undefined name" in l]
    ok = not undefined
    summ("PASS" if ok else "FAIL", "01b pyflakes",
         "clean (%d cosmetic note(s))" % (len(out.splitlines()) - len(real))
         if ok else "%d undefined name(s)" % len(undefined))
    return ok


# ---------------------------------------------------------------------------
# 01c legacy console code page (v0.46)
# ---------------------------------------------------------------------------
def step_legacy_console():
    r"""Run every console-facing script under a NON-UTF-8 code page.

    This step exists because of a bug the v0.43 gate passed clean and the
    operator hit thirty seconds later, on a Korean Windows console:

        print(f"✓ Source directory verified ...")
        UnicodeEncodeError: 'cp949' codec can't encode character '✓'

    dem2dged_package.py printed decorative U+2713 / U+2717 / U+274C glyphs.
    They encode fine under UTF-8 and not at all under cp949, cp932, cp936 or
    plain ASCII -- a large share of the machines this tool actually runs on.
    Release packaging died on a tick mark.

    The gate could not have caught it: step 11 READ dem2dged_package.py's
    exclusion constants without ever executing the script, and every other
    step ran under the developer's own UTF-8-capable console. Both halves of
    that gap are closed here -- the scripts are executed, and they are
    executed under a code page that cannot represent the characters in
    question.

    PYTHONIOENCODING is what makes this reproducible on any machine: it
    forces the child's stdout codec regardless of the host's real console.
    "ascii" is deliberately stricter than cp949, so a pass here implies a
    pass on every national code page, not just the one that was reported.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "ascii:strict"

    checks = [
        ([sys.executable, "audit_pure.py"], "audit_pure.py"),
        ([sys.executable, "dem2dged.py", "--version"], "dem2dged --version"),
        ([sys.executable, "dem2dged.py", "--help"], "dem2dged --help"),
        ([sys.executable, "dem2dged_validate.py", "--version"],
         "dem2dged_validate --version"),
        ([sys.executable, "dem2dged_geo.py", "--help"], "dem2dged_geo --help"),
        ([sys.executable, "dem2dged_utm.py", "--help"], "dem2dged_utm --help"),
    ]

    blocks, bad = [], []
    for cmd, label in checks:
        rc, out = run(cmd, env=env, timeout=600)
        crashed = "UnicodeEncodeError" in out
        blocks.append("=" * 74 + "\n%s   (rc=%s, UnicodeEncodeError=%s)\n"
                      % (label, rc, crashed) + "=" * 74 + "\n" + out[-4000:])
        if crashed:
            bad.append("%s raised UnicodeEncodeError" % label)

    # The packaging scripts are the ones that actually broke, so they get
    # run for real -- into a throwaway output directory, so the gate never
    # leaves a half-built zip lying next to the project.
    tmp_out = tempfile.mkdtemp(prefix="dem2dged_pkgtest_")
    try:
        pkg_env = dict(env)
        pkg_env["DEM2DGED_PACKAGE_OUTPUT_DIR"] = tmp_out
        for script in ("dem2dged_package.py", "dem2dged_validate_package.py"):
            if not os.path.isfile(os.path.join(HERE, script)):
                continue
            rc, out = run([sys.executable, script], env=pkg_env, timeout=900)
            crashed = "UnicodeEncodeError" in out
            blocks.append("=" * 74
                          + "\n%s   (rc=%s, UnicodeEncodeError=%s)\n"
                          % (script, rc, crashed) + "=" * 74 + "\n"
                          + out[-6000:])
            if crashed:
                bad.append("%s raised UnicodeEncodeError" % script)
            elif rc != 0:
                bad.append("%s exited %s under an ASCII console" % (script, rc))
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)

    # Finally, prove safe_print() itself holds the line.
    probe = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "import dem2dged_lib as dl\n"
        "dl.safe_print('glyphs: \\u2713 \\u2717 \\u274c \\u2500 done')\n"
        "print('SAFE_PRINT_SURVIVED')\n"
    ) % HERE
    rc, out = run([sys.executable, "-c", probe], env=env, timeout=300)
    blocks.append("=" * 74 + "\ndem2dged_lib.safe_print() under ascii:strict"
                  "  (rc=%s)\n" % rc + "=" * 74 + "\n" + out)
    if "SAFE_PRINT_SURVIVED" not in out:
        bad.append("safe_print() did not survive an unencodable console")

    log("01c_legacy_console.txt", "\n".join(blocks))
    summ("PASS" if not bad else "FAIL", "01c legacy console",
         "%d script(s) clean under ascii:strict" % (len(checks) + 3)
         if not bad else "; ".join(bad))
    return not bad


# ---------------------------------------------------------------------------
# 02 audit_pure
# ---------------------------------------------------------------------------
def step_audit():
    rc, out = run([sys.executable, "audit_pure.py"])
    log("02_audit_pure.txt", out)
    ok = rc == 0 and "RESULT: 0 problem(s)" in out
    tail = [l for l in out.splitlines() if l.startswith("RESULT:")]
    summ("PASS" if ok else "FAIL", "02 audit_pure.py",
         tail[-1] if tail else "rc=%s" % rc)
    return ok


# ---------------------------------------------------------------------------
# 03 pytest
# ---------------------------------------------------------------------------
def step_pytest():
    """The full suite. A SKIP is reported explicitly, because the whole
    integration layer skips silently when gdalwarp is missing and "0 failed"
    would then look like success over nothing."""
    rc, out = run([sys.executable, "-m", "pytest", "-v", "--tb=short", "-ra"])
    log("03_pytest.txt", out)

    if "No module named pytest" in out:
        summ("FAIL", "03 pytest",
             "pytest not installed -- conda install -c conda-forge pytest")
        return False

    tail = ""
    for line in reversed(out.splitlines()):
        if re.search(r"\d+ (passed|failed|error)", line):
            tail = line.strip().strip("=").strip()
            break
    n_skip = 0
    m = re.search(r"(\d+) skipped", tail or "")
    if m:
        n_skip = int(m.group(1))

    ok = rc == 0
    detail = tail or "rc=%s" % rc
    if ok and n_skip:
        detail += "   <-- %d SKIPPED: the integration layer did not run" % n_skip
    summ("PASS" if ok else "FAIL", "03 pytest", detail)
    if ok and n_skip:
        summ("WARN", "03b integration coverage",
             "%d test(s) skipped -- gdalwarp missing? a skip is not a pass"
             % n_skip)
    return ok


# ---------------------------------------------------------------------------
# 04 CLI surface
# ---------------------------------------------------------------------------
def step_cli():
    blocks, bad = [], []
    checks = [
        ([sys.executable, "dem2dged.py", "--version"], "dem2dged --version"),
        ([sys.executable, "dem2dged.py", "--help"], "dem2dged --help"),
        ([sys.executable, "dem2dged_geo.py", "--help"], "dem2dged_geo --help"),
        ([sys.executable, "dem2dged_utm.py", "--help"], "dem2dged_utm --help"),
        ([sys.executable, "dem2dged_validate.py", "--version"],
         "dem2dged_validate --version"),
        ([sys.executable, "dem2dged_validate.py", "--help"],
         "dem2dged_validate --help"),
    ]
    for cmd, label in checks:
        rc, out = run(cmd)
        blocks.append("=" * 74 + "\n%s   (rc=%s)\n" % (label, rc) + "=" * 74
                      + "\n" + out)
        if rc != 0:
            bad.append(label)

    # Both --version lines must report the library's version, or the tool
    # is shipping a number that does not match what it is.
    import dem2dged_lib as dl
    for cmd, label in checks[:1] + checks[4:5]:
        rc, out = run(cmd)
        if dl.VERSION_DISPLAY not in out:
            bad.append("%s does not report v%s" % (label, dl.VERSION_DISPLAY))

    log("04_cli_help.txt", "\n".join(blocks))
    summ("PASS" if not bad else "FAIL", "04 CLI surface",
         "%d entry points, all report v%s" % (len(checks), dl.VERSION_DISPLAY)
         if not bad else "failed: %s" % bad)
    return not bad


# ---------------------------------------------------------------------------
# synthetic source DEMs (so this needs no operator data)
# ---------------------------------------------------------------------------
def _make_source(path, epsg, gt, w=400, h=300, tag_crs=True):
    import math
    import struct

    from osgeo import gdal, osr

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, w, h, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    if tag_crs:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        ds.SetProjection(srs.ExportToWkt())
    ds.SetMetadataItem("AREA_OR_POINT", "Point")
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767.0)
    for j in range(h):
        row = [100.0 + 0.60 * i + 0.35 * j + 12.0 * math.sin(i / 7.0)
               + 8.0 * math.cos(j / 5.0) for i in range(w)]
        band.WriteRaster(0, j, w, 1, struct.pack("<%df" % w, *row),
                         buf_type=gdal.GDT_Float32)
    band.FlushCache(); ds.FlushCache(); ds = None
    return path


# ---------------------------------------------------------------------------
# 04b v0.46 pre-flight guards, through the real CLI
# ---------------------------------------------------------------------------
def step_preflight(scratch):
    """Each of these used to be an ugly failure. Exercised end to end here
    rather than only in pytest, because what matters to an operator is what
    the CLI actually prints."""
    blocks, bad = [], []

    good = os.path.join(scratch, "preflight_source.tif")
    _make_source(good, 4326, (12.0, 1 / 3600.0, 0.0, 55.5, 0.0, -1 / 3600.0),
                 w=120, h=120)
    untagged = os.path.join(scratch, "preflight_untagged.tif")
    _make_source(untagged, 4326,
                 (12.0, 1 / 3600.0, 0.0, 55.5, 0.0, -1 / 3600.0),
                 w=120, h=120, tag_crs=False)

    cases = [
        # (label, argv, must-appear-in-output, must-be-non-zero-rc)
        ("unknown -resample value",
         [sys.executable, "dem2dged.py", good,
          os.path.join(scratch, "pf_bad_resample"),
          "--mode", "geo", "--level", "5", "--resample", "bilinier"],
         "unknown resampling method", True),
        ("source raster with no EPSG code",
         [sys.executable, "dem2dged.py", untagged,
          os.path.join(scratch, "pf_untagged"),
          "--mode", "geo", "--level", "5"],
         "EPSG", True),
        ("unknown product level",
         [sys.executable, "dem2dged.py", good,
          os.path.join(scratch, "pf_bad_level"),
          "--mode", "geo", "--level", "42"],
         "unknown GEO product level", True),
        ("invalid UTM zone",
         [sys.executable, "dem2dged.py", good,
          os.path.join(scratch, "pf_bad_zone"),
          "--mode", "utm", "--level", "5", "--zone", "99X"],
         "invalid UTM zone", True),
        ("input raster that does not exist",
         [sys.executable, "dem2dged.py",
          os.path.join(scratch, "nope.tif"),
          os.path.join(scratch, "pf_missing"),
          "--mode", "geo"],
         "not found", True),
    ]

    for label, cmd, needle, want_nonzero in cases:
        rc, out = run(cmd)
        out_dir = cmd[3]
        leftovers = sorted(glob.glob(os.path.join(out_dir, "*.tif")))
        good_rc = (rc != 0) if want_nonzero else (rc == 0)
        good_msg = needle.lower() in out.lower()
        clean = not leftovers
        blocks.append(
            "=" * 74 + "\n%s\n" % label + "=" * 74 +
            "\ncommand: %s\nreturncode: %s  (expected non-zero: %s)\n"
            "message contains %r: %s\noutput folder left empty: %s%s\n\n%s"
            % (" ".join(cmd), rc, want_nonzero, needle, good_msg, clean,
               "" if clean else "  -- LEFTOVERS: %s" % leftovers, out))
        if not (good_rc and good_msg and clean):
            bad.append(label)

    log("04b_preflight.txt", "\n".join(blocks))
    summ("PASS" if not bad else "FAIL", "04b pre-flight guards",
         "%d guard(s), all fail fast and leave nothing behind" % len(cases)
         if not bad else "not caught cleanly: %s" % bad)
    return not bad


# ---------------------------------------------------------------------------
# 05-08 real conversions + validation
# ---------------------------------------------------------------------------
def step_convert_and_validate(mode, scratch):
    """mode is 'geo' or 'utm'. Returns (ok, out_dir)."""
    src = os.path.join(scratch, "%s_source.tif" % mode)
    out = os.path.join(scratch, "%s_tiles" % mode)
    os.makedirs(out, exist_ok=True)

    if mode == "geo":
        # 400 x 300 posts at 1"/post spans two level-5 tiles in latitude, so
        # section G has an adjacent pair. 55.5 N also puts this in longitude
        # zone 2, whose x1.5 factor is the one that broke post alignment
        # before v0.27.
        _make_source(src, 4326, (12.0, 1 / 3600.0, 0.0, 55.5, 0.0, -1 / 3600.0))
        cmd = [sys.executable, "dem2dged.py", src, out,
               "--mode", "geo", "--level", "5", "--verbose"]
        n_convert, n_validate = "05_geo_convert.txt", "06_geo_validate.txt"
    else:
        # 1200 x 300 posts at 10 m = 12 km x 3 km. A level-5 UTM tile is
        # (5001-1) * 2 m = 10 km, so this deliberately spans TWO tiles in x
        # and exercises section G on the UTM side too -- the first v0.41 run
        # produced a single tile from a 4 km source and section G could only
        # warn "no adjacent pairs".
        _make_source(src, 32632, (500000.0, 10.0, 0.0, 6150000.0, 0.0, -10.0),
                     w=1200, h=300)
        cmd = [sys.executable, "dem2dged.py", src, out,
               "--mode", "utm", "--level", "5", "--zone", "32N", "--verbose"]
        n_convert, n_validate = "07_utm_convert.txt", "08_utm_validate.txt"

    rc, cout = run(cmd)
    tifs = sorted(glob.glob(os.path.join(out, "*.tif")))
    header = ["command: %s" % " ".join(cmd), "returncode: %s" % rc,
              "tiles produced: %d" % len(tifs), ""]
    log(n_convert, "\n".join(header) + cout)

    conv_ok = rc == 0 and len(tifs) > 0
    # v0.46: the converters now warn loudly on a partial run. Treat that as
    # a failure of the gate even though the command itself returned 0.
    partial = "failed to warp and are MISSING" in cout
    if partial:
        conv_ok = False
    summ("PASS" if conv_ok else "FAIL", "%s conversion" % n_convert[:2],
         "%s: %d tile(s)%s" % (mode.upper(), len(tifs),
                               "  -- PARTIAL RUN" if partial else ""))
    if not conv_ok:
        return False, out

    # The unified CLI auto-validates; ALSO run the standalone validator so
    # both paths are exercised and a full report lands on disk.
    rep_txt = os.path.join(out, "STANDALONE_report.txt")
    rep_html = os.path.join(out, "STANDALONE_report.html")
    vcmd = [sys.executable, "dem2dged_validate.py", out,
            "-src", src, "-report", rep_txt, "-html-report", rep_html,
            "--verbose"]
    vrc, vout = run(vcmd)
    auto_txt = os.path.join(out, "DGED_Validation_Report.txt")
    auto_html = os.path.join(out, "DGED_Validation_Report.html")
    extra = [
        "command: %s" % " ".join(vcmd),
        "returncode: %s   (0 = no FAIL, 1 = at least one FAIL)" % vrc,
        "auto-validation report written by dem2dged.py: txt=%s html=%s"
        % (os.path.isfile(auto_txt), os.path.isfile(auto_html)),
        "standalone report written: txt=%s html=%s"
        % (os.path.isfile(rep_txt), os.path.isfile(rep_html)),
        "",
    ]
    log(n_validate, "\n".join(extra) + vout)

    val_ok = (vrc == 0 and os.path.isfile(auto_txt) and os.path.isfile(auto_html)
              and os.path.isfile(rep_txt) and os.path.isfile(rep_html))
    result = [l for l in vout.splitlines() if l.startswith("RESULT:")]
    summ("PASS" if val_ok else "FAIL", "%s validation" % n_validate[:2],
         "%s: %s" % (mode.upper(), result[-1] if result else "rc=%s" % vrc))
    return val_ok, out


# ---------------------------------------------------------------------------
# 08b a 2 x 2 tile grid, so step 09b can measure BOTH seam kinds
# ---------------------------------------------------------------------------
def step_grid_conversion(scratch):
    """Produce a 2 x 2 GEO tile grid at level 0, and validate it.

    v0.46, and it exists because of a half-fix. The row-seam coverage hole
    the v0.42 gate found was closed in the PYTEST suite (a 2 x 2 fixture),
    but step 09b does not measure pytest's tiles -- it measures the tiles
    THIS script produced in steps 05 and 07, and both of those layouts are a
    single tile row. So 09b went on reporting "0 row + 2 column seam(s)"
    even after the suite itself was fixed. This conversion gives 09b tiles
    that are adjacent in both directions.

    Level 0 keeps it nearly free: 1-degree tiles at 30 arc-second posts are
    121 x 81 (the 81 is longitude zone 2's x1.5 factor at 55 N), against
    4001 x 6001 at level 5. Two useful side effects: level 0 is the Int16
    path, and levels 0-3 use the short filename form -- neither of which any
    other conversion in this gate exercises.

    Extent 12.1-13.9 E, 55.1-56.9 N => tile origins (55,12) (55,13)
    (56,12) (56,13).
    """
    src = os.path.join(scratch, "grid_source.tif")
    out = os.path.join(scratch, "grid_tiles")
    os.makedirs(out, exist_ok=True)
    _make_source(src, 4326, (12.1, 1 / 120.0, 0.0, 56.9, 0.0, -1 / 120.0),
                 w=216, h=216)

    cmd = [sys.executable, "dem2dged.py", src, out,
           "--mode", "geo", "--level", "0", "--verbose"]
    rc, cout = run(cmd)
    tifs = sorted(glob.glob(os.path.join(out, "*.tif")))
    log("08b_grid_convert.txt",
        "command: %s\nreturncode: %s\ntiles produced: %d  (expected 4)\n\n"
        % (" ".join(cmd), rc, len(tifs))
        + "\n".join("  " + os.path.basename(t) for t in tifs)
        + "\n\n" + cout)

    ok = rc == 0 and len(tifs) == 4
    summ("PASS" if ok else "FAIL", "08b 2x2 grid conversion",
         "level 0 Int16: %d tile(s)%s"
         % (len(tifs), "" if len(tifs) == 4 else "  -- expected 4"))
    if not ok:
        return False, out

    rep_txt = os.path.join(out, "GRID_report.txt")
    vcmd = [sys.executable, "dem2dged_validate.py", out,
            "-src", src, "-report", rep_txt, "--verbose"]
    vrc, vout = run(vcmd)
    log("08c_grid_validate.txt",
        "command: %s\nreturncode: %s\n\n" % (" ".join(vcmd), vrc) + vout)
    result = [l for l in vout.splitlines() if l.startswith("RESULT:")]
    val_ok = vrc == 0
    summ("PASS" if val_ok else "FAIL", "08c 2x2 grid validation",
         "level 0 / Int16 / short-form names: %s"
         % (result[-1] if result else "rc=%s" % vrc))
    return val_ok, out


# ---------------------------------------------------------------------------
# 09 tile inspection
# ---------------------------------------------------------------------------
def step_inspect(dirs):
    from osgeo import gdal

    import dem2dged_lib as dl

    lines, bad = [], []
    for d in dirs:
        for t in sorted(glob.glob(os.path.join(d, "*.tif"))):
            base = os.path.basename(t)
            ds = dl.gdal_open(t)
            if ds is None:
                bad.append(base)
                lines.append("FAIL  %s -- gdal.Open returned None" % base)
                continue
            band = ds.GetRasterBand(1)
            gt = ds.GetGeoTransform()
            dtype = gdal.GetDataTypeName(band.DataType)
            comp = ds.GetMetadataItem("COMPRESSION", "IMAGE_STRUCTURE")
            pred = ds.GetMetadataItem("PREDICTOR", "IMAGE_STRUCTURE")
            aop = ds.GetMetadataItem("AREA_OR_POINT")
            nod = band.GetNoDataValue()
            vmin, vmax, miss = dl.compute_tile_stats(t)
            wkt = ds.GetProjection() or ""
            lines.append(
                "%s\n"
                "   size      %d x %d\n"
                "   dtype     %s        expected for the level via "
                "dem2dged_lib.output_type_for_level()\n"
                "   nodata    %s        (spec: -32767)\n"
                "   AREA_OR_POINT %s    (spec: Point)\n"
                "   compress  %s  predictor=%s   (spec 13.1: LZW; v0.39: "
                "3 for Float32, 2 for Int16)\n"
                "   pixel     %.10g x %.10g\n"
                "   origin    %.10f , %.10f\n"
                "   range     %s .. %s m   (NoData-aware; %s%% missing)\n"
                "   EGM2008 tag present: %s"
                % (base, ds.RasterXSize, ds.RasterYSize, dtype, nod, aop,
                   comp, pred, gt[1], abs(gt[5]), gt[0], gt[3], vmin, vmax,
                   miss, ("3855" in wkt or "EGM2008" in wkt.upper())))
            if comp != "LZW":
                bad.append("%s: compression=%s" % (base, comp))
            if nod is None or abs(nod + 32767) > 0.5:
                bad.append("%s: nodata=%s" % (base, nod))
            if (aop or "").upper() != "POINT":
                bad.append("%s: AREA_OR_POINT=%s" % (base, aop))
            if dtype == "Float32" and pred not in (None, "3"):
                bad.append("%s: Float32 with PREDICTOR=%s (expected 3)"
                           % (base, pred))
            if dtype == "Int16" and pred not in (None, "2"):
                bad.append("%s: Int16 with PREDICTOR=%s (expected 2)"
                           % (base, pred))
            if miss >= 100.0:
                bad.append("%s: tile is entirely NoData (v0.34 regression?)"
                           % base)
            ds = None
    lines.insert(0, "dem2dged_lib.VERSION = %s\n" % dl.VERSION)
    if bad:
        lines.append("\n\nPROBLEMS\n" + "\n".join("  " + b for b in bad))
    log("09_tile_inspection.txt", "\n".join(lines))
    summ("PASS" if not bad else "FAIL", "09 tile inspection",
         "all tiles conform" if not bad else "%d problem(s)" % len(bad))
    return not bad


# ---------------------------------------------------------------------------
# 09b measured edge seams (v0.37 Finding 1)
# ---------------------------------------------------------------------------
def step_edges(dirs):
    """Measure the shared row/column between every adjacent pair directly,
    rather than reading the validator's own verdict on it. This is the check
    that caught a 1.6 m seam on the real DGIWG level-4b test set."""
    import numpy as np

    import dem2dged_lib as dl

    lines, bad = [], []
    n_pairs = n_rows = n_cols = 0
    for d in dirs:
        tiles = []
        for t in sorted(glob.glob(os.path.join(d, "*.tif"))):
            ds = dl.gdal_open(t)
            if ds is None:
                continue
            gt = ds.GetGeoTransform()
            tiles.append(dict(path=t, ds=ds, gt=gt,
                              nx=ds.RasterXSize, ny=ds.RasterYSize))
        lines.append("=" * 74)
        lines.append("%s  (%d tile(s))" % (d, len(tiles)))
        lines.append("=" * 74)

        for a in tiles:
            # tile directly EAST: a's right column == b's left column
            east_x = round(a["gt"][0] + a["gt"][1] * (a["nx"] - 1), 6)
            for b in tiles:
                if (round(b["gt"][0], 6) != east_x
                        or round(b["gt"][3], 6) != round(a["gt"][3], 6)):
                    continue
                col_a = a["ds"].GetRasterBand(1).ReadAsArray(
                    a["nx"] - 1, 0, 1, a["ny"]).astype("float64")
                col_b = b["ds"].GetRasterBand(1).ReadAsArray(
                    0, 0, 1, b["ny"]).astype("float64")
                diff = float(np.max(np.abs(col_a - col_b)))
                n_pairs += 1
                n_cols += 1
                lines.append("  column seam  %s | %s   max|diff| = %.6f m"
                             % (os.path.basename(a["path"]),
                                os.path.basename(b["path"]), diff))
                if diff != 0.0:
                    bad.append("column seam %s|%s = %s m"
                               % (os.path.basename(a["path"]),
                                  os.path.basename(b["path"]), diff))

            # tile directly SOUTH: a's bottom row == b's top row
            south_y = round(a["gt"][3] + a["gt"][5] * (a["ny"] - 1), 6)
            for b in tiles:
                if (round(b["gt"][3], 6) != south_y
                        or round(b["gt"][0], 6) != round(a["gt"][0], 6)):
                    continue
                row_a = a["ds"].GetRasterBand(1).ReadAsArray(
                    0, a["ny"] - 1, a["nx"], 1).astype("float64")
                row_b = b["ds"].GetRasterBand(1).ReadAsArray(
                    0, 0, b["nx"], 1).astype("float64")
                diff = float(np.max(np.abs(row_a - row_b)))
                n_pairs += 1
                n_rows += 1
                lines.append("  row seam     %s | %s   max|diff| = %.6f m"
                             % (os.path.basename(a["path"]),
                                os.path.basename(b["path"]), diff))
                if diff != 0.0:
                    bad.append("row seam %s|%s = %s m"
                               % (os.path.basename(a["path"]),
                                  os.path.basename(b["path"]), diff))
        for t in tiles:
            t["ds"] = None

    # v0.46: count the two seam KINDS separately. The v0.42 run measured two
    # column seams, zero row seams, and reported PASS -- while
    # reconcile_tile_edges()' pass 1 (row seams) had not executed at all.
    # "some seams were checked" is not the same claim as "both passes ran".
    lines.append("")
    lines.append("=" * 74)
    lines.append("row seams measured:    %d   (reconcile_tile_edges pass 1)"
                 % n_rows)
    lines.append("column seams measured: %d   (reconcile_tile_edges pass 2)"
                 % n_cols)
    if n_rows == 0 or n_cols == 0:
        lines.append("")
        lines.append("INCOMPLETE -- one of the two reconciliation passes was "
                     "never exercised by")
        lines.append("this run's tile layout. The 09 conversions must produce "
                     "tiles adjacent in")
        lines.append("BOTH directions for this step to mean anything.")
    log("09b_edge_seams.txt", "\n".join(lines))

    if n_pairs == 0:
        summ("FAIL", "09b edge seams",
             "no adjacent tile pair at all -- reconciliation unexercised")
        return False
    if bad:
        summ("FAIL", "09b edge seams", "%d seam(s) differ" % len(bad))
        return False
    if n_rows == 0 or n_cols == 0:
        summ("WARN", "09b edge seams",
             "%d row + %d column seam(s) -- only one of the two passes ran"
             % (n_rows, n_cols))
        return True
    summ("PASS", "09b edge seams",
         "%d row + %d column seam(s), every shared edge bit-identical"
         % (n_rows, n_cols))
    return True


# ---------------------------------------------------------------------------
# 10 full harness (only if the operator has DEMs in DEM\)
# ---------------------------------------------------------------------------
def step_harness():
    dem_dir = os.path.join(HERE, "DEM")
    rasters = (glob.glob(os.path.join(dem_dir, "**", "*.tif"), recursive=True)
               + glob.glob(os.path.join(dem_dir, "**", "*.tiff"), recursive=True))
    if not rasters:
        log("10_run_verification.txt",
            "SKIPPED -- no rasters found under %s\n\n"
            "Drop one or more real source DEMs there and re-run to exercise "
            "the full\n19-step harness against real terrain. That harness is "
            "the only thing that\ncovers the EGM96 -> EGM2008 vertical "
            "transform, which needs PROJ vertical\ngrids AND a source with a "
            "declared vertical datum -- neither of which a\nsynthetic fixture "
            "can provide.\n" % dem_dir)
        summ("SKIP", "10 run_verification", "no rasters under DEM\\")
        return True
    rc, out = run([sys.executable, "run_verification.py"], timeout=3600)
    log("10_run_verification.txt", out)
    ok = rc == 0
    tail = [l for l in out.splitlines() if "/" in l and "pass" in l.lower()]
    summ("PASS" if ok else "FAIL", "10 run_verification",
         tail[-1].strip() if tail else "rc=%s" % rc)
    return ok


# ---------------------------------------------------------------------------
# 10b v0.49 anti-alias pre-filter self-test
# ---------------------------------------------------------------------------
def step_selftests():
    """Run the two feature self-tests that need real GDAL.

    selftest_prefilter.py is new in v0.49 and is the ONLY check that
    exercises build_prefiltered_source() end to end against real GDAL --
    the NoData normalised-convolution path, the strip/halo blocking, and
    the measured error-vs-roughness table the documentation quotes. A
    release that ships the pre-filter without this passing is shipping an
    unverified feature.
    """
    ok = True
    for script, label in (("selftest_prefilter.py", "10b prefilter selftest"),
                          ("selftest_optimize_resampling.py",
                           "10c optimize selftest")):
        path = os.path.join(HERE, script)
        if not os.path.isfile(path):
            summ("FAIL", label, "%s is MISSING from the package" % script)
            ok = False
            continue
        rc, out = run([sys.executable, path], timeout=1800)
        log("10b_%s.txt" % script.replace(".py", ""), out)
        passed = rc == 0
        tail = [l for l in out.splitlines() if "SELFTEST:" in l]
        summ("PASS" if passed else "FAIL", label,
             tail[-1].strip() if tail else "rc=%s" % rc)
        ok = ok and passed
    return ok


# ---------------------------------------------------------------------------
# 11 what the release zip would contain
# ---------------------------------------------------------------------------
def step_package_manifest():
    """List what dem2dged_package.py would actually bundle, WITHOUT writing
    a zip. v0.41 shipped with a 311 KB stray .tmp inside the release
    archive because nobody looked at this list."""
    try:
        sys.path.insert(0, HERE)
        import dem2dged_package as pkg
    except Exception as e:
        log("11_package_manifest.txt", "could not import dem2dged_package: %s" % e)
        summ("FAIL", "11 package manifest", "import failed: %s" % e)
        return False

    included, skipped, total_bytes = [], [], 0
    exclude_dirs = set(getattr(pkg, "EXCLUDE_DIRS", ()))
    exclude_files = set(getattr(pkg, "EXCLUDE_FILES", ()))
    exclude_suffixes = tuple(getattr(pkg, "EXCLUDE_FILE_SUFFIXES", ()))

    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs
                   if d not in exclude_dirs
                   and not d.startswith("__pycache__")
                   and not d.startswith(".")
                   and not d.startswith("dem2dged_validate_v")
                   and d != "_release_check_logs"]
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(root, name), HERE)
            if name in exclude_files or name.endswith(exclude_suffixes):
                skipped.append(rel)
                continue
            size = os.path.getsize(os.path.join(root, name))
            total_bytes += size
            included.append("%9d  %s" % (size, rel))

    suspicious = [r for r in included
                  if r.strip().split("  ", 1)[-1].lower().endswith(
                      (".tmp", ".log", ".bak", ".zip", ".pyc"))]

    lines = ["dem2dged_package.py exclusion rules",
             "  EXCLUDE_FILE_SUFFIXES = %s" % (exclude_suffixes,),
             "",
             "WOULD BE INCLUDED (%d files, %.1f MB)"
             % (len(included), total_bytes / 1e6),
             "=" * 74] + included + [
             "",
             "EXCLUDED BY RULE (%d)" % len(skipped),
             "=" * 74] + ["  " + s for s in sorted(skipped)]
    if suspicious:
        lines += ["", "SUSPICIOUS ENTRIES", "=" * 74] + suspicious
    log("11_package_manifest.txt", "\n".join(lines))

    has_tests = any("tests" + os.sep in r for r in included)
    ok = not suspicious and has_tests
    detail = "%d files, %.1f MB" % (len(included), total_bytes / 1e6)
    if suspicious:
        detail += "  -- %d scratch file(s) would ship" % len(suspicious)
    if not has_tests:
        detail += "  -- tests/ MISSING from the package"
    summ("PASS" if ok else "FAIL", "11 package manifest", detail)
    return ok


# ---------------------------------------------------------------------------
# 12 PyInstaller builds + a real run of the frozen validator
# ---------------------------------------------------------------------------
def step_pyinstaller(dirs):
    """Build both executables and RUN the one that can be run.

    This is the last thing on the v0.42 "not verified" list. It matters more
    than it looks: a PyInstaller build can succeed and still produce an exe
    that dies at runtime, because the failure mode is missing DATA, not
    missing code -- the GDAL and PROJ data directories and the two DGED XML
    templates are bundled by the .spec files, and if that bundling is wrong
    the exe fails on its first real raster with something like
    "PROJ: proj_create_from_database: Cannot find proj.db". Building alone
    proves nothing about that; running the frozen validator against tiles
    produced earlier in this gate does.

    dem2dged.exe is built from dem2dged_gui.py, a Tkinter application with
    no command-line interface, so it CANNOT be smoke-tested headlessly --
    launching it would open a window and block until the timeout. It is
    built and measured here; launching it stays a manual step, and this
    step says so rather than implying coverage it does not have.
    """
    try:
        import PyInstaller
        pyi_version = getattr(PyInstaller, "__version__", "?")
    except ImportError:
        log("12_pyinstaller.txt",
            "SKIPPED -- PyInstaller is not installed in this environment.\n"
            "  conda install -c conda-forge pyinstaller\n\n"
            "Without this step, neither dem2dged.exe nor "
            "dem2dged_validate.exe has been\nbuilt or run, so an EXECUTABLE "
            "release is unverified. A SOURCE release is\nunaffected.\n")
        summ("SKIP", "12 PyInstaller", "PyInstaller not installed")
        return True

    import dem2dged_lib as dl

    blocks, bad = [], []
    dist = os.path.join(HERE, "dist")
    blocks.append("PyInstaller %s   python %s\n"
                  % (pyi_version, sys.version.split()[0]))

    for spec, exe_name in (("dem2dged_validate.spec", "dem2dged_validate"),
                           ("dem2dged.spec", "dem2dged")):
        exe_path = os.path.join(dist, exe_name + (".exe" if os.name == "nt"
                                                  else ""))
        if os.path.isfile(exe_path):
            os.remove(exe_path)

        rc, out = run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                       "--clean", spec], timeout=3600)
        built = os.path.isfile(exe_path)
        size_mb = os.path.getsize(exe_path) / 1e6 if built else 0.0
        blocks.append("=" * 74
                      + "\nBUILD %s -> %s   (rc=%s, built=%s, %.1f MB)\n"
                      % (spec, exe_name, rc, built, size_mb)
                      + "=" * 74 + "\n" + out[-8000:])
        if rc != 0 or not built:
            bad.append("%s did not build" % exe_name)
            continue
        # A onefile exe that bundles GDAL + PROJ data is tens of MB. A few
        # hundred KB means the payload did not make it in.
        if size_mb < 5.0:
            bad.append("%s is only %.1f MB -- the GDAL/PROJ payload is "
                       "probably missing" % (exe_name, size_mb))

    # -- the frozen validator, actually run --------------------------------
    val_exe = os.path.join(dist, "dem2dged_validate"
                           + (".exe" if os.name == "nt" else ""))
    if os.path.isfile(val_exe):
        rc, out = run([val_exe, "--version"], timeout=300)
        blocks.append("=" * 74 + "\ndem2dged_validate.exe --version  (rc=%s)\n"
                      % rc + "=" * 74 + "\n" + out)
        if rc != 0 or dl.VERSION_DISPLAY not in out:
            bad.append("the frozen validator does not report v%s"
                       % dl.VERSION_DISPLAY)

        if dirs:
            folder = dirs[0]
            rc, out = run([val_exe, folder, "--verbose"], timeout=900)
            result = [l for l in out.splitlines() if l.startswith("RESULT:")]
            blocks.append(
                "=" * 74
                + "\ndem2dged_validate.exe against real tiles  (rc=%s)\n"
                  "folder: %s\n" % (rc, folder)
                + "=" * 74 + "\n" + out[-8000:])
            if rc != 0 or not result or "PASS" not in result[-1]:
                bad.append("the frozen validator did not PASS on tiles the "
                           "source validator passed -- almost always a "
                           "bundling problem (GDAL/PROJ data), not a "
                           "validation problem")
        else:
            blocks.append("(no tile folder from step 05/07 to validate "
                          "against -- the frozen validator was only "
                          "version-checked)")
            bad.append("no real run of the frozen validator")
    else:
        bad.append("dem2dged_validate.exe was not produced")

    gui_exe = os.path.join(dist, "dem2dged" + (".exe" if os.name == "nt"
                                               else ""))
    blocks.append(
        "=" * 74 + "\nMANUAL STEP -- dem2dged.exe\n" + "=" * 74 + "\n"
        "dem2dged.exe is built from dem2dged_gui.py, a Tkinter application "
        "with no\ncommand-line interface, so it cannot be launched by this "
        "script without\nopening a window and blocking. It was built "
        "(%s, %s) and its size was\nchecked, which is as far as automation "
        "can honestly go.\n\n"
        "Launch it once by hand before releasing an executable build, and "
        "confirm:\n"
        "  1. the window opens and the console behind it shows no GDAL "
        "import error\n"
        "  2. a small conversion runs to completion\n"
        "  3. 'Validate after conversion' is ENABLED -- if it is greyed out, "
        "the\n"
        "     frozen build cannot import dem2dged_validate, which is exactly "
        "how the\n"
        "     v0.40 blocker presented itself\n"
        % (os.path.isfile(gui_exe),
           "%.1f MB" % (os.path.getsize(gui_exe) / 1e6)
           if os.path.isfile(gui_exe) else "n/a"))

    log("12_pyinstaller.txt", "\n".join(blocks))
    summ("PASS" if not bad else "FAIL", "12 PyInstaller",
         "both exes built; frozen validator runs clean on real tiles"
         if not bad else "; ".join(bad))
    if not bad:
        summ("WARN", "12b GUI exe smoke test",
             "dem2dged.exe built but NOT launched -- manual step, see the log")
    return not bad


# ---------------------------------------------------------------------------
def main():
    if os.path.isdir(LOG_DIR):
        shutil.rmtree(LOG_DIR, ignore_errors=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    sys.path.insert(0, HERE)

    print("=" * 74)
    print(" dem2dged v0.50 release check  -  %s" % stamp())
    print(" logs -> %s" % LOG_DIR)
    print("=" * 74)

    if not step_environment():
        _finish()
        return 2

    step_gdal_flags()
    step_compile()
    step_pyflakes()
    step_legacy_console()
    step_audit()
    step_pytest()
    step_cli()

    scratch = tempfile.mkdtemp(prefix="dem2dged_relcheck_")
    dirs = []
    try:
        step_preflight(scratch)
        for mode in ("geo", "utm"):
            ok, out = step_convert_and_validate(mode, scratch)
            if ok:
                dirs.append(out)
        # v0.46: the 2 x 2 grid, so step 09b below can measure a ROW seam.
        # Steps 05 and 07 both produce a single tile row, which is why 09b
        # reported "0 row + 2 column seam(s)" on the v0.46 gate run.
        grid_ok, grid_out = step_grid_conversion(scratch)
        if grid_ok:
            dirs.append(grid_out)
        if dirs:
            step_inspect(dirs)
            step_edges(dirs)
        else:
            summ("SKIP", "09 tile inspection", "no successful conversion")
            summ("SKIP", "09b edge seams", "no successful conversion")
        step_harness()
        step_selftests()
        step_package_manifest()
        # Must run INSIDE this try block: it validates the tiles from
        # step 05/07, which the finally clause below deletes.
        if SKIP_EXE:
            log("12_pyinstaller.txt",
                "SKIPPED -- --skip-exe was passed on the command line.\n\n"
                "The PyInstaller builds take several minutes each. Skipping "
                "them is fine\nwhile iterating on the source, and is NOT fine "
                "for a release that ships\nexecutables.\n")
            summ("SKIP", "12 PyInstaller", "--skip-exe requested")
        else:
            step_pyinstaller(dirs)
    finally:
        # Copy the reports out before the scratch dir disappears.
        keep = os.path.join(LOG_DIR, "reports")
        os.makedirs(keep, exist_ok=True)
        for d in dirs:
            for f in (glob.glob(os.path.join(d, "*report*"))
                      + glob.glob(os.path.join(d, "*Report*"))):
                try:
                    shutil.copy2(f, os.path.join(
                        keep, os.path.basename(d) + "__" + os.path.basename(f)))
                except Exception:
                    pass
        shutil.rmtree(scratch, ignore_errors=True)

    return _finish()


def _finish():
    n_fail = sum(1 for l in SUMMARY if l.startswith("FAIL"))
    n_warn = sum(1 for l in SUMMARY if l.startswith("WARN"))
    try:
        import dem2dged_lib as dl
        version = dl.VERSION
    except Exception:
        version = "?"
    header = ["dem2dged v%s release check  -  %s" % (version, stamp()),
              "Python: %s" % sys.version.split()[0],
              "=" * 74, ""]
    if n_fail:
        verdict = "%d step(s) FAILED -- NOT releasable" % n_fail
    elif n_warn:
        verdict = ("ALL STEPS PASSED, %d warning(s) -- read them before "
                   "releasing" % n_warn)
    else:
        verdict = "ALL STEPS PASSED"
    footer = ["", "=" * 74, verdict, "=" * 74]
    log("SUMMARY.txt", "\n".join(header + SUMMARY + footer))
    print("\n".join(footer))
    print("\nSend %s (and any log whose line says FAIL)."
          % os.path.join(LOG_DIR, "SUMMARY.txt"))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
