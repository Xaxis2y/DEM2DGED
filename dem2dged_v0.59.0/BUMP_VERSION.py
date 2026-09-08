#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.58.1
#
# BUMP_VERSION.py -- generic, idempotent, dry-run-by-default version bumper.
#
# WHY THIS EXISTS
# ---------------
# Every release before this one shipped its own single-use bump script
# (BUMP_v0.56.0.py, BUMP_v0.57.1.py) plus a one-shot UPDATE_VERSIONS.py that
# PREPENDED a hardcoded changelog section to VERSION.txt.  Two problems came
# out of that:
#
#   1. Each hardcoded script covered a slightly different file list, so a file
#      dropped from one list silently stopped being bumped.  That is exactly
#      how dem2dged_lib.py's VERSION constant sat at 0.57.0 through the v0.57.1
#      release (BUMP_v0.57.1.py's VERSION_CONSTANT_FILES omitted it), and how
#      tests/*.py headers are still stamped 0.56.0.
#   2. UPDATE_VERSIONS.py was not idempotent: running it a second time
#      prepended a DUPLICATE "Changes in 0.57.1" block to VERSION.txt.  There
#      was no guard and no dry run.
#
# This script replaces both.  It is:
#   * GENERIC   -- old and new version are arguments, nothing is hardcoded.
#   * IDEMPOTENT -- it only rewrites OLD -> NEW.  Running it twice changes
#                   nothing the second time, because OLD is already gone.
#   * DRY RUN BY DEFAULT -- it prints what it would change; --apply writes.
#   * EXPLICIT ABOUT CHANGELOGS -- it rewrites the "Version:"/"Package:"
#     HEADER of VERSION.txt / VALIDATOR_VERSION.txt / DGED_Loader/VERSION.txt
#     and never touches the "Changes in vX" history below it.  Writing the new
#     changelog entry is a human decision, so it is deliberately not automated.
#
# USAGE (Anaconda Prompt, DGED environment activated)
# ---------------------------------------------------
#   conda activate DGED
#   python BUMP_VERSION.py --from 0.58.0 --to 0.58.1            :: dry run
#   python BUMP_VERSION.py --from 0.58.0 --to 0.58.1 --apply    :: write
#   python BUMP_VERSION.py --check 0.58.1                       :: audit only
#
# --check reports every file that still declares a version other than the one
# given, so a release can be verified without changing anything.

import argparse
import os
import re
import sys

SRC = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Targets.  Every entry is (relative path, list of (regex, replacement)) where
# the regex and replacement are built per-run from OLD/NEW.
# ---------------------------------------------------------------------------

# Files carrying `VERSION = "X.Y.Z"` (and dem2dged_gui.py's APP_VERSION pair).
VERSION_CONSTANT_FILES = [
    "BUILD_AND_PACKAGE.py",
    "dem2dged_compare.py",       # import-fallback VERSION; was stale
                                 # from v0.45 until v0.58.1
    "dem2dged_compliance.py",
    "dem2dged_lib.py",
    "dem2dged_package.py",
    "dem2dged_validate_package.py",
    "DGED_Loader/arcgis_pro_smoke_test.py",
    "DGED_Loader/build_and_package.py",
]

# Files carrying a `# Version: X.Y.Z` or `Version: X.Y.Z` header line.
VERSION_HEADER_FILES = [
    "dem2dged.py",
    "dem2dged_compare.py",
    "dem2dged_compliance.py",
    "dem2dged_env.py",
    "dem2dged_geo.py",
    "dem2dged_gui.py",
    "dem2dged_lib.py",
    "dem2dged_package.py",
    "dem2dged_terrain.py",
    "dem2dged_utm.py",
    "dem2dged_validate.py",
    "dem2dged_validate_package.py",
    "selftest_optimize_resampling.py",
    "selftest_prefilter.py",
    "selftest_prefilter_math.py",
    "selftest_resampling_comparison.py",
    "tests/conftest.py",
    "tests/test_compliance.py",
    "tests/test_converters.py",
    "tests/test_dged_loader_harness.py",
    "tests/test_lib.py",
    "tests/test_resampling_report.py",
    "tests/test_terrain.py",
    "tests/test_v056_regressions.py",
    "tests/test_v057_regressions.py",
    "tests/test_validator.py",
    "DGED_Loader.pyt",
    "DGED_Loader/DGED_Loader.pyt",
    "DGED_Loader/DGED_Load_Tool_script.py",
    "DGED_Loader/arcgis_pro_smoke_test.py",
    "DGED_Loader/build_and_package.py",
    "DGED_Loader/test_dged_loader.py",
]

