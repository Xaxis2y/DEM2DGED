#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.61.0
"""
Offline verification harness for DGED_Loader.pyt.

There is no real ArcGIS Pro / arcpy in this sandbox, so this builds a
minimal fake `arcpy` module (Parameter, mp.ArcGISProject, a fake Map,
management.BuildPyramids, the AddMessage/AddWarning/AddError/progressor
functions) and loads DGED_Loader.pyt against it with importlib. This
cannot prove the real arcpy.mp calls behave identically inside ArcGIS Pro,
but it does exercise every branch of the tool's own logic: parameter
construction, multivalue parsing (both the iterable-value code path and
the valueAsText-fallback code path), recursive vs. non-recursive folder
walking, de-duplication of overlapping folders/tiles, the missing-sidecar
warning, the group-layer create/add/remove sequence, and the
no-folders-provided error path.

Run: python3 test_dged_loader.py
Exits 0 and prints "ALL TESTS PASSED" if everything checks out, else
prints the failure and exits 1.
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types

FAILURES = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f"  -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(f"{label}: {detail}")


# --------------------------------------------------------------------------
# Fake arcpy
# --------------------------------------------------------------------------

class FakeParameter:
    def __init__(self, displayName="", name="", datatype="", parameterType="Optional",
                 direction="Input", multiValue=False):
        self.displayName = displayName
        self.name = name
        self.datatype = datatype
        self.parameterType = parameterType
        self.direction = direction
        self.multiValue = multiValue
        self._value = None
        self._valueAsText = None
        self.enabled = True
        self.error = None
        self.warning = None

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v

    @property
    def valueAsText(self):
        if self._valueAsText is not None:
            return self._valueAsText
        if self._value is None:
            return None
        if isinstance(self._value, bool):
            return "true" if self._value else "false"
        if isinstance(self._value, (list, tuple)):
            return ";".join("'%s'" % v for v in self._value)
        return str(self._value)

    @valueAsText.setter
    def valueAsText(self, v):
        self._valueAsText = v

    def setErrorMessage(self, msg):
        self.error = msg

    def setWarningMessage(self, msg):
        self.warning = msg

    def clearMessage(self):
        self.error = None
        self.warning = None


class FakeColorItem:
    def __init__(self, value):
        self.values = [[value]]
        self.color = None
        self.label = str(value)


class FakeColorGroup:
    def __init__(self):
        self.items = [FakeColorItem(0), FakeColorItem(1)]


class FakeColorizer:
    def __init__(self):
        self.field = None
        self.groups = [FakeColorGroup()]

    def addAllValues(self):
        return


class FakeSymbology:
    def __init__(self):
        self.colorizer = FakeColorizer()

    def updateColorizer(self, _name):
        return


class FakeLayer:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path) if path else path
        self.visible = True
        self.transparency = 0
        self.symbology = FakeSymbology()


class FakeMap:
    def __init__(self):
        self.added_paths = []
        self.removed_paths = []
        self.groups = {}
        self.group_members = {}
        self.create_group_calls = []
        self.layers = []

    def createGroupLayer(self, name):
        self.create_group_calls.append(name)
        g = FakeLayer("GROUP::" + name)
        self.groups[name] = g
        self.group_members[name] = []
        return g

    def addDataFromPath(self, path):
        self.added_paths.append(path)
        layer = FakeLayer(path)
        self.layers.append(layer)
        return layer

    def addLayerToGroup(self, target_group, layer, position="AUTO_ARRANGE"):
        for gname, g in self.groups.items():
            if g is target_group:
                self.group_members[gname].append(layer.path)
                return
        raise RuntimeError("target group not registered")

    def removeLayer(self, layer):
        self.removed_paths.append(layer.path)


class FakeProject:
    def __init__(self, active_map):
        self.activeMap = active_map


def build_fake_arcpy():
    """Build a fresh fake arcpy module. state.active_map can be swapped
    out between test cases; state.messages accumulates log calls."""
    mod = types.ModuleType("arcpy")
    state = types.SimpleNamespace(active_map=FakeMap(), messages=[])

    mod.Parameter = FakeParameter

    mp_mod = types.ModuleType("arcpy.mp")

    def ArcGISProject(ref):
        return FakeProject(state.active_map)

    mp_mod.ArcGISProject = ArcGISProject
    mod.mp = mp_mod

    mgmt_mod = types.ModuleType("arcpy.management")

    def BuildPyramids(path, *a, **kw):
        state.messages.append(("pyramids", path))

    mgmt_mod.BuildPyramids = BuildPyramids
    mod.management = mgmt_mod

    mod.AddMessage = lambda m: state.messages.append(("info", m))
    mod.AddWarning = lambda m: state.messages.append(("warn", m))
    mod.AddError = lambda m: state.messages.append(("error", m))
    mod.SetProgressor = lambda *a, **k: None
    mod.SetProgressorLabel = lambda *a, **k: None
    mod.SetProgressorPosition = lambda *a, **k: None
    mod.ResetProgressor = lambda: None

    state.param_values = []

    def GetParameterAsText(i):
        v = state.param_values[i] if i < len(state.param_values) else None
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (list, tuple)):
            return ";".join("'%s'" % x for x in v)
        return str(v)

    mod.GetParameterAsText = GetParameterAsText

    mod._state = state
    return mod


PYT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DGED_Loader.pyt")
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "DGED_Load_Tool_script.py")


def load_flat_script(fake_arcpy):
    sys.modules["arcpy"] = fake_arcpy
    loader = importlib.machinery.SourceFileLoader("dged_load_flat_script", SCRIPT_PATH)
    spec = importlib.util.spec_from_file_location("dged_load_flat_script", SCRIPT_PATH,
                                                    loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_pyt(fake_arcpy):
    sys.modules["arcpy"] = fake_arcpy
    loader = importlib.machinery.SourceFileLoader("dged_loader_pyt", PYT_PATH)
    spec = importlib.util.spec_from_file_location("dged_loader_pyt", PYT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Test fixture folder tree
# --------------------------------------------------------------------------

def make_fixture(root):
    def touch(*parts):
        p = os.path.join(root, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")
        return p

    # main/demA_dged_output -- 2 complete tif+xml pairs, plus delivery-level
    # metadata (TABLE_OF_CONTENTS.xml) that must NOT be treated as a tile.
    touch("main", "demA_dged_output", "DGEDL5GtD_5530N00930E_A_U_01.tif")
    touch("main", "demA_dged_output", "DGEDL5GtD_5530N00930E_A_U_01.xml")
    touch("main", "demA_dged_output", "DGEDL5GtD_5531N00930E_A_U_01.tif")
    touch("main", "demA_dged_output", "DGEDL5GtD_5531N00930E_A_U_01.xml")
    touch("main", "demA_dged_output", "TABLE_OF_CONTENTS.xml")

    # main/demB_dged_output -- one complete pair, one tif with NO sidecar
    touch("main", "demB_dged_output", "DGEDL2_27N056E_A_U_01.tif")
    touch("main", "demB_dged_output", "DGEDL2_27N056E_A_U_01.xml")
    touch("main", "demB_dged_output", "DGEDL2_28N056E_A_U_01.tif")  # no .xml

    # a folder outside "main", to be picked via the Specific Subfolders param
    touch("standalone_subfolder", "DGEDL5UtD_32N6210_452_A_U_01.tif")
    touch("standalone_subfolder", "DGEDL5UtD_32N6210_452_A_U_01.xml")

    # a folder whose only tile is nested one level deeper, to test the
    # recursive on/off toggle
    touch("nested_only", "deeper", "DGEDL2_99N001E_A_U_01.tif")
    touch("nested_only", "deeper", "DGEDL2_99N001E_A_U_01.xml")

    # a stray non-tif file that must never be picked up
    touch("main", "demA_dged_output", "notes.txt")
    # QA artefacts and a source raster can sit under the same parent folder;
    # neither is a DGED delivery tile and the loader must ignore both.
    touch("main", "demA_dged_output", "validation", "elevation_diff.tif")
    touch("main", "demA_dged_output", "validation", "error_mask.tif")
    touch("main", "source_dem.tif")

    source = os.path.join(root, "main", "source_dem.tif")
    manifest_path = os.path.join(
        root, "main", "demA_dged_output",
        "DEM2DGED_Conversion_Manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as stream:
        json.dump({"source": {"path": source}}, stream)
    metrics_path = os.path.join(
        root, "main", "demA_dged_output", "validation",
        "terrain_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as stream:
        json.dump({
            "source": source,
            "error_threshold_m": 10.0,
            "metrics": {
                "count": 100,
                "bias": 0.25,
                "mae": 1.5,
                "rmse": 2.5,
                "p95": 4.5,
                "max": 20.668,
            },
        }, stream)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def run_tool(fake_arcpy, module, main_folder=None, subfolders_value=None,
             subfolders_text=None, recursive=True, group_layers=True,
             group_name="DGED Tiles", build_pyramids=False):
    tool = module.LoadDGEDTiles()
    params = tool.getParameterInfo()
    check("getParameterInfo returns 6 parameters", len(params) == 6, str(len(params)))

    params[0].value = main_folder
    if subfolders_value is not None:
        params[1].value = subfolders_value
    if subfolders_text is not None:
        params[1].valueAsText = subfolders_text
    params[2].value = recursive
    params[3].value = group_layers
    params[4].value = group_name
    params[5].value = build_pyramids

    tool.updateParameters(params)
    tool.updateMessages(params)
    tool.execute(params, None)
    return params


def run_comparison_tool(fake_arcpy, module, output_folder,
                        source_raster=None, load_tiles=True,
                        show_mask=True,
                        group_name="DGED vs Source Comparison"):
    tool = module.ShowDGEDDifferences()
    params = tool.getParameterInfo()
    check("comparison tool returns 5 parameters", len(params) == 5,
          str(len(params)))
    params[0].value = output_folder
    params[1].value = source_raster
    params[2].value = load_tiles
    params[3].value = show_mask
    params[4].value = group_name
    tool.updateParameters(params)
    tool.updateMessages(params)
    tool.execute(params, None)
    return params


def main():
    tmp = tempfile.mkdtemp(prefix="dged_loader_test_")
    try:
        make_fixture(tmp)
        main_dir = os.path.join(tmp, "main")
        standalone_dir = os.path.join(tmp, "standalone_subfolder")
        nested_dir = os.path.join(tmp, "nested_only")

        # -- Test 1: main folder only, recursive, default grouping ---------
        print("Test 1: main folder, recursive=True, grouping on")
        fa = build_fake_arcpy()
        mod = load_pyt(fa)
        params = run_tool(fa, mod, main_folder=main_dir, recursive=True,
                           group_layers=True, group_name="DGED Tiles")
        m = fa._state.active_map
        check("found 4 tiles (2 demA + 2 demB, TOC/notes.txt excluded)",
              len(m.added_paths) == 4, str(m.added_paths))
        check("group layer created once named 'DGED Tiles'",
              m.create_group_calls == ["DGED Tiles"], str(m.create_group_calls))
        check("all 4 layers added to the group",
              len(m.group_members.get("DGED Tiles", [])) == 4,
              str(m.group_members))
        check("all 4 top-level copies removed after grouping",
              len(m.removed_paths) == 4, str(m.removed_paths))
        warn_msgs = [t[1] for t in fa._state.messages if t[0] == "warn"]
        check("exactly one missing-sidecar warning",
              sum("no matching .xml sidecar" in w for w in warn_msgs) == 1,
              str(warn_msgs))
        check("the missing-sidecar warning names DGEDL2_28N056E tile",
              any("DGEDL2_28N056E" in w for w in warn_msgs), str(warn_msgs))
        check("source and terrain-QA GeoTIFFs are excluded",
              not any(os.path.basename(p) in {"source_dem.tif", "elevation_diff.tif",
                                               "error_mask.tif"}
                      for p in m.added_paths), str(m.added_paths))

        # -- Test 2: subfolders param only (multivalue, iterable .value) ---
        print("Test 2: Specific Subfolders only, .value given as a list")
        fa2 = build_fake_arcpy()
        mod2 = load_pyt(fa2)
        params2 = run_tool(fa2, mod2, main_folder=None,
                            subfolders_value=[standalone_dir],
                            group_layers=False)
        m2 = fa2._state.active_map
        check("found the 1 tile in the standalone subfolder",
              m2.added_paths == [os.path.join(standalone_dir,
                                  "DGEDL5UtD_32N6210_452_A_U_01.tif")],
              str(m2.added_paths))
        check("no group created when grouping is off",
              m2.create_group_calls == [], str(m2.create_group_calls))

        # -- Test 3: subfolders param via valueAsText fallback parsing -----
        print("Test 3: Specific Subfolders via valueAsText fallback parsing")
        fa3 = build_fake_arcpy()
        mod3 = load_pyt(fa3)
        quoted = "'%s'" % standalone_dir
        params3 = run_tool(fa3, mod3, main_folder=None,
                            subfolders_text=quoted, group_layers=False)
        m3 = fa3._state.active_map
        check("valueAsText-parsed subfolder still finds the 1 tile",
              len(m3.added_paths) == 1, str(m3.added_paths))

        # -- Test 4: overlapping main folder + subfolder de-duplicates -----
        print("Test 4: main folder + an overlapping subfolder de-duplicates")
        fa4 = build_fake_arcpy()
        mod4 = load_pyt(fa4)
        overlap_sub = os.path.join(main_dir, "demA_dged_output")
        params4 = run_tool(fa4, mod4, main_folder=main_dir,
                            subfolders_value=[overlap_sub], group_layers=False)
        m4 = fa4._state.active_map
        check("still exactly 4 tiles, no duplicates from the overlap",
              len(m4.added_paths) == 4, str(m4.added_paths))

        # -- Test 5: recursive toggle ---------------------------------------
        print("Test 5: recursive=False misses the nested tile, True finds it")
        fa5 = build_fake_arcpy()
        mod5 = load_pyt(fa5)
        run_tool(fa5, mod5, main_folder=nested_dir, recursive=False,
                 group_layers=False)
        check("recursive=False finds 0 tiles (tile is one level deeper)",
              len(fa5._state.active_map.added_paths) == 0,
              str(fa5._state.active_map.added_paths))

        fa5b = build_fake_arcpy()
        mod5b = load_pyt(fa5b)
        run_tool(fa5b, mod5b, main_folder=nested_dir, recursive=True,
                 group_layers=False)
        check("recursive=True finds the 1 nested tile",
              len(fa5b._state.active_map.added_paths) == 1,
              str(fa5b._state.active_map.added_paths))

        # -- Test 6: neither folder param given -> AddError, no crash ------
        print("Test 6: no folders provided at all")
        fa6 = build_fake_arcpy()
        mod6 = load_pyt(fa6)
        tool6 = mod6.LoadDGEDTiles()
        p6 = tool6.getParameterInfo()
        p6[0].value = None
        p6[2].value = True
        p6[3].value = True
        p6[4].value = "DGED Tiles"
        p6[5].value = False
        tool6.updateMessages(p6)
        check("updateMessages sets an error on param 0 when both are empty",
              p6[0].error is not None, str(p6[0].error))
        tool6.execute(p6, None)
        errs6 = [t[1] for t in fa6._state.messages if t[0] == "error"]
        check("execute() also calls AddError and adds nothing",
              len(errs6) == 1 and fa6._state.active_map.added_paths == [],
              str(errs6))

        # -- Test 7: updateParameters enables/disables Group Layer Name ----
        print("Test 7: updateParameters toggles Group Layer Name.enabled")
        fa7 = build_fake_arcpy()
        mod7 = load_pyt(fa7)
        tool7 = mod7.LoadDGEDTiles()
        p7 = tool7.getParameterInfo()
        p7[3].value = False
        tool7.updateParameters(p7)
        check("group_name disabled when group_layers is False",
              p7[4].enabled is False, str(p7[4].enabled))
        p7[3].value = True
        tool7.updateParameters(p7)
        check("group_name re-enabled when group_layers is True",
              p7[4].enabled is True, str(p7[4].enabled))

        # -- Test 8: build_pyramids invokes BuildPyramids per loaded tile --
        print("Test 8: build_pyramids=True calls BuildPyramids for each tile")
        fa8 = build_fake_arcpy()
        mod8 = load_pyt(fa8)
        run_tool(fa8, mod8, main_folder=standalone_dir, group_layers=False,
                 build_pyramids=True)
        pyramids_calls = [t[1] for t in fa8._state.messages if t[0] == "pyramids"]
        check("BuildPyramids called once (1 tile in standalone folder)",
              len(pyramids_calls) == 1, str(pyramids_calls))

        # -- Test 9: default parameter values from getParameterInfo --------
        print("Test 9: default values set in getParameterInfo")
        fa9 = build_fake_arcpy()
        mod9 = load_pyt(fa9)
        p9 = mod9.LoadDGEDTiles().getParameterInfo()
        names = [p.name for p in p9]
        check("parameter order/names as expected",
              names == ["main_folder", "subfolders", "recursive",
                        "group_layers", "group_name", "build_pyramids"],
              str(names))
        check("recursive defaults True", p9[2].value is True)
        check("group_layers defaults True", p9[3].value is True)
        check("group_name defaults 'DGED Tiles'", p9[4].value == "DGED Tiles")
        check("build_pyramids defaults False", p9[5].value is False)
        check("subfolders is multiValue", p9[1].multiValue is True)
        check("main_folder is not multiValue", p9[0].multiValue is False)

        # -- Test 10: comparison file discovery and source recovery --------
        print("Test 10: comparison files and source path resolve safely")
        fa_cmp = build_fake_arcpy()
        mod_cmp = load_pyt(fa_cmp)
        delivery_a = os.path.join(main_dir, "demA_dged_output")
        comparison_files = mod_cmp._comparison_files(delivery_a)
        check("delivery folder resolves validation/elevation_diff.tif",
              comparison_files["difference"] == os.path.join(
                  delivery_a, "validation", "elevation_diff.tif"),
              str(comparison_files))
        recovered, origin = mod_cmp._recover_source_path(
            None, comparison_files)
        check("original source is recovered from the conversion manifest",
              recovered == os.path.join(main_dir, "source_dem.tif") and
              origin == "conversion manifest", str((recovered, origin)))
        metric_summary = mod_cmp._metric_text(
            mod_cmp._read_json(comparison_files["terrain_metrics"]))
        check("terrain metric summary includes maximum difference",
              metric_summary is not None and "20.668 m" in metric_summary,
              str(metric_summary))

        # -- Test 11: Show DGED Differences end-to-end with fake arcpy -----
        print("Test 11: Show DGED Differences loads and labels QA layers")
        fa_cmp2 = build_fake_arcpy()
        mod_cmp2 = load_pyt(fa_cmp2)
        cmp_params = run_comparison_tool(
            fa_cmp2, mod_cmp2, delivery_a, source_raster=None,
            load_tiles=True, show_mask=True)
        cmp_map = fa_cmp2._state.active_map
        expected_cmp_paths = {
            os.path.join(main_dir, "source_dem.tif"),
            os.path.join(delivery_a,
                         "DGEDL5GtD_5530N00930E_A_U_01.tif"),
            os.path.join(delivery_a,
                         "DGEDL5GtD_5531N00930E_A_U_01.tif"),
            os.path.join(delivery_a, "validation", "elevation_diff.tif"),
            os.path.join(delivery_a, "validation", "error_mask.tif"),
        }
        check("source, two tiles, difference, and mask are loaded",
              set(cmp_map.added_paths) == expected_cmp_paths,
              str(cmp_map.added_paths))
        check("comparison layers are placed in one group",
              set(cmp_map.group_members.get(
                  "DGED vs Source Comparison", [])) == expected_cmp_paths,
              str(cmp_map.group_members))
        names_by_path = {layer.path: layer.name for layer in cmp_map.layers}
        check("signed difference label says DGED minus source",
              names_by_path.get(comparison_files["difference"]) ==
              "3 - Elevation difference (DGED - source, metres)",
              str(names_by_path))
        mask_path = comparison_files["error_mask"]
        mask_layer = next(layer for layer in cmp_map.layers
                          if layer.path == mask_path)
        red_items = [item for group in mask_layer.symbology.colorizer.groups
                     for item in group.items if item.color is not None]
        check("error-mask value 1 receives red symbology",
              len(red_items) == 1 and red_items[0].color ==
              {"RGB": [255, 0, 0, 100]}, str(red_items))
        info_messages = [item[1] for item in fa_cmp2._state.messages
                         if item[0] == "info"]
        check("tool explains positive and negative difference values",
              any("positive values = DGED is higher" in message
                  for message in info_messages), str(info_messages))
        check("tool reports the stored maximum difference",
              any("20.668 m" in message for message in info_messages),
              str(info_messages))
        check("comparison parameter defaults are correct",
              cmp_params[2].value is True and cmp_params[3].value is True and
              cmp_params[4].value == "DGED vs Source Comparison")

        # -- Test 12: ambiguous parent and missing QA fail explicitly ------
        print("Test 12: comparison discovery rejects unsafe selections")
        second_validation = os.path.join(
            main_dir, "demB_dged_output", "validation")
        os.makedirs(second_validation, exist_ok=True)
        with open(os.path.join(second_validation, "elevation_diff.tif"),
                  "w") as stream:
            stream.write("x")
        try:
            mod_cmp2._comparison_files(main_dir)
            ambiguous_failed = False
        except ValueError as exc:
            ambiguous_failed = "2 comparison result sets" in str(exc)
        check("parent with two QA result sets is rejected",
              ambiguous_failed)

        empty_folder = os.path.join(tmp, "empty_delivery")
        os.makedirs(empty_folder, exist_ok=True)
        fa_cmp3 = build_fake_arcpy()
        mod_cmp3 = load_pyt(fa_cmp3)
        run_comparison_tool(fa_cmp3, mod_cmp3, empty_folder,
                            load_tiles=False)
        cmp_errors = [item[1] for item in fa_cmp3._state.messages
                      if item[0] == "error"]
        check("folder without elevation_diff.tif reports a clear error",
              len(cmp_errors) == 1 and
              "No validation/elevation_diff.tif" in cmp_errors[0],
              str(cmp_errors))

        # -- Test 13: flat script (DGED_Load_Tool_script.py) parity --------
        print("Test 13: flat GetParameterAsText script -- same behaviour")
        fa10 = build_fake_arcpy()
        fa10._state.param_values = [main_dir, None, True, True, "DGED Tiles", False]
        mod10 = load_flat_script(fa10)
        mod10.main()
        m10 = fa10._state.active_map
        check("flat script finds the same 4 tiles as the .pyt tool",
              len(m10.added_paths) == 4, str(m10.added_paths))
        check("flat script groups all 4 tiles",
              len(m10.group_members.get("DGED Tiles", [])) == 4,
              str(m10.group_members))

        fa11 = build_fake_arcpy()
        fa11._state.param_values = [None, [standalone_dir], True, False,
                                     "DGED Tiles", False]
        mod11 = load_flat_script(fa11)
        mod11.main()
        m11 = fa11._state.active_map
        check("flat script: multivalue subfolders param parses correctly",
              len(m11.added_paths) == 1, str(m11.added_paths))

        fa12 = build_fake_arcpy()
        fa12._state.param_values = [None, None, True, True, "DGED Tiles", False]
        mod12 = load_flat_script(fa12)
        mod12.main()
        errs12 = [t[1] for t in fa12._state.messages if t[0] == "error"]
        check("flat script: no folders provided -> AddError, nothing added",
              len(errs12) == 1 and fa12._state.active_map.added_paths == [],
              str(errs12))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"ALL TESTS FAILED ({len(FAILURES)} failure(s)):")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
