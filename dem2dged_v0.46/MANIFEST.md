# dem2dged v0.45 — Package Contents

57 files in the source release. Everything here is required to run, build,
test or understand the tool.

> **v0.42:** `tests/` is listed below AND is now actually in the release
> zip. It had been missing from v0.40 and v0.41 for a reason nobody had
> looked for: `dem2dged_package.py`'s `EXCLUDE_DIRS` contained the entry
> `"tests"` — twice — so the packaging step STRIPPED the test suite out of
> every archive while `pytest.ini` (`testpaths = tests`) and this file's
> "Tests & verification" section shipped intact. Rebuilding the directory by
> hand could never make it stick. `"tests"` is gone from that set; the
> generated output directories it was meant to name are excluded explicitly
> instead.

---

## Runtime — the tool itself (10 files)

| File | Role |
|---|---|
| `dem2dged.py` | **Unified CLI.** The easiest entry point; dispatches to GEO or UTM and auto-validates the result. |
| `dem2dged_gui.py` | **GUI.** Batch conversion, resampling comparison, in-process validation. Built into `dem2dged.exe`. |
| `dem2dged_lib.py` | **Single source of truth.** DGED spec tables, `VERSION`, tile naming, warp extents, edge reconciliation, sidecar/TOC/collection writing. Every other module imports this. |
| `dem2dged_geo.py` | GEO (WGS-84 / EPSG:4326) converter. |
| `dem2dged_utm.py` | UTM converter. |
| `dem2dged_validate.py` | **Validator.** Checks A–H against a tile folder; also builds `dem2dged_validate.exe`. |
| `dem2dged_compare.py` | Resampling-method accuracy comparison + ranked HTML report (v0.33). |
| `dem2dged_logging.py` | Coloured console / file logging used by the CLI. |
| `DGED_GEO_TEMPLATE.xml` | ISO 19115-2 metadata sidecar template, GEO. Bundled into the exe. |
| `DGED_UTM_TEMPLATE.xml` | Same, UTM. Bundled into the exe. |

All entry points import `dem2dged_lib.py`. None of these can be removed.

## Build & packaging (13 files)

| File | Role |
|---|---|
| `rebuild_exe.bat` | **← the normal way to build `dem2dged.exe`.** |
| `rebuild_validate_exe.bat` | **← the normal way to build `dem2dged_validate.exe`.** |
| `build_exe.bat` | Bootstrap build from raw flags — only if `dem2dged.spec` is missing. |
| `build_validate_exe.bat` | Same, for the validator. |
| `dem2dged.spec` | Curated PyInstaller recipe for the GUI exe. |
| `dem2dged_validate.spec` | Curated PyInstaller recipe for the validator exe. |
| `BUILD_AND_PACKAGE.py` | All-in-one: verify → clean → build → version → zip. |
| `dem2dged_package.py` | Zips the **source** release (`dem2dged_v0.45.zip`). |
| `dem2dged_validate_package.py` | Zips the validator-only bundle. |
| `dem2dged_essential_package.py` | Zips dem2dged together with the two companion ArcGIS toolboxes. Requires `arcgis_qa_toolbox/` and `DGED Loader/` to be present alongside this folder; it raises `FileNotFoundError` if they are not. |
| `install.bat` / `install.sh` | Create the `DGED` conda environment with GDAL. |
| `dem2dged_anaconda_environment.py` / `.bat` | Alternative environment bootstrapper (`dem2dged_anaconda_environment` env, Python 3.11). |

**Read `BUILD_SCRIPTS_GUIDE.md` first** — the `rebuild_*` / `build_*` naming
is genuinely confusing, and `rebuild_*` is the primary path, not the fallback.

## Tests & verification (10 files)

