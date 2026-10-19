#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.10
"""Create and audit a seven-step DGED conformance evidence package.

The workflow is intentionally evidence-driven.  It can calculate transparent
statistics from an authority-approved control-point table and verify that the
supporting documents exist, but it cannot invent source metadata or issue an
authority acceptance decision.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from dem2dged_compliance import accuracy_limits


VERSION = "0.62.10"
SCHEMA = "DEM2DGED-evidence-package-1.0"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_HOLD = "HOLD"

CONTROL_POINT_FIELDS = (
    "point_id",
    "test_easting_m",
    "test_northing_m",
    "test_elevation_m",
    "reference_easting_m",
    "reference_northing_m",
    "reference_elevation_m",
    "relative_pair_id",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(base: Path, value: Any) -> Optional[Path]:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _finite_nonnegative(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _percentile(values: Sequence[float], probability: float = 0.90) -> Optional[float]:
    """Return a linearly interpolated percentile using (n-1)*p indexing."""
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(probability)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _result(status: str, summary: str, **details: Any) -> Dict[str, Any]:
    value = {"status": status, "summary": summary}
    value.update(details)
    return value


def _combine(results: Iterable[Dict[str, Any]]) -> str:
    statuses = [result.get("status", STATUS_HOLD) for result in results]
    if STATUS_FAIL in statuses:
        return STATUS_FAIL
    if STATUS_HOLD in statuses:
        return STATUS_HOLD
    return STATUS_PASS


def _document_check(base: Path, record: Any, label: str) -> Dict[str, Any]:
    record = record if isinstance(record, dict) else {}
    path = _resolve(base, record.get("path"))
    document_id = str(record.get("document_id") or "").strip()
    issuer = str(record.get("issuer") or "").strip()
    missing = []
    if path is None or not path.is_file():
        missing.append("document file")
    if not document_id:
        missing.append("document identifier")
    if not issuer:
        missing.append("issuer")
    if missing:
        return _result(
            STATUS_HOLD,
            "%s evidence is incomplete" % label,
            missing=missing,
            path=str(path) if path else None,
            document_id=document_id or None,
            issuer=issuer or None,
        )
    return _result(
        STATUS_PASS,
        "%s evidence document is present" % label,
        path=str(path),
        document_id=document_id,
        issuer=issuer,
        sha256=_sha256(path),
    )


def _vertical_epsg_check(value: Any) -> Dict[str, Any]:
    text = str(value or "").strip().upper().replace("EPSG:", "")
    if not text:
        return _result(STATUS_HOLD, "source vertical EPSG is not declared")
    if not text.isdigit():
        return _result(STATUS_FAIL, "source vertical reference must be an EPSG code", value=value)
    code = int(text)
    try:
        from osgeo import osr

        previous = osr.GetUseExceptions() if hasattr(osr, "GetUseExceptions") else False
        try:
            osr.UseExceptions()
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(code)
            is_vertical = bool(srs.IsVertical())
            name = srs.GetName()
        finally:
            if not previous:
                osr.DontUseExceptions()
    except Exception as exc:
        return _result(STATUS_FAIL, "vertical EPSG could not be resolved", epsg=code, reason=str(exc))
    if not is_vertical:
        return _result(STATUS_FAIL, "declared EPSG is not a vertical CRS", epsg=code, name=name)
    return _result(STATUS_PASS, "valid vertical CRS", epsg=code, name=name)


def evidence_template(level: str = "6") -> Dict[str, Any]:
    limits = accuracy_limits(level)
    return {
        "schema": SCHEMA,
        "tool_version": VERSION,
        "created_utc": _utc_now(),
        "product_level": str(level),
        "source": {
            "raster_path": "",
            "vertical_epsg": "",
            "vertical_datum_evidence": {
                "path": "documents/source_vertical_datum.pdf",
                "document_id": "",
                "issuer": "",
            },
            "horizontal_ce90_m": None,
            "vertical_le90_m": None,
            "accuracy_evidence": {
                "path": "documents/source_accuracy.pdf",
                "document_id": "",
                "issuer": "",
            },
        },
        "independent_control": {
            "dataset_path": "",
            "identifier": "",
            "provider": "",
            "acquisition_date": "",
            "independence_statement": "",
            "evidence_document": {
                "path": "documents/control_dataset_provenance.pdf",
                "document_id": "",
                "issuer": "",
            },
        },
        "evaluation": {
            "method_identifier": "",
            "method_document": {
                "path": "documents/accuracy_evaluation_method.pdf",
                "document_id": "",
                "issuer": "",
            },
            "control_points_csv": "control_points.csv",
            "approved_minimum_control_points": None,
            "results_document": {
                "path": "documents/accuracy_results.pdf",
                "document_id": "",
                "issuer": "",
            },
            "declared_results": {
                "horizontal_absolute_ce90_m": None,
                "horizontal_random_90_m": None,
                "horizontal_relative_90_m": None,
                "vertical_absolute_le90_m": None,
                "vertical_random_90_m": None,
                "vertical_relative_90_m": None,
            },
            "level_limits_for_reference": {
                key: limits.get(key) for key in (
                    "horizontal_random_90_m",
                    "horizontal_relative_90_m",
                    "horizontal_absolute_ce90_goal_m",
                    "vertical_random_90_m",
                    "vertical_relative_90_m",
                    "vertical_absolute_le90_goal_m",
                )
            },
        },
        "strict_validation_report": "",
        "authority_acceptance": {
            "status": "PENDING_AUTHORITY",
            "authority": "",
            "reviewer": "",
            "decision_date": "",
            "record_document": "",
        },
    }


def create_evidence_package(output_folder: str, level: str = "6") -> Dict[str, str]:
    root = Path(output_folder).resolve()
    root.mkdir(parents=True, exist_ok=True)
    documents = root / "documents"
    documents.mkdir(exist_ok=True)
    targets = {
        "manifest": root / "compliance_evidence.json",
        "control_points": root / "control_points.csv",
        "workflow": root / "EVIDENCE_WORKFLOW.md",
        "acceptance_form": root / "AUTHORITY_ACCEPTANCE_FORM.txt",
        "documents_readme": documents / "README.txt",
    }
    existing = [str(path) for path in targets.values() if path.exists()]
    if existing:
        raise FileExistsError(
            "evidence package files already exist; use a new folder: " + ", ".join(existing)
        )

    targets["manifest"].write_text(
        json.dumps(evidence_template(level), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with targets["control_points"].open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(CONTROL_POINT_FIELDS)

    targets["workflow"].write_text(
        """# DEM2DGED Seven-Step Evidence Workflow

