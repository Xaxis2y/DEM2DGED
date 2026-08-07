# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

#!/usr/bin/env python3


import os
import sys
import zipfile
from datetime import datetime

# Configuration
# v0.28: SOURCE_DIR now derives from this script's own location instead of a
# hardcoded absolute path. The previous hardcoded path
# (C:\Users\Son\Documents\DEM2DGED\dem2dged_v0.24) pointed at a different,
# older folder than wherever this script actually lives -- running it as
# shipped would silently package stale v0.24 files instead of the current
# ones. Deriving it from __file__ is correct wherever the project folder
# lives and can't go stale again on the next rename/move.
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_OUTPUT_DIR = os.path.dirname(SOURCE_DIR)
VERSION = "0.42"
# v0.40: release. VERSION stays a bare MAJOR.MINOR (the value the whole
# tool and audit_pure.py key off); the qualifier rides in RELEASE_STAGE
# so the zip/name reads "dem2dged_v0.40" and VERSION.txt shows
# "0.41", without changing the audited numeric version.
RELEASE_STAGE = ""
VERSION_DISPLAY = f"{VERSION}-{RELEASE_STAGE}" if RELEASE_STAGE else VERSION
PACKAGE_NAME = (f"dem2dged_v{VERSION}_{RELEASE_STAGE}" if RELEASE_STAGE
                else f"dem2dged_v{VERSION}")
ZIP_FILENAME = f"{PACKAGE_NAME}.zip"

