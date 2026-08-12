# DEM2DGED — Code Review and Resolution Log (v0.33 audit → v0.34)

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

Audit date: 2026-07-20
Scope: all Python modules, both XML templates, packaging and build scripts, docs.
Outcome: 10 issues found, **all 10 fixed in v0.34**.

---

## Verification method

The review environment had no GDAL and no root access, so the GDAL-dependent
`pytest` suite could not be executed there. Rather than reviewing by reading
alone, a GDAL-free harness — **`audit_pure.py`, shipped with this release** —
stubs `osgeo` and exercises the pure-Python logic directly. Run it any time:

```
python audit_pure.py
```

It needs no GDAL and no test data. Current result: **0 problems**.

| Check | v0.33 | v0.34 |
|---|---|---|
| Syntax / compile, all modules | PASS | PASS |
| pyflakes undefined names | PASS | PASS |
| GEO name → validator regex → coordinate round-trip (110 cases) | PASS | PASS |
| GEO warp extent vs validator's expected post count (all levels × zones) | PASS | PASS |
| GEO post alignment, all 6 zone factors | PASS | PASS |
| UTM warp width vs `posts`, all 7 levels | PASS | PASS |
| UTM tile-grid modulo alignment | PASS | PASS |
| XML templates: placeholders, well-formedness, level keyword | PASS | PASS |
| `pick_resampler` / `output_type_for_level` / `ToDMS` / `lon_multi` | PASS | PASS |
| **UTM filename field widths vs spec 12.1** | **24 FAIL** | **PASS** |
| **Version consistency across 12 declarations** | 2 drifted | **PASS** |
| **Tile-count bound (no empty edge row/col)** | not checked | **PASS** |

The core geometry was correct throughout. The v0.27 half-post registration
fix, the v0.28 GUI/CLI unification, and the v0.30/v0.31 validator
false-positive fixes all held up under test. None of the issues below
corrupted elevation values.

---

## 1. UTM tile names not zero-padded — FIXED (behaviour change)

**Severity:** medium — the only genuine spec-compliance defect in shipped output.

`dem2dged_lib.utm_tile_basename()` built the coordinate subfields with a bare
`int()`:

```python
n_part, e_part = int(t_miny / 1000), int(t_minx / 1000)
```

Spec 12.1 defines the form `ZZh nnnn _ eee` — fixed-width, zero-padded. Any
northing below 1 000 000 m produced a short field:

```
produced:  DGEDL5UtD_32N500_400_A_U_01     ← northing "500", 3 digits
required:  DGEDL5UtD_32N0500_400_A_U_01
produced:  DGEDL4bUtC_32N0_600_A_U_01      ← northing "0", 1 digit
```

Every UTM delivery within roughly 9° of the equator was affected, at levels
4b / 4 / 5 / 6.

The validator never caught it: `UTM_RE` matched `(?P<northing>-?\d+)`, so any
width passed. **Converter and validator were consistently wrong together** —
precisely the failure mode the v0.28 fallback-table removal was meant to
prevent.

**Fix.** `utm_tile_basename()` now formats to fixed width via a new shared
helper `utm_name_field_widths(level)` (4/3 digits for the km-form levels 4b–6,
7/6 for the metre-form levels 7–9). `dem2dged_validate.py` imports that *same
helper* and checks the widths explicitly, so the two cannot drift apart again.

The regex stays permissive (`\d{1,7}`) on purpose: a pre-v0.34 tile now gets a
precise diagnostic —

> `northing field '500' is 3 digit(s), spec 12.1 requires 4 (zero-padded) — regenerate with dem2dged v0.34+`

— rather than an opaque "filename does not match DGED naming convention" that
says nothing about what is actually wrong.

> ⚠️ **This changes filenames.** Tiles delivered by v0.33 or earlier keep their
> old names. Re-run the conversion to regenerate affected deliveries.

---

## 2. `test_geo_conversion_produces_output` asserted the impossible — FIXED

`tests/test_converters.py` asserted `len(tif_files) == len(xml_files)`. Since
v0.27 every delivery also writes `TABLE_OF_CONTENTS.xml` and, for multi-tile
products, `<product>_COLLECTION.xml` — neither has a matching `.tif` by design.

