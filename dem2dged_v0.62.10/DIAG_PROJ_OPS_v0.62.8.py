#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.01  (which PROJ operation steps exist between CGVD2013 and EGM2008)
"""DIAG_PROJ_OPS_v0.62.8.py

WHY THIS EXISTS
---------------
DIAG_PROJ_VERTICAL showed that the strict CGVD2013 -> EGM2008 operation is not
available even though PROJ network access is ON, and that projinfo finds 0
candidate operations even with grid checking switched off. So the cause is not
a missing grid file: PROJ's database has no complete non-ballpark chain for this
pair. This script lists, step by step, what PROJ does know:

   A. the full pair as the converter asks for it
   B. CGVD2013 height -> NAD83(CSRS) 3D            (needs the CGG2013 grid)
   C. NAD83(CSRS) 3D  -> WGS 84 3D                 (the suspected gap)
   D. EGM2008 height  -> WGS 84 3D                 (needs the EGM2008 grid)
   E. NAD83(CSRS) 3D  -> ITRF2014 3D               (an alternative route)
   F. what a ballpark-allowed transform would do to a height (shown only to
      measure it; the converter never uses it)

HOW TO RUN (Anaconda Prompt, DGED environment, dem2dged_v0.62.8 folder):

    python DIAG_PROJ_OPS_v0.62.8.py

It needs no input file. It writes DIAG_PROJ_OPS_<timestamp>.log; send that file.
"""

import datetime
import os
import shutil
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
BBOX = "-75.75852,44.61225,-75.50413,44.79089"      # the Ontario 2 m tile
LON, LAT = -75.63113, 44.70164

_handle = None


def log(text=""):
    print(text, flush=True)
    if _handle:
        _handle.write(text + "\n")
        _handle.flush()


def section(title):
    log("")
    log("=" * 78)
    log(title)
    log("=" * 78)


def find_projinfo():
    exe = shutil.which("projinfo")
    if exe:
        return exe
    prefix = os.environ.get("CONDA_PREFIX") or os.path.dirname(sys.executable)
    for rel in (("Library", "bin", "projinfo.exe"), ("bin", "projinfo")):
        candidate = os.path.join(prefix, *rel)
        if os.path.isfile(candidate):
            return candidate
    return None


def projinfo(exe, source, target, extra, cap=45):
    cmd = [exe, "-s", source, "-t", target, "--bbox", BBOX, "--spatial-test", "intersects"] + extra
    log("$ " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        log("  projinfo failed to run: %s" % exc)
        return
    lines = ((proc.stdout or "") + (proc.stderr or "")).splitlines()
    for line in lines[:cap]:
        log("  | " + line[:700])
    if len(lines) > cap:
        log("  | ... (%d more lines)" % (len(lines) - cap))


def step_projinfo():
    exe = find_projinfo()
    if not exe:
        log("projinfo was not found; skipping the projinfo steps.")
        return
    log("projinfo: %s" % exe)
    steps = [
        ("A. converter pair (2D projected + height)", "EPSG:2959+6647", "EPSG:2959+3855"),
        ("A2. same pair, geographic 2D + height", "EPSG:4617+6647", "EPSG:4617+3855"),
        ("B. CGVD2013 height -> NAD83(CSRS) 3D", "EPSG:4617+6647", "EPSG:4955"),
        ("C. NAD83(CSRS) 3D -> WGS 84 3D", "EPSG:4955", "EPSG:4979"),
        ("D. EGM2008 height -> WGS 84 3D", "EPSG:4326+3855", "EPSG:4979"),
        ("E. NAD83(CSRS) 3D -> ITRF2014 3D", "EPSG:4955", "EPSG:7912"),
    ]
    for title, source, target in steps:
        section("projinfo " + title)
        log("-- all candidates (ballpark ones included), grid check off:")
        projinfo(exe, source, target, ["--summary", "--grid-check", "none"])
        log("-- candidates after removing ballpark ones, grid check off:")
        projinfo(exe, source, target, ["--summary", "--grid-check", "none", "--hide-ballpark"])


def step_python():
    section("F. PYTHON/OSR TESTS (point lon %.5f lat %.5f)" % (LON, LAT))
    from osgeo import gdal, osr
    gdal.UseExceptions()
    osr.UseExceptions()
    try:
        log("PROJ network enabled: %s   (PROJ_NETWORK env = %s)" %
            (bool(osr.GetPROJEnableNetwork()), os.environ.get("PROJ_NETWORK", "<unset>")))
    except Exception as exc:
        log("network flag unreadable: %s" % exc)

    def srs_of(text):
        srs = osr.SpatialReference()
        srs.SetFromUserInput(text)
        if hasattr(srs, "SetAxisMappingStrategy"):
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        return srs

    cases = [
        ("CGVD2013 -> EGM2008, geographic 2D, strict", "EPSG:4617+6647", "EPSG:4617+3855", False),
        ("CGVD2013 -> EGM2008, geographic 2D, ballpark allowed", "EPSG:4617+6647", "EPSG:4617+3855", True),
        ("CGVD2013 -> NAD83(CSRS) 3D, strict", "EPSG:4617+6647", "EPSG:4955", False),
        ("NAD83(CSRS) 3D -> WGS 84 3D, strict", "EPSG:4955", "EPSG:4979", False),
        ("EGM2008 -> WGS 84 3D, strict", "EPSG:4326+3855", "EPSG:4979", False),
        ("NAD83(CSRS) 3D -> ITRF2014 3D, strict", "EPSG:4955", "EPSG:7912", False),
    ]
    for label, source, target, ballpark in cases:
        log("")
        log("-- %s" % label)
        try:
            options = osr.CoordinateTransformationOptions()
            options.SetBallparkAllowed(bool(ballpark))
            options.SetOnlyBest(True)
            options.SetAreaOfInterest(LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
            transform = osr.CreateCoordinateTransformation(srs_of(source), srs_of(target), options)
            out = transform.TransformPoint(LON, LAT, 100.0)
            log("   PASS: lon %.7f lat %.7f z 100.000 -> z %.4f  (height change %+.4f m)" %
                (out[0], out[1], out[2], out[2] - 100.0))
        except Exception as exc:
            text = str(exc).replace("\n", " ")
            log("   FAIL: %s" % text[:400])


def main():
    global _handle
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(HERE, "DIAG_PROJ_OPS_%s.log" % stamp)
    _handle = open(path, "w", encoding="utf-8")
    log("DIAG_PROJ_OPS v0.01   log: %s" % path)
    log("python: %s" % sys.executable)
    log("PROJ_DATA=%s  PROJ_NETWORK=%s" % (os.environ.get("PROJ_DATA"), os.environ.get("PROJ_NETWORK")))
    try:
        step_projinfo()
        step_python()
    except Exception:
        log("UNEXPECTED ERROR:")
        log(traceback.format_exc())
        return 1
    finally:
        log("")
        log("Log file: %s" % path)
        _handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
