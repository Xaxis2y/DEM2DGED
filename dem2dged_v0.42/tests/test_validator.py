# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.42
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Tests for dem2dged_validate.py.

Two groups:

* Pure checks (no raster needed) -- the filename patterns, overall_result(),
  the product-level-XML name test, the placeholder detector, the origin
  tolerance. These are the regression tests for the v0.30 / v0.31 / v0.34 /
  v0.39 / v0.41 fixes, and they run anywhere GDAL can be imported.
* An end-to-end run of run_validation() against a real conversion, which
  additionally needs the gdalwarp executable.
"""

import glob
import os
import re
import shutil

import pytest

pytest.importorskip("osgeo", reason="the validator needs GDAL")

import dem2dged_lib as dl  # noqa: E402
import dem2dged_validate as dv  # noqa: E402


# ==============================================================================
# v0.41 regression -- the module must actually be importable and complete
# ==============================================================================

@pytest.mark.unit
def test_module_exposes_everything_its_callers_use():
    """v0.41: the v0.40 cut of dem2dged_validate.py was missing its imports,
    constants, filename patterns and the overall_result() definition, so the
    file did not byte-compile at all. dem2dged.py and dem2dged_gui.py both
    import this module and call these names."""
    for name in ("GEO_RE", "UTM_RE", "NODATA", "ELEV_MIN_SANE", "ELEV_MAX_SANE",
                 "overall_result", "run_validation", "check_tile", "check_edges",
                 "check_source", "check_pairing", "find_tiles",
                 "is_product_level_xml", "write_text_report",
                 "write_html_report", "render_html_report", "build_parser",
                 "main", "dms_to_deg", "lon_multi", "geo_level_params",
                 "utm_level_params", "Report", "TILE_CHECK_CATEGORIES"):
        assert hasattr(dv, name), "dem2dged_validate.%s is missing" % name


@pytest.mark.unit
def test_nodata_matches_what_the_converters_write():
    assert dv.NODATA == -32767


@pytest.mark.unit
def test_sane_elevation_band_brackets_the_real_world():
    """Deliberately generous: this catches the -32767 marker leaking into
    valid data, not unusual-but-real terrain."""
    assert dv.ELEV_MIN_SANE < -430.0     # Dead Sea shore
    assert dv.ELEV_MAX_SANE > 8849.0     # Everest
    assert dv.ELEV_MIN_SANE > dv.NODATA  # otherwise the check is a no-op


@pytest.mark.unit
def test_validator_version_tracks_the_library():
    assert dv.VERSION == dl.VERSION


# ==============================================================================
# B. filename patterns (spec 12.1)
# ==============================================================================

@pytest.mark.unit
@pytest.mark.parametrize("lvl,tsize_min,latres_sec,letter",
                         dl.level_tilesize_and_spatial_resolution)
@pytest.mark.parametrize("org", ["", "DNK"])
def test_geo_names_round_trip_through_the_pattern(lvl, tsize_min, latres_sec,
                                                  letter, org):
    import math

    tiledim = tsize_min / 60.0
    for lat_i, lon_i in [(55, 12), (0, 0), (-34, -58), (78, 15), (-1, -1)]:
        t_minlat = math.floor(lat_i / tiledim) * tiledim
        t_minlon = math.floor(lon_i / tiledim) * tiledim
        base = dl.geo_tile_basename(lvl, letter, t_minlat, t_minlon,
                                    "A", "U", "01", org=org)
        m = dv.GEO_RE.match(base)
        assert m, "%r does not match GEO_RE" % base
        assert m.group("lv") == lvl
        assert m.group("org") == (org or None)
        lat0 = dv.dms_to_deg(m.group("lat"), True) * (-1 if m.group("hemi") == "S" else 1)
        lon0 = dv.dms_to_deg(m.group("lon"), False) * (-1 if m.group("east") == "W" else 1)
        assert abs(lat0 - t_minlat) < 1e-6
        assert abs(lon0 - t_minlon) < 1e-6
        assert dv.UTM_RE.match(base) is None, "%r also matched UTM_RE" % base


@pytest.mark.unit
@pytest.mark.parametrize("lvl,gsd,posts,letter", dl.PL)
@pytest.mark.parametrize("zone", ["32N", "09S", "01N", "60S"])
def test_utm_names_round_trip_through_the_pattern(lvl, gsd, posts, letter, zone):
    import math

    tiledim = (posts - 1) * gsd
    for east_m, north_m in [(500000.0, 6000000.0), (400000.0, 500000.0),
                            (200000.0, 100000.0), (600000.0, 0.0)]:
        t_minx = math.floor(east_m / tiledim) * tiledim
        t_miny = math.floor(north_m / tiledim) * tiledim
        base = dl.utm_tile_basename(lvl, letter, zone, t_miny, t_minx,
                                    "A", "U", "01")
        m = dv.UTM_RE.match(base)
        assert m, "%r does not match UTM_RE" % base
        assert m.group("lv") == lvl
        assert m.group("zone") == zone
        mult = 1000 if lvl in ("4b", "4", "5", "6") else 1
        assert int(m.group("northing")) * mult == int(round(t_miny))
        assert int(m.group("easting")) * mult == int(round(t_minx))
        n_exp, e_exp = dl.utm_name_field_widths(lvl)
        assert len(m.group("northing")) == n_exp
        assert len(m.group("easting")) == e_exp
        assert dv.GEO_RE.match(base) is None, "%r also matched GEO_RE" % base


@pytest.mark.unit
def test_legacy_short_utm_name_still_parses_so_the_error_can_be_precise():
    """v0.34: the pattern stays permissive (\\d{1,7}) ON PURPOSE, so a
    pre-v0.34 unpadded name gets 'northing field "500" is 3 digit(s), spec
    12.1 requires 4' instead of an opaque 'does not match convention'."""
    legacy = "DGEDL5UtD_32N500_400_A_U_01"
    m = dv.UTM_RE.match(legacy)
    assert m is not None
    n_exp, _e_exp = dl.utm_name_field_widths("5")
    assert len(m.group("northing")) != n_exp


