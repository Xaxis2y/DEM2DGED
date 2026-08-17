# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.49
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Unit tests for dem2dged_validate.py.

The validator is the thing that says whether a delivery is spec-conformant,
so a silent defect in it is worse than a defect in the converters: it turns
into a signed-off delivery that is wrong. Most of this file is therefore
named regression guards for specific past validator bugs, plus an exhaustive
round-trip of the two filename patterns, which are the only place where the
converter's idea of a correct name and the validator's idea of one could
drift apart.

No gdalwarp needed. The only GDAL used is raster creation for the two
"corrupt input must not kill the run" tests.
"""

import pytest

import dem2dged_lib as dl
import dem2dged_validate as dv
from conftest import requires_gdal

ALL_GEO_LEVELS = [row[0] for row in dl.level_tilesize_and_spatial_resolution]
ALL_UTM_LEVELS = [row[0] for row in dl.PL]


# =============================================================================
# v0.41 finding 1: the module must expose everything its callers import
# =============================================================================

def test_the_validator_module_is_complete():
    """v0.41's BLOCKER was that this file did not byte-compile at all -- an
    entire block was missing between the docstring and overall_result(), so
    every import of it failed and every caller degraded silently. Each name
    below is imported by dem2dged.py, dem2dged_gui.py or audit_pure.py; if
    any goes missing again, this fails immediately and loudly instead of
    turning into "skipping auto-validation" in the middle of a successful
    conversion."""
    for name in ("NODATA", "ELEV_MIN_SANE", "ELEV_MAX_SANE", "GEO_RE",
                 "UTM_RE", "overall_result", "run_validation",
                 "write_text_report", "write_html_report",
                 "render_html_report", "check_tile", "check_edges",
                 "check_source", "check_pairing", "find_tiles",
                 "build_parser", "main", "Report", "TILE_CHECK_CATEGORIES"):
        assert hasattr(dv, name), "dem2dged_validate is missing %s" % name


def test_the_validator_reports_the_library_version():
    assert dv.VERSION == dl.VERSION


def test_nodata_matches_what_the_converters_write():
    assert dv.NODATA == -32767


def test_the_sane_elevation_band_brackets_the_real_extremes():
    """This check exists to catch the -32767 NoData marker leaking into
    valid data, NOT to police unusual terrain -- so the band must contain
    the Dead Sea shore and Everest, and stay far above NODATA."""
    assert dv.ELEV_MIN_SANE < -430.0        # Dead Sea shore
    assert dv.ELEV_MAX_SANE > 8849.0        # Everest
    assert dv.ELEV_MIN_SANE > dv.NODATA + 1000


# =============================================================================
# overall_result -- v0.37 Finding 4
# =============================================================================

@pytest.mark.parametrize("p,w,f,expect", [
    (10, 0, 0, "PASS"),
    (10, 3, 0, "WARN"),
    (10, 0, 1, "FAIL"),
    (10, 3, 1, "FAIL"),
    (0, 0, 0, "PASS"),
    (0, 1, 0, "WARN"),
    (0, 0, 5, "FAIL"),
])
def test_overall_result_is_one_three_tier_rule(p, w, f, expect):
    """v0.37 Finding 4: the text report used a 2-tier PASS/FAIL rule that
    ignored warnings, while the HTML badge and the GUI badge used a 3-tier
    one -- so identical counts read "PASS" in one report and "WARN" in
    another for the same run. One shared function now, so they cannot drift
    apart again."""
    assert dv.overall_result(p, w, f) == expect


def test_a_warning_alone_is_not_a_failing_exit_code():
    """WARN must not become FAIL: the CLI exits 1 only on a real FAIL."""
    assert dv.overall_result(5, 2, 0) == "WARN"


# =============================================================================
# Filename patterns -- exhaustive round-trip against the converter's own
# name builders. This is the pair most able to silently disagree.
# =============================================================================

GEO_ORIGINS = [
    (55.5, 12.2), (0.0, 0.0), (-33.75, -58.5), (1.0, -1.0),
    (78.0, 15.0), (-78.0, 15.0), (55.0, 0.0), (5.0, 7.0),
]


@pytest.mark.parametrize("level", ALL_GEO_LEVELS)
@pytest.mark.parametrize("org", ["", "DNK"])
def test_every_geo_name_the_converter_builds_parses_back(level, org):
    letter = [r[3] for r in dl.level_tilesize_and_spatial_resolution
              if r[0] == level][0]
    tiledim = [r[1] for r in dl.level_tilesize_and_spatial_resolution
               if r[0] == level][0] / 60.0
    for lat, lon in GEO_ORIGINS:
        # snap the origin onto this level's tile grid, the way the
        # converter's tile loop does
        t_lat = round(lat / tiledim) * tiledim
        t_lon = round(lon / tiledim) * tiledim
        name = dl.geo_tile_basename(level, letter, t_lat, t_lon,
                                    "A", "U", "01", org=org)
        m = dv.GEO_RE.match(name)
        assert m, "GEO_RE does not match %s" % name
        assert m.group("lv") == level
        assert (m.group("org") or "") == org
        assert m.group("src") == "A" and m.group("cls") == "U"
        assert m.group("ver") == "01"


@pytest.mark.parametrize("level", ALL_UTM_LEVELS)
@pytest.mark.parametrize("zone", ["32N", "09S", "01N", "60S"])
def test_every_utm_name_the_converter_builds_parses_back(level, zone):
    gsd, posts, letter = [r[1:] for r in dl.PL if r[0] == level][0]
    tiledim = (posts - 1) * gsd
    for northing in (0.0, tiledim, 5000000.0, 9990000.0):
        name = dl.utm_tile_basename(level, letter, zone, northing, 500000.0,
                                    "A", "U", "01")
        m = dv.UTM_RE.match(name)
        assert m, "UTM_RE does not match %s" % name
        assert m.group("lv") == level
        assert m.group("zone") == zone
        n_width, e_width = dl.utm_name_field_widths(level)
        assert len(m.group("northing")) == n_width, name
        assert len(m.group("easting")) == e_width, name


def test_a_geo_name_never_matches_the_utm_pattern_and_vice_versa():
    geo = dl.geo_tile_basename("5", "D", 55.5, 12.2, "A", "U", "01")
    utm = dl.utm_tile_basename("5", "D", "32N", 500000.0, 400000.0,
                               "A", "U", "01")
    assert dv.GEO_RE.match(geo) and not dv.UTM_RE.match(geo)
    assert dv.UTM_RE.match(utm) and not dv.GEO_RE.match(utm)


def test_the_pre_v034_unpadded_utm_name_still_PARSES():
    """v0.34 requirement, and the reason the northing/easting subfields stay
    permissive in the pattern. An old, short name must parse so check_tile()
    can say "northing field '500' is 3 digits, spec 12.1 requires 4" rather
    than the opaque "does not match DGED naming convention"."""
    m = dv.UTM_RE.match("DGEDL5UtD_32N500_400_A_U_01")
    assert m and m.group("northing") == "500"
    assert len(m.group("northing")) != dl.utm_name_field_widths("5")[0]


def test_the_pre_v027_geo_legacy_form_still_parses():
    """Levels 0-3 used to carry the Gt<letter> segment. It stays optional in
    the pattern so an old delivery parses; check_tile() then enforces the
    right letter for the level, so a wrong one is still a FAIL."""
    assert dv.GEO_RE.match("DGEDL2GtA_27N056E_A_U_01")


@pytest.mark.parametrize("bad", [
    "DGEDL5GtD_5530N01212E_A_U_1",        # 1-digit version
    "DGEDL5GtD_5530X01212E_A_U_01",       # bad hemisphere letter
    "DGED5GtD_5530N01212E_A_U_01",        # missing the L
    "DGEDL5GtD_5530N01212E_A_U",          # truncated tail
    "random_file_name",
    "DGEDL5UtD_32N0500_400_A_U",          # UTM, truncated tail
])
def test_malformed_names_are_rejected_by_both_patterns(bad):
    assert not dv.GEO_RE.match(bad)
    assert not dv.UTM_RE.match(bad)


# =============================================================================
# Coordinate decoding
# =============================================================================

@pytest.mark.parametrize("digits,is_lat,expect", [
    ("27", True, 27.0),
    ("5530", True, 55.5),
    ("553000", True, 55.5),
    ("056", False, 56.0),
    ("01212", False, 12.2),
    ("0121200", False, 12.2),
])
def test_dms_to_deg(digits, is_lat, expect):
    assert dv.dms_to_deg(digits, is_lat) == pytest.approx(expect, abs=1e-9)


def test_the_validators_longitude_zone_lookup_matches_the_converters():
    """Two independent implementations of the same spec table -- if they
    ever disagree, tiles are validated against the wrong post spacing."""
    import dem2dged_geo as geo
    for lat in (-89.0, -85.0, -80.0, -70.0, -60.0, -50.0, -0.5, 0.0, 1.0,
                49.9, 50.0, 55.0, 60.0, 70.0, 80.0, 85.0, 89.0):
        assert dv.lon_multi(lat) == geo.resolve_lon_multiplication(lat), lat


@pytest.mark.parametrize("level", ALL_GEO_LEVELS)
def test_geo_level_params_come_from_the_shared_table(level):
    assert dv.geo_level_params(level) is not None


@pytest.mark.parametrize("level", ALL_UTM_LEVELS)
def test_utm_level_params_come_from_the_shared_table(level):
    assert dv.utm_level_params(level) is not None


def test_an_unknown_level_returns_nothing_rather_than_raising():
    assert dv.geo_level_params("99") is None
    assert dv.utm_level_params("99") is None


# =============================================================================
# v0.30 / v0.31 regressions
# =============================================================================

def test_delivery_level_xml_is_not_treated_as_a_missing_tile_sidecar(tmp_path):
    """v0.30: TABLE_OF_CONTENTS.xml and <product>_COLLECTION.xml are
    DELIVERY-level metadata, not per-tile sidecars, so pairing used to flag
    them as "missing .tif" on every delivery that included them."""
    toc = tmp_path / dl.TOC_FILENAME
    toc.write_text("<toc/>", encoding="utf-8")
    coll = tmp_path / "DGEDL5G_COLLECTION.xml"
    coll.write_text("<collection/>", encoding="utf-8")
    assert not dv.is_product_level_xml(str(tmp_path / "DGEDL5GtD_x.xml"))
    assert dv.is_product_level_xml(str(toc))
    assert dv.is_product_level_xml(str(coll))


def test_an_unreplaced_placeholder_is_detected():
    """v0.31: a sidecar that still contains {{SOMETHING}} was shipped as
    valid XML because it IS valid XML."""
    assert dv._has_unreplaced_placeholder("<a>{{BASENAME}}</a>")
    assert not dv._has_unreplaced_placeholder("<a>DGEDL5GtD_x</a>")


def test_pixel_centre_origin_tolerance():
    """v0.31: the tile origin is compared at the pixel CENTRE, so a tile
    whose georeferenced corner sits half a post outside the nominal origin
    is correct, not wrong."""
    res = 2.5e-5
    assert dv._origin_close(12.0, 12.0, res)
    # The tolerance is a TINY fraction of a pixel (res * 1e-6), not half a
    # pixel: comparing the raw corner with a half-pixel tolerance sits
    # exactly on the designed half-post gap and passes everything, which is
    # what made the original check useless.
    assert dv._origin_close(12.0 + res * 1e-9, 12.0, res)
    assert not dv._origin_close(12.0 + res * 0.1, 12.0, res)
    assert not dv._origin_close(12.0 + res * 0.5, 12.0, res)
    assert not dv._origin_close(12.0 + res * 5, 12.0, res)


# =============================================================================
# v0.34: both dash spellings
# =============================================================================

@pytest.mark.parametrize("flag", ["-html-report", "--html-report"])
def test_both_dash_spellings_are_accepted(flag):
    """v0.34: argparse treats "-html-report" and "--html-report" as two
    unrelated option strings and does NOT fall back from one to the other,
    so VALIDATOR_VERSION.txt's documented double-dash form was rejected
    outright while README.md's single-dash form worked."""
    args = dv.build_parser().parse_args(["folder", flag, "out.html"])
    assert args.html_report == "out.html"


