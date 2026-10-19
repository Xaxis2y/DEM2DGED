# DEM2DGED v0.59.0 Requirements and Compliance Evidence

SPDX-License-Identifier: GPL-2.0-or-later  
Copyright (c) 2026 Eui Soo SON

This file maps the supplied requirements review to implemented evidence. It
does not treat conversion success, agreement with the input DEM, or a default
accuracy goal as proof of real-world accuracy.

Supersedes `REQUIREMENTS_COMPLIANCE_V0.58.1.md`. The earlier
`_V0.57.1.md` was a relabelled copy of the v0.56.0 matrix and cited a
`RELEASE_GATE_v0.57.1.py` that has never existed in this tree; both errors are
annotated in that file rather than erased.

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

### v0.59.0 — the mountainous-terrain resampler-selection fix

This is the release that closes the finding first raised in the v0.56.0
mountain-terrain review and left open through v0.58.1.

**What was wrong.** `-resample optimize` ranked candidates with a hold-out
cross-validation: the source was point-sampled onto a sparse training grid and
each candidate was scored on how accurately it *reconstructed* the full grid
from it. Reconstruction is upsampling; a DGED conversion is decimation. The
two diverge sharply as the ratio grows, and on steep terrain at 16x the test
produced an exactly **inverted** ranking — Cubic B-Spline first at a true RMSE
of 55.6 m, Nearest Neighbor last at 10.2 m. This was reproduced independently
on the maintainer's own DGED environment (GDAL 3.13.3, Python 3.10.21) and is
recorded in `DIAG_dem2dged_v0.58.1_log.txt`. A second symptom of the same
cause: `near` and `average` scored bit-identically at every ratio, because
GDAL's `average` degenerates to point sampling when it upsamples, so two of
the five candidates were never actually distinguished.

**What it does now.** Each candidate warps the source *down* to the requested
post spacing — the real production operation, with the same source-range clamp
a delivered cubic-family tile receives — and is scored against the best
available estimate of the true terrain height at each target post: a narrow
Catmull-Rom bicubic sample of the source at that exact location. That
reference is deliberately not any candidate's own operation, because GDAL
scales its resampling kernel with the downsampling factor while the reference
always uses a 4-pixel stencil at native spacing. Scoring is pooled over six
sub-pixel phases of the target grid, so a knife-edge alignment cannot decide
the ranking: Nearest Neighbor is charged its real expected offset error and
the smoothing methods their real curvature bias.

**Evidence.** `verify_mountain_terrain_v0.59.0.py` generates terrain from an
analytic formula, so the true elevation is known everywhere, and ranks every
candidate three ways across 32 cases — alpine / ridged / rolling terrain,
integer and non-integer ratios from 2x to 16x, clean and noisy sources, two
seeds:

| Ranking method | Correct candidate chosen | Excess RMSE over the oracle |
|---|---|---|
| hold-out reconstruction (to v0.58.1) | 6 / 32 | +573.62 m |
| decimate-and-score (v0.59.0) | **28 / 32** | **+0.53 m** |

Excess over the oracle — the avoidable error each method's choices added up to
— is the metric that matters, because a wrong pick between near-tied
candidates costs almost nothing. 99.9% of it is removed. The harness exits
non-zero if v0.59.0 does not beat v0.58.1 on the GDAL build it is run against,
so the claim is falsifiable on site rather than taken on trust.

**Compliance effect.** Improves the expected source-to-output error on steep,
high-ratio conversions. Changes no structural check, no metadata field and no
delivered byte for a run that did not use `optimize`. `lanczos` was added as a
sixth scored candidate; it is returned only when it measures strictly best.

**Operational consequence, and this is the one that needs recording.** A
delivery produced with `-resample optimize` on steep terrain at a high ratio
under v0.58.1 or earlier may have been converted with a materially less
accurate resampler than the source warranted. Such a delivery is still
structurally conformant — the resampler choice affects accuracy, not
conformance — but if its acceptance rests on vertical accuracy, re-run
`optimize` under v0.59.0 and compare with
`dem2dged_validate.py --terrain-qa mountain` before relying on it. Deliveries
produced with `auto` or an explicit `-resample <alg>` are bit-for-bit
unaffected.

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

1. **The resampler-selection defect is CLOSED as of v0.59.0**, but two bounded
   residuals remain, both measured rather than assumed:
   *(a)* the truth reference is interpolated from the source, so it carries
   the source's own noise. That slightly under-penalises a candidate which
   does not smooth. In the 32-case validation this produced four wrong picks,
   all at ratios of 4x or below on noisy sources, and all between candidates
   sitting within a quarter of a metre of each other — a total of 0.53 m of
   avoidable error across the whole sweep. At high ratios the curvature bias
   dwarfs this term.
   *(b)* On a source larger than `MAX_DECIMATE_PIXELS` the measurement is made
   on up to four windows at native post spacing rather than the whole raster.
   The windows are placed at the quarter positions, so terrain from four parts
   of the source is sampled, but a source whose character varies strongly
   across its extent may still be ranked on an unrepresentative subset.
   Where a single delivery spans markedly different terrain, convert the
   sub-areas separately or confirm the choice with
   `dem2dged_validate.py --terrain-qa mountain`.
   Neither residual affects an explicit `-resample` choice, which never
   consults the measurement at all.
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
| Resampler selection | `auto` default; explicit override; `optimize` (v0.59.0) performs the real decimation with each of six candidates over six sub-pixel grid phases and scores each against the true terrain height at every target post. Cubic-family and Lanczos candidates are scored on the delivered clamp. `rms` removed as unsound for signed elevation data. | Automated; ground-truth validated by `verify_mountain_terrain_v0.59.0.py`, with the bounded residuals in "Known limitations" item 1 |
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
7. On steep terrain, use `--terrain-qa mountain`. If the delivery was
   produced with `-resample optimize` under v0.58.1 or earlier, re-run
   `optimize` under v0.59.0 before relying on its accuracy (see the v0.59.0
   section above).

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

## Verification performed for v0.59.0

| Check | Command | Result |
|---|---|---|
| Byte-compile, all modules and both `.pyt` | `python -m py_compile` | clean |
| GDAL-free consistency audit | `python audit_pure.py` | `RESULT: 0 problem(s)`; section 9 now also checks that a decimation is never routed to the hold-out test |
| Version consistency, wider set | `python BUMP_VERSION.py --check 0.59.0` | 0 stale declarations |
| Full test suite | `pytest -q` | 471 passed (GDAL 3.8.4, Python 3.12, `gdalwarp` on PATH) |
| Resampler-selection fix vs. ground truth | `python verify_mountain_terrain_v0.59.0.py` | 28/32 correct; avoidable error +573.62 m -> +0.53 m; VERDICT: improves |
| ArcGIS toolbox, offline harness | `python DGED_Loader/test_dged_loader.py` | ALL TESTS PASSED |

Not run for v0.59.0, and still required before an operational release:
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
- The `-resample optimize` decimate-and-score rewrite is DONE (v0.59.0). Its
  two bounded residuals are in "Known limitations" item 1.
- A real-DEM confirmation of the v0.59.0 fix on operator data is still
  outstanding: the evidence above is from analytic terrain, where ground truth
  exists. Convert one representative steep source both ways and compare the
  `--terrain-qa mountain` reports.
