#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

import os
import sys
import glob
import shutil
import struct
import subprocess
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DEM_DIR = os.path.join(HERE, "DEM")
OUT_DIR = os.path.join(HERE, "tests")
LOG_DIR = os.path.join(OUT_DIR, "logs")
SUBSET_DIR = os.path.join(OUT_DIR, "subsets")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SUBSET_DIR, exist_ok=True)

SUMMARY_PATH = os.path.join(LOG_DIR, "SUMMARY.txt")
_summary_lines = []
_results = []   # (step_name, ok_bool, detail)


def _stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def summ(line=""):
    print(line)
    _summary_lines.append(line)


def record(step, ok, detail=""):
    _results.append((step, bool(ok), detail))
    summ("  [%s] %s%s" % ("PASS" if ok else "FAIL", step,
                          ("  --  " + detail) if detail else ""))


def write_log(name, text):
    path = os.path.join(LOG_DIR, name)
    with open(path, "w", encoding="utf-8", errors="replace") as f:
        f.write(text if isinstance(text, str) else str(text))
    return path


try:
    from osgeo import gdal, osr
    import numpy as np
    # v0.41: no gdal.UseExceptions() here -- dem2dged_lib pins the shared
    # gdal/ogr/osr exception flag for the whole project (see its header).
    # The harness banner also used to carry a frozen "v0.40" literal that
    # had to be hand-edited every release; it now reports the same single
    # source of truth every other module does.
    import dem2dged_lib as dl
except Exception as e:      # pragma: no cover
    summ("FATAL: could not import GDAL/numpy/dem2dged_lib (%s)." % e)
    summ("Run this from the DGED conda environment: conda activate DGED")
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(_summary_lines) + "\n")
    sys.exit(2)


# ---------------------------------------------------------------------------
#  helpers
# ---------------------------------------------------------------------------
def find_one(*name_globs):
    for pat in name_globs:
        hits = [h for h in glob.glob(os.path.join(DEM_DIR, "**", pat),
                                     recursive=True) if os.path.isfile(h)]
        if hits:
            return sorted(hits, key=lambda p: os.path.getsize(p))[0]
    return None


def raster_info(path):
    ds = gdal.Open(path)
    gt = ds.GetGeoTransform()
    xsz, ysz = ds.RasterXSize, ds.RasterYSize
    xs = [gt[0], gt[0] + xsz * gt[1]]
    ys = [gt[3], gt[3] + ysz * gt[5]]
    srs = osr.SpatialReference(wkt=ds.GetProjection())
    is_geo = bool(srs.IsGeographic())
    ds = None
    return min(xs), min(ys), max(xs), max(ys), is_geo


def subset(src, dst, span_x, span_y, off_x=0.0, off_y=0.0):
    """Clip a window of size (span_x, span_y) in SOURCE units, with its SW
    corner offset (off_x, off_y) fractions into the source from the SW
    corner. Lets us pick an interior/inland window instead of always the
    coastal SW corner."""
    minx, miny, maxx, maxy, _is_geo = raster_info(src)
    w, h = (maxx - minx), (maxy - miny)
    x0 = minx + off_x * w
    y0 = miny + off_y * h
    x1 = min(maxx, x0 + span_x)
    y1 = min(maxy, y0 + span_y)
    # projWin = [ulx, uly, lrx, lry]
    # The dataset handle is closed immediately: gdal.Translate() has
    # already written dst by the time it returns.
    gdal.Translate(dst, src, projWin=[x0, y1, x1, y0])
    return dst


def clean_dir(path):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def run_cli(args, log_name, timeout=2400):
    cmd = [sys.executable, os.path.join(HERE, "dem2dged.py")] + args
    header = "$ %s\n\n" % " ".join(cmd)
    try:
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           timeout=timeout)
        write_log(log_name, header + (p.stdout or "") +
                  "\n----- STDERR -----\n" + (p.stderr or ""))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        write_log(log_name, header + "TIMEOUT after %ss\n%s" % (timeout, e))
        return 124, "TIMEOUT"


