@echo off
REM SPDX-License-Identifier: GPL-2.0-or-later
REM Copyright (c) 2026 Eui Soo SON
setlocal

REM ============================================================
REM  dem2dged v0.37 - verification script
REM  SPDX-License-Identifier: GPL-2.0-or-later
REM  Copyright (c) 2026 Eui Soo SON
REM
REM  Runs the real pytest suite, then re-runs the exact DGIWG
REM  scenario that DGED_Conversion_Review.md's Findings 1 and 3
REM  were found on (same 3 sources, same 3 resampling methods,
REM  same level), into a NEW output_v037 folder so the original
REM  v0.36 (buggy) reports in tests\DGIWG Test Data\output\ are
REM  left untouched for side-by-side comparison.
REM
REM  Run from Anaconda Prompt with the DGED environment active:
REM      conda activate DGED
REM      verify_v037.bat
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo  Checking environment
echo ============================================================
python -c "from osgeo import gdal; print('GDAL/osgeo OK, version', gdal.__version__)"
if errorlevel 1 (
    echo.
    echo ERROR: osgeo/GDAL not importable in this environment.
    echo Make sure you ran:  conda activate DGED
    echo.
    pause
    exit /b 1
)

python -m pip install pytest -q

if not exist tests\logs mkdir tests\logs

echo.
echo ============================================================
echo  [1/2] Running pytest
echo ============================================================
pytest -v > tests\logs\pytest_v037_log.txt 2>&1
type tests\logs\pytest_v037_log.txt
echo.
echo pytest log saved to: tests\logs\pytest_v037_log.txt

echo.
echo ============================================================
echo  [2/2] Re-running the DGIWG regression scenario (Findings 1 and 3)
echo ============================================================
set "DATA=tests\DGIWG Test Data"
set "OUT=%DATA%\output_v037"

for %%S in (ACAIPGTM.tif.tiff DGED_L4bU_n5563358_U_P_01.tif.tiff utm33_gdal_tiff_rsid_v2.2.1.tiff) do (
    for %%M in (near bilinear cubic) do (
        echo.
        echo --- %%S / %%M ---
        python dem2dged.py "%DATA%\%%S" "%OUT%\%%S\%%M" --mode geo --level 4b --resample %%M > "tests\logs\%%S_%%M.log" 2>&1
        type "tests\logs\%%S_%%M.log"
    )
)

echo.
echo ============================================================
echo  DONE.
echo.
echo  Compare these NEW (v0.37) reports:
echo    "%OUT%\<source>\<method>\DGED_Validation_Report.txt"
echo  against the ORIGINAL (v0.36, buggy) ones already in:
echo    "%DATA%\output\<source>_dged_output\test_N_<method>\DGED_Validation_Report.txt"
echo.
echo  What should be different in the new reports:
echo   - Finding 1: Section G on DGED_L4bU_n5563358 tiles should show
echo     NO "shared row/col differs" failures (was up to 1.6 m).
echo   - Finding 3: Section H min/max on ACAIPGTM and utm33 Cubic runs
echo     should now be clamped to source range (was -41.18..285.31 m
echo     vs true 0..255 m, and -44.38..313.70 m vs true 6..255 m).
echo   - Finding 2: H2 should now diff each run against a re-warp using
echo     THAT run's own resample method, not always bilinear.
echo   - Finding 4: the .txt RESULT line and any HTML badge for the
echo     same run should always agree (PASS/WARN/FAIL).
echo ============================================================
pause
