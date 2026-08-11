# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.45
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

from typing import List, Tuple, Optional, Dict
import os
import sys
import math
from osgeo import gdal, ogr, osr
import subprocess
import datetime

# -- GDAL error-handling contract (v0.41) -------------------------------------
#
# gdal.UseExceptions() is a PROCESS-WIDE setting, and until v0.41 nothing in
# the project agreed on it: dem2dged_gui.py and run_verification.py called
# UseExceptions(), while dem2dged.py, the two converters and
# dem2dged_validate.py did not. Since the GUI imports this module, the same
# library code took two different error paths depending only on which entry
# point the user happened to start from -- with exceptions ON, every
# "if ds is None:" guard below is dead code and a marginal raster raises
# instead of degrading gracefully. Concretely, the same unreadable tile would
# make reconcile_tile_edges() skip one edge from the CLI but abort the whole
# phase-2 pass from the GUI, and would make the pre-flight sanity check warn
# from the CLI but crash from the GUI.
#
# GDAL 3.7+ warns about leaving this unset ("FutureWarning: Neither
# gdal.UseExceptions() nor gdal.DontUseExceptions() has been explicitly
# called. In GDAL 4.0, exceptions will be enabled by default"), which showed
# up in every real-GDAL run log -- and in GDAL 4.0 the CLI would silently
# flip to the GUI's behaviour.
#
# MEASURED, NOT ASSUMED (v0.41, GDAL 3.13.2): gdal, ogr and osr do NOT have
# independent exception flags -- they share ONE global. A first attempt at
# this fix called gdal.UseExceptions() and then ogr/osr.DontUseExceptions(),
# and a test asserting gdal.GetUseExceptions() == 1 immediately afterwards
# failed with "assert 0 == 1": the later ogr/osr calls had turned gdal's
# exceptions back off. So "gdal on, osr off" is not a state that exists, and
# the choice is one setting for all three.
#
# That choice is OFF, deliberately:
#
#   * The entire codebase is written against the "returns None" contract --
#     eight guarded opens in this module alone, plus the validator, the
#     comparison module and the GUI. Those guards implement real graceful
#     degradation (skip one edge, warn and continue, return 0), not just
#     error reporting.
#   * Several call sites must survive a raster with a weak or absent CRS.
#     Most visibly dem2dged_validate.py's check_tile() WARNs -- never fails
#     -- when a tile carries no EGM2008 tag, and then builds
#     osr.SpatialReference(wkt=ds.GetProjection() or "") from it. With
#     exceptions on, that empty WKT raises and a survivable "missing
#     vertical tag" warning becomes a crash that takes the whole validation
#     run with it.
#
# Setting it EXPLICITLY (rather than leaving it unset) is what matters: it
# silences GDAL 3.7+'s "FutureWarning: Neither gdal.UseExceptions() nor
# gdal.DontUseExceptions() has been explicitly called. In GDAL 4.0,
# exceptions will be enabled by default", which appeared in every real run
# log, and it pins today's tested behaviour under GDAL 4.0 instead of
# letting the default flip underneath the tool.
#
# gdal_open() below then makes the contract independent of this setting
# altogether, so a future migration -- or another library in the same
# process flipping the global -- cannot silently change how dem2dged
# handles an unreadable raster.
#
# FOLLOW-UP (not a v0.41 change): moving to exceptions requires a
# None-returning helper for every osr.SpatialReference(wkt=...) built from a
# raster's projection (dem2dged_lib 1525/1612, dem2dged_validate
# 696/1008/1009/1047, dem2dged_gui 160/320), and a decision at each caller
# about what an unusable CRS means.
gdal.DontUseExceptions()
ogr.DontUseExceptions()
osr.DontUseExceptions()


def gdal_open(path: str, mode: int = gdal.GA_ReadOnly):
    """gdal.Open() that returns None on failure instead of raising.

    Use this everywhere the caller wants to decide for itself what an
    unreadable raster means -- skip it, warn, degrade, or raise its own
    error with a better message. It behaves identically whether GDAL
    exceptions are on or off, so the behaviour cannot drift with the GDAL
    version or with which module happened to be imported first.

    Where an unreadable raster is genuinely fatal, the caller still raises
    (see get_extent_and_srs_of_input_raster() and source_gsd_meters()).
    """
    try:
        return gdal.Open(path, mode)
    except RuntimeError:
        return None


# -- Console encoding safety (v0.44) -------------------------------------------
#
# Reported from a Korean Windows console (code page cp949):
#
#     File "dem2dged_package.py", line 353, in verify_source
#       print(f"✓ Source directory verified ...")
#   UnicodeEncodeError: 'cp949' codec can't encode character '✓'
#   During handling of the above exception, another exception occurred:
#       print(f"\n✗ Error: {e}")
#   UnicodeEncodeError: 'cp949' codec can't encode character '✗'
#
# Two distinct defects in that traceback:
#
#   1. The packaging scripts printed U+2713 CHECK MARK / U+2717 BALLOT X /
#      U+274C CROSS MARK / box-drawing characters to the console. Those
#      encode fine in UTF-8 and cp1252-with-luck, and NOT AT ALL in cp949,
#      cp932, cp936 or plain ASCII -- i.e. on a large share of the machines
#      this tool is actually used on. A decorative glyph took down the
#      entire release packaging step.
#   2. The except handler ITSELF printed a glyph, so the second traceback
#      destroyed the error message from the first. Whatever verify_source()
#      was really complaining about was never shown.
#
# This is the same failure class as the v0.38 fix to
# dem2dged_validate.Report._emit(), which was applied there and nowhere
# else. The permanent fix is both belt and braces: the scripts now print
# ASCII markers ([OK] / [FAIL]) so the situation does not arise, AND
# safe_print() below guarantees that no console encoding can ever turn a
# progress message into a crash.

def safe_print(*args, **kwargs):
    """print() that degrades instead of raising on an unencodable console.

    A message the user cannot read is a nuisance; a message that raises
    UnicodeEncodeError and aborts the program is a defect. This tries the
    normal print first (so a UTF-8 console keeps full fidelity), and on
    UnicodeEncodeError re-encodes through the console's own codec with
    errors="replace" -- unencodable characters become "?" and the program
    carries on.

    Use this for any console output that might contain a character outside
    ASCII, including output that merely INTERPOLATES a value which might
    (file paths and exception messages routinely do -- a Korean or accented
    directory name is enough).
    """
    try:
        print(*args, **kwargs)
        return
    except UnicodeEncodeError:
        pass

    stream = kwargs.get("file") or sys.stdout
    encoding = getattr(stream, "encoding", None) or "ascii"
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    text = sep.join(str(a) for a in args) + end
    safe = text.encode(encoding, errors="replace").decode(encoding,
                                                          errors="replace")
    try:
        stream.write(safe)
    except Exception:
        # Last resort: strip to pure ASCII. Nothing below this can fail.
        try:
            stream.write(text.encode("ascii", errors="replace")
                         .decode("ascii"))
        except Exception:
            pass


# -- Pre-flight guards (v0.42) -------------------------------------------------
# Three failure modes that used to surface as a raw traceback, or as N
# identical per-tile errors followed by a cheerful "All done!". Each one is
# now a single, explicit check with an actionable message, run BEFORE any
# tile is warped. They live here rather than in the converters so the CLI,
# the GUI and the tests all get the identical behaviour and message.

# gdalwarp's own -r vocabulary, plus the two dem2dged-only meta-values that
# resolve_resampler()/pick_resampler() understand. "none" and "mode" are
# accepted by gdalwarp but are meaningless for a continuous elevation
# surface, so they are deliberately NOT here.
GDALWARP_RESAMPLERS = ("near", "bilinear", "cubic", "cubicspline",
                       "lanczos", "average", "rms", "min", "max", "med",
                       "q1", "q3")
META_RESAMPLERS = ("auto", "optimize")
VALID_RESAMPLERS = frozenset(GDALWARP_RESAMPLERS + META_RESAMPLERS)


def validate_resampler(name: Optional[str]) -> str:
    """Normalise and check a -resample / GUI resampling value (v0.42).

    Until v0.42 an unrecognised value was handed straight to gdalwarp:
    pick_resampler() returns any override verbatim, the converters put it
    in the "-r" slot, and gdalwarp then rejected it once PER TILE. On a
    150-tile delivery that is 150 lines of "ERROR: gdalwarp failed for
    ... - tile skipped (re-run to retry)", followed by "All done!" and exit
    code 0 over a folder containing nothing, because the tile loop treats a
    failed warp as a skippable per-tile problem (which it is -- for a bad
    tile, not for a bad flag).

    Returns the lower-cased, stripped name. Raises SystemExit with the full
    list of valid values for anything else. None/"" resolves to "auto", the
    documented default.
    """
    n = (name or "auto").strip().lower()
    if n in VALID_RESAMPLERS:
        return n
    raise SystemExit(
        "ERROR: unknown resampling method '%s'.\n"
        "       Valid values are: %s\n"
        "       ('auto' = average when downsampling, else bilinear; "
        "'optimize' = measure\n"
        "        Nearest/Bilinear/Cubic against this DEM and use the most "
        "accurate.)"
        % (name, ", ".join(sorted(VALID_RESAMPLERS))))


def require_gdalwarp() -> str:
    """Confirm gdalwarp is callable before starting a conversion (v0.42).

    run_cmd() invokes gdalwarp through subprocess with shell=False, which
    raises FileNotFoundError -- an uncaught traceback -- when the binary is
    not on PATH. That is the single most common setup problem for this
    tool (running from `base` instead of the DGED conda environment), and
    both CLI converters advertise a friendly "Requirements: GDAL (gdalwarp)
    must be on PATH" in their --help while doing nothing to produce it.

    Returns the resolved path to gdalwarp; raises SystemExit otherwise.
    """
    import shutil as _shutil

    exe = _shutil.which("gdalwarp")
    if exe:
        return exe
    raise SystemExit(
        "ERROR: 'gdalwarp' was not found on PATH, so no tile can be "
        "produced.\n"
        "       dem2dged shells out to the GDAL command-line tools for "
        "every warp.\n"
        "       From an Anaconda Prompt, in a DEDICATED environment (never "
        "base):\n"
        "           conda create -n DGED python=3.11 -c conda-forge\n"
        "           conda activate DGED\n"
        "           conda install -c conda-forge gdal numpy pytest\n"
        "       Then re-run this command from the SAME prompt.")


def require_epsg(srs, raster_path: str) -> str:
    """Return the EPSG code of a source raster's CRS, or fail clearly (v0.42).

    get_extent_and_srs_of_input_raster() reads the code with
    osr.SpatialReference.GetAttrValue("AUTHORITY", 1), which returns None
    whenever the raster's CRS carries no EPSG authority node -- a bare ESRI
    WKT, a local/engineering CRS, a plain .asc grid, or a raster with no
    projection at all. All of those are routine in operator-supplied data.
    The None then reached get_bbox_of_output()'s int(ext[4]) and died as
    "TypeError: int() argument must be a string, a bytes-like object or a
    real number, not 'NoneType'", which says nothing about the actual
    problem; with -source_vertical it first built the equally useless
    "EPSG:None+5773" and handed it to gdalwarp.

    dem2dged cannot reproject a CRS it cannot name -- the tile grid,
    the sidecar EPSG field and the validator's georeferencing check all key
    off the code -- so this is a hard, early stop rather than a guess.
    """
    if srs is not None and str(srs).strip() != "":
        return str(srs).strip()
    # v0.43: the remedy used to lead with "gdal_edit.py -a_srs". The v0.42
    # release-gate environment log recorded gdal_edit.py as NOT ON PATH on a
    # standard conda Windows install -- the GDAL Python utilities ship as
    # modules under osgeo_utils, not as console scripts -- so the suggested
    # command would itself have failed. The "python -m" form works
    # everywhere the osgeo bindings do, which is by definition everywhere
    # this message can be printed, so it goes first.
    raise SystemExit(
        "ERROR: cannot determine the EPSG code of the source raster's "
        "coordinate\n"
        "       reference system: %s\n"
        "       The raster either has no projection at all, or its CRS is "
        "stored in a\n"
        "       form with no EPSG authority code (bare ESRI WKT, a local or "
        "engineering\n"
        "       CRS, ...). dem2dged needs the code to build the tile grid "
        "and to fill\n"
        "       the sidecar metadata, so it will not guess one.\n"
        "\n"
        "       Tag the file in place (substitute the CRS it is really in):\n"
        "           python -m osgeo_utils.gdal_edit -a_srs EPSG:4326 \"%s\"\n"
        "       or, if gdal_edit.py is on your PATH:\n"
        "           gdal_edit.py -a_srs EPSG:4326 \"%s\"\n"
        "       or make a tagged copy instead of modifying the original:\n"
        "           gdalwarp -s_srs EPSG:4326 -t_srs EPSG:4326 \"%s\" "
        "tagged.tif"
        % (raster_path, raster_path, raster_path, raster_path))


