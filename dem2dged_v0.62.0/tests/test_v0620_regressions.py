# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.0
"""v0.62.0: reference finder. Offline: the catalog services are faked and the
'remote' dataset is a local GeoTIFF, so no network is used."""

import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

gdal = pytest.importorskip("osgeo.gdal")
from osgeo import osr  # noqa: E402

import dem2dged_reference as dr  # noqa: E402


def _make_tif(path, epsg=3979, x0=1_500_000.0, y0=-400_000.0, cells=600, pix=1.0, nodata=-9999.0):
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, cells, cells, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, pix, 0, y0, 0, -pix))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    yy, xx = np.mgrid[0:cells, 0:cells]
    band.WriteArray((100 + 0.01 * xx + 0.02 * yy).astype("float32"))
    ds.FlushCache()
    ds = None
    return path


def _lonlat_box_of(path, pad=0.0):
    return dr.extent_wgs84(path, buffer_deg=pad)


def test_catalog_loads_and_has_ca_us():
    catalog = dr.load_catalog(os.path.join(ROOT, "reference_catalog.json"))
    countries = {s["country"] for s in catalog["sources"]}
    assert {"CA", "US"} <= countries
    for source in catalog["sources"]:
        assert source["license"] and source["vertical_datum"] and source["spec_url"]


def test_countries_for_bbox():
    assert "CA" in dr.countries_for_bbox((-75.8, 45.3, -75.6, 45.5))      # border: both may match
    assert dr.countries_for_bbox((-110.0, 60.0, -109.0, 61.0)) == ["CA"]
    assert dr.countries_for_bbox((-77.05, 38.88, -77.03, 38.90)) == ["US"]
    assert dr.countries_for_bbox((0, 0, 1, 1)) == []


def test_suitability_three_to_one_rule():
    assert dr.suitability(0.5, "3")[0] == "OK"
    assert dr.suitability(0.5, "4")[0] == "TOO_COARSE"
    assert dr.suitability(0.17, "4")[0] == "OK"
    assert dr.suitability(0.17, "5")[0] == "MARGINAL"
    assert dr.suitability(0.17, "6")[0] == "TOO_COARSE"
    assert dr.suitability(None, "5")[0] == "UNKNOWN"
    assert dr.suitability(0.17, "99")[0] == "UNKNOWN"


def test_extent_and_clip_local_raster(tmp_path):
    src = _make_tif(str(tmp_path / "ref.tif"))
    box = dr.extent_wgs84(src, buffer_deg=0.0)
    inner = (box[0] + (box[2] - box[0]) * 0.3, box[1] + (box[3] - box[1]) * 0.3,
             box[0] + (box[2] - box[0]) * 0.6, box[1] + (box[3] - box[1]) * 0.6)
    out = str(tmp_path / "clip.tif")
    stats = dr.clip_window(src, inner, out)
    ds = gdal.Open(out)
    assert 0 < ds.RasterXSize < 600 and 0 < ds.RasterYSize < 600
    assert ds.GetGeoTransform()[1] == 1.0              # no resampling
    assert stats["valid_fraction"] == 1.0
    # clipped values are the original cells, not interpolated
    dfull = gdal.Open(src)
    full = dfull.GetRasterBand(1).ReadAsArray()
    part = ds.GetRasterBand(1).ReadAsArray()
    gt_full, gt_part = dfull.GetGeoTransform(), ds.GetGeoTransform()
    xo = int(round((gt_part[0] - gt_full[0]) / 1.0))
    yo = int(round((gt_full[3] - gt_part[3]) / 1.0))
    assert np.array_equal(part, full[yo:yo + part.shape[0], xo:xo + part.shape[1]])


def test_clip_rejects_no_overlap_and_too_big(tmp_path):
    src = _make_tif(str(tmp_path / "ref.tif"))
    with pytest.raises(RuntimeError, match="does not overlap"):
        dr.clip_window(src, (0.0, 0.0, 0.001, 0.001), str(tmp_path / "x.tif"))
    box = dr.extent_wgs84(src, buffer_deg=0.0)
    with pytest.raises(RuntimeError, match="exceeds the limit"):
        dr.clip_window(src, box, str(tmp_path / "y.tif"), max_cells=1000)


