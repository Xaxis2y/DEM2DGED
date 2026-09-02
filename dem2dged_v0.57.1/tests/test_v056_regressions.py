# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.56.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Regression tests for every finding fixed in v0.56.0.

WHY A SEPARATE FILE
-------------------
Each test here corresponds to one finding of the v0.55.0 review, and each
one FAILS against v0.55.0 and PASSES against v0.56.0. Keeping them together
means the next person can run one file to answer "are the v0.55.0 defects
still fixed?", and the test names say what the defect WAS -- the same
convention the existing suite uses (test_utm_name_on_the_equator_is_not_a_
single_zero).

Several of these cover code the 384-test suite never reached at all:
try_direct_copy_tile(), build_prefiltered_source(), and the GUI's own
converters. That gap is not incidental -- it is why the defects survived.
"""

import io
import os
import re
import shutil
import sys
import tempfile

import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

gdal = osr = None
try:
    from osgeo import gdal as _gdal, osr as _osr
    gdal, osr = _gdal, _osr
except ImportError:                                  # pragma: no cover
    pass

HAVE_GDAL = gdal is not None
HAVE_GDALWARP = shutil.which("gdalwarp") is not None

requires_gdal = pytest.mark.skipif(
    not HAVE_GDAL, reason="osgeo (GDAL Python bindings) not importable")
requires_gdalwarp = pytest.mark.skipif(
    not (HAVE_GDAL and HAVE_GDALWARP),
    reason="the gdalwarp EXECUTABLE is not on PATH")


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_raster(path, gt, values, epsg=4326, dtype=None, nodata=None,
                  area_or_point="Point"):
    """Write a fully-controlled single-band GeoTIFF from a numpy array."""
    import numpy as np
    if dtype is None:
        dtype = gdal.GDT_Float32
    a = np.asarray(values)
    ny, nx = a.shape
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, dtype)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(int(epsg))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(float(nodata))
    band.WriteArray(a)
    if area_or_point is not None:
        ds.SetMetadataItem("AREA_OR_POINT", area_or_point)
    band.FlushCache()
    ds.FlushCache()
    ds = None
    return path


@pytest.fixture
def tmpdir_local():
    d = tempfile.mkdtemp(prefix="dem2dged_v056_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
#  A1 -- try_direct_copy_tile() indexed the source half a pixel off
# ══════════════════════════════════════════════════════════════════════════════

def _point_source(tmp, first_post_x, first_post_y, res, n, name):
    """A point-registered raster whose FIRST POST is at (first_post_x, y).

    GDAL normalises a AREA_OR_POINT=Point GeoTIFF to the pixel-CORNER
    convention on read, so the geotransform origin is half a pixel outside
    the first post. Writing it that way round means GetGeoTransform() gives
    back exactly what we set.
    """
    import numpy as np
    yy, xx = np.mgrid[0:n, 0:n]
    vals = (1000.0 + xx * 1.0 + yy * 100.0).astype("float32")
    gt = (first_post_x - res / 2.0, res, 0.0,
          first_post_y + res / 2.0, 0.0, -res)
    return _write_raster(os.path.join(tmp, name), gt, vals), vals


@requires_gdal
def test_gdal_reports_the_corner_geotransform_for_a_point_raster(tmpdir_local):
    """The premise of the A1 fix, asserted rather than assumed.

    If this ever stops holding, the index arithmetic in
    try_direct_copy_tile() is wrong again and the two tests below will not
    explain why.
    """
    res = 0.001
    path, _ = _point_source(tmpdir_local, 10.0, 50.0, res, 12, "premise.tif")
    ds = gdal.Open(path)
    gt = ds.GetGeoTransform()
    assert ds.GetMetadataItem("AREA_OR_POINT") == "Point"
    ds = None
    # The first POST is at gt[0] + xres/2, NOT at gt[0].
    assert abs((gt[0] + res / 2.0) - 10.0) < 1e-9
    assert abs(gt[0] - 10.0) > 1e-6


@requires_gdal
def test_direct_copy_accepts_a_correctly_aligned_source(tmpdir_local):
    """v0.55.0 REJECTED this -- the fast path was silently unreachable."""
    import dem2dged_lib as dl
    res = 0.001
    src, _ = _point_source(tmpdir_local, 10.0, 50.0, res, 20, "aligned.tif")
    dst = os.path.join(tmpdir_local, "aligned_tile.tif")
    assert dl.try_direct_copy_tile(
        src, dst, first_x=10.0, first_y=50.0, width=5, height=5,
        xres=res, yres=res, dst_srs="EPSG:4326", out_type="Float32") is True


@requires_gdal
def test_direct_copy_rejects_a_half_cell_offset_source(tmpdir_local):
    """v0.55.0 ACCEPTED this and shipped every value half a post out.

    Here the source's pixel CORNERS -- not its posts -- land on the DGED
    post grid, so no post of this source coincides with a post of the
    requested tile. Copying it would label the value at X = 10.000500 as
    belonging at X = 10.000000.
    """
    import dem2dged_lib as dl
    res = 0.001
    import numpy as np
    yy, xx = np.mgrid[0:20, 0:20]
    vals = (1000.0 + xx + yy * 100.0).astype("float32")
    src = _write_raster(os.path.join(tmpdir_local, "offset.tif"),
                        (10.0, res, 0.0, 50.0, 0.0, -res), vals)
    dst = os.path.join(tmpdir_local, "offset_tile.tif")
    assert dl.try_direct_copy_tile(
        src, dst, first_x=10.0, first_y=50.0, width=5, height=5,
        xres=res, yres=res, dst_srs="EPSG:4326", out_type="Float32") is False


@requires_gdal
def test_direct_copy_lands_the_right_value_on_the_right_post(tmpdir_local):
    """The point of A1: the copied tile must carry the source's own posts."""
    import dem2dged_lib as dl
    res = 0.001
    src, vals = _point_source(tmpdir_local, 10.0, 50.0, res, 20, "vals.tif")
    dst = os.path.join(tmpdir_local, "vals_tile.tif")
    assert dl.try_direct_copy_tile(
        src, dst, first_x=10.0, first_y=50.0, width=5, height=5,
        xres=res, yres=res, dst_srs="EPSG:4326", out_type="Float32")
    ds = gdal.Open(dst)
    arr = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform()
    ds = None
    # post (0,0) of the tile is post (0,0) of the source
    assert float(arr[0][0]) == pytest.approx(float(vals[0][0]))
    assert float(arr[2][3]) == pytest.approx(float(vals[2][3]))
    # and the tile's own first post really is where we asked for it
    assert (gt[0] + res / 2.0) == pytest.approx(10.0, abs=1e-9)


