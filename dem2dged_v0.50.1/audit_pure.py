# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

import sys, os, types, math, re

# ---- stub osgeo ------------------------------------------------------------
# v0.41: DontUseExceptions and the GA_* / GDT_* constants were added here
# because dem2dged_lib.py now pins the GDAL/OGR/OSR exception behaviour
# explicitly at import time (see its header) and gdal_open() takes a mode
# argument defaulting to gdal.GA_ReadOnly. Without them this harness fails
# on import with an AttributeError before running a single check.
osgeo = types.ModuleType("osgeo")
for name in ("gdal", "ogr", "osr"):
    m = types.ModuleType("osgeo." + name)
    m.UseExceptions = lambda *a, **k: None
    m.DontUseExceptions = lambda *a, **k: None
    m.GetUseExceptions = lambda *a, **k: 0
    m.GetDataTypeName = lambda x: "Float32"
    m.GA_ReadOnly, m.GA_Update = 0, 1
    m.GDT_Byte, m.GDT_Int16, m.GDT_Float32, m.GDT_Float64 = 1, 3, 6, 7
    setattr(osgeo, name, m)
    sys.modules["osgeo." + name] = m
sys.modules["osgeo"] = osgeo

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)

# ---- numpy is required, GDAL is not -----------------------------------------
# v0.44. This harness stubs osgeo (above) so it can run without GDAL, and its
# header has always said "runs without GDAL" -- but it imports
# dem2dged_validate, which imports numpy for real. Reported as:
#
#     C:\...\dem2dged_v0.41>audit_pure.py
#     ModuleNotFoundError: No module named 'numpy'
#
# Note the command: `audit_pure.py`, not `python audit_pure.py`. Typed that
# way, Windows resolves the .py association -- usually the `py` launcher or a
# system Python -- and runs the script in a DIFFERENT interpreter from the
# activated conda environment, where numpy is not installed. The conda prompt
# still says (DGED), so nothing looks wrong.
#
# A bare ModuleNotFoundError sends the reader off installing numpy into the
# wrong environment. Naming the interpreter that is actually running turns it
# into a one-line diagnosis.
try:
    import dem2dged_env
    dem2dged_env.require("numpy", script="audit_pure.py")
except ImportError:
    # dem2dged_env.py is missing (an incomplete checkout); fall back to a
    # plain check so this harness still reports something useful.
    try:
        import numpy  # noqa: F401
    except ImportError:
        sys.exit("ERROR: numpy is not available to %s.\n"
                 "       Use 'python audit_pure.py', not 'audit_pure.py' --\n"
                 "       the second form uses the Windows .py file "
                 "association and\n"
                 "       ignores the activated conda environment."
                 % sys.executable)

import dem2dged_lib as dl
import dem2dged_validate as dv

FAILS = []
def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  FAIL  " + msg)
    return cond

GEO_LEVELS = [l[0] for l in dl.level_tilesize_and_spatial_resolution]
UTM_LEVELS = [l[0] for l in dl.PL]

print("=" * 78)
print("1) GEO filename -> validator regex -> coordinate round trip")
print("=" * 78)
for lvl, tsize_min, latres_sec, letter in dl.level_tilesize_and_spatial_resolution:
    tiledim = tsize_min / 60.0
    latres = latres_sec / 3600.0
    # a few representative tile origins incl. S / W hemispheres
    for lat_i, lon_i in [(55, 12), (0, 0), (-34, -58), (78, 15), (-1, -1)]:
        t_minlat = math.floor(lat_i / tiledim) * tiledim
        t_minlon = math.floor(lon_i / tiledim) * tiledim
        for org in ("", "DNK"):
            base = dl.geo_tile_basename(lvl, letter, t_minlat, t_minlon,
                                        "A", "U", "01", org=org)
            m = dv.GEO_RE.match(base)
            if not check(m, "GEO L%-2s org=%-3s %r does not match GEO_RE"
                            % (lvl, org or "-", base)):
                continue
            check(m.group("lv") == lvl,
                  "GEO L%s: regex parsed level %r" % (lvl, m.group("lv")))
            check(m.group("org") == (org or None),
                  "GEO L%s: regex parsed org %r, expected %r"
                  % (lvl, m.group("org"), org or None))
            lat0 = dv.dms_to_deg(m.group("lat"), True) * (-1 if m.group("hemi") == "S" else 1)
            lon0 = dv.dms_to_deg(m.group("lon"), False) * (-1 if m.group("east") == "W" else 1)
            check(math.isclose(lat0, t_minlat, abs_tol=1e-6),
                  "GEO L%s: name lat %.6f != tile origin %.6f  (%s)"
                  % (lvl, lat0, t_minlat, base))
            check(math.isclose(lon0, t_minlon, abs_tol=1e-6),
                  "GEO L%s: name lon %.6f != tile origin %.6f  (%s)"
                  % (lvl, lon0, t_minlon, base))
