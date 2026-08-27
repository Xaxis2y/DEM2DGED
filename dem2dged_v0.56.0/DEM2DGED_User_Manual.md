# DEM2DGED User Manual — v0.56.0

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
`REQUIREMENTS_COMPLIANCE_V0.56.0.md` for the complete requirement matrix.

## Why comparison pixels can look large

The comparison source is warped onto the DGED delivery grid before subtracting.
Therefore `elevation_diff.tif` and `error_mask.tif` have the same post spacing
as the DGED level, not the native source spacing. A 2 m source converted to
DGED Level 2 produces roughly 30 m QA pixels. This is correct for delivery
QA: it measures exactly the samples in the product. ArcGIS Pro's Bilinear or
Cubic display resampling can make the display smoother but does not add data.

## ArcGIS Pro review

`DGED_Loader/DGED_Loader.pyt` is included with this release. Run it against a
delivery parent folder to recursively add only `DGEDL*` tiles to the active
map. It intentionally ignores original source TIFFs and `validation/`
artefacts, so add the source DEM, `elevation_diff.tif`, and `error_mask.tif`
separately for a clear original-versus-delivery review.

## Resampling guidance

Use direct copy whenever the grids are truly identical. For different grids,
choose `--resample optimize` when source-specific evidence is useful, or use
`near`, `average`, `bilinear`, `cubic`, `cubicspline`, or `lanczos` deliberately.
The Gaussian anti-alias prefilter is opt-in (`--prefilter gaussian`) because it
can improve rough mountainous terrain while harming near-planar terrain.

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

Run `python audit_pure.py` for the GDAL-free audit, then run the full
`RELEASE_CHECK_v0.55.0.py` in the GDAL/PyInstaller environment before producing
executables or release ZIPs. Rebuild executables after source changes so their
embedded version metadata is not stale.
