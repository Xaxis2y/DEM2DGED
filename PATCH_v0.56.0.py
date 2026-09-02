# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# PATCH_v0.56.0.py
# Patch Script Version: 0.01
# Applies the v0.55.0 review fixes and produces v0.56.0.
#
# ============================================================================
# CONTRACT
# ============================================================================
# Every edit below is an EXACT string replacement that must match exactly once.
# If any edit for a file fails to match, NOTHING in that file is written --
# so a partially-applied patch is not a state this script can produce. Re-runs
# are safe: an already-applied edit is detected by the presence of its full
# replacement text and reported as SKIP rather than failing. Testing "is
# `old` gone?" instead would be wrong -- most edits here are insertions whose
# `new` ends with `old` verbatim, so `old` survives and the edit would be
# applied a second time, duplicating the inserted block.
#
# A backup of the pre-patch tree is expected in _backup_v0.55.0/.
#
# ============================================================================
# HOW TO RUN  (Anaconda Prompt -- dedicated environment, never base)
# ============================================================================
#     (base) C:\> conda activate DGED
#     (DGED) C:\> cd C:\Users\Son\Documents\ChatGPT\dem2dged\dem2dged_v0.55.0
#     (DGED) C:\...> python PATCH_v0.56.0.py            (dry run, shows plan)
#     (DGED) C:\...> python PATCH_v0.56.0.py --apply    (writes the files)
# ============================================================================

from __future__ import annotations

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OLD_VERSION = "0.55.0"
NEW_VERSION = "0.56.0"

# (file, finding, description, old_text, new_text)
PATCHES = []


def P(fname, finding, desc, old, new):
    PATCHES.append((fname, finding, desc, old, new))


# ═══════════════════════════════════════════════════════════════════════════
#  dem2dged_lib.py
# ═══════════════════════════════════════════════════════════════════════════

# ---- shared NoData/validity predicate (A6) ---------------------------------
P("dem2dged_lib.py", "A6",
  "add the shared valid_data_mask() predicate",
  '''def gdal_open(path: str, mode: int = gdal.GA_ReadOnly):''',
  '''def valid_data_mask(arr, nodata):
    """Boolean mask of posts that carry a real elevation (v0.56).

    ONE predicate, used by compute_tile_stats(), clamp_tile_to_range() and
    build_prefiltered_source(), because before v0.56 each of those wrote its
    own and two of the three were wrong for a NaN NoData value -- which is
    routine in Float32 DEMs:

      compute_tile_stats()      abs(arr - nodata) > 0.5
          With nodata = NaN every comparison is False, so a perfectly good
          tile reported (0, 0, 100.0): MINZ 0, MAXZ 0 and MISSRATE 100%,
          written straight into the delivered sidecar. MEASURED, not
          assumed -- the v0.55.0 review harness reproduced exactly that.

      build_prefiltered_source()   arr != float(nodata)
          The mirror-image error: NaN != NaN is True, so every pixel counted
          as valid, the NaN entered the separable convolution, and it spread
          across the whole kernel footprint. One NaN post in a 40x40 source
          became 81 NaN posts (9x9, radius 4) in the filtered raster.

    The rules, in order:
      * a non-finite sample (NaN or +/-Inf) is never valid, whatever the
        declared NoData -- this is what makes a NaN sentinel work at all,
        and it also stops a stray NaN in otherwise good data from
        propagating into MINZ/MAXZ;
      * a finite NoData sentinel is matched with the same 0.5 tolerance the
        pre-v0.56 code used, so behaviour for the ordinary -32767 case is
        unchanged, bit for bit;
      * a non-finite NoData sentinel needs no comparison at all -- the
        finiteness test above has already excluded exactly those pixels.

    Integer arrays cannot hold NaN, so the finiteness test is skipped for
    them rather than paying for a float64 cast that would change nothing.
    """
    import numpy as np

    a = np.asarray(arr)
    if a.dtype.kind in "fc":
        valid = np.isfinite(a)
    else:
        valid = np.ones(a.shape, dtype=bool)
    if nodata is not None:
        nd = float(nodata)
        if math.isfinite(nd):
            valid = valid & (np.abs(a.astype("float64") - nd) > 0.5)
    return valid


def gdal_open(path: str, mode: int = gdal.GA_ReadOnly):''')

