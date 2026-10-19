# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.10
"""Separate vertical correction for sources whose datum PROJ cannot chain strictly.

WHY THIS EXISTS (measured, v0.62.8 diagnostics on the DGED environment, PROJ 9.8.1)
---------------------------------------------------------------------------------
The Ontario HRDEM tiles carry the generic horizontal CRS "NAD83(CSRS)"
(EPSG:2959 / 4617).  PROJ's database defines the CGVD2013 grid operations only
for a specific realisation -- NAD83(CSRS)v6 (CGG2013n83.byn) or ITRF2008
(CGG2013i08.byn) -- and joins the generic CRS to them with a BALLPARK offset.
The converter's strict guard (no ballpark, best operation only) therefore
refused CGVD2013 -> EGM2008, correctly: the one ballpark route PROJ offers
(through v6) shifts heights by +1.09 m where five independent routes (ITRF2008,
NAD83(CSRS) v3, v4, v7, v8) agree on -0.022 m at the same point.

WHAT THIS MODULE DOES
---------------------
It computes the CGVD2013 -> EGM2008 height difference on its own, with a
strictly verified route, and adds it to the source heights.  The horizontal
georeferencing is not touched: the result is a copy of the source with the same
grid, the same CRS and the same metadata, only the heights are in EGM2008.

  * The shift is evaluated at a coarse grid of nodes covering the source
    (about one node per kilometre, at most MAX_NODES per axis), with the
    horizontal CRS replaced by ITRF2008 (EPSG:8999) -- a context for which
    PROJ has a complete non-ballpark chain.  The ITRF2008 grid (CGG2013i08)
    is the native one for that CRS.  The context only places the evaluation
    point; it does not re-interpret the DEM's own coordinates.
  * Every node is evaluated a second time with a NAD83(CSRS) realisation (v8,
    v7, v4 or v3) as the context.  If the two routes differ by more than
    TOLERANCE_M anywhere, the correction is refused.  This is the check that
    would have caught the +1.09 m v6 route.  It tests how the horizontal frame
    is handled; the two routes may well read the SAME geoid grid files, so it
    does not by itself validate the CGG2013 or EGM2008 grids.
  * The shift is interpolated bilinearly in pixel space and added block by
    block; NoData stays NoData.

GEOID GRID FILES (v0.62.10)
---------------------------
v0.62.9 relied on PROJ's network access to fetch the geoid grids.  That worked
on the command line (main thread) but not in the GUI's worker thread, where PROJ
reported "Grid ca_nrc_CGG2013i08.tif is not available" and the run stopped.  The
grids are now ordinary local files: the two named in SEPARATE_ROUTES (and any
other grid PROJ reports as missing) are downloaded once from https://cdn.proj.org
with urllib, checked to open as rasters, kept in grid_dir() and added to the PROJ
search paths of the process.  Their SHA-256 is written to the correction record.
Set DEM2DGED_NO_GRID_DOWNLOAD=1 to forbid downloads (the grids must then already
be in a PROJ search path or in grid_dir()).

Only datums listed in SEPARATE_ROUTES are handled.  Everything else keeps the
old behaviour: the strict check runs and the conversion is refused when it
fails.  The operation accuracies recorded in the report are the values stored in
PROJ's database (EPSG:9124 0.03 m for CGVD2013 <-> ITRF2008, EPSG:3858 0.113 m
for WGS 84 -> EGM2008); they are stated accuracies, not measurements.
"""

from __future__ import annotations

import atexit
import hashlib
import math
import os
import re
import shutil
import tempfile
import urllib.request
from typing import Any, Dict, Optional, Sequence

VERSION = "0.62.10"

TARGET_VERTICAL_EPSG = "3855"          # EGM2008
TOLERANCE_M = 0.02                     # primary vs cross-check route, per node
NODE_SPACING_KM = 1.0                  # target spacing of the evaluation grid
MAX_NODES = 400                        # per axis
STRIP_CELLS = 4_000_000                # cells per processing strip
MAX_GRID_BYTES = 600_000_000           # largest grid file the module will download

