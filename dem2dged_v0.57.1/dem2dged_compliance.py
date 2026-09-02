# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.57.1
"""DGIWG DGED compliance and evidence-reporting helpers.

This module keeps three questions deliberately separate:

* is the source suitable for the requested DGED level;
* did the conversion preserve the source terrain on the DGED post grid; and
* does the product meet accuracy goals against independent reference data.

Source-to-output agreement is not independent accuracy evidence.  Therefore
missing reference data is reported as ``NOT_EVALUATED`` and never as PASS.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import platform
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

VERSION = "0.57.1"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_EVALUATED = "NOT_EVALUATED"
STATUS_GOAL_MET = "GOAL_MET"
STATUS_GOAL_NOT_MET = "GOAL_NOT_MET"

STANDARDS = {
    "dged_product_specification": {
        "identifier": "DGIWG 250",
        "version": "1.2.1",
        "date": "2020-09-24",
    },
    "geotiff_profile": {
        "identifier": "DGIWG 116-3-2",
        "version": "1.1.1",
        "date": "2023-11-22",
    },
    "geotiff_standard": {
        "identifier": "OGC 19-008r4",
        "version": "1.1",
    },
}


# Nominal DGED values transcribed from DGIWG 250 Tables 3, 5 and 6.
# Absolute CE90/LE90 entries are product goals.  They are not converted into
# mandatory PASS criteria without independent accuracy evidence.
DGED_LEVEL_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "0": {"gsd_m": 900.0, "post_arcsec": 30.0,
          "horizontal_random_90_m": None, "horizontal_relative_90_m": None,
          "horizontal_absolute_ce90_goal_m": 50.0,
          "vertical_random_90_m": 20.0, "vertical_relative_90_m": None,
          "vertical_absolute_le90_goal_m": 30.0, "data_type": "Int16"},
    "1": {"gsd_m": 90.0, "post_arcsec": 3.0,
          "horizontal_random_90_m": None, "horizontal_relative_90_m": None,
          "horizontal_absolute_ce90_goal_m": 50.0,
          "vertical_random_90_m": 20.0, "vertical_relative_90_m": None,
          "vertical_absolute_le90_goal_m": 30.0, "data_type": "Int16"},
    "2": {"gsd_m": 30.0, "post_arcsec": 1.0,
          "horizontal_random_90_m": None, "horizontal_relative_90_m": None,
          "horizontal_absolute_ce90_goal_m": 23.0,
          "vertical_random_90_m": 12.0, "vertical_relative_90_m": None,
          "vertical_absolute_le90_goal_m": 18.0, "data_type": "Int16"},
    "3": {"gsd_m": 15.0, "post_arcsec": 0.5,
          "horizontal_random_90_m": 4.4, "horizontal_relative_90_m": 12.4,
          "horizontal_absolute_ce90_goal_m": 15.0,
          "vertical_random_90_m": 2.2, "vertical_relative_90_m": 6.2,
          "vertical_absolute_le90_goal_m": 12.4, "data_type": "Float32"},
    "4b": {"gsd_m": 5.0, "post_arcsec": None,
           "horizontal_random_90_m": 1.75, "horizontal_relative_90_m": 5.0,
           "horizontal_absolute_ce90_goal_m": 6.0,
           "vertical_random_90_m": 0.87, "vertical_relative_90_m": 2.5,
           "vertical_absolute_le90_goal_m": 5.0, "data_type": "Float32"},
    "4": {"gsd_m": 4.0, "post_arcsec": None,
          "horizontal_random_90_m": 1.41, "horizontal_relative_90_m": 4.0,
          "horizontal_absolute_ce90_goal_m": 5.0,
          "vertical_random_90_m": 0.71, "vertical_relative_90_m": 2.0,
          "vertical_absolute_le90_goal_m": 4.0, "data_type": "Float32"},
    "5": {"gsd_m": 2.0, "post_arcsec": None,
          "horizontal_random_90_m": 0.71, "horizontal_relative_90_m": 2.0,
          "horizontal_absolute_ce90_goal_m": 3.0,
          "vertical_random_90_m": 0.35, "vertical_relative_90_m": 1.0,
          "vertical_absolute_le90_goal_m": 2.0, "data_type": "Float32"},
    "6": {"gsd_m": 1.0, "post_arcsec": None,
          "horizontal_random_90_m": 0.35, "horizontal_relative_90_m": 1.0,
          "horizontal_absolute_ce90_goal_m": 2.0,
          "vertical_random_90_m": 0.18, "vertical_relative_90_m": 0.5,
          "vertical_absolute_le90_goal_m": 1.0, "data_type": "Float32"},
    "7": {"gsd_m": 0.5, "post_arcsec": None,
          "horizontal_random_90_m": 0.18, "horizontal_relative_90_m": 0.5,
          "horizontal_absolute_ce90_goal_m": 1.0,
          "vertical_random_90_m": 0.09, "vertical_relative_90_m": 0.25,
          "vertical_absolute_le90_goal_m": 0.5, "data_type": "Float32"},
    "8": {"gsd_m": 0.25, "post_arcsec": None,
          "horizontal_random_90_m": 0.09, "horizontal_relative_90_m": 0.25,
          "horizontal_absolute_ce90_goal_m": 0.5,
          "vertical_random_90_m": 0.04, "vertical_relative_90_m": 0.12,
          "vertical_absolute_le90_goal_m": 0.25, "data_type": "Float32"},
    "9": {"gsd_m": 0.125, "post_arcsec": None,
          "horizontal_random_90_m": 0.04, "horizontal_relative_90_m": 0.125,
          "horizontal_absolute_ce90_goal_m": 0.25,
          "vertical_random_90_m": 0.02, "vertical_relative_90_m": 0.06,
          "vertical_absolute_le90_goal_m": 0.12, "data_type": "Float32"},
}


def level_requirement(level: str) -> Dict[str, Any]:
    """Return a copy of the normative/goal values for a DGED level."""
    key = str(level).lower().replace("level", "").strip()
    if key not in DGED_LEVEL_REQUIREMENTS:
        raise ValueError("unsupported DGED level: %s" % level)
    result = dict(DGED_LEVEL_REQUIREMENTS[key])
    result["level"] = key
    return result


def accuracy_limits(level: str, mountainous: bool = False) -> Dict[str, Any]:
    """Return level limits, applying the DGIWG >20% slope allowance.

    DGIWG 250 permits vertical accuracy values to be multiplied by 1.4 in
    terrain whose predominant slope exceeds 20 percent.  The returned record
    preserves the base values and states whether the factor was applied.
    """
    result = level_requirement(level)
    factor = 1.4 if mountainous else 1.0
    for name in ("vertical_random_90_m", "vertical_relative_90_m",
                 "vertical_absolute_le90_goal_m"):
        value = result.get(name)
        if value is not None:
            result[name] = float(value) * factor
    result["mountainous_slope_allowance_factor"] = factor
    return result


def nominal_source_gsd_m(pixel_size: Iterable[float], horizontal_crs: Optional[str],
                         latitude: float = 0.0) -> Optional[float]:
    """Estimate the source's coarser pixel dimension in metres.

    EPSG:4326/CRS84 pixels are converted at the supplied latitude.  Other
    projected grids are treated as metre grids; an unknown CRS is deliberately
    not guessed and returns ``None``.
    """
    values = [abs(float(v)) for v in pixel_size]
    if not values or not all(math.isfinite(v) and v > 0 for v in values):
        return None
    label = (horizontal_crs or "").upper()
    if "4326" in label or "CRS84" in label:
        lat = max(-89.999, min(89.999, float(latitude)))
        x_m = values[0] * 111320.0 * abs(math.cos(math.radians(lat)))
        y_m = values[1] * 110574.0
        return max(x_m, y_m)
    if label:
        return max(values)
    return None


def source_eligibility(level: str, source_gsd_m: Optional[float],
                       source_vertical_accuracy_90_m: Optional[float] = None,
                       source_horizontal_accuracy_90_m: Optional[float] = None,
                       source_vertical_datum: Optional[str] = None,
                       tolerance: float = 0.05) -> Dict[str, Any]:
    """Evaluate whether source evidence supports the requested level."""
    req = level_requirement(level)
    checks: Dict[str, Dict[str, Any]] = {}
    target = float(req["gsd_m"])
    if source_gsd_m is None:
        checks["source_resolution"] = {
            "status": STATUS_NOT_EVALUATED, "target_gsd_m": target,
            "reason": "source CRS or pixel size is unavailable",
        }
    else:
        value = float(source_gsd_m)
        checks["source_resolution"] = {
            "status": STATUS_PASS if value <= target * (1.0 + tolerance) else STATUS_FAIL,
            "source_gsd_m": value, "target_gsd_m": target,
            "rule": "a coarser source must not be used to derive a finer DGED level",
        }

    if source_vertical_datum:
        checks["source_vertical_datum"] = {
            "status": STATUS_PASS, "value": str(source_vertical_datum),
        }
    else:
        checks["source_vertical_datum"] = {
            "status": STATUS_NOT_EVALUATED,
            "reason": "source vertical CRS/datum was not independently declared",
        }

    for label, value, limit_name in (
        ("source_vertical_accuracy", source_vertical_accuracy_90_m,
         "vertical_absolute_le90_goal_m"),
        ("source_horizontal_accuracy", source_horizontal_accuracy_90_m,
         "horizontal_absolute_ce90_goal_m"),
    ):
        limit = req[limit_name]
        if value is None:
            checks[label] = {
                "status": STATUS_NOT_EVALUATED, "limit_m": limit,
                "reason": "no independently established source accuracy was supplied",
            }
        else:
            checks[label] = {
                "status": STATUS_PASS if float(value) <= float(limit) else STATUS_FAIL,
                "value_m": float(value), "limit_m": float(limit),
            }
    return _section("Input source eligibility", checks)


def conversion_fidelity(metrics: Optional[Dict[str, Any]],
                        thresholds: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Evaluate source-to-output agreement as engineering QA, not accuracy."""
    if not metrics or not metrics.get("count"):
        return _section("Source-to-output conversion fidelity", {
            "comparison": {"status": STATUS_NOT_EVALUATED,
                           "reason": "source/output comparison was not run"}
        })
    thresholds = thresholds or {}
    checks: Dict[str, Dict[str, Any]] = {}
    for metric in ("bias", "rmse", "p95", "p99", "max"):
        value = metrics.get(metric)
        limit = thresholds.get("max_" + metric)
        if value is None:
            status = STATUS_NOT_EVALUATED
        elif limit is None:
            status = STATUS_PASS
        else:
            status = STATUS_PASS if abs(float(value)) <= float(limit) else STATUS_FAIL
        checks[metric] = {"status": status, "value_m": value, "limit_m": limit}
    section = _section("Source-to-output conversion fidelity", checks)
    section["disclaimer"] = (
        "Agreement with the source measures conversion fidelity only; it does "
        "not prove absolute or relative terrain accuracy."
    )
    return section


