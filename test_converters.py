# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.54.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""End-to-end conversion tests: run the real converters, then inspect what
actually landed on disk.

REQUIRES the gdalwarp EXECUTABLE on PATH -- dem2dged_lib.run_cmd() shells
out to it for every tile. Without it these tests SKIP rather than fail; the
release gate (RELEASE_CHECK_v0.45.py step 03) reports how many skipped, and
a run where all of them skipped is not evidence that conversion works.

THE main() CALLING CONVENTION -- read this before adding a test
---------------------------------------------------------------
dem2dged_geo.main() and dem2dged_utm.main() take a RAW ARGV LIST, not a
parsed argparse Namespace. They call parser.parse_args(args[1:])
themselves, so element 0 must be the program name -- which is exactly how
dem2dged.py calls them:

    mod.main(["dem2dged_geo.py", input_raster, output_folder, ...])

v0.41 finding 12: the previous cut of this file passed a Namespace. All 22
integration tests errored identically with "TypeError: 'Namespace' object is
not subscriptable" the first time they were ever actually executed. The
_geo_argv / _utm_argv helpers below exist so no test has to remember this.

A second lesson from the same release: assertions here do NOT use
band.ComputeRasterMinMax(), whose behaviour on an all-NoData band varies
with the GDAL version and the exception setting. They use the tool's own
NoData-aware dem2dged_lib.compute_tile_stats() instead.
"""

import glob
import os
import xml.etree.ElementTree as ET

import pytest

import dem2dged_lib as dl
import dem2dged_geo
import dem2dged_utm
import dem2dged_validate as dv
from conftest import requires_gdalwarp

pytestmark = [pytest.mark.integration, requires_gdalwarp]

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO_TEMPLATE = os.path.join(PROJECT_DIR, "DGED_GEO_TEMPLATE.xml")
UTM_TEMPLATE = os.path.join(PROJECT_DIR, "DGED_UTM_TEMPLATE.xml")


# -- argv builders (see the module docstring) ---------------------------------

def _geo_argv(src, out, level="5", **kw):
    argv = ["dem2dged_geo.py", src, out,
            "-product_level", level,
            "-xml_template", GEO_TEMPLATE]
    for key, value in kw.items():
        argv += ["-" + key, str(value)]
    return argv


def _utm_argv(src, out, level="5", zone="32N", **kw):
    argv = ["dem2dged_utm.py", src, out,
            "-product_level", level,
            "-utm_zone", zone,
            "-xml_template", UTM_TEMPLATE]
    for key, value in kw.items():
        argv += ["-" + key, str(value)]
    return argv


def _tifs(folder):
    return sorted(glob.glob(os.path.join(folder, "*.tif")))


def _open(path):
    ds = dl.gdal_open(path)
    assert ds is not None, "GDAL could not open %s" % path
    return ds


# =============================================================================
# GEO conversion
# =============================================================================

def test_geo_conversion_produces_paired_tif_and_xml(geo_source, output_dir):
    dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    tifs = _tifs(output_dir)
    assert tifs, "no tiles were produced at all"
    for tif in tifs:
        assert os.path.isfile(tif[:-4] + ".xml"), "no sidecar for %s" % tif


def test_geo_conversion_returns_the_resolved_resampler(geo_source, output_dir):
    """v0.37 Finding 2: the converters return the RESOLVED algorithm so
    dem2dged.py can tell the validator what was actually used, instead of
    the validator assuming Bilinear and partly measuring "how different is
    this from bilinear"."""
    used = dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    assert used in dl.VALID_RESAMPLERS
    assert used not in ("auto", "optimize"), "an unresolved meta-value leaked"


def test_geo_tiles_have_the_spec_header_profile(geo_source, output_dir):
    dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    for tif in _tifs(output_dir):
        ds = _open(tif)
        band = ds.GetRasterBand(1)
        assert band.GetNoDataValue() == pytest.approx(-32767.0)
        assert (ds.GetMetadataItem("AREA_OR_POINT") or "").upper() == "POINT"
        assert ds.GetMetadataItem("COMPRESSION", "IMAGE_STRUCTURE") == "LZW"
        ds = None


