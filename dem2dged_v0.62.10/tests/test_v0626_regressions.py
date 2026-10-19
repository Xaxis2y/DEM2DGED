# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.10
"""v0.62.6: the Find-reference "Not responding" freeze.

Measured on the DGED environment (GDAL 3.13.3, Windows): after a GDAL /vsicurl/
read in a Python THREAD, the next DLL load in the main thread (tkinter's first
load, native dialogs) deadlocks. The v0.62.5 Search button did exactly that in
a thread of the GUI process. v0.62.6 runs Search in a worker process and
refuses remote GDAL reads in non-main threads.

These tests are offline: no network, no real server.
"""

import inspect
import json
import os
import sys
import threading

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

gdal = pytest.importorskip("osgeo.gdal")
from osgeo import osr  # noqa: E402

import dem2dged_reference as dr  # noqa: E402


def _make_tif(path, cells=64):
    ds = gdal.GetDriverByName("GTiff").Create(path, cells, cells, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((1_500_000.0, 1.0, 0, -400_000.0, 0, -1.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3979)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.full((cells, cells), 100.0, dtype="float32"))
    ds.FlushCache()
    ds = None
    return path


def _run_in_thread(func):
    box = {}

    def target():
        try:
            box["result"] = func()
        except BaseException as exc:      # noqa: BLE001 - captured for the assertion
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(30)
    assert not thread.is_alive()
    return box


# ---------------------------------------------------------------------------
# dem2dged_reference: no remote GDAL reads from a non-main thread
# ---------------------------------------------------------------------------

def test_remote_gdal_read_is_refused_in_a_thread(monkeypatch):
    monkeypatch.delenv("DEM2DGED_ALLOW_THREADED_VSICURL", raising=False)
    box = _run_in_thread(lambda: dr._open_remote("https://example.invalid/x.tif", gdal))
    assert isinstance(box.get("error"), RuntimeError)
    assert "main thread" in str(box["error"])


def test_probe_reports_the_refusal_instead_of_crashing(monkeypatch):
    monkeypatch.delenv("DEM2DGED_ALLOW_THREADED_VSICURL", raising=False)
    box = _run_in_thread(
        lambda: dr.probe_coverage("https://example.invalid/x.tif", (-75.8, 45.3, -75.7, 45.4)))
    result = box["result"]
    assert result["valid_fraction"] is None
    assert "main thread" in result["error"]


def test_local_file_still_opens_in_a_thread(tmp_path, monkeypatch):
    monkeypatch.delenv("DEM2DGED_ALLOW_THREADED_VSICURL", raising=False)
    path = _make_tif(str(tmp_path / "local.tif"))
    box = _run_in_thread(lambda: dr._open_remote(path, gdal).RasterXSize)
    assert box.get("error") is None
    assert box["result"] == 64


def test_module_version_matches_the_release():
    import dem2dged_lib
    assert dr.VERSION == dem2dged_lib.VERSION


# ---------------------------------------------------------------------------
# dem2dged_gui: Search runs in a worker process, never in a thread
# ---------------------------------------------------------------------------

@pytest.fixture()
def gui():
    pytest.importorskip("tkinter")
    import dem2dged_gui
    if getattr(dem2dged_gui, "dr", None) is None:
        pytest.skip("dem2dged_reference not importable in the GUI module")
    return dem2dged_gui


def test_find_reference_dialog_starts_no_threads(gui):
    source = inspect.getsource(gui.App._find_reference_dialog)
    assert "threading.Thread" not in source
    assert 'launch_worker(\n                "search"' in source
    assert 'launch_worker(\n                "clip"' in source
    assert "cancel_worker" in source


def test_entry_point_dispatches_both_workers(gui):
    source = inspect.getsource(gui)
    assert '"--reference-clip-worker"' in source
    assert '"--reference-search-worker"' in source


def test_search_worker_round_trip(gui, tmp_path, monkeypatch, capsys):
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(json.dumps({"source_path": "dem.tif", "level": "0",
                                   "operation_timeout": 5}), encoding="utf-8")
    seen = {}

    def fake_extent(path):
        seen["source"] = path
        return (-75.8, 45.3, -75.7, 45.4)

    def fake_fetch(bbox=None, level=None, list_only=None, operation_timeout=None, log=None):
        seen.update(bbox=bbox, level=level, list_only=list_only, timeout=operation_timeout)
        log("probing 1/1: fake")
        return {"candidates": [{"number": 1, "title": "fake", "coverage": 0.5}], "errors": []}

    monkeypatch.setattr(gui.dr, "extent_wgs84", fake_extent)
    monkeypatch.setattr(gui.dr, "fetch_reference", fake_fetch)
    monkeypatch.setattr(sys, "argv", ["dem2dged.exe", "--reference-search-worker",
                                      str(request), str(result)])
    assert gui._reference_search_worker_main() == 0
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["bbox"] == [-75.8, 45.3, -75.7, 45.4]
    assert payload["candidates"][0]["title"] == "fake"
    assert payload["errors"] == []
    assert seen["source"] == "dem.tif" and seen["level"] == "0"
    assert seen["list_only"] is True and seen["timeout"] == 5
    assert "probing 1/1: fake" in capsys.readouterr().out


def test_search_worker_reports_errors_in_the_result_file(gui, tmp_path, monkeypatch):
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(json.dumps({"source_path": "dem.tif", "level": "0"}), encoding="utf-8")

    def boom(path):
        raise ValueError("source raster has no coordinate system: %s" % path)

    monkeypatch.setattr(gui.dr, "extent_wgs84", boom)
    monkeypatch.setattr(sys, "argv", ["dem2dged.exe", "--reference-search-worker",
                                      str(request), str(result)])
    assert gui._reference_search_worker_main() == 1
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert "no coordinate system" in payload["error"]


def test_search_worker_rejects_bad_arguments(gui, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dem2dged.exe", "--reference-search-worker"])
    assert gui._reference_search_worker_main() == 2
