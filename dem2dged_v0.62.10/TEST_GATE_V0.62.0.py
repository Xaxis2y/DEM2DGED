# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.05
#
# TEST_GATE_V0.62.0.py -- local verification harness for DEM2DGED v0.62.0.
#
# Purpose
#   1. Environment report (warns if run in the conda base environment).
#   2. Verify checksums.sha256.
#   3. Run the existing pytest files that cover compliance / evidence / terrain.
#   4. Run an in-process scenario matrix against dem2dged_compliance
#      (proves conversion-fidelity statistics cannot satisfy the independent gate).
#   5. Run end-to-end CLI cases on a synthetic UTM DEM, including the known
#      suspected gaps (--no-validate bypass, informational profile).
#
# Run from an Anaconda Prompt, in the dedicated DGED environment:
#     conda activate DGED
#     cd /d C:\Users\Son\Documents\ChatGPT\dem2dged\dem2dged_v0.62.0
#     python TEST_GATE_V0.62.0.py
#
# NEVER install packages into the conda base environment.
# Output: logs\gate_test_<timestamp>.log  and  logs\gate_test_<timestamp>.json
# Return both files.

import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
# Works in both layouts: a flat project folder (dem2dged.py beside this
# script) and a release package (sources under source/).
SRC = (ROOT if os.path.isfile(os.path.join(ROOT, "dem2dged.py"))
       else os.path.join(ROOT, "source"))
LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = os.path.join(LOG_DIR, "gate_test_%s.log" % STAMP)
JSON_PATH = os.path.join(LOG_DIR, "gate_test_%s.json" % STAMP)
RESULTS = []          # list of dicts: step, name, expected, actual, status, note
_LOG = open(LOG_PATH, "w", encoding="utf-8")


def log(msg=""):
    line = str(msg)
    print(line)
    _LOG.write(line + "\n")
    _LOG.flush()


def banner(title):
    log("")
    log("=" * 78)
    log(title)
    log("=" * 78)


def record(step, name, expected, actual, note=""):
    """status: OK (matches expectation), MISMATCH (suspected defect), INFO."""
    if expected is None:
        status = "INFO"
    else:
        status = "OK" if str(expected) == str(actual) else "MISMATCH"
    RESULTS.append({"step": step, "name": name, "expected": expected,
                    "actual": actual, "status": status, "note": note})
    log("[%s] %s | expected=%s actual=%s %s" % (status, name, expected, actual, note))


def run(cmd, cwd=None, timeout=1800):
    log("$ " + " ".join(cmd))
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
        rc = p.returncode
    except subprocess.TimeoutExpired:
        out, rc = "TIMEOUT after %ss" % timeout, -999
    log(out.rstrip())
    log("-> exit code %s (%.1fs)" % (rc, time.time() - t0))
    return rc, out


# --------------------------------------------------------------------------
def step1_environment():
    banner("STEP 1  Environment")
    log("time: %s" % datetime.datetime.now().isoformat())
    log("python: %s" % sys.version.replace("\n", " "))
    log("executable: %s" % sys.executable)
    log("platform: %s" % platform.platform())
    env = os.environ.get("CONDA_DEFAULT_ENV", "(none)")
    log("CONDA_DEFAULT_ENV: %s" % env)
    if env.lower() == "base":
        log("WARNING: running in conda base. Use a dedicated environment "
            "(conda activate DGED). Do not install packages into base.")
    record(1, "not running in conda base", "True", str(env.lower() != "base"))
    for mod in ("osgeo", "numpy", "pytest", "scipy"):
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "")
            if mod == "osgeo":
                from osgeo import gdal
                ver = gdal.__version__
            log("%s: OK %s" % (mod, ver))
            record(1, "import " + mod, "True", "True", ver)
        except Exception as e:
            log("%s: MISSING (%s)" % (mod, e))
            if mod == "scipy":
                record(1, "import scipy (optional)", None, "False", str(e))
            else:
                record(1, "import " + mod, "True", "False", str(e))
    try:
        import re
        text = open(os.path.join(SRC, "dem2dged_lib.py"), encoding="utf-8").read()
        ver = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M).group(1)
        log("dem2dged_lib.VERSION: %s" % ver)
        record(1, "dem2dged_lib.VERSION", "0.62.0", ver)
    except Exception as e:
        record(1, "dem2dged_lib.VERSION readable", "True", "False", str(e))


