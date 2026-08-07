# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.42
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
parser.add_argument("--source-vertical", dest="src_vert", default=None,
    metavar="EPSG",
    help="Source vertical EPSG (e.g. 5773=EGM96, 3855=EGM2008). If given and "
         "!= 3855, a real geoid transform to EGM2008 is applied; otherwise "
         "heights are assumed already EGM2008 (label only).")
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
    resample_used = mod.main(sub_args)

    if not args.no_validate:
        _run_auto_validation(args.input_raster, args.output_folder,
                             resample=resample_used)


def _run_auto_validation(input_raster: str, output_folder: str,
                         resample: str = None) -> None:
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
        logger.info("skipping auto-validation (could not import dem2dged_validate: %s)" % e)
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
        dataset = {"name": name, "src": input_raster, "rep": rep, "tiles": tiles}
        dv.write_html_report([dataset], html_path)

        logger.info("Validation report written: %s" % html_path)
    except Exception as e:
        logger.info("validation could not run: %s" % e)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