On the bundled fixture (1°×1° at 40N/10E, level 5) the converter correctly
produces **121 `.tif` and 123 `.xml`**, so the assertion failed on every
*correct* run.

The validator already knew about this — v0.30 added `is_product_level_xml()`
for exactly this reason — but the test was never updated.

**Fix.** A `tile_xmls()` helper filters via the validator's own
`is_product_level_xml()`, so test and validator share one definition. A
separate assertion now confirms both delivery-level files *are* written, so
the exclusion can't mask their absence.

---

## 3. GUI carried stale pre-v0.27 fallback tables — FIXED

`dem2dged_gui.py`'s `except ImportError` fallback still described levels 8 and
9 as 1-minute `"G"` tiles instead of the current 1.5-minute `"F"`:

```
L8 with 1-min tile:  lat 55 (factor 1.5) → 5333.33 intervals   ← non-integer
                     lat 75 (factor 3)   → 2666.67 intervals   ← non-integer
L8 with 1.5-min tile: all six zone factors integer             ← correct
```

Non-integer intervals mean tile origins cannot sit on the longitude post grid
— exactly the post-misalignment bug v0.27 fixed — plus a wrong tile letter in
the filename.

It was also **dead code**: `import dem2dged_lib as dl` above it is unguarded,
so the GUI dies there if the import fails and the fallback is unreachable.
v0.28 deleted the validator's equivalent fallback for this reason; the GUI's
copy was missed.

**Fix.** Deleted. The tables are imported unconditionally from
`dem2dged_lib`, with the GSD display labels moved to a small lookup dict.

---

## 4. Comparison scratch file written into the delivery folder — FIXED

`dem2dged_compare._holdout_stats()` wrote `_dged_holdout_train.tif` **inside
the DGED tile folder** and removed it only on the success path. If the
hold-out warp raised, the file survived — and in comparison mode the GUI then
validated that same folder, reporting `filename does not match DGED naming
convention` + `missing .xml sidecar`. One warp hiccup became a bogus FAIL
badge on a folder whose real tiles were fine.

`tempfile` was already imported and never used — clearly the original intent.

**Fix.** `tempfile.mkdtemp()` with `shutil.rmtree` in a `finally` block. Also
dropped two unused parameters from `_roundtrip_stats()`.

---

## 5. A row and column of pure-NoData tiles on every run — FIXED

All four converters used `ilat_e = math.floor(maxlat / tiledim) + 1`. The `+1`
unconditionally adds a tile past the data — so whenever the source aligns
exactly to the tile grid (whole-degree DEM sheets, the common case) that whole
row and column is outside the extent. On the bundled 1°×1° fixture: **21 of
121 tiles (17%)**, each costing a full warp, a `compute_tile_stats()` pass, a
sidecar and a TOC entry.

**Fix.** `max(start + 1, math.ceil(max / tiledim))` in all four converters —
identical when the maximum is *not* on a boundary, one fewer row/column when
it is, and still ≥1 tile for a degenerate zero-area extent. Verified:

```
extent 40.0–41.0, tiledim 0.1  → 10 tiles (was 11)
extent 40.0–41.05, tiledim 0.1 → 11 tiles (unchanged)
extent 40.0–40.0, tiledim 0.1  →  1 tile  (degenerate, guarded)
```

---

## 6. Validator flag documented with a prefix argparse rejects — FIXED

`VALIDATOR_VERSION.txt` documented `--html-report`; the parser registered
`-html-report`. argparse treats those as unrelated option strings with no
fallback, so the documented form failed outright:

```
dem2dged_validate: error: unrecognized arguments: --html-report o.html
```

**Fix.** Every option is registered under both spellings, and `--version` was
added. All seven forms verified accepted.

---

## 7. Version drift had already reappeared — FIXED, and now enforced

v0.32 was an entire release dedicated to resynchronising version strings. By
v0.33 two had drifted again: `VALIDATOR_VERSION.txt` and the validator
packaging script said `0.32` while the validator printed `0.33` at runtime.

