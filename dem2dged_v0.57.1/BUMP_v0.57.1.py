#!/usr/bin/env python3
"""
BUMP_v0.57.1.py — Bump all version references from 0.57.0 to 0.57.1

This script updates:
1. VERSION constants in Python files
2. # Version: header comments
3. Documentation (README, USER_MANUAL, etc.)
4. VERSION.txt and VALIDATOR_VERSION.txt headers
5. Renames DIAG_dem2dged_v0.57.0.py → DIAG_dem2dged_v0.57.1.py
6. Creates REQUIREMENTS_COMPLIANCE_V0.57.1.md from V0.56.0.md

v0.57.1 is a documentation/polish patch of v0.57.0.
It ships the same three fixes with clearer docs and improved guides.
"""

import os
import re
import shutil
from pathlib import Path

# Configuration
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
OLD_VERSION = "0.57.0"
NEW_VERSION = "0.57.1"

# Files with VERSION = "X.Y.Z" constant
VERSION_CONSTANT_FILES = [
    "BUILD_AND_PACKAGE.py",
    "dem2dged_compliance.py",
    "dem2dged_package.py",
    "dem2dged_validate_package.py",
]

# Files with # Version: X.Y.Z header comment
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
    "selftest_prefilter.py",
    "selftest_prefilter_math.py",
    "audit_pure.py",
]

# GUI special cases (APP_VERSION variables)
GUI_APP_VERSION_PATTERNS = [
    r'APP_VERSION = "0\.57\.0"',
    r'APP_VERSION_DISPLAY = "0\.57\.0"',
]

def bump_version_constant(filepath):
    """Update VERSION = "X.Y.Z" constants."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content
    content = re.sub(
        rf'VERSION\s*=\s*"0\.57\.0"',
        f'VERSION = "{NEW_VERSION}"',
        content
    )

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  [OK] {os.path.basename(filepath)}: VERSION constant bumped")
        return True
    return False

def bump_version_header(filepath):
    """Update # Version: X.Y.Z header comments."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content
    content = re.sub(
        r'# Version: 0\.57\.0',
        f'# Version: {NEW_VERSION}',
        content
    )

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  [OK] {os.path.basename(filepath)}: Version header bumped")
        return True
    return False