# Single source of truth for the project version.
# Bump this on every update (and mirror the change in the README changelog).
# Every module (CLI, GUI, validator) imports this value, so the whole tool
# reports one consistent version.
#
# Changelog:
#   0.42  RELEASE-GATE PASS over v0.41. One blocker and five robustness
#         fixes, all found by re-auditing the extracted package.
#         (1) BLOCKER (regression of the v0.41 finding 3): the tests/
#             directory was missing from the package again. pytest.ini sets
#             "testpaths = tests", so `pytest` exited immediately with
#             "ERROR: file or directory not found: tests" -- release-gate
#             step 03 could not run, MANIFEST.md listed five test files that
#             did not exist, and audit_pure.py section 7 saw only 12 version
#             declarations instead of 18. Rebuilt as conftest.py,
#             test_lib.py, test_validator.py, test_converters.py + README.md.
#         (2) A source raster whose CRS carries no EPSG AUTHORITY code (a
#             bare ESRI WKT, a local/engineering CRS, or no projection at
#             all -- all routine for operator-supplied data) made
#             get_extent_and_srs_of_input_raster() return srs=None, and
#             get_bbox_of_output() then died on int(None) with
#             "TypeError: int() argument must be a string, a bytes-like
#             object or a real number, not 'NoneType'". The -source_vertical
#             path built the equally meaningless "EPSG:None+5773". Now a
#             single explicit check, require_epsg(), raises SystemExit with
#             the file name, what was found, and how to fix it (gdal_edit
#             -a_srs / gdalwarp -s_srs).
#         (3) An unknown -resample value was passed straight through to
#             gdalwarp, which then failed on EVERY tile: N x "ERROR:
#             gdalwarp failed ... tile skipped", followed by "All done!"
#             and exit code 0 over an empty output folder. validate_
#             resampler() now rejects it up front and lists the valid names.
#         (4) gdalwarp missing from PATH raised a bare, uncaught
#             FileNotFoundError traceback out of subprocess.run() on the
#             first tile, despite the CLI epilog promising a clean "GDAL
#             (gdalwarp) must be on PATH" message. require_gdalwarp() now
#             checks once, before any work, and run_cmd() degrades to a
#             non-zero return code instead of raising.
#         (5) Both converters reported success ("All done!", exit 0) even
#             when every tile failed to warp, so dem2dged.py went on to
#             auto-validate an empty folder. A run that produced no tiles
#             at all is now a hard error, and a partial run prints how many
#             tiles failed.
#         (6) dem2dged_package.py's EXCLUDE_FILE_SUFFIXES gained .tmp/.log/
#             .bak, so a stray scratch file can no longer be bundled into
#             the release zip (v0.41 finding 9, left open at the time).
#   0.41  REPAIR RELEASE for v0.40, which did not work as shipped.
#         (1) BLOCKER: dem2dged_validate.py was missing an entire block --
#             the module docstring's closing quotes, every import, the
#             NODATA / ELEV_MIN_SANE / ELEV_MAX_SANE constants,
#             _STATUS_ORDER, the GEO_RE / UTM_RE filename patterns and the
#             "def overall_result(...)" line. The file did not byte-compile
#             ("IndentationError: unexpected indent"), so the validator
#             could not be imported, run, audited or built into an exe, and
#             both dem2dged.py's and the GUI's auto-validation silently
#             degraded to "validator unavailable". Restored and re-verified.
#         (2) The "# Version:" header comment that v0.32 introduced (and
#             that audit_pure.py section 7 checks) was absent from all seven
#             modules that mirror dem2dged_lib.VERSION, so the version-
#             consistency self-audit reported 7 files as declaring version
#             None. Headers restored; audit_pure.py's pattern now actually
#             matches a header COMMENT (it required "Version:" in column 0,
#             which cannot occur in a .py file outside a string, so it could
#             never have matched and the "clean audit" claimed by v0.40 was
#             not real).
#         (3) The tests/ suite documented in MANIFEST.md (conftest.py,
#             test_lib.py, test_converters.py, test_validator.py) was absent
#             while pytest.ini still pointed at it, so "pytest" failed
#             immediately. The suite is restored.
#         (4) Housekeeping: unused imports/locals removed, stale build/,
#             dist/ and __pycache__ artefacts cleared out of the release
#             folder, MANIFEST.md brought back in line with what is actually
#             in the folder.
#         No change to the DGED tables, tile grid geometry, naming,
#         metadata, resampling or validation rules.
#   0.40  Verification re-cut of v0.39 (no functional change). A
#         second review pass over the extracted package: every module byte-
#         compiles, the version-consistency self-audit (audit_pure.py, 12
#         files) is clean, and the end-to-end harness passes 19/19 -- GEO/UTM
#         at every data type and resampler, equatorial zero-padding + the UTM
#         northing clamp, the >50-degree GEO longitude-zone factors
#         (x1.5/x2/x3), the southern hemisphere, a real EGM96->EGM2008
#         transform, the aspect sanity check, and the data-type-aware
#         predictor. All five v0.39 fixes carried forward and re-verified;
#         QUICKSTART.html and the user manual refreshed to v0.40.
#   0.39  First public beta. A full-project review pass (logic, DGIWG
#         250 Ed. 1.2.1 spec cross-check, and an end-to-end real-GDAL test
#         run on user-supplied DEMs). Three changes here, all low-risk:
#         (1) GeoTIFF LZW PREDICTOR is now data-type aware. Every tile was
#             written with PREDICTOR=2 (TIFF "horizontal differencing"),
#             which is only defined for INTEGER samples. Float32 tiles (all
#             UTM levels, and GEO level 3 and above) should use PREDICTOR=3
#             (the IEEE floating-point predictor): more format-correct and
#             materially smaller on real terrain. New predictor_for_type()
#             returns "3" for Float32 and "2" for Int16; both converters and
#             the GUI now build their gdalwarp creation options through it,
#             so they can't drift. Still LZW-lossless, so still spec 13.1
#             compliant; the validator's compression check is unaffected
#             (it checks COMPRESS=LZW, not the predictor).
#         (2) Source-type letter sanity. Spec 12.1 defines the valid source
#             codes (A,B,C,F,G,H,K,L,M,N,O,P,T,U,V,X,Y) and reserves
#             D,E,I,J,Q,R,S,W,Z. The tool accepted any letter silently. New
#             SOURCE_TYPE_CODES / RESERVED_SOURCE_TYPE_CODES tables and
#             describe_source_type() drive a non-blocking WARNING in the CLI
#             converters and a matching WARN in the validator when a
#             reserved/unknown code is used. Warning only -- never blocks a
#             conversion, and the default "A" is silent as before.
#         (3) dem2dged_logging.ColoredFormatter never actually applied its
#             intended "LEVELNAME: message" format: setup_logging() assigned
#             formatter._fmt after construction, but Python's logging.
#             Formatter renders through self._style._fmt, so the unified
#             dem2dged.py CLI printed bare messages with no level prefix.
#             Fixed in dem2dged_logging.py (the fmt is now passed to the
#             constructor); no change to any converter/validator logic.
#         (4) UTM northing clamp (found by the v0.39 beta verification run on
#             an equatorial source): spec 6.3.1 defines UTM northings on
#             [0, 10 000 000] m within a zone. A source whose reprojected
#             extent dips just below the equator -- which happens routinely
#             for an equatorial DEM, because a point-registered source (SRTM)
#             overhangs its nominal edge by half a post -- made the tile grid
#             start at a NEGATIVE northing and emit a non-spec name like
#             "...32N-025..." that the validator then (correctly) rejected.
#             dem2dged_utm.py and dem2dged_gui.py now clamp the tile grid to
#             the valid northing band and warn if that dropped a row. Shared
#             lib tables are unchanged; the fix is in the two UTM tile loops.
#   0.38  Three bugs found by actually running the real CLI + pytest suite
#         with real GDAL for the first time (previously only verifiable by
#         manual re-reading and a GDAL-free reimplementation testbed) --
#         see dem2dged_validate.py's own changelog for the two that live
#         entirely there (a console-encoding crash that silently skipped
#         writing both report files, and an unclamped internal comparison
#         baseline that made every real cubic-convolution run FAIL
#         Section H on "clamped vs unclamped", not a real defect). Here:
#         tests/conftest.py's output_dir fixture always resolved to the
#         same session-wide "output" subdirectory for every test that
#         requested it, so one test's leftover tiles were still present
#         when the next test globbed *.tif expecting only its own --
#         output_dir now returns a fresh tempfile.mkdtemp() per test.
#   0.37  All five findings of DGED_Conversion_Review.md (an independent
#         audit of a 9-run/42-tile DGIWG test-data conversion batch) --
#         two new functions added HERE, called from both converters and
#         the GUI:
#         (1) reconcile_tile_edges() (Finding 1) -- adjacent DGED tiles are
#             warped by independent gdalwarp calls, so nothing guaranteed
#             they agreed on the single post row/column the spec requires
#             them to share; confirmed as a 1.6 m seam on a 5 m-post real-
#             terrain test tile pair (Nearest Neighbor). Copies each tile's
#             shared edge pixels onto its neighbour after both are warped,
#             so the two files are bit-identical along that edge regardless
#             of what either individual gdalwarp call did internally.
#             tile_warp_extent() also now rounds its output to a fixed
#             coordinate precision, narrowing (but not by itself
#             guaranteeing) the same class of mismatch.
#         (2) clamp_tile_to_range() + OVERSHOOT_PRONE_RESAMPLERS (Finding
#             3) -- cubic-family resamplers can overshoot the source's
#             true min/max at sharp discontinuities (confirmed: Cubic
#             Convolution tiles from an 8-bit test raster came out as low
#             as -44 m against a true 0/6 m minimum). Both converters and
#             the GUI now scan the source's exact range once and clamp any
#             tile made with cubic/cubicspline/lanczos back into it.
#         dem2dged_validate.py gained its own independent fixes for
#         Findings 2 and 4 -- see that module's docstring.
#   0.36  Two features prompted by a real validation failure report (an
#         aspect/direction raster fed into the tool as if it were
#         elevation, which produced huge, confusing RMSE/tolerance
#         failures because the tool had no way to know the numbers it was
#         resampling weren't heights):
#         (1) PRE-FLIGHT SANITY CHECK -- sanity_check_elevation_source()
#             inspects the source's filename and its actual value range
#             (via the new quick_raster_range()) for signs it is a terrain
#             DERIVATIVE (aspect/direction/curvature/etc.) rather than
#             elevation. Blocks by default when a filename hint AND a
#             0-360-degree-like range both match; warns but proceeds on
#             either signal alone, to avoid false-positive blocks on real
#             elevation data that happens to span an unusual range. Wired
#             into the CLI (-skip_sanity_check / --skip-sanity-check) and
#             the GUI ("Skip elevation sanity check" checkbox) via the
#             shared run_sanity_check_cli() / direct calls respectively.
#         (2) AUTO-OPTIMIZE RESAMPLING -- resolve_resampler() adds a new
#             "-resample optimize" mode: rather than -resample auto's
#             fixed source/target-GSD-ratio rule of thumb, it measures
#             Nearest / Bilinear / Cubic against the source DEM itself
#             (dem2dged_compare.pick_best_resampling(), the same hold-out
#             cross-validation the Resampling Comparison Test uses, but
#             without writing any tiles or a report) and uses whichever
#             reconstructs it most accurately for that specific file. Ties
#             the two features together: if (1) flags the source as
#             angular/circular data, RMSE is not a meaningful accuracy
#             measure across the 0/360 wraparound seam (averaging 1 degree
#             and 359 degrees gives 180, the opposite compass direction
#             from both), so optimize mode skips the comparison entirely
#             and uses Nearest Neighbor directly instead of measuring
#             something meaningless.
#         Both features' classification/selection logic is unit tested
#         GDAL-free (audit_pure.py sections 8-9, tests/test_lib.py's
#         TestSanityCheck / TestAutoOptimizeResampling) by monkeypatching
#         the one function in each that actually touches a raster
#         (quick_raster_range / _read_source+_holdout_stats) rather than
#         attempting to mock GDAL's dataset object graph.
#   0.35  dem2dged_validate.py's module docstring held its changelog prose
#         in a plain (non-raw) triple-quoted string containing literal
#         "\d+" / "\d{1,7}" describing UTM_RE -- valid but deprecated since
#         Python 3.6, surfaced as SyntaxWarning: invalid escape sequence
#         '\d' on Python 3.12+. Cosmetic only: GEO_RE/UTM_RE themselves were
#         already correctly built as raw strings and are unaffected. Fixed
#         by making the docstring itself a raw string (r-prefixed triple
#         quote).
#         Also: dem2dged_compare.py's HTML comparison report used RMSE/MAE/
#         Bias/Overshoot without ever spelling them out. Column headers now
#         carry a title= tooltip with the full definition, and the report's
#         closing note gains a "Terms" glossary paragraph.
#   0.34  Full-project audit pass (CODE_REVIEW_v0.34.md). Ten fixes:
#         (1) SPEC COMPLIANCE -- utm_tile_basename() built its coordinate
#             subfields with a bare int(), so any northing below 1 000 000 m
#             produced a SHORT field: "DGEDL5UtD_32N500_400_A_U_01" instead of
#             "DGEDL5UtD_32N0500_400_A_U_01" (and northing 0 became "0").
#             Spec 12.1 defines the form ZZh nnnn _ eee -- fixed-width 4/3
#             digits for the km-form levels 4b-6 and 7/6 digits for the
#             metre-form levels 7-9. Every UTM delivery within ~9 degrees of
#             the equator was affected. dem2dged_validate.py never caught it
#             because its UTM_RE used \d+ (any width matched), so converter
#             and validator were consistently wrong together; the validator
#             now checks the field WIDTH explicitly against the level and
#             reports a precise message for pre-0.34 short names instead of
#             an opaque "does not match naming convention".
#             NOTE: this CHANGES FILENAMES for equatorial UTM products. Tiles
#             delivered by v0.33 or earlier keep their old names; re-run the
#             conversion to regenerate them in the spec form.
#         (2) dem2dged_gui.py still carried the pre-v0.27 fallback DGED
#             tables in an `except ImportError` block: levels 8 and 9 as
#             (1 min, "G") instead of the current (1.5 min, "F"). At those
#             numbers latitude zones 2 (50-60 deg) and 4 (70-80 deg) give a
#             NON-INTEGER number of longitude intervals per tile (5333.33 /
#             2666.67), i.e. exactly the post-misalignment bug v0.27 fixed,
#             plus a wrong tile letter in the filename. v0.28 deleted the
#             validator's equivalent fallback for precisely this reason but
#             the GUI's copy was missed. It was also dead code -- the
#             unguarded `import dem2dged_lib as dl` above it means the GUI
#             can never reach the fallback. Deleted.
#         (3) The converters generated one row and one column of pure-NoData
#             tiles on every run: the tile loop bound was
#             floor(max/tiledim) + 1, which unconditionally adds a tile past
#             the data even when the source aligns exactly to the tile grid
#             (whole-degree DEM sheets, the common case). On a 1x1 degree
#             level-5 source that was 21 of 121 tiles -- each costing a full
#             warp, a compute_tile_stats() pass, a sidecar and a TOC entry.
#             Now ceil(max/tiledim), which is identical when the maximum is
#             not on a tile boundary and one fewer row/column when it is.
#             Fixed in all four converters (CLI geo/utm, GUI geo/utm).
#         (4) dem2dged_compare._holdout_stats() wrote its scratch raster
#             (_dged_holdout_train.tif) INTO the DGED delivery folder and
#             removed it only on the success path. If the hold-out warp
#             failed the file survived, and in comparison mode the GUI then
#             validated that same folder -- reporting "filename does not
#             match DGED naming convention" + "missing .xml sidecar" and
#             turning one warp hiccup into a bogus FAIL badge. Now uses
#             tempfile.mkdtemp() with try/finally cleanup (the module
#             already imported tempfile without ever using it).
#         (5) dem2dged_validate.py accepted only single-dash -html-report /
#             -max-diff / -src / -report / -verbose; VALIDATOR_VERSION.txt
#             documented --html-report, which argparse rejected outright.
#             Both spellings are now accepted and the doc is correct.
#         (6) tests/test_converters.py asserted len(*.tif) == len(*.xml),
#             which has been impossible since v0.27: every delivery also
#             writes TABLE_OF_CONTENTS.xml and (multi-tile)
#             <product>_COLLECTION.xml, neither of which has a matching
#             .tif by design. On the bundled fixture that is 121 .tif vs
#             123 .xml, so the test failed on every CORRECT run. It now
#             filters with dem2dged_validate.is_product_level_xml(), the
#             same test check A has used since v0.30.
#         (7) Version drift had already reappeared after v0.32 (a release
#             dedicated to fixing exactly that): VALIDATOR_VERSION.txt and
#             dem2dged_validate_package.py said 0.32 while the validator
#             printed 0.33 at runtime. Rather than resynchronising by hand a
#             third time, tests/test_lib.py now asserts that VERSION here
#             matches VERSION.txt, VALIDATOR_VERSION.txt and both packaging
#             scripts -- the chore is now a failing test.
#         (8) The two axis-order conventions in this file are now explicit.
#             bbox_to_wgs84() forced OAMS_TRADITIONAL_GIS_ORDER while
#             get_extent_and_srs_of_input_raster()/get_bbox_of_output() and
#             the GUI/UTM autodetect relied on GDAL 3's *authority* order
#             (x=lat for EPSG:4326) purely by default. Each group was
#             self-consistent and correct, but a global axis-mapping config
#             would silently swap lat/lon in the second group with no error
#             -- just tiles in the wrong place. The authority-order group now
#             sets OAMS_AUTHORITY_COMPLIANT explicitly. Requires GDAL 3+.
#         (9) BUILD_AND_PACKAGE.py's preflight did not check for
#             dem2dged_compare.py (imported at module level by the GUI since
#             v0.33) or the other converter modules; a missing file passed
#             preflight and only failed at runtime. Full module list now
#             checked.
#        (10) GUI/CLI parity: the GUI hardcoded org="" and never passed
#             abs_hacc / abs_vacc / lineage, all of which the CLI has
#             exposed since v0.27/v0.28. The GUI now has Organisation code,
#             Abs. horizontal accuracy, Abs. vertical accuracy and Lineage
#             fields wired through to the same dl.geo_tile_basename() /
#             dl.sidecar_replacements() / dl.write_collection_metadata()
#             arguments the CLI uses. Also removed unused imports across
#             eight modules.
#   0.33  GUI resampling control + comparison test (new module
#         dem2dged_compare.py):
#         (1) The GUI gets a "Resampling Method" dropdown (default: Auto,
#             the validator-safe automatic choice used since v0.20) with
#             manual overrides Nearest Neighbor / Bilinear Interpolation /
#             Cubic Convolution. The choice is routed through
#             pick_resampler()'s existing override parameter -- the same
#             path the CLI's -resample flag has used since v0.20, so the
#             GUI and CLI now expose identical resampling control.
#         (2) New "Resampling Comparison Test" GUI section: one checkbox
#             per method; any checked subset (1, 2, or all 3) is converted
#             side-by-side into per-file test folders
#             test_1_nearest_neighbor / test_2_bilinear_interpolation /
#             test_3_cubic_convolution.
#         (3) New module dem2dged_compare.py computes round-trip accuracy
#             metrics per method (tiles mosaicked, warped back onto the
#             source DEM's own grid with an identical bilinear back-warp
#             for fairness, then differenced post-by-post: RMSE / MAE /
#             bias / std-dev / max abs error / range overshoot) and writes
#             DGED_Resampling_Comparison_Report.html -- a ranked table per
#             input file with the lowest-RMSE method marked "Most
#             Accurate". If the validator is enabled, each test folder is
#             also validated and its PASS/WARN/FAIL shown in the table.
#   0.32  Housekeeping release: no functional/algorithmic changes. The
#         "Version: 0.29" header comment in dem2dged.py, dem2dged_geo.py and
#         dem2dged_utm.py, and dem2dged_gui.py's APP_VERSION import fallback,
#         had all silently drifted behind this module during the v0.30/v0.31
#         validator-only releases (those bumped VERSION here and in
#         dem2dged_validate.py but nothing else) -- all four now read "0.32"
#         again, consistent with this being the single source of truth for
#         every module's displayed version. dem2dged_package_v0.26.py (the
#         whole-tool zip, as opposed to the validator-only one) walked the
#         entire project folder with no exclusions, so it would bundle
#         PyInstaller build/ and dist/ output, __pycache__, .pytest_cache,
#         and any previous release zips already sitting in the folder into
#         the new package; it now excludes those, matching the curated file
#         list dem2dged_validate_package_v0.26.py already used.
#   0.31  Two more dem2dged_validate.py false-positive fixes, found
#         auditing a real conversion run: (1) the "name says origin X but
#         georef is Y" check (D) compared the raw raster corner against
#         the nominal tile origin with a half-pixel tolerance, but the
#         v0.27 half-post warp extent (tile_warp_extent below) deliberately
#         puts the corner half a pixel before the origin -- exactly on
#         that tolerance boundary -- so it failed every correctly generated
#         tile. Now compares the pixel CENTER with a tiny fractional-pixel
#         tolerance instead. (2) the "unreplaced {{placeholder}}" check (E)
#         was a bare "{{" substring search that matched the DGED template's
#         own header comment describing the templating mechanism, failing
#         every tile regardless of whether real placeholders were
#         substituted. Now matches real {{KEY}} placeholder syntax only.
#         No changes to this module (dem2dged_lib.py) itself; both fixes
#         are in dem2dged_validate.py.
#   0.30  dem2dged_validate.py's file-pairing check (A) no longer flags
#         TABLE_OF_CONTENTS.xml or <product>_COLLECTION.xml as "missing
#         .tif". Both are delivery-level metadata written once per product
#         (write_toc_file() / write_collection_metadata() below, spec 12.1 /
#         6.6), not per-tile sidecars, so they never had a matching .tif --
#         the validator compared every .xml in the folder against the tile
#         .tif set with no exception for these two, so any delivery
#         containing them failed check A even though the tiles themselves
#         were correctly paired. The check now recognises both by the same
#         name test write_toc_file() already uses (TOC_FILENAME / the
#         "_collection.xml" suffix), instead of a second, independent guess
#         at what counts as product-level.
#   0.29  QUICKSTART.html brought up to date with the v0.27/v0.28 feature set
#         it had missed: documents --org / --abs-hacc / --abs-vacc /
#         --lineage, the GUI's Source vertical field, the level-aware Int16
#         (levels 0-2) / Float32 (level 3+) data types, the level 0-3 short
#         filename form, and automatic in-process validation (the old
#         walkthrough still described validation as a separate manual step,
#         which stopped being true back in v0.19). Also fixed a stale "v0.15"
#         label, an incorrect GPL-3.0 license mention (project is
#         GPL-2.0-or-later), and hardcoded Windows paths in the walkthrough
#         steps. No functional code changes.
#   0.28  Finishes what v0.27 started. The v0.27 changelog below says the
#         shared tile logic was "moved into this module so the CLI and the
#         GUI can no longer drift apart" -- that was true for dem2dged_geo.py
#         / dem2dged_utm.py, but dem2dged_gui.py was never actually switched
#         over, so it kept its own independent copy of the pre-v0.27 logic
#         and silently fell out of spec right alongside the fix. This release
#         closes that gap and the others found auditing the result:
#         (1) dem2dged_gui.py's convert_geo()/convert_utm() now call
#             tile_warp_extent(), output_type_for_level(), geo_tile_basename()
#             /utm_tile_basename(), sidecar_replacements()/write_sidecar_file(),
#             and write_toc_file()/write_collection_metadata() from this
#             module instead of a hand-rolled copy. Fixes, in every
#             GUI-produced tile: a half-post pixel misregistration (every
#             sample was offset half a post spacing off the DGED grid --
#             e.g. 1.0 m on a 2 m-GSD level-5 UTM tile), Float32 forced for
#             every level (levels 0-2 must be Int16), the pre-v0.27 filename
#             form for levels 0-3, and XML sidecars with 12 of 17
#             placeholders left as literal unreplaced "{{...}}" text. The GUI
#             can now also perform a real EGM2008 vertical-datum transform
#             (-source_vertical), which the function signature supported
#             since v0.20 but no GUI field ever set.
#         (2) DGED_UTM_TEMPLATE.xml was truncated (not well-formed XML --
#             everything from the mandatory data-quality block onward was
#             missing). Every UTM tile's sidecar was invalid regardless of
#             which converter produced it. Rebuilt from DGED_GEO_TEMPLATE.xml.
#         (3) dem2dged_validate.py had not been updated for the v0.27 naming/
#             data-type changes: it hard-failed correct Int16 level 0-2
#             tiles, its filename patterns rejected the new level 0-3 short
#             form, and its hand-copied fallback DGED tables (used only if
#             importing this module failed) had already drifted out of sync
#             for GEO levels 8-9. All three fixed; the fallback tables were
#             removed rather than resynced, so a broken import fails loudly
#             instead of silently validating against stale numbers.
#         (4) sidecar_replacements()'s EPSG placeholder was being passed as
#             "EPSG:<code>" by both CLI converters, producing a malformed
#             .../EPSG/0/EPSG:4326 CRS URI in every sidecar instead of
#             .../EPSG/0/4326; both now pass the bare code.
#         (5) dem2dged.py: removed a block left over from a prior session
#             that found this file truncated on disk and reconstructed the
#             auto-validation logic by pattern-matching other modules,
#             flagged as unverified. It has since been checked against
#             dem2dged_validate.py's real function signatures and is
#             correct; the disclaimer is gone. Also added --org / --abs-hacc
#             / --abs-vacc / --lineage, which dem2dged_geo.py / dem2dged_utm.py
#             have accepted since v0.27 but this wrapper never exposed.
#         (6) Version strings resynchronised project-wide (this module is
#             the single source of truth; several other files had drifted
#             to older hardcoded values).
#         (7) run_cmd() and the gdalwarp command it runs (built by
#             dem2dged_geo.py / dem2dged_utm.py) no longer use shell=True
#             with a string-interpolated command line; both converters now
#             build an argument LIST and run_cmd() executes it with
#             shell=False (no shell is spawned, so no quoting is needed or
#             can be gotten wrong -- a path containing a double quote,
#             backtick, $(...), or "&"/"|"/"^" character could previously break
#             the intended quoting). ColoredFormatter.format() in
#             dem2dged_logging.py no longer mutates the shared LogRecord's
#             levelname in place; it now restores the original value after
#             formatting, so a plain (non-colored) file handler processing
#             the same record after the console handler no longer inherits
#             leaked ANSI escape codes.
#   0.27  DGED spec-compliance pass (DGIWG 250 Ed. 1.2.1 audit):
#         (1) Half-post registration fix: gdalwarp -te is now expanded by half
#             a post spacing on every side, so pixel CENTERS (the sampled
#             values) fall exactly on the DGED predefined post locations
#             (spec 6.3 / test A.2). Previous output was shifted by half a
#             post in both axes.
#         (2) Levels 0-2 are now encoded as signed 16-bit integers as MANDATED
#             by spec section 7 (Float32 is only valid for level 3 and up).
#         (3) Metadata sidecars now include the mandatory Annex B elements:
#             geographic bounding box, vertical extent (min/max z), lineage,
#             absolute horizontal/vertical accuracy quality reports (spec
#             Table 5/6 goal values by default, overridable), completeness
#             (missing-data percentage, computed per tile) and the conformity
#             report (default: 'Not tested').
#         (4) Security classification is now written into the metadata
#             (was hardcoded 'unclassified' regardless of the CLI flag).
#         (5) GEO levels 8 and 9 now use the 1.5-minute tile (letter F, a
#             valid spec Table 8 option) instead of the 1-minute tile, because
#             the 1-minute tile gives a NON-INTEGER number of longitude
#             intervals in latitude zones 2 (50-60 deg) and 4 (70-80 deg)
#             (zone factors 1.5 and 3), breaking post alignment there.
#         (6) A TABLE_OF_CONTENTS.xml (spec 12.1 'shall') and a collection
#             metadata file (RSTYPE='series', spec 6.6) are now written with
#             every product delivery.
#         (7) Levels 0-3 GEO filenames follow the spec example form
#             DGEDL2_27N056E_A_U_01 (no product-type letter, no tile-size
#             indicator - those apply to levels above 3 only); an optional
#             producer organisation code (-org) can be embedded in all names.
#         Shared tile logic (naming, extents, data types, sidecar rendering,
#         TOC/collection writing) moved into this module so the CLI and the
#         GUI can no longer drift apart.
#   0.26  GUI layout fix: the Convert / Stop bar is pinned to the bottom of the
#         window and the body scrolls, so the Convert button is always visible
#         even on small / high-DPI screens; the window also opens no larger
#         than the screen work area.
#   0.25  Bug-fix pass. GUI: show a completion dialog and surface stopped/
#         error runs (were silently dropped); GUI extent reprojection now uses
#         all four corners (fixes possible edge-tile under-coverage on oblique
#         transforms). Packaging scripts point at the correct source folder.
#   0.24  GUI source-resolution auto-detect + level auto-suggest (Feature #1);
#         per-tile PASS/WARN/FAIL table in the HTML validation report (Feature #2).
VERSION = "0.45"

