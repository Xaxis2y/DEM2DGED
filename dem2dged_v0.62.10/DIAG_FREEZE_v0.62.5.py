#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.01  (diagnostic for dem2dged v0.62.5 "Not responding" in Find reference)
"""DIAG_FREEZE_v0.62.5.py - find out WHY the Find-reference dialog freezes.

Run this from the Anaconda Prompt, inside the dedicated DGED environment, from
the dem2dged_v0.62.5 source folder (the folder that holds dem2dged_reference.py
and dem2dged_gui.py).  It never changes the app; it only writes a log file.

    conda activate DGED                 (your dedicated environment, NOT base)
    cd C:\\Users\\Son\\Documents\\ChatGPT\\dem2dged\\dem2dged_v0.62.5
    python DIAG_FREEZE_v0.62.5.py --source "C:\\path\\to\\dsm_1m_utm10_e_2_187.tif" --level 0

Optional:
    --download 1      also run the v0.62.5 download worker for candidate number 1
                      (clips only your area into a temp folder, deleted afterwards)
    --no-tk           skip the Tk window test
    --skip-control    skip the pure-CPU GDAL control test
    --limit 240       hard time limit per step in seconds (default 240)

THE IDEA
--------
"Not responding" means the Tk main thread did not get to run for several
seconds.  In v0.62.5 the Search button runs GDAL network reads (gdal.Open on
/vsicurl/, ReadAsArray) inside a Python THREAD of the GUI process.  If the GDAL
Python bindings keep the GIL while they wait for the network, the Tk main thread
cannot run and Windows marks the window "Not responding".  This script measures
that directly: while each step runs, the main thread wakes every 50 ms and
records how late it was.  A large "worst gap" = the GUI would have frozen for
that long.  The same search is then repeated in a separate process; if the gap
disappears there, moving the search out of the GUI process is the fix.

If a step stays stuck, faulthandler writes the stack of every Python thread
into the log every 20 seconds, so we can see exactly which call is blocking.

Send me the .log file this script writes next to itself.
"""

import argparse
import datetime
import faulthandler
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TICK = 0.05           # seconds between main-thread heartbeats
STALL_REPORT = 1.0    # a gap longer than this is reported as a stall


class Log:
    def __init__(self, path):
        self.path = path
        self.fh = open(path, "w", encoding="utf-8", buffering=1)
        self.t0 = time.monotonic()

    def __call__(self, message=""):
        line = "[%8.2fs] %s" % (time.monotonic() - self.t0, message)
        try:
            print(line, flush=True)
        except Exception:
            pass
        self.fh.write(line + "\n")
        self.fh.flush()


class GapMeter:
    """Wakes every TICK seconds on the calling thread and records lateness."""

    def __init__(self, tick=TICK):
        self.tick = tick
        self.t0 = time.monotonic()
        self.last = self.t0
        self.max_gap = 0.0
        self.stalls = []

    def sample(self):
        now = time.monotonic()
        gap = now - self.last - self.tick
        if gap > self.max_gap:
            self.max_gap = gap
        if gap > STALL_REPORT:
            self.stalls.append((round(now - self.t0, 2), round(gap, 2)))
        self.last = now

    def wait(self, is_done, limit):
        """Loop until is_done() or limit seconds. Returns True if it timed out."""
        while not is_done():
            if time.monotonic() - self.t0 > limit:
                return True
            time.sleep(self.tick)
            self.sample()
        return False


RESULTS = []   # (name, status, elapsed, max_gap, stall_count)


def record(log, name, status, elapsed, meter):
    max_gap = meter.max_gap if meter is not None else None
    stalls = meter.stalls if meter is not None else []
    RESULTS.append((name, status, elapsed, max_gap, len(stalls)))
    if meter is not None:
        log("RESULT %-34s %-8s elapsed %7.2fs  WORST UI GAP %6.2fs  stalls>%.0fs: %d %s" % (
            name, status, elapsed, max_gap, STALL_REPORT, len(stalls),
            stalls[:6] if stalls else ""))
    else:
        log("RESULT %-34s %-8s elapsed %7.2fs" % (name, status, elapsed))


