# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.10
"""v0.62.9: separate, cross-checked CGVD2013 -> EGM2008 vertical correction.

Measured cause (v0.62.8 diagnostics, PROJ 9.8.1): PROJ joins generic NAD83(CSRS)
to the CGVD2013 grid operations (defined for NAD83(CSRS)v6 / ITRF2008) with a
ballpark offset, which the strict guard refuses. The one ballpark route offers
+1.09 m where five independent routes agree on -0.022 m.

The first group of tests needs no GDAL. The second group builds real GeoTIFFs and
needs the DGED environment with PROJ network access ON (or the CGG2013 and EGM2008
grids installed), exactly like the converter itself.
"""

import json
import math
import os
import re
import sys
import threading

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import dem2dged_vertical as dvt  # noqa: E402


def _read(name):
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as stream:
        return stream.read()


# ---------------------------------------------------------------------------
# no GDAL needed
# ---------------------------------------------------------------------------

PROJ_ERROR = (
    'Cannot find coordinate operations from `{\n'
    '  "$schema": "https://proj.org/schemas/v0.7/projjson.schema.json",\n'
    '  "type": "CompoundCRS",\n'
    '  "name": "NAD83(CSRS) / UTM zone 18N + CGVD2013(CGG2013) height",\n'
    '  "components": [ {"type": "ProjectedCRS", "name": "NAD83(CSRS) / UTM zone 18N"},\n'
    '    {"type": "VerticalCRS", "name": "CGVD2013(CGG2013) height"} ]\n'
    "}' to `{\n"
    '  "$schema": "https://proj.org/schemas/v0.7/projjson.schema.json",\n'
    '  "type": "CompoundCRS",\n'
    '  "name": "NAD83(CSRS) / UTM zone 18N + EGM2008 height",\n'
    '  "components": [ {"type": "VerticalCRS", "name": "EGM2008 height"} ]\n'
    "}'")


def test_proj_error_is_reduced_to_the_two_crs_names():
    text = dvt.summarize_proj_error(PROJ_ERROR)
    assert "CGVD2013(CGG2013) height" in text and "EGM2008 height" in text
    assert "$schema" not in text and "components" not in text
    assert len(text) < 400


def test_other_errors_are_one_capped_line():
    text = dvt.summarize_proj_error("line one\n   line two " + "x" * 1000, limit=100)
    assert "\n" not in text and len(text) <= 103
    assert dvt.summarize_proj_error(None) == ""


def test_only_measured_datums_have_a_separate_route():
    assert set(dvt.SEPARATE_ROUTES) == {"6647"}
    route = dvt.SEPARATE_ROUTES["6647"]
    assert route["primary"]["epsg"] == "8999"                       # ITRF2008
    assert {c["epsg"] for c in route["cross_checks"]} >= {"10414", "8255"}
    assert route["primary"]["epsg"] not in {c["epsg"] for c in route["cross_checks"]}
    assert "8252" not in {c["epsg"] for c in route["cross_checks"]}  # v6 is the +1.09 m outlier
    assert dvt.TOLERANCE_M <= 0.02


def test_bilinear_interpolation_reproduces_a_plane():
    width, height, nx, ny = 1000, 600, 5, 4
    cols = np.linspace(0.0, width, nx)
    rows = np.linspace(0.0, height, ny)
    plane = lambda c, r: 0.5 + 0.0002 * c - 0.0003 * r      # noqa: E731
    grid = np.array([[plane(c, r) for c in cols] for r in rows])
    col_low, col_w = dvt._interp_axes(width, nx)
    row_low, row_w = dvt._interp_axes(height, ny)
    table = dvt._column_table(grid, col_low, col_w)
    fast = dvt._shift_for_rows(grid, table, col_low, col_w, row_low, row_w, 100, 140)
    slow = dvt._shift_for_rows(grid, None, col_low, col_w, row_low, row_w, 100, 140)
    expected = np.array([[plane(c + 0.5, r + 0.5) for c in range(width)] for r in range(100, 140)])
    assert fast.dtype == np.float32
    assert np.allclose(fast, expected, atol=2e-5)
    assert np.allclose(slow, expected, atol=2e-5)


def test_interpolation_axes_stay_inside_the_node_grid():
    for size, nodes in ((10, 2), (1000, 5), (12000, 25), (3, 400)):
        low, weight = dvt._interp_axes(size, nodes)
        assert low.min() >= 0 and low.max() <= nodes - 2
        assert weight.min() >= 0.0 and weight.max() <= 1.0 + 1e-12


@pytest.mark.parametrize("declared", [None, "", "3855", "EPSG:3855"])
def test_no_vertical_or_egm2008_is_left_alone(declared):
    plan = dvt.prepare_vertical_source("does_not_matter.tif", declared)
    assert plan["mode"] == "none" and plan["source"] == "does_not_matter.tif"
    assert plan["temp_dir"] is None