def external_accuracy(metrics: Optional[Dict[str, Any]], level: str,
                      mountainous: bool = False,
                      relative_vertical_90_m: Optional[float] = None,
                      horizontal_ce90_m: Optional[float] = None) -> Dict[str, Any]:
    """Evaluate independent reference metrics against DGIWG level values."""
    limits = accuracy_limits(level, mountainous)
    if not metrics or not metrics.get("count"):
        checks = {
            "vertical_random_90": {"status": STATUS_NOT_EVALUATED,
                                    "limit_m": limits["vertical_random_90_m"]},
            "vertical_relative_90": {"status": STATUS_NOT_EVALUATED,
                                      "limit_m": limits["vertical_relative_90_m"]},
            "vertical_absolute_le90_goal": {"status": STATUS_NOT_EVALUATED,
                                             "goal_m": limits["vertical_absolute_le90_goal_m"]},
            "horizontal_absolute_ce90_goal": {"status": STATUS_NOT_EVALUATED,
                                               "goal_m": limits["horizontal_absolute_ce90_goal_m"]},
        }
        section = _section("Independent reference accuracy", checks)
        section["reference_required"] = True
        section["mountainous_slope_allowance_factor"] = limits["mountainous_slope_allowance_factor"]
        return section

    random_value = metrics.get("bias_removed_p90")
    absolute_value = metrics.get("p90")
    random_limit = limits["vertical_random_90_m"]
    relative_limit = limits["vertical_relative_90_m"]
    checks = {
        "vertical_random_90": _required_check(random_value, random_limit),
        "vertical_relative_90": _required_check(relative_vertical_90_m, relative_limit),
        "vertical_absolute_le90_goal": _goal_check(
            absolute_value, limits["vertical_absolute_le90_goal_m"]),
        "horizontal_absolute_ce90_goal": _goal_check(
            horizontal_ce90_m, limits["horizontal_absolute_ce90_goal_m"]),
    }
    section = _section("Independent reference accuracy", checks)
    section["reference_required"] = True
    section["mountainous_slope_allowance_factor"] = limits["mountainous_slope_allowance_factor"]
    return section