# ---- densified edge sampling (A7) ------------------------------------------
P("dem2dged_lib.py", "A7",
  "add the densified edge sampler used by both bbox transforms",
  '''def set_traditional_axis_order(*srs_list) -> None:''',
  '''# -- Extent reprojection: sample the EDGES, not just the corners (v0.56) -----
#
# Both bbox transforms below used to transform four corner points and take
# the min/max. The image of a lat/lon rectangle in UTM -- or of a UTM
# rectangle in WGS-84 -- is CURVED, so the true extent lies partly outside
# the corner hull. GDAL's own SuggestedWarpOutput densifies each edge with 21
# points for exactly this reason.
#
# MEASURED, NOT ASSUMED (v0.56 review, GDAL 3.13.3): a 6 x 5 degree extent at
# 55-60N reprojected to UTM 32N put 4116.4 m of real source coverage SOUTH of
# the corner-only box -- 0.82 of a level-6 tile. In get_bbox_of_output() that
# shortfall decides the tile grid, so those tiles were never generated and
# nothing downstream reported a gap; in bbox_to_wgs84() it understated the
# bounding box written into every sidecar and the collection metadata.
#
# 21 points per edge matches GDAL. The cost is 84 point transforms instead of
# 4, once per conversion -- unmeasurable next to a single tile warp.
DENSIFY_POINTS_PER_EDGE = 21


def densified_edge_points(min_u: float, min_v: float, max_u: float,
                          max_v: float,
                          n: int = DENSIFY_POINTS_PER_EDGE) -> List[Tuple[float, float]]:
    """Sample points along all four edges of a rectangle, corners included.

    Returns (u, v) pairs -- the caller decides what u and v mean, because the
    two callers use opposite axis conventions (see the axis-order note
    below). n is the number of samples per edge; n = 2 degenerates to the
    pre-v0.56 corners-only behaviour, which is what makes this a safe
    drop-in.
    """
    n = max(2, int(n))
    pts = []
    for i in range(n):
        t = i / float(n - 1)
        u = min_u + t * (max_u - min_u)
        v = min_v + t * (max_v - min_v)
        pts.append((u, min_v))
        pts.append((u, max_v))
        pts.append((min_u, v))
        pts.append((max_u, v))
    return pts


def set_traditional_axis_order(*srs_list) -> None:''')

# ---- zero-sigma kernel guard ----------------------------------------------
P("dem2dged_lib.py", "sigma0",
  "make _gaussian_kernel_1d() a no-op at sigma <= 0 instead of returning NaN",
  '''    radius = int(max(1, math.ceil(truncate * float(sigma))))
    x = np.arange(-radius, radius + 1, dtype="float64")
    k = np.exp(-(x * x) / (2.0 * float(sigma) * float(sigma)))
    return k / k.sum()''',
  '''    # v0.56: sigma = 0 is a legitimate value -- gaussian_sigma_for_ratio()
    # returns it whenever the target grid is not coarser than the source, and
    # "-prefilter_sigma 0" is the documented way to disable the filter by
    # hand. Dividing by 2*sigma*sigma then made every tap NaN and k.sum() NaN,
    # so the "kernel" silently NaN-ed out the entire raster it was convolved
    # with (MEASURED: len=3 sum=nan has_nan=True). Both converters happen to
    # check "sigma_px > 0" before calling, so this was unreachable from the
    # CLI -- but build_prefiltered_source() is a public function and nothing
    # protected a direct caller. A one-tap identity kernel is the correct
    # no-op: convolving with it returns the input unchanged.
    if not (float(sigma) > 0.0):
        return np.array([1.0], dtype="float64")

    radius = int(max(1, math.ceil(truncate * float(sigma))))
    x = np.arange(-radius, radius + 1, dtype="float64")
    k = np.exp(-(x * x) / (2.0 * float(sigma) * float(sigma)))
    return k / k.sum()''')

# ---- prefilter validity mask (A6) ------------------------------------------
P("dem2dged_lib.py", "A6",
  "build_prefiltered_source(): use the shared validity predicate",
  '''        if nodata is None:
            valid = np.ones(arr.shape, dtype="float64")
        else:
            valid = (arr != float(nodata)).astype("float64")
        data0 = arr * valid''',
  '''        # v0.56: was "arr != float(nodata)", which is True for EVERY pixel
        # when nodata is NaN (NaN != NaN), so the normalised-convolution
        # guard never engaged and a single NaN post spread across the full
        # kernel footprint. valid_data_mask() also excludes a stray NaN in
        # otherwise-good data, which is what we want here: an unrepresentable
        # sample must not contaminate its neighbours.
        valid_bool = valid_data_mask(arr, nodata)
        valid = valid_bool.astype("float64")
        data0 = np.where(valid_bool, arr, 0.0)''')

P("dem2dged_lib.py", "A6",
  "build_prefiltered_source(): restore voids from the same predicate",
  '''        # Restore the void footprint exactly: a pixel that was NoData in
        # the source stays NoData, whatever its valid neighbours smoothed to.
        if nodata is not None:
            out = np.where(valid > 0.5, out, float(nodata))''',
  '''        # Restore the void footprint exactly: a pixel that was NoData in
        # the source stays NoData, whatever its valid neighbours smoothed to.
        # v0.56: keyed off the same mask that drove the convolution, so a
        # NaN-sentinel source gets its voids back too (they used to be
        # smoothed over, because the mask said they were valid).
        if nodata is not None:
            out = np.where(valid_bool, out, float(nodata))''')

