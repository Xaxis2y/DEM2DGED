@echo off
REM ============================================================
REM  build_validate_exe.bat
REM    --  FIRST-TIME build of dem2dged_validate.exe (console tool)
REM  SPDX-License-Identifier: GPL-2.0-or-later
REM  Copyright (c) 2026 Eui Soo SON
REM  dem2dged v0.34
REM ============================================================
REM
REM  WHICH SCRIPT DO I RUN?  ->  You almost certainly want
REM                              rebuild_validate_exe.bat, not this one.
REM
REM    rebuild_validate_exe.bat  builds from the CURATED
REM                              dem2dged_validate.spec shipped with the
REM                              project. Use it for every normal build.
REM
REM    build_validate_exe.bat    (this file) builds from command-line
REM                              flags without reading the spec at all.
REM                              Use it only to BOOTSTRAP a build when
REM                              dem2dged_validate.spec is missing or
REM                              corrupted.
REM
REM  This builds the VALIDATOR only -- a standalone console tool that
REM  checks an already-converted DGED tile folder. It is separate from
REM  dem2dged.exe because the validator is useful on its own (e.g. to
REM  QC a delivery received from someone else) and because excluding
REM  tkinter makes it substantially smaller.
REM
REM  Note: dem2dged.exe ALSO validates automatically after every
REM  conversion -- you do not need this exe for that. Build it only if
REM  you want to run validation as a separate step.
REM
REM  v0.34 note: this script used to write its auto-generated spec into
REM  the project folder as "dem2dged_validate.spec", SILENTLY
REM  OVERWRITING the curated one. It now writes to build\autospec\.
REM
REM  Run from Anaconda Prompt (an environment that has GDAL):
REM    conda activate DGED
REM    cd path\to\dem2dged_v0.34
REM    build_validate_exe.bat
REM ============================================================

echo.
echo  ==================================================
echo   dem2dged_validate v0.34  --  bootstrap .exe build
echo   (normal builds use rebuild_validate_exe.bat)
echo  ==================================================
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
  echo    build_validate_exe.bat
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

for /f "tokens=*" %%i in ('python -c "import sys; print(sys.prefix)"') do set CONDA_PREFIX=%%i

set GDAL_DATA_DIR=%CONDA_PREFIX%\Library\share\gdal
set PROJ_DATA_DIR=%CONDA_PREFIX%\Library\share\proj

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

REM 3. Run PyInstaller (console exe -- this is a CLI tool, not a GUI).
REM    tkinter is excluded: the validator never opens a window, and
REM    dropping it saves a noticeable amount of exe size.
REM    --specpath build\autospec keeps the generated spec from
REM    overwriting the curated dem2dged_validate.spec.
echo [3/4] Running PyInstaller...
if exist dist\dem2dged_validate.exe del /q dist\dem2dged_validate.exe
if not exist build\autospec mkdir build\autospec
python -m PyInstaller ^
  --onefile ^
  --console ^
  --name "dem2dged_validate" ^
  --specpath "build\autospec" ^
  --add-data "%GDAL_DATA_DIR%;gdal" ^
  --add-data "%PROJ_DATA_DIR%;proj" ^
  --hidden-import "osgeo.gdal" ^
  --hidden-import "osgeo.osr" ^
  --hidden-import "osgeo.ogr" ^
  --hidden-import "osgeo._gdal" ^
  --hidden-import "osgeo._osr" ^
  --hidden-import "osgeo._ogr" ^
  --hidden-import "numpy" ^
  --collect-all "osgeo" ^
  --exclude-module "PyQt5" ^
  --exclude-module "PySide6" ^
  --exclude-module "PyQt6" ^
  --exclude-module "PySide2" ^
  --exclude-module "tkinter" ^
  --noconfirm ^
  dem2dged_validate.py

echo.
echo [4/4] Checking result...
if exist dist\dem2dged_validate.exe (
  echo  SUCCESS!  Output: dist\dem2dged_validate.exe
  echo.
  echo  Run it from a Command Prompt like this:
  echo    dist\dem2dged_validate.exe output_folder -src my_dem.tif -report report.txt
  echo.
  echo  The curated dem2dged_validate.spec was NOT modified; the
  echo  generated spec is in build\autospec\ if you need it.
) else (
  echo  Build FAILED - check the output above for errors.
)
echo.
pause