def test_unsupported_datum_or_target_has_no_separate_route(tmp_path):
    for datum, target in (("5713", "3855"), ("5703", "3855"), ("6647", "5773")):
        record = dvt.create_corrected_source(str(tmp_path / "a.tif"), datum,
                                             str(tmp_path / "b.tif"), target_vertical_epsg=target)
        assert record["status"] == "FAIL"
        assert "no verified separate route" in record["reason"]
        assert not (tmp_path / "b.tif").exists()


def test_correction_never_writes_over_the_source(tmp_path):
    path = tmp_path / "dem.tif"
    path.write_bytes(b"not a real raster")
    record = dvt.create_corrected_source(str(path), "6647", str(path))
    assert record["status"] == "FAIL" and "over the source" in record["reason"]
    assert path.read_bytes() == b"not a real raster"


def test_cleanup_removes_the_temporary_folder(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "x.tif").write_bytes(b"x")
    plan = {"temp_dir": str(folder)}
    dvt.cleanup(plan)
    assert not folder.exists() and plan["temp_dir"] is None
    dvt.cleanup(plan)
    dvt.cleanup(None)


def test_route_manifest_is_json_safe():
    plan = {"mode": "separate", "vertical": "3855",
            "check": {"status": "FAIL", "reason": "short", "source_vertical_epsg": "6647"},
            "correction": {"status": "PASS", "source_vertical_epsg": "6647",
                           "reason_full": "long text", "cross_check_max_difference_m": 0.0001,
                           "direct_check_reason": "short"}}
    manifest = dvt.route_manifest(plan)
    json.dumps(manifest)
    assert manifest["mode"] == "separate"
    assert manifest["effective_vertical_epsg_for_conversion"] == "3855"
    assert manifest["declared_source_vertical_epsg"] == "6647"
    assert "reason_full" not in manifest["separate_correction"]


def test_module_version_matches_the_release():
    lib = _read("dem2dged_lib.py")
    declared = re.search(r'^VERSION\s*=\s*"([^"]+)"', lib, re.M).group(1)
    assert dvt.VERSION == declared


def test_gui_prepares_the_route_once_per_file_and_converts_the_right_copy():
    text = _read("dem2dged_gui.py")
    assert "dvt.prepare_vertical_source(" in text
    assert 'vertical_plan["mode"] == "failed"' in text
    assert "resamp_used = convert_geo(conv_src," in text
    assert "resamp_used = convert_utm(conv_src," in text
    assert len(re.findall(r"source_vertical=conv_vert,", text)) == 2
    assert "dvt.route_manifest(" in text and "dvt.cleanup(vertical_plan)" in text
    # the declared datum, not the temporary copy, is what the manifest records
    assert '"source_vertical_epsg": src_vert,' in text


def test_command_line_uses_the_same_route():
    text = _read("dem2dged.py")
    assert "dvt.prepare_vertical_source(" in text
    assert "conv_input," in text and 'sub_args += ["-source_vertical", conv_vert]' in text
    assert 'vertical_plan["mode"] in ("failed", "stopped")' in text


def test_terrain_check_keeps_the_full_text_but_reports_a_short_reason():
    text = _read("dem2dged_terrain.py")
    assert "summarize_proj_error" in text and '"reason_full": str(exc)' in text


@pytest.mark.parametrize("name", ["dem2dged.spec", "BUILD_AND_PACKAGE.py", "BUILD_V0.62.0.py",
                                  "RELEASE_AUDIT_V0.62.0.py", "BUMP_VERSION.py"])
def test_packaging_files_know_the_new_module(name):
    assert "dem2dged_vertical" in _read(name)


# ---------------------------------------------------------------------------
# real rasters (DGED environment; PROJ network ON or grids installed)
# ---------------------------------------------------------------------------

try:
    from osgeo import gdal, osr
    import dem2dged_terrain as dt
    HAVE_GDAL = True
except Exception:                       # no GDAL: the tests above still run
    gdal = osr = dt = None
    HAVE_GDAL = False

needs_gdal = pytest.mark.skipif(not HAVE_GDAL, reason="GDAL (osgeo) is not installed")

NODATA = -32767.0