@pytest.mark.parametrize("flag", ["-src", "--src", "-report", "--report",
                                  "-max-diff", "--max-diff",
                                  "-resample", "--resample"])
def test_every_option_has_both_spellings(flag):
    value = "2.5" if "max-diff" in flag else "x"
    args = dv.build_parser().parse_args(["folder", flag, value])
    assert args is not None


def test_resample_defaults_to_bilinear_for_a_standalone_run():
    """v0.37 Finding 2: an operator validating someone else's delivery does
    not know what it was made with, so the default has to stay the value
    every call site used unconditionally before the fix."""
    assert dv.build_parser().parse_args(["folder"]).resample == "bilinear"


# =============================================================================
# v0.38: the report must survive a console that cannot encode it
# =============================================================================

def test_emit_survives_an_unencodable_console(monkeypatch, capsys):
    """v0.38: Report._emit() print()ed every line, including box-drawing
    characters, to the real console. On Windows with stdout redirected to a
    file under cp1252 that raised UnicodeEncodeError, which propagated all
    the way up into dem2dged.py's auto-validation try/except and silently
    skipped BOTH report files -- even though validation itself had already
    finished successfully."""
    rep = dv.Report(verbose=True)

    class Cp1252Stdout:
        encoding = "cp1252"

        def write(self, s):
            s.encode("cp1252")      # raises on a box-drawing character
            return len(s)

        def flush(self):
            pass

    monkeypatch.setattr("sys.stdout", Cp1252Stdout())
    rep._emit("─" * 20 + " section ─")    # box drawing
    rep._emit("plain ascii line")
    # The report CONTENT is what matters and must be intact regardless.
    assert any("section" in line for line in rep.lines)
    assert "plain ascii line" in rep.lines


