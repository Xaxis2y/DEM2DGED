@echo off
REM ============================================================
REM  build_exe.bat  --  FIRST-TIME build of dem2dged.exe (GUI)
REM  SPDX-License-Identifier: GPL-2.0-or-later
REM  Copyright (c) 2026 Eui Soo SON
REM  dem2dged v0.34
REM ============================================================
REM
REM  WHICH SCRIPT DO I RUN?  ->  You almost certainly want
REM                              rebuild_exe.bat, not this one.
REM
REM    rebuild_exe.bat  builds from the CURATED dem2dged.spec that
REM                     ships with the project. That spec pins the
REM                     hidden imports (dem2dged_compare, numpy), the
REM                     bundled XML templates and the GDAL/PROJ data
REM                     folders. Use it for every normal build.
REM
REM    build_exe.bat    (this file) builds from command-line flags
REM                     instead, without reading the spec at all.
REM                     Use it only to BOOTSTRAP a build when
REM                     dem2dged.spec is missing or corrupted, or to
REM                     test a one-off flag change.
REM
REM  v0.34 note: this script used to write its auto-generated spec into
REM  the project folder as "dem2dged.spec", SILENTLY OVERWRITING the
REM  curated one -- so running build_exe.bat once permanently degraded
REM  every later rebuild_exe.bat. It now writes the generated spec to
REM  build\autospec\ instead and the curated file is never touched.
REM
REM  Run from Anaconda Prompt (an environment that has GDAL):
REM    conda activate DGED
REM    cd path\to\dem2dged_v0.34
REM    build_exe.bat
REM ============================================================

echo.
echo  ============================================
echo   dem2dged v0.34  --  bootstrap .exe build
echo   (normal builds should use rebuild_exe.bat)
echo  ============================================
echo.

REM 0. The build environment MUST have GDAL (osgeo) installed --
REM    otherwise the exe builds fine but fails at runtime with
REM    "ModuleNotFoundError: No module named 'osgeo'".
python -c "import osgeo" 2>nul
if errorlevel 1 (
  echo.
  echo  ERROR: Python module 'osgeo' ^(GDAL^) not found in this environment.
  echo  Build the exe from an environment that has GDAL:
  echo.
  echo    conda activate DGED
  echo    pip install pyinstaller
  echo    build_exe.bat
  echo.
  echo  ^(If the DGED env does not exist yet, run install.bat first.^)
  echo.
  pause & exit /b 1
)

REM 1. Install PyInstaller if needed (python -m pip = same env as "python")
echo [1/4] Installing PyInstaller...
python -m pip install pyinstaller --quiet

REM 2. Find GDAL and PROJ data dirs (standard conda/Windows paths)
echo [2/4] Locating GDAL and PROJ data files...

REM Detect conda prefix
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.prefix)"') do set CONDA_PREFIX=%%i

set GDAL_DATA_DIR=%CONDA_PREFIX%\Library\share\gdal
set PROJ_DATA_DIR=%CONDA_PREFIX%\Library\share\proj

REM Fallback: osgeo data folder
if not exist "%GDAL_DATA_DIR%" (
  for /f "tokens=*" %%i in ('python -c "import os,osgeo; print(os.path.join(os.path.dirname(osgeo.__file__), \"data\", \"gdal\"))"') do set GDAL_DATA_DIR=%%i
)

echo    GDAL data : %GDAL_DATA_DIR%
echo    PROJ data : %PROJ_DATA_DIR%

if not exist "%GDAL_DATA_DIR%" (
  echo.
  echo  ERROR: Could not find GDAL data folder at:
  echo    %GDAL_DATA_DIR%
  echo  Make sure GDAL is installed: conda install -c conda-forge gdal
  echo.
  pause & exit /b 1
)
echo.

REM 3. Run PyInstaller (python -m = same environment as "python")
REM
REM    --console (NOT --windowed): dem2dged_gui.py prints diagnostics to
REM    stdout, and if GDAL fails to import it raises BEFORE the Tk window
REM    ever opens. Built --windowed, that failure is completely invisible
REM    -- the user double-clicks the exe and simply nothing happens. The
REM    console window is worth the small cosmetic cost. This also matches
REM    console=True in dem2dged.spec, so both build paths now produce the
REM    same exe (before v0.34 they disagreed: this script said --windowed
REM    while the spec said console=True).
REM
REM    --specpath build\autospec: keeps the auto-generated spec out of the
REM    project folder so it cannot overwrite the curated dem2dged.spec.
echo [3/4] Running PyInstaller...
if exist dist\dem2dged.exe del /q dist\dem2dged.exe
if not exist build\autospec mkdir build\autospec
python -m PyInstaller ^
  --onefile ^
  --console ^
  --name "dem2dged" ^
  --specpath "build\autospec" ^
  --add-data "DGED_GEO_TEMPLATE.xml;." ^
  --add-data "DGED_UTM_TEMPLATE.xml;." ^
  --add-data "%GDAL_DATA_DIR%;gdal" ^
  --add-data "%PROJ_DATA_DIR%;proj" ^
  --hidden-import "osgeo.gdal" ^
  --hidden-import "osgeo.osr" ^
  --hidden-import "osgeo.ogr" ^
  --hidden-import "osgeo._gdal" ^
  --hidden-import "osgeo._osr" ^
  --hidden-import "osgeo._ogr" ^
  --hidden-import "dem2dged_compare" ^
  --hidden-import "dem2dged_validate" ^
  --hidden-import "numpy" ^
  --collect-all "osgeo" ^
  --exclude-module "PyQt5" ^
  --exclude-module "PySide6" ^
  --exclude-module "PyQt6" ^
  --exclude-module "PySide2" ^
  --noconfirm ^
  dem2dged_gui.py

echo.
echo [4/4] Checking result...
if exist dist\dem2dged.exe (
  echo  SUCCESS!  Output: dist\dem2dged.exe
  echo  Double-click it to launch the converter.
  echo.
  echo  The curated dem2dged.spec was NOT modified; the generated
  echo  spec is in build\autospec\dem2dged.spec if you need it.
) else (
  echo  Build FAILED - check the output above for errors.
)
echo.
pause