print("   done")

print()
print("=" * 78)
print("2) GEO raster dimensions: converter warp extent vs validator expectation")
print("=" * 78)
for lvl, tsize_min, latres_sec, letter in dl.level_tilesize_and_spatial_resolution:
    tiledim = tsize_min / 60.0
    latres = latres_sec / 3600.0
    for lat in (0, 55, 75, -55):
        lonres = dv.lon_multi(lat) * latres
        te = (lat, lonres)
        # what gdalwarp produces from tile_warp_extent with -tr lonres latres
        te_xmin = 0 - lonres / 2.0
        te_xmax = 0 + tiledim + lonres / 2.0
        te_ymin = lat - latres / 2.0
        te_ymax = lat + tiledim + latres / 2.0
        w_actual = round((te_xmax - te_xmin) / lonres)
        h_actual = round((te_ymax - te_ymin) / latres)
        # what the validator expects
        w_exp = round(tiledim / lonres) + 1
        h_exp = round(tiledim / latres) + 1
        check(w_actual == w_exp,
              "GEO L%-2s lat=%s: warp width %d vs validator expects %d"
              % (lvl, lat, w_actual, w_exp))
        check(h_actual == h_exp,
              "GEO L%-2s lat=%s: warp height %d vs validator expects %d"
              % (lvl, lat, h_actual, h_exp))
        # integer number of intervals across the tile?
        n_lon = tiledim / lonres
        check(abs(n_lon - round(n_lon)) < 1e-6,
              "GEO L%-2s lat=%s (zone factor %s): %.4f longitude intervals "
              "per tile is NOT an integer -> posts cannot align"
              % (lvl, lat, dv.lon_multi(lat), n_lon))
print("   done")

print()
print("=" * 78)
print("3) UTM filename -> validator regex -> coordinate round trip")
print("=" * 78)
for lvl, gsd, posts, letter in dl.PL:
    tiledim = (posts - 1) * gsd
    for east_m, north_m in [(500000.0, 6000000.0), (400000.0, 500000.0),
                            (200000.0, 100000.0), (600000.0, 0.0)]:
        t_minx = math.floor(east_m / tiledim) * tiledim
        t_miny = math.floor(north_m / tiledim) * tiledim
        for org in ("", "DNK"):
            base = dl.utm_tile_basename(lvl, letter, "32N", t_miny, t_minx,
                                        "A", "U", "01", org=org)
            m = dv.UTM_RE.match(base)
            if not check(m, "UTM L%-2s org=%-3s %r does not match UTM_RE"
                            % (lvl, org or "-", base)):
                continue
            mult = 1000 if lvl in ("4b", "4", "5", "6") else 1
            north0 = int(m.group("northing")) * mult
            east0 = int(m.group("easting")) * mult
            check(math.isclose(north0, t_miny, abs_tol=1e-6),
                  "UTM L%s: name northing %s != tile origin %s  (%s)"
                  % (lvl, north0, t_miny, base))
            check(math.isclose(east0, t_minx, abs_tol=1e-6),
                  "UTM L%s: name easting %s != tile origin %s  (%s)"
                  % (lvl, east0, t_minx, base))
            # spec 12.1 field widths, from the shared helper the converter
            # formats with (v0.34)
            n_exp, e_exp = dl.utm_name_field_widths(lvl)
            n_field, e_field = m.group("northing"), m.group("easting")
            check(len(n_field) == n_exp,
                  "UTM L%s: northing field %r is %d chars, spec 12.1 wants "
                  "%d  (%s)" % (lvl, n_field, len(n_field), n_exp, base))
            check(len(e_field) == e_exp,
                  "UTM L%s: easting field %r is %d chars, spec 12.1 wants "
                  "%d  (%s)" % (lvl, e_field, len(e_field), e_exp, base))
print("   done")

