#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.01  (diagnoses "Vertical conversion preflight failed: Cannot find coordinate operations")
"""DIAG_PROJ_VERTICAL_v0.62.8.py

WHY THIS EXISTS
---------------
After the source vertical datum was declared (CGVD2013, EPSG:6647), the conversion
stopped with:

    Vertical conversion preflight failed: Cannot find coordinate operations from
    'NAD83(CSRS) / UTM zone 18N + CGVD2013(CGG2013) height' to ...

dem2dged asks PROJ for a NON-ballpark operation CGVD2013 -> EGM2008 (EPSG:3855)
and refuses to continue without one, because a ballpark operation would leave the
heights silently unchanged. PROJ can only build the real operation when the geoid
grid files are present (or when PROJ network access is on). This script measures
which of those is the case on THIS computer. It never guesses.

WHAT IT DOES
------------
 1. Prints versions, PROJ search paths and the PROJ network switch.
 2. Asks the PROJ command-line tool (projinfo, if installed) which grid files the
    operation needs, and checks whether each one is present in a search path.
 3. Repeats the exact strict test the converter runs (no ballpark, best only).
 4. Repeats it with PROJ network access switched on (downloads grid chunks from
    cdn.proj.org; needs the internet).
 5. With --fetch: downloads the missing grid files from cdn.proj.org into a
    folder next to this script, adds that folder to the search paths of THIS
    process and repeats the strict test.

HOW TO RUN (Anaconda Prompt, DGED environment, from the dem2dged_v0.62.8 folder;
run each command on its own line):

    python DIAG_PROJ_VERTICAL_v0.62.8.py --source "C:\\Users\\Son\\Downloads\\DEM\\High Res Ontario 2m\\dtm_2m_utm18_w_2_47.tif"

then, only if step 2 reports missing grids:

    python DIAG_PROJ_VERTICAL_v0.62.8.py --source "<same file>" --fetch

It writes DIAG_PROJ_VERTICAL_<timestamp>.log next to itself. Send that file.
"""

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import traceback
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CDN = "https://cdn.proj.org/"
FALLBACK_GRIDS = ["ca_nrc_CGG2013an83.tif", "ca_nrc_CGG2013ai83.tif", "us_nga_egm08_25.tif"]
KEYWORDS = ("cgg2013", "cgvd", "egm08", "egm2008", "ca_nrc", "us_nga")

_log_handle = None


def log(text=""):
    print(text, flush=True)
    if _log_handle:
        _log_handle.write(text + "\n")
        _log_handle.flush()


def section(title):
    log("")
    log("=" * 78)
    log(title)
    log("=" * 78)


def first_lines(text, count=4, width=240):
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    out = [ln[:width] for ln in lines[:count]]
    if len(lines) > count:
        out.append("... (%d more lines; full text is in the log file)" % (len(lines) - count))
    return out


def load_gdal():
    from osgeo import gdal, osr
    gdal.UseExceptions()
    osr.UseExceptions()
    return gdal, osr


# --------------------------------------------------------------------------
# step 1: environment
# --------------------------------------------------------------------------

def search_paths(osr):
    try:
        return list(osr.GetPROJSearchPaths())
    except Exception as exc:
        log("  could not read PROJ search paths: %s" % exc)
        return []


def step_environment(gdal, osr):
    section("1. ENVIRONMENT")
    log("python      : %s" % sys.version.replace("\n", " "))
    log("executable  : %s" % sys.executable)
    log("conda env   : %s" % os.environ.get("CONDA_DEFAULT_ENV"))
    log("GDAL        : %s" % gdal.VersionInfo("RELEASE_NAME"))
    try:
        log("PROJ        : %s" % osr.GetPROJVersion())
    except Exception as exc:
        log("PROJ        : (unknown: %s)" % exc)
    for name in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA", "PROJ_NETWORK",
                 "PROJ_USER_WRITABLE_DIRECTORY", "CONDA_PREFIX"):
        log("%-12s: %s" % (name, os.environ.get("%s" % name, "<unset>")))
    try:
        log("PROJ network enabled in this process: %s" % bool(osr.GetPROJEnableNetwork()))
    except Exception as exc:
        log("PROJ network switch not readable: %s" % exc)
    paths = search_paths(osr)
    log("PROJ search paths (%d):" % len(paths))
    for path in paths:
        has_db = os.path.isfile(os.path.join(path, "proj.db"))
        log("  %s  [exists=%s, proj.db=%s]" % (path, os.path.isdir(path), has_db))
    return paths


