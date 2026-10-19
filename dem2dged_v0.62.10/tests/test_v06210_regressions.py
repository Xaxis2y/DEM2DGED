# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.10
"""v0.62.10: the CGVD2013 correction no longer depends on PROJ's network layer.

Measured cause (vertical_correction.json from the v0.62.9 GUI run): in the GUI's
worker thread PROJ reported "Grid ca_nrc_CGG2013i08.tif is not available" and
"Grid us_nga_egm08_25.tif is not available" (the command line worked because PROJ
fetched them over the network in the main thread). The grids are now downloaded
once with urllib, kept in a local folder and added to the PROJ search paths.

Most tests use fakes and need neither GDAL nor the internet. The two tests at the
end are the real regression: they run the correction in a worker thread with PROJ
network access OFF and need the internet once. They are skipped unless
DEM2DGED_TEST_NETWORK=1 is set.
"""

import hashlib
import os
import sys
import threading

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import dem2dged_vertical as dvt  # noqa: E402

# the real message from the v0.62.9 GUI run (shortened: PROJ repeats it many times)
GRID_ERROR = (
    "PROJ: Attempt to use coordinate operation Inverse of ITRF2008 to CGVD2013(CGG2013) height (1) + "
    "Inverse of Conversion from WGS 84 (G1762) (geocentric) to WGS 84 (G1762) (geog2D) + "
    "WGS 84 (G1762) to ITRF2008 (1) + WGS 84 (G1762) to EGM2008 height (from WGS 84 to EGM2008 height (1)) "
    "using Conversion from ITRF2008 (geog2D) to ITRF2008 (geocentric) failed. "
    "Grid ca_nrc_CGG2013i08.tif is not available. Consult https://proj.org/resource_files.html for guidance. "
    "Grid us_nga_egm08_25.tif is not available. Consult https://proj.org/resource_files.html for guidance.\n"
    + "May be caused by: PROJ: Attempt to use coordinate operation ... failed. "
      "Grid ca_nrc_CGG2013i08.tif is not available.\n" * 40)


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class FakeDataset:
    RasterCount = 1


class FakeGdal:
    def __init__(self, opens=True):
        self.opens = opens
        self.opened = []

    def Open(self, path):                                  # noqa: N802 - GDAL's name
        self.opened.append(path)
        return FakeDataset() if self.opens else None


class FakeOsr:
    def __init__(self, paths):
        self.paths = list(paths)

    def GetPROJSearchPaths(self):                          # noqa: N802
        return list(self.paths)

    def SetPROJSearchPaths(self, paths):                   # noqa: N802
        self.paths = list(paths)


class FakeResponse:
    def __init__(self, payload, length=None):
        self.payload = payload
        self.position = 0
        self.headers = {"Content-Length": str(len(payload) if length is None else length)}

    def read(self, count):
        chunk = self.payload[self.position:self.position + count]
        self.position += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def grid_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEM2DGED_GRID_DIR", str(tmp_path / "grids"))
    monkeypatch.delenv("DEM2DGED_NO_GRID_DOWNLOAD", raising=False)
    return tmp_path / "grids"


def _serve(monkeypatch, payload, length=None):
    requested = []

    def fake_urlopen(request, timeout=0):
        requested.append(request.full_url)
        return FakeResponse(payload, length)

    monkeypatch.setattr(dvt.urllib.request, "urlopen", fake_urlopen)
    return requested


# ---------------------------------------------------------------------------
# error text
# ---------------------------------------------------------------------------

def test_missing_grids_are_read_from_the_proj_message():
    assert dvt.grid_names_from_error(GRID_ERROR) == ["ca_nrc_CGG2013i08.tif", "us_nga_egm08_25.tif"]
    assert dvt.grid_names_from_error("nothing to see") == []
    assert dvt.grid_names_from_error(None) == []


def test_unsafe_grid_names_are_never_returned():
    text = "Grid ../../evil.tif is not available. Grid C:\\x\\y.tif is not available. Grid a.exe is not available."
    assert dvt.grid_names_from_error(text) == []


