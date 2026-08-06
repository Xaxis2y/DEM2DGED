# dem2dged

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

**Current version: v0.40**

Convert raster Digital Elevation Models (DEMs) to military-standard **DGED** (Defense Gridded Elevation Data) tiles.

DGED is a DGIWG product profile for packaging elevation data for military use. It defines strict rules on GeoTIFF structure, tiling, projection, vertical datum (EGM2008), and sidecar metadata — and will replace DTED as the primary elevation exchange format across NATO.

> **Spec currency:** this tool targets DGIWG 250 (DGED) Ed. 1.2.1 — confirmed current against DGIWG's own standards page as of 2026-07-20. See [`DGIWG_STANDARDS_TRACKING.md`](DGIWG_STANDARDS_TRACKING.md) for the full compliance check and what's next in DGIWG's pipeline (a new tiling scheme is in early draft).

---

## What's in this folder

| File | Purpose |
| `dem2dged_gui.py` | **GUI application** — point-and-click converter, supports multiple DEMs |
| `dem2dged.py` | Unified command-line entry point (GEO and UTM modes) |
| `dem2dged_geo.py` | GEO mode converter (WGS-84 / EPSG:4326) |
| `dem2dged_utm.py` | UTM mode converter (auto-detects zone) |
| `dem2dged_lib.py` | Shared library (DGED tables, GDAL helpers) |
| `dem2dged_validate.py` | **Automated validator** — checks tiles for DGED compliance and data integrity |
| `DGED_GEO_TEMPLATE.xml` | ISO 19115-2 metadata sidecar template — GEO tiles |
| `DGED_UTM_TEMPLATE.xml` | ISO 19115-2 metadata sidecar template — UTM tiles |
| `dem2dged_anaconda_environment.py` | **Automated environment setup** (recommended) — creates `dem2dged_anaconda_environment` with GDAL and all dependencies |
| `dem2dged_anaconda_environment.bat` | Windows batch version of the environment setup script |
| `install.bat` | Windows one-click conda installer |
| `install.sh` | Linux / macOS one-click conda installer |
| `build_exe.bat` | Build a standalone `dem2dged.exe` (no Python needed on target machine) |
| `rebuild_exe.bat` | Re-run PyInstaller using the existing `dem2dged.spec` |
| `build_validate_exe.bat` | Build a standalone `dem2dged_validate.exe` (console tool, no Python needed) |
| `rebuild_validate_exe.bat` | Re-run PyInstaller using the existing `dem2dged_validate.spec` |
| `QUICKSTART.html` | Visual quick-start guide — open in any browser |

---

## Option 1 — Standalone EXE (Windows, no Python required)

A pre-built `dist\dem2dged.exe` can be produced by running `build_exe.bat` once on a machine with Anaconda installed. The resulting exe bundles Python, GDAL, and all dependencies — just double-click it on any Windows machine.

### Building the exe

```
# In Anaconda Prompt (base environment is fine)
cd path\to\your\dem2dged\folder
build_exe.bat
```

Output: `dist\dem2dged.exe` (~300–500 MB, fully standalone)

### Using the GUI

1. Double-click `dist\dem2dged.exe`
2. Click **+ Add Files…** and select one or more DEM files (hold Ctrl for multiple)
3. Choose an **Output Folder**
4. Select mode (**GEO** or **UTM**) and **Product Level**
5. Leave **"Validate after conversion and generate a report"** checked (on by default)
6. Click **⚙ Convert**

The GUI processes all files sequentially, shows live progress per file, and writes each DEM's tiles into its own subfolder (optional). When validation is enabled, it automatically runs the same checks as `dem2dged_validate.py` against every converted file right after conversion, and writes one combined `DGED_Validation_Report.html` (+ `.txt`) into the output folder — no separate step needed. The completion dialog shows the report's path; open the `.html` file in any browser.

---

## Option 2 — Python scripts (requires Anaconda + GDAL)

### Installation (one time)

**Automated setup (recommended):**
```bash
python dem2dged_anaconda_environment.py
```
This creates a dedicated environment named `dem2dged_anaconda_environment` with GDAL and all dependencies pre-installed. Supports `--verify` and `--remove` options.

**Alternative: Windows batch installer:**
```batch
dem2dged_anaconda_environment.bat
```

**Manual setup (if you prefer):**
```bash
conda create --name dem2dged_anaconda_environment --channel conda-forge gdal python=3.11 -y
conda activate dem2dged_anaconda_environment
```

Legacy installers (create environment named `DGED`):
```batch
# Windows
install.bat

# Linux / macOS
bash install.sh
```

### Quickstart

```bash
conda activate dem2dged_anaconda_environment
cd path/to/DEM2DGED

# GEO output (WGS-84), default level 5 ≈ 2 m GSD
python dem2dged.py my_dem.tif output_folder

# UTM output
python dem2dged.py my_dem.tif output_folder --mode utm

# All options
python dem2dged.py --help
```

### All options

```
python dem2dged.py <input_raster> <output_folder> [OPTIONS]

  --mode  geo|utm         Output projection  (default: geo)
  --level LEVEL           Product level  (default: 5)
  --zone  ZONE            UTM zone e.g. 32N, 09S  (UTM only; auto if omitted)
  --source-type  LETTER   Source-type code per DGED spec  (default: A)
  --security-class CLASS  T / S / C / R / U  (default: U = unclassified)
  --product-version VER   Two-digit version string  (default: 01)
  --resample ALG          auto|optimize|bilinear|cubic|cubicspline|average|
                          lanczos|near
                          (default: auto — average when downsampling, else
                          bilinear; never overshoots the source min/max.
                          optimize — measures Nearest/Bilinear/Cubic against
                          the source DEM itself and uses whichever
                          reconstructs it most accurately for that file;
                          slower than auto. For a source that looks like
                          angular/circular data — e.g. aspect or flow
                          direction — this is skipped in favor of Nearest
                          Neighbor automatically, since RMSE isn't a
                          meaningful accuracy measure across the 0/360
                          wraparound seam. See "Picking a resampling
                          method automatically" below.)
  --source-vertical EPSG  Source vertical datum EPSG (e.g. 5773=EGM96,
                          3855=EGM2008). If given and != 3855, a real geoid
                          transform to EGM2008 is applied (needs PROJ vertical
                          grids). If omitted, heights are assumed already
                          EGM2008 and only the label is applied (with a warning).
  --org CODE              Producer organisation/nation code (STANAG 1059),
                          embedded in filenames and metadata  (default: none)
  --abs-hacc METRES       Absolute horizontal accuracy (CE90) written to the
                          metadata quality report  (default: auto = spec
                          Table 5 goal value for the level)
  --abs-vacc METRES       Absolute vertical accuracy (LE90) written to the
                          metadata quality report  (default: auto = spec
                          Table 6 goal value for the level)
  --lineage TEXT          Lineage statement written to the metadata (default:
                          generated from the source file name and settings)
  --verbose               Print debug/progress details
  --no-validate           Skip the automatic post-conversion validation report
  --skip-sanity-check     Proceed even if the input raster's value range and
                          filename look like non-elevation data (e.g. an
                          aspect/direction/curvature layer). By default the
                          tool blocks when BOTH the filename and the value
                          range point to non-elevation data, and warns (but
                          proceeds) when only one does. See "Pre-flight
                          elevation sanity check" below.
```

