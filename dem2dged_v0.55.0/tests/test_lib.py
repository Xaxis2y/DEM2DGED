# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.55.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Unit tests for dem2dged_lib.py -- the module every entry point imports.

These are the DGED spec tables, the tile-naming helpers, the warp-extent
arithmetic, the resampler policy, and the pre-flight guards. Nothing here
needs the gdalwarp executable, so this file runs in any environment where
the osgeo bindings import at all.

Each test that exists because of a specific past defect names the release
in its own name or docstring, so a future reader can tell "this is a
regression guard for a real bug" from "this is a general sanity check".
"""

import os
import sys
import re

import pytest

import dem2dged_lib as dl
from conftest import requires_gdal

ALL_GEO_LEVELS = [row[0] for row in dl.level_tilesize_and_spatial_resolution]
ALL_UTM_LEVELS = [row[0] for row in dl.PL]


# =============================================================================
# Version consistency
# =============================================================================

def test_version_is_a_semantic_three_part_string():
    """Release VERSION uses MAJOR.MINOR.PATCH throughout the project."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", dl.VERSION), dl.VERSION


def test_version_display_matches_version_when_no_release_stage():
    if dl.RELEASE_STAGE:
        assert dl.VERSION_DISPLAY == "%s-%s" % (dl.VERSION, dl.RELEASE_STAGE)
    else:
        assert dl.VERSION_DISPLAY == dl.VERSION