# ---- sidecar template read / write (A2, A3, C5) ----------------------------
P("dem2dged_lib.py", "A2 A3 C5",
  "read_sidecar_template()/write_sidecar_file(): UTF-8 and XML escaping",
  '''def read_sidecar_template(template_fnam: str) -> str:
    """Read an XML template file for metadata sidecar creation."""
    with open(template_fnam) as f:
        return f.read()


def write_sidecar_file(template: str, fnam: str, replacements: Dict[str, str]) -> None:
    """Write an XML sidecar file with all {{PLACEHOLDER}} keys replaced.

    replacements maps placeholder names (without braces) to values, e.g.
    {"BASENAME": "DGEDL5GtD_...", "LEVEL": "5", ...}.
    """
    xfile = template
    for key, value in replacements.items():
        xfile = xfile.replace("{{%s}}" % key, str(value))
    with open(fnam, "wt") as f:
        f.write(xfile)''',
  '''def read_sidecar_template(template_fnam: str) -> str:
    """Read an XML template file for metadata sidecar creation.

    v0.56: encoding="utf-8" is now explicit. It used to be absent, so Python
    used the platform's ANSI code page -- cp1252 on an ordinary Windows
    install, cp949/cp932 on a Korean or Japanese one. dem2dged_gui.py's own
    _load_template() has always passed encoding='utf-8', so the GUI and the
    CLI read the SAME template two different ways.
    """
    with open(template_fnam, encoding="utf-8") as f:
        return f.read()


def write_sidecar_file(template: str, fnam: str, replacements: Dict[str, str]) -> None:
    """Write an XML sidecar file with all {{PLACEHOLDER}} keys replaced.

    replacements maps placeholder names (without braces) to values, e.g.
    {"BASENAME": "DGEDL5GtD_...", "LEVEL": "5", ...}.

    v0.56 -- TWO DEFECTS FIXED HERE, BOTH REPRODUCED ON REAL HARDWARE.

    (1) NO XML ESCAPING. Values went in through a bare str.replace(), so any
        value carrying &, < or > produced a sidecar that is not well-formed
        XML. _xml_escape() already existed in this module and was already
        used by write_toc_file() and write_collection_metadata() -- the
        sidecar was the one writer that skipped it. That mattered because
        LINEAGE and ORG are free operator text AND the DEFAULT lineage
        embeds os.path.basename(input_raster): a source file named
        "DEM_A&B.tif" was enough, with no unusual flags at all, to break
        every sidecar in the delivery. MEASURED: ParseError "not well-formed
        (invalid token): line 40, column 52".

        Escaping HERE rather than at each call site also removes an
        order-dependence: values were substituted in dict order, so a value
        that happened to contain the literal text "{{SOMEKEY}}" would be
        re-substituted by a later iteration. Escaped text cannot contain a
        live placeholder.

    (2) NO ENCODING. open(fnam, "wt") used the platform code page while the
        file it writes declares encoding="UTF-8", and dem2dged_validate.py
        reads it back with encoding="utf-8". MEASURED on cp1252:
        UnicodeEncodeError at position 18406 -- the conversion ABORTED
        mid-run, after tiles were already warped, rather than merely writing
        mis-declared bytes.
    """
    xfile = template
    for key, value in replacements.items():
        xfile = xfile.replace("{{%s}}" % key, _xml_escape(value))
    with open(fnam, "wt", encoding="utf-8") as f:
        f.write(xfile)''')

# ---- compute_tile_stats validity (A6) --------------------------------------
P("dem2dged_lib.py", "A6",
  "compute_tile_stats(): use the shared validity predicate",
  '''        if nodata is not None:
            valid_mask = abs(arr - nodata) > 0.5
        else:
            valid_mask = arr == arr   # all True
        n_missing += int((~valid_mask).sum())''',
  '''        # v0.56: was "abs(arr - nodata) > 0.5", which is False for every
        # pixel when nodata is NaN -- a perfectly good tile then reported
        # (0, 0, 100.0) and those numbers went into the delivered sidecar.
        valid_mask = valid_data_mask(arr, nodata)
        n_missing += int((~valid_mask).sum())''')

P("dem2dged_lib.py", "A6",
  "compute_tile_stats(): guard the integer conversion against a non-finite result",
  '''    if vmin is None:
        return 0, 0, 100.0
    miss_pct = round(100.0 * n_missing / max(1, n_total), 4)
    return int(math.floor(vmin)), int(math.ceil(vmax)), miss_pct''',
  '''    if vmin is None:
        return 0, 0, 100.0
    miss_pct = round(100.0 * n_missing / max(1, n_total), 4)
    # v0.56: valid_data_mask() already excludes non-finite samples, so vmin
    # and vmax are finite by construction. This guard is belt and braces --
    # int(math.floor(nan)) raises ValueError, and sidecar_replacements()
    # calls this once per tile, so a single bad post would abort the whole
    # sidecar pass AFTER every tile had been warped. Failing to a "no valid
    # data" answer is strictly better than failing the delivery.
    if not (math.isfinite(vmin) and math.isfinite(vmax)):
        return 0, 0, 100.0
    return int(math.floor(vmin)), int(math.ceil(vmax)), miss_pct''')

# ---- clamp_tile_to_range validity (A6, consistency) ------------------------
P("dem2dged_lib.py", "A6",
  "clamp_tile_to_range(): use the shared validity predicate",
  '''        if nodata is not None:
            is_nodata = abs(arr.astype("float64") - nodata) <= 0.5
            too_low  = too_low  & ~is_nodata
            too_high = too_high & ~is_nodata''',
  '''        # v0.56: the same shared predicate the other two readers use, so
        # "which posts are real data" can no longer mean three things in one
        # module. Behaviour for a finite -32767 sentinel is unchanged.
        is_valid = valid_data_mask(arr, nodata)
        too_low  = too_low  & is_valid
        too_high = too_high & is_valid''')

# ---- write_toc_file encoding (A3) ------------------------------------------
P("dem2dged_lib.py", "A3",
  "write_toc_file(): UTF-8",
  '''    toc_path = os.path.join(folder, TOC_FILENAME)
    with open(toc_path, "wt") as f:''',
  '''    toc_path = os.path.join(folder, TOC_FILENAME)
    # v0.56: explicit UTF-8. The file declares encoding="UTF-8" on its first
    # line and lists tile FILENAMES, which on an operator's machine can carry
    # any character the filesystem allows -- see write_sidecar_file().
    with open(toc_path, "wt", encoding="utf-8") as f:''')

