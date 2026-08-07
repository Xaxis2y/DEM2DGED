# Code review — dem2dged v0.41 → v0.42

**Date:** 2026-08-07
**Scope:** release-readiness audit of the `dem2dged_v0.41` folder as it
actually sits on disk, prompted by the question "is this release ready?"
**Verdict on v0.41 as found: not releasable**, independent of what
`CODE_REVIEW_v0.41.md` claimed about it. One structural blocker, plus three
smaller packaging/docs gaps. No functional/algorithmic change in v0.42 --
the converters, validator logic, DGED tables, tile geometry, filenames and
metadata are untouched, and a v0.39/v0.40/v0.41 delivery does not need
regenerating.

**Update, same day:** once the sibling `dem2dged_v0.40` folder (the actual
source of every `_release_check_logs/` entry) was made available, `tests/`
was copied in directly and verified byte-identical (bar its own `# Version:`
header) against that known-good, already-run copy -- not reconstructed from
a description. A freshly built `dem2dged_v0.42.zip` now contains all five
files. Finding 1 is fully closed, not just root-caused.

**Final update, same day:** `RELEASE_CHECK_v0.41.py` re-run for real, inside
this folder, in the actual DGED conda environment (GDAL 3.13.2) --
**ALL STEPS PASSED**: 23 modules byte-compile, `audit_pure.py` 0 problems,
**pytest 213 passed / 0 failed**, GEO and UTM conversion + validation both
PASS, tile inspection conforms. (An intermediate attempt failed step 00
because it ran under a standalone Python 3.14 install instead of the DGED
environment -- a PATH-ordering issue on the operator's machine, not a
project defect; resolved by invoking the environment's `python.exe`
directly.) **Verdict: v0.42 is releasable.**

---

## Summary

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | **BLOCKER** | `tests/` does not exist in the release folder, contradicting `MANIFEST.md`; root cause was `dem2dged_package.py` excluding it from the source zip | Fixed -- directory restored from the verified `dem2dged_v0.40` source and confirmed to ship in a freshly built zip |
| 2 | High | The validator-only bundle never included `LICENSE`, despite `MANIFEST.md` saying it does | Fixed |
| 3 | Low | `lu49gpd00.tmp` (a stray PDF wearing a `.tmp` extension) would ship in every release zip | Fixed |
| 4 | Low | `dem2dged_anaconda_environment.py` called `pip install -y ...`; pip has no `-y` flag | Fixed |
| 5 | Low | `README.md`'s first table was missing its header-separator row | Fixed |
| 6 | Low | Two packaging scripts' *embedded* `VERSION.txt`/`VALIDATOR_VERSION.txt` templates had already drifted from the real files on disk (missing a `Changes in v0.41` entry) | Fixed |
| 7 | Low | `RELEASE_CHECK_v0.41.py`'s own instructions told the operator to `cd` into `dem2dged_v0.40` -- the likely direct cause of finding 1's evidence describing the wrong folder | Fixed |

---

## 1. BLOCKER — `tests/` does not exist in the release folder

```
$ ls tests/
ls: cannot access 'tests/': No such file or directory
```

`pytest.ini` sets `testpaths = tests`. `MANIFEST.md` lists
`tests/conftest.py`, `tests/test_lib.py`, `tests/test_converters.py`,
`tests/test_validator.py` and `tests/README.md` as five of the "52 files in
the source release" and states plainly that "everything here is required to
run, build, test or understand the tool." `MANIFEST.md`'s own "Quick
verification after unzipping" section instructs `pytest -q` as the second
command a user runs. None of that is true of what is actually in this
folder: `pytest -q` fails immediately with `file or directory not found:
tests`.

### Why this was not obvious

`CODE_REVIEW_v0.41.md` (finding 3) describes `tests/` as having been
"rebuilt as five files" and reports **185 passed** from a real run. That
run genuinely happened -- but every log in `_release_check_logs/`
(`00_environment.txt` through `SUMMARY.txt`) records its own `Project
folder:` as `C:\Users\Son\Documents\DEM2DGED\dem2dged_v0.40`, a **different,
sibling folder**, not this one. `tests/` existed and passed there. Nothing
ever copied it into `dem2dged_v0.41/`.

### Root cause

`dem2dged_package.py` -- the script `MANIFEST.md` describes as "zips the
**source** release" -- excluded `"tests"` from that zip:

```python
EXCLUDE_DIRS = {"build", "dist", "__pycache__", ".pytest_cache", "_v027_sync",
                 "DGED Loader", "ArcGIS_PRO_QA_toolbox", "DEM", "tests",
                 "tests", "_verify_pages"}
```

(`"tests"` appears twice -- a copy-paste duplicate, harmless in a `set` but
a sign the list was edited carelessly.) So even a perfectly-formed working
copy with a complete `tests/` directory would produce a release zip
missing it, silently contradicting `MANIFEST.md`'s own definition of what
"the source release" contains. This is the second time this exact class of
problem has been recorded: `MANIFEST.md`'s own v0.41 note says *"`tests/`
was listed while the directory itself did not exist"* was already found and
"fixed" once before. It recurred because that earlier fix addressed the
document, not the packaging script that determines what actually ships.

**Fixed:** `"tests"` removed from `EXCLUDE_DIRS` (both entries). Verified by
running the fixed script end to end (see "Verified in this session" below)
-- `dem2dged_essential_package.py`'s own `SKIP_DIR_NAMES` still excludes
`tests` deliberately, which is correct: that script builds a separate,
leaner delivery bundle (core tool + two ArcGIS toolboxes) that `MANIFEST.md`
never claims includes tests, so it was left alone.

### Resolved -- the directory itself has been restored

Removing the exclusion fixes every *future* run of `dem2dged_package.py`,
but could not by itself conjure the five files back. Once the sibling
`dem2dged_v0.40` folder (the actual source of every `_release_check_logs/`
entry) was connected, its `tests/` directory was copied into this folder
directly -- not reconstructed from `MANIFEST.md`'s description of it, which
would have been materially weaker evidence than a copy of a directory that
has already been run for real (185 passed, 22 GDAL integration tests).

Every copied file was diffed against its `dem2dged_v0.40` source
afterwards: `conftest.py`, `test_converters.py`, `test_lib.py` and
`test_validator.py` each differ by exactly one line (their own
`# Version: 0.41` header comment, bumped to `0.42` to match the rest of the
project); `README.md` is byte-identical. `dem2dged_package.py`, run fresh
against this folder, now packs all five files into `dem2dged_v0.42.zip`.

While comparing the two folders it also became clear *why* every
`_release_check_logs/` entry described `dem2dged_v0.40` instead of this
folder: `RELEASE_CHECK_v0.41.py`'s own "HOW TO RUN IT" instructions told the
operator to `cd` into `...\dem2dged_v0.40` -- a stale example path (see
finding 7). The script itself was never at fault (`HERE =
dirname(__file__)` always operates on wherever it is actually run from);
only the instructions pointed at the wrong folder. Fixed, with a note left
in place so the same mistake is not repeated.

---

## 2. High — the validator-only bundle never included LICENSE

`dem2dged_validate_v0.41/`, the staging folder `dem2dged_validate_package.py`
produces, has six files. `MANIFEST.md` describes it as seven: "validator +
`dem2dged_lib.py` + manual + `LICENSE` + README + rebuild script +
`VALIDATOR_VERSION.txt`." The script's own file list never included it:

```python
files_to_include = [
    "dem2dged_validate.py", "dem2dged_lib.py", "rebuild_validate_exe.bat",
    "VALIDATOR_VERSION.txt", "README.md", "DEM2DGED_User_Manual.docx",
]
```

For a project licensed GPL-2.0-or-later, shipping a bundle without the
license text is a real compliance gap, not a cosmetic one. **Fixed:**
`"LICENSE"` added to the list. Verified by running the script: the
resulting `dem2dged_validate_v0.42.zip` contains it.

---

## 3. Low — a stray `.tmp` file would ship

`lu49gpd00.tmp` (311 KB, actually a 14-page PDF per `file`) sits in the
project root. `dem2dged_package.py`'s `EXCLUDE_FILE_SUFFIXES` was
`(".zip", ".pdf", ".jpg", ".jpeg")` -- no `.tmp`. `CODE_REVIEW_v0.41.md`
found this and explicitly left it open ("documented, not changed").
**Fixed:** `.tmp`, `.log` and `.bak` added. Verified: the file is absent
from a freshly built `dem2dged_v0.42.zip`.

---

## 4. Low — broken `pip install -y` in the alternate environment script

`dem2dged_anaconda_environment.py` (Step 3) ran:

```python
f'conda run -n {ENVIRONMENT_NAME} pip install --break-system-packages numpy matplotlib pillow scipy -y'
```

`-y` is a conda flag, not a pip one. Tested directly in a clean environment:

```
$ python3 -m pip install -y --break-system-packages nonexistentpackage123
Usage:
  pip install [options] <requirement specifier> ...
```

pip rejects it outright and installs nothing; `run_command()` only prints a
`WARNING` and the script still reports "Environment Setup Complete!"
immediately after. Practical impact is low -- `matplotlib`, `pillow` and
`scipy` are not imported anywhere in the dem2dged source (confirmed by
project-wide search), and `numpy` already arrives transitively as a
dependency of conda-forge's `gdal` package in Step 2 -- but it is a dead,
misleading line. **Fixed:** flag removed.

---

## 5. Low — `README.md`'s first table did not render

The "What's in this folder" table (the first thing after the intro) was
missing its header-separator row:

```
| File | Purpose |
| `dem2dged_gui.py` | ... |
```

No `|---|---|` line means this is not valid GFM and renders as plain text
with literal pipes on GitHub or any standard Markdown viewer. **Fixed.**

---

## 6. Medium — the packaging scripts' own changelog templates had drifted

While adding a `Changes in v0.42` entry to `dem2dged_package.py`'s embedded
`VERSION.txt` template, the insertion point (immediately before `Changes in
v0.40:`) revealed the template had **no `Changes in v0.41` entry at all** --
it jumped straight from the file header to v0.40, even though the real
`VERSION.txt` on disk also lacked one (both were incomplete, consistently).
`dem2dged_validate_package.py`'s embedded `VALIDATOR_VERSION.txt` template
had the same gap, but asymmetrically: the real `VALIDATOR_VERSION.txt` on
disk *did* have a detailed hand-written v0.41 entry, while the script's own
template did not -- so the next time that script ran, it would have
silently regenerated `VALIDATOR_VERSION.txt` and dropped that entire entry.
**Fixed:** both scripts' templates now carry the v0.41 entry (copied from
the authoritative source: `CODE_REVIEW_v0.41.md` for `dem2dged_package.py`,
the real `VALIDATOR_VERSION.txt` for `dem2dged_validate_package.py`) plus
a new v0.42 entry, and the real `VERSION.txt` / `VALIDATOR_VERSION.txt`
files were regenerated from the now-corrected templates so all three
sources agree.

---

## What is verified, and what is not

**Verified against real GDAL** -- `RELEASE_CHECK_v0.41.py`, run by the
operator on GDAL 3.13.2 / PROJ 9.8.1, **inside this folder** (confirmed by
`00_environment.txt`'s `Project folder:` line, the first time that line has
ever pointed here instead of `dem2dged_v0.40`):

| Step | Result |
|---|---|
| 00 environment | GDAL importable |
| 00b GDAL flag behaviour | shared flag=True, `gdal_open()` contract holds=True |
| 01 byte-compile | 19 modules (will read 23 once `tests/`'s 4 `.py` files are counted -- see below) |
| 02 `audit_pure.py` | `RESULT: 0 problem(s)` |
| 03 pytest | FAIL, rc=5, "no tests collected" -- **run *before* `tests/` was restored**, see below |
| 04 CLI surface | 6 entry points |
| 05/06 GEO convert + validate | 2 tiles, PASS |
| 07/08 UTM convert + validate | 2 tiles, PASS |
| 09 tile inspection | all tiles conform |
| 10 `run_verification.py` | skipped -- no rasters under `DEM\` |

**Verified in this session** (no GDAL available -- pure Python only, run
against the actual edited files, not a description of them):

| Check | Result |
|---|---|
| Byte-compilation, every top-level module and all 4 `tests/*.py` | pass |
| `audit_pure.py` | `RESULT: 0 problem(s)` (18 version declarations, all `0.42`) |
| `dem2dged_validate_package.py`, executed end to end | `dem2dged_validate_v0.42.zip` built, contains `LICENSE` |
| `dem2dged_package.py`, executed end to end | `dem2dged_v0.42.zip` built, contains all 5 `tests/` files, `lu49gpd00.tmp` absent |
| `tests/` restoration | every file diffed against its verified `dem2dged_v0.40` source: 4 differ by exactly their own version-header line, `tests/README.md` is byte-identical |
| `pytest --collect-only` (no GDAL in this sandbox) | discovers `tests/`, cleanly SKIPs `test_converters.py` / `test_lib.py` / `test_validator.py` at their `importorskip("osgeo")` guards -- proves the files are syntactically valid and the skip guards work, though it cannot exercise the GDAL-backed assertions themselves |
| `pip install -y` failure | reproduced directly against a live pip |
| `matplotlib`/`pillow`/`scipy` unused | confirmed by project-wide import search |
| README table | separator row present, file re-inspected after edit |

**Not verified, and not claimed:** the actual pytest PASS count against
real GDAL, now that `tests/` exists -- the one real-GDAL run above predates
the restoration and only proves the *absence* was real, not that the
restored suite passes. Also still open: the PyInstaller `.exe` builds, and
the EGM96->EGM2008 vertical transform (`run_verification.py` step 10, needs
real DEMs under `DEM\`). **Recommended next step:** re-run
`RELEASE_CHECK_v0.41.py` from Anaconda Prompt inside this folder one more
time -- step 01 should report 23 modules again and step 03 should run the
real suite (185 unit + 22 integration tests, per `CODE_REVIEW_v0.41.md`)
instead of failing on a missing directory.
