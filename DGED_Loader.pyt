# -*- coding: utf-8 -*-
"""
DGED_Loader.pyt  -  ArcGIS Pro Python Toolbox: load DEM2DGED tile output into the current map.

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON

Version: 0.56.0

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

Requires: ArcGIS Pro 3.x (built/tested against 3.7). No extensions and no
Standard/Advanced license required -- only base ArcGIS Pro.
"""

import arcpy
import os

DGED_TILE_PREFIX = "DGEDL"


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
        self.tools = [LoadDGEDTiles]


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
