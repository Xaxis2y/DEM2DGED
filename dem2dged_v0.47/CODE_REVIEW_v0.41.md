# Code review — dem2dged v0.40 → v0.41

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

**Date:** 2026-08-07
**Scope:** full re-audit of the extracted v0.40 package ahead of release.
**Verdict on v0.40 as shipped:** **not releasable.** One hard blocker, plus
two problems that made the release's own quality claims untrue.

---

## Summary

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | **BLOCKER** | `dem2dged_validate.py` did not byte-compile — an entire block of code was missing | Fixed |
| 2 | High | The version-consistency self-audit was structurally incapable of passing, and reported 7 files as version `None` | Fixed |
| 3 | High | `tests/` did not exist; `pytest` failed immediately | Fixed |
| 4 | Medium | A corrupt tile crashed the whole validation run instead of failing that tile | Fixed |
| 5 | Low | `MANIFEST.md` still described the v0.34 package | Fixed |
| 6 | Low | Unused imports / locals across six modules | Fixed |
| 7 | Low | 469 MB of `build/`, `dist/`, `__pycache__` in the release folder | Removed |
| 8 | Low | Frozen `v0.40` literals in the verification harness banner | Now read from `dem2dged_lib.VERSION` |
| 9 | Open | `.tmp` is not in `dem2dged_package.py`'s exclusion list; `lu49gpd00.tmp` would ship | Documented, not changed |
| 10 | **High** | GDAL exception handling was set per-entry-point, so the same library code took two different error paths — found by the real-GDAL run | Fixed |
| 11 | Medium | The validator's `-src` source DEM had the same unguarded-`None` crash as finding 4 | Fixed |
| 12 | — | `tests/test_converters.py` called `main()` with a parsed `Namespace`; it takes a raw argv list. 22 integration tests errored on first execution | Fixed |

---

## 1. BLOCKER — the validator did not compile

```
$ python -m py_compile dem2dged_validate.py
Sorry: IndentationError: unexpected indent (dem2dged_validate.py, line 247)
```

An entire block was missing from the file, between the end of the module
docstring and the body of `overall_result()`:

* the module docstring's closing `"""`
* **every import** — `argparse`, `glob`, `math`, `os`, `re`, `sys`,
  `xml.etree.ElementTree as ET`, `numpy as np`, `from osgeo import gdal, osr`,
  and the twelve names taken from `dem2dged_lib` (`VERSION`,
  `VERSION_DISPLAY`, `PL`, `level_tilesize_and_spatial_resolution`,
  `zone_lon_spacing`, `output_type_for_level`, `utm_name_field_widths`,
  `describe_source_type`, `compute_tile_stats`,
  `OVERSHOOT_PRONE_RESAMPLERS`, `TOC_FILENAME`)
* the `NODATA`, `ELEV_MIN_SANE`, `ELEV_MAX_SANE` constants
* `_STATUS_ORDER`
* the `GEO_RE` and `UTM_RE` filename patterns
* the `def overall_result(n_pass, n_warn, n_fail):` line itself

Python therefore read the module docstring as running on for another twelve
lines into `overall_result()`'s own docstring, and stopped at the first line
of code it found indented under nothing.

### Why this was not obvious

Every consumer of the validator swallows the failure:

* `dem2dged.py` line 212 — `import dem2dged_validate as dv` sits inside a
  `try/except`, so a full conversion printed one line,
  `skipping auto-validation (could not import dem2dged_validate: ...)`, and
  wrote **neither** `DGED_Validation_Report.txt` nor `.html`.
* `dem2dged_gui.py` imports it at module level inside a guard; on failure the
  "Validate after conversion" checkbox is simply disabled — no error.
* `audit_pure.py` does `import dem2dged_validate as dv` at line 20 and dies
  on import, so the project's own self-audit could not run at all.
* `dem2dged_validate.spec` builds `dem2dged_validate.exe` from this file, so
  the validator executable could not be produced either.

There was no `dem2dged_validate.cpython-*.pyc` in `__pycache__` while every
other module had one — a direct fingerprint of a module that had never
successfully imported.

