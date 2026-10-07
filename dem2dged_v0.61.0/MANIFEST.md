# dem2dged v0.61.0 — Package Contents

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
  `VERSION` source of truth (`0.61.0`).
- `dem2dged_validate.py`, `dem2dged_terrain.py`, `dem2dged_compliance.py`,
  `DEM2DGED_Compliance_Policy.json` — structural validation, source-to-DGED
  terrain QA and policy thresholds.
- `dem2dged_compare.py`, `dem2dged_logging.py`, `dem2dged_env.py` —
  resampling comparison, logging and environment diagnostics.
  `dem2dged_compare.py` holds the v0.59.0 decimate-and-score measurement
  behind `-resample optimize`: each candidate performs the real decimation
  and is scored against the true terrain height at every target post, over
  six sub-pixel grid phases. v0.60.0 adds CRS-aware metre ratios, native
  windows for oversized sources and exact source-range limits. It replaced a
  hold-out reconstruction test whose ranking was inverted on steep terrain
  above ~8x.
- `DGED_GEO_TEMPLATE.xml`, `DGED_UTM_TEMPLATE.xml` — metadata templates.

## ArcGIS Pro delivery review

`DGED_Loader/` contains the ready-to-use `DGED_Loader.pyt`, its native-ATBX
Script Tool source, setup guide, offline mock-ArcPy test harness, licensed-
runtime smoke test and companion documentation. It is packaged with the
converter.

The toolbox holds two tools, both base-ArcGIS-Pro only — no mosaic dataset, no
Spatial Analyst or Image Analyst, no Standard/Advanced license:

- **Load DGED Tiles** — adds a delivery's tiles to the active map. Its
  discovery rule accepts only `DGEDL*` GeoTIFFs, so original source DEMs and
  `validation/elevation_diff.tif` / `validation/error_mask.tif` are never
  mistaken for delivery tiles while scanning parent folders recursively.
- **Show DGED Differences** (v0.58.0) — resolves exactly one validation
  result set, then loads the original source (recovered from
  `DEM2DGED_Conversion_Manifest.json` or `terrain_metrics.json`), the `DGEDL*`
  tiles, the signed `elevation_diff.tif` and the red-styled `error_mask.tif`
  into one comparison group. It reads artifacts the converter already wrote,
  so it introduces no second alignment or resampling step.

`DGED_Loader.pyt` at the project root is a byte-identical convenience copy of
`DGED_Loader/DGED_Loader.pyt`, so the toolbox can be added to a project
without opening the subfolder. Edit the copy under `DGED_Loader/` and mirror
it; `BUMP_VERSION.py` bumps both.

## Documentation

- `README.md` — full reference and options. **This is the project reference,
  not the loader's README**; v0.58.0 shipped with it overwritten by
  `DGED_Loader/README.md` and v0.58.1 restored it.
- `START_HERE.md` — shortest installation and conversion path.
- `QUICKSTART.html` — visual quick-start guide.
- `DEM2DGED_User_Manual.md` — terrain QA, policy and ArcGIS Pro review guide.
- `REQUIREMENTS_COMPLIANCE_V0.61.0.md` — current requirement/evidence matrix.
- `ERROR_REDUCTION_EXPLANATION_V0.61.0.html` — evidence-based explanation of
  the error-reduction method and benchmark limits.
  `_V0.58.1.md`, `_V0.57.1.md` and `_V0.56.0.md` are kept superseded, for the
  audit trail.
- `VERSION.txt`, `VALIDATOR_VERSION.txt` and `DGED_Loader/VERSION.txt` —
  maintained release notes. Hand-written below the three header lines; the
  packagers and `BUMP_VERSION.py` rewrite only the header.
- `dem2dged_v0.56.0_mountain_terrain_review.md`,
  `dem2dged_v0.57.1_mountain_terrain_recheck.md` — the mountainous-terrain
  accuracy investigation behind the v0.57.0 fixes, and the independent
  ground-truth recheck that found the still-open `-resample optimize`
  hold-out limitation.
- `BUILD_SCRIPTS_GUIDE.md`, `REBUILD_GUIDE.md`, `DEM_SOURCES_GUIDE.md`,
  `DGIWG_STANDARDS_TRACKING.md`, `DGED_Conversion_Review.md` — build, source
  and standards reference material.

## Verification and release tooling

- `tests/` — pytest unit/integration suite, including the v0.60.0 accuracy and
  source-preflight regressions. `pytest.ini` sets `testpaths = tests`.
  `pytest.ini` sets `testpaths = tests`.
- `tests/test_v056_regressions.py` — one test per v0.55.0 review finding, each
  failing on v0.55.0 and passing here.
