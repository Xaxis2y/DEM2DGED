#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.8
"""Build, version-stamp, package, and audit the Windows release (VERSION below).

Run this file from an Anaconda Prompt after activating the dedicated DGED
environment. It delegates the PyInstaller build and VERSION.json creation to
the reviewed BUILD_AND_PACKAGE.py script, then independently audits the ZIP.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


VERSION = "0.62.8"
ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
PACKAGE = ROOT / "output_packages" / f"dem2dged_v{VERSION}_win64.zip"
VERSION_FILE = DIST / "VERSION.json"
BUILD_SCRIPT = ROOT / "BUILD_AND_PACKAGE.py"


def main() -> int:
    environment = os.environ.get("CONDA_DEFAULT_ENV", "")
    if not environment or environment.lower() == "base":
        raise SystemExit(
            "Activate the dedicated DGED Conda environment first; "
            "do not build from base."
        )
    if not BUILD_SCRIPT.is_file():
        raise SystemExit(f"Missing build script: {BUILD_SCRIPT}")

    subprocess.run(
        [sys.executable, "-B", str(BUILD_SCRIPT)],
        cwd=str(ROOT),
        check=True,
    )

    if not VERSION_FILE.is_file():
        raise SystemExit(f"Missing generated version file: {VERSION_FILE}")
    version_info = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    if version_info.get("version") != VERSION:
        raise SystemExit(
            f"Version mismatch: expected {VERSION}, got "
            f"{version_info.get('version')}"
        )
    if not PACKAGE.is_file():
        raise SystemExit(f"Missing generated package: {PACKAGE}")

    with zipfile.ZipFile(PACKAGE) as archive:
        bad_member = archive.testzip()
        names = archive.namelist()
        roots = {name.split("/", 1)[0] for name in names if name}
    if bad_member is not None:
        raise SystemExit(f"ZIP integrity failure: {bad_member}")
    if roots != {"dem2dged"}:
        raise SystemExit(f"ZIP must have one root named dem2dged: {sorted(roots)}")
    required_members = {
        "dem2dged/dem2dged.exe",
        "dem2dged/LICENSE",
        "dem2dged/README.md",
        "dem2dged/checksums.sha256",
        "dem2dged/source/dem2dged.py",
        "dem2dged/source/BUILD_AND_PACKAGE.py",
        "dem2dged/source/DGED_Loader.pyt",
        "dem2dged/source/DGED_Loader/DGED_Loader.pyt",
        "dem2dged/source/QUICKSTART.html",
        "dem2dged/EVIDENCE_GATE_BEGINNER_GUIDE.md",
        "dem2dged/EVIDENCE_GATE_BEGINNER_GUIDE.html",
        "dem2dged/source/dem2dged_help.py",
        "dem2dged/source/dem2dged_reference.py",
        "dem2dged/source/dem2dged_datum.py",
        "dem2dged/source/reference_catalog.json",
    }
    missing_members = sorted(required_members.difference(names))
    if missing_members:
        raise SystemExit(
            "Release package is missing required binary/license/source members: "
            + ", ".join(missing_members)
        )
    forbidden_members = [
        name for name in names
        if "/.pytest_tmp" in name.replace("\\", "/") or
        name.lower().endswith("_log.txt")
    ]
    if forbidden_members:
        raise SystemExit(
            "Release package contains generated test/log artifacts: "
            + ", ".join(forbidden_members[:10])
        )

    print(f"Release version: {VERSION}")
    print(f"Executable: {DIST / 'dem2dged.exe'}")
    print(f"Version file: {VERSION_FILE}")
    print(f"Package: {PACKAGE}")
    print(f"ZIP entries: {len(names)}; integrity: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