def run_in_thread(log, name, func, limit):
    """Run func() in a worker thread (like the GUI does) and watch the main thread."""
    box = {"done": False, "result": None, "error": None}

    def target():
        try:
            box["result"] = func()
        except BaseException as exc:      # noqa: BLE001 - diagnostic script
            box["error"] = "%s: %s" % (type(exc).__name__, exc)
            log("  EXCEPTION in %s:\n%s" % (name, traceback.format_exc()))
        finally:
            box["done"] = True

    log("---- %s : start (worker thread, main thread heartbeat every %d ms)" % (name, int(TICK * 1000)))
    meter = GapMeter()
    started = time.monotonic()
    threading.Thread(target=target, daemon=True).start()
    timed_out = meter.wait(lambda: box["done"], limit)
    elapsed = time.monotonic() - started
    if timed_out:
        status = "TIMEOUT"
        log("  STILL RUNNING after %.0f s - see the faulthandler stack dumps above" % limit)
    elif box["error"]:
        status = "ERROR"
    else:
        status = "ok"
    record(log, name, status, elapsed, meter)
    return box["result"]


# --------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------

def step_environment(log, dr):
    log("python      : %s" % sys.version.replace("\n", " "))
    log("executable  : %s" % sys.executable)
    log("platform    : %s" % platform.platform())
    log("conda env   : %s" % os.environ.get("CONDA_DEFAULT_ENV"))
    if os.environ.get("CONDA_DEFAULT_ENV", "").lower() == "base":
        log("WARNING     : you are in the conda BASE environment. Use the dedicated DGED environment.")
    try:
        from osgeo import gdal
        log("GDAL        : %s (%s)" % (gdal.__version__, gdal.VersionInfo("RELEASE_NAME")))
        log("GDAL_DATA   : %s" % gdal.GetConfigOption("GDAL_DATA"))
        log("PROJ_LIB    : %s" % os.environ.get("PROJ_LIB"))
        log("GDAL_HTTP_* : %s" % {k: v for k, v in os.environ.items() if k.startswith(("GDAL_", "CPL_", "VSI"))})
        log("proxy env   : %s" % {k: v for k, v in os.environ.items()
                                  if k.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")})
    except Exception as exc:
        log("GDAL import FAILED: %s" % exc)
    try:
        import tkinter
        log("tkinter     : Tk %s" % tkinter.TkVersion)
    except Exception as exc:
        log("tkinter import FAILED: %s" % exc)
    log("dem2dged_reference : %s  (file %s)" % (getattr(dr, "VERSION", "?"), getattr(dr, "__file__", "?")))
    log("MAX_PROBES=%s  DEFAULT_GDAL_HTTP_TIMEOUT=%s  DEFAULT_OPERATION_TIMEOUT=%s" % (
        getattr(dr, "MAX_PROBES", "?"), dr.DEFAULT_GDAL_HTTP_TIMEOUT, dr.DEFAULT_OPERATION_TIMEOUT))


def step_control_cpu(log, size, limit):
    """Pure-CPU GDAL work with NO network: does this GDAL build release the GIL at all?"""
    def work():
        from osgeo import gdal, osr
        gdal.UseExceptions()
        osr.UseExceptions()
        ds = gdal.GetDriverByName("MEM").Create("", size, size, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((-76.0, 0.0002, 0.0, 45.5, 0.0, -0.0002))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        if hasattr(srs, "SetAxisMappingStrategy"):
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).Fill(12.5)
        out = gdal.Warp("", ds, format="MEM", dstSRS="EPSG:32618", resampleAlg="cubic")
        return "%d x %d" % (out.RasterXSize, out.RasterYSize)
    result = run_in_thread(log, "control: local GDAL warp (no net)", work, limit)
    log("  control output: %s  (if elapsed < 1 s the control is inconclusive; use --control-size 12000)" % result)


def step_extent(log, dr, source, limit):
    box = run_in_thread(log, "source extent (extent_wgs84)", lambda: dr.extent_wgs84(source), limit)
    if box:
        log("  search box lon/lat: %.5f %.5f %.5f %.5f" % tuple(box))
    return box


def step_catalog(log, dr, bbox, level, limit):
    def work():
        return dr.find_candidates(bbox, level, probe=False, log=log, operation_timeout=limit)
    result = run_in_thread(log, "catalog query only (urllib, no probe)", work, limit)
    if not result:
        return []
    candidates, errors = result
    log("  %d candidate(s); catalog errors: %s" % (len(candidates), errors))
    for cand in candidates:
        log("    #%s %s  hrefs=%s" % (cand.get("number"), cand.get("title"),
                                       list((cand.get("hrefs") or {}).keys())))
    return candidates


def step_probes(log, dr, candidates, bbox, limit):
    """Each coverage probe separately: this is the GDAL /vsicurl/ read the GUI runs in a thread."""
    for index, cand in enumerate(candidates[:getattr(dr, "MAX_PROBES", 8)], 1):
        href = (cand.get("hrefs") or {}).get("dtm")
        name = "probe %d: %s" % (index, str(cand.get("title"))[:40])
        if not href:
            log("---- %s : no dtm href, skipped" % name)
            continue
        log("  href: %s" % href)
        res = run_in_thread(log, name, lambda h=href: dr.probe_coverage(h, bbox, log), limit)
        log("  probe result: %s" % res)


def step_subprocess_search(log, bbox, level, limit):
    """The same search, but in a separate process, exactly the isolation we would add to the GUI."""
    script = os.path.join(HERE, "dem2dged_reference.py")
    command = [sys.executable, script, "--bbox"] + ["%.8f" % v for v in bbox] + [
        "--list", "--timeout", str(min(limit, 120))]
    if level is not None:
        command += ["--level", str(level)]
    out_path = os.path.join(tempfile.gettempdir(), "diag_freeze_subprocess_search.log")
    log("---- search in SEPARATE PROCESS : %s" % " ".join(command))
    handle = open(out_path, "w", encoding="utf-8")
    meter = GapMeter()
    started = time.monotonic()
    proc = subprocess.Popen(command, cwd=HERE, stdout=handle, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    timed_out = meter.wait(lambda: proc.poll() is not None, limit)
    if timed_out:
        kill_tree(proc)
    handle.close()
    elapsed = time.monotonic() - started
    status = "TIMEOUT" if timed_out else ("ok" if proc.returncode in (0, 2) else "EXIT %s" % proc.returncode)
    record(log, "search in separate process", status, elapsed, meter)
    try:
        with open(out_path, "r", encoding="utf-8", errors="replace") as stream:
            for line in stream.read().splitlines()[-40:]:
                log("    | " + line)
    except Exception as exc:
        log("  could not read subprocess output: %s" % exc)


def step_tk(log, dr, bbox, level, limit):
    """Replica of the GUI: Tk main loop + the same worker thread the Search button starts."""
    try:
        import tkinter as tk
    except Exception as exc:
        log("tkinter unavailable, Tk test skipped: %s" % exc)
        return
    box = {"done": False, "error": None, "count": None}

    def target():
        try:
            res = dr.fetch_reference(bbox=bbox, level=level, list_only=True,
                                     operation_timeout=dr.DEFAULT_OPERATION_TIMEOUT, log=log)
            box["count"] = len(res["candidates"])
        except BaseException as exc:      # noqa: BLE001
            box["error"] = "%s: %s" % (type(exc).__name__, exc)
            log("  EXCEPTION in Tk test worker:\n%s" % traceback.format_exc())
        finally:
            box["done"] = True

    log("---- Tk replica : a real Tk window + the same Search thread as the GUI.")
    log("     Watch the small window: if its title shows '(Not responding)' the GUI freeze is reproduced.")
    root = tk.Tk()
    root.title("DIAG heartbeat - watch for (Not responding)")
    root.geometry("560x110+80+80")
    label = tk.Label(root, text="starting...", font=("Segoe UI", 11), justify="left")
    label.pack(padx=12, pady=14)
    state = {"last": time.monotonic(), "t0": time.monotonic(), "max": 0.0, "stalls": []}
    interval_ms = int(TICK * 1000)

    def tick():
        now = time.monotonic()
        gap = now - state["last"] - interval_ms / 1000.0
        if gap > state["max"]:
            state["max"] = gap
        if gap > STALL_REPORT:
            state["stalls"].append((round(now - state["t0"], 2), round(gap, 2)))
        state["last"] = now
        label.config(text="elapsed %.1f s    worst UI gap so far %.2f s" % (now - state["t0"], state["max"]))
        if box["done"] or now - state["t0"] > limit:
            root.after(400, root.destroy)
            return
        root.after(interval_ms, tick)

    threading.Thread(target=target, daemon=True).start()
    root.after(interval_ms, tick)
    started = time.monotonic()
    root.mainloop()
    elapsed = time.monotonic() - started

    class _M:   # adapter so record() can print it
        max_gap = state["max"]
        stalls = state["stalls"]
    status = "TIMEOUT" if not box["done"] else ("ERROR" if box["error"] else "ok")
    record(log, "Tk replica: full Search in thread", status, elapsed, _M)
    log("  candidates found: %s   error: %s" % (box["count"], box["error"]))


def kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            proc.kill()
    except Exception:
        pass


def step_download(log, candidates, number, bbox, level, source, limit):
    """Run the v0.62.5 download worker exactly as the GUI launches it."""
    cand = next((c for c in candidates if c.get("number") == number), None)
    if cand is None:
        log("---- download: candidate #%s not found, skipped" % number)
        return
    tmp = tempfile.mkdtemp(prefix="diag_ref_")
    try:
        request_path = os.path.join(tmp, "request.json")
        result_path = os.path.join(tmp, "result.json")
        worker_log = os.path.join(tmp, "worker.log")
        request = {"candidate": cand, "bbox": list(bbox), "out_dir": os.path.join(tmp, "out"),
                   "level": level, "source_path": source, "timeout": 30}
        with open(request_path, "w", encoding="utf-8") as stream:
            json.dump(request, stream)
        command = [sys.executable, os.path.join(HERE, "dem2dged_gui.py"),
                   "--reference-clip-worker", request_path, result_path]
        log("---- download worker for candidate #%s : %s" % (number, " ".join(command)))
        handle = open(worker_log, "w", encoding="utf-8")
        meter = GapMeter()
        started = time.monotonic()
        proc = subprocess.Popen(command, cwd=HERE, stdout=handle, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        timed_out = meter.wait(lambda: proc.poll() is not None, limit)
        if timed_out:
            kill_tree(proc)
        handle.close()
        elapsed = time.monotonic() - started
        status = "TIMEOUT" if timed_out else ("ok" if proc.returncode == 0 else "EXIT %s" % proc.returncode)
        record(log, "download worker (separate process)", status, elapsed, meter)
        with open(worker_log, "r", encoding="utf-8", errors="replace") as stream:
            for line in stream.read().splitlines()[-40:]:
                log("    worker| " + line)
        if os.path.isfile(result_path):
            with open(result_path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
            log("  result.json ok=%s error=%s" % (payload.get("ok"), payload.get("error")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verdict(log):
    log("")
    log("=" * 78)
    log("SUMMARY")
    log("=" * 78)
    for name, status, elapsed, gap, stalls in RESULTS:
        log("%-38s %-8s %7.2fs   worst gap %s   stalls %s" % (
            name, status, elapsed, "n/a" if gap is None else "%6.2fs" % gap, stalls))
    thread_gaps = [g for n, s, e, g, k in RESULTS
                   if g is not None and ("probe" in n or "Tk replica" in n or "catalog" in n or "extent" in n)]
    proc_gaps = [g for n, s, e, g, k in RESULTS if g is not None and "separate process" in n]
    control = [g for n, s, e, g, k in RESULTS if g is not None and n.startswith("control")]
    worst_thread = max(thread_gaps) if thread_gaps else None
    worst_proc = max(proc_gaps) if proc_gaps else None
    log("")
    if worst_thread is not None and worst_thread > 2.0:
        log("VERDICT: the main thread was starved for up to %.1f s while GDAL/network work ran in a THREAD." % worst_thread)
        log("         => the GDAL calls keep the GIL; the v0.62.5 Search (in-process thread) freezes the GUI.")
        if worst_proc is not None and worst_proc < 1.0:
            log("         The same work in a SEPARATE PROCESS kept the main thread alive (worst gap %.2f s)." % worst_proc)
            log("         => fix: run Search (probe_coverage) in the worker process too, never in the GUI process.")
    elif worst_thread is not None:
        log("VERDICT: no long main-thread stall during search (worst gap %.2f s)." % worst_thread)
        log("         => the freeze is NOT the GIL during Search. Check the download step / the faulthandler")
        log("            stack dumps in this log, and the console window text of dem2dged.exe at the moment it hangs.")
    if control and control[0] > 2.0:
        log("NOTE: even the LOCAL no-network GDAL warp stalled the main thread (%.1f s): this GDAL build holds the GIL." % control[0])
    log("Log file: %s" % os.path.abspath(LOG_PATH))


LOG_PATH = ""


def main():
    global LOG_PATH
    parser = argparse.ArgumentParser(description="Diagnose the dem2dged v0.62.5 Find-reference freeze.")
    parser.add_argument("--source", help="your source DEM (the file you load in dem2dged)")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    parser.add_argument("--level", default="0", help="DGED level used in the dialog (default 0)")
    parser.add_argument("--download", type=int, default=0, metavar="N",
                        help="also run the download worker for candidate number N")
    parser.add_argument("--no-tk", action="store_true", help="skip the Tk window test")
    parser.add_argument("--skip-control", action="store_true", help="skip the local GDAL CPU control test")
    parser.add_argument("--control-size", type=int, default=8000, help="control raster size in cells (default 8000)")
    parser.add_argument("--limit", type=float, default=240.0, help="hard time limit per step, seconds")
    args = parser.parse_args()
    if not args.source and not args.bbox:
        parser.error("give --source <your DEM> or --bbox MINLON MINLAT MAXLON MAXLAT")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_PATH = os.path.join(HERE, "DIAG_FREEZE_%s.log" % stamp)
    log = Log(LOG_PATH)
    faulthandler.enable(file=log.fh)
    faulthandler.dump_traceback_later(20, repeat=True, file=log.fh)

    log("DIAG_FREEZE v0.01 for dem2dged v0.62.5 - log: %s" % LOG_PATH)
    try:
        import dem2dged_reference as dr
    except Exception:
        log("FATAL: cannot import dem2dged_reference from %s\n%s" % (HERE, traceback.format_exc()))
        return 1

    step_environment(log, dr)
    level = args.level

    if not args.skip_control:
        try:
            step_control_cpu(log, args.control_size, args.limit)
        except Exception:
            log("control step failed:\n%s" % traceback.format_exc())

    bbox = tuple(args.bbox) if args.bbox else step_extent(log, dr, args.source, args.limit)
    if not bbox:
        log("FATAL: could not determine the search box")
        verdict(log)
        return 1

    candidates = []
    try:
        candidates = step_catalog(log, dr, bbox, level, args.limit)
        step_probes(log, dr, candidates, bbox, args.limit)
    except Exception:
        log("catalog/probe step failed:\n%s" % traceback.format_exc())

    try:
        step_subprocess_search(log, bbox, level, args.limit)
    except Exception:
        log("subprocess search step failed:\n%s" % traceback.format_exc())

    if not args.no_tk:
        try:
            step_tk(log, dr, bbox, level, args.limit)
        except Exception:
            log("Tk step failed:\n%s" % traceback.format_exc())

    if args.download:
        try:
            step_download(log, candidates, args.download, bbox, level, args.source, args.limit)
        except Exception:
            log("download step failed:\n%s" % traceback.format_exc())

    faulthandler.cancel_dump_traceback_later()
    verdict(log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
