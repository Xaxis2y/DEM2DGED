#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.01  (which CRS the PROJ database ties the CGVD2013 grids to)
"""DIAG_PROJ_DB_v0.62.8.py

WHY THIS EXISTS
---------------
DIAG_PROJ_OPS showed that PROJ's only routes from CGVD2013 to NAD83(CSRS) look like

    Ballpark geographic offset from NAD83(CSRS) to NAD83(CSRS)v6
  + Inverse of NAD83(CSRS)v6 to CGVD2013(CGG2013) height (1)

i.e. the CGVD2013 operation is defined for a specific NAD83(CSRS) version (v6) or
for ITRF2008, while the DEM's horizontal CRS (EPSG:2959 / 4617) is the generic
"NAD83(CSRS)". The generic -> v6 link is a ballpark, which the converter's strict
guard refuses. This script reads PROJ's own database (proj.db, read-only) and lists:

  1. every NAD83(CSRS) / ITRF2008 geographic CRS and its EPSG code,
  2. every non-deprecated operation that involves CGVD2013 (6647) or EGM2008 (3855),
     with its grid file name and accuracy,
  3. the converter's strict test (CGVD2013 -> EGM2008, no ballpark) repeated with
     EACH of those horizontal CRSs, so we see which, if any, PROJ accepts.

It changes nothing and needs no input file.

HOW TO RUN (Anaconda Prompt, DGED environment, dem2dged_v0.62.8 folder):

    python DIAG_PROJ_DB_v0.62.8.py

It writes DIAG_PROJ_DB_<timestamp>.log; send that file.
"""

import datetime
import os
import pathlib
import sqlite3
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LON, LAT = -75.63113, 44.70164
_handle = None


def log(text=""):
    print(text, flush=True)
    if _handle:
        _handle.write(text + "\n")
        _handle.flush()


def section(title):
    log("")
    log("=" * 78)
    log(title)
    log("=" * 78)


def find_db(osr):
    candidates = []
    for name in ("PROJ_DATA", "PROJ_LIB"):
        if os.environ.get(name):
            candidates.append(os.environ[name])
    try:
        candidates.extend(osr.GetPROJSearchPaths())
    except Exception:
        pass
    for folder in candidates:
        path = os.path.join(folder, "proj.db")
        if os.path.isfile(path):
            return path
    return None


def query(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except Exception as exc:
        log("  query failed: %s" % exc)
        log("  sql: %s" % sql)
        return []


def step_database(conn):
    section("0. DATABASE VERSION")
    for key, value in query(conn, "SELECT key, value FROM metadata"):
        log("  %s = %s" % (key, value))

    section("1. NAD83(CSRS) / ITRF2008 GEOGRAPHIC CRS")
    rows = query(conn,
                 "SELECT auth_name, code, name, type, deprecated FROM geodetic_crs "
                 "WHERE (name LIKE 'NAD83(CSRS)%' OR name LIKE 'ITRF2008%') "
                 "AND type LIKE 'geographic%' ORDER BY name, type")
    crs_list = []
    for auth, code, name, kind, deprecated in rows:
        log("  %s:%-6s %-14s %-40s %s" % (auth, code, kind, name, "(deprecated)" if deprecated else ""))
        if auth == "EPSG" and kind == "geographic 2D" and not deprecated:
            crs_list.append((code, name))

    section("2. OPERATIONS INVOLVING CGVD2013 (6647) OR EGM2008 (3855)")
    ops = query(conn,
                "SELECT auth_name, code, table_name, name, source_crs_auth_name, source_crs_code, "
                "target_crs_auth_name, target_crs_code, accuracy FROM coordinate_operation_view "
                "WHERE deprecated = 0 AND (source_crs_code IN ('6647','3855') OR target_crs_code IN ('6647','3855')) "
                "ORDER BY name")

    def crs_name(auth, code):
        rows2 = query(conn, "SELECT name FROM crs_view WHERE auth_name = ? AND code = ?", (auth, code))
        return rows2[0][0] if rows2 else "?"

    for auth, code, table, name, s_auth, s_code, t_auth, t_code, accuracy in ops:
        grid = ""
        if table == "grid_transformation":
            grids = query(conn, "SELECT grid_name FROM grid_transformation WHERE auth_name = ? AND code = ?",
                          (auth, code))
            grid = ", ".join(g[0] for g in grids)
        log("  %s:%s  [%s]  accuracy=%s" % (auth, code, table, accuracy))
        log("      %s" % name)
        log("      from %s:%s %s" % (s_auth, s_code, crs_name(s_auth, s_code)))
        log("      to   %s:%s %s" % (t_auth, t_code, crs_name(t_auth, t_code)))
        if grid:
            log("      grid %s" % grid)
    return crs_list


def step_strict(osr, crs_list):
    section("3. STRICT TEST CGVD2013 -> EGM2008 WITH EACH HORIZONTAL CRS (no ballpark, best only)")
    seen = set()
    codes = [("4617", "NAD83(CSRS) generic (what the DEM files use)")]
    for code, name in crs_list:
        if code not in seen and code != "4617":
            codes.append((code, name))
        seen.add(code)
    for code, name in codes:
        log("")
        log("-- horizontal EPSG:%s  %s" % (code, name))
        try:
            def make(text):
                srs = osr.SpatialReference()
                srs.SetFromUserInput(text)
                if hasattr(srs, "SetAxisMappingStrategy"):
                    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                return srs
            options = osr.CoordinateTransformationOptions()
            options.SetBallparkAllowed(False)
            options.SetOnlyBest(True)
            options.SetAreaOfInterest(LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
            transform = osr.CreateCoordinateTransformation(
                make("EPSG:%s+6647" % code), make("EPSG:%s+3855" % code), options)
            x, y = (LAT, LON)     # EPSG authority axis order is lat, lon; mapping strategy is lon, lat
            out = transform.TransformPoint(LON, LAT, 100.0)
            log("   PASS: z 100.000 -> %.4f  (height change %+.4f m)" % (out[2], out[2] - 100.0))
        except Exception as exc:
            text = str(exc).replace("\n", " ")
            log("   FAIL: %s" % (text[:160] + ("..." if len(text) > 160 else "")))


def main():
    global _handle
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(HERE, "DIAG_PROJ_DB_%s.log" % stamp)
    _handle = open(path, "w", encoding="utf-8")
    log("DIAG_PROJ_DB v0.01   log: %s" % path)
    try:
        from osgeo import gdal, osr
        gdal.UseExceptions()
        osr.UseExceptions()
        db_path = find_db(osr)
        log("proj.db: %s" % db_path)
        if not db_path:
            log("proj.db not found; nothing to read.")
            return 1
        conn = sqlite3.connect(pathlib.Path(db_path).as_uri() + "?mode=ro", uri=True)
        crs_list = step_database(conn)
        conn.close()
        step_strict(osr, crs_list)
    except Exception:
        log("UNEXPECTED ERROR:")
        log(traceback.format_exc())
        return 1
    finally:
        log("")
        log("Log file: %s" % path)
        _handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
