#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.0
"""TEST_REFERENCE_V0.62.0.py - local test of the reference finder (v0.62.0).

Run this in the DGED Anaconda environment (NOT base), from the project folder:

    conda activate DGED
    cd /d C:\\Users\\Son\\Documents\\ChatGPT\\dem2dged\\dem2dged_v0.62.0
    python TEST_REFERENCE_V0.62.0.py

It does NOT download whole datasets. The online steps ask the public catalogs
which datasets cover a tiny area and clip about 1 km x 1 km out of one tile
per country (a few MB at most). If a service is unreachable the step is
recorded as FAIL/SKIP and the script carries on.

Options:
    --offline        skip the online steps (steps 1-3 only)
    --ottawa-bbox MINLON MINLAT MAXLON MAXLAT   change the Canadian test area
    --us-bbox     MINLON MINLAT MAXLON MAXLAT   change the US test area
    --keep           keep the clipped test rasters (default: kept in logs\\_ref_test)

Output (return BOTH files to Claude):
    logs\\reference_test_<stamp>.log
    logs\\reference_test_<stamp>.json
"""

import argparse
import datetime
import json
import os
import platform
import socket
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_DIR = os.path.join(HERE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "reference_test_%s.log" % STAMP)
JSON_PATH = os.path.join(LOG_DIR, "reference_test_%s.json" % STAMP)
WORK = os.path.join(LOG_DIR, "_ref_test_%s" % STAMP)

RESULTS = []
EXPECTED_VERSION = "0.62.0"