FAKE_STAC = {"features": [
    {"id": "SNCA-Eastern_Ontario_2022-1m", "bbox": [-77.4, 43.5, -74.2, 46.0],
     "properties": {"datetime": "2022-04-30T12:00:00Z", "proj:epsg": 3979},
     "assets": {"dtm": {"href": "https://example.invalid/a-dtm.tif"},
                "dsm": {"href": "https://example.invalid/a-dsm.tif"}}},
    {"id": "Other_2015-2m", "bbox": [-75.9, 45.3, -75.5, 45.6],
     "properties": {"datetime": "2015-06-01T12:00:00Z"},
     "assets": {"dtm": {"href": "https://example.invalid/b-dtm.tif"}}}]}
FAKE_TNM = {"total": 2, "items": [
    {"title": "USGS 1 Meter 18 x32y432 DC_2018", "sourceId": "abc", "downloadURL":
     "https://example.invalid/USGS_1M_18_x32y432.tif", "sizeInBytes": 55000000,
     "publicationDate": "2020-01-02", "boundingBox":
     {"minX": -77.1, "minY": 38.8, "maxX": -76.9, "maxY": 39.0}},
    {"title": "not a tif", "downloadURL": "https://example.invalid/x.zip"}]}


@pytest.fixture
def fake_net(monkeypatch):
    def fake_get(url, params=None, timeout=45, retries=2, log=None):
        return FAKE_STAC if "hrdem" in url else FAKE_TNM
    monkeypatch.setattr(dr, "http_get_json", fake_get)
    monkeypatch.setattr(dr, "probe_coverage", lambda *a, **k: {"valid_fraction": None, "error": "n/a"})
    return fake_get


def test_find_candidates_canada_and_us(fake_net):
    ca, errs = dr.find_candidates((-75.75, 45.38, -75.65, 45.44), "3")
    ca = [c for c in ca if c["country"] == "CA"]
    assert not errs and len(ca) == 2
    assert ca[0]["resolution_m"] == 1.0 and ca[0]["covers_whole_box"]
    assert ca[0]["suitability"] == "OK"
    us, _ = dr.find_candidates((-77.05, 38.88, -77.03, 38.90), "4")
    ids = {c["source_id"] for c in us}
    assert "us_3dep_1m" in ids
    one_m = [c for c in us if c["source_id"] == "us_3dep_1m"]
    assert len(one_m) == 1 and one_m[0]["resolution_m"] == 1.0   # .zip skipped


