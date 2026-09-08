# -*- coding: utf-8 -*-
"""
DGED_Loader.pyt  -  ArcGIS Pro Python Toolbox: load DEM2DGED tile output into the current map.

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON

Version: 0.59.0
Purpose:
    DEM2DGED splits one DEM into many DGED tiles (*.tif + *.xml sidecar per
    tile), written into one output subfolder per source DEM. Loading dozens
    or hundreds of tiles into ArcGIS Pro one at a time -- or building a
    mosaic dataset with Add Rasters To Mosaic Dataset -- is either tedious
    or requires a Standard/Advanced license (mosaic dataset tools are not
    available under a Basic license). This tool instead walks one main
    folder and/or any number of hand-picked subfolders, finds DGEDL*-named
    tile files, and adds them straight into the active map -- optionally grouped
    into a single layer group -- with no mosaic dataset and no extra
    license required.

Usage (inside ArcGIS Pro):
    1. Add this .pyt as a toolbox: Catalog pane > right-click a folder
       connection > Refresh (if needed), then browse to this file and
       double-click it, or drag it into the Toolboxes node.
    2. Open a map view -- the tool adds layers to the CURRENT project's
       active map, so a map must already be open.
    3. Expand the toolbox, double-click "Load DGED Tiles", set the Main
       DGED Folder and/or Specific Subfolders, and run.

The toolbox also includes "Show DGED Differences". That tool loads the
converter-generated validation/elevation_diff.tif (DGED minus source),
validation/error_mask.tif, the original source when it can be recovered,
and the delivery tiles into one clearly labelled comparison group.

Requires: ArcGIS Pro 3.x. No extensions and no Standard/Advanced license
required -- only base ArcGIS Pro.
"""

import arcpy
import json
import os

DGED_TILE_PREFIX = "DGEDL"


def _read_json(path):
    """Return a JSON object from ``path`` or an empty dictionary."""
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _comparison_files(selected_folder):
    """Resolve exactly one DEM2DGED terrain-QA folder.

    ``selected_folder`` may be a delivery folder, its ``validation`` folder,
    or a parent containing one delivery. A parent containing multiple QA
    result sets is rejected so the map never silently mixes unrelated source
    DEMs and DGED outputs.
    """
    if not selected_folder or not os.path.isdir(selected_folder):
        raise ValueError("The selected DGED output folder does not exist.")

    selected_folder = os.path.normpath(selected_folder)
    candidates = []

    def register(folder):
        diff = os.path.join(folder, "elevation_diff.tif")
        if os.path.isfile(diff):
            candidates.append(os.path.normpath(folder))

    register(selected_folder)
    register(os.path.join(selected_folder, "validation"))

    if not candidates:
        for root, dirs, _files in os.walk(selected_folder):
            dirs[:] = sorted(d for d in dirs if d not in {
                "__pycache__", ".pytest_cache"})
            if os.path.basename(root).lower() == "validation":
                register(root)

    candidates = sorted(set(candidates))
    if not candidates:
        raise ValueError(
            "No validation/elevation_diff.tif was found. Run DEM2DGED "
            "validation with Basic or Full terrain QA, then run this tool "
            "again.")
    if len(candidates) > 1:
        raise ValueError(
            "The selected folder contains {0} comparison result sets. "
            "Select one individual *_dged_output folder, not their parent."
            .format(len(candidates)))

    qa_folder = candidates[0]
    if os.path.basename(qa_folder).lower() == "validation":
        delivery_folder = os.path.dirname(qa_folder)
    else:
        delivery_folder = selected_folder

    return {
        "delivery_folder": delivery_folder,
        "qa_folder": qa_folder,
        "difference": os.path.join(qa_folder, "elevation_diff.tif"),
        "error_mask": os.path.join(qa_folder, "error_mask.tif"),
        "terrain_metrics": os.path.join(qa_folder, "terrain_metrics.json"),
        "manifest": os.path.join(
            delivery_folder, "DEM2DGED_Conversion_Manifest.json"),
    }


def _recover_source_path(explicit_source, files):
    """Resolve the original DEM from input, manifest, or terrain metrics."""
    if explicit_source:
        return os.path.normpath(explicit_source), "selected parameter"

    manifest = _read_json(files["manifest"])
    source = manifest.get("source", {})
    if isinstance(source, dict) and source.get("path"):
        return os.path.normpath(str(source["path"])), "conversion manifest"

    metrics = _read_json(files["terrain_metrics"])
    if metrics.get("source"):
        return os.path.normpath(str(metrics["source"])), "terrain metrics"
    return None, None


