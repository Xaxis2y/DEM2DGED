# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# BUMP_v0.56.0.py
# Bump Script Version: 0.01
# Part 3 of the v0.55.0 -> v0.56.0 release: version strings, changelogs,
# lint hygiene, and test discovery for the DGED_Loader harness.
#
# ============================================================================
# WHAT IT DOES, AND WHAT IT DELIBERATELY DOES NOT
# ============================================================================
# CODE and CONFIG files carry "0.55.0" only ever as "the current version", so
# they get a straight global replace.
#
# VERSION.txt / VALIDATOR_VERSION.txt / DGED_Loader/VERSION.txt are different:
# they hold a HEADER (current version) followed by a CUMULATIVE CHANGELOG in
# which "Changes in v0.55.0:" must survive untouched. Those get a header-only
# edit plus a prepended v0.56.0 section.
#
# DOCUMENTATION (README, START_HERE, the manuals) is NOT globally replaced.
# Each has a "What's new in v0.55.0" section describing what v0.55.0 actually
# did; renaming it to v0.56.0 would make the docs claim this release shipped
# the previous release's features. Only the explicit current-version markers
# are updated, and a real v0.56.0 section is added where one belongs.
#
#     (DGED) C:\...> python BUMP_v0.56.0.py           (dry run)
#     (DGED) C:\...> python BUMP_v0.56.0.py --apply

from __future__ import annotations

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OLD = "0.55.0"
NEW = "0.56.0"

# ── files where "0.55.0" always means "the current version" ──────────────────
GLOBAL_BUMP = [
    "dem2dged.py", "dem2dged_compare.py", "dem2dged_compliance.py",
    "dem2dged_env.py", "dem2dged_geo.py", "dem2dged_gui.py", "dem2dged_lib.py",
    "dem2dged_package.py", "dem2dged_terrain.py", "dem2dged_utm.py",
    "dem2dged_validate.py", "dem2dged_validate_package.py",
    "selftest_prefilter.py", "selftest_prefilter_math.py",
    "BUILD_AND_PACKAGE.py",
    "DEM2DGED_Compliance_Policy.json",
    "version_info_gui.txt", "version_info_validate.txt",
    os.path.join("tests", "conftest.py"),
    os.path.join("tests", "test_compliance.py"),
    os.path.join("tests", "test_converters.py"),
    os.path.join("tests", "test_lib.py"),
    os.path.join("tests", "test_resampling_report.py"),
    os.path.join("tests", "test_terrain.py"),
    os.path.join("tests", "test_validator.py"),
    os.path.join("DGED_Loader", "DGED_Loader.pyt"),
    os.path.join("DGED_Loader", "DGED_Load_Tool_script.py"),
    os.path.join("DGED_Loader", "build_and_package.py"),
    os.path.join("DGED_Loader", "test_dged_loader.py"),
]

# ── changelog entries ────────────────────────────────────────────────────────