@pytest.mark.parametrize("module_name", [
    "dem2dged.py", "dem2dged_geo.py", "dem2dged_utm.py", "dem2dged_lib.py",
    "dem2dged_validate.py", "dem2dged_compare.py", "dem2dged_gui.py",
])
def test_every_module_declares_the_library_version_in_its_header(module_name):
    """v0.41 finding 2: the "# Version: <n>" header comment that v0.32
    introduced was absent from all seven of these modules, and
    audit_pure.py's pattern required "Version:" in COLUMN 0, which cannot
    occur in a .py file outside a string -- so the version-consistency
    audit could never have matched anything, and v0.40's claim that it was
    clean was not true. Asserted here independently of audit_pure.py so
    neither side can quietly stop checking."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(project, module_name), encoding="utf-8").read()
    m = re.search(r"^#\s*Version:\s*(\d+\.\d+(?:\.\d+)?)\s*$", text, re.M)
    assert m, "%s has no '# Version: x.y' header comment" % module_name
    assert m.group(1) == dl.VERSION, (
        "%s declares %s, dem2dged_lib.VERSION is %s"
        % (module_name, m.group(1), dl.VERSION))


def test_version_txt_agrees_with_the_library():
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(project, "VERSION.txt"), encoding="utf-8").read()
    m = re.search(r"^Version:\s*(\d+\.\d+(?:\.\d+)?)", text, re.M)
    assert m and m.group(1) == dl.VERSION


# =============================================================================
# DGED tables (spec Tables 3, 7, 8, 9)
# =============================================================================

def test_geo_levels_are_the_eleven_the_spec_defines():
    assert ALL_GEO_LEVELS == ["0", "1", "2", "3", "4b", "4", "5", "6",
                              "7", "8", "9"]


def test_utm_levels_start_at_4b():
    """UTM products only exist from level 4b upward (spec Table 9)."""
    assert ALL_UTM_LEVELS == ["4b", "4", "5", "6", "7", "8", "9"]


@pytest.mark.parametrize("level,tile_min,lat_arcsec,letter",
                         dl.level_tilesize_and_spatial_resolution)
def test_every_longitude_zone_factor_divides_the_geo_tile_evenly(
        level, tile_min, lat_arcsec, letter):
    """THE invariant behind the v0.27 level 8/9 change.

    A tile origin can only sit on the longitude post grid if the tile's
    longitude span is a whole number of post intervals. With the 1-minute
    tile that v0.27 replaced, latitude zones 2 (50-60 deg, factor 1.5) and 4
    (70-80 deg, factor 3) gave 60 / (0.0075 * 1.5) = 5333.33 intervals at
    level 8 -- a non-integer, i.e. posts that do not line up. All six
    factors divide the 1.5-minute tile evenly, which is why levels 7-9 use
    it. Checked for EVERY level against EVERY factor, so a future table edit
    cannot reintroduce the misalignment at some other level.
    """
    tile_arcsec = tile_min * 60.0
    for factor in sorted({row[4] for row in dl.zone_lon_spacing}):
        lon_arcsec = lat_arcsec * factor
        n_intervals = tile_arcsec / lon_arcsec
        assert abs(n_intervals - round(n_intervals)) < 1e-9, (
            "level %s: %s-minute tile / (%s\" x %s) = %.6f intervals -- not a "
            "whole number, so tile origins cannot sit on the post grid"
            % (level, tile_min, lat_arcsec, factor, n_intervals))


def test_longitude_zones_tile_the_whole_globe_without_gaps():
    bands = sorted(((row[1], row[2]) for row in dl.zone_lon_spacing))
    assert bands[0][0] == -90 and bands[-1][1] == 90
    for (_, prev_hi), (nxt_lo, _) in zip(bands, bands[1:]):
        assert prev_hi == nxt_lo, "gap or overlap at %s/%s" % (prev_hi, nxt_lo)


def test_longitude_zones_are_symmetric_about_the_equator():
    north = {(lo, hi): f for _z, lo, hi, _s, f in dl.zone_lon_spacing if lo >= 0}
    south = {(lo, hi): f for _z, lo, hi, _s, f in dl.zone_lon_spacing if hi <= 0}
    for (lo, hi), factor in north.items():
        assert south.get((-hi, -lo)) == factor, (lo, hi, factor)


@pytest.mark.parametrize("level", ALL_GEO_LEVELS)
def test_accuracy_defaults_exist_for_every_level(level):
    """Tables 5 and 6 goal values are the DEFAULT written into the metadata
    quality report, so a missing entry would be a KeyError mid-conversion."""
    assert level in dl.LEVEL_ABS_HACC
    assert level in dl.LEVEL_ABS_VACC
    assert dl.LEVEL_ABS_HACC[level] > 0
    assert dl.LEVEL_ABS_VACC[level] > 0


def test_accuracy_defaults_improve_monotonically_with_level():
    order = ["0", "1", "2", "3", "4b", "4", "5", "6", "7", "8", "9"]
    h = [dl.LEVEL_ABS_HACC[k] for k in order]
    v = [dl.LEVEL_ABS_VACC[k] for k in order]
    assert h == sorted(h, reverse=True), h
    assert v == sorted(v, reverse=True), v


# =============================================================================
# Data type and LZW predictor
# =============================================================================

@pytest.mark.parametrize("level,expected", [
    ("0", "Int16"), ("1", "Int16"), ("2", "Int16"),
    ("3", "Float32"), ("4b", "Float32"), ("4", "Float32"), ("5", "Float32"),
    ("6", "Float32"), ("7", "Float32"), ("8", "Float32"), ("9", "Float32"),
])
def test_output_type_for_level(level, expected):
    """Spec section 7: Int16 is MANDATORY for levels 0-2."""
    assert dl.output_type_for_level(level) == expected


def test_output_type_accepts_an_int_level():
    assert dl.output_type_for_level(2) == "Int16"


@pytest.mark.parametrize("dtype,predictor", [("Int16", "2"), ("Float32", "3")])
def test_predictor_for_type(dtype, predictor):
    """v0.39: PREDICTOR=2 (horizontal differencing) is only DEFINED for
    integer samples; Float32 needs PREDICTOR=3, the IEEE floating-point
    predictor. Both stay LZW-lossless, so spec 13.1 holds either way."""
    assert dl.predictor_for_type(dtype) == predictor


def test_predictor_follows_the_level_through_the_shared_helpers():
    for level in ALL_GEO_LEVELS:
        t = dl.output_type_for_level(level)
        assert dl.predictor_for_type(t) == ("2" if t == "Int16" else "3")


# =============================================================================
# ToDMS
# =============================================================================

@pytest.mark.parametrize("dd,expect", [
    (0.0, (0, 0, 0.0)),
    (55.5, (55, 30, 0.0)),
    (12.0, (12, 0, 0.0)),
    (-33.75, (-33, 45, 0.0)),
    (1.0 / 60, (0, 1, 0.0)),
])
def test_todms(dd, expect):
    d, m, s = dl.ToDMS(dd)
    assert (d, m, round(s, 6)) == expect


def test_todms_rounds_away_the_59_999_artefact():
    """The reason ToDMS rounds to 1/10000 arc-second first: 55.5 reached by
    floating-point arithmetic must not come back as 55 deg 29' 59.9999"."""
    dd = 55.4 + 0.1
    d, m, s = dl.ToDMS(dd)
    assert (d, m, round(s, 4)) == (55, 30, 0.0)


# =============================================================================
# Tile names (spec 12.1)
# =============================================================================

