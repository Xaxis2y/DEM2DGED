# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# NOTE: GDAL/PROJ data dirs are auto-detected from the active Python
# environment (sys.prefix) rather than hardcoded to a fixed anaconda3
# install path, so `rebuild_validate_exe.bat` works from any conda env.
from PyInstaller.utils.hooks import collect_all
import os, sys

conda_prefix = sys.prefix
gdal_data_dir = os.path.join(conda_prefix, "Library", "share", "gdal")
proj_data_dir = os.path.join(conda_prefix, "Library", "share", "proj")
if not os.path.isdir(gdal_data_dir):
    try:
        import osgeo
        gdal_data_dir = os.path.join(os.path.dirname(osgeo.__file__), "data", "gdal")
    except Exception:
        pass

datas = [(gdal_data_dir, 'gdal'), (proj_data_dir, 'proj')]
binaries = []
hiddenimports = ['osgeo.gdal', 'osgeo.osr', 'osgeo.ogr', 'osgeo._gdal', 'osgeo._osr', 'osgeo._ogr']
tmp_ret = collect_all('osgeo')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['dem2dged_validate.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide6', 'PyQt6', 'PySide2', 'tkinter'],
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
    name='dem2dged_validate',
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
