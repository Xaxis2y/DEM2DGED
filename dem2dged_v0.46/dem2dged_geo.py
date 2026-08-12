# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.46
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

import argparse, os, math, shlex
import dem2dged_lib as dl

# -- CLI ----------------------------------------------------------------------

parser = argparse.ArgumentParser(
    description="Convert a DEM to DGED GEO tiles (WGS-84)."
)
parser.add_argument("input_raster",
    help="Elevation raster - any GDAL source (GeoTIFF, VRT, ...)")
parser.add_argument("output_folder",
    help="Destination folder for generated tiles")
parser.add_argument("-product_level", dest="product_level", default="5",
    help="Product level: 0-3, 4b, 4, 5, 6, 7, 8, 9  (default 5 ~= 2 m GSD)")
parser.add_argument("-xml_template", dest="xml_template",
    default="DGED_GEO_TEMPLATE.xml",
    help="Sidecar XML template  (default: DGED_GEO_TEMPLATE.xml)")
parser.add_argument("-source_type", dest="source_type", default="A",
    help="Source-type letter per DGED spec  (default A)")
parser.add_argument("-security_class", dest="sec_class", default="U",
    help="Security class: T S C R U  (default U = unclassified)")
parser.add_argument("-product_version", dest="prod_ver", default="01",
    help="Two-digit product version  (default 01)")
parser.add_argument("-org", dest="org", default="",
    help="Optional 3-letter producer organisation/nation code (STANAG 1059) "
         "embedded in filenames and metadata (default: none)")
parser.add_argument("-abs_hacc", dest="abs_hacc", default="auto",
    help="Absolute horizontal accuracy CE90 in metres written to the "
         "metadata quality report (default auto = DGED spec Table 5 goal "
         "value for the level)")
parser.add_argument("-abs_vacc", dest="abs_vacc", default="auto",
    help="Absolute vertical accuracy LE90 in metres written to the metadata "
         "quality report (default auto = DGED spec Table 6 goal value)")
parser.add_argument("-lineage", dest="lineage", default="",
    help="Lineage statement written to the metadata (default: generated "
         "from the source file name and processing parameters)")
parser.add_argument("-resample", dest="resample", default="auto",
    help="Resampling: auto|optimize|bilinear|cubic|cubicspline|average|"
         "lanczos|near (default auto = average when downsampling, else "
         "bilinear; optimize = measure Nearest/Bilinear/Cubic against the "
         "source DEM and use whichever reconstructs it most accurately -- "
         "slower, see dl.resolve_resampler())")
parser.add_argument("-source_vertical", dest="src_vert", default=None,
    help="Source vertical EPSG (e.g. 5773=EGM96, 3855=EGM2008, or a national "
         "code). If given and != 3855, a REAL geoid transform to EGM2008 is "
         "performed (needs PROJ vertical grids). If omitted, heights are "
         "assumed to be EGM2008 already and only the label is applied (warned).")
parser.add_argument("-verbose", action="store_true",
    help="Show additional output")
parser.add_argument("-skip_sanity_check", action="store_true",
    help="Proceed even if the input raster's value range and filename "
         "look like non-elevation data (e.g. an aspect/direction layer). "
         "See dl.sanity_check_elevation_source().")

# -- Helpers ------------------------------------------------------------------

# Kept as a thin alias so existing imports (tests, GUI) keep working;
# the implementation lives in dem2dged_lib (v0.27).
ToDMS = dl.ToDMS


def resolve_lon_multiplication(lat):
    multi = 1
    for l in dl.zone_lon_spacing:
        if lat >= l[1]:
            multi = l[4]
    return multi


def resolve_level_geo(lvl):
    for l in dl.level_tilesize_and_spatial_resolution:
        if l[0] == lvl:
            return l[1] / 60, l[2] / 3600, l[3]   # min->deg, arcsec->deg
    valid = ", ".join(l[0] for l in dl.level_tilesize_and_spatial_resolution)
    raise SystemExit("ERROR: unknown GEO product level '%s' (valid: %s)"
                     % (lvl, valid))

