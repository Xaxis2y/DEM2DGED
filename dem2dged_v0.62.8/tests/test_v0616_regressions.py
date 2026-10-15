# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.8
"""v0.61.6: beginner help for the evidence gate (no display required)."""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import dem2dged_help as dh  # noqa: E402


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def test_guide_files_exist_and_are_found():
    assert os.path.isfile(os.path.join(ROOT, "EVIDENCE_GATE_BEGINNER_GUIDE.md"))
    assert os.path.isfile(os.path.join(ROOT, "EVIDENCE_GATE_BEGINNER_GUIDE.html"))
    assert dh.find_guide() is not None


def test_every_gui_evidence_field_has_a_tip():
    gui = _read("dem2dged_gui.py")
    for key in ("reference_id", "accuracy_method", "source_hacc", "source_vacc",
                "reference_hce90", "reference_hrandom", "reference_hrelative",
                "reference_vrelative"):
        assert "%s_var" % key in gui
        assert key in dh.FIELD_HELP and len(dh.FIELD_HELP[key]) > 40
    for key in ("reference_dem", "evidence_manifest", "load",
                "create_template", "strict"):
        assert key in dh.FIELD_HELP


def test_gui_is_wired_to_help():
    gui = _read("dem2dged_gui.py")
    assert "import dem2dged_help as dh" in gui
    assert "How to use" in gui
    assert "_show_evidence_help" in gui
    assert "dem2dged_help" in _read("dem2dged.spec")


def test_help_text_explains_the_three_things():
    text = dh.HELP_TEXT
    for needle in ("INDEPENDENT REFERENCE", "EVIDENCE MANIFEST",
                   "Create template", "Load", "CE90", "LE90", "HOLD",
                   "NOT NATO"):
        assert needle in text, needle


def test_guide_covers_gui_popup_titles():
    guide = _read("EVIDENCE_GATE_BEGINNER_GUIDE.md")
    for title in ("Full evidence is incomplete", "Measured metadata required"):
        assert title in guide
        assert title in _read("dem2dged_gui.py")


def test_packaging_includes_the_guide():
    pack = _read("BUILD_AND_PACKAGE.py")
    assert "EVIDENCE_GATE_BEGINNER_GUIDE.html" in pack
    assert "dem2dged_help.py" in pack
