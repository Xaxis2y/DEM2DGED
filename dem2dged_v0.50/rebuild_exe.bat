@echo off
REM ============================================================
REM  rebuild_exe.bat  --  THE NORMAL WAY to build dem2dged.exe
REM  SPDX-License-Identifier: GPL-2.0-or-later
REM  Copyright (c) 2026 Eui Soo SON
REM  dem2dged v0.34
REM ============================================================
REM
REM  *** This is the script to use for every normal build. ***
REM
REM  It builds dem2dged.exe (the GUI + converter) from the curated
REM  dem2dged.spec that ships with the project. That spec pins:
REM    - the hidden imports PyInstaller's static analysis can miss
REM      (dem2dged_compare, numpy, the osgeo C extensions)
REM    - the two DGED XML templates, bundled into the exe
REM    - the GDAL and PROJ data folders, auto-detected from whichever
REM      conda environment is active (sys.prefix), not hardcoded
REM
REM  Use build_exe.bat INSTEAD only if dem2dged.spec is missing or
REM  corrupted -- it rebuilds from raw command-line flags.
REM
REM  What you get: a single-file console+GUI exe in dist\. The console
REM  window is intentional -- if GDAL fails to load, the error appears
REM  there instead of the exe silently doing nothing.
REM
REM  Run from Anaconda Prompt:
REM    conda activate DGED
REM    cd path\to\dem2dged_v0.34
REM    rebuild_exe.bat
REM ============================================================

echo.
echo  Rebuilding dem2dged.exe from dem2dged.spec  (v0.34) ...
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

REM v0.34: fail early and clearly if the curated spec is absent, rather
REM than letting PyInstaller emit a confusing "script not found" error.
if not exist dem2dged.spec (
  echo  ERROR: dem2dged.spec not found in this folder.
  echo.
  echo  You are either in the wrong directory, or the spec was deleted.
  echo  To rebuild without it, run:  build_exe.bat
  echo.
  pause & exit /b 1
)

REM Remove any previous exe so the success check below cannot be fooled
REM by a stale file from an earlier build.
if exist dist\dem2dged.exe del /q dist\dem2dged.exe

REM Use "python -m PyInstaller" so PyInstaller runs in the SAME Python
REM environment as "python" (a bare "pyinstaller" command may resolve to a
REM different Python installation on PATH, e.g. a standalone Python 3.14).
python -m pip install pyinstaller --quiet
python -m PyInstaller dem2dged.spec --noconfirm
set BUILD_RC=%errorlevel%

echo.
if %BUILD_RC% neq 0 (
    echo  Build FAILED - check output above for errors.
) else if exist dist\dem2dged.exe (
    echo  SUCCESS!  Output: dist\dem2dged.exe
) else (
    echo  Build may have failed - check output above for errors.
)
echo.
pause