# ---- write_collection_metadata encoding (A3) -------------------------------
P("dem2dged_lib.py", "A3",
  "write_collection_metadata(): UTF-8",
  '''    out_path = os.path.join(folder, "%s_COLLECTION.xml" % product_id)
    with open(out_path, "wt") as f:''',
  '''    out_path = os.path.join(folder, "%s_COLLECTION.xml" % product_id)
    # v0.56: explicit UTF-8 -- see write_sidecar_file(). The organisation
    # name interpolated above is free operator text.
    with open(out_path, "wt", encoding="utf-8") as f:''')

# ---- bbox_to_wgs84 densification (A7) --------------------------------------
P("dem2dged_lib.py", "A7",
  "bbox_to_wgs84(): densify the edges",
  '''    corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]
    pts = []
    for x, y in corners:
        p = ogr.CreateGeometryFromWkt("POINT (%s %s)" % (x, y))
        p.Transform(xf)
        pts.append((p.GetX(), p.GetY()))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)''',
  '''    # v0.56: EDGES, not just the four corners -- the transformed rectangle
    # is curved, so a corner-only hull understates the true extent. Here that
    # understated the bounding box written into every sidecar and into the
    # collection metadata. Traditional axis order is set above, so u = x =
    # easting/longitude and v = y = northing/latitude.
    samples = densified_edge_points(minx, miny, maxx, maxy)
    pts = []
    for x, y in samples:
        p = ogr.CreateGeometryFromWkt("POINT (%s %s)" % (x, y))
        p.Transform(xf)
        pts.append((p.GetX(), p.GetY()))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)''')

# ---- get_bbox_of_output densification (A7) ---------------------------------
P("dem2dged_lib.py", "A7",
  "get_bbox_of_output(): densify the edges",
  '''    corners = [
        ogr.CreateGeometryFromWkt("POINT (%s %s)" % (ext[0], ext[3])),
        ogr.CreateGeometryFromWkt("POINT (%s %s)" % (ext[0], ext[1])),
        ogr.CreateGeometryFromWkt("POINT (%s %s)" % (ext[2], ext[1])),
        ogr.CreateGeometryFromWkt("POINT (%s %s)" % (ext[2], ext[3])),
    ]
    pts = []
    for p in corners:
        p.Transform(transform)
        pts.append((p.GetX(), p.GetY()))
    # Use all four corners: with a rotated/oblique transformation the
    # extremes are not always at diagonally opposite corners.
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)''',
  '''    # v0.56: EDGES, not just the four corners. This return value decides the
    # TILE GRID, so a shortfall here is not a cosmetic metadata error -- any
    # tile reachable only from the missing strip is never generated, and
    # nothing downstream reports the gap. MEASURED on a 6 x 5 degree extent
    # at 55-60N into UTM 32N: 4116.4 m of real coverage south of the
    # corner-only box, 0.82 of a level-6 tile.
    #
    # ext is in AUTHORITY axis order (see this function's docstring), so for
    # a geographic source u = latitude and v = longitude. The rectangle is
    # [ext[2], ext[0]] x [ext[1], ext[3]]; min/max rather than assuming which
    # end is which, because the caller's ordering depends on the source.
    samples = densified_edge_points(
        min(ext[0], ext[2]), min(ext[1], ext[3]),
        max(ext[0], ext[2]), max(ext[1], ext[3]))
    pts = []
    for u, v in samples:
        p = ogr.CreateGeometryFromWkt("POINT (%s %s)" % (u, v))
        p.Transform(transform)
        pts.append((p.GetX(), p.GetY()))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)''')

# ---- try_direct_copy_tile indexing (A1) ------------------------------------
P("dem2dged_lib.py", "A1",
  "try_direct_copy_tile(): index the source by POST, not by pixel corner",
  '''    try:
        col = int(round((first_x - gt[0]) / gt[1]))
        row = int(round((first_y - gt[3]) / gt[5]))
    except Exception:
        return False
    if col < 0 or row < 0 or col + width > src.RasterXSize or row + height > src.RasterYSize:
        return False
    # Verify the first and last centers, not merely the resolution. This
    # catches a half-pixel phase error that would otherwise look aligned.
    if abs((gt[0] + col * gt[1]) - first_x) > 1e-7 or \\
       abs((gt[3] + row * gt[5]) - first_y) > 1e-7:
        return False''',
  '''    # v0.56 -- OFF BY HALF A PIXEL, IN BOTH DIRECTIONS AT ONCE.
    #
    # first_x / first_y are DGED POSTS, i.e. pixel CENTRES. GDAL normalises a
    # AREA_OR_POINT=Point GeoTIFF to the pixel-CORNER convention on read: the
    # GTiff driver subtracts half a pixel from the stored ModelTiepoint, so
    # gt[0] is the OUTER CORNER of the first pixel, not its centre. The
    # pre-v0.56 code compared a post against a corner.
    #
    # MEASURED (v0.55.0 review harness, GDAL 3.13.3) -- both outcomes were
    # defects, and both were observed:
    #
    #   * a correctly point-registered source, whose posts land exactly on
    #     the requested DGED posts, was REJECTED. The check missed by
    #     exactly 0.5 * xres every time, so the fast path could never fire
    #     for correct data -- a silently dead optimisation;
    #
    #   * a source whose pixel CORNERS happened to land on the post grid was
    #     ACCEPTED, and the tile was written with post (0,0) labelled
    #     X = 10.000000 while carrying the value of the source post at
    #     X = 10.000500. Half a post of pure coordinate error, in a
    #     delivered product, with no warning anywhere.
    #
    # The source post for column c sits at gt[0] + (c + 0.5) * gt[1].
    try:
        col = int(round((first_x - (gt[0] + gt[1] / 2.0)) / gt[1]))
        row = int(round((first_y - (gt[3] + gt[5] / 2.0)) / gt[5]))
    except Exception:
        return False
    if col < 0 or row < 0 or col + width > src.RasterXSize or row + height > src.RasterYSize:
        return False
    # Verify the actual post CENTRES, not merely the resolution. This is what
    # catches a half-pixel phase error that would otherwise look aligned --
    # and it is the check that was itself half a pixel out before v0.56.
    if abs((gt[0] + (col + 0.5) * gt[1]) - first_x) > 1e-7 or \\
       abs((gt[3] + (row + 0.5) * gt[5]) - first_y) > 1e-7:
        return False''')