def test_geo_level_0_to_3_use_the_short_form():
    """Levels 0-3 are delivered by whole square degree, so the spec's own
    examples carry no product-type letter and no tile-size indicator."""
    name = dl.geo_tile_basename("2", "A", 27.0, 56.0, "A", "U", "01")
    assert name == "DGEDL2_27N056E_A_U_01"


def test_geo_level_5_carries_degrees_and_minutes():
    name = dl.geo_tile_basename("5", "D", 55.5, 12.2, "A", "U", "01")
    assert name == "DGEDL5GtD_5530N01212E_A_U_01"


def test_geo_level_8_carries_degrees_minutes_and_seconds():
    name = dl.geo_tile_basename("8", "F", 55.5, 12.2, "A", "U", "01")
    assert name == "DGEDL8GtF_553000N0121200E_A_U_01"


def test_geo_southern_and_western_hemispheres():
    name = dl.geo_tile_basename("2", "A", -34.0, -58.0, "A", "U", "01")
    assert name == "DGEDL2_34S058W_A_U_01"


def test_geo_organisation_code_is_the_second_subfield():
    name = dl.geo_tile_basename("5", "D", 55.5, 12.2, "A", "U", "01", org="dnk")
    assert name == "DGEDL5GtD_DNK_5530N01212E_A_U_01"


def test_geo_latitude_is_two_digits_and_longitude_three():
    """A one-digit longitude must still occupy three characters, or the
    fixed-width coordinate field the spec defines is not fixed-width."""
    name = dl.geo_tile_basename("2", "A", 5.0, 7.0, "A", "U", "01")
    assert "_05N007E_" in name


@pytest.mark.parametrize("level", ALL_UTM_LEVELS)
def test_utm_name_field_widths_match_the_spec_form(level):
    n, e = dl.utm_name_field_widths(level)
    if level in dl.UTM_KM_FORM_LEVELS:
        assert (n, e) == (4, 3)
    else:
        assert (n, e) == (7, 6)


def test_utm_names_are_zero_padded():
    """v0.34, a real spec violation: a northing below 1 000 000 m -- anywhere
    within roughly 9 degrees of the equator -- used to produce a short,
    non-spec field because the subfields were built with a bare int()."""
    name = dl.utm_tile_basename("5", "D", "32N", 500000.0, 400000.0,
                                "A", "U", "01")
    assert name == "DGEDL5UtD_32N0500_400_A_U_01"


def test_utm_name_on_the_equator_is_not_a_single_zero():
    """The worst case of the same bug: northing 0 produced "..._32N0_..."."""
    name = dl.utm_tile_basename("5", "D", "32N", 0.0, 500000.0,
                                "A", "U", "01")
    assert "_32N0000_500_" in name


def test_utm_level_7_uses_the_full_metre_form():
    name = dl.utm_tile_basename("7", "F", "09S", 5000000.0, 400000.0,
                                "A", "U", "01")
    assert name == "DGEDL7UtF_09S5000000_400000_A_U_01"


def test_utm_organisation_code():
    name = dl.utm_tile_basename("5", "D", "32N", 500000.0, 400000.0,
                                "A", "U", "01", org="nor")
    assert name == "DGEDL5UtD_NOR_32N0500_400_A_U_01"


@pytest.mark.parametrize("level", ALL_UTM_LEVELS)
@pytest.mark.parametrize("zone", ["32N", "09S", "01N", "60S"])
def test_every_utm_name_has_the_declared_field_widths(level, zone):
    """Generated across every level x four zone forms, because the widths
    are the thing the validator checks and the two must not disagree."""
    gsd, posts, letter = [row[1:] for row in dl.PL if row[0] == level][0]
    tiledim = (posts - 1) * gsd
    for northing in (0.0, tiledim, 5000000.0, 9990000.0):
        name = dl.utm_tile_basename(level, letter, zone, northing, 500000.0,
                                    "A", "U", "01")
        n_width, e_width = dl.utm_name_field_widths(level)
        field = name.split("_")[1]
        assert field.startswith(zone)
        assert len(field) - len(zone) == n_width, name
        assert len(name.split("_")[2]) == e_width, name


# =============================================================================
# Warp extent (spec 6.3, v0.27 / v0.37)
# =============================================================================