# Release stage label. The numeric VERSION above is the single value every
# module and the version-consistency self-test (audit_pure.py section 7) key
# off, so it stays a bare "MAJOR.MINOR" string. RELEASE_STAGE carries the
# rc/"" qualifier separately; VERSION_DISPLAY is what the user sees in
# --version, the GUI title bar and the report headers ("0.45").
RELEASE_STAGE = ""
VERSION_DISPLAY = ("%s-%s" % (VERSION, RELEASE_STAGE)) if RELEASE_STAGE else VERSION

# -- GEO zone/level tables (DGED spec Table 3 & 7) ----------------------------

#  (zone_id, lat_min, lat_max, lat_spacing, lon_spacing_multiplier)
zone_lon_spacing = [
    (-6, -90, -85, 1, 10 ),
    (-5, -85, -80, 1, 5  ),
    (-4, -80, -70, 1, 3  ),
    (-3, -70, -60, 1, 2  ),
    (-2, -60, -50, 1, 1.5),
    (-1, -50,  -0, 1, 1  ),
    ( 1,   0,  50, 1, 1  ),
    ( 2,  50,  60, 1, 1.5),
    ( 3,  60,  70, 1, 2  ),
    ( 4,  70,  80, 1, 3  ),
    ( 5,  80,  85, 1, 5  ),
    ( 6,  85,  90, 1, 10 ),
]