@pytest.mark.parametrize("level,expected_type", [("2", "Int16"),
                                                 ("5", "Float32")])
def test_geo_data_type_is_level_aware(geo_source, output_dir, level,
                                      expected_type):
    """Spec section 7: Int16 is MANDATORY for levels 0-2."""
    from osgeo import gdal
    dem2dged_geo.main(_geo_argv(geo_source, output_dir, level=level))
    tifs = _tifs(output_dir)
    assert tifs
    for tif in tifs:
        ds = _open(tif)
        name = gdal.GetDataTypeName(ds.GetRasterBand(1).DataType)
        assert name == expected_type, "%s: %s" % (tif, name)
        ds = None


@pytest.mark.parametrize("level,expected_predictor", [("2", "2"), ("5", "3")])
def test_geo_lzw_predictor_matches_the_data_type(geo_source, output_dir,
                                                 level, expected_predictor):
    """v0.39: PREDICTOR=2 is only defined for integer samples; Float32
    needs PREDICTOR=3. Verified on the bytes actually written."""
    dem2dged_geo.main(_geo_argv(geo_source, output_dir, level=level))
    for tif in _tifs(output_dir):
        ds = _open(tif)
        pred = ds.GetMetadataItem("PREDICTOR", "IMAGE_STRUCTURE")
        assert pred in (None, expected_predictor), "%s: %s" % (tif, pred)
        ds = None


def test_geo_tile_dimensions_include_the_shared_post(geo_source, output_dir):
    """A tile has tiledim/res + 1 posts per axis; the "+1" IS the post
    shared with the next tile (spec 13.2). The longitude count additionally
    reflects the zone factor -- at 55.5 N that is x1.5, so a level-5 tile is
    4001 x 6001, not 6001 x 6001."""
    dem2dged_geo.main(_geo_argv(geo_source, output_dir, level="5"))
    tiledim, latres, _letter = dem2dged_geo.resolve_level_geo("5")
    for tif in _tifs(output_dir):
        ds = _open(tif)
        gt = ds.GetGeoTransform()
        lonres = dem2dged_geo.resolve_lon_multiplication(
            gt[3] + gt[5] * ds.RasterYSize) * latres
        assert ds.RasterYSize == round(tiledim / latres) + 1
        assert ds.RasterXSize == round(tiledim / lonres) + 1
        ds = None


def test_geo_origin_is_half_a_post_outside_the_nominal_corner(geo_source,
                                                              output_dir):
    """v0.27: the warp extent is half-post expanded so PIXEL CENTRES land on
    DGED post locations. The reported corner therefore sits half a post
    OUTSIDE the tile origin -- by design, and the validator's _origin_close()
    is written around it."""
    dem2dged_geo.main(_geo_argv(geo_source, output_dir, level="5"))
    tiledim, latres, _ = dem2dged_geo.resolve_level_geo("5")
    for tif in _tifs(output_dir):
        ds = _open(tif)
        gt = ds.GetGeoTransform()
        centre_x = gt[0] + gt[1] / 2.0
        nominal = round(centre_x / tiledim) * tiledim
        assert dv._origin_close(centre_x, nominal, gt[1]), (tif, centre_x)
        ds = None


