#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.10
"""Beginner help for the DGIWG 250 evidence gate (GUI text and helpers).

This module holds all plain-language help strings so they can be unit-tested
without a display.  tkinter is imported lazily, only by the functions that
actually draw a window or a tooltip.

Nothing here evaluates evidence.  It only explains the workflow.
"""

import os
import sys
import webbrowser

GUIDE_BASENAME = "EVIDENCE_GATE_BEGINNER_GUIDE"

# One-line reminder shown directly under the checkbox.
CHECKLIST_LINE = (
    "Before you tick this: you need (1) an independent reference raster, "
    "(2) an evidence manifest, (3) measured accuracy numbers. "
    "Click '? How to use' for a step-by-step explanation."
)

# Hover text for every field of the evidence section.
FIELD_HELP = {
    "reference_dem": (
        "INDEPENDENT REFERENCE\n"
        "A raster (.tif/.tiff/.img/.vrt) of the same area that was measured "
        "separately from your source DEM, e.g. a survey-grade or lidar DEM. "
        "It is the 'answer key' used to grade your output.\n"
        "It must NOT be your source DEM, a resampled copy of it, or the "
        "output tiles themselves. DEM2DGED rejects those."),
    "evidence_manifest": (
        "EVIDENCE MANIFEST (compliance_evidence.json)\n"
        "A text form that records your evidence: source datum, accuracy "
        "numbers, the reference, documents, and who accepted the result.\n"
        "No manifest yet? Click 'Create template...' to make a blank one, "
        "fill it in, then press 'Load'."),
    "browse": "Choose an existing file on your computer.",
    "find_reference": (
        "FIND REFERENCE (Canada / US)\n"
        "Asks the public NRCan (HRDEM) and USGS (3DEP) catalogs which open lidar "
        "DEMs cover your source area, shows their declared accuracy and whether "
        "they are accurate enough for the selected DGED level, and downloads "
        "only your area. Needs an internet connection; only the bounding box is sent."),
    "load": (
        "Copies the values written in the manifest into the boxes below. "
        "It does NOT make the evidence valid - it only saves typing."),
    "create_template": (
        "Creates a folder with a blank compliance_evidence.json, an empty "
        "control_points.csv and a documents/ folder for the selected level. "
        "Fill them in, then press 'Load'."),
    "reference_id": (
        "A name that identifies the reference so others can find it again: "
        "dataset name + version + date, or the survey ID. "
        "Example: 'LiDAR-2025-06 Tile 12'."),
    "accuracy_method": (
        "Name of the procedure used to measure accuracy, or the ID of your "
        "quality plan. Example: 'STANAG 2215 control-point test, plan QP-7'."),
    "source_hacc": (
        "How accurate the SOURCE DEM's horizontal position is (CE90, metres), "
        "taken from the source's own documentation or survey. "
        "CE90 = 90% of points lie within this horizontal distance."),
    "source_vacc": (
        "How accurate the SOURCE DEM's heights are (LE90, metres), taken from "
        "the source's own documentation. LE90 = 90% of heights are within "
        "this vertical error."),
    "reference_hce90": (
        "MEASURED horizontal absolute accuracy of your OUTPUT (CE90, metres) "
        "against ground control. Comes from the control-point test; the "
        "evidence tool can calculate it for you."),
    "reference_hrandom": (
        "MEASURED random horizontal error per point of your OUTPUT "
        "(90%, metres): the scatter that remains after any constant shift "
        "is removed."),
    "reference_hrelative": (
        "MEASURED relative horizontal accuracy of your OUTPUT (90%, metres): "
        "how well points agree with each other inside the area."),
    "reference_vrelative": (
        "MEASURED relative vertical accuracy of your OUTPUT (90%, metres): "
        "how well heights agree with each other in a local area."),
    "strict": (
        "When ticked, the converter checks all 8 evidence items. If any is "
        "missing or wrong the run ends in HOLD (exit code 2): tiles may be "
        "written, but they must not be called fully DGIWG-compliant."),
}

