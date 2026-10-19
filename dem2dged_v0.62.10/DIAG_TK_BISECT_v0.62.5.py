#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.01  (finds which earlier action makes tkinter.Tk() hang in the DGED environment)
"""DIAG_TK_BISECT_v0.62.5.py

WHY THIS EXISTS
---------------
DIAG_FREEZE_v0.62.5.py showed that GDAL does NOT hold the GIL (the main thread
stayed alive during the network reads).  But the very next step, creating a Tk
window with tkinter.Tk(), hung for minutes with no other work running.  So
something done earlier in that process (faulthandler, GDAL import, a GDAL warp,
a /vsicurl/ network read, a urllib thread, or spawning a hidden child process)
leaves Tcl/Tk unable to start or to run.  That would explain the app's
"Not responding" too.

Each case below runs in its OWN fresh Python process: it performs a few "prior
actions", then creates tkinter.Tk(), and reports OK or HANG (after 30 s the
process is killed).  The pattern of HANG cases points to the culprit.

HOW TO RUN (Anaconda Prompt, DGED environment, from the dem2dged_v0.62.5 folder):

    python DIAG_TK_BISECT_v0.62.5.py

It needs the internet for two cases and takes about 1-4 minutes.  A small Tk
window may flash on screen for each case; that is normal.  It writes
DIAG_TK_BISECT_<timestamp>.log next to itself.
"""

import argparse
import datetime
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

CASE_TIMEOUT = 30.0
STAC_URL = ("https://datacube.services.geo.ca/pgstac/api/collections/hrdem-lidar/items"
            "?bbox=-118.765412,52.336671,-118.614121,52.429635&limit=1")
COG_URL = ("https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-lidar/"
           "BC-BCTS_PrinceGeorgeKamloops_UTM11_2020-1m-dtm.tif")

# case number -> (description, prior actions before Tk())
CASES = {
    0: ("Tk only (clean process)", []),
    1: ("faulthandler.enable() then Tk", ["faulthandler"]),
    2: ("import osgeo.gdal then Tk", ["gdal_import"]),
    3: ("GDAL local warp (no network) then Tk", ["gdal_import", "gdal_warp"]),
    4: ("GDAL /vsicurl/ read in MAIN thread then Tk", ["gdal_import", "vsicurl_main"]),
    5: ("GDAL /vsicurl/ read in a THREAD then Tk", ["gdal_import", "vsicurl_thread"]),
    6: ("urllib request in a thread (no GDAL) then Tk", ["urllib_thread"]),
    7: ("spawn hidden child process then Tk", ["spawn"]),
    8: ("same order as DIAG_FREEZE (faulthandler, gdal, warp, vsicurl thread, spawn) then Tk",
        ["faulthandler", "gdal_import", "gdal_warp", "vsicurl_thread", "spawn"]),
    9: ("import dem2dged_gui (module import only) then Tk", ["import_app"]),
}


# --------------------------------------------------------------------------
# child side: one case
# --------------------------------------------------------------------------

def loaded_modules(patterns):
    """Names of loaded DLLs matching patterns (Windows only)."""
    try:
        import ctypes
        from ctypes import wintypes
        psapi = ctypes.WinDLL("psapi")
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        process = kernel32.GetCurrentProcess()
        modules = (wintypes.HMODULE * 2048)()
        needed = wintypes.DWORD()
        psapi.EnumProcessModules(process, ctypes.byref(modules), ctypes.sizeof(modules),
                                 ctypes.byref(needed))
        count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), 2048)
        found = []
        buffer = ctypes.create_unicode_buffer(1024)
        for index in range(count):
            psapi.GetModuleFileNameExW(process, modules[index], buffer, 1024)
            path = buffer.value
            if any(p in os.path.basename(path).lower() for p in patterns):
                found.append(path)
        return found
    except Exception as exc:
        return ["(module listing failed: %s)" % exc]


