#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.0
"""Find and clip open independent-reference DEMs for Canada and the US.

WHAT THIS DOES
--------------
Given the extent of your source DEM (or a bounding box), this module asks the
public catalogs below which lidar-derived elevation datasets cover the area,
ranks them, and clips ONLY your area out of the chosen dataset into a small
GeoTIFF that you can use as the "Independent reference" in DEM2DGED.

    Canada : NRCan HRDEM lidar (STAC API, cloud-optimized GeoTIFF on S3)
    US     : USGS 3DEP 1 m / 1/3 arc-second DEM (USGS TNM Access API)

WHAT THIS DOES NOT DO
---------------------
* It never downloads a whole dataset: GDAL reads only the pixels inside the
  window over HTTP range requests (/vsicurl/), and the window size is capped.
* It does not decide that a reference is independent of your source. The
  v0.61.5 content check and your own provenance documents do that.
* It does not measure your output's accuracy or fill in measured values.
* It makes network connections only when you call it. Nothing else in
  DEM2DGED uses the network.

The accuracy numbers in reference_catalog.json are the providers' declared
product accuracies, not something this tool measures.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.62.0"
CATALOG_NAME = "reference_catalog.json"
SIDECAR_SCHEMA = "dem2dged-reference/1"
USER_AGENT = "DEM2DGED/%s reference-finder (+GPL-2.0-or-later)" % VERSION
LE90_FROM_RMSE = 1.645
DEFAULT_MAX_CELLS = 40_000_000       # ~160 MB as Float32 before compression
DEFAULT_BUFFER_DEG = 0.0005          # ~50 m, so edge posts are covered
SUITABILITY_RATIO = 3.0              # reference LE90 <= level limit / 3

# Rough country boxes (minlon, minlat, maxlon, maxlat). Only used to decide
# which catalogs to ask, never to make any accuracy statement.
COUNTRY_BOXES = {
    "CA": [(-141.2, 41.5, -52.0, 83.5)],
    "US": [(-125.0, 24.0, -66.0, 50.0),        # contiguous
           (-170.0, 51.0, -129.0, 72.0),       # Alaska
           (-161.0, 18.5, -154.0, 22.5)],      # Hawaii
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class StepLog:
    """Collects timestamped lines; optionally mirrors to a file and callback."""

    def __init__(self, path=None, callback=None, echo=True):
        self.lines = []
        self.path = path
        self.callback = callback
        self.echo = echo
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def __call__(self, message):
        line = "%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), message)
        self.lines.append(line)
        if self.echo:
            print(line, flush=True)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        if self.callback:
            try:
                self.callback(line)
            except Exception:
                pass


def _null_log(_message):
    pass


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def _search_folders():
    here = os.path.dirname(os.path.abspath(__file__))
    folders = []
    if getattr(sys, "frozen", False):
        folders.append(os.path.dirname(sys.executable))
        if getattr(sys, "_MEIPASS", None):
            folders.append(sys._MEIPASS)
    folders += [here, os.path.dirname(here), os.getcwd()]
    return folders


def find_catalog():
    for folder in _search_folders():
        candidate = os.path.join(folder, CATALOG_NAME)
        if os.path.isfile(candidate):
            return candidate
    return None


def load_catalog(path=None):
    path = path or find_catalog()
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(
            "%s not found next to the program. Re-extract the release." % CATALOG_NAME)
    with open(path, encoding="utf-8") as stream:
        catalog = json.load(stream)
    if catalog.get("schema") != "dem2dged-reference-catalog/1":
        raise ValueError("unsupported catalog schema: %s" % catalog.get("schema"))
    catalog["_path"] = path
    return catalog


# ---------------------------------------------------------------------------
# Geometry helpers (GDAL imported lazily so the module can be imported
# without it for text-only uses)
# ---------------------------------------------------------------------------

def _gdal():
    from osgeo import gdal, osr
    gdal.UseExceptions()
    osr.UseExceptions()
    return gdal, osr


def _wgs84(osr):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def dataset_srs(ds, osr):
    srs = osr.SpatialReference()
    srs.ImportFromWkt(ds.GetProjection())
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def transform_bbox(bbox, src_srs, dst_srs, osr, samples=21):
    """Transform a (minx, miny, maxx, maxy) box by densifying its edges."""
    transform = osr.CoordinateTransformation(src_srs, dst_srs)
    minx, miny, maxx, maxy = bbox
    points = []
    for i in range(samples):
        t = i / (samples - 1.0)
        x = minx + t * (maxx - minx)
        y = miny + t * (maxy - miny)
        points += [(x, miny), (x, maxy), (minx, y), (maxx, y)]
    xs, ys = [], []
    for x, y in points:
        px, py = transform.TransformPoint(x, y)[:2]
        if math.isfinite(px) and math.isfinite(py):
            xs.append(px)
            ys.append(py)
    if not xs:
        raise ValueError("bounding box could not be transformed")
    return (min(xs), min(ys), max(xs), max(ys))


def extent_wgs84(raster_path, buffer_deg=DEFAULT_BUFFER_DEG):
    """Return the raster's extent as a buffered WGS-84 (minlon, minlat, maxlon, maxlat)."""
    gdal, osr = _gdal()
    ds = gdal.Open(raster_path)
    try:
        gt = ds.GetGeoTransform()
        width, height = ds.RasterXSize, ds.RasterYSize
        minx, maxx = sorted((gt[0], gt[0] + gt[1] * width + gt[2] * height))
        miny, maxy = sorted((gt[3], gt[3] + gt[4] * width + gt[5] * height))
        wkt = ds.GetProjection()
        if not wkt:
            raise ValueError("source raster has no coordinate system: %s" % raster_path)
        srs = dataset_srs(ds, osr)
    finally:
        ds = None
    box = transform_bbox((minx, miny, maxx, maxy), srs, _wgs84(osr), osr)
    return (box[0] - buffer_deg, box[1] - buffer_deg,
            box[2] + buffer_deg, box[3] + buffer_deg)