def _metric_text(metrics):
    """Return a concise, stable terrain-QA metrics message."""
    values = metrics.get("metrics", {}) if isinstance(metrics, dict) else {}
    if not isinstance(values, dict) or not values.get("count"):
        return None

    def fmt(name):
        value = values.get(name)
        return "n/a" if value is None else "{0:.3f} m".format(float(value))

    return (
        "Valid cells: {0:,}; bias: {1}; MAE: {2}; RMSE: {3}; "
        "P95 |difference|: {4}; maximum |difference|: {5}."
        .format(int(values["count"]), fmt("bias"), fmt("mae"),
                fmt("rmse"), fmt("p95"), fmt("max")))


def _add_layer(active_map, path, group_layer=None, name=None,
               visible=None, transparency=None):
    """Add one raster and apply non-critical display properties safely."""
    layer = active_map.addDataFromPath(path)
    if layer is None:
        raise RuntimeError("ArcGIS Pro did not return a layer for {0}".format(path))
    if name:
        try:
            layer.name = name
        except Exception:
            pass
    if visible is not None:
        try:
            layer.visible = bool(visible)
        except Exception:
            pass
    if transparency is not None:
        try:
            layer.transparency = int(transparency)
        except Exception:
            pass
    if group_layer is not None:
        active_map.addLayerToGroup(group_layer, layer, "TOP")
        active_map.removeLayer(layer)
    return layer


def _style_error_mask(layer, threshold):
    """Best-effort red symbol for the value-1 exceedance mask."""
    try:
        symbology = layer.symbology
        symbology.updateColorizer("RasterUniqueValueColorizer")
        colorizer = symbology.colorizer
        colorizer.field = "Value"
        colorizer.addAllValues()
        for group in colorizer.groups:
            for item in group.items:
                raw_values = getattr(item, "values", [])
                flat = [str(v) for row in raw_values for v in
                        (row if isinstance(row, (list, tuple)) else [row])]
                if "1" in flat or "1.0" in flat:
                    item.color = {"RGB": [255, 0, 0, 100]}
                    item.label = "|DGED - source| > {0:g} m".format(threshold)
        layer.symbology = symbology
    except Exception as exc:
        arcpy.AddWarning(
            "The exceedance mask was loaded, but automatic red symbology "
            "could not be applied: {0}".format(exc))


def _multivalue_to_list(parameter):
    """Return a clean list of individual path strings from an arcpy
    multivalue Parameter (e.g. a multi-select Folder parameter).

    arcpy exposes multivalue parameters two ways depending on version and
    context: parameter.value is sometimes directly iterable (one item per
    selected value), and sometimes only parameter.valueAsText is reliable,
    as a semicolon-delimited string with each entry optionally wrapped in
    single quotes (e.g. "'C:\\a\\b';'C:\\a\\c'"). This tries the iterable
    form first and falls back to parsing valueAsText, so it works either
    way instead of assuming one specific arcpy behaviour.
    """
    if parameter.value is not None:
        try:
            items = [str(v).strip() for v in parameter.value if str(v).strip()]
            if items:
                return items
        except TypeError:
            pass

    text = parameter.valueAsText
    if not text:
        return []

    items = []
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if len(chunk) >= 2 and chunk[0] == "'" and chunk[-1] == "'":
            chunk = chunk[1:-1]
        if chunk:
            items.append(chunk)
    return items


def _find_tiles(folder, recursive):
    """Return DGEDL*-named TIFF paths under ``folder``.

    DGED terrain-QA artefacts (``elevation_diff.tif`` and ``error_mask.tif``)
    and an original source DEM are commonly present beside delivered tiles.
    Restricting the loader to the converter's DGEDL naming convention prevents
    those diagnostic/source rasters from being accidentally loaded as tiles.
    Walk all nested subfolders if ``recursive`` is True; otherwise only inspect
    files directly inside ``folder``.
    """
    found = []
    if not folder or not os.path.isdir(folder):
        return found

    if recursive:
        for root, _dirs, files in os.walk(folder):
            for fn in files:
                if (fn.upper().startswith(DGED_TILE_PREFIX)
                        and fn.lower().endswith((".tif", ".tiff"))):
                    found.append(os.path.join(root, fn))
    else:
        for fn in os.listdir(folder):
            fp = os.path.join(folder, fn)
            if (os.path.isfile(fp) and fn.upper().startswith(DGED_TILE_PREFIX)
                    and fn.lower().endswith((".tif", ".tiff"))):
                found.append(fp)

    return found


