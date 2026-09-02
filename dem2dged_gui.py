# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.57.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

import sys, os, math, threading, queue, time

# ── Fix GDAL / PROJ data paths when running as a frozen PyInstaller exe ───────
if getattr(sys, "frozen", False):
    _base = sys._MEIPASS
    gdal_path = os.path.join(_base, "gdal")
    proj_path = os.path.join(_base, "proj")
    print("DEBUG: Frozen exe detected")
    print("DEBUG: sys._MEIPASS =", _base)
    print("DEBUG: GDAL data path =", gdal_path, " (exists: %s)" % os.path.isdir(gdal_path))
    print("DEBUG: PROJ data path =", proj_path, " (exists: %s)" % os.path.isdir(proj_path))
    os.environ.setdefault("GDAL_DATA", gdal_path)
    os.environ.setdefault("PROJ_LIB", proj_path)
    os.environ.setdefault("PROJ_DATA", proj_path)
else:
    print("DEBUG: Running as script (not frozen)")

try:
    from osgeo import gdal, ogr, osr
    # v0.41: the gdal.UseExceptions() that used to be here is gone on
    # purpose. gdal/ogr/osr share ONE global exception flag, and
    # dem2dged_lib.py (imported just below) pins it for the whole project --
    # see its header for why OFF is the right setting and why measuring
    # beat assuming here. Calling it here as well only made the GUI and the
    # CLI disagree about how the SAME library code reports a bad raster,
    # depending on nothing but import order.
    # Required so GDAL writes compound CRS into GeoTIFF headers correctly
    gdal.SetConfigOption('GTIFF_REPORT_COMPD_CS', 'YES')
    print("DEBUG: GDAL imported successfully")
except ImportError as e:
    print("ERROR: Failed to import GDAL/osgeo: %s" % e)
    print("Make sure GDAL/osgeo is installed in the Python environment")
    raise

# Shared tile logic (extents, data types, naming, sidecar/TOC/collection
# writing) -- the CLI converters (dem2dged_geo.py / dem2dged_utm.py) import
# this same module for the same functions (v0.28; see module docstring).
import dem2dged_lib as dl

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# Project version — single source lives in dem2dged_lib.py
try:
    from dem2dged_lib import VERSION as APP_VERSION, VERSION_DISPLAY as APP_VERSION_DISPLAY
except Exception:
    APP_VERSION = "0.57.0"   # fallback; keep in sync with dem2dged_lib.VERSION
    APP_VERSION_DISPLAY = "0.57.0"

# Validator — used to auto-generate a report right after conversion.
# Imported at module level (not lazily) so PyInstaller's static analysis
# bundles it into dem2dged.exe automatically; if it's ever unavailable the
# "Validate after conversion" checkbox is simply disabled.
try:
    import dem2dged_validate as dv
    _VALIDATE_AVAILABLE = True
except Exception:
    dv = None
    _VALIDATE_AVAILABLE = False

# Resampling comparison (v0.33) — imported at module level for the same
# PyInstaller-bundling reason as the validator above; if unavailable the
# "Resampling Comparison Test" checkboxes are simply disabled.
try:
    import dem2dged_compare as dc
    _COMPARE_AVAILABLE = True
except Exception:
    dc = None
    _COMPARE_AVAILABLE = False

# GUI resampling dropdown (v0.33): (gdalwarp_alg_or_auto, display label).
# "auto" keeps the validator-safe automatic choice used since v0.20
# (average when downsampling, else bilinear — see dl.pick_resampler).
RESAMPLING_OPTIONS = [
    ("auto",     "Auto  (recommended)"),
    ("optimize", "Optimize  (measure and pick the most accurate)"),
    ("near",     "Nearest Neighbor"),
    ("bilinear", "Bilinear Interpolation"),
    ("cubic",    "Cubic Convolution"),
]

# GUI anti-alias pre-filter dropdown (v0.56): (code, display label).
#
# The Gaussian pre-filter shipped in v0.49 as a CLI-only feature
# (-prefilter / -prefilter_sigma). The GUI never gained it, so the headline
# capability of that release was unreachable for every operator who works
# from the window rather than the prompt -- and nothing said so. "none" is
# the default here exactly as it is on the command line, so a GUI run that
# leaves this alone produces bit-identical tiles to every previous version.
#
# v0.57: the label used to read "for high-relief downsampling", framing it
# as an accuracy improvement for exactly the terrain type it turns out to
# hurt most -- see dl.VALID_PREFILTERS' v0.57 CORRECTION note. Reworded so
# the dropdown itself doesn't repeat the retracted claim.
PREFILTER_OPTIONS = [
    ("none",     "None  (default, recommended for point accuracy)"),
    ("gaussian", "Gaussian anti-alias  (may reduce visual banding; can "
                "increase vertical error -- see docs)"),
]

# ── DGED tables (v0.34) ──────────────────────────────────────────────────────
# Imported unconditionally from dem2dged_lib, the single source of truth.
#
# Until v0.34 this was wrapped in a try/except ImportError with a hand-copied
# fallback table. That fallback still carried the PRE-v0.27 values for levels
# 8 and 9 -- (1 min, "G") instead of the current (1.5 min, "F"). With a
# 1-minute tile, latitude zones 2 (50-60 deg) and 4 (70-80 deg) give a
# NON-INTEGER number of longitude intervals per tile (5333.33 and 2666.67),
# so tile origins cannot sit on the longitude post grid -- exactly the
# post-misalignment bug v0.27 fixed -- and the tile letter in the filename
# was wrong too. v0.28 deleted the validator's equivalent fallback for
# precisely this reason ("a hand-copied duplicate would only be exercised on
# this error path, where nothing would ever notice it silently drifting out
# of sync"); this copy was missed.
#
# It was also dead code: `import dem2dged_lib as dl` above is unguarded, so
# if dem2dged_lib were unimportable the GUI would already have died there and
# this fallback could never run. Failing loudly beats validating -- or
# converting -- against numbers nobody is maintaining.
_LEVEL_GSD_LABEL = {
    "0": "1000 m", "1": "100 m", "2": "30 m", "3": "12 m",
    "4b": "5 m", "4": "4 m", "5": "2 m  ★ default", "6": "1 m",
    "7": "0.5 m", "8": "0.25 m", "9": "0.125 m",
}

ZONE_LON_SPACING = dl.zone_lon_spacing
GEO_LEVELS = [
    (r[0], r[1], r[2], r[3], "~" + _LEVEL_GSD_LABEL.get(r[0], "?"))
    for r in dl.level_tilesize_and_spatial_resolution
]
UTM_LEVELS = [
    (r[0], r[1], r[2], r[3], "~" + _LEVEL_GSD_LABEL.get(r[0], "?"))
    for r in dl.PL
]

LEVEL_DISPLAY = {r[0]: "%s  (%s)" % (r[0], r[-1]) for r in GEO_LEVELS}


# ═══════════════════════════════════════════════════════════════════════════════
#  CONVERSION LOGIC  (pure Python / GDAL API — no subprocess)
# ═══════════════════════════════════════════════════════════════════════════════

def _lon_multi(lat):
    m = 1
    for l in ZONE_LON_SPACING:
        if lat >= l[1]:
            m = l[4]
    return m

def _geo_level(lvl):
    for l in GEO_LEVELS:
        if l[0] == lvl:
            return l[1]/60, l[2]/3600, l[3]
    raise RuntimeError("Unknown GEO product level: %s" % lvl)

def _utm_level(lvl):
    for l in UTM_LEVELS:
        if l[0] == lvl:
            return l[1], l[2], l[3]
    raise RuntimeError(
        "Unknown UTM product level: %s (levels 0-3 exist only for GEO)" % lvl)

