# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.50.1
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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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
        value = profiles.get(profile, {})
    except Exception:
        value = DEFAULT_COMPLIANCE_PROFILES.get(profile, {})
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
    if not wkt:
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
    try:
        _, osr = _gdal()
        s = osr.SpatialReference(wkt=wkt)
        auth = s.GetAuthorityCode(None)
        return ("EPSG:" + auth) if auth else s.GetName()
    except Exception:
        return None


def inspect_source(path: str) -> SourceInspection:
    """Read source metadata and basic value statistics without modifying it."""
    gdal, _ = _gdal()
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
    arr = band.ReadAsArray()
    valid = None
    warnings: List[str] = []
    if arr is not None:
        import numpy as np
        a = np.asarray(arr, dtype="float64")
        mask = np.isfinite(a)
        if nodata is not None:
            mask &= ~np.isclose(a, float(nodata))
        if mask.any():
            valid = (float(a[mask].min()), float(a[mask].max()))
    if not ds.GetProjection():
        warnings.append("horizontal CRS is missing")
    if ds.GetMetadataItem("AREA_OR_POINT") is None:
        warnings.append("AREA_OR_POINT is missing; registration is ambiguous")
    return SourceInspection(
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
                "p95": None, "p99": None, "max": None}
    ad = np.abs(d)
    return {"count": int(d.size), "mae": float(ad.mean()),
            "rmse": float(math.sqrt((d * d).mean())), "bias": float(d.mean()),
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


def compliance_result(structural_fail: bool, metrics: Dict[str, Any], thresholds: Dict[str, float], steep: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Apply a profile and return a machine-readable compliance decision."""
    checks = {}
    if structural_fail:
        checks["structural"] = {"status": "FAIL", "reason": "structural validator failure"}
    else:
        checks["structural"] = {"status": "PASS"}
    for key in ("bias", "rmse", "p95", "max"):
        limit = thresholds.get("max_" + key)
        value = metrics.get(key)
        if limit is None or value is None:
            checks[key] = {"status": "INFO", "value": value, "limit": limit}
        else:
            checks[key] = {"status": "PASS" if abs(value) <= limit else "WARN", "value": value, "limit": limit}
    statuses = [x["status"] for x in checks.values()]
    overall = "FAIL" if "FAIL" in statuses else ("WARN" if "WARN" in statuses else "PASS")
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
    lines.append("")
    lines.append("Automatic diagnostic guidance:")
    for note in result.get("diagnostics", []):
        lines.append("  - " + note)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_json(value: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def run_terrain_qa(tile_folder: str, source_path: str, output_dir: Optional[str] = None,
                   resample: str = "bilinear", full: bool = False) -> Dict[str, Any]:
    """Compare a delivered tile mosaic to a like-for-like source warp.

    This is intentionally separate from the DGED structural validator: a
    structurally valid product can still have terrain error concentrated on
    steep slopes.  The function writes JSON, a difference raster and an error
    mask and returns the same dictionary for callers such as the GUI.
    """
    import numpy as np
    gdal, osr = _gdal()
    out = output_dir or tile_folder
    os.makedirs(out, exist_ok=True)
    tiles = [os.path.join(tile_folder, n) for n in os.listdir(tile_folder)
             if n.lower().endswith(".tif")]
    if not tiles:
        raise RuntimeError("no DGED GeoTIFF tiles found in %s" % tile_folder)
    # The Python binding's BuildVRT signature differs across GDAL releases;
    # the destination extension already selects the VRT driver, so omit the
    # newer ``format=`` keyword for compatibility with GDAL 3.x builds.
    vrt = gdal.BuildVRT("/vsimem/dem2dged_terrain_%s.vrt" % os.getpid(),
                        tiles)
    src = gdal.Open(source_path, gdal.GA_ReadOnly)
    if vrt is None or src is None:
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
    a = vrt.GetRasterBand(1).ReadAsArray().astype("float64")
    b = ref.GetRasterBand(1).ReadAsArray().astype("float64")
    nodata = vrt.GetRasterBand(1).GetNoDataValue()
    nodata = NODATA_FALLBACK if nodata is None else float(nodata)
    valid = np.isfinite(a) & np.isfinite(b)
    valid &= ~np.isclose(a, nodata) & ~np.isclose(b, NODATA_FALLBACK)
    diff = np.full(a.shape, np.nan, dtype="float64")
    diff[valid] = a[valid] - b[valid]
    metrics = _metrics(diff[valid])
    slope_bins = slope_error_bins(b, a, (gt[1], gt[5]), nodata=nodata)
    result: Dict[str, Any] = {"source": os.path.abspath(source_path),
                              "tiles": len(tiles), "resample": resample,
                              "metrics": metrics, "slope_bins": slope_bins,
                              "offset_sensitivity": {}}
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
                sa = sw.GetRasterBand(1).ReadAsArray().astype("float64")
                m = valid & np.isfinite(sa) & ~np.isclose(sa, NODATA_FALLBACK)
                result["offset_sensitivity"][key] = _metrics((a - sa)[m])
    drv = gdal.GetDriverByName("GTiff")
    diff_path = os.path.join(out, "elevation_diff.tif")
    mask_path = os.path.join(out, "error_mask.tif")
    for path, array, dtype, nd in ((diff_path, np.where(np.isfinite(diff), diff, NODATA_FALLBACK), gdal.GDT_Float32, NODATA_FALLBACK),
                                   (mask_path, np.where(valid, (np.abs(diff) > 10).astype("uint8"), 0), gdal.GDT_Byte, 0)):
        ds = drv.Create(path, vrt.RasterXSize, vrt.RasterYSize, 1, dtype,
                        options=["COMPRESS=LZW"])
        ds.SetGeoTransform(gt); ds.SetProjection(vrt.GetProjection())
        band = ds.GetRasterBand(1); band.SetNoDataValue(nd); band.WriteArray(array)
        ds.FlushCache(); ds = None
    result["artifacts"] = {"difference": diff_path, "error_mask": mask_path}
    result["diagnostics"] = diagnose_terrain(result)
    write_json(result, os.path.join(out, "terrain_metrics.json"))
    write_terrain_report(result, os.path.join(out, "terrain_report.txt"))
    return result