# ---- try_direct_copy_tile creation options (B4) ----------------------------
P("dem2dged_lib.py", "B4",
  "try_direct_copy_tile(): data-type-aware LZW predictor, matching the warp path",
  '''    drv = gdal.GetDriverByName("GTiff")
    dst = drv.Create(dst_path, width, height, 1, dtype,
                     options=["COMPRESS=LZW", "TILED=YES"])
    if dst is None:
        return False''',
  '''    drv = gdal.GetDriverByName("GTiff")
    # v0.56: PREDICTOR was missing here, so a delivery containing both
    # direct-copied and warped tiles carried two different compression
    # profiles for the same product. predictor_for_type() is the same helper
    # both CLI converters and the GUI use (v0.39): 2 for Int16, 3 for
    # Float32. LZW stays lossless either way, so this is spec 13.1
    # compliant before and after -- only the sub-option changes.
    dst = drv.Create(dst_path, width, height, 1, dtype,
                     options=["COMPRESS=LZW",
                              "PREDICTOR=" + predictor_for_type(out_type),
                              "TILED=YES"])
    if dst is None:
        return False''')


# ═══════════════════════════════════════════════════════════════════════════
#  dem2dged_validate.py
# ═══════════════════════════════════════════════════════════════════════════

P("dem2dged_validate.py", "A4",
  "GDAL import guard: raise ImportError instead of sys.exit at module scope",
  '''except ImportError as _gdal_err:            # pragma: no cover - environment
    sys.exit("ERROR: GDAL/osgeo is not available in this Python environment "
             "(%s).\\nInstall it (conda install -c conda-forge gdal) and try "
             "again." % _gdal_err)''',
  '''except ImportError as _gdal_err:            # pragma: no cover - environment
    # v0.56: was sys.exit(), which raises SystemExit -- and SystemExit
    # derives from BaseException, NOT Exception. Every caller that guards
    # this import with "except Exception" in order to DEGRADE was therefore
    # bypassed, and the importing PROCESS died instead:
    #
    #   dem2dged.py::_run_auto_validation() wraps the import specifically to
    #   log "auto-validation SKIPPED -- could not import dem2dged_validate"
    #   and carry on, because by that point the conversion has already
    #   succeeded. It could not: the CLI terminated instead, right after
    #   writing a good delivery.
    #
    #   dem2dged_gui.py's module header wraps it to set
    #   _VALIDATE_AVAILABLE = False and simply disable one checkbox. A
    #   SystemExit there kills the GUI at startup.
    #
    # ImportError is an Exception, so both guards now work as written and as
    # documented. sys.exit() stays where it belongs -- inside main(), where a
    # CLI exit code is the thing actually wanted.
    raise ImportError(
        "GDAL/osgeo is not available in this Python environment (%s). "
        "Install it (conda install -c conda-forge gdal) and try again."
        % _gdal_err)''')

P("dem2dged_validate.py", "A4",
  "dem2dged_lib import guard: raise ImportError instead of sys.exit",
  '''except ImportError as _lib_err:             # pragma: no cover - install error
    sys.exit("ERROR: cannot import dem2dged_lib.py (%s).\\n"
             "dem2dged_validate.py validates against the DGED tables and the\\n"
             "filename helpers defined there, so it deliberately refuses to\\n"
             "run without them rather than check a delivery against a stale\\n"
             "hand-copied copy. Keep dem2dged_lib.py next to this script."
             % _lib_err)''',
  '''except ImportError as _lib_err:             # pragma: no cover - install error
    # v0.56: ImportError, not sys.exit() -- see the GDAL guard above for why
    # SystemExit at module scope defeats every caller's "except Exception".
    # This is the guard that would fire in the v0.41 blocker scenario (a
    # broken or missing dem2dged_lib.py), which is exactly when the
    # documented graceful degradation matters most.
    raise ImportError(
        "cannot import dem2dged_lib.py (%s). dem2dged_validate.py validates "
        "against the DGED tables and the filename helpers defined there, so "
        "it deliberately refuses to run without them rather than check a "
        "delivery against a stale hand-copied copy. Keep dem2dged_lib.py "
        "next to this script." % _lib_err)''')

