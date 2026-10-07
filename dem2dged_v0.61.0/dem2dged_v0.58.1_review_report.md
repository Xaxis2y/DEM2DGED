# dem2dged v0.58.1 — Full File Sync, Documentation Update and Review

SPDX-License-Identifier: GPL-2.0-or-later  
Copyright (c) 2026 Eui Soo SON

Date: 2026-09-08  
Scope requested: bring every file into line with the last change, update
README / QUICKSTART / manual and the rest of the documentation, and run an
overall check for errors.

---

## 1. Verdict

**It works. Nothing is broken.** No runtime error, no import error, no test
failure was found anywhere in the tree, before or after this pass.

| Check | Before | After |
|---|---|---|
| `pytest -q` (GDAL 3.8.4, Python 3.12, `gdalwarp` on PATH) | 453 passed | **453 passed** |
| `audit_pure.py` | `RESULT: 0 problem(s)` | **`RESULT: 0 problem(s)`** |
| `DGED_Loader/test_dged_loader.py` | ALL TESTS PASSED | **ALL TESTS PASSED** |
| `py_compile`, every module + both `.pyt` | clean | **clean (41 files)** |
| `BUMP_VERSION.py --check 0.58.1` | n/a | **0 stale declarations** |
| `DIAG_dem2dged_v0.58.1.py` | n/a | **20 checks, 0 failed** |

What was wrong was **documentation and release hygiene**, and one of those
defects was serious.

---

## 2. What was found and fixed

### 2.1 The project README had been destroyed (serious)

`README.md` in `dem2dged_v0.58.0` was **byte-identical** to
`DGED_Loader/README.md` (MD5 `40eaf0b5…`). The v0.58.0 release shipped with
the loader's README copied over the project's full reference. The evidence was
unambiguous: the file described only the ArcGIS Pro toolbox, its own
troubleshooting section said *"see DEM2DGED's own README"*, and `MANIFEST.md`
still listed `README.md` as *"full reference and options"*.

Restored from `dem2dged_v0.57.1/README.md` (839 lines) and brought up to
v0.58.1. A regression check for this is now in `DIAG_dem2dged_v0.58.1.py`.

`DGED_Loader.pyt` at the project root is the same kind of stray copy, but it
is harmless and useful, so it is kept, documented in `MANIFEST.md` and
`README.md`, kept in sync by `BUMP_VERSION.py`, and checked for drift by the
diagnostic script.

### 2.2 The documentation contradicted the code on mountainous terrain

`README.md`, `DEM2DGED_User_Manual.md` and `QUICKSTART.html` all still
recommended `--prefilter gaussian` for high-relief sources. The user manual
said, verbatim, that it *"can improve rough mountainous terrain"*. That is the
exact recommendation **v0.57.0 retracted** in the CLI help and the GUI
dropdown after measurement. `selftest_prefilter.py`'s own closing summary also
still said *"Use it on high-relief sources being downsampled."*

An operator following the documents could have shipped a delivery with
knowingly degraded vertical accuracy while the tool's own `--help` said the
opposite.

The two measurements are **not** in conflict, and both are now stated side by
side wherever the feature is described:

| Measurement | Scored against | Question | Verdict |
|---|---|---|---|
| `selftest_prefilter.py` (v0.49) | ideal band-limited surface | how much **aliased** structure is in the product? | filter helps, up to −82% |
| v0.56.0 / v0.57.1 mountain reviews | true elevation at each post | how wrong is the **height** at this post? | filter hurts, +44% to +102% on steep terrain |

Guidance now: **for a delivery judged on LE90, leave `--prefilter` at
`none`.** Corrected in all four places, plus `REQUIREMENTS_COMPLIANCE_V0.58.1.md`.

### 2.3 `dem2dged_compare.py` carried a v0.45 version fallback

```python
except Exception:
    VERSION = "0.45"   # fallback; keep in sync with dem2dged_lib.VERSION
```

Thirteen releases stale. Every single-use bump script listed `dem2dged_lib.py`
but not this file, so a run whose `dem2dged_lib` import failed would have
stamped a **v0.45** banner on a comparison report produced by the current
build. `audit_pure.py` did not catch it because its file list does not include
`dem2dged_compare.py`'s fallback. Fixed, and the file is now in
`BUMP_VERSION.py`'s list.

### 2.4 `UPDATE_VERSIONS.py` corrupted `VERSION.txt` if run twice

It prepended a **hardcoded** `Changes in 0.57.1` block to `VERSION.txt` with
no idempotence guard and no dry run, and rebuilt `VALIDATOR_VERSION.txt`'s
header from a hardcoded `0.57.1` — which on any release after v0.57.1 would
have rolled the validator version *backwards*. Retired: it now exits 2 with an
explanation instead of running.

