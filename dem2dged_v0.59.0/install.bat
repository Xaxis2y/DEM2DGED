@echo off
REM ============================================================
REM  dem2dged  –  Windows install script (Anaconda / conda)
REM  SPDX-License-Identifier: GPL-2.0-or-later
REM Copyright (c) 2026 Eui Soo SON
REM ============================================================

echo.
echo  dem2dged installer
echo  ==================
echo.

REM 1. Create conda environment with GDAL
echo [1/3] Creating conda environment "DGED" ...
conda create --name DGED --channel conda-forge gdal python=3.10 -y

echo.
echo [2/3] Activating environment ...
call conda activate DGED

echo.
echo [3/3] Done!  Run conversions with:
echo.
echo   conda activate DGED
echo   cd %~dp0
echo   python dem2dged.py my_dem.tif output_folder
echo.
echo   (add --help for all options)
echo.
pause