### The repair

The block was reconstructed. The two non-obvious pieces:

**`GEO_RE` / `UTM_RE`** were rebuilt from spec 12.1 and from
`dem2dged_lib.geo_tile_basename()` / `utm_tile_basename()`, then verified by
generating names for **every** product level (0-3, 4b, 4-9) × 8 tile origins
(both hemispheres, prime meridian, ±1°, high latitude) × with and without the
optional 3-letter organisation code, and for UTM additionally × 4 zone forms
(`32N`, `09S`, `01N`, `60S`) × 5 origins including the equator and a
near-10 000 000 m northing — asserting on each that the pattern matches, that
`lv` / `org` / `zone` parse back correctly, that the encoded coordinate
round-trips to the tile origin, and that the field widths equal
`utm_name_field_widths()`. Plus:

* the pre-v0.34 unpadded name `DGEDL5UtD_32N500_400_A_U_01` must still
  **parse** (so the width check can report a precise error rather than an
  opaque "does not match convention") — v0.34 changelog requirement;
* the pre-v0.27 GEO L0-3 legacy `Gt<letter>` form must still parse;
* six malformed names must be rejected;
* a GEO name must never match `UTM_RE` and vice versa.

Result: **0 problems** across all combinations.

**`NODATA` / `ELEV_MIN_SANE` / `ELEV_MAX_SANE`.** `NODATA = -32767` is
determined — it is the literal the converters pass to `gdalwarp -dstnodata`
(`dem2dged_geo.py:260`, `dem2dged_utm.py:340`, `dem2dged_gui.py:237`) and
what `README.md` documents. The sane band is `[-500, 9000]` m, matching the
report's own explanatory text for this check: *"Some elevations are far
below the Dead Sea or above Everest"* (`dem2dged_validate.py`'s
`_EXPLAIN_RULES`). A test asserts the band brackets both real extremes and
stays well above `NODATA`, so the check cannot be silently neutered.

---

## 2. High — the version audit was checking nothing

`audit_pure.py` section 7 searched seven modules for a version declaration
with `re.search(r"^Version:\s*(\d+\.\d+)", ..., re.M)` — **column 0**, which
cannot occur in a `.py` file outside a string literal. Meanwhile the
`# Version: <n>` header comment that v0.32 introduced (and that `README.md`
and `VERSION.txt` both describe at length) was absent from all seven files.

So the check reported:

```
FAIL  dem2dged.py declares version None but dem2dged_lib.VERSION is '0.40'
   ... (7 files)
```

which means the v0.40 release note's claim that *"the version-consistency
self-audit is clean"* was not true — the audit could not run at all, because
of finding 1.

Both sides fixed: the headers are restored in all seven modules, and the
pattern is now `^#?\s*Version:\s*(\d+\.\d+)` so it actually matches a header
comment. `tests/test_lib.py` asserts the same thing independently.

---

## 3. High — `tests/` did not exist

`pytest.ini` sets `testpaths = tests`, `MANIFEST.md` documents four test
files, and the v0.38 changelog describes a specific bug fixed *in*
`tests/conftest.py` — but the directory was not in the package. `pytest`
failed with `file or directory not found: tests`.

Rebuilt as five files:

* `tests/conftest.py` — synthetic GEO / UTM / equatorial source DEMs
  generated with GDAL (no external data, no network), and the **per-test**
  `output_dir` fixture (`tempfile.mkdtemp()`), with the v0.38 rationale
  recorded in the docstring so it is not made session-scoped again.
* `tests/test_lib.py` — 100+ library units: DGED tables, the "every zone
  factor divides the tile evenly" invariant that v0.27's level 8/9 change
  restored, data types, the v0.39 predictor, `ToDMS`, half-post warp extents
  and their reproducibility (v0.37 Finding 1), filenames including v0.34
  zero-padding, source-type codes, resampler selection, the v0.36 sanity
  check, and version consistency.