def bbox_intersects(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def bbox_contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1] and
            outer[2] >= inner[2] and outer[3] >= inner[3])


def countries_for_bbox(bbox):
    found = []
    for code, boxes in COUNTRY_BOXES.items():
        if any(bbox_intersects(bbox, box) for box in boxes):
            found.append(code)
    return found


# ---------------------------------------------------------------------------
# Suitability
# ---------------------------------------------------------------------------

def suitability(vertical_le90_m, level):
    """Return (code, text). Rule of thumb: reference LE90 <= level limit / 3."""
    from dem2dged_compliance import DGED_LEVEL_REQUIREMENTS
    key = str(level).lower().replace("level", "").strip()
    requirement = DGED_LEVEL_REQUIREMENTS.get(key)
    if requirement is None:
        return ("UNKNOWN", "Unknown DGED level %r." % level)
    limit = requirement.get("vertical_random_90_m")
    if vertical_le90_m is None:
        return ("UNKNOWN", "Declared accuracy not known; read the dataset metadata.")
    if limit is None:
        return ("NO_LIMIT", "Level %s has no vertical random-error limit; a 3:1 test "
                "does not apply." % key)
    needed = limit / SUITABILITY_RATIO
    if vertical_le90_m <= needed:
        return ("OK", "Declared LE90 %.2f m <= %.2f m (level %s vertical random 90%% "
                "%.2f m / %.0f)." % (vertical_le90_m, needed, key, limit, SUITABILITY_RATIO))
    if vertical_le90_m <= limit / 2.0:
        return ("MARGINAL", "Declared LE90 %.2f m is between limit/3 and limit/2 (%.2f-%.2f m) "
                "for level %s: usable as a rough check only; the reference error is a large "
                "part of what you would measure." % (vertical_le90_m, needed, limit / 2.0, key))
    return ("TOO_COARSE", "Declared LE90 %.2f m is above %.2f m (level %s vertical random "
            "90%% %.2f m / %.0f): not accurate enough to judge this level." %
            (vertical_le90_m, needed, key, limit, SUITABILITY_RATIO))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def http_get_json(url, params=None, timeout=45, retries=2, log=_null_log):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=",()/ ")
    last = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            return json.loads(payload.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last = exc
            log("  request failed (attempt %d/%d): %s" % (attempt + 1, retries + 1, exc))
            time.sleep(1.0 + attempt)
    raise RuntimeError("could not read %s: %s" % (url, last))


# ---------------------------------------------------------------------------
# Catalog queries
# ---------------------------------------------------------------------------

_RES_RE = re.compile(r"-(\d+(?:\.\d+)?)m(?:\b|-|_|$)")


def _resolution_from_id(identifier):
    match = _RES_RE.search(identifier or "")
    return float(match.group(1)) if match else None


def query_stac(source, bbox, log=_null_log, limit=50):
    url = source["stac_items_url"]
    params = {"bbox": "%.6f,%.6f,%.6f,%.6f" % bbox, "limit": str(limit)}
    log("Canada STAC query: %s?%s" % (url, urllib.parse.urlencode(params, safe=",")))
    data = http_get_json(url, params, log=log)
    features = data.get("features") or []
    log("  STAC returned %d dataset(s)" % len(features))
    if features:
        log("  first item keys: %s" % sorted(features[0].keys()))
    results = []
    for item in features:
        assets = item.get("assets") or {}
        item_bbox = tuple(item.get("bbox") or ())[:4]
        props = item.get("properties") or {}
        results.append({
            "source_id": source["id"],
            "country": source["country"],
            "item_id": item.get("id"),
            "title": item.get("id"),
            "date": (props.get("datetime") or "")[:10],
            "resolution_m": _resolution_from_id(item.get("id")),
            "epsg": props.get("proj:epsg"),
            "item_bbox": item_bbox if len(item_bbox) == 4 else None,
            "covers_whole_box": bool(len(item_bbox) == 4 and bbox_contains(item_bbox, bbox)),
            "hrefs": {
                "dtm": (assets.get("dtm") or {}).get("href"),
                "dsm": (assets.get("dsm") or {}).get("href"),
            },
            "size_bytes": None,
        })
    return results


def query_tnm(source, bbox, log=_null_log, max_items=50):
    url = source["tnm_products_url"]
    params = {
        "datasets": source["tnm_dataset"],
        "bbox": "%.6f,%.6f,%.6f,%.6f" % bbox,
        "max": str(max_items),
        "outputFormat": "JSON",
    }
    log("US TNM query: %s dataset=%r" % (url, source["tnm_dataset"]))
    data = http_get_json(url, params, log=log)
    items = data.get("items") or []
    log("  TNM total=%s, returned=%d" % (data.get("total"), len(items)))
    if items:
        log("  first item keys: %s" % sorted(items[0].keys()))
    results = []
    for item in items:
        href = item.get("downloadURL") or ""
        if not href:
            urls = item.get("urls") or {}
            href = urls.get("GeoTIFF") or next(iter(urls.values()), "")
        if not href.lower().endswith((".tif", ".tiff")):
            continue
        box = item.get("boundingBox") or {}
        try:
            item_bbox = (float(box["minX"]), float(box["minY"]),
                         float(box["maxX"]), float(box["maxY"]))
        except (KeyError, TypeError, ValueError):
            item_bbox = None
        title = item.get("title") or os.path.basename(href)
        res = _resolution_from_id(href) or _resolution_from_id(title)
        if res is None and "1 meter" in source["tnm_dataset"]:
            res = 1.0
        if res is None and "1/3 arc" in source["tnm_dataset"]:
            res = 10.0        # nominal (about 10 m)
        results.append({
            "source_id": source["id"],
            "country": source["country"],
            "item_id": item.get("sourceId") or os.path.basename(href),
            "title": title,
            "date": (item.get("publicationDate") or "")[:10],
            "resolution_m": res,
            "epsg": None,
            "item_bbox": item_bbox,
            "covers_whole_box": bool(item_bbox and bbox_contains(item_bbox, bbox)),
            "hrefs": {"dtm": href, "dsm": None},
            "size_bytes": item.get("sizeInBytes"),
        })
    return results


MIN_COVERAGE = 0.9          # a candidate must have data over at least this much of the box
MAX_PROBES = 14


def find_candidates(bbox, level=None, catalog=None, countries=None, log=_null_log,
                    probe=True):
    """Query the catalogs that match the box. Errors are logged, never raised.

    With probe=True each of the best candidates is sampled to measure how much
    of the box really holds heights ("coverage"); candidates with no data in
    the box sort to the bottom.
    """
    catalog = catalog or load_catalog()
    countries = countries or countries_for_bbox(bbox)
    log("Search box (lon/lat): %.5f %.5f %.5f %.5f   countries: %s" %
        (bbox + (", ".join(countries) or "none",)))
    out, errors = [], []
    for source in catalog["sources"]:
        if source["country"] not in countries:
            continue
        try:
            if source["kind"] == "stac":
                found = query_stac(source, bbox, log)
            elif source["kind"] == "tnm":
                found = query_tnm(source, bbox, log)
            else:
                continue
        except Exception as exc:
            log("  %s query failed: %s" % (source["id"], exc))
            errors.append({"source_id": source["id"], "error": str(exc)})
            continue
        for cand in found:
            cand["source"] = {k: source.get(k) for k in (
                "id", "provider", "product", "vertical_le90_m", "accuracy_statement",
                "vertical_datum", "license", "spec_url", "limits")}
            code, text = (suitability(source.get("vertical_le90_m"), level)
                          if level is not None else ("UNKNOWN", "No level selected."))
            cand["suitability"] = code
            cand["suitability_text"] = text
        out.extend(found)
    out.sort(key=_rank_key)
    if probe and out:
        log("Checking real data coverage of the best %d candidate(s) (small sample reads)..."
            % min(len(out), MAX_PROBES))
        for cand in out[:MAX_PROBES]:
            href = cand["hrefs"].get("dtm")
            result = probe_coverage(href, bbox, log) if href else {"valid_fraction": None}
            cand["coverage"] = result["valid_fraction"]
            log("  %s: coverage %s" % (cand["title"],
                "%.0f%%" % (100 * result["valid_fraction"])
                if result["valid_fraction"] is not None else "unknown"))
        out.sort(key=_rank_key)
    for index, cand in enumerate(out, 1):
        cand["number"] = index
    return out, errors


def _rank_key(cand):
    suit_order = {"OK": 0, "NO_LIMIT": 1, "MARGINAL": 2, "UNKNOWN": 3, "TOO_COARSE": 4}
    cov = cand.get("coverage")
    cov_rank = 0 if (cov is None or cov >= MIN_COVERAGE) else (1 if cov > 0 else 2)
    return (cov_rank,
            suit_order.get(cand.get("suitability"), 3),
            0 if cand.get("covers_whole_box") else 1,
            cand.get("resolution_m") if cand.get("resolution_m") else 999.0,
            "".join(chr(255 - ord(c)) for c in (cand.get("date") or "")))


def describe_candidate(cand):
    src = cand["source"]
    res = cand.get("resolution_m")
    size = cand.get("size_bytes")
    cov = cand.get("coverage")
    return ("#%d  %s | %s | %s | %s | LE90 %s | %s | %s | data %s" % (
        cand["number"], cand["country"], cand["title"],
        ("%g m" % res) if res else "res ?",
        cand.get("date") or "date ?",
        ("%.2f m" % src["vertical_le90_m"]) if src.get("vertical_le90_m") else "n/a",
        src.get("vertical_datum"), cand["suitability"],
        ("%.0f%%" % (100 * cov)) if cov is not None else "?") +
        ((" | tile %.0f MB" % (size / 1e6)) if isinstance(size, (int, float)) else ""))


# ---------------------------------------------------------------------------
# Clip
# ---------------------------------------------------------------------------

def _open_remote(href, gdal):
    if re.match(r"^https?://", href, re.I):
        gdal.SetConfigOption("GDAL_HTTP_USERAGENT", USER_AGENT)
        gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
        gdal.SetConfigOption("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff,.vrt")
        gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "3")
        gdal.SetConfigOption("GDAL_HTTP_RETRY_DELAY", "2")
        gdal.SetConfigOption("GDAL_HTTP_TIMEOUT", "60")
        return gdal.Open("/vsicurl/" + href)
    return gdal.Open(href)          # local file (tests)


