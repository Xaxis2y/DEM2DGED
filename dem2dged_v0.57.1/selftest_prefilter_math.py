# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
#
# selftest_prefilter_math.py
# Version: 0.57.1
#
# GDAL-FREE companion to selftest_prefilter.py.
#
# selftest_prefilter.py needs a working GDAL to exercise the raster I/O
# path. This script needs only numpy: it stubs the osgeo modules (the same
# trick audit_pure.py uses) so dem2dged_lib imports without GDAL, then
# checks the PURE MATH behind the v0.49 anti-alias pre-filter --
# _gaussian_kernel_1d(), _convolve1d(), gaussian_sigma_for_ratio(),
# validate_prefilter(), the normalised-convolution NoData handling, and
# the strip/halo blocking scheme.
#
# If scipy is installed, the separable convolution is additionally checked
# against scipy.ndimage.gaussian_filter as an INDEPENDENT reference
# implementation (agreement is ~3e-13). scipy is optional: the project
# deliberately does not depend on it, and that check is skipped without it.
#
# Usage (Anaconda Prompt):
#   conda activate dem2dged_anaconda_environment
#   python selftest_prefilter_math.py
#
# Prints PASS/FAIL per check. Exits non-zero on failure.

import os
import sys, types
import numpy as np

for name in ("osgeo", "osgeo.gdal", "osgeo.ogr", "osgeo.osr"):
    m = types.ModuleType(name)
    sys.modules[name] = m
sys.modules["osgeo"].gdal = sys.modules["osgeo.gdal"]
sys.modules["osgeo"].ogr = sys.modules["osgeo.ogr"]
sys.modules["osgeo"].osr = sys.modules["osgeo.osr"]
for mod in ("osgeo.gdal", "osgeo.ogr", "osgeo.osr"):
    sys.modules[mod].DontUseExceptions = lambda: None
    sys.modules[mod].UseExceptions = lambda: None
sys.modules["osgeo.gdal"].GA_ReadOnly = 0
sys.modules["osgeo.gdal"].GA_Update = 1
sys.modules["osgeo.gdal"].GDT_Float32 = 6

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dem2dged_lib as dl

try:
    from scipy.ndimage import gaussian_filter
    HAVE_SCIPY = True
except ImportError:
    HAVE_SCIPY = False

fails = []


def check(ok, msg):
    print(("  PASS  " if ok else "  FAIL  ") + msg)
    if not ok:
        fails.append(msg)


print("dem2dged_lib.VERSION =", dl.VERSION)
print()
print("1) kernel normalisation")
for s in (0.25, 0.5, 1.0, 2.5, 7.0):
    k = dl._gaussian_kernel_1d(s)
    check(abs(k.sum() - 1.0) < 1e-12,
          "sigma=%.2f kernel sums to 1 (got %.15f, len=%d)" % (s, k.sum(), len(k)))

print()
print("2) separable convolution matches scipy.ndimage.gaussian_filter")
rng = np.random.default_rng(0)
if not HAVE_SCIPY:
    print("  SKIP  scipy not installed -- optional cross-check skipped")
a = rng.normal(500, 120, size=(97, 131)).astype("float64")
if HAVE_SCIPY:
    for s in (0.5, 1.0, 3.0):
        k = dl._gaussian_kernel_1d(s)
        mine = dl._convolve1d(dl._convolve1d(a, k, 0), k, 1)
        ref = gaussian_filter(a, sigma=s, mode="nearest", truncate=4.0)
        err = np.abs(mine - ref).max()
        check(err < 1e-6, "sigma=%.2f max|mine-scipy| = %.3e" % (s, err))

print()
print("3) gaussian_sigma_for_ratio")
cases = [
    ((10.0, 10.0, "auto"), 0.0, "r=1 -> 0 (no-op)"),
    ((10.0, 5.0, "auto"), 0.0, "upsampling -> 0"),
    ((10.0, 30.0, "auto"), 1.0, "r=3 -> (3-1)/2 = 1.0"),
    ((5.0, 30.0, "auto"), 2.5, "r=6 -> 2.5"),
    ((1.0, 30.0, "auto"), 14.5, "1m -> 30m -> 14.5"),
    ((10.0, 30.0, "0"), 0.0, "explicit 0 disables"),
    ((10.0, 30.0, "2.5"), 2.5, "explicit sigma honoured"),
    ((0.0, 30.0, "auto"), 0.0, "unknown src gsd -> 0, no crash"),
]
for args, want, label in cases:
    got = dl.gaussian_sigma_for_ratio(*args)
    check(abs(got - want) < 1e-12, "%s (got %.4f)" % (label, got))