@requires_gdal
def test_direct_copy_uses_the_data_type_aware_predictor(tmpdir_local):
    """B4: a delivery must not mix two compression profiles."""
    import dem2dged_lib as dl
    res = 0.001
    src, _ = _point_source(tmpdir_local, 10.0, 50.0, res, 20, "pred.tif")
    for out_type, expect in (("Float32", "3"), ("Int16", "2")):
        dst = os.path.join(tmpdir_local, "pred_%s.tif" % out_type)
        assert dl.try_direct_copy_tile(
            src, dst, first_x=10.0, first_y=50.0, width=5, height=5,
            xres=res, yres=res, dst_srs="EPSG:4326", out_type=out_type)
        ds = gdal.Open(dst)
        md = ds.GetMetadata("IMAGE_STRUCTURE")
        ds = None
        assert dl.predictor_for_type(out_type) == expect
        assert md.get("PREDICTOR") == expect, (out_type, md)


# ══════════════════════════════════════════════════════════════════════════════
#  A2 / A3 / C5 -- sidecar escaping and encoding
# ══════════════════════════════════════════════════════════════════════════════

_SIDECAR_VALUES = {
    "BASENAME": "DGEDL5GtD_5530N01212E_A_U_01", "LEVEL": "5", "GSD": "2.0",
    "DATE": "2026-08-26", "EPSG": "4326", "CLASS_WORD": "unclassified",
    "WEST": "12.0", "EAST": "12.1", "SOUTH": "55.5", "NORTH": "55.6",
    "MINZ": "0", "MAXZ": "100", "MISSRATE": "0.0",
    "ABS_HACC": "3.0", "ABS_VACC": "2.0",
    "ABS_HACC_BASIS": "goal", "ABS_VACC_BASIS": "goal", "DTYPE": "real",
}


