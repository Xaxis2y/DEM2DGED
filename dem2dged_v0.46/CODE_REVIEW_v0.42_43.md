# Code review — dem2dged v0.41 → v0.42

**Date:** 2026-08-10
**Scope:** full re-audit of the v0.41 package ahead of release.
**Verdict on v0.41 as shipped:** **not releasable.** One blocker, and the
blocker had a root cause that v0.41's own repair had missed.

---

## Summary

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | **BLOCKER** | `tests/` was missing from the package again — `pytest` could not run | Fixed |
| 2 | **BLOCKER (root cause)** | `dem2dged_package.py` **excludes `tests/` from every release zip**. Rebuilding the directory could never stick. | Fixed |
| 3 | High | An untagged / non-EPSG source raster died on `int(None)` deep inside `get_bbox_of_output()` | Fixed |
| 4 | Medium | An unknown `-resample` value failed once **per tile**, then reported success over an empty folder | Fixed |
| 5 | Medium | `gdalwarp` missing from PATH → raw `FileNotFoundError` traceback on the first tile | Fixed |
| 6 | Medium | A run in which **every** tile failed still printed "All done!" and exited 0 | Fixed |
| 7 | Low | Auto-validation failures logged at INFO — the exact shape of the v0.40 blocker | Now WARNING |
| 8 | Low | Stray `lu49gpd00.tmp` (311 KB) would ship inside the zip (v0.41 finding 9, left open) | Closed |
| 9 | — | `RELEASE_CHECK` rewritten as v0.42: 5 new gate steps, stricter pass criteria | Done |

---

## 1–2. BLOCKER — `tests/` was missing, *and* the packager was deleting it

```
$ pytest
ERROR: file or directory not found: tests
```

`pytest.ini` sets `testpaths = tests`. `MANIFEST.md` documents five files
under "Tests & verification". `VERSION.txt`'s v0.38 entry describes a
specific bug fixed *in* `tests/conftest.py`. The directory was not in the
package.

This is finding 3 of the v0.41 review, verbatim — the same finding, one
release later. That is the interesting part: v0.41 rebuilt the directory by
hand and shipped, and it was gone again by v0.42.

### Why rebuilding it could never work

`dem2dged_package.py`:

```python
EXCLUDE_DIRS = {"build", "dist", "__pycache__", ".pytest_cache", "_v027_sync",
                 "DGED Loader", "ArcGIS_PRO_QA_toolbox", "DEM", "tests",
                 "tests", "_verify_pages"}
```

`"tests"`, listed **twice**. The duplicate is the tell: the comment above it
reads *"`"tests"` and `"tests"` (the local test harness + its generated
tiles/reports/logs)"* — two different things were meant, one of them was
mistyped, and the result names the source directory twice.

So the packaging step stripped the test suite out of every archive, while
`pytest.ini` and `MANIFEST.md` shipped intact. Anyone who unzipped a release
and ran `pytest` as `MANIFEST.md` instructs got the error above. Rebuilding
`tests/` by hand fixed the working folder and changed nothing about the
artefact that actually goes out.

**Both halves fixed.** `"tests"` is gone from `EXCLUDE_DIRS`; the generated
output directories it was meant to name (`test_output`,
`_release_check_logs`) are listed explicitly. And `tests/` is rebuilt as
five files:

* `tests/conftest.py` — synthetic GEO / UTM / equatorial / untagged /
  step-edge source DEMs generated with GDAL, no external data and no
  network, plus the **per-test** `output_dir` fixture with the v0.38
  rationale recorded in the docstring so it is not made session-scoped
  again.
* `tests/test_lib.py` — the DGED tables, the "every zone factor divides the
  tile evenly" invariant that v0.27's level 8/9 change restored, data types
  and the v0.39 predictor, `ToDMS`, half-post warp extents and their
  reproducibility (v0.37 Finding 1), filenames including v0.34 zero-padding,
  source-type codes, resampler policy, the v0.36 sanity check, the v0.41
  GDAL exception contract, the new v0.42 guards, and version consistency.
