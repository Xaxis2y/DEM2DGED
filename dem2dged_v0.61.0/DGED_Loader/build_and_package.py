#!/usr/bin/env python3
"""
DGED Loader Packaging Automation Script

Automates:
1. Preflight check of required files
2. Version-header refresh while preserving the maintained changelog
3. Zip packaging into the parent folder, alongside this source folder

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON

Version: 0.61.0
Note: unlike DEM2DGED's own dem2dged_package.py, this script does NOT
regenerate VERSION.txt from an embedded copy of its changelog text.
DEM2DGED's v0.32/v0.34 notes describe version strings drifting out of
sync more than once because the same text lived in two places at once;
VERSION.txt here is the single source of truth and is simply packaged
as-is, not rewritten by this script.

Usage:
    python build_and_package.py
"""

import os
import sys
import zipfile
from datetime import datetime

SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_OUTPUT_DIR = os.path.dirname(SOURCE_DIR)
VERSION = "0.61.0"
PACKAGE_NAME = "DGED_Loader_v{0}".format(VERSION)
ZIP_FILENAME = "{0}.zip".format(PACKAGE_NAME)

REQUIRED_FILES = [
    "DGED_Loader.pyt",
    "DGED_Load_Tool_script.py",
    "README.md",
    "ATBX_WIZARD_GUIDE.md",
    "arcgis_pro_smoke_test.py",
    "test_dged_loader.py",
    "VERSION.txt",
]

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}
EXCLUDE_FILE_SUFFIXES = (".zip", ".pyc", ".log")


def verify_source():
    """Verify the source directory contains every required file."""
    if not os.path.isdir(SOURCE_DIR):
        raise FileNotFoundError("Source directory not found: {0}".format(SOURCE_DIR))

    missing = [f for f in REQUIRED_FILES
               if not os.path.isfile(os.path.join(SOURCE_DIR, f))]
    if missing:
        raise FileNotFoundError(
            "Missing required file(s): {0}".format(", ".join(missing)))

    print("OK  Source directory verified ({0} items)".format(
        len(os.listdir(SOURCE_DIR))))
    return True


def refresh_version_file():
    """Refresh VERSION.txt metadata without replacing its changelog."""
    path = os.path.join(SOURCE_DIR, "VERSION.txt")
    with open(path, encoding="utf-8") as stream:
        existing = stream.read()
    marker = existing.find("Changes in ")
    if marker < 0:
        raise ValueError(
            "VERSION.txt has no 'Changes in' section; refusing to replace it.")
    body = existing[marker:]
    header = (
        "DGED Loader Version Information\n"
        "================================\n\n"
        "SPDX-License-Identifier: GPL-2.0-or-later\n"
        "Copyright (c) 2026 Eui Soo SON\n\n"
        "Version: {0}\n"
        "Build Date: {1}\n"
        "Package: {2}\n\n"
        .format(VERSION, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                PACKAGE_NAME))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(header + body)
    print("OK  Refreshed VERSION.txt metadata; changelog preserved")


def create_package_zip():
    """Zip this whole folder into PACKAGE_OUTPUT_DIR, one level up --
    matching dem2dged_package.py's convention of keeping the release zip
    alongside the source folder rather than inside it."""
    zip_path = os.path.join(PACKAGE_OUTPUT_DIR, ZIP_FILENAME)

    if os.path.exists(zip_path):
        os.remove(zip_path)
        print("OK  Removed old package")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(SOURCE_DIR):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
            for file in sorted(files):
                if file.endswith(EXCLUDE_FILE_SUFFIXES):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, SOURCE_DIR)
                zf.write(file_path, os.path.join(PACKAGE_NAME, arcname))
                print("  + {0}".format(arcname))

    size_kb = os.path.getsize(zip_path) / 1024
    print("OK  Created {0} ({1:.1f} KB)".format(ZIP_FILENAME, size_kb))
    return zip_path


def main():
    print("\n{0}".format("=" * 60))
    print("DGED Loader v{0} - Automated Packaging".format(VERSION))
    print("{0}\n".format("=" * 60))

    try:
        print("[1/3] Verifying source directory...")
        verify_source()

        print("\n[2/3] Refreshing version metadata...")
        refresh_version_file()

        print("\n[3/3] Creating package zip...")
        zip_path = create_package_zip()

        print("\n{0}".format("=" * 60))
        print("Package Location: {0}".format(zip_path))
        print("Version: {0}".format(VERSION))
        print("{0}\n".format("=" * 60))
        return 0

    except Exception as e:
        print("\nERROR: {0}".format(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