**Fix.** Rather than correcting these by hand a third time, three new tests in
`tests/test_lib.py` assert that `dem2dged_lib.VERSION` matches `VERSION.txt`,
`VALIDATOR_VERSION.txt`, both packaging scripts, and every module's `Version:`
header. `audit_pure.py` checks the same 12 declarations without needing GDAL.
The recurring chore is now a failing test.

---

## 8. Build preflight didn't check `dem2dged_compare.py` — FIXED

`BUILD_AND_PACKAGE.py` checked five files and omitted `dem2dged_compare.py`,
which the GUI has imported at module level since v0.33. A missing module
passed preflight and failed only when the built exe was launched.

**Fix.** The preflight now checks all twelve required files, grouped by role
(entry points / shared modules / bundled data / build definitions).

---

## 9. GUI/CLI parity gap — FIXED

`convert_geo()` / `convert_utm()` hardcoded `org=""` and never passed
`abs_hacc` / `abs_vacc` / `lineage`, all of which the CLI has exposed since
v0.27/v0.28. A GUI operator could not embed a producer organisation code in
filenames or record measured accuracy values in the metadata quality report
at all.

**Fix.** Four new fields — Organisation, Abs. H accuracy, Abs. V accuracy,
Lineage — wired through to the same `dl.geo_tile_basename()` /
`dl.sidecar_replacements()` / `dl.write_collection_metadata()` arguments the
CLI uses. Blank accuracy fields fall back to `"auto"` (the DGED Table 5/6 goal
value for the level); blank lineage generates the same text the CLI does.

---

## 10. Unused imports — FIXED

Removed across eight modules: `typing.List/Tuple/Optional` (`dem2dged.py`),
`math`/`osr` (`dem2dged_compare.py`), `sys` (`dem2dged_geo.py`,
`dem2dged_utm.py`), `datetime` (`dem2dged_gui.py`), `os`
(`BUILD_AND_PACKAGE.py`), `glob` (`tests/test_validator.py`). `tempfile` in
`dem2dged_compare.py` is now genuinely used (see #4).

---

## Also addressed

**Axis-order fragility.** `bbox_to_wgs84()` forced traditional GIS order while
`get_bbox_of_output()` and `autodetect_utm()` relied on GDAL 3's *authority*
order purely by default. Both groups were correct and self-consistent, but a
global axis-mapping config would have silently swapped lat/lon in the second
group with no error — just tiles written in the wrong place. Both strategies
are now set explicitly via new `set_traditional_axis_order()` /
`set_authority_axis_order()` helpers, with the reasoning documented at the
call sites. **Requires GDAL 3+.**

**Build-script confusion** — see `BUILD_SCRIPTS_GUIDE.md`. Two real bugs were
found and fixed while documenting the four `.bat` files:

1. `build_exe.bat` wrote its generated spec into the project folder as
   `dem2dged.spec`, **silently overwriting the curated one** — so running the
   "fallback" script once permanently degraded every later
   `rebuild_exe.bat`. Both `build_*.bat` scripts now use
   `--specpath build\autospec`.
2. `build_exe.bat` used `--windowed` while `dem2dged.spec` used
   `console=True`, so the two paths produced *different exes*. Both are now
   `console=True` — built `--windowed`, a GDAL import failure raises before
   the Tk window opens and the user sees nothing at all.

**Packaging scripts renamed** — `dem2dged_package_v0.26.py` →
`dem2dged_package.py` and likewise for the validator one. They have derived
their source directory from `__file__` since v0.28, so the frozen `v0.26` was
stale and misleading.

---

## Remaining known limitations (not fixed, by choice)

These are documented rather than changed, as they are test-hygiene issues that
only affect the developer workflow:

- `tests/test_converters.py` passes `-xml_template DGED_GEO_TEMPLATE.xml` as a
  *relative* path, so the suite only works when pytest is run from the project
  root.
- The `output_dir` fixture is shared across tests in a class, and the
  converters skip tiles whose `.xml` already exists — so later tests in each
  class largely hit "Skip (exists)" and assert little. Making it
  function-scoped would slow the suite considerably; worth doing if the suite
  grows.
- `except SystemExit: pytest.skip(...)` around converter calls turns genuine
  regressions into skips. Tightening this would need a way to distinguish
  "GDAL missing in this environment" from "the converter broke".
