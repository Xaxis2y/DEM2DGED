# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

import os
import sys
import math
import shutil
import tempfile
import threading

import numpy as np
from osgeo import gdal, osr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dem2dged_gui as gui           # noqa: E402  (uses the GUI's convert_geo)
import dem2dged_compare as dc        # noqa: E402
import dem2dged_lib as dl            # noqa: E402


def make_synthetic_dem(path):
    """Write a 100x100 EPSG:4326 GeoTIFF covering lat 45.0-45.1, lon 10.0-10.1."""
    nx = ny = 100
    gt = (10.0, 0.001, 0.0, 45.1, 0.0, -0.001)
    xs = gt[0] + (np.arange(nx) + 0.5) * gt[1]
    ys = gt[3] + (np.arange(ny) + 0.5) * gt[5]
    X, Y = np.meshgrid(xs, ys)
    Z = (500.0
         + 300.0 * np.sin(2 * math.pi * (X - 10.0) * 3)
                 * np.cos(2 * math.pi * (Y - 45.0) * 2.5)
         + 200.0 * np.exp(-(((X - 10.05) / 0.02) ** 2
                            + ((Y - 45.05) / 0.02) ** 2))
         + 80.0 * np.exp(-((X - 10.03) / 0.004) ** 2))

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767)
    band.WriteArray(Z.astype("float32"))
    ds.FlushCache()
    ds = None
    return float(Z.min()), float(Z.max())


def main():
    print("=" * 64)
    print("dem2dged v%s  -  resampling comparison self-test (real GDAL %s)"
          % (dl.VERSION, gdal.__version__))
    print("=" * 64)

    work = tempfile.mkdtemp(prefix="dem2dged_selftest_")
    try:
        src = os.path.join(work, "synthetic_dem.tif")
        zmin, zmax = make_synthetic_dem(src)
        print("Synthetic source: %s  (range %.1f..%.1f m)" % (src, zmin, zmax))

        logs = []
        stop = threading.Event()
        entry = {"name": "synthetic_dem", "src": src, "level": "5",
                 "mode": "GEO", "methods": []}

        for num, alg, label, folder in dc.COMPARISON_METHODS:
            out_dir = os.path.join(work, folder)
            os.makedirs(out_dir, exist_ok=True)
            print("\n== Test %s: %s -> %s" % (num, label, folder))
            gui.convert_geo(src, out_dir, "5", "A", "U", "01",
                            lambda m: logs.append(m), lambda p: None, stop,
                            resampling=alg)
            tifs = [f for f in os.listdir(out_dir) if f.endswith(".tif")]
            print("   tiles written: %d" % len(tifs))
            assert tifs, "no tiles produced for %s" % label
            st = dc.compute_method_stats(src, out_dir, alg)
            entry["methods"].append({"num": num, "alg": alg, "label": label,
                                     "folder": out_dir, "elapsed": 0.0,
                                     "stats": st})
            print("   hold-out RMSE=%.4f m  MAE=%.4f m  |  round-trip "
                  "RMSE=%.4f m  overshoot=%.3f m"
                  % (st["rmse"], st["mae"], st["rt_rmse"], st["overshoot"]))

        stats = {m["alg"]: m["stats"] for m in entry["methods"]}

        # -- physics checks ------------------------------------------------
        assert stats["near"]["rmse"] >= stats["bilinear"]["rmse"], \
            "hold-out: nearest should not beat bilinear on smooth terrain"
        assert stats["near"]["rmse"] >= stats["cubic"]["rmse"], \
            "hold-out: nearest should not beat cubic on smooth terrain"
        print("\nPhysics checks passed (nearest worst on hold-out; "
              "nearest round-trip RMSE=%.6f m)" % stats["near"]["rt_rmse"])

        rep = os.path.join(work, dc.REPORT_FILENAME)
        dc.write_comparison_report([entry], rep)
        html = open(rep, encoding="utf-8").read()
        assert "Most Accurate" in html, "report is missing the ranking marker"
        best = min(entry["methods"], key=lambda m: (m["stats"]["rmse"],
                                                    m["stats"]["rt_rmse"]))
        print("Report written: %s" % rep)
        print("Most accurate on this terrain: %s" % best["label"])

        # keep a copy of the report next to this script for inspection
        keep = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "selftest_resampling_comparison_report.html")
        shutil.copyfile(rep, keep)
        print("Report copy kept at: %s" % keep)

        print("\nALL SELF-TEST CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