def test_warp_extent_is_half_post_expanded():
    """gdalwarp samples at pixel CENTRES, so the -te extent has to reach
    half a post beyond the outermost posts on every side for those centres
    to land exactly on the DGED post locations. Without it every value in
    every tile is shifted by half a post."""
    # Tolerance is 1e-9, not tighter: tile_warp_extent() deliberately rounds
    # to 9 decimals (v0.37 Finding 1) so the same boundary is always the
    # same float, and 1e-9 degrees is well under 0.1 mm at the equator.
    xmin, ymin, xmax, ymax = dl.tile_warp_extent(12.0, 55.0, 0.1, 2.5e-5,
                                                 1.0 / 60000)
    assert xmin == pytest.approx(12.0 - 2.5e-5 / 2, abs=1e-9)
    assert ymin == pytest.approx(55.0 - (1.0 / 60000) / 2, abs=1e-9)
    assert xmax == pytest.approx(12.1 + 2.5e-5 / 2, abs=1e-9)
    assert ymax == pytest.approx(55.1 + (1.0 / 60000) / 2, abs=1e-9)


def test_warp_extent_gives_a_whole_number_of_posts_plus_one():
    """The tile must contain tiledim/res + 1 posts -- the "+1" IS the post
    shared with the next tile (spec 13.2)."""
    res, tiledim = 2.5e-5, 0.1
    xmin, _ymin, xmax, _ymax = dl.tile_warp_extent(12.0, 55.0, tiledim,
                                                   res, res)
    n_pixels = (xmax - xmin) / res
    assert abs(n_pixels - round(n_pixels)) < 1e-6
    assert round(n_pixels) == round(tiledim / res) + 1


def test_adjacent_tiles_agree_on_their_shared_boundary_exactly():
    """v0.37 Finding 1, the arithmetic half. The east edge of one tile and
    the west edge of the next must be the IDENTICAL float, however each was
    reached -- that is what the rounding in tile_warp_extent() is for.
    (reconcile_tile_edges() is what makes the PIXELS match; this only makes
    the coordinates match.)"""
    res, tiledim = 2.5e-5, 0.1
    a = dl.tile_warp_extent(12.0, 55.0, tiledim, res, res)
    b = dl.tile_warp_extent(12.1, 55.0, tiledim, res, res)
    # The shared post sits at 12.1: it is a's LAST post (half a post inside
    # a's eastern warp edge) and b's FIRST post (half a post inside b's
    # western warp edge). Those two must be the identical float, not merely
    # close, or two independent gdalwarp calls can land on different source
    # pixels for the row they are required to share.
    a_last_post = a[2] - res / 2.0
    b_first_post = b[0] + res / 2.0
    assert a_last_post == b_first_post, (a_last_post, b_first_post)
    assert repr(a_last_post) == repr(b_first_post)


def test_warp_extent_is_reproducible_across_call_paths():
    """The same boundary reached by two different arithmetic routes must
    produce byte-identical floats, or two independent gdalwarp calls can
    disagree about where the shared post is."""
    direct = dl.tile_warp_extent(0.1 * 3, 55.0, 0.1, 2.5e-5, 2.5e-5)
    summed = dl.tile_warp_extent(0.1 + 0.1 + 0.1, 55.0, 0.1, 2.5e-5, 2.5e-5)
    assert direct == summed


# =============================================================================
# Source-type codes (spec 12.1)
# =============================================================================

def test_the_default_source_type_is_valid_and_silent():
    ok, msg = dl.describe_source_type("A")
    assert ok and msg == ""


@pytest.mark.parametrize("letter", sorted(dl.SOURCE_TYPE_CODES))
def test_every_defined_source_code_is_accepted(letter):
    ok, _ = dl.describe_source_type(letter)
    assert ok


@pytest.mark.parametrize("letter", sorted(dl.RESERVED_SOURCE_TYPE_CODES))
def test_reserved_codes_are_reported_as_reserved_not_unknown(letter):
    ok, msg = dl.describe_source_type(letter)
    assert not ok
    assert "reserved" in msg


def test_an_unknown_code_is_rejected_with_the_valid_list():
    ok, msg = dl.describe_source_type("@")
    assert not ok and "valid codes are" in msg


def test_source_code_check_is_case_insensitive_and_strips():
    assert dl.describe_source_type("  a  ")[0] is True


def test_reserved_and_defined_codes_do_not_overlap():
    assert not (set(dl.SOURCE_TYPE_CODES) & dl.RESERVED_SOURCE_TYPE_CODES)


# =============================================================================
# Resampler policy
# =============================================================================

def test_auto_downsampling_uses_average():
    """'average' is a mean of the contributing posts, so it can never leave
    [source min, source max] -- which is why auto never picks a cubic."""
    assert dl.pick_resampler(src_gsd_m=2.0, dst_gsd_m=30.0) == "average"


def test_auto_upsampling_uses_bilinear():
    assert dl.pick_resampler(src_gsd_m=30.0, dst_gsd_m=2.0) == "bilinear"


