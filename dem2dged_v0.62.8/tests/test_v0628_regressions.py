# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.8
"""v0.62.8: vertical-datum detection (Detect button next to Source vertical).

A conversion is held when the source has no vertical reference. dem2dged_datum
collects evidence for the datum (embedded CRS, metadata tags, files next to the
DEM, provider file-name conventions) and the GUI pre-fills the box only after
the operator presses Use. These tests are offline.
"""

import inspect
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import dem2dged_datum as dd  # noqa: E402


def _touch(path, text="x"):
    with open(str(path), "w", encoding="utf-8") as stream:
        stream.write(text)
    return str(path)


def _kinds(result):
    return {(e["kind"], e["datum_key"], e["confidence"]) for e in result["evidence"]}


# ---------------------------------------------------------------------------
# text scanning
# ---------------------------------------------------------------------------

def test_scan_text_finds_names_and_epsg_codes():
    assert "CGVD2013" in dd.scan_text("Vertical datum: CGVD 2013 (CGG2013a)")
    assert "CGVD28" in dd.scan_text("heights are CGVD1928")
    assert "EGM2008" in dd.scan_text("referenced to EGM-2008")
    assert "NAVD88" in dd.scan_text("NAVD 88 orthometric")
    assert "CGVD2013" in dd.scan_text('AUTHORITY["EPSG","6647"]')
    assert dd.scan_text("nothing about heights here") == {}


def test_cgvd2013_text_is_not_mistaken_for_cgvd28():
    hits = dd.scan_text("CGVD2013")
    assert "CGVD2013" in hits and "CGVD28" not in hits


# ---------------------------------------------------------------------------
# evidence from file name and side files (no GDAL needed)
# ---------------------------------------------------------------------------

def test_hrdem_file_name_gives_a_medium_suggestion(tmp_path):
    path = _touch(tmp_path / "dtm_2m_utm17_w_5_100.tif")
    result = dd.detect_vertical_datum(path)
    assert result["status"] == "found"
    assert result["suggestion"]["epsg"] == "6647"
    assert result["suggestion"]["confidence"] == "medium"
    assert ("filename_convention", "CGVD2013", "medium") in _kinds(result)


def test_3dep_file_name_gives_navd88(tmp_path):
    path = _touch(tmp_path / "USGS_1M_18_x32y432_VA_Example_2019.tif")
    result = dd.detect_vertical_datum(path)
    assert result["status"] == "found"
    assert result["suggestion"]["datum_key"] == "NAVD88"


def test_same_stem_side_file_is_medium(tmp_path):
    path = _touch(tmp_path / "ontario_tile.tif")
    _touch(tmp_path / "ontario_tile.xml", "<m><vertical>Vertical datum CGVD28</vertical></m>")
    result = dd.detect_vertical_datum(path)
    assert result["status"] == "found"
    assert result["suggestion"]["epsg"] == "5713"
    assert ("sidecar_file", "CGVD28", "medium") in _kinds(result)


def test_readme_in_same_folder_counts_when_it_talks_about_the_datum(tmp_path):
    path = _touch(tmp_path / "tile_a.tif")
    _touch(tmp_path / "README.txt", "Product notes\nVertical datum: CGVD2013\n")
    result = dd.detect_vertical_datum(path)
    assert result["suggestion"]["epsg"] == "6647"


def test_parent_folder_hint_is_only_weak_and_never_prefilled(tmp_path):
    sub = tmp_path / "tiles"
    sub.mkdir()
    path = _touch(sub / "tile_a.tif")
    _touch(tmp_path / "readme.txt", "Vertical datum: CGVD2013")
    result = dd.detect_vertical_datum(path)
    assert result["status"] == "weak"
    assert result["suggestion"] is None
    assert any(e["confidence"] == "low" for e in result["evidence"])


def test_a_file_that_names_several_datums_is_not_trusted(tmp_path):
    path = _touch(tmp_path / "tile_a.tif")
    _touch(tmp_path / "tile_a.txt", "converted from CGVD28 to CGVD2013 in 2018")
    result = dd.detect_vertical_datum(path)
    assert result["suggestion"] is None
    assert {e["confidence"] for e in result["evidence"]} == {"low"}


def test_conflicting_evidence_is_reported_and_nothing_is_prefilled(tmp_path):
    path = _touch(tmp_path / "dtm_2m_utm17_w_5_100.tif")           # HRDEM name -> CGVD2013
    _touch(tmp_path / "dtm_2m_utm17_w_5_100.txt", "Vertical datum CGVD28")
    result = dd.detect_vertical_datum(path)
    assert result["status"] == "conflict"
    assert result["suggestion"] is None
    assert any("disagrees" in n for n in result["notes"])


def test_no_evidence_gives_none(tmp_path):
    result = dd.detect_vertical_datum(_touch(tmp_path / "plain_name.tif"))
    assert result["status"] == "none"
    assert result["suggestion"] is None
    assert any("provider's documentation" in n for n in result["notes"])


def test_missing_file_never_raises(tmp_path):
    result = dd.detect_vertical_datum(str(tmp_path / "does_not_exist.tif"))
    assert result["status"] in ("none", "weak")


def test_pdf_next_to_the_data_is_reported_not_searched(tmp_path):
    path = _touch(tmp_path / "plain_name.tif")
    _touch(tmp_path / "spec.pdf", "CGVD2013")
    result = dd.detect_vertical_datum(path)
    assert result["suggestion"] is None
    assert any("PDF" in n for n in result["notes"])


# ---------------------------------------------------------------------------
# combining several files, report, command line
# ---------------------------------------------------------------------------

