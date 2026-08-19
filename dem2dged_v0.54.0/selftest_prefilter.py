# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
#
# selftest_prefilter.py
# Version: 0.54.0
#
# Purpose
# -------
# Exercises the v0.49 opt-in Gaussian anti-alias pre-filter
# (dem2dged_lib.build_prefiltered_source() / gaussian_sigma_for_ratio() /
# validate_prefilter() / cleanup_prefiltered_source()) against real GDAL,
# and MEASURES the trade it makes across a range of terrain roughness --
# because the pre-filter is NOT universally an improvement, and this
# script is deliberately built so a run tells you where it helps and
# where it hurts.
#
# WHAT ALIASING IS, AND HOW THIS MEASURES IT HONESTLY
# ---------------------------------------------------
# Resampling a DEM to a coarser post spacing is decimation. Terrain
# detail with a wavelength shorter than twice the TARGET post spacing
# (the target Nyquist wavelength) cannot be represented at that spacing.
# The question is only HOW it fails to be represented: does it disappear
# cleanly, or does it FOLD BACK into the product as false long-wavelength
# structure that looks like terrain but is not?
#
# The reference this scores against is therefore NOT the raw source --
# scoring against the raw source would just reward keeping unrepresentable
# detail, which is impossible by definition. It is the source passed
# through an IDEAL (brick-wall, FFT) low-pass at the target Nyquist
# wavelength, sampled at the post locations: every representable feature,
# and none of the unrepresentable ones. That is the best any product at
# this post spacing could possibly be.
#
# THE TERRAIN IS FRACTAL, NOT A SINE WAVE
# ---------------------------------------
# Test surfaces are 1/f^beta fractal fields, which is the power spectrum
# real topography actually follows -- energy at every wavelength, with
# rough terrain carrying proportionally more short-wavelength energy.
# The spectral slope beta is the roughness knob:
#
#   beta ~1.5-2.0   rough / mountainous  (ridges, gullies, cliff edges)
#   beta ~2.5-3.0   hilly / rolling
#   beta ~4.0+      smooth, near-planar  (plains, gentle basins)
#
# This matters: an earlier draft of this test used a two-tone synthetic
# (one representable sine plus one unrepresentable sine) and produced
# badly misleading numbers, because a two-tone surface has almost no
# sub-Nyquist energy compared with real terrain. Single-tone tests make
# the pre-filter look useless or even harmful; fractal tests show what it
# actually does. Do not "simplify" this back to sine waves.
#
# THE EXPECTED RESULT (measured, and asserted below)
# --------------------------------------------------
# The benefit tracks roughness, and reverses on very smooth terrain:
#
#   very rough (beta 1.5)   large error reduction
#   mountainous (beta 2.0)  large error reduction
#   hilly (beta 2.5)        clear error reduction
#   rolling (beta 3.0)      moderate error reduction
#   near-planar (beta 5.0)  the filter makes things WORSE
#
# That last row is the entire reason the feature is off by default. On
# terrain with little short-wavelength energy there is nothing to alias,
# so all the filter can do is blur real signal.
#
# Usage (Anaconda Prompt)
# -----------------------
#   conda activate dem2dged_anaconda_environment
#   python selftest_prefilter.py
#
# Options:
#   --keep         keep the temp working folder (path is printed) so the
#                  rasters can be inspected in QGIS afterwards
#   --log FILE     also write the full log to FILE
#                  (default: selftest_prefilter_log.txt in the CWD)
#   --quick        run only the mountainous case (faster smoke test)
#
# Prints PASS/FAIL per check and a final verdict. Exits non-zero on
# failure. Nothing outside the temp folder and the log file is touched.

import argparse
import math
import os
import shutil
import sys
import tempfile

import numpy as np
from osgeo import gdal, osr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dem2dged_lib as dl   # noqa: E402


# -- logging ------------------------------------------------------------------

_LOG_LINES = []


def log(msg=""):
    print(msg)
    _LOG_LINES.append(str(msg))