def test_auto_near_equal_resolution_uses_bilinear():
    assert dl.pick_resampler(src_gsd_m=2.0, dst_gsd_m=2.0) == "bilinear"


def test_auto_never_picks_an_overshoot_prone_resampler():
    for src in (0.1, 1.0, 2.0, 30.0, 1000.0):
        for dst in (0.1, 1.0, 2.0, 30.0, 1000.0):
            assert dl.pick_resampler(src, dst) not in \
                dl.OVERSHOOT_PRONE_RESAMPLERS


@pytest.mark.parametrize("alg", ["near", "bilinear", "cubic", "cubicspline",
                                 "average", "lanczos"])
def test_an_explicit_override_always_wins(alg):
    assert dl.pick_resampler(2.0, 30.0, override=alg) == alg


def test_overshoot_prone_set_is_exactly_the_cubic_family():
    assert dl.OVERSHOOT_PRONE_RESAMPLERS == {"cubic", "cubicspline", "lanczos"}


# =============================================================================
# v0.42 pre-flight guards
# =============================================================================

@pytest.mark.parametrize("name", sorted(dl.VALID_RESAMPLERS))
def test_validate_resampler_accepts_every_documented_value(name):
    assert dl.validate_resampler(name) == name


def test_validate_resampler_normalises_case_and_whitespace():
    assert dl.validate_resampler("  BiLiNeAr ") == "bilinear"


def test_validate_resampler_defaults_to_auto():
    assert dl.validate_resampler(None) == "auto"
    assert dl.validate_resampler("") == "auto"


@pytest.mark.parametrize("bad", ["bilinier", "nearest", "cubic-spline",
                                 "none", "mode", "NEAREST_NEIGHBOR"])
def test_validate_resampler_rejects_anything_else(bad):
    """v0.42: before this, a typo reached gdalwarp and was rejected once per
    tile -- N error lines, then "All done!" and exit code 0 over an empty
    output folder."""
    with pytest.raises(SystemExit) as e:
        dl.validate_resampler(bad)
    assert bad in str(e.value)
    assert "bilinear" in str(e.value)      # the valid list is shown


def test_a_bad_resampler_is_caught_before_any_warp():
    """pick_resampler() is the funnel every converter and the GUI go
    through, so the check has to live there rather than in one CLI."""
    with pytest.raises(SystemExit):
        dl.pick_resampler(2.0, 30.0, override="bilinier")


def test_require_epsg_passes_a_real_code_through():
    assert dl.require_epsg("4326", "x.tif") == "4326"
    assert dl.require_epsg(4326, "x.tif") == "4326"


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_require_epsg_rejects_a_missing_code_with_the_file_name(empty):
    """v0.42: this used to reach int(None) inside get_bbox_of_output() and
    surface as a TypeError that named neither the file nor the problem."""
    with pytest.raises(SystemExit) as e:
        dl.require_epsg(empty, "/data/no_crs.tif")
    msg = str(e.value)
    assert "/data/no_crs.tif" in msg
    assert "gdal_edit" in msg               # the fix is in the message


def test_require_gdalwarp_reports_the_path_or_explains_the_fix():
    import shutil
    if shutil.which("gdalwarp"):
        assert dl.require_gdalwarp().lower().find("gdalwarp") >= 0
    else:
        with pytest.raises(SystemExit) as e:
            dl.require_gdalwarp()
        assert "conda" in str(e.value)


# =============================================================================
# GDAL error-handling contract (v0.41)
# =============================================================================

@requires_gdal
def test_gdal_exceptions_are_explicitly_configured():
    """v0.41 finding 10. The setting is process-wide, and importing
    dem2dged_lib is what pins it. It must be OFF: the whole codebase is
    written against the "gdal.Open returns None" contract, and the
    validator deliberately builds an osr.SpatialReference from a possibly
    empty WKT while only WARNING about it."""
    from osgeo import gdal
    assert gdal.GetUseExceptions() == 0


@requires_gdal
def test_gdal_ogr_osr_share_one_exception_flag():
    """Measured on GDAL 3.13.2, and the reason the v0.41 fix could not be
    "gdal on, osr off": that state does not exist. If a future GDAL ever
    separates the flags this test fails loudly, which is the point -- the
    choice above would then need revisiting rather than silently meaning
    something different."""
    from osgeo import gdal, ogr, osr
    assert gdal.GetUseExceptions() == ogr.GetUseExceptions() == \
        osr.GetUseExceptions()


