# DEM2DGED v0.55.0 Requirements and Compliance Evidence

SPDX-License-Identifier: GPL-2.0-or-later  
Copyright (c) 2026 Eui Soo SON

This file maps the supplied requirements review to implemented evidence. It
does not treat conversion success, agreement with the input DEM, or a default
accuracy goal as proof of real-world accuracy.

## Decision model

The consolidated report is written to
`validation/compliance_report.json`, `validation/compliance_report.txt`,
`validation/statistics.json` and `validation/report.html`.
Its overall state is:

- `PASS`: all automated mandatory checks have evidence and pass.
- `FAIL`: at least one mandatory check fails.
- `NOT_EVALUATED`: required evidence is absent. This is not a pass.

Absolute CE90/LE90 values in DGIWG 250 are reported as goals. Default metadata
values are now labelled as goals rather than predicted or measured accuracy.

## Requirement matrix

| Requirement area | v0.55.0 implementation | Evidence/status |
|---|---|---|
| Source CRS, GeoTransform, registration, extent, NoData, type | `inspect_source()` plus the structural validator | Automated |
| PixelIsPoint and half-post alignment | Exact expanded warp extent and validator grid-centre checks | Automated hard check |
| Avoid interpolation for an identical grid | Direct-copy eligibility path | Automated when all grid conditions match |
| Source resolution suitable for target level | Level-specific source eligibility; unified CLI/GUI block a finer target by default | Automated hard check; expert override remains `FAIL` |
| Vertical datum handling | Explicit `--source-vertical`; strict non-ballpark PROJ operation preflight records search paths and blocks missing geoid grids | Automated hard check for declared transformations; undeclared datum remains an assumption |
| DGED structure/header/metadata | Filename, pairing, GeoTIFF driver and byte-order/header signature, type, NoData, PixelIsPoint, CRS/vertical tag, dimensions, post spacing, bounds, XML, TOC and seams | Automated hard check |
| Adjacent tile identity | Edge reconciliation and seam validation | Automated hard check |
| Source-to-output error | Bias, MAE, RMSE, standard deviation, P90/P95/P99, maximum, difference and threshold rasters | Conversion-fidelity evidence only |
| Mountain terrain checks | Optional `mountain` mode: percent slope, >20% predominance, steep-error bins, top/bottom 1%, local peaks/valleys and +/-0.5-post sensitivity | Automated when selected |
| DGIWG mountain allowance | 1.4 vertical-accuracy factor only when predominant slope exceeds 20% | Automated, reported explicitly |
| Independent product accuracy | Separate `--reference-dem`, measured relative vertical 90% and horizontal CE90 inputs | `NOT_EVALUATED` until independent evidence is supplied |
| Source/conversion/final error separation | Same-grid vector identity and covariance-aware MSE decomposition in `error_budget.json`; no invalid MAE/RMSE subtraction | Automated when source and independent reference are supplied |
| Product-level accuracy limits | DGIWG 250 level 0-9/4b resolution, random/relative and absolute-goal values | Automated lookup and decision |
| Traceability and reproducibility | SHA-256 source/output hashes, requested/resolved algorithm, CRS/accuracy assumptions and GDAL/PROJ/Python versions | `DEM2DGED_Conversion_Manifest.json` |

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
