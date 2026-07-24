#!/usr/bin/env python3
"""
DEM2DGED Validator Packaging Script - v0.40-beta

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON

Automates:
1. Version file generation for validator
2. Directory structure verification
3. Zip packaging into designated folder
"""

import os
import sys
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

# Configuration
# v0.28: SOURCE_DIR now derives from this script's own location instead of a
# hardcoded absolute path -- see dem2dged_package_v0.26.py for why (the
# previous hardcoded path pointed at a different, older v0.24 folder).
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_OUTPUT_DIR = os.path.dirname(SOURCE_DIR)
VERSION = "0.40"
# v0.39: beta release -- numeric VERSION stays audited, the beta qualifier
# rides in RELEASE_STAGE (see dem2dged_package.py).
RELEASE_STAGE = "beta"
VERSION_DISPLAY = f"{VERSION}-{RELEASE_STAGE}" if RELEASE_STAGE else VERSION
PACKAGE_NAME = (f"dem2dged_validate_v{VERSION}_{RELEASE_STAGE}" if RELEASE_STAGE
                else f"dem2dged_validate_v{VERSION}")
ZIP_FILENAME = f"{PACKAGE_NAME}.zip"

def create_version_file(target_dir):
    """Create VERSION.txt file for validator."""
    version_content = f"""DEM2DGED Validator Version Information
========================================

Version: {VERSION_DISPLAY}
Build Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Package: {PACKAGE_NAME}

Changes in v0.40-beta:
- Verification re-cut of v0.39-beta; no validator logic change. Re-audited
  and re-run end to end (19/19). The v0.39-beta Section H geoid fix (compare
  in the horizontal CRS only) and the source-type WARN are carried forward.

Changes in v0.39-beta:
- SECTION H GEOID FALSE-POSITIVE (found by the beta verification run on
  inland Lebanon; the most impactful fix this release). check_source()
  re-warped the source into the tiles' COMPOUND CRS (EPSG:<horiz>+3855) for
  the H/H2 comparisons, which makes GDAL apply an ellipsoidal->EGM2008 geoid
  transform to the source (~25 m over Lebanon) even though the converter's
  default vertical handling applies NO such shift to the tiles. A correct
  bilinear near-native delivery was therefore compared against a source
  baseline shifted by the local geoid height and FAILED H/H2, uniformly, by
  ~that geoid height -- for any source without an explicit vertical datum
  (SRTM and most real DEMs) in a non-trivial-geoid region. Both re-warps now
  strip the vertical and compare terrain in the tiles' HORIZONTAL CRS only.
- Source-type letter: a reserved (D/E/I/J/Q/R/S/W/Z) or unknown code in a
  tile name now raises a WARN (not a FAIL). The name still parses and the
  tile is otherwise fine, and metadata prevails over the filename per spec
  12.1, so this is advisory only. Shares dem2dged_lib.describe_source_type()
  with the converters, so the two agree.
- The v0.39 converter-side changes (data-type-aware GeoTIFF LZW predictor,
  PREDICTOR=3 for Float32 / 2 for Int16; and the UTM negative-northing clamp)
  need nothing more here -- the header check verifies COMPRESS=LZW (unchanged,
  both predictors lossless) and the name-width check already rejected the old
  negative northing.
- No change to the hard spec checks (naming, grid geometry, data type,
  NoData, CRS/EGM2008 tag, XML, elevation-range statistics, edge overlap).

Changes in v0.38:
- Report._emit() (used by every WARN/FAIL/PASS line and every section()
  header) unconditionally print()ed to the real console. On Windows with
  stdout redirected to a file under a legacy console code page (cp1252),
  the box-drawing section headers aren't encodable, so print() raised
  UnicodeEncodeError -- confirmed in practice running the real CLI end to
  end. That exception propagated up through run_validation() and made
  dem2dged.py's auto-validation try/except silently skip writing BOTH
  report files even though validation had already completed. Now falls
  back to a best-effort re-encode of just the console echo on that error;
  the report content itself (self.lines) was never affected.
- With that fixed and reports actually being written, both real
  cubic-convolution runs on the DGIWG test set FAILED Section H (global
  min/max) on a validator-side artifact, not a real defect.
  check_source()'s H/H2 checks build their own internal re-warp of the
  source using the tiles' actual resample algorithm (v0.37 Finding 2) as a
  like-for-like comparison baseline -- but that re-warp was never clamped
  the way the real delivered tiles are (v0.37 Finding 3). A correctly-
  clamped tile (e.g. ACAIPGTM: 0.00..255.00 m) was compared against a
  still-overshooting baseline (-18.33..274.21 m) and flagged as an
  18-19 m "defect" that was really just "clamped vs unclamped".
  check_source() now computes the same clamp range the converters use and
  applies it to both H's global-stats re-warp and H2's per-window re-warp.

Changes in v0.37:
- Fixes for Findings 2 and 4 of DGED_Conversion_Review.md (full description
  in VERSION.txt / dem2dged_package.py -- Findings 1 and 3 are converter-
  side, this module is unchanged for those):
  * Finding 2: sections H/H2 (source comparison) re-warped the source DEM
    for comparison as Bilinear UNCONDITIONALLY, regardless of what the
    tiles being validated were actually produced with, despite a code
    comment claiming the two matched -- so Nearest Neighbor / Cubic runs
    partly failed on "how different is this from Bilinear", not "how wrong
    is this tile". check_source() and run_validation() now take a
    ``resample`` argument (default "bilinear", the old hardcoded value, so
    every existing caller keeps working); dem2dged.py and dem2dged_gui.py
    now pass the actual algorithm used. New CLI flag -resample/--resample
    (default bilinear) for validating an existing delivery standalone.
  * Finding 4: the "RESULT:" line in the text report used a 2-tier
    PASS/FAIL rule (ignoring warnings) while the HTML per-dataset badge
    used a 3-tier FAIL > WARN > PASS rule -- identical PASS=/WARN=/FAIL=
    counts for one run could read "PASS" in the .txt report and show a
    "WARN" badge in the HTML report for that same run. Both (and every
    other PASS/WARN/FAIL label dem2dged_gui.py computes) now call one new
    shared function, overall_result(), so this cannot drift apart again.
  * Recommendation #5 (optional polish): H2's three sample windows are now
    coverage-aware -- a cheap, heavily decimated read of the tile mosaic
    nudges a fixed window position to the nearest one that actually has
    data, instead of printing a routine "no overlapping valid data" WARN
    whenever a delivery's real footprint doesn't fill its bounding box
    evenly.

Changes in v0.36:
- Version bump alongside two converter-side features (see dem2dged_
  package.py / VERSION.txt for the full description): a pre-flight
  elevation sanity check that catches aspect/direction/curvature rasters
  fed in by mistake before any tiles are produced, and a new
  "-resample optimize" mode that measures Nearest/Bilinear/Cubic against
  each source DEM and picks whichever is most accurate. This module
  (dem2dged_validate.py) is unchanged -- neither feature runs after
  conversion, so there is nothing new for the validator to check.

Changes in v0.35:
- This module's docstring is now a raw string, fixing a
  "SyntaxWarning: invalid escape sequence '\\d'" on Python 3.12+ (the
  changelog prose contained literal "\\d+" / "\\d{{1,7}}" describing
  UTM_RE in a plain triple-quoted string). Cosmetic only -- GEO_RE / UTM_RE
  were already correctly raw-stringed and unaffected.

Changes in v0.34:
- UTM filename field WIDTHS are now checked (new check under B). Spec 12.1
  defines the coordinate subfields as fixed-width and zero-padded, but
  UTM_RE matched "\\d+" so any width passed -- and the converter was
  emitting short fields for every northing below 1 000 000 m. Converter
  and validator were consistently wrong together. The widths now come from
  dem2dged_lib.utm_name_field_widths(), the same function the converter
  formats with, so the two cannot disagree.
- Every option now also accepts the double-dash spelling: "--html-report"
  was documented here but argparse rejected it outright as unrecognised.
- Renamed from dem2dged_validate_package_v0.26.py (the "v0.26" in the
  filename had been stale since v0.28).

Changes in v0.32:
- Version bump (validator logic unchanged). The "Version: 0.29" header
  comment in dem2dged.py, dem2dged_geo.py and dem2dged_utm.py, and
  dem2dged_gui.py's APP_VERSION fallback, had drifted behind
  dem2dged_lib.py (the single source of truth) during the v0.30/v0.31
  validator-only releases; all four now read 0.32 again
- dem2dged_package_v0.26.py (the whole-tool zip) now excludes build/dist
  output, caches, and prior release zips instead of bundling the entire
  project folder verbatim

Changes in v0.31:
- Two more validator false-positive fixes, found auditing a real conversion
  run:
  1) "Name says origin X but georef is Y" (check D) compared the raw
     raster corner against the nominal tile origin with a half-pixel
     tolerance, but the v0.27 half-post warp extent deliberately puts the
     corner half a pixel before the origin -- exactly on that tolerance
     boundary -- so it failed every correctly generated tile. Now compares
     the pixel CENTER with a tiny fractional-pixel tolerance instead.
  2) "Unreplaced {{{{placeholder}}}}" (check E) was a bare "{{{{" substring
     search that matched the DGED template's own header comment describing
     the templating mechanism, failing every tile regardless of whether
     real placeholders were substituted. Now matches real {{{{KEY}}}}
     placeholder syntax only.

Changes in v0.30:
- Fixed a validator false positive in the file-pairing check (A):
  TABLE_OF_CONTENTS.xml and <product>_COLLECTION.xml are delivery-level
  metadata (spec 12.1 / 6.6), not per-tile sidecars, so they never had a
  matching .tif -- the check now recognises both by the same name test
  write_toc_file() already uses, instead of flagging them as "missing .tif"

Changes in v0.29:
- Version bump alongside the QUICKSTART.html rewrite (validator logic
  unchanged)

Changes in v0.28:
- Data-type check is now level-aware (Int16 required and PASSES for levels
  0-2, Float32 for level 3+) instead of hard-failing every Int16 tile
- Filename patterns accept the current level 0-3 naming (no "Gt<letter>"
  segment) plus the pre-v0.27 legacy form and an optional org-code segment
- Hand-copied fallback DGED tables removed (they had already drifted out of
  sync for GEO levels 8-9); a missing dem2dged_lib.py now fails loudly
  instead of validating against stale numbers

Changes in v0.26:
- Version bump alongside the GUI window-layout fix (validator logic unchanged)

Changes in v0.25:
- Version bump for the tool-wide bug-fix pass (validator logic unchanged)
- Packaging script now points at the correct source folder

Carried over from v0.24:
- Detailed per-tile PASS/WARN/FAIL criteria table (Filename, GSD, Bounds,
  NoData, CRS/Vertical, Data Type, Metadata, Overall) added to the HTML
  validation report

Usage:
python dem2dged_validate.py <tile_folder> [--html-report output.html]

The validator checks:
- GeoTIFF structure and compression
- Projection and coordinate systems
- Tile naming conventions
- ISO 19115-2 metadata compliance
- EGM2008 vertical datum definition
- Elevation data range and statistics

Exit codes:
- 0: All checks passed
- 1: One or more validation failures

Installation:
1. Extract {ZIP_FILENAME}
2. Run rebuild_validate_exe.bat to compile
3. Execute dem2dged_validate.exe when ready
"""

    version_file = os.path.join(target_dir, "VALIDATOR_VERSION.txt")
    with open(version_file, "w") as f:
        f.write(version_content)
    print(f"✓ Created VALIDATOR_VERSION.txt")
    return version_file