class Toolbox(object):
    def __init__(self):
        self.label = "DGED Loader"
        self.alias = "dgedloader"
        self.tools = [LoadDGEDTiles, ShowDGEDDifferences]


class LoadDGEDTiles(object):
    def __init__(self):
        self.label = "Load DGED Tiles"
        self.description = (
            "Recursively finds every DGEDL*-named tile under a main DEM2DGED "
            "output folder and/or hand-picked subfolders, and adds them "
            "all to the active map -- no mosaic dataset, no Standard/"
            "Advanced license required."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        main_folder = arcpy.Parameter(
            displayName="Main DGED Folder",
            name="main_folder",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input")

        subfolders = arcpy.Parameter(
            displayName="Specific Subfolders (optional, multiple allowed)",
            name="subfolders",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input",
            multiValue=True)

        recursive = arcpy.Parameter(
            displayName="Search All Nested Subfolders",
            name="recursive",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        recursive.value = True

        group_layers = arcpy.Parameter(
            displayName="Group Loaded Tiles Into a Layer Group",
            name="group_layers",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        group_layers.value = True

        group_name = arcpy.Parameter(
            displayName="Group Layer Name",
            name="group_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        group_name.value = "DGED Tiles"

        build_pyramids = arcpy.Parameter(
            displayName="Build Pyramids After Loading",
            name="build_pyramids",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        build_pyramids.value = False

        return [main_folder, subfolders, recursive, group_layers,
                group_name, build_pyramids]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        # Group Layer Name only matters if grouping is switched on.
        parameters[4].enabled = bool(parameters[3].value)
        return

    def updateMessages(self, parameters):
        if not parameters[0].valueAsText and not parameters[1].valueAsText:
            parameters[0].setErrorMessage(
                "Provide a Main DGED Folder and/or one or more Specific "
                "Subfolders.")
        return

    def execute(self, parameters, messages):
        main_folder = parameters[0].valueAsText
        subfolder_list = _multivalue_to_list(parameters[1])
        recursive = bool(parameters[2].value)
        group_layers = bool(parameters[3].value)
        group_name = parameters[4].valueAsText or "DGED Tiles"
        build_pyramids = bool(parameters[5].value)

        folders = []
        if main_folder:
            folders.append(main_folder)
        folders.extend(subfolder_list)

        # De-duplicate while preserving the order the folders were given in.
        seen = set()
        unique_folders = []
        for f in folders:
            norm = os.path.normpath(f)
            if norm not in seen:
                seen.add(norm)
                unique_folders.append(norm)

        if not unique_folders:
            arcpy.AddError("No folders provided. Set a Main DGED Folder "
                            "and/or one or more Specific Subfolders.")
            return

        arcpy.AddMessage("Scanning {0} folder(s) ({1})...".format(
            len(unique_folders),
            "recursive" if recursive else "top level only"))

        tif_paths = []
        for folder in unique_folders:
            found = _find_tiles(folder, recursive)
            arcpy.AddMessage("  {0}: {1} tile(s)".format(folder, len(found)))
            tif_paths.extend(found)

        # De-duplicate tiles (a hand-picked subfolder may already sit
        # inside the main folder, or two picked folders may overlap).
        tif_paths = sorted(set(os.path.normpath(p) for p in tif_paths))

        if not tif_paths:
            arcpy.AddWarning("No DGEDL*.tif tile files found under the selected "
                              "folder(s).")
            return

        arcpy.AddMessage("Found {0} raster tile(s) total.".format(
            len(tif_paths)))

        missing_xml = [p for p in tif_paths
                       if not os.path.isfile(os.path.splitext(p)[0] + ".xml")]
        if missing_xml:
            arcpy.AddWarning(
                "{0} tile(s) have no matching .xml sidecar (loading "
                "anyway):".format(len(missing_xml)))
            for p in missing_xml[:10]:
                arcpy.AddWarning("  " + os.path.basename(p))
            if len(missing_xml) > 10:
                arcpy.AddWarning("  ... and {0} more".format(
                    len(missing_xml) - 10))

        aprx = arcpy.mp.ArcGISProject("CURRENT")
        m = aprx.activeMap
        if m is None:
            arcpy.AddError("No active map. Open a map view in ArcGIS Pro "
                            "and run this tool again.")
            return

        target_group = None
        if group_layers:
            try:
                target_group = m.createGroupLayer(group_name)
            except Exception as e:
                arcpy.AddWarning(
                    "Could not create group layer '{0}' ({1}); loading "
                    "tiles at the top level of the map instead.".format(
                        group_name, e))
                target_group = None

        arcpy.SetProgressor("step", "Loading DGED tiles...",
                             0, len(tif_paths), 1)

        loaded = 0
        failed = []
        for i, tif in enumerate(tif_paths):
            arcpy.SetProgressorLabel("Loading {0} ({1}/{2})".format(
                os.path.basename(tif), i + 1, len(tif_paths)))
            try:
                lyr = m.addDataFromPath(tif)
                if target_group is not None and lyr is not None:
                    m.addLayerToGroup(target_group, lyr, "BOTTOM")
                    m.removeLayer(lyr)
                if build_pyramids:
                    try:
                        arcpy.management.BuildPyramids(tif)
                    except Exception as e:
                        arcpy.AddWarning(
                            "Pyramids failed for {0}: {1}".format(
                                os.path.basename(tif), e))
                loaded += 1
            except Exception as e:
                failed.append((tif, str(e)))
                arcpy.AddWarning("Failed to load {0}: {1}".format(
                    os.path.basename(tif), e))
            arcpy.SetProgressorPosition(i + 1)

        arcpy.ResetProgressor()

        arcpy.AddMessage("Loaded {0} of {1} tile(s).".format(
            loaded, len(tif_paths)))
        if failed:
            arcpy.AddWarning(
                "{0} tile(s) failed to load (see warnings above).".format(
                    len(failed)))

    def postExecute(self, parameters):
        return


class ShowDGEDDifferences(object):
    def __init__(self):
        self.label = "Show DGED Differences"
        self.description = (
            "Loads DEM2DGED's signed elevation-difference raster (DGED "
            "minus source), threshold-exceedance mask, original source DEM, "
            "and DGEDL* delivery tiles into one comparison group. It uses "
            "the converter-generated QA rasters, so it does not introduce "
            "a second alignment or resampling operation."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        output_folder = arcpy.Parameter(
            displayName="DGED Output Folder",
            name="dged_output_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input")

        source_raster = arcpy.Parameter(
            displayName="Original Source DEM (optional override)",
            name="source_raster",
            datatype="DERasterDataset",
            parameterType="Optional",
            direction="Input")

        load_tiles = arcpy.Parameter(
            displayName="Load DGED Delivery Tiles",
            name="load_tiles",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        load_tiles.value = True

        show_mask = arcpy.Parameter(
            displayName="Show Threshold Exceedance Mask",
            name="show_error_mask",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        show_mask.value = True

        group_name = arcpy.Parameter(
            displayName="Comparison Group Name",
            name="group_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        group_name.value = "DGED vs Source Comparison"

        return [output_folder, source_raster, load_tiles, show_mask,
                group_name]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        folder = parameters[0].valueAsText
        if folder and not os.path.isdir(folder):
            parameters[0].setErrorMessage(
                "The selected DGED output folder does not exist.")
        source = parameters[1].valueAsText
        if source and not os.path.isfile(source):
            parameters[1].setErrorMessage(
                "The selected original source DEM does not exist.")
        return

    def execute(self, parameters, messages):
        selected_folder = parameters[0].valueAsText
        explicit_source = parameters[1].valueAsText
        load_tiles = bool(parameters[2].value)
        show_mask = bool(parameters[3].value)
        group_name = (parameters[4].valueAsText or
                      "DGED vs Source Comparison")

        try:
            files = _comparison_files(selected_folder)
        except ValueError as exc:
            arcpy.AddError(str(exc))
            return

        if explicit_source and not os.path.isfile(explicit_source):
            arcpy.AddError(
                "Original source DEM not found: {0}".format(explicit_source))
            return

        source_path, source_origin = _recover_source_path(
            explicit_source, files)

        aprx = arcpy.mp.ArcGISProject("CURRENT")
        active_map = aprx.activeMap
        if active_map is None:
            arcpy.AddError(
                "No active map. Open a map view in ArcGIS Pro and run this "
                "tool again.")
            return

        comparison_group = None
        try:
            comparison_group = active_map.createGroupLayer(group_name)
        except Exception as exc:
            arcpy.AddWarning(
                "Could not create comparison group '{0}' ({1}); layers will "
                "be added at the top level.".format(group_name, exc))

        loaded = []

        if source_path:
            if os.path.isfile(source_path):
                try:
                    _add_layer(
                        active_map, source_path, comparison_group,
                        "1 - Original source DEM", visible=False)
                    loaded.append("original source DEM")
                    arcpy.AddMessage(
                        "Original source recovered from {0}: {1}".format(
                            source_origin, source_path))
                except Exception as exc:
                    arcpy.AddWarning(
                        "Could not load the original source DEM: {0}".format(exc))
            else:
                arcpy.AddWarning(
                    "The {0} records an original source path that is no "
                    "longer available: {1}. Browse to it using the optional "
                    "Original Source DEM parameter if you want it in the map."
                    .format(source_origin, source_path))
        else:
            arcpy.AddWarning(
                "No original source path was found in the conversion "
                "manifest or terrain metrics. The difference layers will "
                "still be loaded; select the source raster explicitly if "
                "you also want source-versus-DGED visual switching.")

        if load_tiles:
            tiles = _find_tiles(files["delivery_folder"], recursive=True)
            if not tiles:
                arcpy.AddWarning(
                    "No DGEDL*.tif delivery tiles were found in {0}."
                    .format(files["delivery_folder"]))
            else:
                arcpy.SetProgressor(
                    "step", "Loading DGED tiles for comparison...",
                    0, len(tiles), 1)
                tile_failures = 0
                for index, tile in enumerate(tiles):
                    arcpy.SetProgressorLabel(
                        "Loading {0} ({1}/{2})".format(
                            os.path.basename(tile), index + 1, len(tiles)))
                    try:
                        _add_layer(
                            active_map, tile, comparison_group,
                            "2 - DGED tile - {0}".format(
                                os.path.basename(tile)), visible=False)
                    except Exception as exc:
                        tile_failures += 1
                        arcpy.AddWarning(
                            "Could not load {0}: {1}".format(
                                os.path.basename(tile), exc))
                    arcpy.SetProgressorPosition(index + 1)
                arcpy.ResetProgressor()
                loaded.append("{0} DGED tile(s)".format(
                    len(tiles) - tile_failures))

        difference_layer = _add_layer(
            active_map, files["difference"], comparison_group,
            "3 - Elevation difference (DGED - source, metres)",
            visible=True)
        loaded.append("signed elevation difference")

        metrics = _read_json(files["terrain_metrics"])
        threshold = metrics.get("error_threshold_m", 10.0)
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = 10.0

        if os.path.isfile(files["error_mask"]):
            mask_layer = _add_layer(
                active_map, files["error_mask"], comparison_group,
                "4 - Difference above {0:g} m (red mask)".format(threshold),
                visible=show_mask, transparency=20)
            _style_error_mask(mask_layer, threshold)
            loaded.append("threshold exceedance mask")
        else:
            arcpy.AddWarning(
                "No error_mask.tif was found beside elevation_diff.tif. "
                "The signed difference layer was loaded without the mask.")

        arcpy.AddMessage("Loaded: {0}.".format(", ".join(loaded)))
        arcpy.AddMessage(
            "Difference meaning: positive values = DGED is higher than the "
            "source; negative values = DGED is lower than the source.")
        summary = _metric_text(metrics)
        if summary:
            arcpy.AddMessage(summary)
        arcpy.AddMessage(
            "These values measure source-to-output conversion fidelity. "
            "They do not prove absolute vertical accuracy without an "
            "independent reference dataset.")
        arcpy.AddMessage(
            "For a direct visual check, turn the difference layers off, "
            "turn the source and DGED layers on, select one raster layer, "
            "then use Raster Layer > Appearance > Swipe.")

        try:
            if comparison_group is not None:
                comparison_group.visible = True
        except Exception:
            pass
        try:
            difference_layer.visible = True
        except Exception:
            pass

    def postExecute(self, parameters):
        return
