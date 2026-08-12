#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
r"""
dem2dged v0.46 Packaging Script

Automatically creates version file, zips updated source, and prepares distribution.
Designed for Anaconda Prompt execution with virtual environment.

Usage:
    cd C:\Users\Son\Documents\Claude\dem2dged\dem2dged_v0.45
    python PACKAGE_v0.46.py

Output:
    - dem2dged_v0.46.zip (source archive)
    - VERSION_INFO.txt (version metadata)
"""

import os
import shutil
import zipfile
import json
from datetime import datetime
from pathlib import Path

# Configuration
PROJECT_ROOT = Path(__file__).parent
PROJECT_NAME = "dem2dged"
VERSION = "0.46"
OUTPUT_DIR = PROJECT_ROOT / "dist" / f"{PROJECT_NAME}_v{VERSION}"
ARCHIVE_NAME = f"{PROJECT_NAME}_v{VERSION}.zip"

# Files to include in source distribution
INCLUDE_PATTERNS = [
    "*.py",           # All Python modules
    "*.md",           # Documentation
    "*.txt",          # Text files (VERSION, VALIDATOR_VERSION, etc)
    "*.xml",          # DGED templates
    "*.html",         # Quick start, documentation
    "*.bat",          # Batch scripts
    "*.sh",           # Shell scripts
    "*.spec",         # PyInstaller specs
    "*.ini",          # Config files
]

# Directories to exclude
EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
    "dem2dged_v0.45",
    "dem2dged_validate_v0.45",
    ".git",
    ".github",
    ".venv",
    "venv",
}

def create_version_info():
    """Create VERSION_INFO.txt with metadata."""
    timestamp = datetime.now().isoformat()

    version_info = f"""dem2dged v{VERSION} - Package Information
Generated: {timestamp}

VERSION DETAILS
===============
Version Number:    {VERSION}
Release Stage:     stable
Previous Version:  0.45
Upgrade Type:      feature/enhancement

NEW FEATURES
============
1. Configurable Elevation Tolerance
   - GUI radio buttons for 5m (strict) or 10m (standard)
   - CLI option: -max-diff 5.0 | 10.0
   - Default changed from 5.0m to 10.0m

2. Improved Validation Documentation
   - Enhanced help text explaining tolerance options
   - Clear guidance for steep-terrain conversions
   - Backward compatibility notes

MODIFIED FILES
==============
Core Modules (version updated to 0.46):
  - dem2dged_lib.py
  - dem2dged.py
  - dem2dged_gui.py
  - dem2dged_compare.py
  - dem2dged_validate.py
  - dem2dged_env.py
  - dem2dged_geo.py
  - dem2dged_utm.py

Documentation:
  - CHANGELOG_v0.46.md (NEW)

KEY CHANGES
===========
1. dem2dged_gui.py
   - Added max_diff_var (StringVar)
   - Added radio button UI controls
   - Updated validation calls with max_diff parameter
   - Both comparison and single-file modes supported

2. dem2dged_validate.py
   - run_validation() default max_diff: 5.0 -> 10.0
   - CLI default -max-diff: 5.0 -> 10.0
   - Improved help text with usage examples
   - Updated docstring with rationale

3. dem2dged_lib.py
   - VERSION = "0.46" (single source of truth)

BACKWARD COMPATIBILITY
======================
✓ Fully backward compatible
✓ Existing scripts work with new defaults
✓ Override with -max-diff 5.0 for strict mode
✓ API callers can override max_diff parameter

TESTING RECOMMENDATIONS
=======================
1. GUI Mode:
   - Test comparison with 5m and 10m tolerances
   - Verify radio button selection persists
   - Check validation reports include tolerance in logging

2. CLI Mode:
   - dem2dged_validate folder -src dem.tif -max-diff 5.0
   - dem2dged_validate folder -src dem.tif -max-diff 10.0
   - Verify help text: dem2dged_validate --help

3. Steep Terrain (like n00_e114_1arc_v3.tif):
   - Bilinear should PASS with 10m (was FAIL at 5m)
   - Cubic should PASS with 10m (was FAIL at 5m)
   - Nearest should PASS with either tolerance

INSTALLATION
=============
1. Extract archive to project directory
2. Backup existing dem2dged folder (optional)
3. Replace modified .py files
4. Restart GUI application
5. CLI automatically uses new version on next run

PYTHON ENVIRONMENT
===================
Required:
  - Python 3.8+
  - GDAL >= 3.0 (conda install -c conda-forge gdal)
  - numpy
  - tkinter (usually bundled)

Verification:
  python -c "import dem2dged_lib; print(dem2dged_lib.VERSION)"
  Should output: 0.46

KNOWN ISSUES / NOTES
====================
- No breaking changes
- v0.45 validation reports (.txt/.html) remain compatible
- CLI help text wrapped at 80 chars for console readability
- GUI max_diff radio buttons indented for visual hierarchy

CHANGELOG
=========
See CHANGELOG_v0.46.md for detailed changes.

SUPPORT
=======
For questions or issues:
1. Check CHANGELOG_v0.46.md
2. Review dem2dged_validate.py help: python dem2dged_validate.py --help
3. Verify version: dem2dged --version (GUI) or dem2dged_validate --version (CLI)
"""

    version_file = PROJECT_ROOT / "VERSION_INFO_v0.46.txt"
    with open(version_file, "w", encoding="utf-8") as f:
        f.write(version_info)

    print(f"✓ Created: {version_file.name}")
    return version_file