# datum -> verified separate route.  Entries are data, not code, so a new datum
# is added only after its routes have been measured the same way.
SEPARATE_ROUTES: Dict[str, Dict[str, Any]] = {
    "6647": {
        "name": "CGVD2013(CGG2013) height",
        "primary": {"epsg": "8999", "name": "ITRF2008",
                    "grid": "CGG2013i08.byn", "grid_operation": "EPSG:9124",
                    "grid_accuracy_m": 0.03},
        # files PROJ asked for in the v0.62.9 GUI log; fetched before the first
        # transformation so PROJ never needs its own network layer
        "grid_files": ["ca_nrc_CGG2013i08.tif", "us_nga_egm08_25.tif"],
        # tried in order; the first one PROJ can build strictly is used
        "cross_checks": [
            {"epsg": "10414", "name": "NAD83(CSRS)v8"},
            {"epsg": "8255", "name": "NAD83(CSRS)v7"},
            {"epsg": "8246", "name": "NAD83(CSRS)v4"},
            {"epsg": "8240", "name": "NAD83(CSRS)v3"},
        ],
        "target_accuracy_m": 0.113,     # EPSG:3858 WGS 84 -> EGM2008 height (1)
        "target_operation": "EPSG:3858",
    },
}


# ---------------------------------------------------------------------------
# error text
# ---------------------------------------------------------------------------

SAFE_GRID_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*\.(?:tif|gtx)$")
GRID_HOST = "https://cdn.proj.org/"
FULL_TEXT_LIMIT = 4000


def grid_names_from_error(text: Any):
    """Grid file names PROJ reports as 'not available' (safe plain names only)."""
    names = []
    for name in re.findall(r"Grid (\S+) is not available", str(text or "")):
        if SAFE_GRID_NAME.match(name) and name not in names:
            names.append(name)
    return names


def cap_text(text: Any, limit: int = FULL_TEXT_LIMIT) -> str:
    """PROJ repeats 'May be caused by' blocks dozens of times; keep the head."""
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "\n[... %d more characters cut]" % (len(text) - limit)


def summarize_proj_error(text: Any, limit: int = 300) -> str:
    """Short, readable version of a PROJ error.

    PROJ reports "Cannot find coordinate operations from `{PROJJSON}` to
    `{PROJJSON}`" with hundreds of lines of JSON.  That text made the GUI error
    dialog unreadable, so only the CRS names are kept; the full text stays in
    the JSON record next to the output.
    """
    text = str(text or "")
    missing = grid_names_from_error(text)
    if missing:
        return ("PROJ cannot find the geoid grid file(s) %s (its network access is off in this "
                "process, or the files are not installed)." % ", ".join(missing))
    if "Cannot find coordinate operations" in text:
        names = re.findall(r'"type":\s*"CompoundCRS",\s*"name":\s*"([^"]+)"', text)
        if len(names) < 2:
            names = re.findall(r'"name":\s*"([^"]+)"', text)[:1] + [
                n for n in re.findall(r'"name":\s*"([^"]+)"', text) if "height" in n][-1:]
        if len(names) >= 2:
            return ("PROJ has no non-ballpark operation from '%s' to '%s' "
                    "(a required step is only defined as a ballpark)." % (names[0], names[1]))
        return "PROJ has no non-ballpark operation for the requested vertical conversion."
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[:limit] + "..."


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _gdal():
    from osgeo import gdal, osr
    return gdal, osr


def _traditional(osr, srs):
    if hasattr(srs, "SetAxisMappingStrategy"):
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def grid_dir() -> str:
    """Folder for the grid files dem2dged downloads (override: DEM2DGED_GRID_DIR)."""
    override = os.environ.get("DEM2DGED_GRID_DIR")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "dem2dged", "proj_grids")


def downloads_allowed() -> bool:
    return os.environ.get("DEM2DGED_NO_GRID_DOWNLOAD", "").strip().lower() not in ("1", "true", "yes", "on")


def add_grid_dir(osr) -> str:
    """Make PROJ search grid_dir() as well as its own folders (new contexts pick it up)."""
    folder = grid_dir()
    os.makedirs(folder, exist_ok=True)
    paths = list(osr.GetPROJSearchPaths())
    if os.path.normcase(folder) not in [os.path.normcase(p) for p in paths]:
        osr.SetPROJSearchPaths(paths + [folder])
    return folder


