# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.41
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

r"""
dem2dged_validate.py  –  Automated validator for DGED tile sets
produced by dem2dged (GEO or UTM).

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON


Changelog
    0.41  REPAIR RELEASE. The v0.40 cut of this file was missing an entire
          block between the end of the module docstring and overall_result()'s
          body: the docstring's closing quotes, EVERY import (os, sys, re,
          glob, math, argparse, numpy, xml.etree, osgeo.gdal/osr and the
          dem2dged_lib names), the NODATA / ELEV_MIN_SANE / ELEV_MAX_SANE
          constants, _STATUS_ORDER, the GEO_RE / UTM_RE filename patterns and
          the "def overall_result(...)" line itself. Python therefore read the
          whole module docstring as unterminated up to overall_result()'s own
          docstring, and the file did not even byte-compile:
          "IndentationError: unexpected indent (line 247)". Nothing that
          imports the validator worked -- dem2dged.py's auto-validation
          silently degraded to "could not import dem2dged_validate", the GUI's
          "Validate after conversion" checkbox was permanently disabled,
          audit_pure.py could not run at all, and dem2dged_validate.exe could
          not be built. The block is restored; GEO_RE / UTM_RE were rebuilt
          from spec 12.1 and re-verified against dem2dged_lib.geo_tile_
          basename() / utm_tile_basename() output for every product level,
          both hemispheres, all UTM zone forms and with/without the optional
          organisation code, plus negative cases (see audit_pure.py sections
          1, 3 and 7b). No behavioural change is intended relative to the
          v0.39 validator.
    0.40  Verification re-cut of v0.39; no validator logic change.
          Re-audited and re-run end to end (19/19); the v0.39 Section H
          geoid fix and the source-type WARN are carried forward.
    0.39  First public beta (project-wide review pass).
          (1) SECTION H GEOID FALSE-POSITIVE (found by the v0.39 beta
          verification run on inland Lebanon). check_source() re-warped the
          source to the tiles' COMPOUND CRS (EPSG:<horiz>+3855) for the H
          global-stats and H2 sample-window comparisons. Warping a source to
          a compound +EGM2008 CRS makes GDAL apply an ellipsoidal->EGM2008
          vertical (geoid) transform to the source -- a shift of the local
          geoid height, ~25 m over Lebanon -- even though the converter's
          DEFAULT vertical handling (no -source_vertical) applies NO such
          transform to the tiles (it warps horizontally and only re-tags the
          +3855 label). So a correct bilinear near-native delivery was
          compared against a source baseline shifted by the geoid height and
          FAILED H/H2 on min/max/mean and every sample window, uniformly, by
          ~that geoid height -- not a real defect. Both re-warps now strip
          the vertical and compare in the tiles' HORIZONTAL CRS only (a pure
          terrain-shape comparison, matching how the tile values were
          actually produced). Affects any source without an explicit vertical
          datum -- i.e. SRTM and most real DEMs -- in any region where the
          geoid height is non-trivial, which is why the DGIWG test set (used
          for the v0.37/v0.38 H work) never surfaced it.
          (2) A reserved or unknown source-type code in a tile name now
          raises a WARN (not a FAIL). Spec 12.1 defines the valid source
          codes and reserves D/E/I/J/Q/R/S/W/Z; the name still parses and the
          tile is otherwise fine (metadata prevails over the filename per
          12.1), so this is advisory only. Uses the same
          dem2dged_lib.describe_source_type() the CLI converters warn with,
          so validator and converter agree.
          The converter-side changes for this release (data-type-aware
          GeoTIFF LZW predictor: PREDICTOR=3 for Float32, 2 for Int16; and
          the UTM negative-northing clamp) need nothing else here -- the
          header check verifies COMPRESS=LZW (unchanged, both predictors
          lossless) and the name-width check already rejected the old
          negative northing.
    0.38  Two bugs, both found only after v0.37 got its first real (real
          GDAL, real CLI) run:
          (1) Report._emit() (used by every WARN/FAIL/PASS line and every
          section() header) unconditionally print()ed to the real console
          in addition to recording the line for the report file. Found by
          actually running the CLI end to end with stdout redirected to a
          log file on Windows: the box-drawing section headers aren't
          encodable under a legacy console code page (cp1252), so print()
          raised UnicodeEncodeError, which propagated up through
          run_validation() and made dem2dged.py's auto-validation
          try/except silently skip writing BOTH report files -- even
          though validation itself had already completed. _emit() now
          falls back to a best-effort re-encode of just the console echo
          on that error; the report content itself (self.lines) was never
          affected.
          (2) With that fixed and reports actually being written, both
          real cubic-convolution runs on the DGIWG test set FAILED Section
          H (global min/max) on what turned out to be a validator-side
          artifact, not a real defect. check_source()'s H/H2 checks build
          their own internal re-warp of the source using the tiles' actual
          resample algorithm (the v0.37 Finding 2 fix, above) as a like-
          for-like comparison baseline -- but that internal re-warp was
          never clamped the way the real delivered tiles are (Finding 3,
          dem2dged_lib.clamp_tile_to_range()). So an overshoot-prone
          resampler produced a delivered tile correctly clamped to the
          source's true range, compared against an internal baseline that
          was still overshooting -- e.g. ACAIPGTM: tiles correctly at
          0.00..255.00 m, H's comparison baseline at -18.33..274.21 m,
          reported as a 18-19 m "defect" that was really just "clamped vs
          unclamped". check_source() now computes the same clamp range the
          converters use (dem2dged_lib.compute_tile_stats() on the source)
          whenever ``resample`` is overshoot-prone, and applies it to both
          H's global-stats re-warp and H2's per-window re-warp before
          comparing -- so both sides of the comparison reflect the same
          intended (clamped) product.
    0.37  Fixes for Findings 2 and 4 of DGED_Conversion_Review.md (an
          independent audit of a 9-run/42-tile DGIWG test-data conversion
          batch; Findings 1 and 3 are converter-side, see dem2dged_lib.py):
          (1) Sections H/H2 (source comparison) re-warped the source DEM
              for comparison as Bilinear UNCONDITIONALLY, regardless of
              what the tiles being validated were actually produced with,
              despite a code comment claiming the two matched. check_
              source() and run_validation() now take a ``resample``
              argument (default "bilinear", the old hardcoded value, so
              every existing caller keeps working unchanged); dem2dged.py
              and dem2dged_gui.py now pass the real algorithm used. New
              CLI flag -resample/--resample for validating an existing
              delivery standalone.
          (2) The "RESULT:" line in the text report used a 2-tier PASS/
              FAIL rule (ignoring warnings) while the HTML per-dataset
              badge used a 3-tier FAIL > WARN > PASS rule -- identical
              PASS=/WARN=/FAIL= counts for one run could read "PASS" in
              the .txt report and show "WARN" in the HTML report for that
              same run. Both now call the new overall_result(), the one
              shared rule (dem2dged_gui.py's badges/log lines call it too).
          (3) Optional polish: H2's three sample windows are now coverage-
              aware -- a cheap, heavily decimated read of the tile mosaic
              nudges a fixed window position to the nearest one that
              actually has data, instead of a routine "no overlapping
              valid data" WARN whenever a delivery's real footprint
              doesn't fill its bounding box evenly.
    0.35  This module's own docstring (the one you're reading) is now a raw
          string. It previously held its "\d+" / "\d{1,7}" changelog prose
          in a plain triple-quoted string, which is a deprecated escape
          sequence in Python (SyntaxWarning: invalid escape sequence '\d'
          on 3.12+). Cosmetic only -- GEO_RE / UTM_RE below were already
          correctly built with raw strings and never printed a warning;
          only this descriptive text did.
    0.34  (1) UTM filename field WIDTHS are now checked (new check under B).
          Spec 12.1 defines the coordinate subfields as fixed-width and
          zero-padded -- nnnn/eee for the km-form levels 4b-6, nnnnmmm/
          eeemmm for the metre-form levels 7-9 -- but UTM_RE matched
          "\d+", so any width passed. dem2dged_lib.utm_tile_basename()
          was emitting short fields for every northing below 1 000 000 m
          (i.e. within ~9 degrees of the equator), and this validator
          happily accepted them: converter and validator were consistently
          wrong together, which is exactly the failure mode the v0.28
          fallback-table removal was meant to prevent. The widths now come
          from dem2dged_lib.utm_name_field_widths(), the same function the
          converter formats with, so the two cannot disagree. The pattern
          itself stays permissive (\d{1,7}) on purpose, so a pre-v0.34
          short name gets a precise "northing field '500' is 3 digits,
          spec 12.1 requires 4" message instead of an opaque "filename
          does not match DGED naming convention".
          (2) -html-report / -max-diff / -src / -report / -verbose now also
          accept the double-dash spelling. VALIDATOR_VERSION.txt documented
          "--html-report", which argparse rejected outright as an
          unrecognised argument.
    0.32  Version bump (validator logic unchanged). See dem2dged_lib.py's
          changelog for what this release actually changed: the "Version:
          0.29" header comments in dem2dged.py / dem2dged_geo.py /
          dem2dged_utm.py and dem2dged_gui.py's APP_VERSION fallback had
          drifted behind dem2dged_lib.VERSION during the v0.30/v0.31
          validator-only releases; all resynchronised to 0.32. The
          whole-tool packaging script (dem2dged_package_v0.26.py) also now
          excludes build artefacts and prior release zips instead of
          bundling the entire project folder verbatim.
    0.31  Two more false-positive fixes, found auditing a real conversion
          run: (1) The "name says origin X but georef is Y" check (D)
          compared the raw raster corner against the nominal tile origin
          with a half-pixel tolerance -- but the v0.27 half-post warp
          extent deliberately puts the corner half a pixel before the
          origin (so pixel CENTERS land on DGED posts), which sat exactly
          on that tolerance boundary and failed every correctly generated
          tile. Now compares the pixel center (see the new
          _origin_close()) with a tiny fractional-pixel tolerance instead,
          in both the GEO and UTM branches. (2) The "unreplaced
          {{placeholder}}" check (E) was a bare "{{" substring search,
          which matched the DGED template's own header comment ("
          Placeholders ({{...}}) are replaced per tile...") on every
          single tile regardless of whether the real {{KEY}} placeholders
          had been substituted. Now matches real placeholder syntax only
          (see the new _has_unreplaced_placeholder()).
    0.30  File pairing (A) no longer flags TABLE_OF_CONTENTS.xml or
          <product>_COLLECTION.xml as "missing .tif". Both are delivery-level
          metadata written once per product (spec 12.1 / 6.6), not per-tile
          sidecars, so they never had a matching .tif -- every real delivery
          that included them failed check A even though the tiles themselves
          were correctly paired. This was a validator false positive, not a
          conversion bug. The check now recognises both by the same name
          test dem2dged_lib.write_toc_file() already uses (see the new
          is_product_level_xml() below), so the two can't drift apart.
    0.28  Brought the validator back in sync with the v0.27 converter changes
          it had drifted from: (1) the data-type check (C) is now level-aware
          -- Int16 is required and PASSES for levels 0-2, Float32 for level 3
          and up, instead of hard-failing every Int16 tile. (2) The filename
          patterns (B) now accept the current spec-form level 0-3 names (no
          "Gt<letter>" segment) as well as the pre-v0.27 legacy form, and an
          optional producer-organisation code segment in any level. (3) The
          hand-copied fallback DGED tables (used only if the import from
          dem2dged_lib failed) are removed -- they had already silently
          drifted out of sync for GEO levels 8-9. A missing/broken
          dem2dged_lib.py now fails loudly with a clear message instead of
          validating against stale numbers. (4) The "what this means" text
          for a data-type mismatch is level-aware instead of assuming
          Float32 is always correct.
    0.26  Version bump alongside the GUI window-layout fix (validator logic
          unchanged). See dem2dged_lib.py for the full changelog.
    0.25  Version bump for the tool-wide bug-fix pass (validator logic
          unchanged). See dem2dged_lib.py for the full changelog.
    0.24  Detailed per-tile PASS/WARN/FAIL criteria table added to the HTML
          validation report (Feature #2).
    0.21  HTML report now attaches a plain-language "What this means"
          explanation (with the likely cause and fix) under every WARN and
          FAIL finding, plus a one-line intro describing each check section.
          Console/text output is unchanged.

Usage:
    python dem2dged_validate.py <tile_folder> [options]

    Every option accepts BOTH the single-dash and the double-dash spelling
    (v0.34), e.g. "-html-report" and "--html-report" are equivalent.

    -src  SOURCE_DEM    Original input DEM: enables coverage, statistics
                        and sample-window difference checks against the source
    -report FILE        Also write the full report to a text file
    -html-report FILE   Also write a styled HTML report to this file
    -max-diff METRES    Tolerance for the sample-window comparison vs the
                        source (default 5.0 m; resampling is bilinear, so small
                        differences are expected and normal)
    -verbose            Print every per-tile detail, not just problems

What is checked
---------------
A. File pairing        every .tif has an .xml sidecar and vice versa
B. Filename            parses per DGED naming convention; tile letter matches
                       the product level; UTM coordinate subfields are
                       zero-padded to the spec 12.1 widths; coordinates
                       encoded in the name match the actual georeferencing
C. GeoTIFF header      Data type per level (Int16 for levels 0-2, Float32 for
                       level 3+), NoData=-32767, AREA_OR_POINT=Point,
                       LZW compression, CRS + EGM2008 (EPSG:3855) tag
D. Grid geometry       pixel size == level GSD, raster dimensions == expected
                       posts (incl. the one-post overlap), tile origin aligned
                       to the DGED tile grid
E. XML sidecar         well-formed, no unreplaced {{PLACEHOLDERS}}, basename /
                       level / EPSG consistent with the tile
F. Statistics          elevation range sanity, NoData handling (no "-32767 m
                       trenches" leaking into valid data)
G. Edge overlap        shared row/column between adjacent tiles must be
                       IDENTICAL — catches half-pixel shifts and row/column
                       indexing bugs
H. Source comparison   (-src) mosaic covers the source extent; min/max/mean
                       within tolerance; pixel-level |diff| in sample windows

Exit code: 0 = all checks passed (warnings allowed), 1 = at least one FAIL.
"""