def should_include(path, root):
    """Check if path should be included in archive."""
    rel_path = path.relative_to(root)

    # Skip excluded directories
    for part in rel_path.parts:
        if part in EXCLUDE_DIRS:
            return False

    # Check file patterns
    if path.is_file():
        name = path.name
        for pattern in INCLUDE_PATTERNS:
            if pattern.startswith("*"):
                if name.endswith(pattern[1:]):
                    return True
            elif name == pattern:
                return True
        return False

    return True

def create_archive():
    """Create zip archive of source code."""
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    archive_path = OUTPUT_DIR / ARCHIVE_NAME

    # Remove existing archive
    if archive_path.exists():
        archive_path.unlink()
        print(f"✓ Removed existing: {ARCHIVE_NAME}")

    # Create zip archive
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            # Modify dirs in-place to skip excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            root_path = Path(root)

            for file in files:
                file_path = root_path / file

                if should_include(file_path, PROJECT_ROOT):
                    arcname = file_path.relative_to(PROJECT_ROOT)
                    arcname = f"{PROJECT_NAME}_v{VERSION}/{arcname}"
                    zf.write(file_path, arcname)

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(f"✓ Created: {ARCHIVE_NAME} ({size_mb:.1f} MB)")
    return archive_path

def create_manifest():
    """Create installation manifest."""
    manifest = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "files": [],
        "directories": {
            "project_root": str(PROJECT_ROOT),
            "output": str(OUTPUT_DIR),
        }
    }

    # List included files
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        root_path = Path(root)

        for file in files:
            file_path = root_path / file
            if should_include(file_path, PROJECT_ROOT):
                rel_path = str(file_path.relative_to(PROJECT_ROOT))
                manifest["files"].append(rel_path)

    manifest_file = OUTPUT_DIR / "manifest.json"
    with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    print(f"✓ Created: manifest.json ({len(manifest['files'])} files)")
    return manifest_file

def print_summary():
    """Print summary of packaging results."""
    print("\n" + "="*70)
    print(f"dem2dged v{VERSION} Packaging Complete".center(70))
    print("="*70)
    print(f"\nOutput Directory: {OUTPUT_DIR}")
    print(f"Archive: {ARCHIVE_NAME}")
    print(f"\nNext Steps:")
    print(f"1. Archive location: {OUTPUT_DIR / ARCHIVE_NAME}")
    print(f"2. Extract to desired location")
    print(f"3. Verify version: python -c 'import dem2dged_lib; print(dem2dged_lib.VERSION)'")
    print(f"4. Run GUI: python dem2dged_gui.py")
    print(f"5. Or CLI: python dem2dged.py -h")
    print(f"\nDocumentation:")
    print(f"- CHANGELOG_v0.46.md (detailed changes)")
    print(f"- VERSION_INFO_v0.46.txt (metadata)")
    print(f"- manifest.json (file listing)")
    print("\n" + "="*70 + "\n")

def main():
    """Main packaging workflow."""
    print(f"\ndem2dged v{VERSION} Packaging Script")
    print(f"Project Root: {PROJECT_ROOT}\n")

    try:
        # Step 1: Create version info
        print("Step 1: Creating version information...")
        create_version_info()

        # Step 2: Create archive
        print("\nStep 2: Creating source archive...")
        archive = create_archive()

        # Step 3: Create manifest
        print("\nStep 3: Creating installation manifest...")
        create_manifest()

        # Step 4: Print summary
        print_summary()

        return 0

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