# --------------------------------------------------------------------------
# step 2: which grids are needed / present
# --------------------------------------------------------------------------

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


def run_projinfo(horizontal, bbox):
    exe = find_projinfo()
    if not exe:
        log("projinfo not found in PATH or the conda environment; using the usual grid names instead.")
        return []
    west, south, east, north = bbox
    base = [exe, "-s", "%s+6647" % horizontal, "-t", "%s+3855" % horizontal,
            "--bbox", "%.5f,%.5f,%.5f,%.5f" % (west, south, east, north),
            "--spatial-test", "intersects", "-o", "PROJ", "--single-line", "--hide-ballpark"]
    found = []
    for extra in (["--grid-check", "none"], []):
        cmd = base + extra
        log("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as exc:
            log("  projinfo failed to run: %s" % exc)
            continue
        output = (proc.stdout or "") + (proc.stderr or "")
        for line in output.splitlines():
            log("  | " + line[:600])
        for match in re.finditer(r"\+(?:geoid)?grids=([^\s+]+)", output):
            for name in match.group(1).split(","):
                name = name.lstrip("@").strip()
                if name and name not in found:
                    found.append(name)
        if found:
            break
    return found


def step_grids(osr, horizontal, bbox, paths):
    section("2. GRID FILES")
    required = run_projinfo(horizontal, bbox)
    if required:
        log("grids named by projinfo for this operation: %s" % ", ".join(required))
    else:
        required = list(FALLBACK_GRIDS)
        log("projinfo named no grids; checking the usual names: %s" % ", ".join(required))
    present = {}
    log("files in the search paths whose names look related:")
    shown = 0
    for path in paths:
        if not os.path.isdir(path):
            continue
        try:
            names = os.listdir(path)
        except OSError:
            continue
        lower = {n.lower(): n for n in names}
        for name in required:
            if name.lower() in lower and name not in present:
                present[name] = os.path.join(path, lower[name.lower()])
        for n in names:
            if any(k in n.lower() for k in KEYWORDS):
                size = os.path.getsize(os.path.join(path, n))
                log("  %s  (%.1f MB)  in %s" % (n, size / 1e6, path))
                shown += 1
    if not shown:
        log("  (none)")
    missing = [n for n in required if n not in present]
    for name in required:
        log("  %-28s %s" % (name, "PRESENT: " + present[name] if name in present else "MISSING"))
    return required, missing


# --------------------------------------------------------------------------
# step 3-5: the converter's strict test
# --------------------------------------------------------------------------

def strict_test(osr, horizontal, center_xy, label, source_vertical="6647", target_vertical="3855"):
    """Same call sequence as dem2dged_terrain.check_vertical_operation."""
    log("")
    log("-- %s" % label)
    try:
        source_srs = osr.SpatialReference()
        target_srs = osr.SpatialReference()
        source_srs.SetFromUserInput("%s+%s" % (horizontal, source_vertical))
        target_srs.SetFromUserInput("%s+%s" % (horizontal, target_vertical))
        for srs in (source_srs, target_srs):
            if hasattr(srs, "SetAxisMappingStrategy"):
                srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        options = osr.CoordinateTransformationOptions()
        options.SetBallparkAllowed(False)
        options.SetOnlyBest(True)
        x, y = center_xy
        try:
            horizontal_only = source_srs.Clone()
            horizontal_only.StripVertical()
            wgs84 = osr.SpatialReference()
            wgs84.ImportFromEPSG(4326)
            for srs in (horizontal_only, wgs84):
                if hasattr(srs, "SetAxisMappingStrategy"):
                    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            lon, lat, _ = osr.CoordinateTransformation(horizontal_only, wgs84).TransformPoint(x, y, 0.0)
            options.SetAreaOfInterest(lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01)
            log("   area of interest: lon %.5f lat %.5f (+-0.01)" % (lon, lat))
        except Exception as exc:
            log("   area of interest not set: %s" % exc)
        transform = osr.CreateCoordinateTransformation(source_srs, target_srs, options)
        ox, oy, oz = transform.TransformPoint(x, y, 0.0)
        log("   RESULT: PASS  (a height of 0.000 m in CGVD2013 becomes %.4f m in EGM2008 here)" % oz)
        return True
    except Exception as exc:
        log("   RESULT: FAIL")
        for line in first_lines(exc, 3):
            log("   " + line)
        log("   --- full error text ---")
        for line in str(exc).splitlines():
            log("   | " + line)
        return False


def set_network(osr, on):
    try:
        osr.SetPROJEnableNetwork(1 if on else 0)
        return bool(osr.GetPROJEnableNetwork()) == bool(on)
    except Exception as exc:
        log("   could not switch PROJ network %s: %s" % ("on" if on else "off", exc))
        return False


def fetch(names, dest):
    os.makedirs(dest, exist_ok=True)
    got = []
    for name in names:
        target = os.path.join(dest, name)
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            log("   already downloaded: %s" % target)
            got.append(target)
            continue
        url = CDN + name
        log("   downloading %s" % url)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "dem2dged-diag/0.01"})
            with urllib.request.urlopen(request, timeout=60) as response, \
                    open(target + ".part", "wb") as stream:
                shutil.copyfileobj(response, stream)
            os.replace(target + ".part", target)
            log("   saved %s (%.1f MB)" % (target, os.path.getsize(target) / 1e6))
            got.append(target)
        except Exception as exc:
            log("   FAILED %s: %s" % (name, exc))
            try:
                os.remove(target + ".part")
            except OSError:
                pass
    return got


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def source_geometry(gdal, osr, path):
    """horizontal CRS string, centre (x, y) in that CRS, and a WGS84 bbox."""
    horizontal = "EPSG:32618"
    centre = (445000.0, 5028000.0)
    bbox = (-76.0, 45.0, -75.5, 45.5)
    if not path:
        log("no --source given; using UTM 18N near Ottawa as an example.")
        return horizontal, centre, bbox
    ds = gdal.Open(path)
    srs = osr.SpatialReference()
    srs.ImportFromWkt(ds.GetProjection())
    srs.StripVertical()
    try:
        srs.AutoIdentifyEPSG()
    except Exception:
        pass
    code = srs.GetAuthorityCode(None)
    if code:
        horizontal = "EPSG:%s" % code
    gt = ds.GetGeoTransform()
    x0, y0 = gt[0], gt[3]
    x1, y1 = gt[0] + gt[1] * ds.RasterXSize, gt[3] + gt[5] * ds.RasterYSize
    centre = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    for item in (srs, wgs84):
        if hasattr(item, "SetAxisMappingStrategy"):
            item.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    to_wgs84 = osr.CoordinateTransformation(srs, wgs84)
    lon1, lat1, _ = to_wgs84.TransformPoint(x0, y0, 0.0)
    lon2, lat2, _ = to_wgs84.TransformPoint(x1, y1, 0.0)
    bbox = (min(lon1, lon2), min(lat1, lat2), max(lon1, lon2), max(lat1, lat2))
    log("source file : %s" % path)
    log("horizontal  : %s   centre (%.1f, %.1f)" % (horizontal, centre[0], centre[1]))
    log("WGS84 bbox  : %.5f, %.5f, %.5f, %.5f" % bbox)
    return horizontal, centre, bbox