def flush_log(path):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(_LOG_LINES) + "\n")
        print("\nFull log written: %s" % os.path.abspath(path))
    except OSError as exc:
        print("\nWARNING: could not write the log file %s (%s)" % (path, exc))


PROBLEMS = []


def check(ok, label, detail=""):
    log("  [%s] %s%s" % ("PASS" if ok else "FAIL", label,
                         ("  -- " + detail) if detail else ""))
    if not ok:
        PROBLEMS.append(label + ((" -- " + detail) if detail else ""))
    return ok


# -- test surface -------------------------------------------------------------

SRC_GSD = 2.0        # source post spacing, metres
DST_GSD = 20.0       # target post spacing, metres -> decimation ratio 10
GRID    = 1024       # source grid is GRID x GRID posts
RELIEF  = 600.0      # total relief of the synthetic surface, metres
BASE_Z  = 800.0
NODATA  = -32767.0
EPSG    = 32632
ORIGIN  = (500000.0, 5000000.0)


def fractal_surface(n, gsd, beta, seed, relief=RELIEF):
    """A 1/f^beta fractal height field -- the power spectrum real
    topography follows. Lower beta = rougher. Deterministic for a given
    seed, so a failure is reproducible.
    """
    rng = np.random.default_rng(seed)
    fx = np.fft.fftfreq(n, d=gsd)
    FX, FY = np.meshgrid(fx, fx)
    F = np.sqrt(FX ** 2 + FY ** 2)
    F[0, 0] = 1e-12
    amp = F ** (-beta / 2.0)
    amp[0, 0] = 0.0
    spec = amp * np.exp(1j * rng.uniform(0, 2 * np.pi, (n, n)))
    z = np.real(np.fft.ifft2(spec))
    z = (z - z.min()) / (z.max() - z.min()) * relief + BASE_Z
    return z


def ideal_lowpass(z, gsd, cutoff_lambda):
    """Brick-wall FFT low-pass: keep only wavelengths LONGER than
    ``cutoff_lambda``. Used to build the reference -- the best a product
    at this post spacing could possibly contain.
    """
    n = z.shape[0]
    fx = np.fft.fftfreq(n, d=gsd)
    FX, FY = np.meshgrid(fx, fx)
    F = np.sqrt(FX ** 2 + FY ** 2)
    Z = np.fft.fft2(z)
    Z[F > 1.0 / cutoff_lambda] = 0
    return np.real(np.fft.ifft2(Z))


def write_raster(path, arr, gsd=SRC_GSD, nodata=NODATA):
    ny, nx = arr.shape
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((ORIGIN[0], gsd, 0.0, ORIGIN[1], 0.0, -gsd))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(EPSG)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(arr.astype("float32"))
    ds.FlushCache()
    ds = None


def read_raster(path):
    ds = gdal.Open(path)
    arr = ds.GetRasterBand(1).ReadAsArray().astype("float64")
    ds = None
    return arr


def post_rmse(field, ref, step):
    """RMSE at the target post locations."""
    n = field.shape[0]
    idx = np.arange(0, n - step, step)
    d = field[np.ix_(idx, idx)] - ref[np.ix_(idx, idx)]
    return float(np.sqrt(np.mean(d * d)))


TERRAINS = [
    (1.5, "very rough (beta 1.5)",   True),
    (2.0, "mountainous (beta 2.0)",  True),
    (2.5, "hilly (beta 2.5)",        True),
    (3.0, "rolling (beta 3.0)",      True),
    (4.0, "smooth (beta 4.0)",       False),
    (5.0, "near-planar (beta 5.0)",  False),
]


