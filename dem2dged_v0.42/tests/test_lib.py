# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.42
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Unit tests for dem2dged_lib.py plus the project-wide version-consistency
checks introduced in v0.34.

These are pure-Python: nothing here needs a real raster, so the whole module
runs in a bare environment (GDAL is still imported transitively by
dem2dged_lib, so the file is skipped wholesale if osgeo is missing).
"""

import math
import os
import re

import pytest

pytest.importorskip("osgeo", reason="dem2dged_lib imports osgeo at module level")

import dem2dged_lib as dl  # noqa: E402


# -- DGED tables ---------------------------------------------------------------

@pytest.mark.unit
def test_geo_level_table_is_complete_and_ordered():
    levels = [l[0] for l in dl.level_tilesize_and_spatial_resolution]
    assert levels == ["0", "1", "2", "3", "4b", "4", "5", "6", "7", "8", "9"]
    for lvl, tsize_min, latres_sec, letter in dl.level_tilesize_and_spatial_resolution:
        assert tsize_min > 0
        assert latres_sec > 0
        assert re.fullmatch(r"[A-Z]", letter)


@pytest.mark.unit
def test_utm_level_table_is_complete():
    levels = [l[0] for l in dl.PL]
    assert levels == ["4b", "4", "5", "6", "7", "8", "9"]
    for lvl, gsd, posts, letter in dl.PL:
        assert gsd > 0
        # One-post overlap: a tile carries posts on BOTH its boundaries.
        assert posts >= 2
        assert re.fullmatch(r"[A-Z]", letter)


@pytest.mark.unit
@pytest.mark.parametrize("lvl,tsize_min,latres_sec,letter",
                         dl.level_tilesize_and_spatial_resolution)
def test_every_zone_factor_divides_the_geo_tile_evenly(lvl, tsize_min,
                                                       latres_sec, letter):
    """Posts can only align if a tile spans a whole number of longitude
    intervals in EVERY latitude zone.

    This is exactly the property the v0.27 change to levels 8/9 (1.5-minute
    tiles instead of 1-minute) was made to restore -- with a 1-minute tile,
    zones with factor 1.5 and 3 gave a fractional interval count.
    """
    tiledim = tsize_min / 60.0
    latres = latres_sec / 3600.0
    for _zid, _lo, _hi, _latsp, factor in dl.zone_lon_spacing:
        lonres = factor * latres
        n = tiledim / lonres
        assert abs(n - round(n)) < 1e-6, (
            "level %s zone factor %s: %.4f longitude intervals per tile"
            % (lvl, factor, n))


# -- data types / predictor ----------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("level,expected", [
    ("0", "Int16"), ("1", "Int16"), ("2", "Int16"),
    ("3", "Float32"), ("4b", "Float32"), ("4", "Float32"),
    ("5", "Float32"), ("6", "Float32"), ("7", "Float32"),
    ("8", "Float32"), ("9", "Float32"),
])
def test_output_type_for_level(level, expected):
    assert dl.output_type_for_level(level) == expected


@pytest.mark.unit
def test_predictor_is_data_type_aware():
    """v0.39: PREDICTOR=2 (horizontal differencing) is only defined for
    integer samples; Float32 must use PREDICTOR=3 (IEEE floating point)."""
    assert dl.predictor_for_type("Int16") == "2"
    assert dl.predictor_for_type("Float32") == "3"


# -- GDAL error-handling contract (v0.41) --------------------------------------

@pytest.mark.unit
def test_gdal_exceptions_are_explicitly_configured():
    """v0.41: leaving this unset made the SAME library code take two
    different error paths depending on the entry point -- dem2dged_gui.py
    and run_verification.py called gdal.UseExceptions(), the CLI and the
    validator did not -- and GDAL 3.7+ warns that 4.0 will flip the default.
    dem2dged_lib now pins it explicitly, and OFF, because the whole codebase
    is written against the "returns None" contract and several call sites
    must survive a raster with a weak or absent CRS.

    The point of this test is that the state is EXPLICIT and uniform, not
    left to the GDAL version.
    """
    from osgeo import gdal, ogr, osr

    assert gdal.GetUseExceptions() == 0
    assert ogr.GetUseExceptions() == 0
    assert osr.GetUseExceptions() == 0


@pytest.mark.unit
def test_gdal_ogr_osr_share_one_exception_flag():
    """Measured on GDAL 3.13.2, and the reason the setting is all-or-nothing.

    A first cut of the v0.41 fix tried "gdal on, osr off" and the assertion
    that gdal was on failed immediately afterwards -- ogr/osr's
    DontUseExceptions() had turned gdal's back off. If a future GDAL ever
    separates them, this test fails and the header comment in
    dem2dged_lib.py needs revisiting; the gdal_open() shim means nothing
    else has to change.
    """
    from osgeo import gdal, ogr, osr

    try:
        gdal.UseExceptions()
        assert gdal.GetUseExceptions() == 1
        osr.DontUseExceptions()
        assert gdal.GetUseExceptions() == 0, (
            "gdal/osr no longer share one exception flag -- revisit the "
            "GDAL error-handling note at the top of dem2dged_lib.py")
    finally:
        # Restore what dem2dged_lib pinned, whatever happened above.
        gdal.DontUseExceptions()
        ogr.DontUseExceptions()
        osr.DontUseExceptions()


@pytest.mark.unit
def test_gdal_open_returns_none_instead_of_raising(tmp_path):
    """gdal_open() must give the same answer whichever way GDAL is
    configured, because several call sites degrade gracefully on None
    (reconcile_tile_edges skips an edge, quick_raster_range warns, ...)."""
    missing = str(tmp_path / "does_not_exist.tif")
    assert dl.gdal_open(missing) is None

    junk = tmp_path / "not_a_raster.tif"
    junk.write_bytes(b"this is definitely not a GeoTIFF")
    assert dl.gdal_open(str(junk)) is None


@pytest.mark.unit
def test_quick_raster_range_degrades_instead_of_crashing(tmp_path):
    """The v0.36 sanity check depends on this returning None, not raising."""
    junk = tmp_path / "junk.tif"
    junk.write_bytes(b"nope")
    assert dl.quick_raster_range(str(junk)) is None
    assert dl.quick_raster_range(str(tmp_path / "absent.tif")) is None


@pytest.mark.unit
def test_clamp_tile_to_range_degrades_on_an_unreadable_tile(tmp_path):
    junk = tmp_path / "junk.tif"
    junk.write_bytes(b"nope")
    assert dl.clamp_tile_to_range(str(junk), 0.0, 100.0) == 0


# -- coordinate helpers --------------------------------------------------------

@pytest.mark.unit
def test_todms_basic():
    assert dl.ToDMS(55.5) == (55, 30, 0.0)
    d, m, s = dl.ToDMS(12.0)
    assert (d, m) == (12, 0) and abs(s) < 1e-9


@pytest.mark.unit
def test_todms_avoids_59_999_artefacts():
    """Rounding to 1/10000 arc-second must not produce 59.999... seconds."""
    for dd in (55.999999999, 12.0000000001, 1.0 - 1e-12):
        _d, m, s = dl.ToDMS(dd)
        assert 0 <= m < 60
        assert 0 <= s < 60


@pytest.mark.unit
def test_tile_warp_extent_is_half_post_expanded():
    """v0.27: gdalwarp samples at pixel CENTERS, so the extent must reach
    half a post beyond the outermost posts on every side (spec 6.3)."""
    xmin, ymin, xmax, ymax = dl.tile_warp_extent(10.0, 55.0, 0.1, 0.001, 0.001)
    assert math.isclose(xmin, 10.0 - 0.0005, abs_tol=1e-12)
    assert math.isclose(ymin, 55.0 - 0.0005, abs_tol=1e-12)
    assert math.isclose(xmax, 10.1 + 0.0005, abs_tol=1e-12)
    assert math.isclose(ymax, 55.0 + 0.1 + 0.0005, abs_tol=1e-12)
    # The resulting pixel count is (tiledim / res) + 1 -- the one-post overlap.
    assert round((xmax - xmin) / 0.001) == round(0.1 / 0.001) + 1


@pytest.mark.unit
def test_tile_warp_extent_is_reproducible_however_it_is_reached():
    """v0.37 Finding 1: the same real boundary must be the identical float
    however it was computed, or adjacent tiles disagree on the shared post."""
    a = dl.tile_warp_extent(0.1 + 0.2, 55.0, 0.1, 0.001, 0.001)
    b = dl.tile_warp_extent(0.3, 55.0, 0.1, 0.001, 0.001)
    assert a == b


# -- filenames (spec 12.1) -----------------------------------------------------

@pytest.mark.unit
def test_geo_level_0_to_3_use_the_short_form():
    """No product-type letter and no tile-size indicator for L0-3."""
    b = dl.geo_tile_basename("2", "A", 27.0, 56.0, "A", "U", "01")
    assert b == "DGEDL2_27N056E_A_U_01"
    assert "Gt" not in b


@pytest.mark.unit
def test_geo_level_5_carries_the_tile_letter_and_minutes():
    b = dl.geo_tile_basename("5", "D", 55.5, 12.2, "A", "U", "01")
    assert b.startswith("DGEDL5GtD_")
    assert b == "DGEDL5GtD_5530N01212E_A_U_01"


@pytest.mark.unit
def test_geo_org_code_is_inserted_as_the_second_subfield():
    b = dl.geo_tile_basename("2", "A", 27.0, 56.0, "A", "U", "01", org="dnk")
    assert b == "DGEDL2_DNK_27N056E_A_U_01"


@pytest.mark.unit
def test_geo_southern_and_western_hemispheres():
    b = dl.geo_tile_basename("2", "A", -34.0, -58.0, "A", "U", "01")
    assert "S" in b and "W" in b
    assert b == "DGEDL2_34S058W_A_U_01"


@pytest.mark.unit
@pytest.mark.parametrize("level,widths", [
    ("4b", (4, 3)), ("4", (4, 3)), ("5", (4, 3)), ("6", (4, 3)),
    ("7", (7, 6)), ("8", (7, 6)), ("9", (7, 6)),
])
def test_utm_name_field_widths(level, widths):
    assert dl.utm_name_field_widths(level) == widths


@pytest.mark.unit
def test_utm_names_are_zero_padded():
    """v0.34 (SPEC): every northing below 1 000 000 m -- anywhere within
    ~9 degrees of the equator -- used to produce a short, non-spec field."""
    on_equator = dl.utm_tile_basename("5", "D", "32N", 0.0, 500000.0,
                                      "A", "U", "01")
    assert on_equator == "DGEDL5UtD_32N0000_500_A_U_01"

    low = dl.utm_tile_basename("5", "D", "32N", 500000.0, 400000.0,
                               "A", "U", "01")
    assert low == "DGEDL5UtD_32N0500_400_A_U_01"


@pytest.mark.unit
def test_utm_metre_form_levels_use_seven_and_six_digits():
    b = dl.utm_tile_basename("9", "G", "32N", 6000000.0, 500000.0,
                             "A", "U", "01")
    assert b == "DGEDL9UtG_32N6000000_500000_A_U_01"


# -- source-type codes (spec 12.1) ---------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("letter", list("ABCFGHKLMNOPTUVXY"))
def test_defined_source_type_codes_are_accepted_silently(letter):
    ok, msg = dl.describe_source_type(letter)
    assert ok is True and msg == ""


@pytest.mark.unit
@pytest.mark.parametrize("letter", list("DEIJQRSWZ"))
def test_reserved_source_type_codes_are_flagged(letter):
    ok, msg = dl.describe_source_type(letter)
    assert ok is False
    assert "reserved" in msg.lower()


@pytest.mark.unit
def test_unknown_source_type_code_is_flagged_but_never_crashes():
    for bad in ("", None, "1", "AB"):
        ok, msg = dl.describe_source_type(bad)
        assert ok is False and msg


# -- resampler selection -------------------------------------------------------

@pytest.mark.unit
def test_pick_resampler_rules():
    assert dl.pick_resampler(10, 30) == "average"     # downsampling
    assert dl.pick_resampler(30, 10) == "bilinear"    # upsampling
    assert dl.pick_resampler(30, 10, "cubic") == "cubic"
    assert dl.pick_resampler(30, 10, "auto") == "bilinear"


@pytest.mark.unit
def test_auto_never_resolves_to_an_overshoot_prone_resampler():
    """The clamp in the converters only runs for OVERSHOOT_PRONE_RESAMPLERS,
    so 'auto' must never land on one of its own (v0.37 Finding 3)."""
    for src, dst in [(1, 100), (100, 1), (5, 5), (0.5, 30), (30, 0.5)]:
        assert dl.pick_resampler(src, dst) not in dl.OVERSHOOT_PRONE_RESAMPLERS


@pytest.mark.unit
def test_overshoot_prone_set_contents():
    assert dl.OVERSHOOT_PRONE_RESAMPLERS == frozenset(
        {"cubic", "cubicspline", "lanczos"})


@pytest.mark.unit
def test_resolve_resampler_matches_pick_resampler_for_non_optimize(monkeypatch):
    for override in (None, "auto", "cubic", "near", "average"):
        assert (dl.resolve_resampler("x.tif", 30, 10, override)
                == dl.pick_resampler(30, 10, override))


# -- elevation sanity check (v0.36) --------------------------------------------

def _with_range(monkeypatch, rng):
    monkeypatch.setattr(dl, "quick_raster_range", lambda path: rng)


@pytest.mark.unit
def test_sanity_blocks_on_aspect_filename_and_aspect_range(monkeypatch):
    _with_range(monkeypatch, (18.52, 345.51))
    issues = dl.sanity_check_elevation_source("aspect_dtm_2m_utm18.tif")
    assert [sev for sev, _m in issues] == ["block"]


@pytest.mark.unit
def test_sanity_warns_on_a_single_signal(monkeypatch):
    _with_range(monkeypatch, (100.0, 250.0))
    assert [s for s, _ in dl.sanity_check_elevation_source("aspect_x.tif")] == ["warn"]
    _with_range(monkeypatch, (0.5, 359.8))
    assert [s for s, _ in dl.sanity_check_elevation_source("my_dem.tif")] == ["warn"]


@pytest.mark.unit
def test_sanity_is_clean_for_real_elevation(monkeypatch):
    for rng in [(100.0, 250.0), (0.0, 50.0), (1200.0, 1800.0)]:
        _with_range(monkeypatch, rng)
        assert dl.sanity_check_elevation_source("my_dem.tif") == []


@pytest.mark.unit
def test_sanity_never_crashes_on_an_unreadable_raster(monkeypatch):
    _with_range(monkeypatch, None)
    assert [s for s, _ in dl.sanity_check_elevation_source("curvature.tif")] == ["warn"]
    assert dl.sanity_check_elevation_source("my_dem.tif") == []


# -- accuracy tables -----------------------------------------------------------

@pytest.mark.unit
def test_accuracy_tables_cover_every_level():
    for lvl in [l[0] for l in dl.level_tilesize_and_spatial_resolution]:
        assert lvl in dl.LEVEL_ABS_HACC
        assert lvl in dl.LEVEL_ABS_VACC


# -- version consistency (v0.34; the whole point of this section) --------------

VERSIONED_TXT = ("VERSION.txt", "VALIDATOR_VERSION.txt")
VERSIONED_CONST = ("dem2dged_package.py", "dem2dged_validate_package.py",
                   "BUILD_AND_PACKAGE.py", "dem2dged_essential_package.py")
VERSIONED_HEADER = ("dem2dged.py", "dem2dged_geo.py", "dem2dged_utm.py",
                    "dem2dged_gui.py", "dem2dged_lib.py",
                    "dem2dged_validate.py", "dem2dged_compare.py")


@pytest.mark.unit
def test_version_is_a_bare_major_minor_string():
    assert re.fullmatch(r"\d+\.\d+", dl.VERSION)


@pytest.mark.unit
@pytest.mark.parametrize("fname", VERSIONED_TXT)
def test_release_notes_declare_the_current_version(project_root, fname):
    text = open(os.path.join(project_root, fname), encoding="utf-8").read()
    m = re.search(r"^Version:\s*(\d+\.\d+)", text, re.M)
    assert m, "%s has no 'Version:' line" % fname
    assert m.group(1) == dl.VERSION


@pytest.mark.unit
@pytest.mark.parametrize("fname", VERSIONED_CONST)
def test_packaging_scripts_declare_the_current_version(project_root, fname):
    text = open(os.path.join(project_root, fname), encoding="utf-8").read()
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    assert m, "%s has no module-level VERSION" % fname
    assert m.group(1) == dl.VERSION


@pytest.mark.unit
@pytest.mark.parametrize("fname", VERSIONED_HEADER)
def test_module_header_comments_declare_the_current_version(project_root, fname):
    """v0.41: these header comments were missing from every module, and the
    audit pattern that was supposed to check them required 'Version:' in
    column 0 -- impossible in a .py file outside a string -- so nothing was
    ever actually verified. Both sides are checked here."""
    text = open(os.path.join(project_root, fname), encoding="utf-8").read(4000)
    m = re.search(r"^#?\s*Version:\s*(\d+\.\d+)", text, re.M)
    assert m, "%s has no 'Version:' header comment in its first 4000 bytes" % fname
    assert m.group(1) == dl.VERSION


@pytest.mark.unit
def test_gui_version_fallback_matches(project_root):
    """dem2dged_gui.py hardcodes a fallback used only if the import fails."""
    text = open(os.path.join(project_root, "dem2dged_gui.py"), encoding="utf-8").read()
    for m in re.finditer(r'^\s*APP_VERSION(?:_DISPLAY)?\s*=\s*"([^"]+)"', text, re.M):
        assert m.group(1) == dl.VERSION


@pytest.mark.unit
def test_compare_version_fallback_matches(project_root):
    text = open(os.path.join(project_root, "dem2dged_compare.py"), encoding="utf-8").read()
    m = re.search(r'^\s*VERSION\s*=\s*"([^"]+)"\s*#\s*fallback', text, re.M)
    assert m and m.group(1) == dl.VERSION
