# DEM2DGED User Manual — v0.61.0

SPDX-License-Identifier: GPL-2.0-or-later  
Copyright (c) 2026 Eui Soo SON

## Purpose

DEM2DGED converts a GDAL-readable DEM into DGIWG DGED GeoTIFF tiles and
validates both DGED structure and terrain fidelity. The project scope is DGED;
it does not silently claim to produce DTED.

## Recommended workflow

1. Inspect the source CRS, vertical reference, units, registration, grid phase,
   resolution, extent, NoData value, and data type.
2. Use automatic strategy selection. A provably identical point-registered
   source/target grid uses direct matrix copy; otherwise the tool creates the
   exact DGED target grid and resamples it.
3. Keep vertical datum handling explicit. Use `--source-vertical` for a real
   transformation and `--strict-source` when an unconfirmed source reference
   must block conversion. For a non-EGM2008 source, conversion starts only if
   PROJ proves that a non-ballpark geoid operation is available for the source
   area; see `vertical_operation_check.json` for evidence or remediation.
4. Select a target level no finer than the source. The unified CLI and GUI
   block a coarser-source-to-finer-product run by default; an expert override
   remains a source-eligibility `FAIL`.
5. Run terrain QA. `--terrain-qa basic` writes core metrics; `full` adds nine
   +/-0.5-post cases; `mountain` also checks percent slope, >20% predominance,
   top/bottom extremes and local peaks/valleys.
6. Review product structure, source eligibility, conversion fidelity and
   independent-reference accuracy separately. Conversion success alone does
   not prove DGED compliance.

## Example

```batch
python dem2dged.py input.tif output_folder --terrain-qa mountain --strict-source --compliance-profile standard
```

The validation directory contains
`terrain_metrics.json`, `elevation_diff.tif`, `error_mask.tif`,
`compliance_report.json`, `compliance_report.txt`, `statistics.json` and
`report.html`. With an independent reference it also contains
`error_budget.json`. Review `MAE`, `RMSE`,
`P90`, `P95`, `P99`, `Bias`, `Max`, slope bins, peaks/valleys and offset
sensitivity together; do not use a single maximum-error threshold as the sole
mountainous-terrain decision.

`dem2dged_validate.py --terrain-qa basic|full|mountain` requires `-src`. A terrain-QA
execution error is an exit-code-1 failure, not a warning that permits a false
successful pipeline result. `standard` and `strict` profiles read their limits
from `DEM2DGED_Compliance_Policy.json`; any exceeded enabled limit is a
conversion-fidelity `FAIL`.

## Compliance evidence and independent accuracy

`DEM2DGED_Conversion_Manifest.json` records SHA-256 hashes, the requested and
resolved resampler, vertical-reference assumptions and runtime versions.
Source-to-output differences measure conversion fidelity only. To evaluate
product accuracy, pass a genuinely independent surface with `--reference-dem`
and measured horizontal/relative accuracy evidence where applicable. If that
evidence is absent, the report says `NOT_EVALUATED`; use
`--require-full-compliance` to make that state return exit code 2.

When source and independent reference are both supplied, the error budget is
computed on the exact delivered DGED grid:
`output-reference = source-reference + output-source`. It reports the source
baseline, conversion residual, final output error and the MSE cross term.
MAE/RMSE values must not be subtracted because correlated error terms do not
combine that way.

DGIWG 250 absolute CE90/LE90 values are goals. Automatic values in the tile
metadata are labelled as goals, not predictions or measurements. See
`REQUIREMENTS_COMPLIANCE_V0.59.0.md` for the complete requirement matrix.

## Why comparison pixels can look large

The comparison source is warped onto the DGED delivery grid before subtracting.
Therefore `elevation_diff.tif` and `error_mask.tif` have the same post spacing
as the DGED level, not the native source spacing. A 2 m source converted to
DGED Level 2 produces roughly 30 m QA pixels. This is correct for delivery
QA: it measures exactly the samples in the product. ArcGIS Pro's Bilinear or
Cubic display resampling can make the display smoother but does not add data.

## ArcGIS Pro review

`DGED_Loader/DGED_Loader.pyt` is included with this release (a byte-identical
copy sits at the project root as `DGED_Loader.pyt`). Open a map view first —
both tools add layers to the current project's active map. Neither requires
Spatial Analyst, Image Analyst, or a Standard/Advanced license.

**Load DGED Tiles.** Run it against a delivery parent folder to recursively
add only `DGEDL*` tiles to the active map. It intentionally ignores original
source TIFFs and `validation/` artefacts, so a source DEM sitting beside the
delivery is never loaded as a tile.

**Show DGED Differences** (v0.58.0). Run it against one `*_dged_output`
folder — or that folder's `validation/` subfolder. It resolves exactly one
QA result set and refuses a parent holding several, so two unrelated
deliveries cannot be silently mixed in one map. It then loads, into a single
named group:

1. the original source DEM, recovered from
   `DEM2DGED_Conversion_Manifest.json` or `terrain_metrics.json` (an explicit
   override parameter is available when the source has since moved);
2. the `DGEDL*` delivery tiles, optional;
3. `validation/elevation_diff.tif`, the signed difference — **positive means
   the DGED product is higher than the source**;
4. `validation/error_mask.tif`, styled red, at the threshold recorded in
   `terrain_metrics.json`.

