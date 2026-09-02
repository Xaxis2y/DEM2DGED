# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.57.0
"""Source inspection, terrain QA and compliance helpers.

The module deliberately imports GDAL lazily.  The command line tool can still
show help and run its pure self-audit on machines where GDAL is not installed;
the raster operations fail with an actionable message only when requested.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

NODATA_FALLBACK = -32767.0

DEFAULT_COMPLIANCE_PROFILES = {
    "informational": {"description": "Report metrics without acceptance thresholds"},
    "standard": {"max_bias": 2.0, "max_rmse": 5.0,
                  "max_p95": 8.0, "max_max": 20.0},
    "strict": {"max_bias": 1.0, "max_rmse": 3.0,
               "max_p95": 5.0, "max_max": 10.0},
}


def compliance_thresholds(profile: str = "informational") -> Dict[str, float]:
    """Load the reviewed policy file, with a safe bundled fallback."""
    profile = (profile or "informational").lower()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "DEM2DGED_Compliance_Policy.json")
    try:
        with open(path, encoding="utf-8") as f:
            profiles = json.load(f).get("profiles", {})
    except Exception:
        profiles = {}

    if profile in profiles:
        value = profiles[profile]
    else:
        # v0.56: the fallback used to fire only when READING the file raised.
        # If the file loaded but did not contain the named profile -- someone
        # renames "strict", or ships a trimmed policy -- profiles.get() gave
        # {} and every gate in compliance_result() silently became INFO. A
        # compliance tool then reported a pass for a run in which nothing was
        # evaluated. Fall back to the bundled defaults, and say so.
        value = DEFAULT_COMPLIANCE_PROFILES.get(profile, {})
        if profiles:
            print("WARNING: compliance profile '%s' is not defined in "
                  "DEM2DGED_Compliance_Policy.json; using the bundled "
                  "default for it instead of running with no thresholds."
                  % profile)

    return {k: float(v) for k, v in value.items()
            if k.startswith("max_") and isinstance(v, (int, float))}


def _gdal():
    try:
        from osgeo import gdal, osr
        return gdal, osr
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Terrain QA requires GDAL/osgeo. Activate the dedicated "
            "dem2dged environment first.") from exc


@dataclass
class SourceInspection:
    path: str
    horizontal_crs: Optional[str]
    vertical_crs: Optional[str]
    area_or_point: Optional[str]
    pixel_size: Tuple[float, float]
    origin: Tuple[float, float]
    extent: Tuple[float, float, float, float]
    raster_size: Tuple[int, int]
    nodata: Optional[float]
    data_type: str
    valid_range: Optional[Tuple[float, float]]
    warnings: List[str]


def _srs_name(wkt: str) -> Optional[str]:
    """Return a stable authority/name label for a horizontal CRS WKT."""
    if not wkt:
        return None
    try:
        _, osr = _gdal()
        s = osr.SpatialReference(wkt=wkt)
        if s.IsCompound():
            s = s.Clone()
            s.StripVertical()
        auth = s.GetAuthorityCode(None)
        if auth:
            return "%s:%s" % (s.GetAuthorityName(None) or "EPSG", auth)
        return s.GetName() or None
    except Exception:
        return None


def _vertical_srs_name(wkt: str) -> Optional[str]:
    if not wkt:
        return None
    try:
        _, osr = _gdal()
        s = osr.SpatialReference(wkt=wkt)
        for node in ("VERT_CS", "VERTCRS"):
            code = s.GetAuthorityCode(node)
            if code:
                auth = s.GetAuthorityName(node) or "EPSG"
                return "%s:%s" % (auth, code)
        return None
    except Exception:
        return None


_INSPECTION_CACHE: Dict[Any, "SourceInspection"] = {}


def inspect_source(path: str, use_cache: bool = True) -> SourceInspection:
    """Read source metadata and basic value statistics without modifying it.

    v0.56 -- TWO COSTS REMOVED, NO BEHAVIOUR CHANGED.

    (1) It used to call band.ReadAsArray() with NO WINDOW and then cast the
        result to float64 -- 4x the file size in RAM for an Int16 source --
        purely to obtain a minimum and a maximum. MEASURED: an 8 MB Int16
        probe built a 32 MB working array; a 4 GB delivery source would need
        16 GB. Every other raster reader in this project (compute_tile_stats,
        clamp_tile_to_range, build_prefiltered_source) already streams.
        band.ComputeRasterMinMax(False) is exact, NoData-aware, and streamed
        by GDAL itself.

        This mattered more than it looks: BOTH call sites wrap the call in
        "except Exception", and MemoryError IS an Exception -- so on a large
        source the failure degraded to a missing source_inspection.json and a
        debug-level note. The operator saw a multi-minute stall, no
        explanation, and a silently incomplete delivery.

    (2) It ran TWICE per CLI conversion: dem2dged.py's main() inspects the
        source, then hands off to dem2dged_geo/utm.main(), which inspects it
        again. Those run in the same process, so a small cache keyed on
        (path, mtime, size) collapses the second call to a dict lookup while
        still re-reading a file that has actually changed on disk. Pass
        use_cache=False to force a fresh read.
    """
    gdal, _ = _gdal()

    cache_key = None
    try:
        st = os.stat(path)
        cache_key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        cache_key = None
    if use_cache and cache_key is not None and cache_key in _INSPECTION_CACHE:
        return _INSPECTION_CACHE[cache_key]

    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError("GDAL cannot open source raster: %s" % path)
    gt = ds.GetGeoTransform()
    width, height = ds.RasterXSize, ds.RasterYSize
    x0, y0, rx, ry = gt[0], gt[3], gt[1], gt[5]
    x1 = x0 + width * rx
    y1 = y0 + height * ry
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    valid = None
    warnings: List[str] = []
    # v0.56: streamed by GDAL, NoData-aware, exact (approx_ok = False).
    # Returns None / raises on an all-NoData band, which is a legitimate
    # "no valid range" answer rather than an error worth propagating.
    try:
        vmin, vmax = band.ComputeRasterMinMax(False)
        if vmin == vmin and vmax == vmax:          # both finite, not NaN
            valid = (float(vmin), float(vmax))
    except Exception:
        valid = None
    if not ds.GetProjection():
        warnings.append("horizontal CRS is missing")
    if ds.GetMetadataItem("AREA_OR_POINT") is None:
        warnings.append("AREA_OR_POINT is missing; registration is ambiguous")
    info = SourceInspection(
        path=os.path.abspath(path),
        horizontal_crs=_srs_name(ds.GetProjection()),
        vertical_crs=_vertical_srs_name(ds.GetProjection()),
        area_or_point=ds.GetMetadataItem("AREA_OR_POINT"),
        pixel_size=(float(rx), float(ry)),
        origin=(float(x0), float(y0)),
        extent=(min(x0, x1), min(y1, y0), max(x0, x1), max(y0, y1)),
        raster_size=(int(width), int(height)),
        nodata=float(nodata) if nodata is not None else None,
        data_type=gdal.GetDataTypeName(band.DataType),
        valid_range=valid,
        warnings=warnings,
    )
    if cache_key is not None:
        _INSPECTION_CACHE[cache_key] = info
    return info


def write_inspection_json(info: SourceInspection, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(info), f, indent=2, ensure_ascii=False)


def grid_phase(origin: Sequence[float], reference: Sequence[float], pixel: Sequence[float]) -> Tuple[float, float]:
    """Return normalized x/y phase in pixel units (0 means aligned)."""
    out = []
    for a, b, p in zip(origin, reference, pixel):
        if not p:
            out.append(float("nan"))
        else:
            q = ((a - b) / abs(p)) % 1.0
            out.append(min(q, 1.0 - q))
    return float(out[0]), float(out[1])


def grid_compatibility(source: SourceInspection, target: Dict[str, Any], tolerance: float = 1e-8) -> Dict[str, Any]:
    """Compare source metadata with a target grid description."""
    pixel = tuple(float(x) for x in target["pixel_size"])
    phase = grid_phase(source.origin, target["origin"], pixel)
    same_pixel = all(abs(a - b) <= tolerance for a, b in zip(source.pixel_size, pixel))
    same_crs = (not target.get("crs") or source.horizontal_crs == target.get("crs"))
    same_reg = (not target.get("area_or_point") or source.area_or_point == target.get("area_or_point"))
    same_phase = phase[0] <= tolerance and phase[1] <= tolerance
    direct = bool(same_pixel and same_crs and same_reg and same_phase and target.get("same_extent", False))
    return {
        "same_pixel_size": same_pixel,
        "same_crs": same_crs,
        "same_registration": same_reg,
        "phase_pixels": phase,
        "same_phase": same_phase,
        "direct_copy_eligible": direct,
        "strategy": "direct-copy" if direct else ("aligned-warp" if same_pixel else "resample-warp"),
    }


def _metrics(diff):
    import numpy as np
    d = np.asarray(diff, dtype="float64")
    d = d[np.isfinite(d)]
    if d.size == 0:
        return {"count": 0, "mae": None, "rmse": None, "bias": None,
                "stddev": None, "p90": None, "bias_removed_p90": None,
                "p95": None, "p99": None, "max": None}
    ad = np.abs(d)
    centered = np.abs(d - d.mean())
    return {"count": int(d.size), "mae": float(ad.mean()),
            "rmse": float(math.sqrt((d * d).mean())), "bias": float(d.mean()),
            "stddev": float(d.std()), "p90": float(np.percentile(ad, 90)),
            "bias_removed_p90": float(np.percentile(centered, 90)),
            "p95": float(np.percentile(ad, 95)), "p99": float(np.percentile(ad, 99)),
            "max": float(ad.max())}


def terrain_metrics(source_array, output_array, nodata: Optional[float] = None) -> Dict[str, Any]:
    """Compute robust error metrics for two arrays on the same grid."""
    import numpy as np
    a = np.asarray(source_array, dtype="float64")
    b = np.asarray(output_array, dtype="float64")
    if a.shape != b.shape:
        raise ValueError("source/output arrays must have identical shapes")
    mask = np.isfinite(a) & np.isfinite(b)
    if nodata is not None:
        mask &= ~np.isclose(a, nodata) & ~np.isclose(b, nodata)
    return _metrics((b - a)[mask])


def slope_error_bins(source_array, output_array, pixel_size: Tuple[float, float], nodata: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    import numpy as np
    a = np.asarray(source_array, dtype="float64")
    b = np.asarray(output_array, dtype="float64")
    sx = abs(float(pixel_size[0])) or 1.0
    sy = abs(float(pixel_size[1])) or 1.0
    gy, gx = np.gradient(a, sy, sx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    d = b - a
    mask = np.isfinite(a) & np.isfinite(b) & np.isfinite(slope)
    if nodata is not None:
        mask &= ~np.isclose(a, nodata) & ~np.isclose(b, nodata)
    bins = [(0, 5), (5, 15), (15, 30), (30, 45), (45, 90.1)]
    return {"%g-%g deg" % (lo, hi): _metrics(d[mask & (slope >= lo) & (slope < hi)]) for lo, hi in bins}


def metric_pixel_size(pixel_size: Tuple[float, float], projection: str,
                      center_latitude: float = 0.0) -> Tuple[float, float]:
    """Convert geographic degree spacing to approximate metre spacing."""
    x, y = abs(float(pixel_size[0])), abs(float(pixel_size[1]))
    if projection:
        try:
            _, osr = _gdal()
            srs = osr.SpatialReference(wkt=projection)
            if srs.IsGeographic():
                latitude = max(-89.999, min(89.999, float(center_latitude)))
                x *= 111320.0 * abs(math.cos(math.radians(latitude)))
                y *= 110574.0
        except Exception:
            pass
    return x or 1.0, y or 1.0


def slope_percent_error_bins(source_array, output_array,
                             pixel_size: Tuple[float, float],
                             nodata: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """Report error by percent-slope, including the DGIWG 20% boundary."""
    import numpy as np
    a = np.asarray(source_array, dtype="float64")
    b = np.asarray(output_array, dtype="float64")
    sx = abs(float(pixel_size[0])) or 1.0
    sy = abs(float(pixel_size[1])) or 1.0
    gy, gx = np.gradient(a, sy, sx)
    slope = np.hypot(gx, gy) * 100.0
    d = b - a
    mask = np.isfinite(a) & np.isfinite(b) & np.isfinite(slope)
    if nodata is not None:
        mask &= ~np.isclose(a, nodata) & ~np.isclose(b, nodata)
    bins = [(0, 5), (5, 10), (10, 20), (20, 40), (40, float("inf"))]
    result = {}
    for lo, hi in bins:
        label = "%g-%s %%" % (lo, "inf" if math.isinf(hi) else "%g" % hi)
        result[label] = _metrics(d[mask & (slope >= lo) & (slope < hi)])
    return result


def mountain_preservation_metrics(source_array, output_array,
                                  pixel_size: Tuple[float, float],
                                  nodata: Optional[float] = None,
                                  error_threshold: float = 10.0) -> Dict[str, Any]:
    """Quantify steep-slope, peak and valley preservation on one grid."""
    import numpy as np
    source = np.asarray(source_array, dtype="float64")
    output = np.asarray(output_array, dtype="float64")
    mask = np.isfinite(source) & np.isfinite(output)
    if nodata is not None:
        mask &= ~np.isclose(source, nodata) & ~np.isclose(output, nodata)
    if not mask.any():
        return {"valid_count": 0, "predominant_slope_over_20_percent": None}

    sx = abs(float(pixel_size[0])) or 1.0
    sy = abs(float(pixel_size[1])) or 1.0
    gy, gx = np.gradient(source, sy, sx)
    slope_pct = np.hypot(gx, gy) * 100.0
    steep = mask & np.isfinite(slope_pct) & (slope_pct > 20.0)
    steep_fraction = float(steep.sum()) / float(mask.sum())
    diff = output - source
    values = source[mask]
    high = float(np.percentile(values, 99))
    low = float(np.percentile(values, 1))
    peaks = mask & (source >= high)
    valleys = mask & (source <= low)

    # Local extrema use an eight-neighbour comparison.  Edges are excluded,
    # avoiding wrap-around artefacts from numpy.roll.
    interior = mask.copy()
    if source.shape[0] > 2 and source.shape[1] > 2:
        interior[[0, -1], :] = False
        interior[:, [0, -1]] = False
    local_peak = interior.copy()
    local_valley = interior.copy()
    for row_shift in (-1, 0, 1):
        for col_shift in (-1, 0, 1):
            if row_shift == 0 and col_shift == 0:
                continue
            neighbour = np.roll(np.roll(source, row_shift, axis=0), col_shift, axis=1)
            local_peak &= source >= neighbour
            local_valley &= source <= neighbour
    extreme_mask = peaks | valleys
    threshold_exceedance = float((mask & (np.abs(diff) > abs(float(error_threshold)))).sum()) / float(mask.sum())
    return {
        "valid_count": int(mask.sum()),
        "slope_over_20_percent_fraction": steep_fraction,
        "predominant_slope_over_20_percent": bool(steep_fraction > 0.5),
        "steep_slope_error": _metrics(diff[steep]),
        "upper_one_percent_error": _metrics(diff[peaks]),
        "lower_one_percent_error": _metrics(diff[valleys]),
        "extreme_one_percent_error": _metrics(diff[extreme_mask]),
        "local_peak_error": _metrics(diff[local_peak]),
        "local_valley_error": _metrics(diff[local_valley]),
        "error_threshold_m": abs(float(error_threshold)),
        "error_threshold_exceedance_fraction": threshold_exceedance,
    }


def compliance_result(structural_fail: bool, metrics: Dict[str, Any], thresholds: Dict[str, float], steep: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Apply a profile and return a machine-readable compliance decision."""
    checks = {}
    if structural_fail:
        checks["structural"] = {"status": "FAIL", "reason": "structural validator failure"}
    else:
        checks["structural"] = {"status": "PASS"}
    for key in ("bias", "rmse", "p95", "p99", "max"):
        limit = thresholds.get("max_" + key)
        value = metrics.get(key)
        if limit is None or value is None:
            checks[key] = {"status": "INFO", "value": value, "limit": limit}
        else:
            checks[key] = {"status": "PASS" if abs(value) <= limit else "FAIL",
                           "value": value, "limit": limit}
    statuses = [x["status"] for x in checks.values()]
    metric_statuses = [checks[k]["status"]
                       for k in ("bias", "rmse", "p95", "p99", "max")]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "WARN" in statuses:
        overall = "WARN"
    elif all(s == "INFO" for s in metric_statuses):
        # v0.56: every metric came back INFO, meaning no threshold was
        # applied to any of them -- the "informational" profile, or a
        # profile with no max_* keys. Reporting that as PASS contradicts the
        # principle dem2dged_compliance's own module docstring states:
        # missing evidence is NOT_EVALUATED and never PASS. Note the
        # structural check is deliberately excluded from this test, since it
        # always produces PASS or FAIL and would mask an unevaluated run.
        overall = "NOT_EVALUATED"
    else:
        overall = "PASS"
    return {"overall": overall, "checks": checks, "steep_slope": steep or {}}