print()
print("=" * 78)
print("4) UTM raster dimensions + tile-grid alignment check")
print("=" * 78)
for lvl, gsd, posts, letter in dl.PL:
    tiledim = (posts - 1) * gsd
    te_xmin = 0 - gsd / 2.0
    te_xmax = 0 + tiledim + gsd / 2.0
    w_actual = round((te_xmax - te_xmin) / gsd)
    check(w_actual == posts,
          "UTM L%-2s: warp width %d vs %d posts" % (lvl, w_actual, posts))
    # validator's alignment test uses the % operator on floats
    east0 = math.floor(500000 / tiledim) * tiledim
    try:
        r = east0 % tiledim
        check(abs(r) < 1e-6 or abs(r - tiledim) < 1e-6,
              "UTM L%-2s: east0 %% tiledim = %r (tiledim=%s) -> validator "
              "flags a correctly aligned tile" % (lvl, r, tiledim))
    except Exception as e:
        check(False, "UTM L%s: alignment modulo raised %s" % (lvl, e))
print("   done")

print()
print("=" * 78)
print("5) Sidecar placeholder coverage: template keys vs code keys")
print("=" * 78)
code_keys = {"BASENAME", "LEVEL", "GSD", "DATE", "EPSG", "ORG", "CLASS_WORD",
             "WEST", "EAST", "SOUTH", "NORTH", "MINZ", "MAXZ", "MISSRATE",
             "ABS_HACC", "ABS_VACC", "LINEAGE", "DTYPE"}
for tpl in ("DGED_GEO_TEMPLATE.xml", "DGED_UTM_TEMPLATE.xml"):
    txt = open(os.path.join(SRC, tpl), encoding="utf-8").read()
    tpl_keys = set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", txt))
    missing = tpl_keys - code_keys
    unused = code_keys - tpl_keys
    check(not missing,
          "%s: placeholders present in template but NEVER substituted: %s"
          % (tpl, sorted(missing)))
    if unused:
        print("  note  %s: code supplies unused keys %s" % (tpl, sorted(unused)))
    # well-formedness
    import xml.etree.ElementTree as ET
    sub = txt
    for k in tpl_keys:
        sub = sub.replace("{{%s}}" % k, "1")
    try:
        ET.fromstring(sub)
        print("  ok    %s: well-formed after substitution (%d placeholders)"
              % (tpl, len(tpl_keys)))
    except ET.ParseError as e:
        check(False, "%s: NOT well-formed after substitution (%s)" % (tpl, e))
    # validator check E: does the rendered sidecar contain '>L<level><'?
    for lvl in GEO_LEVELS if "GEO" in tpl else UTM_LEVELS:
        rendered = txt.replace("{{LEVEL}}", lvl)
        if (">L%s<" % lvl) not in rendered.replace(" ", ""):
            check(False, "%s: rendered L%s sidecar lacks '>L%s<' -> validator "
                         "check E reports 'level keyword missing'" % (tpl, lvl, lvl))

print()
print("=" * 78)
print("6) Misc consistency")
print("=" * 78)
check(dl.output_type_for_level("0") == "Int16", "level 0 should be Int16")
check(dl.output_type_for_level("3") == "Float32", "level 3 should be Float32")
check(dl.output_type_for_level("4b") == "Float32", "level 4b should be Float32")
for lvl in GEO_LEVELS:
    check(lvl in dl.LEVEL_ABS_HACC, "LEVEL_ABS_HACC missing level %s" % lvl)
    check(lvl in dl.LEVEL_ABS_VACC, "LEVEL_ABS_VACC missing level %s" % lvl)
# pick_resampler
check(dl.pick_resampler(10, 30) == "average", "downsample should pick average")
check(dl.pick_resampler(30, 10) == "bilinear", "upsample should pick bilinear")
check(dl.pick_resampler(30, 10, "cubic") == "cubic", "override ignored")
check(dl.pick_resampler(30, 10, "auto") == "bilinear", "'auto' not treated as auto")
# ToDMS
check(dl.ToDMS(55.5) == (55, 30, 0.0), "ToDMS(55.5) = %r" % (dl.ToDMS(55.5),))
check(dl.ToDMS(-0.5)[0] == 0 and dl.ToDMS(-0.5)[1] == 30,
      "ToDMS(-0.5) = %r  (sign of a 0-degree southern/western value is lost)"
      % (dl.ToDMS(-0.5),))