* `tests/test_validator.py` — the filename patterns round-tripped per level,
  `overall_result()`'s 3-tier rule (v0.37 Finding 4), and named regressions
  for v0.30 (delivery-level XML pairing), v0.31 (placeholder detection and
  the pixel-centre origin tolerance), v0.34 (both dash spellings), v0.38
  (`_emit()` surviving an unencodable console) and v0.41 (the module exposes
  everything its callers import).
* `tests/test_converters.py` — real GEO/UTM conversions, then inspection of
  what landed on disk: pairing, name↔georeferencing agreement, header
  profile, level-aware data type, tile dimensions incl. the one-post overlap,
  no pure-NoData row/column (v0.34), bit-identical shared edges (v0.37
  Finding 1), sidecar well-formedness, delivery-level metadata, the cubic
  clamp (v0.37 Finding 3), and the v0.39 negative-northing clamp.
* `tests/README.md` — how to run all three layers from the Anaconda Prompt.

**Result here: 185 passed, 22 skipped** (the 22 need real `gdalwarp`).

---

## 4. Medium — a corrupt tile crashed the validator

`check_tile()` guarded `gdal.Open(tif)` with `try/except`, but this module
deliberately does not call `gdal.UseExceptions()` (neither does
`dem2dged_lib.py`, and `check_source()` relies on `gdal.BuildVRT` returning
`None`). So a truncated or non-raster `.tif` returned `None`, fell through
the `except`, and killed the entire validation run with an `AttributeError`
on `ds.GetGeoTransform()` — instead of failing one tile and carrying on.

Now an explicit `if ds is None:` → FAIL for that tile. Covered by
`test_a_corrupt_tile_is_reported_not_crashed`.

---

## 10. High — GDAL exception handling depended on the entry point

Found by the first run of `RELEASE_CHECK_v0.41.py` against real GDAL
(3.13.2 / PROJ 9.8.1). All four real-GDAL logs carried:

```
FutureWarning: Neither gdal.UseExceptions() nor gdal.DontUseExceptions()
has been explicitly called. In GDAL 4.0, exceptions will be enabled by default.
```

`gdal.UseExceptions()` is **process-wide**, and the project did not agree on
it: `dem2dged_gui.py` and `run_verification.py` called it; `dem2dged.py`,
`dem2dged_geo.py`, `dem2dged_utm.py` and `dem2dged_validate.py` did not.
Because the GUI imports `dem2dged_lib`, the *same library code* took two
different error paths depending only on which entry point the user started
from. With exceptions on, every `if ds is None:` guard in `dem2dged_lib.py`
is dead code and a marginal raster raises instead of degrading:

| Function | CLI (exceptions off) | GUI (exceptions on) |
|---|---|---|
| `reconcile_tile_edges._read_edge` | returns `None`, that edge is skipped | raises, aborting the whole phase-2 pass |
| `quick_raster_range` | returns `None`, sanity check warns | raises, crashing the pre-flight check |
| `clamp_tile_to_range` | returns `0` | raises mid-conversion |
| `fix_header` | prints a warning, continues | raises after the tile was written |

And GDAL 4.0 would have silently moved the CLI onto the GUI's behaviour.

**First attempt, and what measurement said.** The obvious fix looked like
"enable `gdal` exceptions, pin `ogr`/`osr` off" — `osr` has to stay off
because `check_tile()` *warns* (never fails) on a missing EGM2008 tag and
then builds `osr.SpatialReference(wkt=ds.GetProjection() or "")` from it,
which raises under `osr` exceptions. A test asserting the result failed
immediately on the next real run:

```
tests\test_lib.py:104: in test_gdal_exceptions_are_explicitly_configured
    assert gdal.GetUseExceptions() == 1
E   AssertionError: assert 0 == 1
```

On GDAL 3.13.2 the three modules **share one global flag**. The later
`osr.DontUseExceptions()` had turned `gdal`'s exceptions back off — so
"gdal on, osr off" is not a state that exists, and the first fix had
silently reverted to the old behaviour while looking like it hadn't. This is
exactly why the release gate runs against real GDAL instead of being
reasoned about.

