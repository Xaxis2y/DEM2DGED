# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.48
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

r"""One-shot packaging automation for the dem2dged v0.48 release.

Run this LAST -- after RELEASE_CHECK_v0.48.py reports ALL STEPS PASSED.

    conda activate DGED
    cd /d C:\Users\xaxis\Documents\ES_Project\dem2dged_v0.48
    python PACKAGE_v0.48.py

What it does, in order:

  1. Refuses to run if the project version is not what this script expects,
     or if tests/ is missing -- the two things that went wrong in v0.40 and
     v0.41.
  2. Sweeps __pycache__, .pytest_cache, build/, dist/ and _release_check_logs
     out of the project folder.
  3. Verifies with audit_pure.py that every version declaration agrees.
  4. Builds dem2dged_v0.48.zip (source release) and
     dem2dged_validate_v0.48.zip (validator-only bundle) by calling the
     project's own packaging scripts, so there is exactly ONE definition of
     what belongs in a release.
  5. Prints the manifest of each zip, and FAILS if tests/ is absent from the
     source zip or a scratch file made it in.

Nothing here duplicates dem2dged_package.py's exclusion rules -- it calls
them. A second copy of that list is how "tests" ended up excluded in the
first place.
"""

import os
import shutil
import subprocess
import sys
import zipfile

EXPECTED_VERSION = "0.48"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.dirname(HERE)

SWEEP_DIRS = ("__pycache__", ".pytest_cache", "build", "dist",
              "_release_check_logs", ".mypy_cache")


def fail(msg):
    print("\nERROR: %s" % msg)
    sys.exit(1)


def banner(text):
    print()
    print("=" * 74)
    print(" " + text)
    print("=" * 74)


def run(cmd):
    print("$ " + " ".join(cmd))
    p = subprocess.run(cmd, cwd=HERE, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", errors="replace")
    print(out)
    return p.returncode, out


# ---------------------------------------------------------------------------
banner("1/5  Pre-conditions")

sys.path.insert(0, HERE)

# v0.46: this used to read "cannot import dem2dged_lib (...). Are you in the
# DGED environment?" -- which was reported from a prompt that plainly said
# (DGED), with osgeo installed in it. The message asserted the one thing the
# operator could see was false, sending them to reinstall packages into an
# environment that was never the problem. The real cause is running
# `PACKAGE_v0.46.py` instead of `python PACKAGE_v0.46.py`: Windows then
# resolves the .py file association and uses a different interpreter
# entirely. dem2dged_env diagnoses exactly that.
try:
    import dem2dged_env
except Exception:
    dem2dged_env = None

try:
    import dem2dged_lib as dl
except ImportError as e:
    missing = str(e).split("'")[1] if "'" in str(e) else "dem2dged_lib"
    if dem2dged_env is not None:
        sys.exit(dem2dged_env.missing_module_message(
            missing, script=os.path.basename(__file__),
            install_hint="conda install -c conda-forge gdal numpy"))
    fail("cannot import dem2dged_lib (%s)" % e)

if dl.VERSION != EXPECTED_VERSION:
    fail("dem2dged_lib.VERSION is %r but this script packages %r. "
         "Bump one or the other." % (dl.VERSION, EXPECTED_VERSION))
print("  dem2dged_lib.VERSION = %s" % dl.VERSION)

tests_dir = os.path.join(HERE, "tests")
required_tests = ("conftest.py", "test_lib.py", "test_validator.py",
                  "test_converters.py", "README.md")
if not os.path.isdir(tests_dir):
    fail("tests/ does not exist. pytest.ini sets testpaths = tests, so the "
         "release would ship a suite that cannot run. This is exactly what "
         "went wrong in v0.40 and v0.41.")
missing = [f for f in required_tests
           if not os.path.isfile(os.path.join(tests_dir, f))]
if missing:
    fail("tests/ is incomplete -- missing %s" % ", ".join(missing))
print("  tests/ present and complete (%d files)" % len(required_tests))


# ---------------------------------------------------------------------------
banner("2/5  Sweeping build artefacts")

removed = 0
for root, dirs, _files in os.walk(HERE, topdown=True):
    for d in list(dirs):
        if d in SWEEP_DIRS:
            path = os.path.join(root, d)
            shutil.rmtree(path, ignore_errors=True)
            print("  removed %s" % os.path.relpath(path, HERE))
            dirs.remove(d)
            removed += 1
print("  %d directory/ies removed" % removed)


# ---------------------------------------------------------------------------
banner("3/5  Version-consistency self-audit")

rc, out = run([sys.executable, "audit_pure.py"])
if rc != 0 or "RESULT: 0 problem(s)" not in out:
    fail("audit_pure.py did not report 0 problems -- fix that before "
         "packaging.")


# ---------------------------------------------------------------------------
banner("4/5  Building the release archives")

for script in ("dem2dged_package.py", "dem2dged_validate_package.py"):
    path = os.path.join(HERE, script)
    if not os.path.isfile(path):
        print("  SKIP %s (not present)" % script)
        continue
    rc, _ = run([sys.executable, script])
    if rc != 0:
        fail("%s exited %s" % (script, rc))


# ---------------------------------------------------------------------------
banner("5/5  Verifying the archives")

problems = []
for name in ("dem2dged_v%s.zip" % EXPECTED_VERSION,
             "dem2dged_validate_v%s.zip" % EXPECTED_VERSION):
    path = os.path.join(OUT_DIR, name)
    if not os.path.isfile(path):
        path = os.path.join(HERE, name)
    if not os.path.isfile(path):
        problems.append("%s was not produced" % name)
        continue

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    size_mb = os.path.getsize(path) / 1e6
    print("\n%s   (%d entries, %.2f MB)" % (path, len(names), size_mb))
    for n in sorted(names)[:200]:
        print("   " + n)
    if len(names) > 200:
        print("   ... and %d more" % (len(names) - 200))

    scratch = [n for n in names
               if n.lower().endswith((".tmp", ".log", ".bak", ".pyc"))
               or "__pycache__" in n]
    if scratch:
        problems.append("%s contains scratch files: %s" % (name, scratch[:5]))

    # v0.46: this used to test name.startswith("dem2dged_v"), and
    # "dem2dged_validate_v0.44.zip" starts with that prefix too --
    # "dem2dged_" followed by the "v" of "validate". So the validator-only
    # bundle, which correctly contains six files and no tests, was reported
    # as "does NOT contain tests/ -- EXCLUDE_DIRS is stripping it again".
    # An exact filename match cannot be fooled by a shared prefix.
    if name == "dem2dged_v%s.zip" % EXPECTED_VERSION:
        if not any("tests/" in n or "tests\\" in n for n in names):
            problems.append(
                "%s does NOT contain tests/ -- dem2dged_package.py's "
                "EXCLUDE_DIRS is stripping it again (v0.46 finding 2)" % name)

banner("Result")
if problems:
    for p in problems:
        print("  FAIL  %s" % p)
    sys.exit(1)

print("  Both archives built and verified.")
print("  Next: unzip %s somewhere clean, then in that folder run"
      % ("dem2dged_v%s.zip" % EXPECTED_VERSION))
print("      python RELEASE_CHECK_v%s.py" % EXPECTED_VERSION)
print("  A release gate that passes in the DEVELOPMENT folder but not in the")
print("  UNZIPPED one is precisely the class of bug that shipped v0.40.")