@pytest.mark.parametrize("name,ok", [
    ("ca_nrc_CGG2013i08.tif", True), ("us_nga_egm08_25.tif", True), ("x.gtx", True),
    ("../x.tif", False), ("a/b.tif", False), ("a\\b.tif", False), ("x.exe", False),
    ("", False), (".hidden.tif", False)])
def test_grid_name_whitelist(name, ok):
    assert bool(dvt.SAFE_GRID_NAME.match(name)) is ok


def test_grid_error_is_summarised_with_the_file_names_and_stays_short():
    text = dvt.summarize_proj_error(GRID_ERROR)
    assert "ca_nrc_CGG2013i08.tif" in text and "us_nga_egm08_25.tif" in text
    assert len(text) < 300 and "\n" not in text


def test_full_text_is_capped():
    capped = dvt.cap_text(GRID_ERROR * 20)
    assert len(capped) < dvt.FULL_TEXT_LIMIT + 100 and "more characters cut" in capped
    assert dvt.cap_text("short") == "short"


# ---------------------------------------------------------------------------
# where the files live, and whether downloading is allowed
# ---------------------------------------------------------------------------

def test_grid_dir_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("DEM2DGED_GRID_DIR", str(tmp_path / "mine"))
    assert dvt.grid_dir() == str(tmp_path / "mine")
    monkeypatch.delenv("DEM2DGED_GRID_DIR")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert dvt.grid_dir() == os.path.join(str(tmp_path / "local"), "dem2dged", "proj_grids")


@pytest.mark.parametrize("value,allowed", [("", True), ("0", True), ("1", False), ("true", False), ("YES", False)])
def test_downloads_can_be_switched_off(monkeypatch, value, allowed):
    monkeypatch.setenv("DEM2DGED_NO_GRID_DOWNLOAD", value)
    assert dvt.downloads_allowed() is allowed


def test_grid_dir_is_added_to_the_proj_search_paths_once(grid_env):
    osr = FakeOsr(["C:/env/proj"])
    assert dvt.add_grid_dir(osr) == str(grid_env)
    assert osr.paths == ["C:/env/proj", str(grid_env)] and grid_env.is_dir()
    dvt.add_grid_dir(osr)
    assert osr.paths.count(str(grid_env)) == 1


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

def test_download_writes_the_file_and_leaves_no_part_file(grid_env, monkeypatch):
    requested = _serve(monkeypatch, b"x" * 3_500_000)
    gdal = FakeGdal()
    logs = []
    path = dvt.fetch_grid("ca_nrc_CGG2013i08.tif", str(grid_env), gdal, log=logs.append)
    assert requested == ["https://cdn.proj.org/ca_nrc_CGG2013i08.tif"]
    assert os.path.getsize(path) == 3_500_000 and not os.path.exists(path + ".part")
    assert gdal.opened == [path + ".part"]
    assert any("downloading" in line and "once" in line for line in logs)


def test_a_download_that_is_not_a_raster_is_discarded(grid_env, monkeypatch):
    _serve(monkeypatch, b"<html>not a grid</html>")
    with pytest.raises(RuntimeError, match="does not open as a raster"):
        dvt.fetch_grid("ca_nrc_CGG2013i08.tif", str(grid_env), FakeGdal(opens=False))
    assert os.listdir(str(grid_env)) == []


def test_oversized_downloads_are_refused(grid_env, monkeypatch):
    _serve(monkeypatch, b"x", length=dvt.MAX_GRID_BYTES + 1)
    with pytest.raises(RuntimeError, match="refusing a download"):
        dvt.fetch_grid("us_nga_egm08_25.tif", str(grid_env), FakeGdal())
    assert os.listdir(str(grid_env)) == []


def test_stopping_aborts_the_download(grid_env, monkeypatch):
    _serve(monkeypatch, b"x" * 3_000_000)
    stop = threading.Event()
    stop.set()
    with pytest.raises(RuntimeError, match="stopped"):
        dvt.fetch_grid("us_nga_egm08_25.tif", str(grid_env), FakeGdal(), stop_event=stop)
    assert os.listdir(str(grid_env)) == []