@pytest.mark.unit
@pytest.mark.parametrize("lvl", ["0", "1", "2", "3"])
def test_pre_v027_geo_legacy_form_with_tile_letter_still_parses(lvl):
    """v0.28: L0-3 dropped the 'Gt<letter>' segment; a delivery produced
    before that must still parse so the letter can be checked."""
    base = "DGEDL%sGtA_27N056E_A_U_01" % lvl
    m = dv.GEO_RE.match(base)
    assert m and m.group("letter") == "A" and m.group("lv") == lvl


@pytest.mark.unit
def test_current_geo_short_form_reports_no_tile_letter():
    m = dv.GEO_RE.match("DGEDL2_27N056E_A_U_01")
    assert m and m.group("letter") is None


@pytest.mark.unit
@pytest.mark.parametrize("base", [
    "not_a_dged_tile",
    "DGEDL5GtD_5530N01212E_A_U_1",          # 1-digit product version
    "DGEDL5UtD_32N0500_400_A_U",            # truncated
    "DGEDL5GtD_5530N01212E_A_U_01_extra",   # trailing junk
    "DGEDLXUtD_32N0500_400_A_U_01",         # non-numeric level
    "DGEDL5UtD_32X0500_400_A_U_01",         # zone hemisphere letter
])
def test_malformed_names_are_rejected(base):
    assert dv.GEO_RE.match(base) is None
    assert dv.UTM_RE.match(base) is None


# ==============================================================================
# A. file pairing -- v0.30 regression
# ==============================================================================

@pytest.mark.unit
def test_delivery_level_xml_is_not_flagged_as_missing_a_tif():
    """v0.30: TABLE_OF_CONTENTS.xml and <product>_COLLECTION.xml are
    delivery-level metadata (spec 12.1 / 6.6), never per-tile sidecars."""
    assert dv.is_product_level_xml("/x/" + dl.TOC_FILENAME)
    assert dv.is_product_level_xml("/x/table_of_contents.xml")
    assert dv.is_product_level_xml("/x/DGEDL5_COLLECTION.xml")
    assert dv.is_product_level_xml("/x/anything_collection.xml")
    assert not dv.is_product_level_xml("/x/DGEDL5GtD_5530N01212E_A_U_01.xml")