# PyInstaller VS_VERSION_INFO resources: numeric tuples plus display strings.
VERSION_INFO_FILES = [
    "version_info_gui.txt",
    "version_info_validate.txt",
]

# Release-note files: ONLY the header block is touched, never the changelog.
VERSION_TXT_FILES = [
    "VERSION.txt",
    "VALIDATOR_VERSION.txt",
    "DGED_Loader/VERSION.txt",
]

# Documentation whose *current version* banner must track the release.  These
# are reported, not blind-replaced, unless --docs is given, because a doc can
# legitimately name an older version when describing history.
DOC_FILES = [
    "README.md",
    "START_HERE.md",
    "MANIFEST.md",
    "DEM2DGED_User_Manual.md",
    "QUICKSTART.html",
    "BUILD_SCRIPTS_GUIDE.md",
    "REBUILD_GUIDE.md",
    "DEM_SOURCES_GUIDE.md",
    "DGIWG_STANDARDS_TRACKING.md",
    "DEM2DGED_Compliance_Policy.json",
    "DGED_Loader/README.md",
    "tests/README.md",
]


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _tuple(version):
    """'0.58.1' -> '0, 58, 1, 0' for a PyInstaller filevers/prodvers tuple."""
    parts = [int(p) for p in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return ", ".join(str(p) for p in parts[:4])


def rules_for(old, new):
    """Return {relative path: [(compiled regex, replacement), ...]}."""
    o = re.escape(old)
    rules = {}

    def add(path, pairs):
        rules.setdefault(path, []).extend(pairs)

    for path in VERSION_CONSTANT_FILES:
        add(path, [(re.compile(r'(VERSION\s*=\s*")%s(")' % o),
                    r"\g<1>%s\g<2>" % new)])
    add("dem2dged_gui.py",
        [(re.compile(r'(APP_VERSION(?:_DISPLAY)?\s*=\s*")%s(")' % o),
          r"\g<1>%s\g<2>" % new)])

    for path in VERSION_HEADER_FILES:
        add(path, [(re.compile(r"(^\s*#?\s*Version:\s*)%s\s*$" % o, re.M),
                    r"\g<1>%s" % new)])

    for path in VERSION_INFO_FILES:
        add(path, [
            (re.compile(r"(filevers=\()%s(\))" % re.escape(_tuple(old))),
             r"\g<1>%s\g<2>" % _tuple(new)),
            (re.compile(r"(prodvers=\()%s(\))" % re.escape(_tuple(old))),
             r"\g<1>%s\g<2>" % _tuple(new)),
            (re.compile(r"(u')%s(')" % o), r"\g<1>%s\g<2>" % new),
        ])

    for path in VERSION_TXT_FILES:
        add(path, [
            (re.compile(r"(^Version:\s*)%s\s*$" % o, re.M), r"\g<1>%s" % new),
            (re.compile(r"(^Package:\s*\S*?_?v?)%s\s*$" % o, re.M),
             r"\g<1>%s" % new),
        ])
    return rules


def apply_rules(rules, apply_changes):
    changed, skipped = [], []
    for rel, pairs in sorted(rules.items()):
        path = os.path.join(SRC, rel)
        if not os.path.isfile(path):
            skipped.append((rel, "not found"))
            continue
        text = original = _read(path)
        hits = 0
        for pattern, repl in pairs:
            text, n = pattern.subn(repl, text)
            hits += n
        if hits and text != original:
            if apply_changes:
                _write(path, text)
            changed.append((rel, hits))
        else:
            skipped.append((rel, "no match (already current, or not present)"))
    return changed, skipped


def scan_declared(expected):
    """Report every declared version that is not ``expected``."""
    patterns = [
        re.compile(r'VERSION\s*=\s*"(\d+\.\d+(?:\.\d+)?)"'),
        re.compile(r'APP_VERSION(?:_DISPLAY)?\s*=\s*"(\d+\.\d+(?:\.\d+)?)"'),
        re.compile(r"^\s*#?\s*Version:\s*(\d+\.\d+(?:\.\d+)?)\s*$", re.M),
    ]
    stale = []
    seen = set(VERSION_CONSTANT_FILES + VERSION_HEADER_FILES
               + VERSION_TXT_FILES + VERSION_INFO_FILES)
    for rel in sorted(seen):
        path = os.path.join(SRC, rel)
        if not os.path.isfile(path):
            continue
        head = _read(path)[:8000]
        if rel in VERSION_TXT_FILES:
            # Release-note files carry every historical version below the
            # header, and their prose quotes old version strings verbatim
            # (e.g. 'VERSION = "0.45"' in a changelog entry about fixing it).
            # Only the header block declares the CURRENT version, so stop at
            # the first "Changes in " line.
            cut = head.find("Changes in ")
            if cut > 0:
                head = head[:cut]
        for pattern in patterns:
            for found in pattern.findall(head):
                if found != expected:
                    stale.append((rel, found))
    return stale


def scan_docs(expected):
    """Report documentation lines naming a version other than ``expected``."""
    banner = re.compile(
        r"^(?:#|\s*<title>|\s*<div class=\"badge\">|\*\*Current version"
        r"|\s*dem2dged\s+v|\s*DEM2DGED\s+v)"
        r".*?v?(\d+\.\d+(?:\.\d+)?)", re.M)
    stale = []
    for rel in DOC_FILES:
        path = os.path.join(SRC, rel)
        if not os.path.isfile(path):
            continue
        # Only the FIRST banner in a document states its current version.
        # Later headings are legitimately historical ("What was new in
        # v0.55.0", "Summary of v0.23 Changes") and reporting them as stale
        # would train the reader to ignore this output.
        # ...and only in the file's banner region (the first 15 lines).
        # Below that, a version in a heading is history, not a claim about
        # what this file describes.
        for line in _read(path).splitlines()[:15]:
            match = banner.match(line)
            if match:
                if match.group(1) != expected:
                    stale.append((rel, match.group(1), line.strip()[:90]))
                break
    return stale


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Bump or audit dem2dged version declarations.")
    ap.add_argument("--from", dest="old", help="version currently declared")
    ap.add_argument("--to", dest="new", help="version to write")
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default: dry run)")
    ap.add_argument("--check", metavar="VERSION",
                    help="audit only: list declarations that are not VERSION")
    args = ap.parse_args(argv)

    if args.check:
        stale = scan_declared(args.check)
        docs = scan_docs(args.check)
        for rel, found in stale:
            print("  STALE  %-46s declares %s" % (rel, found))
        for rel, found, line in docs:
            print("  DOC    %-46s names %s | %s" % (rel, found, line))
        total = len(stale) + len(docs)
        print("\n%d stale declaration(s) against %s" % (total, args.check))
        return 1 if total else 0

    if not args.old or not args.new:
        ap.error("--from and --to are required unless --check is used")
    if args.old == args.new:
        ap.error("--from and --to are identical; nothing to do")

    rules = rules_for(args.old, args.new)
    changed, skipped = apply_rules(rules, args.apply)

    mode = "APPLIED" if args.apply else "DRY RUN (use --apply to write)"
    print("dem2dged version bump %s -> %s   [%s]\n" % (args.old, args.new, mode))
    for rel, hits in changed:
        print("  [%s] %-46s %d replacement(s)"
              % ("ok" if args.apply else "--", rel, hits))
    for rel, why in skipped:
        print("  [ ..] %-46s %s" % (rel, why))
    print("\n%d file(s) %s." % (len(changed),
                                "updated" if args.apply else "would change"))
    print("Release notes are NOT auto-written: add the new 'Changes in v%s'"
          % args.new)
    print("section to VERSION.txt / VALIDATOR_VERSION.txt / "
          "DGED_Loader/VERSION.txt by hand, then re-run with --check %s."
          % args.new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
