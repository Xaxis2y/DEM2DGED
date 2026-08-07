# dem2dged v0.42 — Package Contents

59 files in the source release (52, plus `CODE_REVIEW_v0.41.md` --
previously missing from this manifest despite being in the folder --
`CODE_REVIEW_v0.42.md`, and the 5-file `tests/` directory restored per the
v0.42 note below). Everything here is required to run, build, test or
understand the tool.

> **v0.42:** a release-readiness review of the extracted v0.41 folder found
> `tests/` missing again -- the same problem this file's v0.41 note (below)
> said had been fixed. Root cause this time was structural, not a stale
> doc: `dem2dged_package.py`'s `EXCLUDE_DIRS` excluded `"tests"` from the
> source zip it builds, so any release actually produced by that script
> would never contain the directory this file lists as required, no matter
> how correct the listing itself was. The exclusion is removed and
> verified end to end -- a freshly built `dem2dged_v0.42.zip` now contains
> all five `tests/` files -- and the directory itself is restored in this
> working folder (copied from the sibling `dem2dged_v0.40` checkout that
> `_release_check_logs/` was, it turns out, actually exercising; every
> copied file diffs byte-identical against that source except its own
> `# Version:` header comment). See `CODE_REVIEW_v0.42.md` / `VERSION.txt`
> for the full write-up and for the other packaging gaps found alongside
> it (validator bundle missing `LICENSE`, a stray `.tmp` file not excluded
> from release zips).
>
> **v0.41:** this file had been left describing the v0.34 package. It now
> matches what is actually in the folder — the entries added since (the
> verification harness, the standards-tracking and review documents, the
> environment/installer scripts, `CODE_REVIEW_v0.39.md`) were all missing,
> and `tests/` was listed while the directory itself did not exist.

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
| `dem2dged_package.py` | Zips the **source** release (`dem2dged_v0.41.zip`). |
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
| `pytest.ini` | pytest configuration (`testpaths = tests`, markers `unit` / `integration` / `slow`). |
| `tests/conftest.py` | Synthetic GEO / UTM / equatorial sample DEMs — no external test data. Per-test `output_dir` (v0.38). |
| `tests/test_lib.py` | Library units + the version-consistency tests. |
| `tests/test_converters.py` | End-to-end GEO/UTM conversion (needs GDAL + `gdalwarp` on PATH). |
| `tests/test_validator.py` | Validator checks and regressions for the v0.30/v0.31/v0.34/v0.38/v0.39/v0.41 fixes. |
| `tests/README.md` | How to run the suite from the Anaconda Prompt. |
| `run_verification.py` | The 19-step release harness against real DEMs placed under `DEM/`. |
| `verify.bat` | Runs `run_verification.py` with logging. |
| `verify_v037.bat` | Older end-to-end CLI verification batch, kept for comparison. |
| `selftest_resampling_comparison.py` | End-to-end self-test of the v0.33 comparison feature on a synthetic DEM. |

## Documentation (16 files)

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
| `CODE_REVIEW_v0.41.md` | The v0.41 audit (the validator byte-compile blocker and four other findings) -- previously missing from this table. |
| `CODE_REVIEW_v0.42.md` | This release-readiness pass: `tests/` found excluded from the source zip, the validator bundle missing `LICENSE`, and three smaller packaging/docs gaps. |
| `MANIFEST.md` | This file. |
| `DEM2DGED_User_Manual.docx` | Formal user manual. |
| `VERSION.txt` / `VALIDATOR_VERSION.txt` | Release notes; checked by `audit_pure.py` and `tests/test_lib.py`. |
| `LICENSE` | GPL-2.0-or-later. |

## Staging folder

`dem2dged_validate_v0.41/` is the validator-only bundle laid out ready to
zip (validator + `dem2dged_lib.py` + manual + LICENSE + README + rebuild
script + `VALIDATOR_VERSION.txt`). `dem2dged_package.py` excludes any
`dem2dged_validate_v*` folder from the source release, so it never nests
inside `dem2dged_v0.41.zip`.

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

> **Note:** `dem2dged_package.py`'s `EXCLUDE_FILE_SUFFIXES` covers
> `.zip/.pdf/.jpg/.jpeg` but **not** `.tmp`. A stray scratch file such as
> `lu49gpd00.tmp` sitting in the project folder will therefore be bundled
> into the release zip. Delete stray files before packaging, or add `.tmp`
> to that tuple.

## Quick verification after unzipping

```bat
conda activate DGED
python audit_pure.py     :: no GDAL required — expect "RESULT: 0 problem(s)"
pytest -q                :: full suite, requires the GDAL environment
python run_verification.py   :: 19-step end-to-end harness
```
