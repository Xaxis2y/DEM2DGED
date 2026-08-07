@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  dem2dged v0.42  -  release verification
REM  SPDX-License-Identifier: GPL-2.0-or-later
REM  Copyright (c) 2026 Eui Soo SON
REM
REM  Runs the full end-to-end verification (logic audit, real-GDAL
REM  conversions on your DEMs under DEM\, validation, equatorial
REM  UTM zero-padding, the aspect sanity-check, and the new
REM  data-type-aware GeoTIFF predictor) and writes every result to
REM  tests\logs\ for review.
REM
REM  Run from an Anaconda Prompt with the DGED environment active:
REM      conda activate DGED
REM      verify.bat
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo  dem2dged v0.42 verification
echo ============================================================
echo.
echo Checking environment (GDAL/osgeo must be importable)...
python -c "from osgeo import gdal; print('  GDAL/osgeo OK, version', gdal.__version__)"
if errorlevel 1 (
    echo.
    echo ERROR: osgeo/GDAL is not importable in this environment.
    echo Make sure you ran:  conda activate DGED
    echo.
    pause
    exit /b 1
)

echo.
echo Running verification driver (this converts small DEM subsets and may
echo take a few minutes)...
echo.

python run_verification.py
set RC=%errorlevel%

echo.
echo ============================================================
echo  SUMMARY  (also saved to tests\logs\SUMMARY.txt)
echo ============================================================
if exist "tests\logs\SUMMARY.txt" (
    type "tests\logs\SUMMARY.txt"
) else (
    echo No SUMMARY.txt was produced -- see the console output above.
)

echo.
if "%RC%"=="0" (
    echo RESULT: ALL STEPS PASSED.
) else (
    echo RESULT: one or more steps FAILED ^(exit %RC%^) -- see
    echo         tests\logs\ for the detailed per-step logs.
)
echo.
echo Detailed logs : %~dp0tests\logs
echo Delivered tiles: %~dp0tests
echo.
pause
exit /b %RC%
