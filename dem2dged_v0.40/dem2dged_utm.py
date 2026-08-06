# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

import argparse, os, math, shlex
from osgeo import ogr, osr
import dem2dged_lib as dl

# -- CLI ----------------------------------------------------------------------

parser = argparse.ArgumentParser(
    description="Convert a DEM to DGED UTM tiles."
)
parser.add_argument("input_raster",
    help="Elevation raster - any GDAL source (GeoTIFF, VRT, ...)")
parser.add_argument("output_folder",
    help="Destination folder for generated tiles")
parser.add_argument("-utm_zone", dest="utm", default="autodetect",
    help="UTM zone e.g. '32N' or '09S'  (default: auto-detect)")
parser.add_argument("-product_level", dest="product_level", default="5",
    help="Product level: 4b, 4, 5, 6, 7, 8, 9  (default 5 = 2 m GSD)")
parser.add_argument("-xml_template", dest="xml_template",
    default="DGED_UTM_TEMPLATE.xml",
    help="Sidecar XML template  (default: DGED_UTM_TEMPLATE.xml)")
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

def resolve_level_utm(lvl):
    for l in dl.PL:
        if l[0] == lvl:
            return l[1], l[2], l[3]
    valid = ", ".join(l[0] for l in dl.PL)
    raise SystemExit(
        "ERROR: unknown UTM product level '%s' (valid: %s).\n"
        "Levels 0-3 exist only for GEO output." % (lvl, valid))