def test_query_failure_is_reported_not_raised(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(dr, "http_get_json", boom)
    found, errs = dr.find_candidates((-75.75, 45.38, -75.65, 45.44), "3")
    assert found == [] and errs and "offline" in errs[0]["error"]


def test_fetch_end_to_end_with_local_dataset(tmp_path, fake_net, monkeypatch):
    src = _make_tif(str(tmp_path / "ref.tif"))
    box = dr.extent_wgs84(src, buffer_deg=0.0)
    mid = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    bbox = (mid[0] - 0.0008, mid[1] - 0.0008, mid[0] + 0.0008, mid[1] + 0.0008)
    stac = {"features": [{"id": "Local_2024-1m", "bbox": list(box),
                          "properties": {"datetime": "2024-01-01T00:00:00Z"},
                          "assets": {"dtm": {"href": src}}}]}
    monkeypatch.setattr(dr, "http_get_json",
                        lambda url, params=None, **k: stac if "hrdem" in url else {"items": []})
    # force the search into Canada even though the synthetic raster sits elsewhere
    res = dr.fetch_reference(bbox=bbox, out_dir=str(tmp_path / "refs"), level="3",
                             countries=["CA"], source_vertical_epsg="6647",
                             log=dr.StepLog(str(tmp_path / "run.log"), echo=False))
    assert res["output"] and os.path.isfile(res["output"])
    side = json.load(open(res["sidecar"]))
    assert side["schema"] == dr.SIDECAR_SCHEMA and side["sha256"]
    assert side["reference_identifier"].startswith("ca_hrdem_lidar Local_2024-1m")
    assert any("Vertical datum check" in w for w in side["warnings"])
    assert any("Independence is NOT proven" in w for w in side["warnings"])
    assert side["suitability_for_level"]["result"] == "OK"


def test_list_only_downloads_nothing(tmp_path, fake_net):
    res = dr.fetch_reference(bbox=(-75.75, 45.38, -75.65, 45.44), out_dir=str(tmp_path / "r"),
                             level="3", list_only=True)
    assert res["candidates"] and res["output"] is None
    assert not (tmp_path / "r").exists()


def _make_empty_tif(path, **kw):
    ds = gdal.Open(_make_tif(path, **kw), gdal.GA_Update)
    ds.GetRasterBand(1).WriteArray(np.full((600, 600), -9999.0, dtype="float32"))
    ds.FlushCache()
    ds = None
    return path


def test_probe_measures_real_coverage(tmp_path):
    good = _make_tif(str(tmp_path / "good.tif"))
    empty = _make_empty_tif(str(tmp_path / "empty.tif"))
    box = dr.extent_wgs84(good, buffer_deg=0.0)
    mid = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    small = (mid[0] - 0.0008, mid[1] - 0.0008, mid[0] + 0.0008, mid[1] + 0.0008)
    assert dr.probe_coverage(good, small)["valid_fraction"] == 1.0
    assert dr.probe_coverage(empty, small)["valid_fraction"] == 0.0
    assert dr.probe_coverage(str(tmp_path / "missing.tif"), small)["valid_fraction"] is None


def test_fetch_skips_dataset_with_no_data_in_the_box(tmp_path, monkeypatch):
    good = _make_tif(str(tmp_path / "good.tif"))
    empty = _make_empty_tif(str(tmp_path / "empty.tif"))
    box = dr.extent_wgs84(good, buffer_deg=0.0)
    mid = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    small = (mid[0] - 0.0008, mid[1] - 0.0008, mid[0] + 0.0008, mid[1] + 0.0008)
    stac = {"features": [
        # newest and listed first, but holds no heights in the box
        {"id": "Empty_2025-1m", "bbox": list(box), "properties": {"datetime": "2025-01-01T00:00:00Z"},
         "assets": {"dtm": {"href": empty}}},
        {"id": "Good_2020-1m", "bbox": list(box), "properties": {"datetime": "2020-01-01T00:00:00Z"},
         "assets": {"dtm": {"href": good}}}]}
    monkeypatch.setattr(dr, "http_get_json",
                        lambda url, params=None, **k: stac if "hrdem" in url else {"items": []})
    res = dr.fetch_reference(bbox=small, out_dir=str(tmp_path / "o"), level="3", countries=["CA"])
    assert res["chosen"]["item_id"] == "Good_2020-1m"
    assert res["stats"]["valid_fraction"] == 1.0
    side = json.load(open(res["sidecar"]))
    assert side["coverage_estimate_before_clip"] == 1.0
    # empty one is listed last with 0 coverage
    assert [c["item_id"] for c in res["candidates"]] == ["Good_2020-1m", "Empty_2025-1m"]
    assert res["candidates"][1]["coverage"] == 0.0


def test_fetch_errors_when_nothing_covers_the_box(tmp_path, monkeypatch):
    empty = _make_empty_tif(str(tmp_path / "empty.tif"))
    box = dr.extent_wgs84(empty, buffer_deg=0.0)
    mid = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    small = (mid[0] - 0.0008, mid[1] - 0.0008, mid[0] + 0.0008, mid[1] + 0.0008)
    stac = {"features": [{"id": "Empty_2025-1m", "bbox": list(box),
                          "properties": {"datetime": "2025-01-01T00:00:00Z"},
                          "assets": {"dtm": {"href": empty}}}]}
    monkeypatch.setattr(dr, "http_get_json",
                        lambda url, params=None, **k: stac if "hrdem" in url else {"items": []})
    with pytest.raises(RuntimeError, match="No dataset has data"):
        dr.fetch_reference(bbox=small, out_dir=str(tmp_path / "o"), level="3", countries=["CA"])
