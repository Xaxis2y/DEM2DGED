#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
Build and package dem2dged v0.50 executable.

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON

This script:
1. Verifies the build environment
2. Cleans previous builds
3. Rebuilds the executable using PyInstaller
4. Creates a version file
5. Packages everything into a zip file

Usage:
    python BUILD_AND_PACKAGE.py

Must be run from Anaconda Prompt with DGED environment activated:
    conda activate DGED
    cd path\to\this\project\folder
    python BUILD_AND_PACKAGE.py
"""


import sys
import shutil
import subprocess
import zipfile
import json
from pathlib import Path
from datetime import datetime

VERSION = "0.50.1"
# v0.40: release -- numeric VERSION stays audited (audit_pure.py section
# 7), the qualifier rides in RELEASE_STAGE (see dem2dged_package.py).
RELEASE_STAGE = ""
VERSION_DISPLAY = f"{VERSION}-{RELEASE_STAGE}" if RELEASE_STAGE else VERSION
PROJECT_ROOT = Path(__file__).parent.absolute()
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
OUTPUT_PACKAGES_DIR = PROJECT_ROOT / "output_packages"


def print_header(text):
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")


def check_environment():
    print_header("CHECKING BUILD ENVIRONMENT")

    errors = []

    print(f"Python: {sys.version}")
    print(f"Executable: {sys.executable}")
    print(f"Project root: {PROJECT_ROOT}")

    try:
        import osgeo
        print(f"[OK] GDAL/osgeo found: {osgeo.__file__}")
    except ImportError:
        errors.append("ERROR: GDAL/osgeo not found. Run: conda activate DGED")

    try:
        import PyInstaller
        print(f"[OK] PyInstaller found: {PyInstaller.__file__}")
    except ImportError:
        errors.append("ERROR: PyInstaller not found. Run: pip install pyinstaller")

    # v0.34: the full runtime module set is checked, not just five of them.
    # dem2dged_compare.py in particular is imported at MODULE level by
    # dem2dged_gui.py (since v0.33) and listed as a hidden import in
    # dem2dged.spec, but it was absent from this preflight -- so a missing
    # or mistyped file passed every check here and only surfaced as an
    # ImportError when the built .exe was launched.
    required_files = [
        # entry points
        "dem2dged_gui.py",
        "dem2dged.py",
        "dem2dged_validate.py",
        # shared modules imported by the entry points
        "dem2dged_lib.py",
        "dem2dged_geo.py",
        "dem2dged_utm.py",
        "dem2dged_compare.py",
        "dem2dged_logging.py",
        # data files bundled into the exe
        "DGED_GEO_TEMPLATE.xml",
        "DGED_UTM_TEMPLATE.xml",
        # build definitions
        "dem2dged.spec",
        "dem2dged_validate.spec",
    ]

    for fname in required_files:
        fpath = PROJECT_ROOT / fname
        if fpath.exists():
            print(f"[OK] {fname}")
        else:
            errors.append(f"ERROR: Missing {fname}")

    if errors:
        print("\n" + "\n".join(errors))
        return False

    print("\n[OK] All checks passed!\n")
    return True


def clean_previous_builds():
    print_header("CLEANING PREVIOUS BUILDS")

    dirs_to_clean = [BUILD_DIR, DIST_DIR]

    for directory in dirs_to_clean:
        if directory.exists():
            print(f"Removing {directory.name}...")
            try:
                shutil.rmtree(directory)
                print(f"  [OK] Removed")
            except Exception as e:
                print(f"  WARNING: Could not fully remove {directory.name}: {e}")
                print(f"  (This is OK - PyInstaller will rebuild it)\n")
        else:
            print(f"{directory.name} not found (fresh build)")

    print()


def build_executable():
    print_header("BUILDING EXECUTABLE WITH PYINSTALLER")

    spec_file = PROJECT_ROOT / "dem2dged.spec"

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        str(spec_file),
        "--noconfirm"
    ]

    print(f"Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    if result.returncode != 0:
        print("\n[FAIL] PyInstaller build FAILED!")
        return False

    exe_file = DIST_DIR / "dem2dged.exe"
    if exe_file.exists():
        print(f"\n[OK] Executable created: {exe_file}")
        print(f"  Size: {exe_file.stat().st_size / (1024*1024):.1f} MB")
        return True
    else:
        print(f"\n[FAIL] Executable not found: {exe_file}")
        return False


def create_version_file():
    print_header("CREATING VERSION FILE")

    version_info = {
        "version": VERSION,
        "build_date": datetime.now().isoformat(),
        "python_version": sys.version,
        "executable": str(DIST_DIR / "dem2dged.exe"),
    }

    version_file = DIST_DIR / "VERSION.json"

    with open(version_file, "w") as f:
        json.dump(version_info, f, indent=2)

    print(f"Version file created: {version_file}")
    print(json.dumps(version_info, indent=2))
    print()


def create_package():
    print_header("CREATING DISTRIBUTION PACKAGE")

    OUTPUT_PACKAGES_DIR.mkdir(exist_ok=True)

    package_name = f"dem2dged_v{VERSION_DISPLAY}_win64.zip"
    package_path = OUTPUT_PACKAGES_DIR / package_name

    if package_path.exists():
        print(f"Removing existing package: {package_path}")
        package_path.unlink()

    print(f"Creating package: {package_path}\n")

    files_to_zip = [
        ("dist", "dem2dged"),
        (PROJECT_ROOT / "README.md", "dem2dged/README.md"),
    ]

    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arcname in files_to_zip:
            src_path = PROJECT_ROOT / src if not isinstance(src, Path) else src

            if isinstance(src_path, Path) and src_path.is_dir():
                for file_path in src_path.rglob("*"):
                    if file_path.is_file():
                        arcname_full = str(Path(arcname) / file_path.relative_to(src_path))
                        zf.write(file_path, arcname_full)
                        print(f"  + {arcname_full}")
            else:
                zf.write(src_path, arcname)
                print(f"  + {arcname}")

    print(f"\n[OK] Package created: {package_path}")
    print(f"  Size: {package_path.stat().st_size / (1024*1024):.1f} MB\n")

    return package_path


def main():
    print("\n")
    print("+" + "=" * 68 + "+")
    print("|" + " " * 15 + f"dem2dged v{VERSION_DISPLAY} BUILD & PACKAGE" + " " * 19 + "|")
    print("+" + "=" * 68 + "+")

    if not check_environment():
        print("\n[FAIL] Environment check FAILED - cannot proceed")
        sys.exit(1)

    clean_previous_builds()

    if not build_executable():
        print("\n[FAIL] Build FAILED")
        sys.exit(1)

    create_version_file()
    package_path = create_package()

    print_header("BUILD COMPLETE")
    print(f"[OK] Executable: {DIST_DIR / 'dem2dged.exe'}")
    print(f"[OK] Package: {package_path}")
    print(f"\nNext steps:")
    print(f"  1. Test the executable: dist\\dem2dged.exe")
    print(f"  2. If working, distribute: {package_path}")
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAIL] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