import argparse
import glob
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np

try:
    from osgeo import gdal, osr
except ImportError as _gdal_err:            # pragma: no cover - environment
    sys.exit("ERROR: GDAL/osgeo is not available in this Python environment "
             "(%s).\nInstall it (conda install -c conda-forge gdal) and try "
             "again." % _gdal_err)

# v0.28: the hand-copied fallback DGED tables are gone on purpose. The
# validator must measure a delivery against the SAME tables and the SAME
# name-formatting helpers the converters used, or the two silently drift
# apart and agree on something that is wrong (exactly what happened for
# GEO levels 8-9 before v0.28, and for the UTM field widths before v0.34).
# So a missing/broken dem2dged_lib.py is a hard, loud error -- never a
# quiet fall back to stale numbers.
try:
    from dem2dged_lib import (
        VERSION,
        VERSION_DISPLAY,
        PL,
        level_tilesize_and_spatial_resolution,
        zone_lon_spacing,
        output_type_for_level,
        utm_name_field_widths,
        describe_source_type,
        compute_tile_stats,
        OVERSHOOT_PRONE_RESAMPLERS,
        TOC_FILENAME,
        gdal_open,
    )
except ImportError as _lib_err:             # pragma: no cover - install error
    sys.exit("ERROR: cannot import dem2dged_lib.py (%s).\n"
             "dem2dged_validate.py validates against the DGED tables and the\n"
             "filename helpers defined there, so it deliberately refuses to\n"
             "run without them rather than check a delivery against a stale\n"
             "hand-copied copy. Keep dem2dged_lib.py next to this script."
             % _lib_err)

# -- Constants ----------------------------------------------------------------

# DGED NoData value (spec 13.1; also the value the converters pass to
# gdalwarp -dstnodata and the GUI passes as dstNodata).
NODATA = -32767

# Plausible real-world elevation band, in metres. Deliberately generous on
# both sides of the true extremes (Dead Sea shore ~ -430 m, Everest 8849 m):
# this check exists to catch the -32767 NoData marker leaking into valid
# data ("-32767 m trenches"), not to police unusual-but-real terrain.
ELEV_MIN_SANE = -500.0
ELEV_MAX_SANE = 9000.0

# Ranking used to collapse several per-category results into one status.
_STATUS_ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}

# -- DGED filename patterns (spec 12.1) ---------------------------------------
#
# GEO   DGEDL<lv>[Gt<letter>]_[ORG_]<coord>_<S>_<c>_<vv>
#         levels 0-3   short form, whole degrees      27N056E
#         levels 4b-6  degrees+minutes                5530N01212E
#         levels 7-9   degrees+minutes+seconds        553012N0121230E
#       The "Gt<letter>" segment is optional so BOTH the current level 0-3
#       short form (which omits it entirely) and the pre-v0.27 legacy form
#       (which carried it) parse; check_tile() then enforces the right
#       letter for the level, so a wrong letter is still a FAIL.
#
# UTM   DGEDL<lv>Ut<letter>_[ORG_]<ZZh><northing>_<easting>_<S>_<c>_<vv>
#       The zone is always two digits plus N/S (dem2dged_lib.utm_tile_
#       basename formats it "%02d%s"), so <ZZh> and the northing that
#       follows it are unambiguous even though nothing separates them.
#
# v0.34: the northing/easting subfields stay permissive (\d{1,7}) ON PURPOSE.
# Spec 12.1 requires fixed, zero-padded widths, but enforcing them in the
# pattern would reduce a pre-v0.34 short name to an opaque "does not match
# DGED naming convention". Letting it parse means check_tile() can report
# "northing field '500' is 3 digit(s), spec 12.1 requires 4" instead. The
# widths themselves come from dem2dged_lib.utm_name_field_widths(), the same
# helper the converter formats with, so the two cannot disagree.
_LEVEL_PAT = r"(?:4b|\d)"
_ORG_PAT = r"(?:(?P<org>[A-Z]{3})_)?"
_TAIL_PAT = r"_(?P<src>[A-Za-z])_(?P<cls>[A-Za-z])_(?P<ver>\d{2})$"

GEO_RE = re.compile(
    r"^DGEDL(?P<lv>" + _LEVEL_PAT + r")"
    r"(?:Gt(?P<letter>[A-Za-z]))?_"
    + _ORG_PAT +
    r"(?P<lat>\d{2}(?:\d{2}){0,2})(?P<hemi>[NS])"
    r"(?P<lon>\d{3}(?:\d{2}){0,2})(?P<east>[EW])"
    + _TAIL_PAT)

UTM_RE = re.compile(
    r"^DGEDL(?P<lv>" + _LEVEL_PAT + r")"
    r"Ut(?P<letter>[A-Za-z])_"
    + _ORG_PAT +
    r"(?P<zone>\d{2}[NS])"
    r"(?P<northing>\d{1,7})_"
    r"(?P<easting>\d{1,7})"
    + _TAIL_PAT)


def overall_result(n_pass, n_warn, n_fail):
    """The one PASS/WARN/FAIL rule for a validation run's overall status.

    v0.37 fix for DGED_Conversion_Review.md Finding 4: this single 3-tier
    rule (FAIL if any check failed, else WARN if any check warned, else
    PASS) is now used everywhere an overall status is shown -- the text
    report's "RESULT:" line, the HTML report's per-dataset badge, and
    dem2dged_gui.py's Resampling Comparison badge. Previously the text
    report used a DIFFERENT, 2-tier rule (PASS/FAIL only, ignoring
    warnings), so the exact same PASS=/WARN=/FAIL= counts for one run
    could read "RESULT: PASS" in the .txt report and show a "WARN" badge
    in the HTML report for that same run.
    """
    if n_fail:
        return "FAIL"
    if n_warn:
        return "WARN"
    return "PASS"

# Fixed set of per-tile criteria columns shown in the detailed validation
# table (v0.24 — Feature #2). Order here is the display order of the table.
TILE_CHECK_CATEGORIES = [
    ("filename",   "Filename"),
    ("gsd",        "GSD"),
    ("bounds",     "Bounds"),
    ("nodata",     "NoData"),
    ("crs",        "CRS / Vertical"),
    ("data_type",  "Data Type"),
    ("metadata",   "Metadata"),
]


class Report:
    def __init__(self, verbose=False):
        self.lines, self.n_pass, self.n_warn, self.n_fail = [], 0, 0, 0
        self.verbose = verbose
        # Per-tile, per-criterion status used to build the detailed table
        # (v0.24 — Feature #2). tile_checks[base][category] = "PASS"/"WARN"/"FAIL"
        # (worst status recorded wins if a category is checked more than once).
        self.tile_checks = {}
        self.tile_order = []   # tile base names in first-seen order

    def _record(self, tile, cat, status):
        if not tile or not cat:
            return
        if tile not in self.tile_checks:
            self.tile_checks[tile] = {}
            self.tile_order.append(tile)
        cur = self.tile_checks[tile].get(cat)
        if cur is None or _STATUS_ORDER[status] > _STATUS_ORDER[cur]:
            self.tile_checks[tile][cat] = status

    def _emit(self, line):
        self.lines.append(line)
        try:
            print(line)
        except UnicodeEncodeError:
            # v0.38: on a Windows console (or stdout redirected to a file,
            # e.g. "> log.txt 2>&1") using a legacy code page such as
            # cp1252, the box-drawing section-header characters section()
            # builds below aren't encodable, and an unguarded print() here
            # raised UnicodeEncodeError -- confirmed in practice running
            # the real CLI end to end ("'charmap' codec can't encode
            # characters in position 0-1"). That exception propagated all
            # the way up through run_validation() into dem2dged.py's
            # auto-validation try/except, which silently skipped writing
            # BOTH report files even though every check had already
            # finished -- self.lines (the actual report content, written to
            # disk by write_text_report()/write_html_report()) was never
            # affected, only this live console echo. Degrade gracefully
            # instead of losing the whole report: best-effort re-encode for
            # whatever the console can actually display.
            enc = sys.stdout.encoding or "ascii"
            print(line.encode(enc, errors="replace").decode(enc))

    def ok(self, msg, tile=None, cat=None):
        self.n_pass += 1
        if self.verbose:
            self._emit("  PASS  " + msg)
        self._record(tile, cat, "PASS")

    def warn(self, msg, tile=None, cat=None):
        self.n_warn += 1
        self._emit("  WARN  " + msg)
        self._record(tile, cat, "WARN")

    def fail(self, msg, tile=None, cat=None):
        self.n_fail += 1
        self._emit("  FAIL  " + msg)
        self._record(tile, cat, "FAIL")

    def section(self, title):
        self._emit("")
        self._emit("── %s " % title + "─" * max(0, 66 - len(title)))

    def tile_overall(self, tile):
        """Worst status across every recorded category for one tile."""
        cats = self.tile_checks.get(tile)
        if not cats:
            return None
        worst = "PASS"
        for status in cats.values():
            if _STATUS_ORDER[status] > _STATUS_ORDER[worst]:
                worst = status
        return worst


# ── helpers ───────────────────────────────────────────────────────────────────

