#!/usr/bin/env python3
"""Licensed ArcGIS Pro smoke test for DGED_Loader.pyt.

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON
Version: 0.59.0
Run this from an activated ArcGIS Pro Python environment, not from Anaconda's
base environment. The default run is read-only. Supplying --load-current-map
also executes Show DGED Differences against the current ArcGIS Pro map.
"""

import argparse
from datetime import datetime, timezone
import importlib.machinery
import importlib.util
import os
import platform
import sys
import traceback


VERSION = "0.59.0"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLBOX_PATH = os.path.join(SCRIPT_DIR, "DGED_Loader.pyt")
DEFAULT_LOG = os.path.join(SCRIPT_DIR, "DGED_Loader_arcgis_smoke_test.log")


class TestLog:
    def __init__(self):
        self.lines = []
        self.failures = 0

    def write(self, text=""):
        line = str(text)
        self.lines.append(line)
        print(line)

    def check(self, label, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = "" if not detail else " -- {0}".format(detail)
        self.write("[{0}] {1}{2}".format(status, label, suffix))
        if not condition:
            self.failures += 1

    def save(self, path):
        folder = os.path.dirname(os.path.abspath(path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("\n".join(self.lines) + "\n")


def load_python_toolbox():
    loader = importlib.machinery.SourceFileLoader(
        "dged_loader_arcgis_smoke", TOOLBOX_PATH)
    spec = importlib.util.spec_from_file_location(
        "dged_loader_arcgis_smoke", TOOLBOX_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Smoke-test DGED_Loader.pyt in a licensed ArcGIS Pro runtime.")
    parser.add_argument(
        "--dged-output",
        help="Optional individual *_dged_output folder for QA-file checks.")
    parser.add_argument(
        "--source-dem",
        help="Optional source DEM override used with --load-current-map.")
    parser.add_argument(
        "--load-current-map",
        action="store_true",
        help="Execute Show DGED Differences and add layers to the current map.")
    parser.add_argument(
        "--log",
        default=DEFAULT_LOG,
        help="Output log path. Default: %(default)s")
    return parser.parse_args(argv)


def run(args):
    log = TestLog()
    log.write("DGED Loader v{0} ArcGIS Pro Smoke Test".format(VERSION))
    log.write("Generated UTC: {0}".format(
        datetime.now(timezone.utc).isoformat()))
    log.write("Python: {0}".format(sys.version.replace("\n", " ")))
    log.write("Platform: {0}".format(platform.platform()))
    log.write("Toolbox: {0}".format(TOOLBOX_PATH))
    log.write("")

    try:
        import arcpy
        install = arcpy.GetInstallInfo()
        log.check("arcpy imports with an initialized product license", True)
        log.write("ArcGIS product: {0}".format(install.get("ProductName")))
        log.write("ArcGIS version: {0}".format(install.get("Version")))
        log.write("License level: {0}".format(arcpy.ProductInfo()))

        log.check("DGED_Loader.pyt exists", os.path.isfile(TOOLBOX_PATH))
        imported = arcpy.ImportToolbox(TOOLBOX_PATH, "dgedloader_smoke")
        log.check("arcpy.ImportToolbox succeeds", imported is not None)

        module = load_python_toolbox()
        toolbox = module.Toolbox()
        labels = [tool().label for tool in toolbox.tools]
        log.check("toolbox exposes Load DGED Tiles",
                  "Load DGED Tiles" in labels, str(labels))
        log.check("toolbox exposes Show DGED Differences",
                  "Show DGED Differences" in labels, str(labels))

        comparison = module.ShowDGEDDifferences()
        parameters = comparison.getParameterInfo()
        parameter_names = [parameter.name for parameter in parameters]
        expected = ["dged_output_folder", "source_raster", "load_tiles",
                    "show_error_mask", "group_name"]
        log.check("comparison parameters are in the expected order",
                  parameter_names == expected, str(parameter_names))
        log.check("comparison tool requires no ArcGIS extension",
                  comparison.isLicensed() is True)

        if args.dged_output:
            files = module._comparison_files(args.dged_output)
            log.write("")
            log.write("Resolved delivery: {0}".format(files["delivery_folder"]))
            log.write("Resolved QA folder: {0}".format(files["qa_folder"]))
            log.check("elevation_diff.tif exists",
                      arcpy.Exists(files["difference"]), files["difference"])
            log.check("error_mask.tif exists",
                      arcpy.Exists(files["error_mask"]), files["error_mask"])
            metrics = module._read_json(files["terrain_metrics"])
            log.check("terrain_metrics.json is readable",
                      bool(metrics), files["terrain_metrics"])
            source, origin = module._recover_source_path(
                args.source_dem, files)
            if source:
                log.check("original source DEM exists",
                          arcpy.Exists(source),
                          "{0} ({1})".format(source, origin))
            else:
                log.write("[WARN] No source path was recovered; use --source-dem.")

            if args.load_current_map:
                project = arcpy.mp.ArcGISProject("CURRENT")
                log.check("ArcGIS Pro has an active map",
                          project.activeMap is not None)
                if project.activeMap is not None:
                    parameters[0].value = args.dged_output
                    parameters[1].value = args.source_dem
                    parameters[2].value = True
                    parameters[3].value = True
                    parameters[4].value = (
                        "DGED vs Source Comparison - Smoke Test")
                    comparison.updateMessages(parameters)
                    comparison.execute(parameters, None)
                    log.check("Show DGED Differences executes", True)
        elif args.load_current_map:
            log.check("--load-current-map requires --dged-output", False)
        else:
            log.write("")
            log.write("No --dged-output supplied; data-specific checks skipped.")

    except Exception as exc:
        log.check("smoke test completed without an exception", False, str(exc))
        log.write(traceback.format_exc())

    log.write("")
    log.write("RESULT: {0}".format(
        "PASS" if log.failures == 0 else
        "FAIL ({0} failed check(s))".format(log.failures)))
    log.write("Log: {0}".format(os.path.abspath(args.log)))
    log.save(args.log)
    return 0 if log.failures == 0 else 1


def main(argv=None):
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
