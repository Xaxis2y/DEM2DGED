@echo off
REM SPDX-License-Identifier: GPL-2.0-or-later
REM Copyright (c) 2026 Eui Soo SON
REM dem2dged Anaconda Environment Setup Script
REM This script creates and configures a dedicated Anaconda environment for dem2dged
REM
REM Usage: Run this script from Anaconda Prompt
REM    dem2dged_anaconda_environment.bat

setlocal enabledelayedexpansion

set ENVIRONMENT_NAME=dem2dged_anaconda_environment
set PYTHON_VERSION=3.11

echo.
echo ============================================================================
echo dem2dged Anaconda Environment Setup
echo ============================================================================
echo.
echo This script will create a new Anaconda environment: %ENVIRONMENT_NAME%
echo Python version: %PYTHON_VERSION%
echo.

REM Check if conda is available
conda --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: conda not found. Please ensure Anaconda is installed and Anaconda Prompt is used.
    pause
    exit /b 1
)

echo Step 1: Creating environment '%ENVIRONMENT_NAME%' with Python %PYTHON_VERSION%...
call conda create -n %ENVIRONMENT_NAME% python=%PYTHON_VERSION% -y
if errorlevel 1 (
    echo ERROR: Failed to create environment.
    pause
    exit /b 1
)

echo.
echo Step 2: Activating environment '%ENVIRONMENT_NAME%'...
call conda activate %ENVIRONMENT_NAME%
if errorlevel 1 (
    echo ERROR: Failed to activate environment.
    pause
    exit /b 1
)

echo.
echo Step 3: Installing GDAL from conda-forge...
call conda install -c conda-forge gdal -y
if errorlevel 1 (
    echo WARNING: GDAL installation may have had issues. Continuing anyway...
)

echo.
echo Step 4: Installing core dependencies...
call pip install --break-system-packages numpy matplotlib pillow scipy -y
if errorlevel 1 (
    echo WARNING: Some dependencies may not have installed. Continuing anyway...
)

echo.
echo ============================================================================
echo Environment Setup Complete!
echo ============================================================================
echo.
echo To use the environment, run one of these commands:
echo.
echo   From Anaconda Prompt:
echo   conda activate %ENVIRONMENT_NAME%
echo.
echo   Then navigate to your dem2dged directory and run:
echo   python dem2dged.py [input_raster] [output_folder] [options]
echo.
echo To deactivate the environment:
echo   conda deactivate
echo.
echo To remove the environment later (if needed):
echo   conda remove --name %ENVIRONMENT_NAME% --all
echo.
pause
endlocal