def step2_checksums():
    banner("STEP 2  checksums.sha256")
    path = os.path.join(ROOT, "checksums.sha256")
    if not os.path.isfile(path):
        record(2, "checksums.sha256 present (release package only)", None,
               "False", "flat project folder: checksums are made by the build")
        return
    bad = missing = n = 0
    listed = set()
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        h, p = line.split(None, 1)
        p = p.strip().lstrip("*").replace("\\", "/")
        rel = p.split("/", 1)[1] if p.startswith("dem2dged/") else p
        listed.add(rel)
        n += 1
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            log("MISSING  " + rel)
            missing += 1
            continue
        d = hashlib.sha256()
        with open(full, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                d.update(chunk)
        if d.hexdigest() != h:
            log("MISMATCH " + rel)
            bad += 1
    record(2, "checksum mismatches", "0", bad, "of %d entries" % n)
    record(2, "checksum missing files", "0", missing)
    unlisted = []
    for r, _, fs in os.walk(ROOT):
        if os.path.abspath(r).startswith(LOG_DIR) or "__pycache__" in r \
                or ".pytest_cache" in r:
            continue
        for f in fs:
            rel = os.path.relpath(os.path.join(r, f), ROOT).replace("\\", "/")
            if rel not in listed:
                unlisted.append(rel)
    log("files not listed in checksums: %s" % sorted(unlisted))
    record(2, "unlisted files (informational)", None, len(unlisted),
           "; ".join(sorted(unlisted)[:12]))


def step3_pytest():
    banner("STEP 3  pytest (existing test suite)")
    try:
        import pytest  # noqa: F401
    except Exception:
        log("pytest missing. In the DGED env run:  conda install -n DGED pytest")
        record(3, "pytest available", "True", "False")
        return
    files = ["test_compliance.py", "test_evidence.py", "test_terrain.py",
             "test_validator.py", "test_resampling_report.py",
             "test_v057_regressions.py", "test_v059_regressions.py", "test_v0614_regressions.py", "test_v0615_regressions.py",
             "test_lib.py", "test_converters.py"]
    for name in files:
        tp = os.path.join("tests", name)
        if not os.path.isfile(os.path.join(SRC, tp)):
            record(3, name, "exists", "missing")
            continue
        rc, _ = run([sys.executable, "-m", "pytest", tp, "-v", "--tb=short",
                     "-p", "no:cacheprovider"], cwd=SRC, timeout=1800)
        record(3, "pytest " + name, "0", rc)


def step4_matrix():
    banner("STEP 4  Gate scenario matrix (dem2dged_compliance, in-process)")
    sys.path.insert(0, SRC)
    sys.dont_write_bytecode = True
    try:
        import dem2dged_compliance as c
    except Exception:
        log(traceback.format_exc())
        record(4, "import dem2dged_compliance", "True", "False")
        return

    perfect = {"count": 1000, "bias": 0, "rmse": 0, "p95": 0, "p99": 0, "max": 0}
    strict = {"max_bias": 1, "max_rmse": 3, "max_p95": 5, "max_p99": 8, "max_max": 10}
    conv_ok = c.conversion_fidelity(perfect, strict)
    conv_bad = c.conversion_fidelity(dict(perfect, rmse=9), strict)
    conv_info = c.conversion_fidelity(dict(perfect, rmse=500, max=900), {})
    src_ok = c.source_eligibility("6", 0.5, 0.5, 0.5, "3855")
    src_coarse = c.source_eligibility("6", 5.0, 0.5, 0.5, "3855")
    struct = c.structural_compliance(0, 3)
    meta_ok = c.accuracy_metadata_evidence({
        "metadata_absolute_horizontal_accuracy": "1.2",
        "metadata_absolute_vertical_accuracy": "0.8",
        "metadata_accuracy_basis": "operator-supplied"})
    meta_auto = c.accuracy_metadata_evidence({
        "metadata_absolute_horizontal_accuracy": "auto",
        "metadata_absolute_vertical_accuracy": "auto",
        "metadata_accuracy_basis": "DGIWG-level-goal-not-measured"})
    good = dict(reference_independent=True, reference_identifier="CTRL-1",
                accuracy_method="QP-1", horizontal_ce90_m=1.0,
                horizontal_random_90_m=0.30, relative_horizontal_90_m=0.8,
                relative_vertical_90_m=0.4)
    m_ok = {"count": 10, "p90": 0.15, "bias_removed_p90": 0.10}

    def overall(conv, ind, src=src_ok, meta=meta_ok):
        return c.build_compliance_report("6", struct, src, conv, ind,
                                         metadata_accuracy=meta)["overall"]

    def ind(metrics, **kw):
        return c.external_accuracy(metrics, "6", **kw)

    cases = [
        ("A perfect fidelity, no reference", "NOT_EVALUATED",
         overall(conv_ok, ind(None))),
        ("B perfect fidelity, reference == source", "FAIL",
         overall(conv_ok, ind(m_ok, **dict(good, reference_independent=False)))),
        ("C full independent evidence (L6)", "PASS",
         overall(conv_ok, ind(m_ok, **good))),
        ("D no method identifier", "NOT_EVALUATED",
         overall(conv_ok, ind(m_ok, **dict(good, accuracy_method=None)))),
        ("E no reference identifier", "NOT_EVALUATED",
         overall(conv_ok, ind(m_ok, **dict(good, reference_identifier=None)))),
        ("F missing horizontal random (L6)", "NOT_EVALUATED",
         overall(conv_ok, ind(m_ok, **dict(good, horizontal_random_90_m=None)))),
        ("G missing relative vertical (L6)", "NOT_EVALUATED",
         overall(conv_ok, ind(m_ok, **dict(good, relative_vertical_90_m=None)))),
        ("H vertical random above limit (0.18)", "FAIL",
         overall(conv_ok, ind({"count": 10, "p90": .5, "bias_removed_p90": .5}, **good))),
        ("I metadata 'auto' goal placeholders", "NOT_EVALUATED",
         overall(conv_ok, ind(m_ok, **good), meta=meta_auto)),
        ("J coarse source for L6", "FAIL",
         overall(conv_ok, ind(m_ok, **good), src=src_coarse)),
        ("K fidelity FAIL, everything else good", "FAIL",
         overall(conv_bad, ind(m_ok, **good))),
        ("L informational profile (no limits), huge error", "PASS",
         overall(conv_info, ind(m_ok, **good))),
    ]
    for name, exp, act in cases:
        record(4, name, exp, act)
    log("NOTE: case L documents that the 'informational' profile has no "
        "numeric limits, so gate item 3 passes with any error. Expected PASS "
        "here confirms the suspected gap; the CLI should force 'strict'.")

    # Fidelity statistics must never leak into the independent section.
    section = ind(None)
    leak = any(k in section["checks"] for k in ("rmse", "bias", "p95", "p99"))
    record(4, "fidelity metrics absent from independent section", "False", str(leak))


# --------------------------------------------------------------------------
def make_synthetic(workdir):
    from osgeo import gdal, osr
    import numpy as np
    gdal.UseExceptions()
    n, px = 1500, 1.0
    x0, y0 = 500000.0, 4501500.0
    rng = np.random.default_rng(42)
    xs, ys = np.meshgrid(np.arange(n), np.arange(n))
    base = (120 + 25 * np.sin(xs / 140.0) + 18 * np.cos(ys / 110.0)
            + 0.02 * xs).astype("float32")
    src = base + rng.normal(0, 0.05, base.shape).astype("float32")
    ref = base + rng.normal(0, 0.10, base.shape).astype("float32")

    def write(path, arr):
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(path, n, n, 1, gdal.GDT_Float32, ["COMPRESS=LZW"])
        ds.SetGeoTransform((x0, px, 0, y0, 0, -px))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(32618)
        ds.SetProjection(srs.ExportToWkt())
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(-32767)
        b.SetUnitType("metre")
        b.WriteArray(arr)
        ds.FlushCache()
        ds = None

    p_src = os.path.join(workdir, "synthetic_source.tif")
    p_ref = os.path.join(workdir, "independent_control.tif")
    p_dup = os.path.join(workdir, "copy_of_source.tif")
    p_rgd = os.path.join(workdir, "regridded_copy_of_source.tif")
    p_off = os.path.join(workdir, "offset_copy_of_source.tif")
    write(p_src, src)
    write(p_ref, ref)
    shutil.copyfile(p_src, p_dup)
    # v0.61.5 cases: derived references that are NOT byte-identical
    gdal.Warp(p_rgd, p_src, xRes=1.3, yRes=1.3, resampleAlg="cubic",
              outputBounds=(x0 + 10.4, y0 - n * px + 10.4,
                            x0 + n * px - 10.4, y0 - 10.4))
    write(p_off, src + np.float32(2.5))
    return p_src, p_ref, p_dup, p_rgd, p_off


def read_report(out_dir):
    p = os.path.join(out_dir, "validation", "compliance_report.json")
    if not os.path.isfile(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def summarize_report(rep):
    if not rep:
        log("   (no compliance_report.json written)")
        return None
    log("   overall = %s" % rep.get("overall"))
    ind = (rep.get("sections", {}).get("independent_accuracy", {})
           .get("checks", {}).get("source_reference_independence", {}))
    cc = ind.get("content_check") or {}
    if ind:
        log("   independence = %s  min_stddev_m=%s best=%s  %s" % (
            ind.get("status"), cc.get("min_stddev_m"), cc.get("best_method"),
            ind.get("reason") or ""))
    for name, sec in rep.get("sections", {}).items():
        log("   section %-22s %s" % (name, sec.get("status")))
        for cn, cv in sec.get("checks", {}).items():
            if cv.get("status") not in ("PASS", "NOT_APPLICABLE", "GOAL_MET"):
                log("       - %-38s %s %s" % (cn, cv.get("status"),
                                               cv.get("reason") or ""))
    return rep.get("overall")


def step5_e2e():
    banner("STEP 5  End-to-end CLI cases (synthetic 1 m UTM DEM -> Level 5)")
    try:
        from osgeo import gdal  # noqa: F401
    except Exception as e:
        record(5, "GDAL available for e2e", "True", "False", str(e))
        return
    work = tempfile.mkdtemp(prefix="dem2dged_gate_")
    log("work dir: " + work)
    try:
        p_src, p_ref, p_dup, p_rgd, p_off = make_synthetic(work)
    except Exception:
        log(traceback.format_exc())
        record(5, "synthetic data created", "True", "False")
        return
    record(5, "synthetic data created", "True", "True")

    base = [sys.executable, "dem2dged.py", p_src, None, "--mode", "utm",
            "--zone", "18N", "--level", "5", "--source-vertical", "3855",
            "--source-horizontal-accuracy", "0.30",
            "--source-vertical-accuracy", "0.50",
            "--terrain-qa", "full", "--quiet"]
    evidence = ["--reference-identifier", "CONTROL-TEST-01",
                "--accuracy-evaluation-method", "QUALITY-PLAN-TEST-01",
                "--reference-horizontal-ce90", "1.2",
                "--reference-horizontal-random-90", "0.30",
                "--reference-relative-horizontal-90", "0.80",
                "--reference-relative-vertical-90", "0.40",
                "--abs-hacc", "1.2", "--abs-vacc", "0.8"]

    def case(tag, extra, expected_exit, expected_overall, note="", post=None):
        out_dir = os.path.join(work, tag)
        cmd = list(base)
        cmd[3] = out_dir
        cmd += extra
        log("")
        log("--- CASE %s: %s" % (tag, note))
        rc, _ = run(cmd, cwd=SRC, timeout=1800)
        overall = summarize_report(read_report(out_dir))
        record(5, tag + " exit code", expected_exit, rc, note)
        record(5, tag + " compliance overall", expected_overall, overall)
        if post:
            post(out_dir, rc)

    case("E1_no_reference_full_gate",
         ["--require-full-compliance", "--compliance-profile", "strict"],
         2, "NOT_EVALUATED", "no reference supplied -> must not pass")
    case("E2_reference_is_source_copy",
         ["--reference-dem", p_dup, "--require-full-compliance",
          "--compliance-profile", "strict"] + evidence,
         2, "FAIL", "byte-identical reference -> independence FAIL")
    case("E3_independent_reference_full_gate",
         ["--reference-dem", p_ref, "--require-full-compliance",
          "--compliance-profile", "strict"] + evidence,
         0, "PASS",
         "all evidence supplied; read any non-PASS line above to diagnose")
    case("E4_auto_metadata_full_gate",
         ["--reference-dem", p_ref, "--require-full-compliance",
          "--compliance-profile", "strict"]
         + evidence[:-4],   # drop the trailing --abs-hacc/--abs-vacc pairs only
         2, "NOT_EVALUATED", "abs-hacc/abs-vacc left on auto -> must HOLD")
    def e5_post(out_dir, rc):
        record(5, "E5 rejected before conversion (no output folder)", "False",
               str(os.path.exists(out_dir)))

    def e6_post(out_dir, rc):
        prof = None
        try:
            prof = json.load(open(os.path.join(
                out_dir, "validation", "terrain_metrics.json"),
                encoding="utf-8")).get("compliance_profile")
        except Exception as exc:
            log("   could not read terrain_metrics.json: %s" % exc)
        record(5, "E6 effective compliance profile", "strict", prof)

    case("E5_no_validate_with_full_gate",
         ["--no-validate", "--require-full-compliance",
          "--reference-dem", p_ref, "--compliance-profile", "strict"] + evidence,
         2, None,
         "v0.61.4: must be rejected before conversion (exit 2, no tiles)",
         post=e5_post)
    case("E6_informational_profile_full_gate",
         ["--reference-dem", p_ref, "--require-full-compliance"] + evidence,
         0, "PASS",
         "v0.61.4: informational is replaced by strict; strict profile applied",
         post=e6_post)
    case("E8_terrain_qa_none_with_full_gate",
         ["--terrain-qa", "none", "--require-full-compliance",
          "--reference-dem", p_ref] + evidence,
         2, None,
         "v0.61.4: rejected up front, later --terrain-qa wins in argparse")
    case("E7_optimize_resampler_independent_still_required",
         ["--resample", "optimize", "--require-full-compliance",
          "--compliance-profile", "strict"],
         2, "NOT_EVALUATED",
         "resampler selection must not substitute for independent evidence")
    case("E9_reference_is_regridded_copy",
         ["--reference-dem", p_rgd, "--require-full-compliance",
          "--compliance-profile", "strict"] + evidence,
         2, "FAIL",
         "v0.61.5: cubic-resampled 1.3 m copy of the source -> independence FAIL")
    case("E10_reference_is_offset_copy",
         ["--reference-dem", p_off, "--require-full-compliance",
          "--compliance-profile", "strict"] + evidence,
         2, "FAIL",
         "v0.61.5: source + 2.5 m constant offset -> independence FAIL")
    log("")
    log("outputs kept in: " + work)


def final_summary():
    banner("SUMMARY")
    counts = {"OK": 0, "MISMATCH": 0, "INFO": 0}
    for r in RESULTS:
        counts[r["status"]] += 1
    log("OK=%d  MISMATCH=%d  INFO=%d" % (counts["OK"], counts["MISMATCH"], counts["INFO"]))
    log("%-4s %-9s %-58s %-16s %s" % ("step", "status", "name", "expected", "actual"))
    for r in RESULTS:
        log("%-4s %-9s %-58s %-16s %s" % (r["step"], r["status"], r["name"][:58],
                                          r["expected"], r["actual"]))
    json.dump({"stamp": STAMP, "python": sys.version, "results": RESULTS},
              open(JSON_PATH, "w", encoding="utf-8"), indent=2, default=str)
    log("")
    log("LOG : " + LOG_PATH)
    log("JSON: " + JSON_PATH)
    log("Return BOTH files to Claude.")


def main():
    for fn in (step1_environment, step2_checksums, step3_pytest,
               step4_matrix, step5_e2e):
        try:
            fn()
        except Exception:
            log("STEP CRASHED: " + fn.__name__)
            log(traceback.format_exc())
            record(0, fn.__name__ + " crashed", "no crash", "crash")
    final_summary()


if __name__ == "__main__":
    main()