def dms_to_deg(digits, is_lat):
    """'5536' → 55.6°  |  '553630' → 55.6083°  (deg / deg+min / deg+min+sec)"""
    dlen = 2 if is_lat else 3
    d = int(digits[:dlen]); rest = digits[dlen:]
    m = int(rest[:2]) if len(rest) >= 2 else 0
    s = int(rest[2:4]) if len(rest) >= 4 else 0
    return d + m / 60.0 + s / 3600.0


def lon_multi(lat):
    m = 1
    for z in zone_lon_spacing:
        if lat >= z[1]:
            m = z[4]
    return m


def geo_level_params(lv):
    for l in level_tilesize_and_spatial_resolution:
        if l[0] == lv:
            return l[1] / 60.0, l[2] / 3600.0, l[3]
    return None


def utm_level_params(lv):
    for l in PL:
        if l[0] == lv:
            return l[1], l[2], l[3]
    return None


def read_band(ds):
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype(np.float64)
    nod = band.GetNoDataValue()
    mask = np.ones(arr.shape, bool) if nod is None else ~np.isclose(arr, nod)
    return arr, mask, nod


def _origin_close(center, nominal, res):
    """True if a raster's pixel-center coordinate matches the nominal DGED
    tile origin, within a tiny fraction of one pixel (v0.31).

    Tile rasters are warped with a half-post EXPANDED extent (v0.27,
    dem2dged_lib.tile_warp_extent): the geotransform corner GDAL reports
    sits exactly half a pixel before the nominal origin BY DESIGN, so it is
    the pixel CENTER -- not the raw corner -- that is supposed to land on
    the origin (spec 6.3, AREA_OR_POINT=Point). Comparing the raw corner
    to the origin with a half-pixel tolerance sits exactly on that designed
    gap and fails every correctly generated tile; comparing the pixel
    center instead, with a tolerance that is a tiny fraction of a pixel
    (not half of one), checks what the spec actually requires while still
    catching a real half-pixel-or-larger misalignment bug.
    """
    return math.isclose(center, nominal, rel_tol=1e-9, abs_tol=abs(res) * 1e-6)


_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def _has_unreplaced_placeholder(txt):
    """True if real template placeholder syntax ({{BASENAME}}, {{ABS_HACC}},
    ...) is still present in an XML sidecar, i.e. template substitution did
    not complete for this tile (v0.31).

    Deliberately NOT a bare "{{" substring search: the DGED_*_TEMPLATE.xml
    header comment says, verbatim, "Placeholders ({{...}}) are replaced per
    tile at conversion time" to document the mechanism -- a substring
    search flagged that explanatory prose as an unreplaced placeholder on
    every single tile, regardless of whether the real {{KEY}} placeholders
    were substituted. Real placeholders are always an uppercase
    identifier in braces, which "{{...}}" (three literal dots) is not.
    """
    return bool(_PLACEHOLDER_RE.search(txt))


# ── per-tile checks ───────────────────────────────────────────────────────────

def check_tile(tif, rep, folder):
    base = os.path.splitext(os.path.basename(tif))[0]
    m_geo, m_utm = GEO_RE.match(base), UTM_RE.match(base)

    # B. filename
    if not (m_geo or m_utm):
        rep.fail("%s: filename does not match DGED naming convention" % base,
                  tile=base, cat="filename")
        return None
    m = m_geo or m_utm
    mode = "geo" if m_geo else "utm"
    lv = m.group("lv")
    params = geo_level_params(lv) if mode == "geo" else utm_level_params(lv)
    if params is None:
        rep.fail("%s: level '%s' invalid for %s mode" % (base, lv, mode.upper()),
                  tile=base, cat="filename")
        return None
    letter_expected = params[2]
    letter_seen = m.group("letter")
    if mode == "geo" and lv in ("0", "1", "2", "3"):
        # Current spec form omits the tile-size letter for L0-3 entirely
        # (letter_seen is None); a pre-v0.27 file may still carry it, in
        # which case it must still be the right one.
        letter_ok = letter_seen in (None, letter_expected)
    else:
        letter_ok = letter_seen == letter_expected
    if not letter_ok:
        rep.fail("%s: tile letter '%s' but level %s requires '%s'"
                 % (base, letter_seen, lv, letter_expected),
                  tile=base, cat="filename")
    else:
        rep.ok("%s: filename OK" % base, tile=base, cat="filename")

    # B1b. Source-type code (spec 12.1) -- v0.39. Advisory: the name already
    # parsed, so this never fails; it only flags a code that is reserved
    # (D/E/I/J/Q/R/S/W/Z) or not one of the spec's defined source letters, so
    # a non-standard delivery is visible rather than silent. Uses the same
    # dem2dged_lib.describe_source_type() the CLI converters warn with.
    _src_letter = m.group("src")
    _st_ok, _st_msg = describe_source_type(_src_letter)
    if not _st_ok:
        rep.warn("%s: %s" % (base, _st_msg), tile=base, cat="filename")

    # B2. UTM coordinate subfield widths (spec 12.1) -- v0.34.
    # The widths come from dem2dged_lib.utm_name_field_widths(), the same
    # function dem2dged_lib.utm_tile_basename() formats with, so this check
    # and the converter can't drift apart. Before v0.34 UTM_RE matched \d+
    # and nothing checked the width, so the converter's unpadded fields
    # (every northing below 1 000 000 m) passed validation unnoticed.
    if mode == "utm":
        n_want, e_want = utm_name_field_widths(lv)
        n_seen, e_seen = m.group("northing"), m.group("easting")
        width_problems = []
        if len(n_seen) != n_want:
            width_problems.append(
                "northing field '%s' is %d digit(s), spec 12.1 requires %d "
                "(zero-padded)" % (n_seen, len(n_seen), n_want))
        if len(e_seen) != e_want:
            width_problems.append(
                "easting field '%s' is %d digit(s), spec 12.1 requires %d "
                "(zero-padded)" % (e_seen, len(e_seen), e_want))
        if width_problems:
            rep.fail("%s: %s -- regenerate with dem2dged v0.34+ "
                     "(names produced before v0.34 were not zero-padded)"
                     % (base, "; ".join(width_problems)),
                     tile=base, cat="filename")
        else:
            rep.ok("%s: UTM name field widths %d/%d match spec 12.1"
                   % (base, n_want, e_want), tile=base, cat="filename")

    # v0.41: a corrupt or truncated .tif used to kill the ENTIRE validation
    # run. The try/except here looks like it covers that, but it did not:
    # with GDAL exceptions off (the state the standalone CLI ran in) a bad
    # file makes gdal.Open return None rather than raise, so the None fell
    # straight through to ds.GetGeoTransform() on the next line and the run
    # died with an AttributeError instead of reporting one bad tile.
    # dem2dged_lib.gdal_open() gives the same "returns None" answer whichever
    # way GDAL is configured; the except is kept for anything else that can
    # go wrong. An unreadable tile is a FAIL for that tile and nothing more.
    try:
        ds = gdal_open(tif)
    except Exception as e:
        rep.fail("%s: cannot open (%s)" % (base, e), tile=base, cat="filename")
        return None
    if ds is None:
        rep.fail("%s: cannot open -- not a readable GeoTIFF (corrupt, "
                 "truncated, or not an image at all)" % base,
                 tile=base, cat="filename")
        return None

    gt = ds.GetGeoTransform()
    xres, yres = gt[1], abs(gt[5])
    ulx, uly = gt[0], gt[3]
    lrx = ulx + ds.RasterXSize * gt[1]
    lry = uly + ds.RasterYSize * gt[5]
    minx, maxx = min(ulx, lrx), max(ulx, lrx)
    miny, maxy = min(uly, lry), max(uly, lry)

    # C. header
    # Data type is level-dependent (spec section 7): Int16 is MANDATORY for
    # levels 0-2, Float32 for level 3 and up -- not "always Float32".
    band = ds.GetRasterBand(1)
    expected_dtype = output_type_for_level(lv)
    actual_dtype = gdal.GetDataTypeName(band.DataType)
    if actual_dtype != expected_dtype:
        rep.fail("%s: data type is %s, expected %s for level %s"
                 % (base, actual_dtype, expected_dtype, lv),
                  tile=base, cat="data_type")
    else:
        rep.ok("%s: %s (correct for level %s)" % (base, actual_dtype, lv),
                tile=base, cat="data_type")

    nod = band.GetNoDataValue()
    if nod is None or not math.isclose(nod, NODATA, abs_tol=0.5):
        rep.fail("%s: NoData is %s, expected %s" % (base, nod, NODATA),
                  tile=base, cat="nodata")
    else:
        rep.ok("%s: NoData=-32767" % base, tile=base, cat="nodata")

    aop = ds.GetMetadataItem("AREA_OR_POINT")
    if (aop or "").upper() != "POINT":
        rep.fail("%s: AREA_OR_POINT=%s, expected Point (DGED requirement)"
                 % (base, aop), tile=base, cat="metadata")
    else:
        rep.ok("%s: AREA_OR_POINT=Point" % base, tile=base, cat="metadata")

    comp = ds.GetMetadataItem("COMPRESSION", "IMAGE_STRUCTURE")
    if comp != "LZW":
        rep.warn("%s: compression is %s, DGED profile uses LZW" % (base, comp),
                  tile=base, cat="metadata")
    else:
        rep.ok("%s: LZW compression" % base, tile=base, cat="metadata")

    wkt = ds.GetProjection() or ""
    if "3855" in wkt or "EGM2008" in wkt.upper() or "EGM_2008" in wkt.upper():
        rep.ok("%s: EGM2008 vertical CRS tag present" % base, tile=base, cat="crs")
    else:
        rep.warn("%s: EGM2008 (EPSG:3855) tag not found in CRS" % base,
                  tile=base, cat="crs")

    srs = osr.SpatialReference(wkt=wkt)
    epsg_h = None
    try:
        srs2 = srs.Clone()
        if srs2.IsCompound():
            # first sub-CRS is the horizontal one
            epsg_h = srs2.GetAuthorityCode("PROJCS") or srs2.GetAuthorityCode("GEOGCS")
        else:
            epsg_h = srs2.GetAuthorityCode(None)
    except Exception:
        pass

    # D. grid geometry + name/georef cross-check
    if mode == "geo":
        tiledim, latres, _ = params
        lat0 = dms_to_deg(m.group("lat"), True) * (-1 if m.group("hemi") == "S" else 1)
        lon0 = dms_to_deg(m.group("lon"), False) * (-1 if m.group("east") == "W" else 1)
        lonres = lon_multi(lat0) * latres
        exp_w = round(tiledim / lonres) + 1
        exp_h = round(tiledim / latres) + 1
        if not (math.isclose(xres, lonres, rel_tol=1e-6)
                and math.isclose(yres, latres, rel_tol=1e-6)):
            rep.fail("%s: pixel size %.6g×%.6g°, expected %.6g×%.6g°"
                     % (base, xres, yres, lonres, latres), tile=base, cat="gsd")
        else:
            rep.ok("%s: pixel size matches level %s" % (base, lv), tile=base, cat="gsd")
        center_x, center_y = minx + xres / 2.0, miny + yres / 2.0
        if not (_origin_close(center_x, lon0, lonres)
                and _origin_close(center_y, lat0, latres)):
            rep.fail("%s: name says origin (%.4f, %.4f) but georef is (%.4f, %.4f)"
                     % (base, lon0, lat0, center_x, center_y), tile=base, cat="bounds")
        else:
            rep.ok("%s: filename coordinates match georeferencing" % base,
                    tile=base, cat="bounds")
        if abs((lat0 / tiledim) - round(lat0 / tiledim)) > 1e-6 or \
           abs((lon0 / tiledim) - round(lon0 / tiledim)) > 1e-6:
            rep.fail("%s: origin not aligned to %g° tile grid" % (base, tiledim),
                      tile=base, cat="bounds")
        else:
            rep.ok("%s: aligned to tile grid" % base, tile=base, cat="bounds")
    else:
        gsd, posts, _ = params
        tiledim = (posts - 1) * gsd
        north0 = int(m.group("northing")) * (1000 if lv in ("4b","4","5","6") else 1)
        east0  = int(m.group("easting"))  * (1000 if lv in ("4b","4","5","6") else 1)
        exp_w = exp_h = posts

        # B (cont.). Coordinate subfield WIDTHS (spec 12.1) -- new in v0.34.
        # The widths come from the same helper dem2dged_lib.
        # utm_tile_basename() formats with, so the converter and this check
        # cannot drift apart (which is precisely what happened before v0.34:
        # the converter emitted short fields and UTM_RE's "\d+" accepted
        # them, so both sides were consistently wrong and nothing noticed).
        n_width_exp, e_width_exp = utm_name_field_widths(lv)
        n_field, e_field = m.group("northing"), m.group("easting")
        width_problems = []
        if len(n_field) != n_width_exp:
            width_problems.append(
                "northing field '%s' is %d digit(s), spec 12.1 requires %d "
                "(zero-padded)" % (n_field, len(n_field), n_width_exp))
        if len(e_field) != e_width_exp:
            width_problems.append(
                "easting field '%s' is %d digit(s), spec 12.1 requires %d "
                "(zero-padded)" % (e_field, len(e_field), e_width_exp))
        if width_problems:
            rep.fail("%s: %s -- regenerate with dem2dged v0.34+ "
                     "(tiles produced by v0.33 or earlier were not padded)"
                     % (base, "; ".join(width_problems)),
                      tile=base, cat="filename")
        else:
            rep.ok("%s: UTM coordinate fields correctly zero-padded "
                   "(%d/%d digits)" % (base, n_width_exp, e_width_exp),
                    tile=base, cat="filename")
        if not (math.isclose(xres, gsd, rel_tol=1e-6)
                and math.isclose(yres, gsd, rel_tol=1e-6)):
            rep.fail("%s: pixel size %.6g×%.6g m, expected %g m" % (base, xres, yres, gsd),
                      tile=base, cat="gsd")
        else:
            rep.ok("%s: pixel size %g m matches level %s" % (base, gsd, lv),
                    tile=base, cat="gsd")
        center_x, center_y = minx + xres / 2.0, miny + yres / 2.0
        if not (_origin_close(center_x, east0, gsd)
                and _origin_close(center_y, north0, gsd)):
            rep.fail("%s: name says origin (%d, %d) but georef is (%.1f, %.1f)"
                     % (base, east0, north0, center_x, center_y), tile=base, cat="bounds")
        else:
            rep.ok("%s: filename coordinates match georeferencing" % base,
                    tile=base, cat="bounds")
        if east0 % tiledim or north0 % tiledim:
            rep.fail("%s: origin not aligned to %g m tile grid" % (base, tiledim),
                      tile=base, cat="bounds")
        else:
            rep.ok("%s: aligned to tile grid" % base, tile=base, cat="bounds")

    if (ds.RasterXSize, ds.RasterYSize) != (exp_w, exp_h):
        rep.fail("%s: dimensions %d×%d, expected %d×%d (posts incl. overlap)"
                 % (base, ds.RasterXSize, ds.RasterYSize, exp_w, exp_h),
                  tile=base, cat="bounds")
    else:
        rep.ok("%s: dimensions %d×%d" % (base, exp_w, exp_h), tile=base, cat="bounds")

    # E. XML sidecar
    xml_path = os.path.join(folder, base + ".xml")
    if not os.path.isfile(xml_path):
        rep.fail("%s: missing .xml sidecar" % base, tile=base, cat="metadata")
    else:
        try:
            txt = open(xml_path, encoding="utf-8").read()
            ET.fromstring(txt)
            problems = []
            if _has_unreplaced_placeholder(txt):
                problems.append("unreplaced {{placeholder}}")
            if base not in txt:
                problems.append("basename not referenced")
            if ">L%s<" % lv not in txt.replace(" ", ""):
                problems.append("level keyword L%s missing" % lv)
            if problems:
                rep.fail("%s.xml: %s" % (base, "; ".join(problems)), tile=base, cat="metadata")
            else:
                rep.ok("%s.xml: well-formed, placeholders replaced" % base,
                        tile=base, cat="metadata")
        except ET.ParseError as e:
            rep.fail("%s.xml: not well-formed XML (%s)" % (base, e), tile=base, cat="metadata")

    # F. statistics / NoData sanity
    arr, mask, _ = read_band(ds)
    n_valid = int(mask.sum())
    if n_valid == 0:
        rep.warn("%s: entirely NoData (border tile — normal at the data edge)" % base,
                  tile=base, cat="nodata")
        stats = None
    else:
        v = arr[mask]
        vmin, vmax, vmean = float(v.min()), float(v.max()), float(v.mean())
        if vmin < ELEV_MIN_SANE or vmax > ELEV_MAX_SANE:
            rep.fail("%s: elevation range [%.1f, %.1f] m outside sane bounds "
                     "[%g, %g] — possible NoData leakage into valid data"
                     % (base, vmin, vmax, ELEV_MIN_SANE, ELEV_MAX_SANE),
                      tile=base, cat="nodata")
        else:
            rep.ok("%s: elevation range [%.1f, %.1f] m" % (base, vmin, vmax),
                    tile=base, cat="nodata")
        stats = (vmin, vmax, vmean, n_valid)

    info = {"base": base, "path": tif, "mode": mode, "lv": lv,
            "minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy,
            "xres": xres, "yres": yres, "epsg": epsg_h, "stats": stats}
    ds = None
    return info