@requires_gdal
def test_gdal_open_returns_none_instead_of_raising():
    assert dl.gdal_open("this_file_does_not_exist_anywhere.tif") is None


@requires_gdal
def test_quick_raster_range_degrades_instead_of_crashing():
    assert dl.quick_raster_range("this_file_does_not_exist_anywhere.tif") is None


@requires_gdal
def test_clamp_tile_to_range_degrades_on_an_unreadable_tile():
    assert dl.clamp_tile_to_range("no_such_tile.tif", 0.0, 100.0) == 0


# =============================================================================
# Elevation sanity check (v0.36)
# =============================================================================

def _with_fixed_range(rng, path):
    original = dl.quick_raster_range
    dl.quick_raster_range = lambda _p, _v=rng: _v
    try:
        return dl.sanity_check_elevation_source(path)
    finally:
        dl.quick_raster_range = original


def test_plain_elevation_raises_nothing():
    assert _with_fixed_range((-5.0, 1800.0), "srtm_n55e012.tif") == []


def test_filename_hint_alone_is_only_a_warning():
    issues = _with_fixed_range((-5.0, 1800.0), "terrain_aspect.tif")
    assert issues and all(sev == "warn" for sev, _ in issues)


def test_angular_range_alone_is_only_a_warning():
    issues = _with_fixed_range((0.0, 359.9), "dem_tile_07.tif")
    assert issues and all(sev == "warn" for sev, _ in issues)


def test_both_signals_together_block():
    """The whole point of the v0.36 check: an aspect raster fed in as if it
    were elevation produces a mechanically valid DGED package full of
    compass bearings. Either signal alone is only ever a warning, because
    real elevation files are sometimes named oddly and real terrain can
    genuinely span close to 360 units."""
    issues = _with_fixed_range((0.0, 359.9), "flow_direction_aspect.tif")
    assert any(sev == "block" for sev, _ in issues)


def test_the_real_aspect_raster_that_motivated_the_v036_widening():
    """min 18.52, max 345.51 -- the actual numbers from the bug report. The
    first cut of _classify_angular_range() used tight windows at exactly 0
    and 360 and would have MISSED this, the very case it exists to catch."""
    issues = _with_fixed_range((18.52, 345.51), "slope_aspect_utm32.tif")
    assert any(sev == "block" for sev, _ in issues)


def test_an_unreadable_raster_never_blocks_a_conversion():
    """A failure to inspect must not itself stop a run the operator wants."""
    assert _with_fixed_range(None, "perfectly_normal_dem.tif") == []


def test_angular_classifier_is_shared_so_it_cannot_drift():
    assert dl._classify_angular_range((0.0, 359.9)) is True
    assert dl._classify_angular_range((-430.0, 8849.0)) is False
    assert dl._classify_angular_range(None) is False


# =============================================================================
# Statistics helper
# =============================================================================

@requires_gdal
def test_compute_tile_stats_ignores_nodata(tmp_path):
    from osgeo import gdal
    import struct
    p = str(tmp_path / "stats.tif")
    ds = gdal.GetDriverByName("GTiff").Create(p, 10, 10, 1, gdal.GDT_Float32)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767.0)
    for j in range(10):
        row = [(-32767.0 if (i + j) % 5 == 0 else 100.0 + i) for i in range(10)]
        band.WriteRaster(0, j, 10, 1, struct.pack("<10f", *row),
                         buf_type=gdal.GDT_Float32)
    band.FlushCache(); ds.FlushCache(); ds = None

    vmin, vmax, miss = dl.compute_tile_stats(p)
    assert vmin >= 100 and vmax <= 109
    assert 0.0 < miss < 100.0


@requires_gdal
def test_compute_tile_stats_on_an_all_nodata_tile(tmp_path):
    from osgeo import gdal
    import struct
    p = str(tmp_path / "empty.tif")
    ds = gdal.GetDriverByName("GTiff").Create(p, 8, 8, 1, gdal.GDT_Float32)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767.0)
    for j in range(8):
        band.WriteRaster(0, j, 8, 1, struct.pack("<8f", *([-32767.0] * 8)),
                         buf_type=gdal.GDT_Float32)
    band.FlushCache(); ds.FlushCache(); ds = None
    assert dl.compute_tile_stats(p) == (0, 0, 100.0)


@requires_gdal
def test_compute_tile_stats_raises_on_an_unreadable_file():
    with pytest.raises(FileNotFoundError):
        dl.compute_tile_stats("definitely_not_here.tif")


# =============================================================================
# Misc
# =============================================================================