def test_combine_needs_every_file_to_agree(tmp_path):
    a = dd.detect_vertical_datum(_touch(tmp_path / "dtm_2m_utm17_w_5_100.tif"))
    b = dd.detect_vertical_datum(_touch(tmp_path / "dtm_2m_utm17_w_5_101.tif"))
    c = dd.detect_vertical_datum(_touch(tmp_path / "plain_name.tif"))
    assert dd.combine([a, b])["status"] == "found"
    assert dd.combine([a, b])["suggestion"]["epsg"] == "6647"
    partial = dd.combine([a, c])
    assert partial["status"] == "partial" and partial["suggestion"] is None
    assert dd.combine([])["status"] == "none"


def test_combine_flags_different_datums(tmp_path):
    a = dd.detect_vertical_datum(_touch(tmp_path / "dtm_2m_utm17_w_5_100.tif"))       # CGVD2013
    b = dd.detect_vertical_datum(_touch(tmp_path / "USGS_1M_18_x32y432_VA_X_2019.tif"))  # NAVD88
    combined = dd.combine([a, b])
    assert combined["status"] == "conflict" and combined["suggestion"] is None


def test_report_tells_the_operator_to_confirm(tmp_path):
    result = dd.detect_vertical_datum(_touch(tmp_path / "dtm_2m_utm17_w_5_100.tif"))
    report = dd.format_report([result])
    assert "SUGGESTION: EPSG:6647" in report
    assert "not a verification" in report
    none = dd.format_report([dd.detect_vertical_datum(_touch(tmp_path / "plain_name.tif"))])
    assert "NO DATUM WAS PRE-FILLED" in none and "6647" in none


def test_command_line_json_and_exit_codes(tmp_path, capsys):
    good = _touch(tmp_path / "dtm_2m_utm17_w_5_100.tif")
    assert dd.main([good, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["combined"]["suggestion"]["epsg"] == "6647"
    assert dd.main([_touch(tmp_path / "plain_name.tif")]) == 2


def test_module_version_matches_the_release():
    import dem2dged_lib
    assert dd.VERSION == dem2dged_lib.VERSION


# ---------------------------------------------------------------------------
# evidence inside the raster (needs GDAL)
# ---------------------------------------------------------------------------

gdal = pytest.importorskip("osgeo.gdal")
from osgeo import osr  # noqa: E402


def _tif(path, wkt=None, metadata=None, cells=16):
    ds = gdal.GetDriverByName("GTiff").Create(str(path), cells, cells, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((500000.0, 2.0, 0, 5000000.0, 0, -2.0))
    if wkt is None:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(32617)
        wkt = srs.ExportToWkt()
    ds.SetProjection(wkt)
    for key, value in (metadata or {}).items():
        ds.SetMetadataItem(key, value)
    ds.GetRasterBand(1).WriteArray(np.zeros((cells, cells), dtype="float32"))
    ds.FlushCache()
    ds = None
    return str(path)


def test_embedded_vertical_crs_is_high_reliability(tmp_path):
    srs = osr.SpatialReference()
    try:
        srs.SetFromUserInput("EPSG:32617+6647")
    except Exception:
        pytest.skip("this PROJ database cannot build EPSG:32617+6647")
    path = _tif(tmp_path / "with_vertical.tif", wkt=srs.ExportToWkt())
    result = dd.detect_vertical_datum(path)
    assert ("embedded_crs", "CGVD2013", "high") in _kinds(result)
    assert result["suggestion"]["epsg"] == "6647"
    assert result["suggestion"]["confidence"] == "high"


def test_datum_in_a_metadata_tag_is_high_reliability(tmp_path):
    path = _tif(tmp_path / "tagged.tif", metadata={"VERTICAL_DATUM": "CGVD28"})
    result = dd.detect_vertical_datum(path)
    assert ("gdal_metadata", "CGVD28", "high") in _kinds(result)
    assert result["suggestion"]["epsg"] == "5713"


def test_plain_raster_without_any_hint_finds_nothing(tmp_path):
    result = dd.detect_vertical_datum(_tif(tmp_path / "plain_name.tif"))
    assert result["status"] == "none"


def test_embedded_and_file_name_evidence_can_conflict(tmp_path):
    path = _tif(tmp_path / "dtm_2m_utm17_w_5_100.tif", metadata={"VERTICAL_DATUM": "CGVD28"})
    result = dd.detect_vertical_datum(path)
    assert result["status"] == "conflict"
    assert result["suggestion"] is None


# ---------------------------------------------------------------------------
# GUI wiring and packaging lists
# ---------------------------------------------------------------------------

@pytest.fixture()
def gui():
    pytest.importorskip("tkinter")
    import dem2dged_gui
    return dem2dged_gui


def test_gui_has_the_detect_button_and_records_the_declaration(gui):
    build = inspect.getsource(gui.App._build_ui)
    assert '"Detect"' in build and "_detect_vertical_datum" in build
    detect = inspect.getsource(gui.App._detect_vertical_datum)
    assert "Use EPSG" in detect and "operator_confirmed" in detect
    assert "dd.combine" in detect and "dd.format_report" in detect
    assert "vertical_declaration" in inspect.getsource(gui.App._start)


def test_held_conversion_messages_point_at_detect(gui):
    text = inspect.getsource(gui.App)
    assert "Detect suggests the datum" in text
    assert "click Detect next to Source vertical" in text


@pytest.mark.parametrize("name", ["dem2dged.spec", "BUILD_AND_PACKAGE.py",
                                  "BUILD_V0.62.0.py", "RELEASE_AUDIT_V0.62.0.py"])
def test_packaging_files_know_the_new_module(name):
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as stream:
        assert "dem2dged_datum" in stream.read()