def _window_for_bbox(ds, bbox, gdal, osr):
    """Pixel window (xoff, yoff, xsize, ysize) of a WGS-84 box inside ds."""
    gt = ds.GetGeoTransform()
    if abs(gt[2]) > 1e-12 or abs(gt[4]) > 1e-12:
        raise RuntimeError("rotated rasters are not supported")
    srs = dataset_srs(ds, osr)
    native = transform_bbox(bbox, _wgs84(osr), srs, osr)
    x0 = (native[0] - gt[0]) / gt[1]
    x1 = (native[2] - gt[0]) / gt[1]
    y0 = (native[1] - gt[3]) / gt[5]
    y1 = (native[3] - gt[3]) / gt[5]
    xoff = max(0, int(math.floor(min(x0, x1))))
    yoff = max(0, int(math.floor(min(y0, y1))))
    xend = min(ds.RasterXSize, int(math.ceil(max(x0, x1))))
    yend = min(ds.RasterYSize, int(math.ceil(max(y0, y1))))
    return xoff, yoff, xend - xoff, yend - yoff


def probe_coverage(href, bbox, log=_null_log, sample=96):
    """Cheaply estimate how much of the box holds valid heights in a dataset.

    A dataset's footprint (bounding box) can be much larger than the area it
    really has data for, so a candidate must be probed before it is trusted.
    Reads a coarse nearest-neighbour sample of the window (at most
    sample x sample cells). Returns {"valid_fraction": float|None, "error": str|None}.
    """
    import numpy as np
    gdal, osr = _gdal()
    try:
        ds = _open_remote(href, gdal)
        if ds is None:
            raise RuntimeError("could not open dataset")
        xoff, yoff, xsize, ysize = _window_for_bbox(ds, bbox, gdal, osr)
        if xsize <= 0 or ysize <= 0:
            return {"valid_fraction": 0.0, "error": None}
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        bx, by = min(sample, xsize), min(sample, ysize)
        array = band.ReadAsArray(xoff, yoff, xsize, ysize, buf_xsize=bx, buf_ysize=by,
                                 resample_alg=gdal.GRIORA_NearestNeighbour).astype("float64")
        mask = np.isfinite(array)
        if nodata is not None:
            mask &= (array != nodata)
        return {"valid_fraction": float(mask.mean()), "error": None}
    except Exception as exc:
        log("  coverage probe failed for %s: %s" % (href, exc))
        return {"valid_fraction": None, "error": str(exc)}