def grid_path(osr, name: str):
    """Full path of a grid file in any PROJ search path, or None."""
    for folder in list(osr.GetPROJSearchPaths()):
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            return candidate
    return None


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_grid(name: str, folder: str, gdal, log=None, stop_event=None, timeout: int = 60) -> str:
    """Download one PROJ grid file from cdn.proj.org into ``folder``; return its path.

    urllib is used on purpose: PROJ's own network layer (libcurl through GDAL) did
    not work in the GUI's worker thread.  The file is written to a .part file,
    must open as a raster, and only then gets its final name.
    """
    log = log or (lambda message: None)
    if not SAFE_GRID_NAME.match(name):
        raise ValueError("refusing to download an unexpected grid name: %r" % name)
    if not downloads_allowed():
        raise RuntimeError("grid downloads are switched off (DEM2DGED_NO_GRID_DOWNLOAD) and %s is missing" % name)
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, name)
    part = target + ".part"
    url = GRID_HOST + name
    log("  Vertical correction: downloading %s once from cdn.proj.org (stored in %s)" % (name, folder))
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "dem2dged/%s" % VERSION})
        with urllib.request.urlopen(request, timeout=timeout) as response, open(part, "wb") as stream:
            total = int(response.headers.get("Content-Length") or 0)
            if total > MAX_GRID_BYTES:
                raise RuntimeError("%s is %.0f MB; refusing a download over %d MB"
                                   % (name, total / 1e6, MAX_GRID_BYTES // 1_000_000))
            done, next_mark = 0, 10
            while True:
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("stopped by the operator")
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                stream.write(chunk)
                done += len(chunk)
                if done > MAX_GRID_BYTES:
                    raise RuntimeError("download of %s exceeded %d MB; stopped" % (name, MAX_GRID_BYTES // 1_000_000))
                if total and done * 100 // total >= next_mark:
                    log("  Vertical correction: %s %d%% of %.0f MB" % (name, done * 100 // total, total / 1e6))
                    next_mark += 10
        dataset = gdal.Open(part)
        if dataset is None or dataset.RasterCount < 1:
            raise RuntimeError("the downloaded file does not open as a raster")
        dataset = None
        os.replace(part, target)
    except Exception:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return target


def ensure_grids(names, osr, gdal, record: Dict[str, Any], log=None, stop_event=None) -> None:
    """Have every named grid as a local file PROJ can find; note them in ``record``."""
    folder = add_grid_dir(osr)
    for name in names:
        if grid_path(osr, name):
            continue
        fetch_grid(name, folder, gdal, log=log, stop_event=stop_event)
    files = record.setdefault("grid_files", [])
    for name in names:
        path = grid_path(osr, name)
        if path and not any(item["name"] == name for item in files):
            files.append({"name": name, "path": path, "bytes": os.path.getsize(path),
                          "sha256": _sha256(path), "source": GRID_HOST + name})


def _with_grid_retry(call, osr, gdal, record, log=None, stop_event=None, rounds: int = 3):
    """Run ``call``; if PROJ says a grid is missing, fetch it and try again."""
    for attempt in range(rounds):
        try:
            return call()
        except Exception as exc:
            names = [n for n in grid_names_from_error(exc) if not grid_path(osr, n)]
            if not names or attempt == rounds - 1 or not downloads_allowed():
                raise
            ensure_grids(names, osr, gdal, record, log=log, stop_event=stop_event)


def _strict_transform(osr, context_epsg: str, source_vertical: str, target_vertical: str,
                      lon: float, lat: float):
    """Strict (no ballpark, best only) CGVD-like -> EGM2008 transformation in a context CRS."""
    source = _traditional(osr, osr.SpatialReference())
    target = _traditional(osr, osr.SpatialReference())
    source.SetFromUserInput("EPSG:%s+%s" % (context_epsg, source_vertical))
    target.SetFromUserInput("EPSG:%s+%s" % (context_epsg, target_vertical))
    options = osr.CoordinateTransformationOptions()
    options.SetBallparkAllowed(False)
    options.SetOnlyBest(True)
    options.SetAreaOfInterest(lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01)
    return osr.CreateCoordinateTransformation(source, target, options)


def _shift_at_nodes(osr, context_epsg: str, source_vertical: str, target_vertical: str,
                    lons: Sequence[float], lats: Sequence[float]):
    """Height difference (target - source) in metres at each node, via one context."""
    import numpy as np
    count = len(lons)
    out = np.empty(count, dtype="float64")
    # PROJ picks the operation by area of interest, so build one transformation
    # per node block rather than one for the whole (possibly large) extent.
    block = 100
    for start in range(0, count, block):
        stop = min(count, start + block)
        mid = (start + stop - 1) // 2
        transform = _strict_transform(osr, context_epsg, source_vertical,
                                      target_vertical, lons[mid], lats[mid])
        points = [(float(lons[i]), float(lats[i]), 0.0) for i in range(start, stop)]
        result = transform.TransformPoints(points)
        for offset, point in enumerate(result):
            out[start + offset] = point[2] - 0.0
    return out


def _node_plan(ds, osr, srs_h) -> Dict[str, Any]:
    """Node grid in source pixel space plus the matching lon/lat of every node."""
    import numpy as np
    gt = ds.GetGeoTransform()
    width, height = ds.RasterXSize, ds.RasterYSize
    wgs84 = _traditional(osr, osr.SpatialReference())
    wgs84.ImportFromEPSG(4326)
    to_wgs84 = osr.CoordinateTransformation(srs_h, wgs84)

    def lonlat(col: float, row: float):
        x = gt[0] + gt[1] * col + gt[2] * row
        y = gt[3] + gt[4] * col + gt[5] * row
        lon, lat, _ = to_wgs84.TransformPoint(x, y, 0.0)
        return lon, lat

    corners = [lonlat(c, r) for c in (0, width) for r in (0, height)]
    lons = [p[0] for p in corners]
    lats = [p[1] for p in corners]
    mid_lat = (min(lats) + max(lats)) / 2.0
    span_x_km = (max(lons) - min(lons)) * 111.32 * max(0.1, math.cos(math.radians(mid_lat)))
    span_y_km = (max(lats) - min(lats)) * 111.32
    nx = int(min(MAX_NODES, max(2, math.ceil(span_x_km / NODE_SPACING_KM) + 1)))
    ny = int(min(MAX_NODES, max(2, math.ceil(span_y_km / NODE_SPACING_KM) + 1)))
    cols = np.linspace(0.0, float(width), nx)
    rows = np.linspace(0.0, float(height), ny)
    node_lon = np.empty((ny, nx))
    node_lat = np.empty((ny, nx))
    for j, row in enumerate(rows):
        for i, col in enumerate(cols):
            node_lon[j, i], node_lat[j, i] = lonlat(float(col), float(row))
    return {"nx": nx, "ny": ny, "cols": cols, "rows": rows,
            "lon": node_lon, "lat": node_lat, "width": width, "height": height,
            "span_km": (span_x_km, span_y_km)}


def _interp_axes(size: int, nodes: int):
    """For every pixel centre: lower node index and weight along one axis."""
    import numpy as np
    pos = (np.arange(size, dtype="float64") + 0.5) / float(size) * (nodes - 1)
    low = np.minimum(np.floor(pos).astype("int64"), nodes - 2)
    return low, pos - low


MAX_COLUMN_TABLE_CELLS = 80_000_000


def _column_table(grid, col_low, col_w):
    """Node rows already interpolated to every pixel column (None if too large)."""
    import numpy as np
    if grid.shape[0] * len(col_low) > MAX_COLUMN_TABLE_CELLS:
        return None
    return (grid[:, col_low] * (1.0 - col_w) + grid[:, col_low + 1] * col_w).astype("float32")


def _shift_for_rows(grid, table, col_low, col_w, row_low, row_w, r0: int, r1: int):
    """Bilinear shift for pixel rows r0..r1-1 (all columns), as float32."""
    import numpy as np
    rows = np.arange(r0, r1)
    low = row_low[rows]
    wy = row_w[rows].astype("float32")[:, None]
    if table is not None:
        return table[low] * (1.0 - wy) + table[low + 1] * wy
    out = np.empty((r1 - r0, len(col_low)), dtype="float32")
    for k in range(r1 - r0):
        j = low[k]
        top = grid[j, col_low] * (1.0 - col_w) + grid[j, col_low + 1] * col_w
        bottom = grid[j + 1, col_low] * (1.0 - col_w) + grid[j + 1, col_low + 1] * col_w
        out[k, :] = top * (1.0 - wy[k, 0]) + bottom * wy[k, 0]
    return out


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def create_corrected_source(src_path: str, source_vertical_epsg: str, out_path: str,
                            log=None, stop_event=None,
                            target_vertical_epsg: str = TARGET_VERTICAL_EPSG) -> Dict[str, Any]:
    """Write a copy of ``src_path`` whose heights are in ``target_vertical_epsg``.

    Returns a record (JSON-serialisable).  ``record["status"]`` is PASS, FAIL or
    STOPPED.  On FAIL nothing is left at ``out_path``.
    """
    log = log or (lambda message: None)
    source_vertical = str(source_vertical_epsg or "").replace("EPSG:", "")
    target_vertical = str(target_vertical_epsg or "").replace("EPSG:", "")
    record: Dict[str, Any] = {
        "status": "FAIL", "route": "separate_vertical_correction",
        "source_vertical_epsg": source_vertical, "target_vertical_epsg": target_vertical,
        "module_version": VERSION, "horizontal_georeferencing_changed": False,
        "tolerance_m": TOLERANCE_M,
    }
    route = SEPARATE_ROUTES.get(source_vertical)
    if not route or target_vertical != TARGET_VERTICAL_EPSG:
        record["reason"] = ("no verified separate route for EPSG:%s -> EPSG:%s"
                            % (source_vertical, target_vertical))
        return record

    if os.path.abspath(out_path) == os.path.abspath(src_path):
        record["reason"] = "refusing to write the corrected copy over the source file"
        return record

    import numpy as np
    gdal, osr = _gdal()
    previous_gdal = gdal.GetUseExceptions() if hasattr(gdal, "GetUseExceptions") else False
    previous_osr = osr.GetUseExceptions() if hasattr(osr, "GetUseExceptions") else False
    gdal.UseExceptions()
    osr.UseExceptions()
    ds = out = None
    try:
        ds = gdal.Open(src_path)
        gt = ds.GetGeoTransform()
        if gt[2] != 0.0 or gt[4] != 0.0:
            record["reason"] = "rotated rasters are not supported by the separate correction"
            return record
        band = ds.GetRasterBand(1)
        if (band.GetScale() not in (None, 1.0)) or (band.GetOffset() not in (None, 0.0)):
            record["reason"] = "the source band has a scale/offset; refusing to guess"
            return record
        nodata = band.GetNoDataValue()
        srs_h = osr.SpatialReference()
        srs_h.ImportFromWkt(ds.GetProjection())
        srs_h.StripVertical()
        _traditional(osr, srs_h)
        plan = _node_plan(ds, osr, srs_h)
        nx, ny = plan["nx"], plan["ny"]
        log("  Vertical correction: %d x %d evaluation nodes over %.1f x %.1f km"
            % (nx, ny, plan["span_km"][0], plan["span_km"][1]))
        lons = plan["lon"].ravel()
        lats = plan["lat"].ravel()

        primary = route["primary"]
        try:
            ensure_grids(route.get("grid_files", []), osr, gdal, record, log=log, stop_event=stop_event)
        except Exception as exc:
            if stop_event is not None and stop_event.is_set():
                record["status"] = "STOPPED"
                record["reason"] = "stopped by the operator"
                return record
            # not fatal yet: PROJ may still have its own way to reach the grids,
            # and a failure there is reported with the names of the missing files
            log("  Vertical correction: could not prepare the grid files (%s)" % summarize_proj_error(exc, 160))
            record["grid_prepare_error"] = str(exc)
        primary_shift = _with_grid_retry(
            lambda: _shift_at_nodes(osr, primary["epsg"], source_vertical,
                                    target_vertical, lons, lats),
            osr, gdal, record, log=log, stop_event=stop_event)
        if not np.all(np.isfinite(primary_shift)):
            record["reason"] = ("the %s route returned no value at some nodes (outside the "
                                "geoid grid coverage)" % primary["name"])
            return record

        cross_used: Optional[Dict[str, Any]] = None
        cross_error = []
        cross_shift = None
        for candidate in route["cross_checks"]:
            try:
                cross_shift = _with_grid_retry(
                    lambda: _shift_at_nodes(osr, candidate["epsg"], source_vertical,
                                            target_vertical, lons, lats),
                    osr, gdal, record, log=log, stop_event=stop_event)
                cross_used = candidate
                break
            except Exception as exc:
                cross_error.append("%s: %s" % (candidate["name"], summarize_proj_error(exc, 120)))
        if cross_shift is None:
            record["reason"] = ("no independent cross-check route could be built (%s); "
                                "refusing an unverified correction" % "; ".join(cross_error))
            record["cross_check_errors"] = cross_error
            return record
        max_diff = float(np.max(np.abs(primary_shift - cross_shift)))
        record.update({
            "primary_context": primary, "cross_check_context": cross_used,
            "cross_check_max_difference_m": max_diff,
            "nodes": [ny, nx],
            "node_spacing_km_target": NODE_SPACING_KM,
            "shift_min_m": float(primary_shift.min()), "shift_max_m": float(primary_shift.max()),
            "shift_mean_m": float(primary_shift.mean()),
            "stated_operation_accuracy_m": {
                "source_to_ellipsoid_grid": primary["grid_accuracy_m"],
                "ellipsoid_to_target_grid": route["target_accuracy_m"],
                "combined_rss": math.sqrt(primary["grid_accuracy_m"] ** 2 + route["target_accuracy_m"] ** 2),
                "basis": "values stored in proj.db (%s and %s); stated, not measured"
                         % (primary["grid_operation"], route["target_operation"]),
            },
            "interpolation": "bilinear in source pixel space between evaluation nodes",
        })
        log("  Vertical correction: %s vs %s routes differ by at most %.4f m (limit %.3f m)"
            % (primary["name"], cross_used["name"], max_diff, TOLERANCE_M))
        if max_diff > TOLERANCE_M:
            record["reason"] = ("the two independent routes disagree by %.4f m (limit %.3f m); "
                                "refusing the correction" % (max_diff, TOLERANCE_M))
            return record
        log("  Vertical correction: shift %s -> EGM2008 ranges %+.4f .. %+.4f m (mean %+.4f m)"
            % (source_vertical, record["shift_min_m"], record["shift_max_m"], record["shift_mean_m"]))

        grid = primary_shift.reshape(ny, nx)
        col_low, col_w = _interp_axes(plan["width"], nx)
        row_low, row_w = _interp_axes(plan["height"], ny)
        table = _column_table(grid, col_low, col_w)

        # Copy with identical georeferencing and metadata, then update heights in place.
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        if os.path.exists(out_path):
            os.remove(out_path)
        out = gdal.Translate(
            out_path, ds, format="GTiff", outputType=gdal.GDT_Float32,
            creationOptions=["TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256",
                             "COMPRESS=DEFLATE", "PREDICTOR=3", "BIGTIFF=IF_SAFER"])
        if out is None:
            record["reason"] = "could not create the corrected copy"
            return record
        out.SetMetadataItem("DEM2DGED_VERTICAL_CORRECTION",
                            "EPSG:%s -> EPSG:%s via %s (v%s)"
                            % (source_vertical, target_vertical, primary["name"], VERSION))
        wkt_h = srs_h.ExportToWkt()
        try:
            if osr.SpatialReference(wkt=ds.GetProjection()).IsCompound():
                # the heights are no longer in the declared datum: do not leave
                # the old vertical CRS in the copy
                out.SetProjection(wkt_h)
        except Exception:
            pass
        out_gt = out.GetGeoTransform()
        if (out.RasterXSize, out.RasterYSize) != (ds.RasterXSize, ds.RasterYSize) or any(
                abs(a - b) > 1e-9 * max(1.0, abs(a)) for a, b in zip(out_gt, gt)):
            record["reason"] = "the corrected copy does not share the source grid; refusing"
            out = None
            return record
        out_band = out.GetRasterBand(1)
        width, height = plan["width"], plan["height"]
        strip = max(256, (STRIP_CELLS // max(1, width)) // 256 * 256)
        done = 0
        for r0 in range(0, height, strip):
            if stop_event is not None and stop_event.is_set():
                out = None
                record["status"] = "STOPPED"
                record["reason"] = "stopped by the operator"
                return record
            r1 = min(height, r0 + strip)
            data = out_band.ReadAsArray(0, r0, width, r1 - r0).astype("float32")
            shift = _shift_for_rows(grid, table, col_low, col_w, row_low, row_w, r0, r1)
            if nodata is None:
                valid = np.isfinite(data)
            elif isinstance(nodata, float) and math.isnan(nodata):
                valid = np.isfinite(data)
            else:
                valid = (data != np.float32(nodata)) & np.isfinite(data)
            data[valid] = data[valid] + shift[valid]
            out_band.WriteArray(data, 0, r0)
            done = r1
            if height > strip and (r0 // strip) % 5 == 4:
                log("  Vertical correction: %d%%" % int(100.0 * done / height))
        out_band.FlushCache()
        out.FlushCache()
        out = None
        record["status"] = "PASS"
        return record
    except Exception as exc:
        record["status"] = "FAIL"
        record["reason"] = summarize_proj_error(exc)
        record["reason_full"] = cap_text(exc)
        return record
    finally:
        out = None
        ds = None
        if record.get("status") != "PASS" and os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        if not previous_gdal:
            gdal.DontUseExceptions()
        if not previous_osr:
            osr.DontUseExceptions()


def prepare_vertical_source(src_path: str, source_vertical: Optional[str], record_dir: Optional[str] = None,
                            log=None, stop_event=None, inspection=None) -> Dict[str, Any]:
    """Decide how the source heights reach EGM2008 and, if needed, correct them.

    Returns ``{"mode", "source", "vertical", "check", "correction", "reason"}``:

      * mode "none"      -- no vertical declared or already EGM2008; use the source as is.
      * mode "direct"    -- the strict PROJ check passed; the converter warps with the
                            compound CRS exactly as before (``vertical`` = declared code).
      * mode "separate"  -- the strict check failed but a verified separate route exists;
                            ``source`` is a corrected temporary copy and ``vertical`` is
                            "3855" (the heights are now EGM2008).
      * mode "failed"    -- nothing safe is available; ``reason`` is short and readable.

    ``record_dir`` receives vertical_operation_check.json and, for mode "separate",
    vertical_correction.json.  The temporary copy lives in a new temp folder
    (``result["temp_dir"]``) under the original file name; call ``cleanup(result)``.
    """
    log = log or (lambda message: None)
    declared = str(source_vertical or "").replace("EPSG:", "")
    result: Dict[str, Any] = {"mode": "none", "source": src_path, "vertical": source_vertical,
                              "check": None, "correction": None, "reason": None, "temp_dir": None}
    if not declared or declared == TARGET_VERTICAL_EPSG:
        return result

    from dem2dged_terrain import check_vertical_operation, inspect_source, write_json
    info = inspection or inspect_source(src_path)
    horizontal = info.horizontal_crs
    check = check_vertical_operation(horizontal or "", declared, extent=info.extent)
    result["check"] = check
    if record_dir:
        os.makedirs(record_dir, exist_ok=True)
        write_json(check, os.path.join(record_dir, "vertical_operation_check.json"))
    if check.get("status") == "PASS":
        result["mode"] = "direct"
        return result

    direct_reason = check.get("reason", "operation unavailable")
    if declared not in SEPARATE_ROUTES:
        result.update(mode="failed", reason=direct_reason)
        return result

    log("  Vertical: the direct PROJ operation is not available (%s)" % direct_reason)
    log("  Vertical: trying the separate correction for EPSG:%s (strict, cross-checked)" % declared)
    temp_dir = tempfile.mkdtemp(prefix="dem2dged_vertical_")
    atexit.register(shutil.rmtree, temp_dir, True)       # fallback if the caller never cleans up
    out_path = os.path.join(temp_dir, os.path.basename(src_path))
    correction = create_corrected_source(src_path, declared, out_path, log=log, stop_event=stop_event)
    correction["direct_check_reason"] = direct_reason
    result["correction"] = correction
    if correction["status"] == "PASS":
        correction["corrected_source_is_temporary"] = True
        result.update(mode="separate", source=out_path, vertical=TARGET_VERTICAL_EPSG,
                      temp_dir=temp_dir)
        if record_dir:
            write_json(correction, os.path.join(record_dir, "vertical_correction.json"))
        log("  Vertical: separate correction applied -> heights are EGM2008 (EPSG:3855); "
            "horizontal georeferencing unchanged")
        return result
    shutil.rmtree(temp_dir, ignore_errors=True)
    result.update(mode="stopped" if correction["status"] == "STOPPED" else "failed",
                  reason="%s Separate correction: %s" % (direct_reason, correction.get("reason")))
    if record_dir:
        write_json(correction, os.path.join(record_dir, "vertical_correction.json"))
    return result


def cleanup(result: Optional[Dict[str, Any]]) -> None:
    """Remove the temporary corrected copy, if any."""
    folder = (result or {}).get("temp_dir")
    if folder:
        shutil.rmtree(folder, ignore_errors=True)
        result["temp_dir"] = None


def route_manifest(result: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, JSON-safe description for conversion manifests and reports."""
    correction = result.get("correction") or {}
    return {
        "mode": result.get("mode"),
        "declared_source_vertical_epsg": (result.get("correction") or {}).get("source_vertical_epsg")
                                         or (result.get("check") or {}).get("source_vertical_epsg"),
        "effective_vertical_epsg_for_conversion": result.get("vertical"),
        "direct_check_status": (result.get("check") or {}).get("status"),
        "direct_check_reason": ((result.get("check") or {}).get("reason")
                                or correction.get("direct_check_reason")),
        "separate_correction": {k: v for k, v in correction.items()
                                if k not in ("reason_full",)} if correction else None,
    }


# ---------------------------------------------------------------------------
# command line: verify the correction on a real file without the GUI
# ---------------------------------------------------------------------------

def compare_heights(src_path: str, out_path: str) -> Dict[str, Any]:
    """Difference (corrected - source) over the cells that are valid in both."""
    import numpy as np
    gdal, _osr = _gdal()
    a = gdal.Open(src_path)
    b = gdal.Open(out_path)
    band_a, band_b = a.GetRasterBand(1), b.GetRasterBand(1)
    nodata_a, nodata_b = band_a.GetNoDataValue(), band_b.GetNoDataValue()
    width, height = a.RasterXSize, a.RasterYSize
    rows = max(1, 4_000_000 // max(1, width))
    low, high, total, count, void_mismatch = math.inf, -math.inf, 0.0, 0, 0
    for r0 in range(0, height, rows):
        r1 = min(height, r0 + rows)
        da = band_a.ReadAsArray(0, r0, width, r1 - r0).astype("float64")
        db = band_b.ReadAsArray(0, r0, width, r1 - r0).astype("float64")
        va = np.isfinite(da) if nodata_a is None else (da != nodata_a) & np.isfinite(da)
        vb = np.isfinite(db) if nodata_b is None else (db != nodata_b) & np.isfinite(db)
        void_mismatch += int(np.count_nonzero(va != vb))
        both = va & vb
        if both.any():
            diff = db[both] - da[both]
            low, high = min(low, float(diff.min())), max(high, float(diff.max()))
            total += float(diff.sum())
            count += int(diff.size)
    return {"valid_cells_compared": count, "difference_min_m": None if not count else low,
            "difference_max_m": None if not count else high,
            "difference_mean_m": None if not count else total / count,
            "cells_valid_in_only_one_raster": void_mismatch}


def main(argv=None) -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(
        description="Apply the separate vertical correction to one DEM and report what it did.")
    parser.add_argument("source", nargs="?", help="the DEM (GeoTIFF)")
    parser.add_argument("--fetch-grids", action="store_true",
                        help="download the geoid grid files for --vertical now (one time) and exit")
    parser.add_argument("--vertical", default="6647", help="declared source vertical EPSG (default 6647)")
    parser.add_argument("--out", help="keep the corrected copy here (default: a temporary file that is deleted)")
    parser.add_argument("--json", action="store_true", help="print the full record as JSON")
    args = parser.parse_args(argv)

    if args.fetch_grids:
        route = SEPARATE_ROUTES.get(str(args.vertical).replace("EPSG:", ""))
        if not route:
            print("no separate route for EPSG:%s" % args.vertical)
            return 2
        gdal, osr = _gdal()
        gdal.UseExceptions()
        osr.UseExceptions()
        info: Dict[str, Any] = {}
        try:
            ensure_grids(route.get("grid_files", []), osr, gdal, info, log=print)
        except Exception as exc:
            print("could not fetch the grid files: %s" % exc)
            return 2
        for item in info.get("grid_files", []):
            print("%s  %.1f MB  sha256 %s\n    %s" % (item["name"], item["bytes"] / 1e6, item["sha256"], item["path"]))
        return 0
    if not args.source:
        parser.error("the DEM to correct is required (or use --fetch-grids)")

    temp_dir = None
    out_path = args.out
    if not out_path:
        temp_dir = tempfile.mkdtemp(prefix="dem2dged_vertical_cli_")
        out_path = os.path.join(temp_dir, os.path.basename(args.source))
    try:
        record = create_corrected_source(args.source, args.vertical, out_path, log=print)
        if record["status"] == "PASS":
            record["comparison"] = compare_heights(args.source, out_path)
        if args.json:
            print(json.dumps(record, indent=2, default=str))
        else:
            print("")
            print("status                 : %s" % record["status"])
            if record.get("reason"):
                print("reason                 : %s" % record["reason"])
            for key in ("cross_check_max_difference_m", "shift_min_m", "shift_max_m", "shift_mean_m"):
                if key in record:
                    print("%-23s: %.4f" % (key, record[key]))
            for item in record.get("grid_files", []):
                print("grid file              : %s (%.1f MB) %s" % (item["name"], item["bytes"] / 1e6, item["path"]))
            if "primary_context" in record:
                print("primary route          : %s" % record["primary_context"]["name"])
                print("cross-check route      : %s" % record["cross_check_context"]["name"])
                print("nodes (rows x columns) : %s x %s" % tuple(record["nodes"]))
            comparison = record.get("comparison")
            if comparison:
                print("corrected - source (m) : min %+.4f  max %+.4f  mean %+.4f  over %d cells"
                      % (comparison["difference_min_m"], comparison["difference_max_m"],
                         comparison["difference_mean_m"], comparison["valid_cells_compared"]))
                print("cells valid in only one: %d (must be 0)" % comparison["cells_valid_in_only_one_raster"])
            if args.out and record["status"] == "PASS":
                print("corrected copy kept at : %s" % args.out)
        return 0 if record["status"] == "PASS" else 2
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    sys.exit(main())