1. Obtain the source vertical datum from authoritative supplier metadata and place the document in `documents/`.
2. Obtain source CE90/LE90 evidence from the supplier or an approved source evaluation.
3. Identify an independent control dataset and preserve its provenance.
4. Run the approved accuracy evaluation. Enter its results in `compliance_evidence.json` or populate `control_points.csv` when the approved method permits these calculations.
5. Record the method/procedure identifier and place the controlled method document or permitted extract in `documents/`.
6. Run DEM2DGED strict validation and set `strict_validation_report` to the resulting `validation/compliance_report.json`.
7. Submit the complete package to the responsible authority. Only that authority may change `authority_acceptance.status` to `ACCEPTED` and supply a signed record.

The control-point calculator reports transparent percentiles. Its use must be authorized by the applicable quality plan; it does not claim to reproduce every STANAG 2215 sampling rule.
""",
        encoding="utf-8",
    )
    targets["acceptance_form"].write_text(
        """DEM2DGED DELIVERY ACCEPTANCE RECORD

Delivery identifier:
Compliance report SHA-256:
Evidence package SHA-256:
Authority:
Reviewer:
Decision: ACCEPTED / REJECTED
Decision date (YYYY-MM-DD):
Conditions or limitations:
Signature/reference:

This record is completed by the designated acceptance authority, not by DEM2DGED.
""",
        encoding="utf-8",
    )
    targets["documents_readme"].write_text(
        "Place authoritative source, control, method, results, and signed acceptance documents here.\n"
        "Do not use empty placeholder files as evidence.\n",
        encoding="utf-8",
    )
    return {name: str(path) for name, path in targets.items()}


def read_control_points(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = [field for field in CONTROL_POINT_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("control-point CSV is missing columns: %s" % ", ".join(missing))
        for line_number, raw in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in raw.values()):
                continue
            row: Dict[str, Any] = {
                "point_id": str(raw["point_id"] or "").strip(),
                "relative_pair_id": str(raw["relative_pair_id"] or "").strip(),
            }
            if not row["point_id"]:
                raise ValueError("control-point row %d has no point_id" % line_number)
            for field in CONTROL_POINT_FIELDS[1:7]:
                try:
                    value = float(raw[field])
                except (TypeError, ValueError):
                    raise ValueError("control-point row %d has invalid %s" % (line_number, field))
                if not math.isfinite(value):
                    raise ValueError("control-point row %d has non-finite %s" % (line_number, field))
                row[field] = value
            rows.append(row)
    return rows


def calculate_control_point_metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        raise ValueError("the control-point CSV contains no observations")
    observations = []
    for row in rows:
        dx = float(row["test_easting_m"]) - float(row["reference_easting_m"])
        dy = float(row["test_northing_m"]) - float(row["reference_northing_m"])
        dz = float(row["test_elevation_m"]) - float(row["reference_elevation_m"])
        observations.append({"row": row, "dx": dx, "dy": dy, "dz": dz})
    mean_dx = sum(item["dx"] for item in observations) / len(observations)
    mean_dy = sum(item["dy"] for item in observations) / len(observations)
    mean_dz = sum(item["dz"] for item in observations) / len(observations)
    absolute_horizontal = [math.hypot(item["dx"], item["dy"]) for item in observations]
    random_horizontal = [
        math.hypot(item["dx"] - mean_dx, item["dy"] - mean_dy)
        for item in observations
    ]
    absolute_vertical = [abs(item["dz"]) for item in observations]
    random_vertical = [abs(item["dz"] - mean_dz) for item in observations]

    pairs: Dict[str, List[Dict[str, Any]]] = {}
    for item in observations:
        pair_id = str(item["row"].get("relative_pair_id") or "").strip()
        if pair_id:
            pairs.setdefault(pair_id, []).append(item)
    invalid_pairs = sorted(pair_id for pair_id, members in pairs.items() if len(members) != 2)
    if invalid_pairs:
        raise ValueError(
            "each relative_pair_id must occur exactly twice; invalid: %s"
            % ", ".join(invalid_pairs)
        )
    relative_horizontal = []
    relative_vertical = []
    for members in pairs.values():
        first, second = members
        relative_horizontal.append(
            math.hypot(first["dx"] - second["dx"], first["dy"] - second["dy"])
        )
        relative_vertical.append(abs(first["dz"] - second["dz"]))

    return {
        "calculation": {
            "percentile": "linear interpolation at (n-1)*0.90",
            "horizontal_absolute": "P90 of radial test-minus-reference error",
            "horizontal_random": "P90 after removing mean dx/dy bias",
            "vertical_absolute": "P90 of absolute test-minus-reference elevation error",
            "vertical_random": "P90 after removing mean vertical bias",
            "relative": "P90 of error-vector differences for declared two-point pairs",
            "method_boundary": (
                "These calculations require approval in the governing quality plan; "
                "they are not, by themselves, a STANAG 2215 certification."
            ),
        },
        "control_point_count": len(observations),
        "relative_pair_count": len(pairs),
        "mean_horizontal_bias_east_m": mean_dx,
        "mean_horizontal_bias_north_m": mean_dy,
        "mean_vertical_bias_m": mean_dz,
        "horizontal_absolute_ce90_m": _percentile(absolute_horizontal),
        "horizontal_random_90_m": _percentile(random_horizontal),
        "horizontal_relative_90_m": _percentile(relative_horizontal),
        "vertical_absolute_le90_m": _percentile(absolute_vertical),
        "vertical_random_90_m": _percentile(random_vertical),
        "vertical_relative_90_m": _percentile(relative_vertical),
    }


def _metric_check(value: Any, limit: Any, label: str) -> Dict[str, Any]:
    number = _finite_nonnegative(value)
    if number is None:
        return _result(STATUS_HOLD, "%s was not measured" % label, value=value, limit_m=limit)
    if limit is None:
        return _result(STATUS_PASS, "%s was reported" % label, value_m=number, limit_m=None)
    if number <= float(limit):
        return _result(STATUS_PASS, "%s meets the level threshold" % label, value_m=number, limit_m=float(limit))
    return _result(STATUS_FAIL, "%s exceeds the level threshold" % label, value_m=number, limit_m=float(limit))


def _reported_check(value: Any, label: str, goal: Any) -> Dict[str, Any]:
    number = _finite_nonnegative(value)
    if number is None:
        return _result(STATUS_HOLD, "%s estimate was not reported" % label, value=value, goal_m=goal)
    return _result(
        STATUS_PASS,
        "%s estimate was reported" % label,
        value_m=number,
        goal_m=goal,
        goal_status=("GOAL_MET" if goal is not None and number <= float(goal) else "GOAL_NOT_MET"),
    )


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object: %s" % path)
    return value


def evaluate_evidence(manifest: Dict[str, Any], manifest_path: str) -> Dict[str, Any]:
    base = Path(manifest_path).resolve().parent
    level = str(manifest.get("product_level") or "").strip()
    try:
        limits = accuracy_limits(level)
    except Exception as exc:
        return {
            "schema": "DEM2DGED-evidence-readiness-1.0",
            "tool_version": VERSION,
            "generated_utc": _utc_now(),
            "technical_readiness": STATUS_FAIL,
            "delivery_acceptance": STATUS_FAIL,
            "items": {"product_level": _result(STATUS_FAIL, str(exc))},
        }

    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    control = (manifest.get("independent_control")
               if isinstance(manifest.get("independent_control"), dict) else {})
    evaluation = (manifest.get("evaluation")
                  if isinstance(manifest.get("evaluation"), dict) else {})
    acceptance = (manifest.get("authority_acceptance")
                  if isinstance(manifest.get("authority_acceptance"), dict) else {})

    vertical_code = _vertical_epsg_check(source.get("vertical_epsg"))
    vertical_document = _document_check(
        base, source.get("vertical_datum_evidence"), "source vertical datum"
    )
    item1_status = _combine((vertical_code, vertical_document))
    item1 = _result(
        item1_status,
        "source vertical datum is verified" if item1_status == STATUS_PASS else
        "source vertical datum requires a valid EPSG and authoritative evidence",
        vertical_crs=vertical_code,
        evidence=vertical_document,
    )

    source_accuracy_document = _document_check(
        base, source.get("accuracy_evidence"), "source accuracy"
    )
    source_h = _metric_check(
        source.get("horizontal_ce90_m"), limits.get("horizontal_absolute_ce90_goal_m"),
        "source horizontal CE90",
    )
    source_v = _metric_check(
        source.get("vertical_le90_m"), limits.get("vertical_absolute_le90_goal_m"),
        "source vertical LE90",
    )
    item2_status = _combine((source_accuracy_document, source_h, source_v))
    item2 = _result(
        item2_status,
        "source accuracy evidence supports the requested level" if item2_status == STATUS_PASS else
        "source CE90/LE90 evidence is incomplete or insufficient",
        evidence=source_accuracy_document,
        horizontal_ce90=source_h,
        vertical_le90=source_v,
    )

    source_path = _resolve(base, source.get("raster_path"))
    control_path = _resolve(base, control.get("dataset_path"))
    control_document = _document_check(
        base, control.get("evidence_document"), "independent control provenance"
    )
    control_missing = []
    if control_path is None or not control_path.is_file():
        control_missing.append("control dataset")
    if source_path is None or not source_path.is_file():
        control_missing.append("source raster")
    for field, label in (
        ("identifier", "control identifier"),
        ("provider", "control provider"),
        ("acquisition_date", "control acquisition date"),
        ("independence_statement", "independence statement"),
    ):
        if not str(control.get(field) or "").strip():
            control_missing.append(label)
    same_path = bool(source_path and control_path and os.path.normcase(str(source_path)) == os.path.normcase(str(control_path)))
    same_hash = False
    if source_path and control_path and source_path.is_file() and control_path.is_file() and not same_path:
        same_hash = _sha256(source_path) == _sha256(control_path)
    if same_path or same_hash:
        item3 = _result(
            STATUS_FAIL,
            "control dataset is the conversion source or has identical content",
            source_path=str(source_path),
            control_path=str(control_path),
            same_path=same_path,
            same_sha256=same_hash,
            evidence=control_document,
        )
    else:
        item3_status = _combine((control_document,)) if not control_missing else STATUS_HOLD
        item3 = _result(
            item3_status,
            "independent control provenance is complete" if item3_status == STATUS_PASS else
            "independent control evidence is incomplete",
            missing=control_missing,
            source_path=str(source_path) if source_path else None,
            control_path=str(control_path) if control_path else None,
            evidence=control_document,
        )

    method_document = _document_check(
        base, evaluation.get("method_document"), "accuracy evaluation method"
    )
    method_identifier = str(evaluation.get("method_identifier") or "").strip()
    item5_status = _combine((method_document,)) if method_identifier else STATUS_HOLD
    item5 = _result(
        item5_status,
        "evaluation method is documented" if item5_status == STATUS_PASS else
        "evaluation method identifier and controlled document are required",
        method_identifier=method_identifier or None,
        evidence=method_document,
    )

    calculated = None
    control_csv_path = _resolve(base, evaluation.get("control_points_csv"))
    control_csv_error = None
    if control_csv_path and control_csv_path.is_file():
        try:
            rows = read_control_points(str(control_csv_path))
            if rows:
                calculated = calculate_control_point_metrics(rows)
        except Exception as exc:
            control_csv_error = str(exc)
    declared = (evaluation.get("declared_results")
                if isinstance(evaluation.get("declared_results"), dict) else {})
    results = dict(declared)
    if calculated:
        for key in (
            "horizontal_absolute_ce90_m",
            "horizontal_random_90_m",
            "horizontal_relative_90_m",
            "vertical_absolute_le90_m",
            "vertical_random_90_m",
            "vertical_relative_90_m",
        ):
            if calculated.get(key) is not None:
                results[key] = calculated[key]

    results_document = _document_check(
        base, evaluation.get("results_document"), "accuracy results"
    )
    metric_checks = {
        "horizontal_random_90": _metric_check(
            results.get("horizontal_random_90_m"), limits.get("horizontal_random_90_m"),
            "output random horizontal error at 90 percent",
        ),
        "horizontal_relative_90": _metric_check(
            results.get("horizontal_relative_90_m"), limits.get("horizontal_relative_90_m"),
            "output relative horizontal accuracy at 90 percent",
        ),
        "vertical_random_90": _metric_check(
            results.get("vertical_random_90_m"), limits.get("vertical_random_90_m"),
            "output random vertical error at 90 percent",
        ),
        "vertical_relative_90": _metric_check(
            results.get("vertical_relative_90_m"), limits.get("vertical_relative_90_m"),
            "output relative vertical accuracy at 90 percent",
        ),
        "horizontal_absolute_ce90": _reported_check(
            results.get("horizontal_absolute_ce90_m"), "output absolute horizontal CE90",
            limits.get("horizontal_absolute_ce90_goal_m"),
        ),
        "vertical_absolute_le90": _reported_check(
            results.get("vertical_absolute_le90_m"), "output absolute vertical LE90",
            limits.get("vertical_absolute_le90_goal_m"),
        ),
    }
    minimum = evaluation.get("approved_minimum_control_points")
    sample_check = _result(
        STATUS_HOLD,
        "the approved method must declare its minimum control-point count",
        required=minimum,
        actual=(calculated or {}).get("control_point_count"),
    )
    if minimum is not None:
        try:
            required_count = int(minimum)
            actual_count = int((calculated or {}).get("control_point_count") or 0)
            if required_count <= 0:
                raise ValueError
            sample_check = _result(
                STATUS_PASS if actual_count >= required_count else STATUS_FAIL,
                "control-point count meets the approved method" if actual_count >= required_count else
                "control-point count is below the approved method",
                required=required_count,
                actual=actual_count,
            )
        except (TypeError, ValueError):
            sample_check = _result(STATUS_FAIL, "approved minimum control-point count must be a positive integer", value=minimum)
    item4_status = _combine(list(metric_checks.values()) + [results_document, sample_check])
    if control_csv_error:
        item4_status = STATUS_FAIL
    item4 = _result(
        item4_status,
        "measured accuracy results meet mandatory thresholds" if item4_status == STATUS_PASS else
        "measured accuracy results are incomplete or outside mandatory thresholds",
        metrics=results,
        checks=metric_checks,
        results_evidence=results_document,
        control_points=str(control_csv_path) if control_csv_path else None,
        control_point_calculation=calculated,
        control_point_error=control_csv_error,
        sample_size=sample_check,
        absolute_accuracy_note="absolute CE90/LE90 values are reported goals, not mandatory threshold passes",
    )

    validation_path = _resolve(base, manifest.get("strict_validation_report"))
    if validation_path is None or not validation_path.is_file():
        item6 = _result(STATUS_HOLD, "strict compliance report is missing", path=str(validation_path) if validation_path else None)
    else:
        try:
            validation = _load_json(validation_path)
            overall = str(validation.get("overall") or "").upper()
            report_level = str(validation.get("product_level") or "")
            if overall == STATUS_PASS and report_level == level:
                item6 = _result(
                    STATUS_PASS,
                    "strict DEM2DGED validation report passed",
                    path=str(validation_path),
                    sha256=_sha256(validation_path),
                    product_level=report_level,
                )
            else:
                item6 = _result(
                    STATUS_FAIL,
                    "strict validation report did not pass for the declared level",
                    path=str(validation_path),
                    overall=overall or None,
                    report_level=report_level or None,
                    expected_level=level,
                )
        except Exception as exc:
            item6 = _result(STATUS_FAIL, "strict validation report could not be read", path=str(validation_path), reason=str(exc))

    authority_status = str(acceptance.get("status") or "PENDING_AUTHORITY").strip().upper()
    acceptance_path = _resolve(base, acceptance.get("record_document"))
    acceptance_missing = []
    for field, label in (
        ("authority", "authority"),
        ("reviewer", "reviewer"),
        ("decision_date", "decision date"),
    ):
        if not str(acceptance.get(field) or "").strip():
            acceptance_missing.append(label)
    if acceptance_path is None or not acceptance_path.is_file():
        acceptance_missing.append("signed acceptance record")
    if authority_status == "ACCEPTED" and not acceptance_missing:
        item7 = _result(
            STATUS_PASS,
            "designated authority acceptance is documented",
            authority=acceptance.get("authority"),
            reviewer=acceptance.get("reviewer"),
            decision_date=acceptance.get("decision_date"),
            record_document=str(acceptance_path),
            record_sha256=_sha256(acceptance_path),
        )
    elif authority_status in {"REJECTED", "DENIED"}:
        item7 = _result(STATUS_FAIL, "designated authority rejected the delivery", authority_status=authority_status)
    else:
        item7 = _result(
            STATUS_HOLD,
            "authority acceptance is pending and cannot be issued by DEM2DGED",
            authority_status=authority_status,
            missing=acceptance_missing,
        )

    items = {
        "1_verified_source_vertical_datum": item1,
        "2_verified_source_accuracy": item2,
        "3_independent_control_dataset": item3,
        "4_measured_accuracy_results": item4,
        "5_documented_evaluation_method": item5,
        "6_strict_validation_pass": item6,
        "7_authority_acceptance": item7,
    }
    technical_readiness = _combine(items[key] for key in list(items)[:6])
    delivery_acceptance = _combine(items.values())
    return {
        "schema": "DEM2DGED-evidence-readiness-1.0",
        "tool_version": VERSION,
        "generated_utc": _utc_now(),
        "manifest": str(Path(manifest_path).resolve()),
        "manifest_sha256": _sha256(Path(manifest_path).resolve()),
        "product_level": level,
        "technical_readiness": technical_readiness,
        "delivery_acceptance": delivery_acceptance,
        "certification": "NOT_CERTIFIED_BY_SOFTWARE",
        "items": items,
    }


def write_readiness_outputs(report: Dict[str, Any], output_folder: str) -> Dict[str, str]:
    root = Path(output_folder).resolve()
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "evidence_readiness.json"
    text_path = root / "evidence_readiness.txt"
    html_path = root / "evidence_readiness.html"
    checksums_path = root / "evidence_checksums.sha256"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "DEM2DGED Seven-Step Evidence Readiness",
        "========================================",
        "Technical readiness (items 1-6): %s" % report.get("technical_readiness"),
        "Delivery acceptance (items 1-7): %s" % report.get("delivery_acceptance"),
        "Certification: %s" % report.get("certification"),
        "",
    ]
    for name, item in report.get("items", {}).items():
        lines.append("%s: %s" % (name, item.get("status")))
        lines.append("  %s" % item.get("summary", ""))
    lines.extend([
        "",
        "A PASS for items 1-6 means the implemented technical evidence is complete.",
        "Item 7 can pass only with a documented decision from the designated authority.",
    ])
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows = []
    for name, item in report.get("items", {}).items():
        rows.append(
            "<tr><td>%s</td><td class='%s'>%s</td><td>%s</td></tr>"
            % (
                html.escape(name),
                html.escape(str(item.get("status", "")).lower()),
                html.escape(str(item.get("status", ""))),
                html.escape(str(item.get("summary", ""))),
            )
        )
    html_template = """<!doctype html><html><head><meta charset="utf-8"><title>DEM2DGED Evidence Readiness</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:1050px;margin:32px auto;padding:0 20px;color:#202124}table{border-collapse:collapse;width:100%}th,td{border:1px solid #d8dce2;padding:9px;text-align:left}.pass{color:#137333;font-weight:700}.fail{color:#b3261e;font-weight:700}.hold{color:#b06000;font-weight:700}.card{background:#f7f8fa;border:1px solid #d8dce2;border-radius:8px;padding:14px;margin:16px 0}</style></head><body>