- `tests/test_v057_regressions.py` — 21 tests covering the three v0.57.0
  mountain-terrain fixes.
- `tests/test_dged_loader_harness.py` — runs the DGED_Loader mock-ArcPy
  harness under pytest, including the v0.58.0 comparison tool.
- `DGED_Loader/test_dged_loader.py` — offline mock-ArcPy coverage of both
  Loader implementations; `DGED_Loader/arcgis_pro_smoke_test.py` is the
  licensed-runtime counterpart, run on the ArcGIS Pro workstation.
- `audit_pure.py` — GDAL-free consistency audit (naming, tables, 12 version
  declarations).
- `BUMP_VERSION.py` — generic, idempotent, dry-run-by-default version bumper
  and auditor. `--check <version>` verifies a release without writing.
  Supersedes `BUMP_v0.56.0.py`, `BUMP_v0.57.1.py` and `UPDATE_VERSIONS.py`;
  the last of those is now a hard-failing guard, because it prepended a
  hardcoded v0.57.1 changelog block to `VERSION.txt` on every run.
- `tests/test_v059_regressions.py` — 16 tests covering the v0.59.0
  resampler-selection fix, four of which score the tool's choice against the
  analytic surface rather than against the tool's own metric.
- `tests/test_v060_regressions.py` — v0.60.0 coverage for CRS-aware ratios,
- `tests/test_v061_regressions.py` — v0.61.0 coverage for P90 error reporting,
  source HOLD enforcement and serialized expert overrides.
  exact source-range clamping, source metadata HOLD/OVERRIDE decisions and
  comparison-report measurement labels.
- `RUN_V0610_VALIDATION.py` — dedicated-environment validation and packaging
  runner that writes one detailed log under `validation_logs/`.
- `make_version_info.py`, `version_info_gui.txt`,
  `version_info_validate.txt` — Windows executable version-resource generation
  and current generated resources.
- `verify_mountain_terrain_v0.59.0.py` — the ground-truth harness behind the
  v0.59.0 accuracy claim: analytic terrain, 32 cases, every candidate ranked
  three ways (oracle / old hold-out / new decimate-and-score). Exits non-zero
  if v0.59.0 does not beat v0.58.1 on your GDAL build.
- `verify_mountain_terrain_v0.57.1.py` — the earlier harness, which found the
  defect v0.59.0 fixes.
- `selftest_optimize_resampling.py`, `selftest_prefilter.py`,
  `selftest_prefilter_math.py`, `selftest_resampling_comparison.py` —
  feature-level self-tests. Note that `selftest_prefilter.py` measures
  ALIASING against an ideal band-limited reference, which is a different
  question from point accuracy; see README.md, "Anti-alias pre-filtering".
- `RELEASE_GATE_v0.56.0.py` — one command, ten stages: environment,
  byte-compile, audit, pytest, regression harness, real GEO and UTM
  conversions with validation, pre-filter (CLI and GUI), resume behaviour and
  packaging. Writes `release_gate/release_gate_<timestamp>.log`. Still the
  current gate; there is no `RELEASE_GATE_v0.57.x` or `_v0.58.x`.
- `DIAG_dem2dged_v0.56.0.py`, `DIAG_dem2dged_v0.57.0.py`,
  `DIAG_dem2dged_v0.57.1.py` — per-release regression harnesses; each check
  measures one former defect, so a FAIL is a regression.
- `PATCH_v0.56.0.py`, `PATCH_v0.56.0_gui.py`, `BUMP_v0.56.0.py`,
  `BUMP_v0.57.1.py` — the exact-match edits that produced those releases,
  kept for audit. Superseded for future bumps by `BUMP_VERSION.py`.
- `RELEASE_CHECK_v0.55.0.py` — full real-GDAL/PyInstaller release gate.
- `PACKAGE_v0.55.0.py`, `PACKAGE_GITHUB_v0.55.0.py`,
  `dem2dged_package.py`, `dem2dged_validate_package.py`,
  `BUILD_AND_PACKAGE.py` — archive builders.

## Excluded from the source release

- `build/`, `dist/`, `__pycache__/`, `.pytest_cache/`, `.pytest_tmp_*/` and
  release-check logs.
- Operator DEM inputs and generated conversion/validation output folders.
- Existing `.zip`, `.pyc`, `.tmp`, `.log`, `.bak`, image and PDF artefacts.

## Post-extraction check

```batch
conda activate DGED
python BUMP_VERSION.py --check 0.59.0
python audit_pure.py
pytest
python RELEASE_GATE_v0.56.0.py
```