| File | Role |
|---|---|
| `audit_pure.py` | **Runs without GDAL.** Naming round-trips, tile geometry, converter↔validator agreement, template placeholders, sanity-check and auto-optimize logic, version consistency. Fastest check: `python audit_pure.py` → `RESULT: 0 problem(s)`. |
| `RELEASE_CHECK_v0.45.py` | **The release gate.** Runs every layer against real GDAL and writes one log per step into `_release_check_logs/`. |
| `pytest.ini` | pytest configuration (`testpaths = tests`, markers `unit` / `integration` / `slow`). |
| `tests/conftest.py` | Synthetic GEO / UTM / equatorial sample DEMs — no external test data. Per-test `output_dir` (v0.38). |
| `tests/test_lib.py` | Library units + the version-consistency tests. |
| `tests/test_converters.py` | End-to-end GEO/UTM conversion (needs GDAL + `gdalwarp` on PATH). |
| `tests/test_validator.py` | Validator checks and regressions for the v0.30/v0.31/v0.34/v0.37/v0.38/v0.41 fixes. |
| `tests/README.md` | How to run the suite from the Anaconda Prompt. |
| `run_verification.py` | The 19-step release harness against real DEMs placed under `DEM/`. |
| `verify.bat` | Runs `run_verification.py` with logging. |
| `verify_v037.bat` | Older end-to-end CLI verification batch, kept for comparison. |
| `selftest_resampling_comparison.py` | End-to-end self-test of the v0.33 comparison feature on a synthetic DEM. |

## Documentation (14 files)

| File | Role |
|---|---|
| `START_HERE.md` | First stop for a new user. |
| `README.md` | Full reference + changelog. |
| `QUICKSTART.html` | Illustrated walkthrough. |
| `BUILD_SCRIPTS_GUIDE.md` | Which build script to run and why. |
| `REBUILD_GUIDE.md` | Deeper PyInstaller / rebuild notes. |
| `DEM_SOURCES_GUIDE.md` | Where to obtain suitable source DEMs. |
| `DGIWG_STANDARDS_TRACKING.md` | Clause-by-clause tracking against DGIWG 250. |
| `DGED_Conversion_Review.md` | The independent audit of a 9-run / 42-tile DGIWG test batch (source of the v0.37 findings). |
| `CODE_REVIEW_v0.34.md` | The v0.34 audit, evidence, and how each of the 10 issues was resolved. |
| `CODE_REVIEW_v0.39.md` | The v0.39 review pass. |
| `MANIFEST.md` | This file. |
| `DEM2DGED_User_Manual.docx` | Formal user manual. |
| `VERSION.txt` / `VALIDATOR_VERSION.txt` | Release notes; checked by `audit_pure.py` and `tests/test_lib.py`. |
| `LICENSE` | GPL-2.0-or-later. |

## Staging folder

`dem2dged_validate_v0.45/` is the validator-only bundle laid out ready to
zip (validator + `dem2dged_lib.py` + manual + LICENSE + README + rebuild
script + `VALIDATOR_VERSION.txt`). `dem2dged_package.py` excludes any
`dem2dged_validate_v*` folder from the source release, so it never nests
inside `dem2dged_v0.45.zip`.

---

## Not part of the release

Generated or scratch, excluded by the packaging scripts:

- `build/`, `dist/`, `__pycache__/`, `.pytest_cache/` — PyInstaller and
  Python build artefacts, regenerated by `rebuild_exe.bat`
- `output*/`, `DEM/`, `_verify_pages/` — conversion output and
  operator-supplied source data
- `selftest_resampling_comparison_report.html` — an artefact of a past
  self-test run, not an input
- Loose `*.zip` from previous releases

> **v0.42:** `EXCLUDE_FILE_SUFFIXES` now covers
> `.zip/.pdf/.jpg/.jpeg/.tmp/.log/.bak`, and the stray `lu49gpd00.tmp` that
> would have shipped inside `dem2dged_v0.41.zip` has been deleted (v0.41
> finding 9, closed). `RELEASE_CHECK_v0.45.py` step 11 prints the exact file
> list the zip would contain, so this is checkable rather than trusted.

## Quick verification after unzipping

```bat
conda activate DGED
python audit_pure.py     :: no GDAL required — expect "RESULT: 0 problem(s)"
pytest -q                :: full suite, requires the GDAL environment
python run_verification.py   :: 19-step end-to-end harness
```