def test_geo_names_parse_and_agree_with_the_georeferencing(geo_source,
                                                           output_dir):
    """The name encodes the tile origin. If the name and the geotransform
    disagree, the delivery is unusable even though every individual file
    looks fine."""
    dem2dged_geo.main(_geo_argv(geo_source, output_dir, level="5"))
    for tif in _tifs(output_dir):
        base = os.path.basename(tif)[:-4]
        m = dv.GEO_RE.match(base)
        assert m, base
        ds = _open(tif)
        gt = ds.GetGeoTransform()
        name_lon = dv.dms_to_deg(m.group("lon"), False)
        name_lat = dv.dms_to_deg(m.group("lat"), True)
        if m.group("east") == "W":
            name_lon = -name_lon
        if m.group("hemi") == "S":
            name_lat = -name_lat
        real_lon = gt[0] + gt[1] / 2.0
        real_lat = gt[3] + gt[5] * ds.RasterYSize - gt[5] / 2.0
        assert name_lon == pytest.approx(real_lon, abs=gt[1])
        assert name_lat == pytest.approx(real_lat, abs=abs(gt[5]))
        ds = None


def test_no_pure_nodata_row_or_column_of_tiles(geo_source, output_dir):
    """v0.34: the tile loop bound was floor()+1, which unconditionally added
    a row and a column of tiles past the data. On a 1x1 degree level-5
    source that was 21 of 121 tiles, each costing a warp, a stats pass, a
    sidecar and a TOC entry -- all containing nothing but NoData."""
    dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    empty = [t for t in _tifs(output_dir)
             if dl.compute_tile_stats(t)[2] >= 100.0]
    assert not empty, "entirely-NoData tiles were delivered: %s" % empty


def test_geo_adjacent_tiles_share_a_bit_identical_column(geo_source,
                                                         output_dir):
    """v0.37 Finding 1, the half that arithmetic alone cannot guarantee:
    adjacent tiles are warped by INDEPENDENT gdalwarp calls, and on the real
    DGIWG level-4b test set Nearest Neighbor picked a different source pixel
    for the shared row in the two warps -- a 1.6 m seam on 5 m posts.
    reconcile_tile_edges() copies the edge so the two files are identical
    along it no matter what either warp did internally.

    v0.43: this test used to end with
    ``pytest.skip("no vertically adjacent pair in this fixture")`` and it
    ALWAYS took that branch, because ``geo_source`` spans two tiles in
    longitude and one in latitude. So it reported a skip forever while
    reading as though it covered row seams. Row and corner coverage now
    lives in ``test_a_two_by_two_tile_grid_matches_on_every_seam_and_corner``
    below, where it is real; this test is scoped to what its own fixture
    actually produces -- the COLUMN seam, on full-size Float32 level-5
    tiles -- and asserts it unconditionally instead of skipping.
    """
    import numpy as np
    dem2dged_geo.main(_geo_argv(geo_source, output_dir, level="5"))
    tifs = _tifs(output_dir)
    assert len(tifs) >= 2, (
        "geo_source must span at least two tiles for this test to mean "
        "anything; got %d" % len(tifs))

    by_origin = {}
    for tif in tifs:
        ds = _open(tif)
        gt = ds.GetGeoTransform()
        by_origin[(round(gt[0], 6), round(gt[3], 6))] = (tif, ds)

    compared = 0
    for (x0, y0), (tif_a, ds_a) in by_origin.items():
        gt_a = ds_a.GetGeoTransform()
        # the tile directly EAST: its left column is our right column
        east_x = round(x0 + gt_a[1] * (ds_a.RasterXSize - 1), 6)
        for (x1, y1), (tif_b, ds_b) in by_origin.items():
            if round(x1, 6) != east_x or round(y1, 6) != round(y0, 6):
                continue
            right = ds_a.GetRasterBand(1).ReadAsArray(
                ds_a.RasterXSize - 1, 0, 1, ds_a.RasterYSize)
            left = ds_b.GetRasterBand(1).ReadAsArray(
                0, 0, 1, ds_b.RasterYSize)
            assert right.shape == left.shape
            assert np.array_equal(right, left), (
                "shared column differs between %s and %s (max |diff| %s)"
                % (os.path.basename(tif_a), os.path.basename(tif_b),
                   float(np.nanmax(np.abs(right - left)))))
            compared += 1
    for _tif, ds in by_origin.values():
        ds = None
    assert compared >= 1, "no horizontally adjacent pair was compared"