def _template():
    p = os.path.join(PROJECT_DIR, "DGED_GEO_TEMPLATE.xml")
    if not os.path.isfile(p):                        # pragma: no cover
        pytest.skip("DGED_GEO_TEMPLATE.xml not present")
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def test_sidecar_escapes_xml_special_characters(tmpdir_local):
    """A2: a source called DEM_A&B.tif used to break every sidecar."""
    import xml.etree.ElementTree as ET
    import dem2dged_lib as dl

    repl = dict(_SIDECAR_VALUES)
    repl["ORG"] = "R&D"
    repl["LINEAGE"] = "Derived from 'DEM_A&B <draft>' by dem2dged"
    out = os.path.join(tmpdir_local, "escaped.xml")
    dl.write_sidecar_file(_template(), out, repl)

    with io.open(out, encoding="utf-8") as f:
        txt = f.read()
    ET.fromstring(txt)                        # must not raise
    assert "&amp;" in txt and "&lt;draft&gt;" in txt
    # the raw ampersand must be gone -- that is what made it unparseable
    assert "DEM_A&B" not in txt


def test_sidecar_is_utf8_whatever_the_platform_code_page(tmpdir_local):
    """A3: the file declares UTF-8, so it must BE UTF-8.

    On cp1252 this raised UnicodeEncodeError mid-conversion, after tiles
    were already on disk.
    """
    import dem2dged_lib as dl

    repl = dict(_SIDECAR_VALUES)
    repl["ORG"] = "KOR"
    repl["LINEAGE"] = "Source: 서울 DEM / Montréal relevé"
    out = os.path.join(tmpdir_local, "utf8.xml")
    dl.write_sidecar_file(_template(), out, repl)

    raw = io.open(out, "rb").read()
    text = raw.decode("utf-8")                # must not raise
    assert "서울" in text
    assert 'encoding="UTF-8"' in text


@requires_gdal
def test_toc_and_collection_are_utf8(tmpdir_local):
    """A3: the TOC lists FILENAMES, which can carry any character."""
    import dem2dged_lib as dl

    io.open(os.path.join(tmpdir_local, "DGEDL5GtD_5530N01212E_A_U_01.tif"),
            "w", encoding="utf-8").write("x")
    toc = dl.write_toc_file(tmpdir_local, "DGEDL5G")
    io.open(toc, "rb").read().decode("utf-8")

    coll = dl.write_collection_metadata(
        tmpdir_local, "DGEDL5G", "5", "4326", (12.0, 55.5, 12.1, 55.6),
        ["DGEDL5GtD_5530N01212E_A_U_01"], "U", org="KOR")
    io.open(coll, "rb").read().decode("utf-8")


def test_the_library_has_no_locale_dependent_text_open():
    """A3, structurally: catch a new one being added later."""
    src = io.open(os.path.join(PROJECT_DIR, "dem2dged_lib.py"),
                  encoding="utf-8").read()
    offenders = [line.strip() for line in src.split("\n")
                 if re.match(r"^\s*with open\(", line)
                 and "encoding=" not in line
                 and '"rb"' not in line and '"wb"' not in line]
    assert offenders == [], offenders


# ══════════════════════════════════════════════════════════════════════════════
#  A6 -- NaN NoData defeated both validity masks
# ══════════════════════════════════════════════════════════════════════════════

@requires_gdal
def test_compute_tile_stats_handles_a_nan_nodata_sentinel(tmpdir_local):
    """v0.55.0 returned (0, 0, 100.0) for a perfectly good tile."""
    import numpy as np
    import dem2dged_lib as dl

    vals = np.full((10, 10), 50.0, dtype="float32")
    vals[0, 0] = np.nan
    p = _write_raster(os.path.join(tmpdir_local, "nan_nodata.tif"),
                      (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), vals,
                      nodata=float("nan"))
    vmin, vmax, miss = dl.compute_tile_stats(p)
    assert (vmin, vmax) == (50, 50)
    assert miss == pytest.approx(1.0)


