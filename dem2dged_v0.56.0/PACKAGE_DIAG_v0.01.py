# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# PACKAGE_DIAG_v0.01.py
# Packaging Script Version: 0.01
# Companion to: DIAG_dem2dged_v0.55.0.py (diagnostic harness v0.01)
#
# ============================================================================
# WHAT THIS DOES
# ============================================================================
# Collects the review deliverables into one versioned ZIP, next to the project
# folder (never inside it, so a re-run can never bundle its own output):
#
#     dem2dged_v0.55.0_review_diag_v0.01_<YYYYmmdd_HHMMSS>.zip
#         DIAG_dem2dged_v0.55.0.py         the harness itself
#         diagnostics/*.log                every diagnostic log found
#         diagnostics/*.json               every machine-readable summary
#         MANIFEST.txt                     what went in, with SHA-256 per file
#
# Nothing is deleted or modified. The scratch rasters under
# diagnostics/scratch/ are deliberately EXCLUDED -- they are regenerated on
# every run and can be tens of megabytes.
#
# ASCII-only console output on purpose: a decorative glyph must never take
# down a packaging run on a cp949 / cp932 / cp1252 console. This is the same
# rule dem2dged_package.py adopted in v0.44.
#
# ============================================================================
# HOW TO RUN  (Anaconda Prompt -- dedicated environment, never base)
# ============================================================================
#     (base) C:\> conda activate DGED
#     (DGED) C:\> cd C:\Users\Son\Documents\ChatGPT\dem2dged\dem2dged_v0.55.0
#     (DGED) C:\...> python PACKAGE_DIAG_v0.01.py
#
# Type `python PACKAGE_DIAG_v0.01.py`, not the bare filename -- the bare form
# resolves the Windows .py file association and may run in a completely
# different interpreter from the activated environment.
#
# Optional:
#     --out-dir <path>    write the zip somewhere else
#     --latest-only       include only the newest .log / .json pair
# ============================================================================

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import sys
import zipfile

PACKAGE_SCRIPT_VERSION = "0.01"
DIAG_VERSION = "0.03"
PROJECT_VERSION = "0.56.0"

SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
DIAG_DIR = os.path.join(SOURCE_DIR, "diagnostics")
DEFAULT_OUT_DIR = os.path.dirname(SOURCE_DIR)

HARNESS_NAME = "DIAG_dem2dged_v%s.py" % PROJECT_VERSION


def sha256_file(path):
    """SHA-256 of one file, streamed so a large log costs no extra memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(latest_only=False):
    """Return [(absolute_path, name_inside_zip), ...] for everything to bundle."""
    items = []

    harness = os.path.join(SOURCE_DIR, HARNESS_NAME)
    if os.path.isfile(harness):
        items.append((harness, HARNESS_NAME))
    else:
        print("WARNING: %s not found next to this script -- the zip will "
              "contain logs only." % HARNESS_NAME)

    if not os.path.isdir(DIAG_DIR):
        print("WARNING: no diagnostics/ folder yet. Run "
              "'python %s' first." % HARNESS_NAME)
        return items

    logs, jsons = [], []
    for name in sorted(os.listdir(DIAG_DIR)):
        path = os.path.join(DIAG_DIR, name)
        if not os.path.isfile(path):
            continue                      # skips diagnostics/scratch/
        if name.endswith(".log"):
            logs.append(path)
        elif name.endswith(".json"):
            jsons.append(path)

    if latest_only:
        logs = logs[-1:]
        jsons = jsons[-1:]

    for path in logs + jsons:
        items.append((path, "diagnostics/" + os.path.basename(path)))

    return items


def build_manifest(items, zip_name):
    lines = []
    lines.append("DEM2DGED REVIEW / DIAGNOSTIC PACKAGE")
    lines.append("=" * 60)
    lines.append("")
    lines.append("package script version : %s" % PACKAGE_SCRIPT_VERSION)
    lines.append("diagnostic harness     : %s" % DIAG_VERSION)
    lines.append("target project version : %s" % PROJECT_VERSION)
    lines.append("built                  : %s"
                 % datetime.datetime.now().isoformat(timespec="seconds"))
    lines.append("built on               : %s" % sys.platform)
    lines.append("python                 : %s" % sys.version.split()[0])
    lines.append("source folder          : %s" % SOURCE_DIR)
    lines.append("archive                : %s" % zip_name)
    lines.append("")
    lines.append("CONTENTS  (%d file(s))" % len(items))
    lines.append("-" * 60)
    for path, arcname in items:
        lines.append("%-52s %10d bytes" % (arcname, os.path.getsize(path)))
        lines.append("    sha256 %s" % sha256_file(path))
    lines.append("")
    lines.append("EXCLUDED ON PURPOSE")
    lines.append("-" * 60)
    lines.append("diagnostics/scratch/   synthetic test rasters, regenerated")
    lines.append("                       on every diagnostic run.")
    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(
        description="Package the dem2dged v%s review diagnostics "
                    "(packaging script v%s)."
                    % (PROJECT_VERSION, PACKAGE_SCRIPT_VERSION))
    ap.add_argument("--out-dir", default=None,
                    help="where to write the zip (default: the parent of the "
                         "project folder)")
    ap.add_argument("--latest-only", action="store_true",
                    help="bundle only the newest .log and .json")
    args = ap.parse_args()

    out_dir = args.out_dir or os.environ.get("DEM2DGED_PACKAGE_OUTPUT_DIR") \
        or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = ("dem2dged_v%s_review_diag_v%s_%s.zip"
                % (PROJECT_VERSION, DIAG_VERSION, stamp))
    zip_path = os.path.join(out_dir, zip_name)

    print("-" * 60)
    print("DEM2DGED review / diagnostic packaging  v%s"
          % PACKAGE_SCRIPT_VERSION)
    print("-" * 60)
    print("source folder : %s" % SOURCE_DIR)
    print("output folder : %s" % out_dir)
    print("")

    items = collect(latest_only=args.latest_only)
    if not items:
        print("[FAIL] Nothing to package.")
        return 1

    manifest = build_manifest(items, zip_name)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, arcname in items:
                zf.write(path, arcname)
                print("  added  %s" % arcname)
            zf.writestr("MANIFEST.txt", manifest)
            print("  added  MANIFEST.txt")
    except Exception as e:
        print("")
        print("[FAIL] Could not write the archive: %s" % e)
        return 1

    size = os.path.getsize(zip_path)
    print("")
    print("[OK]   %s" % zip_path)
    print("       %d file(s), %.1f KB" % (len(items) + 1, size / 1024.0))
    print("")
    print("MANIFEST.txt inside the archive lists every file with its SHA-256.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