def do_action(name):
    if name == "faulthandler":
        import faulthandler
        faulthandler.enable(file=sys.stderr)
    elif name == "gdal_import":
        from osgeo import gdal, osr
        gdal.UseExceptions()
        osr.UseExceptions()
    elif name == "gdal_warp":
        from osgeo import gdal, osr
        size = 4000
        ds = gdal.GetDriverByName("MEM").Create("", size, size, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((-76.0, 0.0002, 0.0, 45.5, 0.0, -0.0002))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        if hasattr(srs, "SetAxisMappingStrategy"):
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).Fill(12.5)
        gdal.Warp("", ds, format="MEM", dstSRS="EPSG:32618", resampleAlg="cubic")
    elif name in ("vsicurl_main", "vsicurl_thread"):
        from osgeo import gdal

        def work():
            gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
            gdal.SetConfigOption("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff,.vrt")
            gdal.SetConfigOption("GDAL_HTTP_TIMEOUT", "30")
            ds = gdal.Open("/vsicurl/" + COG_URL)
            band = ds.GetRasterBand(1)
            band.ReadAsArray(0, 0, 64, 64)
            ds = None

        if name == "vsicurl_main":
            work()
        else:
            thread = threading.Thread(target=work, daemon=True)
            thread.start()
            thread.join(60)
    elif name == "urllib_thread":
        import urllib.request

        def work():
            with urllib.request.urlopen(STAC_URL, timeout=20) as response:
                response.read()

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(40)
    elif name == "spawn":
        proc = subprocess.Popen([sys.executable, "-c", "pass"],
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        proc.wait(30)
    elif name == "import_app":
        sys.path.insert(0, HERE)
        import dem2dged_gui  # noqa: F401
    else:
        raise ValueError(name)


def run_case(number):
    import faulthandler
    description, actions = CASES[number]
    # On a hang, write every thread's stack to stderr after 15 s.
    faulthandler.dump_traceback_later(15, repeat=False, file=sys.stderr)
    print("CASE %d: %s" % (number, description), flush=True)
    for action in actions:
        started = time.monotonic()
        do_action(action)
        print("  prior action %-14s done in %.2fs" % (action, time.monotonic() - started), flush=True)
    print("  creating tkinter.Tk() ...", flush=True)
    import tkinter as tk
    started = time.monotonic()
    root = tk.Tk()
    root.update()
    elapsed = time.monotonic() - started
    print("  Tk() + update() took %.2fs" % elapsed, flush=True)
    print("  Tcl/Tk DLLs: %s" % loaded_modules(("tcl", "tk86")), flush=True)
    print("  curl/gdal DLLs: %s" % loaded_modules(("curl", "gdal")), flush=True)
    print("  TCL_LIBRARY=%s TK_LIBRARY=%s" % (os.environ.get("TCL_LIBRARY"), os.environ.get("TK_LIBRARY")),
          flush=True)
    root.destroy()
    print("TK_OK", flush=True)
    return 0


# --------------------------------------------------------------------------
# driver side
# --------------------------------------------------------------------------

def kill_tree(proc):
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        proc.kill()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=int, help="(internal) run one case in this process")
    parser.add_argument("--only", type=int, nargs="*", help="run only these case numbers")
    args = parser.parse_args()
    if args.case is not None:
        return run_case(args.case)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(HERE, "DIAG_TK_BISECT_%s.log" % stamp)
    log_handle = open(log_path, "w", encoding="utf-8", buffering=1)

    def log(text=""):
        print(text, flush=True)
        log_handle.write(text + "\n")

    log("DIAG_TK_BISECT v0.01 - python %s" % sys.version.replace("\n", " "))
    log("executable: %s" % sys.executable)
    log("conda env : %s" % os.environ.get("CONDA_DEFAULT_ENV"))
    log("log file  : %s" % log_path)
    log("")
    summary = []
    for number in (args.only if args.only else sorted(CASES)):
        description = CASES[number][0]
        log("=" * 78)
        log("CASE %d: %s" % (number, description))
        out_file = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".txt", encoding="utf-8")
        started = time.monotonic()
        proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--case", str(number)],
                                cwd=HERE, stdout=out_file, stderr=subprocess.STDOUT)
        hung = False
        while proc.poll() is None:
            if time.monotonic() - started > CASE_TIMEOUT:
                hung = True
                break
            time.sleep(0.2)
        if hung:
            time.sleep(0.5)
            kill_tree(proc)
        out_file.close()
        elapsed = time.monotonic() - started
        with open(out_file.name, "r", encoding="utf-8", errors="replace") as stream:
            text = stream.read()
        os.remove(out_file.name)
        for line in text.splitlines():
            log("    | " + line)
        ok = (not hung) and ("TK_OK" in text)
        status = "OK" if ok else ("HANG" if hung else "FAIL(exit %s)" % proc.returncode)
        summary.append((number, description, status, elapsed))
        log("  => %s  (%.1fs)" % (status, elapsed))

    log("")
    log("=" * 78)
    log("SUMMARY (tkinter.Tk() after each kind of prior action)")
    log("=" * 78)
    for number, description, status, elapsed in summary:
        log("case %d  %-6s %5.1fs  %s" % (number, status, elapsed, description))
    hung = [n for n, d, s, e in summary if s == "HANG"]
    log("")
    if not hung:
        log("VERDICT: Tk never hung in any case. Then the hang in DIAG_FREEZE came from the combination or from")
        log("         running the full Search in the same process; send both logs.")
    else:
        log("VERDICT: Tk hung in case(s) %s. The prior action(s) common to those cases and absent from the OK" % hung)
        log("         cases is the trigger. Send this log file.")
    log("Log file: %s" % log_path)
    log_handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
