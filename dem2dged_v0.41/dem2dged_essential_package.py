# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

import os
import sys
import zipfile
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION = "0.41"
ZIP_FILENAME = "DEM2DGED_Toolkit_v%s.zip" % VERSION
ZIP_PATH = os.path.join(PROJECT_ROOT, ZIP_FILENAME)

# Directories that are never walked into, anywhere in the tree, regardless
# of which component they turn up under (build caches, not source).
SKIP_DIR_NAMES = {"build", "dist", "tests", "__pycache__", ".pytest_cache",
                  "dem2dged_arcgis_qa_v1.0.0", "dem2dged_arcgis_qa_v1.0.1",
                  "dem2dged_arcgis_qa_v1.0.2"}

# File-level exclusions applied everywhere.
SKIP_FILE_SUFFIXES = (".zip", ".pyt.xml", ".pyc")
SKIP_FILE_NAMES = {"DEM2DGED_User_Manual_old.docx", "note_and_issue.md"}


def _iter_component_files(component_root, arc_prefix):
    """Yield (abs_path, arcname) pairs for one component, applying the
    shared skip rules. component_root is an absolute path on disk;
    arc_prefix is the folder name this component will sit under inside
    the zip (e.g. "dem2dged")."""
    for dirpath, dirnames, filenames in os.walk(component_root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_NAMES)
        for fname in sorted(filenames):
            if fname in SKIP_FILE_NAMES:
                continue
            if fname.endswith(SKIP_FILE_SUFFIXES):
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, component_root)
            arcname = os.path.join(ZIP_FILENAME[:-4], arc_prefix, rel_path)
            yield abs_path, arcname


def verify_components():
    """Confirm all three component folders/files exist before zipping."""
    checks = {
        "dem2dged core (dem2dged.py)": os.path.join(PROJECT_ROOT, "dem2dged.py"),
        "arcgis_qa_toolbox/": os.path.join(PROJECT_ROOT, "arcgis_qa_toolbox"),
        "DGED Loader/": os.path.join(PROJECT_ROOT, "DGED Loader"),
    }
    missing = [label for label, path in checks.items() if not os.path.exists(path)]
    if missing:
        raise FileNotFoundError("Missing required component(s): %s" % ", ".join(missing))
    print("[OK] All three components found.")


def create_package():
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
        print("[OK] Removed old %s" % ZIP_FILENAME)

    file_count = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:

        # --- dem2dged core: everything at the project root EXCEPT the two
        # companion toolboxes' own folders (handled separately below) and
        # the shared skip rules (tests/, build/, dist/, loose zips, etc.).
        # Walking the project root itself, one level, then recursing only
        # into subfolders that are NOT one of the other two components.
        core_skip_top = {"arcgis_qa_toolbox", "DGED Loader"} | SKIP_DIR_NAMES
        for entry in sorted(os.listdir(PROJECT_ROOT)):
            full = os.path.join(PROJECT_ROOT, entry)
            if os.path.isdir(full):
                if entry in core_skip_top:
                    continue
                for abs_path, arcname in _iter_component_files(full, os.path.join("dem2dged", entry)):
                    zf.write(abs_path, arcname)
                    file_count += 1
            else:
                if entry in SKIP_FILE_NAMES or entry.endswith(SKIP_FILE_SUFFIXES):
                    continue
                # This script's own packaging-script sibling belongs with
                # the QA toolbox component, not the core tool.
                if entry == "dem2dged_arcgis_qa_package.py":
                    continue
                arcname = os.path.join(ZIP_FILENAME[:-4], "dem2dged", entry)
                zf.write(full, arcname)
                file_count += 1

        # --- arcgis_qa_toolbox component
        qa_dir = os.path.join(PROJECT_ROOT, "arcgis_qa_toolbox")
        for abs_path, arcname in _iter_component_files(qa_dir, "arcgis_qa_toolbox"):
            zf.write(abs_path, arcname)
            file_count += 1
        qa_pkg_script = os.path.join(PROJECT_ROOT, "dem2dged_arcgis_qa_package.py")
        if os.path.isfile(qa_pkg_script):
            arcname = os.path.join(ZIP_FILENAME[:-4], "arcgis_qa_toolbox", "dem2dged_arcgis_qa_package.py")
            zf.write(qa_pkg_script, arcname)
            file_count += 1

        # --- DGED Loader component
        loader_dir = os.path.join(PROJECT_ROOT, "DGED Loader")
        for abs_path, arcname in _iter_component_files(loader_dir, "DGED Loader"):
            zf.write(abs_path, arcname)
            file_count += 1

    size_mb = os.path.getsize(ZIP_PATH) / (1024 * 1024)
    print("[OK] Wrote %d files into %s (%.2f MB)" % (file_count, ZIP_FILENAME, size_mb))
    return file_count, size_mb


def list_contents_by_component():
    with zipfile.ZipFile(ZIP_PATH) as zf:
        names = zf.namelist()
    root = ZIP_FILENAME[:-4]
    buckets = {"dem2dged": [], "arcgis_qa_toolbox": [], "DGED Loader": []}
    for n in names:
        rel = n[len(root) + 1:] if n.startswith(root + "/") else n
        for key in buckets:
            if rel.startswith(key + "/") or rel == key:
                buckets[key].append(rel)
                break
    for key, items in buckets.items():
        print("\n%s  (%d files)" % (key, len(items)))
        for item in items:
            print("   " + item)


def main():
    print("\n" + "=" * 60)
    print("DEM2DGED Essential Toolkit - Packaging  (built %s)" %
          datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60 + "\n")

    try:
        print("[1/3] Verifying components...")
        verify_components()

        print("\n[2/3] Creating package...")
        file_count, size_mb = create_package()

        print("\n[3/3] Contents by component:")
        list_contents_by_component()

        print("\n" + "=" * 60)
        print("Package : %s" % ZIP_PATH)
        print("Size    : %.2f MB  (%d files)" % (size_mb, file_count))
        print("=" * 60 + "\n")
        return 0

    except Exception as e:
        print("\n[FAIL] %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
