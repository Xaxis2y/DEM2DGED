# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.56.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

# (typing imports removed in v0.34 -- none were used)
import argparse
import logging
import sys
import os

import dem2dged_lib as dl
import dem2dged_logging

HERE = os.path.dirname(os.path.abspath(__file__))

# -- CLI ----------------------------------------------------------------------

parser = argparse.ArgumentParser(
    prog="dem2dged",
    description="Convert a raster DEM to DGED tiles (GEO or UTM).",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Product levels and approx ground sample distance
-------------------------------------------------
  0  ->  ~1000 m   |   5  ->  ~2 m
  1  ->  ~100 m    |   6  ->  ~1 m
  2  ->  ~30 m     |   7  ->  ~0.5 m
  3  ->  ~12 m     |   8  ->  ~0.25 m
  4b ->  ~5 m      |   9  ->  ~0.125 m
  4  ->  ~4 m      |

Requirements: GDAL (gdalwarp) must be on PATH.
Install via:  conda install -c conda-forge gdal
""",
)
parser.add_argument("input_raster",
    help="Input elevation raster (GeoTIFF, VRT, ...)")
parser.add_argument("output_folder",
    help="Output directory (will be created if absent)")
parser.add_argument("--mode", choices=["geo", "utm"], default="geo",
    help="Output projection mode  (default: geo)")
parser.add_argument("--level", dest="level", default="5",
    metavar="LEVEL",
    help="DGED product level  (default: 5)")
parser.add_argument("--zone", dest="zone", default="autodetect",
    metavar="ZONE",
    help="UTM zone e.g. 32N  (UTM mode only; auto-detect if omitted)")
parser.add_argument("--source-type", dest="source_type", default="A",
    metavar="LETTER",
    help="Source-type code  (default: A)")
parser.add_argument("--security-class", dest="sec_class", default="U",
    metavar="CLASS",
    help="Security classification  (default: U)")
parser.add_argument("--product-version", dest="prod_ver", default="01",
    metavar="VER",
    help="Product version string  (default: 01)")
parser.add_argument("--resample", dest="resample", default="auto",
    metavar="ALG",
    help="Resampling: auto|optimize|bilinear|cubic|cubicspline|average|"
         "lanczos|near (default: auto = average when downsampling, else "
         "bilinear; optimize = measure Nearest/Bilinear/Cubic against the "
         "source DEM and use whichever reconstructs it most accurately -- "
         "slower than auto, skipped in favor of Nearest automatically for "
         "angular/circular-looking sources)")
parser.add_argument("--prefilter", dest="prefilter", default="none",
    metavar="MODE",
    help="Anti-alias pre-filter applied to the SOURCE before warping: "
         "none|gaussian (default: none = pre-v0.49 behaviour, bit for bit). "
         "'gaussian' low-passes the source so terrain detail too short to "
         "survive the target post spacing is removed cleanly instead of "
         "aliasing back in as false structure. Opt-in, and worth measuring "
         "with dem2dged_validate.py on your own data -- it trades a small "
         "systematic peak/valley bias for lower aliasing error.")
parser.add_argument("--prefilter-sigma", dest="prefilter_sigma",
    default="auto", metavar="SIGMA",
    help="Gaussian sigma in SOURCE PIXELS for --prefilter gaussian "
         "(default: auto = (target/source GSD - 1)/2, the standard "
         "image-pyramid anti-aliasing rule; 0 disables, larger smooths "
         "harder). Ignored unless --prefilter gaussian.")
parser.add_argument("--source-vertical", dest="src_vert", default=None,
    metavar="EPSG",
    help="Source vertical EPSG (e.g. 5773=EGM96, 3855=EGM2008). If given and "
         "!= 3855, a real geoid transform to EGM2008 is applied; otherwise "
         "heights are assumed already EGM2008 (label only).")
parser.add_argument("--source-horizontal-accuracy", type=float, default=None,
    metavar="CE90_METRES",
    help="Independently established source horizontal CE90 for source "
         "eligibility evidence")
parser.add_argument("--source-vertical-accuracy", type=float, default=None,
    metavar="LE90_METRES",
    help="Independently established source vertical LE90 for source "
         "eligibility evidence")
parser.add_argument("--reference-dem", default=None, metavar="INDEPENDENT_DEM",
    help="Independent DEM/control surface for accuracy evaluation; never "
         "substituted by the conversion source")
parser.add_argument("--reference-horizontal-ce90", type=float, default=None,
    metavar="METRES", help="Measured product CE90 against independent control")
parser.add_argument("--reference-relative-vertical-90", type=float, default=None,
    metavar="METRES", help="Measured relative vertical accuracy at 90%%")
parser.add_argument("--org", dest="org", default="",
    metavar="CODE",
    help="Producer organisation/nation code (STANAG 1059) embedded in "
         "filenames and metadata  (default: none)")
parser.add_argument("--abs-hacc", dest="abs_hacc", default="auto",
    metavar="METRES",
    help="Absolute horizontal accuracy (CE90) written to the metadata "
         "quality report  (default: auto = DGED spec Table 5 goal value "
         "for the level)")
parser.add_argument("--abs-vacc", dest="abs_vacc", default="auto",
    metavar="METRES",
    help="Absolute vertical accuracy (LE90) written to the metadata "
         "quality report  (default: auto = DGED spec Table 6 goal value "
         "for the level)")
parser.add_argument("--lineage", dest="lineage", default="",
    metavar="TEXT",
    help="Lineage statement written to the metadata  (default: generated "
         "from the source file name and processing parameters)")
parser.add_argument("--verbose", action="store_true",
    help="Show extra output")
parser.add_argument("--debug", action="store_true",
    help="Enable debug-level logging output")
parser.add_argument("--quiet", action="store_true",
    help="Suppress info messages, only show warnings and errors")
parser.add_argument("--no-validate", dest="no_validate", action="store_true",
    help="Skip the automatic validation report generated after conversion")
parser.add_argument("--skip-sanity-check", dest="skip_sanity_check",
    action="store_true",
    help="Proceed even if the input raster's value range and filename "
         "look like non-elevation data (e.g. an aspect/direction layer)")
parser.add_argument("--terrain-qa", choices=["none", "basic", "full", "mountain"],
    default="basic", metavar="LEVEL",
    help="Terrain-fidelity QA: none|basic|full|mountain (default: basic; "
         "mountain checks >20%% slopes, peaks/valleys and +/-0.5-post phase)")
parser.add_argument("--strict-source", action="store_true",
    help="Require a CRS and explicit --source-vertical before conversion")
parser.add_argument("--allow-finer-than-source", action="store_true",
    help="Expert override: allow interpolation to a DGED level finer than "
         "the source. The compliance report will still mark source "
         "eligibility FAIL")
parser.add_argument("--compliance-profile", choices=["informational", "standard", "strict"],
    default="informational", metavar="PROFILE",
    help="Terrain QA compliance profile (default: informational)")
parser.add_argument("--version", action="version",
    version="dem2dged v%s" % dl.VERSION_DISPLAY)

# -- Dispatch -----------------------------------------------------------------

def main() -> None:
    """Main entry point for dem2dged CLI."""
    args = parser.parse_args()

    # Set up logging based on command-line flags
    if args.debug:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.WARNING
    elif args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    dem2dged_logging.setup_logging(level=log_level)
    logger = dem2dged_logging.get_logger()

    # Validate input
    if not os.path.exists(args.input_raster):
        logger.error("input raster not found: %s" % args.input_raster)
        sys.exit(1)

    # Source inspection is read-only and happens before any tile is written.
    # It is deliberately performed here, once, so GEO and UTM follow the same
    # policy and the metadata is available even if a later warp fails.
    inspection = None
    try:
        from dem2dged_terrain import (check_vertical_operation, inspect_source,
                                      write_inspection_json, write_json)
        inspection = inspect_source(args.input_raster)
        os.makedirs(args.output_folder, exist_ok=True)
        write_inspection_json(inspection,
                              os.path.join(args.output_folder, "source_inspection.json"))
        if args.strict_source:
            if not inspection.horizontal_crs:
                logger.error("strict source mode: horizontal CRS is missing")
                sys.exit(2)
            if not args.src_vert:
                logger.error("strict source mode: pass --source-vertical explicitly")
                sys.exit(2)
        if args.src_vert and str(args.src_vert) != "3855":
            vertical_check = check_vertical_operation(
                inspection.horizontal_crs, args.src_vert,
                extent=inspection.extent)
            write_json(vertical_check, os.path.join(
                args.output_folder, "vertical_operation_check.json"))
            if vertical_check["status"] != "PASS":
                logger.error(
                    "vertical conversion preflight failed: %s"
                    % vertical_check.get("reason", "required geoid operation unavailable"))
                sys.exit(2)
        from dem2dged_compliance import nominal_source_gsd_m, source_eligibility
        source_latitude = (inspection.extent[1] + inspection.extent[3]) / 2.0
        source_gsd = nominal_source_gsd_m(
            inspection.pixel_size, inspection.horizontal_crs, source_latitude)
        eligibility = source_eligibility(args.level, source_gsd)
        resolution_check = eligibility["checks"]["source_resolution"]
        if (resolution_check["status"] == "FAIL" and
                not args.allow_finer_than_source):
            logger.error(
                "source resolution %.3f m is coarser than DGED Level %s "
                "target %.3f m; DGIWG-compliant production cannot create a "
                "finer level from this source. Select a coarser level or use "
                "--allow-finer-than-source for a clearly non-compliant "
                "interpolation run."
                % (resolution_check["source_gsd_m"], args.level,
                   resolution_check["target_gsd_m"]))
            sys.exit(2)
    except Exception as e:
        if args.strict_source:
            logger.error("source inspection failed: %s" % e)
            sys.exit(2)
        logger.warning("source inspection unavailable: %s" % e)

    # Build sub-script argument list
    if args.mode == "geo":
        import dem2dged_geo as mod
        sub_args = [
            "dem2dged_geo.py",
            args.input_raster,
            args.output_folder,
            "-product_level", args.level,
            "-source_type",   args.source_type,
            "-security_class", args.sec_class,
            "-product_version", args.prod_ver,
            "-resample",       args.resample,
            "-xml_template",
                os.path.join(HERE, "DGED_GEO_TEMPLATE.xml"),
        ]
    else:
        import dem2dged_utm as mod
        sub_args = [
            "dem2dged_utm.py",
            args.input_raster,
            args.output_folder,
            "-product_level", args.level,
            "-utm_zone",      args.zone,
            "-source_type",   args.source_type,
            "-security_class", args.sec_class,
            "-product_version", args.prod_ver,
            "-resample",       args.resample,
            "-xml_template",
                os.path.join(HERE, "DGED_UTM_TEMPLATE.xml"),
        ]

    # Options shared verbatim by both dem2dged_geo.py and dem2dged_utm.py
    # (v0.28: -org / -abs_hacc / -abs_vacc / -lineage were accepted by both
    # sub-scripts since v0.27 but had no pass-through here, so they were
    # only reachable by calling dem2dged_geo.py / dem2dged_utm.py directly).
    # v0.49: pre-filter pass-through. Only appended when actually requested,
    # so the sub-command line for a default run is unchanged from v0.48.
    if args.prefilter and args.prefilter != "none":
        sub_args += ["-prefilter", args.prefilter]
        if args.prefilter_sigma != "auto":
            sub_args += ["-prefilter_sigma", args.prefilter_sigma]
    if args.src_vert:
        sub_args += ["-source_vertical", args.src_vert]
    if args.org:
        sub_args += ["-org", args.org]
    if args.abs_hacc != "auto":
        sub_args += ["-abs_hacc", args.abs_hacc]
    if args.abs_vacc != "auto":
        sub_args += ["-abs_vacc", args.abs_vacc]
    if args.lineage:
        sub_args += ["-lineage", args.lineage]
    if args.verbose:
        sub_args.append("-verbose")
    if args.skip_sanity_check:
        sub_args.append("-skip_sanity_check")

    logger.info("=" * 60)
    logger.info("dem2dged v%s  -  mode: %s   level: %s" % (dl.VERSION, args.mode.upper(), args.level))
    logger.info("input  : %s" % args.input_raster)
    logger.info("output : %s" % args.output_folder)
    logger.info("=" * 60)

    # v0.37: capture the RESOLVED resampler (dem2dged_geo.py / dem2dged_utm.py
    # now return it) rather than args.resample, which may just be "auto" or
    # "optimize" -- the actual algorithm used is only known once resolve_
    # resampler() has run inside the sub-module. See DGED_Conversion_Review.md
    # Finding 2: the validator used to always assume Bilinear.
    # v0.42: the converters now raise SystemExit when a run produced no
    # tiles at all, so a failed conversion leaves this process with a
    # non-zero status instead of quietly going on to auto-validate an
    # empty folder. SystemExit is deliberately NOT caught here -- argparse
    # and the converters both use it, and its message is already the
    # operator-facing one.
    resample_used = mod.main(sub_args)

    # Record exact source/output hashes, resolved algorithm and every material
    # operator assumption.  This manifest is evidence for reproducibility;
    # it does not make unmeasured accuracy claims.
    try:
        from dem2dged_compliance import write_conversion_manifest
        write_conversion_manifest(
            os.path.join(args.output_folder,
                         "DEM2DGED_Conversion_Manifest.json"),
            args.input_raster, args.output_folder,
            {"mode": args.mode, "level": args.level,
             "resample_requested": args.resample,
             "resample_resolved": resample_used,
             "prefilter": args.prefilter,
             "prefilter_sigma": args.prefilter_sigma,
             "source_vertical_epsg": args.src_vert,
             "source_vertical_basis": ("operator-declared" if args.src_vert
                                       else "assumed-EGM2008-label-only"),
             "source_horizontal_accuracy_90_m": args.source_horizontal_accuracy,
             "source_vertical_accuracy_90_m": args.source_vertical_accuracy,
             "metadata_absolute_horizontal_accuracy": args.abs_hacc,
             "metadata_absolute_vertical_accuracy": args.abs_vacc,
             "metadata_accuracy_basis": ("operator-supplied" if
                 args.abs_hacc != "auto" or args.abs_vacc != "auto" else
                 "DGIWG-level-goal-not-measured")})
    except Exception as e:
        logger.warning("conversion manifest could not be written: %s" % e)

    if not args.no_validate:
        _run_auto_validation(args.input_raster, args.output_folder,
                             resample=resample_used,
                             terrain_qa=args.terrain_qa,
                             compliance_profile=args.compliance_profile,
                             reference_dem=args.reference_dem,
                             source_horizontal_accuracy=args.source_horizontal_accuracy,
                             source_vertical_accuracy=args.source_vertical_accuracy,
                             reference_horizontal_ce90=args.reference_horizontal_ce90,
                             reference_relative_vertical_90=
                                 args.reference_relative_vertical_90)


def _run_auto_validation(input_raster: str, output_folder: str,
                         resample: str = None, terrain_qa: str = "basic",
                         compliance_profile: str = "informational",
                         reference_dem: str = None,
                         source_horizontal_accuracy: float = None,
                         source_vertical_accuracy: float = None,
                         reference_horizontal_ce90: float = None,
                         reference_relative_vertical_90: float = None) -> None:
    """Run the validator against the just-produced output folder and write
    both a text and an HTML report into it. Never lets a validation problem
    fail the overall conversion - conversion already succeeded by this point.

    This mirrors the same validate + report-writing pattern used by
    dem2dged_validate.py's own CLI (main()) and by dem2dged_gui.py's
    worker() -- run_validation() returns (Report, tiles), write_text_report()
    takes (report, path), and write_html_report() takes a list of dataset
    dicts with "name" / "src" / "rep" / "tiles" keys.

    ``resample``: the resampling algorithm the conversion actually used
    (v0.37, Finding 2). None falls back to run_validation()'s own default
    ("bilinear") rather than guessing.
    """
    logger = dem2dged_logging.get_logger()
    try:
        import dem2dged_validate as dv
    except Exception as e:
        # v0.42: WARNING, not INFO. This exact line is what a broken
        # validator looked like for the whole of v0.40 -- one quiet info
        # message in the middle of a successful-looking conversion, with no
        # DGED_Validation_Report.txt/.html written and nothing that reads
        # like a problem. See the v0.41 code review, finding 1.
        logger.warning("auto-validation SKIPPED -- could not import "
                       "dem2dged_validate (%s). No validation report was "
                       "written for this delivery." % e)
        return

    logger.info("=" * 60)
    logger.info("Validating output...")
    try:
        kw = {"resample": resample} if resample else {}
        rep, tiles = dv.run_validation(output_folder, src=input_raster, **kw)
        # v0.37: shared 3-tier rule (Finding 4) instead of a locally
        # re-typed 2-tier copy of it -- see dv.overall_result()'s docstring.
        logger.info("Validation: PASS=%d  WARN=%d  FAIL=%d  -> %s"
                     % (rep.n_pass, rep.n_warn, rep.n_fail,
                        dv.overall_result(rep.n_pass, rep.n_warn, rep.n_fail)))

        txt_path = os.path.join(output_folder, "DGED_Validation_Report.txt")
        html_path = os.path.join(output_folder, "DGED_Validation_Report.html")
        dv.write_text_report(rep, txt_path)

        name = os.path.basename(os.path.normpath(output_folder))
        dataset = {"name": name, "src": input_raster, "rep": rep,
                   "tiles": tiles, "resample": resample}
        dv.write_html_report([dataset], html_path)

        qa = None
        independent_qa = None
        error_budget = None
        if terrain_qa != "none":
            try:
                from dem2dged_terrain import (compliance_result,
                                               compliance_thresholds,
                                               run_terrain_qa, write_json)
                qa = run_terrain_qa(output_folder, input_raster,
                                    output_dir=os.path.join(output_folder,
                                                             "validation"),
                                    resample=resample or "bilinear",
                                    full=(terrain_qa in ("full", "mountain")),
                                    mountain=(terrain_qa == "mountain"))
                qa["compliance_profile"] = compliance_profile
                limits = compliance_thresholds(compliance_profile)
                qa["compliance"] = compliance_result(
                    rep.n_fail > 0, qa["metrics"], limits,
                    steep=qa.get("slope_bins"))
                validation_dir = os.path.join(output_folder, "validation")
                write_json(qa, os.path.join(validation_dir, "terrain_metrics.json"))
                terrain_txt = os.path.join(output_folder, "validation",
                                           "terrain_report.txt")
                if os.path.isfile(terrain_txt):
                    with open(txt_path, "a", encoding="utf-8") as f, \
                            open(terrain_txt, encoding="utf-8") as tf:
                        f.write("\n\n" + tf.read())
                logger.info("Terrain QA written: %s" %
                            os.path.join(validation_dir, "terrain_metrics.json"))
            except Exception as e:
                logger.warning("terrain QA FAILED (%s: %s)" % (type(e).__name__, e))

        if reference_dem:
            try:
                from dem2dged_terrain import run_terrain_qa
                independent_qa = run_terrain_qa(
                    output_folder, reference_dem,
                    output_dir=os.path.join(output_folder, "validation",
                                            "independent_reference"),
                    resample=resample or "bilinear",
                    full=(terrain_qa in ("full", "mountain")),
                    mountain=(terrain_qa == "mountain"),
                    comparison_type="independent_reference")
                logger.info("Independent-reference QA written")
            except Exception as e:
                logger.warning("independent-reference QA FAILED (%s: %s)" %
                               (type(e).__name__, e))

        if reference_dem:
            try:
                from dem2dged_terrain import run_error_budget_qa
                error_budget = run_error_budget_qa(
                    output_folder, input_raster, reference_dem,
                    output_dir=os.path.join(output_folder, "validation"),
                    resample=resample or "bilinear")
                logger.info("Three-part error budget written")
            except Exception as e:
                logger.warning("three-part error-budget QA FAILED (%s: %s)" %
                               (type(e).__name__, e))

        try:
            compliance = dv.write_dgiwg_compliance(
                output_folder, rep, source_path=input_raster,
                terrain_qa=qa, independent_qa=independent_qa,
                error_budget=error_budget,
                compliance_profile=compliance_profile,
                source_horizontal_accuracy=source_horizontal_accuracy,
                source_vertical_accuracy=source_vertical_accuracy,
                reference_horizontal_ce90=reference_horizontal_ce90,
                reference_relative_vertical_90=reference_relative_vertical_90)
            logger.info("DGIWG compliance evidence: %s" % compliance["overall"])
        except Exception as e:
            logger.warning("DGIWG compliance report FAILED (%s: %s)" %
                           (type(e).__name__, e))

        logger.info("Validation report written: %s" % html_path)
    except Exception as e:
        # v0.42: WARNING, and it names both reports that are now missing.
        # The conversion itself has already succeeded at this point, so this
        # still never fails the run -- but it can no longer look like
        # routine progress output.
        logger.warning("auto-validation FAILED (%s: %s). "
                       "DGED_Validation_Report.txt / .html were NOT written "
                       "for %s -- validate it manually with "
                       "'python dem2dged_validate.py \"%s\" -src \"%s\"'."
                       % (type(e).__name__, e, output_folder,
                          output_folder, input_raster))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
