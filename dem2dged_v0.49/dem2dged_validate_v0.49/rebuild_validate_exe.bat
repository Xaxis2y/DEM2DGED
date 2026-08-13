@echo off
REM ============================================================
REM  rebuild_validate_exe.bat
REM    --  THE NORMAL WAY to build dem2dged_validate.exe
REM  SPDX-License-Identifier: GPL-2.0-or-later
REM  Copyright (c) 2026 Eui Soo SON
REM  dem2dged v0.34
REM ============================================================
REM
REM  *** This is the script to use for every normal validator build. ***
REM
REM  It builds dem2dged_validate.exe from the curated
REM  dem2dged_validate.spec that ships with the project.
REM
REM  Use build_validate_exe.bat INSTEAD only if that spec is missing or
REM  corrupted -- it rebuilds from raw command-line flags.
REM
REM  Do I even need this exe?
REM    Probably not. dem2dged.exe already runs the exact same checks
REM    automatically after every conversion and writes
REM    DGED_Validation_Report.html. Build this separate console exe only
REM    if you want to validate as a standalone step -- for example to QC
REM    a DGED delivery produced by someone else, or to run validation in
REM    a batch script or CI job by exit code (0 = pass, 1 = at least one
REM    FAIL).
REM
REM  Run from Anaconda Prompt:
REM    conda activate DGED
REM    cd path\to\dem2dged_v0.34
REM    rebuild_validate_exe.bat
REM ============================================================

echo.
echo  Rebuilding dem2dged_validate.exe from dem2dged_validate.spec  (v0.34) ...
echo.

REM The build environment MUST have GDAL (osgeo) installed -- otherwise
REM the exe fails at runtime with "No module named 'osgeo'".
python -c "import osgeo" 2>nul
if errorlevel 1 (
  echo  ERROR: 'osgeo' ^(GDAL^) not found in this Python environment.
  echo  Run:   conda activate DGED     then try again.
  echo  ^(If the DGED env does not exist, run install.bat first.^)
  echo.
  pause & exit /b 1
)

REM v0.34: fail early and clearly if the curated spec is absent.
if not exist dem2dged_validate.spec (
  echo  ERROR: dem2dged_validate.spec not found in this folder.
  echo.
  echo  You are either in the wrong directory, or the spec was deleted.
  echo  To rebuild without it, run:  build_validate_exe.bat
  echo.
  pause & exit /b 1
)

REM Remove any previous exe so the success check below cannot be fooled
REM by a stale file from an earlier build.
if exist dist\dem2dged_validate.exe del /q dist\dem2dged_validate.exe

REM Use "python -m PyInstaller" so PyInstaller runs in the SAME Python
REM environment as "python" (a bare "pyinstaller" command may resolve to a
REM different Python installation on PATH).
python -m pip install pyinstaller --quiet
python -m PyInstaller dem2dged_validate.spec --noconfirm
set BUILD_RC=%errorlevel%

echo.
if %BUILD_RC% neq 0 (
    echo  Build FAILED - check output above for errors.
) else if exist dist\dem2dged_validate.exe (
    echo  SUCCESS!  Output: dist\dem2dged_validate.exe
    echo.
    echo  Usage:
    echo    dem2dged_validate.exe TILE_FOLDER -src SOURCE.tif ^
-html-report report.html
) else (
    echo  Build may have failed - check output above for errors.
)
echo.
pause