# zone lookup at exact boundaries
for lat, want in [(-90, 10), (-60, 1.5), (0, 1), (50, 1.5), (70, 3), (85, 10)]:
    got = dv.lon_multi(lat)
    check(got == want, "lon_multi(%s) = %s, expected %s" % (lat, got, want))

print()
print("=" * 78)
print("7) v0.34 regression checks")
print("=" * 78)
# (a) UTM zero-padding on the equator and at low northings
for lvl, expect in (("5", "DGEDL5UtD_32N0000_0500_A_U_01".replace("_0500", "_500")),
                    ("4b", None)):
    pass
b = dl.utm_tile_basename("5", "D", "32N", 0.0, 500000.0, "A", "U", "01")
check(b == "DGEDL5UtD_32N0000_500_A_U_01",
      "equator UTM tile name is %r, expected DGEDL5UtD_32N0000_500_A_U_01" % b)
b = dl.utm_tile_basename("5", "D", "32N", 500000.0, 400000.0, "A", "U", "01")
check(b == "DGEDL5UtD_32N0500_400_A_U_01",
      "low-northing UTM tile name is %r, expected "
      "DGEDL5UtD_32N0500_400_A_U_01" % b)

# (b) validator now FAILS a pre-v0.34 short name, with a precise message
legacy = "DGEDL5UtD_32N500_400_A_U_01"
m = dv.UTM_RE.match(legacy)
check(m is not None,
      "validator regex should still PARSE the legacy short name %r so it can "
      "report a precise width error rather than 'does not match convention'"
      % legacy)
if m:
    n_exp, e_exp = dl.utm_name_field_widths("5")
    check(len(m.group("northing")) != n_exp,
          "legacy name %r should be detected as wrong-width" % legacy)

# (c) tile-count bound: ceil() must not add an empty row/col on an exact
#     boundary, and must still cover a partial tile
def n_tiles(vmin, vmax, tiledim):
    s = math.floor(vmin / tiledim)
    e = max(s + 1, math.ceil(vmax / tiledim))
    return e - s
check(n_tiles(40.0, 41.0, 0.1) == 10,
      "exact-boundary extent should need 10 tiles, got %d"
      % n_tiles(40.0, 41.0, 0.1))
check(n_tiles(40.0, 41.05, 0.1) == 11,
      "partial-tile extent should need 11 tiles, got %d"
      % n_tiles(40.0, 41.05, 0.1))
check(n_tiles(40.0, 40.0, 0.1) == 1,
      "degenerate zero-area extent should still yield 1 tile, got %d"
      % n_tiles(40.0, 40.0, 0.1))

# (d) version consistency across every file that declares one
import re as _re
ver_sources = {}
for fn in ("VERSION.txt", "VALIDATOR_VERSION.txt"):
    p = os.path.join(SRC, fn)
    if os.path.isfile(p):
        mm = _re.search(r"^Version:\s*(\d+\.\d+(?:\.\d+)?)",
                        open(p, encoding="utf-8").read(), _re.M)
        ver_sources[fn] = mm.group(1) if mm else None
for fn in ("dem2dged_package.py", "dem2dged_validate_package.py",
           "BUILD_AND_PACKAGE.py"):
    p = os.path.join(SRC, fn)
    if os.path.isfile(p):
        mm = _re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']',
                        open(p, encoding="utf-8").read(), _re.M)
        ver_sources[fn] = mm.group(1) if mm else None
for fn in ("dem2dged.py", "dem2dged_geo.py", "dem2dged_utm.py",
           "dem2dged_gui.py", "dem2dged_lib.py", "dem2dged_validate.py",
           "dem2dged_compare.py"):
    p = os.path.join(SRC, fn)
    if os.path.isfile(p):
        # v0.41: the pattern used to require "Version:" in column 0, which
        # cannot occur in a .py file outside a string -- so this branch
        # silently reported every module as declaring version None and the
        # check never actually verified anything. The version lives in a
        # HEADER COMMENT ("# Version: 0.41"), per the v0.32 changelog.
        mm = _re.search(r"^#?\s*Version:\s*(\d+\.\d+(?:\.\d+)?)",
                        open(p, encoding="utf-8").read(4000), _re.M)
        ver_sources[fn] = mm.group(1) if mm else None