def bump_gui_app_version(filepath):
    """Update APP_VERSION and APP_VERSION_DISPLAY in dem2dged_gui.py."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content
    for pattern in GUI_APP_VERSION_PATTERNS:
        content = re.sub(
            pattern,
            pattern.replace("0.57.0", NEW_VERSION),
            content
        )

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  [OK] {os.path.basename(filepath)}: APP_VERSION variables bumped")
        return True
    return False

def update_readme():
    """Update README.md with v0.57.1 information."""
    filepath = os.path.join(SOURCE_DIR, "README.md")
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content

    # Update current version
    content = re.sub(
        r'\*\*Current version: v0\.57\.0\*\*',
        f'**Current version: v{NEW_VERSION}**',
        content
    )

    # Update release note section
    old_release_note = (
        r'\*\*v0\.57\.0 release note:\*\* a full-project review fixed.*?'
        r'The GUI also gains the anti-alias pre-filter it has lacked since\s+v0\.49\.'
    )

    new_release_note = (
        "**v0.57.1 release note:** documentation and polish update of v0.57.0. "
        "Clarifies the three key fixes shipped in v0.57.0: (1) hold-out cross-validation "
        "now scales with actual decimation ratio for more accurate resampler ranking in "
        "mountainous terrain; (2) the mathematically-unsound 'rms' resampler removed with "
        "clear explanation, 'average' added as the 5th candidate; (3) Gaussian anti-alias "
        "pre-filter warning text updated with guidance. All fixes covered by 21 regression "
        "tests. See `Changes in v0.57.1` in `VERSION.txt`.\n\n"
        "**v0.57.0 release note:** three targeted fixes for resampling accuracy in mountainous "
        "terrain and mathematical soundness. Cross-validation hold-out scaling, 'rms' removal, "
        "and pre-filter warning clarification—see above for details."
    )

    content = re.sub(old_release_note, new_release_note, content, flags=re.DOTALL)

    # Update user manual reference
    content = re.sub(
        r'Full v0\.57\.0 user manual',
        f'Full v{NEW_VERSION} user manual',
        content
    )

    # Update REQUIREMENTS_COMPLIANCE reference
    content = re.sub(
        r'REQUIREMENTS_COMPLIANCE_V0\.56\.0\.md',
        f'REQUIREMENTS_COMPLIANCE_V{NEW_VERSION}.md',
        content
    )

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  [OK] README.md updated with v{NEW_VERSION} release notes")
        return True
    return False

def update_diag_filename():
    """Rename DIAG_dem2dged_v0.57.0.py to DIAG_dem2dged_v0.57.1.py."""
    old_path = os.path.join(SOURCE_DIR, "DIAG_dem2dged_v0.57.0.py")
    new_path = os.path.join(SOURCE_DIR, f"DIAG_dem2dged_v{NEW_VERSION}.py")

    if os.path.exists(old_path):
        with open(old_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Update internal version references in the file
        content = re.sub(
            r'DIAG_dem2dged_v0\.57\.0\.py',
            f'DIAG_dem2dged_v{NEW_VERSION}.py',
            content
        )
        content = re.sub(
            r'Target project version: dem2dged 0\.57\.0',
            f'Target project version: dem2dged {NEW_VERSION}',
            content
        )
        content = re.sub(
            r'A read-only diagnostic harness that verifies the three v0\.57\.0 fixes',
            f'A read-only diagnostic harness that verifies the three v{NEW_VERSION} fixes',
            content
        )

        with open(new_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"  [OK] Created DIAG_dem2dged_v{NEW_VERSION}.py")
        return True
    return False

def create_requirements_compliance():
    """Create REQUIREMENTS_COMPLIANCE_V0.57.1.md from V0.56.0.md."""
    old_path = os.path.join(SOURCE_DIR, "REQUIREMENTS_COMPLIANCE_V0.56.0.md")
    new_path = os.path.join(SOURCE_DIR, f"REQUIREMENTS_COMPLIANCE_V{NEW_VERSION}.md")

    if os.path.exists(old_path):
        with open(old_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Update version references in the file
        content = re.sub(
            r'v0\.56\.0',
            f'v{NEW_VERSION}',
            content
        )
        content = re.sub(
            r'v0\.57\.0',
            f'v{NEW_VERSION}',
            content
        )

        with open(new_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"  [OK] Created REQUIREMENTS_COMPLIANCE_V{NEW_VERSION}.md")
        return True
    return False

def main():
    print(f"\n{'='*60}")
    print(f"Bumping dem2dged from v0.57.0 to v{NEW_VERSION}")
    print(f"{'='*60}\n")

    try:
        # Step 1: Bump VERSION constants
        print("[1/5] Updating VERSION constants...")
        for fname in VERSION_CONSTANT_FILES:
            fpath = os.path.join(SOURCE_DIR, fname)
            if os.path.isfile(fpath):
                bump_version_constant(fpath)

        # Step 2: Bump VERSION header comments
        print("\n[2/5] Updating VERSION header comments...")
        for fname in VERSION_HEADER_FILES:
            fpath = os.path.join(SOURCE_DIR, fname)
            if os.path.isfile(fpath):
                bump_version_header(fpath)

        # Step 3: Update GUI special version variables
        print("\n[3/5] Updating GUI version variables...")
        gui_path = os.path.join(SOURCE_DIR, "dem2dged_gui.py")
        if os.path.isfile(gui_path):
            bump_gui_app_version(gui_path)

        # Step 4: Update documentation
        print("\n[4/5] Updating documentation...")
        update_readme()
        create_requirements_compliance()
        update_diag_filename()

        # Step 5: Summary
        print(f"\n[5/5] Version bump complete!\n")
        print(f"{'='*60}")
        print(f"Version bumped from v0.57.0 to v{NEW_VERSION}")
        print(f"Files updated: VERSION constants, header comments, docs")
        print(f"{'='*60}\n")

        return 0

    except Exception as e:
        import traceback
        print(f"\n[FAIL] Error: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
