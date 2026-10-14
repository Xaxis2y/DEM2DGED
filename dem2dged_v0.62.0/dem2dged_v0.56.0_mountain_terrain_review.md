# dem2dged v0.56.0 — Regression Re-check + Mountainous-Terrain Accuracy Investigation

Date: 2026-09-02
Scope: (1) re-run the existing test/diagnostic harness end-to-end, (2) build an independent, controlled accuracy experiment specifically for steep/mountainous terrain, (3) evaluate whether a better method exists to reduce vertical error there.

---

## 1. Regression re-check

The full pytest suite (`tests/`) was re-run in a clean environment (Python 3.12, GDAL 3.8.4, pytest 9.1.1, numpy 1.26.4).

**Result: 433 / 433 tests pass.** No functional defects were found in the existing code paths.

The first pass showed 7 failures, all traced to my sandbox being incomplete, not the codebase:
- 3 failures came from `dem2dged_gui.py`/`VERSION.txt` not yet being copied into the test environment.
- 4 more came from `tkinter` not being installed in the sandbox (the GUI-parity tests import it).

Both gaps were closed (files copied, `python3-tk` installed) and the suite went to 433/433 clean. This confirms your last release-gate run — nothing has regressed since v0.56.0 was packaged.

---

## 2. Why "mountainous terrain has a lot of error" — investigation approach

Rather than guess, I built a controlled numerical experiment: a synthetic terrain surface with a known, exact elevation at every coordinate (a smooth fractal/fBm surface, tuned to realistic mountain statistics — median slope ≈ 65%, 94% of the surface over 20% slope). Because the "true" elevation is known everywhere, I can measure the *exact* error of any resampling method at the *exact* DGED post locations, instead of comparing two already-resampled rasters (which is what the tool's own QA usually has to do, for lack of ground truth).

Four things were tested against this ground truth, at realistic DGED decimation ratios (4×, 8×, 16× — i.e. converting a 5 m source down to 20/40/80 m posts, the situation that actually produces "a lot of error" on high-relief DEMs):

1. Which `gdalwarp` resampler is actually most accurate at each ratio.
2. Whether the tool's `-resample optimize` feature picks the right one.
3. Whether the v0.49 Gaussian anti-alias pre-filter (`-prefilter gaussian`) actually helps.
4. Whether the `rms` resampler option is safe to offer at all.

All four turned up something worth acting on. Full detail below; a corrected/updated round of the same tests confirmed each result before it's reported here (an earlier attempt using an *unrealistically rough* synthetic surface gave misleading numbers and was discarded — noted in §5 for transparency).

---

## 3. Findings

### 3.1 `-resample optimize` can pick the wrong algorithm for high-relief, high-ratio conversions — confirmed, reproducible

`dem2dged_compare.pick_best_resampling()` (used by `-resample optimize`) always measures accuracy using a **fixed 2× hold-out test** (`_holdout_stats()`: every other source post is withheld, the rest are used to reconstruct it), regardless of what decimation ratio the conversion actually requests.

Problem: which resampler reconstructs terrain best is **ratio-dependent**, and the effect is large exactly on steep terrain:

| Noise in source | Ratio tested | Winner at that ratio | RMSE of winner | RMSE of what `optimize` would have picked (Cubic) | Cubic's regret |
|---|---|---|---|---|---|
| none | 2× (what `optimize` measures) | Cubic | 0.222 m | — | — |
| none | 8× (a realistic delivery ratio) | **Nearest** | 1.075 m | 1.625 m | +51% worse |
| none | 16× (a realistic delivery ratio) | **Nearest** | 1.272 m | 3.936 m | **+209% worse** |
| 0.3 m sensor noise | 8× | **Nearest** | 1.126 m | 1.625 m | +44% worse |
| 0.3 m sensor noise | 16× | **Nearest** | 1.312 m | 3.936 m | +200% worse |

(RMSE in metres, averaged over 4 random sub-pixel grid phases; interior of the tile only, edge effects trimmed.)

Cubic wins comfortably at the 2× ratio `optimize` actually tests — so `optimize` isn't broken in what it measures, it's just measuring the wrong thing for a conversion that isn't 2×. On a high-relief source going down to a coarse DGED level (which is exactly where users reach for `optimize` because they're worried about accuracy), it can recommend a resampler that is **2–3× worse than Nearest Neighbor** at the ratio actually being delivered.

**Why this happens (mechanism):** at a gentle 2× decimation there's little aliasing risk, so a smooth interpolator (Cubic) reconstructs withheld posts very accurately. At a steep 8–16× decimation of genuinely rough terrain, every interpolating method blends multiple source samples and is systematically biased toward the *local mean* rather than the *true point elevation* — which is what a DGED post actually has to represent. Nearest Neighbor never blends, so it has no such bias; it just copies the nearest real measurement.

