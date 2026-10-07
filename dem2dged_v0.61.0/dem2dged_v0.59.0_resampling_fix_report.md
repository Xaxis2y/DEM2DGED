# dem2dged v0.59.0 — Mountainous-Terrain Conversion Error: Full Fix

SPDX-License-Identifier: GPL-2.0-or-later  
Copyright (c) 2026 Eui Soo SON

Date: 2026-09-08  
Requested: apply the mountainous-terrain accuracy improvement fully, not
partially — minimise the conversion error as far as it can be minimised.

---

## 1. What was still wrong after v0.58.1

`-resample optimize` ranked candidates with a **hold-out cross-validation**:
the source was point-sampled onto a sparse training grid, and each candidate
was scored on how accurately it **reconstructed** the full grid from it.

Reconstruction is *upsampling*. A DGED conversion is *decimation*. The two
diverge sharply as the ratio grows, and on steep terrain the ranking came out
**exactly inverted**. Your own DGED environment (GDAL 3.13.3, Python 3.10.21)
produced this, at 16x:

| | true point accuracy | what the old test said |
|---|---|---|
| `near` | **0.000 m** — best | 147.551 m — **worst** |
| `cubic` | 21.938 m | 133.448 m |
| `average` | 22.993 m | 147.551 m — *identical to `near`* |
| `bilinear` | 36.579 m | 126.564 m |
| `cubicspline` | **56.512 m — worst** | 120.054 m — **"best"** |

`near` and `average` scoring bit-identically was the tell: GDAL's `average`
degenerates to point sampling when it **upsamples**, so inside the old test
two of the five candidates were literally the same operation and had never
been distinguished at any ratio.

---

## 2. What v0.59.0 does instead

Each candidate now performs **the real production operation** and is scored
against the best available estimate of the truth.

1. **Decimate for real.** The source is warped *down* to the requested post
   spacing with that candidate's algorithm — the same `gdal.Warp` call the
   conversion will make, with the same source-range clamp a delivered
   cubic-family or Lanczos tile receives.
2. **Score against point truth.** A DGED post carries the elevation *at a
   point*. The truth used is a narrow Catmull-Rom bicubic sample of the source
   at that post's exact location. This is deliberately **not** any candidate's
   own operation: GDAL scales its resampling kernel with the downsampling
   factor, so a candidate warping 16x averages over a 16-pixel footprint,
   while the truth reference always uses a 4-pixel stencil at native spacing.
3. **Average over sub-pixel phases.** Scoring on one target grid would let a
   knife-edge alignment decide everything — where a target post happens to
   coincide with a source post, `near` is trivially exact. Real DGED grids are
   snapped to their own global lattice, so posts land at every phase. Each
   candidate is scored over **six sub-pixel phases** and the errors pooled.
   That charges `near` its real expected offset error and charges the
   smoothing methods their real curvature bias.
4. **Bounded cost.** A source larger than `MAX_DECIMATE_PIXELS` is sampled
   with up to four windows at **native** post spacing — never decimated,
   because decimating the source would shrink the very ratio under test,
   which is the defect v0.57.0 fixed.

`lanczos` was added as a sixth scored candidate. It was previously left out
because widening a ranking that could not be trusted only widened the blast
radius; now that the measurement is sound, a candidate can only help.

---

## 3. Does the error actually drop? — measured against known ground truth

`verify_mountain_terrain_v0.59.0.py` generates terrain from an **analytic
formula**, so the true elevation is known everywhere, not just at posts. It
ranks every candidate three ways across 32 cases (alpine / ridged / rolling
terrain, integer and non-integer ratios from 2x to 16x, clean and noisy
sources, two seeds).

| Ranking method | Correct candidate chosen | Excess RMSE over the oracle |
|---|---|---|
| hold-out reconstruction (≤ v0.58.1) | 6 / 32 | **+573.62 m** |
| decimate-and-score (v0.59.0) | **28 / 32** | **+0.53 m** |

**99.9% of the avoidable error is removed.** Worked examples from that run, on
1 m alpine terrain:

| ratio | oracle | old pick | old realised | new pick | new realised |
|---|---|---|---|---|---|
| 16x | 10.157 m | `cubicspline` | 55.624 m | `near` | **10.157 m** |
| 8x | 2.703 m | `cubicspline` | 20.345 m | `cubic` | **2.703 m** |
| 4x | 0.437 m | `bilinear` | 3.110 m | `cubic` | **0.437 m** |

"Excess over the oracle" is the metric that matters — the avoidable error each
method's choices added up to. Counting correct picks alone would overstate the
fix, because a wrong pick between near-tied candidates costs almost nothing.

The four remaining mis-picks are all at ratios of 4x or below on **noisy**
sources, where the candidates sit within a quarter of a metre of each other.
The cause is known and documented rather than hidden: the truth reference is
interpolated from the source, so it carries the source's own noise, which
slightly under-penalises a candidate that does not smooth. At high ratios the
curvature bias dwarfs that term. I tested three noise-aware variants of the
truth reference (Gaussian pre-smoothing at σ = 0.5, σ = 0.8, and an adaptive σ
driven by an estimated noise floor); none improved the overall result, so the
simplest reference was kept rather than adding a knob that buys nothing.

---

## 4. What did NOT change

This matters for your existing deliveries.

