# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a focused GitHub/source ZIP for dem2dged v0.50.1.

This intentionally excludes historical release wrappers, old code reviews,
scratch logs, generated binaries and manual-update scripts.  It is separate
from PACKAGE_v0.50.1.py, which preserves the broader archival source package.
"""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "dem2dged_v0.50.1_github.zip"
FILES = [
    "README.md", "START_HERE.md", "QUICKSTART.html", "MANIFEST.md",
    "VERSION.txt", "VALIDATOR_VERSION.txt",
    "DEM2DGED_Compliance_Policy.json",
    "dem2dged.py", "dem2dged_gui.py", "dem2dged_geo.py", "dem2dged_utm.py",
    "dem2dged_lib.py", "dem2dged_validate.py", "dem2dged_compare.py",
    "dem2dged_terrain.py", "dem2dged_logging.py", "dem2dged_env.py",
    "DGED_GEO_TEMPLATE.xml", "DGED_UTM_TEMPLATE.xml",
    "dem2dged.spec", "dem2dged_validate.spec", "version_info_gui.txt",
    "version_info_validate.txt", "make_version_info.py",
    "install.bat", "install.sh", "dem2dged_anaconda_environment.py",
    "dem2dged_anaconda_environment.bat", "build_exe.bat",
    "rebuild_exe.bat", "build_validate_exe.bat", "rebuild_validate_exe.bat",
    "BUILD_SCRIPTS_GUIDE.md", "REBUILD_GUIDE.md", "DEM_SOURCES_GUIDE.md",
    "DGIWG_STANDARDS_TRACKING.md", "DGED_Conversion_Review.md",
    "BUILD_AND_PACKAGE.py", "dem2dged_package.py",
    "dem2dged_validate_package.py", "PACKAGE_v0.50.1.py",
    "PACKAGE_GITHUB_v0.50.1.py", "RELEASE_CHECK_v0.50.1.py",
    "audit_pure.py", "run_verification.py", "verify.bat", "pytest.ini",
    "selftest_optimize_resampling.py", "selftest_prefilter.py",
    "selftest_prefilter_math.py", "selftest_resampling_comparison.py",
]
TEST_FILES = ["tests/conftest.py", "tests/README.md", "tests/test_lib.py",
              "tests/test_validator.py", "tests/test_converters.py",
              "tests/test_terrain.py"]

missing = [p for p in FILES + TEST_FILES if not (ROOT / p).is_file()]
if missing:
    raise SystemExit("Missing required GitHub package files: " + ", ".join(missing))

if OUT.exists():
    OUT.unlink()
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel in FILES + TEST_FILES:
        zf.write(ROOT / rel, "dem2dged_v0.50.1/" + rel)

print("Created %s (%d files, %.2f MB)" %
      (OUT, len(FILES) + len(TEST_FILES), OUT.stat().st_size / 1048576.0))
