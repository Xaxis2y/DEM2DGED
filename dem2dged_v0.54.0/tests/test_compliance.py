# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.54.0

import dem2dged_compliance as dc
import dem2dged_validate as dv
from conftest import requires_gdal


def test_level_4b_values_and_mountain_allowance():
    base = dc.accuracy_limits("4b")
    mountain = dc.accuracy_limits("4b", mountainous=True)
    assert base["gsd_m"] == 5.0
    assert base["vertical_random_90_m"] == 0.87
    assert mountain["vertical_random_90_m"] == 0.87 * 1.4
    assert mountain["mountainous_slope_allowance_factor"] == 1.4


def test_coarser_source_cannot_claim_finer_level():
    result = dc.source_eligibility(
        "5", source_gsd_m=10.0,
        source_vertical_accuracy_90_m=1.0,
        source_horizontal_accuracy_90_m=1.0)
    assert result["checks"]["source_resolution"]["status"] == dc.STATUS_FAIL
    assert result["status"] == dc.STATUS_FAIL


def test_missing_independent_reference_is_not_a_pass():
    result = dc.external_accuracy(None, "4b")
    assert result["status"] == dc.STATUS_NOT_EVALUATED
    assert all(check["status"] == dc.STATUS_NOT_EVALUATED
               for check in result["checks"].values())


def test_absolute_accuracy_goal_does_not_replace_mandatory_checks():
    metrics = {"count": 100, "bias_removed_p90": 0.5, "p90": 6.0}
    result = dc.external_accuracy(
        metrics, "4b", relative_vertical_90_m=2.0,
        horizontal_ce90_m=5.0)
    assert result["checks"]["vertical_random_90"]["status"] == dc.STATUS_PASS
    assert result["checks"]["vertical_absolute_le90_goal"]["status"] == dc.STATUS_GOAL_NOT_MET
    assert result["status"] == dc.STATUS_PASS


def test_geographic_source_gsd_is_converted_to_metres():
    value = dc.nominal_source_gsd_m((1.0 / 3600.0, -1.0 / 3600.0),
                                    "EPSG:4326", latitude=45.0)
    assert 29.0 < value < 32.0


def test_report_preserves_not_evaluated_state():
    report = dc.build_compliance_report(
        "4b", dc.structural_compliance(0),
        dc.source_eligibility("4b", 5.0),
        dc.conversion_fidelity({"count": 1, "bias": 0.0, "rmse": 0.0,
                                "p95": 0.0, "p99": 0.0, "max": 0.0}),
        dc.external_accuracy(None, "4b"))
    assert report["overall"] == dc.STATUS_NOT_EVALUATED


def test_consolidated_statistics_and_html_are_written(tmp_path):
    report = dc.build_compliance_report(
        "4b", dc.structural_compliance(0),
        dc.source_eligibility("4b", 5.0),
        dc.conversion_fidelity({"count": 1, "bias": 0.0, "rmse": 0.0,
                                "p95": 0.0, "p99": 0.0, "max": 0.0}),
        dc.external_accuracy(None, "4b"))
    paths = dc.write_consolidated_outputs(
        report, str(tmp_path), terrain_qa={"metrics": {"rmse": 0.0}})
    statistics = (tmp_path / "statistics.json").read_text(encoding="utf-8")
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert paths["statistics"].endswith("statistics.json")
    assert '"overall_compliance": "NOT_EVALUATED"' in statistics
    assert "SPDX-License-Identifier: GPL-2.0-or-later" in html
    assert "NOT_EVALUATED" in html


@requires_gdal
def test_validator_compliance_call_writes_stable_consolidated_names(
        geo_source, tmp_path):
    import shutil
    from types import SimpleNamespace

    tile_folder = tmp_path / "delivery"
    tile_folder.mkdir()
    shutil.copyfile(geo_source, tile_folder / "DGEDL2_55N012E_A_U_01.tif")
    metrics = {"count": 10, "bias": 0.0, "mae": 0.0, "rmse": 0.0,
               "p90": 0.0, "bias_removed_p90": 0.0, "p95": 0.0,
               "p99": 0.0, "max": 0.0}
    result = dv.write_dgiwg_compliance(
        str(tile_folder), SimpleNamespace(n_fail=0, n_warn=0),
        source_path=geo_source, terrain_qa={"metrics": metrics})
    assert result["overall"] == dc.STATUS_NOT_EVALUATED
    assert (tile_folder / "validation" / "statistics.json").is_file()
    assert (tile_folder / "validation" / "report.html").is_file()