**Caveat, tested and confirmed (not a blind recommendation):** this only holds while the source DEM is reasonably low-noise. I also swept synthetic sensor noise from 0 to 4 m added to the source:

| Source noise | Nearest RMSE | Cubic RMSE | Average RMSE | Bilinear RMSE |
|---|---|---|---|---|
| 0.00 m | 1.03 | 1.61 | 1.61 | 2.33 |
| 0.15 m | 1.04 | 1.61 | 1.61 | 2.33 |
| 0.50 m | 1.16 | 1.61 | 1.61 | 2.33 |
| 1.50 m | 1.84 | 1.61 | 1.61 | 2.33 |
| 4.00 m | 4.12 | 1.65 | 1.67 | 2.35 |

(all at ratio 8×)

Nearest degrades roughly linearly with source noise (it has no averaging to suppress noise), while Cubic/Average barely move. The crossover is around ~1 m of source vertical noise. So "Nearest is best on steep terrain" is true for clean high-resolution sources (good LiDAR, good photogrammetry) but **not** for noisier sources (coarse SRTM/InSAR-class DEMs), where Cubic/Average remain the safer choice.

**Recommendation:** have `pick_best_resampling()` / `_holdout_stats()` hold out at (or near) the *actual requested* decimation ratio instead of a hardcoded 2×, and add `average` to `AUTO_OPTIMIZE_CANDIDATES` (it isn't currently a candidate at all, despite being the tool's own `-resample auto` default for downsampling, and it is the most noise-robust option other than Cubic in every test above). This turns `optimize` into what it already claims to be — a measurement of "what actually reconstructs *this* DEM best" — instead of one that's silently calibrated to a 2× case.

### 3.2 The existing `-resample auto` default is actually fine — no change needed there

Worth stating clearly since it's a relief: the plain default (`average` when downsampling >1.25×, `bilinear` otherwise) was the *most stable* performer across the noise sweep in §3.1 (1.61 → 1.67 m as noise went 0 → 4 m). It never wins outright against a noise-free Nearest-Neighbor best case, but it never falls badly behind either, and it doesn't require the user to know their source DEM's own noise characteristics. If you don't implement the `optimize` fix above, the honest advice for users converting steep terrain today is: leave `-resample` at `auto` (or explicit `average`), and only reach for `optimize` if you're going to sanity-check its choice against `average` yourself.

### 3.3 The Gaussian anti-alias pre-filter (`-prefilter gaussian`, v0.49) makes point-accuracy *worse*, not better, on steep terrain — confirmed, reproducible, mechanism understood