def test_write_text_report_reports_failure_instead_of_raising(tmp_path):
    rep = dv.Report()
    rep._emit("hello")
    ok = dv.write_text_report(rep, str(tmp_path / "no_such_dir" / "r.txt"))
    assert ok is False


def test_write_text_report_round_trips(tmp_path):
    rep = dv.Report()
    rep._emit("first")
    rep._emit("second")
    path = str(tmp_path / "report.txt")
    assert dv.write_text_report(rep, path) is True
    assert open(path, encoding="utf-8").read().splitlines() == \
        ["first", "second"]


# =============================================================================
# v0.41: a corrupt tile fails THAT tile, it does not kill the run
# =============================================================================

@requires_gdal
def test_a_corrupt_tile_is_reported_not_crashed(tmp_path):
    """v0.41 finding 4. check_tile() guarded gdal.Open() with try/except,
    but this module deliberately runs with GDAL exceptions OFF, so a
    truncated .tif returned None, fell straight through the except, and
    killed the whole validation run with an AttributeError on
    ds.GetGeoTransform()."""
    bad = tmp_path / "DGEDL5GtD_5530N01212E_A_U_01.tif"
    bad.write_bytes(b"this is not a GeoTIFF at all")
    rep = dv.Report()
    info = dv.check_tile(str(bad), rep, str(tmp_path))
    assert info is None
    assert rep.n_fail >= 1