def test_a_two_by_two_tile_grid_matches_on_every_seam_and_corner(
        geo_grid_source, output_dir):
    """v0.43, and the reason this fixture exists.

    reconcile_tile_edges() has TWO passes: pass 1 copies each south tile's
    top row onto its north neighbour's bottom row, pass 2 does the same for
    west/east columns. Until now every edge test in the suite produced tiles
    that were side by side only, so pass 2 was covered and **pass 1 was
    never executed at all** — the v0.42 release gate reported it as
    "1 skipped: no vertically adjacent pair in this fixture".

    A 2 x 2 grid covers both passes plus the thing the pass ORDER exists to
    protect: the single post shared by all four tiles at the centre corner.
    If the column pass ran first, it would read each tile's original edge
    rather than its already-row-corrected one, and that corner post could
    end up with three different values across four files.
    """
    import numpy as np
    dem2dged_geo.main(_geo_argv(geo_grid_source, output_dir, level="0"))
    tifs = _tifs(output_dir)
    assert len(tifs) == 4, "expected a 2x2 grid, got %d tile(s): %s" % (
        len(tifs), [os.path.basename(t) for t in tifs])

    grid = {}
    for tif in tifs:
        ds = _open(tif)
        gt = ds.GetGeoTransform()
        south = gt[3] + gt[5] * (ds.RasterYSize - 1)
        grid[(round(south, 6), round(gt[0], 6))] = (tif, ds)

    souths = sorted({k[0] for k in grid})
    wests = sorted({k[1] for k in grid})
    assert len(souths) == 2 and len(wests) == 2, (souths, wests)

    rows_checked = cols_checked = 0
    for (s, w), (tif_a, ds_a) in grid.items():
        band_a = ds_a.GetRasterBand(1)

        # NORTH neighbour: our top row is its bottom row.
        north = [k for k in grid if k[1] == w and k[0] > s]
        for key in north:
            tif_b, ds_b = grid[key]
            mine = band_a.ReadAsArray(0, 0, ds_a.RasterXSize, 1)
            theirs = ds_b.GetRasterBand(1).ReadAsArray(
                0, ds_b.RasterYSize - 1, ds_b.RasterXSize, 1)
            assert np.array_equal(mine, theirs), (
                "ROW seam differs: %s top vs %s bottom"
                % (os.path.basename(tif_a), os.path.basename(tif_b)))
            rows_checked += 1

        # EAST neighbour: our right column is its left column.
        east = [k for k in grid if k[0] == s and k[1] > w]
        for key in east:
            tif_b, ds_b = grid[key]
            mine = band_a.ReadAsArray(ds_a.RasterXSize - 1, 0, 1,
                                      ds_a.RasterYSize)
            theirs = ds_b.GetRasterBand(1).ReadAsArray(
                0, 0, 1, ds_b.RasterYSize)
            assert np.array_equal(mine, theirs), (
                "COLUMN seam differs: %s right vs %s left"
                % (os.path.basename(tif_a), os.path.basename(tif_b)))
            cols_checked += 1

    assert rows_checked == 2, "row seams checked: %d (expected 2)" % rows_checked
    assert cols_checked == 2, "column seams checked: %d (expected 2)" % cols_checked

    # The shared CORNER post: bottom-left of the NE tile, top-right of the
    # SE tile, etc. All four tiles must agree on the single post at
    # (souths[1], wests[1]) -- this is what pass ordering protects.
    corner_values = []
    for (s, w), (tif, ds) in grid.items():
        band = ds.GetRasterBand(1)
        x = 0 if w == wests[1] else ds.RasterXSize - 1
        y = ds.RasterYSize - 1 if s == souths[1] else 0
        corner_values.append((os.path.basename(tif),
                              float(band.ReadAsArray(x, y, 1, 1)[0][0])))
    distinct = {v for _n, v in corner_values}
    assert len(distinct) == 1, (
        "the post shared by all four tiles has %d different values: %s"
        % (len(distinct), corner_values))

    for _tif, ds in grid.values():
        ds = None