MAIN_CHANGELOG = """Changes in v0.56.0:
- FIXED (A1) try_direct_copy_tile() indexed the source half a pixel off. GDAL
  reports the pixel-CORNER geotransform for an AREA_OR_POINT=Point raster, but
  the code compared that corner against a DGED POST. A correctly registered
  source was therefore always rejected (the fast path was unreachable), and a
  source whose corners happened to land on the post grid was accepted and
  written with every value half a post out of place.
- FIXED (A2) sidecar XML values were never escaped. A source file named
  "DEM_A&B.tif" was enough, with no unusual flags, to make every sidecar in a
  delivery malformed. _xml_escape() is now applied at the write boundary.
- FIXED (A3) the four XML writers used the platform code page while declaring
  encoding="UTF-8". On cp1252 a non-ASCII lineage aborted the conversion
  mid-run with UnicodeEncodeError. All four now write UTF-8, and the validator
  reports a mis-encoded sidecar as a finding instead of crashing on it.
- FIXED (A4) dem2dged_validate.py called sys.exit() at module scope.
  SystemExit is a BaseException, so it passed straight through the
  "except Exception" guards in dem2dged.py and dem2dged_gui.py that exist to
  degrade gracefully. Both guards now raise ImportError.
- FIXED (A5) the Svalbard UTM auto-detect split on the wrong longitudes
  (-6/6/18 instead of 0/9/21/33), resolving 7 of 9 test longitudes to the
  wrong zone. The Norway branch was byte-identical to the generic branch and
  applied no special handling; both warnings went through dl.dp() and were
  invisible without -verbose.
- FIXED (A6) a NaN NoData sentinel defeated both validity masks: a good tile
  reported (0, 0, 100.0), and the pre-filter spread one NaN post into 81. One
  shared valid_data_mask() predicate now serves compute_tile_stats(),
  clamp_tile_to_range() and build_prefiltered_source().
- FIXED (A7) extent reprojection sampled only the four corners, so the curved
  edges of a reprojected rectangle fell outside the box. Measured at 4116 m of
  lost coverage on a 6x5 degree extent at 55-60N -- 0.82 of a level-6 tile,
  and those tiles were never generated. Both bbox transforms now densify each
  edge with 21 points, matching GDAL's own SuggestedWarpOutput.
- FIXED (B1) the GUI is a second converter implementation and had fallen
  behind: no anti-alias pre-filter (the v0.49 headline feature), no per-tile
  failure tolerance (one bad tile aborted the whole file, leaving no table of
  contents or collection metadata) and no "no tiles produced" error. All three
  closed, and a GUI-versus-CLI equivalence test now guards against future
  drift.
- FIXED (B2) inspect_source() read the entire raster into memory and cast it
  to float64 -- 4x an Int16 source -- to obtain a min and a max, and ran twice
  per CLI conversion. It now uses GDAL's streamed ComputeRasterMinMax and
  caches per (path, mtime, size).
- FIXED (B3) a compliance profile absent from the policy file silently meant
  "no thresholds", and an all-INFO result reported overall PASS. Missing
  profiles now fall back to the bundled defaults, and a run that evaluated
  nothing reports NOT_EVALUATED.
- FIXED (B4) direct-copied tiles were written without the data-type-aware LZW
  predictor, so a delivery could mix two compression profiles.
- FIXED (B5) the resume check keyed only on the sidecar, so a deleted or
  corrupted tile beside a surviving .xml read as "already done" and could
  never be regenerated.
- FIXED (B6) the product extent was widened at the top of the tile loop,
  before the skip and failure branches, so tiles that never reached the
  delivery still shaped the collection bounding box.
- FIXED (C3) the validator leaked a file handle reading each sidecar.
- FIXED (C4) unused imports and placeholder-free f-strings removed.
- ADDED tests/test_v056_regressions.py: one test per finding above, each
  failing on v0.55.0 and passing here, including the first coverage of
  try_direct_copy_tile(), build_prefiltered_source() and the GUI converters.
- ADDED tests/test_dged_loader_harness.py so the DGED_Loader test harness runs
  under pytest instead of only when invoked by hand.

"""

VALIDATOR_CHANGELOG = """Changes in v0.56.0:
- The two module-scope sys.exit() import guards now raise ImportError.
  SystemExit is a BaseException, so callers guarding the import with
  "except Exception" in order to degrade -- dem2dged.py's auto-validation and
  dem2dged_gui.py's "Validate after conversion" checkbox -- were bypassed and
  the importing process died instead.
- A sidecar that is not valid UTF-8, or that cannot be read at all, is now
  reported as a per-tile finding. Only ET.ParseError was caught before, so a
  sidecar written in the platform code page by a pre-v0.56 converter crashed
  the validator with a raw traceback.
- The sidecar read now uses a context manager (the file handle leaked).

"""

LOADER_CHANGELOG = """Changes in v0.56.0:
- Version-aligned with DEM2DGED v0.56.0; tile discovery behaviour is unchanged.
- The test harness now also runs under pytest, via
  tests/test_dged_loader_harness.py. pytest.ini sets "testpaths = tests", so
  this harness had never run in the release gate.

"""