def autodetect_utm(ext):
    """Auto-detect UTM zone from extent center point.

    Handles special zones for Svalbard (31X, 33X, 35X, 37X) and Norway
    (32V, 32W). Issues a WARNING for high-latitude regions where zone
    boundaries are ambiguous.
    """
    cx = (ext[0] + ext[2]) / 2
    cy = (ext[1] + ext[3]) / 2

    src_srs = osr.SpatialReference()
    src_srs.ImportFromEPSG(int(ext[4]))
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    # v0.34: authority axis order set EXPLICITLY. The GetX=lat / GetY=lon
    # unpacking below only holds under authority order; before v0.34 this
    # relied on that being GDAL 3's silent default, so a global axis-mapping
    # config would have swapped lat and lon here with no error -- just a
    # wrong UTM zone. See the axis-order note in dem2dged_lib.py.
    dl.set_authority_axis_order(src_srs, wgs84)
    xform = osr.CoordinateTransformation(src_srs, wgs84)

    pt = ogr.CreateGeometryFromWkt("POINT (%s %s)" % (cx, cy))
    pt.Transform(xform)
    lon, lat = pt.GetY(), pt.GetX()   # GetX=lat, GetY=lon after to-geographic

    # Special case: Svalbard (74-81°N) uses special wide zones (31X, 33X, 35X, 37X)
    if 74 <= lat < 81:
        dl.dp("WARNING: Svalbard region detected (74-81°N). UTM auto-detect may be "
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
    # Special case: Norway (60-74°N) zones 32V, 32W
    elif 60 <= lat < 74 and 3 <= lon < 12:
        dl.dp("WARNING: Norway region detected. UTM auto-detect may be unreliable. "
              "Consider specifying --zone explicitly (e.g. 32N, 32V, or 32W)")
        zone = math.floor((lon + 180) / 6) + 1
        ns = "7" if lat < 0 else "6"
        epsg = int("32%s%02d" % (ns, zone))
    else:
        # Standard global UTM formula
        zone = math.floor((lon + 180) / 6) + 1
        ns = "7" if lat < 0 else "6"
        # Zero-pad the zone: zone 9 N must give 32609, not 3269
        epsg = int("32%s%02d" % (ns, zone))

    dl.dp("Auto-detected UTM zone %s (EPSG:%s)" % (zone, epsg))
    return epsg, zone

# -- Main ---------------------------------------------------------------------

def main(args):
    pargs = parser.parse_args(args[1:])
    dl.debug = pargs.verbose
    dl.checkos()

    os.makedirs(pargs.output_folder, exist_ok=True)

    # v0.36: catch an aspect/direction/curvature raster being fed in by
    # mistake BEFORE spending any time on it, instead of only surfacing it
    # in the post-conversion validation report after a full tile run.
    dl.run_sanity_check_cli(pargs.input_raster, pargs.skip_sanity_check)

    template = dl.read_sidecar_template(pargs.xml_template)
    in_ext   = dl.get_extent_and_srs_of_input_raster(pargs.input_raster)
    dl.dp("Input extent: %s" % str(in_ext))

    if pargs.utm == "autodetect":
        out_srs, zone_num = autodetect_utm(in_ext)
        utmzone = "%02d%s" % (zone_num, "S" if out_srs > 32699 else "N")
    else:
        z = pargs.utm.strip().upper()
        if len(z) < 2 or z[-1] not in ("N", "S") or not z[:-1].isdigit():
            raise SystemExit("ERROR: invalid UTM zone '%s' (expected e.g. 32N or 09S)"
                             % pargs.utm)
        zone_num = int(z[:-1])
        if not 1 <= zone_num <= 60:
            raise SystemExit("ERROR: UTM zone number must be 1-60, got %s" % zone_num)
        out_srs = int("32%s%02d" % ("6" if z[-1] == "N" else "7", zone_num))
        utmzone = "%02d%s" % (zone_num, z[-1])

    gsd, posts, tile_letter = resolve_level_utm(pargs.product_level)
    tiledim = (posts - 1) * gsd

    dl.dp("GSD=%s m  posts=%s  tile=%s m  EPSG:%s" % (gsd, posts, tiledim, out_srs))

    # -- Data type (v0.27) -----------------------------------------------------
    # All UTM levels are 4b and above, so Float32 is spec-valid throughout;
    # the helper keeps the policy in one place.
    out_type = dl.output_type_for_level(pargs.product_level)
    dl.dp("Output data type: %s" % out_type)

    # v0.39: LZW predictor is data-type aware -- PREDICTOR=3 (floating-point)
    # for Float32 tiles, PREDICTOR=2 (horizontal differencing) for Int16.
    # All UTM levels are Float32, so this is PREDICTOR=3 in practice; kept
    # data-type driven via the shared helper so the policy lives in one place.
    predictor = dl.predictor_for_type(out_type)

    # v0.39: warn (never block) on a reserved/unknown source-type code so a
    # non-spec filename doesn't ship silently (spec 12.1). Default "A" is
    # valid and stays quiet.
    _st_ok, _st_msg = dl.describe_source_type(pargs.source_type)
    if not _st_ok:
        print("WARNING: %s" % _st_msg)

    # -- Resampler selection (v0.20) ------------------------------------------
    # Both source and target GSD are in metres here (UTM target is metric).
    src_gsd_m = dl.source_gsd_meters(pargs.input_raster)
    resamp    = dl.resolve_resampler(pargs.input_raster, src_gsd_m, gsd,
                                     pargs.resample)
    dl.dp("Resampler: %s  (src~=%.3f m -> dst=%.3f m)" % (resamp, src_gsd_m, gsd))

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
    # Declared source vertical datum != EGM2008 -> real geoid shift via gdalwarp;
    # otherwise historic label-only re-tag, with a warning.
    if pargs.src_vert and str(pargs.src_vert) != "3855":
        s_srs_args = ["-s_srs", "EPSG:%s+%s" % (in_ext[4], pargs.src_vert)]
        t_srs_args = ["-t_srs", "EPSG:%s+3855" % out_srs]
        do_retag  = False
        vert_note = ("vertical datum transformed EPSG:%s -> EPSG:3855 "
                     "(EGM2008)" % pargs.src_vert)
        dl.dp("Vertical: transforming EPSG:%s+%s -> EPSG:%s+3855 (EGM2008)"
              % (in_ext[4], pargs.src_vert, out_srs))
    else:
        if not pargs.src_vert:
            print("WARNING: -source_vertical not set - output heights are "
                  "ASSUMED to already be EGM2008; no vertical transform is "
                  "applied (only the EPSG:%s+3855 label). Pass -source_vertical "
                  "if your DEM uses another vertical datum." % out_srs)
        s_srs_args = []
        t_srs_args = ["-t_srs", "EPSG:%s" % out_srs]
        do_retag  = True
        vert_note = "heights assumed EGM2008 (label only, no vertical transform)"

    lineage = pargs.lineage or (
        "Derived from source raster '%s' by dem2dged v%s; gdalwarp resampling"
        "=%s; %s." % (os.path.basename(pargs.input_raster), dl.VERSION,
                      resamp, vert_note))

    minx, maxx, miny, maxy = dl.get_bbox_of_output(in_ext, out_srs)
    dl.dp("Bounding box: %s %s %s %s" % (minx, maxx, miny, maxy))

    # v0.34: ceil(), not floor()+1 -- see the identical change and rationale
    # in dem2dged_geo.py (floor()+1 always produced one row and column of
    # pure-NoData tiles past the data whenever the source extent landed on a
    # tile boundary).
    ix_s = math.floor(minx / tiledim)
    ix_e = max(ix_s + 1, math.ceil(maxx / tiledim))
    iy_s = math.floor(miny / tiledim)
    iy_e = max(iy_s + 1, math.ceil(maxy / tiledim))

    # v0.39: clamp the tile grid to the valid UTM northing band. Spec 6.3.1
    # defines northings on [0, 10 000 000] m within a zone (0 at the equator
    # for the northern hemisphere, 10 000 000 at the equator for the
    # southern). A source whose reprojected extent dips just below the equator
    # -- which happens routinely for an equatorial DEM, because a point-
    # registered source such as SRTM overhangs its nominal edge by half a post
    # -- would otherwise emit a tile at a NEGATIVE northing, producing a
    # non-spec filename like "...32N-025..." (utm_tile_basename formats the
    # negative value straight into the fixed-width field) that the validator
    # then correctly rejects. Drop any tile row outside the band and warn if
    # that actually happened, since genuine sub-equator (or trans-equator)
    # data belongs in the other hemisphere's zone.
    NORTHING_MAX = 10_000_000.0
    iy_s_raw, iy_e_raw = iy_s, iy_e
    iy_s = max(iy_s, 0)
    iy_e = min(iy_e, int(math.ceil(NORTHING_MAX / tiledim)))
    iy_e = max(iy_e, iy_s + 1)
    if iy_s_raw < iy_s or iy_e_raw > iy_e:
        print("WARNING: the source extent reaches outside the valid UTM "
              "northing band [0, 10 000 000] m for zone %s -- tiles outside "
              "it were skipped (a spec-conformant DGED UTM northing must be "
              ">= 0). This is normal for an equatorial DEM whose edge "
              "overhangs the equator by half a post. If your data genuinely "
              "spans the equator, convert each hemisphere separately with an "
              "explicit -utm_zone." % utmzone)

    total = (ix_e - ix_s) * (iy_e - iy_s)
    done  = 0

    tile_basenames = []
    prod_minx = prod_miny = prod_maxx = prod_maxy = None
    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below

    # -- Phase 1: warp every tile -------------------------------------------
    for yy in range(iy_s, iy_e):
        for xx in range(ix_s, ix_e):
            done += 1
            pct   = int(100 * done / total)

            t_minx = xx * tiledim
            t_miny = yy * tiledim

            # v0.27: HALF-POST EXPANDED warp extent (spec 6.3 / test A.2).
            # Posts run from t_min to t_min+tiledim INCLUSIVE; gdalwarp
            # samples at pixel centers, so the -te extent extends half a
            # post spacing beyond the outermost posts on every side. Pixel
            # centers then coincide exactly with DGED post locations
            # ({500000 +- i*dE, j*dN} from the UTM zone origin, spec 6.3.1).
            #
            # v0.37 (DGED_Conversion_Review.md Finding 1): rounded to a
            # fixed decimal precision so the same real-world boundary is
            # always represented by the identical float, however it is
            # reached arithmetically -- 1e-9 m is far finer than any DEM
            # post spacing, so this is a no-op for real coordinates. This
            # narrows, but does not by itself guarantee, the tile-edge
            # mismatch described in the review; reconcile_tile_edges()
            # below is what makes the shared post an exact match
            # unconditionally.
            te_xmin = round(t_minx - gsd / 2.0, 9)
            te_ymin = round(t_miny - gsd / 2.0, 9)
            te_xmax = round(t_minx + tiledim + gsd / 2.0, 9)
            te_ymax = round(t_miny + tiledim + gsd / 2.0, 9)

            basename = dl.utm_tile_basename(
                pargs.product_level, tile_letter, utmzone, t_miny, t_minx,
                pargs.source_type, pargs.sec_class, pargs.prod_ver,
                org=pargs.org)

            tif_path = os.path.join(pargs.output_folder, basename + ".tif")
            xml_path = os.path.join(pargs.output_folder, basename + ".xml")

            # Track product extent (post extent, not the expanded warp extent)
            prod_minx = t_minx if prod_minx is None else min(prod_minx, t_minx)
            prod_miny = t_miny if prod_miny is None else min(prod_miny, t_miny)
            tmx, tmy = t_minx + tiledim, t_miny + tiledim
            prod_maxx = tmx if prod_maxx is None else max(prod_maxx, tmx)
            prod_maxy = tmy if prod_maxy is None else max(prod_maxy, tmy)

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
                "-tr", str(gsd), str(gsd),
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
                continue

            dl.dp("Fixing TIFF header ...")
            # do_retag=False when gdalwarp already produced the compound CRS:
            # only set AREA_OR_POINT=Point, don't overwrite the projection.
            dl.fix_header(tif_path,
                          "EPSG:%s+3855" % out_srs if do_retag else None)

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
                                 xml_path=xml_path, tmx=tmx, tmy=tmy,
                                 t_minx=t_minx, t_miny=t_miny))
            tile_basenames.append(basename)
            print("%d%% done" % pct)

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
    for item in pending:
        bbox84 = dl.bbox_to_wgs84(item["t_minx"], item["t_miny"],
                                  item["tmx"], item["tmy"], out_srs)
        repl = dl.sidecar_replacements(
            item["basename"], pargs.product_level, gsd,
            str(out_srs), pargs.sec_class, pargs.org,
            bbox84, item["tif_path"],
            abs_hacc=pargs.abs_hacc, abs_vacc=pargs.abs_vacc,
            lineage=lineage)
        dl.write_sidecar_file(template, item["xml_path"], repl)

    # -- Product delivery files (v0.27, spec 12.1 / 6.6) -----------------------
    if tile_basenames:
        product_id = "DGEDL%sU_%s" % (pargs.product_level, utmzone)
        toc = dl.write_toc_file(pargs.output_folder, product_id)
        print("Table of contents written: %s" % toc)
        if len(tile_basenames) > 1:
            bbox84 = dl.bbox_to_wgs84(prod_minx, prod_miny,
                                      prod_maxx, prod_maxy, out_srs)
            coll = dl.write_collection_metadata(
                pargs.output_folder, product_id, pargs.product_level,
                str(out_srs), bbox84, tile_basenames, pargs.sec_class,
                org=pargs.org)
            print("Collection metadata written: %s" % coll)
            # Regenerate the TOC so it also lists the collection metadata.
            dl.write_toc_file(pargs.output_folder, product_id)

    print("All done!")
    # v0.37: return the resolved resampler so callers that auto-validate
    # right after conversion (dem2dged.py) can tell the validator what was
    # actually used instead of it assuming Bilinear -- see
    # DGED_Conversion_Review.md Finding 2.
    return resamp