def test_level_0_tiles_are_int16_with_predictor_2(geo_grid_source, output_dir):
    """The Int16 path, end to end. Every other tile this suite produces is
    Float32, so without this the v0.39 PREDICTOR=2 branch is only ever
    checked as a pure function, never on bytes actually written."""
    from osgeo import gdal
    dem2dged_geo.main(_geo_argv(geo_grid_source, output_dir, level="0"))
    tifs = _tifs(output_dir)
    assert tifs
    for tif in tifs:
        ds = _open(tif)
        assert gdal.GetDataTypeName(ds.GetRasterBand(1).DataType) == "Int16"
        pred = ds.GetMetadataItem("PREDICTOR", "IMAGE_STRUCTURE")
        assert pred in (None, "2"), "%s: PREDICTOR=%s" % (tif, pred)
        ds = None


def test_geo_sidecars_are_well_formed_and_fully_substituted(geo_source,
                                                            output_dir):
    """v0.28 shipped a truncated DGED_UTM_TEMPLATE.xml that made every UTM
    sidecar not-well-formed; v0.31 shipped sidecars still containing
    {{PLACEHOLDER}} text, which is valid XML and therefore invisible to a
    well-formedness check alone. Both are checked here."""
    dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    xmls = sorted(glob.glob(os.path.join(output_dir, "*.xml")))
    assert xmls
    for path in xmls:
        text = open(path, encoding="utf-8").read()
        ET.fromstring(text)                       # raises if malformed
        assert not dv._has_unreplaced_placeholder(text), path


def test_delivery_level_metadata_is_written(geo_source, output_dir):
    dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    toc = os.path.join(output_dir, dl.TOC_FILENAME)
    assert os.path.isfile(toc)
    ET.fromstring(open(toc, encoding="utf-8").read())
    if len(_tifs(output_dir)) > 1:
        colls = glob.glob(os.path.join(output_dir, "*_COLLECTION.xml"))
        assert colls, "more than one tile but no collection metadata"
        ET.fromstring(open(colls[0], encoding="utf-8").read())


def test_rerunning_skips_existing_tiles(geo_source, output_dir):
    """The resume path. A second run must not re-warp or modify a tile that
    was already delivered -- reconcile_tile_edges() is deliberately given
    only the tiles created in THIS run for exactly that reason."""
    dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    first = {t: os.path.getmtime(t) for t in _tifs(output_dir)}
    assert first
    dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    second = {t: os.path.getmtime(t) for t in _tifs(output_dir)}
    assert set(first) == set(second)
    assert first == second, "an existing tile was rewritten on a re-run"


# =============================================================================
# UTM conversion
# =============================================================================

def test_utm_conversion_produces_tiles(utm_source, output_dir):
    dem2dged_utm.main(_utm_argv(utm_source, output_dir))
    assert _tifs(output_dir)


def test_utm_names_are_zero_padded_on_disk(utm_source, output_dir):
    """v0.34, checked against real filenames rather than the helper alone."""
    dem2dged_utm.main(_utm_argv(utm_source, output_dir, level="5"))
    n_width, e_width = dl.utm_name_field_widths("5")
    for tif in _tifs(output_dir):
        base = os.path.basename(tif)[:-4]
        m = dv.UTM_RE.match(base)
        assert m, base
        assert len(m.group("northing")) == n_width, base
        assert len(m.group("easting")) == e_width, base


def test_utm_tile_is_the_declared_number_of_posts(utm_source, output_dir):
    dem2dged_utm.main(_utm_argv(utm_source, output_dir, level="5"))
    gsd, posts, _letter = dem2dged_utm.resolve_level_utm("5")
    for tif in _tifs(output_dir):
        ds = _open(tif)
        assert (ds.RasterXSize, ds.RasterYSize) == (posts, posts)
        gt = ds.GetGeoTransform()
        assert gt[1] == pytest.approx(gsd)
        assert abs(gt[5]) == pytest.approx(gsd)
        ds = None