def verify_source():
    """Verify source directory exists and contains validator files."""
    if not os.path.isdir(SOURCE_DIR):
        raise FileNotFoundError(f"Source directory not found: {SOURCE_DIR}")

    required_files = [
        "dem2dged_validate.py",
        "dem2dged_lib.py",
        "rebuild_validate_exe.bat",
    ]

    for fname in required_files:
        fpath = os.path.join(SOURCE_DIR, fname)
        if not os.path.isfile(fpath):
            raise FileNotFoundError(f"Missing required file: {fname}")

    print(f"✓ Source directory verified")
    return True

def create_package_zip():
    """Create zip package from source directory."""
    zip_path = os.path.join(PACKAGE_OUTPUT_DIR, ZIP_FILENAME)

    # Remove old zip if exists
    if os.path.exists(zip_path):
        os.remove(zip_path)
        print(f"✓ Removed old package")

    # Create zip with only validator-related files
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        files_to_include = [
            "dem2dged_validate.py",
            "dem2dged_lib.py",
            "rebuild_validate_exe.bat",
            "VALIDATOR_VERSION.txt",
            "README.md",
            "DEM2DGED_User_Manual.docx"
        ]

        for file in files_to_include:
            file_path = os.path.join(SOURCE_DIR, file)
            if os.path.isfile(file_path):
                arcname = os.path.relpath(file_path, SOURCE_DIR)
                zf.write(file_path, os.path.join(PACKAGE_NAME, arcname))

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"✓ Created {ZIP_FILENAME} ({size_mb:.2f} MB)")
    return zip_path

def main():
    print(f"\n{'='*60}")
    print(f"DEM2DGED Validator v{VERSION_DISPLAY} - Automated Packaging")
    print(f"{'='*60}\n")

    try:
        # Step 1: Verify source
        print("[1/4] Verifying source directory...")
        verify_source()

        # Step 2: Create version file
        print("\n[2/4] Creating validator version file...")
        create_version_file(SOURCE_DIR)

        # Step 3: Create package
        print("\n[3/4] Creating validator package...")
        zip_path = create_package_zip()

        # Step 4: Summary
        print("\n[4/4] Packaging complete!\n")
        print(f"{'='*60}")
        print(f"Package Location: {zip_path}")
        print(f"Package Name: {ZIP_FILENAME}")
        print(f"Version: {VERSION_DISPLAY}")
        print(f"{'='*60}\n")

        print("Next Steps:")
        print("1. Extract the zip file")
        print("2. Run rebuild_validate_exe.bat to compile")
        print("3. Test dem2dged_validate.exe with sample tiles\n")

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