def main():
    global _log_handle
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="one of the Ontario DEM tiles (to take its horizontal CRS and location)")
    parser.add_argument("--fetch", action="store_true",
                        help="download the missing grid files into ./proj_grids and retest")
    args = parser.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(HERE, "DIAG_PROJ_VERTICAL_%s.log" % stamp)
    _log_handle = open(log_path, "w", encoding="utf-8")
    log("DIAG_PROJ_VERTICAL v0.01   log: %s" % log_path)

    try:
        gdal, osr = load_gdal()
    except Exception:
        log("Cannot import osgeo.gdal - run this in the DGED Anaconda environment.")
        log(traceback.format_exc())
        return 1

    summary = []
    try:
        paths = step_environment(gdal, osr)
        section("SOURCE")
        horizontal, centre, bbox = source_geometry(gdal, osr, args.source)
        required, missing = step_grids(osr, horizontal, bbox, paths)

        section("3. STRICT TEST (exactly what the converter runs)")
        network_was_on = False
        try:
            network_was_on = bool(osr.GetPROJEnableNetwork())
        except Exception:
            pass
        set_network(osr, False)
        ok_local = strict_test(osr, horizontal, centre, "network OFF, grids from search paths only")
        summary.append(("strict test, network off", ok_local))

        section("4. STRICT TEST WITH PROJ NETWORK ON (needs internet)")
        if set_network(osr, True):
            ok_net = strict_test(osr, horizontal, centre, "network ON (grids fetched from cdn.proj.org)")
            summary.append(("strict test, network on", ok_net))
        else:
            ok_net = False
            summary.append(("strict test, network on", None))
        set_network(osr, network_was_on)

        ok_fetch = None
        if args.fetch:
            section("5. DOWNLOAD MISSING GRIDS AND RETEST")
            dest = os.path.join(HERE, "proj_grids")
            wanted = missing if missing else []
            if not wanted:
                log("no grids reported missing; nothing to download.")
            else:
                got = fetch(wanted, dest)
                if got:
                    set_network(osr, False)
                    osr.SetPROJSearchPaths(search_paths(osr) + [dest])
                    ok_fetch = strict_test(osr, horizontal, centre,
                                           "network OFF, with %s added to the search paths" % dest)
                    summary.append(("strict test after download", ok_fetch))
                    target_dir = next((p for p in paths if os.path.isfile(os.path.join(p, "proj.db"))), None)
                    log("")
                    log("To make the converter use these files permanently, copy them next to proj.db:")
                    if target_dir:
                        log('    copy "%s\\*.tif" "%s"' % (dest, target_dir))
                    else:
                        log("    (no search path with proj.db was found; send this log)")

        section("SUMMARY")
        for label, value in summary:
            log("  %-30s %s" % (label, {True: "PASS", False: "FAIL", None: "NOT RUN"}[value]))
        log("  grids missing from search paths: %s" % (", ".join(missing) if missing else "none"))
        log("")
        if ok_local:
            log("VERDICT: PROJ can already do the operation with local files. The converter's error came from")
            log("         something else; send this log and vertical_operation_check.json from the output folder.")
        elif ok_net and missing:
            log("VERDICT: the operation works only with network access. Missing local grid file(s): %s." %
                ", ".join(missing))
            log("         Re-run with --fetch to download them, then copy them next to proj.db.")
        elif ok_fetch:
            log("VERDICT: the operation works once the downloaded grid files are in a PROJ search path.")
        else:
            log("VERDICT: the operation still fails. Send this log file; nothing here should be guessed.")
    except Exception:
        log("UNEXPECTED ERROR:")
        log(traceback.format_exc())
        return 1
    finally:
        log("")
        log("Log file: %s" % log_path)
        _log_handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