def structural_compliance(fail_count: int, warn_count: int = 0) -> Dict[str, Any]:
    checks = {
        "automated_structure_and_metadata": {
            "status": STATUS_FAIL if fail_count else STATUS_PASS,
            "fail_count": int(fail_count), "warn_count": int(warn_count),
        }
    }
    return _section("Product structure and metadata", checks)


def build_compliance_report(level: str, structural: Dict[str, Any],
                            source: Dict[str, Any], conversion: Dict[str, Any],
                            independent: Dict[str, Any],
                            provenance: Optional[Dict[str, Any]] = None,
                            error_budget: Optional[Dict[str, Any]] = None
                            ) -> Dict[str, Any]:
    """Build the final report without collapsing unknown evidence into PASS."""
    sections = {
        "product_structure": structural,
        "source_eligibility": source,
        "conversion_fidelity": conversion,
        "independent_accuracy": independent,
    }
    statuses = [section.get("status", STATUS_NOT_EVALUATED)
                for section in sections.values()]
    if STATUS_FAIL in statuses:
        overall = STATUS_FAIL
    elif STATUS_NOT_EVALUATED in statuses:
        overall = STATUS_NOT_EVALUATED
    else:
        overall = STATUS_PASS
    return {
        "schema": "DEM2DGED-compliance-report-1.0",
        "tool_version": VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "product_level": str(level),
        "overall": overall,
        "standards": STANDARDS,
        "sections": sections,
        "provenance": provenance or {},
        "error_budget": error_budget or {},
        "interpretation": {
            "PASS": "all automated mandatory checks have evidence and passed",
            "FAIL": "at least one mandatory check failed",
            "NOT_EVALUATED": "required evidence is missing; this is not a pass",
            "absolute_accuracy": "DGIWG absolute CE90/LE90 values are goals",
        },
    }


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def runtime_provenance() -> Dict[str, Any]:
    result: Dict[str, Any] = {"python": platform.python_version(),
                              "platform": platform.platform()}
    try:
        from osgeo import gdal
        result["gdal"] = gdal.VersionInfo("RELEASE_NAME")
    except Exception:
        result["gdal"] = None
    try:
        import pyproj
        result["proj"] = pyproj.proj_version_str
    except Exception:
        result["proj"] = None
    return result


