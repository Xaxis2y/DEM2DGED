# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.0
import csv
import json
from pathlib import Path

import dem2dged_evidence as de


def _write_control_points(path: Path) -> None:
    rows = [
        ["A", 100.01, 200.01, 50.01, 100.00, 200.00, 50.00, "P1"],
        ["B", 110.02, 200.01, 51.02, 110.00, 200.00, 51.00, "P1"],
        ["C", 100.01, 210.02, 52.01, 100.00, 210.00, 52.00, "P2"],
        ["D", 110.02, 210.02, 53.02, 110.00, 210.00, 53.00, "P2"],
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(de.CONTROL_POINT_FIELDS)
        writer.writerows(rows)


def _complete_manifest(root: Path):
    manifest_path = root / "compliance_evidence.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (root / "source.tif").write_bytes(b"source")
    (root / "control.tif").write_bytes(b"independent-control")
    _write_control_points(root / "control_points.csv")
    for name in (
        "source_vertical_datum.pdf",
        "source_accuracy.pdf",
        "control_dataset_provenance.pdf",
        "accuracy_evaluation_method.pdf",
        "accuracy_results.pdf",
    ):
        (root / "documents" / name).write_bytes(("evidence-" + name).encode("ascii"))
    (root / "compliance_report.json").write_text(
        json.dumps({"overall": "PASS", "product_level": "6"}),
        encoding="utf-8",
    )

    manifest["source"].update({
        "raster_path": "source.tif",
        "vertical_epsg": "3855",
        "horizontal_ce90_m": 0.2,
        "vertical_le90_m": 0.5,
    })
    manifest["source"]["vertical_datum_evidence"].update({
        "document_id": "VERT-001",
        "issuer": "Source Provider",
    })
    manifest["source"]["accuracy_evidence"].update({
        "document_id": "ACC-001",
        "issuer": "Source Provider",
    })
    manifest["independent_control"].update({
        "dataset_path": "control.tif",
        "identifier": "CONTROL-2026-01",
        "provider": "Independent Survey Authority",
        "acquisition_date": "2026-01-15",
        "independence_statement": "Acquired independently from the conversion source.",
    })
    manifest["independent_control"]["evidence_document"].update({
        "document_id": "CONTROL-PROV-001",
        "issuer": "Independent Survey Authority",
    })
    manifest["evaluation"].update({
        "method_identifier": "QUALITY-PLAN-2215-01",
        "approved_minimum_control_points": 4,
    })
    manifest["evaluation"]["method_document"].update({
        "document_id": "METHOD-001",
        "issuer": "Quality Authority",
    })
    manifest["evaluation"]["results_document"].update({
        "document_id": "RESULTS-001",
        "issuer": "Independent Survey Authority",
    })
    manifest["strict_validation_report"] = "compliance_report.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path, manifest


def test_create_evidence_package_is_non_destructive(tmp_path):
    root = tmp_path / "evidence"
    paths = de.create_evidence_package(str(root), "6")
    assert Path(paths["manifest"]).is_file()
    assert Path(paths["control_points"]).is_file()
    try:
        de.create_evidence_package(str(root), "6")
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing evidence package should not be overwritten")


def test_control_point_metrics_are_transparent_and_complete(tmp_path):
    csv_path = tmp_path / "control.csv"
    _write_control_points(csv_path)
    metrics = de.calculate_control_point_metrics(de.read_control_points(str(csv_path)))
    assert metrics["control_point_count"] == 4
    assert metrics["relative_pair_count"] == 2
    assert metrics["horizontal_absolute_ce90_m"] < 0.04
    assert metrics["horizontal_random_90_m"] < 0.02
    assert metrics["vertical_absolute_le90_m"] < 0.03
    assert metrics["vertical_relative_90_m"] < 0.02


def test_empty_template_is_hold(tmp_path):
    root = tmp_path / "evidence"
    paths = de.create_evidence_package(str(root), "6")
    report, outputs = de.check_evidence_file(paths["manifest"])
    assert report["technical_readiness"] == de.STATUS_HOLD
    assert report["delivery_acceptance"] == de.STATUS_HOLD
    assert Path(outputs["html"]).is_file()


def test_items_one_through_six_can_pass_but_authority_stays_pending(tmp_path):
    root = tmp_path / "evidence"
    de.create_evidence_package(str(root), "6")
    manifest_path, _ = _complete_manifest(root)
    report, _ = de.check_evidence_file(str(manifest_path))
    assert report["technical_readiness"] == de.STATUS_PASS
    assert report["delivery_acceptance"] == de.STATUS_HOLD
    assert report["items"]["7_authority_acceptance"]["status"] == de.STATUS_HOLD


def test_signed_authority_record_completes_delivery_acceptance(tmp_path):
    root = tmp_path / "evidence"
    de.create_evidence_package(str(root), "6")
    manifest_path, manifest = _complete_manifest(root)
    signed = root / "signed_acceptance.pdf"
    signed.write_bytes(b"signed-authority-record")
    manifest["authority_acceptance"].update({
        "status": "ACCEPTED",
        "authority": "Designated Acceptance Authority",
        "reviewer": "Authorized Reviewer",
        "decision_date": "2026-10-13",
        "record_document": "signed_acceptance.pdf",
    })
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report, _ = de.check_evidence_file(str(manifest_path))
    assert report["technical_readiness"] == de.STATUS_PASS
    assert report["delivery_acceptance"] == de.STATUS_PASS