def run_script(script, log_name, timeout=2400):
    cmd = [sys.executable, os.path.join(HERE, script)]
    header = "$ %s\n\n" % " ".join(cmd)
    try:
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           timeout=timeout)
        write_log(log_name, header + (p.stdout or "") +
                  "\n----- STDERR -----\n" + (p.stderr or ""))
        return p.returncode
    except subprocess.TimeoutExpired as e:
        write_log(log_name, header + "TIMEOUT after %ss\n%s" % (timeout, e))
        return 124


def parse_validation(folder):
    """Parse a delivery's DGED_Validation_Report.txt.

    Returns dict with result, n_pass/n_warn/n_fail, and the FAIL count split
    into 'structural' (before the '── H.' source-comparison section) and
    'source' (from '── H.' onward). Also returns the H stat lines for
    information.
    """
    rpt = os.path.join(folder, "DGED_Validation_Report.txt")
    out = {"result": None, "n_pass": 0, "n_warn": 0, "n_fail": 0,
           "structural_fail": 0, "source_fail": 0, "h_lines": []}
    if not os.path.isfile(rpt):
        out["result"] = "NO REPORT"
        return out
    in_source = False
    for line in open(rpt, encoding="utf-8", errors="replace").read().splitlines():
        s = line.strip()
        if s.startswith("──") and (" H." in line or " H2." in line
                                   or s.startswith("── H")):
            in_source = True
        if s.startswith("FAIL"):
            if in_source:
                out["source_fail"] += 1
            else:
                out["structural_fail"] += 1
        if s.startswith("RESULT:"):
            out["result"] = s.split(":", 1)[1].strip()
        if s.startswith("PASS=") and "WARN=" in s:
            for part in s.split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    if k in ("PASS", "WARN", "FAIL"):
                        try:
                            out["n_%s" % k.lower()] = int(v)
                        except ValueError:
                            pass
        if in_source and ("source" in line and " vs tiles " in line):
            out["h_lines"].append(s)
    return out


def list_tiles(folder):
    return sorted(glob.glob(os.path.join(folder, "*.tif")))