for bad in ("banana", "-1"):
    try:
        dl.gaussian_sigma_for_ratio(10.0, 30.0, bad)
        check(False, "sigma=%r should raise SystemExit" % bad)
    except SystemExit:
        check(True, "sigma=%r raises SystemExit" % bad)

print()
print("4) validate_prefilter")
check(dl.validate_prefilter(None) == "none", "None -> 'none' (opt-in default)")
check(dl.validate_prefilter("") == "none", "empty -> 'none'")
check(dl.validate_prefilter(" GAUSSIAN ") == "gaussian", "case/space normalised")
try:
    dl.validate_prefilter("gauss")
    check(False, "'gauss' should raise SystemExit")
except SystemExit:
    check(True, "'gauss' raises SystemExit")

print()
print("5) normalised convolution does NOT leak NoData into real terrain")
# 60x60 terrain at ~1000 m with a NoData void; a PLAIN gaussian would drag
# the -32767 sentinel far into the valid terrain around the void.
NODATA = -32767.0
z = np.full((60, 60), 1000.0)
z[20:30, 20:30] = NODATA
sigma = 3.0
k = dl._gaussian_kernel_1d(sigma)

valid = (z != NODATA).astype("float64")
num = dl._convolve1d(dl._convolve1d(z * valid, k, 0), k, 1)
den = dl._convolve1d(dl._convolve1d(valid, k, 0), k, 1)
out = np.where(den > 1e-8, num / np.maximum(den, 1e-8), 0.0)
out = np.where(valid > 0.5, out, NODATA)

naive = gaussian_filter(z, sigma=sigma, mode="nearest") if HAVE_SCIPY else None

valid_mask = valid > 0.5
worst_norm = np.abs(out[valid_mask] - 1000.0).max()
worst_naive = (np.abs(naive[valid_mask] - 1000.0).max()
               if naive is not None else float("nan"))
check(worst_norm < 1e-9,
      "normalised: worst valid-pixel error vs true 1000 m = %.3e m" % worst_norm)
if HAVE_SCIPY:
    check(worst_naive > 100.0,
          "naive (for contrast) drags valid pixels %.1f m off -- this is the "
          "bug normalised convolution avoids" % worst_naive)
check(np.all(out[~valid_mask] == NODATA),
      "void footprint preserved exactly (%d px still NoData)"
      % int((~valid_mask).sum()))

print()
print("6) flat terrain is preserved exactly (kernel has unit DC gain)")
flat = np.full((40, 40), 742.5)
k = dl._gaussian_kernel_1d(2.0)
sm = dl._convolve1d(dl._convolve1d(flat, k, 0), k, 1)
check(np.abs(sm - 742.5).max() < 1e-9,
      "constant field unchanged, max dev %.3e m" % np.abs(sm - 742.5).max())

print()
print("7) strip-with-halo blocking == whole-array pass (no seam)")
big = rng.normal(800, 200, size=(200, 64))
sigma = 2.0
k = dl._gaussian_kernel_1d(sigma)
radius = (len(k) - 1) // 2
whole = dl._convolve1d(dl._convolve1d(big, k, 0), k, 1)

ny = big.shape[0]
blocked = np.zeros_like(whole)
rows_per_block = 37          # deliberately not a divisor of 200
y = 0
while y < ny:
    h = min(rows_per_block, ny - y)
    ry0, ry1 = max(0, y - radius), min(ny, y + h + radius)
    arr = big[ry0:ry1, :]
    top_pad = radius - (y - ry0)
    bot_pad = radius - (ry1 - (y + h))
    if top_pad > 0 or bot_pad > 0:
        arr = np.pad(arr, ((max(0, top_pad), max(0, bot_pad)), (0, 0)),
                     mode="edge")
    o = dl._convolve1d(dl._convolve1d(arr, k, 0), k, 1)
    blocked[y:y + h, :] = o[radius:radius + h, :]
    y += h
seam = np.abs(blocked - whole).max()
check(seam < 1e-9,
      "blocked pass identical to whole-array pass, max diff %.3e m" % seam)

print()
print("=" * 62)
if fails:
    print("RESULT: %d FAILURE(S)" % len(fails))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("RESULT: all checks passed")
sys.exit(0)