### 2.5 Version declarations were drifting again

`tests/*.py` were stamped `0.56.0`, `tests/test_v057_regressions.py` `0.57.0`,
`selftest_prefilter*.py` `0.57.1`; two selftests had no version header at all.
The root cause is structural: each release wrote its own bump script with its
own hand-written file list, so a file dropped from one list silently stopped
being bumped — the same mechanism that stranded `dem2dged_lib.VERSION` at
0.57.0 during the v0.57.1 release.

**New `BUMP_VERSION.py`** replaces all of them: generic (`--from/--to`),
idempotent, dry run by default, with a `--check <version>` release audit that
covers every module, test, selftest, `.pyt`, PyInstaller `version_info`
resource and release-note header. It deliberately does not write changelog
prose.

### 2.6 Stale banners and stale package documentation

- `MANIFEST.md` still described the v0.56.0 package (VERSION source of truth
  "0.56.0", no mention of anything from v0.57.x or v0.58.x). Rewritten.
- `build_exe.bat`, `build_validate_exe.bat`, `rebuild_exe.bat`,
  `rebuild_validate_exe.bat` said **v0.34**; `verify.bat` said **v0.41**;
  `QUICKSTART.html`'s footer said **v0.49**; `REBUILD_GUIDE.md`'s sample
  console output said **v0.23**; `tests/README.md` promised `352 passed`.
  All corrected.
- `REQUIREMENTS_COMPLIANCE_V0.57.1.md` was a relabelled copy of the v0.56.0
  matrix, and cited a **`RELEASE_GATE_v0.57.1.py` that has never existed**.
  Annotated as superseded with both errors named, and replaced by
  `REQUIREMENTS_COMPLIANCE_V0.58.1.md`.
- `START_HERE.md` still led with v0.55.0 and pointed at
  `PACKAGE_v0.55.0.py`; its ArcGIS section still told you to add the source
  and QA rasters by hand, which the v0.58.0 tool now does for you.

---

## 3. Answering the two questions you asked mid-run

### "산악지대 변환 오차 개선은 적용이 된 건가?" — Is the mountain-terrain fix applied?

**Partly. Two of three layers are in; the deepest one is not.**

| Layer | Status |
|---|---|
| v0.57.0 fix 1 — hold-out benchmarks at the **actual** decimation ratio (`pick_holdout_factor()`), `average` added as a 5th candidate | **Applied**, verified in code and by 21 tests |
| v0.57.0 fix 2 — `--prefilter` help/GUI text corrected | **Applied** in code since v0.57.0; **the docs only caught up in v0.58.1** (§2.2) |
| v0.57.0 fix 3 — `rms` resampler removed (discards sign) | **Applied**, raises a specific `SystemExit` |
| v0.57.1 recheck finding — the hold-out test measures **reconstruction**, not **decimation** | **NOT applied.** Still open. |

v0.58.0 was the ArcGIS "Show DGED Differences" release; it did not touch any
of this.

I reproduced the open flaw live, with real GDAL, on smooth analytic mountain
terrain decimated 16x (no white noise, so Nearest gets no trivial advantage):

```
TRUE point accuracy at 16x        optimize's hold-out ranking
  near          0.000 m             cubicspline   119.6 m   <- picked
  cubic        20.6   m             bilinear      126.2 m
  average      22.2   m             cubic         133.7 m
  lanczos      24.5   m             near          147.7 m
  bilinear     35.6   m             average       147.7 m   <- identical to near
  cubicspline  55.6   m   <- picked
```

`optimize` chose the **worst of six** by true point accuracy. `near` and
`average` scoring bit-identically is the signature of the cause: GDAL's
`average` degenerates to point sampling when it *upsamples*, which is what the
hold-out test makes every candidate do.

Per your decision, this pass **documents** rather than fixes it. v0.58.1 adds:

- a **runtime advisory** in `pick_best_resampling()` that fires at decimation
  ratios ≥ 8x, and again when Nearest and Average tie — it prints the
  limitation and tells the operator to verify with `--terrain-qa mountain`.
  **It changes no selection**, and is covered by the diagnostic script;
- the limitation written into `README.md`, `DEM2DGED_User_Manual.md`,
  `QUICKSTART.html` and `REQUIREMENTS_COMPLIANCE_V0.58.1.md`;
- a status note at the top of
  `dem2dged_v0.57.1_mountain_terrain_recheck.md` recording that the offered
  v0.58.0 patch was never taken up.

The decimate-and-score rewrite is queued for **v0.59.0**.

### "이거 적용해도 dem2dged requirement 를 다 충족시킬 수 있는거야?" — Do the requirements still hold?