def _tile(path, point_registered=False, size=64, wkt=None):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2959)                      # NAD83(CSRS) / UTM zone 18N, generic realisation
    ds = gdal.GetDriverByName("GTiff").Create(str(path), size, size, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((450000.0, 2.0, 0, 4950000.0, 0, -2.0))
    ds.SetProjection(wkt or srs.ExportToWkt())
    if point_registered:
        ds.SetMetadataItem("AREA_OR_POINT", "Point")
    data = (100.0 + np.add.outer(np.arange(size), np.arange(size)) * 0.1).astype("float32")
    data[5:9, 10:14] = NODATA
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(NODATA)
    band.WriteArray(data)
    ds.FlushCache()
    ds = None
    return str(path), data


def _must_pass(record):
    assert record["status"] == "PASS", (
        "the correction could not be built in this environment: %s" % record.get("reason"))


@pytest.mark.parametrize("point_registered", [False, True])
@needs_gdal
def test_correction_matches_the_independent_routes_and_keeps_the_grid(tmp_path, point_registered):
    src, data = _tile(tmp_path / "dtm_2m_utm18_w_2_47.tif", point_registered)
    out = str(tmp_path / "out" / "dtm_2m_utm18_w_2_47.tif")
    record = dvt.create_corrected_source(src, "6647", out)
    _must_pass(record)
    assert record["cross_check_max_difference_m"] <= dvt.TOLERANCE_M
    assert record["primary_context"]["epsg"] == "8999"
    # measured near Ottawa: -0.022 m; the v6 ballpark route would give about +1.09 m
    assert abs(record["shift_mean_m"]) < 0.1

    a, b = gdal.Open(src), gdal.Open(out)
    assert (a.RasterXSize, a.RasterYSize) == (b.RasterXSize, b.RasterYSize)
    assert a.GetGeoTransform() == pytest.approx(b.GetGeoTransform(), abs=1e-9)
    assert a.GetMetadataItem("AREA_OR_POINT") == b.GetMetadataItem("AREA_OR_POINT")
    assert osr.SpatialReference(wkt=a.GetProjection()).IsSame(osr.SpatialReference(wkt=b.GetProjection()))
    assert b.GetRasterBand(1).GetNoDataValue() == NODATA
    result = b.GetRasterBand(1).ReadAsArray()
    void = data == NODATA
    assert np.array_equal(result == NODATA, void)                  # NoData stays NoData
    diff = result[~void] - data[~void]
    assert np.all(np.abs(diff) < 0.1)
    assert diff.max() - diff.min() < 0.01                         # smooth over a 128 m tile
    assert "EPSG:6647" in (b.GetMetadataItem("DEM2DGED_VERTICAL_CORRECTION") or "")


@needs_gdal
def test_vertical_crs_is_not_left_in_the_corrected_copy(tmp_path):
    srs = osr.SpatialReference()
    try:
        srs.SetFromUserInput("EPSG:2959+6647")
    except Exception:
        pytest.skip("this PROJ database cannot build EPSG:2959+6647")
    src, _ = _tile(tmp_path / "with_vertical.tif", wkt=srs.ExportToWkt())
    out = str(tmp_path / "o" / "with_vertical.tif")
    _must_pass(dvt.create_corrected_source(src, "6647", out))
    corrected = osr.SpatialReference(wkt=gdal.Open(out).GetProjection())
    assert not corrected.IsCompound()


@needs_gdal
def test_stopping_removes_the_partial_copy(tmp_path):
    src, _ = _tile(tmp_path / "a.tif")
    out = str(tmp_path / "o" / "a.tif")
    stop = threading.Event()
    stop.set()
    record = dvt.create_corrected_source(src, "6647", out, stop_event=stop)
    assert record["status"] in ("STOPPED", "FAIL")
    assert not os.path.exists(out)


@needs_gdal
def test_prepare_uses_direct_or_separate_and_records_the_route(tmp_path):
    src, _ = _tile(tmp_path / "dtm.tif")
    records = tmp_path / "records"
    plan = dvt.prepare_vertical_source(src, "6647", record_dir=str(records))
    try:
        assert plan["mode"] in ("direct", "separate"), plan.get("reason")
        assert (records / "vertical_operation_check.json").is_file()
        if plan["mode"] == "separate":
            assert plan["vertical"] == "3855"
            assert os.path.basename(plan["source"]) == "dtm.tif"      # name kept for the metadata
            assert os.path.dirname(plan["source"]) != str(tmp_path)   # never beside the source
            assert (records / "vertical_correction.json").is_file()
            saved = json.loads((records / "vertical_correction.json").read_text(encoding="utf-8"))
            assert saved["status"] == "PASS" and saved["horizontal_georeferencing_changed"] is False
            json.dumps(dvt.route_manifest(plan))
        else:
            assert plan["source"] == src and plan["vertical"] == "6647"
    finally:
        dvt.cleanup(plan)
    if plan["mode"] == "separate":
        assert not os.path.exists(os.path.dirname(plan["source"]))


@pytest.mark.parametrize("datum", ["5713", "5703"])
@needs_gdal
def test_other_datums_never_take_the_separate_route(tmp_path, datum):
    src, _ = _tile(tmp_path / "dtm.tif")
    plan = dvt.prepare_vertical_source(src, datum, record_dir=str(tmp_path / "r"))
    try:
        assert plan["mode"] != "separate"
        if plan["mode"] == "failed":
            assert len(plan["reason"]) < 600 and "$schema" not in plan["reason"]
    finally:
        dvt.cleanup(plan)


@needs_gdal
def test_failed_strict_check_has_a_short_reason_and_keeps_the_full_text(tmp_path):
    src, _ = _tile(tmp_path / "dtm.tif")
    info = dt.inspect_source(src)
    check = dt.check_vertical_operation(info.horizontal_crs, "6647", extent=info.extent)
    if check["status"] == "PASS":
        pytest.skip("this PROJ build already has a strict CGVD2013 chain for EPSG:2959")
    assert len(check["reason"]) < 600 and "$schema" not in check["reason"]
    assert "reason_full" in check and len(check["reason_full"]) > len(check["reason"])