# ── G. edge-overlap consistency ───────────────────────────────────────────────

def _compare_edge(a_path, a_win, b_path, b_win, a_name, b_name, kind, rep):
    """Compare one shared row/column between two tiles.

    a_win / b_win are (xoff, yoff, xsize, ysize) windows passed straight to
    GDAL's ReadAsArray for the respective raster.  Returns True if a
    comparison was actually made (enough overlapping valid data), else False.

    Any GDAL/read error here is reported as a WARN (this check could not be
    completed) rather than raised -- a single unreadable tile must not abort
    the whole run and lose every result collected so far.
    """
    try:
        a, b = gdal_open(a_path), gdal_open(b_path)
        if a is None or b is None:
            raise RuntimeError("could not open %s"
                               % (a_path if a is None else b_path))
        va = a.GetRasterBand(1).ReadAsArray(*a_win).ravel().astype(np.float64)
        vb = b.GetRasterBand(1).ReadAsArray(*b_win).ravel().astype(np.float64)
        a = b = None
    except Exception as e:
        rep.warn("%s ↔ %s: could not read shared %s (%s)"
                 % (a_name, b_name, kind, e))
        return False
    n = min(len(va), len(vb))
    va, vb = va[:n], vb[:n]
    valid = (~np.isclose(va, NODATA)) & (~np.isclose(vb, NODATA))
    if valid.sum() == 0:
        return False
    diff = np.abs(va[valid] - vb[valid])
    if diff.max() > 1e-3:
        rep.fail("%s ↔ %s: shared %s differs (max %.3f m) — "
                 "possible half-pixel shift or indexing bug"
                 % (a_name, b_name, kind, diff.max()))
    else:
        rep.ok("%s ↔ %s: shared %s identical" % (a_name, b_name, kind))
    return True


def check_edges(tiles, rep, max_pairs=20):
    rep.section("G. Edge-overlap consistency between adjacent tiles")
    by_origin = {(round(t["minx"], 6), round(t["miny"], 6)): t for t in tiles}
    checked = 0
    for t in tiles:
        if checked >= max_pairs:
            break

        try:
            ds = gdal_open(t["path"])
            tx, ty = ds.RasterXSize, ds.RasterYSize
            ds = None
        except Exception as e:
            rep.warn("%s: could not open for edge check (%s)" % (t["base"], e))
            continue

        step_x = (t["maxx"] - t["minx"]) - t["xres"]   # tile grid pitch (E-W)
        step_y = (t["maxy"] - t["miny"]) - t["yres"]   # tile grid pitch (N-S)

        # East neighbour: t's last column must equal the neighbour's first column.
        e = by_origin.get((round(t["minx"] + step_x, 6), round(t["miny"], 6)))
        if e:
            try:
                ds = gdal_open(e["path"]); ey = ds.RasterYSize; ds = None
                if _compare_edge(t["path"], (tx - 1, 0, 1, ty),
                                  e["path"], (0, 0, 1, ey),
                                  t["base"], e["base"], "column", rep):
                    checked += 1
            except Exception as ex:
                rep.warn("%s ↔ %s: could not open for edge check (%s)"
                         % (t["base"], e["base"], ex))

        # North neighbour: t's first (top) row must equal the neighbour's
        # last (bottom) row. This was previously not checked at all, even
        # though this section (and the README) documents checking both the
        # shared row AND column between adjacent tiles.
        nb = by_origin.get((round(t["minx"], 6), round(t["miny"] + step_y, 6)))
        if nb:
            try:
                ds = gdal_open(nb["path"]); nx, ny = ds.RasterXSize, ds.RasterYSize; ds = None
                if _compare_edge(t["path"], (0, 0, tx, 1),
                                  nb["path"], (0, ny - 1, nx, 1),
                                  t["base"], nb["base"], "row", rep):
                    checked += 1
            except Exception as ex:
                rep.warn("%s ↔ %s: could not open for edge check (%s)"
                         % (t["base"], nb["base"], ex))

    if checked == 0:
        rep.warn("no adjacent tile pairs with valid data found to compare")


# ── H. source comparison ──────────────────────────────────────────────────────