# (level, tile_size_minutes, lat_res_arcsec, tile_letter)
#
# v0.27: levels 8 and 9 use the 1.5-minute tile (letter F, spec Table 8
# option) instead of the 1-minute tile. With a 1-minute tile, latitude
# zones 2 (50-60 deg) and 4 (70-80 deg) - longitude factors 1.5 and 3 -
# yield a NON-INTEGER number of longitude intervals per tile
# (e.g. 60 arcsec / (0.0075 * 1.5) = 5333.33), so tile origins could not
# sit on the longitude post grid. All six zone factors divide the
# 1.5-minute tile evenly at both levels.
level_tilesize_and_spatial_resolution = [
    ("0",  60,  30,     "A"),   # ~1000 m
    ("1",  60,  3,      "A"),   # ~100 m
    ("2",  60,  1,      "A"),   # ~30 m
    ("3",  60,  0.4,    "A"),   # ~12 m
    ("4b", 15,  0.15,   "C"),   # ~5 m
    ("4",  15,  0.12,   "C"),   # ~4 m
    ("5",  6,   0.06,   "D"),   # ~2 m
    ("6",  3,   0.03,   "E"),   # ~1 m
    ("7",  1.5, 0.015,  "F"),   # ~0.5 m
    ("8",  1.5, 0.0075, "F"),   # ~0.25 m
    ("9",  1.5, 0.00375,"F"),   # ~0.125 m
]

# -- UTM level table (DGED spec Table 9) --------------------------------------

# (level, GSD_m, posts_per_tile, tile_letter)
PL = [
    ("4b", 5,    5001,  "C"),
    ("4",  4,    6251,  "C"),
    ("5",  2,    5001,  "D"),
    ("6",  1,    5001,  "E"),
    ("7",  0.5,  5001,  "F"),
    ("8",  0.25, 5001,  "G"),
    ("9",  0.125,10001, "G"),
]

# -- Data type policy (DGED spec section 7) ------------------------------------
# Signed 16-bit integer is MANDATORY for levels 0-2 (integer metric values).
# Float32 is valid for level 3 and above (Int16 also valid for level 3, but
# Float32 is used to preserve sub-metre detail).
INT16_LEVELS = ("0", "1", "2")


def output_type_for_level(level: str) -> str:
    """Return the gdalwarp -ot data type mandated/valid for a DGED level."""
    return "Int16" if str(level) in INT16_LEVELS else "Float32"


def predictor_for_type(out_type: str) -> str:
    """Return the GeoTIFF LZW PREDICTOR creation-option value for a data type.

    v0.39: the TIFF "horizontal differencing" predictor (PREDICTOR=2) is only
    defined for INTEGER samples. Applying it to floating-point data (Float32,
    used for every UTM level and GEO level 3+) is not the correct predictor
    and compresses real terrain markedly worse; PREDICTOR=3 is the dedicated
    IEEE floating-point predictor. Both keep the compression LZW-lossless, so
    this stays spec 13.1 compliant either way -- only the predictor sub-option
    changes. Returned as a string so callers can drop it straight into a
    gdalwarp "-co PREDICTOR=<n>" / creationOptions list.

      Int16   -> "2"   (horizontal differencing, integer)
      Float32 -> "3"   (floating-point predictor)
    """
    return "2" if str(out_type) == "Int16" else "3"


# -- Accuracy defaults (DGED spec Tables 5 & 6, goal columns) -------------------
# Used as the DEFAULT 'predicted' absolute accuracy written to the metadata
# quality reports when the operator does not supply measured values.
LEVEL_ABS_HACC = {
    "0": 50.0, "1": 50.0, "2": 23.0, "3": 15.0, "4b": 6.0, "4": 5.0,
    "5": 3.0, "6": 2.0, "7": 1.0, "8": 0.5, "9": 0.25,
}
LEVEL_ABS_VACC = {
    "0": 30.0, "1": 30.0, "2": 18.0, "3": 12.4, "4b": 5.0, "4": 4.0,
    "5": 2.0, "6": 1.0, "7": 0.5, "8": 0.25, "9": 0.12,
}

# -- Security classification (DGED spec 12.1 / 13.4) ----------------------------
CLASSIFICATION_WORDS = {
    "T": "topSecret",
    "S": "secret",
    "C": "confidential",
    "R": "restricted",
    "U": "unclassified",
}

# -- Source-type code (DGED spec 12.1, source data type letter) -----------------
# The single-character source-data-type code in the filename (subfield after
# the coordinates). Spec 12.1 defines the meaning of each valid letter and
# explicitly reserves D, E, I, J, Q, R, S, W and Z "for future use". The tool
# used to accept any A-Z letter silently; describe_source_type() lets the CLI
# converters and the validator flag a reserved or unknown code with a precise,
# non-blocking warning (the default, "A" = optical unedited reflective surface,
# stays silent).
SOURCE_TYPE_CODES = {
    "A": "optical source, unedited reflective surface",
    "B": "optical source, edited reflective surface",
    "C": "optical source, edited bare earth surface",
    "F": "IFSAR source, unedited reflective surface",
    "G": "IFSAR source, edited reflective surface",
    "H": "IFSAR source, edited bare earth surface",
    "K": "LIDAR source, unedited first return",
    "L": "LIDAR source, unedited last return",
    "M": "LIDAR source, unedited bare earth",
    "N": "LIDAR source, edited first return",
    "O": "LIDAR source, edited last return",
    "P": "LIDAR source, edited bare earth",
    "T": "SAR source, unedited reflective surface",
    "U": "SAR source, edited reflective surface",
    "V": "SAR source, edited bare earth",
    "X": "unidentified source, reflective surface",
    "Y": "unidentified source, bare earth surface",
}
RESERVED_SOURCE_TYPE_CODES = frozenset("DEIJQRSWZ")


