# DGED Loader and Comparison Tools v0.59.0

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

Integrated with the DEM2DGED v0.59.0 source release. The loader finds only
`DGEDL*` delivery tiles, so source DEMs and terrain-QA rasters such as
`validation/elevation_diff.tif` and `validation/error_mask.tif` are not
mistaken for DGED tiles.

The Python toolbox contains two ArcGIS Pro tools:

1. **Load DGED Tiles** loads a delivery into the current map in one run.
2. **Show DGED Differences** loads the original source, DGED tiles, signed
   elevation difference, and threshold-exceedance mask into one comparison
   group.

Neither tool creates a mosaic dataset or requires Spatial Analyst, Image
Analyst, Standard, or Advanced licensing.

## Why this exists

DEM2DGED splits one DEM into many DGED tiles: one `.tif` + `.xml` sidecar
pair per tile, written into an output subfolder per source DEM (the
`<input name>_dged_output` convention). A batch run over several DEMs
leaves you with a parent folder full of these subfolders, each holding
dozens to hundreds of tiles.

The normal way to bring that into ArcGIS Pro as one dataset is
**Add Rasters To Mosaic Dataset**, but that tool -- along with the rest of
the mosaic dataset toolset -- requires a **Standard or Advanced** license
and is unavailable under **Basic**. DGED Loader sidesteps mosaic datasets
entirely: it walks the folder(s) you point it at, finds every `.tif`
tile, and adds them straight into the active map as regular raster
layers (optionally grouped into one layer group). This only needs base
ArcGIS Pro -- no extension, no Standard/Advanced license.

## What's in this folder

| File | Purpose |
|---|---|
| `DGED_Loader.pyt` | The ready-to-run ArcGIS Pro Python Toolbox containing both tools. |
| `DGED_Load_Tool_script.py` | Same logic, written for ArcGIS Pro's Script Tool wizard -- use this only if you specifically need a native `.atbx` container (see below). |
| `ATBX_WIZARD_GUIDE.md` | Step-by-step guide (~2 minutes) to build a native `.atbx` from `DGED_Load_Tool_script.py`. |
| `arcgis_pro_smoke_test.py` | Licensed-runtime smoke test that writes a detailed log. |
| `build_and_package.py` | Zips this folder into `DGED_Loader_v0.59.0.zip` for backup or sharing. |
| `VERSION.txt` | Version history. |

> This file documents the ArcGIS Pro toolbox only. The project reference is
> `README.md` in the parent folder. In v0.58.0 this file was accidentally
> copied over that one; v0.58.1 restored it.

## Quick start

1. In ArcGIS Pro, open the **Catalog** pane.
2. Browse to this folder and double-click `DGED_Loader.pyt` (or drag it
   onto the **Toolboxes** node) to add it to your project.
3. Open a map view -- the tool adds layers to the active map of the
   **current** project, so a map must already be open.
4. Expand the toolbox and run either **Load DGED Tiles** or
   **Show DGED Differences**.

No script tool wizard, no parameter setup -- `DGED_Loader.pyt` is a
complete, ready-to-run toolbox as-is. It behaves identically to a
`.atbx` script tool in the Geoprocessing pane: same dialog, same
progress bar, same messages.

### Why not just hand you a `.atbx` file directly?

`.atbx` is a zipped, Esri-proprietary container with no published
schema -- Esri's own guidance is to build it inside ArcGIS Pro, not by
hand, and there's no way to test-open one outside Pro itself. Rather
than gamble on a hand-built file that might get flagged as corrupt,
`DGED_Loader.pyt` gives you the exact same tool with zero risk. If you
specifically need the `.atbx` format (for distribution, policy, etc.),
`ATBX_WIZARD_GUIDE.md` walks through generating a genuine one from
`DGED_Load_Tool_script.py` in about two minutes -- Pro builds the
container itself, so it's guaranteed valid.

## Parameter reference

### Load DGED Tiles