HELP_TITLE = "How to use the full DGIWG 250 evidence gate"

# Short beginner explanation shown in the help window.
HELP_TEXT = """\
WHAT THIS CHECKBOX DOES
Normally DEM2DGED converts your DEM and reports how faithfully the output
copies the source. That tells you the CONVERSION was clean. It does not tell
you the HEIGHTS ARE CORRECT. The full evidence gate asks for proof that the
output is accurate against something measured separately. If the proof is
missing, the result is "HOLD" - it is not a crash and nothing is deleted.

Do you need it? Only if you must claim the product meets DGIWG 250 accuracy
requirements. For testing or everyday conversion, leave it unticked.


THE 3 THINGS YOU NEED
1. An INDEPENDENT REFERENCE  (a raster file)
2. An EVIDENCE MANIFEST      (compliance_evidence.json)
3. MEASURED ACCURACY NUMBERS (typed in, or loaded from the manifest)


1) INDEPENDENT REFERENCE - what is it and which file?
It is the "answer key": a raster of the same place that was measured by a
different method than your source DEM, with better accuracy. Examples:
survey-grade lidar DEM, a GNSS-controlled photogrammetric DEM.

GOOD: a separate lidar/survey DEM that covers your area.
BAD : your source DEM, a resampled/smoothed copy of it, the output tiles,
      or a lower-quality global DEM. DEM2DGED compares file hashes and the
      actual heights, and rejects copies (the result is FAIL, or
      NOT_EVALUATED if the overlap is too small).

Click [Browse...] next to "Independent reference" and choose the file
(.tif, .tiff, .img or .vrt). It should cover your whole area.

No reference file? In Canada or the US click [Find reference...]. It lists
open lidar DEMs (NRCan HRDEM, USGS 3DEP) that cover your source area, tells
you whether each is accurate enough for the selected level, and downloads
only your area. Fine levels (about 6 and finer) need surveyed ground control
points; open DEMs are not accurate enough to judge them.


2) EVIDENCE MANIFEST - what is it?
A plain-text form (JSON) that collects all evidence in one place: source
datum, source accuracy, reference, measured results, supporting documents
and the authority's acceptance. DEM2DGED reads it; it never invents it.

How to get one:
  a. Click [Create template...] and pick an empty folder.
  b. Open the created compliance_evidence.json in a text editor and fill
     in the values (the guide explains every field).
  c. Click [Browse...] to select the file, then [Load].
  [Load] only copies numbers into the boxes. It does not make them true.
  The "authority acceptance" entry can only be signed by an authorized
  reviewer - you cannot sign it yourself.


WHAT THE BOXES MEAN (all values are in metres)
  Reference identifier   name/version/date of the reference
  Evaluation method      procedure or quality plan used to measure accuracy
  Source horizontal CE90 source DEM's horizontal accuracy (from its docs)
  Source vertical LE90   source DEM's vertical accuracy (from its docs)
  Output absolute H CE90 measured horizontal accuracy of your OUTPUT
  Output random H 90%    measured random horizontal error of your OUTPUT
  Output relative H 90%  measured relative horizontal accuracy of OUTPUT
  Output relative V 90%  measured relative vertical accuracy of OUTPUT
  Also in the options area: "Source vertical" (vertical datum EPSG of the
  source), "Abs. H accuracy" and "Abs. V accuracy" - these must hold real
  measured numbers, NOT "auto".

Terms: CE90 = 90% of points are within this horizontal distance.
       LE90 = 90% of heights are within this vertical error.
       Absolute = against the real world. Relative = points against each
       other. Random = scatter after removing a constant shift.


STEP BY STEP
  1. Pick Source and Output folders, choose the DGED level.
  2. Select the independent reference with [Browse...].
  3. [Create template...] -> fill it in -> [Browse...] -> [Load].
  4. Check that no accuracy box is empty and Abs. H / Abs. V are not "auto".
  5. Tick "Require full implemented DGIWG 250 evidence gate".
  6. Press Convert and read the Compliance report.


IF A POP-UP APPEARS
  "Full evidence is incomplete"   a box listed in the message is empty.
  "Measured metadata required"    Abs. H / Abs. V still say "auto".
  "Invalid accuracy evidence"     a number is not a positive value in metres.
  "Reference not found"           the reference path is wrong.
  "Validator unavailable"         the validation module is missing; the full
                                  gate cannot run without it.
  Log: "Compliance HOLD ..."      the run finished but evidence did not pass.

Also: the full gate cannot be combined with --no-validate or terrain QA
"none". An "informational" profile is raised to "strict".


IMPORTANT
This produces technical evidence. It is NOT NATO or national authority
certification. Only an authorized reviewer can accept the product.
"""


