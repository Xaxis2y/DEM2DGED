# DEM2DGED v0.58.1 Requirements and Compliance Evidence

SPDX-License-Identifier: GPL-2.0-or-later  
Copyright (c) 2026 Eui Soo SON

> **SUPERSEDED by `REQUIREMENTS_COMPLIANCE_V0.59.0.md` (2026-09-08).** Kept for the audit trail. Its "Known limitations" item 1 describes the `-resample optimize` defect as open; v0.59.0 fixed it. Everything else in this file still stands.

This file maps the supplied requirements review to implemented evidence. It
does not treat conversion success, agreement with the input DEM, or a default
accuracy goal as proof of real-world accuracy.

Supersedes `REQUIREMENTS_COMPLIANCE_V0.57.1.md`, which was a relabelled copy
of the v0.56.0 matrix and cited a `RELEASE_GATE_v0.57.1.py` that has never
existed in this tree. Both errors are annotated in that file rather than
erased.

## Decision model

The consolidated report is written to
`validation/compliance_report.json`, `validation/compliance_report.txt`,
`validation/statistics.json` and `validation/report.html`.
Its overall state is:

- `PASS`: all automated mandatory checks have evidence and pass.
- `FAIL`: at least one mandatory check fails.
- `NOT_EVALUATED`: required evidence is absent. This is not a pass.

Absolute CE90/LE90 values in DGIWG 250 are reported as goals. Default metadata
values are labelled as goals rather than predicted or measured accuracy.

## What changed since the v0.56.0 matrix, and what it means for compliance

### v0.57.0 — three mountainous-terrain accuracy fixes

A controlled investigation against synthetic terrain with realistic mountain
slope statistics, where the true elevation at every post is known
(`dem2dged_v0.56.0_mountain_terrain_review.md`), found three issues. All three
are implemented, and covered by 21 tests in `tests/test_v057_regressions.py`.

| Finding | Fix in v0.57.0 | Compliance effect |
|---|---|---|
| `-resample optimize` always benchmarked candidates at a fixed 2x hold-out ratio regardless of the ratio actually requested, so at 8x–16x on steep terrain it could recommend Cubic where Nearest was 1.5–3x more accurate. | New `pick_holdout_factor()` runs the hold-out test at (approximately) the actual requested decimation ratio; `average` added as a fifth scored candidate. | Improves the expected source-to-output error on steep, high-ratio conversions. Changes no structural check and no metadata field. |
| The v0.49 Gaussian anti-alias `--prefilter` measurably worsened point accuracy at every ratio and resampler tested on steep terrain, by 44–102%. | Messaging only: the CLI help and the GUI dropdown now warn instead of recommending. Filter math unchanged; default remains `none`. | No change to a default delivery. Prevents an operator from degrading absolute vertical accuracy on the strength of the old advice. |
| The `rms` resampler is mathematically unsound for signed elevation data — it discards sign and can be wrong by more than 100 m. | Removed. Requesting it raises a specific `SystemExit` explaining why and pointing to `average`. | Removes a route to a delivery that could not meet any vertical-accuracy limit. |

### v0.58.0 — ArcGIS Pro difference viewer

`DGED_Loader/DGED_Loader.pyt` gained **Show DGED Differences**. It is a
review aid only: it loads the `validation/elevation_diff.tif` and
`validation/error_mask.tif` the converter already wrote, plus the source and
the delivery tiles, into one comparison group. It performs no alignment,
resampling, statistics or decision of its own, so it neither adds to nor
weakens any compliance claim. Covered by `DGED_Loader/test_dged_loader.py`
(offline mock-ArcPy, also run under pytest) and
`DGED_Loader/arcgis_pro_smoke_test.py` (licensed workstation).

### v0.58.1 — documentation and version consistency

No conversion, tiling, resampling, metadata or validation logic changed. The
compliance-relevant part is that `README.md`, `DEM2DGED_User_Manual.md` and
`QUICKSTART.html` had continued to recommend `--prefilter gaussian` for
mountainous sources after v0.57.0 retracted that advice in the CLI and GUI.
An operator following the documents could have shipped a delivery with
knowingly degraded point accuracy. Corrected.

## Does the mountain-terrain work still satisfy the DGED requirements?

Yes, and the reason is worth stating precisely, because the two things are
independent:

- **DGIWG 250 structural conformance** is decided by tile naming, grid
  geometry and post spacing, point registration (`PixelIsPoint`), horizontal
  and vertical CRS, data type per level, NoData, shared-edge identity, sidecar
  metadata and the table of contents. **None of these depends on which
  resampler is chosen, or on whether the pre-filter ran.** Every v0.57.x
  change was to resampler *selection* and to *guidance*; the `rms` removal
  narrowed the set of selectable resamplers, and the remaining set was already
  conformant. `dem2dged_validate.py`'s structural checks are unchanged, and
  the full suite (453 tests) passes.