P("dem2dged_validate.py", "A3 C3",
  "check_tile(): read the sidecar in a context manager and report decode/IO errors",
  '''        try:
            txt = open(xml_path, encoding="utf-8").read()
            ET.fromstring(txt)''',
  '''        try:
            # v0.56: a context manager (the file handle used to leak), and
            # see the widened except clause below.
            with open(xml_path, encoding="utf-8") as _xf:
                txt = _xf.read()
            ET.fromstring(txt)''')

P("dem2dged_validate.py", "A3",
  "check_tile(): a mis-encoded or unreadable sidecar is a finding, not a traceback",
  '''        except ET.ParseError as e:
            rep.fail("%s.xml: not well-formed XML (%s)" % (base, e), tile=base, cat="metadata")''',
  '''        except ET.ParseError as e:
            rep.fail("%s.xml: not well-formed XML (%s)" % (base, e), tile=base, cat="metadata")
        except UnicodeDecodeError as e:
            # v0.56: only ET.ParseError was caught, so a sidecar written in
            # the platform code page instead of the UTF-8 it declares -- what
            # dem2dged_lib did before v0.56 -- crashed the validator with a
            # raw traceback instead of producing a finding. A delivery the
            # validator cannot read is exactly the delivery it must report on.
            rep.fail("%s.xml: not valid UTF-8 (%s). The sidecar declares "
                     "encoding=\\"UTF-8\\"; it was probably written by a "
                     "pre-v0.56 converter on a non-UTF-8 console."
                     % (base, e), tile=base, cat="metadata")
        except OSError as e:
            rep.fail("%s.xml: cannot be read (%s)" % (base, e),
                     tile=base, cat="metadata")''')


# ═══════════════════════════════════════════════════════════════════════════
#  dem2dged_utm.py
# ═══════════════════════════════════════════════════════════════════════════

P("dem2dged_utm.py", "A5",
  "autodetect_utm(): correct Svalbard zone boundaries, honest Norway handling, visible warnings",
  '''    # Special case: Svalbard (74-81 deg N) uses special wide zones (31X, 33X, 35X, 37X)
    if 74 <= lat < 81:
        dl.dp("WARNING: Svalbard region detected (74-81 deg N). UTM auto-detect may be "
              "incorrect. Please specify the zone explicitly with --zone (e.g. 33X)")
        if lon < -6:
            zone = 31
        elif lon < 6:
            zone = 33
        elif lon < 18:
            zone = 35
        else:
            zone = 37
        epsg = int("326%02d" % zone)  # 326XX for special Svalbard zones
    # Special case: Norway (60-74 deg N) zones 32V, 32W
    elif 60 <= lat < 74 and 3 <= lon < 12:
        dl.dp("WARNING: Norway region detected. UTM auto-detect may be unreliable. "
              "Consider specifying --zone explicitly (e.g. 32N, 32V, or 32W)")
        zone = math.floor((lon + 180) / 6) + 1
        ns = "7" if lat < 0 else "6"
        epsg = int("32%s%02d" % (ns, zone))
    else:''',
  '''    # Special case: Svalbard (74-81 deg N) uses four WIDE zones.
    #
    # v0.56 -- THE BOUNDARIES WERE WRONG, AND THE WARNING WAS INVISIBLE.
    #
    # The spec zones are 31X = 0-9E, 33X = 9-21E, 35X = 21-33E and
    # 37X = 33-42E. The pre-v0.56 code split on -6 / 6 / 18, so every
    # Svalbard longitude resolved one zone too high, and its first threshold
    # (lon < -6) cannot occur in Svalbard at all. MEASURED at lat 78N:
    # 7 of 9 probe longitudes returned the wrong zone -- 20E gave zone 37
    # where the spec says 33. A wrong zone here is a wrong CRS for the whole
    # delivery, not a cosmetic naming issue.
    #
    # The warning also went through dl.dp(), which prints ONLY under
    # -verbose. The one message an operator most needs to see was the one
    # they could not. Both warnings now use print().
    if 74 <= lat < 81:
        print("WARNING: Svalbard region detected (74-81 deg N), which uses "
              "the wide zones 31X / 33X / 35X / 37X. Auto-detect follows the "
              "spec boundaries (0-9E, 9-21E, 21-33E, 33-42E), but if your "
              "data straddles one, pass -utm_zone explicitly.")
        if lon < 9:
            zone = 31
        elif lon < 21:
            zone = 33
        elif lon < 33:
            zone = 35
        else:
            zone = 37
        # Northern hemisphere by definition at these latitudes. The Svalbard
        # zones share the standard zones' projection parameters (same central
        # meridian); only their east-west EXTENT is non-standard, so the
        # standard 326XX code is the correct CRS.
        epsg = int("326%02d" % zone)
    # Special case: Norway. Zone 32V is widened to cover 3-12E at 56-64N.
    #
    # v0.56: the pre-v0.56 branch here was byte-for-byte identical to the
    # generic branch below -- same formula, same result -- so it applied no
    # special handling whatsoever while claiming to. It is now honest: the
    # generic formula is used (which is correct for the CRS, since 32V shares
    # zone 32's projection), and the operator is TOLD, visibly, that the
    # zone boundary in this band is non-standard.
    elif 56 <= lat < 64 and 3 <= lon < 12:
        zone = math.floor((lon + 180) / 6) + 1
        if zone != 32:
            print("WARNING: this extent falls in the widened Norwegian zone "
                  "32V (3-12E at 56-64N). Auto-detect resolved zone %d from "
                  "the generic formula; if your data belongs in 32V, pass "
                  "-utm_zone 32N explicitly." % zone)
        ns = "7" if lat < 0 else "6"
        epsg = int("32%s%02d" % (ns, zone))
    else:''')


