#!/usr/bin/env python3
"""
Independent re-verification of the v0.57.0/v0.57.1 mountain-terrain fix,
using the SAME methodology as dem2dged_v0.56.0_mountain_terrain_review.md:
a continuous, analytic fBm-style surface (sum of random cosine plane waves,
amplitude ~ k^-1.25) tuned to realistic mountain slope statistics, so the
true elevation at ANY coordinate is known exactly -- no interpolation
approximation needed for "ground truth".

For ratios 4x, 8x, 16x this script:
  1. Calls the REAL, shipped dem2dged_compare.pick_best_resampling() with
     dst_gsd_m set (the NEW, patched behaviour: hold out near the actual
     ratio) and records what it picks.
  2. Calls it again with dst_gsd_m=None (the OLD, pre-v0.57 behaviour:
     always a fixed 2x hold-out) and records what IT would have picked.
  3. Independently gdalwarps the source at that exact ratio for EVERY
     candidate resampler and scores each one against the true analytic
     surface at the destination post locations (ground truth the tool
     itself never has access to).
  4. Reports whether the NEW pick is actually the best (or near-best) true
     performer, and how much worse the OLD pick would really have been.
"""
import os
import sys
import shutil
import tempfile
import numpy as np
from osgeo import gdal, osr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dem2dged_compare as dc

gdal.UseExceptions()

SRC_GSD = 5.0      # m -- matches the review's "5 m source" scenario
N = 800            # source grid is N x N posts (4000 m x 4000 m)
N_TERMS = 300
BETA = 1.25        # amplitude ~ k^-BETA, matches the review's exponent
SEED = 20260904


def build_surface(seed=SEED, n_terms=N_TERMS, beta=BETA,
                   domain=N * SRC_GSD, k_min_mult=1.0, k_max_mult=0.5,
                   target_median_slope=0.65):
    """Continuous analytic terrain: z(x,y) = sum_i a_i*cos(kx_i*x+ky_i*y+phi_i).
    Returns a callable elev(X, Y) -> Z (numpy-vectorised), calibrated so the
    median slope over a sample grid is close to target_median_slope (65%,
    matching the review's stated mountain statistics)."""
    rng = np.random.default_rng(seed)
    k_min = 2 * np.pi / domain * k_min_mult
    k_max = 2 * np.pi / (2 * SRC_GSD) * k_max_mult  # up to source Nyquist
    logk = rng.uniform(np.log(k_min), np.log(k_max), n_terms)
    k = np.exp(logk)
    theta = rng.uniform(0, 2 * np.pi, n_terms)
    kx = k * np.cos(theta)
    ky = k * np.sin(theta)
    phi = rng.uniform(0, 2 * np.pi, n_terms)
    amp = k ** (-beta)

    def raw_elev(X, Y):
        Z = np.zeros_like(X, dtype=np.float64)
        for i in range(n_terms):
            Z += amp[i] * np.cos(kx[i] * X + ky[i] * Y + phi[i])
        return Z

    # Calibrate global scale to hit the target median slope on a modest
    # probe grid (cheap: N_TERMS x probe_n^2).
    probe_n = 200
    xs = (np.arange(probe_n) + 0.5) * (domain / probe_n)
    ys = (np.arange(probe_n) + 0.5) * (domain / probe_n)
    XX, YY = np.meshgrid(xs, ys)
    Zp = raw_elev(XX, YY)
    gx, gy = np.gradient(Zp, domain / probe_n)
    slope = np.sqrt(gx ** 2 + gy ** 2)
    med = np.median(slope)
    scale = target_median_slope / med if med > 0 else 1.0

    def elev(X, Y):
        return scale * raw_elev(X, Y)

    # report achieved stats
    Zc = scale * Zp
    gx, gy = np.gradient(Zc, domain / probe_n)
    slope = np.sqrt(gx ** 2 + gy ** 2)
    print("  calibrated: median slope %.1f%%, frac>20%% slope %.0f%%, relief %.1f m"
          % (100 * np.median(slope), 100 * np.mean(slope > 0.20),
             Zc.max() - Zc.min()))
    return elev


def write_source(path, elev, n=N, gsd=SRC_GSD, nodata=-32767.0):
    # geotransform origin (0,0), pixel size (+gsd, -gsd): row r's centre Y
    # is -(r+0.5)*gsd, matching gdal's north-up convention (row index
    # increases downward = Y decreases). Must match this exactly or the
    # written raster and the "truth" evaluated post-warp are unrelated.
    xs = (np.arange(n) + 0.5) * gsd
    ys = -(np.arange(n) + 0.5) * gsd
    XX, YY = np.meshgrid(xs, ys)
    Z = elev(XX, YY)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, n, n, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((0.0, gsd, 0.0, 0.0, 0.0, -gsd))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(Z.astype(np.float32))
    ds.FlushCache()
    ds = None
    return float(Z.min()), float(Z.max())


