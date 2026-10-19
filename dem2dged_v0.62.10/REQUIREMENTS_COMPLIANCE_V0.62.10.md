# DEM2DGED v0.62.10 Conformance Evidence Guide

SPDX-License-Identifier: GPL-2.0-or-later  
Copyright (c) 2026 Eui Soo SON

## Scope

DEM2DGED produces Defence Gridded Elevation Data (DGED) GeoTIFF deliveries.
The implemented product target is DGIWG 250 Edition 1.2.1, dated 2 October
2020, together with its referenced elevation and GeoTIFF standards.

The software produces technical conformance evidence. It does not issue NATO,
national, contractual, or operational certification. The accepting authority
must review the evidence package against its controlled standards baseline.

## Standards baseline

| Standard | Edition | Implemented role |
|---|---:|---|
| DGIWG 250 | 1.2.1 | DGED product profile and Annex A conformance criteria |
| DGIWG 116-1 | 1.1.1 | Elevation Surface Model |
| DGIWG 116-3-1 | 1.1.1 | ESM core encoding rules |
| DGIWG 116-3-2 | 1.1.1 | ESM GeoTIFF encoding rules |
| DGIWG 108 | 2.3.1 | DGIWG GeoTIFF profile |
| OGC 19-008r4 | 1.1 | GeoTIFF 1.1 |
| STANAG 2215 | Edition 7, July 2010 | Accuracy-evaluation context referenced by DGIWG 250 |
| STANAG 3809 | Edition 4, January 2004 | DTED exchange reference; not the output encoding of this tool |

Current public DGIWG listings:

- https://dgiwg.org/documents/dgiwg-standards
- https://portal.dgiwg.org/files/71215

## What ERROR_REDUCTION means

`ERROR_REDUCTION` and resampling comparison statistics measure agreement
between the conversion source and converted posts. They help select a
resampler and detect conversion damage. They do not measure source truth,
horizontal geolocation, vertical datum correctness, or absolute/relative
terrain accuracy. They can never satisfy the independent-accuracy gate.

## Full implemented evidence gate

The `--require-full-compliance` option, or the GUI option **Require full
implemented DGIWG 250 evidence gate**, returns or reports HOLD unless all of
the following have evidence. HOLD means report status `NOT_EVALUATED` or
`FAIL` and CLI exit code 2:

1. Product structure, naming, grid, tiling, encoding, metadata, seams, NoData,
   CRS, units, and delivery checks pass.
2. Source resolution, vertical reference, source horizontal CE90, and source
   vertical LE90 support the requested DGED level.
3. Source-to-output conversion fidelity passes the selected engineering
   policy. This is not independent accuracy.
4. An independent reference/control dataset is supplied and is not the source
   file, identical content, or a resampled/offset copy of the source (see
   *Reference independence screen*).
5. The reference has a durable identifier and the evaluation method or quality
   plan is declared.
6. Random horizontal error, relative horizontal accuracy, random vertical
   error, and relative vertical accuracy are evaluated against the applicable
   DGIWG 250 level thresholds.
7. Absolute horizontal CE90 and absolute vertical LE90 estimates are reported.
   Their DGIWG table values are goals, not substitutes for measured or
   defensibly predicted dataset estimates.
8. The output metadata contains numeric dataset CE90/LE90 estimates and a
   measured or defensible predicted basis. `auto` goal placeholders do not
   pass this gate.

For Levels 6 through 9, horizontal random/relative and vertical
random/relative evidence is particularly important and must not be omitted.

### Gate option rules (v0.61.4)

`--require-full-compliance` is rejected, before any conversion, when combined
with `--no-validate` (the validation step is what evaluates the gate) or
`--terrain-qa none` (item 3 needs the source-to-output comparison). The
`informational` compliance profile has no numeric limits, so with this option
it is replaced by `strict`; `standard` and `strict` are used as supplied.
The standalone `dem2dged_validate.py` applies the same rules. The GUI option
already forces `strict`.

### Reference independence screen (v0.61.5)

The reference is treated as independent only when all three checks pass:

| Check | FAIL when |
|---|---|
| Path | the reference is the conversion source file |
| SHA-256 | the reference has byte-identical content |
| Content | the source, resampled onto the reference grid with near, bilinear, cubic, cubicspline, lanczos, average or mode, matches the reference with a bias-removed residual standard deviation of 5 mm or less |

If the content check cannot run (no overlap, or fewer than 1000 overlapping
posts), independence is `NOT_EVALUATED` and the full gate holds. The
per-method statistics are recorded in `compliance_report.json` under
`independent_accuracy.checks.source_reference_independence.content_check`.

This is an engineering screen, not proof. Copies made with the med, min,
max, q1 or q3 resamplers or with a smoothing filter are not detected. The
control dataset's provenance document (evidence item 3) remains the primary
evidence that the reference is independent.