def diagnose_terrain(result: Dict[str, Any]) -> List[str]:
    """Turn metrics into actionable, non-authoritative explanations."""
    m = result.get("metrics", {})
    notes: List[str] = []
    bias = abs(m.get("bias")) if m.get("bias") is not None else None
    rmse = m.get("rmse")
    p95 = m.get("p95")
    if bias is not None and bias >= 5.0:
        notes.append("Large systematic vertical bias detected; verify source vertical datum, geoid model and elevation units before changing resampling.")
    steep = result.get("slope_bins", {}).get("45-90.1 deg", {})
    if steep.get("rmse") is not None and rmse and steep["rmse"] >= max(2.0 * rmse, 5.0):
        notes.append("Error is concentrated on very steep terrain; inspect grid registration and compare Near/Bilinear/Optimize before changing product level.")
    offsets = result.get("offset_sensitivity", {})
    center = offsets.get("+0.0,+0.0", {}).get("rmse")
    if center is not None:
        alternatives = [v.get("rmse") for k, v in offsets.items()
                        if k != "+0.0,+0.0" and v.get("rmse") is not None]
        if alternatives and center > 0 and min(alternatives) < center * 0.75:
            notes.append("A half-pixel offset reconstructs the source substantially better; investigate PixelIsArea/PixelIsPoint and grid phase alignment.")
    if p95 is not None and m.get("max") is not None and p95 > 0 and m["max"] > 3.0 * p95:
        notes.append("Maximum error is much larger than P95; likely isolated outlier(s). Review elevation_diff.tif and error_mask.tif before rejecting the whole delivery.")
    if not notes:
        notes.append("No single dominant failure pattern was detected. Review the metrics, slope bins and difference raster together with the source DEM.")
    return notes


