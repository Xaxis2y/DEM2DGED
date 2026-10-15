# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# NOTE: GDAL/PROJ data dirs are auto-detected from the active Python
# environment (sys.prefix) rather than hardcoded to a fixed anaconda3
# install path, so `rebuild_exe.bat` works from any conda env.
from PyInstaller.utils.hooks import collect_all
import os, sys

# Get absolute path to current directory (where rebuild_exe.bat is run from)
# Note: __file__ is not available in spec namespace, so use current working directory
spec_dir = os.getcwd()

# XML template files - use absolute paths
geo_template = os.path.join(spec_dir, 'DGED_GEO_TEMPLATE.xml')
utm_template = os.path.join(spec_dir, 'DGED_UTM_TEMPLATE.xml')
compliance_policy = os.path.join(spec_dir, 'DEM2DGED_Compliance_Policy.json')

print("DEBUG: spec_dir =", spec_dir)
print("DEBUG: geo_template =", geo_template, "(exists: %s)" % os.path.isfile(geo_template))
print("DEBUG: utm_template =", utm_template, "(exists: %s)" % os.path.isfile(utm_template))

conda_prefix = sys.prefix
gdal_data_dir = os.path.join(conda_prefix, "Library", "share", "gdal")
proj_data_dir = os.path.join(conda_prefix, "Library", "share", "proj")
if not os.path.isdir(gdal_data_dir):
    try:
        import osgeo
        gdal_data_dir = os.path.join(os.path.dirname(osgeo.__file__), "data", "gdal")
    except Exception:
        pass

print("DEBUG: gdal_data_dir =", gdal_data_dir, "(exists: %s)" % os.path.isdir(gdal_data_dir))
print("DEBUG: proj_data_dir =", proj_data_dir, "(exists: %s)" % os.path.isdir(proj_data_dir))

# Use absolute paths for datas - this is critical for PyInstaller to find the files
datas = [(os.path.join(spec_dir, 'reference_catalog.json'), '.'), (geo_template, '.'), (utm_template, '.'), (compliance_policy, '.'),
         (gdal_data_dir, 'gdal'), (proj_data_dir, 'proj')]
binaries = []

# v0.62.3: collect_all('osgeo') includes the Python extension modules but does
# not include the Conda native DLL closure required by _gdal.pyd on a machine
# that does not have the DGED environment installed. Without this list the
# one-file executable fails to import osgeo._gdal and closes with exit code 1.
native_runtime_dlls = [
    "api-ms-win-crt-convert-l1-1-0.dll",
    "api-ms-win-crt-environment-l1-1-0.dll",
    "api-ms-win-crt-filesystem-l1-1-0.dll",
    "api-ms-win-crt-heap-l1-1-0.dll",
    "api-ms-win-crt-locale-l1-1-0.dll",
    "api-ms-win-crt-math-l1-1-0.dll",
    "api-ms-win-crt-runtime-l1-1-0.dll",
    "api-ms-win-crt-stdio-l1-1-0.dll",
    "api-ms-win-crt-string-l1-1-0.dll",
    "api-ms-win-crt-time-l1-1-0.dll",
    "api-ms-win-crt-utility-l1-1-0.dll",
    "VCOMP140.DLL",
    "VCRUNTIME140.dll",
    "VCRUNTIME140_1.dll",
    "MSVCP140.dll",
    "archive.dll",
    "blosc.dll",
    "brotlicommon.dll",
    "brotlidec.dll",
    "brotlienc.dll",
    "charset.dll",
    "deflate.dll",
    "freexl.dll",
    "gdal.dll",
    "geos.dll",
    "geos_c.dll",
    "hwy.dll",
    "iconv.dll",
    "icudt78.dll",
    "icuuc78.dll",
    "jpeg8.dll",
    "jxl.dll",
    "jxl_cms.dll",
    "jxl_threads.dll",
    "Lerc.dll",
    "libbz2.dll",
    "libcrypto-3-x64.dll",
    "libcurl.dll",
    "libexpat.dll",
    "liblzma.dll",
    "libminizip.dll",
    "libpng16.dll",
    "libsharpyuv.dll",
    "libssh2.dll",
    "libssl-3-x64.dll",
    "libwebp.dll",
    "libxml2.dll",
    "libzstd.dll",
    "lz4.dll",
    "muparser.dll",
    "pcre2-8.dll",
    "proj_9.dll",
    "snappy.dll",
    "spatialite.dll",
    "sqlite3.dll",
    "tiff.dll",
    "xerces-c_3_3.dll",
    "zlib.dll",
]
for native_dll in native_runtime_dlls:
    native_path = os.path.join(conda_prefix, "Library", "bin", native_dll)
    if not os.path.isfile(native_path):
        raise RuntimeError("Required GDAL runtime DLL is missing: %s" % native_path)
    binaries.append((native_path, "."))

# v0.33: dem2dged_compare (resampling comparison report) and numpy are
# imported at module level by dem2dged_gui.py / dem2dged_compare.py, so
# static analysis should find them -- listed explicitly for safety.
hiddenimports = ['osgeo.gdal', 'osgeo.osr', 'osgeo.ogr', 'osgeo._gdal', 'osgeo._osr', 'osgeo._ogr',
                 'dem2dged_compare', 'dem2dged_terrain',
                 'dem2dged_compliance', 'dem2dged_evidence', 'dem2dged_help', 'dem2dged_reference', 'dem2dged_datum', 'numpy']
tmp_ret = collect_all('osgeo')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['dem2dged_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide6', 'PyQt6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='dem2dged',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