@pytest.mark.unit
def test_check_pairing_ignores_delivery_level_metadata(tmp_path):
    rep = dv.Report()
    tifs = [str(tmp_path / "DGEDL2_27N056E_A_U_01.tif")]
    xmls = [str(tmp_path / "DGEDL2_27N056E_A_U_01.xml"),
            str(tmp_path / dl.TOC_FILENAME),
            str(tmp_path / "DGEDL2_COLLECTION.xml")]
    dv.check_pairing(tifs, xmls, rep)
    assert rep.n_fail == 0


# ==============================================================================
# E. placeholder detection -- v0.31 regression
# ==============================================================================

@pytest.mark.unit
def test_template_prose_is_not_mistaken_for_an_unreplaced_placeholder():
    """v0.31: a bare '{{' substring search matched the template's own header
    comment ('Placeholders ({{...}}) are replaced per tile...') and failed
    every single tile."""
    prose = "<!-- Placeholders ({{...}}) are replaced per tile at conversion -->"
    assert not dv._has_unreplaced_placeholder(prose)


@pytest.mark.unit
def test_real_placeholders_are_still_detected():
    assert dv._has_unreplaced_placeholder("<gco:CharacterString>{{BASENAME}}</...>")
    assert dv._has_unreplaced_placeholder("{{ABS_HACC}}")


@pytest.mark.unit
def test_shipped_templates_contain_only_substitutable_placeholders(project_root):
    code_keys = {"BASENAME", "LEVEL", "GSD", "DATE", "EPSG", "ORG", "CLASS_WORD",
                 "WEST", "EAST", "SOUTH", "NORTH", "MINZ", "MAXZ", "MISSRATE",
                 "ABS_HACC", "ABS_VACC", "LINEAGE", "DTYPE"}
    for tpl in ("DGED_GEO_TEMPLATE.xml", "DGED_UTM_TEMPLATE.xml"):
        txt = open(os.path.join(project_root, tpl), encoding="utf-8").read()
        keys = set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", txt))
        assert keys, "%s has no placeholders at all" % tpl
        assert not (keys - code_keys), \
            "%s: placeholders never substituted: %s" % (tpl, sorted(keys - code_keys))


# ==============================================================================
# D. origin tolerance -- v0.31 regression
# ==============================================================================

@pytest.mark.unit
def test_origin_check_accepts_a_correct_half_post_expanded_tile():
    """v0.31: comparing the RAW CORNER to the origin with a half-pixel
    tolerance sat exactly on the designed gap and failed every correct tile.
    The PIXEL CENTER is what must land on the origin."""
    res = 0.06 / 3600.0
    assert dv._origin_close(55.5, 55.5, res)
    assert dv._origin_close(55.5 + res * 1e-9, 55.5, res)


@pytest.mark.unit
def test_origin_check_still_catches_a_real_half_pixel_shift():
    res = 0.06 / 3600.0
    assert not dv._origin_close(55.5 + res / 2.0, 55.5, res)
    assert not dv._origin_close(55.5 + res, 55.5, res)


# ==============================================================================
# Shared PASS/WARN/FAIL rule -- v0.37 Finding 4
# ==============================================================================

@pytest.mark.unit
@pytest.mark.parametrize("counts,expected", [
    ((10, 0, 0), "PASS"),
    ((0, 0, 0), "PASS"),
    ((10, 1, 0), "WARN"),
    ((10, 0, 1), "FAIL"),
    ((10, 5, 5), "FAIL"),
])
def test_overall_result_is_three_tier(counts, expected):
    assert dv.overall_result(*counts) == expected


@pytest.mark.unit
def test_report_tile_overall_takes_the_worst_category():
    rep = dv.Report()
    rep.ok("x", tile="T", cat="filename")
    rep.warn("y", tile="T", cat="gsd")
    assert rep.tile_overall("T") == "WARN"
    rep.fail("z", tile="T", cat="bounds")
    assert rep.tile_overall("T") == "FAIL"
    # A later PASS must not downgrade an already-recorded FAIL.
    rep.ok("w", tile="T", cat="bounds")
    assert rep.tile_overall("T") == "FAIL"
    assert rep.tile_overall("nope") is None


