# dem2dged v0.56.0 — Package Contents

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

`dem2dged_package.py` creates the source-release ZIP from this folder. It
includes all runtime sources, documentation, tests and the integrated
`DGED_Loader/` companion; generated executables, test caches and operator DEM
data are excluded.

`LICENSE` contains the GPL-2.0 text and the GPL-2.0-or-later project notice.

## Runtime and QA

- `dem2dged.py`, `dem2dged_gui.py`, `dem2dged_geo.py`, `dem2dged_utm.py` —
  converter entry points.
- `dem2dged_lib.py` — DGED tables, tile generation helpers and release
  `VERSION` source of truth (`0.56.0`).
- `dem2dged_validate.py`, `dem2dged_terrain.py`, `dem2dged_compliance.py`,
  `DEM2DGED_Compliance_Policy.json` — structural validation, source-to-DGED
  terrain QA and policy thresholds.
- `dem2dged_compare.py`, `dem2dged_logging.py`, `dem2dged_env.py` —
  resampling comparison, logging and environment diagnostics.
- `DGED_GEO_TEMPLATE.xml`, `DGED_UTM_TEMPLATE.xml` — metadata templates.

## ArcGIS Pro delivery review

`DGED_Loader/` contains the ready-to-use `DGED_Loader.pyt`, its native-ATBX
Script Tool source, setup guide, offline mock-ArcPy test harness and companion
documentation. It is packaged with the converter in v0.56.0.
The loader's default discovery rule accepts only `DGEDL*` GeoTIFFs, avoiding
original source DEMs and `validation/elevation_diff.tif` /
`validation/error_mask.tif` while scanning parent folders recursively.

## Documentation

- `README.md` — full reference and options.
- `START_HERE.md` — shortest installation and conversion path.
- `QUICKSTART.html` — visual quick-start guide.
- `DEM2DGED_User_Manual.md` — terrain QA, policy and ArcGIS Pro review guide.
- `REQUIREMENTS_COMPLIANCE_V0.56.0.md` — requirement/evidence matrix.
- `VERSION.txt` and `VALIDATOR_VERSION.txt` — maintained release notes.
- `BUILD_SCRIPTS_GUIDE.md`, `REBUILD_GUIDE.md`, `DEM_SOURCES_GUIDE.md`,
  `DGIWG_STANDARDS_TRACKING.md`, `DGED_Conversion_Review.md` — build, source
  and standards reference material.

## Verification and release tooling

- `tests/` — pytest unit/integration suite, including terrain QA tests.
- `tests/test_v056_regressions.py` — one test per v0.55.0 review finding, each
  failing on v0.55.0 and passing here. First coverage of
  `try_direct_copy_tile()`, `build_prefiltered_source()` and the GUI
  converters.
- `tests/test_dged_loader_harness.py` — runs the DGED_Loader harness under
  pytest. `pytest.ini` sets `testpaths = tests`, so before v0.56.0 that
  harness had never run as part of the suite.
- `DGED_Loader/test_dged_loader.py` — offline mock-ArcPy coverage of both
  Loader implementations.
- `audit_pure.py` — GDAL-free consistency audit.
- `RELEASE_GATE_v0.56.0.py` — one command, ten stages: environment,
  byte-compile, audit, pytest, regression harness, real GEO and UTM
  conversions with validation, pre-filter (CLI and GUI), resume behaviour and
  packaging. Writes `release_gate/release_gate_<timestamp>.log`.
- `DIAG_dem2dged_v0.56.0.py` — the v0.55.0 review harness, retargeted: each
  check measures one former defect, so a FAIL is now a regression.
- `PATCH_v0.56.0.py`, `PATCH_v0.56.0_gui.py`, `BUMP_v0.56.0.py` — the
  exact-match edits that produced this release from v0.55.0, kept for audit.
- `RELEASE_CHECK_v0.55.0.py` — full real-GDAL/PyInstaller release gate.
- `PACKAGE_v0.55.0.py`, `PACKAGE_GITHUB_v0.55.0.py`,
  `dem2dged_package.py`, `dem2dged_validate_package.py` — archive builders.

## Excluded from the source release

- `build/`, `dist/`, `__pycache__/`, `.pytest_cache/` and release-check logs.
- Operator DEM inputs and generated conversion/validation output folders.
- Existing `.zip`, `.pyc`, `.tmp`, `.log`, `.bak`, image and PDF artefacts.

## Post-extraction check

```batch
conda activate DGED
python RELEASE_GATE_v0.56.0.py
```
