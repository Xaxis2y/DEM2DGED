# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.55.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Regression tests for resampling-comparison delivery decisions."""

import dem2dged_compare as dc


def _stats(rmse):
    return {
        "rmse": rmse,
        "mae": rmse / 2.0,
        "max_abs_err": rmse * 2.0,
        "rt_rmse": rmse / 4.0,
        "rt_bias": 0.0,
        "rt_max_abs_err": rmse,
        "out_min": 100.0,
        "out_max": 200.0,
        "src_min": 100.0,
        "src_max": 200.0,
        "overshoot": 0.0,
        "n_tiles": 1,
        "n_holdout": 100,
    }


def test_delivery_recommendation_excludes_the_failed_method(tmp_path):
    entries = [{
        "name": "source",
        "src": "source.tif",
        "level": "6",
        "mode": "GEO",
        "methods": [
            {"num": "1", "alg": "near", "label": "Nearest Neighbor",
             "folder": "near", "elapsed": 1.0, "stats": _stats(1.0),
             "validation": "FAIL"},
            {"num": "2", "alg": "bilinear", "label": "Bilinear Interpolation",
             "folder": "bilinear", "elapsed": 1.0, "stats": _stats(2.0),
             "validation": "WARN"},
        ],
    }]
    report = tmp_path / "comparison.html"
    dc.write_comparison_report(entries, str(report))
    html = report.read_text(encoding="utf-8")
    assert "Best hold-out reconstruction: <b>Nearest Neighbor</b>" in html
    assert "Recommended for delivery: <b>Bilinear Interpolation</b>" in html
    assert "validation: WARN; no validation FAIL" in html


def test_unvalidated_methods_do_not_receive_a_delivery_recommendation(tmp_path):
    entries = [{
        "name": "source",
        "src": "source.tif",
        "level": "6",
        "mode": "GEO",
        "methods": [
            {"num": "1", "alg": "bilinear", "label": "Bilinear Interpolation",
             "folder": "bilinear", "elapsed": 1.0, "stats": _stats(1.0)},
        ],
    }]
    report = tmp_path / "comparison.html"
    dc.write_comparison_report(entries, str(report))
    html = report.read_text(encoding="utf-8")
    assert "No delivery recommendation:</b> no method completed validation" in html