* `tests/test_validator.py` — the filename patterns round-tripped across
  every level × org × zone form against the converter's own name builders,
  `overall_result()`'s 3-tier rule (v0.37 Finding 4), and named regressions
  for v0.30, v0.31, v0.34, v0.38 and v0.41 — including
  `test_the_validator_module_is_complete`, which fails loudly if the v0.41
  blocker (a module missing an entire block of code) ever recurs.
* `tests/test_converters.py` — real GEO/UTM conversions, then inspection of
  what landed on disk, plus the round-trip that matters most: the tool's own
  validator run against the tool's own output.
* `tests/README.md` — how to run all three layers from the Anaconda Prompt,
  and why **a skip is not a pass**.

**Result: 317 passed, 32 skipped** in a GDAL-free environment (the 32 are
the integration layer, which needs the `gdalwarp` executable).

`RELEASE_CHECK_v0.42.py` step 11 now prints the exact file list the zip
would contain and **fails** if `tests/` is not in it, so this specific
regression cannot happen a third time silently.

---

## 3. High — an untagged source raster crashed with an unrelated message

```python
srs = proj_osgeo.GetAttrValue("AUTHORITY", 1)   # -> None
...
source.ImportFromEPSG(int(ext[4]))              # TypeError: int() ... 'NoneType'
```

`GetAttrValue("AUTHORITY", 1)` returns `None` whenever the raster's CRS
carries no EPSG authority node — a bare ESRI WKT, a local or engineering
CRS, a plain `.asc` grid, or a raster with no projection at all. Every one
of those is routine in operator-supplied data.

The `None` then travelled two calls before dying inside
`get_bbox_of_output()` as:

```
TypeError: int() argument must be a string, a bytes-like object or a real
number, not 'NoneType'
```

which names neither the file nor the problem. With `-source_vertical` it
first built the equally useless `"EPSG:None+5773"` and handed that to
gdalwarp.

**Fixed** with `dem2dged_lib.require_epsg()`, called from
`get_extent_and_srs_of_input_raster()` — where the **file name is still in
scope** — and again from `get_bbox_of_output()` as a backstop. The message
names the file, says what was found, and gives the `gdal_edit.py -a_srs` /
`gdalwarp -s_srs` command that fixes it. dem2dged cannot reproject a CRS it
cannot name (the tile grid, the sidecar EPSG field and the validator's
georeferencing check all key off the code), so this is a hard, early stop
rather than a guess.

---

## 4. Medium — a typo in `-resample` failed once per tile

`pick_resampler()` returns any override verbatim; the converters put it in
gdalwarp's `-r` slot; gdalwarp rejects it. The tile loop treats a failed
warp as a **skippable per-tile problem** — which it is, for a bad tile, and
is not, for a bad flag. So `-resample bilinier` on a 150-tile delivery
produced:

```
ERROR: gdalwarp failed for DGEDL5GtD_... - tile skipped (re-run to retry)
   ... x150 ...
All done!
```

exit code 0, output folder empty.

**Fixed** with `dem2dged_lib.validate_resampler()`, called from
`pick_resampler()` — the funnel both converters *and* the GUI go through, so
the check cannot be present in one entry point and absent from another. One
error, before any work, listing every valid value.

---

## 5. Medium — `gdalwarp` not on PATH produced a traceback

`run_cmd()` runs the command with `shell=False`, which raises
`FileNotFoundError` when the binary is not found. That propagated out of the
tile loop as a raw traceback on the very first tile — while both converters'
`--help` advertises *"Requirements: GDAL (gdalwarp) must be on PATH"* and
did nothing to produce that message.

This is the single most common setup problem for this tool: running from
`base` instead of the `DGED` conda environment.

**Fixed** two ways. `require_gdalwarp()` checks once, before any work, and
prints the `conda create` / `conda activate` / `conda install` sequence.
`run_cmd()` additionally catches `FileNotFoundError` and returns **127**
(the conventional "command not found" status), so the callers' documented
contract — "returns an exit code" — holds even if some future call site
skips the pre-flight.