def test_nodata_value_is_the_one_the_converters_pass_to_gdalwarp():
    """-32767 appears as a literal in both converters and the GUI; the
    validator imports its own NODATA. They have to be the same number."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for mod in ("dem2dged_geo.py", "dem2dged_utm.py"):
        text = open(os.path.join(project, mod), encoding="utf-8").read()
        assert '"-dstnodata", "-32767"' in text, mod


def test_toc_filename_is_the_spec_name():
    assert dl.TOC_FILENAME == "TABLE_OF_CONTENTS.xml"


def test_classification_words_cover_every_spec_class():
    assert set(dl.CLASSIFICATION_WORDS) == {"T", "S", "C", "R", "U"}


def test_run_cmd_returns_127_for_a_missing_executable():
    """v0.42: this used to raise FileNotFoundError out of the tile loop as a
    raw traceback. The callers' contract is an exit code."""
    assert dl.run_cmd(["definitely_not_a_real_program_xyz", "--help"]) == 127


# =============================================================================
# Console encoding safety (v0.44)
# =============================================================================

GLYPHS = "\u2713 \u2717 \u274c \u2500 \u2192"     # check, ballot-x, cross,
                                                  # box-drawing, arrow


class _StrictConsole:
    """A stdout that behaves like a Korean/Japanese/Chinese Windows console:
    it accepts ASCII and raises UnicodeEncodeError on anything else."""

    encoding = "cp949"

    def __init__(self):
        self.written = []

    def write(self, s):
        s.encode("ascii")          # raises UnicodeEncodeError on a glyph
        self.written.append(s)
        return len(s)

    def flush(self):
        pass


def test_plain_print_really_does_fail_on_a_legacy_console(monkeypatch):
    """Establish the premise before testing the fix -- otherwise the test
    below could pass because the harness is wrong rather than because
    safe_print works."""
    console = _StrictConsole()
    monkeypatch.setattr("sys.stdout", console)
    with pytest.raises(UnicodeEncodeError):
        print(GLYPHS)


def test_safe_print_survives_an_unencodable_console(monkeypatch):
    """v0.44. Reported from a real cp949 console:

        print(f"\u2713 Source directory verified ...")
        UnicodeEncodeError: 'cp949' codec can't encode character '\u2713'

    A decorative tick mark aborted release packaging. safe_print() must
    degrade to a replacement character and carry on -- a message the user
    cannot read is a nuisance, a message that raises is a defect.
    """
    console = _StrictConsole()
    monkeypatch.setattr("sys.stdout", console)
    dl.safe_print(GLYPHS)                      # must not raise
    dl.safe_print("plain ascii line")
    assert any("plain ascii line" in s for s in console.written)


def test_safe_print_handles_an_unencodable_path_in_a_message(monkeypatch):
    """The realistic case is not a decorative glyph but an interpolated
    value: a Korean or accented directory name in a path or an exception
    message is enough to hit this."""
    console = _StrictConsole()
    monkeypatch.setattr("sys.stdout", console)
    dl.safe_print("[FAIL] Error: cannot read %s" % "C:\\\uc0ac\uc6a9\uc790\\dem.tif")


def test_the_packaging_scripts_contain_no_non_ascii(  # noqa: N802
        ):
    """v0.44, and the reason the bug existed at all: dem2dged_package.py
    printed U+2713 / U+2717 / U+274C. Those encode under UTF-8 and not at
    all under cp949, cp932, cp936 or ASCII -- a large share of the machines
    this tool runs on. The scripts below write to the console and nowhere
    else, so keeping them pure ASCII removes the failure mode rather than
    handling it.

    dem2dged_gui.py is excluded on purpose (Tkinter labels, not console
    output) and so is dem2dged_validate.py (report CONTENT, written to a
    UTF-8 file, with its console echo already protected since v0.38).
    """
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("dem2dged_package.py", "dem2dged_validate_package.py",
                 "BUILD_AND_PACKAGE.py", "dem2dged_anaconda_environment.py",
                 "run_verification.py", "audit_pure.py", "dem2dged.py",
                 "dem2dged_geo.py", "dem2dged_utm.py"):
        path = os.path.join(project, name)
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        offenders = sorted({c for c in text if ord(c) > 127})
        assert not offenders, (
            "%s contains non-ASCII character(s) %s -- these raise "
            "UnicodeEncodeError on a cp949/cp932/cp936 console"
            % (name, [hex(ord(c)) for c in offenders]))


# =============================================================================
# The packaging scripts must not destroy the release notes (v0.45)
# =============================================================================