def resample_true_rmse(src_path, elev, dst_gsd, alg, work, extent):
    out = os.path.join(work, "out_%s_%d.tif" % (alg, int(dst_gsd)))
    ro = gdal.WarpOptions(
        format="GTiff",
        xRes=dst_gsd, yRes=dst_gsd,
        outputBounds=[0.0, -extent, extent, 0.0],
        resampleAlg=alg,
        dstNodata=-32767.0,
        multithread=False,
    )
    gdal.Warp(out, src_path, options=ro)
    ds = gdal.Open(out)
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    ogt = ds.GetGeoTransform()
    ny, nx = arr.shape
    ds = None

    margin = 2
    xs = ogt[0] + (np.arange(nx) + 0.5) * ogt[1]
    ys = ogt[3] + (np.arange(ny) + 0.5) * ogt[5]
    XX, YY = np.meshgrid(xs, ys)
    truth = elev(XX, YY)

    a = arr[margin:ny - margin, margin:nx - margin]
    t = truth[margin:ny - margin, margin:nx - margin]
    err = a - t
    rmse = float(np.sqrt(np.mean(err ** 2)))
    os.remove(out)
    return rmse


def main():
    work = tempfile.mkdtemp(prefix="mtn_verify_")
    try:
        seeds = [SEED, SEED + 1, SEED + 2, SEED + 3]
        extent = N * SRC_GSD
        ratios = (4, 8, 16)

        # accum[ratio] -> list of dicts per seed: {alg: rmse}, new_alg, old_alg
        accum = {r: [] for r in ratios}

        for si, seed in enumerate(seeds):
            print("=== realization %d/%d (seed=%d) ===" % (si + 1, len(seeds), seed))
            elev = build_surface(seed=seed)
            src_path = os.path.join(work, "source_%d.tif" % seed)
            zmin, zmax = write_source(src_path, elev)
            print("  source range: %.1f .. %.1f m (span %.1f m)" % (zmin, zmax, zmax - zmin))

            for ratio in ratios:
                dst_gsd = SRC_GSD * ratio
                new_alg, new_label, _ = dc.pick_best_resampling(
                    src_path, angular=False, log_fn=None, dst_gsd_m=dst_gsd)
                old_alg, old_label, _ = dc.pick_best_resampling(
                    src_path, angular=False, log_fn=None, dst_gsd_m=None)
                true_by_alg = {}
                for alg, label in dc.AUTO_OPTIMIZE_CANDIDATES:
                    true_by_alg[alg] = resample_true_rmse(
                        src_path, elev, dst_gsd, alg, work, extent)
                accum[ratio].append(dict(true=true_by_alg, new_alg=new_alg,
                                          old_alg=old_alg))
            os.remove(src_path)
            print()

        print("=" * 100)
        print("AVERAGED OVER %d RANDOM TERRAIN REALIZATIONS" % len(seeds))
        print("=" * 100)
        header = "%-4s | %-24s | %-24s | %9s | %9s | %s"
        print(header % ("rto", "NEW pick (mean true)", "OLD pick (mean true)",
                         "NEW true", "OLD true", "regret (old vs new)"))
        print("-" * 100)
        for ratio in ratios:
            runs = accum[ratio]
            # mean true RMSE per algorithm across realizations
            algs = [a for a, _ in dc.AUTO_OPTIMIZE_CANDIDATES]
            mean_true = {a: float(np.mean([r["true"][a] for r in runs])) for a in algs}
            # mean RMSE actually incurred by following the NEW pick / OLD pick
            # each realization (pick can differ per realization)
            new_incurred = float(np.mean([r["true"][r["new_alg"]] for r in runs]))
            old_incurred = float(np.mean([r["true"][r["old_alg"]] for r in runs]))
            best_alg = min(mean_true, key=lambda a: mean_true[a])
            regret = 100.0 * (old_incurred - new_incurred) / new_incurred if new_incurred > 0 else 0.0
            new_picks = [r["new_alg"] for r in runs]
            old_picks = [r["old_alg"] for r in runs]
            print(header % (
                "%dx" % ratio,
                "%s" % ",".join(sorted(set(new_picks))),
                "%s" % ",".join(sorted(set(old_picks))),
                "%.3fm" % new_incurred, "%.3fm" % old_incurred,
                ("old +%.0f%% worse" % regret) if regret > 0.5
                else (("new +%.0f%% worse" % -regret) if regret < -0.5 else "~same")))
            print("      mean true RMSE per candidate @ %dx (over %d realizations):"
                  % (ratio, len(runs)))
            label_by_alg = dict(dc.AUTO_OPTIMIZE_CANDIDATES)
            for a in algs:
                tags = []
                if a in new_picks:
                    tags.append("chosen by NEW in %d/%d runs" % (new_picks.count(a), len(runs)))
                if a in old_picks:
                    tags.append("chosen by OLD in %d/%d runs" % (old_picks.count(a), len(runs)))
                if a == best_alg:
                    tags.append("true best on average")
                tagstr = (" <- " + "; ".join(tags)) if tags else ""
                print("        %-22s mean RMSE=%.4f m%s" % (label_by_alg[a], mean_true[a], tagstr))
            print()

        print("DONE")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