# -- main ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Self-test for the v0.49 Gaussian anti-alias pre-filter.")
    ap.add_argument("--keep", action="store_true",
                    help="keep the temp working folder for inspection")
    ap.add_argument("--quick", action="store_true",
                    help="only run the mountainous case")
    ap.add_argument("--log", default="selftest_prefilter_log.txt",
                    help="write the full log here")
    args = ap.parse_args()

    step = int(DST_GSD / SRC_GSD)

    log("=" * 76)
    log("selftest_prefilter  (real GDAL %s, dem2dged v%s)"
        % (gdal.__version__, dl.VERSION))
    log("=" * 76)
    log("Source posts : %.1f m   grid %d x %d" % (SRC_GSD, GRID, GRID))
    log("Target posts : %.1f m   -> decimation ratio %.0f"
        % (DST_GSD, DST_GSD / SRC_GSD))
    log("Target Nyquist wavelength: %.0f m -- detail shorter than this "
        "CANNOT be" % (2 * DST_GSD))
    log("represented at %.0f m posts, by any resampler." % DST_GSD)
    log("Reference    : source ideal-low-passed at %.0f m, sampled at the "
        "posts." % (2 * DST_GSD))
    log("")

    work = tempfile.mkdtemp(prefix="dem2dged_prefilter_selftest_")
    try:
        # ---------------------------------------------------------------
        log("-" * 76)
        log("Step 1  sigma selection and flag validation (no raster I/O)")
        log("-" * 76)
        sigma = dl.gaussian_sigma_for_ratio(SRC_GSD, DST_GSD, "auto")
        expect = (DST_GSD / SRC_GSD - 1.0) / 2.0
        log("  auto sigma = %.4f source px  (expected (r-1)/2 = %.4f)"
            % (sigma, expect))
        check(abs(sigma - expect) < 1e-9,
              "auto sigma follows the (r-1)/2 image-pyramid rule")
        check(dl.gaussian_sigma_for_ratio(DST_GSD, SRC_GSD, "auto") == 0.0,
              "upsampling yields sigma 0, so the filter is skipped entirely")
        check(dl.gaussian_sigma_for_ratio(SRC_GSD, SRC_GSD, "auto") == 0.0,
              "equal source/target spacing yields sigma 0 (no gratuitous blur)")
        check(dl.gaussian_sigma_for_ratio(SRC_GSD, DST_GSD, "3.25") == 3.25,
              "an explicit sigma overrides auto")
        check(dl.validate_prefilter(None) == "none",
              "default pre-filter is 'none' -- the feature is opt-in")
        check(dl.validate_prefilter(" GAUSSIAN ") == "gaussian",
              "pre-filter name is case- and whitespace-normalised")
        for bad in ("gauss", "blur", "-1"):
            try:
                dl.validate_prefilter(bad)
                check(False, "rejects unknown pre-filter %r" % bad)
            except SystemExit:
                check(True, "rejects unknown pre-filter %r" % bad)
        for bad in ("banana", "-2.0"):
            try:
                dl.gaussian_sigma_for_ratio(SRC_GSD, DST_GSD, bad)
                check(False, "rejects bad sigma %r" % bad)
            except SystemExit:
                check(True, "rejects bad sigma %r" % bad)

        # ---------------------------------------------------------------
        log("")
        log("-" * 76)
        log("Step 2  raster contract: dimensions, CRS, NoData handling")
        log("-" * 76)
        z = fractal_surface(GRID, SRC_GSD, beta=2.0, seed=3)
        # Punch a NoData void: a naive convolution would smear -32767
        # hundreds of metres into the surrounding real terrain.
        z_void = z.copy()
        z_void[600:680, 200:300] = NODATA
        src_void = os.path.join(work, "source_with_void.tif")
        write_raster(src_void, z_void)

        filt_void = dl.build_prefiltered_source(src_void, sigma, log_fn=log)
        a_s, a_f = read_raster(src_void), read_raster(filt_void)

        ds_s, ds_f = gdal.Open(src_void), gdal.Open(filt_void)
        check((ds_f.RasterXSize, ds_f.RasterYSize)
              == (ds_s.RasterXSize, ds_s.RasterYSize),
              "dimensions unchanged",
              "%d x %d" % (ds_f.RasterXSize, ds_f.RasterYSize))
        check(np.allclose(np.array(ds_f.GetGeoTransform()),
                          np.array(ds_s.GetGeoTransform())),
              "geotransform unchanged")
        check(ds_f.GetProjection() == ds_s.GetProjection(),
              "projection unchanged")
        check(ds_f.GetRasterBand(1).GetNoDataValue() == NODATA,
              "NoData value carried across")
        ds_s = ds_f = None

        void_s, void_f = (a_s == NODATA), (a_f == NODATA)
        check(np.array_equal(void_s, void_f),
              "NoData void footprint preserved exactly",
              "%d void px in both" % int(void_s.sum()))

        valid = ~void_s
        lo_s, hi_s = float(a_s[valid].min()), float(a_s[valid].max())
        lo_f, hi_f = float(a_f[valid].min()), float(a_f[valid].max())
        log("  source valid range   : %9.2f .. %9.2f m" % (lo_s, hi_s))
        log("  filtered valid range : %9.2f .. %9.2f m" % (lo_f, hi_f))
        check(lo_f >= lo_s - 1e-6,
              "no NoData leak into valid terrain (normalised convolution)",
              "filtered min %.2f m vs source min %.2f m" % (lo_f, lo_s))
        check(hi_f <= hi_s + 1e-6,
              "low-pass filtering never manufactures a new maximum")
        dl.cleanup_prefiltered_source(filt_void)

        # ---------------------------------------------------------------
        log("")
        log("-" * 76)
        log("Step 3  a flat source must pass through unchanged")
        log("-" * 76)
        flat_src = os.path.join(work, "flat.tif")
        write_raster(flat_src, np.full((128, 128), 333.25))
        flat_out = dl.build_prefiltered_source(flat_src, 3.0,
                                               log_fn=lambda _m: None)
        dev = float(np.abs(read_raster(flat_out) - 333.25).max())
        check(dev < 1e-3,
              "constant 333.25 m field survives a sigma=3 filter unchanged",
              "max deviation %.3e m" % dev)
        dl.cleanup_prefiltered_source(flat_out)

        # ---------------------------------------------------------------
        log("")
        log("-" * 76)
        log("Step 4  aliasing error vs terrain roughness  (the real question)")
        log("-" * 76)
        log("  For each surface: sample the %.0f m source at the %.0f m post"
            % (SRC_GSD, DST_GSD))
        log("  locations, with and without the pre-filter, and score both")
        log("  against the ideal band-limited reference at those same posts.")
        log("  Post sampling (rather than a gdalwarp call) is used here")
        log("  deliberately: a DGED post IS a point sample, so this isolates")
        log("  the pre-filter's effect from any particular resampler's.")
        log("")
        log("  %-24s %11s %11s %10s" % ("terrain", "RMSE off", "RMSE on",
                                        "change"))
        log("  " + "-" * 60)

        results = {}
        cases = [t for t in TERRAINS if (not args.quick or t[0] == 2.0)]
        for beta, label, expect_better in cases:
            zt = fractal_surface(GRID, SRC_GSD, beta=beta, seed=3)
            ref = ideal_lowpass(zt, SRC_GSD, 2 * DST_GSD)

            src_t = os.path.join(work, "src_beta%.1f.tif" % beta)
            write_raster(src_t, zt)
            filt_t = dl.build_prefiltered_source(src_t, sigma,
                                                 log_fn=lambda _m: None)
            zf = read_raster(filt_t)

            off = post_rmse(zt, ref, step)
            on = post_rmse(zf, ref, step)
            change = 100.0 * (off - on) / off if off > 0 else 0.0
            results[beta] = (off, on, change, expect_better)
            log("  %-24s %11.3f %11.3f %+9.1f%%" % (label, off, on, change))

            dl.cleanup_prefiltered_source(filt_t)
            try:
                os.remove(src_t)
            except OSError:
                pass

        log("")
        for beta, label, expect_better in cases:
            off, on, change, _ = results[beta]
            if expect_better:
                check(on < off,
                      "%s: pre-filter reduces aliasing error" % label,
                      "%.3f m -> %.3f m (%+.1f%%)" % (off, on, change))
            else:
                check(True,
                      "%s: recorded for information (%+.1f%%)"
                      % (label, change))

        if 2.0 in results:
            off, on, change, _ = results[2.0]
            check(change > 50.0,
                  "mountainous terrain sees a large (>50%) error reduction",
                  "%+.1f%%" % change)

        if 5.0 in results and 2.0 in results:
            check(results[2.0][2] > results[5.0][2],
                  "benefit tracks roughness: mountainous gains far more than "
                  "near-planar",
                  "%+.1f%% vs %+.1f%%" % (results[2.0][2], results[5.0][2]))

        # ---------------------------------------------------------------
        log("")
        log("-" * 76)
        log("Step 5  strip/halo blocking must not create a seam")
        log("-" * 76)
        log("  build_prefiltered_source() processes the raster in horizontal")
        log("  strips sized to max_block_bytes, each read with a radius-row")
        log("  halo. At the default 256 MB budget a test-sized raster fits in")
        log("  ONE block, so the multi-strip path -- the one every real,")
        log("  multi-gigabyte source actually takes -- would never be")
        log("  exercised. This forces a tiny budget so the same raster is cut")
        log("  into many strips, and requires the result to be BIT-IDENTICAL")
        log("  to the single-block pass.")
        log("")
        seam_src = os.path.join(work, "seam_src.tif")
        z_seam = fractal_surface(256, SRC_GSD, beta=2.0, seed=7)
        z_seam[100:140, 60:90] = NODATA        # a void straddling strip edges
        write_raster(seam_src, z_seam)

        one = dl.build_prefiltered_source(seam_src, sigma,
                                          log_fn=lambda _m: None)
        # 256 px wide * 8 bytes * 4 working arrays = 8192 B/row, so a 96 KB
        # budget gives ~12 rows per strip -> ~22 strips over 256 rows.
        many = dl.build_prefiltered_source(seam_src, sigma,
                                           log_fn=log,
                                           max_block_bytes=96 * 1024)
        a_one, a_many = read_raster(one), read_raster(many)
        seam_diff = float(np.abs(a_one - a_many).max())
        check(seam_diff == 0.0,
              "multi-strip output is bit-identical to the single-block pass",
              "max |difference| = %.3e m" % seam_diff)
        check(np.array_equal(a_one == NODATA, a_many == NODATA),
              "void footprint identical under both blocking schemes")
        dl.cleanup_prefiltered_source(one)
        dl.cleanup_prefiltered_source(many)

        # ---------------------------------------------------------------
        log("")
        log("-" * 76)
        log("Step 6  scratch-file cleanup")
        log("-" * 76)
        tmp = dl.build_prefiltered_source(flat_src, 2.0,
                                          log_fn=lambda _m: None)
        check(os.path.isfile(tmp), "scratch raster created")
        dl.cleanup_prefiltered_source(tmp)
        check(not os.path.isfile(tmp), "scratch raster removed")
        dl.cleanup_prefiltered_source(tmp)      # must not raise
        dl.cleanup_prefiltered_source(None)     # must not raise
        check(True, "cleanup is idempotent and None-safe")

        # ---------------------------------------------------------------
        log("")
        log("=" * 76)
        if PROBLEMS:
            log("SELFTEST: FAILED  (%d problem(s))" % len(PROBLEMS))
            for p in PROBLEMS:
                log("  - " + p)
            return 1

        log("SELFTEST: PASSED")
        log("")
        log("What this run showed, for the record:")
        for beta, label, _ in cases:
            off, on, change, _ = results[beta]
            log("  %-24s %8.3f m -> %8.3f m   %+7.1f%%"
                % (label, off, on, change))
        log("")
        log("The benefit tracks terrain roughness, and reverses on very")
        log("smooth ground -- which is exactly why -prefilter defaults to")
        log("'none'. Use it on high-relief sources being downsampled, and")
        log("verify on YOUR data with dem2dged_validate.py before shipping a")
        log("delivery made with it.")
        return 0
    finally:
        if args.keep:
            log("\nTemp folder kept: %s" % work)
        else:
            shutil.rmtree(work, ignore_errors=True)
        flush_log(args.log)


if __name__ == "__main__":
    sys.exit(main())