@pytest.mark.unit
def test_report_emit_survives_an_unencodable_console(monkeypatch, capsys):
    """v0.38: box-drawing section headers raised UnicodeEncodeError on a
    cp1252 console, which propagated up and silently skipped BOTH report
    files even though validation had already finished."""
    rep = dv.Report()

    real_print = print
    calls = {"n": 0}

    def exploding_print(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise UnicodeEncodeError("charmap", "x", 0, 1, "boom")
        return real_print(*args, **kwargs)

    monkeypatch.setattr("builtins.print", exploding_print)
    rep.section("A. File pairing")          # must not raise
    monkeypatch.undo()
    assert rep.lines, "the report content itself must never be lost"


# ==============================================================================
# CLI surface
# ==============================================================================

@pytest.mark.unit
@pytest.mark.parametrize("flag", ["-html-report", "--html-report",
                                  "-max-diff", "--max-diff",
                                  "-report", "--report",
                                  "-src", "--src",
                                  "-resample", "--resample"])
def test_every_option_accepts_both_dash_spellings(flag):
    """v0.34: '--html-report' was documented but argparse rejected it."""
    parser = dv.build_parser()
    value = "bilinear" if "resample" in flag else ("1.0" if "max-diff" in flag else "x")
    args = parser.parse_args(["somefolder", flag, value])
    assert args is not None


@pytest.mark.unit
def test_verbose_flag_parses_both_spellings():
    parser = dv.build_parser()
    assert parser.parse_args(["f", "-verbose"]).verbose is True
    assert parser.parse_args(["f", "--verbose"]).verbose is True


# ==============================================================================
# End-to-end
# ==============================================================================

HAVE_GDALWARP = shutil.which("gdalwarp") is not None


@pytest.mark.integration
@pytest.mark.skipif(not HAVE_GDALWARP, reason="gdalwarp not on PATH")
def test_a_real_conversion_validates_clean(geo_dem, output_dir):
    import dem2dged_geo as geo

    # main() takes a raw argv list (it does parse_args(args[1:]) itself).
    resamp = geo.main(["dem2dged_geo.py", geo_dem, output_dir,
                       "-product_level", "5"])
    rep, tiles = dv.run_validation(output_dir, src=geo_dem, max_diff=5.0,
                                   resample=resamp)
    assert tiles, "the validator parsed no tiles from a real conversion"
    assert rep.n_fail == 0, (
        "a correctly generated delivery FAILED validation:\n"
        + "\n".join(l for l in rep.lines if "FAIL" in l))
    assert dv.overall_result(rep.n_pass, rep.n_warn, rep.n_fail) in ("PASS", "WARN")


@pytest.mark.integration
@pytest.mark.skipif(not HAVE_GDALWARP, reason="gdalwarp not on PATH")
def test_reports_are_written(geo_dem, output_dir, tmp_path):
    import dem2dged_geo as geo

    geo.main(["dem2dged_geo.py", geo_dem, output_dir, "-product_level", "5"])
    rep, _tiles = dv.run_validation(output_dir)

    txt = tmp_path / "report.txt"
    assert dv.write_text_report(rep, str(txt))
    assert txt.read_text(encoding="utf-8").strip()

    html = tmp_path / "report.html"
    dataset = {"name": os.path.basename(output_dir), "src": geo_dem,
               "rep": rep, "tiles": _tiles}
    assert dv.write_html_report([dataset], str(html), tool_version=dl.VERSION)
    body = html.read_text(encoding="utf-8")
    assert "<html" in body.lower()
    assert dl.VERSION in body


@pytest.mark.integration
@pytest.mark.skipif(not HAVE_GDALWARP, reason="gdalwarp not on PATH")
def test_an_empty_folder_fails_cleanly(output_dir):
    rep, tiles = dv.run_validation(output_dir)
    assert tiles == []
    assert rep.n_fail >= 1
    assert dv.overall_result(rep.n_pass, rep.n_warn, rep.n_fail) == "FAIL"


@pytest.mark.integration
@pytest.mark.skipif(not HAVE_GDALWARP, reason="gdalwarp not on PATH")
def test_a_corrupt_tile_is_reported_not_crashed(geo_dem, output_dir):
    """A truncated/garbage .tif must produce a FAIL line, never a traceback."""
    import dem2dged_geo as geo

    geo.main(["dem2dged_geo.py", geo_dem, output_dir, "-product_level", "5"])
    victim = sorted(glob.glob(os.path.join(output_dir, "*.tif")))[0]
    with open(victim, "wb") as f:
        f.write(b"this is not a GeoTIFF")
    rep, _tiles = dv.run_validation(output_dir)
    assert rep.n_fail >= 1