# ═══════════════════════════════════════════════════════════════════════════
#  dem2dged_terrain.py
# ═══════════════════════════════════════════════════════════════════════════

P("dem2dged_terrain.py", "B3",
  "compliance_thresholds(): fall back to the bundled profile instead of no gate at all",
  '''    try:
        with open(path, encoding="utf-8") as f:
            profiles = json.load(f).get("profiles", {})
        value = profiles.get(profile, {})
    except Exception:
        value = DEFAULT_COMPLIANCE_PROFILES.get(profile, {})
    return {k: float(v) for k, v in value.items()
            if k.startswith("max_") and isinstance(v, (int, float))}''',
  '''    try:
        with open(path, encoding="utf-8") as f:
            profiles = json.load(f).get("profiles", {})
    except Exception:
        profiles = {}

    if profile in profiles:
        value = profiles[profile]
    else:
        # v0.56: the fallback used to fire only when READING the file raised.
        # If the file loaded but did not contain the named profile -- someone
        # renames "strict", or ships a trimmed policy -- profiles.get() gave
        # {} and every gate in compliance_result() silently became INFO. A
        # compliance tool then reported a pass for a run in which nothing was
        # evaluated. Fall back to the bundled defaults, and say so.
        value = DEFAULT_COMPLIANCE_PROFILES.get(profile, {})
        if profiles:
            print("WARNING: compliance profile '%s' is not defined in "
                  "DEM2DGED_Compliance_Policy.json; using the bundled "
                  "default for it instead of running with no thresholds."
                  % profile)

    return {k: float(v) for k, v in value.items()
            if k.startswith("max_") and isinstance(v, (int, float))}''')

P("dem2dged_terrain.py", "B3",
  "compliance_result(): report NOT_EVALUATED when no threshold was applied",
  '''    statuses = [x["status"] for x in checks.values()]
    overall = "FAIL" if "FAIL" in statuses else ("WARN" if "WARN" in statuses else "PASS")
    return {"overall": overall, "checks": checks, "steep_slope": steep or {}}''',
  '''    statuses = [x["status"] for x in checks.values()]
    metric_statuses = [checks[k]["status"]
                       for k in ("bias", "rmse", "p95", "p99", "max")]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "WARN" in statuses:
        overall = "WARN"
    elif all(s == "INFO" for s in metric_statuses):
        # v0.56: every metric came back INFO, meaning no threshold was
        # applied to any of them -- the "informational" profile, or a
        # profile with no max_* keys. Reporting that as PASS contradicts the
        # principle dem2dged_compliance's own module docstring states:
        # missing evidence is NOT_EVALUATED and never PASS. Note the
        # structural check is deliberately excluded from this test, since it
        # always produces PASS or FAIL and would mask an unevaluated run.
        overall = "NOT_EVALUATED"
    else:
        overall = "PASS"
    return {"overall": overall, "checks": checks, "steep_slope": steep or {}}''')

P("dem2dged_terrain.py", "B2",
  "inspect_source(): stream the statistics instead of loading the whole raster, and cache",
  '''def inspect_source(path: str) -> SourceInspection:
    """Read source metadata and basic value statistics without modifying it."""
    gdal, _ = _gdal()
    ds = gdal.Open(path, gdal.GA_ReadOnly)''',
  '''_INSPECTION_CACHE: Dict[Any, "SourceInspection"] = {}


def inspect_source(path: str, use_cache: bool = True) -> SourceInspection:
    """Read source metadata and basic value statistics without modifying it.

    v0.56 -- TWO COSTS REMOVED, NO BEHAVIOUR CHANGED.

    (1) It used to call band.ReadAsArray() with NO WINDOW and then cast the
        result to float64 -- 4x the file size in RAM for an Int16 source --
        purely to obtain a minimum and a maximum. MEASURED: an 8 MB Int16
        probe built a 32 MB working array; a 4 GB delivery source would need
        16 GB. Every other raster reader in this project (compute_tile_stats,
        clamp_tile_to_range, build_prefiltered_source) already streams.
        band.ComputeRasterMinMax(False) is exact, NoData-aware, and streamed
        by GDAL itself.

        This mattered more than it looks: BOTH call sites wrap the call in
        "except Exception", and MemoryError IS an Exception -- so on a large
        source the failure degraded to a missing source_inspection.json and a
        debug-level note. The operator saw a multi-minute stall, no
        explanation, and a silently incomplete delivery.

    (2) It ran TWICE per CLI conversion: dem2dged.py's main() inspects the
        source, then hands off to dem2dged_geo/utm.main(), which inspects it
        again. Those run in the same process, so a small cache keyed on
        (path, mtime, size) collapses the second call to a dict lookup while
        still re-reading a file that has actually changed on disk. Pass
        use_cache=False to force a fresh read.
    """
    gdal, _ = _gdal()

    cache_key = None
    try:
        st = os.stat(path)
        cache_key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        cache_key = None
    if use_cache and cache_key is not None and cache_key in _INSPECTION_CACHE:
        return _INSPECTION_CACHE[cache_key]

    ds = gdal.Open(path, gdal.GA_ReadOnly)''')