**Yes.** The two concerns are independent, and this is now written into
`REQUIREMENTS_COMPLIANCE_V0.58.1.md` rather than left to inference:

1. **DGIWG 250 structural conformance does not depend on the resampler.** It
   is decided by tile naming, grid geometry and post spacing, `PixelIsPoint`
   registration, horizontal and vertical CRS, per-level data type, NoData,
   shared-edge identity, sidecar metadata and the table of contents. Every
   v0.57.x change was to resampler *selection* and to *guidance*. Removing
   `rms` only narrowed an already-conformant set. The structural validator is
   unchanged and all 453 tests pass.
2. **Vertical accuracy is an evidence question, not a structural one.** The
   v0.57.0 fixes can only reduce source-to-output error on steep terrain;
   none can increase it. Absolute CE90/LE90 against DGIWG 250 still requires
   independent control data (`--reference-dem` plus measured accuracy inputs)
   and stays `NOT_EVALUATED` without it — exactly as before.
3. **The mountain allowance stays conservative.** `--terrain-qa mountain`
   records `dgiwg_vertical_accuracy_factor = 1.4` only when
   `predominant_slope_over_20_percent` is true, and reports it explicitly.

So the changes are **compliance-neutral to compliance-positive**. They create
no new requirement, relax no existing check, and change no delivered byte for
a run that did not use `-resample optimize`, `--prefilter` or `rms`.

The one caveat now stated in the compliance matrix: if a delivery was produced
with `-resample optimize` at a ratio above roughly 8x on steep terrain, record
a comparison against at least one explicit resampler before signing it off.

---

## 4. What still needs your machine

Everything above was verified in a Linux sandbox on **GDAL 3.8.4 / Python
3.12**, which is not your DGED environment. Please run, in an **Anaconda
Prompt** with the dedicated environment activated (never `base`):

```batch
conda activate DGED
cd C:\Users\Son\Documents\ChatGPT\dem2dged\dem2dged_v0.58.0
python DIAG_dem2dged_v0.58.1.py
```

It writes `DIAG_dem2dged_v0.58.1_log.txt` — 20 checks covering the byte
compile, the version audit, every v0.58.1 regression, the optimize advisory
against real GDAL, the ArcGIS harness and the full pytest suite. Send the log
back and I will review it.

Still outstanding, and not runnable from here:

- `python RELEASE_GATE_v0.56.0.py` — the ten-stage gate with real conversions.
- The PyInstaller `.exe` build and smoke test (`rebuild_exe.bat`,
  `rebuild_validate_exe.bat`). The embedded version resources are already
  bumped to 0.58.1, so the exes must be rebuilt or they will report 0.58.0.
- `DGED_Loader/arcgis_pro_smoke_test.py` under a licensed ArcGIS Pro runtime,
  for the new **Show DGED Differences** tool.
- `DGED_Loader_v0.58.0.zip` in the folder is the old build artifact; re-run
  `python DGED_Loader/build_and_package.py` to produce the v0.58.1 zip.

---

## 5. Files changed in this pass

**Restored:** `README.md`.  
**New:** `BUMP_VERSION.py`, `DIAG_dem2dged_v0.58.1.py`,
`REQUIREMENTS_COMPLIANCE_V0.58.1.md`, this report.  
**Rewritten:** `MANIFEST.md`, `UPDATE_VERSIONS.py` (now a guard).  
**Code:** `dem2dged_compare.py` (fallback VERSION + advisory),
`selftest_prefilter.py` (guidance), plus the 0.58.1 bump across 38 files.  
**Docs:** `START_HERE.md`, `DEM2DGED_User_Manual.md`, `QUICKSTART.html`,
`DGED_Loader/README.md`, `REBUILD_GUIDE.md`, `BUILD_SCRIPTS_GUIDE.md`,
`DGIWG_STANDARDS_TRACKING.md`, `tests/README.md`,
`REQUIREMENTS_COMPLIANCE_V0.57.1.md` (superseded banner + two corrections),
`dem2dged_v0.57.1_mountain_terrain_recheck.md` (status note),
`VERSION.txt` / `VALIDATOR_VERSION.txt` / `DGED_Loader/VERSION.txt`.  
**Build scripts:** `build_exe.bat`, `build_validate_exe.bat`,
`rebuild_exe.bat`, `rebuild_validate_exe.bat`, `verify.bat`.

One item left alone deliberately: `DEM2DGED_Compliance_Policy.json`'s
`"policy_version": "0.56.0-baseline"`. It records **when the threshold
baseline was set**, not the product version, and no code reads it. Bumping it
would erase that provenance. Say the word if you would rather it track the
release.
