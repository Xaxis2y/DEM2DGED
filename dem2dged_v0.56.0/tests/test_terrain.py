# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.56.0

import shutil

import numpy as np

import dem2dged_terrain as dt
from conftest import requires_gdal


def test_grid_phase_and_strategy():
    info = dt.SourceInspection(
        path="x", horizontal_crs="EPSG:4326", vertical_crs="EPSG:3855",
        area_or_point="Point", pixel_size=(1.0, -1.0), origin=(0.0, 10.0),
        extent=(0.0, 0.0, 10.0, 10.0), raster_size=(10, 10), nodata=None,
        data_type="Float32", valid_range=(0.0, 100.0), warnings=[])
    result = dt.grid_compatibility(info, {
        "crs": "EPSG:4326", "area_or_point": "Point",
        "pixel_size": (1.0, -1.0), "origin": (0.0, 10.0),
        "same_extent": True})
    assert result["direct_copy_eligible"] is True
    assert result["strategy"] == "direct-copy"


def test_grid_phase_detects_half_pixel_shift():
    assert dt.grid_phase((15.0, 15.0), (0.0, 0.0), (30.0, 30.0)) == (0.5, 0.5)


def test_terrain_metrics_and_slope_bins():
    src = np.arange(16, dtype=float).reshape(4, 4)
    out = src + 2.0
    metrics = dt.terrain_metrics(src, out)
    assert metrics["count"] == 16
    assert metrics["mae"] == 2.0
    assert metrics["bias"] == 2.0
    assert metrics["p90"] == 2.0
    assert metrics["bias_removed_p90"] == 0.0
    bins = dt.slope_error_bins(src, out, (1.0, 1.0))
    assert sum(v["count"] for v in bins.values()) == 16


def test_error_budget_uses_vector_identity_and_cross_term():
    reference = np.array([[100.0, 100.0], [100.0, 100.0]])
    source = reference + np.array([[2.0, -2.0], [1.0, -1.0]])
    output = source + np.array([[1.0, 1.0], [-1.0, -1.0]])
    result = dt.error_budget_metrics(source, output, reference)
    mse = result["mse_decomposition"]
    assert result["valid_count"] == 4
    assert result["error_vector_closure_max_abs"] == 0.0
    assert abs(mse["closure"]) < 1e-12
    assert abs(mse["output_mse"] - mse["reconstructed_output_mse"]) < 1e-12
    assert "Do not subtract" in result["warning"]


def test_mountain_metrics_detect_steep_terrain_and_extremes():
    src = np.tile(np.arange(8, dtype=float) * 5.0, (8, 1))
    out = src.copy()
    out[:, -1] -= 2.0
    result = dt.mountain_preservation_metrics(
        src, out, (10.0, 10.0), error_threshold=1.0)
    assert result["slope_over_20_percent_fraction"] > 0.5
    assert result["predominant_slope_over_20_percent"] is True
    assert result["upper_one_percent_error"]["max"] == 2.0


def test_compliance_profile_is_machine_readable():
    result = dt.compliance_result(False, {"bias": 0.2, "rmse": 1.2, "p95": 2.0, "max": 4.0},
                                  {"max_bias": 1.0, "max_rmse": 2.0, "max_p95": 3.0, "max_max": 5.0})
    assert result["overall"] == "PASS"
    assert set(result["checks"]) == {"structural", "bias", "rmse", "p95", "p99", "max"}


def test_compliance_threshold_breach_fails_the_profile():
    result = dt.compliance_result(
        False, {"bias": 2.1, "rmse": 1.2, "p95": 2.0, "max": 4.0},
        {"max_bias": 2.0, "max_rmse": 5.0, "max_p95": 8.0, "max_max": 20.0})
    assert result["checks"]["bias"]["status"] == "FAIL"
    assert result["overall"] == "FAIL"


@requires_gdal
def test_source_inspection_reports_horizontal_crs(geo_source):
    info = dt.inspect_source(geo_source)
    assert info.horizontal_crs == "EPSG:4326"


@requires_gdal
def test_vertical_operation_identity_passes_and_invalid_epsg_fails():
    identity = dt.check_vertical_operation("EPSG:4326", "3855")
    invalid = dt.check_vertical_operation("EPSG:4326", "999999")
    assert identity["status"] == "PASS"
    assert identity["operation"] == "identity"
    assert invalid["status"] == "FAIL"


@requires_gdal
def test_terrain_qa_writes_to_validation_and_uses_error_threshold(geo_source, tmp_path):
    tile_folder = tmp_path / "delivery"
    tile_folder.mkdir()
    tile = tile_folder / "DGEDL2_55N012E_A_U_01.tif"
    shutil.copyfile(geo_source, tile)

    result = dt.run_terrain_qa(str(tile_folder), geo_source,
                               error_threshold=0.25)

    assert result["tiles"] == 1
    assert result["error_threshold_m"] == 0.25
    assert result["metrics"]["count"] > 0
    assert (tile_folder / "validation" / "elevation_diff.tif").is_file()
    assert (tile_folder / "validation" / "error_mask.tif").is_file()


@requires_gdal
def test_error_budget_qa_writes_json_on_delivered_grid(geo_source, tmp_path):
    tile_folder = tmp_path / "delivery"
    tile_folder.mkdir()
    shutil.copyfile(geo_source, tile_folder / "DGEDL2_55N012E_A_U_01.tif")
    result = dt.run_error_budget_qa(
        str(tile_folder), geo_source, geo_source)
    assert result["valid_count"] > 0
    assert result["error_vector_closure_max_abs"] == 0.0
    assert (tile_folder / "validation" / "error_budget.json").is_file()