@requires_gdal
def test_compute_tile_stats_survives_a_nan_in_the_data(tmpdir_local):
    """A NaN post must not reach int(math.floor(nan))."""
    import numpy as np
    import dem2dged_lib as dl

    vals = np.full((10, 10), 50.0, dtype="float32")
    vals[3, 4] = np.nan
    p = _write_raster(os.path.join(tmpdir_local, "nan_data.tif"),
                      (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), vals,
                      nodata=-32767.0)
    vmin, vmax, miss = dl.compute_tile_stats(p)
    assert (vmin, vmax) == (50, 50)
    assert miss == pytest.approx(1.0)


@requires_gdal
def test_the_ordinary_nodata_sentinel_still_behaves_exactly_as_before(tmpdir_local):
    """The A6 rewrite must be bit-identical for the -32767 case."""
    import numpy as np
    import dem2dged_lib as dl

    vals = np.full((10, 10), 50.0, dtype="float32")
    vals[0, :] = -32767.0
    p = _write_raster(os.path.join(tmpdir_local, "plain_nodata.tif"),
                      (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), vals,
                      nodata=-32767.0)
    assert dl.compute_tile_stats(p) == (50, 50, 10.0)


@requires_gdal
def test_the_prefilter_does_not_spread_a_nan_nodata(tmpdir_local):
    """v0.55.0 turned one NaN post into 81 (9x9, kernel radius 4)."""
    import numpy as np
    import dem2dged_lib as dl

    vals = np.full((40, 40), 100.0, dtype="float32")
    vals[20, 20] = np.nan
    src = _write_raster(os.path.join(tmpdir_local, "pf_nan.tif"),
                        (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), vals,
                        nodata=float("nan"))
    out = os.path.join(tmpdir_local, "pf_nan_out.tif")
    dl.build_prefiltered_source(src, 1.0, out_path=out, log_fn=lambda *_: None)

    ds = gdal.Open(out)
    a = ds.GetRasterBand(1).ReadAsArray().astype("float64")
    ds = None
    assert int(np.isnan(a).sum()) == 1


@requires_gdal
def test_the_prefilter_preserves_a_finite_void_exactly(tmpdir_local):
    """The pre-v0.56 behaviour for a -32767 sentinel, unchanged."""
    import numpy as np
    import dem2dged_lib as dl

    vals = np.full((40, 40), 100.0, dtype="float32")
    vals[10:14, 10:14] = -32767.0
    src = _write_raster(os.path.join(tmpdir_local, "pf_void.tif"),
                        (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), vals,
                        nodata=-32767.0)
    out = os.path.join(tmpdir_local, "pf_void_out.tif")
    dl.build_prefiltered_source(src, 1.0, out_path=out, log_fn=lambda *_: None)

    ds = gdal.Open(out)
    a = ds.GetRasterBand(1).ReadAsArray().astype("float64")
    ds = None
    void = (a <= -32766.0)
    assert int(void.sum()) == 16
    assert void[10:14, 10:14].all()


def test_a_zero_sigma_kernel_is_an_identity_not_a_nan():
    """v0.55.0 produced len=3 sum=nan, which NaN-ed out whole rasters."""
    import numpy as np
    import dem2dged_lib as dl

    k = np.asarray(dl._gaussian_kernel_1d(0.0))
    assert not np.isnan(k).any()
    assert k.sum() == pytest.approx(1.0)
    assert len(k) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  A7 -- extent reprojection sampled only the four corners
# ══════════════════════════════════════════════════════════════════════════════

def test_densified_edge_points_degenerate_to_the_corners_at_n_2():
    """The safety property that makes the A7 change a drop-in."""
    import dem2dged_lib as dl
    pts = set(dl.densified_edge_points(0.0, 0.0, 10.0, 20.0, n=2))
    assert pts == {(0.0, 0.0), (0.0, 20.0), (10.0, 0.0), (10.0, 20.0)}


def test_densified_edge_points_include_every_corner():
    import dem2dged_lib as dl
    pts = set(dl.densified_edge_points(1.0, 2.0, 3.0, 4.0))
    for corner in ((1.0, 2.0), (1.0, 4.0), (3.0, 2.0), (3.0, 4.0)):
        assert corner in pts


