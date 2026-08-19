# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.54.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Shared pytest fixtures for the dem2dged suite.

WHAT IS AND IS NOT HERE
-----------------------
Every source DEM used by the suite is GENERATED, with GDAL, in a temporary
directory. Nothing here reads operator data, downloads anything, or depends
on a file that has to be shipped alongside the tests -- so `pytest` gives
the same answer on a clean checkout, on a build agent, and on the operator's
machine.

The unit layer (tests/test_lib.py, tests/test_validator.py) needs only
Python + numpy + the osgeo bindings. The integration layer
(tests/test_converters.py) additionally needs the gdalwarp EXECUTABLE on
PATH, because that is what dem2dged_lib.run_cmd() shells out to; those tests
skip cleanly when it is absent rather than failing.

THE output_dir FIXTURE (v0.38 -- do not make this session-scoped)
-----------------------------------------------------------------
This fixture returns a FRESH tempfile.mkdtemp() for every test that asks
for one. It used to resolve to a single session-wide "output" subdirectory
shared by every test, which meant one test's leftover tiles were still on
disk when the next one globbed *.tif expecting only its own. The failure
that exposed it, test_utm_names_are_zero_padded, was failing on a leftover
GEO-named file from an EARLIER test -- nothing was wrong with UTM naming at
all. A shared output directory turns "test A is broken" into "test B fails",
which is the most expensive kind of test bug, so the isolation is
deliberate and worth the handful of extra temp directories.
"""

import math
import os
import shutil
import struct
import sys
import tempfile

import pytest

# The project modules live one directory up from tests/. Insert rather than
# append so a stale dem2dged installed elsewhere on the path cannot shadow
# the copy actually being tested.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

gdal = osr = None
try:
    from osgeo import gdal as _gdal, osr as _osr
    gdal, osr = _gdal, _osr
except ImportError:                                  # pragma: no cover
    pass


# -- Capability probes --------------------------------------------------------

HAVE_GDAL = gdal is not None
HAVE_GDALWARP = shutil.which("gdalwarp") is not None

requires_gdal = pytest.mark.skipif(
    not HAVE_GDAL,
    reason="osgeo (GDAL Python bindings) not importable in this environment")

requires_gdalwarp = pytest.mark.skipif(
    not (HAVE_GDAL and HAVE_GDALWARP),
    reason="the gdalwarp EXECUTABLE is not on PATH -- dem2dged shells out to "
           "it for every tile, so a real conversion cannot be exercised here")


# -- Raster generation --------------------------------------------------------

def make_raster(path, epsg, geotransform, width, height,
                dtype=None, nodata=-32767.0, area_or_point="Point",
                base=100.0, slope_x=0.60, slope_y=0.35, relief=12.0,
                set_projection=True):
    """Write a small, smoothly-varying synthetic elevation raster.

    Smooth on purpose: a continuous surface is what the resamplers under
    test are actually designed for, so a difference between two of them is
    signal rather than the aliasing noise a random field would produce.
    ``relief=0`` gives a pure plane, which makes an exact-arithmetic
    assertion possible where a test needs one.

    ``set_projection=False`` writes the raster with NO CRS at all -- used to
    exercise the v0.42 require_epsg() guard.
    """
    if gdal is None:                                 # pragma: no cover
        pytest.skip("GDAL not available")
    if dtype is None:
        dtype = gdal.GDT_Float32

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, width, height, 1, dtype)
    ds.SetGeoTransform(geotransform)
    if set_projection:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        ds.SetProjection(srs.ExportToWkt())
    ds.SetMetadataItem("AREA_OR_POINT", area_or_point)

    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(float(nodata))
    for j in range(height):
        row = [base + slope_x * i + slope_y * j
               + relief * math.sin(i / 7.0) + (relief * 0.7) * math.cos(j / 5.0)
               for i in range(width)]
        band.WriteRaster(0, j, width, 1,
                         struct.pack("<%df" % width, *row),
                         buf_type=gdal.GDT_Float32)
    band.FlushCache()
    ds.FlushCache()
    ds = None
    return path


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
def output_dir():
    """A private, empty output directory for ONE test. See the module
    docstring -- this must not become session-scoped again (v0.38)."""
    d = tempfile.mkdtemp(prefix="dem2dged_out_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def scratch_dir():
    """A private scratch directory for ONE test's source rasters."""
    d = tempfile.mkdtemp(prefix="dem2dged_src_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def geo_source(scratch_dir):
    """A WGS-84 source DEM at 55.5 N, 12 E (Denmark), 1 arc-second posts.

    400 x 300 posts at 1"/post is 0.111 x 0.083 degrees, which at level 5
    (6-minute = 0.1-degree tiles) spans TWO tiles in latitude -- so the edge
    reconciliation of v0.37 Finding 1 has an adjacent pair to work on. The
    latitude also puts it in GEO longitude zone 2, whose x1.5 factor is the
    one that used to break post alignment before v0.27.
    """
    p = os.path.join(scratch_dir, "geo_source.tif")
    return make_raster(p, 4326,
                       (12.0, 1 / 3600.0, 0.0, 55.5, 0.0, -1 / 3600.0),
                       width=400, height=300)


@pytest.fixture
def geo_grid_source(scratch_dir):
    """A source that produces a 2 x 2 GEO tile grid — deliberately at
    level 0, where tiles are only 121 x 81 posts.

    v0.43. The v0.42 release gate exposed a hole: `geo_source` spans two
    tiles in LONGITUDE but only one in latitude, and `utm_source` spans two
    in EASTING only. So every edge test in the suite exercised
    reconcile_tile_edges()' **pass 2** (column seams) and none of them ever
    reached **pass 1** (row seams: south tile's top row copied onto the
    north tile's bottom row). Those are separate loops over separate
    edges, and the docstring is explicit that running all row fixes BEFORE
    any column fix is what keeps a tile's four corners — each shared with
    three other tiles — mutually consistent. A 2 x 2 grid is the smallest
    arrangement that covers both passes and the shared corner at once.

    Level 0 keeps it cheap: 1-degree tiles at 30 arc-second posts are
    121 x 81 (the 81 is longitude zone 2's x1.5 factor at 55 N), against
    4001 x 6001 at level 5. It is also Int16, so this is the only edge test
    that exercises reconciliation on the integer path.

    Extent 12.1–13.9 E, 55.1–56.9 N => tile origins (55,12) (55,13)
    (56,12) (56,13), all four with real data.
    """
    p = os.path.join(scratch_dir, "geo_grid_source.tif")
    return make_raster(p, 4326,
                       (12.1, 1 / 120.0, 0.0, 56.9, 0.0, -1 / 120.0),
                       width=216, height=216)


@pytest.fixture
def utm_source(scratch_dir):
    """A UTM zone 32N source DEM, 10 m posts, 12 km x 3 km.

    Deliberately WIDER than one level-5 UTM tile ((5001-1) * 2 m = 10 km) so
    the conversion produces two tiles side by side. The first v0.41 release
    run used a 4 km source, got a single tile, and section G could only warn
    "no adjacent tile pairs with valid data found to compare" -- meaning UTM
    edge reconciliation had never actually been exercised.
    """
    p = os.path.join(scratch_dir, "utm_source.tif")
    return make_raster(p, 32632,
                       (500000.0, 10.0, 0.0, 6150000.0, 0.0, -10.0),
                       width=1200, height=300)


@pytest.fixture
def equatorial_utm_source(scratch_dir):
    """A UTM 32N source whose extent dips just BELOW the equator.

    This is the v0.39 negative-northing case: a point-registered source such
    as SRTM overhangs its nominal edge by half a post, so a northern-zone
    conversion used to emit a tile at a negative northing and a filename
    like "...32N-025..." that the validator then correctly rejected.
    """
    p = os.path.join(scratch_dir, "equatorial_source.tif")
    return make_raster(p, 32632,
                       (500000.0, 10.0, 0.0, 3000.0, 0.0, -10.0),
                       width=600, height=600)


@pytest.fixture
def untagged_source(scratch_dir):
    """A raster with NO coordinate reference system at all (v0.42)."""
    p = os.path.join(scratch_dir, "untagged.tif")
    return make_raster(p, 4326,
                       (12.0, 1 / 3600.0, 0.0, 55.5, 0.0, -1 / 3600.0),
                       width=60, height=60, set_projection=False)


@pytest.fixture
def step_edge_source(scratch_dir):
    """A hard step edge: the shape that makes cubic-family resamplers ring.

    Half the raster at 0 m, half at 255 m, with nothing in between. v0.37
    Finding 3 was confirmed on exactly this kind of input -- real DGIWG test
    rasters with values 0-255 and 6-255 produced Cubic Convolution tiles
    reaching -44 m and 313 m, which is physically impossible elevation.
    """
    if gdal is None:                                 # pragma: no cover
        pytest.skip("GDAL not available")
    p = os.path.join(scratch_dir, "step_edge.tif")
    w = h = 400
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(p, w, h, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((500000.0, 10.0, 0.0, 6150000.0, 0.0, -10.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32632)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetMetadataItem("AREA_OR_POINT", "Point")
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767.0)
    for j in range(h):
        row = [0.0 if (i // 25) % 2 == 0 else 255.0 for i in range(w)]
        band.WriteRaster(0, j, w, 1, struct.pack("<%df" % w, *row),
                         buf_type=gdal.GDT_Float32)
    band.FlushCache()
    ds.FlushCache()
    ds = None
    return p
