# DGED Conversion Review — DGIWG Test Data (dem2dged v0.36)

Reviewed: `tests/DGIWG Test Data/` (source rasters + `output/` folder), against `dem2dged_geo.py`, `dem2dged_lib.py`, `dem2dged_validate.py`, and `dem2dged_gui.py` (dem2dged v0.36, built 2026-07-20).

## Bottom line

The pipeline is working correctly at the structural level. All three real DEM inputs converted successfully under all three resampling methods (9 runs, 42 tiles total): every tile has a paired, well-formed XML sidecar, every run wrote a `TABLE_OF_CONTENTS.xml`, multi-tile sets got a `_COLLECTION.xml`, filenames and grid alignment match the DGED level-4b convention, and none of the 60 delivered XML files contain a leftover unreplaced `{{...}}` template field. Across all 9 runs, 599 of 621 individual validator checks passed (96.4%).

The FAIL results in `DGED_Validation_Report.txt/html` are real, but they cluster into three different causes, only one of which is an actual defect in the converted files. Details and line references below.

## What was and wasn't converted

Three sources were converted, three ways each:

- `ACAIPGTM.tif.tiff` — 1792×1536, EPSG:4326, **8-bit (uint8)**, only 7 distinct values (0, 29, 95, 170, 201, 251, 255). Its own TIFF tag says `IMAGEDESCRIPTION = "GeoTIFF prototype ARC with TM (test pattern file), Unclassified"` — this is a synthetic DGIWG conformance test pattern, not real terrain. → 2 tiles/run.
- `DGED_L4bU_n5563358_U_P_01.tif.tiff` — 2000×2000, EPSG:32633, Float32, 5 m posts, 1966 distinct elevations 276.4–472.9 m — this is the one real-terrain source in the set. → 4 tiles/run.
- `utm33_gdal_tiff_rsid_v2.2.1.tiff` — 2000×2000, EPSG:32633, uint8, 25 m posts, 114 distinct values 6–255, NoData=0. Also a DGIWG sample/test raster (byte-quantized). → 8 tiles/run.

Two files in the folder were **not** processed, and that looks correct: `E005N19_50k_GBJ2_R_U_01_FRA.jp2` is an orthophoto (its sidecar `CZE_Ortho_product_metadata.xml` is an ISO-19115 ortho-imagery record, not elevation), so it's out of scope for a DEM→DGED converter. `DGEDL9U_32N_6157500_546250.7z` was never extracted — dem2dged has no built-in archive handling — and its sidecar XML is itself a DGED-profile ISO-19115 metadata record from the Danish Mapping Agency, suggesting the archive already **is** a finished DGED Level-9 product rather than a raw input DEM. Worth confirming your intent here: if you meant to test conversion of whatever's inside, it needs manual extraction first; if it's meant as a reference/known-good product, it would be more useful run through `dem2dged_validate.py` directly than through the converter.

## Finding 1 (real defect): tile edge seam on the real-terrain dataset

`DGED_L4bU_n5563358` is the only dataset that trips Section G (edge-overlap) in the validator, and it does so on **all three** resampling methods:

```
FAIL  DGEDL4bGtC_5000N01600E_A_U_01 ↔ DGEDL4bGtC_5015N01600E_A_U_01: shared row differs
      (max 1.600 m) — Nearest Neighbor
      (max 0.121 m) — Bilinear
      (max 0.134 m) — Cubic Convolution
```

Adjacent DGED tiles are designed to share one exact post row/column at their common boundary (`dem2dged_geo.py`, the "HALF-POST EXPANDED warp extent" comment around line 190). But each tile is produced by its **own independent `gdalwarp` subprocess call** (lines 229–238), computing that shared boundary coordinate from two different expressions — once as `t_minlat + tiledim + latres/2` (south tile's top edge) and once as `(t_minlat + tiledim) − latres/2` (north tile's bottom edge). These are mathematically the same point, but floating-point arithmetic can land them a few ULPs apart. When that shared post sits close to a tie between two source pixels, Nearest Neighbor's pixel-selection can flip depending on which side of the tie the tiny FP error falls on — which is exactly the pattern in the numbers above: Nearest Neighbor (a discontinuous, tie-sensitive algorithm) shows a full-pixel-scale jump (1.6 m, on a ~5 m source), while Bilinear/Cubic (continuous interpolants) show only a sub-pixel wobble (12–13 cm) from the same root cause.

This is worth fixing, not just noting: 1.6 m at 5 m post spacing is a visible seam in a delivered product, not cosmetic rounding. The fix is to make the shared boundary coordinate bit-identical regardless of which tile computes it — e.g. derive both tiles' shared edge from one canonical formula (integer post index × spacing from a single global origin, rounded to a fixed precision) instead of recomputing `t_minlat ± half-post` independently per tile.

Note the validator itself already documents this exact failure mode in its own explanation text (`dem2dged_validate.py` ~line 1022–1028 and ~1185–1189) — the tool's authors clearly anticipated this class of bug, and the check is doing its job correctly here.

## Finding 2 (validator bug, not a tile defect): H/H2 always compares against a Bilinear reference

Sections H and H2 re-warp the source DEM for comparison, and in **both** places the resampling algorithm is hardcoded:

```
dem2dged_validate.py:784   resampleAlg="bilinear"   (section H, global min/max/mean)
dem2dged_validate.py:843   resampleAlg="bilinear"   (section H2, sample-window pixel diff)
```