def out(text=""):
    print(text, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as stream:
        stream.write(text + "\n")


def record(step, status, name, detail=""):
    RESULTS.append({"step": step, "status": status, "name": name, "detail": str(detail)})
    out("%-5s %-6s %-52s %s" % (step, status, name, detail))


def section(title):
    out("")
    out("=" * 78)
    out(title)
    out("=" * 78)


def run_step(step, name, func):
    try:
        func()
    except Exception as exc:
        record(step, "FAIL", name, "%s: %s" % (type(exc).__name__, exc))
        out(traceback.format_exc())


# --------------------------------------------------------------------------
def step1_environment():
    section("STEP 1  environment")
    out("python  : %s" % sys.version.replace("\n", " "))
    out("platform: %s" % platform.platform())
    out("cwd     : %s" % os.getcwd())
    out("conda env: %s" % os.environ.get("CONDA_DEFAULT_ENV", "(not set)"))
    if os.environ.get("CONDA_DEFAULT_ENV", "") == "base":
        record(1, "WARN", "running in conda base", "create/activate a dedicated env")
    from osgeo import gdal
    record(1, "OK", "GDAL import", gdal.__version__)
    import numpy
    record(1, "OK", "numpy import", numpy.__version__)
    import dem2dged_reference as dr
    ok = dr.VERSION == EXPECTED_VERSION
    record(1, "OK" if ok else "MISMATCH", "dem2dged_reference.VERSION", dr.VERSION)
    catalog = dr.load_catalog()
    record(1, "OK", "catalog loaded", "%s (%d sources)" % (catalog["_path"], len(catalog["sources"])))
    gdal.UseExceptions()


def step2_pytest():
    section("STEP 2  offline unit tests (no network)")
    cmd = [sys.executable, "-m", "pytest", os.path.join("tests", "test_v0620_regressions.py"),
           "-q", "-p", "no:cacheprovider"]
    out("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    out(proc.stdout[-3000:])
    if proc.stderr.strip():
        out(proc.stderr[-1500:])
    record(2, "OK" if proc.returncode == 0 else "FAIL", "pytest test_v0620_regressions", "exit %d" % proc.returncode)


def step3_gui_import():
    section("STEP 3  module wiring")
    text = open(os.path.join(HERE, "dem2dged_gui.py"), encoding="utf-8").read()
    for needle in ("import dem2dged_reference as dr", "_find_reference_dialog", "Find reference"):
        record(3, "OK" if needle in text else "FAIL", "GUI contains %r" % needle)
    spec = open(os.path.join(HERE, "dem2dged.spec"), encoding="utf-8").read()
    record(3, "OK" if "dem2dged_reference" in spec else "FAIL", "spec lists dem2dged_reference")


def reachable(host, port=443, timeout=8):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "connected"
    except Exception as exc:
        return False, str(exc)


def step4_network():
    section("STEP 4  network reachability (TCP 443 only)")
    hosts = ["datacube.services.geo.ca", "canelevation-dem.s3.ca-central-1.amazonaws.com",
             "tnmaccess.nationalmap.gov", "prd-tnm.s3.amazonaws.com"]
    for host in hosts:
        ok, detail = reachable(host)
        record(4, "OK" if ok else "FAIL", host, detail)


def online_case(step, label, bbox, level, countries, expect_country):
    import dem2dged_reference as dr
    from osgeo import gdal
    section("STEP %d  %s  bbox=%s level=%s" % (step, label, bbox, level))
    out_dir = os.path.join(WORK, label.replace(" ", "_"))
    steplog = dr.StepLog(LOG_PATH, echo=True)
    t0 = time.time()
    # 5a: list only
    listed = dr.fetch_reference(bbox=tuple(bbox), out_dir=out_dir, level=level,
                                countries=countries, list_only=True, log=steplog)
    n = len(listed["candidates"])
    record(step, "OK" if n else "FAIL", "%s: candidates found" % label, "%d in %.1f s" % (n, time.time() - t0))
    for err in listed["errors"]:
        record(step, "FAIL", "%s: query error" % label, "%s: %s" % (err["source_id"], err["error"]))
    if not n:
        return
    countries_found = sorted({c["country"] for c in listed["candidates"]})
    record(step, "OK" if expect_country in countries_found else "FAIL",
           "%s: has %s candidates" % (label, expect_country), countries_found)
    # raw look at the first candidate for debugging the service shape
    first = listed["candidates"][0]
    out("first candidate (for debugging): " + json.dumps(
        {k: first.get(k) for k in ("source_id", "item_id", "date", "resolution_m", "epsg",
                               "covers_whole_box", "size_bytes", "suitability", "coverage")}, default=str))
    out("first candidate hrefs: " + json.dumps(first["hrefs"]))
    # 5b: clip the best candidate from the expected country
    covered = [c for c in listed["candidates"]
               if c["country"] == expect_country and (c.get("coverage") or 0) >= dr.MIN_COVERAGE]
    record(step, "OK" if covered else "FAIL", "%s: a dataset has real data in the area" % label,
           ", ".join("#%d %s %.0f%%" % (c["number"], c["title"], 100 * c["coverage"]) for c in covered[:4])
           or "none of %d candidates has data over >= %.0f%% of the box" % (n, 100 * dr.MIN_COVERAGE))
    if not covered:
        return
    t1 = time.time()
    res = dr.fetch_reference(bbox=tuple(bbox), out_dir=out_dir, level=level,
                             countries=countries, pick=None, max_cells=8_000_000, log=steplog)
    out_path = res.get("output")
    if not out_path or not os.path.isfile(out_path):
        record(step, "FAIL", "%s: clip written" % label, "no output")
        return
    size = os.path.getsize(out_path)
    record(step, "OK", "%s: clip written" % label, "%.1f MB in %.1f s" % (size / 1e6, time.time() - t1))
    stats = res["stats"]
    record(step, "OK" if stats["valid_fraction"] > 0.5 else "FAIL",
           "%s: valid height fraction" % label, "%.1f%%" % (100 * stats["valid_fraction"]))
    sane = stats["min"] is not None and -500 < stats["min"] < 9000 and -500 < stats["max"] < 9000
    record(step, "OK" if sane else "FAIL", "%s: height range plausible" % label,
           "min %.2f max %.2f mean %.2f" % (stats["min"], stats["max"], stats["mean"]) if stats["min"] is not None else "no data")
    ds = gdal.Open(out_path)
    gt = ds.GetGeoTransform()
    out("clip CRS: %s" % (ds.GetProjection()[:90] + "..."))
    out("clip pixel size: %.4g x %.4g, size %d x %d" % (gt[1], gt[5], ds.RasterXSize, ds.RasterYSize))
    ds = None
    side = json.load(open(res["sidecar"], encoding="utf-8"))
    record(step, "OK" if side.get("sha256") and side.get("reference_identifier") else "FAIL",
           "%s: sidecar complete" % label, side.get("reference_identifier"))
    for warning in side["warnings"]:
        out("  warning in sidecar: " + warning)
    record(step, "INFO", "%s: suitability for level %s" % (label, level),
           "%s - %s" % (side["suitability_for_level"]["result"], side["suitability_for_level"]["text"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--ottawa-bbox", nargs=4, type=float, default=[-75.700, 45.400, -75.690, 45.409])
    parser.add_argument("--us-bbox", nargs=4, type=float, default=[-77.040, 38.890, -77.030, 38.899])
    args = parser.parse_args()

    open(LOG_PATH, "w", encoding="utf-8").close()
    out("DEM2DGED reference-finder test  v%s   %s" % (EXPECTED_VERSION, datetime.datetime.now().isoformat(timespec="seconds")))
    run_step(1, "environment", step1_environment)
    run_step(2, "pytest", step2_pytest)
    run_step(3, "wiring", step3_gui_import)
    if not args.offline:
        run_step(4, "network", step4_network)
        run_step(5, "Ottawa", lambda: online_case(5, "Canada Ottawa", args.ottawa_bbox, "3", ["CA"], "CA"))
        run_step(6, "Washington", lambda: online_case(6, "US Washington DC", args.us_bbox, "3", ["US"], "US"))

    section("SUMMARY")
    counts = {}
    for r in RESULTS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    out("  ".join("%s=%d" % (k, v) for k, v in sorted(counts.items())))
    with open(JSON_PATH, "w", encoding="utf-8") as stream:
        json.dump({"stamp": STAMP, "python": sys.version, "args": vars(args),
                   "results": RESULTS, "counts": counts}, stream, indent=2)
    out("")
    out("LOG : %s" % LOG_PATH)
    out("JSON: %s" % JSON_PATH)
    out("Clipped test rasters (if any) are in: %s" % WORK)
    out("Return BOTH files to Claude.")
    return 1 if counts.get("FAIL") or counts.get("MISMATCH") else 0


if __name__ == "__main__":
    sys.exit(main())
