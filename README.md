# dem2dged v0.57.1 — Mountain-Terrain Fix Re-check + Doc/Version Sync

Date: 2026-09-04
Scope: (1) re-verify the three v0.57.0 mountain-terrain fixes actually work and actually reduce error, on real GDAL, against independent ground truth; (2) fix a version/documentation drift found along the way; (3) look for a better method to reduce steep-terrain conversion error.

---

## 1. Doc/version sync (fixed)

Requested mid-session ("update all documents like readme, quickstart etc with proper version"). Found and fixed:

- **Real bug, not just docs**: `dem2dged_lib.VERSION` was still `"0.57.0"` — `BUMP_v0.57.1.py`'s `VERSION_CONSTANT_FILES` list bumped the `# Version:` header *comment* in `dem2dged_lib.py` but never touched the `VERSION = "..."` *constant* two lines below it, which is the single value every other module and `VERSION.txt` are checked against. `tests/test_lib.py` caught this immediately once run in a real environment (`dem2dged.py declares 0.57.1, dem2dged_lib.VERSION is 0.57.0`, x7). Fixed the constant, and added `dem2dged_lib.py` to `BUMP_v0.57.1.py`'s `VERSION_CONSTANT_FILES` so this can't recur on the next bump.
- `VERSION.txt`'s own `Changes in 0.57.1:` line was missing the `v` prefix every other entry in the file has (`Changes in v0.57.0:`, `v0.56.0:`, ...) — cosmetic, but it broke `test_the_shipped_version_txt_still_has_its_recent_entries`. Fixed.
- `README.md`, `QUICKSTART.html`, `MANIFEST.md`, `DEM2DGED_User_Manual.md`, `START_HERE.md`, `BUILD_SCRIPTS_GUIDE.md`, `REBUILD_GUIDE.md` all still had `v0.56.0`/`v0.55.0` in their "current version" title/header. Bumped to v0.57.1. Historical changelog references to older versions (e.g. "What's new in v0.55.0", "the v0.54.0 evidence distinction") were left untouched — those are legitimate historical record, not stale headers.
- `README.md` had no "v0.57.1 release note" at all — the compliance-doc link for v0.57.1 had been tacked onto the end of the unrelated v0.55.0 paragraph instead. Added a proper v0.57.1 note (sourced from `VERSION.txt` and the mountain-terrain review) as the new top entry, and moved the link to it.

**Not fixed, flagged for you to decide:** `REQUIREMENTS_COMPLIANCE_V0.57.1.md` is a near-byte-identical copy of `REQUIREMENTS_COMPLIANCE_V0.56.0.md` — only a handful of title/header strings were swapped. Its body still describes the *v0.55.0→v0.56.0* defects, says nothing about the actual v0.57 mountain-terrain fixes, and now falsely states that `RELEASE_GATE_v0.57.1.py` "runs the whole gate in one command" — **no such file exists** (only `RELEASE_GATE_v0.56.0.py`). Similarly, `START_HERE.md` §7 and `DEM2DGED_User_Manual.md`'s release section still point at `PACKAGE_v0.55.0.py` / `RELEASE_CHECK_v0.55.0.py` — there is no v0.57.x packaging/release-gate script yet. I didn't rewrite these since it's a content-authoring decision (what evidence to claim), not a version-string fix — let me know if you want that done too.

Result after fixes: **pytest 451/451 pass, `audit_pure.py` 0 problems** (real GDAL 3.8.4/Python 3.12 sandbox — same setup used for the original v0.57.0 verification).

---

## 2. Do the three shipped fixes work? Yes, mechanically — verified independently

Confirmed directly in `dem2dged_compare.py` (not just from the changelog):
- `pick_holdout_factor(ratio, shape)` scales the hold-out test to the requested decimation ratio (capped at 20x, floored so the training grid keeps ≥8 posts per side).
- `AUTO_OPTIMIZE_CANDIDATES` now has 5 entries including `average`.
- `rms` is gone from `dem2dged_lib.VALID_RESAMPLERS`; selecting it raises a specific `SystemExit`.