def create_version_file(target_dir):
    """Create VERSION.txt file in the target directory."""
    version_content = f"""DEM2DGED Version Information
============================

Version: {VERSION_DISPLAY}
Build Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Package: {PACKAGE_NAME}

Changes in v0.42:
- Release-readiness review of the v0.41 package found it was not actually
  ready to ship, independent of what CODE_REVIEW_v0.41.md claimed: the
  tests/ directory documented in MANIFEST.md (five files, described as
  part of "the source release") did not exist anywhere in the release
  folder, so pytest could not run at all ("file or directory not found:
  tests"). Root cause: this packaging script's own EXCLUDE_DIRS excluded
  "tests" (listed twice, a copy-paste duplicate) from the source zip,
  directly contradicting MANIFEST.md's definition of the release contents
  and its "run pytest -q after unzipping" instructions. "tests" is no
  longer excluded.
- The validator-only bundle (dem2dged_validate_package.py) never included
  LICENSE, despite MANIFEST.md saying it does -- a real gap for a
  GPL-2.0-or-later project. LICENSE is now one of the files copied into
  that bundle.
- lu49gpd00.tmp, a stray 311 KB scratch file (actually a PDF wearing a
  .tmp extension), sat in the project root and was not caught by this
  script's EXCLUDE_FILE_SUFFIXES -- flagged as an open item in
  CODE_REVIEW_v0.41.md and left unresolved there. ".tmp"/".log"/".bak"
  are now excluded.
- dem2dged_anaconda_environment.py's dependency-install step called
  "pip install -y ..."; pip has no -y flag and rejects it outright
  (confirmed by running it directly), so the step silently installed
  nothing while the script still reported success. Flag removed.
- README.md's "What's in this folder" table was missing its header
  separator row and did not render as a table. Fixed.
- No functional change to the converters, validator logic, DGED tables,
  tile geometry, filenames, or metadata -- this release is packaging and
  documentation only. A v0.41 delivery does not need regenerating.

Changes in v0.41:
- REPAIR RELEASE for v0.40, which did not work as shipped. Full findings
  and evidence in CODE_REVIEW_v0.41.md; summary:
  * BLOCKER: dem2dged_validate.py did not byte-compile -- an entire block
    was missing between the end of the module docstring and the body of
    overall_result() (the docstring's closing quotes, every import, the
    NODATA/ELEV_MIN_SANE/ELEV_MAX_SANE constants, _STATUS_ORDER, the
    GEO_RE/UTM_RE filename patterns, and the function definition line
    itself). Every consumer swallowed the failure silently: dem2dged.py's
    auto-validation logged one line and wrote no report, the GUI's
    "Validate after conversion" checkbox was just disabled, audit_pure.py
    couldn't run at all, and dem2dged_validate.exe couldn't be built.
    Restored and re-verified against every product level, both
    hemispheres, all UTM zone forms, and the pre-v0.34/pre-v0.27 legacy
    name forms.
  * The version-consistency self-audit (audit_pure.py section 7) was
    structurally incapable of passing: its pattern required "Version:" in
    column 0, which cannot occur in a .py file outside a string, so it
    silently reported all seven modules as version None. Fixed pattern;
    the "clean version audit" claimed for v0.40 was not real.
  * tests/ did not exist despite pytest.ini pointing at it; rebuilt as
    five files (185 unit tests + 22 GDAL integration tests).
  * A corrupt tile, or an unreadable -src source DEM, crashed the entire
    validation run with an AttributeError instead of failing that one
    item; both now a clean FAIL.
  * GDAL exception handling depended on which entry point launched the
    process (CLI vs GUI), so identical library code took two different
    error paths. Now pinned process-wide in dem2dged_lib.py via a shared
    gdal_open() helper.
  * Housekeeping: unused imports/locals removed (pyflakes clean
    project-wide), 469 MB of stale build/dist/__pycache__ removed,
    MANIFEST.md rewritten to match actual contents.
- No change to the DGED tables, tile grid geometry, naming, or metadata --
  a v0.39/v0.40 delivery does not need regenerating.

Changes in v0.40:
- Verification re-cut of v0.39. A second review pass over the extracted
  package: all modules byte-compile, the version-consistency self-audit is
  clean, and the end-to-end verification harness passes 19/19 (GEO/UTM at all
  data types and resamplers, equatorial zero-padding + UTM northing clamp,
  high-latitude GEO longitude-zone factors x1.5/x2/x3, southern hemisphere, a
  real EGM96->EGM2008 transform, the aspect sanity-check, and the data-type-
  aware predictor). No functional change from v0.39 -- the five
  v0.39 fixes are carried forward and re-verified. QUICKSTART.html and
  the user manual refreshed to v0.40.

Changes in v0.39:
- First public beta, cut after a full-project review pass (logic audit,
  DGIWG 250 Ed. 1.2.1 spec cross-check, and an end-to-end real-GDAL test run
  on operator-supplied DEMs -- 19/19 verification steps pass). Five low-risk
  changes; three from the static review, two surfaced by the test run:
  * GeoTIFF LZW PREDICTOR is now data-type aware. Every tile was written with
    PREDICTOR=2 (TIFF horizontal differencing), which is only defined for
    integer samples. Float32 tiles (all UTM levels and GEO level 3+) now use
    PREDICTOR=3, the IEEE floating-point predictor -- more format-correct and
    materially smaller on real terrain. Int16 tiles (GEO levels 0-2) keep
    PREDICTOR=2. Still LZW-lossless, so still spec 13.1 compliant. Shared
    dem2dged_lib.predictor_for_type() drives both CLI converters and the GUI.
    THIS CHANGES TILE BYTES: re-run the conversion to regenerate deliveries.
  * Source-type letter sanity. Spec 12.1 defines the valid source codes and
    reserves D/E/I/J/Q/R/S/W/Z; a reserved/unknown code now raises a
    non-blocking WARNING in the CLI converters and the GUI, and a WARN (not a
    FAIL) in the validator. The default "A" stays silent.
  * dem2dged_logging.ColoredFormatter never actually applied its intended
    "LEVELNAME: message" console format (the format was assigned to
    formatter._fmt after construction, but logging renders through
    self._style); the unified dem2dged.py CLI now prints the level prefix.
  * UTM negative-northing clamp. An equatorial DEM's extent dips just below
    the equator (routine for a point-registered source like SRTM, whose edge
    overhangs by half a post), so a northern UTM zone emitted a tile at a
    NEGATIVE northing -- a non-spec name like "...32N-025..." that the
    validator rejected. The UTM tile grid (dem2dged_utm.py and the GUI) now
    clamps to the valid [0, 10 000 000] m northing band, warning if it drops
    a row. (spec 6.3.1)
  * Section H geoid false-positive (validator, the most impactful find).
    check_source() re-warped the source into the tiles' COMPOUND CRS
    (EPSG:<horiz>+3855), which makes GDAL apply an ellipsoidal->EGM2008 geoid
    shift to the source (~25 m over Lebanon) even though the default
    conversion never shifts the tiles that way -- so a correct delivery was
    flagged ~25 m wrong, uniformly, for any source without an explicit
    vertical datum (SRTM and most real DEMs) in a non-trivial-geoid region.
    Both H/H2 re-warps now strip the vertical and compare terrain in the
    horizontal CRS only.
- No change to the DGED tables, tile grid geometry, naming, or metadata. The
  spec cross-check found the existing behaviour compliant; the two validator
  changes touch an advisory warning and the Section H source-accuracy
  comparison, not any hard spec-compliance check.

Changes in v0.38:
- Two bugs found by actually running the real CLI end to end (via
  verify_v037.bat) with real GDAL, plus the real pytest suite -- the first
  time either had run outside manual code review:
  * dem2dged_validate.py's Report._emit() unconditionally print()ed every
    report line (including box-drawing section headers) to the real
    console. On Windows with stdout redirected to a file under a legacy
    console code page (cp1252), that print() raised UnicodeEncodeError,
    which propagated up through run_validation() into dem2dged.py's
    auto-validation try/except -- silently skipping BOTH
    DGED_Validation_Report.txt/.html even though validation had already
    completed successfully. Now falls back to a best-effort re-encode of
    just the console echo; the report content itself was never affected.
  * tests/conftest.py's output_dir fixture always resolved to the same
    session-wide "output" subdirectory for every test that requested it,
    so one test's leftover tiles were still present when the next globbed
    *.tif expecting only its own -- e.g. test_utm_names_are_zero_padded
    failing on a leftover GEO-named file from an earlier GEO test, not on
    anything wrong with UTM naming. Now a fresh tempfile.mkdtemp() per
    test.
  * Independently re-verified Findings 1 and 3 directly against the real
    GDAL-produced output tiles (not just a reimplementation testbed):
    shared-edge max|diff| = 0.0000 m on the real-terrain dataset across
    all three resampling methods, and cubic-convolution tiles' min/max now
    land exactly on the two test rasters' true source ranges (0..255 and
    6..255) instead of overshooting to -41..285 / -44..313.
  * With reports actually being written again, both real cubic-convolution
    runs FAILED Section H (global min/max) on a validator-side artifact:
    check_source()'s internal source re-warp (used as a like-for-like
    comparison baseline, per the v0.37 Finding 2 fix) was never clamped
    the way the real delivered tiles are (v0.37 Finding 3) -- so a
    correctly-clamped tile (e.g. ACAIPGTM: 0.00..255.00 m) was compared
    against a still-overshooting baseline (-18.33..274.21 m) and flagged
    as an 18-19 m "defect" that was really just "clamped vs unclamped".
    check_source() now computes the same clamp range the converters use
    and applies it to both H's and H2's internal re-warps.

Changes in v0.37:
- All five findings of DGED_Conversion_Review.md (an independent audit of a
  9-run / 42-tile DGIWG test-data conversion batch) addressed, in the CLI
  converters (dem2dged_geo.py / dem2dged_utm.py), the GUI
  (dem2dged_gui.py), and the validator (dem2dged_validate.py):
  * Finding 1 (real defect, real-terrain delivery): adjacent DGED tiles are
    warped by independent gdalwarp calls, so nothing guaranteed they agreed
    on the single post row/column the spec requires them to share --
    confirmed as a 1.6 m seam on a 5 m-post real-terrain test tile pair
    (Nearest Neighbor; 12-13 cm for Bilinear/Cubic on the same pair, from
    the same root cause). Two changes: warp extents are now rounded to a
    fixed coordinate precision (dem2dged_lib.tile_warp_extent(), and the
    matching inline math in both converters), and a new post-warp pass,
    dem2dged_lib.reconcile_tile_edges(), copies each tile's shared edge
    pixels onto its neighbour so the two files are bit-identical along
    that edge regardless of what either individual gdalwarp call did
    internally -- verified against the actual DGIWG test tiles that showed
    the seam, for all three resampling methods.
  * Finding 2 (validator bug): sections H/H2 of the validator re-warp the
    source DEM for comparison, always as Bilinear regardless of what the
    tiles were actually made with, despite a code comment claiming
    otherwise -- so Nearest Neighbor / Cubic runs were partly failing on
    "how different is this from Bilinear", not "how wrong is this tile".
    The actual resampling algorithm is now threaded through from the
    converters (which return it) and the GUI down into
    dem2dged_validate.check_source()/run_validation(), with a new
    dem2dged_validate CLI flag -resample/--resample for validating an
    existing delivery standalone.
  * Finding 3 (real, expected, now handled): cubic-family resamplers
    (cubic, cubicspline, lanczos) can overshoot the source's true min/max
    at sharp discontinuities -- confirmed on two 8-bit, hard-step-edge
    DGIWG test rasters, with Cubic Convolution tiles as low as -44 m
    against a true source minimum of 0 m and 6 m. Tiles produced with one
    of these resamplers are now clamped back into the source's exact
    min/max range right after warping (dem2dged_lib.clamp_tile_to_range()
    with dem2dged_lib.OVERSHOOT_PRONE_RESAMPLERS), so an explicit
    -resample cubic (etc.) on choppy data can no longer silently ship a
    physically impossible elevation. Resamplers dem2dged picks
    automatically (average, bilinear) never overshoot and are unaffected.
  * Finding 4 (cosmetic, but confusing): the text report's "RESULT:" line
    used a 2-tier PASS/FAIL rule (ignoring warnings) while the HTML
    per-dataset badge and the GUI's Resampling Comparison badge each used
    a 3-tier FAIL > WARN > PASS rule -- so identical PASS=/WARN=/FAIL=
    counts for the same run could read "PASS" in one report and "WARN" in
    another. All four places (plus two GUI/CLI log lines using the same
    ad hoc 2-tier check) now call one shared function,
    dem2dged_validate.overall_result(), so this cannot drift apart again.
  * Recommendation #5 (optional polish): the validator's H2 sample-window
    placement is now coverage-aware -- a cheap, heavily decimated read of
    the tile mosaic nudges a fixed window position to the nearest one that
    actually has data, instead of printing a routine "no overlapping valid
    data" WARN whenever a delivery's real footprint doesn't fill its
    bounding box evenly.

Changes in v0.36:
- New pre-flight elevation sanity check (dem2dged_lib.sanity_check_
  elevation_source()), prompted by a real bug report: an aspect/direction
  raster fed into the tool as if it were elevation, producing huge and
  confusing RMSE/tolerance failures because the tool had no way to know the
  numbers it was resampling weren't heights. It inspects the source's
  filename and its actual value range for signs of a terrain DERIVATIVE
  rather than elevation, blocking by default when both signals agree (a
  filename hint AND a 0-360-degree-like range) and warning on either signal
  alone. New CLI flag -skip_sanity_check / --skip-sanity-check and GUI
  checkbox "Skip elevation sanity check" override it when the input is
  genuinely fine.
- New "-resample optimize" mode (dem2dged_lib.resolve_resampler()), the
  answer to "how do I automatically get the most accurate conversion":
  instead of -resample auto's fixed source/target-GSD-ratio rule of thumb,
  it measures Nearest / Bilinear / Cubic against the source DEM itself
  (the same hold-out cross-validation the Resampling Comparison Test uses,
  but without writing any tiles or a report) and uses whichever
  reconstructs it most accurately for that specific file. New GUI dropdown
  entry "Optimize". Ties into the sanity check above: for a source flagged
  as angular/circular data, RMSE is not a meaningful accuracy measure
  across the 0/360 wraparound seam, so optimize mode skips the comparison
  and uses Nearest Neighbor directly instead of ranking methods by a
  number that would not mean anything.

Changes in v0.35:
- dem2dged_validate.py's module docstring is now a raw string. It held its
  changelog prose in a plain triple-quoted string containing literal
  "\\d+" / "\\d{{1,7}}" describing UTM_RE, which is a deprecated escape
  sequence in Python and prints "SyntaxWarning: invalid escape sequence
  '\\d'" on 3.12+. Cosmetic only: GEO_RE / UTM_RE themselves were already
  correctly built as raw strings and unaffected.
- dem2dged_compare.py's HTML Resampling Comparison Report used RMSE / MAE /
  Bias / Overshoot without spelling any of them out. Column headers now
  carry a title= tooltip with the full definition, and the closing note
  gains a "Terms" glossary paragraph.

Changes in v0.34:
- Full-project audit pass (see CODE_REVIEW_v0.34.md). Ten fixes, of which
  three change behaviour:
  * SPEC: UTM tile filenames are now zero-padded to the spec 12.1 field
    widths (nnnn/eee for levels 4b-6, nnnnmmm/eeemmm for levels 7-9).
    Northings below 1 000 000 m -- anywhere within ~9 degrees of the
    equator -- previously produced short, non-spec fields, and the
    validator's "\\d+" pattern accepted them. THIS CHANGES FILENAMES:
    re-run the conversion to regenerate affected deliveries.
  * The converters no longer emit one row and column of pure-NoData tiles
    past the data (the tile loop bound was floor()+1, now ceil()).
  * dem2dged_gui.py's stale pre-v0.27 fallback DGED tables are deleted --
    they still described levels 8/9 as 1-minute "G" tiles, which breaks
    post alignment in latitude zones 2 and 4.
- Report-only / robustness: validator now checks UTM field widths and
  accepts double-dash flags; the resampling comparison writes its scratch
  raster to a private temp dir instead of the delivery folder; GUI gains
  Organisation / Abs. H accuracy / Abs. V accuracy / Lineage fields to
  match the CLI; version consistency is now enforced by tests.
- This script was renamed from dem2dged_package_v0.26.py: it has been
  version-agnostic since v0.28 (SOURCE_DIR derives from __file__), so the
  frozen "v0.26" in the filename was stale and misleading.

Changes in v0.33:
- GUI "Resampling Method" dropdown (default Auto; manual Nearest Neighbor /
  Bilinear Interpolation / Cubic Convolution) routed through the same
  pick_resampler override path as the CLI's -resample flag
- New "Resampling Comparison Test": checkboxes run 1-3 methods side-by-side
  into per-file test folders (test_1_nearest_neighbor /
  test_2_bilinear_interpolation / test_3_cubic_convolution)
- New module dem2dged_compare.py: round-trip accuracy analysis per method
  (RMSE / MAE / bias / std-dev / max abs error / range overshoot) and a
  ranked HTML table (DGED_Resampling_Comparison_Report.html) marking the
  most accurate method per input file

Changes in v0.32:
- Housekeeping release, no functional/algorithmic changes. The "Version:
  0.29" header comment in dem2dged.py, dem2dged_geo.py and dem2dged_utm.py,
  and dem2dged_gui.py's APP_VERSION fallback, had drifted behind
  dem2dged_lib.py (the single source of truth) during the v0.30/v0.31
  validator-only releases; all four now read 0.32 again
- This packaging script now excludes build/dist output, __pycache__,
  .pytest_cache, and prior release zips from the package instead of
  walking the entire project folder with no exclusions

Changes in v0.31:
- Two more validator false-positive fixes, found auditing a real conversion
  run (report-only; no changes to the converters or to what gets written to
  disk) -- see VALIDATOR_VERSION.txt / dem2dged_lib.py for details

Changes in v0.30:
- Fixed a validator false positive in the file-pairing check (A):
  TABLE_OF_CONTENTS.xml and <product>_COLLECTION.xml are delivery-level
  metadata, not per-tile sidecars, so they were wrongly flagged as
  "missing .tif" on every delivery that included them

Changes in v0.29:
- QUICKSTART.html rewritten for v0.27/v0.28 feature parity: documents
  --org / --abs-hacc / --abs-vacc / --lineage, the GUI Source vertical
  field, level-aware Int16/Float32 data types, the level 0-3 short
  filename form, and automatic in-process validation
- Fixed a stale "v0.15" label and an incorrect GPL-3.0 mention (project is
  GPL-2.0-or-later) in QUICKSTART.html; genericised hardcoded Windows paths
- No functional code changes

Changes in v0.28:
- Fixed a truncated DGED_UTM_TEMPLATE.xml that made every UTM tile's XML
  sidecar invalid (not well-formed) since v0.27
- GUI now calls the same shared conversion logic as the CLI converters
  instead of an independently-maintained copy that had drifted out of spec:
  fixes a half-post pixel misregistration, wrong data type below level 3,
  a stale filename form for levels 0-3, and mostly-blank XML sidecars in
  every GUI-produced tile
- GUI can now perform a real EGM2008 vertical-datum transform (-source-
  vertical), previously accepted by the code but unreachable from the UI
- Validator brought back in sync with the v0.27 converter changes: data-type
  check is level-aware (Int16 for levels 0-2), filename patterns accept the
  current level 0-3 naming, hand-copied fallback tables removed
- dem2dged.py (unified CLI) gained --org / --abs-hacc / --abs-vacc /
  --lineage, previously only reachable via the mode-specific scripts
- Version strings and this packaging script's source path resynchronised
  across the project

Changes in v0.26:
- GUI window-layout fix: the Convert / Stop buttons and progress bar are
  pinned to the bottom of the window (always visible), the rest of the form
  scrolls, and the window opens no larger than the screen work area

Changes in v0.25:
- GUI now shows a completion dialog and reports stopped/error runs instead
  of silently discarding them
- GUI extent reprojection uses all four corners (fixes possible edge-tile
  under-coverage on oblique transforms)
- Packaging scripts now point at the correct source folder

Carried over from v0.24:
- Auto-detect source DEM resolution and auto-suggest a matching product
  level in the GUI, with a warning when the selected level is finer than
  the source (Feature #1)
- Detailed per-tile PASS/WARN/FAIL criteria table in the HTML validation
  report (Feature #2)

Installation:
1. Extract {ZIP_FILENAME}
2. Run rebuild_exe.bat to compile
3. Execute dem2dged.exe when ready
"""

    version_file = os.path.join(target_dir, "VERSION.txt")
    with open(version_file, "w") as f:
        f.write(version_content)
    print(f"✓ Created VERSION.txt")
    return version_file

