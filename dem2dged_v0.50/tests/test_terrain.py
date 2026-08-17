import json

import numpy as np

import dem2dged_terrain as dt


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
    bins = dt.slope_error_bins(src, out, (1.0, 1.0))
    assert sum(v["count"] for v in bins.values()) == 16


def test_compliance_profile_is_machine_readable():
    result = dt.compliance_result(False, {"bias": 0.2, "rmse": 1.2, "p95": 2.0, "max": 4.0},
                                  {"max_bias": 1.0, "max_rmse": 2.0, "max_p95": 3.0, "max_max": 5.0})
    assert result["overall"] == "PASS"
    assert set(result["checks"]) == {"structural", "bias", "rmse", "p95", "max"}

