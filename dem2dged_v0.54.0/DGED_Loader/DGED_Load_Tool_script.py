# -*- coding: utf-8 -*-
"""
DGED_Load_Tool_script.py  -  Script source for a native ArcGIS Pro .atbx
script tool that loads DEM2DGED tile output into the current map.

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON

Version: 0.54.0

This is the flat-script twin of DGED_Loader.pyt, written for ArcGIS Pro's
"New Script" wizard (Insert > Toolbox > New > Script), which builds a real
.atbx container around whatever .py file you point it to and asks you to
define parameters by hand in its own dialog rather than in code. See
ATBX_WIZARD_GUIDE.md in this folder for the exact parameter table to enter
and the six GetParameterAsText/GetParameter calls below for how each row
maps to arcpy's parameter index.

Same behaviour as DGED_Loader.pyt: walks a main folder and/or hand-picked
    subfolders, finds every DGEDL*-named tile, and adds them to the active map --
optionally grouped into one layer group -- with no mosaic dataset and no
Standard/Advanced license required.

Parameter indices this script expects (see ATBX_WIZARD_GUIDE.md):
    0  Main DGED Folder                     (Folder, optional)
    1  Specific Subfolders                  (Folder, optional, multivalue)
    2  Search All Nested Subfolders         (Boolean, optional, default True)
    3  Group Loaded Tiles Into a Layer Group (Boolean, optional, default True)
    4  Group Layer Name                     (String, optional, default "DGED Tiles")
    5  Build Pyramids After Loading         (Boolean, optional, default False)

Requires: ArcGIS Pro 3.x (built/tested against 3.7). No extensions and no
Standard/Advanced license required -- only base ArcGIS Pro.
"""

import arcpy
import os

DGED_TILE_PREFIX = "DGEDL"


def _parse_multivalue_text(text):
    """Parse the semicolon-delimited, optionally single-quoted text that
    GetParameterAsText() returns for a multivalue parameter (e.g.
    "'C:\\a\\b';'C:\\a\\c'") into a clean list of path strings.
    """
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

    The filter deliberately excludes a source DEM and terrain-QA artefacts
    such as ``elevation_diff.tif`` / ``error_mask.tif`` that can sit beside
    the DGED delivery.  Walk all nested subfolders if ``recursive`` is True;
    otherwise only inspect files directly inside ``folder``.
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


def main():
    main_folder = arcpy.GetParameterAsText(0)
    subfolder_list = _parse_multivalue_text(arcpy.GetParameterAsText(1))

    recursive_text = arcpy.GetParameterAsText(2)
    recursive = True if recursive_text == "" else recursive_text.lower() == "true"

    group_layers_text = arcpy.GetParameterAsText(3)
    group_layers = True if group_layers_text == "" else group_layers_text.lower() == "true"

    group_name = arcpy.GetParameterAsText(4) or "DGED Tiles"

    build_pyramids_text = arcpy.GetParameterAsText(5)
    build_pyramids = False if build_pyramids_text == "" else build_pyramids_text.lower() == "true"

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

    # De-duplicate tiles (a hand-picked subfolder may already sit inside
    # the main folder, or two picked folders may overlap).
    tif_paths = sorted(set(os.path.normpath(p) for p in tif_paths))

    if not tif_paths:
        arcpy.AddWarning("No DGEDL*.tif tile files found under the selected folder(s).")
        return

    arcpy.AddMessage("Found {0} raster tile(s) total.".format(len(tif_paths)))

    missing_xml = [p for p in tif_paths
                   if not os.path.isfile(os.path.splitext(p)[0] + ".xml")]
    if missing_xml:
        arcpy.AddWarning(
            "{0} tile(s) have no matching .xml sidecar (loading "
            "anyway):".format(len(missing_xml)))
        for p in missing_xml[:10]:
            arcpy.AddWarning("  " + os.path.basename(p))
        if len(missing_xml) > 10:
            arcpy.AddWarning("  ... and {0} more".format(len(missing_xml) - 10))

    aprx = arcpy.mp.ArcGISProject("CURRENT")
    m = aprx.activeMap
    if m is None:
        arcpy.AddError("No active map. Open a map view in ArcGIS Pro and "
                        "run this tool again.")
        return

    target_group = None
    if group_layers:
        try:
            target_group = m.createGroupLayer(group_name)
        except Exception as e:
            arcpy.AddWarning(
                "Could not create group layer '{0}' ({1}); loading tiles "
                "at the top level of the map instead.".format(group_name, e))
            target_group = None

    arcpy.SetProgressor("step", "Loading DGED tiles...", 0, len(tif_paths), 1)

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
                    arcpy.AddWarning("Pyramids failed for {0}: {1}".format(
                        os.path.basename(tif), e))
            loaded += 1
        except Exception as e:
            failed.append((tif, str(e)))
            arcpy.AddWarning("Failed to load {0}: {1}".format(
                os.path.basename(tif), e))
        arcpy.SetProgressorPosition(i + 1)

    arcpy.ResetProgressor()

    arcpy.AddMessage("Loaded {0} of {1} tile(s).".format(loaded, len(tif_paths)))
    if failed:
        arcpy.AddWarning("{0} tile(s) failed to load (see warnings above).".format(
            len(failed)))


if __name__ == "__main__":
    main()