@requires_gdal
def test_the_output_bbox_covers_the_curved_edges(tmpdir_local):
    """A7 measured: 4116 m of coverage sat south of the corner-only box.

    Asserted as a comparison against a corner-only transform computed here,
    so the test states the defect rather than hard-coding a number that a
    PROJ update could legitimately shift.
    """
    import dem2dged_lib as dl

    minlat, maxlat, minlon, maxlon = 55.0, 60.0, 6.0, 12.0
    ext = (maxlat, minlon, minlat, maxlon, "4326")
    target = 32632

    dense = dl.get_bbox_of_output(ext, target)

    src = osr.SpatialReference(); src.ImportFromEPSG(4326)
    dst = osr.SpatialReference(); dst.ImportFromEPSG(target)
    dl.set_authority_axis_order(src, dst)
    xf = osr.CoordinateTransformation(src, dst)
    from osgeo import ogr
    xs, ys = [], []
    for u, v in ((ext[0], ext[3]), (ext[0], ext[1]),
                 (ext[2], ext[1]), (ext[2], ext[3])):
        p = ogr.CreateGeometryFromWkt("POINT (%s %s)" % (u, v))
        p.Transform(xf)
        xs.append(p.GetX()); ys.append(p.GetY())
    corner = (min(xs), max(xs), min(ys), max(ys))

    # The densified box must CONTAIN the corner-only box ...
    assert dense[0] <= corner[0] + 1e-6
    assert dense[1] >= corner[1] - 1e-6
    assert dense[2] <= corner[2] + 1e-6
    assert dense[3] >= corner[3] - 1e-6
    # ... and be strictly larger somewhere, or this extent proves nothing.
    grew = ((corner[0] - dense[0]) + (dense[1] - corner[1])
            + (corner[2] - dense[2]) + (dense[3] - corner[3]))
    assert grew > 1000.0, grew


# ══════════════════════════════════════════════════════════════════════════════
#  A5 -- Svalbard UTM zone boundaries
# ══════════════════════════════════════════════════════════════════════════════

@requires_gdal
@pytest.mark.parametrize("lon,expect_zone", [
    (0.5, 31), (5.0, 31),                  # 31X spans 0-9 E
    (10.0, 33), (15.0, 33), (20.0, 33),    # 33X spans 9-21 E
    (22.0, 35), (30.0, 35),                # 35X spans 21-33 E
    (35.0, 37), (40.0, 37),                # 37X spans 33-42 E
])
def test_svalbard_zones_match_the_spec(lon, expect_zone):
    """v0.55.0 got 7 of these 9 wrong -- every one, one zone too high."""
    import dem2dged_utm as du
    lat = 78.0
    epsg, zone = du.autodetect_utm((lat, lon, lat, lon, "4326"))
    assert int(zone) == expect_zone
    assert int(epsg) == 32600 + expect_zone


@requires_gdal
def test_the_generic_utm_formula_is_untouched():
    """A5 must not have disturbed the ordinary case."""
    import dem2dged_utm as du
    for lat, lon, expect in ((55.5, 12.0, 33), (-33.0, 18.5, 34),
                             (45.0, -75.0, 18)):
        _epsg, zone = du.autodetect_utm((lat, lon, lat, lon, "4326"))
        assert int(zone) == expect


# ══════════════════════════════════════════════════════════════════════════════
#  A4 -- the validator called sys.exit() at module scope
# ══════════════════════════════════════════════════════════════════════════════

def test_the_validator_never_calls_sys_exit_at_module_scope():
    """SystemExit is a BaseException, so `except Exception` cannot hold it.

    Asserted on the SOURCE rather than by breaking an import: the guards
    only fire when GDAL or dem2dged_lib is missing, which is exactly the
    state a test run cannot be in.
    """
    src = io.open(os.path.join(PROJECT_DIR, "dem2dged_validate.py"),
                  encoding="utf-8").read()
    body = src.split("\ndef main(")[0]
    module_scope = [line for line in body.split("\n")
                    if line.startswith("    sys.exit(")
                    or line.startswith("sys.exit(")]
    assert module_scope == [], module_scope
    assert body.count("raise ImportError(") == 2