for fn, v in sorted(ver_sources.items()):
    check(v == dl.VERSION,
          "%s declares version %r but dem2dged_lib.VERSION is %r"
          % (fn, v, dl.VERSION))
print("   checked %d version declarations against dl.VERSION=%s"
      % (len(ver_sources), dl.VERSION))

print()
print("=" * 78)
print("8) Elevation sanity check heuristics (v0.36)")
print("=" * 78)

# quick_raster_range() needs a real GDAL raster, which this harness doesn't
# have -- so it's monkey-patched with a fixed return value to exercise
# sanity_check_elevation_source()'s classification logic (the actual thing
# worth regression-testing) without touching GDAL at all.
_orig_quick_range = dl.quick_raster_range


def _check_sanity(label, filename, fixed_range, expect_severities):
    dl.quick_raster_range = lambda path, _v=fixed_range: _v
    try:
        issues = dl.sanity_check_elevation_source(filename)
    finally:
        dl.quick_raster_range = _orig_quick_range
    got = [sev for sev, _msg in issues]
    check(got == expect_severities,
          "%s: expected severities %r, got %r (issues=%r)"
          % (label, expect_severities, got, issues))


_check_sanity("aspect filename + aspect range -> block",
              "aspect_dtm_2m_utm18_w_5_46.tif", (18.52, 345.51), ["block"])
_check_sanity("aspect filename + normal elevation range -> warn",
              "aspect_dtm_2m_utm18_w_5_46.tif", (100.0, 250.0), ["warn"])
_check_sanity("normal filename + aspect-like range -> warn",
              "my_dem.tif", (0.5, 359.8), ["warn"])
_check_sanity("normal filename + normal range -> clean",
              "my_dem.tif", (100.0, 250.0), [])
_check_sanity("low-lying elevation (0-50 m) is not angular -> clean",
              "coastal_plain.tif", (0.0, 50.0), [])
_check_sanity("high but non-angular elevation range -> clean",
              "rockies.tif", (1200.0, 1800.0), [])
_check_sanity("range exactly at the angular thresholds -> block",
              "flow_direction_grid.tif", (0.0, 360.0), ["block"])
_check_sanity("unreadable raster (None) + filename hint only -> warn, no crash",
              "curvature_layer.tif", None, ["warn"])
_check_sanity("unreadable raster (None) + clean filename -> clean, no crash",
              "my_dem.tif", None, [])

print("   checked 9 sanity-check scenarios")

print()
print("=" * 78)
print("9) Auto-optimize resampling selection (v0.36)")
print("=" * 78)

import dem2dged_compare as dc

# -- looks_like_angular_data(): same classifier as section 8, exposed as a
#    plain boolean for resolve_resampler() to consume -----------------------
_orig_quick_range = dl.quick_raster_range
dl.quick_raster_range = lambda path: (18.52, 345.51)
try:
    check(dl.looks_like_angular_data("anything.tif") is True,
          "looks_like_angular_data should be True for a real aspect range")
finally:
    dl.quick_raster_range = _orig_quick_range

dl.quick_raster_range = lambda path: (100.0, 250.0)
try:
    check(dl.looks_like_angular_data("anything.tif") is False,
          "looks_like_angular_data should be False for a normal elevation range")
finally:
    dl.quick_raster_range = _orig_quick_range

# -- resolve_resampler(): every override other than "optimize" must behave
#    IDENTICALLY to calling pick_resampler() directly (no behaviour change
#    for existing users of -resample auto/near/bilinear/cubic/...) ---------
check(dl.resolve_resampler("x.tif", 10, 30, None) == "average",
      "resolve_resampler downsample/no-override should match pick_resampler")
check(dl.resolve_resampler("x.tif", 30, 10, None) == "bilinear",
      "resolve_resampler upsample/no-override should match pick_resampler")
check(dl.resolve_resampler("x.tif", 30, 10, "cubic") == "cubic",
      "resolve_resampler explicit override should pass through unchanged")
check(dl.resolve_resampler("x.tif", 30, 10, "auto") == "bilinear",
      "resolve_resampler('auto') should match pick_resampler('auto')")