def test_utm_adjacent_tiles_share_an_identical_edge(utm_source, output_dir):
    """The UTM half of v0.37 Finding 1. The v0.41 release run used a 4 km
    source against a 10 km level-5 tile, produced ONE tile, and section G
    could only warn "no adjacent tile pairs" -- so this path had never
    actually been exercised. The fixture is 12 km wide for that reason."""
    import numpy as np
    dem2dged_utm.main(_utm_argv(utm_source, output_dir, level="5"))
    tifs = _tifs(output_dir)
    if len(tifs) < 2:
        pytest.skip("fixture produced a single tile -- no shared edge")

    entries = []
    for tif in tifs:
        ds = _open(tif)
        gt = ds.GetGeoTransform()
        entries.append((round(gt[0], 3), round(gt[3], 3), tif, ds))

    compared = 0
    for x0, y0, tif_a, ds_a in entries:
        east_x = round(x0 + ds_a.GetGeoTransform()[1] * (ds_a.RasterXSize - 1), 3)
        for x1, y1, tif_b, ds_b in entries:
            if x1 != east_x or y1 != y0:
                continue
            right = ds_a.GetRasterBand(1).ReadAsArray(
                ds_a.RasterXSize - 1, 0, 1, ds_a.RasterYSize)
            left = ds_b.GetRasterBand(1).ReadAsArray(
                0, 0, 1, ds_b.RasterYSize)
            assert np.array_equal(right, left), (
                "shared column differs between %s and %s"
                % (os.path.basename(tif_a), os.path.basename(tif_b)))
            compared += 1
    if compared == 0:
        pytest.skip("no horizontally adjacent pair in this fixture")


def test_utm_northing_is_never_negative(equatorial_utm_source, output_dir):
    """v0.39. A point-registered equatorial source overhangs the equator by
    half a post, so a northern zone used to emit a tile at a NEGATIVE
    northing and a non-spec name like "...32N-025...". Spec 6.3.1 puts
    northings on [0, 10 000 000] m."""
    dem2dged_utm.main(_utm_argv(equatorial_utm_source, output_dir, level="5"))
    for tif in _tifs(output_dir):
        base = os.path.basename(tif)
        assert "-" not in base, base
        m = dv.UTM_RE.match(base[:-4])
        assert m, base
        assert 0 <= int(m.group("northing")) * 1000 <= 10_000_000
        ds = _open(tif)
        assert ds.GetGeoTransform()[3] >= 0
        ds = None


# =============================================================================
# Resampling behaviour
# =============================================================================

def test_cubic_overshoot_is_clamped_to_the_source_range(step_edge_source,
                                                        output_dir):
    """v0.37 Finding 3. Cubic-family kernels RING at a sharp discontinuity:
    on the real DGIWG 8-bit step-edge rasters (0-255 and 6-255) Cubic
    Convolution produced tiles reaching -44 m and 313 m -- physically
    impossible elevation, and silent unless someone read section H closely.
    Tiles made with one of these resamplers are clamped back into the
    source's exact range straight after warping."""
    src_min, src_max, _ = dl.compute_tile_stats(step_edge_source)
    dem2dged_utm.main(_utm_argv(step_edge_source, output_dir, level="5",
                                resample="cubic"))
    tifs = _tifs(output_dir)
    assert tifs
    for tif in tifs:
        vmin, vmax, miss = dl.compute_tile_stats(tif)
        if miss >= 100.0:
            continue
        assert vmin >= src_min, "%s undershoots: %s < %s" % (tif, vmin, src_min)
        assert vmax <= src_max, "%s overshoots: %s > %s" % (tif, vmax, src_max)


