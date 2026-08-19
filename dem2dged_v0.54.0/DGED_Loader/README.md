# DGED Loader v0.54.0

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

Integrated with the DEM2DGED v0.54.0 source release. It loads only
`DGEDL*` delivery tiles, so source DEMs and terrain-QA rasters such as
`validation/elevation_diff.tif` and `validation/error_mask.tif` are not
mistaken for DGED tiles.

An ArcGIS Pro tool that loads the tile output of DEM2DGED into the current
map in one run -- no mosaic dataset, no Standard/Advanced license required.

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
| `DGED_Loader.pyt` | The tool itself -- an ArcGIS Pro Python Toolbox. Add it and run it, nothing else needed. |
| `DGED_Load_Tool_script.py` | Same logic, written for ArcGIS Pro's Script Tool wizard -- use this only if you specifically need a native `.atbx` container (see below). |
| `ATBX_WIZARD_GUIDE.md` | Step-by-step guide (~2 minutes) to build a native `.atbx` from `DGED_Load_Tool_script.py`. |
| `build_and_package.py` | Zips this folder into `DGED_Loader_v0.54.0.zip` for backup or sharing. |
| `VERSION.txt` | Version history. |

## Quick start

1. In ArcGIS Pro, open the **Catalog** pane.
2. Browse to this folder and double-click `DGED_Loader.pyt` (or drag it
   onto the **Toolboxes** node) to add it to your project.
3. Open a map view -- the tool adds layers to the active map of the
   **current** project, so a map must already be open.
4. Expand the toolbox, double-click **Load DGED Tiles**, fill in the
   parameters below, and click **Run**.

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

ArcGIS Pro 3.x, built and tested against 3.7. No extensions, no
Standard/Advanced license -- base ArcGIS Pro only.

## License

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON
