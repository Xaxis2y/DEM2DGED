# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.42
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Shared pytest fixtures for the dem2dged test suite.

Everything the suite needs is generated here from scratch -- no external
test data, no network, no operator-supplied DEM. Two synthetic sources are
built with GDAL:

  geo_dem   a small WGS-84 (EPSG:4326) elevation raster
  utm_dem   the same terrain in a metric UTM zone (EPSG:32632)

Both carry a smooth, non-degenerate surface (a tilted plane plus a couple of
sine ripples) so resampling actually has something to interpolate and the
validator's statistics checks see a realistic elevation spread rather than a
constant.

v0.38 (regression): ``output_dir`` used to resolve to ONE session-wide
"output" subdirectory shared by every test that requested it, so one test's
leftover tiles were still on disk when the next globbed *.tif expecting only
its own -- e.g. test_utm_names_are_zero_padded failed on a leftover
GEO-named file from an earlier GEO test rather than on anything wrong with
UTM naming. It is now a fresh tempfile.mkdtemp() per test, removed on
teardown. Do not make it session-scoped again.
"""

import os
import shutil
import sys
import tempfile

import pytest

# The project root is the parent of tests/; put it first on sys.path so the
# suite always exercises THIS checkout rather than an installed copy.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# GDAL is optional for the pure-library tests (tests/test_lib.py runs without
# it); test_converters.py and test_validator.py skip themselves when it is
# missing rather than erroring the whole session.
try:
    from osgeo import gdal, osr

    # v0.41: deliberately NOT calling gdal.UseExceptions() here. gdal, ogr
    # and osr share one global flag, and dem2dged_lib.py pins it for the
    # whole project; a call here would mean the suite tested a GDAL
    # configuration the shipped tool never runs in. tests/test_lib.py
    # asserts what the library actually set.
    HAVE_GDAL = True
except Exception:  # pragma: no cover - depends on the environment
    gdal = osr = None
    HAVE_GDAL = False

requires_gdal = pytest.mark.skipif(
    not HAVE_GDAL, reason="GDAL/osgeo is not available in this environment"
)


# -- helpers ------------------------------------------------------------------

def _surface(width, height):
    """A smooth synthetic elevation surface as a list of rows.

    Deliberately plain Python (no numpy dependency in conftest) so the
    fixtures work in a bare environment: the arrays are tiny.
    """
    import math

    rows = []
    for j in range(height):
        row = []
        for i in range(width):
            z = (100.0
                 + 0.60 * i
                 + 0.35 * j
                 + 12.0 * math.sin(i / 7.0)
                 + 8.0 * math.cos(j / 5.0))
            row.append(z)
        rows.append(row)
    return rows


def _write_raster(path, width, height, gt, epsg, nodata=-32767.0):
    """Write a single-band Float32 GeoTIFF with AREA_OR_POINT=Point."""
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, width, height, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetMetadataItem("AREA_OR_POINT", "Point")
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    for j, row in enumerate(_surface(width, height)):
        band.WriteRaster(0, j, width, 1,
                         __import__("struct").pack("<%df" % width, *row),
                         buf_type=gdal.GDT_Float32)
    band.FlushCache()
    ds.FlushCache()
    ds = None
    return path


# -- fixtures -----------------------------------------------------------------

@pytest.fixture()
def output_dir():
    """A FRESH, empty directory for one test's conversion output.

    v0.38: per-test, never shared. See this module's docstring.
    """
    d = tempfile.mkdtemp(prefix="dem2dged_out_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="session")
def sample_data_dir():
    """Session-scoped scratch dir holding the generated source rasters.

    Safe to share (unlike ``output_dir``): the sources are read-only inputs
    and regenerating them for every test would be pure overhead.
    """
    d = tempfile.mkdtemp(prefix="dem2dged_src_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="session")
def geo_dem(sample_data_dir):
    """A synthetic WGS-84 elevation raster (EPSG:4326).

    Origin 12.0E / 55.5N, 1 arc-second posts, 400x300 -- roughly 0.111 x
    0.083 degrees, comfortably inside a single level-2 (1 degree) tile and
    spanning several level-5 (6 arc-minute) tiles.
    """
    if not HAVE_GDAL:
        pytest.skip("GDAL not available")
    path = os.path.join(sample_data_dir, "geo_source_dem.tif")
    if not os.path.isfile(path):
        res = 1.0 / 3600.0
        # (originX, pixelWidth, 0, originY, 0, pixelHeight)
        gt = (12.0, res, 0.0, 55.5, 0.0, -res)
        _write_raster(path, 400, 300, gt, 4326)
    return path


@pytest.fixture(scope="session")
def utm_dem(sample_data_dir):
    """A synthetic UTM raster (EPSG:32632, zone 32N), 10 m posts."""
    if not HAVE_GDAL:
        pytest.skip("GDAL not available")
    path = os.path.join(sample_data_dir, "utm_source_dem.tif")
    if not os.path.isfile(path):
        gt = (500000.0, 10.0, 0.0, 6150000.0, 0.0, -10.0)
        _write_raster(path, 400, 300, gt, 32632)
    return path


@pytest.fixture(scope="session")
def utm_dem_wide(sample_data_dir):
    """A UTM raster wide enough to span TWO level-5 tiles.

    A level-5 UTM tile is (5001-1) * 2 m = 10 km, so the default 4 km-wide
    ``utm_dem`` only ever produces one tile and cannot exercise the
    shared-edge reconciliation of v0.37 Finding 1 on the UTM side. 1200
    posts at 10 m = 12 km, starting on a tile boundary, gives two.
    """
    if not HAVE_GDAL:
        pytest.skip("GDAL not available")
    path = os.path.join(sample_data_dir, "utm_source_dem_wide.tif")
    if not os.path.isfile(path):
        gt = (500000.0, 10.0, 0.0, 6150000.0, 0.0, -10.0)
        _write_raster(path, 1200, 300, gt, 32632)
    return path


@pytest.fixture(scope="session")
def equator_utm_dem(sample_data_dir):
    """A UTM raster whose extent dips just BELOW the equator.

    Regression fixture for the v0.39 negative-northing clamp: a northern
    zone must not emit a tile at a negative northing (spec 6.3.1).
    """
    if not HAVE_GDAL:
        pytest.skip("GDAL not available")
    path = os.path.join(sample_data_dir, "utm_equator_dem.tif")
    if not os.path.isfile(path):
        # Top edge 3000 m north of the equator, 300 rows of 10 m => the
        # bottom edge lands at -0 m ... i.e. it crosses zero.
        gt = (500000.0, 10.0, 0.0, 3000.0, 0.0, -10.0)
        _write_raster(path, 400, 300, gt, 32632)
    return path


@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT
