# DEM2DGED Evidence Gate — Beginner's Guide

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON

**For DEM2DGED v0.62.0.** This guide explains, in plain language, the part of
DEM2DGED that confuses most new users: the box called **"Require full
implemented DGIWG 250 evidence gate"**, the **Independent reference** file,
and the **Evidence manifest**. You do not need to know anything about DGIWG
before you start.

---

## Contents

1. [Do I need this at all?](#1-do-i-need-this-at-all)
2. [The big idea in one minute](#2-the-big-idea-in-one-minute)
3. [Words you will see (glossary)](#3-words-you-will-see-glossary)
4. [What is the "Independent reference"?](#4-what-is-the-independent-reference)
5. [What is the "Evidence manifest"?](#5-what-is-the-evidence-manifest)
6. [Every box in the GUI, one by one](#6-every-box-in-the-gui-one-by-one)
7. [Step-by-step: run the full gate in the GUI](#7-step-by-step-run-the-full-gate-in-the-gui)
8. [The same thing from the command line](#8-the-same-thing-from-the-command-line)
9. [The pop-up messages and what to do](#9-the-pop-up-messages-and-what-to-do)
10. [Reading the result](#10-reading-the-result)
11. [Every field of the evidence manifest explained](#11-every-field-of-the-evidence-manifest-explained)
12. [The control-point CSV file](#12-the-control-point-csv-file)
13. [The seven evidence steps](#13-the-seven-evidence-steps)
14. [Accuracy limits per level](#14-accuracy-limits-per-level)
15. [Practice run with safe test data](#15-practice-run-with-safe-test-data)
16. [Common mistakes and FAQ](#16-common-mistakes-and-faq)
17. [What this tool does not claim](#17-what-this-tool-does-not-claim)

---

## 1. Do I need this at all?

**Most conversions do not.** A normal conversion already checks that your
tiles are built correctly (names, grid, file format, metadata, edges, NoData).
That is the default and needs none of the boxes in this guide.

| Your situation | What to do |
|---|---|
| "I just want DGED tiles that open in ArcGIS Pro." | Leave the evidence boxes **empty**. Skip this guide. |
| "I want to check that the conversion did not damage the terrain." | Tick **Validate after conversion**. No evidence boxes needed. |
| "Someone asked me to *prove* the delivery meets DGIWG 250 accuracy." | **Use this guide.** You need a second, independent elevation dataset and some measured numbers. |
| "I only want a quick demo with fake numbers." | Do not use the full gate. It is designed to refuse fake or missing evidence. |

If the last two rows do not describe you, close this guide and convert as
usual.

---

## 2. The big idea in one minute

DEM2DGED can ask two very different questions:

| Question | Everyday comparison | How DEM2DGED answers it |
|---|---|---|
| **A. Did the conversion copy my source faithfully?** | "Did the photocopier copy the page correctly?" | Compares the tiles with your source DEM. Always available. Called **conversion fidelity**. |
| **B. Is the elevation data itself correct, compared with the real ground?** | "Is the page that was copied even true?" | Needs a **second, independent dataset** that is more trustworthy than your source. This is the **independent reference**. |

Question A can never answer question B. A perfect copy of a wrong map is still
a wrong map. That is why DEM2DGED will not give a full PASS without question B
being answered with real, independent evidence.

The **full evidence gate** is a switch that says:
*"Do not call this delivery fully checked unless **every** required piece of
evidence is present and passes."* If anything is missing the result is a
**HOLD** (an incomplete result — not a failure of your tiles).

```
 Your source DEM ──► DEM2DGED ──► DGED tiles
        │                             │
        │  (A) fidelity check ◄───────┤
        │                             │
 Independent reference ─────────────► (B) accuracy check   ◄── measured numbers
 (a different, better dataset)                                  (from your survey / quality plan)
                                      │
                                      ▼
                          compliance_report: PASS / FAIL / NOT_EVALUATED
```

---

## 3. Words you will see (glossary)

You can come back to this table whenever a word is unfamiliar.

| Word | Plain meaning |
|---|---|
| **DGED** | The tile format DEM2DGED produces (Defence Gridded Elevation Data). |
| **DGIWG 250** | The rulebook that defines DGED. "Level 5, Level 6…" come from it. |
| **Level** | How fine the grid is. Level 5 ≈ 2 m between points, Level 6 ≈ 1 m, Level 7 ≈ 0.5 m. A higher number means finer detail and **tighter accuracy limits**. |
| **Post** | One elevation value in the grid (one "pixel"). |
| **Metres (m)** | Every accuracy number in this guide is in metres. |
| **Horizontal** | Position on the map (east/north). "Is this hill in the right place?" |
| **Vertical** | Height. "Is this hill the right height?" |
| **Error** | Your data minus the truth (or minus the reference). Can be positive or negative. |
| **Bias** | The average error. If every height is 0.3 m too high, the bias is +0.3 m. |
| **Absolute accuracy** | How close the data is to the real world, including any bias. |
| **Random error** | The scatter that is left after you remove the bias. |
| **Relative accuracy** | How well two nearby points agree with *each other*, even if both are shifted. Measured on *pairs* of points. |
| **CE90** | "Circular Error 90%". A horizontal accuracy number: 90 % of points are within this many metres of their true position. |
| **LE90** | "Linear Error 90%". A vertical accuracy number: 90 % of points are within this many metres of their true height. |
| **"90 %" / P90** | "90 % of the measurements are at least this good." Statisticians call it the 90th percentile. |
| **Independent reference** | A second elevation dataset, not made from your source, used as the yardstick. See [section 4](#4-what-is-the-independent-reference). |
| **Control points** | Individual spots whose true position and height were measured very accurately (for example by a survey crew). |
| **Evidence manifest** | A checklist file (`compliance_evidence.json`) that records your evidence and where the supporting documents are. See [section 5](#5-what-is-the-evidence-manifest). |
| **Provenance** | The paper trail: who made a dataset, when, and how. |
| **Quality plan / evaluation method** | The written procedure that says *how* accuracy is measured. DEM2DGED does not invent one — you supply its ID. |
| **STANAG 2215** | A NATO standard about evaluating the accuracy of geospatial data. DEM2DGED's checks are *aligned with* it; they do not replace it. |
| **EGM2008 / EPSG:3855** | The height reference ("zero level") that DGED uses. A DEM measured from a different zero level must be converted first. |
| **Vertical datum / vertical EPSG** | The code naming the height reference of your source (for example 3855 = EGM2008, 5773 = EGM96). |
| **PASS** | Every automatic check had evidence and passed. |
| **FAIL** | At least one check ran and did not meet the rule. |
| **NOT_EVALUATED** | A check could not run because evidence is missing. **This is not a pass.** |
| **HOLD** | The "stop and complete the evidence" state. In practice: the report is NOT_EVALUATED or FAIL, and the command line returns exit code 2. |
| **SHA-256** | A fingerprint of a file. Two files with the same fingerprint are identical. |

---

## 4. What is the "Independent reference"?

### In one sentence

**A second elevation raster of the same place that someone else measured by a
different method, used as the yardstick for your delivered tiles.**

### What it is used for

DEM2DGED compares your finished DGED tiles with the independent reference and
calculates the **vertical** accuracy numbers itself (random and absolute
vertical error). It also builds an *error budget* that separates the error
that was already in your source from the error added by the conversion.

### What file to pick

| Requirement | Why |
|---|---|
| A raster file: `.tif`, `.tiff`, `.img` or `.vrt`. | These are the types the **Browse…** button offers. |
| Covers the same area as the DEM you are converting (at least a good part of it). | There must be overlap to compare. |
| One elevation band in **metres**. | The comparison is done in metres. |
| **Already in the same height reference (vertical datum) as your DGED output** (EGM2008, EPSG:3855). | DEM2DGED aligns the position of the two rasters but **never silently shifts heights**. A datum mismatch would show up as a fake error. |
| **Not your source DEM, and not made from it.** | See below. |
| More trustworthy than your source. | A yardstick must be better than the thing it measures. Many quality plans ask for a reference that is several times more accurate; follow the rule in *your* quality plan. |
| Has a paper trail (who, when, how). | Required for the evidence package (identifier, provider, date, provenance document). |

### Good examples

* A survey-grade airborne LiDAR elevation model of the area, produced by a
  different supplier than your source.
* A national mapping agency's high-accuracy DEM, if your source is a global or
  satellite DEM.
* A DEM built from a separate field survey or a separate photogrammetry
  campaign.

### Bad examples (DEM2DGED will reject or flag these)

| What you might try | What happens |
|---|---|
| The same file as the source DEM. | Rejected: independence **FAIL**. |
| A copy of the source (copy/paste, different file name). | Rejected: identical fingerprint, independence **FAIL**. |
| The source re-saved, resampled to another cell size, re-projected, or shifted by a constant. | Rejected: since v0.61.5 DEM2DGED resamples your source onto the reference grid. If the two differ by no more than about 5 mm after removing a constant offset, the reference is judged **derived from the source** → independence **FAIL**. |
| The DGED tiles you are testing. | Not independent — it is the thing being tested. |
| A reference too small or not overlapping. | Independence **NOT_EVALUATED** (the check could not run), so the gate holds. |

> **Honest limit of the automatic check.** It catches straight copies and
> common resampled/shifted copies. It cannot catch every disguised copy (for
> example one that was heavily smoothed or made with unusual resampling
> methods). The provenance document you attach (*who made the reference and
> how*) remains the real proof of independence. Never choose a derived file on
> purpose to "get a PASS": the report would then be false.

### Where do I get one?

Ask the people who supplied or commissioned the data — a survey provider, a
mapping agency, or your quality-assurance team. The project file
`DEM_SOURCES_GUIDE.md` lists places to look for source DEMs. If you have no
independent reference, you cannot complete the full gate; ordinary conversion
and validation still work (see section 1).

---

### 4.6 Finding a reference automatically (Canada and US, new in v0.62.0)

You do not have to hunt for the file yourself. Add your source DEM, choose the
DGED level, and click **Find reference…** next to *Independent reference*.

1. Press **Search**. DEM2DGED asks the public catalogs of Natural Resources
   Canada (HRDEM) and the US Geological Survey (3DEP) which open lidar DEMs
   cover your source area. Only the box around your area is sent.
2. Read the table. **Fit for level** is the important column:

   | Fit | Meaning |
   |---|---|
   | `OK` | The reference's declared vertical accuracy is at least 3 times better than the level needs. Good. |
   | `MARGINAL` | Between 2 and 3 times better. Usable as a rough check only. |
   | `TOO_COARSE` | Not accurate enough to judge this level. Choose another dataset or use surveyed ground control points. |
   | `UNKNOWN` | The provider does not state an accuracy. Read its metadata. |

3. Select a row to read its accuracy statement, vertical datum, license and
   limits. Press **Download clip**, choose a folder and confirm. Only the pixels
   inside your area are copied, with no resampling, and the boxes
   *Independent reference* and *Reference identifier* are filled in for you.
4. A small `…_reference.json` file is saved beside the clip. It records the
   dataset, its SHA-256, the declared accuracy, the datum, the license and
   warnings. Keep it with your evidence documents.

Please remember:

* **Open DEMs cannot judge fine levels.** The best open US data (3DEP 1 m) is
  only marginal at Level 5 and too coarse for Levels 6 and finer. Those levels
  need surveyed ground control points (section 12).
* **Check the vertical datum.** HRDEM uses CGVD2013 and 3DEP uses NAVD88. If your
  source or output uses a different one, heights differ by decimetres to
  metres and the accuracy numbers will be wrong.
* **A download does not prove independence.** If your source DEM was made from
  the same lidar survey, the reference is not independent. Say so in your
  reference provenance document.
* The accuracy shown is what the provider declares. DEM2DGED does not measure it.

Command line: `python dem2dged_reference.py --source my_dem.tif --level 5 --list`
shows the table; add `--pick 1` (without `--list`) to download.

## 5. What is the "Evidence manifest"?

### In one sentence

**A checklist/record file named `compliance_evidence.json` where you write
down your evidence — values, document IDs and file locations — so you (and a
reviewer) have it all in one place.**

Think of it as the **cover sheet of an inspection folder**. The folder holds
the real documents (PDF reports, survey certificates); the cover sheet lists
what is inside and records the key numbers.

### What it is NOT

* It does **not** create evidence. Typing a number into it does not make it
  true.
* It does **not** approve your delivery. Only your designated authority can do
  that (step 7 in [section 13](#13-the-seven-evidence-steps)).
* It is **not required** to run the gate. It is a convenience. You can type
  every value into the GUI by hand instead.

### What the buttons do

| Button (GUI) | What it does |
|---|---|
| **Create template…** | You pick an empty folder. DEM2DGED writes the evidence package skeleton there (see below) and fills in the manifest field with its path. |
| **Browse…** | Pick an existing `compliance_evidence.json`. |
| **Load** | Reads the manifest and **copies its values into the GUI boxes** (reference file, identifier, method, accuracy numbers, source vertical code). It also prints the readiness of your evidence in the log. It changes nothing in the manifest and creates no evidence. |

### What "Create template…" makes

```
your_evidence_folder/
├── compliance_evidence.json        ← the manifest (the cover sheet)
├── control_points.csv              ← empty table for survey points (optional)
├── EVIDENCE_WORKFLOW.md            ← the 7 steps, short version
├── AUTHORITY_ACCEPTANCE_FORM.txt   ← form for the approving authority
└── documents/
    └── README.txt                  ← put your real PDFs here
```

The template will not overwrite existing files: if the folder already holds
these files, choose a new folder.

Section 11 explains every field inside the manifest.

---

## 6. Every box in the GUI, one by one

The box **"DGIWG Accuracy Evidence (required for full gate)"** and two boxes
in the options area are involved.

| GUI box | What to enter | Where the value comes from | Example |
|---|---|---|---|
| **Source vertical** (options area) | The EPSG number of your **source's** height reference. | The source's metadata or product specification. Leave empty only if the raster itself carries it. | `3855` (EGM2008), `5773` (EGM96) |
| **Abs. H accuracy** (options area) | Your **measured** absolute horizontal accuracy (CE90) of the delivered data, in metres. A number, not `auto`. | The result of your accuracy evaluation (the "Output absolute H CE90" value below). | `1.2` |
| **Abs. V accuracy** (options area) | Your **measured** absolute vertical accuracy (LE90) of the delivered data, in metres. A number, not `auto`. | Your accuracy evaluation. | `0.8` |
| **Independent reference** | The second elevation raster from [section 4](#4-what-is-the-independent-reference). | Your survey/mapping provider. | `D:\ref\lidar_survey.tif` |
| **Evidence manifest** | Optional. Path to `compliance_evidence.json`. | **Create template…** or an existing one. | `D:\evidence\compliance_evidence.json` |
| **Reference identifier** | A name/version/date that uniquely names the reference dataset. | The reference's metadata or provider. | `CONTROL-2026-01` |
| **Evaluation method** | The ID of the written procedure used to evaluate accuracy. | Your quality plan. | `QUALITY-PLAN-2215-01` |
| **Source horizontal CE90** | How good the **source's** position accuracy is, in metres, as stated by whoever made it. | The source's metadata/specification. | `0.30` |
| **Source vertical LE90** | How good the **source's** height accuracy is, in metres. | The source's metadata/specification. | `0.80` |
| **Output absolute H CE90** | Measured horizontal CE90 of your **delivered output** against independent control. | Your accuracy evaluation (section 12 can calculate it). | `1.2` |
| **Output random H 90%** | Horizontal scatter after removing the average shift, in metres. | Same. | `0.30` |
| **Output relative H 90%** | Horizontal agreement between pairs of nearby points, in metres. | Same. | `0.80` |
| **Output relative V 90%** | Vertical agreement between pairs of nearby points, in metres. | Same. | `0.40` |
| **Require full implemented DGIWG 250 evidence gate** | The master switch. Tick it only when everything above is filled in. | — | ☑ |

Why are there both "Source" and "Output" accuracy boxes?

* **Source** numbers answer: *"Was the DEM I started with good enough for the
  level I asked for?"*
* **Output** numbers answer: *"Is what I delivered good enough?"*

What DEM2DGED calculates for you versus what you supply:

| You supply | DEM2DGED calculates from the reference raster |
|---|---|
| Source CE90 and LE90, output horizontal CE90, random horizontal, relative horizontal, relative vertical, the identifiers and method | Vertical random error and vertical absolute error of your tiles against the reference |

Horizontal accuracy cannot be worked out from elevation values alone, which is
why you must bring measured horizontal numbers from a proper survey or
evaluation.

---

## 7. Step-by-step: run the full gate in the GUI

Before you start, gather: the source DEM, the independent reference raster,
the source's accuracy statement, and your measured accuracy results.

1. **Open** `dem2dged.exe` (or run `dem2dged_gui.py` from the Anaconda Prompt
   in your `DGED` environment — never in `base`).
2. **Add your source DEM** and choose the **output folder**, **mode** (GEO or
   UTM) and **level**.
3. **Source vertical:** enter the height-reference EPSG of your source (for
   example `3855`).
4. **Prepare the evidence** (pick one):
   * **Quick way:** skip the manifest and type values straight into the boxes
     in section 6.
   * **Organised way:** click **Create template…**, choose a new empty
     folder, open `compliance_evidence.json` in a text editor, fill in the
     fields (section 11), put your PDFs in `documents/`, save, then click
     **Load**.
5. **Check every box** in section 6 has a value. The two **Abs. H / Abs. V
   accuracy** boxes must be numbers, not `auto`.
6. Make sure **Validate after conversion** is ticked (the gate switches it on
   for you).
7. **Tick** *Require full implemented DGIWG 250 evidence gate*.
8. Click **Convert**.
   * If a pop-up appears, read [section 9](#9-the-pop-up-messages-and-what-to-do).
     Nothing has been converted yet; fix what it says and click Convert again.
9. When the run finishes, open
   `<output>\validation\report.html` and `compliance_report.txt`
   ([section 10](#10-reading-the-result)).

> **Strict profile:** when the gate is ticked, DEM2DGED automatically uses the
> *strict* terrain-quality profile, because the lenient default has no
> numeric limits and could pass anything.

---

## 8. The same thing from the command line

Open an **Anaconda Prompt**, activate your dedicated environment (never
`base`), and run (all on one line):

```bat
conda activate DGED
python dem2dged.py source.tif output --mode geo --level 6 ^
  --source-vertical 3855 ^
  --source-horizontal-accuracy 0.30 --source-vertical-accuracy 0.80 ^
  --reference-dem independent_control.tif ^
  --reference-identifier "CONTROL-2026-01" ^
  --accuracy-evaluation-method "QUALITY-PLAN-2215-01" ^
  --reference-horizontal-ce90 1.20 --reference-horizontal-random-90 0.30 ^
  --reference-relative-horizontal-90 0.80 --reference-relative-vertical-90 0.40 ^
  --abs-hacc 1.20 --abs-vacc 0.80 ^
  --terrain-qa full --compliance-profile strict --require-full-compliance
```

(`^` continues a command onto the next line in Windows.) The numbers above are
**illustrations only**. Use your own measured values.

| Option | GUI box it matches |
|---|---|
| `--source-vertical` | Source vertical |
| `--source-horizontal-accuracy` / `--source-vertical-accuracy` | Source horizontal CE90 / Source vertical LE90 |
| `--reference-dem` | Independent reference |
| `--reference-identifier` | Reference identifier |
| `--accuracy-evaluation-method` | Evaluation method |
| `--reference-horizontal-ce90` | Output absolute H CE90 |
| `--reference-horizontal-random-90` | Output random H 90% |
| `--reference-relative-horizontal-90` | Output relative H 90% |
| `--reference-relative-vertical-90` | Output relative V 90% |
| `--abs-hacc` / `--abs-vacc` | Abs. H accuracy / Abs. V accuracy |
| `--require-full-compliance` | The master switch |

**Exit codes:** `0` = full gate passed. `2` = **HOLD** (something missing or
failed; read the report). `--require-full-compliance` cannot be combined with
`--no-validate` or `--terrain-qa none` — the program refuses before
converting, because those options would skip the very checks the gate needs.

Evidence-package helper (separate small tool):

```bat
python dem2dged_evidence.py init  D:\evidence --level 6
python dem2dged_evidence.py calculate D:\evidence\control_points.csv
python dem2dged_evidence.py check D:\evidence\compliance_evidence.json
```

---

## 9. The pop-up messages and what to do

These appear when you click **Convert** with the gate ticked. They appear
**before** anything is converted, so nothing is wasted.

| Message you see | What it means | What to do |
|---|---|---|
| **Full evidence is incomplete** — "Strict DGIWG evidence mode requires: …" followed by a list. | Each bullet is an empty box. | Fill in every listed box ([section 6](#6-every-box-in-the-gui-one-by-one)), or untick the gate if you do not need it. |
| **Measured metadata required** — "Abs. H accuracy / Abs. V accuracy must contain a measured … value". | The box still says `auto`. `auto` means "use the rule-book *goal*", and a goal is not evidence. | Replace `auto` with your real measured number in metres. |
| **Invalid accuracy evidence** — "… must be a number in metres." | You typed text, or a comma instead of a point. | Use digits and a dot, e.g. `0.30`. No unit text. |
| **Invalid accuracy evidence** — "… cannot be negative." | An accuracy value is below zero. | Accuracy values are positive distances. |
| **Reference not found** — "The independent reference file does not exist". | The path is wrong or the file moved. | Use **Browse…** to pick it again. |
| **Validator unavailable** | `dem2dged_validate` could not load in this installation. | Reinstall/rebuild; the gate cannot run without it. |
| **Evidence manifest not found / could not be loaded** | The manifest path is empty, wrong, or the file is not a DEM2DGED manifest. | Pick `compliance_evidence.json` made by **Create template…**; check it is valid JSON (no missing commas or quotes). |
| **Evidence workflow unavailable** | `dem2dged_evidence.py` is missing from this installation. | Use the files from the release package. |

Messages in the **log** after the run:

| Log line | Meaning |
|---|---|
| `Reference independence: PASS` | Your reference is not a copy of the source. |
| `Reference independence: FAIL — … derived from the source` | The reference is the source, a copy of it, or a resampled/shifted version. Choose a truly independent dataset. |
| `Reference independence: NOT_EVALUATED — … only N overlapping posts` | Too little overlap to judge. Use a reference that covers the delivered area. |
| `Compliance HOLD: full evidence gate did not pass` | The run finished but the report is not PASS. Open the report to see which item is missing or failed. |

---

## 10. Reading the result

Open these files in the output folder (you can open `.html` in any browser):

| File | Use |
|---|---|
| `validation\compliance_report.txt` | The easiest summary. Start here. |
| `validation\compliance_report.json` | Same information for programs. |
| `validation\report.html` | Pretty overview with statistics. |
| `DGED_Validation_Report.html` | Structure checks of the tiles. |
| `validation\error_budget.json` | Splits the final error into "was in the source" and "added by the conversion". |
| `validation\independent_reference\…` | Detailed comparison against your reference. |

The report is divided into **sections**. Each is PASS, FAIL or NOT_EVALUATED;
the overall result is FAIL if any is FAIL, NOT_EVALUATED if none fail but one
is missing, and PASS only when all pass.

| Section | Question it answers | Typical reason it is not PASS |
|---|---|---|
| `product_structure` | Are the tiles built correctly (names, grid, format)? | A validator check failed (see `DGED_Validation_Report`). |
| `source_eligibility` | Was the source fine enough, with a stated height reference and accuracy, for this level? | Source coarser than the level; vertical code or accuracy missing; accuracy worse than the level's goal. |
| `conversion_fidelity` | Is the conversion faithful to the source? | Terrain QA off, or errors above the strict limits. (This is **not** accuracy.) |
| `independent_accuracy` | Does the output meet the level's accuracy limits, measured against independent evidence? | Reference missing/not independent; identifier or method missing; a measured number missing or above the limit. |
| `accuracy_metadata` | Are the accuracy numbers in the tile metadata real numbers? | `Abs. H/V accuracy` left at `auto`. |

Each failing line also shows a short reason in the text report.

---

## 11. Every field of the evidence manifest explained

Open `compliance_evidence.json` in Notepad (or any text editor). Keep the
structure; only change the values between the quotation marks. Text goes in
`"quotes"`, numbers do not.

Fields you do **not** edit are marked *(automatic)*.

### Top level

| Field | Meaning | Example |
|---|---|---|
| `schema` *(automatic)* | Identifies the file format. Do not change it. | `DEM2DGED-evidence-package-1.0` |
| `tool_version` *(automatic)* | Version that created the file. | `0.62.0` |
| `created_utc` *(automatic)* | When the template was made. | `2026-10-14T…` |
| `product_level` | The DGED level of this delivery. Must match the level you convert. | `"6"` |
| `strict_validation_report` | Path to the report DEM2DGED writes after a **gated** run: `<output>\validation\compliance_report.json`. Leave empty until the first run, then fill it in. | `"D:\\out\\validation\\compliance_report.json"` |

### `source` — facts about the DEM you are converting

| Field | Meaning | Example |
|---|---|---|
| `raster_path` | Path to the source DEM file. | `"source.tif"` |
| `vertical_epsg` | EPSG number of its height reference. | `"3855"` |
| `vertical_datum_evidence` | The document that proves the height reference. It has three sub-fields: `path` (the file in `documents/`), `document_id` (its reference number/title), `issuer` (who wrote it). | `documents/source_vertical_datum.pdf` |
| `horizontal_ce90_m` | The source's stated position accuracy, in metres. | `0.30` |
| `vertical_le90_m` | The source's stated height accuracy, in metres. | `0.80` |
| `accuracy_evidence` | The document that proves those two numbers (`path`, `document_id`, `issuer`). | `documents/source_accuracy.pdf` |

### `independent_control` — facts about the reference

| Field | Meaning | Example |
|---|---|---|
| `dataset_path` | The independent reference raster. | `"independent_control.tif"` |
| `identifier` | A unique name/version/date for it. | `"CONTROL-2026-01"` |
| `provider` | Who produced it. | `"Independent Survey Authority"` |
| `acquisition_date` | When the data was collected. | `"2026-01-15"` |
| `independence_statement` | One or two sentences saying why it is independent. | `"Acquired by a separate survey; not derived from the source."` |
| `evidence_document` | Provenance paper (`path`, `document_id`, `issuer`). | `documents/control_dataset_provenance.pdf` |

### `evaluation` — how accuracy was measured

| Field | Meaning | Example |
|---|---|---|
| `method_identifier` | ID of the written evaluation procedure. | `"QUALITY-PLAN-2215-01"` |
| `method_document` | The procedure document (`path`, `document_id`, `issuer`). | `documents/accuracy_evaluation_method.pdf` |
| `control_points_csv` | The table of measured points ([section 12](#12-the-control-point-csv-file)). Optional. | `"control_points.csv"` |
| `approved_minimum_control_points` | The smallest number of points your procedure allows. A whole number. | `20` |
| `results_document` | The report of the measured results (`path`, `document_id`, `issuer`). | `documents/accuracy_results.pdf` |
| `declared_results` | The six measured numbers, in metres (see below). Ignored for any value that is calculated from the CSV. | |
| `level_limits_for_reference` *(automatic)* | The limits for your level, shown for convenience. | |

`declared_results` fields:

| Field | Meaning |
|---|---|
| `horizontal_absolute_ce90_m` | Measured horizontal CE90 of the output. Becomes the **Abs. H accuracy** metadata. |
| `horizontal_random_90_m` | Horizontal scatter after removing the average shift. |
| `horizontal_relative_90_m` | Horizontal agreement between point pairs. |
| `vertical_absolute_le90_m` | Measured vertical LE90 of the output. Becomes the **Abs. V accuracy** metadata. |
| `vertical_random_90_m` | Vertical scatter after removing the average height shift. |
| `vertical_relative_90_m` | Vertical agreement between point pairs. |

### `authority_acceptance` — the sign-off (never you)

| Field | Meaning |
|---|---|
| `status` | Starts as `"PENDING_AUTHORITY"`. Only the **designated approving authority** may change it to `"ACCEPTED"` (or `"REJECTED"`). |
| `authority`, `reviewer`, `decision_date` | Who approved, the person, and the date (`YYYY-MM-DD`). |
| `record_document` | The **signed** acceptance record file. Without it, ACCEPTED does not count. |

> **A "document" entry has three parts, and all three are required:**
> the file must exist (not an empty placeholder), it needs a
> `document_id`, and it needs an `issuer`. Missing any of them keeps that
> step on HOLD.

### A filled-in example (illustration only)

```json
"source": {
  "raster_path": "source.tif",
  "vertical_epsg": "3855",
  "vertical_datum_evidence": {
    "path": "documents/source_vertical_datum.pdf",
    "document_id": "VERT-001",
    "issuer": "Source Provider"
  },
  "horizontal_ce90_m": 0.30,
  "vertical_le90_m": 0.80,
  "accuracy_evidence": {
    "path": "documents/source_accuracy.pdf",
    "document_id": "ACC-001",
    "issuer": "Source Provider"
  }
}
```

**JSON tips for beginners:** every `"name": value` pair except the last in a
group ends with a comma; text needs straight double quotes `"…"`; use `/` or
`\\` (double backslash) in Windows paths inside the file; numbers have no
quotes; `null` means "empty". If **Load** reports an error, paste the file
into any online JSON checker or open it in an editor that highlights errors.

---

## 12. The control-point CSV file

`control_points.csv` is an optional table. Each row is one **control point**:
a place where you know the true position and height, next to what the
delivered data says.

| Column | Meaning |
|---|---|
| `point_id` | A name for the point (`A`, `P-017`). Must not be empty. |
| `test_easting_m`, `test_northing_m`, `test_elevation_m` | Position and height **as read from your delivered DGED data**. |
| `reference_easting_m`, `reference_northing_m`, `reference_elevation_m` | The **true** position and height from the survey. |
| `relative_pair_id` | Tag two nearby points with the same ID (e.g. `P1`) to measure relative accuracy. **Each ID must appear exactly twice.** Leave empty if the point is not part of a pair. |

Example (four points, two pairs):

```csv
point_id,test_easting_m,test_northing_m,test_elevation_m,reference_easting_m,reference_northing_m,reference_elevation_m,relative_pair_id
A,100.04,200.03,50.06,100.00,200.00,50.00,P1
B,110.05,200.02,51.08,110.00,200.00,51.00,P1
C,100.03,210.04,52.05,100.00,210.00,52.00,P2
D,110.06,210.03,53.07,110.00,210.00,53.00,P2
```

Calculate the six accuracy numbers:

```bat
python dem2dged_evidence.py calculate control_points.csv
```

For the table above it reports (metres, rounded):

| Result | Value | Where it goes |
|---|---|---|
| `horizontal_absolute_ce90_m` | 0.063 | Output absolute H CE90 and Abs. H accuracy |
| `horizontal_random_90_m` | 0.017 | Output random H 90% |
| `horizontal_relative_90_m` | 0.030 | Output relative H 90% |
| `vertical_absolute_le90_m` | 0.077 | Abs. V accuracy |
| `vertical_random_90_m` | 0.015 | (vertical, calculated by the run) |
| `vertical_relative_90_m` | 0.020 | Output relative V 90% |

How it is computed: for each point, error = delivered − true. "Absolute" = the
90th percentile of the error size. "Random" = the 90th percentile after
removing the average error (bias). "Relative" = the 90th percentile of the
difference between the errors of the two points in each pair.

> **Important.** This calculator uses a plain, transparent 90th-percentile
> formula. Use it **only if your quality plan allows it**. It does not claim to
> reproduce every STANAG 2215 sampling or acceptance rule. If your plan
> specifies another method, use the numbers from your plan's results report
> instead.

How many points do I need? Whatever your approved procedure says. Put that
number in `approved_minimum_control_points`; the checker compares it with the
number of rows in your CSV.

---

## 13. The seven evidence steps

The evidence package lines up with seven steps. Steps 1–6 can be technically
checked by DEM2DGED. Step 7 is a human decision.

| # | Step | You provide | Status words |
|---|---|---|---|
| 1 | **Verified source vertical datum** | EPSG code + a document proving it | PASS / HOLD / FAIL |
| 2 | **Verified source accuracy** | Source CE90 and LE90 + a document proving them; they must be within the level's goals | PASS / HOLD / FAIL |
| 3 | **Independent control dataset** | Reference file + identifier, provider, date, independence statement, provenance document. A reference identical to the source is a **FAIL**. | PASS / HOLD / FAIL |
| 4 | **Measured accuracy results** | The six measured numbers (or the CSV), the results document, and a control-point count that meets your approved minimum. Random/relative values must be within the level limits (section 14). | PASS / HOLD / FAIL |
| 5 | **Documented evaluation method** | Method ID + the method document | PASS / HOLD |
| 6 | **Strict validation pass** | The `compliance_report.json` from a gated DEM2DGED run, with overall `PASS` and the same level | PASS / HOLD / FAIL |
| 7 | **Authority acceptance** | Signed record from the designated authority | **always HOLD until a human accepts** |

Run the checker at any time to see which steps are complete:

```bat
python dem2dged_evidence.py check D:\evidence\compliance_evidence.json
```

It writes readiness reports and prints each step's status. **Technical
readiness PASS only means steps 1–6 passed. It is not an acceptance.**

Order that works well:

1. Create the template. 2. Collect documents for steps 1, 2, 3 and 5.
3. Do the accuracy evaluation (step 4). 4. Run a gated conversion (step 6).
5. Put the report path into `strict_validation_report`. 6. Run `check`.
7. Hand the package to your authority for step 7.

---

## 14. Accuracy limits per level

These are the numbers your measured values are compared with (DGIWG 250 as
implemented in DEM2DGED v0.62.0). All values are in metres.

| Level | Post spacing | H random 90 | H relative 90 | V random 90 | V relative 90 | Abs H CE90 *goal* | Abs V LE90 *goal* |
|---|---|---|---|---|---|---|---|
| 3 | 15 | 4.4 | 12.4 | 2.2 | 6.2 | 15 | 12.4 |
| 4b | 5 | 1.75 | 5 | 0.87 | 2.5 | 6 | 5 |
| 4 | 4 | 1.41 | 4 | 0.71 | 2 | 5 | 4 |
| 5 | 2 | 0.71 | 2 | 0.35 | 1 | 3 | 2 |
| 6 | 1 | 0.35 | 1 | 0.18 | 0.5 | 2 | 1 |
| 7 | 0.5 | 0.18 | 0.5 | 0.09 | 0.25 | 1 | 0.5 |
| 8 | 0.25 | 0.09 | 0.25 | 0.04 | 0.12 | 0.5 | 0.25 |
| 9 | 0.125 | 0.04 | 0.125 | 0.02 | 0.06 | 0.25 | 0.12 |

Levels 0–2 (very coarse) have vertical random limits of 20, 20 and 12 m and
no random/relative horizontal limits.

* **Random and relative** values must be **at or below** the limit. If not,
  that check is a **FAIL**.
* The **absolute** CE90/LE90 values in the last two columns are **goals**. You
  must *report your measured value* (a blank or `auto` is not accepted), but a
  value above the goal does not by itself fail the gate.
* In terrain where the typical slope is **steeper than 20 %**, DGIWG 250 allows
  the **vertical** limits to be multiplied by **1.4**. DEM2DGED applies this
  automatically when mountain terrain QA detects it.
* Finer levels have much tighter limits. For Levels 6–9 the horizontal random
  and relative evidence is especially important and must not be left out.
* If your **source** is coarser than the level you choose, the report shows a
  **FAIL**: you cannot make fine data from coarse data.

---

## 15. Practice run with safe test data

Want to see a PASS and a FAIL happen without real data? The release includes a
test program that builds a small fake DEM and runs the gate on it.

```bat
conda activate DGED
cd /d <folder that contains TEST_GATE_V0.62.0.py>
python TEST_GATE_V0.62.0.py
```

It writes a log in the `logs` folder showing, among other cases: no reference
(NOT_EVALUATED), a copy of the source (FAIL), a resampled copy (FAIL), a
genuinely independent reference with full evidence (PASS). **The numbers it
uses are made up — never reuse them for a real delivery.**

---

## 16. Common mistakes and FAQ

**I ticked the box and got a pop-up. Did something break?**
No. The gate refuses to start until every piece of evidence is present. Read
section 9.

**Can I use the same DEM as both source and reference?**
No. That compares a file with itself and proves nothing. DEM2DGED rejects it.

**My reference is a smoothed or resampled version of my source — is that OK?**
No. It is derived from the source. It is rejected when detected, and it is not
a valid use even when it is not detected.

**What do I type in "Abs. H accuracy" and "Abs. V accuracy"?**
Your measured absolute accuracy (CE90 horizontal, LE90 vertical) for the
delivered data. Not `auto`. These numbers are written into the tile metadata.

**Is "Source CE90/LE90" the same as "Abs. H/V accuracy"?**
No. Source = quality of the DEM you started with (from its supplier). Abs. =
quality of the data you deliver (from your accuracy evaluation).

**Where do the horizontal numbers come from? The tool only has elevations.**
From your survey/evaluation: control points measured on the ground compared
with the delivered data. See section 12.

**The report says NOT_EVALUATED. Is my data bad?**
No. It means a required piece of evidence is missing, so DEM2DGED will not
judge. Open `compliance_report.txt` and read which line says NOT_EVALUATED.

**The report says PASS. Can I say the delivery is NATO-certified?**
No. See section 17.

**Do I have to use the evidence manifest?**
No. It is an organising aid. Type the values into the GUI if you prefer. You
**do** need the documents it points to if a reviewer will examine your
evidence package.

**Does "Load" check or change my evidence?**
Load copies the manifest's values into the GUI and prints a readiness
summary. It never edits the manifest and never turns missing evidence into a
pass.

**Can I convert first and gather evidence later?**
Yes. Convert normally without the gate. You can re-run later with the
reference and numbers (or run `dem2dged_validate.py` on the existing output
folder with `--terrain-qa`, `--reference-dem` and
`--require-full-compliance`).

**Why does `--require-full-compliance` refuse to run with `--no-validate`?**
Because the gate is evaluated by the validation step. Skipping validation
would make the gate meaningless.

**Which Python environment?**
Always a dedicated one (for example `DGED`). Never install packages into
`base`.

---

## 17. What this tool does not claim

* DEM2DGED produces **technical conformance evidence**. It does **not** issue
  NATO, national, contractual or operational certification.
* A report **PASS** means the checks this software implements had evidence and
  passed for *that delivery*. Your accepting authority reviews the evidence
  against its own controlled standards.
* **STANAG 3809 (DTED)** is not the output format of this tool, so it is
  reported as not applicable. A DTED product needs a separate encoder.
* **STANAG 2215** status describes quality-evaluation *evidence* only.
* **Authority acceptance** stays *not evaluated / pending* until the designated
  authority signs.
* Do not label the software or a product "NATO certified" because of a PASS.

*Related files:* `README.md`, `DEM2DGED_User_Manual.md`,
`REQUIREMENTS_COMPLIANCE_V0.62.0.md` (the formal rules this guide explains),
`DEM_SOURCES_GUIDE.md`.