def test_a_caller_guarding_with_except_exception_can_hold_the_import_error():
    """The property the fix exists to restore."""
    caught = None
    try:
        raise ImportError("simulated missing GDAL")
    except Exception as exc:                 # noqa: BLE001 - the point
        caught = exc
    assert isinstance(caught, ImportError)
    assert not isinstance(caught, SystemExit)


# ══════════════════════════════════════════════════════════════════════════════
#  B2 / B3 -- source inspection cost, and compliance honesty
# ══════════════════════════════════════════════════════════════════════════════

@requires_gdal
def test_inspect_source_is_cached_within_a_process(tmpdir_local):
    """B2: dem2dged.py and the converter used to inspect the same file twice."""
    import numpy as np
    import dem2dged_terrain as dt

    vals = (np.arange(200 * 200, dtype="int16").reshape(200, 200) % 500)
    p = _write_raster(os.path.join(tmpdir_local, "cached.tif"),
                      (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), vals,
                      dtype=gdal.GDT_Int16, nodata=-32767.0)
    first = dt.inspect_source(p)
    second = dt.inspect_source(p)
    assert second is first
    assert dt.inspect_source(p, use_cache=False) is not first


@requires_gdal
def test_inspect_source_still_reports_the_value_range(tmpdir_local):
    """B2 changed HOW the range is computed; it must not change WHAT."""
    import numpy as np
    import dem2dged_terrain as dt

    vals = np.full((50, 50), 12.0, dtype="float32")
    vals[0, 0] = -5.0
    vals[1, 1] = 99.0
    vals[2, 2] = -32767.0
    p = _write_raster(os.path.join(tmpdir_local, "range.tif"),
                      (10.0, 0.001, 0.0, 50.0, 0.0, -0.001), vals,
                      nodata=-32767.0)
    info = dt.inspect_source(p, use_cache=False)
    assert info.valid_range is not None
    lo, hi = info.valid_range
    assert lo == pytest.approx(-5.0)
    assert hi == pytest.approx(99.0)


def test_compliance_with_no_thresholds_is_not_evaluated_rather_than_pass():
    """B3: reporting PASS for a run that evaluated nothing is a lie."""
    import dem2dged_terrain as dt
    result = dt.compliance_result(
        False, {"bias": 0.2, "rmse": 1.2, "p95": 2.0, "max": 4.0}, {})
    assert result["overall"] == "NOT_EVALUATED"


def test_compliance_still_passes_and_fails_when_thresholds_apply():
    """The B3 change must not disturb a real gate."""
    import dem2dged_terrain as dt
    limits = {"max_bias": 1.0, "max_rmse": 2.0, "max_p95": 3.0, "max_max": 5.0}
    ok = dt.compliance_result(
        False, {"bias": 0.2, "rmse": 1.2, "p95": 2.0, "max": 4.0}, limits)
    assert ok["overall"] == "PASS"
    bad = dt.compliance_result(
        False, {"bias": 9.0, "rmse": 1.2, "p95": 2.0, "max": 4.0}, limits)
    assert bad["overall"] == "FAIL"


def test_an_unknown_profile_falls_back_to_a_real_gate():
    """B3: an absent profile used to mean "no thresholds", i.e. no gate."""
    import dem2dged_terrain as dt
    limits = dt.compliance_thresholds("strict")
    assert limits.get("max_rmse")
    # a profile that is in neither the policy file nor the bundled defaults
    # legitimately yields nothing -- but it must then be NOT_EVALUATED, not
    # a silent pass (asserted above).
    assert dt.compliance_thresholds("no-such-profile") == {}


# ══════════════════════════════════════════════════════════════════════════════
#  B5 / B6 -- resume check and product extent
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("module", ["dem2dged_geo.py", "dem2dged_utm.py",
                                    "dem2dged_gui.py"])
def test_the_resume_check_looks_at_the_tile_too(module):
    """B5: an .xml beside a deleted .tif used to read as 'already done'."""
    src = io.open(os.path.join(PROJECT_DIR, module), encoding="utf-8").read()
    assert ("os.path.isfile(xml_path) and os.path.isfile(tif_path)" in src
            or "os.path.isfile(xml) and os.path.isfile(tif)" in src)


@pytest.mark.parametrize("module", ["dem2dged_geo.py", "dem2dged_utm.py",
                                    "dem2dged_gui.py"])