## GUI workflow

1. Select the source DEM, output mode, and DGED level.
2. Resolve source registration, elevation units, and verified vertical EPSG.
3. Enter numeric **Abs. H accuracy** and **Abs. V accuracy** dataset estimates;
   do not leave them as `auto` for a full evidence run.
4. In **DGIWG Accuracy Evidence**, select an independent control raster.
5. Enter its identifier and the approved evaluation procedure or quality-plan
   identifier.
6. Enter source CE90/LE90 and independently measured output horizontal random,
   horizontal relative, horizontal absolute CE90, and vertical relative values.
   Absolute and random vertical statistics are also calculated from the
   independent raster comparison.
7. Enable **Require full implemented DGIWG 250 evidence gate** and convert.
8. Review `validation/compliance_report.json`,
   `validation/compliance_report.txt`, and `validation/report.html`.

## CLI example

Run from an Anaconda Prompt in the dedicated `DGED` environment:

```bat
conda activate DGED
python dem2dged.py source.tif output --mode geo --level 6 --source-vertical 3855 --source-horizontal-accuracy 0.30 --source-vertical-accuracy 0.80 --reference-dem independent_control.tif --reference-identifier "CONTROL-2026-01" --accuracy-evaluation-method "QUALITY-PLAN-2215-01" --reference-horizontal-ce90 1.20 --reference-horizontal-random-90 0.30 --reference-relative-horizontal-90 0.80 --reference-relative-vertical-90 0.40 --abs-hacc 1.20 --abs-vacc 0.80 --terrain-qa full --compliance-profile strict --require-full-compliance
```

Never install GDAL or build dependencies into the Conda `base` environment.

## Claim boundaries

- A report `PASS` means all checks implemented by this software had evidence
  and passed for that delivery.
- STANAG 3809 conformance is `NOT_APPLICABLE` to the DGED GeoTIFF output. A
  DTED-format deliverable requires a separate DTED encoder and test suite.
- STANAG 2215 status describes quality-evaluation evidence only.
- Operational acceptance remains `NOT_EVALUATED` until the designated NATO,
  national, or customer authority accepts the delivery.
- A `PASS` is not permission to label the software or product “NATO certified.”

## Vertical datum conversion evidence (v0.62.10)

Every height conversion to EGM2008 (EPSG:3855) is checked against PROJ with
ballpark operations disabled; a conversion that PROJ can only express as a
ballpark is refused rather than applied. For CGVD2013 (EPSG:6647) data on the
generic NAD83(CSRS) horizontal CRS, PROJ has no strict chain, so dem2dged applies
a separate correction (`dem2dged_vertical.py`) and records:

- `vertical_operation_check.json` - the direct strict check and why it failed;
- `vertical_correction.json` - the route (ITRF2008 context), the independent
  cross-check realisation, the largest difference between the two routes (limit
  0.02 m), the shift range, the node grid and the operation accuracies stored in
  PROJ's database (0.03 m and 0.113 m; stated values, not measurements);
- `vertical_route` in `DEM2DGED_Conversion_Manifest.json`.

The correction is a model-to-model conversion between two published geoid
models. It does not measure or improve the absolute vertical accuracy of the
source data; the source LE90 must still come from the data provider.

## Seven-step evidence package

The bundled `dem2dged_evidence.py` utility creates and audits a review package
for requirements 1 through 7. Run `init` to create a manifest, control-point
CSV template, document folder, and authority acceptance form. Populate the
manifest only from authoritative source and quality documents, then run
`check` after the strict DEM2DGED validation report exists.

The utility can calculate transparent P90 statistics from the control-point
CSV when the governing quality plan authorizes that calculation. It records
the formula and sample count in the report; it does not claim to reproduce
every STANAG 2215 sampling or acceptance rule. The authority acceptance item
remains `HOLD` until an authorized reviewer supplies a signed acceptance
record.

## v0.62.10 addendum: geoid grid files and cross-check scope

- The separate CGVD2013 correction needs `ca_nrc_CGG2013i08.tif` and
  `us_nga_egm08_25.tif`. dem2dged fetches them once from cdn.proj.org into a local
  folder (`DEM2DGED_GRID_DIR`, default `%LOCALAPPDATA%\dem2dged\proj_grids`), can be
  told not to (`DEM2DGED_NO_GRID_DOWNLOAD=1`), and records the SHA-256 of each file
  in `vertical_correction.json`.
- The node cross-check (ITRF2008 route vs NAD83(CSRS) v8/v7/v4/v3 route) uses the
  same geoid grids on both sides. It verifies the horizontal-frame handling; it is
  not an independent test of the grid values. An independent comparison against an
  NRCan reference value has not been done.
- Stated accuracies (0.03 m, 0.113 m) come from PROJ's database and are not
  measured on the user's data.
