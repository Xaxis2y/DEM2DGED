# dem2dged v0.55.0 Rebuild Guide

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

## Issues Found and Fixed

### Problem 1: Relative Paths in .spec File
**Issue**: The `dem2dged.spec` file used relative paths for bundled data files (templates and GDAL/PROJ data).

```python
# BEFORE (broken)
datas = [('DGED_GEO_TEMPLATE.xml', '.'), ('DGED_UTM_TEMPLATE.xml', '.'),
```

**Why it failed**: PyInstaller couldn't reliably locate these files when running from different directories.

**Fix**: Changed to absolute paths that are resolved at build time.

```python
# AFTER (fixed)
spec_dir = os.path.dirname(os.path.abspath(__file__))
geo_template = os.path.join(spec_dir, 'DGED_GEO_TEMPLATE.xml')
utm_template = os.path.join(spec_dir, 'DGED_UTM_TEMPLATE.xml')
datas = [(geo_template, '.'), (utm_template, '.'),
```

### Problem 2: No Console Output for Error Messages
**Issue**: The executable had `console=False` in the spec file, which means any errors during startup exit silently.

**Why it failed**: If the GUI failed to initialize, the exe would just close without showing any error.

**Fix**: Changed to `console=True` (keeps a console window visible). This allows you to see startup errors and debug issues.

```python
# BEFORE (silent failures)
console=False,

# AFTER (shows errors)
console=True,
```

### Problem 3: Missing Error Handling
**Issue**: The `_load_template()` function and GDAL initialization had no error handling.

**Fix**: Added comprehensive error messages showing:
- Where it's looking for files
- Whether it's running as a frozen exe
- GDAL/PROJ paths and whether they exist
- Detailed exception messages

```python
# ADDED: Debug output on startup
print("DEM2DGED v0.23 Startup")
print("Running as frozen executable:", is_frozen)
print("sys._MEIPASS:", sys._MEIPASS)
print("Working directory:", os.getcwd())

# ADDED: Better template loading with diagnostics
try:
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()
except FileNotFoundError:
    raise RuntimeError(
        "Template file not found: %s\n"
        "Expected at: %s\n" % (name, template_path))
```

### Problem 4: Version Number Update
**Issue**: Code was still at v0.22 even though improvements were made.

**Fix**: Bumped version to v0.23 in `dem2dged_lib.py`.

## How to Rebuild

### Step 1: Prepare Environment

```batch
:: Open Anaconda Prompt as Administrator

:: Verify the DGED conda environment exists
conda env list

:: Activate the environment
conda activate DGED

:: Verify required packages
python -c "import osgeo; print('GDAL OK')"
python -c "import PyInstaller; print('PyInstaller OK')"

:: Navigate to project directory
cd C:\Users\Son\Documents\DEM2DGED\dem2dged_v0.22
```

### Step 2: Run Build Script

```batch
cd C:\Users\Son\Documents\DEM2DGED\dem2dged_v0.22
python BUILD_AND_PACKAGE.py
```

This script will:
- ✓ Verify all dependencies
- ✓ Clean previous builds
- ✓ Rebuild the executable
- ✓ Create a distribution package

### Step 3: Test the Executable

```batch
:: Run the newly built exe
dist\dem2dged.exe
```

You should see:
```
======================================================================
DEM2DGED v0.23 Startup
Running as frozen executable: True
sys._MEIPASS: C:\Users\Son\...\dem2dged\_internal
Working directory: C:\Users\Son\Documents\DEM2DGED\dem2dged_v0.22
======================================================================
```

Then the GUI window should appear.

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'osgeo'"

**Cause**: GDAL is not installed in the active Python environment.

**Fix**:
```batch
conda activate DGED
conda list | grep gdal  # Should show osgeo
```

If not present:
```batch
conda install -c conda-forge gdal
```

### Issue: "No module named 'PyInstaller'"

**Cause**: PyInstaller is not installed.

**Fix**:
```batch
conda activate DGED
pip install pyinstaller
```

### Issue: "FileNotFoundError: Cannot find DGED_GEO_TEMPLATE.xml"

**Cause**: The spec file paths are not resolving correctly.

**Fix**:
1. Verify the XML files exist in the project root:
   ```batch
   dir C:\Users\Son\Documents\DEM2DGED\dem2dged_v0.22\*.xml
   ```

2. Check the spec file uses absolute paths (should already be fixed)

3. Rebuild:
   ```batch
   python BUILD_AND_PACKAGE.py
   ```

### Issue: "GDAL data path not found" or "PROJ data path not found"

**Cause**: GDAL/PROJ data directories are not being bundled correctly.

**Check**:
```python
# In the spec file, these should resolve correctly:
print("gdal_data_dir:", gdal_data_dir, "exists:", os.path.isdir(gdal_data_dir))
print("proj_data_dir:", proj_data_dir, "exists:", os.path.isdir(proj_data_dir))
```

If paths don't exist, GDAL is not installed correctly. Reinstall:
```batch
conda activate DGED
conda install -c conda-forge gdal proj
```

### Issue: Executable hangs or takes too long to start

**Possible Cause**: GDAL is initializing with missing data files.

**Solution**:
1. Check console output for warnings
2. Verify GDAL_DATA and PROJ_DATA environment variables point to correct paths
3. Ensure conda env has gdal and proj: `conda list | grep -E "gdal|proj"`

## File Changes Summary

### dem2dged.spec (FIXED)
- Line 7-10: Changed relative paths to absolute paths
- Line 55: Changed `console=False` to `console=True`

### dem2dged_gui.py (FIXED)
- Line 18-40: Added GDAL initialization with debug output
- Line 242-258: Enhanced template loading with error handling
- Line 476-495: Added startup diagnostics
- Line 958-964: Added main error handler

### dem2dged_lib.py (UPDATED)
- Line 22: Version bumped from 0.22 to 0.23

## Distribution

After successful build, you have:

- **dist/dem2dged.exe** - The standalone executable
- **output_packages/dem2dged_v0.23_win64.zip** - Complete distribution package

Users can extract the zip and run:
```batch
dem2dged\dem2dged.exe
```

No dependencies required (all GDAL/PROJ libraries included).

## Summary of v0.23 Changes

| Change | Reason | Impact |
|--------|--------|--------|
| Fixed spec file paths | PyInstaller couldn't find bundled files | Build now works reliably |
| Enabled console=True | Silent startup failures | Errors now visible |
| Added error handling | No diagnostics on failure | Better troubleshooting |
| Added debug output | Can't verify GDAL setup | Startup messages confirm correct initialization |
| Bumped version | Track changes | Clearer version management |