This one surprised me, so I checked the implementation itself first: `build_prefiltered_source()` and `gaussian_sigma_for_ratio()` are correctly implemented (normalised-convolution NoData handling is correct, the sigma formula matches the documented scikit-image convention, no NaN/zero-sigma bug — I re-read the whole function and it's sound). The problem isn't a bug in the filter; it's that turning it on hurts the accuracy metric that matters for DGED delivery:

| Ratio | Plain Average | Prefilter + Average | Plain Cubic | Prefilter + Cubic | Plain Bilinear | Prefilter + Bilinear |
|---|---|---|---|---|---|---|
| 4× | 0.664 m | 1.168 m (+76%) | 0.671 m | 1.065 m (+59%) | 0.978 m | 1.409 m (+44%) |
| 8× | 1.593 m | 3.105 m (+95%) | 1.605 m | 2.853 m (+78%) | 2.325 m | 3.664 m (+58%) |
| 16× | 3.700 m | 7.469 m (+102%) | 3.934 m | 7.067 m (+80%) | 5.405 m | 8.575 m (+59%) |

Every single combination got worse with the pre-filter on, and the penalty grows with ratio — the opposite of what the feature is meant to do, and worse exactly where the user says they're seeing the most error.

**Why:** `average`, `bilinear` and `cubic` all already blend multiple source samples per output pixel — they are themselves a form of low-pass filter. The v0.49 pre-filter applies a *second*, independent low-pass pass before that. Stacking two low-pass filters over-smooths the terrain: it reduces whatever aliasing "ringing" exists, but the extra smoothing bias it introduces (flattening real ridges and valleys toward their local mean) costs more accuracy, at the post-elevation level, than the aliasing it removes.

This doesn't mean the feature is worthless — it may still reduce large-scale visual banding/moiré artifacts in an exported hillshade or overview, which this experiment didn't measure. But as currently documented ("to suppress aliasing when downsampling high-relief terrain"), it reads as an accuracy improvement, and on the evidence here it is not one. **Recommendation: don't tell users to turn on `-prefilter gaussian` to fix mountain-terrain accuracy — the data says it makes it worse.** If you want to keep the feature, the docstring/GUI copy should be corrected, and it's worth being opt-in-only exactly as it already is.

### 3.4 `-resample rms` is mathematically unsound for elevation data — should probably be removed

Quick, isolated, 100%-reproducible check (not dependent on the synthetic terrain model above):

```
4x4 footprint, true mean = -50.0 m
average  -> -50.00 m   (correct)
rms      -> +100.00 m  (150 m off, and the WRONG SIGN)
med      -> -100.00 m
bilinear -> -31.94 m
```

GDAL's `rms` resampler computes the quadratic mean (`sqrt(mean(x²))`) of each output pixel's contributing footprint. That is mathematically guaranteed to be `≥ |true mean|` for any footprint with variation — it is never an unbiased estimator of elevation, and for any area straddling a vertical datum (or, at scale, any area with real local relief) it can be badly and silently wrong, as shown above.

This is documented, standard GDAL behaviour (added in GDAL 3.3, intended for use cases like acoustic/backscatter magnitude, not signed physical elevation) — not a dem2dged bug. But `dem2dged_lib.GDALWARP_RESAMPLERS` currently lists `rms` as a valid `-resample` value with no warning, so a user experimenting with resamplers (which the tool actively encourages via `-resample optimize`) could select it and get silently corrupted output — gdalwarp doesn't error, it just produces a number that's wrong, possibly by hundreds of metres, with no diagnostic.

**Recommendation:** remove `rms` from `VALID_RESAMPLERS`/`GDALWARP_RESAMPLERS`, or keep it only behind an explicit warning in `validate_resampler()` explaining it is unsuitable for elevation rasters.

---

## 4. Summary of recommendations, in priority order

1. **Fix `-resample optimize`'s hold-out ratio.** This is the one with the biggest real-world impact on exactly the scenario you asked about (mountain terrain, large decimation ratios) — up to a 3x accuracy regret versus what's actually best. Test the requested ratio (or something close to it), and add `average` as a candidate.
2. **Stop recommending the Gaussian pre-filter for accuracy** on steep terrain (correct the docs/GUI copy); the data says it hurts point accuracy, consistently, at every ratio tested.
3. **Remove or gate the `rms` resampler option.** It's a latent trap with no upside for elevation data.
4. No change needed to the current `-resample auto` default — it's already the most robust choice across unknown source-noise levels.

None of this is a change I've made yet — the shipped v0.56.0 code is functionally correct (433/433 tests pass) and these are all about the *choice of resampling parameters*, not bugs in the conversion pipeline itself. Let me know if you'd like me to implement #1–#3 as a v0.57.0 patch (with regression tests + a release-gate run), following the same process as the v0.56.0 patch.

---

## 5. Methodology notes (for the record)

- All experiments used a synthetic fractional-Brownian-motion-style terrain surface (`z(x,y) = Σ aᵢ·cos(kᵢ·(x,y) + φᵢ)`, amplitude spectrum `aᵢ ∝ kᵢ^-1.25`), which is smooth (infinitely differentiable, unlike a real DEM) but whose *evaluated grid samples* reproduce realistic mountain slope statistics (median slope 65%, 94% > 20% slope). Because the underlying function is exact and continuous, the "true" elevation at any DGED post coordinate is known exactly — the ground truth a real accuracy study never has.
- An earlier attempt used a "folded"/ridged surface (`relief − |Σ cosines|`) intended to look more like sharp ridgelines. That surface turned out to have creases sharp enough that the *source* raster itself couldn't resolve them cleanly — it produced results (Nearest beating every interpolator by 10–20×, uniformly) that didn't survive scrutiny and were discarded rather than reported. Flagging this here in case it's useful context for interpreting confidence in the numbers above: the reported results (§3) are from the corrected, smooth-surface version, re-verified across multiple random sub-pixel grid phases (to rule out grid-alignment artifacts — an initial pass that didn't randomise sub-pixel phase gave "Nearest is perfect," which was an alignment artifact, not a real result) and cross-checked with an independent noise sweep.
- All comparisons trim a border margin equal to the pre-filter/interpolation kernel radius, so no method is penalized for edge-of-array artifacts another method doesn't have.
- The `rms` finding (§3.4) is standalone and doesn't depend on the synthetic terrain model at all — it's a direct, minimal numerical check.