| Parameter | Type | Default | Notes |
|---|---|---|---|
| Main DGED Folder | Folder, optional | -- | The parent folder to search (e.g. the folder holding several `_dged_output` subfolders from a batch run). |
| Specific Subfolders | Folder, optional, multiple | -- | Pick one or more individual folders instead of, or in addition to, the main folder -- e.g. only some deliveries out of a larger batch. Ctrl+click to select several in the browse dialog. |
| Search All Nested Subfolders | Boolean | On | Applies to every folder above. On: walk every level below each folder. Off: only look directly inside each folder. |
| Group Loaded Tiles Into a Layer Group | Boolean | On | Adds all loaded tiles inside one collapsible group layer instead of scattering them across the top of the Contents pane. |
| Group Layer Name | String | `DGED Tiles` | Only used when grouping is on. |
| Build Pyramids After Loading | Boolean | Off | Optional. Runs Build Pyramids on each tile as it loads -- faster pan/zoom later, slower first load. Leave off for a quick load. |

At least one of **Main DGED Folder** / **Specific Subfolders** must be
set. Either one alone, or both together, is fine -- if a subfolder you
pick also sits inside the main folder, its tiles are only loaded once.

### Show DGED Differences

| Parameter | Type | Default | Notes |
|---|---|---|---|
| DGED Output Folder | Folder, required | -- | Select one individual `*_dged_output` folder, or its `validation` folder. A parent containing multiple deliveries is rejected to prevent mixing datasets. |
| Original Source DEM | Raster, optional | Auto | Overrides the source path stored in `DEM2DGED_Conversion_Manifest.json` or `terrain_metrics.json`. Use this if the source file was moved. |
| Load DGED Delivery Tiles | Boolean | On | Loads only `DGEDL*.tif` delivery tiles and initially hides them to keep the difference visible. |
| Show Threshold Exceedance Mask | Boolean | On | Displays `error_mask.tif` over the signed difference, with value 1 styled red when ArcGIS Pro permits the symbology update. |
| Comparison Group Name | String | `DGED vs Source Comparison` | Name of the group created in the active map. |

The comparison tool does not calculate a new raster. It loads the exact QA
artifacts created during DEM2DGED validation:

- `elevation_diff.tif` is **DGED output minus the source resampled onto the
  DGED grid**, in metres. Positive values mean DGED is higher; negative
  values mean DGED is lower.
- `error_mask.tif` marks cells whose absolute difference exceeds the terrain
  QA threshold stored in `terrain_metrics.json` (normally 10 m).

This is conversion-fidelity evidence, not independent absolute-accuracy
evidence. A large difference can identify alignment, resampling, or local
terrain-preservation problems, but independent control data is still needed
to prove absolute vertical accuracy.

For a direct source-versus-output visual check, turn the difference and mask
layers off, turn the source and DGED layers on, select a raster layer, then
use **Raster Layer > Appearance > Swipe**.

## What it does with the `.xml` sidecars

Nothing directly -- the sidecars are metadata, not rasters, so they're
never loaded as layers. The tool does check that each `.tif` has a
matching `.xml` and prints a warning (not an error) for any that don't,
since that usually means an interrupted conversion. `TABLE_OF_CONTENTS.xml`
and `<product>_COLLECTION.xml` (DEM2DGED's delivery-level metadata, not
per-tile sidecars) are correctly ignored -- they were never `.tif`
partners to begin with.

## Troubleshooting

**"No active map" error.** Open a map view in the project before running
the tool -- it adds layers to the *current* project's active map, so
there has to be one open.

**A tile fails to load.** The tool logs a warning per failed tile and
keeps going rather than stopping the whole run; check the message log
for the reason (commonly a corrupt or zero-byte `.tif` from an
interrupted DEM2DGED run -- see DEM2DGED's own README, "Interrupted
runs").

**Group layer doesn't appear.** If `createGroupLayer` isn't available in
your Pro version for some reason, the tool logs a warning and falls back
to loading tiles at the top level instead of stopping the run.

**Nothing loads / 0 tiles found.** Check "Search All Nested Subfolders"
-- if it's off and your tiles are one level deeper than the folder you
picked (e.g. you picked the batch parent instead of a `_dged_output`
subfolder), turn it on.

## Requirements

ArcGIS Pro 3.x. No extensions and no Standard/Advanced license -- base
ArcGIS Pro only. The Python logic is covered by an offline fake-ArcPy harness;
run `arcgis_pro_smoke_test.py` from an activated ArcGIS Pro Python environment
on the licensed workstation before operational use.

## License

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON
