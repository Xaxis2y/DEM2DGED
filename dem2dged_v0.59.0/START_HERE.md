# DEM2DGED v0.59.0 — Start Here

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

Convert any GDAL raster elevation source into DGIWG 250 **DGED** tiles
(GeoTIFF), in Geographic (WGS-84) or UTM, with automatic post-conversion
validation. This folder is the **core tool** (CLI + GUI + validator).

v0.58.0 added **Show DGED Differences** to the ArcGIS Pro toolbox: it loads
the source DEM, the delivery tiles, the signed elevation difference and the
threshold-exceedance mask into one comparison group, using the QA rasters the
converter already wrote. v0.58.1 is a documentation, version-consistency and
release-tooling patch over it — no conversion or validation logic changed.

**Converting mountainous terrain? Two rules.** Use `--resample optimize`:
as of v0.59.0 it measures the real decimation and picks the most accurate of
six candidates for your specific source (over 32 ground-truth cases it now
picks correctly 28 times instead of 6). And leave `--prefilter` at `none` —
it reduces aliasing but measurably *worsens* elevation accuracy at each post
on steep terrain, so it is the wrong trade if you are judged on LE90. Both
are explained in `README.md`.

Everything runs in the same GDAL-enabled conda environment. If you don't
have it yet, use one of these methods:

**Method 1 — Automated (recommended):**
```batch
python dem2dged_anaconda_environment.py
```

**Method 2 — Manual (if you prefer):**
```batch
conda create --name dem2dged_anaconda_environment --channel conda-forge gdal python=3.11 -y
```

> The environment name is only a label. `dem2dged_anaconda_environment.py`
> creates one called `dem2dged_anaconda_environment`; some older docs and
> build notes say `DGED`, the name used on the maintainer's workstation. Use
> whichever you actually created — just never install into `base`, which is
> where the dependency conflicts come from.

Then, in an **Anaconda Prompt**:

```batch
conda activate dem2dged_anaconda_environment
cd path\to\dem2dged
```

---

## 1. Convert a DEM (quickest path)

```batch
:: GEO (WGS-84) output, level 5 (~2 m), auto resampler, auto-validated:
python dem2dged.py my_dem.tif output_folder

:: UTM output, level 4b (5 m), zone auto-detected:
python dem2dged.py my_dem.tif output_folder --mode utm --level 4b
```

Product levels → approximate ground sample distance:

| Level | GSD | Level | GSD |
|-------|------|-------|------|
| 0 | ~1000 m | 5 | ~2 m |
| 1 | ~100 m | 6 | ~1 m |
| 2 | ~30 m | 7 | ~0.5 m |
| 3 | ~12 m | 8 | ~0.25 m |
| 4b | ~5 m | 9 | ~0.125 m |
| 4 | ~4 m | | |

Useful options: `--resample auto|optimize|bilinear|cubic|average|near`,
`--org ABC` (producer code), `--abs-hacc` / `--abs-vacc`, `--source-vertical`
(real EGM2008 geoid transform), `--no-validate`, `--skip-sanity-check`,
`--terrain-qa mountain`, `--reference-dem`, `--verbose`. Run
`python dem2dged.py --help` for the full list.

Each delivery folder gets the tiles (`.tif`) + ISO 19115-2 metadata sidecars
(`.xml`), a `TABLE_OF_CONTENTS.xml`, a `*_COLLECTION.xml` (multi-tile), and a
`DGED_Validation_Report.txt` / `.html`.
It also gets `DEM2DGED_Conversion_Manifest.json` and
`validation/compliance_report.json` / `.txt`, `validation/statistics.json` and
`validation/report.html`. Supplying `--reference-dem` additionally creates
`validation/error_budget.json`, separating source error, conversion residual
and final output error on one DGED grid.

## 2. GUI

```batch
python dem2dged_gui.py
```

## 3. Validate an existing delivery