def find_guide(extensions=(".html", ".md")):
    """Return the path of the beginner guide, or None.

    Looks next to the executable, in the source folder, one folder up
    (the release zip puts the guide beside the exe), and in the PyInstaller
    bundle directory.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    folders = []
    if getattr(sys, "frozen", False):
        folders.append(os.path.dirname(sys.executable))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            folders.append(meipass)
    folders += [here, os.path.dirname(here), os.getcwd()]
    for ext in extensions:
        for folder in folders:
            candidate = os.path.join(folder, GUIDE_BASENAME + ext)
            if os.path.isfile(candidate):
                return candidate
    return None


def open_guide():
    """Open the full guide in the default viewer. Returns the path or None."""
    path = find_guide()
    if not path:
        return None
    try:
        if hasattr(os, "startfile") and sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open("file://" + path)
    except Exception:
        return None
    return path


class ToolTip:
    """Small hover tooltip for a tkinter widget (lazy tkinter import)."""

    def __init__(self, widget, text, delay_ms=500, wrap=420):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.wrap = wrap
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        import tkinter as tk
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry("+%d+%d" % (x, y))
        tk.Label(self._tip, text=self.text, justify="left",
                 background="#ffffe0", foreground="#222",
                 relief="solid", borderwidth=1, wraplength=self.wrap,
                 font=("Segoe UI", 9), padx=6, pady=4).pack()

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def add_tooltip(widget, key_or_text):
    """Attach a tooltip using a FIELD_HELP key (or literal text)."""
    return ToolTip(widget, FIELD_HELP.get(key_or_text, key_or_text))


def show_help_window(parent, dark="#1a1a2e", light="#f4f6f9", mid="#2c5282"):
    """Open a scrollable beginner-help window with an 'Open full guide' button."""
    import tkinter as tk
    from tkinter import scrolledtext, messagebox

    win = tk.Toplevel(parent)
    win.title(HELP_TITLE)
    win.geometry("760x640")
    win.configure(bg=light)
    box = scrolledtext.ScrolledText(win, wrap="word", font=("Consolas", 10),
                                    bg="#ffffff", fg="#111", relief="flat")
    box.pack(fill="both", expand=True, padx=10, pady=(10, 4))
    box.insert("1.0", HELP_TEXT)
    box.configure(state="disabled")

    bar = tk.Frame(win, bg=light)
    bar.pack(fill="x", padx=10, pady=(0, 10))

    def _open():
        if not open_guide():
            messagebox.showinfo(
                "Guide file not found",
                "%s.html / .md was not found next to the program.\n"
                "The text in this window is the same summary; the full guide "
                "ships in the release zip." % GUIDE_BASENAME, parent=win)

    tk.Button(bar, text="Open full guide", command=_open, bg=mid, fg="white",
              relief="flat", padx=10, pady=4).pack(side="left")
    tk.Button(bar, text="Close", command=win.destroy, bg=mid, fg="white",
              relief="flat", padx=10, pady=4).pack(side="right")
    return win