**Actual fix.** One setting for all three, and that setting is **off** —
the whole codebase is written against the "returns None" contract, and the
`osr` constraint above is real. What matters is that it is now *explicit*:
the `FutureWarning` is gone from every log, and GDAL 4.0 cannot flip the
default underneath the tool. On top of that:

```python
def gdal_open(path, mode=gdal.GA_ReadOnly):
    try:
        return gdal.Open(path, mode)
    except RuntimeError:
        return None
```

Every guarded open in the library (8 sites), the validator (6), the
comparison module (1) and the GUI (3) goes through it, so the `is None`
contract holds regardless of the GDAL version, of import order, or of
another library in the same process flipping the global.

`dem2dged_gui.py`, `run_verification.py` and `tests/conftest.py` no longer
call `UseExceptions()` themselves — the library owns the setting, so nothing
fights over it.

Covered by `test_gdal_exceptions_are_explicitly_configured`,
`test_gdal_ogr_osr_share_one_exception_flag` (fails loudly if a future GDAL
separates them), `test_gdal_open_returns_none_instead_of_raising`,
`test_quick_raster_range_degrades_instead_of_crashing`,
`test_clamp_tile_to_range_degrades_on_an_unreadable_tile`, and step `00b` of
the release gate, which records the measured flag behaviour per environment.

---

## 11. Medium — the validator's `-src` had the same crash as finding 4

`check_source()` opened the source DEM inside a `try/except` with no `is
None` check, so an unreadable `-src` returned `None` and then raised
`AttributeError` on `src.GetGeoTransform()` a few lines later — aborting the
run instead of reporting a bad source. Now a clean FAIL.

---

## 12. Defect in the new test suite itself

The 22 integration tests had never actually *executed* — the first release
run skipped them (no `pytest` in the environment), the second ran them and
all 22 errored identically:

```
dem2dged_geo.py:88: in main
    pargs = parser.parse_args(args[1:])
E   TypeError: 'Namespace' object is not subscriptable
```

`dem2dged_geo.main()` / `dem2dged_utm.main()` take a **raw argv list**, not a
parsed `Namespace` — they call `parse_args(args[1:])` themselves, so element
0 must be the program name (which is how `dem2dged.py` calls them:
`["dem2dged_geo.py", input, output, ...]`). The helpers now build argv lists
and the contract is documented at the top of the file.

Two assertions in the same suite were also rewritten to stop depending on
`ComputeRasterMinMax()`, whose behaviour on an all-NoData band varies with
the GDAL version and the exception setting; they use the tool's own
NoData-aware `dl.compute_tile_stats()` instead.

Worth stating plainly: a test suite that has never been run is not evidence
of anything. These two release-gate runs are what turned it into evidence.

---

## 5–8. Housekeeping

* `MANIFEST.md` rewritten: it claimed "dem2dged v0.34 — 40 files" and omitted
  `run_verification.py`, `verify*.bat`, `DGIWG_STANDARDS_TRACKING.md`,
  `DGED_Conversion_Review.md`, `CODE_REVIEW_v0.39.md`, `install.*`,
  `dem2dged_essential_package.py` and `dem2dged_anaconda_environment.*`.
* Unused imports/locals removed from `audit_pure.py`, `dem2dged_package.py`,
  `dem2dged_validate_package.py`, `dem2dged_anaconda_environment.py`,
  `BUILD_AND_PACKAGE.py`, `run_verification.py`. **pyflakes is now clean
  project-wide** apart from cosmetic "f-string is missing placeholders".
* `build/`, `dist/`, `__pycache__/`, `.pytest_cache/` deleted — 470 MB → 1.5 MB.
  `rebuild_exe.bat` regenerates them.
* `run_verification.py`'s banner read a frozen `v0.40`; it now reads
  `dem2dged_lib.VERSION`.
* The validator staging folder was renamed `dem2dged_validate_v0.40/` →
  `dem2dged_validate_v0.41/` and re-synced (it carried the same broken
  validator).

---

## 9. Open item — `.tmp` files reach the release zip