- Tile geometry, grid snapping, post positions, filenames, metadata, seam
  reconciliation, the cubic-family clamp and **every spec-compliance check**
  are untouched.
- `-resample auto` and every explicit `-resample <alg>` are **bit-for-bit
  identical** to v0.58.1. Only what `optimize` *recommends* changes.
- The hold-out test was not deleted. It is still used where it is the
  **correct** measure — equal post spacing or upsampling, where there is no
  decimation to score — and as a fallback if the decimation test cannot be set
  up (for example a source too small for the requested ratio). On that
  fallback path the v0.58.1 high-ratio warning still fires; on the normal path
  it no longer does, because there is nothing left to warn about.

**One operational consequence.** A delivery produced with `-resample optimize`
on steep terrain at a high ratio under v0.58.1 or earlier may have used a
materially less accurate resampler than the source warranted. It is still
structurally conformant — resampler choice affects accuracy, not conformance —
but if its acceptance rests on vertical accuracy, re-run `optimize` under
v0.59.0 and compare with `dem2dged_validate.py --terrain-qa mountain`.

---

## 5. Verification (cloud sandbox, GDAL 3.8.4 / Python 3.12)

| Check | Result |
|---|---|
| `pytest -q` | **471 passed** (453 before; +18 new) |
| `audit_pure.py` | `RESULT: 0 problem(s)` — section 9 now also checks the dispatch |
| `BUMP_VERSION.py --check 0.59.0` | 0 stale declarations |
| `DGED_Loader/test_dged_loader.py` | ALL TESTS PASSED |
| `verify_mountain_terrain_v0.59.0.py` | 28/32 correct; +573.62 m → +0.53 m; **VERDICT: improves** |
| `DIAG_dem2dged_v0.59.0.py` | **28 checks, 0 failed** |
| `py_compile`, all modules + both `.pyt` | clean (44 files) |

New tests in `tests/test_v059_regressions.py` (16), of which four score the
tool's choice against the **analytic surface** rather than against the tool's
own metric — the check that the measurement is not merely self-consistent.
`audit_pure.py` section 9 now asserts that a decimation is never routed to the
hold-out test, that the real ratio reaches the decimation test, and that
scratch rasters are cleaned up.

---

## 6. Please run this on your machine

```batch
conda activate DGED
cd C:\Users\Son\Documents\ChatGPT\dem2dged\dem2dged_v0.58.0
python DIAG_dem2dged_v0.59.0.py
```

28 checks. Section 4 re-derives the accuracy claim against real GDAL on your
build and prints what v0.58.1 *would* have picked on the same source next to
what v0.59.0 picks, with the metres saved. Section 6 runs the ground-truth
sweep. Writes `DIAG_dem2dged_v0.59.0_log.txt` — send it back.

For the full 32-case sweep rather than the quick subset:

```batch
python verify_mountain_terrain_v0.59.0.py
```

It exits non-zero if v0.59.0 does **not** beat v0.58.1 on your GDAL build, so
the claim is falsifiable on site rather than taken on trust.

Still outstanding and not runnable from here:

- `python RELEASE_GATE_v0.56.0.py` — the ten-stage gate with real conversions.
- The PyInstaller rebuild (`rebuild_exe.bat`, `rebuild_validate_exe.bat`).
  The embedded version resources are already at 0.59.0, so the existing exes
  will report 0.58.1 until rebuilt.
- `DGED_Loader/arcgis_pro_smoke_test.py` under a licensed ArcGIS Pro runtime.
- **A real-DEM confirmation.** The evidence above is from analytic terrain,
  where ground truth exists. Convert one representative steep source both ways
  and compare the `--terrain-qa mountain` reports.

---

## 7. Files changed

**New:** `verify_mountain_terrain_v0.59.0.py`, `DIAG_dem2dged_v0.59.0.py`,
`tests/test_v059_regressions.py`, `REQUIREMENTS_COMPLIANCE_V0.59.0.md`, this
report.

**Code:** `dem2dged_compare.py` (the fix: `_sample_bicubic`,
`_decimate_windows`, `_prepare_decimate_test`, `_decimate_stats`,
`_cleanup_decimate_test`, rewired `pick_best_resampling`, `compute_method_stats`
and the report ranking), `dem2dged_lib.py` (`resolve_resampler` docstring),
`dem2dged.py` / `dem2dged_geo.py` / `dem2dged_utm.py` (CLI help),
`dem2dged_gui.py` (dropdown label and docstring), `audit_pure.py` (section 9),
`tests/conftest.py` (`make_raster(array=...)`),
`tests/test_v057_regressions.py` and `tests/test_resampling_report.py`
(updated to the v0.59.0 contract, with the reason recorded in each).

**Docs:** `README.md`, `START_HERE.md`, `DEM2DGED_User_Manual.md`,
`QUICKSTART.html`, `MANIFEST.md`, `tests/README.md`, `DGED_Loader/README.md`,
`BUILD_SCRIPTS_GUIDE.md`, `REBUILD_GUIDE.md`,
`dem2dged_v0.57.1_mountain_terrain_recheck.md` (marked resolved),
`REQUIREMENTS_COMPLIANCE_V0.58.1.md` (marked superseded), `VERSION.txt`,
`VALIDATOR_VERSION.txt`, `DGED_Loader/VERSION.txt`.

All 38 version declarations bumped 0.58.1 → 0.59.0 with `BUMP_VERSION.py`.