It prints the terrain-QA summary (valid cells, bias, MAE, RMSE, P95, maximum
absolute difference) alongside the layers, and states explicitly that these
measure source-to-output conversion fidelity, not absolute vertical accuracy.
For a visual check, turn the difference layers off, select a raster layer and
use **Raster Layer > Appearance > Swipe**.

Because the tool consumes the rasters the converter already wrote, it adds no
second alignment or resampling step of its own — what you see on screen is
exactly what the validator measured.

## Resampling guidance

Use direct copy whenever the grids are truly identical. For different grids,
choose `--resample optimize` when source-specific evidence is useful, or use
`near`, `average`, `bilinear`, `cubic`, `cubicspline`, or `lanczos`
deliberately. The `rms` resampler was removed in v0.57.0: it discards sign, so
on signed elevation data it can be wrong by more than 100 m. Use `average`.

**`--resample optimize` is the recommended choice on high-relief sources
as of v0.59.0.** It warps the source down to the requested post spacing with
each of Nearest Neighbor, Bilinear, Cubic Convolution, Cubic B-Spline, Average
and Lanczos — the real conversion, not a proxy for it — over six sub-pixel
grid phases, and scores each against the best available estimate of the true
terrain height at every target post. Cubic-family and Lanczos candidates are
scored on the same source-range clamp their delivered tiles receive.

*What changed.* Through v0.58.1 `optimize` ranked candidates on how well they
*reconstructed* a point-sampled training grid — an upsampling test standing in
for a downsampling decision. Above roughly 8x on steep terrain the two diverge
and the ranking came out inverted: at 16x it put Cubic B-Spline first (true
RMSE 55.6 m) and Nearest Neighbor last (10.2 m). A second symptom was `near`
and `average` scoring bit-identically at every ratio, because GDAL's `average`
degenerates to point sampling when it upsamples. Over 32 ground-truth cases
the new measurement picks correctly 28 times instead of 6, cutting the
avoidable error from +573.62 m to +0.53 m — 99.9% of it. Reproduce it with
`python verify_mountain_terrain_v0.59.0.py`.

*Operational consequence.* If you produced a delivery with `-resample
optimize` on steep terrain at a high ratio under v0.58.1 or earlier, re-run
`optimize`: it may choose differently now, and the earlier choice may have
been materially less accurate. Deliveries made with `auto` or an explicit
resampler are bit-for-bit unaffected.

*Where the hold-out test survives.* It is still used where it is the correct
measure — equal post spacing or upsampling, where there is no decimation to
score — and as a fallback if the decimation test cannot be set up on a given
source (for example a source too small for the requested ratio). On that
fallback path the high-ratio warning still appears in the log, and the earlier
advice applies: treat the pick as a hint and confirm with
`dem2dged_validate.py --terrain-qa mountain`.

**Anti-alias pre-filter (`--prefilter gaussian`): opt-in, and not recommended
for point accuracy.** Earlier editions of this manual said it "can improve
rough mountainous terrain while harming near-planar terrain". That is the
recommendation v0.57.0 retracted, and this manual carried it until v0.58.1.
The correction is not a reversal of the v0.49 measurement — the two
measurements answer different questions:

| Measurement | Scored against | Question answered | Result |
|---|---|---|---|
| `selftest_prefilter.py` (v0.49) | an ideal band-limited surface | how much false, aliased structure is in the product? | filter **helps** on rough terrain, up to −82% RMSE |
| v0.56.0 / v0.57.1 mountain reviews | true elevation at each delivered post | how wrong is the height at this post? | filter **hurts**, +44% to +102% on steep terrain, at every ratio and resampler tested |

Both stand. Low-pass filtering removes aliased structure by smoothing, and
smoothing clips real summits and fills real valleys — exactly what a
point-accuracy metric punishes, and it stacks with the resamplers' own
low-pass behaviour. **For a delivery judged on DGIWG 250 absolute vertical
accuracy, leave `--prefilter` at `none` (the default).** The CLI help and the
GUI dropdown have said so since v0.57.0.

## Reading resampling-comparison reports

Each candidate is independently converted and validated. A sample-window FAIL
belongs only to the resampling method shown in that candidate's validation
card; it does not mean that Bilinear, Cubic, or another separately validated
candidate also failed. Do not distribute a candidate marked FAIL.

The comparison report distinguishes two decisions: **Best hold-out** ranks the
source-reconstruction experiment, while **Recommended for delivery** selects
the best-ranked candidate that has no validation FAIL. A validation WARN is
not a structural failure, but must still be reviewed before delivery.

## Release and verification

Run `python BUMP_VERSION.py --check 0.59.0` to confirm every version
declaration in the tree agrees, then `python audit_pure.py` for the GDAL-free
audit and `pytest` for the full suite (471 tests). For the resampler-selection
fix specifically, `python verify_mountain_terrain_v0.59.0.py` re-derives its
accuracy claim against known ground truth on your own GDAL build. Before producing
executables or release ZIPs, run `python RELEASE_GATE_v0.56.0.py` — still the
current ten-stage gate; there is no `RELEASE_GATE_v0.57.x` or `_v0.58.x`
despite what earlier compliance documents claimed — or the older
`RELEASE_CHECK_v0.55.0.py`, which additionally drives the PyInstaller build.
Rebuild executables after source changes so their embedded version metadata is
not stale.