`dem2dged.py` validates automatically after every conversion (unless `--no-validate` is passed): it runs the same checks as `dem2dged_validate.py` against the output it just produced, comparing back against your source DEM, and writes `DGED_Validation_Report.html` + `.txt` into `output_folder`. This also works from `dem2dged.exe` once rebuilt — see "Automatic validation" below.

### Pre-flight elevation sanity check

New in v0.36. Before doing any work, the tool checks whether the input actually looks like elevation data. This exists because DGED is an elevation-only format, but nothing about a GeoTIFF says "these numbers are heights" — feeding in a slope-direction (aspect) raster, a flow-direction grid, or a curvature layer converts without error and only shows up later as confusing, oversized RMSE/tolerance failures in the validation report.

The check looks at two independent signals:

- **Filename** — does it contain a word like `aspect`, `direction`, `curvature`, `orientation`, `bearing`, `azimuth`, `hillshade`, or similar.
- **Value range** — does the raster's actual min/max closely span 0–360, the range compass/aspect output always falls in.

If **both** signals point away from elevation, the tool stops before producing any output:

```
ERROR: source filename contains 'aspect' AND its value range (18.52 to 345.51)
matches compass/aspect output (0-360 degrees) almost exactly. This looks like
a slope-direction (aspect) raster, not elevation -- DGED is an elevation-only
format. If you meant to convert the elevation DEM/DTM this was derived from,
point the tool at that file instead.
ERROR: conversion stopped before doing any work -- the input above is very
likely not elevation data. Re-run with -skip_sanity_check if you are sure
this is correct.
```

If only **one** signal is present (an oddly-named but genuine elevation file, or real terrain that happens to span close to 0–360 in some unit), the tool prints a `WARNING:` and proceeds normally — false positives never block a legitimate conversion. If you've checked the warning and the input is correct, or you need to bypass a block, pass `-skip_sanity_check` (`dem2dged_geo.py` / `dem2dged_utm.py`) or `--skip-sanity-check` (`dem2dged.py`). In the GUI, use the "Skip elevation sanity check" checkbox.

### Picking a resampling method automatically

New in v0.36. `-resample auto` (the default) is a fixed rule of thumb based only on the ratio between source and target ground sample distance — it never looks at how accurately each algorithm actually reconstructs your specific DEM.

`-resample optimize` instead **measures** it: using the same hold-out cross-validation as the Resampling Comparison Test (see below), it withholds every other source post, reconstructs the full grid from the rest using Nearest Neighbor / Bilinear / Cubic Convolution, and scores each method against the real values it withheld — then uses whichever method reconstructed the source most accurately. No extra tiles or reports are written; it only costs a bit of extra time up front (one read of the source plus three small in-memory warps) before the real conversion runs once, with the winning method. In the GUI, pick "Optimize" from the Resampling Method dropdown.