def test_unexpected_names_and_the_off_switch_prevent_any_request(grid_env, monkeypatch):
    requested = _serve(monkeypatch, b"x")
    with pytest.raises(ValueError):
        dvt.fetch_grid("../evil.tif", str(grid_env), FakeGdal())
    monkeypatch.setenv("DEM2DGED_NO_GRID_DOWNLOAD", "1")
    with pytest.raises(RuntimeError, match="switched off"):
        dvt.fetch_grid("us_nga_egm08_25.tif", str(grid_env), FakeGdal())
    assert requested == []


# ---------------------------------------------------------------------------
# ensure_grids / retry
# ---------------------------------------------------------------------------

def test_ensure_grids_fetches_only_missing_files_and_records_their_hash(grid_env, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "us_nga_egm08_25.tif").write_bytes(b"already installed")
    requested = _serve(monkeypatch, b"payload")
    osr, record = FakeOsr([str(proj)]), {}
    dvt.ensure_grids(["ca_nrc_CGG2013i08.tif", "us_nga_egm08_25.tif"], osr, FakeGdal(), record)
    assert requested == ["https://cdn.proj.org/ca_nrc_CGG2013i08.tif"]
    names = {item["name"]: item for item in record["grid_files"]}
    assert set(names) == {"ca_nrc_CGG2013i08.tif", "us_nga_egm08_25.tif"}
    assert names["ca_nrc_CGG2013i08.tif"]["sha256"] == hashlib.sha256(b"payload").hexdigest()
    assert names["us_nga_egm08_25.tif"]["sha256"] == hashlib.sha256(b"already installed").hexdigest()


def test_retry_downloads_the_grid_named_in_the_error_then_succeeds(grid_env, monkeypatch):
    _serve(monkeypatch, b"payload")
    osr, record = FakeOsr([]), {}
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("failed. Grid us_nga_egm08_25.tif is not available. Consult ...")
        return "shifted"

    assert dvt._with_grid_retry(call, osr, FakeGdal(), record) == "shifted"
    assert calls["n"] == 2 and record["grid_files"][0]["name"] == "us_nga_egm08_25.tif"


def test_retry_does_not_hide_other_errors_or_loop_forever(grid_env, monkeypatch):
    requested = _serve(monkeypatch, b"payload")
    osr = FakeOsr([])
    with pytest.raises(RuntimeError, match="boom"):
        dvt._with_grid_retry(lambda: (_ for _ in ()).throw(RuntimeError("boom")), osr, FakeGdal(), {})
    assert requested == []
    # a grid that stays "missing" (PROJ cannot use the downloaded file) gives up after 3 rounds
    attempts = {"n": 0}

    def always_missing():
        attempts["n"] += 1
        raise RuntimeError("Grid us_nga_egm08_25.tif is not available.")

    class NeverFound(FakeOsr):
        def GetPROJSearchPaths(self):                      # noqa: N802
            return []

    with pytest.raises(RuntimeError, match="not available"):
        dvt._with_grid_retry(always_missing, NeverFound([]), FakeGdal(), {})
    assert attempts["n"] <= 3


def test_retry_respects_the_off_switch(grid_env, monkeypatch):
    monkeypatch.setenv("DEM2DGED_NO_GRID_DOWNLOAD", "1")
    requested = _serve(monkeypatch, b"payload")
    with pytest.raises(RuntimeError, match="not available"):
        dvt._with_grid_retry(
            lambda: (_ for _ in ()).throw(RuntimeError("Grid us_nga_egm08_25.tif is not available.")),
            FakeOsr([]), FakeGdal(), {})
    assert requested == []


def test_the_route_names_the_grids_proj_asked_for():
    assert set(dvt.SEPARATE_ROUTES["6647"]["grid_files"]) == {"ca_nrc_CGG2013i08.tif", "us_nga_egm08_25.tif"}
    assert all(dvt.SAFE_GRID_NAME.match(n) for n in dvt.SEPARATE_ROUTES["6647"]["grid_files"])