<h1>DEM2DGED Seven-Step Evidence Readiness</h1>
<div class="card"><b>Technical readiness:</b> __TECHNICAL__<br><b>Delivery acceptance:</b> __DELIVERY__<br><b>Certification:</b> __CERTIFICATION__</div>
<table><thead><tr><th>Requirement</th><th>Status</th><th>Summary</th></tr></thead><tbody>__ROWS__</tbody></table>
<p>Software technical evidence does not replace acceptance by the designated authority.</p></body></html>"""
    html_path.write_text(
        html_template
        .replace("__TECHNICAL__", html.escape(str(report.get("technical_readiness"))))
        .replace("__DELIVERY__", html.escape(str(report.get("delivery_acceptance"))))
        .replace("__CERTIFICATION__", html.escape(str(report.get("certification"))))
        .replace("__ROWS__", "".join(rows)),
        encoding="utf-8",
    )

    checksum_paths = [Path(report["manifest"]), json_path, text_path, html_path]
    for item in report.get("items", {}).values():
        stack = [item]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
            elif isinstance(value, str):
                candidate = Path(value)
                if candidate.is_absolute() and candidate.is_file():
                    checksum_paths.append(candidate)
    unique = []
    seen = set()
    for path in checksum_paths:
        resolved = path.resolve()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    checksums_path.write_text(
        "\n".join("%s  %s" % (_sha256(path), path) for path in unique) + "\n",
        encoding="utf-8",
    )
    return {
        "json": str(json_path),
        "text": str(text_path),
        "html": str(html_path),
        "checksums": str(checksums_path),
    }


def check_evidence_file(manifest_path: str, output_folder: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, str]]:
    path = Path(manifest_path).resolve()
    manifest = _load_json(path)
    if manifest.get("schema") != SCHEMA:
        raise ValueError("unsupported evidence schema: %s" % manifest.get("schema"))
    report = evaluate_evidence(manifest, str(path))
    output = Path(output_folder).resolve() if output_folder else path.parent
    return report, write_readiness_outputs(report, str(output))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or audit a DEM2DGED seven-step evidence package.")
    parser.add_argument("--version", action="version", version="dem2dged_evidence v%s" % VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="create a new evidence package template")
    init_parser.add_argument("output_folder")
    init_parser.add_argument("--level", default="6")
    check_parser = subparsers.add_parser("check", help="audit an evidence manifest")
    check_parser.add_argument("manifest")
    check_parser.add_argument("--output", default=None)
    calculate_parser = subparsers.add_parser("calculate", help="calculate transparent control-point statistics")
    calculate_parser.add_argument("control_points_csv")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        paths = create_evidence_package(args.output_folder, args.level)
        print("Evidence package created:")
        for name, path in paths.items():
            print("  %s: %s" % (name, path))
        return 0
    if args.command == "calculate":
        metrics = calculate_control_point_metrics(read_control_points(args.control_points_csv))
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
        return 0
    report, paths = check_evidence_file(args.manifest, args.output)
    print("Technical readiness: %s" % report["technical_readiness"])
    print("Delivery acceptance: %s" % report["delivery_acceptance"])
    for name, item in report["items"].items():
        print("  %s: %s" % (name, item["status"]))
    print("Reports:")
    for name, path in paths.items():
        print("  %s: %s" % (name, path))
    if report["delivery_acceptance"] == STATUS_FAIL:
        return 1
    if report["delivery_acceptance"] != STATUS_PASS:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
