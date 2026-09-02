# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.56.0
# (single source of truth: dem2dged_lib.VERSION -- audit_pure.py
#  section 7 checks every declaration in the project against it)

"""Run the DGED_Loader test harness under pytest (v0.56.0, finding C2).

WHY THIS WRAPPER EXISTS
-----------------------
DGED_Loader/test_dged_loader.py is a complete, working test suite -- roughly
forty assertions against a hand-built fake `arcpy` -- but it is written as a
standalone script: a module-level `check()` helper, a `FAILURES` list, and a
`main()` that ends in sys.exit(0) or sys.exit(1). It defines no `test_*`
functions.

pytest.ini sets `testpaths = tests`, and the harness lives in DGED_Loader/.
Between those two facts, it had never once run as part of the suite -- not in
the release gate, not in CI, not in any of the 384-test runs on record. A test
that only runs when someone remembers to invoke it by hand is a test that
eventually stops being run at all.

Rather than rewrite the harness into pytest style -- which would mean touching
every one of its assertions and losing its readable single-script form -- this
loads it, runs main(), and reports what it found. `main()` calls sys.exit(),
so SystemExit is the expected outcome, not an error; the assertion is on the
exit code and on FAILURES.

If the harness is ever converted to real test_* functions, delete this file
and add DGED_Loader to `testpaths` instead.
"""

import importlib.util
import os

import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(PROJECT_DIR, "DGED_Loader", "test_dged_loader.py")


def _load_harness():
    """Import the harness by path, without putting DGED_Loader on sys.path.

    The harness builds its own fake `arcpy` and imports the toolbox through
    it, so it must not be shadowed by, or shadow, anything else importable.
    """
    spec = importlib.util.spec_from_file_location(
        "dged_loader_test_harness", HARNESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not os.path.isfile(HARNESS),
                    reason="DGED_Loader/test_dged_loader.py is not present")
def test_the_dged_loader_harness_passes(capsys):
    """Every assertion in the loader harness, run as part of the suite."""
    module = _load_harness()

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    failures = list(getattr(module, "FAILURES", []))
    if failures:
        # Surface the harness's own labels -- they are more informative than
        # a bare exit code, and this is the only place they would otherwise
        # be swallowed by capsys.
        captured = capsys.readouterr()
        pytest.fail(
            "DGED_Loader harness reported %d failure(s):\n  %s\n\n"
            "--- harness output ---\n%s"
            % (len(failures), "\n  ".join(failures), captured.out[-4000:]))

    assert exit_info.value.code == 0


@pytest.mark.skipif(not os.path.isfile(HARNESS),
                    reason="DGED_Loader/test_dged_loader.py is not present")
def test_the_harness_is_reachable_from_the_configured_testpaths():
    """Guard the wiring itself, not just the harness.

    If someone later moves this wrapper, or narrows `testpaths` again, this
    fails loudly instead of the loader silently dropping out of the suite
    the way it did between the harness being written and v0.56.0.
    """
    ini = os.path.join(PROJECT_DIR, "pytest.ini")
    if not os.path.isfile(ini):                      # pragma: no cover
        pytest.skip("pytest.ini not present")
    with open(ini, encoding="utf-8") as f:
        text = f.read()
    testpaths = [line.split("=", 1)[1].strip()
                 for line in text.split("\n")
                 if line.strip().startswith("testpaths")]
    assert testpaths, "pytest.ini declares no testpaths"
    covered = any(os.path.abspath(os.path.join(PROJECT_DIR, p))
                  == os.path.dirname(os.path.abspath(__file__))
                  for p in testpaths[0].split())
    assert covered, (
        "this wrapper lives outside the configured testpaths (%s), so the "
        "DGED_Loader harness is not being run" % testpaths[0])