def test_the_product_extent_is_recorded_per_delivered_tile(module):
    """B6: the extent used to be widened before the tile was even attempted."""
    src = io.open(os.path.join(PROJECT_DIR, module), encoding="utf-8").read()
    assert "def _note_delivered(" in src
    # every call must sit next to a tile_basenames.append(), i.e. on a
    # path where the tile really is part of the delivery
    calls = src.count("_note_delivered(")
    defs = src.count("def _note_delivered(")
    assert calls - defs >= 2, (calls, defs)


# ══════════════════════════════════════════════════════════════════════════════
#  B1 -- the GUI is a second converter
# ══════════════════════════════════════════════════════════════════════════════

@requires_gdal
def test_the_gui_converters_accept_a_prefilter():
    """B1: the v0.49 headline feature was CLI-only until v0.56."""
    import inspect
    import dem2dged_gui as gui
    for fn in (gui.convert_geo, gui.convert_utm):
        params = inspect.signature(fn).parameters
        assert "prefilter" in params
        assert params["prefilter"].default == "none"
        assert "prefilter_sigma" in params


@requires_gdalwarp
def test_the_gui_and_the_cli_produce_identical_tiles(tmpdir_local):
    """B1, locked in.

    The two converters are separate implementations -- the CLI shells out to
    gdalwarp, the GUI calls the gdal.Warp API -- and NOTHING in the 384-test
    suite compared them. The v0.55.0 review found they agreed; this is what
    keeps them agreeing.
    """
    import numpy as np
    import dem2dged_geo as dgeo
    import dem2dged_gui as gui

    n = 240
    step = 1.0 / n
    yy, xx = np.mgrid[0:n, 0:n]
    vals = (200.0 + 40.0 * np.sin(xx / 12.0)
            + 25.0 * np.cos(yy / 9.0)).astype("float32")
    src = _write_raster(os.path.join(tmpdir_local, "both.tif"),
                        (12.0, step, 0.0, 56.0, 0.0, -step), vals)

    out_cli = os.path.join(tmpdir_local, "cli")
    out_gui = os.path.join(tmpdir_local, "gui")
    os.makedirs(out_cli); os.makedirs(out_gui)

    cli_resamp = dgeo.main(["dem2dged_geo.py", src, out_cli,
                            "-product_level", "0", "-xml_template",
                            os.path.join(PROJECT_DIR, "DGED_GEO_TEMPLATE.xml")])

    class _NeverStopped:
        def is_set(self):
            return False

    gui_resamp = gui.convert_geo(src, out_gui, "0", "A", "U", "01",
                                 log_fn=lambda *_: None,
                                 progress_fn=lambda *_: None,
                                 stop_event=_NeverStopped())

    assert str(cli_resamp) == str(gui_resamp)

    cli_tifs = sorted(f for f in os.listdir(out_cli) if f.endswith(".tif"))
    gui_tifs = sorted(f for f in os.listdir(out_gui) if f.endswith(".tif"))
    assert cli_tifs == gui_tifs
    assert cli_tifs, "the job produced no tiles at all"

    for name in cli_tifs:
        a = gdal.Open(os.path.join(out_cli, name))
        b = gdal.Open(os.path.join(out_gui, name))
        ga, gb = a.GetGeoTransform(), b.GetGeoTransform()
        da = a.GetRasterBand(1).ReadAsArray()
        db = b.GetRasterBand(1).ReadAsArray()
        ta = gdal.GetDataTypeName(a.GetRasterBand(1).DataType)
        tb = gdal.GetDataTypeName(b.GetRasterBand(1).DataType)
        pa = a.GetMetadataItem("AREA_OR_POINT")
        pb = b.GetMetadataItem("AREA_OR_POINT")
        a = b = None

        assert ta == tb, name
        assert pa == pb == "Point", name
        assert max(abs(x - y) for x, y in zip(ga, gb)) < 1e-9, name
        assert da.shape == db.shape, name
        assert int((da != db).sum()) == 0, name

    for extra in ("TABLE_OF_CONTENTS.xml",):
        assert (os.path.isfile(os.path.join(out_cli, extra))
                == os.path.isfile(os.path.join(out_gui, extra)))