The code comment immediately above the second one (lines 836–838) says this re-warp uses *"the same resampling algorithm the tiles were produced with, so this is a like-for-like comparison"* — but it doesn't; it's always Bilinear. Neither `check_source()` (line 729) nor `run_validation()` (line 1453) even accept a parameter for which resampler produced the tiles, and the GUI's caller (`dem2dged_gui.py:1487`) doesn't pass one either — so this can never have worked as commented.

Practical effect: Nearest Neighbor and Cubic Convolution tiles get diffed against a Bilinear reconstruction of the source, so some of the "FAIL" numbers are really just "how different is this algorithm from Bilinear," not "how wrong is this tile." That's most of the large H2 numbers for non-bilinear runs:

- ACAIPGTM Nearest Neighbor: 70.8 m — mostly NN-vs-Bilinear mismatch on a source with 255 m step edges, not a tile defect.
- ACAIPGTM Cubic: 24.1 m — same effect, smaller because Cubic is closer to Bilinear than NN is.
- DGED_L4bU Nearest Neighbor: 8.25 m — same effect on real terrain.

Fix: thread the actual `-resample` value used for the tiles through to `check_source()`/`run_validation()` and pass it as `resampleAlg` at both call sites, matching the comment's stated intent.

## Finding 3 (real, and expected): Cubic Convolution overshoot on the two byte-encoded test patterns

Unlike Finding 2, this one is *not* an artifact of the Bilinear-reference bug — it shows up in Section H's direct tile-vs-source min/max comparison, and I independently confirmed it by reading the delivered GeoTIFF pixel values directly:

- `ACAIPGTM` Cubic tiles: elevation range **−41.18 .. 285.31 m** vs. true source range 0 .. 255 m.
- `utm33` Cubic tiles: **−44.38 .. 313.70 m** vs. true source range 6 .. 255 m.

This is classic cubic-convolution "ringing": the kernel overshoots at sharp discontinuities, and both these sources are 8-bit synthetic test patterns with hard step edges (7 and 114 distinct values respectively) — about as adversarial an input as cubic convolution can get. The real-terrain source (`DGED_L4bU`, smooth Float32 data) shows no such overshoot. This isn't dem2dged's default behavior either — `resolve_resampler()`'s "auto" mode only ever picks average or bilinear, never cubic; you only get this because the Resampling Comparison test explicitly forces all three methods for evaluation. Still, worth deciding whether cubic output should be clamped to the source's min/max (or at least flagged) so a user who does pass `-resample cubic` on choppy data doesn't ship negative elevations silently.

## Finding 4 (cosmetic): PASS/WARN/FAIL labels disagree with each other for the same run

`ACAIPGTM [Bilinear Interpolation]` (PASS=31, WARN=2, FAIL=0) is labeled differently in three places that all describe the identical run:

- `DGED_Validation_Report.txt` → **RESULT: PASS** (line ~1490 only checks `n_fail`, ignores warnings — a 2-tier rule).
- `DGED_Validation_Report.html` per-dataset badge → **WARN** (line ~1310 uses a 3-tier rule: FAIL > WARN > PASS).
- `DGED_Resampling_Comparison_Report.html` badge → **WARN** (`dem2dged_gui.py` 1488–1490 mirrors the 3-tier rule).

Same underlying numbers everywhere, just different pass/warn thresholds depending on which report you're reading — which is exactly what surfaced this while comparing your two reports side by side. Not a functional bug, but worth picking one rule (2-tier or 3-tier) and using it consistently in all three places so a dataset can't be "PASS" in one report and "WARN" in another.

## Housekeeping checks (all clean)

I independently re-verified rather than just trusting the reports: all 60 delivered XML sidecars parse as well-formed XML with zero errors; a regex scan for unreplaced `{{FIELD}}` template tokens found none (the only literal `{{` in any file is one explanatory template comment, not a real placeholder); every `.tif` has its matching `.xml` in every run; `TABLE_OF_CONTENTS.xml` is present in all 9 output folders; output data type is Float32 for level 4b, which matches the tool's own DGED-spec table (`INT16_LEVELS = ("0","1","2")` — Int16 is only mandatory below level 3). The recurring "no overlapping valid data" WARNs (2 per run) are from H2's sample windows being placed at fixed image-relative offsets (center ± ¼ extent) that happen to land outside actual data coverage on these particular tiles — benign, not a defect, though the window placement could be made coverage-aware to stop generating routine warnings.

## Recommendations, in priority order

1. Fix the tile-boundary floating-point tie-break (Finding 1) — the only defect that affects a real-terrain delivery.
2. Fix `check_source()` to validate each run against its own resampling method instead of a hardcoded Bilinear reference (Finding 2) — this is currently making Nearest Neighbor/Cubic runs look worse than they are.
3. Unify the PASS/WARN/FAIL rule across the `.txt` RESULT line, the HTML per-dataset badge, and the GUI comparison badge (Finding 4).
4. Decide on cubic-convolution overshoot handling (clamp vs. document) and confirm intent for the untouched `.jp2` and `.7z` files.
5. Optional polish: make H2's sample windows coverage-aware.

Happy to implement any of these — let me know which ones you want done and I'll follow your versioning/packaging workflow for the code changes.