P("dem2dged_terrain.py", "B2",
  "inspect_source(): replace the whole-raster read with a streamed min/max",
  '''    arr = band.ReadAsArray()
    valid = None
    warnings: List[str] = []
    if arr is not None:
        import numpy as np
        a = np.asarray(arr, dtype="float64")
        mask = np.isfinite(a)
        if nodata is not None:
            mask &= ~np.isclose(a, float(nodata))
        if mask.any():
            valid = (float(a[mask].min()), float(a[mask].max()))''',
  '''    valid = None
    warnings: List[str] = []
    # v0.56: streamed by GDAL, NoData-aware, exact (approx_ok = False).
    # Returns None / raises on an all-NoData band, which is a legitimate
    # "no valid range" answer rather than an error worth propagating.
    try:
        vmin, vmax = band.ComputeRasterMinMax(False)
        if vmin == vmin and vmax == vmax:          # both finite, not NaN
            valid = (float(vmin), float(vmax))
    except Exception:
        valid = None''')

P("dem2dged_terrain.py", "B2",
  "inspect_source(): store the result in the cache before returning",
  '''    return SourceInspection(
        path=os.path.abspath(path),''',
  '''    info = SourceInspection(
        path=os.path.abspath(path),''')

P("dem2dged_terrain.py", "B2",
  "inspect_source(): close the constructor and populate the cache",
  '''        valid_range=valid,
        warnings=warnings,
    )''',
  '''        valid_range=valid,
        warnings=warnings,
    )
    if cache_key is not None:
        _INSPECTION_CACHE[cache_key] = info
    return info''')

P("dem2dged_terrain.py", "C4",
  "drop the unused typing.Iterable import",
  '''from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple''',
  '''from typing import Any, Dict, List, Optional, Sequence, Tuple''')


# ═══════════════════════════════════════════════════════════════════════════
#  runner
# ═══════════════════════════════════════════════════════════════════════════


def main():
    ap = argparse.ArgumentParser(
        description="Apply the v%s review fixes to produce v%s."
                    % (OLD_VERSION, NEW_VERSION))
    ap.add_argument("--apply", action="store_true",
                    help="write the files (without this it is a dry run)")
    args = ap.parse_args()

    by_file = {}
    for fname, finding, desc, old, new in PATCHES:
        by_file.setdefault(fname, []).append((finding, desc, old, new))

    print("=" * 74)
    print("dem2dged  v%s -> v%s   (%s)"
          % (OLD_VERSION, NEW_VERSION,
             "APPLY" if args.apply else "DRY RUN -- nothing will be written"))
    print("=" * 74)

    total_applied = total_skipped = total_failed = 0

    for fname in by_file:
        path = os.path.join(HERE, fname)
        print("")
        print("-- %s" % fname)
        if not os.path.isfile(path):
            print("   [FAIL] file not found")
            total_failed += len(by_file[fname])
            continue

        text = io.open(path, encoding="utf-8", newline="").read()
        working = text
        applied, skipped, failed = [], [], []

        for finding, desc, old, new in by_file[fname]:
            # Already applied? Test for the REPLACEMENT text, and test it
            # FIRST. Most edits here are insertions whose `new` ends with
            # `old` verbatim, so `old` survives the edit -- an "is old gone?"
            # test re-applies them and duplicates the inserted block. A
            # line-level marker heuristic was tried instead and was worse:
            # `_note_delivered(...)` indented 12 spaces is a SUBSTRING of the
            # same call indented 16, so applying one edit made the next look
            # already-applied and it was silently skipped. The full `new`
            # block cannot be ambiguous: it is present after the edit and
            # cannot occur in the original file.
            if working.count(new) >= 1:
                skipped.append((finding, desc))
                continue
            n = working.count(old)
            if n == 1:
                working = working.replace(old, new, 1)
                applied.append((finding, desc))
            elif n == 0:
                failed.append((finding, desc, "no match"))
            else:
                failed.append((finding, desc, "%d matches, expected 1" % n))

        for finding, desc in applied:
            print("   [ OK ] %-8s %s" % (finding, desc))
        for finding, desc in skipped:
            print("   [SKIP] %-8s %s  (already applied)" % (finding, desc))
        for finding, desc, why in failed:
            print("   [FAIL] %-8s %s  (%s)" % (finding, desc, why))

        total_applied += len(applied)
        total_skipped += len(skipped)
        total_failed += len(failed)

        if failed:
            print("   -> %d edit(s) did not match; %s LEFT UNCHANGED."
                  % (len(failed), fname))
            continue

        if applied and args.apply:
            with io.open(path, "w", encoding="utf-8", newline="") as f:
                f.write(working)
            print("   -> written (%d edit(s))" % len(applied))
        elif applied:
            print("   -> %d edit(s) would be written" % len(applied))

    print("")
    print("=" * 74)
    print("applied=%d  already-applied=%d  failed=%d"
          % (total_applied, total_skipped, total_failed))
    if not args.apply and total_applied:
        print("Dry run. Re-run with --apply to write the files.")
    print("=" * 74)
    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(main())