```batch
python dem2dged_validate.py output_folder -src my_dem.tif --terrain-qa mountain -html-report report.html
```

Exit code 0 = no automated failure (warnings allowed), 1 = structural/QA
failure, and 2 = `--require-full-compliance` found missing independent evidence.

## 4. Review a delivery in ArcGIS Pro

Open `DGED_Loader/DGED_Loader.pyt` from the Catalog pane (or the identical
copy `DGED_Loader.pyt` in this folder) with a map view already open. It
contains two tools:

- **Load DGED Tiles** — run it against the delivery parent folder. It
  recursively loads only `DGEDL*` tiles; the original DEM and
  `validation/elevation_diff.tif` / `error_mask.tif` are intentionally
  excluded.
- **Show DGED Differences** (v0.58.0) — run it against one `*_dged_output`
  folder. It loads the original source (recovered from the conversion
  manifest), the delivery tiles, the signed `elevation_diff.tif` and the
  red-styled `error_mask.tif` into one comparison group, prints the sign
  convention and the terrain-QA summary, and leaves the map ready for
  **Raster Layer > Appearance > Swipe**. You no longer need to add the source
  and QA rasters by hand.

Both need base ArcGIS Pro only — no mosaic dataset, no Spatial Analyst or
Image Analyst, no Standard/Advanced license.

---

## 5. Verify this build (recommended before you rely on it)