def write_terrain_report(result: Dict[str, Any], path: str) -> None:
    """Write a readable text report for operators and ticket attachments."""
    lines = ["DEM2DGED Terrain-Fidelity QA", "=" * 32,
             "Source: %s" % result.get("source", ""),
             "Resampling: %s" % result.get("resample", ""), "",
             "Metrics:"]
    for k, v in result.get("metrics", {}).items():
        lines.append("  %-8s %s" % (k, "n/a" if v is None else v))
    lines.append("")
    lines.append("Slope bins:")
    for k, values in result.get("slope_bins", {}).items():
        lines.append("  %s: RMSE=%s P95=%s count=%s" %
                     (k, values.get("rmse"), values.get("p95"), values.get("count")))
    if result.get("mountain_qa"):
        mountain = result.get("mountain_metrics", {})
        lines.extend(["", "Mountain terrain precision QA:",
                      "  slope >20%% fraction: %s" % mountain.get("slope_over_20_percent_fraction"),
                      "  predominant >20%%: %s" % mountain.get("predominant_slope_over_20_percent"),
                      "  error-mask fraction: %s" % mountain.get("error_threshold_exceedance_fraction"),
                      "  DGIWG vertical accuracy factor: %s" % result.get("dgiwg_vertical_accuracy_factor")])
    lines.append("")
    lines.append("Automatic diagnostic guidance:")
    for note in result.get("diagnostics", []):
        lines.append("  - " + note)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_json(value: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def check_vertical_operation(horizontal_crs: str,
                             source_vertical_epsg: str,
                             target_vertical_epsg: str = "3855",
                             extent: Optional[Sequence[float]] = None
                             ) -> Dict[str, Any]:
    """Prove that PROJ can perform the requested vertical transformation.

    GDAL/PROJ may otherwise fall back to a ballpark or unchanged-height
    operation when a required geoid grid is unavailable.  This preflight
    explicitly rejects ballpark operations and asks PROJ for its best
    operation before conversion starts.
    """
    _, osr = _gdal()
    source_vertical = str(source_vertical_epsg or "").replace("EPSG:", "")
    target_vertical = str(target_vertical_epsg or "").replace("EPSG:", "")
    result: Dict[str, Any] = {
        "status": "NOT_EVALUATED",
        "horizontal_crs": horizontal_crs,
        "source_vertical_epsg": source_vertical or None,
        "target_vertical_epsg": target_vertical or None,
        "ballpark_allowed": False,
        "only_best": True,
        "proj_search_paths": list(osr.GetPROJSearchPaths()),
    }
    if not horizontal_crs or not source_vertical:
        result["reason"] = "horizontal CRS and source vertical EPSG are required"
        return result
    if source_vertical == target_vertical:
        result.update({"status": "PASS", "operation": "identity",
                       "vertical_shift_m": 0.0})
        return result

    source_compound = "%s+%s" % (horizontal_crs, source_vertical)
    target_compound = "%s+%s" % (horizontal_crs, target_vertical)
    result["source_compound_crs"] = source_compound
    result["target_compound_crs"] = target_compound
    previous_exceptions = (osr.GetUseExceptions()
                           if hasattr(osr, "GetUseExceptions") else False)
    try:
        osr.UseExceptions()
        source_srs = osr.SpatialReference()
        target_srs = osr.SpatialReference()
        source_srs.SetFromUserInput(source_compound)
        target_srs.SetFromUserInput(target_compound)
        for srs in (source_srs, target_srs):
            if hasattr(srs, "SetAxisMappingStrategy"):
                srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

        options = osr.CoordinateTransformationOptions()
        options.SetBallparkAllowed(False)
        options.SetOnlyBest(True)

        x = y = 0.0
        if extent and len(extent) == 4:
            x = (float(extent[0]) + float(extent[2])) / 2.0
            y = (float(extent[1]) + float(extent[3])) / 2.0
            # AOI is always longitude/latitude even when the source is
            # projected.  Supplying it helps PROJ choose the correct grid.
            try:
                horizontal = source_srs.Clone()
                horizontal.StripVertical()
                wgs84 = osr.SpatialReference()
                wgs84.ImportFromEPSG(4326)
                for srs in (horizontal, wgs84):
                    if hasattr(srs, "SetAxisMappingStrategy"):
                        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                to_wgs84 = osr.CoordinateTransformation(horizontal, wgs84)
                lon, lat, _ = to_wgs84.TransformPoint(x, y, 0.0)
                options.SetAreaOfInterest(lon - 0.01, lat - 0.01,
                                          lon + 0.01, lat + 0.01)
                result["area_of_interest"] = [lon - 0.01, lat - 0.01,
                                                lon + 0.01, lat + 0.01]
            except Exception:
                pass

        transform = osr.CreateCoordinateTransformation(
            source_srs, target_srs, options)
        ox, oy, oz = transform.TransformPoint(x, y, 0.0)
        result.update({
            "status": "PASS",
            "sample_input": [x, y, 0.0],
            "sample_output": [float(ox), float(oy), float(oz)],
            "vertical_shift_m": float(oz),
            "operation": "strict non-ballpark PROJ operation available",
        })
    except Exception as exc:
        result.update({
            "status": "FAIL",
            "reason": str(exc),
            "remediation": (
                "Install the required geoid grid in a listed PROJ search "
                "path, or supply elevations already referenced to EPSG:%s."
                % target_vertical),
        })
    finally:
        if not previous_exceptions:
            osr.DontUseExceptions()
    return result


def error_budget_metrics(source_array, output_array, reference_array,
                         nodata: Optional[float] = None) -> Dict[str, Any]:
    """Separate source, conversion and final errors on one common grid.

    ``output-reference = (source-reference) + (output-source)``.  RMSE and
    MAE are deliberately not subtracted: the MSE identity includes the
    cross term, which records correlation between source and conversion
    errors.
    """
    import numpy as np
    source = np.asarray(source_array, dtype="float64")
    output = np.asarray(output_array, dtype="float64")
    reference = np.asarray(reference_array, dtype="float64")
    if source.shape != output.shape or source.shape != reference.shape:
        raise ValueError("source/output/reference arrays must have identical shapes")
    valid = np.isfinite(source) & np.isfinite(output) & np.isfinite(reference)
    if nodata is not None:
        valid &= (~np.isclose(source, nodata) & ~np.isclose(output, nodata)
                  & ~np.isclose(reference, nodata))
    source_error = source[valid] - reference[valid]
    conversion_error = output[valid] - source[valid]
    output_error = output[valid] - reference[valid]
    if not output_error.size:
        return {"valid_count": 0, "source_error": _metrics([]),
                "conversion_error": _metrics([]), "output_error": _metrics([]),
                "mse_decomposition": {}}
    mse_source = float(np.mean(source_error ** 2))
    mse_conversion = float(np.mean(conversion_error ** 2))
    cross_term = float(2.0 * np.mean(source_error * conversion_error))
    mse_output = float(np.mean(output_error ** 2))
    closure = output_error - source_error - conversion_error
    return {
        "valid_count": int(output_error.size),
        "identity": "output-reference = source-reference + output-source",
        "source_error": _metrics(source_error),
        "conversion_error": _metrics(conversion_error),
        "output_error": _metrics(output_error),
        "mse_decomposition": {
            "source_mse": mse_source,
            "conversion_mse": mse_conversion,
            "cross_term_2_mean_source_x_conversion": cross_term,
            "reconstructed_output_mse": mse_source + mse_conversion + cross_term,
            "output_mse": mse_output,
            "closure": mse_output - (mse_source + mse_conversion + cross_term),
        },
        "error_vector_closure_max_abs": float(np.max(np.abs(closure))),
        "warning": "Do not subtract MAE or RMSE; use the vector/MSE decomposition.",
    }


def run_error_budget_qa(tile_folder: str, source_path: str,
                        reference_path: str,
                        output_dir: Optional[str] = None,
                        resample: str = "bilinear") -> Dict[str, Any]:
    """Compute the three-part error budget on the exact delivered DGED grid."""
    import numpy as np
    gdal, osr = _gdal()
    out = output_dir or os.path.join(tile_folder, "validation")
    os.makedirs(out, exist_ok=True)
    tiles = [os.path.join(tile_folder, n) for n in sorted(os.listdir(tile_folder))
             if n.lower().endswith(".tif") and n.upper().startswith("DGEDL")
             and os.path.isfile(os.path.join(tile_folder, n))]
    if not tiles:
        raise RuntimeError("no DGED GeoTIFF tiles found in %s" % tile_folder)
    vrt_path = "/vsimem/dem2dged_budget_%s.vrt" % os.getpid()
    vrt = gdal.BuildVRT(vrt_path, tiles)
    source_ds = gdal.Open(source_path, gdal.GA_ReadOnly)
    reference_ds = gdal.Open(reference_path, gdal.GA_ReadOnly)
    if vrt is None or source_ds is None or reference_ds is None:
        gdal.Unlink(vrt_path)
        raise RuntimeError("could not open source/reference or build DGED mosaic")
    try:
        gt = vrt.GetGeoTransform()
        bounds = [gt[0], gt[3] + vrt.RasterYSize * gt[5],
                  gt[0] + vrt.RasterXSize * gt[1], gt[3]]
        dst_srs = vrt.GetProjection()
        try:
            horizontal = osr.SpatialReference(wkt=dst_srs)
            horizontal.StripVertical()
            dst_srs = horizontal.ExportToWkt() or dst_srs
        except Exception:
            pass

        def warp_to_grid(dataset):
            return gdal.Warp(
                "", dataset, format="MEM", dstSRS=dst_srs,
                outputBounds=bounds, width=vrt.RasterXSize,
                height=vrt.RasterYSize, resampleAlg=resample,
                dstNodata=NODATA_FALLBACK, outputType=gdal.GDT_Float32)

        source_grid = warp_to_grid(source_ds)
        reference_grid = warp_to_grid(reference_ds)
        if source_grid is None or reference_grid is None:
            raise RuntimeError("could not align source/reference to the DGED grid")
        output_array = vrt.GetRasterBand(1).ReadAsArray().astype("float64")
        source_array = source_grid.GetRasterBand(1).ReadAsArray().astype("float64")
        reference_array = reference_grid.GetRasterBand(1).ReadAsArray().astype("float64")
        output_nodata = vrt.GetRasterBand(1).GetNoDataValue()
        valid = (np.isfinite(output_array) & np.isfinite(source_array)
                 & np.isfinite(reference_array))
        if output_nodata is not None:
            valid &= ~np.isclose(output_array, float(output_nodata))
        valid &= (~np.isclose(source_array, NODATA_FALLBACK)
                  & ~np.isclose(reference_array, NODATA_FALLBACK))
        masked_source = np.where(valid, source_array, np.nan)
        masked_output = np.where(valid, output_array, np.nan)
        masked_reference = np.where(valid, reference_array, np.nan)
        result = error_budget_metrics(masked_source, masked_output,
                                      masked_reference)
        result.update({
            "source": os.path.abspath(source_path),
            "independent_reference": os.path.abspath(reference_path),
            "tile_folder": os.path.abspath(tile_folder),
            "resample": resample,
            "grid": {"width": int(vrt.RasterXSize),
                     "height": int(vrt.RasterYSize),
                     "geotransform": list(gt)},
            "vertical_reference_assumption": (
                "Source and independent reference values must already be in "
                "the delivered vertical reference; this QA performs horizontal "
                "alignment only and never applies a hidden geoid shift."),
        })
        write_json(result, os.path.join(out, "error_budget.json"))
        return result
    finally:
        source_ds = None
        reference_ds = None
        vrt = None
        gdal.Unlink(vrt_path)


def run_terrain_qa(tile_folder: str, source_path: str, output_dir: Optional[str] = None,
                   resample: str = "bilinear", full: bool = False,
                   error_threshold: float = 10.0,
                   mountain: bool = False,
                   comparison_type: str = "source_to_output") -> Dict[str, Any]:
    """Compare a delivered tile mosaic to a like-for-like source warp.

    This is intentionally separate from the DGED structural validator: a
    structurally valid product can still have terrain error concentrated on
    steep slopes.  The function writes JSON, a difference raster and an error
    mask and returns the same dictionary for callers such as the GUI.  The
    comparison is always on the DGED grid, so its pixels represent DGED post
    spacing rather than the (usually finer) source DEM pixels.

    QA artefacts default to ``<tile_folder>/validation``.  Keeping them out
    of the tile folder prevents a later QA run from treating its own
    ``elevation_diff.tif`` / ``error_mask.tif`` as DGED tiles.
    """
    import numpy as np
    gdal, osr = _gdal()
    out = output_dir or os.path.join(tile_folder, "validation")
    os.makedirs(out, exist_ok=True)
    tiles = [os.path.join(tile_folder, n) for n in sorted(os.listdir(tile_folder))
             if n.lower().endswith(".tif") and n.upper().startswith("DGEDL")
             and os.path.isfile(os.path.join(tile_folder, n))]
    if not tiles:
        raise RuntimeError("no DGED GeoTIFF tiles found in %s" % tile_folder)
    try:
        error_threshold = abs(float(error_threshold))
    except (TypeError, ValueError) as exc:
        raise ValueError("error_threshold must be a number of metres") from exc
    # The Python binding's BuildVRT signature differs across GDAL releases;
    # the destination extension already selects the VRT driver, so omit the
    # newer ``format=`` keyword for compatibility with GDAL 3.x builds.
    vrt_path = "/vsimem/dem2dged_terrain_%s.vrt" % os.getpid()
    vrt = gdal.BuildVRT(vrt_path, tiles)
    src = gdal.Open(source_path, gdal.GA_ReadOnly)
    if vrt is None or src is None:
        gdal.Unlink(vrt_path)
        raise RuntimeError("could not open source or build DGED mosaic")
    gt = vrt.GetGeoTransform()
    bounds = [gt[0], gt[3] + vrt.RasterYSize * gt[5],
              gt[0] + vrt.RasterXSize * gt[1], gt[3]]
    dst_srs = vrt.GetProjection()
    # Strip the vertical component for a source-shape comparison. The
    # converter's default mode labels EGM2008 without applying a geoid shift.
    try:
        s = osr.SpatialReference(wkt=dst_srs)
        s.StripVertical()
        dst_srs = s.ExportToWkt() or dst_srs
    except Exception:
        pass
    ref = gdal.Warp("", src, format="MEM", dstSRS=dst_srs,
                    outputBounds=bounds, width=vrt.RasterXSize,
                    height=vrt.RasterYSize, resampleAlg=resample,
                    dstNodata=NODATA_FALLBACK, outputType=gdal.GDT_Float32)
    if ref is None:
        vrt = None
        src = None
        gdal.Unlink(vrt_path)
        raise RuntimeError("could not warp the source DEM onto the DGED grid")
    a = vrt.GetRasterBand(1).ReadAsArray().astype("float64")
    b = ref.GetRasterBand(1).ReadAsArray().astype("float64")
    nodata = vrt.GetRasterBand(1).GetNoDataValue()
    nodata = NODATA_FALLBACK if nodata is None else float(nodata)
    valid = np.isfinite(a) & np.isfinite(b)
    valid &= ~np.isclose(a, nodata) & ~np.isclose(b, NODATA_FALLBACK)
    diff = np.full(a.shape, np.nan, dtype="float64")
    diff[valid] = a[valid] - b[valid]
    metrics = _metrics(diff[valid])
    center_latitude = gt[3] + 0.5 * vrt.RasterYSize * gt[5]
    pixel_metres = metric_pixel_size((gt[1], gt[5]), vrt.GetProjection(),
                                     center_latitude)
    slope_bins = slope_error_bins(b, a, pixel_metres, nodata=nodata)
    mountain = bool(mountain)
    full = bool(full or mountain)
    result: Dict[str, Any] = {"source": os.path.abspath(source_path),
                              "tiles": len(tiles), "resample": resample,
                              "metrics": metrics, "slope_bins": slope_bins,
                              "pixel_size_metres": pixel_metres,
                              "slope_percent_bins": {},
                              "mountain_qa": mountain,
                              "comparison_type": comparison_type,
                              "offset_sensitivity": {}}
    if mountain:
        result["slope_percent_bins"] = slope_percent_error_bins(
            b, a, pixel_metres, nodata=nodata)
        result["mountain_metrics"] = mountain_preservation_metrics(
            b, a, pixel_metres, nodata=nodata,
            error_threshold=error_threshold)
        result["dgiwg_vertical_accuracy_factor"] = (
            1.4 if result["mountain_metrics"].get(
                "predominant_slope_over_20_percent") else 1.0)
    if full:
        # A compact diagnostic: shift the source comparison grid by half a
        # post in each direction and measure the same overlap.
        for dx in (-0.5, 0.0, 0.5):
            for dy in (-0.5, 0.0, 0.5):
                key = "%+.1f,%+.1f" % (dx, dy)
                shifted = list(bounds)
                shifted[0] += dx * gt[1]; shifted[2] += dx * gt[1]
                shifted[1] += dy * abs(gt[5]); shifted[3] += dy * abs(gt[5])
                sw = gdal.Warp("", src, format="MEM", dstSRS=dst_srs,
                               outputBounds=shifted, width=vrt.RasterXSize,
                               height=vrt.RasterYSize, resampleAlg=resample,
                               dstNodata=NODATA_FALLBACK,
                               outputType=gdal.GDT_Float32)
                if sw is None:
                    raise RuntimeError("could not create an offset source comparison")
                sa = sw.GetRasterBand(1).ReadAsArray().astype("float64")
                m = valid & np.isfinite(sa) & ~np.isclose(sa, NODATA_FALLBACK)
                result["offset_sensitivity"][key] = _metrics((a - sa)[m])
                sw = None
    drv = gdal.GetDriverByName("GTiff")
    diff_path = os.path.join(out, "elevation_diff.tif")
    mask_path = os.path.join(out, "error_mask.tif")
    for path, array, dtype, nd in ((diff_path, np.where(np.isfinite(diff), diff, NODATA_FALLBACK), gdal.GDT_Float32, NODATA_FALLBACK),
                                   (mask_path, np.where(valid, (np.abs(diff) > error_threshold).astype("uint8"), 0), gdal.GDT_Byte, 0)):
        ds = drv.Create(path, vrt.RasterXSize, vrt.RasterYSize, 1, dtype,
                        options=["COMPRESS=LZW"])
        ds.SetGeoTransform(gt); ds.SetProjection(vrt.GetProjection())
        band = ds.GetRasterBand(1); band.SetNoDataValue(nd); band.WriteArray(array)
        ds.FlushCache(); ds = None
    result["error_threshold_m"] = error_threshold
    result["artifacts"] = {"difference": diff_path, "error_mask": mask_path}
    result["diagnostics"] = diagnose_terrain(result)
    write_json(result, os.path.join(out, "terrain_metrics.json"))
    write_terrain_report(result, os.path.join(out, "terrain_report.txt"))
    ref = None
    src = None
    vrt = None
    gdal.Unlink(vrt_path)
    return result
