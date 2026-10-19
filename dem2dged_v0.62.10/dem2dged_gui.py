# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.10
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

import sys, os, math, threading, queue, time, json
import shutil, subprocess, tempfile, traceback

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
    APP_VERSION = "0.62.10"   # fallback; keep in sync with dem2dged_lib.VERSION
    APP_VERSION_DISPLAY = "0.62.10"

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

# Evidence package workflow (v0.61.3). This is kept at module level so the
# packaged executable includes the same seven-step evidence checker used by
# the command-line workflow.
try:
    import dem2dged_evidence as de
    _EVIDENCE_AVAILABLE = True
except Exception:
    de = None
    _EVIDENCE_AVAILABLE = False

# Beginner help for the evidence gate (v0.61.6): plain-language help window,
# hover tips and a pointer to EVIDENCE_GATE_BEGINNER_GUIDE.  Module level so
# PyInstaller bundles it; the GUI still works if it is missing.
try:
    import dem2dged_help as dh
    _HELP_AVAILABLE = True
except Exception:
    dh = None
    _HELP_AVAILABLE = False

# Reference finder (v0.62.0): looks up open Canadian / US lidar DEMs for the
# source extent and clips only that window. Network use happens only when the
# user presses "Find reference...".
try:
    import dem2dged_reference as dr
    _REFERENCE_AVAILABLE = True
except Exception:
    dr = None
    _REFERENCE_AVAILABLE = False

# Vertical-datum detection (v0.62.8): suggests the Source vertical EPSG code
# from the file, its metadata and files next to it. Evidence only; the operator
# confirms before anything is applied. Module level so PyInstaller bundles it.
try:
    import dem2dged_datum as dd
    _DATUM_AVAILABLE = True
except Exception:
    dd = None
    _DATUM_AVAILABLE = False

# Separate vertical correction (v0.62.9): used when PROJ has no strict chain for
# the declared datum (CGVD2013 on generic NAD83(CSRS) data). Module level so
# PyInstaller bundles it.
try:
    import dem2dged_vertical as dvt
    _VERTICAL_AVAILABLE = True
except Exception:
    dvt = None
    _VERTICAL_AVAILABLE = False

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
    ("optimize", "Optimize  (measure the real decimation, pick the most "
                 "accurate)"),
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
    cubic ringing), or 'optimize' (v0.36) to measure every candidate
    against ``src`` itself and use whichever is most accurate. v0.59.0
    changed WHAT is measured: each candidate now performs the real
    decimation to the requested post spacing and is scored against the true
    terrain height at each target post, instead of being scored on how well
    it reconstructed a point-sampled training grid. On steep terrain above
    roughly 8x the old measurement produced an inverted ranking; see
    dl.resolve_resampler()'s docstring. Any explicit override always takes precedence over 'auto',
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