@requires_gdal
def test_a_whole_folder_of_junk_still_produces_a_report(tmp_path):
    for i in range(3):
        p = tmp_path / ("DGEDL5GtD_553%dN01212E_A_U_01.tif" % i)
        p.write_bytes(b"junk")
        (tmp_path / p.name.replace(".tif", ".xml")).write_text(
            "<a/>", encoding="utf-8")
    rep, tiles = dv.run_validation(str(tmp_path))
    assert tiles == []
    assert rep.n_fail >= 3
    assert dv.overall_result(rep.n_pass, rep.n_warn, rep.n_fail) == "FAIL"


@requires_gdal
def test_an_unreadable_src_is_a_clean_fail_not_a_crash(tmp_path):
    """v0.41 finding 11: check_source() had the same unguarded-None crash
    as finding 4, so a bad -src aborted the run instead of reporting it."""
    rep = dv.Report()
    dv.check_source([], str(tmp_path / "not_a_raster.tif"), rep, 5.0)
    assert rep.n_fail >= 1


# =============================================================================
# Report plumbing
# =============================================================================

def test_report_counts_each_status_once():
    rep = dv.Report()
    rep.ok("fine")
    rep.ok("also fine")
    rep.warn("hmm")
    rep.fail("no")
    assert (rep.n_pass, rep.n_warn, rep.n_fail) == (2, 1, 1)


def test_the_worst_status_wins_for_a_tile_criterion():
    """The per-tile table shows one cell per criterion, so a PASS recorded
    after a FAIL must not overwrite it."""
    rep = dv.Report()
    rep._record("TILE", "filename", "PASS")
    rep._record("TILE", "filename", "FAIL")
    rep._record("TILE", "filename", "WARN")
    assert rep.tile_checks["TILE"]["filename"] == "FAIL"


def test_tile_order_is_first_seen_order():
    rep = dv.Report()
    for name in ("C", "A", "B"):
        rep._record(name, "gsd", "PASS")
    assert rep.tile_order == ["C", "A", "B"]


def test_every_declared_tile_category_is_a_two_tuple():
    for key, label in dv.TILE_CHECK_CATEGORIES:
        assert isinstance(key, str) and isinstance(label, str)


def test_html_report_renders_without_a_dataset():
    html = dv.render_html_report([])
    assert "<html" in html.lower()


def test_html_report_escapes_a_hostile_dataset_name():
    rep = dv.Report()
    rep.ok("fine")
    ds = {"name": "<script>alert(1)</script>", "src": None,
          "rep": rep, "tiles": []}
    html = dv.render_html_report([ds])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_find_tiles_returns_tifs_and_xmls_separately(tmp_path):
    (tmp_path / "a.tif").write_bytes(b"")
    (tmp_path / "a.xml").write_text("<a/>", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    tifs, xmls = dv.find_tiles(str(tmp_path))
    assert len(tifs) == 1 and len(xmls) == 1
    assert all(not t.endswith(".txt") for t in tifs)