def clip_window(href, bbox, out_path, max_cells=DEFAULT_MAX_CELLS, log=_null_log):
    """Copy only the pixels inside bbox (WGS-84) to out_path. No resampling."""
    gdal, osr = _gdal()
    log("Opening %s" % href)
    ds = _open_remote(href, gdal)
    if ds is None:
        raise RuntimeError("could not open dataset")
    gt = ds.GetGeoTransform()
    srs = dataset_srs(ds, osr)
    log("  dataset: %d x %d cells, pixel %.4g x %.4g, CRS %s" % (
        ds.RasterXSize, ds.RasterYSize, gt[1], gt[5],
        srs.GetAuthorityCode(None) or srs.GetName()))
    xoff, yoff, xsize, ysize = _window_for_bbox(ds, bbox, gdal, osr)
    xend, yend = xoff + xsize, yoff + ysize
    if xsize <= 0 or ysize <= 0:
        raise RuntimeError("the search box does not overlap this dataset")
    cells = xsize * ysize
    log("  window: x %d..%d, y %d..%d  = %d x %d = %.1f million cells" % (
        xoff, xend, yoff, yend, xsize, ysize, cells / 1e6))
    if cells > max_cells:
        raise RuntimeError(
            "window of %.1f million cells exceeds the limit of %.1f million; use a "
            "smaller area or raise --max-cells" % (cells / 1e6, max_cells / 1e6))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    options = ["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"]
    band = ds.GetRasterBand(1)
    if band.DataType in (gdal.GDT_Float32, gdal.GDT_Float64):
        options.append("PREDICTOR=3")
    started = time.time()
    out = gdal.Translate(out_path, ds, srcWin=[xoff, yoff, xsize, ysize],
                         creationOptions=options)
    out.FlushCache()
    stats = raster_stats(out)
    out = None
    ds = None
    log("  wrote %s (%.1f MB) in %.1f s; valid cells %.1f%%" % (
        out_path, os.path.getsize(out_path) / 1e6, time.time() - started,
        100.0 * stats["valid_fraction"]))
    return stats