def verify_source():
    """Verify source directory exists and contains key files."""
    if not os.path.isdir(SOURCE_DIR):
        raise FileNotFoundError(f"Source directory not found: {SOURCE_DIR}")

    required_files = [
        "dem2dged_gui.py",
        "dem2dged_lib.py",
        "rebuild_exe.bat",
    ]

    for fname in required_files:
        fpath = os.path.join(SOURCE_DIR, fname)
        if not os.path.isfile(fpath):
            raise FileNotFoundError(f"Missing required file: {fname}")

    print(f"✓ Source directory verified ({len(os.listdir(SOURCE_DIR))} items)")
    return True

# v0.32: create_package_zip() used to os.walk(SOURCE_DIR) with no exclusions
# at all, so every release zip also bundled PyInstaller's build/ and dist/
# output (including the compiled .exe files), __pycache__, .pytest_cache,
# and any earlier release zips already sitting in the project folder --
# each new package nested every previous one inside it. These are the
# directories and file patterns that don't belong in a source/docs release
# package; keep this list in sync with what actually accumulates in the
# project folder between releases.
# v0.35: "DGED Loader" added, a standalone ArcGIS Pro toolbox that loads
# DEM2DGED's *.tif output into a map (a Basic-license workaround for Add
# Rasters To Mosaic Dataset). It lives in this same project folder for
# convenience but isn't part of the dem2dged source release -- it has its
# own VERSION.txt/README.md and its own zip (DGED_Loader_v*.zip, already
# caught by EXCLUDE_FILE_SUFFIXES below). Without this entry it would get
# walked and bundled into dem2dged_v{VERSION}.zip like any other subfolder.
# v0.39: "DEM" (operator-supplied source DEM data placed in the tool folder
# for testing -- can be gigabytes) and any "output*" conversion folders are
# excluded: neither is part of the source/docs release, and the DEM data in
# particular must never be bundled into the shipped zip.
# v0.42: "tests" (appearing twice, a copy-paste duplicate) used to be
# excluded here too, which silently contradicted MANIFEST.md -- it lists
# tests/conftest.py, test_lib.py, test_converters.py, test_validator.py and
# tests/README.md as five of the "52 files in the source release", and the
# same MANIFEST's "Quick verification after unzipping" section tells the
# user to run `pytest -q` immediately after extracting the zip. With "tests"
# excluded, that zip never contained a tests/ directory and pytest would
# fail immediately with "file or directory not found: tests" on a real
# release build -- caught during the v0.41 -> v0.42 readiness review because
# the tests/ folder was found missing from the working release directory
# itself. "tests" is intentionally NOT in this set any more: the source
# release is defined (by MANIFEST.md) to include it.
EXCLUDE_DIRS = {"build", "dist", "__pycache__", ".pytest_cache", "_v027_sync",
                 "DGED Loader", "ArcGIS_PRO_QA_toolbox", "DEM",
                 "_verify_pages"}