This ties directly into the sanity check above: for a source flagged as angular/circular data (e.g. an aspect layer you've deliberately chosen to convert anyway with `-skip_sanity_check`), RMSE is not a meaningful accuracy measure — averaging a true value of 1° and a reconstructed value of 359° gives 180°, the compass direction opposite both real values. `-resample optimize` detects this and uses Nearest Neighbor directly instead of ranking methods by a number that would not mean anything.

```bash
python dem2dged.py my_dem.tif output_folder --resample optimize
```

---

## Product levels

| Level | Approx GSD | Tile size (GEO) | Tile size (UTM) |
|-------|-----------|-----------------|-----------------|
| 0     | ~1000 m   | 1°              | —               |
| 1     | ~100 m    | 1°              | —               |
| 2     | ~30 m     | 1°              | —               |
| 3     | ~12 m     | 1°              | —               |
| 4b    | ~5 m      | 15'             | 25 km × 25 km   |
| 4     | ~4 m      | 15'             | 25 km × 25 km   |
| **5** | **~2 m**  | **6'**          | **10 km × 10 km** |
| 6     | ~1 m      | 3'              | 5 km × 5 km     |
| 7     | ~0.5 m    | 1.5'            | 2.5 km × 2.5 km |
| 8     | ~0.25 m   | 1'              | 2.5 km × 2.5 km |
| 9     | ~0.125 m  | 1'              | 1.25 km × 1.25 km |

Level 5 (default) is a good all-round choice for standard LiDAR or high-res satellite DEMs. Pick the level that matches your input data's native resolution — upsampling to a higher level won't add real detail.

---

## Output file naming

The output filename encodes the tile's location and metadata — it does **not** use the input file's name.

### GEO tiles

Levels 4b and up carry the tile-size letter and are delivered per sub-degree tile:
```
DGEDL<LEVEL>Gt<LETTER>_[<ORG>_]<LAT><HEMI><LON><EAST>_<SRC>_<SEC>_<VER>.tif/.xml

Example:  DGEDL5GtD_5530N00930E_A_U_01.tif
          └─ Level 5, GEO, lat 55°30'N, lon 009°30'E, source A, unclassified, v01
```

Levels 0-3 are delivered per whole square degree and omit the tile-size letter (v0.27+):
```
DGEDL<LEVEL>_[<ORG>_]<LAT><HEMI><LON><EAST>_<SRC>_<SEC>_<VER>.tif/.xml

Example:  DGEDL2_27N056E_A_U_01.tif
          └─ Level 2, GEO, lat 27°N, lon 056°E, source A, unclassified, v01
```

### UTM tiles
```
DGEDL<LEVEL>Ut<LETTER>_[<ORG>_]<ZONE><NORTHING>_<EASTING>_<SRC>_<SEC>_<VER>.tif/.xml

Example:  DGEDL5UtD_32N6210_452_A_U_01.tif
          └─ Level 5, UTM zone 32N, northing 6210 km, easting 452 km
```

`<ORG>` is the optional 2-4 letter producer/nation code set with `--org` (both modes); it's omitted from the name entirely when not set.

A large DEM typically produces many tiles — one `.tif` + `.xml` pair per tile covering the input extent — plus, per output folder: a `TABLE_OF_CONTENTS.xml` listing every file in the delivery, and (for multi-tile products) a `<product>_COLLECTION.xml` with series-level metadata.

---

## Verifying output

### Automatic validation (default, no extra step needed)

Both `dem2dged.py` and `dem2dged_gui.py` (and their `.exe` builds, once rebuilt)
run the validator automatically right after conversion and write a styled
`DGED_Validation_Report.html` (+ a plain-text `.txt` copy) into the output
folder — open the `.html` file in any browser. Disable it with `--no-validate`
on the CLI, or by unchecking "Validate after conversion" in the GUI.

Because `dem2dged_gui.py` `import`s `dem2dged_validate.py` directly (in-process,
no subprocess call), this works the same way whether you run the `.py` scripts
or the compiled `.exe` — PyInstaller bundles the validator module into
`dem2dged.exe` automatically the next time it's rebuilt:

```
conda activate DGED
cd path\to\your\dem2dged\folder
rebuild_exe.bat
```

A single combined report is written per batch: for the GUI, one
`DGED_Validation_Report.html` in the output folder covering every file you
converted in that run (one card per dataset); for the CLI, one report per
`dem2dged.py` invocation, saved inside that run's `output_folder`.

### Manual validator run

```bash
# Full validation of a tile folder, comparing against the original DEM
python dem2dged_validate.py output_folder -src my_dem.tif -report validation_report.txt -html-report validation_report.html

# Quick spec-compliance check only (no source comparison)
python dem2dged_validate.py output_folder
```

A standalone `dem2dged_validate.exe` (no Python/GDAL install needed on the
machine that runs it) can be built the same way as `dem2dged.exe`:

```
REM In Anaconda Prompt, an environment with GDAL installed (e.g. DGED)
conda activate DGED
pip install pyinstaller
cd path\to\your\dem2dged\folder
build_validate_exe.bat
```

Output: `dist\dem2dged_validate.exe`. Run it exactly like the Python script:

```
dist\dem2dged_validate.exe output_folder -src my_dem.tif -report report.txt -html-report report.html
```

Use `rebuild_validate_exe.bat` afterwards to rebuild from the checked-in
`dem2dged_validate.spec` (picks up code changes without re-typing all the
PyInstaller flags).

The validator checks, per tile and across the tile set:

- **File pairing** — every `.tif` has its `.xml` sidecar and vice versa
- **Naming** — DGED filename convention; encoded coordinates must match the actual georeferencing; tile letter must match the level
- **Header** — correct data type for the level (`Int16` for levels 0-2, `Float32` for level 3+), NoData `-32767`, `AREA_OR_POINT=Point`, LZW, EGM2008 (EPSG:3855) tag
- **Grid geometry** — pixel size = level GSD, dimensions = expected posts (incl. one-post overlap), origin aligned to the DGED tile grid
- **XML sidecar** — well-formed, all placeholders replaced, level/basename consistent
- **Statistics & NoData** — sane elevation range, no NoData values leaking into valid data ("-32767 m trenches")
- **Edge overlap** — the shared row/column of adjacent tiles must be *identical*; catches half-pixel shifts and row/column indexing bugs
- **Source comparison** (`-src`) — mosaic must cover the source extent; min/max/mean within tolerance; pixel-level |difference| in sample windows (default tolerance 5 m, adjustable with `-max-diff`)

Exit code 0 = PASS, 1 = FAIL — suitable for scripted pipelines.

> Note: dem2dged re-projects and resamples (bilinear) onto the DGED tile grid, so a bit-exact
> "round-trip" comparison with the source is not applicable by design. Small differences in the
> sample-window check are expected; large ones indicate a real problem.

### Manual check

```bash
gdalinfo <tile>.tif
```

Confirm these in the output:
- `AREA_OR_POINT=Point` — required by DGED spec
- `COMPD_CS` or `EPSG:4326+3855` in the CRS — confirms compound CRS is tagged
- Data type: `Int16` for levels 0-2, `Float32` for level 3+ (spec section 7) — elevation values intact

---

## Compatibility notes

### ArcGIS Pro
Tiles load correctly into ArcGIS Pro. The compound CRS (`EPSG:4326+3855`) is written as a metadata tag — ArcGIS Pro reads the horizontal component for display and the EGM2008 vertical tag for datum-aware analysis.

### Vertical datum (EGM2008)
The tool tags each tile with the EGM2008 vertical datum (`EPSG:3855`) per the DGED spec. It does **not** perform a physical height transformation from ellipsoidal to EGM2008 (which would require the `egm08_25.gtx` grid shift file). This matches the behaviour of most DGED converters — the elevation values from your input DEM are preserved as-is, and only the CRS metadata label is set to EGM2008. If your workflow requires a true vertical datum shift, pre-process your DEM with `gdalwarp -t_srs EPSG:3855` before converting.

---

## Known limitations

- **Norway / Svalbard:** UTM auto-detect may pick the wrong zone. Use `--zone` explicitly (e.g. `--zone 33N`).
- **Border tiles:** A ring of near-empty tiles appears around the data extent due to the DGED "one-cell overlap" rule. Filter by file size or delete manually if unwanted.
- **Interrupted runs:** Re-run the same command — the tool skips tiles that already have a completed `.xml` sidecar. Delete the last tile first if it may be partially written.

---

## Troubleshooting

### GDAL / PROJ initialization errors

**Symptom:** `ERROR: GDAL cannot open: ...` or `ModuleNotFoundError: No module named 'osgeo'`

**Solution:**
- Ensure the environment is activated: `conda activate dem2dged_anaconda_environment`
- If the environment doesn't exist, set it up: `python dem2dged_anaconda_environment.py`
- For Windows EXE: the GDAL/PROJ data should be bundled. If still failing, rebuild the EXE using `build_exe.bat` after activating the environment.

### GDAL_DATA or PROJ_LIB not found

**Symptom:** Coordinate transformation fails silently or produces incorrect results.

**Solution:**
- These environment variables are automatically set by `dem2dged.exe` and the Python scripts.
- If manually running `dem2dged.py` outside the environment, ensure you have activated it: `conda activate dem2dged_anaconda_environment`
- Check paths: `python -c "import os, osgeo; print(os.path.dirname(osgeo.__file__))"`

### Geoid transformation fails (EGM96, EGM2008, etc.)

**Symptom:** `ERROR: Cannot apply geoid transformation` or `vertical grid file not found`

**Solution:**
- The geoid transformation (--source-vertical option) requires PROJ grid files (e.g., `egm08_25.gtx`).
- These are not bundled in the EXE by default. Download them:
  ```bash
  conda activate dem2dged_anaconda_environment
  projsync --all
  ```
- Alternatively, omit `--source-vertical` and the tool will assume your input heights are already in the target datum (EGM2008 by default) and only apply the label.

### Incorrect elevation ranges or min/max mismatches

**Symptom:** Validator reports `FAIL: min/max out of tolerance` or elevation values seem wrong.

**Solution:**
- Check your source DEM's vertical datum. If it's not EGM2008, use `--source-vertical EPSG:CODE` (e.g., `5773` for EGM96).
- Ensure your source DEM is a valid GeoTIFF with proper georeferencing: `gdalinfo my_dem.tif | head -20`
- If using ellipsoidal heights (WGS-84 ellipsoid), convert to EGM2008 first: `gdalwarp -t_srs EPSG:3855 my_dem.tif dem_egm2008.tif`

### Border tiles (near-empty tiles around extent)

**Symptom:** Many .tif files created but many are nearly empty or very small file sizes.

**Solution:**
This is expected behavior due to the DGED "one-cell overlap" rule (adjacent tiles share their edge pixels for validation). To clean up:
- Delete tiles < 50 KB: `find output_folder -name "*.tif" -size -50k -delete`
- Or filter by minimum valid pixel count in post-processing.

### Svalbard / Norway UTM zone warnings

**Symptom:** `WARNING: Svalbard region detected...` or `WARNING: Norway region detected...`

**Solution:**
- The tool auto-detected high-latitude data (60-81°N). Zone boundaries are ambiguous in this region.
- Specify the correct zone explicitly: `--zone 33X` (Svalbard) or `--zone 32N` (mainland Norway).
- Common Svalbard zones: 31X (west), 33X (center), 35X (east), 37X (far east)
- Refer to [UTM special zones](https://en.wikipedia.org/wiki/Universal_Transverse_Mercator_coordinate_system#Exceptions)

### Interrupted / partial conversion (missing or incomplete tiles)

**Symptom:** Last .tif file is smaller than expected, or .xml sidecar is missing.

**Solution:**
- The tool skips tiles that already have a completed `.xml` sidecar (resumption logic).
- To re-run: delete the partially-written tile first, then re-run the same command.
- Or delete the last tile's .xml to force re-conversion of that tile.

### Out of memory on large DEMs

**Symptom:** Process crashes with `MemoryError` or OS kills the process.

**Solution:**
- The tool processes DEM data in tiles, but very large source DEMs (>100k × 100k pixels) may exceed available RAM during reprojection.
- Options:
  - Use a machine with more RAM.
  - Split the source DEM into smaller tiles before conversion: `gdal_translate -srcwin ...`
  - Use the validator in parallel on multiple machines if you have pre-split tiles.

### File size differences between expected and actual output

**Symptom:** Output .tif files are larger or smaller than expected.

**Solution:**
- File size depends on elevation data diversity (entropy). Flat areas compress better than mountainous areas.
- LZW compression is deterministic; the same data always produces the same size.
- Use `gdalinfo output_file.tif` to verify dimensions and data type (should be Int16 for levels 0-2, Float32 for level 3+).

### Validation report shows many WARN or FAIL

**Symptom:** Validation report has warnings or failures; tiles don't meet spec.

**Solution:**
- Open the HTML report (`DGED_Validation_Report.html`) for detailed explanations of each failure.
- Common issues:
  - **Header mismatches:** Check `AREA_OR_POINT=Point` and CRS tags with `gdalinfo`
  - **Grid geometry errors:** Source data not perfectly aligned to the DGED grid (expected; usually small differences are OK)
  - **Edge overlap:** Adjacent tiles' shared row/column don't match exactly (resampling can cause 0-5 m differences; tolerance is 10 m by default)
  - **Statistics:** NoData values leaking into valid data; check source DEM for artifacts

### Cannot open template XML files

**Symptom:** `ERROR: GDAL cannot open: DGED_GEO_TEMPLATE.xml`

**Solution:**
- The template files must be in the same directory as the scripts (for Python) or bundled in the EXE (for `.exe`).
- For manual template path: `python dem2dged_geo.py input.tif output/ -xml_template /path/to/template.xml`
- Rebuild the EXE if you modified the template: `rebuild_exe.bat`

---

## Technical notes

- Output: **LZW-compressed, tiled GeoTIFF**, `Int16` for levels 0-2 / `Float32` for level 3+ (spec section 7), `PREDICTOR=2`
- Vertical datum tag: **EGM2008** (EPSG:3855) — metadata only, no height transform
- Horizontal CRS: WGS-84 geographic (GEO) or UTM (auto-detected or user-specified)
- No-data value: **−32767**
- Resampling: **bilinear**
- Sidecar metadata: **ISO 19115-2 / DGIWG DMF 2.0** XML

---

## Versioning

The project version lives in **one place**: `VERSION` at the top of `dem2dged_lib.py`. On every update, bump that value and add a row to the changelog below. The version is displayed in the CLI banner (`python dem2dged.py --version`), the GUI title bar, and the release zip filename (`dem2dged_vX.XX.zip`).

## Changelog

| Version | Change |
|---|---|
| v0.38 (2026-07-20) | **Two real bugs found by actually running the real CLI and pytest suite** — the previous v0.37 release had only been verified by manual code review plus a GDAL-free reimplementation testbed, since GDAL wasn't available in that environment; this is the first time either the real tool or the real test suite had run end to end. **Bug 1 (validator silently dropped both report files):** `dem2dged_validate.py`'s `Report._emit()` unconditionally `print()`ed every report line, including the box-drawing section headers (`section()`), straight to the console. On Windows with stdout redirected to a file under a legacy console code page (cp1252), that `print()` raised `UnicodeEncodeError`, which propagated up through `run_validation()` into `dem2dged.py`'s auto-validation `try`/`except` — silently skipping *both* `DGED_Validation_Report.txt` and `.html` even though every check had already completed successfully. `_emit()` now falls back to a best-effort re-encode of just the console echo on that error; the report content itself (`self.lines`, what actually gets written to disk) was never affected. **Bug 2 (flaky test):** `tests/conftest.py`'s `output_dir` fixture always resolved to the same session-wide `output` subdirectory for every test that requested it, so a test's leftover tiles were still sitting there — never cleaned up — when the next test ran its own conversion into the "same" folder and globbed `*.tif` expecting only its own output. That's why `test_utm_names_are_zero_padded` could fail on a leftover *GEO*-named tile left behind by an earlier `TestGeoConverter` test; the UTM zero-padding logic itself was never wrong. Every test now gets a fresh `tempfile.mkdtemp()`. **Independent re-verification of v0.37's Findings 1 and 3**, this time directly against real GDAL-produced tiles instead of a reimplementation testbed: shared-edge `max\|diff\|` = 0.0000 m on the real-terrain dataset across all three resampling methods (was up to 1.6 m), and Cubic Convolution tiles' min/max now land exactly on the two test rasters' true source ranges — 0..255 and 6..255 — instead of overshooting to -41..285 / -44..313. **Bug 3 (validator-side false FAIL on cubic runs):** with Bug 1 fixed and reports actually being written, both real cubic-convolution runs FAILED Section H (global min/max) on a validator-side artifact, not a real defect. `check_source()`'s H/H2 checks build their own internal re-warp of the source using the tiles' actual resample algorithm (v0.37 Finding 2) as a like-for-like comparison baseline — but that re-warp was never clamped the way the real delivered tiles are (v0.37 Finding 3), so a correctly-clamped tile (e.g. ACAIPGTM: 0.00..255.00 m) was compared against a still-overshooting baseline (-18.33..274.21 m) and flagged as an 18–19 m "defect" that was really just clamped-vs-unclamped. `check_source()` now computes the same clamp range the converters use (`dem2dged_lib.compute_tile_stats()` on the source) and applies it to both H's global-stats re-warp and H2's per-window re-warp. |
| v0.37 (2026-07-20) | **All five findings of an independent code review fixed** (`DGED_Conversion_Review.md`, an audit of a 9-run/42-tile DGIWG test-data conversion batch). **Finding 1 (real defect, real-terrain delivery):** adjacent DGED tiles are warped by independent `gdalwarp` calls, so nothing guaranteed they agreed on the single post row/column the spec requires them to share — confirmed as a 1.6 m seam on a 5 m-post real-terrain tile pair (Nearest Neighbor; 12–13 cm for Bilinear/Cubic on the same pair, same root cause). Warp extents are now rounded to a fixed coordinate precision, and a new post-warp pass, `dem2dged_lib.reconcile_tile_edges()`, copies each tile's shared edge pixels onto its neighbour so the two files are bit-identical along that edge regardless of what either individual `gdalwarp` call did internally — verified against the actual DGIWG test tiles that showed the seam, for all three resampling methods, and applied to both CLI converters and the GUI. **Finding 2 (validator bug):** the validator's source-comparison sections (H/H2) re-warped the source DEM as Bilinear unconditionally, regardless of what the tiles were actually made with, despite a code comment claiming otherwise — so Nearest Neighbor/Cubic runs partly failed on "how different is this from Bilinear," not "how wrong is this tile." The actual resampling algorithm is now threaded through from the converters and GUI into `dem2dged_validate.check_source()`/`run_validation()`, with a new `-resample`/`--resample` validator CLI flag for standalone use. **Finding 3 (real, expected, now handled):** cubic-family resamplers (cubic, cubicspline, lanczos) can overshoot the source's true min/max at sharp discontinuities — confirmed on two 8-bit, hard-step-edge DGIWG test rasters, with Cubic Convolution tiles as low as -44 m against a true source minimum of 0–6 m. Tiles made with one of these resamplers are now clamped back into the source's exact range right after warping (`dem2dged_lib.clamp_tile_to_range()`); resamplers dem2dged picks automatically (average, bilinear) never overshoot and are unaffected. **Finding 4 (cosmetic, but confusing):** the text report's `RESULT:` line used a 2-tier PASS/FAIL rule while the HTML badge and GUI comparison badge each used a 3-tier FAIL > WARN > PASS rule, so identical PASS=/WARN=/FAIL= counts for the same run could read differently across reports. All of them now call one shared `dem2dged_validate.overall_result()`. **Optional polish:** the validator's H2 sample-window placement is now coverage-aware, nudging a fixed window to the nearest spot with actual data instead of routinely warning "no overlapping valid data" on deliveries whose footprint doesn't fill its bounding box evenly. |
| v0.36 (2026-07-20) | **Pre-flight elevation sanity check + auto-optimize resampling**, prompted by a real validation-failure report: an aspect/direction raster fed into the tool as if it were elevation, which produced huge, confusing RMSE/tolerance failures because nothing about a GeoTIFF says "these numbers are heights." (1) **New pre-flight check** (`dem2dged_lib.sanity_check_elevation_source()`) inspects the source's filename (`aspect`, `direction`, `curvature`, `orientation`, `bearing`, `azimuth`, `hillshade`, `flow_dir`/`flow_acc`, `slope_class`) and its actual value range (`quick_raster_range()`, a fast approximate `ComputeStatistics()` call) for signs it is a terrain *derivative* rather than elevation. Blocks by default only when **both** a filename hint and a 0–360-degree-like range are present; warns but proceeds on either signal alone, so real elevation data with an unusual filename or range is never falsely blocked. New CLI flag `-skip_sanity_check` / `--skip-sanity-check` and GUI checkbox "Skip elevation sanity check" override it. (2) **New `-resample optimize` mode** (`dem2dged_lib.resolve_resampler()`): instead of `-resample auto`'s fixed source/target-GSD-ratio rule of thumb, it measures Nearest Neighbor / Bilinear / Cubic Convolution against the source DEM itself — reusing the Resampling Comparison Test's hold-out cross-validation (`dem2dged_compare.pick_best_resampling()`), but writing no tiles or report — and uses whichever reconstructs it most accurately for that specific file. New GUI dropdown entry "Optimize." The two features are linked: for a source that the sanity check flags as angular/circular data, RMSE is not a meaningful accuracy measure across the 0/360 wraparound seam (averaging 1° and 359° gives 180°, the compass direction opposite both real values), so `optimize` mode skips the comparison entirely and uses Nearest Neighbor directly rather than ranking methods by a number that would not mean anything. Both features' classification/selection logic is unit tested GDAL-free — `audit_pure.py` sections 8–9 and `tests/test_lib.py`'s `TestSanityCheck` / `TestAutoOptimizeResampling` — by monkeypatching the one function in each that actually touches a raster, rather than mocking GDAL's dataset object graph. |
| v0.35 (2026-07-20) | **Docstring fix + comparison-report glossary.** (1) `dem2dged_validate.py`'s module docstring held its changelog prose in a plain (non-raw) triple-quoted string containing literal `\d+` / `\d{1,7}` describing `UTM_RE` — valid but deprecated since Python 3.6, printing `SyntaxWarning: invalid escape sequence '\d'` on Python 3.12+. Cosmetic only: `GEO_RE`/`UTM_RE` themselves were already correctly built as raw strings and unaffected; fixed by making the docstring itself a raw string. (2) `dem2dged_compare.py`'s HTML Resampling Comparison Report used RMSE / MAE / Bias / Overshoot without ever spelling any of them out — column headers now carry a `title=` tooltip with the full definition, and the report's closing note gains a "Terms" glossary paragraph, so the report is readable without already knowing the jargon. |
| v0.34 (2026-07-20) | **Full-project audit pass — 10 fixes.** See `CODE_REVIEW_v0.34.md` for the evidence behind each, and run `python audit_pure.py` (no GDAL needed) to verify. **Three behaviour changes:** (1) **SPEC — UTM filenames are now zero-padded** to the spec 12.1 field widths (`nnnn`/`eee` for levels 4b-6, `nnnnmmm`/`eeemmm` for 7-9). `utm_tile_basename()` built these with a bare `int()`, so any northing below 1 000 000 m produced a short field — `..._32N500_400_...` instead of `..._32N0500_400_...`, and a tile on the equator produced `..._32N0_...`. Every UTM delivery within ~9° of the equator was affected, and the validator's `\d+` pattern accepted them, so converter and validator were consistently wrong together. Both now use the shared `utm_name_field_widths()`. **⚠️ This changes filenames — re-run the conversion to regenerate affected deliveries.** (2) The converters no longer emit a row and column of pure-NoData tiles past the data (loop bound was `floor()+1`, now `ceil()`; that was 21 of 121 tiles on a 1°×1° level-5 source). (3) `dem2dged_gui.py`'s stale pre-v0.27 fallback DGED tables are deleted — they still described levels 8/9 as 1-minute "G" tiles, which gives non-integer longitude intervals in latitude zones 2 and 4, i.e. exactly the post-misalignment bug v0.27 fixed. **Report-only / robustness:** the validator checks UTM field widths and accepts double-dash flags (`--html-report` was documented but rejected outright by argparse); `dem2dged_compare.py` writes its scratch raster to a private temp dir instead of the delivery folder (a failed warp used to leave it behind and trigger a bogus validation FAIL); the GUI gains **Organisation / Abs. H accuracy / Abs. V accuracy / Lineage** fields to match the CLI; `test_converters.py` no longer asserts `len(*.tif) == len(*.xml)`, impossible since v0.27; version consistency across 12 declarations is now enforced by tests instead of by hand; `BUILD_AND_PACKAGE.py` checks the full module list; axis-order strategy is set explicitly (**requires GDAL 3+**). **Build scripts:** `build_exe.bat` used to silently overwrite the curated `dem2dged.spec`, and disagreed with it about `--windowed` vs `console=True` — both fixed; see the new `BUILD_SCRIPTS_GUIDE.md`. Packaging scripts renamed to drop the stale `_v0.26` suffix. |
| v0.33 (2026-07-17) | **GUI resampling control + resampling comparison test.** (1) New "Resampling Method" dropdown in the GUI — default **Auto** (the validator-safe automatic choice used since v0.20: `average` when downsampling, else `bilinear`) with manual overrides **Nearest Neighbor / Bilinear Interpolation / Cubic Convolution**; routed through `pick_resampler()`'s existing override parameter, the same path the CLI's `-resample` flag has used since v0.20, so GUI and CLI now expose identical resampling control. (2) New "Resampling Comparison Test" section: one checkbox per method — any checked subset (1, 2, or all 3) is converted side-by-side into per-file test folders `test_1_nearest_neighbor` / `test_2_bilinear_interpolation` / `test_3_cubic_convolution` (the dropdown is ignored in comparison mode; a failed method is recorded and the others continue). (3) New module `dem2dged_compare.py` measures each method two ways — **hold-out cross-validation** (every other source post withheld, reconstructed with the method's algorithm, and scored against the true withheld elevations; the primary ranking metric, immune to nearest-neighbor's trivially-perfect round trip) and a **tile round-trip residual** (delivered tiles mosaicked, warped back onto the source grid with an identical bilinear back-warp for fairness, and differenced post-by-post, including min/max range overshoot — the fingerprint of cubic ringing) — and writes `DGED_Resampling_Comparison_Report.html`, a ranked side-by-side table per input file with the lowest hold-out-RMSE method marked "★ Most Accurate". If "Validate after conversion" is on, each test folder is also validated and its PASS/WARN/FAIL badge shown in the table. (4) New `selftest_resampling_comparison.py` runs the whole feature end-to-end on a synthetic DEM with real GDAL and checks the expected physics. |
| v0.32 (2026-07-16) | **Housekeeping release — no functional/algorithmic changes.** (1) The `Version: 0.29` header comment in `dem2dged.py`, `dem2dged_geo.py` and `dem2dged_utm.py`, and `dem2dged_gui.py`'s `APP_VERSION` import fallback, had all silently drifted behind `dem2dged_lib.py` (the single source of truth) during the v0.30/v0.31 validator-only releases, which bumped `VERSION` there and in `dem2dged_validate.py` but not the header comments of the four other modules that just mirror it — all four now read `0.32` again. (2) `dem2dged_package_v0.26.py` (the whole-tool zip, separate from the validator-only package) walked the entire project folder with no exclusions, so every release zip bundled PyInstaller `build`/`dist` output, `__pycache__`, `.pytest_cache`, and any earlier release zips already sitting in the folder — it now excludes those, matching the curated file list `dem2dged_validate_package_v0.26.py` already used. |
| v0.31 (2026-07-16) | **Two more validator false-positive fixes, found auditing a real conversion run.** (1) "Name says origin X but georef is Y" (check D) compared the raw raster corner against the nominal tile origin with a half-pixel tolerance — but the v0.27 half-post warp extent deliberately puts the corner half a pixel before the origin (so pixel *centers* land on DGED posts), which sat exactly on that tolerance boundary and failed every correctly generated tile. Now compares the pixel center instead, with a tiny fractional-pixel tolerance, in both the GEO and UTM branches. (2) "Unreplaced `{{placeholder}}`" (check E) was a bare `"{{"` substring search that matched the DGED template's own header comment ("Placeholders (`{{...}}`) are replaced per tile...") on every tile, regardless of whether the real `{{KEY}}` placeholders had been substituted. Now matches real placeholder syntax only. Report-only fixes — no changes to the converters or to what gets written to disk. |
| v0.30 (2026-07-16) | **Fixed a validator false positive in the file-pairing check (A).** `TABLE_OF_CONTENTS.xml` and `<product>_COLLECTION.xml` are delivery-level metadata written once per product (spec 12.1 / 6.6), not per-tile sidecars, so they never had a matching `.tif` — `dem2dged_validate.py` didn't know that and flagged both as "missing .tif" on every delivery that included them, even though the tiles themselves were correctly paired. The check now recognises both by the same name test `write_toc_file()` already uses, so the two can't drift out of sync. Report-only fix — no changes to the converters or to what gets written to disk. |
| v0.29 (2026-07-15) | **QUICKSTART.html brought up to date.** It had missed the v0.27/v0.28 feature set: now documents `--org` / `--abs-hacc` / `--abs-vacc` / `--lineage`, the GUI's Source vertical field, the level-aware `Int16` (levels 0-2) / `Float32` (level 3+) data types, the level 0-3 short filename form, and automatic in-process validation (the walkthrough still described validation as a separate manual step, which stopped being true back in v0.19). Also fixed a stale "v0.15" label, an incorrect GPL-3.0 license mention (project is GPL-2.0-or-later), and hardcoded Windows paths in the walkthrough steps. No functional code changes. |
| v0.28 (2026-07-15) | **Brings the GUI, validator, and unified CLI back in sync with v0.27.** v0.27 (below) fixed `dem2dged_geo.py` / `dem2dged_utm.py` but never actually updated `dem2dged_gui.py` despite that release's changelog saying it did, so the GUI's independent copy of the conversion logic quietly stayed out of spec. This release: (1) `dem2dged_gui.py` now calls `dem2dged_lib`'s shared tile-extent, data-type, naming, and sidecar functions instead of its own copy — fixes a half-post pixel misregistration (every GUI-produced elevation sample was offset half a post spacing off the DGED grid), `Float32` forced on every level (0-2 must be `Int16`), a stale filename form for levels 0-3, and XML sidecars with 12 of 17 fields left as literal unreplaced text; the GUI also gained a working Source Vertical field for real EGM2008 transforms. (2) `DGED_UTM_TEMPLATE.xml` was truncated (not well-formed XML) — every UTM tile's sidecar was invalid; rebuilt from the GEO template. (3) The validator's data-type check is now level-aware, its filename patterns accept the current level 0-3 naming, and its hand-copied fallback DGED tables (already drifted) were removed. (4) `dem2dged.py` gained `--org` / `--abs-hacc` / `--abs-vacc` / `--lineage`. (5) Fixed a malformed CRS reference URI in every sidecar's `{{EPSG}}` field. |
| v0.27 (2026-07-14) | **DGED spec-compliance pass** (DGIWG 250 Ed. 1.2.1 audit) for `dem2dged_geo.py` / `dem2dged_utm.py`: (1) half-post pixel registration fix — the warp extent is now expanded by half a post spacing on every side so sampled values land exactly on DGED predefined post locations (spec 6.3), instead of being shifted half a post off-grid. (2) Levels 0-2 are now encoded as signed 16-bit integers as mandated by spec section 7 (was `Float32` for every level). (3) Metadata sidecars gained the mandatory Annex B elements: geographic bounding box, vertical extent, lineage, absolute horizontal/vertical accuracy quality reports, completeness, and conformity. (4) Security classification is now written into the metadata (was hardcoded `unclassified`). (5) GEO levels 8-9 now use the 1.5-minute tile instead of the 1-minute tile, which gave a non-integer number of longitude intervals (breaking post alignment) in two latitude zones. (6) A `TABLE_OF_CONTENTS.xml` and collection-level metadata are now written with every delivery. (7) Levels 0-3 filenames follow the spec's short example form (no tile-size letter); an optional `-org` producer code can be embedded in any filename. |
| v0.26 (2026-07-14) | **GUI window-layout fix.** The Convert / Stop buttons and progress bar are pinned to the bottom of the window so they're always visible, the rest of the form scrolls (mouse-wheel supported), and the window opens no larger than the screen work area. |
| v0.25 (2026-07-14) | **Bug-fix pass.** GUI now shows a completion dialog and surfaces stopped/error runs instead of silently dropping them; GUI extent reprojection uses all four corners (fixes possible edge-tile under-coverage on oblique transforms). |
| v0.24 (2026-07-14) | **Auto-resolution detection + detailed validation table.** (1) The GUI now detects the source DEM's ground sample distance as soon as a file is added, shows it next to the file list, and auto-selects the closest matching product level (log-scale nearest match, mode-aware for GEO/UTM); manually picking a level noticeably finer than the source now shows an on-screen warning instead of silently producing interpolated output. (2) The HTML validation report gains a "Detailed Per-Tile Results" table — one row per tile with a PASS/WARN/FAIL badge for each DGED criterion (Filename, GSD, Bounds, NoData, CRS/Vertical, Data Type, Metadata) plus an Overall column, sitting alongside the existing per-finding explanations. |
| v0.23 (2026-07-13) | **Packaging & startup robustness.** Fixed PyInstaller path resolution so the frozen `.exe` finds its bundled GDAL/PROJ data and XML templates correctly; improved console/debug output on startup; added broader error handling and GDAL diagnostics to help diagnose environment issues. |
| v0.22 (2026-07-13) | **Quality & robustness overhaul.** (1) Added pytest unit tests (5–10 cases) covering GEO/UTM conversion, validator checks, error handling, and edge cases. (2) Consolidated duplicated tables (ZONE_LON_SPACING, GEO_LEVELS, UTM_LEVELS) into `dem2dged_lib.py` — single source of truth, imported by `dem2dged_gui.py` and `dem2dged_validate.py`. (3) Added Python 3.10+ type hints to all function signatures across all modules (str, int, float, List, Dict, Optional, etc.) for self-documenting code and mypy static checking. (4) Replaced bare `print()` statements with Python `logging` module for structured output; added `--quiet` and `--debug` CLI flags to control verbosity. (5) Fixed Svalbard/Norway UTM auto-detect issue (74-81°N) — now emits explicit WARN when auto-detecting high-latitude regions; added lookup table for known problem areas. (6) Added comprehensive "Troubleshooting" section to README covering GDAL_DATA/PROJ_LIB errors, version mismatches, geoid grid failures, border tiles, interrupted runs, memory issues, and UTM zone ambiguities. |
| v0.20 (2026-07-13) | **Accuracy: resolution-aware resampling + real vertical-datum transform.** (1) Resampling is no longer hardcoded to bilinear. A new `auto` mode (default) picks the resampler from the source→target GSD ratio: `average` when downsampling (a mean, so it never overshoots the source min/max — safer than bilinear's nearest-2×2 and no cubic "ringing", staying within the validator's 10 m tolerance) and `bilinear` when up-sampling or near-equal. Override with `--resample` (CLI) / `-resample` (geo/utm). (2) New `--source-vertical` / `-source_vertical EPSG` (e.g. 5773=EGM96): when the source vertical datum differs from EGM2008, `gdalwarp` now applies a **real geoid shift** to EGM2008 (needs PROJ vertical grids) instead of only re-tagging the `+3855` label. When omitted, behaviour is unchanged (heights assumed EGM2008) but the tool now prints an explicit WARNING so mislabeled heights aren't silent. Applied consistently across `dem2dged_geo.py`, `dem2dged_utm.py`, the `dem2dged.py` dispatcher, and the GUI (`dem2dged_gui.py`, auto-resampler + warning; pass `source_vertical=` to `convert_geo`/`convert_utm` for the real transform). Added `source_gsd_meters()` and `pick_resampler()` to `dem2dged_lib.py`; `fix_header()` now accepts `None` to set only AREA_OR_POINT=Point without overwriting a warp-produced compound CRS. |
| v0.19 (2026-07-13) | **Automatic validation.** `dem2dged.py` and `dem2dged_gui.py` now run `dem2dged_validate.py` automatically right after conversion (in-process import, so it also works from the compiled `.exe` once rebuilt) and write a styled `DGED_Validation_Report.html` (+ `.txt`) into the output folder — no separate manual validator run needed. Disable with `--no-validate` (CLI) or the GUI checkbox. Added a reusable `dem2dged_validate.run_validation()` function and a new `-html-report FILE` flag for manual runs, plus a combined multi-dataset HTML report (one card per file) for GUI batch conversions, styled to match the existing badge/pill/card report format used for manual reviews. |
| v0.18 (2026-07-10) | **Fixed critical elevation-accuracy bug**: `dem2dged_geo.py`, `dem2dged_utm.py`, and `dem2dged_gui.py` all used cubic resampling in gdalwarp, which overshoots/undershoots ("rings") past the source's true min/max near steep elevation discontinuities — validated on sample data with a 21-53 m min/max error against the source, failing the validator's 10 m tolerance. Switched default resampling to bilinear, which does not overshoot; re-validated with 0 min/max error. Also: `dem2dged_validate.py` was missing its `main()`/CLI entry point and had a truncated `check_source()` function — running it did nothing (silent no-op, exit code 0). Completed the sample-window diff logic and added the missing CLI (`-src`, `-report`, `-max-diff`, `-verbose`) and file-pairing (A) check, so the validator now actually runs and produces a report. |
| v0.17 (2026-07-10) | Added `build_validate_exe.bat` / `rebuild_validate_exe.bat` / `dem2dged_validate.spec` — `dem2dged_validate.py` can now be packaged into a standalone `dem2dged_validate.exe` (console tool) the same way `dem2dged.exe` is built, so tile validation works on machines without Python/GDAL installed |
| v0.16 (2026-07-10) | `dem2dged_validate.py`: fixed the "G. Edge overlap" check — it only ever compared the shared **column** between east-west neighbours; the shared **row** between north-south neighbours (documented and reported as checked) was never actually compared. Both are now checked. Also: a missing GDAL/numpy install now prints a clear "activate `conda activate DGED`" message instead of a raw `ModuleNotFoundError` traceback. |
| v0.15 (2026-07-08) | **New: `dem2dged_validate.py`** — automated DGED validator (pairing, naming↔georeferencing cross-check, header/grid/XML compliance, NoData integrity, adjacent-tile edge-overlap identity, source coverage + statistics + sample-window diff); exit code usable in pipelines |
| v0.14 (2026-07-08) | QUICKSTART.html rewritten: GUI-first walkthrough (exe / dem2dged_gui.py, six-click guide, `_dged_output` subfolder naming), updated troubleshooting (osgeo build error, UTM level restriction), stale gdal_edit.py advice removed |
| v0.13 (2026-07-08) | Build scripts use `python -m PyInstaller` so the build always runs in the active conda env (a bare `pyinstaller` could silently resolve to a different Python install on PATH); stale exe deleted before build and real exit code checked, so "SUCCESS" is never reported for a failed build |
| v0.12 (2026-07-08) | Build scripts now verify GDAL (osgeo) is present in the build environment before running PyInstaller — prevents exes that fail with "No module named 'osgeo'" |
| v0.12 (2026-07-08) | `dem2dged.spec` auto-detects GDAL/PROJ data paths (previously hardcoded to `C:\ProgramData\anaconda3`) so `rebuild_exe.bat` works from any conda env |
| v0.11 (2026-07-08) | GUI per-file output subfolder is now named `<input name>_dged_output` |
