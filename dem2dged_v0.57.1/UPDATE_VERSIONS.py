#!/usr/bin/env python3
"""Update VERSION.txt and VALIDATOR_VERSION.txt with v0.57.1 section."""

import os
from datetime import datetime

SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_DISPLAY = "0.57.1"

def update_version_txt():
    """Prepend v0.57.1 section to VERSION.txt."""
    path = os.path.join(SOURCE_DIR, "VERSION.txt")
    
    new_section = f"""Changes in {VERSION_DISPLAY}:
- Documentation and polish update of v0.57.0
- Clarified release notes for the three v0.57.0 fixes:
  * Hold-out cross-validation now scales with actual decimation ratio
  * RMS resampler removed (mathematically unsound), average added
  * Gaussian anti-alias pre-filter warning text clarified
- Updated README.md with consolidated release notes
- Created REQUIREMENTS_COMPLIANCE_V0.57.1.md
- All v0.57.0 fixes covered by 21 regression tests

"""

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the "Changes in" marker
    marker = content.find("Changes in ")
    if marker >= 0:
        # Insert the new section before existing changes
        updated = content[:marker] + new_section + content[marker:]
    else:
        # No existing changes, just prepend
        updated = new_section + content
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(updated)
    
    print("[OK] VERSION.txt updated with v0.57.1 section")

def update_validator_version_txt():
    """Update VALIDATOR_VERSION.txt header with v0.57.1."""
    path = os.path.join(SOURCE_DIR, "VALIDATOR_VERSION.txt")
    
    # Read existing file
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the changelog marker
    marker = content.find("Changes in ")
    if marker >= 0:
        body = content[marker:]
    else:
        body = content
    
    # Create new header
    header = (f"DEM2DGED Validator Version Information\n"
              f"========================================\n"
              f"\n"
              f"SPDX-License-Identifier: GPL-2.0-or-later\n"
              f"Copyright (c) 2026 Eui Soo SON\n"
              f"\n"
              f"Version: {VERSION_DISPLAY}\n"
              f"Build Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
              f"Package: dem2dged_validate_v{VERSION_DISPLAY}\n"
              f"\n")
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(header + body)
    
    print("[OK] VALIDATOR_VERSION.txt header updated")

if __name__ == "__main__":
    update_version_txt()
    update_validator_version_txt()
    print("\nVersion files updated successfully!")
