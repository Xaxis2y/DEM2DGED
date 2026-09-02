# Build Scripts — which one do I run?

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

dem2dged v0.56.0

There are four `.bat` files and they are easy to mix up. The short answer:

> **Normal build: run `rebuild_exe.bat`. That's it.**
> Add `rebuild_validate_exe.bat` only if you want the standalone validator.

---

## The four scripts at a glance

| Script | Builds | Uses | When to run it |
|---|---|---|---|
| **`rebuild_exe.bat`** | `dem2dged.exe` (GUI + converter) | the curated `dem2dged.spec` | **Every normal build.** |
| `build_exe.bat` | `dem2dged.exe` | raw command-line flags | Only if `dem2dged.spec` is missing/corrupted |
| **`rebuild_validate_exe.bat`** | `dem2dged_validate.exe` (console) | the curated `dem2dged_validate.spec` | When you want the standalone validator |
| `build_validate_exe.bat` | `dem2dged_validate.exe` | raw command-line flags | Only if that spec is missing/corrupted |

The naming is the confusing part: **`rebuild_*` is the primary path, not the
fallback.** "Rebuild" refers to rebuilding *from the spec file*, which is the
normal, reproducible way to run PyInstaller. `build_*` is the bootstrap that
*generates* build settings from scratch.

---

## `rebuild_*` vs `build_*` — what actually differs

A PyInstaller `.spec` file is a build recipe. The two `.spec` files shipped
with the project are hand-maintained and pin things PyInstaller's automatic
analysis gets wrong:

- **Hidden imports** — `dem2dged_compare`, `numpy`, and the `osgeo._gdal` /
  `_osr` / `_ogr` C extensions. Static analysis can miss these, and a missing
  one produces an exe that builds cleanly and then dies on launch.
- **Bundled data** — `DGED_GEO_TEMPLATE.xml` and `DGED_UTM_TEMPLATE.xml` are
  packed into the exe and extracted at runtime under `sys._MEIPASS`.
- **GDAL / PROJ data folders** — auto-detected from `sys.prefix`, so the spec
  works from any conda environment instead of a hardcoded Anaconda path.

`rebuild_*.bat` feeds that recipe to PyInstaller. `build_*.bat` passes the
same information as long `--hidden-import` / `--add-data` flags instead. They
should produce equivalent exes — but the spec is the version-controlled,
reviewable source of truth, so it's the one to trust.

### Two bugs fixed in v0.34

1. **`build_*.bat` used to destroy the curated spec.** PyInstaller writes a
   generated `.spec` named after `--name`, so `build_exe.bat` wrote
   `dem2dged.spec` straight into the project folder, overwriting the curated
   file. Running the "fallback" script once permanently degraded every later
   `rebuild_exe.bat`. Both `build_*.bat` scripts now pass
   `--specpath build\autospec`, so the generated spec lands in
   `build\autospec\` and the curated file is never touched.

2. **The two paths disagreed about the console window.** `build_exe.bat` used
   `--windowed` while `dem2dged.spec` used `console=True` — so the same
   project produced two different exes depending on which script you ran.
   Both are now `console=True`, deliberately: `dem2dged_gui.py` prints
   diagnostics to stdout, and if GDAL fails to import it raises *before* the
   Tk window opens. Built `--windowed`, that failure is invisible — you
   double-click the exe and nothing happens, with no error anywhere. The
   console window costs a little polish and saves a lot of debugging.

---

## Do I need the validator exe?

**Usually no.** `dem2dged.exe` already runs the identical checks in-process
after every conversion and writes `DGED_Validation_Report.html` next to the
tiles. The GUI's "Validate after conversion" checkbox controls it; the CLI
does it unless you pass `--no-validate`.

Build `dem2dged_validate.exe` only if you want validation as a *separate*
step:

- QC a DGED delivery someone else produced
- Run validation in a batch script or CI job and branch on the exit code
  (`0` = passed, `1` = at least one FAIL)
- Re-validate an old delivery after a validator fix, without re-converting

```bat
dem2dged_validate.exe TILE_FOLDER -src SOURCE.tif -html-report report.html
```

As of v0.34 every option also accepts the double-dash spelling
(`--html-report` works as well as `-html-report`).

---

## Prerequisites for all four

All four scripts check these and stop with a clear message if they fail:

1. **A Python environment with GDAL.** Run `install.bat` (Windows) or
   `install.sh` (Linux/macOS) first if you don't have one:
   ```
   conda create --name DGED --channel conda-forge gdal python=3.10 -y
   conda activate DGED
   ```
   Building without GDAL produces an exe that fails at launch with
   `ModuleNotFoundError: No module named 'osgeo'`.

2. **PyInstaller**, installed into that same environment. The scripts do this
   for you with `python -m pip install pyinstaller`.

All four invoke PyInstaller as `python -m PyInstaller` rather than the bare
`pyinstaller` command. A bare `pyinstaller` on `PATH` may belong to a
completely different Python installation, which then builds an exe against
the wrong interpreter and the wrong GDAL.

---

## `BUILD_AND_PACKAGE.py` — the all-in-one alternative

For a full release, `python BUILD_AND_PACKAGE.py` does everything in one go:
verifies the environment, checks every required source file is present,
cleans `build/` and `dist/`, runs PyInstaller against `dem2dged.spec`, writes
`VERSION.json`, and zips the result into `output_packages/`.

Its preflight file list was extended in v0.34 — it previously checked only
five files and omitted `dem2dged_compare.py`, which the GUI has imported at
module level since v0.33. A missing module passed preflight and only failed
when the built exe was launched.

## `dem2dged_package.py` — source/docs release zip

Separate from the exe build: `python dem2dged_package.py` zips the *source*
release (scripts, templates, docs, tests) into `dem2dged_v0.34.zip` one level
above the project folder, excluding `build/`, `dist/`, `__pycache__`,
`.pytest_cache` and previous release zips.

`dem2dged_validate_package.py` does the same for the validator-only bundle.

Both were renamed in v0.34 — they were `dem2dged_package_v0.26.py` and
`dem2dged_validate_package_v0.26.py`, but they've derived their source
directory from `__file__` since v0.28, so the frozen `v0.26` in the filenames
was stale and misleading.
