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
# v0.44: the output directory can be overridden with the environment
# variable DEM2DGED_PACKAGE_OUTPUT_DIR. RELEASE_CHECK step 01c uses it to run
# this script for real -- under an ASCII console, to prove it cannot die on a
# tick mark again -- without leaving a half-built zip next to the project.
# Unset (the normal case) it is the parent of the source folder, exactly as
# before.
PACKAGE_OUTPUT_DIR = os.environ.get("DEM2DGED_PACKAGE_OUTPUT_DIR") \
    or os.path.dirname(SOURCE_DIR)
VERSION = "0.55.0"
# VERSION is a three-part semantic release number and is the value checked by
# the tool, audit and package metadata. RELEASE_STAGE is only for an optional
# pre-release qualifier such as rc1.
RELEASE_STAGE = ""
VERSION_DISPLAY = f"{VERSION}-{RELEASE_STAGE}" if RELEASE_STAGE else VERSION
PACKAGE_NAME = (f"dem2dged_v{VERSION}_{RELEASE_STAGE}" if RELEASE_STAGE
                else f"dem2dged_v{VERSION}")
ZIP_FILENAME = f"{PACKAGE_NAME}.zip"

def create_version_file(target_dir):
    """Refresh VERSION.txt's HEADER, preserving the changelog below it.

    v0.45 -- THIS FUNCTION USED TO DESTROY THE RELEASE NOTES.

    It wrote VERSION.txt from a hardcoded f-string whose changelog was
    frozen at "Changes in v0.40". Every packaging run therefore overwrote
    the maintained file with that stale copy, silently deleting every
    entry written since. It is why the v0.41 release notes do not exist:
    they were written, then packaged away. The damage is invisible at the
    time -- the script prints "[OK] Created VERSION.txt" and the header
    it writes is correct, so only the body is wrong, and only if you look.

    VERSION.txt is now treated as what it actually is: a maintained
    document. Only the three header lines (Version / Build Date / Package)
    are rewritten; everything from the first "Changes in" line onward is
    kept exactly as it was. If the file does not exist at all, a minimal
    stub is created so a fresh checkout still gets something valid.
    """
    path = os.path.join(target_dir, "VERSION.txt")
    header = ("DEM2DGED Version Information\n"
              "============================\n"
              "\n"
              "SPDX-License-Identifier: GPL-2.0-or-later\n"
              "Copyright (c) 2026 Eui Soo SON\n"
              "\n"
              "Version: %s\n"
              "Build Date: %s\n"
              "Package: %s\n"
              "\n" % (VERSION_DISPLAY,
                       datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                       PACKAGE_NAME))

    body = ""
    if os.path.isfile(path):
        existing = open(path, encoding="utf-8").read()
        marker = existing.find("Changes in ")
        if marker >= 0:
            body = existing[marker:]
        else:
            # No recognisable changelog: keep the whole thing rather than
            # throw away something we do not understand.
            body = existing

    if not body:
        body = ("Changes in %s:\n"
                "- See README.md for the full changelog.\n" % VERSION_DISPLAY)

    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body)

    print(f"[OK] Refreshed VERSION.txt header (changelog preserved: "
          f"{len(body.splitlines())} lines)")

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

    print(f"[OK] Source directory verified ({len(os.listdir(SOURCE_DIR))} items)")
    return True

# v0.32: create_package_zip() used to os.walk(SOURCE_DIR) with no exclusions
# at all, so every release zip also bundled PyInstaller's build/ and dist/
# output (including the compiled .exe files), __pycache__, .pytest_cache,
# and any earlier release zips already sitting in the project folder --
# each new package nested every previous one inside it. These are the
# directories and file patterns that don't belong in a source/docs release
# package; keep this list in sync with what actually accumulates in the
# project folder between releases.
# v0.50.3: DGED_Loader is now an integrated companion component. It is
# intentionally INCLUDED so the source release contains the ArcGIS Pro tile
# loader that opens a delivered DGED set for visual source/difference review.
# v0.39: "DEM" (operator-supplied source DEM data placed in the tool folder
# for testing -- can be gigabytes) and any "output*" conversion folders are
# excluded: neither is part of the source/docs release, and the DEM data in
# particular must never be bundled into the shipped zip.
#
# v0.42 -- THE ROOT CAUSE OF A BUG THAT HAD TO BE FIXED TWICE.
# This set listed "tests" -- twice, the giveaway that it was meant to name
# two different things and one of them got mistyped. So `dem2dged_package.py`
# STRIPPED THE TEST SUITE OUT OF EVERY RELEASE ZIP, while `pytest.ini`
# (testpaths = tests) and `MANIFEST.md` (which documents five test files
# under "Tests & verification") both shipped intact. Anyone who unzipped a
# release and ran `pytest` as MANIFEST.md instructs got:
#
#     ERROR: file or directory not found: tests
#
# That is exactly how tests/ came to be "missing from the package" in v0.40
# (finding 3 of the v0.41 review), get rebuilt by hand, and then go missing
# again in v0.41 -- rebuilding the directory could never stick, because the
# packaging step deleted it on the way out every time.
#
# The intent was clearly to exclude the test suite's GENERATED OUTPUT, not
# its source. Those are named explicitly below instead, and "tests" is gone.
EXCLUDE_DIRS = {"build", "dist", "__pycache__", ".pytest_cache", "_v027_sync",
                  "DGED Loader", "ArcGIS_PRO_QA_toolbox", "DEM",
                 "test_output", "_release_check_logs", "_verify_pages",
                 "logs"}  # generated test/run logs are evidence, not release input
