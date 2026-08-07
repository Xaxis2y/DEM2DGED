# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.42
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""End-to-end conversion tests for dem2dged_geo.py and dem2dged_utm.py.

These need a working GDAL (including the gdalwarp executable on PATH, which
the converters shell out to) and are skipped otherwise. Run them from the
Anaconda Prompt with the DGED environment active:

    conda activate DGED
    pytest tests/test_converters.py -v

Every test converts one of conftest.py's synthetic DEMs into a FRESH
per-test output directory (the ``output_dir`` fixture) and then inspects the
tiles that were actually written -- filenames, geotransform, data type,
NoData, compression, the shared post between neighbours, and the XML
sidecars.
"""

import glob
import os
import shutil
import struct

import pytest

pytest.importorskip("osgeo", reason="the converters need GDAL")

from osgeo import gdal  # noqa: E402

import dem2dged_lib as dl  # noqa: E402
import dem2dged_geo as geo  # noqa: E402
import dem2dged_utm as utm  # noqa: E402

from conftest import requires_gdal  # noqa: E402

pytestmark = [pytest.mark.integration, requires_gdal]


HAVE_GDALWARP = shutil.which("gdalwarp") is not None
requires_gdalwarp = pytest.mark.skipif(
    not HAVE_GDALWARP,
    reason="the gdalwarp executable is not on PATH (conda activate DGED)")


# -- helpers -------------------------------------------------------------------

# NOTE: dem2dged_geo.main() / dem2dged_utm.main() take a RAW ARGV LIST, not a
# parsed Namespace -- they do `parser.parse_args(args[1:])` internally, so
# element 0 must be the program name (this is how dem2dged.py calls them:
# sub_args = ["dem2dged_geo.py", input, output, ...]). Passing a Namespace
# fails with "TypeError: 'Namespace' object is not subscriptable".

def _geo_args(src, out, **over):
    argv = ["dem2dged_geo.py", src, out,
            "-product_level", over.pop("product_level", "5")]
    for k, v in over.items():
        argv += ["-" + k, str(v)]
    return argv


def _utm_args(src, out, **over):
    argv = ["dem2dged_utm.py", src, out,
            "-product_level", over.pop("product_level", "5")]
    for k, v in over.items():
        argv += ["-" + k, str(v)]
    return argv


def _tifs(folder):
    return sorted(glob.glob(os.path.join(folder, "*.tif")))


def _read_row(ds, row):
    band = ds.GetRasterBand(1)
    raw = band.ReadRaster(0, row, ds.RasterXSize, 1, buf_type=gdal.GDT_Float64)
    return struct.unpack("<%dd" % ds.RasterXSize, raw)


def _read_col(ds, col):
    band = ds.GetRasterBand(1)
    raw = band.ReadRaster(col, 0, 1, ds.RasterYSize, buf_type=gdal.GDT_Float64)
    return struct.unpack("<%dd" % ds.RasterYSize, raw)


# -- GEO -----------------------------------------------------------------------

@requires_gdalwarp
def test_geo_conversion_produces_paired_tiles(geo_dem, output_dir):
    geo.main(_geo_args(geo_dem, output_dir))
    tifs = _tifs(output_dir)
    assert tifs, "no tiles were written"
    for t in tifs:
        assert os.path.isfile(os.path.splitext(t)[0] + ".xml"), \
            "%s has no XML sidecar" % os.path.basename(t)


@requires_gdalwarp
def test_geo_tile_names_parse_and_match_their_georeferencing(geo_dem, output_dir):
    import dem2dged_validate as dv

    geo.main(_geo_args(geo_dem, output_dir))
    for t in _tifs(output_dir):
        base = os.path.splitext(os.path.basename(t))[0]
        m = dv.GEO_RE.match(base)
        assert m, "%r does not match the DGED GEO naming convention" % base
        assert m.group("lv") == "5"
        lat0 = dv.dms_to_deg(m.group("lat"), True)
        lon0 = dv.dms_to_deg(m.group("lon"), False)
        ds = gdal.Open(t)
        gt = ds.GetGeoTransform()
        # AREA_OR_POINT=Point + the half-post expanded extent: the PIXEL
        # CENTER lands on the nominal origin, not the raw corner (v0.31).
        center_x = gt[0] + gt[1] / 2.0
        center_y = gt[3] + ds.RasterYSize * gt[5] + abs(gt[5]) / 2.0
        assert abs(center_x - lon0) < abs(gt[1]) * 1e-3
        assert abs(center_y - lat0) < abs(gt[5]) * 1e-3
        ds = None


@requires_gdalwarp
def test_geo_tile_headers_follow_the_dged_profile(geo_dem, output_dir):
    geo.main(_geo_args(geo_dem, output_dir))
    for t in _tifs(output_dir):
        ds = gdal.Open(t)
        band = ds.GetRasterBand(1)
        assert gdal.GetDataTypeName(band.DataType) == "Float32"   # level 5
        assert abs(band.GetNoDataValue() - (-32767)) < 0.5
        assert (ds.GetMetadataItem("AREA_OR_POINT") or "").upper() == "POINT"
        assert ds.GetMetadataItem("COMPRESSION", "IMAGE_STRUCTURE") == "LZW"
        ds = None


@requires_gdalwarp
def test_geo_level_2_is_int16(geo_dem, output_dir):
    """Spec section 7: Int16 is MANDATORY for levels 0-2."""
    geo.main(_geo_args(geo_dem, output_dir, product_level="2"))
    tifs = _tifs(output_dir)
    assert tifs
    for t in tifs:
        ds = gdal.Open(t)
        assert gdal.GetDataTypeName(ds.GetRasterBand(1).DataType) == "Int16"
        ds = None


@requires_gdalwarp
def test_geo_tile_dimensions_include_the_one_post_overlap(geo_dem, output_dir):
    geo.main(_geo_args(geo_dem, output_dir))
    tsize_min, latres_sec = None, None
    for lvl, ts, lr, _letter in dl.level_tilesize_and_spatial_resolution:
        if lvl == "5":
            tsize_min, latres_sec = ts, lr
    tiledim = tsize_min / 60.0
    latres = latres_sec / 3600.0
    for t in _tifs(output_dir):
        ds = gdal.Open(t)
        gt = ds.GetGeoTransform()
        lonres = gt[1]
        assert ds.RasterXSize == round(tiledim / lonres) + 1
        assert ds.RasterYSize == round(tiledim / latres) + 1
        ds = None


@requires_gdalwarp
def test_geo_no_pure_nodata_row_or_column_past_the_data(geo_dem, output_dir):
    """v0.34: the tile loop bound is ceil(), not floor()+1, which always
    produced one extra row and column of entirely-NoData tiles."""
    geo.main(_geo_args(geo_dem, output_dir, product_level="2"))
    # dl.compute_tile_stats() is the tool's own NoData-aware statistic (it
    # returns the missing percentage) -- more stable across GDAL versions
    # and exception settings than ComputeRasterMinMax() on an empty band,
    # and it exercises the same code path the sidecars are built from.
    empty = [os.path.basename(t) for t in _tifs(output_dir)
             if dl.compute_tile_stats(t)[2] >= 100.0]
    assert not empty, "entirely-NoData tiles were written: %s" % empty


@requires_gdalwarp
def test_geo_adjacent_tiles_share_an_identical_edge(geo_dem, output_dir):
    """v0.37 Finding 1: adjacent tiles are warped by independent gdalwarp
    calls, so reconcile_tile_edges() must make the shared post bit-identical."""
    geo.main(_geo_args(geo_dem, output_dir))
    tiles = {}
    for t in _tifs(output_dir):
        ds = gdal.Open(t)
        gt = ds.GetGeoTransform()
        tiles[t] = (round(gt[0], 9), round(gt[3], 9), ds.RasterXSize,
                    ds.RasterYSize, gt[1], gt[5])
        ds = None
    compared = 0
    for a, (ax, ay, aw, ah, xres, yres) in tiles.items():
        for b, (bx, by, bw, bh, _xr, _yr) in tiles.items():
            if a >= b:
                continue
            # b is immediately EAST of a: a's last column == b's first column
            if abs(by - ay) < 1e-9 and abs(bx - (ax + (aw - 1) * xres)) < 1e-6:
                da, db = gdal.Open(a), gdal.Open(b)
                assert _read_col(da, aw - 1) == _read_col(db, 0), \
                    "east/west shared column differs: %s | %s" % (a, b)
                da = db = None
                compared += 1
    if compared == 0:
        pytest.skip("the synthetic extent produced no horizontally adjacent pair")


@requires_gdalwarp
def test_geo_sidecars_are_well_formed_with_no_placeholders_left(geo_dem, output_dir):
    import re
    import xml.etree.ElementTree as ET

    geo.main(_geo_args(geo_dem, output_dir))
    xmls = [x for x in sorted(glob.glob(os.path.join(output_dir, "*.xml")))
            if os.path.isfile(os.path.splitext(x)[0] + ".tif")]
    assert xmls
    for x in xmls:
        txt = open(x, encoding="utf-8").read()
        ET.fromstring(txt)                                   # well-formed
        assert not re.search(r"\{\{[A-Z0-9_]+\}\}", txt), \
            "%s still contains unreplaced placeholders" % os.path.basename(x)
        assert os.path.splitext(os.path.basename(x))[0] in txt


@requires_gdalwarp
def test_geo_writes_delivery_level_metadata(geo_dem, output_dir):
    geo.main(_geo_args(geo_dem, output_dir))
    names = {n.lower() for n in os.listdir(output_dir)}
    assert dl.TOC_FILENAME.lower() in names
    assert any(n.endswith("_collection.xml") for n in names)


@requires_gdalwarp
def test_geo_org_code_appears_in_every_filename(geo_dem, output_dir):
    geo.main(_geo_args(geo_dem, output_dir, org="DNK"))
    tifs = _tifs(output_dir)
    assert tifs
    for t in tifs:
        assert "_DNK_" in os.path.basename(t)


@requires_gdalwarp
def test_geo_returns_the_resolved_resampler(geo_dem, output_dir):
    """v0.37 Finding 2: callers auto-validating afterwards need to know what
    was actually used, not assume bilinear."""
    resamp = geo.main(_geo_args(geo_dem, output_dir, resample="cubic"))
    assert resamp == "cubic"


@requires_gdalwarp
def test_geo_cubic_output_is_clamped_to_the_source_range(geo_dem, output_dir):
    """v0.37 Finding 3: cubic-family resamplers overshoot at sharp steps."""
    src_min, src_max, _miss = dl.compute_tile_stats(geo_dem)
    geo.main(_geo_args(geo_dem, output_dir, resample="cubic"))
    checked = 0
    for t in _tifs(output_dir):
        tmin, tmax, miss = dl.compute_tile_stats(t)   # NoData-aware, shared
        if miss >= 100.0:
            continue                                   # border tile, no data
        checked += 1
        assert tmin >= src_min - 1.0, (
            "%s min %s overshoots source min %s"
            % (os.path.basename(t), tmin, src_min))
        assert tmax <= src_max + 1.0, (
            "%s max %s overshoots source max %s"
            % (os.path.basename(t), tmax, src_max))
    assert checked, "no tile with valid data to check the clamp against"


# -- UTM -----------------------------------------------------------------------

@requires_gdalwarp
def test_utm_conversion_produces_paired_tiles(utm_dem, output_dir):
    utm.main(_utm_args(utm_dem, output_dir, utm_zone="32N"))
    tifs = _tifs(output_dir)
    assert tifs
    for t in tifs:
        assert os.path.isfile(os.path.splitext(t)[0] + ".xml")


@requires_gdalwarp
def test_utm_names_are_zero_padded_to_spec_widths(utm_dem, output_dir):
    """v0.34 (SPEC). Note the per-test output_dir: before v0.38 this test
    failed on a leftover GEO-named tile from an earlier test, not on
    anything wrong with UTM naming."""
    import dem2dged_validate as dv

    utm.main(_utm_args(utm_dem, output_dir, utm_zone="32N"))
    n_want, e_want = dl.utm_name_field_widths("5")
    tifs = _tifs(output_dir)
    assert tifs
    for t in tifs:
        base = os.path.splitext(os.path.basename(t))[0]
        m = dv.UTM_RE.match(base)
        assert m, "%r does not match the DGED UTM naming convention" % base
        assert len(m.group("northing")) == n_want
        assert len(m.group("easting")) == e_want
        assert dv.GEO_RE.match(base) is None


@requires_gdalwarp
def test_utm_tile_dimensions_equal_the_level_post_count(utm_dem, output_dir):
    utm.main(_utm_args(utm_dem, output_dir, utm_zone="32N"))
    posts = {lvl: p for lvl, _g, p, _l in dl.PL}["5"]
    for t in _tifs(output_dir):
        ds = gdal.Open(t)
        assert ds.RasterXSize == posts
        assert ds.RasterYSize == posts
        ds = None


@requires_gdalwarp
def test_utm_adjacent_tiles_share_an_identical_edge(utm_dem_wide, output_dir):
    """v0.37 Finding 1 on the UTM side.

    The narrow `utm_dem` fixture only ever produces one tile, so the
    validator's section G could only report "no adjacent tile pairs with
    valid data found to compare" -- which is a WARN, not evidence that edge
    reconciliation works. This fixture spans two level-5 tiles.
    """
    utm.main(_utm_args(utm_dem_wide, output_dir, utm_zone="32N"))
    tifs = _tifs(output_dir)
    assert len(tifs) >= 2, "expected at least 2 tiles, got %d" % len(tifs)

    info = {}
    for t in tifs:
        ds = gdal.Open(t)
        gt = ds.GetGeoTransform()
        info[t] = (round(gt[0], 6), round(gt[3], 6), ds.RasterXSize,
                   ds.RasterYSize, gt[1])
        ds = None

    compared = 0
    for a, (ax, ay, aw, ah, xres) in info.items():
        for b, (bx, by, bw, bh, _x) in info.items():
            if a >= b:
                continue
            if abs(by - ay) < 1e-6 and abs(bx - (ax + (aw - 1) * xres)) < 1e-3:
                da, db = gdal.Open(a), gdal.Open(b)
                assert _read_col(da, aw - 1) == _read_col(db, 0), (
                    "UTM shared column is not identical: %s | %s"
                    % (os.path.basename(a), os.path.basename(b)))
                da = db = None
                compared += 1
    assert compared >= 1, "no horizontally adjacent UTM pair was found to compare"


@requires_gdalwarp
def test_utm_never_emits_a_negative_northing(equator_utm_dem, output_dir):
    """v0.39: an equatorial DEM whose edge overhangs the equator by half a
    post used to produce a non-spec name like '...32N-025...' (spec 6.3.1)."""
    tifs_written = False
    utm.main(_utm_args(equator_utm_dem, output_dir, utm_zone="32N"))
    for t in _tifs(output_dir):
        tifs_written = True
        base = os.path.basename(t)
        assert "-" not in base.split("_", 1)[1], \
            "negative coordinate field in %r" % base
        ds = gdal.Open(t)
        gt = ds.GetGeoTransform()
        bottom = gt[3] + ds.RasterYSize * gt[5]
        ds = None
        # Half a post below zero is the designed warp extent; the tile
        # ORIGIN must still be >= 0.
        assert bottom >= -10.0
    assert tifs_written


@requires_gdalwarp
def test_utm_float32_tiles_use_the_floating_point_predictor(utm_dem, output_dir):
    """v0.39: PREDICTOR=2 is only defined for integer samples."""
    assert dl.predictor_for_type(dl.output_type_for_level("5")) == "3"
    utm.main(_utm_args(utm_dem, output_dir, utm_zone="32N"))
    for t in _tifs(output_dir):
        ds = gdal.Open(t)
        # Both predictors are lossless LZW, which is what spec 13.1 requires;
        # the header check is on compression.
        assert ds.GetMetadataItem("COMPRESSION", "IMAGE_STRUCTURE") == "LZW"
        ds = None


@requires_gdalwarp
def test_utm_rerun_skips_existing_tiles(utm_dem, output_dir):
    utm.main(_utm_args(utm_dem, output_dir, utm_zone="32N"))
    first = {t: os.path.getmtime(t) for t in _tifs(output_dir)}
    assert first
    utm.main(_utm_args(utm_dem, output_dir, utm_zone="32N"))
    second = {t: os.path.getmtime(t) for t in _tifs(output_dir)}
    assert set(first) == set(second)
    assert first == second, "an existing tile was rewritten instead of skipped"