def test_create_version_file_preserves_the_changelog(tmp_path):
    """v0.45. create_version_file() wrote VERSION.txt from a hardcoded
    f-string whose changelog was frozen at "Changes in v0.40", so EVERY
    packaging run overwrote the maintained file with that stale copy and
    silently deleted every entry written since. It is why the v0.41 release
    notes do not exist anywhere: they were written, then packaged away.

    The damage is invisible while it happens -- the script prints a success
    line and the HEADER it writes is correct. Only the body is wrong, and
    only if you read it.
    """
    import importlib.util

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "_pkg", os.path.join(project, "dem2dged_package.py"))
    pkg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pkg)

    sentinel = "Changes in v9.99:\n- A UNIQUE MARKER THAT MUST SURVIVE.\n"
    target = tmp_path / "VERSION.txt"
    target.write_text(
        "DEM2DGED Version Information\n"
        "============================\n\n"
        "Version: 0.01\nBuild Date: long ago\nPackage: old\n\n" + sentinel,
        encoding="utf-8")

    pkg.create_version_file(str(tmp_path))

    after = target.read_text(encoding="utf-8")
    assert "A UNIQUE MARKER THAT MUST SURVIVE" in after, (
        "create_version_file() destroyed the changelog again")
    assert "Version: %s" % pkg.VERSION_DISPLAY in after, "header not refreshed"
    assert "Build Date:" in after
    assert "Version: 0.01" not in after, "stale header line left behind"


def test_create_version_file_writes_a_stub_when_none_exists(tmp_path):
    import importlib.util

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "_pkg2", os.path.join(project, "dem2dged_package.py"))
    pkg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pkg)

    pkg.create_version_file(str(tmp_path))
    text = (tmp_path / "VERSION.txt").read_text(encoding="utf-8")
    assert "Version: %s" % pkg.VERSION_DISPLAY in text
    assert "Changes in" in text


def test_the_shipped_version_txt_still_has_its_recent_entries():
    """A direct guard on the artefact itself: if a packaging run ever eats
    the changelog again, this fails on the next test run rather than being
    noticed several releases later."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(project, "VERSION.txt"), encoding="utf-8").read()
    assert "Changes in v%s:" % dl.VERSION in text, (
        "VERSION.txt has no entry for the current version %s" % dl.VERSION)
    n_entries = text.count("\nChanges in v")
    assert n_entries >= 10, (
        "VERSION.txt has only %d changelog entries -- it looks truncated"
        % n_entries)


# =============================================================================
# Interpreter diagnosis (v0.45)
# =============================================================================

def test_dem2dged_env_imports_with_nothing_installed():
    """It has to be importable in exactly the broken interpreter where
    nothing else is, so it may not import anything but os and sys."""
    import ast

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tree = ast.parse(open(os.path.join(project, "dem2dged_env.py"),
                          encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"os", "sys"}, (
        "dem2dged_env.py must not import %s -- it has to work in an "
        "interpreter where third-party packages are missing"
        % (imported - {"os", "sys"}))


def test_the_wrong_interpreter_message_names_the_command_form(monkeypatch):
    """v0.45. Both reported instances of this were misdiagnosed by the
    tool's own message: 'Are you in the DGED environment?' asked from a
    prompt that said (DGED). The message must point at the COMMAND FORM."""
    import dem2dged_env

    monkeypatch.setenv("CONDA_PREFIX", os.path.join("X:", "envs", "DGED"))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "DGED")
    monkeypatch.setattr("sys.executable",
                        os.path.join("C:", "Windows", "py.exe"))

    assert dem2dged_env.running_inside_active_env() is False
    msg = dem2dged_env.missing_module_message("osgeo", script="PACKAGE.py")
    assert "python PACKAGE.py" in msg
    assert "file association" in msg
    assert "COMMAND-FORM PROBLEM" in msg
    assert "conda install" not in msg      # must NOT send them to reinstall


def test_the_right_interpreter_message_does_suggest_installing(monkeypatch):
    import dem2dged_env

    prefix = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
    monkeypatch.setenv("CONDA_PREFIX", os.path.dirname(
        os.path.abspath(sys.executable)))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "DGED")
    assert dem2dged_env.running_inside_active_env() is True
    msg = dem2dged_env.missing_module_message("numpy")
    assert "conda install" in msg
    assert "COMMAND-FORM PROBLEM" not in msg
    assert prefix is not None


def test_no_active_environment_is_reported_as_such(monkeypatch):
    import dem2dged_env

    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)
    assert dem2dged_env.running_inside_active_env() is None
    msg = dem2dged_env.missing_module_message("numpy")
    assert "No conda environment is active" in msg