def describe_source_type(letter: str) -> Tuple[bool, str]:
    """Classify a DGED source-type code letter (spec 12.1).

    Returns (ok, message):
      ok=True,  message="" for a valid, defined code (SOURCE_TYPE_CODES).
      ok=False, message=<why> for a reserved (D/E/I/J/Q/R/S/W/Z) or unknown
      code -- callers WARN with it but never block, since a non-standard code
      still produces a mechanically valid tile and metadata prevails over the
      filename per spec 12.1.
    """
    c = (letter or "").strip().upper()
    if c in SOURCE_TYPE_CODES:
        return True, ""
    if c in RESERVED_SOURCE_TYPE_CODES:
        return False, ("source-type code '%s' is reserved for future use by "
                       "DGED spec 12.1 -- valid codes are %s. Metadata still "
                       "prevails over the filename, so this is a warning, not "
                       "an error." % (c, ", ".join(sorted(SOURCE_TYPE_CODES))))
    return False, ("source-type code '%s' is not a DGED spec 12.1 source code "
                   "(valid codes are %s). Metadata still prevails over the "
                   "filename, so this is a warning, not an error."
                   % (c, ", ".join(sorted(SOURCE_TYPE_CODES))))

# -- Shared helpers -----------------------------------------------------------

debug: bool = False


def dp(st: str) -> None:
    """Debug print: print only if debug mode is enabled."""
    if debug:
        print(st)