def test_auto_resampling_never_needs_clamping(step_edge_source, output_dir):
    """The other half of the same finding: the resamplers dem2dged chooses
    on its own (average, bilinear) cannot overshoot, which is exactly why
    they are the automatic choices."""
    src_min, src_max, _ = dl.compute_tile_stats(step_edge_source)
    used = dem2dged_utm.main(_utm_argv(step_edge_source, output_dir,
                                       level="5", resample="auto"))
    assert used in ("average", "bilinear")
    for tif in _tifs(output_dir):
        vmin, vmax, miss = dl.compute_tile_stats(tif)
        if miss < 100.0:
            assert src_min <= vmin and vmax <= src_max


# =============================================================================
# v0.42 pre-flight guards, end to end
# =============================================================================

def test_a_bad_resampler_stops_before_any_tile_is_written(geo_source,
                                                          output_dir):
    """The whole point of the v0.42 guard: fail once, up front, with an
    EMPTY output folder -- not once per tile after the damage is done."""
    with pytest.raises(SystemExit) as e:
        dem2dged_geo.main(_geo_argv(geo_source, output_dir,
                                    resample="bilinier"))
    assert "bilinier" in str(e.value)
    assert _tifs(output_dir) == []


def test_an_untagged_source_fails_with_a_message_naming_the_file(
        untagged_source, output_dir):
    """v0.42: this used to be "TypeError: int() argument must be ... not
    'NoneType'" from inside get_bbox_of_output(), which names neither the
    file nor the problem."""
    with pytest.raises(SystemExit) as e:
        dem2dged_geo.main(_geo_argv(untagged_source, output_dir))
    msg = str(e.value)
    assert os.path.basename(untagged_source) in msg
    assert "EPSG" in msg
    assert _tifs(output_dir) == []


def test_an_unknown_level_is_rejected_with_the_valid_list(geo_source,
                                                          output_dir):
    with pytest.raises(SystemExit) as e:
        dem2dged_geo.main(_geo_argv(geo_source, output_dir, level="42"))
    assert "4b" in str(e.value)


@pytest.mark.parametrize("zone", ["32X", "0N", "61N", "abc"])
def test_an_invalid_utm_zone_is_rejected(utm_source, output_dir, zone):
    with pytest.raises(SystemExit):
        dem2dged_utm.main(_utm_argv(utm_source, output_dir, zone=zone))


# =============================================================================
# The converter -> validator round trip
# =============================================================================

def test_a_fresh_geo_delivery_validates_clean(geo_source, output_dir):
    """The single most valuable test in the suite: the tool's own validator
    is run against the tool's own output, so converter and validator have to
    agree about the spec rather than each being self-consistently wrong."""
    used = dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    rep, tiles = dv.run_validation(output_dir, src=geo_source,
                                   resample=used)
    assert tiles, "the validator parsed no tiles from a fresh delivery"
    assert rep.n_fail == 0, "\n".join(rep.lines[-60:])


def test_a_fresh_utm_delivery_validates_clean(utm_source, output_dir):
    used = dem2dged_utm.main(_utm_argv(utm_source, output_dir))
    rep, tiles = dv.run_validation(output_dir, src=utm_source,
                                   resample=used)
    assert tiles
    assert rep.n_fail == 0, "\n".join(rep.lines[-60:])


def test_both_report_formats_are_written(geo_source, output_dir, tmp_path):
    """v0.38: a UnicodeEncodeError in the console echo used to take BOTH
    report files with it, even though validation had already succeeded."""
    used = dem2dged_geo.main(_geo_argv(geo_source, output_dir))
    rep, tiles = dv.run_validation(output_dir, src=geo_source, resample=used)
    txt = str(tmp_path / "r.txt")
    html = str(tmp_path / "r.html")
    assert dv.write_text_report(rep, txt) is True
    dv.write_html_report([{"name": "d", "src": geo_source, "rep": rep,
                           "tiles": tiles}], html)
    assert os.path.getsize(txt) > 0
    assert os.path.getsize(html) > 0
    assert "RESULT:" in open(txt, encoding="utf-8").read()