`verify.bat` runs an end-to-end check on your own DEMs (place them under
a `DEM\` subfolder) — logic audit, real conversions, validation, the
equatorial UTM zero-padding case, the aspect sanity-check, and the
data-type-aware GeoTIFF predictor — and writes everything to
`tests\logs\` (see `SUMMARY.txt`).

```batch
conda activate dem2dged_anaconda_environment
verify.bat
```

## 6. Build the standalone .exe (optional)

```batch
python BUILD_AND_PACKAGE.py      :: or rebuild_exe.bat
```

## 7. Package a source release

```batch
python dem2dged_package.py       :: -> dem2dged_v0.58.1.zip (one level up)
python BUILD_AND_PACKAGE.py      :: build the exes, then package both bundles
```

Before packaging, confirm every version declaration agrees:

```batch
python BUMP_VERSION.py --check 0.59.0
python audit_pure.py
pytest
```

---

## What's new in v0.59.0

- **`-resample optimize` now measures the operation it will actually
  perform.** It used to rank candidates on how well they *reconstructed* a
  point-sampled training grid — an upsampling test used to make a
  downsampling decision. On steep terrain at 16x that ranking was exactly
  inverted: Cubic B-Spline first (true RMSE 55.6 m), Nearest Neighbor last
  (10.2 m). Each candidate now warps your source down to the requested post
  spacing over six sub-pixel grid phases and is scored against the true
  terrain height at every target post.
- **Measured against known ground truth**, 32 cases: the correct candidate is
  chosen **28 times instead of 6**, and the avoidable error falls from
  **+573.62 m to +0.53 m**. Run `python verify_mountain_terrain_v0.59.0.py`
  to reproduce it on your own GDAL build.
- **`lanczos` added** as a sixth scored candidate; the comparison report now
  ranks on the same measurement, so it can no longer disagree with
  `optimize`.
- **Nothing else changed.** Tile geometry, filenames, metadata, seams and
  every compliance check are untouched; `auto` and every explicit
  `-resample <alg>` are bit-for-bit identical. Only what `optimize`
  *recommends* changes — so if you produced a steep-terrain delivery with
  `optimize` before this release, re-run it.

## What was new in v0.58.1

- **`README.md` restored.** v0.58.0 shipped with the project README
  overwritten by `DGED_Loader/README.md`, so the full reference was missing
  from the release.
- **Pre-filter guidance corrected** in `README.md`, `DEM2DGED_User_Manual.md`
  and `QUICKSTART.html`. They still recommended `--prefilter gaussian` for
  mountainous sources; v0.57.0 retracted that in the CLI help and the GUI
  after measurement showed it *worsens* point accuracy on steep terrain by
  44–102%. Both measurements are now shown side by side with the question
  each one answers.
- **`dem2dged_compare.py`'s import-fallback `VERSION`** had been stuck at
  `"0.45"` since v0.45; fixed, along with the `# Version:` headers of every
  file under `tests/`.
- **`BUMP_VERSION.py`** replaces the single-use bump scripts: generic,
  idempotent, dry run by default, with `--check <version>` as a release audit.
  `UPDATE_VERSIONS.py` is retired — it prepended a hardcoded v0.57.1
  changelog block to `VERSION.txt` on every run.
- **Known limitation documented** (not yet fixed): `-resample optimize`'s
  hold-out test scores *reconstruction* quality as a proxy for *decimation*
  accuracy, and the two diverge at high ratios on steep terrain. See
  `README.md`.

## What was new in v0.58.0

- **Show DGED Differences**, a second tool in the ArcGIS Pro Python toolbox —
  source, tiles, signed difference and exceedance mask in one comparison
  group, built from the QA rasters the converter already wrote.

## What was new in v0.55.0

- Reports now name the actual resampling method for every validation result.
- A sample-window FAIL is explained as a failure of that named method only;
  the report explicitly says not to distribute that comparison candidate.
- The resampling-comparison report distinguishes the best hold-out result from
  the recommended non-FAIL delivery candidate.

## Historical: v0.41

**Repair release — v0.40 did not work as shipped.**

- **Blocker fixed: the validator did not byte-compile.** `dem2dged_validate.py`
  was missing an entire block — every import, the `NODATA`/elevation-bound
  constants, `_STATUS_ORDER`, the `GEO_RE`/`UTM_RE` filename patterns and the
  `def overall_result(...)` line — so it failed with
  `IndentationError: unexpected indent (line 247)`. Auto-validation after a
  conversion silently wrote no report, the GUI's "Validate after conversion"
  checkbox was permanently disabled, and `dem2dged_validate.exe` could not be
  built. Restored and re-verified against every product level, hemisphere and
  UTM zone form.
- **The version self-audit was checking nothing** — the `# Version:` header
  comment was missing from all seven modules, and the pattern meant to check it
  could never match. Both fixed.
- **`tests/` is back** — `pytest.ini` pointed at a directory that did not exist,
  so `pytest` failed immediately. 185 unit tests + 22 GDAL integration tests.
- **A corrupt tile is now one FAIL, not a crash** in the validator.

No change to the DGED tables, tile geometry, filenames, metadata, resampling or
any spec-compliance check — a v0.39/v0.40 delivery does not need regenerating.

## What was new in v0.40

- **Data-type-aware GeoTIFF LZW predictor.** Float32 tiles (all UTM levels
  and GEO level 3+) now use `PREDICTOR=3` (the IEEE floating-point predictor)
  instead of `PREDICTOR=2`; Int16 tiles (GEO 0–2) keep `PREDICTOR=2`. Still
  LZW-lossless. *Re-run conversions to regenerate deliveries.*
- **Source-type letter sanity** — reserved/unknown codes (spec 12.1) now warn
  in the converters and the validator (non-blocking; default `A` is silent).
- **Logging fix** — the unified CLI now prints the `LEVELNAME:` prefix it
  always intended to.

See `VERSION.txt` for the full changelog and `README.md` for the complete reference.

## Troubleshooting

- `No module named 'osgeo'` → Activate the environment with `conda activate dem2dged_anaconda_environment` (and if the env was never created, run `python dem2dged_anaconda_environment.py` to set it up).
- Wrong UTM zone near Norway/Svalbard → pass `--zone` explicitly (e.g. `33X`).
- A `WARNING: -source_vertical not set` line just means heights are assumed to already be EGM2008 (only the label is applied). Pass `--source-vertical` for a real geoid transform.