def ToDMS(dd: float) -> Tuple[int, int, float]:
    """Decimal degrees -> (deg, min, sec).

    Rounds to 1/10000 arc-second first to avoid 59.999... floating-point
    artefacts.
    """
    total_sec = round(abs(float(dd)) * 3600, 4)
    deg  = int(total_sec // 3600)
    rem  = total_sec - deg * 3600
    mins = int(rem // 60)
    sec  = rem - mins * 60
    if dd < 0:
        deg = -deg
    return deg, mins, sec


def geo_tile_basename(level: str, tile_letter: str, t_minlat: float,
                      t_minlon: float, source_type: str, sec_class: str,
                      prod_ver: str, org: str = "") -> str:
    """Build the DGED GEO tile basename per spec 12.1.

    Levels 0-3 use the short form from the spec examples
    (DGEDL2_27N056E_A_U_01): no product-type letter and no tile-size
    indicator, since those products are delivered by square degree.
    Levels 4b-6 add minutes; levels 7-9 add minutes and seconds.
    An optional 3-letter producer organisation code (org) is inserted as
    the second subfield.
    """
    hemi = "S" if t_minlat < 0 else "N"
    east = "W" if t_minlon < 0 else "E"
    dms_lat = ToDMS(t_minlat)
    dms_lon = ToDMS(t_minlon)
    org_part = (org.strip().upper() + "_") if org and org.strip() else ""

    if level in ("0", "1", "2", "3"):
        coord = "%s%s%s%s" % (
            str(abs(int(dms_lat[0]))).rjust(2, "0"), hemi,
            str(abs(int(dms_lon[0]))).rjust(3, "0"), east)
        return "DGEDL%s_%s%s_%s_%s_%s" % (
            level, org_part, coord, source_type, sec_class, prod_ver)
    elif level in ("4b", "4", "5", "6"):
        coord = "%s%s%s%s%s%s" % (
            str(abs(int(dms_lat[0]))).rjust(2, "0"),
            str(abs(int(dms_lat[1]))).rjust(2, "0"), hemi,
            str(abs(int(dms_lon[0]))).rjust(3, "0"),
            str(abs(int(dms_lon[1]))).rjust(2, "0"), east)
    else:
        coord = "%s%s%s%s%s%s%s%s" % (
            str(abs(int(dms_lat[0]))).rjust(2, "0"),
            str(abs(int(dms_lat[1]))).rjust(2, "0"),
            str(abs(int(round(dms_lat[2])))).rjust(2, "0"), hemi,
            str(abs(int(dms_lon[0]))).rjust(3, "0"),
            str(abs(int(dms_lon[1]))).rjust(2, "0"),
            str(abs(int(round(dms_lon[2])))).rjust(2, "0"), east)
    return "DGEDL%sGt%s_%s%s_%s_%s_%s" % (
        level, tile_letter, org_part, coord, source_type, sec_class, prod_ver)


# -- UTM name field widths (DGED spec 12.1) -----------------------------------
# The UTM tile name encodes the tile origin as ZZh nnnn _ eee, where the
# northing/easting subfields are FIXED WIDTH and zero-padded:
#
#   levels 4b-6 ("km form", tile origins are whole kilometres)
#       northing nnnn  = 4 digits   easting eee  = 3 digits
#   levels 7-9  ("metre form", sub-kilometre tiles need full metres)
#       northing nnnnmmm = 7 digits easting eeemmm = 6 digits
#
# v0.34: these widths used to be implicit -- the fields were built with a
# bare int(), so a northing below 1 000 000 m (anywhere within roughly 9
# degrees of the equator) produced a short, non-spec field, and a northing
# of exactly 0 produced the single character "0". See the v0.34 changelog.
UTM_KM_FORM_LEVELS = ("4b", "4", "5", "6")
UTM_NORTHING_WIDTH = {True: 4, False: 7}   # keyed by "is km form"
UTM_EASTING_WIDTH = {True: 3, False: 6}


def utm_name_field_widths(level: str) -> Tuple[int, int]:
    """Return (northing_digits, easting_digits) required by spec 12.1 for a
    UTM product level. Shared with dem2dged_validate.py so the converter and
    the validator can't disagree about what a correct name looks like."""
    km_form = str(level) in UTM_KM_FORM_LEVELS
    return UTM_NORTHING_WIDTH[km_form], UTM_EASTING_WIDTH[km_form]


def utm_tile_basename(level: str, tile_letter: str, utmzone: str,
                      t_miny: float, t_minx: float, source_type: str,
                      sec_class: str, prod_ver: str, org: str = "") -> str:
    """Build the DGED UTM tile basename per spec 12.1
    (DGEDLnT[tS]_[ORG]_ZZhnnnn[mmm]_eee[mmm]_S_c_vv).

    v0.34: the northing/easting subfields are now ZERO-PADDED to the widths
    spec 12.1 requires (see utm_name_field_widths above). Previously they
    were written with a bare int(), so e.g. a level-5 tile at northing
    500 000 m produced "..._32N500_400_..." (3-digit northing) instead of
    "..._32N0500_400_...", and a tile on the equator produced "..._32N0_...".
    """
    org_part = (org.strip().upper() + "_") if org and org.strip() else ""
    if str(level) in UTM_KM_FORM_LEVELS:
        n_part, e_part = int(round(t_miny / 1000)), int(round(t_minx / 1000))
    else:
        n_part, e_part = int(round(t_miny)), int(round(t_minx))
    n_width, e_width = utm_name_field_widths(level)
    return "DGEDL%sUt%s_%s%s%0*d_%0*d_%s_%s_%s" % (
        level, tile_letter, org_part, utmzone,
        n_width, n_part, e_width, e_part,
        source_type, sec_class, prod_ver)


def tile_warp_extent(min_x: float, min_y: float, tiledim: float,
                     xres: float, yres: float) -> Tuple[float, float, float, float]:
    """gdalwarp -te extent for one DGED tile, HALF-POST EXPANDED (v0.27).

    DGED posts for the tile run from min to min+tiledim INCLUSIVE (the last
    post overlaps the first post of the next tile, spec 13.2). gdalwarp
    samples at pixel CENTERS, so the warp extent must extend half a post
    spacing beyond the outermost posts on every side. This puts every pixel
    center exactly on a DGED predefined post location (spec 6.3); the
    previous unexpanded extent shifted all values by half a post.

    v0.37 (DGED_Conversion_Review.md Finding 1): rounded to a fixed decimal
    precision so the same real-world boundary is always represented by the
    identical float, however it is reached arithmetically -- 1e-9 (degrees
    or metres, depending on caller) is far finer than any DEM post spacing,
    so this is a no-op for real coordinates. This narrows, but does not by
    itself guarantee, adjacent tiles disagreeing on their shared post;
    reconcile_tile_edges() (below) is what makes that an exact match
    unconditionally.

    Returns (xmin, ymin, xmax, ymax) for -te / outputBounds.
    """
    return (round(min_x - xres / 2.0, 9),
            round(min_y - yres / 2.0, 9),
            round(min_x + tiledim + xres / 2.0, 9),
            round(min_y + tiledim + yres / 2.0, 9))


def read_sidecar_template(template_fnam: str) -> str:
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
        f.write(xfile)


def compute_tile_stats(tif_path: str) -> Tuple[int, int, float]:
    """Compute (min_z, max_z, missing_percent) for one tile.

    Reads the raster in row strips so even the largest DGED tiles do not
    need to fit in memory. min/max are rounded to integers (DMF 2.0 stores
    the vertical extent as integer metres). missing_percent is the NoData
    percentage (the DGED CompletenessCommission 'missRate' measure).
    Entirely-NoData tiles return (0, 0, 100.0).
    """
    ds = gdal_open(tif_path)
    if ds is None:
        raise FileNotFoundError("GDAL cannot open: %s" % tif_path)
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    xsize, ysize = ds.RasterXSize, ds.RasterYSize
    strip = max(1, min(ysize, 8 * 1024 * 1024 // max(1, xsize * 8)))

    vmin, vmax = None, None
    n_missing, n_total = 0, xsize * ysize
    y = 0
    while y < ysize:
        rows = min(strip, ysize - y)
        arr = band.ReadAsArray(0, y, xsize, rows)
        y += rows
        if arr is None:
            continue
        arr = arr.astype("float64")
        if nodata is not None:
            valid_mask = abs(arr - nodata) > 0.5
        else:
            valid_mask = arr == arr   # all True
        n_missing += int((~valid_mask).sum())
        if valid_mask.any():
            v = arr[valid_mask]
            smin, smax = float(v.min()), float(v.max())
            vmin = smin if vmin is None else min(vmin, smin)
            vmax = smax if vmax is None else max(vmax, smax)
    ds = None

    if vmin is None:
        return 0, 0, 100.0
    miss_pct = round(100.0 * n_missing / max(1, n_total), 4)
    return int(math.floor(vmin)), int(math.ceil(vmax)), miss_pct


# -- Adjacent-tile edge reconciliation (v0.37) ---------------------------------
# DGED_Conversion_Review.md Finding 1: every tile is warped by its own,
# independent gdalwarp subprocess (see dem2dged_geo.py / dem2dged_utm.py main
# loops), so nothing GUARANTEES that two adjacent tiles agree on the single
# post row/column the DGED spec (6.3) requires them to share at their common
# boundary. In practice the two warps almost always do agree -- but on the
# DGIWG level-4b real-terrain test set, Nearest Neighbor resampling picked a
# different source pixel for the shared row in two independently-run warps,
# producing a 1.6 m seam on a 5 m post spacing (Bilinear/Cubic showed the
# same root cause as a much smaller, sub-pixel wobble, since they are
# continuous interpolants rather than a discontinuous, tie-sensitive
# nearest-pixel pick). Rounding the warp extent to a fixed coordinate
# precision (see the tile loops) narrows how often this can happen, but
# cannot guarantee it, because gdalwarp's own internal coordinate-transform
# approximation is outside this tool's control. reconcile_tile_edges() makes
# the guarantee unconditional by copying the authoritative tile's edge
# pixels onto its neighbour after both are warped, so the two files are
# bit-identical along their shared edge no matter what either individual
# gdalwarp call did internally.

def reconcile_tile_edges(tile_grid: Dict[Tuple[int, int], str]) -> int:
    """Force the post row/column shared by adjacent DGED tiles to match
    exactly, by copying pixels rather than trusting two separate gdalwarp
    calls to agree.

    tile_grid: {(row, col): tif_path} for the tiles created in ONE
    conversion run -- row increases northward (GEO: latitude tile index;
    UTM: northing tile index), col increases eastward (longitude / easting
    tile index). Only tiles actually present in the dict (i.e. successfully
    warped THIS run) are considered; a tile skipped because its .xml already
    existed (the resume path) is deliberately left out by the caller so a
    resumed run can never modify a previously delivered tile.

    For each pair of tiles that share a boundary, the SOUTH tile's top row
    is copied onto the NORTH tile's bottom row, and -- in a second pass, run
    only after every row seam is settled -- the WEST tile's right column is
    copied onto the EAST tile's left column. Running all row fixes before
    any column fix matters: it is what keeps a tile's four corners -- each
    one shared with three OTHER tiles -- mutually consistent, because the
    column pass then reads each tile's already-corrected edge rather than
    its original one.

    Returns the number of shared edges that needed correcting (0 means every
    independent gdalwarp call already agreed).
    """
    from osgeo import gdal

    def _read_edge(path, edge):
        ds = gdal_open(path)
        if ds is None:
            return None
        band = ds.GetRasterBand(1)
        xsize, ysize = ds.RasterXSize, ds.RasterYSize
        if edge == "top":
            arr = band.ReadAsArray(0, 0, xsize, 1)
        elif edge == "bottom":
            arr = band.ReadAsArray(0, ysize - 1, xsize, 1)
        elif edge == "left":
            arr = band.ReadAsArray(0, 0, 1, ysize)
        else:   # "right"
            arr = band.ReadAsArray(xsize - 1, 0, 1, ysize)
        ds = None
        return arr

    def _write_edge(path, edge, arr):
        """Write arr onto path's named edge, but ONLY if it actually
        differs from what is already there -- so the caller's return
        count reflects genuine corrections, not every edge visited."""
        ds = gdal_open(path, gdal.GA_Update)
        if ds is None:
            return False
        band = ds.GetRasterBand(1)
        xsize, ysize = ds.RasterXSize, ds.RasterYSize
        # Defensive: a shape mismatch means the two tiles are not really
        # aligned (e.g. a longitude-zone boundary changes post spacing) --
        # leave both files untouched rather than write a malformed edge.
        if edge in ("top", "bottom") and arr.shape[1] != xsize:
            return False
        if edge in ("left", "right") and arr.shape[0] != ysize:
            return False
        xoff, yoff = {
            "top":    (0, 0),
            "bottom": (0, ysize - 1),
            "left":   (0, 0),
            "right":  (xsize - 1, 0),
        }[edge]
        current = band.ReadAsArray(xoff, yoff, arr.shape[1], arr.shape[0])
        if current is not None and (current == arr).all():
            ds = None
            return False   # already identical -- nothing to correct
        band.WriteArray(arr, xoff, yoff)
        ds.FlushCache()
        ds = None
        return True

    n_fixed = 0

    # Pass 1: row seams. South tile's top row -> north tile's bottom row.
    for (row, col), south_path in list(tile_grid.items()):
        north_path = tile_grid.get((row + 1, col))
        if north_path is None:
            continue
        edge = _read_edge(south_path, "top")
        if edge is not None and _write_edge(north_path, "bottom", edge):
            n_fixed += 1

    # Pass 2: column seams, AFTER every row seam above. West tile's right
    # column -> east tile's left column. Must run second -- see docstring.
    for (row, col), west_path in list(tile_grid.items()):
        east_path = tile_grid.get((row, col + 1))
        if east_path is None:
            continue
        edge = _read_edge(west_path, "right")
        if edge is not None and _write_edge(east_path, "left", edge):
            n_fixed += 1

    return n_fixed


# -- Cubic-family overshoot clamp (v0.37) --------------------------------------
# DGED_Conversion_Review.md Finding 3: cubic-family resamplers can "ring" --
# overshoot past the source's true min/max -- at sharp discontinuities. This
# is expected, standard resampling-kernel behaviour, not a dem2dged bug, but
# it is worst exactly where DGED's own "auto" resampler choice would never
# go (resolve_resampler()/pick_resampler() only ever pick average or
# bilinear automatically, precisely to avoid this) -- so it only bites a
# user who explicitly asks for cubic/cubicspline/lanczos. Confirmed on the
# DGIWG test set: two 8-bit, hard-step-edge test rasters (values 0-255 and
# 6-255) produced Cubic Convolution tiles with elevations as low as -44 m
# and as high as 313 m -- physically impossible, and silent unless someone
# reads the validator's Section H min/max comparison closely.
OVERSHOOT_PRONE_RESAMPLERS = frozenset({"cubic", "cubicspline", "lanczos"})


def clamp_tile_to_range(tif_path: str, vmin: float, vmax: float) -> int:
    """Clamp one tile's elevation values into [vmin, vmax], leaving NoData
    untouched. Intended for ``vmin``/``vmax`` = the SOURCE raster's own
    true min/max (e.g. from compute_tile_stats() run once on the source) --
    clamping to the tile's OWN min/max would defeat the purpose.

    Reads/writes in row strips, like compute_tile_stats(), so this does not
    need the whole tile in memory. Only writes a strip back if it actually
    contains an out-of-range pixel, so a tile with no overshoot (the common
    case -- most resamplers never overshoot, and even cubic-family ones
    only do on sharp discontinuities) is reopened for reading but never
    rewritten.

    Returns the number of pixels that were actually out of range and got
    clamped (0 = nothing to do).
    """
    ds = gdal_open(tif_path, gdal.GA_Update)
    if ds is None:
        return 0
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    xsize, ysize = ds.RasterXSize, ds.RasterYSize
    strip = max(1, min(ysize, 8 * 1024 * 1024 // max(1, xsize * 8)))

    n_clamped = 0
    y = 0
    while y < ysize:
        rows = min(strip, ysize - y)
        arr = band.ReadAsArray(0, y, xsize, rows)
        y0 = y
        y += rows
        if arr is None:
            continue
        too_low  = arr < vmin
        too_high = arr > vmax
        if nodata is not None:
            is_nodata = abs(arr.astype("float64") - nodata) <= 0.5
            too_low  = too_low  & ~is_nodata
            too_high = too_high & ~is_nodata
        n = int(too_low.sum()) + int(too_high.sum())
        if n:
            arr[too_low]  = vmin
            arr[too_high] = vmax
            band.WriteArray(arr, 0, y0)
            n_clamped += n
    if n_clamped:
        ds.FlushCache()
    ds = None
    return n_clamped


# -- Pre-flight elevation sanity check (v0.36) ---------------------------------
# DGED is an elevation-only spec. Feeding it a terrain DERIVATIVE raster
# (aspect/direction, curvature, hillshade...) instead of the elevation surface
# itself produces a mechanically valid-looking DGED package with wrong,
# misleading content -- gdalwarp doesn't know or care that the numbers it is
# resampling aren't heights, and no exception is raised anywhere. The mistake
# is usually only caught by carefully reading the (optional, easy-to-skip)
# post-conversion validation report. This check runs BEFORE conversion starts,
# so the mistake costs a second instead of a full tile run.
#
# Two independent signals, deliberately kept separate rather than merged into
# one score: a filename hint (weak alone -- plenty of real elevation files are
# named oddly) and a value range matching compass/aspect output almost exactly
# (also weak alone -- real terrain can genuinely span close to 0-360 units in
# some regions). Together they are strong enough to block by default; either
# one alone is only ever a warning, to keep false positives from blocking a
# legitimate conversion.

NON_ELEVATION_FILENAME_HINTS = (
    "aspect", "direction", "flow_dir", "flowdir", "curvature",
    "orientation", "bearing", "azimuth", "hillshade", "shaded_relief",
    "flow_acc", "flowacc", "slope_class",
)


def quick_raster_range(path: str) -> Optional[Tuple[float, float]]:
    """Fast, approximate (min, max) of a raster's first band, for the
    pre-flight sanity check below -- NOT for DGED delivery statistics
    (see compute_tile_stats() for the exact, NoData-aware version used
    for that). Uses GDAL's own statistics call so this stays fast even on
    a multi-gigabyte source DEM. Returns None if the raster can't be
    opened or has no computable statistics (e.g. all-NoData) -- callers
    should treat that as "unknown", not as a clean bill of health.
    """
    ds = gdal_open(path)
    if ds is None:
        return None
    try:
        band = ds.GetRasterBand(1)
        vmin, vmax, _vmean, _vstd = band.ComputeStatistics(True)  # approx_ok
    except Exception:
        return None
    finally:
        ds = None
    return float(vmin), float(vmax)


def _classify_angular_range(rng: Optional[Tuple[float, float]]) -> bool:
    """Pure threshold check: does a (min, max) range look like compass
    aspect / flow-direction output (0-360 degrees) rather than elevation?

    Shared by looks_like_angular_data() and sanity_check_elevation_source()
    so the two can never drift apart into disagreeing about the same
    raster.

    v0.36 fix: the first cut of this check used tight windows right at 0
    and 360 (e.g. 355-365 for the max), calibrated on the theoretical
    bounds of gdaldem aspect output. audit_pure.py's own regression test,
    run against the ACTUAL numbers from the report that motivated this
    check (min 18.52, max 345.51 -- a real aspect layer, just not one that
    happened to have a pixel at exactly 0 or 360 degrees), caught that
    those tight windows would have missed the very case this exists to
    catch. Widened to "fits inside roughly 0-360 with a wide span" instead
    of "sits right at the two endpoints".
    """
    if rng is None:
        return False
    span = rng[1] - rng[0]
    return 0.0 <= rng[0] <= 30.0 and 330.0 <= rng[1] <= 360.5 and span >= 250.0


def looks_like_angular_data(input_path: str) -> bool:
    """True if `input_path`'s value range closely matches the 0-360 degree
    span typical of compass/aspect/flow-direction data.

    This is the range-only half of sanity_check_elevation_source()'s
    heuristic (no filename check), exposed separately for callers that
    need a plain yes/no on whether an error metric like RMSE is even
    meaningful for this raster -- e.g. resolve_resampler() /
    dem2dged_compare.pick_best_resampling() below, which cannot rank
    resampling methods by RMSE across a 0/360 wraparound seam (averaging
    1 degree and 359 degrees gives 180, the compass direction opposite
    both real values -- see pick_best_resampling()'s docstring). Re-reads
    the raster range rather than sharing sanity_check_elevation_source()'s
    -- a second approximate ComputeStatistics() call is cheap, and it
    keeps the two checks fully independent of each other's call signature.
    """
    return _classify_angular_range(quick_raster_range(input_path))


def sanity_check_elevation_source(input_path: str) -> List[Tuple[str, str]]:
    """Cheap pre-flight check for signs that `input_path` is not an
    elevation surface.

    Returns a list of (severity, message) pairs, severity is "block"
    (both signals hit -- very likely wrong; callers should refuse to
    proceed unless explicitly overridden) or "warn" (one signal hit --
    worth a second look, but not blocking). Returns [] if nothing looked
    wrong, INCLUDING if the raster couldn't be inspected at all (a
    failure here should never itself block a conversion the user wants
    to run).
    """
    base = os.path.basename(input_path).lower()
    hits = [kw for kw in NON_ELEVATION_FILENAME_HINTS if kw in base]

    rng = quick_raster_range(input_path)
    looks_angular = _classify_angular_range(rng)

    if looks_angular and hits:
        return [("block",
            "source filename contains '%s' AND its value range (%.2f to "
            "%.2f) matches compass/aspect output (0-360 degrees) almost "
            "exactly. This looks like a slope-direction (aspect) raster, "
            "not elevation -- DGED is an elevation-only format. If you "
            "meant to convert the elevation DEM/DTM this was derived "
            "from, point the tool at that file instead."
            % (hits[0], rng[0], rng[1]))]
    if looks_angular:
        return [("warn",
            "source value range (%.2f to %.2f) closely matches the 0-360 "
            "degree range typical of compass/aspect/direction data, not a "
            "typical elevation range. If this is genuinely elevation data "
            "spanning that range, ignore this warning -- otherwise, DGED "
            "is an elevation-only format and this may be the wrong input "
            "file." % rng)]
    if hits:
        return [("warn",
            "source filename contains '%s', which usually names a terrain "
            "DERIVATIVE (direction, curvature, or shading) rather than the "
            "elevation surface itself. Double check this is the elevation "
            "DEM/DTM and not a product derived from it." % hits[0])]
    return []


def run_sanity_check_cli(input_path: str, skip: bool) -> None:
    """Shared CLI presentation for sanity_check_elevation_source(): prints
    "warn"-severity findings and continues; on a "block"-severity finding,
    prints it as an ERROR and raises SystemExit unless `skip` is True (the
    -skip_sanity_check flag). Used identically by dem2dged_geo.py and
    dem2dged_utm.py so the two can't drift into different wording or
    different exit behaviour for the same check.
    """
    issues = sanity_check_elevation_source(input_path)
    blocking = [msg for sev, msg in issues if sev == "block"]
    for sev, msg in issues:
        if sev != "block":
            print("WARNING: %s" % msg)
    if blocking:
        for msg in blocking:
            print("ERROR: %s" % msg)
        if not skip:
            raise SystemExit(
                "ERROR: conversion stopped before doing any work -- the "
                "input above is very likely not elevation data. Re-run "
                "with -skip_sanity_check if you are sure this is correct.")
        print("WARNING: -skip_sanity_check set -- proceeding anyway.")


# -- Axis order (v0.34) --------------------------------------------------------
# This module deliberately uses BOTH osr axis-mapping strategies, because the
# two groups of functions below express coordinates differently:
#
#   TRADITIONAL (x=lon/easting, y=lat/northing)
#       bbox_to_wgs84() -- returns a plain (west, south, east, north) box for
#       the metadata sidecars, which are always lon/lat.
#
#   AUTHORITY  (x=lat, y=lon for EPSG:4326)
#       get_bbox_of_output() and dem2dged_utm.autodetect_utm() -- the GEO
#       converter unpacks their result as "minlat, maxlat, minlon, maxlon",
#       which only holds under authority order.
#
# Before v0.34 only the first group set a strategy; the second relied on GDAL
# 3's default being authority-compliant. That was correct but fragile -- a
# global axis-mapping configuration (or a GDAL 2 environment, where the
# default is traditional) would silently swap lat/lon with no error at all,
# just tiles written in the wrong place. Both groups are now explicit.
# GDAL 3+ is required; on GDAL 2 the constants do not exist and the calls are
# skipped, which restores the pre-v0.34 (traditional-by-default) behaviour.

def set_traditional_axis_order(*srs_list) -> None:
    """Force x=lon/easting, y=lat/northing on every SpatialReference given."""
    for srs in srs_list:
        try:
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        except AttributeError:
            pass   # GDAL 2.x: traditional order is already the default


def set_authority_axis_order(*srs_list) -> None:
    """Force the EPSG authority's own axis order (x=lat, y=lon for 4326)."""
    for srs in srs_list:
        try:
            srs.SetAxisMappingStrategy(osr.OAMS_AUTHORITY_COMPLIANT)
        except AttributeError:
            pass   # GDAL 2.x: no such strategy; caller keeps legacy behaviour


def bbox_to_wgs84(minx: float, miny: float, maxx: float, maxy: float,
                  epsg: int) -> Tuple[float, float, float, float]:
    """Transform an extent in EPSG:<epsg> to a WGS84 (lon/lat) bounding box.

    Returns (west, south, east, north) in decimal degrees. Uses traditional
    GIS axis order (x=lon/easting, y=lat/northing) on both sides so the
    result is independent of GDAL's authority axis order handling.
    """
    if int(epsg) == 4326:
        return minx, miny, maxx, maxy
    src = osr.SpatialReference(); src.ImportFromEPSG(int(epsg))
    dst = osr.SpatialReference(); dst.ImportFromEPSG(4326)
    set_traditional_axis_order(src, dst)
    xf = osr.CoordinateTransformation(src, dst)
    corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]
    pts = []
    for x, y in corners:
        p = ogr.CreateGeometryFromWkt("POINT (%s %s)" % (x, y))
        p.Transform(xf)
        pts.append((p.GetX(), p.GetY()))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def sidecar_replacements(basename: str, level: str, gsd: float, epsg: str,
                         sec_class: str, org: str,
                         bbox_wgs84: Tuple[float, float, float, float],
                         tif_path: str, abs_hacc: Optional[str] = None,
                         abs_vacc: Optional[str] = None,
                         lineage: str = "") -> Dict[str, str]:
    """Build the full placeholder dictionary for one tile's XML sidecar.

    Computes the vertical extent and the missing-data percentage from the
    freshly written tile. Absolute accuracies default to the spec Table 5/6
    goal values for the level unless explicit values are supplied.
    """
    minz, maxz, miss_pct = compute_tile_stats(tif_path)
    west, south, east, north = bbox_wgs84

    def _acc(value, table):
        if value is None or str(value).strip().lower() in ("", "auto"):
            return table.get(level, "")
        return value

    return {
        "BASENAME":  basename,
        "LEVEL":     level,
        "GSD":       gsd,
        "DATE":      str(datetime.date.today()),
        "EPSG":      epsg,
        "ORG":       org.strip().upper() if org and org.strip() else "Unknown",
        "CLASS_WORD": CLASSIFICATION_WORDS.get(sec_class, "unclassified"),
        "WEST":      "%.9f" % west,
        "EAST":      "%.9f" % east,
        "SOUTH":     "%.9f" % south,
        "NORTH":     "%.9f" % north,
        "MINZ":      minz,
        "MAXZ":      maxz,
        "MISSRATE":  miss_pct,
        "ABS_HACC":  _acc(abs_hacc, LEVEL_ABS_HACC),
        "ABS_VACC":  _acc(abs_vacc, LEVEL_ABS_VACC),
        "LINEAGE":   lineage if lineage else "Derived from a source DEM by "
                     "dem2dged v%s (GDAL warp)." % VERSION,
        "DTYPE":     "integer" if output_type_for_level(level) == "Int16"
                     else "real",
    }


# -- Product delivery: table of contents + collection metadata (v0.27) ---------

TOC_FILENAME = "TABLE_OF_CONTENTS.xml"


def _xml_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def write_toc_file(folder: str, product_id: str) -> str:
    """Write the DGED 'table of content' XML (spec 12.1 'shall').

    Lists every elevation data file, metadata sidecar and the collection
    metadata file present in the product folder. Regenerated on every run
    so it always reflects the current folder content.
    """
    entries = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        low = name.lower()
        if low.endswith(".tif"):
            role = "elevationData"
        elif low == TOC_FILENAME.lower():
            continue
        elif low.endswith("_collection.xml"):
            role = "collectionMetadata"
        elif low.endswith(".xml"):
            role = "datasetMetadata"
        else:
            continue
        entries.append((name, role, os.path.getsize(path)))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<DGED_TableOfContents product="%s" specification='
                 '"DGIWG 250 DGED Product Implementation Profile Ed. 1.2.1" '
                 'generator="dem2dged v%s" created="%s">'
                 % (_xml_escape(product_id), VERSION, datetime.date.today()))
    lines.append('  <folder path=".">')
    for name, role, size in entries:
        lines.append('    <file name="%s" role="%s" sizeBytes="%d"/>'
                     % (_xml_escape(name), role, size))
    lines.append('  </folder>')
    lines.append('</DGED_TableOfContents>')

    toc_path = os.path.join(folder, TOC_FILENAME)
    with open(toc_path, "wt") as f:
        f.write("\n".join(lines) + "\n")
    return toc_path


def write_collection_metadata(folder: str, product_id: str, level: str,
                              epsg: str, bbox_wgs84: Tuple[float, float, float, float],
                              tile_basenames: List[str], sec_class: str,
                              org: str = "") -> str:
    """Write collection-level (series) metadata per DGED spec 6.6 / Annex B.

    A DGED product spanning several tiles is a collection of datasets and
    requires an ESM Collection metadata set with RSTYPE = 'series'.
    """
    west, south, east, north = bbox_wgs84
    today = str(datetime.date.today())
    org_name = org.strip().upper() if org and org.strip() else "Unknown"
    cls_word = CLASSIFICATION_WORDS.get(sec_class, "unclassified")
    tile_kw = "\n".join(
        '          <gmd:keyword><gco:CharacterString>%s</gco:CharacterString></gmd:keyword>'
        % _xml_escape(b) for b in sorted(tile_basenames))

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<gmi:MI_Metadata
  xsi:schemaLocation="urn:dgiwg:xmlns:dmf:2.0:iso-g1:profile:all"
  xmlns:gmi="http://standards.iso.org/iso/19115/-2/gmi/1.0"
  xmlns:gmd="http://www.isotc211.org/2005/gmd"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:gco="http://www.isotc211.org/2005/gco"
  xmlns:gmx="http://www.isotc211.org/2005/gmx"
  xmlns:xlink="http://www.w3.org/1999/xlink">
  <gmd:fileIdentifier>
    <gco:CharacterString>%(pid)s_COLLECTION.xml</gco:CharacterString>
  </gmd:fileIdentifier>
  <gmd:language>
    <gmd:LanguageCode codeList="http://www.isotc211.org/2005/resources/Codelist/ML_gmxCodelists.xml#LanguageCode" codeListValue="eng">eng</gmd:LanguageCode>
  </gmd:language>
  <gmd:characterSet>
    <gmd:MD_CharacterSetCode codeList="http://www.isotc211.org/2005/resources/Codelist/gmxCodelists.xml#MD_CharacterSetCode" codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
  </gmd:characterSet>
  <gmd:hierarchyLevel>
    <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19115/resources/Codelists/cat/codelists.xml#MD_ScopeCode" codeListValue="series">series</gmd:MD_ScopeCode>
  </gmd:hierarchyLevel>
  <gmd:hierarchyLevelName>
    <gco:CharacterString>Collection</gco:CharacterString>
  </gmd:hierarchyLevelName>
  <gmd:contact>
    <gmd:CI_ResponsibleParty>
      <gmd:organisationName><gco:CharacterString>%(org)s</gco:CharacterString></gmd:organisationName>
      <gmd:role>
        <gmd:CI_RoleCode codeList="http://standards.iso.org/iso/19115/resources/Codelists/cat/codelists.xml#CI_RoleCode" codeListValue="pointOfContact">pointOfContact</gmd:CI_RoleCode>
      </gmd:role>
    </gmd:CI_ResponsibleParty>
  </gmd:contact>
  <gmd:dateStamp><gco:Date>%(date)s</gco:Date></gmd:dateStamp>
  <gmd:metadataStandardName><gco:CharacterString>urn:dgiwg:metadata:dmf</gco:CharacterString></gmd:metadataStandardName>
  <gmd:metadataStandardVersion><gco:CharacterString>2.0</gco:CharacterString></gmd:metadataStandardVersion>
  <gmd:referenceSystemInfo>
    <gmd:MD_ReferenceSystem>
      <gmd:referenceSystemIdentifier>
        <gmd:RS_Identifier>
          <gmd:code><gco:CharacterString>http://www.opengis.net/def/crs/EPSG/0/%(epsg_code)s</gco:CharacterString></gmd:code>
        </gmd:RS_Identifier>
      </gmd:referenceSystemIdentifier>
    </gmd:MD_ReferenceSystem>
  </gmd:referenceSystemInfo>
  <gmd:identificationInfo>
    <gmd:MD_DataIdentification>
      <gmd:citation>
        <gmd:CI_Citation>
          <gmd:title><gco:CharacterString>%(pid)s Collection</gco:CharacterString></gmd:title>
          <gmd:date>
            <gmd:CI_Date>
              <gmd:date><gco:Date>%(date)s</gco:Date></gmd:date>
              <gmd:dateType>
                <gmd:CI_DateTypeCode codeList="http://standards.iso.org/iso/19115/resources/Codelists/cat/codelists.xml#CI_DateTypeCode" codeListValue="creation">creation</gmd:CI_DateTypeCode>
              </gmd:dateType>
            </gmd:CI_Date>
          </gmd:date>
        </gmd:CI_Citation>
      </gmd:citation>
      <gmd:abstract><gco:CharacterString>DGED (Defence Gridded Elevation Data) Version 1.2.1 collection of Level %(level)s tiles. Tiling scheme: DGED standard tiling per DGIWG 250 section 13.2. Member tiles are listed in the descriptiveKeywords and in TABLE_OF_CONTENTS.xml.</gco:CharacterString></gmd:abstract>
      <gmd:resourceConstraints>
        <gmd:MD_SecurityConstraints>
          <gmd:classification>
            <gmd:MD_ClassificationCode codeList="http://standards.iso.org/iso/19115/resources/Codelists/cat/codelists.xml#MD_ClassificationCode" codeListValue="%(cls)s">%(cls)s</gmd:MD_ClassificationCode>
          </gmd:classification>
        </gmd:MD_SecurityConstraints>
      </gmd:resourceConstraints>
      <gmd:descriptiveKeywords>
        <gmd:MD_Keywords>
%(tiles)s
          <gmd:thesaurusName>
            <gmd:CI_Citation>
              <gmd:title><gco:CharacterString>DGED Collection member tiles</gco:CharacterString></gmd:title>
              <gmd:date>
                <gmd:CI_Date>
                  <gmd:date><gco:Date>%(date)s</gco:Date></gmd:date>
                  <gmd:dateType>
                    <gmd:CI_DateTypeCode codeList="http://standards.iso.org/iso/19115/resources/Codelists/cat/codelists.xml#CI_DateTypeCode" codeListValue="creation">creation</gmd:CI_DateTypeCode>
                  </gmd:dateType>
                </gmd:CI_Date>
              </gmd:date>
            </gmd:CI_Citation>
          </gmd:thesaurusName>
        </gmd:MD_Keywords>
      </gmd:descriptiveKeywords>
      <gmd:language>
        <gmd:LanguageCode codeList="http://www.isotc211.org/2005/resources/Codelist/ML_gmxCodelists.xml#LanguageCode" codeListValue="eng">eng</gmd:LanguageCode>
      </gmd:language>
      <gmd:topicCategory>
        <gmd:MD_TopicCategoryCode>elevation</gmd:MD_TopicCategoryCode>
      </gmd:topicCategory>
      <gmd:extent>
        <gmd:EX_Extent>
          <gmd:geographicElement>
            <gmd:EX_GeographicBoundingBox>
              <gmd:westBoundLongitude><gco:Decimal>%(west).9f</gco:Decimal></gmd:westBoundLongitude>
              <gmd:eastBoundLongitude><gco:Decimal>%(east).9f</gco:Decimal></gmd:eastBoundLongitude>
              <gmd:southBoundLatitude><gco:Decimal>%(south).9f</gco:Decimal></gmd:southBoundLatitude>
              <gmd:northBoundLatitude><gco:Decimal>%(north).9f</gco:Decimal></gmd:northBoundLatitude>
            </gmd:EX_GeographicBoundingBox>
          </gmd:geographicElement>
        </gmd:EX_Extent>
      </gmd:extent>
    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>
</gmi:MI_Metadata>
""" % {
        "pid": _xml_escape(product_id), "org": _xml_escape(org_name),
        "date": today, "level": _xml_escape(level),
        "epsg_code": _xml_escape(str(epsg).replace("EPSG:", "")),
        "cls": cls_word, "tiles": tile_kw,
        "west": west, "east": east, "south": south, "north": north,
    }

    out_path = os.path.join(folder, "%s_COLLECTION.xml" % product_id)
    with open(out_path, "wt") as f:
        f.write(xml)
    return out_path


def get_extent_and_srs_of_input_raster(rasras: str) -> Tuple[float, float, float, float, Optional[str]]:
    """Get the bounding box and EPSG code of an input raster.

    v0.42: the EPSG code is now required HERE, where the file name is still
    in scope, rather than being allowed through as None and blowing up two
    calls later inside get_bbox_of_output() -- see require_epsg().
    """
    src = gdal_open(rasras)
    if src is None:
        raise FileNotFoundError("GDAL cannot open: %s" % rasras)
    ulx, xres, _, uly, _, yres = src.GetGeoTransform()
    lrx = ulx + src.RasterXSize * xres
    lry = uly + src.RasterYSize * yres
    proj_osgeo = osr.SpatialReference(wkt=src.GetProjection())
    srs = require_epsg(proj_osgeo.GetAttrValue("AUTHORITY", 1), rasras)
    if proj_osgeo.IsGeographic():
        return uly, ulx, lry, lrx, srs
    return ulx, uly, lrx, lry, srs


def get_bbox_of_output(ext: Tuple[float, float, float, float, Optional[str]], srs: int) -> Tuple[float, float, float, float]:
    """Transform extent to target SRS and return bounding box.

    Coordinates are in EPSG AUTHORITY axis order on both sides, so for
    EPSG:4326 the returned tuple is (minLAT, maxLAT, minLON, maxLON) -- which
    is exactly how dem2dged_geo.main() unpacks it. v0.34 sets that strategy
    explicitly instead of relying on it being GDAL 3's default (see the axis
    order note above).
    """
    # v0.42: an untagged / non-EPSG source used to die here as
    # "TypeError: int() argument ... not 'NoneType'". require_epsg() turns
    # that into a message that names the file and says what to do about it.
    source = osr.SpatialReference()
    source.ImportFromEPSG(int(require_epsg(ext[4], "<source raster>")))
    target = osr.SpatialReference()
    target.ImportFromEPSG(srs)
    set_authority_axis_order(source, target)
    transform = osr.CoordinateTransformation(source, target)
    corners = [
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
    return min(xs), max(xs), min(ys), max(ys)


def checkos() -> None:
    """Print operating system info for debugging."""
    dp("OS: %s" % sys.platform)


def fix_header(tif_path: str, epsg_compound: Optional[str]) -> None:
    """Set AREA_OR_POINT=Point and, if epsg_compound is given, re-tag the
    GeoTIFF with that compound CRS (e.g. 'EPSG:4326+3855') using the GDAL
    API directly.

    Pass epsg_compound=None when gdalwarp has ALREADY produced the correct
    (compound) CRS via a real vertical transformation -- in that case we must
    NOT overwrite the projection, only set the Point pixel-is-point flag.

    Metadata-only change: elevation values are not modified.

    NOTE (v0.27): the warp extent is already half-post expanded (see
    tile_warp_extent), so with AREA_OR_POINT=Point the GeoTIFF PixelIsPoint
    tiepoint lands exactly on the tile's first post - readers of either
    convention resolve every sample to a DGED predefined post location.
    """
    ds = gdal_open(tif_path, gdal.GA_Update)
    if ds is None:
        print("WARNING: could not re-open %s to fix header" % tif_path)
        return
    if epsg_compound is not None:
        srs = osr.SpatialReference()
        srs.SetFromUserInput(epsg_compound)
        ds.SetProjection(srs.ExportToWkt())
    ds.SetMetadataItem("AREA_OR_POINT", "Point")
    ds.FlushCache()
    ds = None


# -- Accuracy helpers (v0.20) -------------------------------------------------

def source_gsd_meters(rasras: str) -> float:
    """Approximate the input raster's post spacing (GSD) in metres.

    Geographic sources are in degrees, so the north-south pixel size is
    converted with 1 deg latitude ~= 111 320 m.  Projected sources (UTM etc.)
    are already metric.  Used only to choose a resampler, so an approximation
    is fine.
    """
    src = gdal_open(rasras)
    if src is None:
        raise FileNotFoundError("GDAL cannot open: %s" % rasras)
    _, xres, _, _, _, yres = src.GetGeoTransform()
    proj = osr.SpatialReference(wkt=src.GetProjection())
    if proj.IsGeographic():
        return abs(yres) * 111320.0
    return abs(yres)


def pick_resampler(src_gsd_m: float, dst_gsd_m: float, override: Optional[str] = None) -> str:
    """Choose a gdalwarp resampler from the source-to-target resolution ratio.

    Validator-safe by design (see v0.18/v0.20 changelog): the auto choices
    never overshoot the source's true min/max, so they can't reintroduce the
    cubic "ringing" that failed the 10 m tolerance.

      - ratio > 1.25  (downsampling, target coarser):  'average'
            a mean of the contributing source posts -- always within
            [source min, source max], and reflects ALL source pixels instead
            of bilinear's nearest 2x2 (less aliasing).
      - otherwise      (upsampling / near-equal):       'bilinear'
            no overshoot.  Cubic-family smoothers are NOT auto-selected
            because they can ring past the source extremes.

    Any explicit override (anything other than "auto") always takes
    precedence over the automatic choice above.

    v0.42: the override is checked against VALID_RESAMPLERS first, so a
    typo fails once, here, instead of once per tile inside gdalwarp.
    """
    override = validate_resampler(override)
    if override != "auto":
        return override
    if src_gsd_m and src_gsd_m > 0 and (dst_gsd_m / src_gsd_m) > 1.25:
        return "average"
    return "bilinear"


def resolve_resampler(input_path: str, src_gsd_m: float, dst_gsd_m: float,
                       override: Optional[str], log_fn=print) -> str:
    """Resolve the gdalwarp resampling algorithm for one conversion.

    New in v0.36. This is the single entry point CLI and GUI callers should
    use instead of calling pick_resampler() directly, because it adds one
    more override value pick_resampler() does not understand on its own:
    "optimize" (case-insensitive).

    "auto" (pick_resampler()'s existing default) is a fixed RULE OF THUMB
    based only on the source/target GSD ratio -- it never actually looks at
    how accurately each algorithm reconstructs this particular DEM.
    "optimize" is a MEASUREMENT: it hands off to
    dem2dged_compare.pick_best_resampling(), which runs the same hold-out
    cross-validation as the Resampling Comparison Test directly against the
    source raster (three cheap in-memory warps, no tiles written, no HTML
    report) and returns whichever of Nearest / Bilinear / Cubic reconstructs
    withheld source posts most accurately for THIS input. It costs extra
    time (roughly one read of the source plus three small warps) that
    "auto" does not, which is why it is opt-in rather than the default.

    If the source looks like angular/circular data (see
    looks_like_angular_data() above --  e.g. an aspect or flow-direction
    layer fed in by mistake, or genuinely angular data the caller chose to
    convert anyway via -skip_sanity_check), RMSE is not a meaningful
    accuracy measure across the 0/360 wraparound seam, so the comparison is
    skipped entirely and Nearest Neighbor is returned directly -- see
    dem2dged_compare.pick_best_resampling()'s docstring for why.

    Every override value OTHER than "optimize" (including "auto", None, or
    an explicit algorithm name) is passed straight through to
    pick_resampler() unchanged -- this function only ever adds behaviour,
    it never changes any existing one.

    ``log_fn``: callable(str) for the "optimize" path's progress/result
    lines. Defaults to plain print() for CLI callers; dem2dged_gui.py
    passes its own thread-safe log_fn instead so the lines land in the
    GUI's log box rather than a console window that may not exist in the
    packaged .exe. Unused for every other override value.

    dem2dged_compare is imported lazily (inside the function body) so:
      (a) importing dem2dged_lib never requires numpy / a working GDAL
          Warp() call just to define this function, and
      (b) it avoids a module-load-time circular import, since
          dem2dged_compare.py itself does `from dem2dged_lib import
          VERSION` at its top.
    """
    if not override or str(override).lower() != "optimize":
        return pick_resampler(src_gsd_m, dst_gsd_m, override)

    import dem2dged_compare as _dc

    angular = looks_like_angular_data(input_path)
    alg, _label, _stats_by_alg = _dc.pick_best_resampling(
        input_path, angular=angular, log_fn=log_fn)
    return alg


# dem2dged_geo.py / dem2dged_utm.py both call dl.run_cmd(cmd) with a
# pre-built gdalwarp command and check the returned exit code.
def run_cmd(cmd) -> int:
    """Run the gdalwarp invocation built by dem2dged_geo.py /
    dem2dged_utm.py and return its exit code.

    v0.28: `cmd` is now expected to be an argument LIST, e.g.
    ["gdalwarp", "-te", "1", "2", "3", "4", ...], run with shell=False
    (the subprocess default -- no shell is even spawned). Earlier versions
    built one big shell-formatted string ('gdalwarp %s ... "%s" "%s"' with
    paths substituted into quotes) and ran it with shell=True. That pattern
    is fragile and, for input/output paths that are attacker- or
    user-influenced, a potential command-injection vector: any path
    containing a double quote, backtick, $(...), or (on Windows) an
    "&"/"|"/"^" character could break out of the intended quoting instead
    of being treated as a literal filename. Passing an argument list to
    subprocess.run() with shell=False hands each element straight to the
    OS's process-exec call, so no shell ever parses the paths and no
    quoting is needed (or possible to get wrong) at all.

    A bare string is still accepted for backward compatibility -- it is
    run through the shell exactly as before, but logs a warning, since any
    remaining caller using this form should be updated to build a list.

    v0.42: with shell=False, a missing gdalwarp makes subprocess.run()
    raise FileNotFoundError, which propagated out of the tile loop as a raw
    traceback on the very first tile. The callers' contract is "returns an
    exit code", so that is what happens now -- 127, the conventional
    "command not found" status -- and require_gdalwarp() is what produces
    the readable, actionable message, once, before any tile is attempted.
    """
    try:
        if isinstance(cmd, str):
            dp("WARNING: run_cmd() called with a shell command string instead "
               "of an argument list -- update the caller to pass a list. "
               "Running via the shell for backward compatibility.")
            return subprocess.run(cmd, shell=True).returncode
        return subprocess.run(cmd, shell=False).returncode
    except FileNotFoundError as e:
        print("ERROR: could not execute %r (%s). Is GDAL on PATH?"
              % (cmd[0] if not isinstance(cmd, str) else cmd.split()[0], e))
        return 127
    except OSError as e:
        print("ERROR: could not execute the gdalwarp command (%s)" % e)
        return 126

# end of dem2dged_lib.py