# ── targeted documentation edits ─────────────────────────────────────────────
DOC_EDITS = [
    ("README.md",
     "**Current version: v0.55.0**",
     "**Current version: v0.56.0**"),
    ("README.md",
     "**v0.55.0 release note:**",
     "**v0.56.0 release note:** a full-project review fixed seven correctness\n"
     "defects, six robustness gaps and five hygiene items -- see\n"
     "`Changes in v0.56.0` in `VERSION.txt`. Every one is covered by a test in\n"
     "`tests/test_v056_regressions.py` that fails on v0.55.0. Three are worth\n"
     "knowing about before you re-run an existing job: the direct-copy fast\n"
     "path shipped half-post-shifted coordinates, sidecar XML was neither\n"
     "escaped nor UTF-8 encoded, and wide high-latitude extents lost edge\n"
     "tiles. The GUI also gains the anti-alias pre-filter it has lacked since\n"
     "v0.49.\n"
     "\n"
     "**v0.55.0 release note:**"),
    ("START_HERE.md",
     "# DEM2DGED v0.55.0 — Start Here",
     "# DEM2DGED v0.56.0 — Start Here"),
    ("MANIFEST.md",
     "# dem2dged v0.55.0 — Package Contents",
     "# dem2dged v0.56.0 — Package Contents"),
    ("DEM2DGED_User_Manual.md",
     "# DEM2DGED User Manual — v0.55.0",
     "# DEM2DGED User Manual — v0.56.0"),
    ("REBUILD_GUIDE.md",
     "# dem2dged v0.55.0 Rebuild Guide",
     "# dem2dged v0.56.0 Rebuild Guide"),
    ("BUILD_SCRIPTS_GUIDE.md",
     "dem2dged v0.55.0",
     "dem2dged v0.56.0"),
    ("QUICKSTART.html",
     "<title>dem2dged v0.55.0 – Quick Start Guide</title>",
     "<title>dem2dged v0.56.0 – Quick Start Guide</title>"),
    ("QUICKSTART.html",
     '<div class="badge">Quick Start Guide · v0.55.0</div>',
     '<div class="badge">Quick Start Guide · v0.56.0</div>'),
    ("DGED_Loader/README.md",
     "# DGED Loader v0.55.0",
     "# DGED Loader v0.56.0"),
    ("DGED_Loader/README.md",
     "Integrated with the DEM2DGED v0.55.0 source release.",
     "Integrated with the DEM2DGED v0.56.0 source release."),
]

# ── C4 lint hygiene ──────────────────────────────────────────────────────────
# NOTE: audit_pure.py's `import numpy` is NOT removed, even though pyflakes
# reports it as unused. It sits inside a try/except ImportError whose whole
# purpose is to probe whether numpy is importable and print a diagnosis if it
# is not -- the import IS the test. It already carries `# noqa: F401`.
# Deleting it because a linter complained would silently delete the check.
HYGIENE = [
    ("selftest_prefilter.py", "import math\n", ""),
    (os.path.join("tests", "test_terrain.py"), "import json\n", ""),
]


def _read(path):
    return io.open(path, encoding="utf-8", newline="").read()


def _write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def bump_header_and_changelog(path, changelog, package_prefix):
    """Update the 'Version:' / 'Package:' header lines and prepend a section.

    Everything below the header -- the cumulative changelog -- is left exactly
    as it is, which is the whole point: 'Changes in v0.55.0:' has to survive.
    """
    text = _read(path)
    changed = False
    if ("Version: %s" % OLD) in text:
        text = text.replace("Version: %s" % OLD, "Version: %s" % NEW, 1)
        changed = True
    if ("Package: %s%s" % (package_prefix, OLD)) in text:
        text = text.replace("Package: %s%s" % (package_prefix, OLD),
                            "Package: %s%s" % (package_prefix, NEW), 1)
        changed = True
    if ("Changes in v%s:" % NEW) not in text:
        marker = "Changes in v%s:" % OLD
        if marker in text:
            i = text.index(marker)
            text = text[:i] + changelog + text[i:]
            changed = True
    return text, changed