- **Vertical accuracy** is an evidence question, not a structural one. The
  v0.57.0 fixes can only improve the source-to-output error on steep terrain;
  none of them can make it worse. Absolute accuracy against DGIWG 250's CE90/
  LE90 goals still requires independent control data (`--reference-dem` plus
  measured accuracy inputs) and remains `NOT_EVALUATED` without it — exactly
  as before.
- **The mountain allowance is applied conservatively.** `--terrain-qa
  mountain` records `dgiwg_vertical_accuracy_factor = 1.4` only when
  `predominant_slope_over_20_percent` is true, and reports the factor
  explicitly rather than folding it silently into a verdict.

So: the improvements are compliance-neutral-to-positive. They do not create a
new requirement, do not relax an existing check, and do not change any
delivered byte for a run that did not use `-resample optimize`, `--prefilter`
or `rms`.

## Known limitations that bound the accuracy claims

These are stated here so a reviewer does not have to infer them.

1. **`-resample optimize`'s hold-out test measures the wrong thing (open).**
   `dem2dged_compare._holdout_stats()` builds its training grid by
   point-sampling the source, then scores how accurately each candidate
   **reconstructs** (upsamples) the full grid from it. That is a
   reconstruction metric used as a proxy for decimation accuracy, and the two
   diverge sharply at high ratios: on 65%-median-slope synthetic terrain at
   16x, the test still ranked Cubic B-Spline (true RMSE about 8 m) above
   Nearest Neighbor (about 2 m). `near` and `average` can also score
   bit-identically there, because GDAL's `average` degenerates to point
   sampling when it upsamples. Evidence and a proposed decimate-and-score
   rewrite are in `dem2dged_v0.57.1_mountain_terrain_recheck.md`; the rewrite
   is deferred to v0.59.0. **Until then, on steep sources above roughly 8x,
   treat `optimize`'s recommendation as a hint and verify with
   `dem2dged_validate.py --terrain-qa mountain`.** This does not affect an
   explicit `-resample` choice, which is unaffected by the hold-out test.
2. **`--prefilter gaussian` trades point accuracy for reduced aliasing.**
   `selftest_prefilter.py` scores against an ideal band-limited reference (an
   aliasing metric) and shows a large improvement on rough terrain; the
   mountain reviews score against true elevation at each post (a
   point-accuracy metric) and show a 44–102% degradation on steep terrain.
   Both are correct. For a delivery judged on LE90, leave it at `none`.
3. **Terrain-QA metrics measure conversion fidelity, not product accuracy.**
   `elevation_diff.tif` and every statistic derived from it compare the output
   against the *conversion source*, on the delivered DGED grid. They cannot
   detect an error already present in that source.
4. **Independent accuracy is never inferred.** Absent control evidence stays
   `NOT_EVALUATED`; `--require-full-compliance` turns that state into exit
   code 2.

## Requirement matrix

| Requirement area | v0.58.1 implementation | Evidence/status |
|---|---|---|
| Source CRS, GeoTransform, registration, extent, NoData, type | `inspect_source()` plus the structural validator | Automated |
| PixelIsPoint and half-post alignment | Exact expanded warp extent and validator grid-centre checks | Automated hard check |
| Avoid interpolation for an identical grid | Direct-copy eligibility path | Automated when all grid conditions match |
| Source resolution suitable for target level | Level-specific source eligibility; unified CLI/GUI block a finer target by default | Automated hard check; expert override remains `FAIL` |
| Vertical datum handling | Explicit `--source-vertical`; strict non-ballpark PROJ operation preflight records search paths and blocks missing geoid grids | Automated hard check for declared transformations; undeclared datum remains an assumption |
| DGED structure/header/metadata | Filename, pairing, GeoTIFF driver and byte-order/header signature, type, NoData, PixelIsPoint, CRS/vertical tag, dimensions, post spacing, bounds, XML, TOC and seams | Automated hard check |
| Adjacent tile identity | Edge reconciliation and seam validation | Automated hard check |
| Resampler selection | `auto` default; explicit override; `optimize` runs hold-out cross-validation at the actual decimation ratio over five candidates (v0.57.0). `rms` removed as unsound for signed elevation data. | Automated, with the limitation in "Known limitations" item 1 |
| Anti-alias pre-filter | Opt-in, default `none`; NoData-safe normalised convolution; recorded in the sidecar lineage | Off by default; not recommended where point accuracy is the criterion |
| Source-to-output error | Bias, MAE, RMSE, standard deviation, P90/P95/P99, maximum, difference and threshold rasters | Conversion-fidelity evidence only |
| Mountain terrain checks | Optional `mountain` mode: percent slope, >20% predominance, steep-error bins, top/bottom 1%, local peaks/valleys and +/-0.5-post sensitivity | Automated when selected |
| DGIWG mountain allowance | 1.4 vertical-accuracy factor only when predominant slope exceeds 20% | Automated, reported explicitly |
| Independent product accuracy | Separate `--reference-dem`, measured relative vertical 90% and horizontal CE90 inputs | `NOT_EVALUATED` until independent evidence is supplied |
| Source/conversion/final error separation | Same-grid vector identity and covariance-aware MSE decomposition in `error_budget.json`; no invalid MAE/RMSE subtraction | Automated when source and independent reference are supplied |
| Product-level accuracy limits | DGIWG 250 level 0-9/4b resolution, random/relative and absolute-goal values | Automated lookup and decision |
| Delivery review | ArcGIS Pro toolbox: `Load DGED Tiles`, `Show DGED Differences` (v0.58.0) | Review aid; makes no compliance decision |
| Traceability and reproducibility | SHA-256 source/output hashes, requested/resolved algorithm, CRS/accuracy assumptions and GDAL/PROJ/Python versions | `DEM2DGED_Conversion_Manifest.json` |
| Version consistency of the shipped build | `audit_pure.py` (12 declarations) plus `BUMP_VERSION.py --check <version>` (every module, test, selftest, `.pyt`, PyInstaller resource and release-note header) | Automated; run both before packaging |

