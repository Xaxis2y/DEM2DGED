# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.10
#
# Regression tests for v0.61.5: content-based reference independence.
# Through v0.61.4 only the file path and SHA-256 were compared, so a
# resampled, re-gridded or constant-offset copy of the conversion source was
# accepted as "independent" accuracy evidence.

import pytest

import dem2dged_compliance as c


# ---- pure decision logic (no GDAL) ----------------------------------------

def _sim(stddev, count=5000, method="bilinear"):
    return {"min_stddev_m": stddev, "count": count, "best_method": method}


def test_same_path_and_same_hash_fail():
    assert c.judge_reference_independence(True, False)["status"] == "FAIL"
    assert c.judge_reference_independence(False, True)["status"] == "FAIL"


def test_resampled_copy_fails():
    r = c.judge_reference_independence(False, False, _sim(0.0004))
    assert r["independent"] is False and r["status"] == "FAIL"
    assert "derived" in r["reason"]


def test_independent_surface_passes():
    r = c.judge_reference_independence(False, False, _sim(0.12))
    assert r["independent"] is True and r["status"] == "PASS"


def test_limit_is_inclusive():
    r = c.judge_reference_independence(
        False, False, _sim(c.REFERENCE_DERIVED_STDDEV_M))
    assert r["status"] == "FAIL"


@pytest.mark.parametrize("similarity", [
    None, {"error": "no overlap"}, _sim(0.2, count=10), _sim(None)])
def test_unverifiable_independence_is_not_evaluated(similarity):
    r = c.judge_reference_independence(False, False, similarity)
    assert r["independent"] is None and r["status"] == "NOT_EVALUATED"


def test_external_accuracy_uses_independence_evidence():
    evidence = c.judge_reference_independence(False, False, _sim(0.0001))
    section = c.external_accuracy(
        {"count": 10, "p90": 0.1, "bias_removed_p90": 0.05}, "6",
        reference_independent=False, reference_identifier="X",
        accuracy_method="Y", horizontal_ce90_m=1.0,
        horizontal_random_90_m=0.3, relative_horizontal_90_m=0.8,
        relative_vertical_90_m=0.4, independence_evidence=evidence)
    check = section["checks"]["source_reference_independence"]
    assert check["status"] == "FAIL"
    assert check["content_check"]["min_stddev_m"] == 0.0001
    assert section["status"] == "FAIL"


# ---- GDAL end-to-end screen -----------------------------------------------

def _write(path, arr, gt, epsg=32618):
    from osgeo import gdal, osr
    ds = gdal.GetDriverByName("GTiff").Create(
        str(path), arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767)
    band.WriteArray(arr)
    ds = None


@pytest.fixture
def rasters(tmp_path):
    np = pytest.importorskip("numpy")
    gdal = pytest.importorskip("osgeo.gdal")
    gdal.UseExceptions()
    n = 400
    ys, xs = np.mgrid[0:n, 0:n]
    base = (150 + 30 * np.sin(xs / 37.0) + 22 * np.cos(ys / 29.0)
            + 0.05 * xs).astype("float32")
    gt = (500000.0, 1.0, 0.0, 4500400.0, 0.0, -1.0)
    src = tmp_path / "source.tif"
    _write(src, base + np.random.default_rng(1).normal(0, 0.05, base.shape)
           .astype("float32"), gt)
    paths = {"src": str(src)}
    # independent: same terrain, different measurement noise
    ind = tmp_path / "independent.tif"
    _write(ind, base + np.random.default_rng(2).normal(0, 0.10, base.shape)
           .astype("float32"), gt)
    paths["independent"] = str(ind)
    # constant-offset copy on the same grid (e.g. a datum label change)
    off = tmp_path / "offset.tif"
    arr = gdal.Open(str(src)).ReadAsArray()
    _write(off, arr + np.float32(3.25), gt)
    paths["offset"] = str(off)
    # resampled and re-gridded copy (1.7 m posts, shifted origin)
    for method in ("bilinear", "cubic", "near", "average", "mode"):
        out = tmp_path / ("regrid_%s.tif" % method)
        gdal.Warp(str(out), str(src), xRes=1.7, yRes=1.7,
                  outputBounds=(500010.3, 4500010.3, 500390.3, 4500390.3),
                  resampleAlg=method)
        paths["regrid_" + method] = str(out)
    return paths


def test_gdal_independent_reference_passes(rasters):
    from dem2dged_terrain import assess_reference_independence
    r = assess_reference_independence(rasters["src"], rasters["independent"])
    assert r["status"] == "PASS", r


def test_gdal_offset_copy_fails(rasters):
    from dem2dged_terrain import assess_reference_independence
    r = assess_reference_independence(rasters["src"], rasters["offset"])
    assert r["status"] == "FAIL", r
    assert abs(r["content_check"]["bias_at_best_m"] + 3.25) < 1e-3


@pytest.mark.parametrize("method", ["bilinear", "cubic", "near", "average",
                                    "mode"])
def test_gdal_resampled_copy_fails(rasters, method):
    from dem2dged_terrain import assess_reference_independence
    r = assess_reference_independence(rasters["src"],
                                      rasters["regrid_" + method])
    assert r["status"] == "FAIL", r


def test_gdal_identical_copy_fails_by_hash(rasters, tmp_path):
    import shutil
    from dem2dged_terrain import assess_reference_independence
    dup = tmp_path / "dup.tif"
    shutil.copyfile(rasters["src"], dup)
    r = assess_reference_independence(rasters["src"], str(dup))
    assert r["status"] == "FAIL" and r["same_sha256"] is True