EXCLUDE_DIR_PREFIXES = ("dem2dged_validate_v",   # unzipped staging snapshots
                        "output",                # output/, output_v037/, ...
                        ".pytest_tmp")           # explicit pytest --basetemp dirs
# v0.42: .tmp / .log / .bak added. The v0.41 review (finding 9) recorded
# that a stray 311 KB scratch file, lu49gpd00.tmp, was sitting in the
# project folder and WOULD be bundled into dem2dged_v0.41.zip, because the
# tuple stopped at .jpeg. Scratch files of these three kinds are never a
# release input, so excluding them by suffix is safer than relying on
# somebody remembering to delete them before packaging.
EXCLUDE_FILE_SUFFIXES = (".zip", ".pdf", ".jpg", ".jpeg",
                         ".tmp", ".log", ".bak")
# v0.36: note_and_issue.md is a session diagnostic note (written for one
# specific bug investigation, not maintained release documentation like
# README.md/CODE_REVIEW_*.md) -- it doesn't help a user run, build, test, or
# understand the tool, so it doesn't belong in the release zip any more than
# the old user-manual draft below does.
# 2026-08-11: selftest_resampling_comparison_report.html added. MANIFEST.md's
# "Not part of the release" section has documented this filename by name
# since it was written -- "an artefact of a past self-test run, not an
# input" -- but nothing in EXCLUDE_FILE_SUFFIXES actually caught it (.html
# isn't excludable by suffix; QUICKSTART.html must still ship), so every
# release zip built since has quietly included whatever the last local
# self-test run happened to leave on disk. Found while packaging v0.45: the
# file sitting in the project folder was a stale run from a previous
# session, bundled into dem2dged_v0.45.zip until this line was added. Same
# shape of bug as the "tests" EXCLUDE_DIRS entry in v0.42 -- documented
# intent that the code never actually carried out.
# 2026-08-12: selftest_log.txt added -- the same shape of gap as
# selftest_resampling_comparison_report.html above. It is DIAGNOSE_SECTION_H's
# --selftest LOG OUTPUT from a session run (see DIAGNOSE_SECTION_H_v0.11.py),
# not a release input, and ".txt" is not one of EXCLUDE_FILE_SUFFIXES so
# nothing else would have caught it.
EXCLUDE_FILES = {"DEM2DGED_User_Manual_old.docx", "note_and_issue.md",
                 "selftest_resampling_comparison_report.html",
                 "selftest_log.txt", "selftest_prefilter_log.txt"}


def create_package_zip():
    """Create zip package from source directory."""
    # v0.44: create the output directory if it does not exist.
    # Normally it is the parent of the project folder and always
    # exists, but DEM2DGED_PACKAGE_OUTPUT_DIR can point anywhere,
    # and zipfile.ZipFile() reports a missing parent as a bare
    # FileNotFoundError naming the ZIP rather than the directory.
    os.makedirs(PACKAGE_OUTPUT_DIR, exist_ok=True)
    zip_path = os.path.join(PACKAGE_OUTPUT_DIR, ZIP_FILENAME)

    # Remove old zip if exists
    if os.path.exists(zip_path):
        os.remove(zip_path)
        print(f"[OK] Removed old package")

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
    print(f"[OK] Created {ZIP_FILENAME} ({size_mb:.2f} MB)")
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
        # v0.44: this handler used to print a U+2717 glyph, so on a cp949
        # console it raised UnicodeEncodeError of its own and the SECOND
        # traceback replaced the first -- whatever the real failure was, it
        # was never shown. An error path must not be able to fail. Both the
        # marker (ASCII) and the printer (dl.safe_print, which cannot raise
        # on an unencodable console) are now chosen with that in mind, and
        # the traceback is printed so a non-obvious failure is diagnosable
        # from one run instead of two.
        import traceback

        try:
            import dem2dged_lib as _dl
            _p = _dl.safe_print
        except Exception:
            def _p(*a, **k):
                try:
                    print(*a, **k)
                except Exception:
                    pass
        _p("\n[FAIL] Error: %s: %s" % (type(e).__name__, e))
        _p(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())