def _to_dms(dd):
    # Round to 1/10000 arcsec to avoid 59.999… float artefacts.
    total_sec = round(abs(float(dd)) * 3600, 4)
    d = int(total_sec // 3600)
    rem = total_sec - d * 3600
    m = int(rem // 60)
    s = rem - m * 60
    return (-d if dd < 0 else d), m, s

def _get_extent(path):
    ds = dl.gdal_open(path)
    if ds is None:
        raise RuntimeError("Cannot open: %s" % path)
    ulx, xr, _, uly, _, yr = ds.GetGeoTransform()
    lrx = ulx + ds.RasterXSize * xr
    lry = uly + ds.RasterYSize * yr
    srs = osr.SpatialReference(wkt=ds.GetProjection())
    epsg = srs.GetAttrValue("AUTHORITY", 1)
    if srs.IsGeographic():
        return uly, ulx, lry, lrx, epsg   # lat/lon order
    return ulx, uly, lrx, lry, epsg

def _bbox_in_srs(ext, target_epsg):
    src = osr.SpatialReference(); src.ImportFromEPSG(int(ext[4]))
    tgt = osr.SpatialReference(); tgt.ImportFromEPSG(target_epsg)
    xf  = osr.CoordinateTransformation(src, tgt)
    pts = [
        ogr.CreateGeometryFromWkt("POINT (%s %s)" % (ext[0], ext[3])),
        ogr.CreateGeometryFromWkt("POINT (%s %s)" % (ext[0], ext[1])),
        ogr.CreateGeometryFromWkt("POINT (%s %s)" % (ext[2], ext[1])),
        ogr.CreateGeometryFromWkt("POINT (%s %s)" % (ext[2], ext[3])),
    ]
    xy = []
    for p in pts:
        p.Transform(xf); xy.append((p.GetX(), p.GetY()))
    # Use ALL FOUR reprojected corners: under a rotated/oblique transform the
    # extremes are not always on the diagonally opposite corners, so taking
    # only xy[0]/xy[2] can under-cover the extent and drop edge tiles. This
    # matches dem2dged_lib.get_bbox_of_output.
    xs = [c[0] for c in xy]
    ys = [c[1] for c in xy]
    return min(xs), max(xs), min(ys), max(ys)

def _autodetect_utm(ext):
    cx = (ext[0]+ext[2])/2;  cy = (ext[1]+ext[3])/2
    s = osr.SpatialReference(); s.ImportFromEPSG(int(ext[4]))
    w = osr.SpatialReference(); w.ImportFromEPSG(4326)
    xf = osr.CoordinateTransformation(s, w)
    p  = ogr.CreateGeometryFromWkt("POINT (%s %s)" % (cx, cy))
    p.Transform(xf)
    lon, lat = p.GetY(), p.GetX()
    zone = math.floor((lon+180)/6)+1
    ns   = "7" if lat < 0 else "6"
    # Zero-pad the zone: zone 9 N must give 32609, not 3269
    return int("32%s%02d" % (ns, zone)), zone, ("S" if lat<0 else "N")

def _gdal_dtype_for_level(level):
    """Map dem2dged_lib's data-type policy ("Int16"/"Float32") to the
    matching gdal.GDT_* constant the Python Warp API wants (v0.28: the GUI
    used to hardcode GDT_Float32 for every level, which violated the spec's
    mandatory Int16 for levels 0-2 -- see dem2dged_lib.output_type_for_level)."""
    return gdal.GDT_Int16 if dl.output_type_for_level(level) == "Int16" else gdal.GDT_Float32


def _warp_tile(src_path, dst_path, dst_srs_str, te, xres, yres, gdal_dtype,
               resample="bilinear", src_srs_str=None):
    """Run gdal.Warp to produce one DGED tile.

    Vertical handling (v0.20):
      - src_srs_str=None (default): warp with the HORIZONTAL CRS only and let
        _fix_header re-tag the +3855 label afterwards — heights are ASSUMED
        to be EGM2008 already (historic behaviour).
      - src_srs_str given (e.g. "EPSG:32632+5773"): a REAL geoid transform to
        the compound dst CRS is performed, so no re-tag is needed.

    ``te`` must already be the HALF-POST EXPANDED extent from
    dl.tile_warp_extent() (v0.28) -- gdal.Warp samples at pixel centers, so an
    unexpanded [post_min, post_max] extent shifts every value half a post off
    the DGED grid (see dem2dged_lib.tile_warp_extent docstring).

    ``gdal_dtype`` must be the level-correct type from _gdal_dtype_for_level()
    -- Int16 for levels 0-2, Float32 for level 3+ (spec section 7).

    ``resample`` is chosen by the caller via dl.pick_resampler.
    """
    if src_srs_str:
        # Real vertical transform: keep the compound dst CRS as-is.
        dst_srs = dst_srs_str
    else:
        # Strip compound vertical CRS so warp never needs egm08 grid shift files
        dst_srs = dst_srs_str.split("+")[0]   # "EPSG:4326+3855" → "EPSG:4326"

    opts = gdal.WarpOptions(
        srcSRS          = src_srs_str,        # None → use the raster's own CRS
        dstSRS          = dst_srs,
        outputBounds    = [te[0], te[1], te[2], te[3]],  # minx miny maxx maxy
        dstNodata       = -32767,
        xRes            = xres,
        yRes            = yres,
        resampleAlg     = resample,
        outputType      = gdal_dtype,
        # v0.39: data-type-aware LZW predictor (PREDICTOR=3 for Float32,
        # PREDICTOR=2 for Int16) via the shared dl.predictor_for_type(), so
        # the GUI and the two CLI converters can't drift on this.
        creationOptions = ["COMPRESS=LZW",
                           "PREDICTOR=" + dl.predictor_for_type(
                               "Int16" if gdal_dtype == gdal.GDT_Int16
                               else "Float32"),
                           "TILED=YES"],
        format          = "GTiff",
        multithread     = True,
    )
    result = gdal.Warp(dst_path, src_path, options=opts)
    if result is None:
        raise RuntimeError("gdalwarp failed for %s" % dst_path)
    result = None   # flush & close

def _fix_header(tif_path, epsg_compound):
    """Set AREA_OR_POINT=Point and, if epsg_compound is given, re-tag the TIFF
    with that full compound CRS.

    Pass epsg_compound=None when the warp already produced the correct compound
    CRS via a real vertical transform — then only the Point flag is written and
    the projection is left untouched. Re-tagging does NOT re-transform heights.
    """
    ds = dl.gdal_open(tif_path, gdal.GA_Update)
    if ds is None:
        return
    if epsg_compound is not None:
        srs = osr.SpatialReference()
        srs.SetFromUserInput(epsg_compound)
        ds.SetProjection(srs.ExportToWkt())
    ds.SetMetadataItem("AREA_OR_POINT", "Point")
    ds.FlushCache()
    ds = None

# Sidecar XML writing (v0.28): moved to dl.sidecar_replacements() +
# dl.write_sidecar_file(), the same functions the CLI converters use. The
# old local _write_xml() only ever filled 5 of the template's 17
# placeholders (BASENAME/LEVEL/GSD/DATE/EPSG) -- every other field (ORG,
# CLASS_WORD, the bounding box, MINZ/MAXZ, MISSRATE, ABS_HACC/ABS_VACC,
# LINEAGE, DTYPE) was left as literal unreplaced "{{...}}" text in every
# GUI-generated tile, which is what the validator's "unreplaced placeholder"
# check was catching.


def _load_template(name):
    """Load XML template from exe bundle or script directory."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base, name)
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        raise RuntimeError(
            "Template file not found: %s\n"
            "Expected at: %s\n"
            "Current working directory: %s\n"
            "sys._MEIPASS: %s" % (
                name, template_path, os.getcwd(),
                getattr(sys, '_MEIPASS', 'NOT SET')))
    except Exception as e:
        raise RuntimeError("Failed to load template %s: %s" % (name, e))


# ── Accuracy helpers (v0.20) — inlined so the GUI stays self-contained ────────

def _source_gsd_meters(path):
    """Approximate the input raster's post spacing (GSD) in metres."""
    src = dl.gdal_open(path)
    if src is None:
        return None
    _, xres, _, _, _, yres = src.GetGeoTransform()
    proj = osr.SpatialReference(wkt=src.GetProjection())
    if proj.IsGeographic():
        return abs(yres) * 111320.0
    return abs(yres)


def _pick_resampler(src, src_gsd_m, dst_gsd_m, override=None, log_fn=None):
    """Resampler choice, delegated to the shared dl.resolve_resampler
    (v0.36; wraps dl.pick_resampler, used directly through v0.33-0.35).

    ``override`` is a gdalwarp algorithm name ('near', 'bilinear', 'cubic',
    ...) selected in the GUI's Resampling Method dropdown, 'auto'/None for
    the validator-safe automatic choice used since v0.20 ('average' when
    downsampling — never overshoots source min/max — else 'bilinear', no
    cubic ringing), or 'optimize' (v0.36) to measure Nearest/Bilinear/Cubic
    against ``src`` itself and use whichever reconstructs it most
    accurately. Any explicit override always takes precedence over 'auto',
    the same rule the CLI's -resample flag has followed since v0.20.

    ``src`` is only actually opened when override == 'optimize' (or when
    it's needed to check whether the source looks like angular/circular
    data for that same path) — every other override value ignores it, same
    cost as before v0.36.

    ``log_fn`` (v0.36): the caller's thread-safe log_fn, forwarded so the
    'optimize' path's per-candidate RMSE lines land in the GUI's log box
    instead of a console window that doesn't exist in the packaged .exe.
    Falls back to dl.resolve_resampler's own print() default if omitted."""
    kw = {"log_fn": log_fn} if log_fn is not None else {}
    return dl.resolve_resampler(src, src_gsd_m, dst_gsd_m, override, **kw)


def _resampler_note(resampling):
    """Log-line suffix explaining how the resampler choice was made."""
    code = str(resampling).lower()
    if code == "optimize":
        return "  (optimized for this file)"
    if code in ("", "auto"):
        return "  (auto)"
    return "  (manual override)"


# ─── GEO conversion ──────────────────────────────────────────────────────────

def convert_geo(src, out_dir, level, source_type, sec_class, prod_ver,
                log_fn, progress_fn, stop_event, source_vertical=None,
                resampling="auto", org="", abs_hacc="auto", abs_vacc="auto",
                lineage="", skip_sanity_check=False,
                prefilter="none", prefilter_sigma="auto"):
    """Convert one source DEM to DGED GEO (WGS-84) tiles.

    v0.34: org / abs_hacc / abs_vacc / lineage added. dem2dged_geo.py has
    accepted all four since v0.27 (and dem2dged.py since v0.28), but the GUI
    hardcoded org="" and never passed the other three, so a GUI operator
    could not embed a producer organisation code in the filenames or record
    measured accuracy values in the metadata quality report at all.

    v0.36: pre-flight elevation sanity check (dl.sanity_check_elevation_
    source()). Unlike the CLI, a failed check does not raise SystemExit --
    that would abort the whole batch over one bad file. It logs the finding
    via log_fn (thread-safe: this runs on the worker thread) and returns
    early, skipping just this file, unless skip_sanity_check is set.
    """
    issues = dl.sanity_check_elevation_source(src)
    blocking = [msg for sev, msg in issues if sev == "block"]
    for sev, msg in issues:
        if sev != "block":
            log_fn("  WARNING: %s" % msg)
    if blocking:
        for msg in blocking:
            log_fn("  ERROR: %s" % msg)
        if not skip_sanity_check:
            log_fn("  ERROR: skipping this file -- check 'Skip elevation "
                   "sanity check' above if you are sure this is correct.")
            return
        log_fn("  WARNING: 'Skip elevation sanity check' is on -- "
               "proceeding anyway.")

    # v0.39: warn (never block) on a reserved/unknown source-type code so a
    # non-spec filename doesn't ship silently (spec 12.1). Default "A" is
    # valid and stays quiet.
    _st_ok, _st_msg = dl.describe_source_type(source_type)
    if not _st_ok:
        log_fn("  WARNING: %s" % _st_msg)

    MY_SRS = 4326
    srs_str = "EPSG:%s+3855" % MY_SRS
    tmpl = _load_template("DGED_GEO_TEMPLATE.xml")

    ext = _get_extent(src)
    # GDAL 3 axis order for EPSG:4326 is (lat, lon): the first pair from
    # _bbox_in_srs is the LATITUDE range, the second the LONGITUDE range.
    minlat, maxlat, minlon, maxlon = _bbox_in_srs(ext, MY_SRS)

    tiledim, latres, tile_letter = _geo_level(level)

    # -- Data type (v0.28) ------------------------------------------------------
    # DGED spec section 7: Int16 is MANDATORY for levels 0-2, Float32 for
    # level 3+. Shared with the CLI via dl.output_type_for_level() -- this
    # used to be hardcoded to Float32 for every level.
    gdal_dtype = _gdal_dtype_for_level(level)
    log_fn("  Output data type: %s" % dl.output_type_for_level(level))

    # ── Resampler + vertical strategy (v0.20; override v0.33) ────────────────
    src_gsd_m = _source_gsd_meters(src)
    resamp    = _pick_resampler(src, src_gsd_m, latres * 111320, resampling,
                                log_fn=log_fn)
    log_fn("  Resampler: %s%s" % (resamp, _resampler_note(resampling)))

    # -- Anti-alias pre-filter (v0.56 in the GUI; v0.49 on the CLI) -----------
    # Opt-in, and identical in effect to the CLI's -prefilter: a Gaussian-
    # smoothed COPY of the source is built once, and every tile is warped
    # from that copy instead of the original. Tile geometry, grid snapping
    # and the resampler are untouched -- only the elevations being sampled
    # change.
    #
    # Deliberately placed AFTER the resampler choice and BEFORE the clamp
    # scan below, and note the clamp block reads `src`, not `warp_input`, on
    # purpose: the overshoot clamp must use the ORIGINAL source's true
    # min/max, because it exists to catch a resampler inventing a physically
    # impossible elevation, and smoothing narrows the range rather than
    # widening it.
    prefilter = dl.validate_prefilter(prefilter)
    warp_input     = src
    prefilter_tmp  = None
    prefilter_note = "no anti-alias pre-filter"
    if prefilter == "gaussian":
        sigma_px = dl.gaussian_sigma_for_ratio(src_gsd_m, latres * 111320,
                                               prefilter_sigma)
        if sigma_px > 0:
            prefilter_tmp = dl.build_prefiltered_source(
                src, sigma_px, log_fn=lambda m: log_fn("  " + str(m)))
            warp_input = prefilter_tmp
            prefilter_note = ("Gaussian anti-alias pre-filter, sigma=%.3f "
                              "source pixels" % sigma_px)
            log_fn("  Pre-filter: %s" % prefilter_note)
        else:
            log_fn("  NOTE: Gaussian pre-filter requested but the target post "
                   "spacing is not coarser than the source, so there is "
                   "nothing to alias -- pre-filter skipped.")

    # v0.56: tiles whose warp raised. The GUI used to let a single failed
    # tile abort the whole file -- see the tile loop below.
    n_failed = 0

    # v0.37 (DGED_Conversion_Review.md Finding 3): cubic-family resamplers
    # can overshoot -- "ring" -- past the source's true min/max at sharp
    # discontinuities. Scan the source's exact min/max ONCE up front so
    # every tile can be clamped back into range right after it is warped.
    clamp_range = None
    if resamp in dl.OVERSHOOT_PRONE_RESAMPLERS:
        src_vmin, src_vmax, _src_miss = dl.compute_tile_stats(src)
        clamp_range = (src_vmin, src_vmax)
        log_fn("  Overshoot-prone resampler (%s): tiles will be clamped to "
               "the source's range %s..%s m" % (resamp, src_vmin, src_vmax))

    src_horiz = ext[4]   # source horizontal EPSG
    if source_vertical and str(source_vertical) != "3855":
        from dem2dged_terrain import (check_vertical_operation, inspect_source,
                                      write_json)
        source_info = inspect_source(src)
        vertical_check = check_vertical_operation(
            source_info.horizontal_crs or "EPSG:%s" % src_horiz,
            source_vertical, extent=source_info.extent)
        write_json(vertical_check,
                   os.path.join(out_dir, "vertical_operation_check.json"))
        if vertical_check["status"] != "PASS":
            raise RuntimeError("Vertical conversion preflight failed: %s" %
                               vertical_check.get("reason", "operation unavailable"))
        warp_src_srs = "EPSG:%s+%s" % (src_horiz, source_vertical)
        retag_srs    = None            # warp already yields compound CRS
        log_fn("  Vertical: transforming +%s → +3855 (EGM2008)" % source_vertical)
    else:
        warp_src_srs = None
        retag_srs    = srs_str
        if not source_vertical:
            log_fn("  WARNING: heights ASSUMED EGM2008 — no vertical transform "
                   "applied (label only).")

    # v0.34: ceil(), not floor()+1 -- see dem2dged_geo.py for the rationale
    # (floor()+1 always produced a row and column of pure-NoData tiles past
    # the data whenever the source extent landed on a tile boundary).
    ilat_s = math.floor(minlat/tiledim)
    ilat_e = max(ilat_s+1, math.ceil(maxlat/tiledim))
    ilon_s = math.floor(minlon/tiledim)
    ilon_e = max(ilon_s+1, math.ceil(maxlon/tiledim))

    total = (ilat_e-ilat_s)*(ilon_e-ilon_s); done = 0

    # v0.34: lineage default matches the CLI converters' wording.
    # v0.56: the pre-filter changes the delivered elevations, so it belongs
    # in the lineage statement -- a downstream consumer must be able to tell
    # a smoothed product from an unsmoothed one from the metadata alone.
    # Same wording as the CLI converters have used since v0.49.
    lineage_text = lineage or (
        "Derived from source raster '%s' by dem2dged v%s; gdalwarp "
        "resampling=%s; %s; %s." % (
            os.path.basename(src), dl.VERSION, resamp, prefilter_note,
            "vertical datum transformed EPSG:%s -> EPSG:3855 (EGM2008)"
            % source_vertical if (source_vertical
                                  and str(source_vertical) != "3855")
            else "heights assumed EGM2008 (label only, no vertical transform)"))

    tile_basenames = []
    prod_west = prod_east = prod_south = prod_north = None
    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below

    def _note_delivered(w, s, e, n):
        """Extend the product extent by one delivered tile (v0.56)."""
        nonlocal prod_west, prod_south, prod_east, prod_north
        prod_west  = w if prod_west  is None else min(prod_west, w)
        prod_south = s if prod_south is None else min(prod_south, s)
        prod_east  = e if prod_east  is None else max(prod_east, e)
        prod_north = n if prod_north is None else max(prod_north, n)

    # -- Phase 1: warp every tile ---------------------------------------------
    stopped = False
    for yy in range(ilat_s, ilat_e):
        if stopped:
            break
        for xx in range(ilon_s, ilon_e):
            if stop_event.is_set():
                stopped = True
                break
            done += 1
            pct = int(100*done/total)

            t_minlat = yy * tiledim
            lonres   = _lon_multi(t_minlat) * latres
            t_minlon = xx * tiledim

            # v0.28: HALF-POST EXPANDED warp extent from the shared helper
            # (dem2dged_lib.tile_warp_extent). Posts run from t_min to
            # t_min+tiledim INCLUSIVE; gdal.Warp samples at pixel CENTERS, so
            # the extent must extend half a post spacing beyond the outermost
            # posts on every side, or every sampled value lands half a post
            # off the DGED grid. The previous local formula here (unexpanded
            # min, one full post added only on the max side) had exactly that
            # bug in every GUI-produced tile. v0.37: tile_warp_extent() now
            # rounds to a fixed coordinate precision (Finding 1 hardening,
            # see its docstring) -- reconcile_tile_edges() below is what
            # actually guarantees the shared post matches, though.
            te_xmin, te_ymin, te_xmax, te_ymax = dl.tile_warp_extent(
                t_minlon, t_minlat, tiledim, lonres, latres)

            # v0.28: filename built by the same function the CLI converters
            # use (dem2dged_lib.geo_tile_basename) -- was a hand-rolled copy
            # here that still used the pre-v0.27 "Gt<letter>" form for
            # levels 0-3, which no longer matches what the CLI (or the spec
            # example names) produce for those levels.
            bn = dl.geo_tile_basename(level, tile_letter, t_minlat, t_minlon,
                                      source_type, sec_class, prod_ver,
                                      org=org)

            tif = os.path.join(out_dir, bn+".tif")
            xml = os.path.join(out_dir, bn+".xml")

            # Track product extent (post extent, not the expanded warp extent).
            # v0.56: recorded only where a tile joins the delivery -- see the
            # identical change in dem2dged_geo.py.
            pw, ps = t_minlon, t_minlat
            pe, pn = t_minlon+tiledim, t_minlat+tiledim

            # v0.56: the .tif is checked too. Phase 3 writes sidecars only
            # after every warp completes, so an .xml without its .tif is
            # unusual -- but a tile deleted or corrupted after delivery, beside
            # a surviving sidecar, was silently accepted as "done" and could
            # never be regenerated by re-running. It then reached the validator
            # as a missing or unreadable file.
            if os.path.isfile(xml) and os.path.isfile(tif):
                log_fn("  Skip (exists): %s" % bn)
                tile_basenames.append(bn)
                _note_delivered(pw, ps, pe, pn)
                progress_fn(pct); continue

            log_fn("  Creating: %s" % bn)
            # v0.56: _warp_tile() raises RuntimeError when gdal.Warp returns
            # None, and nothing caught it here -- so ONE bad tile aborted the
            # entire file, leaving a partial folder with no TABLE_OF_CONTENTS
            # and no collection metadata. The CLI has treated a failed warp
            # as a skippable per-tile problem since v0.42 (which it is: a
            # bad tile is not a bad run), and the GUI now matches it exactly,
            # including the "re-run to retry only the missing tiles" contract
            # that the resume path already supports.
            try:
                _warp_tile(warp_input, tif, srs_str,
                           (te_xmin, te_ymin, te_xmax, te_ymax),
                           lonres, latres, gdal_dtype,
                           resample=resamp, src_srs_str=warp_src_srs)
            except Exception as warp_err:
                log_fn("  ERROR: warp failed for %s (%s) -- tile skipped, "
                       "re-run to retry it." % (bn, warp_err))
                n_failed += 1
                progress_fn(pct)
                continue
            _fix_header(tif, retag_srs)

            # v0.37 (Finding 3): clamp BEFORE this tile is added to
            # tile_grid, so if Finding 1's edge reconciliation later copies
            # this tile's edge onto a neighbour, it copies the already-
            # clamped values.
            if clamp_range is not None:
                n_clamped = dl.clamp_tile_to_range(tif, *clamp_range)
                if n_clamped:
                    log_fn("    Clamped %d pixel(s) back into the source "
                           "range" % n_clamped)

            tile_grid[(yy, xx)] = tif
            pending.append(dict(bn=bn, tif=tif, xml=xml,
                                 pw=pw, ps=ps, pe=pe, pn=pn))
            tile_basenames.append(bn)
            _note_delivered(pw, ps, pe, pn)
            progress_fn(pct)

    # v0.56: every tile has been warped (or the Stop button cut the batch
    # short), so the pre-filter scratch raster -- which can be several
    # hundred MB in the system temp folder -- is no longer needed. Removed
    # BEFORE the no-tiles error below, so a failed run cleans up after
    # itself too.
    dl.cleanup_prefiltered_source(prefilter_tmp, log_fn=log_fn)

    # v0.56: a run in which EVERY warp failed used to fall straight through
    # to writing delivery metadata for an empty folder, and the GUI then
    # auto-validated it. Nothing produced is a hard failure; a partial run
    # says so plainly and continues, because the tiles that DID warp are
    # still valid deliverables. Same rule as the CLI converters since v0.42.
    if not tile_basenames and not stopped:
        raise RuntimeError(
            "No tiles were produced (%d warp call(s) failed). Nothing was "
            "written to %s. The usual causes are a source raster GDAL cannot "
            "read, a full disk, or a source that does not overlap the "
            "requested area at all." % (n_failed, out_dir))
    if n_failed:
        log_fn("  WARNING: %d tile(s) failed to warp and are MISSING from "
               "the delivery. Re-run this exact job to retry only the "
               "missing tiles (existing tiles are skipped)." % n_failed)

    # -- Phase 2: reconcile shared edges (v0.37, Finding 1) --------------------
    # Runs once, after every tile in this batch has been warped (or the Stop
    # button cut the batch short), and BEFORE per-tile stats are computed
    # below, so the sidecar XML's min/max/completeness always describe the
    # pixels actually delivered.
    if len(tile_grid) > 1:
        n_fixed = dl.reconcile_tile_edges(tile_grid)
        if n_fixed:
            log_fn("  Reconciled %d shared tile edge(s) so adjacent posts "
                   "match exactly." % n_fixed)

    # -- Phase 3: per-tile stats + sidecar XML ----------------------------------
    # v0.28: sidecar built by dl.sidecar_replacements() + dl.write_sidecar_
    # file() -- the same functions the CLI uses. The previous local
    # _write_xml() only filled 5 of the template's 17 placeholders; the rest
    # (ORG, CLASS_WORD, the bounding box, MINZ/MAXZ, MISSRATE, ABS_HACC/
    # ABS_VACC, LINEAGE, DTYPE) were left as literal unreplaced "{{...}}"
    # text. Sidecar GSD field is in metres — convert degrees to approx m.
    gsd_m = round(latres*111320, 3)
    for item in pending:
        repl = dl.sidecar_replacements(
            item["bn"], level, gsd_m, str(MY_SRS), sec_class, org,
            (item["pw"], item["ps"], item["pe"], item["pn"]), item["tif"],
            abs_hacc=abs_hacc, abs_vacc=abs_vacc, lineage=lineage_text)
        dl.write_sidecar_file(tmpl, item["xml"], repl)

    # v0.37: return the resolved resampler (even when the user hit Stop
    # partway through) so the worker thread can tell the validator what was
    # actually used instead of it assuming Bilinear -- see
    # DGED_Conversion_Review.md Finding 2.
    if stopped:
        return resamp

    # -- Product delivery files (v0.28, spec 12.1 / 6.6) -------------------------
    # Table of contents ("shall", spec 12.1) and, for multi-tile products,
    # collection-level metadata (spec 6.6). The CLI converters have written
    # these since v0.27; the GUI never did until now.
    if tile_basenames:
        product_id = "DGEDL%sG" % level
        toc = dl.write_toc_file(out_dir, product_id)
        log_fn("  Table of contents written: %s" % toc)
        if len(tile_basenames) > 1:
            coll = dl.write_collection_metadata(
                out_dir, product_id, level, str(MY_SRS),
                (prod_west, prod_south, prod_east, prod_north),
                tile_basenames, sec_class, org=org)
            log_fn("  Collection metadata written: %s" % coll)
            dl.write_toc_file(out_dir, product_id)

    return resamp


# ─── UTM conversion ──────────────────────────────────────────────────────────

def convert_utm(src, out_dir, level, zone_str, source_type, sec_class,
                prod_ver, log_fn, progress_fn, stop_event, source_vertical=None,
                resampling="auto", org="", abs_hacc="auto", abs_vacc="auto",
                lineage="", skip_sanity_check=False,
                prefilter="none", prefilter_sigma="auto"):
    """Convert one source DEM to DGED UTM tiles.

    v0.34: org / abs_hacc / abs_vacc / lineage added -- see convert_geo().
    v0.36: pre-flight elevation sanity check -- see convert_geo().
    """
    issues = dl.sanity_check_elevation_source(src)
    blocking = [msg for sev, msg in issues if sev == "block"]
    for sev, msg in issues:
        if sev != "block":
            log_fn("  WARNING: %s" % msg)
    if blocking:
        for msg in blocking:
            log_fn("  ERROR: %s" % msg)
        if not skip_sanity_check:
            log_fn("  ERROR: skipping this file -- check 'Skip elevation "
                   "sanity check' above if you are sure this is correct.")
            return
        log_fn("  WARNING: 'Skip elevation sanity check' is on -- "
               "proceeding anyway.")

    # v0.39: warn (never block) on a reserved/unknown source-type code so a
    # non-spec filename doesn't ship silently (spec 12.1). Default "A" is
    # valid and stays quiet.
    _st_ok, _st_msg = dl.describe_source_type(source_type)
    if not _st_ok:
        log_fn("  WARNING: %s" % _st_msg)

    tmpl = _load_template("DGED_UTM_TEMPLATE.xml")
    ext  = _get_extent(src)

    if zone_str.upper() == "AUTO":
        epsg, zone_num, ns = _autodetect_utm(ext)
        utmzone = "%02d%s" % (zone_num, ns)
    else:
        z = zone_str.strip().upper()
        if (len(z) < 2 or z[-1] not in ("N", "S") or not z[:-1].isdigit()
                or not 1 <= int(z[:-1]) <= 60):
            raise RuntimeError(
                "Invalid UTM zone '%s' (expected e.g. 32N or 09S, or AUTO)" % zone_str)
        zone_num = int(z[:-1])
        epsg = int("32%s%02d" % ("6" if z[-1] == "N" else "7", zone_num))
        utmzone = "%02d%s" % (zone_num, z[-1])

    srs_str = "EPSG:%s+3855" % epsg
    gsd, posts, tile_letter = _utm_level(level)
    tiledim = (posts-1)*gsd
    log_fn("  UTM zone: %s  EPSG: %s  GSD: %s m" % (utmzone, epsg, gsd))

    # -- Data type (v0.28) ------------------------------------------------------
    # All UTM levels are 4b and above, so this is Float32 today either way --
    # routed through the shared helper so the policy lives in one place.
    gdal_dtype = _gdal_dtype_for_level(level)

    # ── Resampler + vertical strategy (v0.20; override v0.33) ────────────────
    src_gsd_m = _source_gsd_meters(src)
    resamp    = _pick_resampler(src, src_gsd_m, gsd, resampling, log_fn=log_fn)
    log_fn("  Resampler: %s%s" % (resamp, _resampler_note(resampling)))

    # -- Anti-alias pre-filter (v0.56 in the GUI) ----------------------------
    # See the identical block and rationale in convert_geo() above.
    prefilter = dl.validate_prefilter(prefilter)
    warp_input     = src
    prefilter_tmp  = None
    prefilter_note = "no anti-alias pre-filter"
    if prefilter == "gaussian":
        sigma_px = dl.gaussian_sigma_for_ratio(src_gsd_m, gsd, prefilter_sigma)
        if sigma_px > 0:
            prefilter_tmp = dl.build_prefiltered_source(
                src, sigma_px, log_fn=lambda m: log_fn("  " + str(m)))
            warp_input = prefilter_tmp
            prefilter_note = ("Gaussian anti-alias pre-filter, sigma=%.3f "
                              "source pixels" % sigma_px)
            log_fn("  Pre-filter: %s" % prefilter_note)
        else:
            log_fn("  NOTE: Gaussian pre-filter requested but the target post "
                   "spacing is not coarser than the source, so there is "
                   "nothing to alias -- pre-filter skipped.")

    n_failed = 0

    # v0.37 (DGED_Conversion_Review.md Finding 3): cubic-family resamplers
    # can overshoot -- "ring" -- past the source's true min/max at sharp
    # discontinuities. Scan the source's exact min/max ONCE up front so
    # every tile can be clamped back into range right after it is warped.
    clamp_range = None
    if resamp in dl.OVERSHOOT_PRONE_RESAMPLERS:
        src_vmin, src_vmax, _src_miss = dl.compute_tile_stats(src)
        clamp_range = (src_vmin, src_vmax)
        log_fn("  Overshoot-prone resampler (%s): tiles will be clamped to "
               "the source's range %s..%s m" % (resamp, src_vmin, src_vmax))

    src_horiz = ext[4]   # source horizontal EPSG
    if source_vertical and str(source_vertical) != "3855":
        from dem2dged_terrain import (check_vertical_operation, inspect_source,
                                      write_json)
        source_info = inspect_source(src)
        vertical_check = check_vertical_operation(
            source_info.horizontal_crs or "EPSG:%s" % src_horiz,
            source_vertical, extent=source_info.extent)
        write_json(vertical_check,
                   os.path.join(out_dir, "vertical_operation_check.json"))
        if vertical_check["status"] != "PASS":
            raise RuntimeError("Vertical conversion preflight failed: %s" %
                               vertical_check.get("reason", "operation unavailable"))
        warp_src_srs = "EPSG:%s+%s" % (src_horiz, source_vertical)
        retag_srs    = None
        log_fn("  Vertical: transforming +%s → +3855 (EGM2008)" % source_vertical)
    else:
        warp_src_srs = None
        retag_srs    = srs_str
        if not source_vertical:
            log_fn("  WARNING: heights ASSUMED EGM2008 — no vertical transform "
                   "applied (label only).")

    minx, maxx, miny, maxy = _bbox_in_srs(ext, epsg)

    # v0.34: ceil(), not floor()+1 -- see dem2dged_geo.py for the rationale.
    ix_s = math.floor(minx/tiledim)
    ix_e = max(ix_s+1, math.ceil(maxx/tiledim))
    iy_s = math.floor(miny/tiledim)
    iy_e = max(iy_s+1, math.ceil(maxy/tiledim))

    # v0.39: clamp to the valid UTM northing band [0, 10 000 000] m so an
    # equatorial source (whose point-registered edge overhangs the equator by
    # half a post) can't emit a negative-northing tile -- see the identical
    # fix and rationale in dem2dged_utm.py.
    NORTHING_MAX = 10_000_000.0
    iy_s_raw, iy_e_raw = iy_s, iy_e
    iy_s = max(iy_s, 0)
    iy_e = min(iy_e, int(math.ceil(NORTHING_MAX / tiledim)))
    iy_e = max(iy_e, iy_s + 1)
    if iy_s_raw < iy_s or iy_e_raw > iy_e:
        log_fn("  WARNING: source extent reaches outside the valid UTM "
               "northing band [0, 10 000 000] m for zone %s -- out-of-band "
               "tiles skipped (a DGED UTM northing must be >= 0). Normal for "
               "an equatorial DEM; for data spanning the equator, convert "
               "each hemisphere separately with an explicit zone." % utmzone)

    total = (ix_e-ix_s)*(iy_e-iy_s); done = 0

    # v0.34: lineage default matches the CLI converters' wording.
    # v0.56: the pre-filter changes the delivered elevations, so it belongs
    # in the lineage statement -- a downstream consumer must be able to tell
    # a smoothed product from an unsmoothed one from the metadata alone.
    # Same wording as the CLI converters have used since v0.49.
    lineage_text = lineage or (
        "Derived from source raster '%s' by dem2dged v%s; gdalwarp "
        "resampling=%s; %s; %s." % (
            os.path.basename(src), dl.VERSION, resamp, prefilter_note,
            "vertical datum transformed EPSG:%s -> EPSG:3855 (EGM2008)"
            % source_vertical if (source_vertical
                                  and str(source_vertical) != "3855")
            else "heights assumed EGM2008 (label only, no vertical transform)"))

    tile_basenames = []
    prod_minx = prod_miny = prod_maxx = prod_maxy = None
    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below

    def _note_delivered(x0, y0, x1, y1):
        """Extend the product extent by one delivered tile (v0.56)."""
        nonlocal prod_minx, prod_miny, prod_maxx, prod_maxy
        prod_minx = x0 if prod_minx is None else min(prod_minx, x0)
        prod_miny = y0 if prod_miny is None else min(prod_miny, y0)
        prod_maxx = x1 if prod_maxx is None else max(prod_maxx, x1)
        prod_maxy = y1 if prod_maxy is None else max(prod_maxy, y1)

    # -- Phase 1: warp every tile ---------------------------------------------
    stopped = False
    for yy in range(iy_s, iy_e):
        if stopped:
            break
        for xx in range(ix_s, ix_e):
            if stop_event.is_set():
                stopped = True
                break
            done += 1
            pct = int(100*done/total)

            t_minx = xx*tiledim
            t_miny = yy*tiledim

            # v0.28: HALF-POST EXPANDED warp extent from the shared helper
            # (see the matching comment in convert_geo() above). The old
            # local formula here (unexpanded min, one full post added only
            # on the max side) put every sampled value half a post off the
            # DGED grid -- e.g. a full 1.0 m shift on a 2 m-GSD level-5 tile.
            # v0.37: tile_warp_extent() now rounds to a fixed coordinate
            # precision (Finding 1 hardening) -- reconcile_tile_edges()
            # below is what actually guarantees the shared post matches.
            te_xmin, te_ymin, te_xmax, te_ymax = dl.tile_warp_extent(
                t_minx, t_miny, tiledim, gsd, gsd)

            # v0.28: filename built by the shared dem2dged_lib.utm_tile_basename
            # (was a hand-rolled copy here).
            bn = dl.utm_tile_basename(level, tile_letter, utmzone, t_miny, t_minx,
                                      source_type, sec_class, prod_ver, org=org)

            tif = os.path.join(out_dir, bn+".tif")
            xml = os.path.join(out_dir, bn+".xml")

            # Track product extent (post extent, not the expanded warp extent).
            # v0.56: recorded only where a tile joins the delivery -- see the
            # identical change in dem2dged_geo.py.
            tmx, tmy = t_minx+tiledim, t_miny+tiledim

            # v0.56: the .tif is checked too. Phase 3 writes sidecars only
            # after every warp completes, so an .xml without its .tif is
            # unusual -- but a tile deleted or corrupted after delivery, beside
            # a surviving sidecar, was silently accepted as "done" and could
            # never be regenerated by re-running. It then reached the validator
            # as a missing or unreadable file.
            if os.path.isfile(xml) and os.path.isfile(tif):
                log_fn("  Skip (exists): %s" % bn)
                tile_basenames.append(bn)
                _note_delivered(t_minx, t_miny, tmx, tmy)
                progress_fn(pct); continue

            log_fn("  Creating: %s" % bn)
            # v0.56: skip and count instead of aborting the file -- see the
            # matching block and rationale in convert_geo() above.
            try:
                _warp_tile(warp_input, tif, srs_str,
                           (te_xmin, te_ymin, te_xmax, te_ymax), gsd, gsd,
                           gdal_dtype,
                           resample=resamp, src_srs_str=warp_src_srs)
            except Exception as warp_err:
                log_fn("  ERROR: warp failed for %s (%s) -- tile skipped, "
                       "re-run to retry it." % (bn, warp_err))
                n_failed += 1
                progress_fn(pct)
                continue
            _fix_header(tif, retag_srs)

            # v0.37 (Finding 3): clamp BEFORE this tile is added to
            # tile_grid, so if Finding 1's edge reconciliation later copies
            # this tile's edge onto a neighbour, it copies the already-
            # clamped values.
            if clamp_range is not None:
                n_clamped = dl.clamp_tile_to_range(tif, *clamp_range)
                if n_clamped:
                    log_fn("    Clamped %d pixel(s) back into the source "
                           "range" % n_clamped)

            tile_grid[(yy, xx)] = tif
            pending.append(dict(bn=bn, tif=tif, xml=xml, t_minx=t_minx,
                                 t_miny=t_miny, tmx=tmx, tmy=tmy))
            tile_basenames.append(bn)
            _note_delivered(t_minx, t_miny, tmx, tmy)
            progress_fn(pct)

    # v0.56: see the matching block in convert_geo() above.
    dl.cleanup_prefiltered_source(prefilter_tmp, log_fn=log_fn)

    if not tile_basenames and not stopped:
        raise RuntimeError(
            "No tiles were produced (%d warp call(s) failed). Nothing was "
            "written to %s. The usual causes are a source raster GDAL cannot "
            "read, a full disk, or a source that does not overlap the "
            "requested UTM zone at all." % (n_failed, out_dir))
    if n_failed:
        log_fn("  WARNING: %d tile(s) failed to warp and are MISSING from "
               "the delivery. Re-run this exact job to retry only the "
               "missing tiles (existing tiles are skipped)." % n_failed)

    # -- Phase 2: reconcile shared edges (v0.37, Finding 1) --------------------
    # Runs once, after every tile in this batch has been warped (or the Stop
    # button cut the batch short), and BEFORE per-tile stats are computed
    # below, so the sidecar XML's min/max/completeness always describe the
    # pixels actually delivered.
    if len(tile_grid) > 1:
        n_fixed = dl.reconcile_tile_edges(tile_grid)
        if n_fixed:
            log_fn("  Reconciled %d shared tile edge(s) so adjacent posts "
                   "match exactly." % n_fixed)

    # -- Phase 3: per-tile stats + sidecar XML ----------------------------------
    # v0.28: sidecar built by the shared dl.sidecar_replacements() +
    # dl.write_sidecar_file() (see the matching comment in convert_geo()
    # above for what this fixes).
    for item in pending:
        bbox84 = dl.bbox_to_wgs84(item["t_minx"], item["t_miny"],
                                  item["tmx"], item["tmy"], epsg)
        repl = dl.sidecar_replacements(
            item["bn"], level, gsd, str(epsg), sec_class, org, bbox84,
            item["tif"], abs_hacc=abs_hacc, abs_vacc=abs_vacc,
            lineage=lineage_text)
        dl.write_sidecar_file(tmpl, item["xml"], repl)

    # v0.37: return the resolved resampler (even when the user hit Stop
    # partway through) so the worker thread can tell the validator what was
    # actually used instead of it assuming Bilinear -- see
    # DGED_Conversion_Review.md Finding 2.
    if stopped:
        return resamp

    # -- Product delivery files (v0.28, spec 12.1 / 6.6) -------------------------
    if tile_basenames:
        product_id = "DGEDL%sU_%s" % (level, utmzone)
        toc = dl.write_toc_file(out_dir, product_id)
        log_fn("  Table of contents written: %s" % toc)
        if len(tile_basenames) > 1:
            bbox84 = dl.bbox_to_wgs84(prod_minx, prod_miny,
                                      prod_maxx, prod_maxy, epsg)
            coll = dl.write_collection_metadata(
                out_dir, product_id, level, str(epsg), bbox84,
                tile_basenames, sec_class, org=org)
            log_fn("  Collection metadata written: %s" % coll)
            dl.write_toc_file(out_dir, product_id)

    return resamp


# ═══════════════════════════════════════════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════════════════════════════════════════

DARK  = "#1a1a2e"
MID   = "#16213e"
ACCENT= "#e94560"
LIGHT = "#f4f6f9"
WHITE = "#ffffff"
GRAY  = "#888"
GREEN = "#27ae60"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("dem2dged v%s  –  DEM to DGED Converter" % APP_VERSION_DISPLAY)
        self.resizable(True, True)
        # Smaller minimum so the window fits laptop screens / high-DPI scaling;
        # the body scrolls and the Convert bar is pinned, so nothing is lost.
        self.minsize(640, 480)
        self.configure(bg=DARK)

        self._stop = threading.Event()
        self._q    = queue.Queue()
        self._files = []   # list of absolute paths
        self._last_report_path = None
        self._last_cmp_report_path = None   # comparison report (v0.33)
        self._last_source_gsd_m = None   # detected resolution of self._files[0] (v0.24)
        self._suppress_level_warn = False  # True while auto-suggesting, to avoid a spurious warning

        # Verify critical files and settings
        is_frozen = getattr(sys, "frozen", False)
        print("=" * 60)
        print("DEM2DGED v%s Startup" % APP_VERSION)
        print("Running as frozen executable:", is_frozen)
        if is_frozen:
            print("sys._MEIPASS:", sys._MEIPASS)
        print("Working directory:", os.getcwd())
        print("=" * 60)

        self._build_ui()
        self._center()
        self.after(100, self._poll_queue)

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header (fixed at the top)
        hdr = tk.Frame(self, bg=DARK, pady=16)
        hdr.pack(side="top", fill="x")
        tk.Label(hdr, text="dem2dged", font=("Segoe UI", 24, "bold"),
                 bg=DARK, fg=WHITE).pack()
        tk.Label(hdr, text="DEM  →  DGED Tiles   ·   v%s" % APP_VERSION_DISPLAY,
                 font=("Segoe UI", 11), bg=DARK, fg="#aaa").pack()

        # ── Action bar pinned to the BOTTOM edge ─────────────────────────────
        # Packed before the scrolling body so it always keeps its space: the
        # Convert / Stop buttons stay visible no matter how small the window is.
        action = tk.Frame(self, bg=LIGHT, padx=28, pady=10)
        action.pack(side="bottom", fill="x")
        tk.Frame(self, bg="#c8ccd2", height=1).pack(side="bottom", fill="x")

        brow = tk.Frame(action, bg=LIGHT); brow.pack(fill="x")
        self.go_btn = tk.Button(brow, text="⚙  Convert",
                                font=("Segoe UI",13,"bold"),
                                bg=ACCENT, fg=WHITE, relief="flat",
                                padx=28, pady=10, cursor="hand2",
                                activebackground="#c0392b",
                                activeforeground=WHITE,
                                command=self._start)
        self.go_btn.pack(side="left")
        self.stop_btn = tk.Button(brow, text="■  Stop",
                                  font=("Segoe UI",13,"bold"),
                                  bg="#555", fg=WHITE, relief="flat",
                                  padx=20, pady=10, cursor="hand2",
                                  state="disabled",
                                  activebackground="#333",
                                  activeforeground=WHITE,
                                  command=self._stop_conv)
        self.stop_btn.pack(side="left", padx=10)
        self.status_lbl = tk.Label(brow, text="Ready",
                                   font=("Segoe UI",10), bg=LIGHT, fg=GRAY)
        self.status_lbl.pack(side="left", padx=16)

        self.progress = ttk.Progressbar(action, mode="determinate")
        self.progress.pack(fill="x", pady=(8,0))
        self.file_progress_lbl = tk.Label(action, text="",
                                          font=("Segoe UI",9), bg=LIGHT, fg=GRAY)
        self.file_progress_lbl.pack(anchor="e")

        # ── Scrollable body (everything else) ────────────────────────────────
        outer = tk.Frame(self, bg=LIGHT)
        outer.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=LIGHT, highlightthickness=0)
        vsb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=LIGHT, padx=28, pady=16)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(inner_id, width=e.width))
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Mouse-wheel scrolling for the body (Windows / macOS / Linux)
        def _wheel(e):
            if e.num == 5:
                delta = 1
            elif e.num == 4:
                delta = -1
            else:
                delta = -1 * (e.delta // 120)
            canvas.yview_scroll(delta, "units")
        canvas.bind_all("<MouseWheel>", _wheel)
        canvas.bind_all("<Button-4>", _wheel)
        canvas.bind_all("<Button-5>", _wheel)
        self._body_canvas = canvas

        # ── Input files ──────────────────────────────────────────────────────
        self._section(inner, "Input DEM Files")

        # listbox + scrollbar
        lb_frame = tk.Frame(inner, bg=LIGHT)
        lb_frame.pack(fill="x", pady=(4,0))

        sb = tk.Scrollbar(lb_frame, orient="vertical")
        self.file_lb = tk.Listbox(lb_frame, height=5,
                                  yscrollcommand=sb.set,
                                  selectmode="extended",
                                  font=("Segoe UI", 9),
                                  bg=WHITE, fg=DARK,
                                  selectbackground=ACCENT,
                                  selectforeground=WHITE,
                                  relief="flat", bd=1,
                                  activestyle="none")
        sb.config(command=self.file_lb.yview)
        sb.pack(side="right", fill="y")
        self.file_lb.pack(fill="x", expand=True)

        # placeholder text
        self._lb_placeholder()

        # buttons row
        br = tk.Frame(inner, bg=LIGHT); br.pack(fill="x", pady=6)
        self._btn(br, "+ Add Files…",    self._add_files).pack(side="left", padx=(0,6))
        self._btn(br, "− Remove Selected", self._remove_selected).pack(side="left", padx=(0,6))
        self._btn(br, "✕ Clear All",      self._clear_files).pack(side="left")
        self.file_count_lbl = tk.Label(br, text="0 file(s)",
                                       font=("Segoe UI",9), bg=LIGHT, fg=GRAY)
        self.file_count_lbl.pack(side="right")

        # detected source resolution (v0.24 — Feature #1)
        self.resolution_label = tk.Label(
            inner, text="Detected resolution: (no file selected)",
            font=("Segoe UI", 9), bg=LIGHT, fg=GRAY, anchor="w")
        self.resolution_label.pack(fill="x", pady=(0, 6))

        # ── Output folder ─────────────────────────────────────────────────────
        self._section(inner, "Output Folder")

        row2 = tk.Frame(inner, bg=LIGHT); row2.pack(fill="x", pady=4)
        self.dst_var = tk.StringVar()
        tk.Entry(row2, textvariable=self.dst_var, font=("Segoe UI",10),
                 relief="flat", bg=WHITE, bd=1).pack(side="left", fill="x", expand=True, padx=(0,6))
        self._btn(row2, "Browse…", self._browse_dst).pack(side="left")

        # subfolder option
        srow = tk.Frame(inner, bg=LIGHT); srow.pack(fill="x", pady=(2,4))
        self.subfolder_var = tk.BooleanVar(value=True)
        tk.Checkbutton(srow, text="Create subfolder per file  (e.g. output/dem1_dged_output/…)",
                       variable=self.subfolder_var,
                       bg=LIGHT, font=("Segoe UI",9), fg=DARK,
                       activebackground=LIGHT).pack(anchor="w")

        # auto-validate option
        vrow = tk.Frame(inner, bg=LIGHT); vrow.pack(fill="x", pady=(0,4))
        self.validate_var = tk.BooleanVar(value=_VALIDATE_AVAILABLE)
        vcb = tk.Checkbutton(
            vrow,
            text="Validate after conversion and generate a report  (DGED_Validation_Report.html)",
            variable=self.validate_var,
            bg=LIGHT, font=("Segoe UI",9), fg=DARK,
            activebackground=LIGHT,
            state="normal" if _VALIDATE_AVAILABLE else "disabled")
        vcb.pack(anchor="w")
        if not _VALIDATE_AVAILABLE:
            tk.Label(vrow, text="  (dem2dged_validate module not found — skipping)",
                     font=("Segoe UI",8), bg=LIGHT, fg=GRAY).pack(anchor="w")

        # Opt-in: conversion remains unchanged, while validation adds
        # slope/peak/valley and half-post registration diagnostics.
        mqa_row = tk.Frame(inner, bg=LIGHT); mqa_row.pack(fill="x", pady=(0,4), padx=(20,0))
        self.mountain_qa_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            mqa_row,
            text="Mountain terrain precision QA  (>20% slope, peaks/valleys, +/-0.5 post)",
            variable=self.mountain_qa_var,
            bg=LIGHT, font=("Segoe UI",9), fg=DARK,
            activebackground=LIGHT,
            state="normal" if _VALIDATE_AVAILABLE else "disabled").pack(anchor="w")

        # max_diff tolerance option (v0.46)
        vrow2 = tk.Frame(inner, bg=LIGHT); vrow2.pack(fill="x", pady=(0,4), padx=(20,0))
        tk.Label(vrow2, text="Elevation tolerance for validation:",
                 font=("Segoe UI",9), bg=LIGHT, fg=DARK).pack(anchor="w", pady=(0,2))
        self.max_diff_var = tk.StringVar(value="5.0")
        for val, label in [("5.0", "5m (stricter)"), ("10.0", "10m (standard)")]:
            tk.Radiobutton(
                vrow2, text=label, variable=self.max_diff_var, value=val,
                bg=LIGHT, font=("Segoe UI",8), fg=DARK,
                activebackground=LIGHT).pack(anchor="w", padx=(10,0))

        # skip-sanity-check option (v0.36)
        srow2 = tk.Frame(inner, bg=LIGHT); srow2.pack(fill="x", pady=(0,4))
        self.skip_sanity_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            srow2,
            text="Skip elevation sanity check  (allow aspect/direction/"
                 "curvature input — normally blocked)",
            variable=self.skip_sanity_var,
            bg=LIGHT, font=("Segoe UI",9), fg=DARK,
            activebackground=LIGHT).pack(anchor="w")

        # ── Mode ──────────────────────────────────────────────────────────────
        self._section(inner, "Output Mode")
        mrow = tk.Frame(inner, bg=LIGHT); mrow.pack(fill="x", pady=6)
        self.mode_var = tk.StringVar(value="geo")
        for val, lbl, desc in [
            ("geo", "GEO  (WGS-84)", "Global lat/lon tiles"),
            ("utm", "UTM  (metric)", "Projected metric tiles"),
        ]:
            f = tk.Frame(mrow, bg=WHITE, relief="flat", bd=1, padx=12, pady=10)
            f.pack(side="left", fill="both", expand=True, padx=(0,8))
            tk.Radiobutton(f, text=lbl, variable=self.mode_var, value=val,
                           font=("Segoe UI",11,"bold"), bg=WHITE,
                           activebackground=WHITE,
                           command=self._on_mode).pack(anchor="w")
            tk.Label(f, text=desc, font=("Segoe UI",9), bg=WHITE,
                     fg=GRAY).pack(anchor="w")

        zrow = tk.Frame(inner, bg=LIGHT); zrow.pack(fill="x", pady=4)
        tk.Label(zrow, text="UTM Zone:", width=12, anchor="w",
                 bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
        self.zone_var = tk.StringVar(value="AUTO")
        self.zone_entry = tk.Entry(zrow, textvariable=self.zone_var,
                                   font=("Segoe UI",10), width=8,
                                   relief="flat", bg=WHITE, bd=1, state="disabled")
        self.zone_entry.pack(side="left")
        tk.Label(zrow, text="  e.g. 32N, 09S — AUTO to auto-detect",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY).pack(side="left")

        # ── Level ─────────────────────────────────────────────────────────────
        self._section(inner, "Product Level")
        lrow = tk.Frame(inner, bg=LIGHT); lrow.pack(fill="x", pady=4)
        tk.Label(lrow, text="Level:", width=12, anchor="w",
                 bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
        self.level_var = tk.StringVar(value="5")
        self.level_cb = ttk.Combobox(lrow, textvariable=self.level_var,
                                     state="readonly", width=32,
                                     font=("Segoe UI",10))
        self.level_cb["values"] = ["%s  (%s)" % (r[0], r[-1]) for r in GEO_LEVELS]
        self.level_cb.current(6)
        self.level_cb.pack(side="left")
        self.level_cb.bind("<<ComboboxSelected>>", self._on_level)

        # ── Resampling (v0.33) ────────────────────────────────────────────────
        self._section(inner, "Resampling Method")
        rrow = tk.Frame(inner, bg=LIGHT); rrow.pack(fill="x", pady=4)
        tk.Label(rrow, text="Resampling:", width=12, anchor="w",
                 bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
        self.resample_var = tk.StringVar(value=RESAMPLING_OPTIONS[0][1])
        self.resample_cb = ttk.Combobox(rrow, textvariable=self.resample_var,
                                        state="readonly", width=32,
                                        font=("Segoe UI",10))
        self.resample_cb["values"] = [lbl for _, lbl in RESAMPLING_OPTIONS]
        self.resample_cb.current(0)   # default: Auto
        self.resample_cb.pack(side="left")
        tk.Label(rrow,
                 text="  Auto = average (downsampling) / bilinear.  "
                      "Optimize = tests Nearest/Bilinear/Cubic and keeps "
                      "the most accurate (slower).",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY).pack(side="left")

        # ── Anti-alias pre-filter (v0.56) ─────────────────────────────────────
        # Reaches dl.build_prefiltered_source() through convert_geo/convert_utm,
        # the same path the CLI's -prefilter takes. Default "none" keeps every
        # existing GUI job bit-identical.
        prow = tk.Frame(inner, bg=LIGHT); prow.pack(fill="x", pady=4)
        tk.Label(prow, text="Pre-filter:", width=12, anchor="w",
                 bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
        self.prefilter_var = tk.StringVar(value=PREFILTER_OPTIONS[0][1])
        self.prefilter_cb = ttk.Combobox(prow, textvariable=self.prefilter_var,
                                         state="readonly", width=32,
                                         font=("Segoe UI",10))
        self.prefilter_cb["values"] = [lbl for _, lbl in PREFILTER_OPTIONS]
        self.prefilter_cb.current(0)   # default: None
        self.prefilter_cb.pack(side="left")
        tk.Label(prow,
                 text="  Low-passes the source before warping, to stop "
                      "short-wavelength terrain aliasing back in when "
                      "downsampling. A bias/variance trade -- verify on "
                      "your own data.",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY).pack(side="left")

        # ── Resampling Comparison Test (v0.33) ────────────────────────────────
        self._section(inner, "Resampling Comparison Test (optional)")
        tk.Label(inner,
                 text="Check 1-3 methods to convert side-by-side into test "
                      "folders 1 / 2 / 3 and rank their accuracy in a "
                      "Comparison Report. Ignores the dropdown above.",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY,
                 anchor="w", justify="left").pack(fill="x", pady=(2,2))
        cmp_row = tk.Frame(inner, bg=LIGHT); cmp_row.pack(fill="x", pady=(0,4))
        self.compare_vars = []   # [(BooleanVar, num, alg, label, folder), ...]
        cmp_methods = (dc.COMPARISON_METHODS if _COMPARE_AVAILABLE else [
            ("1", "near",     "Nearest Neighbor",       "test_1_nearest_neighbor"),
            ("2", "bilinear", "Bilinear Interpolation", "test_2_bilinear_interpolation"),
            ("3", "cubic",    "Cubic Convolution",      "test_3_cubic_convolution"),
        ])
        for num, alg, label, folder in cmp_methods:
            v = tk.BooleanVar(value=False)
            self.compare_vars.append((v, num, alg, label, folder))
            tk.Checkbutton(cmp_row,
                           text="%s  %s" % (num, label),
                           variable=v,
                           bg=LIGHT, font=("Segoe UI",9), fg=DARK,
                           activebackground=LIGHT,
                           state="normal" if _COMPARE_AVAILABLE else "disabled"
                           ).pack(side="left", padx=(0,18))
        if not _COMPARE_AVAILABLE:
            tk.Label(inner, text="  (dem2dged_compare module not found — "
                                 "comparison test disabled)",
                     font=("Segoe UI",8), bg=LIGHT, fg=GRAY).pack(anchor="w")

        # ── Advanced ──────────────────────────────────────────────────────────
        self._section(inner, "Advanced (optional)")
        adv = tk.Frame(inner, bg=LIGHT); adv.pack(fill="x")
        # v0.34: Organisation code / Abs. horizontal accuracy / Abs. vertical
        # accuracy / Lineage added. dem2dged_geo.py and dem2dged_utm.py have
        # accepted -org / -abs_hacc / -abs_vacc / -lineage since v0.27 and
        # dem2dged.py has exposed them since v0.28, but no GUI field ever set
        # them, so a GUI operator could not embed a producer organisation
        # code in the filenames or record measured accuracy values in the
        # metadata quality report at all. The entry width is per-field now
        # because "auto" and a free-text lineage need more room than "01".
        for label, var_name, default, width, tip in [
            ("Source type:",    "src_type_var", "A",    6,
             "A = optical unedited"),
            ("Security class:", "sec_cls_var",  "U",    6,
             "U = Unclassified"),
            ("Product ver.:",   "prod_ver_var", "01",   6,
             "Two-digit code"),
            ("Source vertical:","src_vert_var", "",     6,
             "EPSG code, e.g. 5773=EGM96 "
             "(v0.28 - blank = assume EGM2008, no transform)"),
            ("Organisation:",   "org_var",      "",     6,
             "STANAG 1059 producer code, e.g. DNK "
             "(v0.34 - blank = omit from filenames)"),
            ("Abs. H accuracy:","abs_hacc_var", "auto", 6,
             "CE90 metres written to the metadata "
             "(v0.34 - auto = DGED Table 5 goal for the level)"),
            ("Abs. V accuracy:","abs_vacc_var", "auto", 6,
             "LE90 metres written to the metadata "
             "(v0.34 - auto = DGED Table 6 goal for the level)"),
            ("Lineage:",        "lineage_var",  "",     40,
             "(v0.34 - blank = generated from the source file and settings)"),
        ]:
            r = tk.Frame(adv, bg=LIGHT); r.pack(fill="x", pady=2)
            tk.Label(r, text=label, width=14, anchor="w",
                     bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
            v = tk.StringVar(value=default)
            setattr(self, var_name, v)
            tk.Entry(r, textvariable=v, width=width, font=("Segoe UI",10),
                     relief="flat", bg=WHITE, bd=1).pack(side="left")
            tk.Label(r, text="  "+tip, font=("Segoe UI",9),
                     bg=LIGHT, fg=GRAY).pack(side="left")

        # ── Log ───────────────────────────────────────────────────────────────
        # (Convert / Stop / progress now live in the pinned bottom action bar.)
        tk.Label(inner, text="Log", font=("Segoe UI",10,"bold"),
                 bg=LIGHT, fg=DARK).pack(anchor="w", pady=(8,0))
        self.log = scrolledtext.ScrolledText(inner, height=9, state="disabled",
                                             font=("Consolas",9),
                                             bg=DARK, fg="#90cdf4",
                                             relief="flat", bd=0,
                                             insertbackground=WHITE)
        self.log.pack(fill="both", expand=True)
        # Let the wheel scroll the log itself when the pointer is over it,
        # instead of the outer body canvas.
        def _log_wheel(e):
            if e.num == 5:
                d = 1
            elif e.num == 4:
                d = -1
            else:
                d = -1 * (e.delta // 120)
            self.log.yview_scroll(d, "units")
            return "break"
        self.log.bind("<MouseWheel>", _log_wheel)
        self.log.bind("<Button-4>", _log_wheel)
        self.log.bind("<Button-5>", _log_wheel)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _section(self, parent, title):
        f = tk.Frame(parent, bg=LIGHT, pady=6); f.pack(fill="x")
        tk.Label(f, text=title, font=("Segoe UI",11,"bold"),
                 bg=LIGHT, fg=DARK).pack(anchor="w")
        tk.Frame(f, bg="#ddd", height=1).pack(fill="x", pady=(2,0))

    def _btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd,
                         bg=MID, fg=WHITE, relief="flat",
                         padx=10, pady=4, cursor="hand2",
                         font=("Segoe UI",9),
                         activebackground=ACCENT,
                         activeforeground=WHITE)

    def _center(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        # Preferred size, but never taller/wider than the screen work area so
        # the whole window (including the pinned Convert bar) is visible on
        # laptops and high-DPI displays. Leave a margin for the taskbar.
        w = min(760, sw - 80)
        h = min(880, sh - 120)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)   # bias upward so the title bar is reachable
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _lb_placeholder(self):
        if not self._files:
            self.file_lb.config(state="normal")
            self.file_lb.delete(0, "end")
            self.file_lb.insert("end", "  Click '+ Add Files…' to select one or more DEM files")
            self.file_lb.config(fg="#aaa", state="disabled")

    def _refresh_listbox(self):
        self.file_lb.config(state="normal", fg=DARK)
        self.file_lb.delete(0, "end")
        if self._files:
            for p in self._files:
                self.file_lb.insert("end", "  " + os.path.basename(p) + "   (" + os.path.dirname(p) + ")")
        else:
            self._lb_placeholder()
        self.file_count_lbl.config(text="%d file(s)" % len(self._files))
        self._update_resolution_display()

    def _log(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg+"\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _set_status(self, msg, color=GRAY):
        self.status_lbl.config(text=msg, fg=color)

    # ── file list actions ─────────────────────────────────────────────────────

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select DEM file(s)",
            filetypes=[("Raster files","*.tif *.tiff *.vrt *.hgt *.img *.asc"),
                       ("All files","*.*")])
        for p in paths:
            if p not in self._files:
                self._files.append(p)
        self._refresh_listbox()

    def _remove_selected(self):
        sel = list(self.file_lb.curselection())
        for i in reversed(sel):
            if i < len(self._files):
                del self._files[i]
        self._refresh_listbox()

    def _clear_files(self):
        self._files.clear()
        self._refresh_listbox()

    def _browse_dst(self):
        p = filedialog.askdirectory(title="Select output folder")
        if p: self.dst_var.set(p)

    # ── resolution auto-detect / auto-suggest (v0.24 — Feature #1) ─────────────

    def _level_gsd_meters(self, level_code):
        """Approximate ground sample distance (metres) for a product level
        code, in whichever mode (GEO/UTM) is currently selected."""
        rows = UTM_LEVELS if self.mode_var.get() == "utm" else GEO_LEVELS
        for r in rows:
            if r[0] == level_code:
                if self.mode_var.get() == "utm":
                    return float(r[1])                       # already metres
                return float(r[2]) / 3600.0 * 111320.0        # arcsec -> metres
        return None

    def _update_resolution_display(self):
        """Detect the GSD of the first input file and show it, then
        auto-suggest a matching product level."""
        if not self._files:
            self._last_source_gsd_m = None
            self.resolution_label.config(
                text="Detected resolution: (no file selected)", fg=GRAY)
            return

        src_file = self._files[0]
        try:
            src_gsd_m = _source_gsd_meters(src_file)
        except Exception as e:
            src_gsd_m = None
            self._log("  WARNING: could not detect resolution of %s (%s)"
                       % (os.path.basename(src_file), e))

        self._last_source_gsd_m = src_gsd_m
        if src_gsd_m:
            suffix = "" if len(self._files) == 1 else \
                "   (first of %d files)" % len(self._files)
            self.resolution_label.config(
                text="Detected resolution: %.2f m%s" % (src_gsd_m, suffix),
                fg=DARK)
            self._auto_suggest_level(src_gsd_m)
        else:
            self.resolution_label.config(
                text="Detected resolution: (unable to determine)", fg=GRAY)

    def _auto_suggest_level(self, source_gsd_m):
        """Automatically select the product level whose GSD is closest
        (on a log scale, since levels span three orders of magnitude) to
        the detected source resolution."""
        rows = UTM_LEVELS if self.mode_var.get() == "utm" else GEO_LEVELS
        candidates = []
        for r in rows:
            gsd = self._level_gsd_meters(r[0])
            if gsd:
                candidates.append((r[0], gsd))
        if not candidates or source_gsd_m <= 0:
            return

        suggested_level, suggested_gsd = min(
            candidates, key=lambda c: abs(math.log(c[1] / source_gsd_m)))

        codes = [r[0] for r in rows]
        if suggested_level in codes:
            self._suppress_level_warn = True
            try:
                self.level_cb.current(codes.index(suggested_level))
                self.level_var.set(suggested_level)
            finally:
                self._suppress_level_warn = False

            self._set_status(
                "✓ Auto-selected Level %s (~%.2gm, matches %.2fm source)"
                % (suggested_level, suggested_gsd, source_gsd_m), GREEN)

    def _check_level_warning(self):
        """Warn (status line only — non-blocking) if the currently selected
        level's output GSD is significantly finer than the detected source
        resolution, i.e. the output would be interpolated rather than
        genuine ground-measured detail."""
        if self._suppress_level_warn or not self._files or not self._last_source_gsd_m:
            return
        selected_level = self.level_var.get().split()[0]
        level_gsd = self._level_gsd_meters(selected_level)
        if level_gsd is None:
            return
        src_gsd_m = self._last_source_gsd_m
        if level_gsd < src_gsd_m * 0.8:   # output requested finer than source
            self._set_status(
                "⚠ Warning: Level %s output (~%.2gm) is finer than the "
                "%.2fm source — output will be interpolated"
                % (selected_level, level_gsd, src_gsd_m), "#f39c12")

    # ── mode / level handlers ─────────────────────────────────────────────────

    def _on_mode(self):
        utm = self.mode_var.get() == "utm"
        self.zone_entry.config(state="normal" if utm else "disabled")
        # UTM supports only levels 4b-9; GEO supports 0-9.
        rows = UTM_LEVELS if utm else GEO_LEVELS
        self.level_cb["values"] = ["%s  (%s)" % (r[0], r[-1]) for r in rows]
        cur = self.level_var.get().split()[0]
        codes = [r[0] for r in rows]
        self.level_cb.current(codes.index(cur) if cur in codes
                              else codes.index("5"))
        self._on_level()
        # Re-run auto-suggest for the new mode's level table, if we have a
        # detected source resolution already.
        if self._last_source_gsd_m:
            self._auto_suggest_level(self._last_source_gsd_m)

    def _on_level(self, _=None):
        self.level_var.set(self.level_var.get().split()[0])
        self._check_level_warning()

    # ── conversion ────────────────────────────────────────────────────────────

    def _start(self):
        if not self._files:
            messagebox.showerror("No files", "Add at least one DEM file.")
            return
        dst = self.dst_var.get().strip()
        if not dst:
            messagebox.showerror("No output", "Select an output folder.")
            return

        missing = [f for f in self._files if not os.path.exists(f)]
        if missing:
            messagebox.showerror("File not found",
                "These files no longer exist:\n" + "\n".join(missing))
            return

        lv      = self.level_var.get().split()[0]
        mode    = self.mode_var.get()
        zone    = self.zone_var.get().strip() or "AUTO"
        subdir  = self.subfolder_var.get()
        do_validate = _VALIDATE_AVAILABLE and self.validate_var.get()
        mountain_qa = do_validate and self.mountain_qa_var.get()
        max_diff = float(self.max_diff_var.get()) if do_validate else 5.0
        files   = list(self._files)
        total_f = len(files)

        # DGIWG source eligibility: deriving a finer product from a coarser
        # source is blocked by default.  The confirmation is an explicit
        # expert override and the compliance report will still record FAIL.
        target_gsd = self._level_gsd_meters(lv)
        if (target_gsd and self._last_source_gsd_m and
                self._last_source_gsd_m > target_gsd * 1.05):
            proceed = messagebox.askyesno(
                "Source is too coarse for this DGED level",
                "The detected source spacing is approximately %.3f m, but "
                "DGED Level %s targets %.3f m. DGIWG-compliant production "
                "must not derive a finer level from a coarser source.\n\n"
                "Select No and choose a coarser level. Select Yes only for "
                "an intentional interpolation test; its compliance report "
                "will record FAIL."
                % (self._last_source_gsd_m, lv, target_gsd))
            if not proceed:
                return
        self._last_report_path = None
        self._last_cmp_report_path = None

        # ── Resampling selection (v0.33) ────────────────────────────────────
        resample_label = self.resample_var.get()
        resample_code  = "auto"
        for code, lbl in RESAMPLING_OPTIONS:
            if lbl == resample_label:
                resample_code = code
                break

        # ── Pre-filter selection (v0.56) ────────────────────────────────────
        prefilter_label = self.prefilter_var.get()
        prefilter_code  = "none"
        for code, lbl in PREFILTER_OPTIONS:
            if lbl == prefilter_label:
                prefilter_code = code
                break

        # ── Comparison test selection (v0.33) ───────────────────────────────
        compare_methods = ([(num, alg, label, folder)
                            for v, num, alg, label, folder in self.compare_vars
                            if v.get()]
                           if _COMPARE_AVAILABLE else [])

        self._stop.clear()
        self.go_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress["value"] = 0
        self.file_progress_lbl.config(text="")
        self.log.config(state="normal"); self.log.delete("1.0","end")
        self.log.config(state="disabled")
        self._set_status("Running…", ACCENT)

        self._log("=" * 54)
        self._log("Converting %d file(s)  |  mode: %s  |  level: %s" % (total_f, mode.upper(), lv))
        if compare_methods:
            self._log("Resampling comparison test: %s"
                      % ", ".join("%s (%s)" % (m[0], m[2]) for m in compare_methods))
            self._log("(Resampling dropdown is ignored in comparison mode)")
        else:
            self._log("Resampling: %s" % resample_label)
        self._log("Output: %s" % dst)
        if mountain_qa:
            self._log("Mountain terrain precision QA: enabled")
        self._log("=" * 54)

        def worker():
            val_results = []
            cmp_entries = []
            runs_per_file = max(1, len(compare_methods))
            total_runs    = total_f * runs_per_file
            try:
                run_i = 0
                for idx, src in enumerate(files):
                    if self._stop.is_set(): break
                    name = os.path.splitext(os.path.basename(src))[0]
                    # Per-file subfolder: <input name>_dged_output
                    base_dir = (os.path.join(dst, name + "_dged_output")
                                if subdir else dst)

                    # Record the same pre-flight source inspection as the
                    # unified CLI. This is read-only and gives GUI operators
                    # a durable explanation of CRS/registration/NoData
                    # assumptions alongside the DGED delivery.
                    try:
                        from dem2dged_terrain import inspect_source, write_inspection_json
                        os.makedirs(base_dir, exist_ok=True)
                        write_inspection_json(
                            inspect_source(src),
                            os.path.join(base_dir, "source_inspection.json"))
                    except Exception as ie:
                        self._q.put(("log", "   Source inspection warning: %s" % ie))

                    self._q.put(("file_hdr", (idx+1, total_f, name)))

                    # v0.28: -source_vertical was accepted by convert_geo/
                    # convert_utm since v0.20 but never had a UI field or a
                    # call site that passed it, so the GUI could never do a
                    # real EGM2008 geoid transform -- it always fell back to
                    # the "heights assumed EGM2008" label-only path.
                    src_vert = self.src_vert_var.get().strip() or None

                    # v0.34: metadata fields the CLI has had since v0.27/v0.28
                    # but the GUI never passed (it hardcoded org="" and left
                    # accuracy/lineage at their defaults). Empty accuracy
                    # fields fall back to "auto", which dl.sidecar_replacements
                    # resolves to the DGED Table 5/6 goal value for the level.
                    org_code  = self.org_var.get().strip().upper()
                    abs_hacc  = self.abs_hacc_var.get().strip() or "auto"
                    abs_vacc  = self.abs_vacc_var.get().strip() or "auto"
                    lineage   = self.lineage_var.get().strip()

                    # v0.33: in comparison mode each checked method runs into
                    # its own test folder (test_1_... / test_2_... / test_3_...)
                    # under the per-file output folder; otherwise one normal
                    # run with the dropdown's resampling choice.
                    if compare_methods:
                        runs = [((num, alg, label, folder), alg,
                                 os.path.join(base_dir, folder))
                                for num, alg, label, folder in compare_methods]
                    else:
                        runs = [(None, resample_code, base_dir)]

                    entry = {"name": name, "src": src, "level": lv,
                             "mode": mode.upper(), "methods": []}

                    for meth, alg_code, out_dir in runs:
                        if self._stop.is_set(): break
                        os.makedirs(out_dir, exist_ok=True)
                        if meth:
                            self._q.put(("log", "\n  == Test %s: %s  ->  %s"
                                         % (meth[0], meth[2], meth[3])))

                        def log_fn(m):    self._q.put(("log", m))
                        def prog_fn(p, _run=run_i):
                            # blend run-level % into overall bar
                            overall = int((_run / total_runs) * 100
                                          + p / total_runs)
                            self._q.put(("pct", overall))

                        t0 = time.time()
                        resamp_used = None   # v0.37: set from convert_*()'s
                                              # return value below, for the
                                              # validation calls further down
                                              # (Finding 2 -- see convert_geo)
                        try:
                            if mode == "geo":
                                resamp_used = convert_geo(src, out_dir, lv,
                                            self.src_type_var.get(),
                                            self.sec_cls_var.get(),
                                            self.prod_ver_var.get(),
                                            log_fn, prog_fn, self._stop,
                                            source_vertical=src_vert,
                                            resampling=alg_code,
                                            org=org_code,
                                            abs_hacc=abs_hacc,
                                            abs_vacc=abs_vacc,
                                            lineage=lineage,
                                            skip_sanity_check=
                                                self.skip_sanity_var.get(),
                                            prefilter=prefilter_code)
                            else:
                                resamp_used = convert_utm(src, out_dir, lv, zone,
                                            self.src_type_var.get(),
                                            self.sec_cls_var.get(),
                                            self.prod_ver_var.get(),
                                            log_fn, prog_fn, self._stop,
                                            source_vertical=src_vert,
                                            resampling=alg_code,
                                            org=org_code,
                                            abs_hacc=abs_hacc,
                                            abs_vacc=abs_vacc,
                                            lineage=lineage,
                                            skip_sanity_check=
                                                self.skip_sanity_var.get(),
                                            prefilter=prefilter_code)
                        except Exception as conv_err:
                            if not meth:
                                raise   # normal mode: abort as before
                            # comparison mode: record and continue with the
                            # next method so one failure doesn't kill the test
                            entry["methods"].append({
                                "num": meth[0], "alg": meth[1],
                                "label": meth[2], "folder": out_dir,
                                "elapsed": time.time() - t0,
                                "error": str(conv_err)})
                            self._q.put(("log", "     ERROR: %s" % conv_err))
                            run_i += 1
                            continue
                        elapsed = time.time() - t0
                        run_i += 1
                        if self._stop.is_set(): break

                        try:
                            from dem2dged_compliance import write_conversion_manifest
                            write_conversion_manifest(
                                os.path.join(out_dir,
                                    "DEM2DGED_Conversion_Manifest.json"),
                                src, out_dir,
                                {"mode": mode, "level": lv,
                                 "resample_requested": alg_code,
                                 "resample_resolved": resamp_used,
                                 "source_vertical_epsg": src_vert,
                                 "source_vertical_basis": (
                                     "operator-declared" if src_vert else
                                     "assumed-EGM2008-label-only"),
                                 "source_horizontal_accuracy_90_m": None,
                                 "source_vertical_accuracy_90_m": None,
                                 "metadata_absolute_horizontal_accuracy": abs_hacc,
                                 "metadata_absolute_vertical_accuracy": abs_vacc,
                                 "metadata_accuracy_basis": (
                                     "operator-supplied" if abs_hacc != "auto" or
                                     abs_vacc != "auto" else
                                     "DGIWG-level-goal-not-measured")})
                        except Exception as me:
                            self._q.put(("log", "   Manifest warning: %s" % me))

                        if meth:
                            mrec = {"num": meth[0], "alg": meth[1],
                                    "label": meth[2], "folder": out_dir,
                                    "elapsed": elapsed}
                            # Accuracy stats vs. the original source DEM
                            self._q.put(("log", "     Analyzing accuracy…"))
                            try:
                                st = dc.compute_method_stats(src, out_dir,
                                                             meth[1])
                                mrec["stats"] = st
                                self._q.put(("log",
                                    "     RMSE=%.4f m  MAE=%.4f m  "
                                    "Max|Err|=%.3f m  Overshoot=%.3f m"
                                    % (st["rmse"], st["mae"],
                                       st["max_abs_err"], st["overshoot"])))
                            except Exception as ce:
                                mrec["error"] = str(ce)
                                self._q.put(("log",
                                    "     Accuracy analysis failed: %s" % ce))
                            # Optional spec validation of this test folder
                            if do_validate:
                                try:
                                    # v0.37: comparison-mode entries already
                                    # carry a concrete algorithm (meth[1],
                                    # e.g. "near"/"bilinear"/"cubic" -- never
                                    # "auto") -- pass it through instead of
                                    # letting the validator assume Bilinear
                                    # (DGED_Conversion_Review.md Finding 2).
                                    rep, tiles = dv.run_validation(
                                        out_dir, src=src, max_diff=max_diff,
                                        resample=meth[1])
                                    # v0.37: shared 3-tier rule (Finding 4)
                                    # instead of a locally re-typed copy of
                                    # it -- see dv.overall_result()'s
                                    # docstring.
                                    mrec["validation"] = dv.overall_result(
                                        rep.n_pass, rep.n_warn, rep.n_fail)
                                    val_results.append(
                                        {"name": "%s [%s]" % (name, meth[2]),
                                         "src": src, "rep": rep, "tiles": tiles,
                                         "resample": meth[1]})
                                    self._q.put(("log",
                                        "     Validation: PASS=%d  WARN=%d  FAIL=%d"
                                        % (rep.n_pass, rep.n_warn, rep.n_fail)))
                                    try:
                                        from dem2dged_terrain import run_terrain_qa
                                        qa = run_terrain_qa(
                                            out_dir, src,
                                            output_dir=os.path.join(out_dir, "validation"),
                                            resample=meth[1],
                                            full=mountain_qa,
                                            mountain=mountain_qa)
                                        dv.write_dgiwg_compliance(
                                            out_dir, rep, source_path=src,
                                            terrain_qa=qa)
                                    except Exception as qe:
                                        self._q.put(("log", "     Terrain QA warning: %s" % qe))
                                except Exception as ve:
                                    val_results.append(
                                        {"name": "%s [%s]" % (name, meth[2]),
                                         "error": str(ve)})
                                    self._q.put(("log",
                                        "     Validation could not run: %s" % ve))
                            entry["methods"].append(mrec)
                        else:
                            self._q.put(("file_done", (idx+1, total_f, out_dir)))
                            if do_validate and not self._stop.is_set():
                                self._q.put(("log", "   Validating…"))
                                try:
                                    # v0.37: pass the actually-resolved
                                    # resampler (captured above from convert_
                                    # geo()/convert_utm()'s return value)
                                    # instead of letting the validator assume
                                    # Bilinear (DGED_Conversion_Review.md
                                    # Finding 2).
                                    rep, tiles = dv.run_validation(
                                        out_dir, src=src, max_diff=max_diff,
                                        resample=resamp_used)
                                    val_results.append({"name": name, "src": src,
                                                         "rep": rep, "tiles": tiles,
                                                         "resample": resamp_used})
                                    self._q.put(("log",
                                        "   Validation: PASS=%d  WARN=%d  FAIL=%d  -> %s"
                                        % (rep.n_pass, rep.n_warn, rep.n_fail,
                                           # v0.37: shared 3-tier rule
                                           # (Finding 4) -- see
                                           # dv.overall_result()'s docstring.
                                           dv.overall_result(rep.n_pass,
                                               rep.n_warn, rep.n_fail))))
                                    try:
                                        from dem2dged_terrain import run_terrain_qa
                                        qa = run_terrain_qa(
                                            out_dir, src,
                                            output_dir=os.path.join(out_dir, "validation"),
                                            resample=resamp_used or "bilinear",
                                            full=mountain_qa,
                                            mountain=mountain_qa)
                                        dv.write_dgiwg_compliance(
                                            out_dir, rep, source_path=src,
                                            terrain_qa=qa)
                                        self._q.put(("log", "   Terrain QA written"))
                                    except Exception as qe:
                                        self._q.put(("log", "   Terrain QA warning: %s" % qe))
                                except Exception as ve:
                                    val_results.append({"name": name, "error": str(ve)})
                                    self._q.put(("log", "   Validation could not run: %s" % ve))

                    if compare_methods and entry["methods"]:
                        cmp_entries.append(entry)
                        self._q.put(("file_done", (idx+1, total_f, base_dir)))

                # ── Resampling Comparison Report (v0.33) ─────────────────────
                if cmp_entries and not self._stop.is_set():
                    try:
                        cmp_path = os.path.join(dst, dc.REPORT_FILENAME)
                        dc.write_comparison_report(cmp_entries, cmp_path)
                        self._q.put(("cmp_report", cmp_path))
                        self._q.put(("log",
                            "\nResampling comparison report written: %s" % cmp_path))
                        for e in cmp_entries:
                            ok = [m for m in e["methods"] if m.get("stats")]
                            if ok:
                                best = min(ok, key=lambda m: m["stats"]["rmse"])
                                self._q.put(("log",
                                    "  %s: most accurate = %s  (RMSE %.4f m)"
                                    % (e["name"], best["label"],
                                       best["stats"]["rmse"])))
                    except Exception as ce:
                        self._q.put(("log",
                            "\nWARNING: could not write comparison report (%s)" % ce))

                if do_validate and val_results:
                    try:
                        txt_path  = os.path.join(dst, "DGED_Validation_Report.txt")
                        html_path = os.path.join(dst, "DGED_Validation_Report.html")
                        with open(txt_path, "w", encoding="utf-8") as f:
                            for r in val_results:
                                if r.get("rep"):
                                    f.write("\n".join(r["rep"].lines) + "\n\n")
                                else:
                                    f.write("%s: could not validate (%s)\n\n"
                                            % (r["name"], r.get("error")))
                        dv.write_html_report(val_results, html_path)
                        self._q.put(("report", html_path))
                        self._q.put(("log", "\nValidation report written: %s" % html_path))
                    except Exception as re:
                        self._q.put(("log",
                            "\nWARNING: could not write validation report (%s)" % re))

                if self._stop.is_set():
                    self._q.put(("done", "stopped"))
                else:
                    self._q.put(("done", "ok:%s" % dst))

            except Exception as e:
                import traceback
                self._q.put(("done", "error: %s\n%s" % (e, traceback.format_exc())))

        threading.Thread(target=worker, daemon=True).start()

    def _stop_conv(self):
        self._stop.set()
        self._set_status("Stopping...", "#f39c12")

    def _poll_queue(self):
        try:
            while True:
                kind, val = self._q.get_nowait()
                if kind == "log":
                    self._log(val)
                elif kind == "pct":
                    self.progress["value"] = val
                elif kind == "file_hdr":
                    idx, total, name = val
                    self._log("\n-- File %d/%d: %s" % (idx, total, name))
                    self.file_progress_lbl.config(
                        text="File %d of %d" % (idx, total))
                elif kind == "file_done":
                    idx, total, out = val
                    self._log("   Done -> %s" % out)
                elif kind == "report":
                    self._last_report_path = val
                elif kind == "cmp_report":
                    self._last_cmp_report_path = val
                elif kind == "done":
                    self.go_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self.file_progress_lbl.config(text="")
                    if val.startswith("ok:"):
                        self.progress["value"] = 100
                        self._set_status("All done!", GREEN)
                        self._log("\nAll conversions complete!")
                        msg = ("All %d file(s) converted!\n\nOutput saved to:\n%s"
                               % (len(self._files), val[3:]))
                        if self._last_report_path:
                            msg += "\n\nValidation report:\n%s" % self._last_report_path
                        if self._last_cmp_report_path:
                            msg += ("\n\nResampling comparison report:\n%s"
                                    % self._last_cmp_report_path)
                        messagebox.showinfo("Conversion complete", msg)
                    elif val == "stopped":
                        self._set_status("Stopped.", "#f39c12")
                        self._log("\nConversion stopped by user.")
                        messagebox.showwarning(
                            "Stopped",
                            "Conversion was stopped before all files finished.\n"
                            "Any tiles already written have been kept.")
                    elif val.startswith("error:"):
                        detail = val[len("error:"):].strip()
                        self.progress["value"] = 0
                        self._set_status("Error - see log.", ACCENT)
                        self._log("\nERROR: %s" % detail)
                        messagebox.showerror(
                            "Conversion failed",
                            "The conversion stopped with an error:\n\n%s" % detail)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_queue)


if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        import traceback
        error_msg = "FATAL ERROR:\n\n%s\n\n%s" % (str(e), traceback.format_exc())
        print(error_msg)
        try:
            messagebox.showerror("Error", error_msg)
        except:
            pass
        sys.exit(1)

# end of dem2dged_gui.py (v0.34)