def check_source(tiles, src_path, rep, max_diff, resample="bilinear"):
    """Compare the delivered tiles against the source DEM (sections H/H2).

    ``resample``: the gdalwarp resampling algorithm ACTUALLY used to
    produce ``tiles`` (e.g. "near", "bilinear", "cubic", "average"). v0.37
    fix for DGED_Conversion_Review.md Finding 2: both re-warps of the
    source below were previously hardcoded to "bilinear" regardless of
    what the tiles were made with, despite the code comment above the H2
    re-warp claiming it used "the same resampling algorithm the tiles
    were produced with" -- so Nearest Neighbor / Cubic runs were being
    diffed against a Bilinear reconstruction of the source and partly
    failing on "how different is this algorithm from Bilinear", not "how
    wrong is this tile". Falls back to "bilinear" (the old hardcoded
    value) if the caller does not know or pass the real one, so every
    existing caller keeps working exactly as before.
    """
    resample = resample or "bilinear"

    # v0.38: if the tiles were made with an overshoot-prone resampler, they
    # were clamped back into the source's exact range right after warping
    # (dem2dged_lib.clamp_tile_to_range() -- Finding 3 of
    # DGED_Conversion_Review.md). But H/H2 below build their OWN internal
    # re-warp of the source using this same ``resample`` algorithm, purely
    # as a like-for-like comparison baseline (the Finding 2 fix above) --
    # and that internal re-warp is not clamped, so it overshoots exactly
    # the way an unclamped tile would have. Comparing clamped delivered
    # tiles against an unclamped comparison baseline made every cubic run
    # on the two sharp-discontinuity DGIWG test rasters FAIL Section H/H2
    # on a difference that is really just "clamped vs unclamped", not a
    # real defect. Clamp the comparison baseline the exact same way, with
    # the exact same function, so both sides reflect the same intended
    # (clamped) product.
    clamp_range = None
    if resample in OVERSHOOT_PRONE_RESAMPLERS:
        try:
            _cvmin, _cvmax, _cmiss = compute_tile_stats(src_path)
            clamp_range = (_cvmin, _cvmax)
        except Exception:
            clamp_range = None

    rep.section("H. Comparison against source DEM")
    try:
        # v0.41: same class of bug as check_tile's -- with exceptions off an
        # unreadable -src returned None here and then blew up on
        # src.GetGeoTransform() below, aborting the run instead of reporting
        # a bad source. gdal_open() answers None either way.
        src = gdal_open(src_path)
        if src is None:
            raise RuntimeError("GDAL cannot open it (corrupt, truncated, "
                               "or not a raster)")
    except Exception as e:
        rep.fail("cannot open source DEM %s (%s)" % (src_path, e))
        return
    # mosaic of all tiles
    try:
        vrt = gdal.BuildVRT("/vsimem/dged_mosaic.vrt", [t["path"] for t in tiles])
        if vrt is None:
            raise RuntimeError("gdal.BuildVRT returned None")
    except Exception as e:
        rep.fail("could not build tile mosaic for source comparison (%s)" % e)
        return

    # coverage: source corners → tile CRS
    s_gt = src.GetGeoTransform()
    s_corners = [(s_gt[0] + i * src.RasterXSize * s_gt[1],
                  s_gt[3] + j * src.RasterYSize * s_gt[5])
                 for i in (0, 1) for j in (0, 1)]
    src_srs = osr.SpatialReference(wkt=src.GetProjection())
    dst_srs = osr.SpatialReference(wkt=vrt.GetProjection())
    src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    xf = osr.CoordinateTransformation(src_srs, dst_srs)
    pts = [xf.TransformPoint(x, y)[:2] for x, y in s_corners]
    sminx, smaxx = min(p[0] for p in pts), max(p[0] for p in pts)
    sminy, smaxy = min(p[1] for p in pts), max(p[1] for p in pts)

    v_gt = vrt.GetGeoTransform()
    vminx, vmaxy = v_gt[0], v_gt[3]
    vmaxx = vminx + vrt.RasterXSize * v_gt[1]
    vminy = vmaxy + vrt.RasterYSize * v_gt[5]
    tol = 2 * abs(v_gt[1])
    if (vminx - tol <= sminx and vmaxx + tol >= smaxx and
            vminy - tol <= sminy and vmaxy + tol >= smaxy):
        rep.ok("tile mosaic fully covers the source extent")
    else:
        rep.fail("tile mosaic does NOT cover the source extent "
                 "(mosaic %.4f..%.4f / %.4f..%.4f vs source %.4f..%.4f / %.4f..%.4f)"
                 % (vminx, vmaxx, vminy, vmaxy, sminx, smaxx, sminy, smaxy))

    # v0.39: compare in the tiles' HORIZONTAL CRS only. The tiles carry a
    # COMPOUND CRS (EPSG:<horiz>+3855, i.e. + EGM2008). Warping the source to
    # that full compound CRS makes GDAL apply an ellipsoidal->EGM2008 vertical
    # (geoid) transform to the SOURCE -- a shift of the local geoid height
    # (e.g. ~25 m over Lebanon, found by the v0.39 beta verification run) --
    # even though the converter's DEFAULT vertical handling (no
    # -source_vertical) applies NO such transform to the tiles: it warps
    # horizontally and only re-tags the +3855 label. That injected a
    # spurious, roughly-constant geoid-height bias into every H/H2 min/max/
    # mean and sample-window diff for any source without an explicit vertical
    # datum (SRTM and most real DEMs) in any region with a non-trivial geoid
    # height, failing Section H on a difference that isn't a real defect.
    # Stripping the vertical makes this a pure HORIZONTAL terrain-
    # reconstruction comparison, matching how the tile values were actually
    # produced. (A delivery made with a real -source_vertical geoid transform
    # is in EGM2008 on both sides for terrain-shape purposes; Section H
    # validates that shape, not the vertical-datum shift itself.)
    _cmp_srs = osr.SpatialReference(wkt=vrt.GetProjection())
    try:
        _cmp_srs.StripVertical()
    except AttributeError:
        pass   # very old GDAL: fall back to the compound CRS (pre-v0.39)
    cmp_dst_wkt = _cmp_srs.ExportToWkt() or vrt.GetProjection()

    # global statistics comparison (source warped to mosaic grid, downsampled)
    scale = max(1, int(max(vrt.RasterXSize, vrt.RasterYSize) / 2000))
    # outputType must be forced to Float32: without it, gdal.Warp keeps the
    # SOURCE raster's native data type (e.g. Byte/Int16 for many real-world
    # DEMs). If the source isn't already floating point, -32767 doesn't fit
    # and GDAL silently clamps dstNodata to 0 (see the "destination nodata
    # value has been clamped" warning) -- which then makes every 0-elevation
    # source pixel look like NoData, and corrupts the min/max/mean compared
    # against the tiles (which dem2dged always writes as Float32).
    warp = gdal.Warp("", src, format="MEM", dstSRS=cmp_dst_wkt,
                     outputBounds=[vminx, vminy, vmaxx, vmaxy],
                     xRes=v_gt[1] * scale, yRes=abs(v_gt[5]) * scale,
                     resampleAlg=resample, dstNodata=NODATA,
                     outputType=gdal.GDT_Float32)
    w_arr, w_mask, _ = read_band(warp)
    if clamp_range is not None:
        w_arr = np.clip(w_arr, clamp_range[0], clamp_range[1])
    have = [t["stats"] for t in tiles if t["stats"]]
    if have and w_mask.sum() > 0:
        wv = w_arr[w_mask]
        t_min = min(s[0] for s in have)
        t_max = max(s[1] for s in have)
        n_tot = sum(s[3] for s in have)
        t_mean = sum(s[2] * s[3] for s in have) / n_tot
        for name, sv, tv, tol_v in [
                ("min",  float(wv.min()),  t_min,  max_diff * 2),
                ("max",  float(wv.max()),  t_max,  max_diff * 2),
                ("mean", float(wv.mean()), t_mean, max_diff)]:
            if abs(sv - tv) > tol_v:
                rep.fail("%s: source %.2f m vs tiles %.2f m (|Δ|=%.2f > %.2f)"
                         % (name, sv, tv, abs(sv - tv), tol_v))
            else:
                rep.ok("%s: source %.2f m vs tiles %.2f m (|Δ|=%.2f)"
                       % (name, sv, tv, abs(sv - tv)))
    warp = None

    # pixel-level sample windows ("round-trip" style diff)
    rep.section("H2. Sample-window pixel difference (tiles vs re-warped source)")
    win = 512

    # v0.37 polish (DGED_Conversion_Review.md recommendations, #5): make
    # window placement coverage-aware. The three windows below are still
    # centered on the same image-relative spots as before (the mosaic's
    # center, and center +/- a quarter of its width/height) -- but a
    # delivery whose actual data footprint is a non-rectangular or
    # off-center shape within its bounding box (a diagonal swath, an
    # irregular AOI) can leave one or more of those fixed spots entirely in
    # NoData, so every run prints the same routine "no overlapping valid
    # data" WARNs regardless of whether the tiles are actually fine. A
    # cheap, heavily decimated read of the WHOLE mosaic (not full
    # resolution -- this is only meant to answer "roughly where is there
    # data", not to measure anything) is enough to nudge a fixed spot with
    # no coverage to the nearest one that has some.
    _cov_size = 256
    try:
        _cov_w = min(_cov_size, vrt.RasterXSize)
        _cov_h = min(_cov_size, vrt.RasterYSize)
        _cov = vrt.GetRasterBand(1).ReadAsArray(
            0, 0, vrt.RasterXSize, vrt.RasterYSize,
            buf_xsize=_cov_w, buf_ysize=_cov_h)
        _cov_mask = ~np.isclose(_cov.astype(np.float64), NODATA)
        _cov_sx = vrt.RasterXSize / float(_cov_w)
        _cov_sy = vrt.RasterYSize / float(_cov_h)
        if not _cov_mask.any():
            _cov_mask = None   # entirely NoData -- nothing to nudge towards
    except Exception:
        _cov_mask = None       # fall back to the un-nudged fixed positions

    def _nearest_covered(ox, oy):
        """Nudge a candidate window's top-left corner (full-res image
        coords) to the nearest low-res cell with data, if the fixed
        position's cell has none. Unchanged if coverage couldn't be
        sampled, or the fixed position is already fine."""
        if _cov_mask is None:
            return ox, oy
        cx_lo = min(max(int((ox + win / 2) / _cov_sx), 0), _cov_mask.shape[1] - 1)
        cy_lo = min(max(int((oy + win / 2) / _cov_sy), 0), _cov_mask.shape[0] - 1)
        if _cov_mask[cy_lo, cx_lo]:
            return ox, oy
        ys, xs = np.where(_cov_mask)
        i = int(np.argmin((xs - cx_lo) ** 2 + (ys - cy_lo) ** 2))
        return (int(xs[i] * _cov_sx - win / 2), int(ys[i] * _cov_sy - win / 2))

    cx, cy = vrt.RasterXSize // 2, vrt.RasterYSize // 2
    windows = [(cx - win // 2, cy - win // 2),
               (max(0, cx - vrt.RasterXSize // 4), max(0, cy - vrt.RasterYSize // 4)),
               (min(vrt.RasterXSize - win, cx + vrt.RasterXSize // 4),
                min(vrt.RasterYSize - win, cy + vrt.RasterYSize // 4))]
    windows = [_nearest_covered(ox, oy) for ox, oy in windows]
    done = 0
    overall_max = 0.0
    for ox, oy in windows:
        ox = max(0, min(ox, vrt.RasterXSize - win))
        oy = max(0, min(oy, vrt.RasterYSize - win))
        w = min(win, vrt.RasterXSize)
        h = min(win, vrt.RasterYSize)
        if w <= 0 or h <= 0:
            continue

        # geographic bounds of this window on the mosaic grid
        wx0 = vminx + ox * v_gt[1]
        wx1 = vminx + (ox + w) * v_gt[1]
        wy1 = vmaxy + oy * v_gt[5]
        wy0 = vmaxy + (oy + h) * v_gt[5]

        try:
            tile_arr = vrt.GetRasterBand(1).ReadAsArray(ox, oy, w, h).astype(np.float64)
        except Exception as e:
            rep.warn("sample window (%d,%d): could not read tile mosaic (%s)" % (ox, oy, e))
            continue

        # Re-warp the source at full (native) resolution over just this
        # window's extent, using ``resample`` -- the same resampling
        # algorithm the tiles were produced with (v0.37: this is now
        # actually true; see check_source()'s docstring for Finding 2 of
        # DGED_Conversion_Review.md) -- so this is a real like-for-like
        # comparison. dstSRS is the HORIZONTAL-only CRS (v0.39, cmp_dst_wkt
        # above): warping to the tiles' compound +3855 CRS would apply a
        # phantom ellipsoidal->EGM2008 geoid shift to the source that the
        # tiles never got.
        src_win = gdal.Warp("", src, format="MEM", dstSRS=cmp_dst_wkt,
                             outputBounds=[min(wx0, wx1), min(wy0, wy1),
                                           max(wx0, wx1), max(wy0, wy1)],
                             width=w, height=h,
                             resampleAlg=resample, dstNodata=NODATA,
                             outputType=gdal.GDT_Float32)
        src_arr, src_mask, _ = read_band(src_win)
        if clamp_range is not None:
            src_arr = np.clip(src_arr, clamp_range[0], clamp_range[1])
        tile_mask = ~np.isclose(tile_arr, NODATA)
        both = tile_mask & src_mask
        if both.sum() == 0:
            rep.warn("sample window (%d,%d): no overlapping valid data" % (ox, oy))
            continue

        diff = np.abs(tile_arr[both] - src_arr[both])
        wmax = float(diff.max())
        overall_max = max(overall_max, wmax)
        if wmax > max_diff:
            rep.fail("sample window (%d,%d): max |diff| %.3f m > tolerance %.2f m"
                     % (ox, oy, wmax, max_diff))
        else:
            rep.ok("sample window (%d,%d): max |diff| %.3f m" % (ox, oy, wmax))
        done += 1

    if done:
        rep._emit("  Pixel-level sample window: max difference %.2f m" % overall_max)
    else:
        rep.warn("no sample windows could be compared (no overlapping valid data)")


# -- A. file pairing ------------------------------------------------------------

def find_tiles(folder):
    tifs = sorted(glob.glob(os.path.join(folder, "*.tif")))
    xmls = sorted(glob.glob(os.path.join(folder, "*.xml")))
    return tifs, xmls


def is_product_level_xml(xml_path):
    """True for delivery-level metadata that intentionally has no .tif.

    TABLE_OF_CONTENTS.xml (spec 12.1 'shall') and <product_id>_COLLECTION.xml
    (spec 6.6) are written once per delivery by dem2dged_lib.write_toc_file()
    / write_collection_metadata() -- they describe the whole tile set, not a
    single tile, so they never have (and were never supposed to have) a
    matching .tif. This uses the exact same name test write_toc_file() itself
    uses to tell product-level files apart from per-tile sidecars (see its
    role classification loop), so the two checks can't drift out of sync.
    """
    name_low = os.path.basename(xml_path).lower()
    return name_low == TOC_FILENAME.lower() or name_low.endswith("_collection.xml")


def check_pairing(tifs, xmls, rep):
    rep.section("A. File pairing (.tif <-> .xml)")
    if not tifs and not xmls:
        rep.fail("no .tif/.xml tiles found in folder")
        return
    tile_xmls = [x for x in xmls if not is_product_level_xml(x)]
    tif_bases = {os.path.splitext(os.path.basename(t))[0] for t in tifs}
    xml_bases = {os.path.splitext(os.path.basename(x))[0] for x in tile_xmls}
    missing_xml = sorted(tif_bases - xml_bases)
    missing_tif = sorted(xml_bases - tif_bases)
    for b in missing_xml:
        rep.fail("%s.tif: missing .xml sidecar" % b)
    for b in missing_tif:
        rep.fail("%s.xml: missing .tif" % b)
    if not missing_xml and not missing_tif:
        rep.ok("all %d tile(s) paired (.tif + .xml)" % len(tif_bases))


# -- HTML report -----------------------------------------------------------------

_HTML_CSS = """
  :root{
    --green:#1e8e3e; --green-bg:#e6f4ea;
    --red:#c5221f; --red-bg:#fce8e6;
    --yellow:#b06000; --yellow-bg:#fef7e0;
    --gray:#5f6368; --gray-bg:#f1f3f4;
    --border:#dadce0; --text:#202124;
  }
  *{box-sizing:border-box;}
  body{
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
    color:var(--text); background:#fafafa; margin:0; padding:32px 20px 80px;
    line-height:1.5;
  }
  .wrap{max-width:920px;margin:0 auto;}
  h1{font-size:26px;margin:0 0 4px;}
  .subtitle{color:var(--gray);font-size:14px;margin-bottom:28px;}
  h2{font-size:19px;margin:40px 0 14px;border-bottom:2px solid var(--border);padding-bottom:8px;}
  h3{font-size:15px;margin:22px 0 8px;}
  table{width:100%;border-collapse:collapse;margin-bottom:18px;background:#fff;border:1px solid var(--border);border-radius:8px;overflow:hidden;}
  th,td{padding:9px 12px;text-align:left;font-size:13.5px;border-bottom:1px solid var(--border);}
  th{background:#f8f9fa;font-weight:600;color:var(--gray);}
  tr:last-child td{border-bottom:none;}
  .badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:700;letter-spacing:.3px;}
  .b-pass{background:var(--green-bg);color:var(--green);}
  .b-fail{background:var(--red-bg);color:var(--red);}
  .b-warn{background:var(--yellow-bg);color:var(--yellow);}
  .b-na{background:var(--gray-bg);color:var(--gray);}
  .dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle;}
  .dot-green{background:var(--green);} .dot-red{background:var(--red);} .dot-yellow{background:var(--yellow);} .dot-gray{background:var(--gray);}
  .card{background:#fff;border:1px solid var(--border);border-radius:10px;padding:20px 22px;margin-bottom:22px;}
  .card-head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:6px;}
  .card-head .name{font-size:16.5px;font-weight:700;}
  .meta{color:var(--gray);font-size:12.5px;margin-bottom:14px;}
  .stat-row{display:flex;gap:10px;margin:12px 0 16px;flex-wrap:wrap;}
  .stat{flex:1;min-width:110px;background:var(--gray-bg);border-radius:8px;padding:10px 12px;text-align:center;}
  .stat .num{font-size:20px;font-weight:700;}
  .stat.pass .num{color:var(--green);} .stat.fail .num{color:var(--red);} .stat.warn .num{color:var(--yellow);}
  .stat .lbl{font-size:11px;color:var(--gray);text-transform:uppercase;letter-spacing:.4px;}
  .finding{border-left:3px solid var(--border);padding:8px 12px;margin:6px 0;font-size:13.5px;border-radius:0 6px 6px 0;}
  .finding.red{border-color:var(--red);background:var(--red-bg);}
  .finding.yellow{border-color:var(--yellow);background:var(--yellow-bg);}
  .finding.green{border-color:var(--green);background:var(--green-bg);}
  .finding.gray{border-color:var(--gray);background:var(--gray-bg);}
  .explain{margin-top:6px;font-size:12.5px;line-height:1.45;color:#3c4043;background:rgba(255,255,255,.55);border-radius:6px;padding:7px 10px;}
  .explain b{color:var(--text);}
  .sec-intro{font-size:13px;color:var(--gray);margin:0 0 10px;line-height:1.45;}
  code{background:#f1f3f4;padding:1px 5px;border-radius:4px;font-size:12.5px;}
  .legend{font-size:12.5px;color:var(--gray);margin-top:6px;}
  .note{background:#fff8e1;border:1px solid #ffe08a;border-radius:8px;padding:14px 16px;font-size:13.5px;margin:18px 0;}
  .summary-top{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:8px;}
  .summary-top .pill{flex:1;min-width:150px;border-radius:10px;padding:14px 16px;color:#fff;}
  .pill.g{background:var(--green);} .pill.r{background:var(--red);} .pill.gy{background:var(--gray);}
  .pill .n{font-size:24px;font-weight:800;} .pill .l{font-size:12px;opacity:.9;}
  footer{color:var(--gray);font-size:12px;margin-top:50px;border-top:1px solid var(--border);padding-top:14px;}
"""

_REQ_TABLE_ROWS = [
    ("A", "File pairing", "Every <code>.tif</code> has a matching <code>.xml</code> sidecar and vice versa"),
    ("B", "Filename convention", "Name parses per DGED spec; tile letter matches the product level; UTM northing/easting subfields zero-padded to the spec 12.1 widths (<code>nnnn</code>/<code>eee</code> for levels 4b-6, <code>nnnnmmm</code>/<code>eeemmm</code> for levels 7-9)"),
    ("C", "GeoTIFF header", "Correct data type for the level (Int16 for levels 0-2, Float32 for level 3+), NoData = -32767, <code>AREA_OR_POINT=Point</code>, LZW compression, EGM2008 (EPSG:3855) CRS tag"),
    ("D", "Grid geometry", "Pixel size matches the level's GSD; raster dimensions match expected posts (incl. the required 1-pixel overlap); origin aligned to the DGED tile grid; filename coordinates match the actual georeferencing"),
    ("E", "XML sidecar", "Well-formed XML, no leftover <code>{{PLACEHOLDER}}</code> text, basename/level consistent with the tile"),
    ("F", "Statistics / NoData", "Elevation values are within a sane range; NoData isn't leaking into valid data"),
    ("G", "Edge overlap", "The shared row/column between north-south and east-west neighbouring tiles must be pixel-identical"),
    ("H", "Source comparison", "(only if a source DEM is supplied) tile mosaic covers the source extent; min/max/mean within tolerance; pixel-level differences in sample windows"),
]


def _esc(s):
    import html as _html
    return _html.escape(str(s), quote=True)


def _parse_sections(rep):
    """Group a Report's flat line list back into (section_title, [(kind, msg), ...])
    tuples, so the HTML renderer can lay them out per-category (A, B-F, G, H...)."""
    sections = []
    cur_title, cur_lines = None, []
    for line in rep.lines:
        s = line.strip()
        if s.startswith(u"──"):   # "── Section title ──" (box-drawing dashes)
            if cur_title is not None or cur_lines:
                sections.append((cur_title, cur_lines))
            cur_title = s.strip(u"─ ").strip()
            cur_lines = []
        elif s.startswith("PASS  ") or s.startswith("WARN  ") or s.startswith("FAIL  "):
            kind, msg = s[:4].strip().lower(), s[6:].strip()
            cur_lines.append((kind, msg))
        elif s and not s.startswith("PASS=") and "RESULT:" not in s \
                and not s.startswith("dem2dged_validate") and not s.startswith("Tile folder:"):
            cur_lines.append(("info", s))
    if cur_title is not None or cur_lines:
        sections.append((cur_title, cur_lines))
    return sections


def _infer_note(sections):
    """Best-effort, heuristic explanation for the most common failure
    patterns, mirroring the kind of \"what this means\" callouts a human
    reviewer would add. Returns None if nothing recognisable was found."""
    fails = []
    for title, lines in sections:
        for kind, msg in lines:
            if kind == "fail":
                fails.append((title or "", msg))
    if not fails:
        return None

    joined = " | ".join(m for _, m in fails)

    if any("shared row" in m or "shared column" in m for _, m in fails):
        return ("One or more adjacent tiles do not share an exactly identical border row/column "
                "(differences are typically a few centimetres). Each tile is warped independently, "
                "so tiny floating-point differences in how the target grid is computed near tile "
                "boundaries can shift the shared edge by a sub-pixel fraction. Small (cm-scale) "
                "differences are a cosmetic stitching artefact; large ones would indicate a real "
                "half-pixel-shift or indexing bug.")
    if any("missing .xml sidecar" in m for _, m in fails):
        return ("At least one tile is missing its .xml sidecar (and/or its GeoTIFF header looks "
                "incomplete). This matches the pattern of a run that was interrupted partway through "
                "a tile. Delete the affected .tif and re-run the same conversion — completed tiles "
                "(the ones with an .xml already) are skipped automatically, so only the missing tile "
                "will be regenerated.")
    if ("min:" in joined or "max:" in joined) and "mean:" not in joined.split("min:")[0]:
        # min/max failed but nothing else obviously did -> resampling overshoot pattern
        return ("The global min/max elevation is outside tolerance versus the source, but this is "
                "worth checking against the per-tile elevation ranges and the pixel-level sample-window "
                "result above: if those stay within the source's own range, this is most likely "
                "resampling overshoot (\"ringing\") near a steep elevation edge rather than a "
                "georeferencing or NoData bug.")
    return None


# One-line, plain-language introduction shown under each section heading so a
# reader who is not steeped in the DGED spec understands what the group of
# checks below is actually verifying. Keyed by the leading token of the
# section title emitted by Report.section().
_SECTION_INTRO = {
    "A": "Checks that every elevation image (.tif) is paired with its matching "
         "metadata file (.xml). Deliverables must ship both together.",
    "B-F": "Per-tile checks: the file is named the way the DGED spec requires, "
           "the GeoTIFF header carries the correct data type / NoData value / "
           "coordinate system, the grid spacing and size are right, the XML "
           "sidecar is complete, and the elevation values look sane.",
    "G": "Where two tiles touch, the row or column they share must contain "
         "exactly the same elevations in both tiles, so the tiles line up "
         "seamlessly with no visible seam.",
    "H": "Compares the delivered tiles against the original source DEM to "
         "confirm they cover the same area and carry the same elevations "
         "(small differences from resampling are expected).",
    "H2": "Spot-checks a few 512-pixel windows, comparing each tile pixel "
          "against the source re-sampled the same way, to measure the actual "
          "elevation difference in metres.",
}


def _section_intro(title):
    """Return the plain-language intro sentence for a section title, or None."""
    if not title:
        return None
    token = title.split(".", 1)[0].strip()
    return _SECTION_INTRO.get(token)


# Ordered list of (matcher, explanation) pairs. The first matcher whose
# substrings ALL appear in the finding message wins. Each explanation says, in
# plain language, what the check means and — for problems — the most likely
# cause and how to fix it. Matching is done on the lower-cased message so the
# rules are case-insensitive.
_EXPLAIN_RULES = [
    # -- A. pairing ------------------------------------------------------------
    (["missing .xml sidecar"],
     "This tile's image has no accompanying metadata (.xml) file. A DGED "
     "delivery must include both. This usually means the conversion was "
     "interrupted before the sidecar was written. Fix: delete this .tif and "
     "re-run the conversion — finished tiles are skipped, so only the missing "
     "one is regenerated."),
    (["missing .tif"],
     "A metadata (.xml) file exists but its elevation image (.tif) is gone. "
     "The pair is incomplete. Fix: re-run the conversion, or remove the "
     "orphaned .xml if that tile is no longer wanted."),
    (["no .tif/.xml tiles found"],
     "The folder contains no DGED tiles at all. Fix: point the validator at "
     "the output folder that actually holds the generated .tif/.xml files."),
    # -- B. filename -----------------------------------------------------------
    (["filename does not match", "naming convention"],
     "The file name doesn't follow the DGED naming pattern, so it can't be "
     "identified as a valid tile. Likely the file was renamed by hand or is "
     "not a dem2dged output. Fix: keep the original generated file names."),
    (["level", "invalid for"],
     "The level code embedded in the file name isn't a recognised DGED level "
     "for this projection mode. Fix: regenerate the tiles with a supported "
     "level rather than editing the name."),
    (["tile letter", "requires"],
     "The single letter in the file name encodes the product level, and it "
     "doesn't match the level number in the same name. The name is internally "
     "inconsistent. Fix: regenerate the tiles so the letter and level agree."),
    (["cannot open"],
     "GDAL could not open this GeoTIFF — the file is likely truncated or "
     "corrupted (often from a run that was stopped midway). Fix: delete it and "
     "re-run the conversion."),
    # -- C. header -------------------------------------------------------------
    (["data type is", "expected"],
     "DGED mandates a specific data type per product level: signed 16-bit "
     "integer for levels 0-2, 32-bit floating point for level 3 and up. This "
     "tile's data type doesn't match what its level requires. Fix: "
     "regenerate the tile with the current converter, which selects the "
     "correct type for the level automatically — a mismatch usually points "
     "to a hand-edited, third-party, or very old (pre-v0.27) file."),
    (["nodata is", "expected"],
     "The 'no data' marker (which flags pixels with no elevation) isn't the "
     "required value of -32767. Tools downstream won't recognise empty pixels. "
     "Fix: regenerate the tile so the correct NoData value is written."),
    (["area_or_point"],
     "DGED elevations are point samples, so the header must say "
     "AREA_OR_POINT=Point. This tile says otherwise, which shifts every value "
     "by half a pixel in interpretation. Fix: regenerate the tile."),
    (["compression is", "lzw"],
     "The DGED profile expects LZW compression. This tile uses something else "
     "(or none). It will still open, but the file is larger / off-profile — "
     "hence a warning, not a failure. Fix: regenerate with LZW if strict "
     "profile compliance is required."),
    (["egm2008"],
     "The vertical coordinate system tag (EGM2008 / EPSG:3855, which defines "
     "what 'height zero' means) wasn't found in the CRS. Heights may be "
     "misinterpreted against the wrong reference. This is a warning because "
     "many viewers ignore it. Fix: regenerate the tile so the vertical CRS tag "
     "is written."),
    # -- D. grid geometry ------------------------------------------------------
    (["pixel size", "expected"],
     "The spacing between elevation posts doesn't match the ground sample "
     "distance defined for this level. The grid is the wrong resolution. Fix: "
     "regenerate at the correct level — don't resample the tile afterwards."),
    (["name says origin", "georef"],
     "The coordinates written into the file name don't match the tile's actual "
     "georeferencing. The name and the data disagree about where the tile sits. "
     "Fix: regenerate the tile (a mismatch usually follows a manual rename or a "
     "grid-alignment bug)."),
    (["origin not aligned", "tile grid"],
     "The tile's corner doesn't fall exactly on the DGED tile grid, so it won't "
     "line up with neighbouring tiles. Fix: regenerate — the source extent was "
     "probably clipped to an off-grid boundary."),
    (["dimensions", "expected", "posts"],
     "The tile has the wrong number of rows/columns. DGED tiles include a "
     "one-pixel overlap with each neighbour, so an off-by-one size means that "
     "overlap is missing or doubled. Fix: regenerate the tile."),
    # -- E. XML sidecar --------------------------------------------------------
    (["unreplaced", "placeholder"],
     "The XML metadata still contains template markers like {{...}} that were "
     "never filled in with real values. Fix: regenerate — the template "
     "substitution step didn't complete for this tile."),
    (["basename not referenced"],
     "The XML doesn't mention its own tile file name, so metadata and image may "
     "have been mismatched. Fix: regenerate the tile's sidecar."),
    (["level keyword", "missing"],
     "The XML doesn't state the product level it belongs to, which breaks "
     "metadata consistency. Fix: regenerate the sidecar from the correct "
     "template."),
    (["not well-formed xml"],
     "The XML sidecar has a syntax error and can't be parsed. Fix: regenerate "
     "it — hand-editing usually introduces this (an unclosed tag or stray "
     "character)."),
    # -- F. statistics ---------------------------------------------------------
    (["elevation range", "outside sane bounds"],
     "Some elevations are far below the Dead Sea or above Everest, which almost "
     "always means the -32767 'no data' marker leaked in and is being treated "
     "as a real height. Fix: check NoData handling and regenerate the tile."),
    (["entirely nodata", "border tile"],
     "This tile has no elevation data at all — normal for a tile that sits at "
     "the very edge of the coverage area. No action needed; it's flagged as a "
     "warning only so you're aware."),
    # -- G. edges --------------------------------------------------------------
    (["shared", "differs", "half-pixel"],
     "Two neighbouring tiles don't hold identical values along the row/column "
     "they share, so a faint seam can appear where they meet. A few centimetres "
     "is a harmless rounding artefact from warping each tile separately; a large "
     "difference points to a real half-pixel shift or row/column indexing bug. "
     "Fix: if the difference is large, regenerate the affected tiles."),
    (["could not read shared"],
     "The shared edge between two tiles couldn't be read, so this consistency "
     "check was skipped for that pair (reported as a warning, not a failure). "
     "Fix: confirm both tiles open correctly."),
    (["no adjacent tile pairs"],
     "No two tiles with overlapping valid data were found to compare, so the "
     "seam check couldn't run. Normal for a single tile or scattered tiles."),
    (["could not open for edge check"],
     "A tile couldn't be opened while checking edges, so that comparison was "
     "skipped. Fix: verify the tile isn't corrupted."),
    # -- H. source comparison --------------------------------------------------
    (["does not cover the source extent"],
     "The delivered tiles don't span the whole area of the source DEM — part of "
     "the input is missing from the output. Fix: re-run the conversion over the "
     "full source extent."),
    (["no valid tiles to compare against source"],
     "No usable tiles were parsed, so there was nothing to compare against the "
     "source DEM. Fix: resolve the per-tile failures above first."),
    (["source", "vs tiles"],
     "A summary elevation statistic (min, max or mean) differs from the source "
     "by more than the tolerance. Cross-check it against the per-tile ranges and "
     "the pixel-level window result: if those stay within the source's own "
     "range, this is most likely resampling overshoot near a steep slope rather "
     "than a real error. Fix: raise -max-diff if the difference is expected, or "
     "investigate the flagged tiles."),
    (["sample window", "tolerance"],
     "In a spot-checked window, the largest tile-vs-source elevation difference "
     "exceeds the allowed tolerance. Some difference is normal from bilinear "
     "resampling; a large one suggests a georeferencing or alignment problem. "
     "Fix: raise -max-diff if the gap is expected, otherwise check tile "
     "alignment."),
    (["sample window", "no overlapping valid data"],
     "This spot-check window had no pixels where both the tiles and the source "
     "hold data, so it was skipped. No action needed."),
    (["no sample windows could be compared"],
     "None of the spot-check windows had overlapping valid data, so the "
     "pixel-level comparison couldn't run. Often means the source and tiles "
     "barely overlap."),
]


def _explain_finding(kind, msg):
    """Return a plain-language 'what this means' explanation (with likely cause
    and fix) for a WARN/FAIL finding, or None if no rule matches. PASS and info
    lines are not explained (they need no action)."""
    if kind not in ("fail", "warn"):
        return None
    low = msg.lower()
    for needles, explanation in _EXPLAIN_RULES:
        if all(n in low for n in needles):
            return explanation
    return None


_TILE_TABLE_MAX_ROWS = 500   # cap so a 1000+ tile run doesn't blow up the HTML


def _status_cell_html(status):
    """One <td> for the per-tile detail table: a coloured PASS/WARN/FAIL
    badge, or a grey '-' if that criterion wasn't recorded for this tile."""
    if status is None:
        return '<td><span class="badge b-na">-</span></td>'
    cls = {"PASS": "b-pass", "WARN": "b-warn", "FAIL": "b-fail"}[status]
    symbol = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}[status]
    return '<td><span class="badge %s">%s</span></td>' % (cls, symbol)


def _tile_table_html(rep):
    """Build the detailed per-tile criteria table (v0.24 — Feature #2):
    one row per tile, one column per validation criterion, PASS/WARN/FAIL
    badges, plus an Overall column. Returns '' if no per-tile checks were
    recorded (e.g. every tile failed to even parse)."""
    if not rep.tile_order:
        return ""

    truncated = len(rep.tile_order) > _TILE_TABLE_MAX_ROWS
    tile_list = rep.tile_order[:_TILE_TABLE_MAX_ROWS]

    header_cells = "".join(
        "<th>%s</th>" % _esc(label) for _, label in TILE_CHECK_CATEGORIES)

    rows = []
    for base in tile_list:
        cells = "".join(
            _status_cell_html(rep.tile_checks.get(base, {}).get(cat_key))
            for cat_key, _ in TILE_CHECK_CATEGORIES)
        overall = _status_cell_html(rep.tile_overall(base))
        rows.append("    <tr><td>%s</td>%s%s</tr>" % (_esc(base), cells, overall))

    note = ""
    if truncated:
        note = ('    <p class="sec-intro">Showing the first %d of %d tiles here; '
                 'see the findings below (or the text report) for the rest.</p>\n'
                 % (_TILE_TABLE_MAX_ROWS, len(rep.tile_order)))

    return """
    <h3>Detailed Per-Tile Results</h3>
    <p class="sec-intro">One row per tile, one column per DGED criterion — see "What DGED requires" above for what each check verifies.</p>
%s    <table>
      <tr><th>Tile Name</th>%s<th>Overall</th></tr>
%s
    </table>""" % (note, header_cells, "\n".join(rows))


def _dataset_card_html(ds):
    name = _esc(ds.get("name", "dataset"))
    rep = ds.get("rep")
    error = ds.get("error")

    if error:
        return """
  <div class="card">
    <div class="card-head">
      <div class="name">%s</div>
      <span class="badge b-na">COULD NOT VALIDATE</span>
    </div>
    <div class="finding gray"><span class="dot dot-gray"></span>%s</div>
  </div>""" % (name, _esc(error))

    n_pass, n_warn, n_fail = rep.n_pass, rep.n_warn, rep.n_fail
    # v0.37: shared 3-tier rule (Finding 4) -- see overall_result()'s docstring.
    _result = overall_result(n_pass, n_warn, n_fail)
    badge = {"FAIL": ("b-fail", "FAIL"), "WARN": ("b-warn", "WARN"),
             "PASS": ("b-pass", "PASS")}[_result]
    src = ds.get("src")
    tiles = ds.get("tiles") or []
    mode = tiles[0]["mode"].upper() if tiles else "?"
    lv = tiles[0]["lv"] if tiles else "?"
    meta_bits = ["%s tile(s)" % len(tiles), "mode %s" % mode, "level %s" % lv]
    if src:
        meta_bits.append("compared against <code>%s</code>" % _esc(os.path.basename(src)))
    meta = " &nbsp;·&nbsp; ".join(meta_bits)

    tile_table = _tile_table_html(rep)

    sections = _parse_sections(rep)
    body = []
    for title, lines in sections:
        if title in (None, "Summary") or not lines:
            continue
        body.append('    <h3>%s</h3>' % _esc(title))
        intro = _section_intro(title)
        if intro:
            body.append('    <p class="sec-intro">%s</p>' % _esc(intro))
        passes = [m for k, m in lines if k == "pass"]
        others = [(k, m) for k, m in lines if k != "pass"]
        # Collapse long runs of PASS lines into one summary finding so a
        # 100-tile batch doesn't produce a wall of green boxes.
        if passes:
            if len(passes) <= 6:
                for m in passes:
                    body.append('    <div class="finding green"><span class="dot dot-green"></span>%s</div>' % _esc(m))
            else:
                body.append('    <div class="finding green"><span class="dot dot-green"></span>%d checks passed.</div>' % len(passes))
        for kind, m in others:
            cls = {"fail": "red", "warn": "yellow", "info": "gray"}.get(kind, "gray")
            dot = {"fail": "dot-red", "warn": "dot-yellow", "info": "dot-gray"}.get(kind, "dot-gray")
            label = "<b>FAIL — </b>" if kind == "fail" else ("<b>WARN — </b>" if kind == "warn" else "")
            explain = _explain_finding(kind, m)
            explain_html = ('<div class="explain"><b>What this means:</b> %s</div>'
                            % _esc(explain)) if explain else ""
            body.append('    <div class="finding %s"><span class="dot %s"></span>%s%s%s</div>'
                        % (cls, dot, label, _esc(m), explain_html))

    note = _infer_note(sections)
    note_html = ('    <div class="note"><b>What this means:</b> %s</div>' % _esc(note)) if note else ""

    return """
  <div class="card">
    <div class="card-head">
      <div class="name">%s</div>
      <span class="badge %s">%s</span>
    </div>
    <div class="meta">%s</div>
    <div class="stat-row">
      <div class="stat pass"><div class="num">%d</div><div class="lbl">Passed</div></div>
      <div class="stat warn"><div class="num">%d</div><div class="lbl">Warnings</div></div>
      <div class="stat fail"><div class="num">%d</div><div class="lbl">Failed</div></div>
    </div>
%s
%s
%s
  </div>""" % (name, badge[0], badge[1], meta, n_pass, n_warn, n_fail,
               tile_table, "\n".join(body), note_html)


def render_html_report(datasets, tool_version=None):
    """Render the same Google-Material-style report (badges/pills/cards)
    used for manual reviews, generalised to any number of datasets so it
    can be produced automatically after every conversion run."""
    import datetime as _dt
    tool_version = tool_version or VERSION
    today = str(_dt.date.today())

    n_total = len(datasets)
    n_fail_ds = sum(1 for d in datasets if d.get("error") or (d.get("rep") and d["rep"].n_fail))
    n_ok_ds = sum(1 for d in datasets if not d.get("error") and d.get("rep") and not d["rep"].n_fail)
    n_na_ds = sum(1 for d in datasets if d.get("error"))
    tot_pass = sum(d["rep"].n_pass for d in datasets if d.get("rep"))
    tot_checks = sum(d["rep"].n_pass + d["rep"].n_warn + d["rep"].n_fail
                      for d in datasets if d.get("rep"))

    pills = []
    if n_ok_ds:
        pills.append('<div class="pill g"><div class="n">%d / %d</div><div class="l">dataset(s) fully PASS</div></div>' % (n_ok_ds, n_total))
    if n_fail_ds:
        pills.append('<div class="pill r"><div class="n">%d / %d</div><div class="l">dataset(s) have at least one FAIL</div></div>' % (n_fail_ds, n_total))
    if n_na_ds:
        pills.append('<div class="pill gy"><div class="n">%d / %d</div><div class="l">dataset(s) could not be validated</div></div>' % (n_na_ds, n_total))
    pills.append('<div class="pill g"><div class="n">%d / %d</div><div class="l">individual checks passed overall</div></div>' % (tot_pass, tot_checks))

    req_rows = "\n".join(
        "    <tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (l, t, d)
        for l, t, d in _REQ_TABLE_ROWS)

    cards = "\n".join(_dataset_card_html(d) for d in datasets)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>dem2dged Validation Report</title>
<style>%s</style>
</head>
<body>
<div class="wrap">

  <h1>dem2dged Validation Report</h1>
  <div class="subtitle">Generated %s &nbsp;·&nbsp; dem2dged_validate.py v%s &nbsp;·&nbsp; %d tile set(s) checked</div>

  <div class="summary-top">
%s
  </div>

  <h2>What DGED requires (and what the validator checks)</h2>
  <table>
    <tr><th style="width:26px">#</th><th>Requirement</th><th>What's checked</th></tr>
%s
  </table>
  <div class="legend"><span class="dot dot-green"></span>PASS &nbsp; <span class="dot dot-yellow"></span>WARN (worth a look, not a failure) &nbsp; <span class="dot dot-red"></span>FAIL &nbsp; <span class="dot dot-gray"></span>could not be checked</div>
%s
  <footer>
    dem2dged v%s &nbsp;·&nbsp; Report reflects checks A-H per dem2dged_validate.py &nbsp;·&nbsp; generated automatically after conversion.
  </footer>

</div>
</body>
</html>
""" % (_HTML_CSS, today, tool_version, n_total, "\n".join("    " + p for p in pills),
       req_rows, cards, tool_version)
    return html


def write_html_report(datasets, out_path, tool_version=None):
    try:
        html = render_html_report(datasets, tool_version=tool_version)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        return True
    except Exception as e:
        print("WARNING: could not write HTML report %s (%s)" % (out_path, e))
        return False


# -- CLI / driver -----------------------------------------------------------------

def run_validation(tile_folder, src=None, max_diff=5.0, verbose=False,
                    resample="bilinear"):
    """Run every check (A-H) against one tile folder and return the
    populated Report plus the list of successfully-parsed tile info dicts.

    This is the reusable entry point: the CLI below is a thin wrapper
    around it, and dem2dged.py / dem2dged_gui.py call it directly
    in-process to auto-validate right after a conversion finishes
    (no subprocess, so it works the same way whether run from source
    or from inside a PyInstaller-frozen .exe).

    ``resample``: the gdalwarp resampling algorithm that actually produced
    ``tile_folder``'s tiles, forwarded to check_source() for section H/H2's
    source re-warp (v0.37, DGED_Conversion_Review.md Finding 2). Defaults
    to "bilinear" -- the value every call site used unconditionally before
    this fix -- so a caller that does not know the real algorithm (e.g. an
    operator validating someone else's delivery from the standalone CLI
    without -resample) gets exactly the old behaviour.
    """
    rep = Report(verbose=verbose)
    rep._emit("dem2dged_validate v%s" % VERSION)
    rep._emit("Tile folder: %s" % tile_folder)

    tifs, xmls = find_tiles(tile_folder)
    check_pairing(tifs, xmls, rep)

    rep.section("B-F. Per-tile checks (naming, header, grid, XML, statistics)")
    tiles = []
    for tif in tifs:
        info = check_tile(tif, rep, tile_folder)
        if info:
            tiles.append(info)

    if tiles:
        check_edges(tiles, rep)
    else:
        rep.warn("no valid tiles parsed -- skipping edge-overlap and source checks")

    if src:
        if tiles:
            check_source(tiles, src, rep, max_diff, resample=resample)
        else:
            rep.fail("no valid tiles to compare against source %s" % src)

    rep.section("Summary")
    rep._emit("PASS=%d  WARN=%d  FAIL=%d" % (rep.n_pass, rep.n_warn, rep.n_fail))
    rep._emit("RESULT: %s" % overall_result(rep.n_pass, rep.n_warn, rep.n_fail))

    return rep, tiles


def write_text_report(rep, path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(rep.lines) + "\n")
        return True
    except OSError as e:
        print("WARNING: could not write report file %s (%s)" % (path, e))
        return False


def build_parser():
    """Build the CLI parser.

    v0.34: every option is registered under BOTH its historic single-dash
    spelling and the double-dash spelling. argparse treats "-html-report"
    and "--html-report" as two completely unrelated option strings -- it
    does not fall back from one to the other -- so VALIDATOR_VERSION.txt's
    documented "--html-report" was rejected outright as an unrecognised
    argument while README.md's "-html-report" worked. Registering both keeps
    every existing script and batch file working and makes the documented
    form correct too.
    """
    p = argparse.ArgumentParser(
        prog="dem2dged_validate",
        description="Automated validator for DGED tile sets produced by dem2dged.",
    )
    p.add_argument("tile_folder",
        help="Folder containing generated .tif/.xml DGED tiles")
    p.add_argument("-src", "--src", dest="src", default=None,
        metavar="SOURCE_DEM",
        help="Original input DEM: enables coverage, statistics and "
             "sample-window difference checks against the source")
    p.add_argument("-report", "--report", dest="report", default=None,
        metavar="FILE",
        help="Also write the full report to a text file")
    p.add_argument("-html-report", "--html-report", dest="html_report",
        default=None, metavar="FILE",
        help="Also write a styled HTML report to this file")
    p.add_argument("-max-diff", "--max-diff", dest="max_diff", type=float,
        default=5.0, metavar="METRES",
        help="Tolerance for the sample-window comparison vs the source "
             "(default 5.0 m; some difference from resampling is expected "
             "and normal)")
    p.add_argument("-resample", "--resample", dest="resample",
        default="bilinear", metavar="ALG",
        help="Resampling algorithm the tiles being validated were "
             "actually produced with (near|bilinear|cubic|cubicspline|"
             "average|lanczos|...) -- must match the -resample value (or "
             "the GUI's Resampling Method choice) used for the conversion, "
             "so the section H/H2 source comparison re-warps the source "
             "the same way the tiles were made (default: bilinear, the "
             "tool's long-standing default resampler)")
    p.add_argument("-verbose", "--verbose", action="store_true",
        help="Print every per-tile detail, not just problems")
    p.add_argument("--version", action="version",
        version="dem2dged_validate v%s" % VERSION_DISPLAY)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    rep, tiles = run_validation(args.tile_folder, src=args.src,
                                 max_diff=args.max_diff, verbose=args.verbose,
                                 resample=args.resample)

    if args.report:
        write_text_report(rep, args.report)

    if args.html_report:
        name = os.path.basename(os.path.normpath(args.tile_folder))
        dataset = {"name": name, "folder": args.tile_folder, "src": args.src,
                   "rep": rep, "tiles": tiles}
        write_html_report([dataset], args.html_report)

    return 1 if rep.n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