def main():
    ap = argparse.ArgumentParser(
        description="Bump dem2dged from v%s to v%s." % (OLD, NEW))
    ap.add_argument("--apply", action="store_true",
                    help="write the files (without this it is a dry run)")
    args = ap.parse_args()

    print("=" * 74)
    print("dem2dged version bump  v%s -> v%s   (%s)"
          % (OLD, NEW, "APPLY" if args.apply else "DRY RUN"))
    print("=" * 74)

    n_files = n_edits = n_missing = 0

    # 1. global replace in code and config
    print("\n-- version strings (global replace)")
    for rel in GLOBAL_BUMP:
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            print("   [MISS] %s" % rel)
            n_missing += 1
            continue
        text = _read(path)
        hits = text.count(OLD)
        if not hits:
            print("   [ -- ] %-46s (already %s)" % (rel, NEW))
            continue
        if args.apply:
            _write(path, text.replace(OLD, NEW))
        print("   [ OK ] %-46s %d occurrence(s)" % (rel, hits))
        n_files += 1
        n_edits += hits

    # 2. version files: header + prepended changelog
    print("\n-- version files (header + new changelog section)")
    for rel, changelog, prefix in (
            ("VERSION.txt", MAIN_CHANGELOG, "dem2dged_v"),
            ("VALIDATOR_VERSION.txt", VALIDATOR_CHANGELOG,
             "dem2dged_validate_v"),
            (os.path.join("DGED_Loader", "VERSION.txt"), LOADER_CHANGELOG,
             "DGED_Loader_v")):
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            print("   [MISS] %s" % rel)
            n_missing += 1
            continue
        text, changed = bump_header_and_changelog(path, changelog, prefix)
        if not changed:
            print("   [ -- ] %-46s (already current)" % rel)
            continue
        if args.apply:
            _write(path, text)
        print("   [ OK ] %-46s header + changelog" % rel)
        n_files += 1
        n_edits += 1

    # 3. targeted documentation edits
    print("\n-- documentation (targeted, changelog sections preserved)")
    doc_texts = {}
    for rel, old, new in DOC_EDITS:
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            print("   [MISS] %s" % rel)
            n_missing += 1
            continue
        text = doc_texts.get(rel) or _read(path)
        if new in text:
            print("   [SKIP] %-46s %s" % (rel, old[:34]))
            doc_texts[rel] = text
            continue
        if old not in text:
            print("   [FAIL] %-46s %s" % (rel, old[:34]))
            n_missing += 1
            doc_texts[rel] = text
            continue
        doc_texts[rel] = text.replace(old, new, 1)
        print("   [ OK ] %-46s %s" % (rel, old[:34]))
        n_edits += 1
    if args.apply:
        for rel, text in doc_texts.items():
            _write(os.path.join(HERE, rel), text)
            n_files += 1

    # 4. lint hygiene
    print("\n-- lint hygiene (C4)")
    for rel, old, new in HYGIENE:
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            continue
        text = _read(path)
        if old not in text:
            print("   [ -- ] %-46s (nothing to remove)" % rel)
            continue
        if args.apply:
            _write(path, text.replace(old, new, 1))
        print("   [ OK ] %-46s removed unused import" % rel)
        n_edits += 1

    # 5. placeholder-free f-strings
    print("\n-- placeholder-free f-strings (C4)")
    import re
    fstring = re.compile(r'''(?<![\w'"])f(?=(["'])(?:(?!\1).)*\1)''')
    for rel in ("BUILD_AND_PACKAGE.py", "dem2dged_anaconda_environment.py",
                "dem2dged_package.py", "dem2dged_validate_package.py"):
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            continue
        text = _read(path)
        out_lines, fixed = [], 0
        for line in text.split("\n"):
            # only touch a line whose f-string contains no {...} at all
            if "f\"" in line or "f'" in line:
                if "{" not in line:
                    new_line = fstring.sub("", line)
                    if new_line != line:
                        fixed += 1
                        line = new_line
            out_lines.append(line)
        if not fixed:
            print("   [ -- ] %-46s (none)" % rel)
            continue
        if args.apply:
            _write(path, "\n".join(out_lines))
        print("   [ OK ] %-46s %d f-string(s)" % (rel, fixed))
        n_edits += fixed

    print("")
    print("=" * 74)
    print("files touched=%d  edits=%d  missing/failed=%d"
          % (n_files, n_edits, n_missing))
    if not args.apply:
        print("Dry run. Re-run with --apply to write the files.")
    print("=" * 74)
    return 1 if n_missing else 0


if __name__ == "__main__":
    sys.exit(main())