---

## 6. Medium — a fully failed run reported success

Both converters `continue` past a failed warp, then fall through to
`print("All done!")` and return normally. If *every* warp failed, that is a
successful-looking run over an empty folder — and `dem2dged.py` then went on
to auto-validate it.

**Fixed.** Nothing produced is now a `SystemExit` naming the output folder,
the failure count and the likely causes. A *partial* run is not fatal (the
tiles that did warp are still valid deliverables) but prints how many are
missing and how to retry them. `RELEASE_CHECK_v0.42.py` treats a partial
conversion as a gate failure.

---

## 7. Low — auto-validation failures were logged at INFO

```python
logger.info("skipping auto-validation (could not import dem2dged_validate: %s)" % e)
logger.info("validation could not run: %s" % e)
```

This is *precisely* what the v0.40 blocker looked like from the outside: one
quiet line in the middle of a successful-looking conversion, no
`DGED_Validation_Report.txt`, no `.html`, and nothing that reads like a
problem. It took a byte-compilation check to find it.

Both are `logger.warning()` now, and both name the reports that were **not**
written plus the standalone command to produce them manually.

---

## 8. Low — the stray `.tmp` (v0.41 finding 9, closed)

`lu49gpd00.tmp` — 311 KB, actually a 14-page PDF with a `.tmp` extension —
deleted, and `EXCLUDE_FILE_SUFFIXES` extended to
`.zip/.pdf/.jpg/.jpeg/.tmp/.log/.bak`. Step 11 of the release gate flags any
scratch file that would reach the zip, so this is now checkable rather than
remembered.

---

## 9. The release gate, rewritten

`RELEASE_CHECK_v0.41.py` → `RELEASE_CHECK_v0.42.py`. Five new steps, and
three existing ones made stricter:

| Step | New / changed |
|---|---|
| 00 | Warns when run from conda `base`; **fails** if `gdalwarp`/`gdalinfo` are missing rather than discovering it four steps later |
| 00b | Also asserts the degrade-to-None contract for `quick_raster_range` and `clamp_tile_to_range`, not just `gdal_open` |
| **01b** | **New** — pyflakes across the whole project; an *undefined name* fails the gate |
| 03 | Reports the **skip count** explicitly and raises a WARN when the integration layer skipped — "0 failed" over 32 skips is not evidence |
| 04 | Also asserts both `--version` outputs actually report `dem2dged_lib.VERSION` |
| **04b** | **New** — the five pre-flight guards driven through the real CLI, each asserted to fail fast *and leave the output folder empty* |
| 05/07 | A **partial** conversion (some tiles failed) is now a gate failure, not a pass |
| 09 | Uses the tool's NoData-aware `compute_tile_stats()` instead of `ComputeRasterMinMax()`, and flags an all-NoData tile |
| **09b** | **New** — measures max &#124;diff&#124; on every shared tile edge directly, rather than reading the validator's verdict on it |
| **11** | **New** — prints the exact file list the release zip would contain; fails if `tests/` is absent or a scratch file would ship |

The summary line now distinguishes "ALL STEPS PASSED" from "ALL STEPS
PASSED, *n* warning(s)".

---

## What is verified, and what is not

**Verified in this session** (no GDAL available — pure Python only):

| Check | Result |
|---|---|
| Byte-compilation, all 23 modules | pass |
| pyflakes, whole project | clean (16 cosmetic "f-string missing placeholders") |
| `audit_pure.py` | `RESULT: 0 problem(s)` |
| `pytest`, unit layer | **317 passed**, 32 skipped (integration needs `gdalwarp`) |
| Version consistency, 12 declarations + `VERSION.txt` + `VALIDATOR_VERSION.txt` | 0 mismatches |
| Package manifest | 53 files, 0.9 MB, `tests/` present, no scratch files |

**Not yet verified — this is what `RELEASE_CHECK_v0.42.py` is for:**