`dem2dged_package.py`'s `EXCLUDE_FILE_SUFFIXES` is
`(".zip", ".pdf", ".jpg", ".jpeg")`. A stray 311 KB scratch file,
`lu49gpd00.tmp` (actually a 14-page PDF with a `.tmp` extension), sits in the
project folder and **would be bundled into `dem2dged_v0.41.zip`**.

Left as-is per instruction. Two ways to close it:

```python
# dem2dged_package.py
EXCLUDE_FILE_SUFFIXES = (".zip", ".pdf", ".jpg", ".jpeg", ".tmp", ".log", ".bak")
```

or simply delete the file before packaging. This is noted in `MANIFEST.md`.

---

## What is verified, and what is not

**Verified in this session** (no GDAL available — pure Python only):

| Check | Result |
|---|---|
| Byte-compilation, all 23 modules, `SyntaxWarning` as error | pass |
| pyflakes, whole project | clean |
| Import smoke test, every module | pass |
| `audit_pure.py` | `RESULT: 0 problem(s)` |
| `pytest` unit layer | 185 passed |
| Filename patterns, exhaustive round-trip | 0 problems |
| Version consistency, 18 declarations | 0 mismatches |

**Verified against real GDAL** — `RELEASE_CHECK_v0.41.py`, run by the
operator on GDAL 3.13.2 / PROJ 9.8.1, Python 3.10.20:

| Step | Result |
|---|---|
| 00 environment | GDAL importable, `gdalwarp`/`gdalinfo` on PATH |
| 01 byte-compile | 23 modules |
| 02 `audit_pure.py` | `RESULT: 0 problem(s)` |
| 03 pytest | run 1: FAIL, `pytest` not installed. run 2: FAIL, 23 failed / 189 passed — findings 10 and 12 |
| 04 CLI surface | 6 entry points |
| 05/06 GEO convert + validate | 2 tiles, **PASS=33 WARN=0 FAIL=0** |
| 07/08 UTM convert + validate | run 1: 1 tile, WARN. run 2 (wider fixture): **2 tiles, PASS** |
| 09 tile inspection | all tiles conform |
| 10 `run_verification.py` | skipped — no rasters under `DEM\` |

The gate was run twice. Run 1 surfaced finding 10 (the `FutureWarning` in
every log) and showed the UTM `WARN` was only "one tile, no adjacent pair to
compare". Run 2, with `pytest` installed and the wider UTM fixture,
surfaced finding 12 and disproved the first attempt at finding 10 — the
`FutureWarning` was gone from all logs and UTM validated PASS across two
tiles with a reconciled shared edge.

Substantive confirmations from that run, none of which had ever been checked
against real output before:

* **v0.37 Finding 1** — section G reported *"shared column identical"* on the
  two real warped GEO tiles. Edge reconciliation works on real gdalwarp
  output.
* **v0.39 predictor** — `compress LZW predictor=3` on every Float32 tile,
  confirmed on disk.
* **Half-post extent (v0.27)** — GEO origin `11.9999875` = 12.0 − 2.5e-5/2,
  UTM origin `499999.0` = 500000 − 2/2. Exact.
* **Tile geometry** — GEO 4001 × 6001 (longitude zone factor 1.5 at 55°N
  correctly applied), UTM 5001 × 5001. Both match the level tables.
* **Section H/H2** — max |diff| 0.00 m, mean |Δ| 0.05 m.

The UTM `WARN` was *"no adjacent tile pairs with valid data found to
compare"* — the synthetic UTM source was 4 km wide against a 10 km level-5
tile, so only one tile existed. Not a defect, but it meant UTM edge
reconciliation went unexercised; the fixture is now 12 km wide and
`test_utm_adjacent_tiles_share_an_identical_edge` covers it.

**Still not verified:** PyInstaller builds of `dem2dged.exe` and
`dem2dged_validate.exe`, and the EGM96→EGM2008 vertical transform (needs
PROJ grids and a source with a declared vertical datum — `run_verification.py`
step 10 covers it if real DEMs are placed under `DEM\`).