def raster_stats(ds):
    import numpy as np
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    array = band.ReadAsArray().astype("float64")
    mask = np.isfinite(array)
    if nodata is not None:
        mask &= (array != nodata)
    valid = array[mask]
    return {
        "columns": ds.RasterXSize, "rows": ds.RasterYSize,
        "nodata": nodata,
        "valid_fraction": float(mask.mean()) if mask.size else 0.0,
        "min": float(valid.min()) if valid.size else None,
        "max": float(valid.max()) if valid.size else None,
        "mean": float(valid.mean()) if valid.size else None,
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Sidecar and GUI hand-off
# ---------------------------------------------------------------------------

def write_sidecar(out_path, cand, product, bbox, stats, source_path=None,
                  source_vertical_epsg=None, level=None):
    src = cand["source"]
    sha = sha256_file(out_path)
    identifier = "%s %s (%s, %s) clip sha256:%s" % (
        src["id"], cand["item_id"], product.upper(), cand.get("date") or "date unknown",
        sha[:12])
    warnings = []
    if source_vertical_epsg and src.get("vertical_datum"):
        warnings.append(
            "Vertical datum check: your source vertical EPSG is %s; this reference is "
            "%s. If they differ, the heights are offset by the geoid/datum difference "
            "(decimetres to metres) and absolute accuracy statistics will be wrong "
            "unless one of them is converted." % (source_vertical_epsg, src["vertical_datum"]))
    else:
        warnings.append(
            "Vertical datum: this reference uses %s. Make sure your source and output "
            "use the same vertical datum before judging accuracy." % src.get("vertical_datum"))
    if product == "dsm":
        warnings.append("DSM includes trees and buildings; DGED terrain products are "
                        "normally judged against bare earth (DTM).")
    if stats.get("valid_fraction", 1.0) < 0.95:
        warnings.append("Only %.0f%% of the clip has valid heights; the dataset does not "
                        "cover your whole area." % (100 * stats["valid_fraction"]))
    warnings.append("Independence is NOT proven by this download. Confirm your source DEM "
                    "was not made from the same survey.")
    sidecar = {
        "schema": SIDECAR_SCHEMA,
        "tool_version": VERSION,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z",
        "file": os.path.basename(out_path),
        "sha256": sha,
        "reference_identifier": identifier,
        "product": product,
        "source_id": src["id"],
        "provider": src["provider"],
        "dataset_id": cand["item_id"],
        "dataset_date": cand.get("date"),
        "dataset_href": cand["hrefs"].get(product) or cand["hrefs"].get("dtm"),
        "declared_vertical_le90_m": src.get("vertical_le90_m"),
        "accuracy_statement": src.get("accuracy_statement"),
        "vertical_datum": src.get("vertical_datum"),
        "license": src.get("license"),
        "spec_url": src.get("spec_url"),
        "suitability_for_level": {"level": level, "result": cand.get("suitability"),
                                  "text": cand.get("suitability_text")},
        "search_box_wgs84": list(bbox),
        "source_raster": source_path,
        "clip_stats": stats,
        "coverage_estimate_before_clip": cand.get("coverage"),
        "warnings": warnings,
        "note": "Declared accuracy comes from the provider, not from DEM2DGED.",
    }
    path = os.path.splitext(out_path)[0] + "_reference.json"
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(sidecar, stream, indent=2)
    return path, sidecar


# ---------------------------------------------------------------------------
# One-call workflow
# ---------------------------------------------------------------------------

def clip_candidate(cand, bbox, out_dir, product="dtm", level=None, max_cells=DEFAULT_MAX_CELLS,
                   source_path=None, source_vertical_epsg=None, log=_null_log):
    """Clip one candidate. Returns {"output", "sidecar", "stats"}."""
    href = cand["hrefs"].get(product) or cand["hrefs"].get("dtm")
    if not href:
        raise RuntimeError("candidate has no %s asset" % product)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", cand["title"] or cand["item_id"])[:80]
    out_path = os.path.join(out_dir, "reference_%s_%s.tif" % (safe, product))
    stats = clip_window(href, bbox, out_path, max_cells, log)
    sidecar_path, _ = write_sidecar(out_path, cand, product, bbox, stats, source_path,
                                    source_vertical_epsg, level)
    log("Sidecar: %s" % sidecar_path)
    return {"output": out_path, "sidecar": sidecar_path, "stats": stats}


def fetch_reference(source_path=None, bbox=None, out_dir=".", level=None, countries=None,
                    pick=None, product="dtm", max_cells=DEFAULT_MAX_CELLS,
                    list_only=False, source_vertical_epsg=None, catalog=None,
                    probe=True, log=_null_log):
    """Find candidates and (unless list_only) clip one.

    pick=None chooses the best-ranked candidate whose real data coverage of the
    box is at least MIN_COVERAGE. pick=N forces candidate number N.
    Returns a dict: candidates, errors, chosen, output, sidecar, stats.
    """
    result = {"candidates": [], "errors": [], "chosen": None, "output": None,
              "sidecar": None, "stats": None}
    if bbox is None:
        if not source_path:
            raise ValueError("give a source raster or a bounding box")
        bbox = extent_wgs84(source_path)
    result["bbox"] = list(bbox)
    candidates, errors = find_candidates(bbox, level, catalog, countries, log, probe)
    result["candidates"], result["errors"] = candidates, errors
    log("%d candidate dataset(s):" % len(candidates))
    for cand in candidates:
        log("  " + describe_candidate(cand))
    if list_only or not candidates:
        if not candidates:
            log("No candidates found. The area may be outside Canada/US coverage, or the "
                "catalog service could not be reached.")
        return result
    if pick is None:
        chosen = next((c for c in candidates
                       if c.get("coverage") is None or c["coverage"] >= MIN_COVERAGE), None)
        if chosen is None:
            best = max(candidates, key=lambda c: c.get("coverage") or 0.0)
            raise RuntimeError(
                "No dataset has data over the whole area. Best coverage is %.0f%% (%s). "
                "Use a smaller area or force a candidate with --pick." % (
                    100 * (best.get("coverage") or 0.0), best["title"]))
    else:
        if pick < 1 or pick > len(candidates):
            raise ValueError("--pick must be between 1 and %d" % len(candidates))
        chosen = candidates[pick - 1]
    log("Chosen: " + describe_candidate(chosen))
    result.update(clip_candidate(chosen, bbox, out_dir, product, level, max_cells,
                                 source_path, source_vertical_epsg, log))
    result["chosen"] = chosen
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Find and clip an open independent-reference DEM (Canada / US).")
    parser.add_argument("--source", help="your source DEM (its extent is the search area)")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    parser.add_argument("--out-dir", default="references")
    parser.add_argument("--level", help="DGED level for the suitability check, e.g. 6")
    parser.add_argument("--country", action="append", choices=["CA", "US"])
    parser.add_argument("--list", action="store_true", help="list candidates, download nothing")
    parser.add_argument("--pick", type=int, default=None,
                        help="candidate number to clip (default: best with real data coverage)")
    parser.add_argument("--no-probe", action="store_true", help="skip the data-coverage check")
    parser.add_argument("--product", choices=["dtm", "dsm"], default="dtm")
    parser.add_argument("--max-cells", type=int, default=DEFAULT_MAX_CELLS)
    parser.add_argument("--source-vertical-epsg")
    parser.add_argument("--log", help="log file")
    args = parser.parse_args(argv)
    log = StepLog(args.log)
    try:
        result = fetch_reference(
            args.source, tuple(args.bbox) if args.bbox else None, args.out_dir, args.level,
            args.country, args.pick, args.product, args.max_cells, args.list,
            args.source_vertical_epsg, probe=not args.no_probe, log=log)
    except Exception as exc:
        log("ERROR: %s" % exc)
        return 1
    return 0 if (result["candidates"] and (args.list or result["output"])) else 2


if __name__ == "__main__":
    sys.exit(main())
