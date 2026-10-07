# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.60.0
#
# Regression coverage for the accuracy and source-preflight changes introduced
# by dem2dged v0.60.0.

import os

import numpy as np

import dem2dged_compare as dc
import dem2dged_terrain as dt
from conftest import make_raster, requires_gdal


def _inspection(**overrides):
    values = dict(
        path="source.tif",
        horizontal_crs="EPSG:32633",
        vertical_crs="EPSG:3855",
        area_or_point="Point",
        pixel_size=(5.0, -5.0),
        origin=(500000.0, 5600000.0),
        extent=(500000.0, 5599000.0, 501000.0, 5600000.0),
        raster_size=(200, 200),
        nodata=-32767.0,
        data_type="Float32",
        valid_range=(100.25, 200.75),
        warnings=[],
        elevation_unit="metre",
        scale=1.0,
        offset=0.0,
    )
    values.update(overrides)
    return dt.SourceInspection(**values)


def test_source_preflight_holds_missing_registration_units_and_vertical():
    info = _inspection(
        vertical_crs=None,
        area_or_point=None,
        elevation_unit=None,
    )
    result = dt.source_preflight(info, mode="hold")
    assert result["status"] == "HOLD"
    assert "pixel registration is missing or ambiguous" in result["issues"]
    assert "elevation unit is missing or is not metres" in result["issues"]
    assert "source vertical reference is missing" in result["issues"]


def test_source_preflight_accepts_explicit_complete_metadata():
    result = dt.source_preflight(_inspection(), mode="hold")
    assert result["status"] == "PASS"
    assert result["decision"] == "conversion may proceed"


def test_source_preflight_records_explicit_override():
    info = _inspection(elevation_unit="foot", scale=0.3048)
    result = dt.source_preflight(
        info, mode="hold", allow_unknown=True)
    assert result["status"] == "OVERRIDE"
    assert result["allow_unknown"] is True
    assert result["issues"]


def test_geographic_optimizer_ratio_uses_metres_not_degree_geotransform(
        monkeypatch):
    class FakeArray:
        shape = (400, 400)

    seen = {}
    cgt = (-75.0, 0.0001, 0.0, 45.0, 0.0, -0.0001)
    monkeypatch.setattr(
        dc, "_read_source",
        lambda _path: (FakeArray(), np.ones((1, 1), bool), cgt,
                       "EPSG:4326", None, 1))
    def fake_prepare(arr, valid, gt, proj, nodata, ratio, source_path=None):
        seen["ratio"] = ratio
        return {"ratio": ratio, "n_windows": 1, "n_phases": 1}

    monkeypatch.setattr(dc, "_prepare_decimate_test", fake_prepare)
    monkeypatch.setattr(dc, "_cleanup_decimate_test", lambda _prep: None)
    monkeypatch.setattr(
        dc, "_decimate_stats",
        lambda prep, alg: {"rmse": 1.0, "mae": 1.0,
                           "max_abs_err": 1.0, "n_scored": 10,
                           "ratio": prep["ratio"], "method": "decimate"})

    alg, _label, stats = dc.pick_best_resampling(
        "geographic.tif", dst_gsd_m=30.0, src_gsd_m=10.0)
    assert alg == "near"
    assert seen["ratio"] == 3.0
    assert all(value["method"] == "decimate" for value in stats.values())


@requires_gdal
def test_optimizer_clamp_uses_exact_non_integer_source_range(scratch_dir):
    src = os.path.join(scratch_dir, "non_integer_range.tif")
    values = np.linspace(100.25, 200.75, 32 * 32).reshape(32, 32)
    make_raster(
        src, 32633,
        (500000.0, 1.0, 0.0, 5600000.0, 0.0, -1.0),
        32, 32, relief=0.0, array=values)
    arr, valid, gt, proj, nodata, _dec = dc._read_source(src)
    prep = dc._prepare_decimate_test(
        arr, valid, gt, proj, nodata, 2.0, source_path=src)
    try:
        assert prep["clamp"] == (100.25, 200.75)
    finally:
        dc._cleanup_decimate_test(prep)


def test_report_identifies_primary_measurement_method(tmp_path):
    report = tmp_path / "comparison.html"
    stats = {
        "rmse": 1.0, "mae": 0.5, "max_abs_err": 2.0,
        "rt_rmse": 0.1, "rt_bias": 0.0, "rt_max_abs_err": 0.2,
        "out_min": 100.0, "out_max": 200.0,
        "src_min": 100.0, "src_max": 200.0, "overshoot": 0.0,
        "n_tiles": 1, "n_scored": 100, "method": "holdout_fallback",
    }
    dc.write_comparison_report([{
        "name": "source", "src": "source.tif", "level": "6",
        "mode": "GEO", "methods": [{
            "num": "1", "alg": "bilinear", "label": "Bilinear",
            "folder": "bilinear", "elapsed": 1.0,
            "stats": stats, "validation": "WARN",
        }],
    }], str(report))
    html = report.read_text(encoding="utf-8")
    assert "Primary accuracy metric:" in html
    assert "METHOD-SPECIFIC / FALLBACK" in html
    assert "Primary Rank" in html