def test_command_line_can_prefetch_the_grids_and_refuses_unknown_datums(capsys):
    assert dvt.main(["--fetch-grids", "--vertical", "5713"]) == 2
    assert "no separate route" in capsys.readouterr().out


def test_module_version_matches_the_release():
    import re
    with open(os.path.join(ROOT, "dem2dged_lib.py"), encoding="utf-8") as stream:
        declared = re.search(r'^VERSION\s*=\s*"([^"]+)"', stream.read(), re.M).group(1)
    assert dvt.VERSION == declared == "0.62.10"


# ---------------------------------------------------------------------------
# the real regression (needs GDAL and the internet once): opt-in
# ---------------------------------------------------------------------------

try:
    from osgeo import gdal, osr
    HAVE_GDAL = True
except Exception:
    gdal = osr = None
    HAVE_GDAL = False

needs_network_run = pytest.mark.skipif(
    not HAVE_GDAL or os.environ.get("DEM2DGED_TEST_NETWORK") != "1",
    reason="set DEM2DGED_TEST_NETWORK=1 (needs GDAL and the internet once)")


def _tile(path, size=64):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2959)
    ds = gdal.GetDriverByName("GTiff").Create(str(path), size, size, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((450000.0, 2.0, 0, 4950000.0, 0, -2.0))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767.0)
    band.WriteArray(np.full((size, size), 100.0, dtype="float32"))
    ds.FlushCache()
    ds = None
    return str(path)


@needs_network_run
def test_correction_works_in_a_worker_thread_with_proj_network_off(tmp_path, monkeypatch):
    monkeypatch.setenv("DEM2DGED_GRID_DIR", str(tmp_path / "grids"))
    monkeypatch.delenv("DEM2DGED_NO_GRID_DOWNLOAD", raising=False)
    saved_paths = list(osr.GetPROJSearchPaths())
    try:
        was_on = bool(osr.GetPROJEnableNetwork())
    except Exception:
        was_on = False
    try:
        osr.SetPROJEnableNetwork(False)
        src = _tile(tmp_path / "dtm.tif")
        box = {}

        def work():
            box["record"] = dvt.create_corrected_source(src, "6647", str(tmp_path / "o" / "dtm.tif"))

        thread = threading.Thread(target=work)
        thread.start()
        thread.join(900)
        assert not thread.is_alive()
        record = box["record"]
        assert record["status"] == "PASS", record.get("reason")
        names = {item["name"] for item in record["grid_files"]}
        assert {"ca_nrc_CGG2013i08.tif", "us_nga_egm08_25.tif"} <= names
        assert all(os.path.isfile(os.path.join(str(tmp_path / "grids"), n)) for n in names)
        assert record["cross_check_max_difference_m"] <= dvt.TOLERANCE_M
        assert abs(record["shift_mean_m"]) < 0.1
    finally:
        osr.SetPROJSearchPaths(saved_paths)
        try:
            osr.SetPROJEnableNetwork(was_on)
        except Exception:
            pass


@needs_network_run
def test_prefetched_grids_are_reused_without_another_download(tmp_path, monkeypatch):
    monkeypatch.setenv("DEM2DGED_GRID_DIR", str(tmp_path / "grids"))
    saved_paths = list(osr.GetPROJSearchPaths())
    try:
        info = {}
        dvt.ensure_grids(dvt.SEPARATE_ROUTES["6647"]["grid_files"], osr, gdal, info)
        monkeypatch.setenv("DEM2DGED_NO_GRID_DOWNLOAD", "1")          # a second call must not need the network
        again = {}
        dvt.ensure_grids(dvt.SEPARATE_ROUTES["6647"]["grid_files"], osr, gdal, again)
        assert [i["sha256"] for i in again["grid_files"]] == [i["sha256"] for i in info["grid_files"]]
    finally:
        osr.SetPROJSearchPaths(saved_paths)