Ran the shipped self-tests on real GDAL:
- `selftest_optimize_resampling.py` — PASS.
- `selftest_prefilter_math.py` — PASS (confirms the prefilter's *implementation* — kernel normalization, NoData handling, sigma formula — is sound; nothing to fix there).
- `selftest_prefilter.py` — PASS, **but see §4** below; its own printed guidance now conflicts with the corrected messaging elsewhere in the tool.

## 3. Does the error *actually* go down? Only partially — found a deeper, unfixed problem

I built an independent verification (not reusing the tool's own test harness) using the same methodology as the original review: a continuous analytic mountain surface (sum of ~300 random cosine plane waves, amplitude ∝ k⁻¹·²⁵, calibrated to the review's own stated 65% median slope / 94%-over-20%-slope target), so the true elevation at any coordinate is known exactly. I called the real, shipped `pick_best_resampling()` — both with `dst_gsd_m` set (new v0.57 behavior) and without (old, always-2x behavior) — and independently scored every candidate against true ground truth at 4×/8×/16×, averaged over 4 random terrain realizations.

**Finding: at 16× (an 80 m DGED delivery from a 5 m source — exactly the scenario the fix targets), the patched `optimize` picked Cubic B-Spline or Bilinear in every run. True ground-truth accuracy says Nearest Neighbor was actually best (RMSE ≈ 2.2 m), roughly 4× better than what the patched code selected (Cubic B-Spline, RMSE ≈ 7.7–8.4 m) — and worse, in some runs, than even the OLD pre-patch pick (Cubic Convolution).**

Root cause, confirmed by direct instrumentation: `_holdout_stats()` trains each candidate on a *sparse* lattice decimated to the hold-out spacing, then **warps it back up to full resolution** and scores the reconstruction against the dense source — i.e., it measures each algorithm's **upsampling/reconstruction quality**, not its **downsampling/decimation accuracy** (the operation `-resample optimize` is actually choosing an algorithm for). These are not the same thing, and they diverge sharply at high ratios:
- Nearest Neighbor and Average scored **identical** RMSE in every hold-out run I inspected (also visible in `selftest_optimize_resampling.py`'s own printed output: `Nearest Neighbor RMSE=0.3139` / `Average (Box Filter) RMSE=0.3139`, bit-for-bit equal). That's because GDAL's `average` resampler, when *upsampling* (destination finer than source, which is what the hold-out reconstruction step always does), typically has no other source pixel in its footprint and degenerates to picking the single nearest one — i.e., it silently behaves like Nearest during the test, even though during *real downsampling* it genuinely blends many source pixels and behaves completely differently.
- Cubic-family methods interpolate meaningfully in both directions, so they "win" this upsampling-shaped test even when, in true point-accuracy terms during real decimation, they're the worst performers on steep terrain (their local-mean bias — the same mechanism the original review identified for the pre-filter — costs them accuracy at the post itself).

The v0.57.0 fix correctly identified and fixed the *ratio* the test targets, but the test's *direction* (predict-fine-detail-from-coarse vs. actually-decimate-and-check-the-post) was never re-examined, and this is the dominant error source at high ratios — bigger than the ratio-miscalibration problem the patch fixed. There is currently **no regression test** that checks the fix's actual accuracy *outcome* (only that `holdout_factor`/`dst_gsd_m` are correctly threaded through and that `average` is a listed candidate) — `tests/test_v057_regressions.py` is structural-only, which is how this went uncaught.

## 4. Secondary finding: `selftest_prefilter.py`'s own guidance now contradicts the corrected messaging

`selftest_prefilter.py` measures error against an *ideal band-limited reference* (the theoretically best signal representable at the target post spacing) — a legitimate signal-processing question, and under that metric the pre-filter genuinely helps (+73.8% for mountainous terrain, as it reports). But the mountain-terrain review's finding — and the corrected help/GUI/README text from the v0.57.0 patch — measures error against **true physical elevation at the exact post location**, which is what DGED accuracy actually means, and under *that* metric the pre-filter measurably *hurts*. Both numbers are correct under their own definitions, but `selftest_prefilter.py`'s closing summary still says "Use it on high-relief sources being downsampled" — the literal opposite of the now-corrected guidance elsewhere. Worth a one-line caveat in that script so a future reader doesn't get two contradictory recommendations from the same codebase.

## 5. Recommendation — a better method exists, worth implementing

1. **Highest-impact fix**: redesign the hold-out test in `_holdout_stats()` (or add a second evaluation path used by `pick_best_resampling()`) so it exercises **decimation**, not reconstruction: hold out a set of source pixels, decimate the *remaining dense* source down to the target ratio with each candidate exactly as a real conversion would, and score the result against the true elevation at the withheld locations — rather than training on a sparse lattice and upsampling it back up. This directly targets the confound found in §3 and should let Nearest/Average score on their own real merits instead of collapsing to (or losing to) Cubic's upsampling behavior.
2. **Until #1 ships**, the honest guidance is the same one the original review already reached in its §3.2, now reinforced rather than superseded: default to `-resample average` (the plain `auto` default already does this above 1.25× downsampling) for steep terrain, and treat `optimize`'s recommendation at high ratios (8×+) as unverified rather than authoritative.
3. Add a **ground-truth accuracy regression test** (using the same synthetic-terrain approach as this report and the original review) that asserts `pick_best_resampling()`'s pick is within some tolerance of the true-best candidate at 8×/16× — this is the missing test that would have caught the issue in §3, and will catch a regression in any future fix to it.
4. Give `selftest_prefilter.py`'s closing summary a one-line caveat distinguishing "aliasing error vs. ideal reference" from "point accuracy vs. true elevation," pointing to the corrected guidance (§4).
5. Reconcile `REQUIREMENTS_COMPLIANCE_V0.57.1.md`, `MANIFEST.md`'s tooling list, and the release-gate references in `START_HERE.md`/`DEM2DGED_User_Manual.md` — flagged in §1, not fixed here.

Let me know if you'd like #1 and #3 implemented as a v0.58.0 patch (same process as before: implementation + regression tests + a release-gate run), or if you'd rather I address the §1 doc-content gaps first.
