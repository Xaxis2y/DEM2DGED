# dem2dged v0.34 — Package Contents

40 files. Everything here is required to run, build, test or understand the
tool. Development scratch files and superseded documents were left behind in
the previous working folder (listed at the bottom).

---

## Runtime — the tool itself (10 files)

| File | Role |
|---|---|
| `dem2dged.py` | **Unified CLI.** The easiest entry point; dispatches to GEO or UTM and auto-validates the result. |
| `dem2dged_gui.py` | **GUI.** Batch conversion, resampling comparison, in-process validation. Built into `dem2dged.exe`. |
| `dem2dged_lib.py` | **Single source of truth.** DGED spec tables, `VERSION`, tile naming, warp extents, sidecar/TOC/collection writing. Every other module imports this. |
| `dem2dged_geo.py` | GEO (WGS-84 / EPSG:4326) converter. |
| `dem2dged_utm.py` | UTM converter. |
| `dem2dged_validate.py` | **Validator.** Checks A–H against a tile folder; also builds `dem2dged_validate.exe`. |
| `dem2dged_compare.py` | Resampling-method accuracy comparison + ranked HTML report (v0.33). |
| `dem2dged_logging.py` | Coloured console / file logging used by the CLI. |
| `DGED_GEO_TEMPLATE.xml` | ISO 19115-2 metadata sidecar template, GEO. Bundled into the exe. |
| `DGED_UTM_TEMPLATE.xml` | Same, UTM. Bundled into the exe. |

All entry points import `dem2dged_lib.py`. None of these can be removed.

## Build (11 files)

| File | Role |
|---|---|
| `rebuild_exe.bat` | **← the normal way to build `dem2dged.exe`.** |
| `rebuild_validate_exe.bat` | **← the normal way to build `dem2dged_validate.exe`.** |
| `build_exe.bat` | Bootstrap build from raw flags — only if `dem2dged.spec` is missing. |
| `build_validate_exe.bat` | Same, for the validator. |
| `dem2dged.spec` | Curated PyInstaller recipe for the GUI exe. |
| `dem2dged_validate.spec` | Curated PyInstaller recipe for the validator exe. |
| `BUILD_AND_PACKAGE.py` | All-in-one: verify → clean → build → version → zip. |
| `dem2dged_package.py` | Zips the **source** release (`dem2dged_v0.34.zip`). |
| `dem2dged_validate_package.py` | Zips the validator-only bundle. |
| `install.bat` / `install.sh` | Create the `DGED` conda environment with GDAL. |

**Read `BUILD_SCRIPTS_GUIDE.md` first** — the `rebuild_*` / `build_*` naming
is genuinely confusing, and `rebuild_*` is the primary path, not the fallback.

## Tests (8 files)

| File | Role |
|---|---|
| `audit_pure.py` | **Runs without GDAL.** Naming round-trips, tile geometry, converter↔validator agreement, template placeholders, version consistency. Fastest sanity check: `python audit_pure.py`. |
| `pytest.ini` | pytest configuration. |
| `tests/conftest.py` | Synthetic GEO and UTM sample DEMs — no external test data needed. |
| `tests/test_lib.py` | Library units + the v0.34 version-consistency tests. |
| `tests/test_converters.py` | End-to-end GEO/UTM conversion (needs GDAL). |
| `tests/test_validator.py` | Validator checks and regression tests for the v0.30/v0.31 fixes. |
| `tests/README.md` | How to run the suite. |
| `selftest_resampling_comparison.py` | End-to-end self-test of the v0.33 comparison feature on a synthetic DEM. |

## Documentation (11 files)

| File | Role |
|---|---|
| `START_HERE.md` | First stop for a new user. |
| `README.md` | Full reference + changelog. |
| `QUICKSTART.html` | Illustrated walkthrough. |
| `BUILD_SCRIPTS_GUIDE.md` | **New in v0.34** — which build script to run and why. |
| `REBUILD_GUIDE.md` | Deeper PyInstaller / rebuild notes. |
| `DEM_SOURCES_GUIDE.md` | Where to obtain suitable source DEMs. |
| `CODE_REVIEW_v0.34.md` | **New in v0.34** — the audit, evidence, and how each of the 10 issues was resolved. |
| `MANIFEST.md` | This file. |
| `DEM2DGED_User_Manual.docx` | Formal user manual. |
| `VERSION.txt` / `VALIDATOR_VERSION.txt` | Release notes; now checked by tests. |

---

## Left behind in the previous folder (not required)

Superseded or development-only, kept in place rather than shipped:

- `CODE_REVIEW_v0.27.md`, `CODE_REVIEW_v0.33.md` — superseded by
  `CODE_REVIEW_v0.34.md`
- `FEATURE_PLAN_v0.24.md`, `CODE_CHANGES_SUMMARY.txt` — historical planning notes
- `Plan for Tomorrow.txt`, `TOMORROW_SESSION.txt` — session scratch notes
- `QUICK_START.txt` — superseded by `START_HERE.md` + `QUICKSTART.html`
- `selftest_*.html` — output artefacts from past self-test runs, not inputs
- `_sync_probe.txt` — scratch file

## Quick verification after unzipping

```bash
python audit_pure.py     # no GDAL required — expect "RESULT: 0 problem(s)"
pytest                   # full suite, requires the GDAL environment
```