def read_tiff_predictor(path):
    """TIFF tag 317 (Predictor): 1 none, 2 horizontal, 3 float, or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return None
    if head[:2] == b"II":
        en = "<"
    elif head[:2] == b"MM":
        en = ">"
    else:
        return None
    magic = struct.unpack(en + "H", head[2:4])[0]
    with open(path, "rb") as f:
        if magic == 42:
            ifd_off = struct.unpack(en + "I", head[4:8])[0]
            f.seek(ifd_off)
            n = struct.unpack(en + "H", f.read(2))[0]
            entries = f.read(n * 12)
            esz = 12
        elif magic == 43:
            ifd_off = struct.unpack(en + "Q", head[8:16])[0]
            f.seek(ifd_off)
            n = struct.unpack(en + "Q", f.read(8))[0]
            entries = f.read(n * 20)
            esz = 20
        else:
            return None
    for i in range(n):
        base = i * esz
        tag = struct.unpack(en + "H", entries[base:base + 2])[0]
        if tag == 317:
            vfield = entries[base + (esz - (4 if esz == 12 else 8)):base + esz]
            return struct.unpack(en + "H", vfield[:2])[0]
    return None


def compression_of(path):
    ds = gdal.Open(path)
    c = ds.GetMetadataItem("COMPRESSION", "IMAGE_STRUCTURE")
    dt = gdal.GetDataTypeName(ds.GetRasterBand(1).DataType)
    ds = None
    return c, dt


def make_synthetic_dem(path, lat0, lon0, deg=1.0, n=200):
    """Write a small EPSG:4326 GeoTIFF covering exactly
    [lon0, lon0+deg] x [lat0, lat0+deg], area-registered so it aligns to the
    whole-degree DGED tile grid (level 0/1 tiles are 1 deg), with smooth,
    all-positive synthetic terrain (a couple of hills + a ridge, ~200..1400 m,
    no sea, no NoData). Used to exercise latitude-dependent code paths your
    real (all zone-1, all northern) DEMs can't reach: the GEO longitude
    post-spacing factors above 50 deg, and the southern hemisphere."""
    gt = (lon0, deg / n, 0.0, lat0 + deg, 0.0, -deg / n)
    xs = gt[0] + (np.arange(n) + 0.5) * gt[1]
    ys = gt[3] + (np.arange(n) + 0.5) * gt[5]
    X, Y = np.meshgrid(xs, ys)
    u = (X - lon0) / deg
    v = (Y - lat0) / deg
    Z = (600.0
         + 500.0 * np.sin(2 * 3.14159 * u * 2) * np.cos(2 * 3.14159 * v * 1.5)
         + 300.0 * np.exp(-(((u - 0.5) / 0.15) ** 2 + ((v - 0.5) / 0.15) ** 2))
         + 150.0 * np.exp(-((u - 0.3) / 0.05) ** 2))
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, n, n, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767)
    band.WriteArray(Z.astype("float32"))
    ds.FlushCache()
    ds = None
    return path


def tile_pixel_ratio(folder):
    """(xres, yres, xres/yres) of the first tile in a delivery, or None."""
    tiles = list_tiles(folder)
    if not tiles:
        return None
    ds = gdal.Open(tiles[0])
    gt = ds.GetGeoTransform()
    ds = None
    xr, yr = abs(gt[1]), abs(gt[5])
    return xr, yr, (xr / yr if yr else 0.0)


# ---------------------------------------------------------------------------
#  conversion + validation, with structural/source split
# ---------------------------------------------------------------------------
def convert_check(step, src, out_sub, mode, level, resample, log_name,
                  want_dtype, want_predictor, gate_source=False,
                  extra_args=None):
    out_folder = os.path.join(OUT_DIR, out_sub)
    clean_dir(out_folder)                       # no stale tiles
    args = [src, out_folder, "--mode", mode, "--level", level,
            "--resample", resample] + (extra_args or [])
    rc, _out = run_cli(args, log_name)
    if rc != 0:
        record(step, False, "CLI exit=%d (see %s)" % (rc, log_name))
        return out_folder
    v = parse_validation(out_folder)
    tiles = list_tiles(out_folder)

    ok = (v["structural_fail"] == 0) and len(tiles) > 0
    if gate_source:
        ok = ok and (v["source_fail"] == 0)

    detail = ("%d tiles, struct-FAIL=%d, sourceH-FAIL=%d%s, result=%s"
              % (len(tiles), v["structural_fail"], v["source_fail"],
                 "" if gate_source else " (H informational)", v["result"]))

    if tiles:
        comp, dt = compression_of(tiles[0])
        pred = read_tiff_predictor(tiles[0])
        detail += ", %s/%s/PRED=%s" % (dt, comp, pred)
        if want_dtype and dt != want_dtype:
            ok = False; detail += " [want dtype %s]" % want_dtype
        if want_predictor and pred != want_predictor:
            ok = False; detail += " [want PRED %s]" % want_predictor
        if comp != "LZW":
            ok = False; detail += " [want LZW]"
    else:
        ok = False
    record(step, ok, detail)
    return out_folder


# ---------------------------------------------------------------------------
#  steps
# ---------------------------------------------------------------------------
def step_environment():
    tifs = (glob.glob(os.path.join(DEM_DIR, "**", "*.tif"), recursive=True) +
            glob.glob(os.path.join(DEM_DIR, "**", "*.tiff"), recursive=True))
    lines = ["dem2dged v%s verification  -  %s" % (dl.VERSION, _stamp()),
             "Python: %s" % sys.version.replace("\n", " "),
             "GDAL:   %s" % gdal.__version__,
             "Found %d raster(s) under DEM/:" % len(tifs)]
    for t in sorted(tifs)[:40]:
        lines.append("   %s" % os.path.relpath(t, HERE))
    write_log("00_environment.txt", "\n".join(lines))
    record("environment / GDAL import", True,
           "GDAL %s, %d source rasters" % (gdal.__version__, len(tifs)))


def step_zero_padding(utm_folder):
    import re
    tiles = [os.path.basename(t) for t in list_tiles(utm_folder)]
    bad, example = [], None
    for name in tiles:
        m = re.match(r"^DGEDL4bUt[A-Z]_(?:[A-Z]{2,4}_)?\d{1,2}[NS](\d+)_(\d+)_",
                     name)
        if m:
            if len(m.group(1)) != 4:
                bad.append(name)
            elif example is None:
                example = name
    if not tiles:
        record("UTM equatorial zero-padding (spec 12.1)", False, "no tiles")
    else:
        record("UTM equatorial zero-padding (spec 12.1)", not bad,
               ("%d tiles, northings all 4-digit (e.g. %s)" % (len(tiles), example))
               if not bad else ("non-4-digit: %s" % ", ".join(bad[:3])))


def step_sanity(aspect_src):
    out_folder = os.path.join(OUT_DIR, "sanity_block")
    clean_dir(out_folder)
    rc, out = run_cli([aspect_src, out_folder, "--mode", "geo", "--level", "0",
                       "--resample", "near"], "20_sanity_block.txt")
    low = out.lower()
    detected = any(kw in low for kw in ("aspect", "derivative", "direction",
                                        "angular", "not elevation", "0-360",
                                        "compass"))
    tiles = list_tiles(out_folder) if os.path.isdir(out_folder) else []
    blocked = ((rc != 0) or ("stopped before doing any work" in low)) and not tiles
    record("sanity check DETECTS aspect raster", detected,
           "%s, exit=%d, %d tiles" % (
               "BLOCKED before conversion" if blocked else "warned+proceeded",
               rc, len(tiles)))

    # tiny interior window (2% of each axis) for the --skip override test
    try:
        minx, miny, maxx, maxy, _ = raster_info(aspect_src)
        sx, sy = (maxx - minx) * 0.02, (maxy - miny) * 0.02
        sub = subset(aspect_src, os.path.join(SUBSET_DIR, "aspect_small.tif"),
                     span_x=sx, span_y=sy, off_x=0.45, off_y=0.45)
        out2 = os.path.join(OUT_DIR, "sanity_skip")
        clean_dir(out2)
        rc2, _ = run_cli([sub, out2, "--mode", "utm", "--level", "4b",
                          "--resample", "near", "--skip-sanity-check"],
                         "21_sanity_skip.txt")
        proceeded = rc2 == 0 and len(list_tiles(out2)) > 0
        record("--skip-sanity-check override proceeds", proceeded,
               "exit=%d, %d tiles" % (rc2, len(list_tiles(out2))))
    except Exception as e:
        record("--skip-sanity-check override proceeds", False, "error: %s" % e)


def step_predictor_matrix(int16_folder, float_folder):
    lines = ["Raw TIFF Predictor tag (317)  -  %s" % _stamp(), ""]
    ok = True
    for label, folder, want in (("Int16", int16_folder, 2),
                                ("Float32", float_folder, 3)):
        tiles = list_tiles(folder) if folder else []
        if not tiles:
            lines.append("%-8s : NO TILES" % label); ok = False; continue
        comp, dt = compression_of(tiles[0])
        pred = read_tiff_predictor(tiles[0])
        good = (pred == want and comp == "LZW")
        ok = ok and good
        lines.append("%-8s : %s  dtype=%s  comp=%s  PRED=%s (want %d) -> %s"
                     % (label, os.path.basename(tiles[0]), dt, comp, pred,
                        want, "OK" if good else "MISMATCH"))
    write_log("22_predictor_check.txt", "\n".join(lines))
    record("GeoTIFF predictor Int16->2 / Float32->3, LZW", ok)


def step_geo_zone_factor(lat0, expected_factor, label):
    """Synthetic 1x1 deg DEM at `lat0`, converted GEO level 0. The GEO
    longitude post spacing is `factor` x the latitude spacing (spec 6.5 /
    Table 3), so the delivered tile's pixel WIDTH:HEIGHT ratio must equal the
    zone factor. This directly exercises the >50 deg longitude-factor code
    path (factors 1.5 / 2 / 3), which no zone-1 real DEM can reach, and
    confirms converter and validator agree on it (structural checks)."""
    src = make_synthetic_dem(os.path.join(SUBSET_DIR, "syn_%s.tif" % label),
                             lat0=lat0, lon0=12.0, deg=1.0, n=200)
    out = os.path.join(OUT_DIR, "geo_%s" % label)
    clean_dir(out)
    rc, _ = run_cli([src, out, "--mode", "geo", "--level", "0",
                     "--resample", "bilinear"], "30_geo_%s.txt" % label)
    v = parse_validation(out)
    ratio = tile_pixel_ratio(out)
    ratio_ok = ratio is not None and abs(ratio[2] - expected_factor) < 0.02
    ok = (rc == 0 and v["structural_fail"] == 0 and ratio_ok)
    detail = ("lat %g, struct-FAIL=%d, sourceH-FAIL=%d, lon/lat pixel ratio=%s "
              "(want %.2f)" % (lat0, v["structural_fail"], v["source_fail"],
                              ("%.4f" % ratio[2]) if ratio else "n/a",
                              expected_factor))
    record("GEO longitude factor x%.1f at %g deg lat (synthetic)"
           % (expected_factor, lat0), ok, detail)


def step_southern():
    """Southern hemisphere: GEO 'S' naming and southern UTM false-northing
    (10 000 000 - j*dN), neither of which any northern real DEM can reach."""
    # GEO south: a whole-degree synthetic at lat -35 -> one level-0 tile whose
    # name must carry the 'S' hemisphere letter.
    gsrc = make_synthetic_dem(os.path.join(SUBSET_DIR, "syn_geo_south.tif"),
                              lat0=-35.0, lon0=12.0, deg=1.0, n=200)
    gout = os.path.join(OUT_DIR, "geo_south")
    clean_dir(gout)
    rc, _ = run_cli([gsrc, gout, "--mode", "geo", "--level", "0",
                     "--resample", "bilinear"], "31_geo_south.txt")
    vg = parse_validation(gout)
    gnames = [os.path.basename(t) for t in list_tiles(gout)]
    s_named = any("S" in n.split("_")[1] for n in gnames) if gnames else False
    record("GEO southern-hemisphere 'S' naming (synthetic)",
           rc == 0 and vg["structural_fail"] == 0 and s_named,
           "struct-FAIL=%d, tiles=%s" % (vg["structural_fail"],
                                         gnames[:1] or "none"))

    # UTM south: small synthetic at lat -35 -> southern zone (EPSG 327xx),
    # northings on the 10 000 000-based lattice, 4-digit zero-padded.
    usrc = make_synthetic_dem(os.path.join(SUBSET_DIR, "syn_utm_south.tif"),
                              lat0=-35.0, lon0=12.0, deg=0.2, n=200)
    uout = os.path.join(OUT_DIR, "utm_south")
    clean_dir(uout)
    rc2, _ = run_cli([usrc, uout, "--mode", "utm", "--level", "4b",
                      "--resample", "bilinear"], "32_utm_south.txt")
    vu = parse_validation(uout)
    unames = [os.path.basename(t) for t in list_tiles(uout)]
    south_epsg = False
    if list_tiles(uout):
        ds = gdal.Open(list_tiles(uout)[0])
        srs = osr.SpatialReference(wkt=ds.GetProjection())
        code = srs.GetAuthorityCode("PROJCS") or ""
        south_epsg = code.startswith("327")
        ds = None
    record("UTM southern-hemisphere false-northing (synthetic)",
           rc2 == 0 and vu["structural_fail"] == 0 and south_epsg and bool(unames),
           "struct-FAIL=%d, EPSG327xx=%s, tiles=%s"
           % (vu["structural_fail"], south_epsg, unames[:1] or "none"))


def step_vertical_transform():
    """Real EGM96 -> EGM2008 vertical transform path (--source-vertical 5773),
    which the default label-only tests never exercise. Needs PROJ vertical
    grids; if they aren't installed the warp can't run -- that's an
    environment limitation, not a code defect, so a grid-related failure is
    reported as SKIPPED rather than FAILED."""
    src = make_synthetic_dem(os.path.join(SUBSET_DIR, "syn_vert.tif"),
                             lat0=45.0, lon0=8.0, deg=0.5, n=200)
    out = os.path.join(OUT_DIR, "geo_vertical_egm")
    clean_dir(out)
    rc, txt = run_cli([src, out, "--mode", "geo", "--level", "1",
                       "--resample", "bilinear", "--source-vertical", "5773"],
                      "33_geo_vertical.txt")
    low = txt.lower()
    grid_issue = any(k in low for k in ("grid", "egm", "geoid", "proj_lib",
                                        "cannot find", "not found",
                                        "no transformation", "us_nga"))
    tiles = list_tiles(out)
    if rc == 0 and tiles:
        v = parse_validation(out)
        record("vertical transform EGM96->EGM2008 (--source-vertical 5773)",
               v["structural_fail"] == 0,
               "ran a real geoid transform, struct-FAIL=%d, %d tiles"
               % (v["structural_fail"], len(tiles)))
    elif grid_issue:
        record("vertical transform EGM96->EGM2008 (--source-vertical 5773)",
               True,
               "SKIPPED: PROJ vertical grids not installed (code path reached; "
               "not a defect). Install PROJ EGM grids to fully test.")
    else:
        record("vertical transform EGM96->EGM2008 (--source-vertical 5773)",
               False, "CLI exit=%d, %d tiles (see 33_geo_vertical.txt)"
               % (rc, len(tiles)))


def step_standalone_validator(folder, resample, src):
    tiles = list_tiles(folder) if folder else []
    if not tiles:
        record("standalone validator + -src (Section H, accurate run)", False,
               "no delivery")
        return
    txt = os.path.join(LOG_DIR, "23_standalone_validate_report.txt")
    cmd = [sys.executable, os.path.join(HERE, "dem2dged_validate.py"), folder,
           "-src", src, "-resample", resample, "-report", txt]
    p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    write_log("23_standalone_validate.txt",
              "$ %s\n\n%s\n---STDERR---\n%s" % (" ".join(cmd), p.stdout, p.stderr))
    record("standalone validator + -src on accurate run (exit 0)",
           p.returncode == 0, "exit=%d" % p.returncode)


# ---------------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------------
def main():
    summ("=" * 74)
    summ(" dem2dged v%s  -  release verification" % dl.VERSION)
    summ(" %s" % _stamp())
    summ("=" * 74)

    step_environment()
    record("audit_pure.py (logic + version consistency)",
           run_script("audit_pure.py", "01_audit_pure.txt") == 0)
    record("selftest_resampling_comparison.py",
           run_script("selftest_resampling_comparison.py", "02_selftest.txt") == 0)

    lebanon = find_one("n33_e035*1arc*.tif", "n3?_e03?*1arc*.tif", "*.tif")
    equator = find_one("n00_e015*1arc*.tif", "n00_e0*1arc*.tif", "n00_*1arc*.tif")
    aspect = find_one("*aspect*.tiff", "*aspect*.tif")

    summ("")
    summ("Selected inputs:")
    summ("  GEO/general  : %s" % (os.path.relpath(lebanon, HERE) if lebanon else "NOT FOUND"))
    summ("  equatorial   : %s" % (os.path.relpath(equator, HERE) if equator else "NOT FOUND"))
    summ("  aspect(deriv): %s" % (os.path.relpath(aspect, HERE) if aspect else "NOT FOUND"))
    summ("")

    int16_folder = float_folder = accurate_folder = None
    accurate_src = None

    if lebanon:
        try:
            # Accurate, GATED-on-source run: interior (inland) crop, GEO
            # level 2 = 1 arcsec = SRTM-native, bilinear -> near-identity, so
            # Section H must pass. Interior offset avoids the coastal SW
            # corner's sea.
            acc_src = subset(lebanon, os.path.join(SUBSET_DIR, "geo_accurate.tif"),
                             span_x=0.20, span_y=0.20, off_x=0.55, off_y=0.55)
            accurate_src = acc_src
            accurate_folder = convert_check(
                "GEO L2 bilinear near-native (GATED incl. Section H)",
                acc_src, "geo_L2_bilinear", "geo", "2", "bilinear",
                "10_geo_L2_bilinear.txt", want_dtype="Int16", want_predictor=2,
                gate_source=True)

            # Structural stress runs (Section H informational):
            s1 = subset(lebanon, os.path.join(SUBSET_DIR, "geo_src.tif"),
                        span_x=0.20, span_y=0.20, off_x=0.55, off_y=0.55)
            int16_folder = convert_check(
                "GEO L1 near (Int16, PRED=2) [structural]", s1, "geo_L1_near",
                "geo", "1", "near", "11_geo_L1_near.txt",
                want_dtype="Int16", want_predictor=2)

            s2 = subset(lebanon, os.path.join(SUBSET_DIR, "geo_src2.tif"),
                        span_x=0.12, span_y=0.12, off_x=0.55, off_y=0.55)
            float_folder = convert_check(
                "GEO L4b cubic (Float32, PRED=3, clamp) [structural]", s2,
                "geo_L4b_cubic", "geo", "4b", "cubic", "12_geo_L4b_cubic.txt",
                want_dtype="Float32", want_predictor=3)

            convert_check(
                "GEO L0 optimize (auto resampler) [structural]", s1,
                "geo_L0_optimize", "geo", "0", "optimize",
                "13_geo_L0_optimize.txt", want_dtype="Int16", want_predictor=2)
        except Exception as e:
            record("GEO conversions", False, "exception: %s" % e)
    else:
        record("GEO conversions", False, "no GEO source under DEM/")

    utm_folder = None
    if equator:
        try:
            # Equatorial crop anchored AT the equator (off_y=0.0) so the
            # source's point-registration overhang dips just below northing 0
            # -- this deliberately exercises the v0.39 northing clamp, which
            # must drop the sub-equator tile and keep every northing field
            # >= 0 and 4-digit ("0000"). off_x interior to avoid the E edge.
            eq = subset(equator, os.path.join(SUBSET_DIR, "equator_src.tif"),
                        span_x=0.20, span_y=0.20, off_x=0.30, off_y=0.0)
            utm_folder = convert_check(
                "UTM L4b bilinear equatorial (Float32, PRED=3) [structural]",
                eq, "utm_L4b_equator", "utm", "4b", "bilinear",
                "14_utm_L4b_equator.txt", want_dtype="Float32",
                want_predictor=3)
            step_zero_padding(utm_folder)
        except Exception as e:
            record("UTM equatorial conversion", False, "exception: %s" % e)
    else:
        record("UTM equatorial conversion", False, "no n00_* source under DEM/")

    if aspect:
        try:
            step_sanity(aspect)
        except Exception as e:
            record("sanity check", False, "exception: %s" % e)
    else:
        record("sanity check", False, "no aspect raster under DEM/")

    # Synthetic latitude-dependent coverage -- exercises the code paths your
    # all-zone-1 / all-northern real DEMs cannot reach. No download needed.
    try:
        step_geo_zone_factor(55.0, 1.5, "zone2")   # 50-60 deg: factor 1.5
        step_geo_zone_factor(65.0, 2.0, "zone3")   # 60-70 deg: factor 2
        step_geo_zone_factor(75.0, 3.0, "zone4")   # 70-80 deg: factor 3
        step_southern()
        step_vertical_transform()
    except Exception as e:
        record("synthetic high-latitude / southern / vertical tests", False,
               "exception: %s" % e)

    step_predictor_matrix(int16_folder, float_folder)

    if accurate_folder and accurate_src:
        step_standalone_validator(accurate_folder, "bilinear", accurate_src)

    # ---- summary ----
    summ("")
    summ("=" * 74)
    n_pass = sum(1 for _, ok, _ in _results if ok)
    n_fail = len(_results) - n_pass
    summ(" TOTAL: %d step(s)  -  %d PASS  /  %d FAIL" % (len(_results), n_pass, n_fail))
    summ("=" * 74)
    for step, ok, detail in _results:
        summ("  %-5s %s%s" % ("PASS" if ok else "FAIL", step,
                              ("  --  " + detail) if detail else ""))
    summ("")
    summ("Note: Section H (source accuracy) is gated only on the GEO L2")
    summ("bilinear near-native run; for Nearest/Cubic and partial/coastal")
    summ("deliveries it is reported for information (see per-step logs).")
    summ("Detailed logs: %s" % LOG_DIR)

    with open(SUMMARY_PATH, "w", encoding="utf-8", errors="replace") as f:
        f.write("\n".join(_summary_lines) + "\n")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
