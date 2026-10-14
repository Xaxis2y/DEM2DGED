# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.0
#
# Regression tests for v0.61.4 (found by TEST_GATE cases E5 and E6 on v0.61.3):
#   E5  --no-validate with --require-full-compliance exited 0, no gate run.
#   E6  the default 'informational' profile has no numeric limits, so gate
#       item 3 passed with any conversion error.

import os
import subprocess
import sys

import pytest

import dem2dged_compliance as c

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_validate_cannot_skip_full_gate():
    with pytest.raises(ValueError, match="no-validate"):
        c.resolve_full_gate_options(True, no_validate=True)


def test_terrain_qa_none_cannot_skip_fidelity_item():
    with pytest.raises(ValueError, match="terrain-qa"):
        c.resolve_full_gate_options(True, False, "strict", "none")


def test_informational_profile_is_upgraded_to_strict_for_full_gate():
    profile, notes = c.resolve_full_gate_options(True, False, "informational", "full")
    assert profile == "strict"
    assert notes and "strict" in notes[0]


@pytest.mark.parametrize("profile", ["standard", "strict"])
def test_numeric_profiles_are_kept(profile):
    out, notes = c.resolve_full_gate_options(True, False, profile, "basic")
    assert out == profile and notes == []


def test_options_untouched_without_full_gate():
    assert c.resolve_full_gate_options(
        False, True, "informational", "none") == ("informational", [])


def test_cli_rejects_no_validate_with_full_gate_before_converting(tmp_path):
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "dem2dged.py", str(tmp_path / "missing.tif"), str(out),
         "--no-validate", "--require-full-compliance"],
        cwd=SRC_DIR, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
    assert "no-validate" in proc.stderr
    assert not out.exists()


def test_validator_rejects_full_gate_without_terrain_qa(tmp_path):
    proc = subprocess.run(
        [sys.executable, "dem2dged_validate.py", str(tmp_path),
         "--require-full-compliance"],
        cwd=SRC_DIR, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
    assert "terrain-qa" in proc.stderr