def _reference_clip_worker_main():
    """Run one remote reference clip in a separate process for the GUI."""
    if len(sys.argv) != 4:
        print("reference clip worker requires request and result paths", flush=True)
        return 2
    request_path, result_path = sys.argv[2], sys.argv[3]
    try:
        with open(request_path, "r", encoding="utf-8") as stream:
            request = json.load(stream)
        result = dr.clip_candidate(
            request["candidate"],
            tuple(request["bbox"]),
            request["out_dir"],
            level=request.get("level"),
            source_path=request.get("source_path"),
            log=lambda message: print(message, flush=True),
            timeout=request.get("timeout", dr.DEFAULT_GDAL_HTTP_TIMEOUT),
            max_cells=request.get("max_cells", dr.DEFAULT_MAX_CELLS),
        )
        payload = {"ok": True, "result": result}
        with open(result_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        return 0
    except Exception as exc:
        payload = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        try:
            with open(result_path, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
        except Exception:
            pass
        print("ERROR: %s" % exc, flush=True)
        traceback.print_exc()
        return 1


def _reference_search_worker_main():
    """Run one reference SEARCH (catalog query + coverage probes) in a child process.

    v0.62.6: GDAL /vsicurl/ reads must run on the MAIN thread of a separate
    process, never in a thread of the GUI process.  DIAG_TK_BISECT showed that
    after a /vsicurl/ read in a Python thread, the next DLL load in the main
    thread (tkinter's first load, native dialogs) deadlocks; Windows reports
    that as "Not responding".  The GUI therefore only polls this process.
    """
    if len(sys.argv) != 4:
        print("reference search worker requires request and result paths", flush=True)
        return 2
    request_path, result_path = sys.argv[2], sys.argv[3]
    try:
        with open(request_path, "r", encoding="utf-8") as stream:
            request = json.load(stream)
        box = dr.extent_wgs84(request["source_path"])
        res = dr.fetch_reference(
            bbox=box,
            level=request.get("level"),
            list_only=True,
            operation_timeout=request.get("operation_timeout", dr.DEFAULT_OPERATION_TIMEOUT),
            log=lambda message: print(message, flush=True),
        )
        payload = {
            "ok": True,
            "bbox": list(box),
            "candidates": res["candidates"],
            "errors": res["errors"],
        }
        with open(result_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, default=str)
        return 0
    except Exception as exc:
        payload = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        try:
            with open(result_path, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
        except Exception:
            pass
        print("ERROR: %s" % exc, flush=True)
        traceback.print_exc()
        return 1


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
        self._vertical_detections = {}   # abs source path -> detection record (v0.62.8)
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
        # v0.61.1: source metadata decisions are explicit and separate from
        # the output metadata fields below. A PixelIsArea source is common,
        # but blindly changing its tag to Point can introduce a half-post
        # shift. The selected decision is recorded in source_metadata.json;
        # the source raster itself is never modified.
        mrow = tk.Frame(adv, bg=LIGHT); mrow.pack(fill="x", pady=2)
        tk.Label(mrow, text="Source registration:", width=14, anchor="w",
                 bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
        self.src_registration_var = tk.StringVar(
            value="PixelIsArea -> DGED Point (explicit)")
        self.src_registration_cb = ttk.Combobox(
            mrow, textvariable=self.src_registration_var, state="readonly",
            width=39, font=("Segoe UI",10))
        self.src_registration_cb["values"] = [
            "PixelIsArea -> DGED Point (explicit)",
            "Source is already PixelIsPoint",
        ]
        self.src_registration_cb.current(0)
        self.src_registration_cb.pack(side="left")
        tk.Label(mrow,
                 text="  Required when source metadata says PixelIsArea",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY).pack(side="left")

        urow = tk.Frame(adv, bg=LIGHT); urow.pack(fill="x", pady=2)
        tk.Label(urow, text="Source elevation unit:", width=14, anchor="w",
                 bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
        self.src_unit_var = tk.StringVar(value="metre")
        tk.Entry(urow, textvariable=self.src_unit_var, width=12,
                 font=("Segoe UI",10), relief="flat", bg=WHITE,
                 bd=1).pack(side="left")
        tk.Label(urow,
                 text="  Explicit operator declaration when the raster tag is empty",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY).pack(side="left")

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
             "Required if the source has no vertical CRS; enter EPSG:3855 "
             "only when the source is verified as EGM2008"),
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
            if var_name == "src_vert_var":
                self._btn(r, "Detect", self._detect_vertical_datum).pack(
                    side="left", padx=(6, 0))
            tk.Label(r, text="  "+tip, font=("Segoe UI",9),
                     bg=LIGHT, fg=GRAY).pack(side="left")

        # v0.61.2: full DGIWG evidence is intentionally separate from the
        # source-to-output resampling comparison. The reference must be an
        # independent control dataset, and horizontal quality measures cannot
        # be inferred from elevation-value residuals.
        self._section(inner, "DGIWG Accuracy Evidence (required for full gate)")
        helprow = tk.Frame(inner, bg=LIGHT); helprow.pack(fill="x", pady=(0,4))
        help_btn = self._btn(helprow, "?  How to use", self._show_evidence_help)
        help_btn.pack(side="left")
        tk.Label(helprow,
                 text="  New to this? Click for a step-by-step explanation "
                      "of the reference, the manifest and every box.",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY).pack(side="left")
        erow = tk.Frame(inner, bg=LIGHT); erow.pack(fill="x", pady=2)
        tk.Label(erow, text="Independent reference:", width=21, anchor="w",
                 bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
        self.reference_dem_var = tk.StringVar(value="")
        _ref_entry = tk.Entry(erow, textvariable=self.reference_dem_var,
                 font=("Segoe UI",10), relief="flat", bg=WHITE,
                 bd=1)
        _ref_entry.pack(side="left", fill="x", expand=True, padx=(0,6))
        self._tip(_ref_entry, "reference_dem")
        self._tip(erow.winfo_children()[0], "reference_dem")
        self._btn(
            erow, "Browse…",
            lambda: self.reference_dem_var.set(
                filedialog.askopenfilename(
                    title="Select independent accuracy reference",
                    filetypes=[("Raster files", "*.tif *.tiff *.img *.vrt"),
                               ("All files", "*.*")]) or
                self.reference_dem_var.get())).pack(side="left")
        _find_btn = self._btn(erow, "Find reference…", self._find_reference_dialog)
        _find_btn.pack(side="left", padx=(5,0))
        self._tip(_find_btn, "find_reference")

        evidence_row = tk.Frame(inner, bg=LIGHT); evidence_row.pack(fill="x", pady=(5,2))
        tk.Label(evidence_row, text="Evidence manifest:", width=21, anchor="w",
                 bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
        self.evidence_manifest_var = tk.StringVar(value="")
        _man_entry = tk.Entry(evidence_row, textvariable=self.evidence_manifest_var,
                 font=("Segoe UI",10), relief="flat", bg=WHITE,
                 bd=1)
        _man_entry.pack(side="left", fill="x", expand=True, padx=(0,6))
        self._tip(_man_entry, "evidence_manifest")
        self._tip(evidence_row.winfo_children()[0], "evidence_manifest")
        self._btn(
            evidence_row, "Browse…",
            lambda: self.evidence_manifest_var.set(
                filedialog.askopenfilename(
                    title="Select DEM2DGED evidence manifest",
                    filetypes=[("Evidence manifest", "compliance_evidence.json"),
                               ("JSON files", "*.json"),
                               ("All files", "*.*")]) or
                self.evidence_manifest_var.get())).pack(side="left")
        _load_btn = self._btn(evidence_row, "Load", self._load_evidence_manifest)
        _load_btn.pack(side="left", padx=(5,0))
        self._tip(_load_btn, "load")
        _tpl_btn = self._btn(evidence_row, "Create template…",
                  self._create_evidence_template)
        _tpl_btn.pack(side="left", padx=(5,0))
        self._tip(_tpl_btn, "create_template")
        tk.Label(
            inner,
            text="The manifest loads evidence values into this run; it never creates evidence or authority acceptance.\n"
                 "No manifest yet? Click 'Create template…', fill it in, then 'Browse…' and 'Load'.",
            justify="left",
            font=("Segoe UI",8), bg=LIGHT, fg=GRAY).pack(anchor="w", padx=(21,0))

        for label, var_name, tip in [
            ("Reference identifier:", "reference_id_var",
             "Dataset/version/date or control survey ID"),
            ("Evaluation method:", "accuracy_method_var",
             "STANAG 2215-aligned procedure or quality-plan ID"),
            ("Source horizontal CE90:", "source_hacc_var",
             "Independent source eligibility evidence, metres"),
            ("Source vertical LE90:", "source_vacc_var",
             "Independent source eligibility evidence, metres"),
            ("Output absolute H CE90:", "reference_hce90_var",
             "Measured output horizontal CE90, metres"),
            ("Output random H 90%:", "reference_hrandom_var",
             "Random horizontal error per point, metres"),
            ("Output relative H 90%:", "reference_hrelative_var",
             "Relative horizontal accuracy, metres"),
            ("Output relative V 90%:", "reference_vrelative_var",
             "Relative vertical accuracy, metres"),
        ]:
            r = tk.Frame(inner, bg=LIGHT); r.pack(fill="x", pady=2)
            _lbl = tk.Label(r, text=label, width=21, anchor="w",
                     bg=LIGHT, font=("Segoe UI",10))
            _lbl.pack(side="left")
            v = tk.StringVar(value="")
            setattr(self, var_name, v)
            _ent = tk.Entry(r, textvariable=v, width=24, font=("Segoe UI",10),
                     relief="flat", bg=WHITE, bd=1)
            _ent.pack(side="left")
            self._tip(_lbl, var_name[:-4])
            self._tip(_ent, var_name[:-4])
            tk.Label(r, text="  " + tip, font=("Segoe UI",9),
                     bg=LIGHT, fg=GRAY).pack(side="left")

        grow = tk.Frame(inner, bg=LIGHT); grow.pack(fill="x", pady=(4,2))
        self.strict_compliance_var = tk.BooleanVar(value=False)
        _strict_cb = tk.Checkbutton(
            grow,
            text="Require full implemented DGIWG 250 evidence gate (HOLD if incomplete)",
            variable=self.strict_compliance_var,
            bg=LIGHT, font=("Segoe UI",9,"bold"), fg=DARK,
            activebackground=LIGHT)
        _strict_cb.pack(anchor="w")
        self._tip(_strict_cb, "strict")
        tk.Label(
            grow,
            text=(dh.CHECKLIST_LINE if _HELP_AVAILABLE else
                  "Needs: independent reference, evidence manifest, measured accuracy values."),
            font=("Segoe UI",8), bg=LIGHT, fg=GRAY, justify="left",
            wraplength=640).pack(anchor="w", padx=(20,0))
        tk.Label(
            grow,
            text="This is technical evidence, not NATO or national authority certification.",
            font=("Segoe UI",8), bg=LIGHT, fg=GRAY).pack(anchor="w", padx=(20,0))

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

    def _tip(self, widget, key):
        """Attach a plain-language hover tip (v0.61.6); never fatal."""
        if _HELP_AVAILABLE:
            try:
                dh.add_tooltip(widget, key)
            except Exception:
                pass

    def _show_evidence_help(self):
        """Open the beginner help window for the evidence gate (v0.61.6)."""
        if not _HELP_AVAILABLE:
            messagebox.showinfo(
                "Help unavailable",
                "dem2dged_help.py is missing. See EVIDENCE_GATE_BEGINNER_GUIDE.html "
                "in the release folder.")
            return
        dh.show_help_window(self, dark=DARK, light=LIGHT, mid=MID)

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

    def _find_reference_dialog(self):
        """Look up open CA/US lidar DEMs for the first source file (v0.62.0)."""
        if not _REFERENCE_AVAILABLE:
            messagebox.showerror(
                "Reference finder unavailable",
                "dem2dged_reference.py is not available in this installation.")
            return
        if not self._files:
            messagebox.showinfo(
                "Select a source DEM first",
                "Add your source DEM(s) at the top of the window first. The search area "
                "is taken from the first file.")
            return
        source = self._files[0]
        level = self.level_var.get().split()[0]
        win = tk.Toplevel(self)
        win.title("Find an independent reference (Canada / US)")
        win.geometry("980x640")
        win.configure(bg=LIGHT)
        tk.Label(win, text="Search area: " + os.path.basename(source) + "   |   DGED level " + level,
                 font=("Segoe UI",10,"bold"), bg=LIGHT, fg=DARK).pack(anchor="w", padx=10, pady=(10,0))
        tk.Label(win, justify="left", wraplength=940, font=("Segoe UI",9), bg=LIGHT, fg=GRAY,
                 text="Search contacts public servers (NRCan CanElevation, USGS 3DEP) and sends only "
                      "the bounding box of your source. Download copies only the pixels inside your "
                      "area (no resampling). The declared accuracy is the provider's, not measured "
                      "by DEM2DGED, and a download does not prove independence from your source."
                 ).pack(anchor="w", padx=10, pady=(2,6))
        cols = ("n", "country", "dataset", "res", "date", "le90", "fit", "cover", "cells")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=9)
        for col, text, width in (("n","#",32),("country","Country",60),("dataset","Dataset",330),
                                 ("res","Res (m)",60),("date","Date",90),("le90","LE90 (m)",70),
                                 ("fit","Fit for level",110),("cover","Data in area",85),
                                 ("cells","Window (M cells)",100)):
            tree.heading(col, text=text); tree.column(col, width=width, anchor="w")
        tree.pack(fill="x", padx=10)
        detail = scrolledtext.ScrolledText(win, height=11, wrap="word", font=("Segoe UI",9),
                                           bg=WHITE, relief="flat")
        detail.pack(fill="both", expand=True, padx=10, pady=6)
        status = tk.Label(win, text="Press Search.", font=("Segoe UI",9), bg=LIGHT, fg=GRAY, anchor="w")
        status.pack(fill="x", padx=10)
        bar = tk.Frame(win, bg=LIGHT); bar.pack(fill="x", padx=10, pady=8)
        max_cells_var = tk.StringVar(value="%g" % (dr.DEFAULT_MAX_CELLS / 1e6))
        state = {
            "cands": [], "bbox": None, "q": queue.Queue(), "busy": False,
            "process": None, "temp_dir": None, "result_path": None,
            "log_path": None, "log_handle": None, "started_at": None,
        }

        def cleanup_reference_files():
            handle = state.pop("log_handle", None)
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            temp_dir = state.pop("temp_dir", None)
            state.pop("result_path", None)
            state.pop("log_path", None)
            state.pop("started_at", None)
            state.pop("mode", None)
            state.pop("limit", None)
            state.pop("log_pos", None)
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

        def terminate_reference_process():
            process = state.get("process")
            if process is not None and process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            state["process"] = None
            cleanup_reference_files()

        def show(text):
            detail.config(state="normal"); detail.delete("1.0", "end")
            detail.insert("1.0", text); detail.config(state="disabled")

        def on_select(_e=None):
            sel = tree.selection()
            if not sel:
                return
            c = state["cands"][int(sel[0])]
            src = c["source"]
            cov = c.get("coverage")
            covtext = ("%.0f%% of your area holds heights in this dataset." % (100 * cov)
                       if cov is not None else "Coverage of your area could not be checked.")
            if cov is not None and cov < dr.MIN_COVERAGE:
                covtext += " Not recommended: choose a dataset with more data in your area."
            if c.get("window_cells"):
                covtext += ("\nDownload window: %.1f million cells (about %.0f MB as uncompressed "
                            "Float32). The 'Max cells' box limits it." % (
                                c["window_cells"] / 1e6, c["window_cells"] * 4 / 1e6))
            show(covtext + "\n\n" + "%s\n\nProvider: %s\nProduct: %s\nDeclared accuracy: %s\nVertical datum: %s\n"
                 "License: %s\nLimits: %s\n\nFit for DGED level %s: %s - %s\n\nSpecification: %s" % (
                     c["title"], src["provider"], src["product"], src["accuracy_statement"],
                     src["vertical_datum"], src["license"], src["limits"], level,
                     c["suitability"], c["suitability_text"], src["spec_url"]))
        tree.bind("<<TreeviewSelect>>", on_select)

        def poll():
            try:
                while True:
                    kind, payload = state["q"].get_nowait()
                    if kind == "log":
                        self._log(payload)
                    elif kind == "found":
                        state["busy"] = False
                        state["bbox"], state["cands"], errors = payload
                        tree.delete(*tree.get_children())
                        for i, c in enumerate(state["cands"]):
                            sz = c["source"].get("vertical_le90_m")
                            tree.insert("", "end", iid=str(i), values=(
                                c["number"], c["country"], c["title"],
                                ("%g" % c["resolution_m"]) if c["resolution_m"] else "?",
                                c.get("date") or "?", ("%.2f" % sz) if sz else "n/a",
                                c["suitability"],
                                ("%.0f%%" % (100 * c["coverage"])) if c.get("coverage") is not None else "?",
                                ("%.1f" % (c["window_cells"] / 1e6)) if c.get("window_cells") else "?"))
                        msg = "%d dataset(s) found." % len(state["cands"])
                        if errors:
                            msg += " Some services failed: " + "; ".join(
                                e["source_id"] for e in errors)
                        status.config(text=msg)
                        if not state["cands"]:
                            show("Nothing found. The area may be outside Canada/US lidar coverage, "
                                 "or the services could not be reached (see the main log).")
                    elif kind == "done":
                        state["busy"] = False
                        state["process"] = None
                        res = payload
                        self.reference_dem_var.set(res["output"])
                        import json as _json
                        side = _json.load(open(res["sidecar"], encoding="utf-8"))
                        self.reference_id_var.set(side["reference_identifier"])
                        status.config(text="Saved: " + res["output"])
                        messagebox.showinfo(
                            "Reference downloaded",
                            "Saved:\n%s\n\nThe reference path and identifier were filled in.\n\n"
                            "Please read:\n- %s" % (res["output"], "\n- ".join(side["warnings"])),
                            parent=win)
                    elif kind == "error":
                        state["busy"] = False
                        state["process"] = None
                        status.config(text="Failed: " + payload)
                        messagebox.showerror("Reference finder", payload, parent=win)
            except queue.Empty:
                pass
            if win.winfo_exists():
                win.after(200, poll)
        poll()

        def drain_worker_log(final=False):
            """Copy new lines of the worker's log into the main log and the status line."""
            path = state.get("log_path")
            if not path or not os.path.isfile(path):
                return
            try:
                with open(path, "rb") as stream:
                    stream.seek(state.get("log_pos", 0))
                    data = stream.read()
            except Exception:
                return
            if not data:
                return
            if not final:
                cut = data.rfind(b"\n")
                if cut < 0:
                    return
                data = data[:cut + 1]
            state["log_pos"] = state.get("log_pos", 0) + len(data)
            last = ""
            for line in data.decode("utf-8", errors="replace").splitlines():
                if line.strip():
                    self._log(line.strip())
                    last = line.strip()
            if last and not final and state.get("process") is not None:
                status.config(text=("Working: " + last)[:160])

        def launch_worker(mode, request, limit, status_text):
            """Run one reference job ("search" or "clip") in a CHILD PROCESS (v0.62.6).

            GDAL /vsicurl/ reads never run in a thread of this GUI process: after
            such a thread, the next DLL load in the main thread (tkinter, native
            dialogs) deadlocks and Windows shows "Not responding".
            """
            state["busy"] = True
            status.config(text=status_text)
            temp_dir = tempfile.mkdtemp(prefix="dem2dged_reference_")
            request_path = os.path.join(temp_dir, "request.json")
            result_path = os.path.join(temp_dir, "result.json")
            log_path = os.path.join(temp_dir, "worker.log")
            state.update(temp_dir=temp_dir, result_path=result_path, log_path=log_path,
                         started_at=time.monotonic(), mode=mode, limit=limit, log_pos=0)
            flag = "--reference-%s-worker" % mode
            try:
                with open(request_path, "w", encoding="utf-8") as stream:
                    json.dump(request, stream)
                if getattr(sys, "frozen", False):
                    command = [sys.executable, flag, request_path, result_path]
                else:
                    command = [sys.executable, os.path.abspath(__file__),
                               flag, request_path, result_path]
                log_handle = open(log_path, "w", encoding="utf-8")
                state["log_handle"] = log_handle
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = subprocess.Popen(
                    command,
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
                state["process"] = process
                win.after(100, poll_worker_process)
            except Exception as exc:
                state["busy"] = False
                state["process"] = None
                cleanup_reference_files()
                messagebox.showerror("Reference finder", str(exc), parent=win)

        def poll_worker_process():
            process = state.get("process")
            if process is None:
                return
            drain_worker_log()
            mode = state.get("mode") or "clip"
            label = "search" if mode == "search" else "download"
            started_at = state.get("started_at") or time.monotonic()
            limit = state.get("limit") or dr.DEFAULT_OPERATION_TIMEOUT
            if time.monotonic() - started_at > limit:
                drain_worker_log(final=True)
                terminate_reference_process()
                state["busy"] = False
                state["q"].put((
                    "error",
                    "reference %s exceeded the %.0f-second process limit" % (label, limit),
                ))
                return
            returncode = process.poll()
            if returncode is None:
                if win.winfo_exists():
                    win.after(200, poll_worker_process)
                return
            state["process"] = None
            drain_worker_log(final=True)
            log_handle = state.pop("log_handle", None)
            if log_handle is not None:
                try:
                    log_handle.close()
                except Exception:
                    pass
            result_path = state.get("result_path")
            try:
                payload = None
                if result_path and os.path.isfile(result_path):
                    with open(result_path, "r", encoding="utf-8") as stream:
                        payload = json.load(stream)
                if returncode != 0:
                    error = ((payload or {}).get("error")
                             or "reference %s process exited with code %d" % (label, returncode))
                    state["q"].put(("error", error))
                elif payload is None:
                    state["q"].put(("error", "reference %s produced no result file" % label))
                elif not payload.get("ok"):
                    state["q"].put(("error", payload.get("error") or "reference %s failed" % label))
                elif mode == "search":
                    state["q"].put(("found", (tuple(payload["bbox"]),
                                              payload["candidates"], payload["errors"])))
                else:
                    state["q"].put(("done", payload["result"]))
            except Exception as exc:
                state["q"].put(("error", str(exc)))
            finally:
                cleanup_reference_files()

        def do_search():
            if state["busy"]:
                return
            launch_worker(
                "search",
                {"source_path": source, "level": level,
                 "operation_timeout": dr.DEFAULT_OPERATION_TIMEOUT},
                dr.DEFAULT_OPERATION_TIMEOUT + 30.0,
                "Searching in a separate process (up to %.0f seconds)..." %
                dr.DEFAULT_OPERATION_TIMEOUT)

        def do_download():
            if state["busy"]:
                messagebox.showinfo("Please wait", "A search or download is still running.", parent=win)
                return
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Select a dataset", "Select a row first.", parent=win)
                return
            cand = state["cands"][int(sel[0])]
            try:
                cap_m = float(max_cells_var.get().replace(",", "").strip())
                if cap_m <= 0:
                    raise ValueError("not positive")
            except ValueError:
                messagebox.showerror(
                    "Max cells",
                    "'Max cells (millions)' must be a positive number, for example 40.",
                    parent=win)
                return
            cap = int(cap_m * 1e6)
            cells = cand.get("window_cells")
            if cap > dr.ABSOLUTE_MAX_CELLS:
                messagebox.showerror(
                    "Max cells",
                    "The largest window this tool will download is %.0f million cells." %
                    (dr.ABSOLUTE_MAX_CELLS / 1e6), parent=win)
                return
            if cells and cells > cap:
                need_m = int(cells // 1e6) + 2
                if need_m * 1e6 > dr.ABSOLUTE_MAX_CELLS:
                    messagebox.showerror(
                        "Window too large",
                        "This window has %.1f million cells, more than the %.0f million "
                        "this tool will download. Use a smaller source area." % (
                            cells / 1e6, dr.ABSOLUTE_MAX_CELLS / 1e6), parent=win)
                    return
                if not messagebox.askyesno(
                        "Window is larger than the cap",
                        "Your search area covers %.1f million cells in this dataset, above the "
                        "'Max cells' limit of %.0f million.\n\nRaise the limit to %d million "
                        "and continue?\n(About %.0f MB as uncompressed Float32; the download "
                        "can take several minutes.)" % (
                            cells / 1e6, cap_m, need_m, cells * 4 / 1e6), parent=win):
                    return
                max_cells_var.set(str(need_m))
                cap = need_m * 1000000
            default_dir = os.path.join(self.dst_var.get().strip() or os.path.dirname(source), "references")
            folder = filedialog.askdirectory(title="Save the clipped reference in", initialdir=os.path.dirname(default_dir) or None)
            if not folder:
                return
            size_text = ("%.1f million cells" % (cells / 1e6)) if cells else "up to %.0f million cells" % (cap / 1e6)
            cov = cand.get("coverage")
            warn_text = ""
            if cov is not None and cov < dr.MIN_COVERAGE:
                warn_text = ("\n\nWarning: only %.0f%% of your area holds heights in this "
                             "dataset. A better dataset may exist." % (100 * cov))
            if not messagebox.askyesno(
                    "Download only your area?",
                    "Download the pixels of\n%s\ninside your search area from the public server "
                    "and save them in\n%s ?\n\nOnly the bounding box is sent. Window: %s "
                    "(limit %.0f million cells).%s" % (
                        cand["title"], folder, size_text, cap / 1e6, warn_text),
                    parent=win):
                return
            launch_worker(
                "clip",
                {"candidate": cand, "bbox": list(state["bbox"]), "out_dir": folder,
                 "level": level, "source_path": source, "max_cells": cap,
                 "timeout": dr.DEFAULT_GDAL_HTTP_TIMEOUT},
                dr.clip_time_limit(cells or cap),
                "Downloading %s in a separate process (limit %.0f seconds)..." % (
                    size_text, dr.clip_time_limit(cells or cap)))

        def cancel_worker():
            if state.get("process") is None:
                status.config(text="No active search or download.")
                return
            label = "search" if state.get("mode") == "search" else "download"
            terminate_reference_process()
            state["busy"] = False
            status.config(text="Reference %s cancelled." % label)

        def close_window():
            terminate_reference_process()
            win.destroy()

        self._btn(bar, "Search", do_search).pack(side="left")
        self._btn(bar, "Download clip", do_download).pack(side="left", padx=(6,0))
        self._btn(bar, "Cancel", cancel_worker).pack(side="left", padx=(6,0))
        tk.Label(bar, text="Max cells (millions):", bg=LIGHT, fg=DARK,
                 font=("Segoe UI", 9)).pack(side="left", padx=(16, 4))
        tk.Entry(bar, textvariable=max_cells_var, width=6).pack(side="left")
        self._btn(bar, "Close", close_window).pack(side="right")

    def _detect_vertical_datum(self):
        """Suggest the source vertical datum from the file, its metadata and
        files next to it (v0.62.8). Evidence only: nothing is applied until the
        operator presses Use."""
        if not _DATUM_AVAILABLE:
            messagebox.showerror(
                "Datum detection unavailable",
                "dem2dged_datum.py is not available in this installation.")
            return
        if not self._files:
            messagebox.showinfo(
                "Select a source DEM first",
                "Add your source DEM(s) at the top of the window first.")
            return
        files = list(self._files[:20])
        results = []
        for path in files:
            try:
                results.append(dd.detect_vertical_datum(path))
            except Exception as exc:
                results.append({"source": path, "status": "none", "suggestion": None,
                                "evidence": [], "notes": ["detection failed: %s" % exc]})
        combined = dd.combine(results)
        for result in results:
            self._vertical_detections[os.path.abspath(result["source"])] = {
                "applied_epsg": None, "operator_confirmed": False, "result": result}
        win = tk.Toplevel(self)
        win.title("Detect source vertical datum")
        win.geometry("920x600")
        win.configure(bg=LIGHT)
        note = ("Checked %d file(s)." % len(files))
        if len(self._files) > len(files):
            note += " Only the first %d were checked." % len(files)
        tk.Label(win, text=note + "  Nothing is changed until you press Use.",
                 font=("Segoe UI", 9), bg=LIGHT, fg=GRAY, anchor="w").pack(
                     fill="x", padx=10, pady=(10, 0))
        box = scrolledtext.ScrolledText(win, wrap="word", font=("Consolas", 9),
                                        bg=WHITE, relief="flat")
        box.pack(fill="both", expand=True, padx=10, pady=8)
        box.insert("1.0", dd.format_report(results, combined))
        box.config(state="disabled")
        bar = tk.Frame(win, bg=LIGHT)
        bar.pack(fill="x", padx=10, pady=8)
        suggestion = combined.get("suggestion")

        def use():
            self.src_vert_var.set(suggestion["epsg"])
            for result in results:
                self._vertical_detections[os.path.abspath(result["source"])] = {
                    "applied_epsg": suggestion["epsg"], "operator_confirmed": True,
                    "result": result}
            self._log("Source vertical set to EPSG:%s (%s) from detected evidence "
                      "(reliability %s). Confirm it against the provider's metadata." % (
                          suggestion["epsg"], suggestion["datum_key"], suggestion["confidence"]))
            win.destroy()

        if suggestion:
            self._btn(bar, "Use EPSG:%s (%s)" % (suggestion["epsg"], suggestion["datum_key"]),
                      use).pack(side="left")
        self._btn(bar, "Close", win.destroy).pack(side="right")

    def _create_evidence_template(self):
        if not _EVIDENCE_AVAILABLE:
            messagebox.showerror(
                "Evidence workflow unavailable",
                "dem2dged_evidence.py is not available in this installation.")
            return
        folder = filedialog.askdirectory(title="Create seven-step evidence package in")
        if not folder:
            return
        level = self.level_var.get().split()[0]
        try:
            paths = de.create_evidence_package(folder, level)
        except Exception as exc:
            messagebox.showerror("Evidence package could not be created", str(exc))
            return
        self.evidence_manifest_var.set(paths["manifest"])
        self._log("Evidence package template created: %s" % paths["manifest"])
        messagebox.showinfo(
            "Evidence package created",
            "Populate the manifest and documents, then use Load or run the evidence checker.\n\n"
            "Authority acceptance remains pending until an authorized reviewer signs it.")

    def _load_evidence_manifest(self):
        if not _EVIDENCE_AVAILABLE:
            messagebox.showerror(
                "Evidence workflow unavailable",
                "dem2dged_evidence.py is not available in this installation.")
            return
        manifest_path = self.evidence_manifest_var.get().strip()
        if not manifest_path or not os.path.isfile(manifest_path):
            messagebox.showerror("Evidence manifest not found", manifest_path or "Select a manifest first.")
            return
        try:
            with open(manifest_path, encoding="utf-8") as stream:
                manifest = json.load(stream)
            if manifest.get("schema") != de.SCHEMA:
                raise ValueError("unsupported evidence schema: %s" % manifest.get("schema"))
            source = manifest.get("source", {})
            control = manifest.get("independent_control", {})
            evaluation = manifest.get("evaluation", {})
            declared = evaluation.get("declared_results", {})
            self.src_vert_var.set(str(source.get("vertical_epsg") or ""))
            self.source_hacc_var.set(str(source.get("horizontal_ce90_m") or ""))
            self.source_vacc_var.set(str(source.get("vertical_le90_m") or ""))
            reference_value = str(control.get("dataset_path") or "")
            if reference_value and not os.path.isabs(reference_value):
                reference_value = os.path.abspath(os.path.join(
                    os.path.dirname(manifest_path), reference_value))
            self.reference_dem_var.set(reference_value)
            self.reference_id_var.set(str(control.get("identifier") or ""))
            self.accuracy_method_var.set(str(evaluation.get("method_identifier") or ""))
            self.reference_hce90_var.set(str(declared.get("horizontal_absolute_ce90_m") or ""))
            self.reference_hrandom_var.set(str(declared.get("horizontal_random_90_m") or ""))
            self.reference_hrelative_var.set(str(declared.get("horizontal_relative_90_m") or ""))
            self.reference_vrelative_var.set(str(declared.get("vertical_relative_90_m") or ""))
            self.abs_hacc_var.set(str(declared.get("horizontal_absolute_ce90_m") or "auto"))
            self.abs_vacc_var.set(str(declared.get("vertical_absolute_le90_m") or "auto"))
            report = de.evaluate_evidence(manifest, manifest_path)
            self._log("Evidence manifest loaded: technical readiness=%s; delivery acceptance=%s"
                       % (report.get("technical_readiness"), report.get("delivery_acceptance")))
            self._log("  This load copies declarations only; it does not make missing evidence valid.")
        except Exception as exc:
            messagebox.showerror("Evidence manifest could not be loaded", str(exc))

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
        strict_compliance = self.strict_compliance_var.get()
        reference_dem = self.reference_dem_var.get().strip() or None
        reference_identifier = self.reference_id_var.get().strip() or None
        accuracy_method = self.accuracy_method_var.get().strip() or None

        def optional_nonnegative_float(var, label):
            text = var.get().strip()
            if not text:
                return None
            try:
                value = float(text)
            except ValueError:
                messagebox.showerror("Invalid accuracy evidence",
                                     "%s must be a number in metres." % label)
                raise
            if value < 0:
                messagebox.showerror("Invalid accuracy evidence",
                                     "%s cannot be negative." % label)
                raise ValueError(label)
            return value

        try:
            source_hacc = optional_nonnegative_float(
                self.source_hacc_var, "Source horizontal CE90")
            source_vacc = optional_nonnegative_float(
                self.source_vacc_var, "Source vertical LE90")
            reference_hce90 = optional_nonnegative_float(
                self.reference_hce90_var, "Output absolute horizontal CE90")
            reference_hrandom = optional_nonnegative_float(
                self.reference_hrandom_var, "Output random horizontal error")
            reference_hrelative = optional_nonnegative_float(
                self.reference_hrelative_var, "Output relative horizontal accuracy")
            reference_vrelative = optional_nonnegative_float(
                self.reference_vrelative_var, "Output relative vertical accuracy")
        except ValueError:
            return

        if reference_dem and not os.path.isfile(reference_dem):
            messagebox.showerror("Reference not found",
                                 "The independent reference file does not exist:\n" +
                                 reference_dem)
            return
        if strict_compliance:
            if not _VALIDATE_AVAILABLE:
                messagebox.showerror(
                    "Validator unavailable",
                    "Full DGIWG evidence mode requires dem2dged_validate.")
                return
            do_validate = True
            self.validate_var.set(True)
            missing_evidence = []
            for value, label in [
                (reference_dem, "independent reference"),
                (reference_identifier, "reference identifier"),
                (accuracy_method, "evaluation method"),
                (source_hacc, "source horizontal CE90"),
                (source_vacc, "source vertical LE90"),
                (reference_hce90, "output absolute horizontal CE90"),
                (reference_hrandom, "output random horizontal error"),
                (reference_hrelative, "output relative horizontal accuracy"),
                (reference_vrelative, "output relative vertical accuracy"),
            ]:
                if value is None:
                    missing_evidence.append(label)
            if missing_evidence:
                messagebox.showerror(
                    "Full evidence is incomplete",
                    "Strict DGIWG evidence mode requires:\n- " +
                    "\n- ".join(missing_evidence) +
                    "\n\nHow to fix: click '? How to use' in the "
                    "'DGIWG Accuracy Evidence' section, or create and load an "
                    "evidence manifest with 'Create template…' and 'Load'.\n"
                    "If you do not need a full DGIWG claim, untick "
                    "'Require full implemented DGIWG 250 evidence gate'.")
                return
            for value, label in [
                (self.abs_hacc_var.get().strip(), "Abs. H accuracy"),
                (self.abs_vacc_var.get().strip(), "Abs. V accuracy"),
            ]:
                if not value or value.lower() == "auto":
                    messagebox.showerror(
                        "Measured metadata required",
                        "%s must contain a measured or defensible predicted "
                        "dataset value in strict mode. The DGIWG goal cannot "
                        "be used as the estimate.\n\nType the measured number "
                        "in metres (for example 3.5), or fill it in the "
                        "evidence manifest and press 'Load'. See '? How to "
                        "use' for what these values mean." % label)
                    return

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
        if strict_compliance:
            self._log("Full DGIWG technical evidence gate: required")
            self._log("Independent reference: %s" % reference_dem)
        self._log("=" * 54)

        def worker():
            val_results = []
            cmp_entries = []
            converted_files = 0
            held_files = 0
            failed_files = 0
            runs_per_file = max(1, len(compare_methods))
            total_runs    = total_f * runs_per_file

            def write_evidence(out_dir, rep, src, qa, resampler):
                independent_qa = None
                error_budget = None
                reference_independent = None
                independence = None
                if reference_dem:
                    # v0.61.5: path, SHA-256 and content-similarity checks.
                    # A derived reference no longer aborts evidence writing;
                    # it is recorded as FAIL (or NOT_EVALUATED) in the report.
                    from dem2dged_terrain import assess_reference_independence
                    independence = assess_reference_independence(
                        src, reference_dem)
                    reference_independent = independence["independent"]
                    self._q.put(("log", "     Reference independence: %s%s" % (
                        independence["status"],
                        (" -- " + independence["reason"])
                        if independence.get("reason") else "")))
                if reference_independent is True:
                    from dem2dged_terrain import run_error_budget_qa, run_terrain_qa
                    independent_qa = run_terrain_qa(
                        out_dir, reference_dem,
                        output_dir=os.path.join(
                            out_dir, "validation", "independent_reference"),
                        resample=resampler or "bilinear",
                        full=mountain_qa, mountain=mountain_qa,
                        comparison_type="independent_reference")
                    error_budget = run_error_budget_qa(
                        out_dir, src, reference_dem,
                        output_dir=os.path.join(out_dir, "validation"),
                        resample=resampler or "bilinear")
                return dv.write_dgiwg_compliance(
                    out_dir, rep, source_path=src, terrain_qa=qa,
                    independent_qa=independent_qa, error_budget=error_budget,
                    compliance_profile="strict" if strict_compliance else "informational",
                    reference_path=reference_dem,
                    source_horizontal_accuracy=source_hacc,
                    source_vertical_accuracy=source_vacc,
                    reference_horizontal_ce90=reference_hce90,
                    reference_horizontal_random_90=reference_hrandom,
                    reference_relative_horizontal_90=reference_hrelative,
                    reference_relative_vertical_90=reference_vrelative,
                    reference_identifier=reference_identifier,
                    accuracy_evaluation_method=accuracy_method,
                    reference_independent=reference_independent,
                    independence_evidence=independence)
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

                    # v0.61.1: resolve the source metadata HOLD before any
                    # comparison run creates output. Missing unit or vertical
                    # metadata is not inferable from raster values, so the
                    # operator must make the declaration in Advanced. The
                    # source is read-only; no metadata tag is silently changed.
                    metadata_check = None
                    try:
                        from dem2dged_terrain import (
                            inspect_source, source_metadata_preflight,
                            write_json)
                        source_info = inspect_source(src)
                        registration_text = self.src_registration_var.get()
                        registration_decision = (
                            "area_to_point"
                            if registration_text.startswith("PixelIsArea")
                            else "source_point")
                        metadata_check = source_metadata_preflight(
                            source_info,
                            registration_decision=registration_decision,
                            declared_unit=self.src_unit_var.get(),
                            declared_vertical=src_vert)
                        write_json(
                            {"source": source_info.__dict__,
                             "preflight": metadata_check,
                             "vertical_declaration": {
                                 "declared_in_advanced": src_vert,
                                 "detection": self._vertical_detections.get(
                                     os.path.abspath(src))}},
                            os.path.join(base_dir, "source_metadata.json"))
                    except Exception as metadata_error:
                        metadata_check = {
                            "status": "HOLD",
                            "reason": "source metadata preflight could not run: %s"
                                      % metadata_error,
                            "reasons": [str(metadata_error)]}

                    if metadata_check.get("status") != "PASS":
                        held_files += 1
                        reason = metadata_check.get("reason", "metadata is incomplete")
                        self._q.put((
                            "log",
                            "   Source preflight HOLD: %s" % reason))
                        self._q.put((
                            "log",
                            "   No tiles were created for %s. Set the source "
                            "registration, elevation unit, and verified "
                            "vertical reference, then run again. Tip: Advanced > "
                            "Source vertical > Detect suggests the datum from "
                            "the file, its metadata and files next to it."
                            % name))
                        run_i += len(runs)
                        self._q.put(("pct", int((run_i / total_runs) * 100)))
                        continue

                    # Use the source CRS vertical code when it is present, or
                    # the explicit Advanced-field declaration when it is not.
                    # This prevents an EPSG: prefix from being duplicated in
                    # the compound CRS string passed to GDAL.
                    src_vert = metadata_check.get("effective_vertical_epsg") or src_vert
                    self._q.put((
                        "log",
                        "   Source metadata accepted: registration=%s; unit=%s; "
                        "vertical=%s"
                        % (metadata_check.get("registration_decision"),
                           metadata_check.get("elevation_unit"), src_vert)))

                    # v0.62.9: decide how the heights reach EGM2008 ONCE per
                    # file. "direct" keeps the old behaviour (the converter
                    # warps with the compound CRS). "separate" is used when
                    # PROJ has no strict chain for the declared datum but a
                    # verified, cross-checked separate correction exists
                    # (CGVD2013 on generic NAD83(CSRS) data): a temporary copy
                    # with EGM2008 heights is converted instead. "failed" stops
                    # with a short message; the strict guard is never loosened.
                    vertical_plan = None
                    conv_src = src
                    conv_vert = src_vert
                    if src_vert and str(src_vert) != "3855":
                        try:
                            vertical_plan = dvt.prepare_vertical_source(
                                src, src_vert, record_dir=base_dir,
                                log=lambda m: self._q.put(("log", m)),
                                stop_event=self._stop)
                        except Exception as vertical_error:
                            vertical_plan = {
                                "mode": "failed", "check": None, "correction": None,
                                "reason": "the vertical preflight could not run: %s"
                                          % vertical_error}
                        if vertical_plan["mode"] == "stopped":
                            break
                        if vertical_plan["mode"] == "failed":
                            raise RuntimeError(
                                "Vertical conversion preflight failed: %s\n\n"
                                "The heights were not converted and no tiles were "
                                "written. Details: vertical_operation_check.json and "
                                "vertical_correction.json in %s."
                                % (vertical_plan.get("reason"), base_dir))
                        if vertical_plan["mode"] == "separate":
                            conv_src = vertical_plan["source"]
                            conv_vert = vertical_plan["vertical"]

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
                                resamp_used = convert_geo(conv_src, out_dir, lv,
                                            self.src_type_var.get(),
                                            self.sec_cls_var.get(),
                                            self.prod_ver_var.get(),
                                            log_fn, prog_fn, self._stop,
                                            source_vertical=conv_vert,
                                            resampling=alg_code,
                                            org=org_code,
                                            abs_hacc=abs_hacc,
                                            abs_vacc=abs_vacc,
                                            lineage=lineage,
                                            skip_sanity_check=
                                                self.skip_sanity_var.get(),
                                            prefilter=prefilter_code)
                            else:
                                resamp_used = convert_utm(conv_src, out_dir, lv, zone,
                                            self.src_type_var.get(),
                                            self.sec_cls_var.get(),
                                            self.prod_ver_var.get(),
                                            log_fn, prog_fn, self._stop,
                                            source_vertical=conv_vert,
                                            resampling=alg_code,
                                            org=org_code,
                                            abs_hacc=abs_hacc,
                                            abs_vacc=abs_vacc,
                                            lineage=lineage,
                                            skip_sanity_check=
                                                self.skip_sanity_var.get(),
                                            prefilter=prefilter_code)
                        except Exception as conv_err:
                            failed_files += 1
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
                                 "vertical_route": (
                                     dvt.route_manifest(vertical_plan)
                                     if vertical_plan and dvt else None),
                                 "source_vertical_basis": (
                                     "operator-declared" if src_vert else
                                     "assumed-EGM2008-label-only"),
                                 "source_horizontal_accuracy_90_m": source_hacc,
                                 "source_vertical_accuracy_90_m": source_vacc,
                                 "reference_dem": reference_dem,
                                 "reference_identifier": reference_identifier,
                                 "accuracy_evaluation_method": accuracy_method,
                                 "reference_horizontal_ce90_m": reference_hce90,
                                 "reference_horizontal_random_90_m": reference_hrandom,
                                 "reference_relative_horizontal_90_m": reference_hrelative,
                                 "reference_relative_vertical_90_m": reference_vrelative,
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
                                        compliance = write_evidence(
                                            out_dir, rep, src, qa, meth[1])
                                        self._q.put((
                                            "log", "     DGIWG evidence: %s"
                                            % compliance["overall"]))
                                        if (strict_compliance and
                                                compliance["overall"] != "PASS"):
                                            held_files += 1
                                            self._q.put((
                                                "log", "     Compliance HOLD: full "
                                                "evidence gate did not pass"))
                                    except Exception as qe:
                                        self._q.put(("log", "     Terrain QA warning: %s" % qe))
                                        if strict_compliance:
                                            held_files += 1
                                except Exception as ve:
                                    val_results.append(
                                        {"name": "%s [%s]" % (name, meth[2]),
                                         "error": str(ve)})
                                    self._q.put(("log",
                                        "     Validation could not run: %s" % ve))
                            entry["methods"].append(mrec)
                        else:
                            converted_files += 1
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
                                        compliance = write_evidence(
                                            out_dir, rep, src, qa,
                                            resamp_used or "bilinear")
                                        self._q.put((
                                            "log", "   DGIWG evidence: %s"
                                            % compliance["overall"]))
                                        if (strict_compliance and
                                                compliance["overall"] != "PASS"):
                                            held_files += 1
                                            self._q.put((
                                                "log", "   Compliance HOLD: full "
                                                "evidence gate did not pass"))
                                    except Exception as qe:
                                        self._q.put(("log", "   Terrain QA warning: %s" % qe))
                                        if strict_compliance:
                                            held_files += 1
                                except Exception as ve:
                                    val_results.append({"name": name, "error": str(ve)})
                                    self._q.put(("log", "   Validation could not run: %s" % ve))

                    if compare_methods and entry["methods"]:
                        if any("error" not in method for method in entry["methods"]):
                            converted_files += 1
                        cmp_entries.append(entry)
                        self._q.put(("file_done", (idx+1, total_f, base_dir)))

                    if vertical_plan and dvt:
                        try:
                            dvt.cleanup(vertical_plan)
                        except Exception:
                            pass

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
                elif converted_files == 0 and held_files:
                    self._q.put((
                        "done",
                        "held:%d:%s" % (held_files, dst)))
                elif held_files or failed_files:
                    self._q.put((
                        "done",
                        "partial:%s|converted=%d|held=%d|failed=%d"
                        % (dst, converted_files, held_files, failed_files)))
                else:
                    self._q.put((
                        "done",
                        "ok:%s|converted=%d" % (dst, converted_files)))

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
                        summary = val[3:]
                        output_path = summary.split("|", 1)[0]
                        self.progress["value"] = 100
                        self._set_status("All done!", GREEN)
                        self._log("\nAll conversions complete!")
                        msg = ("All %d file(s) converted!\n\nOutput saved to:\n%s"
                               % (len(self._files), output_path))
                        if self._last_report_path:
                            msg += "\n\nValidation report:\n%s" % self._last_report_path
                        if self._last_cmp_report_path:
                            msg += ("\n\nResampling comparison report:\n%s"
                                    % self._last_cmp_report_path)
                        messagebox.showinfo("Conversion complete", msg)
                    elif val.startswith("held:"):
                        parts = val.split(":", 2)
                        held_count = parts[1] if len(parts) > 1 else "some"
                        output_path = parts[2] if len(parts) > 2 else "the selected output folder"
                        self.progress["value"] = 100
                        self._set_status("No conversions performed.", ACCENT)
                        self._log(
                            "\nNo conversions were performed: %s file(s) were "
                            "held by source metadata preflight."
                            % held_count)
                        messagebox.showerror(
                            "Conversion held",
                            "%s file(s) were held before tile generation.\n\n"
                            "Review the source metadata fields, especially the "
                            "verified vertical reference, then run again.\n\n"
                            "Tip: in Advanced, click Detect next to Source vertical "
                            "to see where the datum can be read from.\n\n"
                            "Output folder:\n%s" % (held_count, output_path))
                    elif val.startswith("partial:"):
                        summary = val[len("partial:"):]
                        output_path, _, counts = summary.partition("|")
                        self.progress["value"] = 100
                        self._set_status("Completed with holds.", "#f39c12")
                        self._log(
                            "\nConversion completed with unresolved files: %s"
                            % counts)
                        messagebox.showwarning(
                            "Conversion incomplete",
                            "Some files converted, but others were held or failed.\n\n"
                            "%s\n\nOutput folder:\n%s" % (counts, output_path))
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
    if len(sys.argv) >= 2 and sys.argv[1] == "--reference-clip-worker":
        sys.exit(_reference_clip_worker_main())
    if len(sys.argv) >= 2 and sys.argv[1] == "--reference-search-worker":
        sys.exit(_reference_search_worker_main())
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
