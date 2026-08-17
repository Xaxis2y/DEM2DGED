# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

#!/usr/bin/env python3


import os
import sys
import zipfile
from datetime import datetime

# Configuration
# v0.28: SOURCE_DIR now derives from this script's own location instead of a
# hardcoded absolute path -- see dem2dged_package_v0.26.py for why (the
# previous hardcoded path pointed at a different, older v0.24 folder).
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
# v0.44: the output directory can be overridden with the environment
# variable DEM2DGED_PACKAGE_OUTPUT_DIR. RELEASE_CHECK step 01c uses it to run
# this script for real -- under an ASCII console, to prove it cannot die on a
# tick mark again -- without leaving a half-built zip next to the project.
# Unset (the normal case) it is the parent of the source folder, exactly as
# before.
PACKAGE_OUTPUT_DIR = os.environ.get("DEM2DGED_PACKAGE_OUTPUT_DIR") \
    or os.path.dirname(SOURCE_DIR)
VERSION = "0.50.1"
# v0.40: release -- numeric VERSION stays audited, the qualifier
# rides in RELEASE_STAGE (see dem2dged_package.py).
RELEASE_STAGE = ""
VERSION_DISPLAY = f"{VERSION}-{RELEASE_STAGE}" if RELEASE_STAGE else VERSION
PACKAGE_NAME = (f"dem2dged_validate_v{VERSION}_{RELEASE_STAGE}" if RELEASE_STAGE
                else f"dem2dged_validate_v{VERSION}")
ZIP_FILENAME = f"{PACKAGE_NAME}.zip"

def create_version_file(target_dir):
    """Refresh VALIDATOR_VERSION.txt's HEADER, preserving the changelog below it.

    v0.45 -- THIS FUNCTION USED TO DESTROY THE RELEASE NOTES.

    It wrote VALIDATOR_VERSION.txt from a hardcoded f-string whose changelog was
    frozen at "Changes in v0.40". Every packaging run therefore overwrote
    the maintained file with that stale copy, silently deleting every
    entry written since. It is why the v0.41 release notes do not exist:
    they were written, then packaged away. The damage is invisible at the
    time -- the script prints "[OK] Created VALIDATOR_VERSION.txt" and the header
    it writes is correct, so only the body is wrong, and only if you look.

    VALIDATOR_VERSION.txt is now treated as what it actually is: a maintained
    document. Only the three header lines (Version / Build Date / Package)
    are rewritten; everything from the first "Changes in" line onward is
    kept exactly as it was. If the file does not exist at all, a minimal
    stub is created so a fresh checkout still gets something valid.
    """
    path = os.path.join(target_dir, "VALIDATOR_VERSION.txt")
    header = ("DEM2DGED Validator Version Information\n"
              "========================================\n"
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

    print(f"[OK] Refreshed VALIDATOR_VERSION.txt header (changelog preserved: "
          f"{len(body.splitlines())} lines)")

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

    print(f"[OK] Source directory verified")
    return True

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

    # Create zip with only validator-related files
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 2026-08-11: LICENSE added. MANIFEST.md's "Staging folder" section
        # has always described this bundle as "validator + dem2dged_lib.py +
        # manual + LICENSE + README + rebuild script + VALIDATOR_VERSION.txt"
        # -- the intent was there from the start -- but this list never
        # actually carried LICENSE, so every dem2dged_validate_v*.zip shipped
        # without it despite being GPL-2.0-or-later source. Found while
        # packaging v0.45.
        files_to_include = [
            "dem2dged_validate.py",
            "dem2dged_lib.py",
            "dem2dged_terrain.py",
            "DEM2DGED_Compliance_Policy.json",
            "rebuild_validate_exe.bat",
            "VALIDATOR_VERSION.txt",
            "README.md",
            "DEM2DGED_User_Manual.docx",
            "LICENSE"
        ]

        for file in files_to_include:
            file_path = os.path.join(SOURCE_DIR, file)
            if os.path.isfile(file_path):
                arcname = os.path.relpath(file_path, SOURCE_DIR)
                zf.write(file_path, os.path.join(PACKAGE_NAME, arcname))

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"[OK] Created {ZIP_FILENAME} ({size_mb:.2f} MB)")
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
        # v0.44: see the identical handler and rationale in
        # dem2dged_package.py -- an error path must not itself be able to
        # fail on a legacy console code page.
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