def infer_product_level(tile_folder: str) -> Optional[str]:
    """Infer one unambiguous DGED level from delivery TIFF names."""
    levels = set()
    if not os.path.isdir(tile_folder):
        return None
    for name in os.listdir(tile_folder):
        match = re.match(r"^DGEDL(4b|\d)", name, re.IGNORECASE)
        if match and name.lower().endswith(".tif"):
            levels.add(match.group(1).lower())
    return next(iter(levels)) if len(levels) == 1 else None


def read_conversion_manifest(tile_folder: str) -> Dict[str, Any]:
    path = os.path.join(tile_folder, "DEM2DGED_Conversion_Manifest.json")
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError, TypeError):
        return {}


def write_conversion_manifest(path: str, source_path: str, output_folder: str,
                              parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Write reproducibility information after a successful conversion."""
    outputs = []
    if os.path.isdir(output_folder):
        for name in sorted(os.listdir(output_folder)):
            item = os.path.join(output_folder, name)
            if os.path.isfile(item) and name.lower().endswith((".tif", ".xml")):
                outputs.append({"name": name, "sha256": sha256_file(item),
                                "size_bytes": os.path.getsize(item)})
    source = {"path": os.path.abspath(source_path)}
    if os.path.isfile(source_path):
        source["sha256"] = sha256_file(source_path)
        source["size_bytes"] = os.path.getsize(source_path)
    manifest = {
        "schema": "DEM2DGED-conversion-manifest-1.0",
        "tool_version": VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "output_folder": os.path.abspath(output_folder),
        "parameters": dict(parameters),
        "runtime": runtime_provenance(),
        "outputs": outputs,
    }
    write_json(manifest, path)
    return manifest


def write_json(value: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)


def write_compliance_text(report: Dict[str, Any], path: str) -> None:
    lines = ["DEM2DGED DGIWG Compliance Report", "=" * 34,
             "Overall: %s" % report.get("overall"),
             "Product level: %s" % report.get("product_level"), ""]
    for key, section in report.get("sections", {}).items():
        lines.append("%s: %s" % (section.get("title", key), section.get("status")))
        for name, check in section.get("checks", {}).items():
            lines.append("  %-36s %s" % (name, check.get("status")))
        lines.append("")
    lines.extend([
        "Important:",
        "  Source-to-output agreement is conversion fidelity, not absolute accuracy.",
        "  NOT_EVALUATED means that required independent evidence was not supplied.",
        "  DGIWG absolute CE90/LE90 values are goals.",
    ])
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def write_consolidated_outputs(report: Dict[str, Any], validation_dir: str,
                               terrain_qa: Optional[Dict[str, Any]] = None,
                               independent_qa: Optional[Dict[str, Any]] = None,
                               error_budget: Optional[Dict[str, Any]] = None
                               ) -> Dict[str, str]:
    """Write the plan's stable machine and operator-facing report names."""
    os.makedirs(validation_dir, exist_ok=True)
    statistics = {
        "schema": "DEM2DGED-statistics-1.0",
        "tool_version": VERSION,
        "license": "GPL-2.0-or-later",
        "copyright": "Copyright (c) 2026 Eui Soo SON",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "overall_compliance": report.get("overall"),
        "product_level": report.get("product_level"),
        "conversion_fidelity": (terrain_qa or {}).get("metrics"),
        "slope_bins": (terrain_qa or {}).get("slope_bins", {}),
        "slope_percent_bins": (terrain_qa or {}).get("slope_percent_bins", {}),
        "mountain_metrics": (terrain_qa or {}).get("mountain_metrics", {}),
        "offset_sensitivity": (terrain_qa or {}).get("offset_sensitivity", {}),
        "independent_accuracy": (independent_qa or {}).get("metrics"),
        "error_budget": error_budget or {},
    }
    statistics_path = os.path.join(validation_dir, "statistics.json")
    html_path = os.path.join(validation_dir, "report.html")
    write_json(statistics, statistics_path)

    def value(value: Any) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, float):
            return "%.6g" % value
        return html.escape(str(value))

    def metrics_table(title: str, metrics: Optional[Dict[str, Any]]) -> str:
        if not metrics:
            return "<h2>%s</h2><p>NOT_EVALUATED</p>" % html.escape(title)
        rows = "".join("<tr><th>%s</th><td>%s</td></tr>" %
                       (html.escape(str(k)), value(v))
                       for k, v in metrics.items())
        return "<h2>%s</h2><table>%s</table>" % (html.escape(title), rows)

    section_rows = []
    for key, section in report.get("sections", {}).items():
        section_rows.append("<tr><th>%s</th><td class='%s'>%s</td></tr>" %
                            (html.escape(section.get("title", key)),
                             html.escape(section.get("status", "")),
                             html.escape(section.get("status", ""))))
    budget = error_budget or {}
    budget_html = "".join([
        metrics_table("Source error vs independent reference",
                      budget.get("source_error")),
        metrics_table("Conversion residual (output minus source)",
                      budget.get("conversion_error")),
        metrics_table("Final output error vs independent reference",
                      budget.get("output_error")),
        metrics_table("MSE decomposition", budget.get("mse_decomposition")),
    ]) if budget else "<h2>Error budget</h2><p>NOT_EVALUATED — an independent reference DEM was not supplied.</p>"
    document = """<!doctype html>
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- Copyright (c) 2026 Eui Soo SON -->
<html lang="en"><head><meta charset="utf-8">
<title>DEM2DGED Consolidated Compliance Report</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17202a}
h1,h2{color:#17365d} table{border-collapse:collapse;width:100%%;margin:.8rem 0 1.6rem}
th,td{border:1px solid #ccd4dc;padding:.45rem;text-align:left}th{background:#eef3f7;width:42%%}
.PASS,.GOAL_MET{color:#176b32;font-weight:700}.FAIL,.GOAL_NOT_MET{color:#a61b1b;font-weight:700}
.NOT_EVALUATED{color:#8a5a00;font-weight:700}.note{background:#fff8df;padding:1rem;border-left:4px solid #d89b00}
footer{margin-top:2rem;color:#566573;font-size:.9rem}
</style></head><body>
<h1>DEM2DGED Consolidated Compliance Report</h1>
<p><strong>Overall:</strong> <span class="%(overall)s">%(overall)s</span> &nbsp; Product level: %(level)s</p>
<table>%(sections)s</table>
%(conversion)s
%(independent)s
%(budget)s
<p class="note">Source-to-output agreement measures conversion fidelity, not absolute accuracy. Missing independent evidence remains NOT_EVALUATED. MAE and RMSE are not subtracted; the error budget uses the exact vector identity and MSE cross term.</p>
<footer>DEM2DGED v%(version)s · SPDX-License-Identifier: GPL-2.0-or-later · Copyright (c) 2026 Eui Soo SON</footer>
</body></html>""" % {
        "overall": html.escape(str(report.get("overall", "NOT_EVALUATED"))),
        "level": html.escape(str(report.get("product_level", "n/a"))),
        "sections": "".join(section_rows),
        "conversion": metrics_table(
            "Conversion fidelity", (terrain_qa or {}).get("metrics")),
        "independent": metrics_table(
            "Independent output accuracy", (independent_qa or {}).get("metrics")),
        "budget": budget_html,
        "version": VERSION,
    }
    with open(html_path, "w", encoding="utf-8") as stream:
        stream.write(document)
    return {"statistics": statistics_path, "html": html_path}


def _required_check(value: Optional[float], limit: Optional[float]) -> Dict[str, Any]:
    if value is None or limit is None:
        return {"status": STATUS_NOT_EVALUATED, "value_m": value,
                "limit_m": limit}
    return {"status": STATUS_PASS if float(value) <= float(limit) else STATUS_FAIL,
            "value_m": float(value), "limit_m": float(limit)}


def _goal_check(value: Optional[float], goal: Optional[float]) -> Dict[str, Any]:
    if value is None or goal is None:
        return {"status": STATUS_NOT_EVALUATED, "value_m": value, "goal_m": goal}
    return {"status": STATUS_GOAL_MET if float(value) <= float(goal) else STATUS_GOAL_NOT_MET,
            "value_m": float(value), "goal_m": float(goal)}


def _section(title: str, checks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    statuses = [item.get("status", STATUS_NOT_EVALUATED) for item in checks.values()]
    if STATUS_FAIL in statuses:
        status = STATUS_FAIL
    elif STATUS_NOT_EVALUATED in statuses:
        status = STATUS_NOT_EVALUATED
    else:
        status = STATUS_PASS
    return {"title": title, "status": status, "checks": checks}
