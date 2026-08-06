# DEM2DGED v0.40 — Start Here

Convert any GDAL raster elevation source into DGIWG 250 **DGED** tiles
(GeoTIFF), in Geographic (WGS-84) or UTM, with automatic post-conversion
validation. This folder is the **core tool** (CLI + GUI + validator).

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
`--verbose`. Run `python dem2dged.py --help` for the full list.

Each delivery folder gets the tiles (`.tif`) + ISO 19115-2 metadata sidecars
(`.xml`), a `TABLE_OF_CONTENTS.xml`, a `*_COLLECTION.xml` (multi-tile), and a
`DGED_Validation_Report.txt` / `.html`.

## 2. GUI

```batch
python dem2dged_gui.py
```

## 3. Validate an existing delivery

```batch
python dem2dged_validate.py output_folder -src my_dem.tif -resample auto -html-report report.html
```

Exit code 0 = no failures (warnings allowed), 1 = at least one FAIL.

---

## 4. Verify this build (recommended before you rely on it)

`verify.bat` runs an end-to-end check on your own DEMs (place them under
a `DEM\` subfolder) — logic audit, real conversions, validation, the
equatorial UTM zero-padding case, the aspect sanity-check, and the
data-type-aware GeoTIFF predictor — and writes everything to
`tests\logs\` (see `SUMMARY.txt`).

```batch
conda activate dem2dged_anaconda_environment
verify.bat
```

## 5. Build the standalone .exe (optional)

```batch
python BUILD_AND_PACKAGE.py      :: or rebuild_exe.bat
```

## 6. Package a source release

```batch
python dem2dged_package.py       :: -> dem2dged_v0.40.zip (one level up)
```

---

## What's new in v0.40

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