# -- resolve_resampler("optimize"): must dispatch into
#    dem2dged_compare.pick_best_resampling(), passing looks_like_angular_
#    data()'s result through as the `angular` argument, case-insensitively.
#    Monkeypatched at the module level (not a real GDAL call) -- this checks
#    the WIRING between the two functions, not pick_best_resampling's own
#    numeric logic (checked separately below). --------------------------
_orig_looks_angular = dl.looks_like_angular_data
_orig_pick_best = dc.pick_best_resampling
_dispatch_calls = []
dl.looks_like_angular_data = lambda p: (p == "aspect.tif")
dc.pick_best_resampling = (lambda src, angular=False, log_fn=None:
    (_dispatch_calls.append((src, angular)), ("cubic", "Cubic Convolution", {}))[1])
try:
    r1 = dl.resolve_resampler("mydem.tif", 10, 10, "optimize")
    r2 = dl.resolve_resampler("aspect.tif", 10, 10, "OPTIMIZE")  # case-insensitive
    check(r1 == "cubic" and r2 == "cubic",
          "resolve_resampler('optimize') should return pick_best_resampling's choice")
    check(_dispatch_calls == [("mydem.tif", False), ("aspect.tif", True)],
          "resolve_resampler('optimize') passed the wrong (src, angular) "
          "pair(s) through to pick_best_resampling: %r" % (_dispatch_calls,))
finally:
    dl.looks_like_angular_data = _orig_looks_angular
    dc.pick_best_resampling = _orig_pick_best

# -- pick_best_resampling(): angular short-circuit must skip the RMSE
#    comparison ENTIRELY (no _read_source call -- proven by making it raise)
#    and return Nearest Neighbor with an explanatory log line. -------------
_orig_read_source = dc._read_source
dc._read_source = lambda *a, **k: check(False,
    "pick_best_resampling(angular=True) must not call _read_source at all")
try:
    logged = []
    alg, label, stats = dc.pick_best_resampling(
        "aspect_layer.tif", angular=True, log_fn=logged.append)
    check((alg, label, stats) == ("near", "Nearest Neighbor", {}),
          "angular short-circuit should return (near, Nearest Neighbor, {}), "
          "got %r" % ((alg, label, stats),))
    check(any("angular" in m or "circular" in m for m in logged),
          "angular short-circuit should explain itself via log_fn")
finally:
    dc._read_source = _orig_read_source

# -- pick_best_resampling(): non-angular path picks the LOWEST hold-out RMSE
#    among the three candidates, and falls back to Bilinear (never crashes)
#    if every candidate's warp fails. Both _read_source and _holdout_stats
#    are monkeypatched so this needs no real raster / GDAL Warp() call. ----
dc._read_source = lambda src: ("ARR", "VALID", "CGT", "PROJ", "NODATA", 1)
try:
    _rmse_by_alg = {"near": 5.0, "bilinear": 1.2, "cubic": 1.8}
    dc._holdout_stats = (lambda arr, valid, cgt, proj, nodata, alg:
        {"rmse": _rmse_by_alg[alg], "mae": _rmse_by_alg[alg] * 0.8, "n_holdout": 1000})
    alg, label, stats = dc.pick_best_resampling("dem.tif", angular=False)
    check(alg == "bilinear" and label == "Bilinear Interpolation",
          "lowest-RMSE candidate (bilinear=1.2) should win, got %r" % (alg,))
    check(set(stats) == {"near", "bilinear", "cubic"},
          "stats_by_alg should report all 3 candidates, got %r" % (set(stats),))

    _rmse_by_alg["cubic"] = 0.1   # now cubic is the most accurate
    alg2, _label2, _stats2 = dc.pick_best_resampling("dem2.tif", angular=False)
    check(alg2 == "cubic",
          "lowest-RMSE candidate (cubic=0.1) should win, got %r" % (alg2,))

    def _always_fail(*a, **k):
        raise RuntimeError("warp failed")
    dc._holdout_stats = _always_fail
    alg3, label3, stats3 = dc.pick_best_resampling("bad.tif", angular=False)
    check((alg3, label3, stats3) == ("bilinear", "Bilinear Interpolation", {}),
          "all-candidates-failed should fall back to Bilinear with empty "
          "stats, got %r" % ((alg3, label3, stats3),))
finally:
    dc._read_source = _orig_read_source
    # _holdout_stats has no meaningful "original" to restore to here since
    # it was only ever exercised through this monkeypatch in this harness;
    # re-importing dem2dged_compare in a later run always gets the real one.

print("   checked auto-optimize dispatch + selection logic")

print()
print("=" * 78)
print("RESULT: %d problem(s)" % len(FAILS))
print("=" * 78)