* every real `gdalwarp` call and the tile geometry on disk
* the 32 skipped integration tests
* the validator running against tiles it did not fabricate
* the five pre-flight guards' actual CLI output
* shared-edge reconciliation on real warp output
* PyInstaller builds of `dem2dged.exe` and `dem2dged_validate.exe`
* the EGM96→EGM2008 vertical transform (needs PROJ grids **and** a source
  with a declared vertical datum — `run_verification.py` step 10 covers it
  if real DEMs are placed under `DEM\`)

A test suite that has never been run is not evidence of anything. Run the
gate, send `SUMMARY.txt`.

---

# Addendum — the v0.42 gate run, and v0.43

**Run:** 2026-08-10 23:11, GDAL 3.13.2 / PROJ 9.8.1, Python 3.10.20, conda
env `DGED`. **Result: ALL STEPS PASSED, 1 warning.**

Everything above was confirmed against real GDAL. The substantive
measurements:

| What | Measured |
|---|---|
| pytest | **350 passed, 1 skipped** (was 317 passed / 32 skipped without gdalwarp) |
| Pre-flight guards (04b) | all 5 fail fast, correct message, **output folder empty in every case** |
| GEO tiles | 4001 × 6001, origin `11.9999875` = 12.0 − 2.5e-5/2 — exact half-post |
| UTM tiles | 5001 × 5001, origin `499999.0` = 500000 − 2/2 — exact |
| Predictor | `LZW predictor=3` on every Float32 tile, on disk |
| Edge seams (09b) | max &#124;diff&#124; = **0.000000 m** on both pairs |
| Validation | GEO and UTM both `RESULT: PASS` |
| Package manifest | 55 files, 1.0 MB, `tests/` present, 0 scratch files |
| GDAL flags | `SHARED_FLAG=True` — confirms the v0.41 measurement on this build |

## The warning was a real hole, not a fixture quirk

```
WARN 03b integration coverage  1 test(s) skipped
SKIPPED [1] tests\test_converters.py:257: no vertically adjacent pair in this fixture
```

`reconcile_tile_edges()` has **two passes**: pass 1 copies each south tile's
top row onto its north neighbour's bottom row; pass 2 does the same for
west/east columns. Both edge fixtures produced tiles that were *side by side
only* — `geo_source` spans two tiles in longitude but one in latitude,
`utm_source` two in easting only. So every edge assertion in the suite
exercised pass 2, and **pass 1 had never executed at all**.

Step 09b said `PASS  2 pair(s), every shared edge bit-identical` — both of
them column seams. The gate could not tell "both passes ran" from "one pass
ran twice".

**v0.43 closes both halves:**

* New fixture `geo_grid_source` → a **2 × 2 tile grid at level 0**, where
  tiles are 121 × 81 posts instead of 4001 × 6001, so it costs almost
  nothing. It covers pass 1, pass 2, the corner post shared by all four
  tiles (which is what the pass *ordering* exists to protect), and — level 0
  being Int16 — the only edge reconciliation test on the integer path.
* Step 09b counts row and column seams **separately** and WARNs if either is
  zero.

## Two log-quality defects the run also exposed

* `gdal_edit.py  NOT ON PATH`. `require_epsg()`'s remedy led with
  `gdal_edit.py -a_srs` — a command that does not exist on a standard conda
  Windows install, because the GDAL Python utilities ship as modules under
  `osgeo_utils`, not as console scripts. An error message whose suggested
  fix also fails is worse than no suggestion. Now leads with
  `python -m osgeo_utils.gdal_edit`.
* `(conda list unavailable: rc=999)`. On Windows `conda` is a `.bat` shim,
  which `subprocess` with `shell=False` cannot execute — nothing was wrong
  with the environment. Step 00 now tries `conda` / `conda.bat` /
  `python -m conda` in order.

## Still not verified

`PyInstaller MISSING` in the environment log, so neither `dem2dged.exe` nor
`dem2dged_validate.exe` has been built. And step 10 skipped — no rasters
under `DEM\`, which is the only path that covers the EGM96→EGM2008 vertical
transform. Neither blocks a **source** release; both would block an
executable one.
