# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.10
"""v0.62.7: Find reference shows the download window size before downloading and
lets the user raise the 40-million-cell cap.

Before v0.62.7 a large source area failed only AFTER the download had started:
"window of 174.5 million cells exceeds the limit of 40.0 million".
These tests are offline: no network, no real server.
"""

import inspect
import json
import os
import re
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

gdal = pytest.importorskip("osgeo.gdal")
from osgeo import osr  # noqa: E402

import dem2dged_reference as dr  # noqa: E402


def _make_tif(path, cells=600):
    ds = gdal.GetDriverByName("GTiff").Create(path, cells, cells, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((1_500_000.0, 1.0, 0, -400_000.0, 0, -1.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3979)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.full((cells, cells), 100.0, dtype="float32"))
    ds.FlushCache()
    ds = None
    return path


def _inner_box(path):
    box = dr.extent_wgs84(path, buffer_deg=0.0)
    return (box[0] + (box[2] - box[0]) * 0.3, box[1] + (box[3] - box[1]) * 0.3,
            box[0] + (box[2] - box[0]) * 0.6, box[1] + (box[3] - box[1]) * 0.6)


# ---------------------------------------------------------------------------
# dem2dged_reference
# ---------------------------------------------------------------------------

def test_probe_reports_the_window_size(tmp_path):
    path = _make_tif(str(tmp_path / "ref.tif"))
    box = _inner_box(path)
    ds = gdal.Open(path)
    _xoff, _yoff, xsize, ysize = dr._window_for_bbox(ds, box, gdal, osr)
    ds = None
    result = dr.probe_coverage(path, box)
    assert result["valid_fraction"] == 1.0
    assert result["window_cells"] == xsize * ysize
    assert 0 < result["window_cells"] < 600 * 600


def test_probe_window_is_zero_when_the_box_misses_the_dataset(tmp_path):
    path = _make_tif(str(tmp_path / "ref.tif"))
    result = dr.probe_coverage(path, (0.0, 0.0, 0.001, 0.001))
    assert result["valid_fraction"] == 0.0
    assert result["window_cells"] == 0


def test_probe_failure_has_no_window_size(tmp_path):
    result = dr.probe_coverage(str(tmp_path / "missing.tif"), (0.0, 0.0, 0.001, 0.001))
    assert result["valid_fraction"] is None
    assert not result.get("window_cells")


def test_clip_time_limit_scales_with_the_window():
    small = dr.clip_time_limit(40_000_000)
    large = dr.clip_time_limit(174_500_000)
    assert small >= dr.DEFAULT_OPERATION_TIMEOUT
    assert large > small
    assert dr.clip_time_limit(None) == dr.DEFAULT_OPERATION_TIMEOUT
    assert dr.clip_time_limit(0) == dr.DEFAULT_OPERATION_TIMEOUT


def test_absolute_ceiling_is_above_the_default_cap():
    assert dr.ABSOLUTE_MAX_CELLS > dr.DEFAULT_MAX_CELLS


def test_describe_candidate_shows_the_window():
    cand = {"number": 1, "country": "CA", "title": "BC-test-1m", "resolution_m": 1,
            "date": "2019-10-11", "suitability": "OK", "coverage": 0.38,
            "window_cells": 174_500_000,
            "source": {"vertical_le90_m": 0.5, "vertical_datum": "CGVD2013"}}
    assert "window 174.5 M cells" in dr.describe_candidate(cand)
    del cand["window_cells"]
    assert "window" not in dr.describe_candidate(cand)


def test_cap_error_names_both_the_gui_box_and_the_command_line(tmp_path):
    path = _make_tif(str(tmp_path / "ref.tif"))
    box = dr.extent_wgs84(path, buffer_deg=0.0)
    with pytest.raises(RuntimeError, match="exceeds the limit") as info:
        dr.clip_window(path, box, str(tmp_path / "y.tif"), max_cells=1000)
    assert "Max cells" in str(info.value)
    assert "--max-cells" in str(info.value)


# ---------------------------------------------------------------------------
# dem2dged_gui
# ---------------------------------------------------------------------------

@pytest.fixture()
def gui():
    pytest.importorskip("tkinter")
    import dem2dged_gui
    if getattr(dem2dged_gui, "dr", None) is None:
        pytest.skip("dem2dged_reference not importable in the GUI module")
    return dem2dged_gui


def test_dialog_has_the_size_column_and_cap_box(gui):
    source = inspect.getsource(gui.App._find_reference_dialog)
    assert "Window (M cells)" in source
    assert "Max cells (millions)" in source
    assert "max_cells_var" in source
    assert re.search(r'"max_cells":\s*cap', source)
    assert "clip_time_limit" in source
    assert "ABSOLUTE_MAX_CELLS" in source


def _run_clip_worker(gui, tmp_path, monkeypatch, request):
    req = tmp_path / "request.json"
    res = tmp_path / "result.json"
    req.write_text(json.dumps(request), encoding="utf-8")
    captured = {}

    def fake_clip(cand, bbox, out_dir, **kwargs):
        captured.update(kwargs)
        return {"output": "o.tif", "sidecar": "o.json", "stats": {}}

    monkeypatch.setattr(gui.dr, "clip_candidate", fake_clip)
    monkeypatch.setattr(sys, "argv", ["dem2dged.exe", "--reference-clip-worker", str(req), str(res)])
    assert gui._reference_clip_worker_main() == 0
    assert json.loads(res.read_text(encoding="utf-8"))["ok"] is True
    return captured


def test_clip_worker_passes_the_user_cap(gui, tmp_path, monkeypatch):
    captured = _run_clip_worker(gui, tmp_path, monkeypatch, {
        "candidate": {"title": "x"}, "bbox": [-75.8, 45.3, -75.7, 45.4], "out_dir": str(tmp_path),
        "level": "0", "source_path": "dem.tif", "timeout": 30, "max_cells": 175_000_000})
    assert captured["max_cells"] == 175_000_000


def test_clip_worker_defaults_to_the_standard_cap(gui, tmp_path, monkeypatch):
    captured = _run_clip_worker(gui, tmp_path, monkeypatch, {
        "candidate": {"title": "x"}, "bbox": [-75.8, 45.3, -75.7, 45.4], "out_dir": str(tmp_path),
        "level": "0", "source_path": "dem.tif", "timeout": 30})
    assert captured["max_cells"] == dr.DEFAULT_MAX_CELLS