# -- Main ---------------------------------------------------------------------

def main(args):
    MY_OUT_SRS = 4326
    pargs = parser.parse_args(args[1:])
    dl.debug = pargs.verbose

    os.makedirs(pargs.output_folder, exist_ok=True)

    # v0.42 pre-flight, in the order a run actually depends on things:
    #   1. gdalwarp on PATH  -- otherwise subprocess raised a raw
    #      FileNotFoundError traceback on the first tile.
    #   2. the -resample value  -- otherwise gdalwarp rejected it once per
    #      tile and the run still ended with "All done!" and exit code 0.
    # Both are cheap and neither touches the raster, so they run first.
    dl.require_gdalwarp()
    pargs.resample = dl.validate_resampler(pargs.resample)

    # v0.36: catch an aspect/direction/curvature raster being fed in by
    # mistake BEFORE spending any time on it, instead of only surfacing it
    # in the post-conversion validation report after a full tile run.
    dl.run_sanity_check_cli(pargs.input_raster, pargs.skip_sanity_check)

    template  = dl.read_sidecar_template(pargs.xml_template)
    in_ext    = dl.get_extent_and_srs_of_input_raster(pargs.input_raster)

    # NOTE: with GDAL 3 the EPSG:4326 axis order is authority-compliant
    # (lat, lon), so the FIRST pair returned by get_bbox_of_output is the
    # LATITUDE range and the second pair is the LONGITUDE range.
    minlat, maxlat, minlon, maxlon = dl.get_bbox_of_output(in_ext, MY_OUT_SRS)
    dl.dp("Bounding box: lat %s..%s  lon %s..%s" % (minlat, maxlat, minlon, maxlon))

    tiledim, latres, tile_letter = resolve_level_geo(pargs.product_level)
    dl.dp("Tile dim: %s deg  lat-res: %s deg  letter: %s" % (tiledim, latres, tile_letter))

    # -- Data type (v0.27) -----------------------------------------------------
    # DGED spec section 7: signed 16-bit integer is MANDATORY for levels 0-2;
    # Float32 is valid for level 3 and above.
    out_type = dl.output_type_for_level(pargs.product_level)
    dl.dp("Output data type: %s" % out_type)

    # v0.39: LZW predictor is data-type aware -- PREDICTOR=3 (floating-point)
    # for Float32 tiles, PREDICTOR=2 (horizontal differencing) for Int16.
    # See dl.predictor_for_type().
    predictor = dl.predictor_for_type(out_type)

    # v0.39: warn (never block) on a reserved/unknown source-type code so a
    # non-spec filename doesn't ship silently (spec 12.1). Default "A" is
    # valid and stays quiet.
    _st_ok, _st_msg = dl.describe_source_type(pargs.source_type)
    if not _st_ok:
        print("WARNING: %s" % _st_msg)

    # -- Resampler selection (v0.20) ------------------------------------------
    # Compare source post spacing to the target (lat) spacing, both in metres.
    src_gsd_m = dl.source_gsd_meters(pargs.input_raster)
    dst_gsd_m = latres * 111320
    resamp    = dl.resolve_resampler(pargs.input_raster, src_gsd_m, dst_gsd_m,
                                     pargs.resample)
    dl.dp("Resampler: %s  (src~=%.3f m -> dst~=%.3f m)" % (resamp, src_gsd_m, dst_gsd_m))

    # v0.37 (DGED_Conversion_Review.md Finding 3): cubic-family resamplers
    # can overshoot -- "ring" -- past the source's true min/max at sharp
    # discontinuities. Scan the source's exact min/max ONCE up front so
    # every tile can be clamped back into range right after it is warped,
    # instead of silently shipping a physically impossible elevation. Only
    # done for resamplers actually capable of it -- "auto"/"optimize" never
    # resolve to one of these on their own (see pick_resampler()'s
    # docstring), so this only costs anything when explicitly requested.
    clamp_range = None
    if resamp in dl.OVERSHOOT_PRONE_RESAMPLERS:
        src_vmin, src_vmax, _src_miss = dl.compute_tile_stats(pargs.input_raster)
        clamp_range = (src_vmin, src_vmax)
        dl.dp("Overshoot-prone resampler (%s): tiles will be clamped to the "
              "source's range %s..%s m" % (resamp, src_vmin, src_vmax))

    # -- Vertical-datum strategy (v0.20) --------------------------------------
    # If the caller declares a source vertical datum other than EGM2008, let
    # gdalwarp apply the real geoid shift; otherwise fall back to the historic
    # label-only re-tag and warn that heights are ASSUMED to be EGM2008.
    if pargs.src_vert and str(pargs.src_vert) != "3855":
        s_srs_args  = ["-s_srs", "EPSG:%s+%s" % (in_ext[4], pargs.src_vert)]
        t_srs_args  = ["-t_srs", "EPSG:%s+3855" % MY_OUT_SRS]
        do_retag    = False   # warp output already carries the correct CRS
        vert_note   = ("vertical datum transformed EPSG:%s -> EPSG:3855 "
                       "(EGM2008)" % pargs.src_vert)
        dl.dp("Vertical: transforming EPSG:%s+%s -> EPSG:%s+3855 (EGM2008)"
              % (in_ext[4], pargs.src_vert, MY_OUT_SRS))
    else:
        if not pargs.src_vert:
            print("WARNING: -source_vertical not set - output heights are "
                  "ASSUMED to already be EGM2008; no vertical transform is "
                  "applied (only the EPSG:%s+3855 label). Pass -source_vertical "
                  "if your DEM uses another vertical datum." % MY_OUT_SRS)
        s_srs_args = []
        t_srs_args = ["-t_srs", "EPSG:%s" % MY_OUT_SRS]
        do_retag  = True
        vert_note = "heights assumed EGM2008 (label only, no vertical transform)"

    lineage = pargs.lineage or (
        "Derived from source raster '%s' by dem2dged v%s; gdalwarp resampling"
        "=%s; %s." % (os.path.basename(pargs.input_raster), dl.VERSION,
                      resamp, vert_note))

    # v0.34: the upper bound is ceil(), not floor()+1. floor()+1
    # unconditionally added one tile row and column past the data, so a
    # source whose extent lands exactly on the tile grid -- a whole-degree
    # DEM sheet, the common case -- got a full row and column of tiles that
    # start outside it and contain nothing but NoData. On a 1x1 degree
    # level-5 source that was 21 of 121 tiles, each costing a warp, a
    # compute_tile_stats() pass, a sidecar and a TOC entry. ceil() gives an
    # identical result whenever the maximum is NOT on a tile boundary, and
    # one fewer row/column when it is. max(...) keeps at least one tile for
    # a degenerate zero-area extent.
    ilat_s = math.floor(minlat / tiledim)
    ilat_e = max(ilat_s + 1, math.ceil(maxlat / tiledim))
    ilon_s = math.floor(minlon / tiledim)
    ilon_e = max(ilon_s + 1, math.ceil(maxlon / tiledim))

    total  = (ilat_e - ilat_s) * (ilon_e - ilon_s)
    done   = 0

    tile_basenames = []
    prod_west = prod_east = prod_south = prod_north = None
    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below
    n_failed = 0      # v0.42: tiles whose gdalwarp call returned non-zero

    # -- Phase 1: warp every tile -------------------------------------------
    for yy in range(ilat_s, ilat_e):
        for xx in range(ilon_s, ilon_e):
            done += 1
            pct   = int(100 * done / total)

            t_minlat = yy * tiledim
            lonres   = resolve_lon_multiplication(t_minlat) * latres
            t_minlon = xx * tiledim

            # v0.27: HALF-POST EXPANDED warp extent (spec 6.3 / test A.2).
            # Posts run from t_min to t_min+tiledim INCLUSIVE; gdalwarp
            # samples at pixel centers, so the -te extent extends half a
            # post spacing beyond the outermost posts on every side. Pixel
            # centers then coincide exactly with DGED post locations.
            #
            # v0.37 (DGED_Conversion_Review.md Finding 1): rounded to a
            # fixed decimal precision so the same real-world boundary is
            # always represented by the identical float, however it is
            # reached arithmetically -- 1e-9 degrees is below 0.1 mm at the
            # equator, far finer than any DEM post spacing, so this is a
            # no-op for real coordinates. This narrows, but does not by
            # itself guarantee, the tile-edge mismatch described in the
            # review; reconcile_tile_edges() below is what makes the shared
            # post an exact match unconditionally.
            te_xmin = round(t_minlon - lonres / 2.0, 9)
            te_ymin = round(t_minlat - latres / 2.0, 9)
            te_xmax = round(t_minlon + tiledim + lonres / 2.0, 9)
            te_ymax = round(t_minlat + tiledim + latres / 2.0, 9)

            basename = dl.geo_tile_basename(
                pargs.product_level, tile_letter, t_minlat, t_minlon,
                pargs.source_type, pargs.sec_class, pargs.prod_ver,
                org=pargs.org)

            tif_path = os.path.join(pargs.output_folder, basename + ".tif")
            xml_path = os.path.join(pargs.output_folder, basename + ".xml")

            # Track product extent (post extent, not the expanded warp extent)
            pw, ps = t_minlon, t_minlat
            pe, pn = t_minlon + tiledim, t_minlat + tiledim
            prod_west  = pw if prod_west  is None else min(prod_west, pw)
            prod_south = ps if prod_south is None else min(prod_south, ps)
            prod_east  = pe if prod_east  is None else max(prod_east, pe)
            prod_north = pn if prod_north is None else max(prod_north, pn)

            if os.path.isfile(xml_path):
                print("Skip (exists): %s" % xml_path)
                tile_basenames.append(basename)
                continue

            dl.dp("-" * 60)
            dl.dp("Creating: %s" % tif_path)

            # Vertical handling (v0.20): either a real -s_srs/-t_srs geoid
            # transform, or the historic horizontal-only warp + label re-tag.
            # v0.28: built as an argument LIST (not a shell string) so
            # run_cmd() can execute it with shell=False -- see dl.run_cmd()
            # for why that matters for paths with special characters.
            cmd = (["gdalwarp"] + s_srs_args + t_srs_args + [
                "-te", str(te_xmin), str(te_ymin), str(te_xmax), str(te_ymax),
                "-dstnodata", "-32767",
                "-tr", str(lonres), str(latres),
                "-r", resamp,
                "-ot", out_type,
                "-co", "COMPRESS=LZW", "-co", "PREDICTOR=" + predictor,
                "-co", "TILED=YES",
                "--config", "GTIFF_REPORT_COMPD_CS", "YES",
                pargs.input_raster, tif_path,
            ])
            dl.dp(shlex.join(cmd))
            if dl.run_cmd(cmd) != 0:
                print("ERROR: gdalwarp failed for %s - tile skipped (re-run to retry)" % basename)
                n_failed += 1
                continue

            dl.dp("Fixing TIFF header ...")
            # do_retag=False when gdalwarp already produced the compound CRS:
            # only set AREA_OR_POINT=Point, don't overwrite the projection.
            dl.fix_header(tif_path,
                          "EPSG:%s+3855" % MY_OUT_SRS if do_retag else None)

            # v0.37 (Finding 3): clamp BEFORE this tile is added to
            # tile_grid, so if Finding 1's edge reconciliation later copies
            # this tile's edge onto a neighbour, it copies the already-
            # clamped values.
            if clamp_range is not None:
                n_clamped = dl.clamp_tile_to_range(tif_path, *clamp_range)
                if n_clamped:
                    dl.dp("  Clamped %d pixel(s) back into the source range"
                          % n_clamped)

            tile_grid[(yy, xx)] = tif_path
            pending.append(dict(basename=basename, tif_path=tif_path,
                                 xml_path=xml_path, pw=pw, ps=ps, pe=pe, pn=pn))
            tile_basenames.append(basename)
            print("%d%% done" % pct)

    # v0.42: a run in which EVERY warp failed used to fall straight through
    # to "All done!" and return normally, so dem2dged.py went on to
    # auto-validate an empty folder and the operator's only clue was the
    # per-tile ERROR lines scrolled off the top. Nothing produced is a hard
    # failure; a partial run says so plainly and continues, because the
    # tiles that DID warp are still valid deliverables.
    if not tile_basenames:
        raise SystemExit(
            "ERROR: no tiles were produced (%d of %d gdalwarp call(s) "
            "failed).\n"
            "       Nothing was written to %s.\n"
            "       Check the gdalwarp errors above -- the usual causes are "
            "a source\n"
            "       raster GDAL cannot read, a full disk, or a source that "
            "does not\n"
            "       overlap the requested area at all."
            % (n_failed, total, pargs.output_folder))
    if n_failed:
        print("WARNING: %d of %d tile(s) failed to warp and are MISSING from "
              "the delivery. Re-run this exact command to retry only the "
              "missing tiles (existing tiles are skipped)." % (n_failed, total))

    # -- Phase 2: reconcile shared edges (v0.37, Finding 1) ------------------
    # Runs once, after every tile in this batch has been warped, and BEFORE
    # per-tile stats are computed below, so the sidecar XML's min/max/
    # completeness always describe the pixels actually delivered. Progress
    # ("X% done") is already printed above, tied to warping (the slow part)
    # rather than to this bookkeeping pass.
    if len(tile_grid) > 1:
        n_fixed = dl.reconcile_tile_edges(tile_grid)
        if n_fixed:
            dl.dp("Reconciled %d shared tile edge(s) so adjacent posts match "
                  "exactly." % n_fixed)

    # -- Phase 3: per-tile stats + sidecar XML --------------------------------
    # Sidecar GSD field is in metres - convert lat resolution (degrees) to
    # approximate metres (1 deg latitude ~= 111 320 m). Loop-invariant, so
    # computed once rather than once per tile as before v0.37.
    gsd_m = round(latres * 111320, 3)
    for item in pending:
        repl = dl.sidecar_replacements(
            item["basename"], pargs.product_level, gsd_m,
            str(MY_OUT_SRS), pargs.sec_class, pargs.org,
            (item["pw"], item["ps"], item["pe"], item["pn"]), item["tif_path"],
            abs_hacc=pargs.abs_hacc, abs_vacc=pargs.abs_vacc,
            lineage=lineage)
        dl.write_sidecar_file(template, item["xml_path"], repl)

    # -- Product delivery files (v0.27, spec 12.1 / 6.6) -----------------------
    if tile_basenames:
        product_id = "DGEDL%sG" % pargs.product_level
        toc = dl.write_toc_file(pargs.output_folder, product_id)
        print("Table of contents written: %s" % toc)
        if len(tile_basenames) > 1:
            coll = dl.write_collection_metadata(
                pargs.output_folder, product_id, pargs.product_level,
                str(MY_OUT_SRS),
                (prod_west, prod_south, prod_east, prod_north),
                tile_basenames, pargs.sec_class, org=pargs.org)
            print("Collection metadata written: %s" % coll)
            # Regenerate the TOC so it also lists the collection metadata.
            dl.write_toc_file(pargs.output_folder, product_id)

    print("All done!")
    # v0.37: return the resolved resampler so callers that auto-validate
    # right after conversion (dem2dged.py) can tell the validator what was
    # actually used instead of it assuming Bilinear -- see
    # DGED_Conversion_Review.md Finding 2.
    return resamp