## Required evidence for a defensible full PASS

1. Use a source whose native post spacing is not coarser than the selected
   DGED level.
2. Establish the source horizontal and vertical accuracy independently and
   pass `--source-horizontal-accuracy` and `--source-vertical-accuracy`.
3. Declare the actual source vertical CRS with `--source-vertical`, unless it
   is embedded unambiguously in the source CRS.
4. Supply independent reference/control data with `--reference-dem`; do not
   reuse the conversion input as the reference.
5. Supply independently measured `--reference-horizontal-ce90` and
   `--reference-relative-vertical-90` where those checks apply.
6. Run the standalone validator with `--require-full-compliance`. Exit code 2
   means required evidence remains `NOT_EVALUATED`.
7. On steep terrain, use `--terrain-qa mountain`, and if the run used
   `-resample optimize` at a decimation ratio above roughly 8x, record a
   comparison against at least one explicit resampler (see "Known
   limitations" item 1).

Example:

```batch
python dem2dged.py source.tif delivery --mode utm --level 4b ^
  --source-vertical 3855 --source-horizontal-accuracy 3.0 ^
  --source-vertical-accuracy 2.0 --terrain-qa mountain ^
  --reference-dem independent_control_dem.tif ^
  --reference-horizontal-ce90 4.0 ^
  --reference-relative-vertical-90 2.0

python dem2dged_validate.py delivery -src source.tif ^
  --terrain-qa mountain --reference-dem independent_control_dem.tif ^
  --source-horizontal-accuracy 3.0 --source-vertical-accuracy 2.0 ^
  --reference-horizontal-ce90 4.0 ^
  --reference-relative-vertical-90 2.0 --require-full-compliance
```

The numeric examples above are illustrative operator inputs, not certified
accuracy values for any dataset.

## Verification performed for v0.58.1

| Check | Command | Result |
|---|---|---|
| Byte-compile, all modules and both `.pyt` | `python -m py_compile` | clean |
| GDAL-free consistency audit | `python audit_pure.py` | `RESULT: 0 problem(s)`, 12 version declarations agree |
| Version consistency, wider set | `python BUMP_VERSION.py --check 0.58.1` | 0 stale declarations |
| Full test suite | `pytest -q` | 453 passed (GDAL 3.8.4, Python 3.12, `gdalwarp` on PATH) |
| ArcGIS toolbox, offline harness | `python DGED_Loader/test_dged_loader.py` | ALL TESTS PASSED |

Not run for v0.58.1, and still required before an operational release:
`python RELEASE_GATE_v0.56.0.py` and the PyInstaller `.exe` build and smoke
test, both of which need the Anaconda `DGED` environment on the target
workstation; and `DGED_Loader/arcgis_pro_smoke_test.py` under a licensed
ArcGIS Pro runtime.

## Remaining improvement or external-evidence items

- Full accuracy compliance cannot be proven by software alone. A qualified,
  genuinely independent reference/control dataset and its CE90/LE90 or
  relative-accuracy evidence are still required.
- If the source vertical datum is omitted, the tool cannot infer whether its
  values are truly EGM2008; the label-only path is recorded as an assumption.
- The independent source/reference error budget performs horizontal alignment
  only. Both elevation datasets must already use the delivered vertical
  reference; hidden or unknown vertical-datum differences remain invalid input.
- Project policy thresholds in `DEM2DGED_Compliance_Policy.json` require
  acceptance by the responsible approving authority; tool tests do not replace
  formal product certification or accredited field/control-point testing.
- `-resample optimize`'s decimate-and-score rewrite is outstanding (v0.59.0).