EXCLUDE_DIR_PREFIXES = ("dem2dged_validate_v",   # unzipped staging snapshots
                        "output")                # output/, output_v037/, ...
# v0.42: ".tmp" added. A stray 311 KB scratch file (lu49gpd00.tmp -- in
# practice a PDF wearing a .tmp extension) was found sitting in the project
# root during the v0.41 -> v0.42 review and would have been bundled into
# every release zip, since only the four suffixes below were ever excluded.
# ".log"/".bak" added at the same time for the same reason: neither belongs
# in a source/docs release and both are the kind of file that accumulates
# unnoticed in a working folder between releases.
EXCLUDE_FILE_SUFFIXES = (".zip", ".pdf", ".jpg", ".jpeg", ".tmp", ".log",
                          ".bak")
# v0.36: note_and_issue.md is a session diagnostic note (written for one
# specific bug investigation, not maintained release documentation like
# README.md/CODE_REVIEW_*.md) -- it doesn't help a user run, build, test, or
# understand the tool, so it doesn't belong in the release zip any more than
# the old user-manual draft below does.
EXCLUDE_FILES = {"DEM2DGED_User_Manual_old.docx", "note_and_issue.md"}


def create_package_zip():
    """Create zip package from source directory."""
    zip_path = os.path.join(PACKAGE_OUTPUT_DIR, ZIP_FILENAME)

    # Remove old zip if exists
    if os.path.exists(zip_path):
        os.remove(zip_path)
        print(f"✓ Removed old package")

    # Create zip
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(SOURCE_DIR):
            # Prune excluded directories in place so os.walk doesn't descend
            # into them at all (build artefacts, caches, old staging folders).
            dirs[:] = sorted(
                d for d in dirs
                if d not in EXCLUDE_DIRS and not d.startswith(EXCLUDE_DIR_PREFIXES)
            )
            for file in files:
                if (file in EXCLUDE_FILES or file.endswith(EXCLUDE_FILE_SUFFIXES)
                        or file.startswith(".~lock") or file.startswith("~$")):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, SOURCE_DIR)
                zf.write(file_path, os.path.join(PACKAGE_NAME, arcname))
                print(f"  + {arcname}")

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"✓ Created {ZIP_FILENAME} ({size_mb:.2f} MB)")
    return zip_path

def main():
    print(f"\n{'='*60}")
    print(f"DEM2DGED v{VERSION_DISPLAY} - Automated Packaging")
    print(f"{'='*60}\n")

    try:
        # Step 1: Verify source
        print("[1/4] Verifying source directory...")
        verify_source()

        # Step 2: Create version file
        print("\n[2/4] Creating version file...")
        create_version_file(SOURCE_DIR)

        # Step 3: Create package
        print("\n[3/4] Creating package zip...")
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
        print("2. Run rebuild_exe.bat to compile")
        print("3. Test dem2dged.exe\n")

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
