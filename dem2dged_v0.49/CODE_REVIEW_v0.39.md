# DEM2DGED — Full Review for the v0.39 Release

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

Scope of this pass: the **core `dem2dged/` tool** (shared library, GEO/UTM CLI
converters, unified CLI, GUI, validator, resampling-comparison module,
logging, packaging). Cross-checked against **DGIWG 250 *Defence Gridded
Elevation Data Product Implementation Profile*, Ed. 1.2.1 (2 Oct 2020)** in
`Docs/`, and compared against the upstream project **lethorable/dem2dged**.

Bottom line: the tool is **logically sound and, on every requirement checked,
compliant with DGIWG 250.** No correctness defect was found in the DGED
tables, tile geometry, naming, metadata, or validator. The review produced
three small, low-risk improvements (now in v0.39) plus a self-contained
verification harness.

---

## 1. Spec compliance — verified against DGIWG 250 Ed. 1.2.1

Every item below was checked line-by-line against the PDF and confirmed
correct in the code (`dem2dged_lib.py` tables + the converter/validator logic):

| Requirement (spec ref) | In the tool | Verdict |
|---|---|---|
| 11 GEO / 7 UTM levels, post spacings (Table 1) | `level_tilesize_and_spatial_resolution`, `PL` | ✅ exact |
| Tile-size letters A–G (Table 7) | GEO `C/D/E/F`, UTM `C/D/E/F/G` | ✅ exact |
| Posts-per-tile, smallest tile (Tables 8 & 9) | 5001/6251/10001 UTM; 6001/… GEO | ✅ exact |
| Data type: Int16 mandatory L0–2, Float32 L3+ (§7) | `output_type_for_level()` | ✅ |
| NoData = −32767 (§7) | `-dstnodata -32767`, validator checks it | ✅ |
| Horizontal WGS-84; vertical EGM2008 (§8) | `EPSG:4326` / `+3855`, real geoid transform optional | ✅ |
| Abs. H/V accuracy goals (Tables 5 & 6) | `LEVEL_ABS_HACC/VACC` | ✅ exact |
| Half-post registration, `AREA_OR_POINT=Point` (§6.3) | half-post-expanded warp + `fix_header()` | ✅ |
| Overlapping posts of adjacent tiles identical (§13.2) | `reconcile_tile_edges()` (v0.37) | ✅ |
| LZW lossless compression (§13.1) | `COMPRESS=LZW` | ✅ |
| Filename convention `DGEDLn[T][tS]_[ORG]_…_S_c_vv` (§12.1) | `geo_/utm_tile_basename()` | ✅ |
| UTM zero-padded coordinate fields (§12.1) | `utm_name_field_widths()` (v0.34) | ✅ |
| Table-of-contents + collection metadata (§12.1, §6.6) | `write_toc_file()`, `write_collection_metadata()` | ✅ |
| ISO 19115-2 / DMF 2.0 sidecars, Annex B elements | XML templates + `sidecar_replacements()` | ✅ |
| UTM point origin, both hemispheres (§6.3.1) | tile grid anchored on the 10 000 000 m false-northing lattice | ✅ |

Two design decisions worth calling out as **correct, non-obvious** choices:

- **GEO levels 8–9 use the 1.5-minute (F) tile, not the smaller 1-minute (G)
  tile.** The 1-minute tile yields a *non-integer* number of longitude
  intervals in latitude zones 2 (50–60°) and 4 (70–80°) — 5333.33 / 2666.67 —
  which would break post alignment there. 1.5-minute is a valid Table 8 option
  for both levels and divides evenly in every zone. Right call.
- **Southern-hemisphere UTM** posts land on the same `k·GSD` lattice as the
  spec's `10 000 000 − j·ΔN`, because 10 000 000 m is an exact multiple of
  every UTM level's GSD. Verified.

---

## 2. Findings and fixes applied in v0.39

Five issues. The first three came out of the static review; the last two were
surfaced by the end-to-end verification run on your DEMs (Sections 4). None
change any DGED table, tile geometry, naming, or metadata spec-check.

1. **GeoTIFF LZW predictor was integer-only.** Every tile was written with
   `PREDICTOR=2` (TIFF *horizontal differencing*), which is only defined for
   integer samples. Float32 tiles — **all UTM levels and GEO level 3+** — were
   getting the wrong predictor: less correct and worse compression on real
   terrain. **Fix:** new `dem2dged_lib.predictor_for_type()` → `PREDICTOR=3`
   (IEEE floating-point predictor) for Float32, `PREDICTOR=2` for Int16, wired
   through both CLI converters and the GUI so they can't drift. Still
   LZW-lossless, so still §13.1-compliant; the validator's `COMPRESS=LZW`
   check is unaffected. *This changes tile bytes — regenerate deliveries.*

2. **Source-type letter was never validated.** Spec 12.1 defines the valid
   source codes and reserves `D/E/I/J/Q/R/S/W/Z`; the tool accepted any letter
   silently. **Fix:** `describe_source_type()` drives a **non-blocking
   WARNING** in both CLI converters and the GUI, and a **WARN (not FAIL)** in
   the validator. Default `A` stays silent; metadata still prevails over the
   filename per 12.1, so this is advisory only.

3. **Logging format string was a no-op.** `dem2dged_logging` assigned
   `formatter._fmt` *after* construction, but `logging.Formatter` renders
   through `self._style._fmt`, so the unified `dem2dged.py` CLI printed bare
   messages with no `LEVELNAME:` prefix. **Fix:** the format is now passed to
   the constructor.

4. **UTM negative-northing at the equator (converter).** An equatorial DEM's
   extent dips just below the equator — routine for a point-registered source
   like SRTM, whose edge overhangs by half a post — so a northern UTM zone
   emitted a tile at a *negative* northing, producing a non-spec name like
   `…32N-025…` that the validator (correctly) rejected. **Fix:** the UTM tile
   grid (CLI **and** GUI) is now clamped to the valid `[0, 10 000 000] m`
   northing band, with a warning if it drops a row. Confirmed by the
   equatorial run now yielding `33N0000`.

5. **Section H phantom geoid shift (validator) — the most impactful find.**
   The source-comparison re-warped the source into the tiles' *compound* CRS
   (`EPSG:<horiz>+3855`), which makes GDAL apply an ellipsoidal→EGM2008 geoid
   transform to the source (~25 m over Lebanon) — even though the default
   conversion never shifts the tiles that way. So a *correct* delivery was
   flagged ~25 m wrong, uniformly, for **any source without an explicit
   vertical datum (SRTM and most real DEMs)** in any region with a non-trivial
   geoid height. The DGIWG test set never exposed it (small geoid there).
   **Fix:** both Section H/H2 re-warps now strip the vertical and compare
   terrain in the horizontal CRS only. Confirmed by the gated bilinear
   near-native run dropping from 6 Section-H failures (~25 m) to zero.

The project's own GDAL-free self-audit (`audit_pure.py`) — including its
12-file version-consistency check — passes with **0 problems** after the bump
to 0.39.

### Notes / optional future items (not changed)

- **L9 GEO 1.5-min tiles are ~2.2 GB uncompressed** (Table 10), above the
  spec's <1 GB *design goal* — but that goal yields to post-alignment
  correctness, and LZW shrinks it substantially. Acceptable; documented.
- **Svalbard widened UTM zones (31X/33X/35X/37X)** map to the standard 326xx
  EPSG codes (there is no distinct EPSG for the widened geometry). Flagged
  with a warning; use `--zone` explicitly there.

---

## 3. Objective comparison — this tool vs. lethorable/dem2dged

Both convert a GDAL raster to DGED tiles. The upstream project is an explicit
"very much BETA, use at own risk" pair of scripts; this tool is a much larger,
QA-focused toolkit built on the same idea.

| Dimension | lethorable/dem2dged | This tool (v0.39) |
|---|---|---|
| Structure | 2 scripts + lib | lib + GEO/UTM CLI + unified CLI + GUI + validator + comparison |
| Interface | CLI only | CLI **and** GUI, plus a one-command unified CLI |
| Post registration | pixel-corner (needs bundled `gdal_edit` for `AREA_OR_POINT=Point`) | **half-post-expanded**, `Point` set via GDAL API — samples land exactly on DGED posts |
| Empty border tiles | yes (known issue) | fixed (`ceil()` tile bound) |
| Adjacent-tile shared edge | not guaranteed identical | **`reconcile_tile_edges()`** makes them bit-identical (§13.2) |
| Data type by level | Float32 throughout | **Int16 for L0–2, Float32 L3+** per §7 |
| GeoTIFF predictor | integer predictor for all | **data-type-aware (2/3)** — v0.39 |
| Metadata | basic sidecar template | full ISO 19115-2/DMF 2.0 + TOC + collection + accuracy/lineage/completeness |
| Vertical datum | label only | **real EGM2008 geoid transform** optional |
| Cubic overshoot | can ship impossible elevations | **clamped** to source range |
| Wrong-input guard | none | **pre-flight sanity check** (aspect/derivative rasters) |
| Resampler choice | manual | auto + **`optimize`** (hold-out cross-validation) + side-by-side comparison report |
| Validation | none | **standalone + automatic** validator (A–H, per-tile PASS/WARN/FAIL, HTML) |
| Tests | none shipped | `audit_pure.py`, self-test, and this beta harness |
| Naming (equatorial UTM) | `\d+` (unpadded accepted) | **zero-padded to spec 12.1 widths**, enforced |
| License | GPL-3.0 | GPL-2.0-or-later |

**Assessment.** On **accuracy and spec-conformance** this tool is clearly
ahead: correct half-post registration, level-correct data types, guaranteed
identical shared edges, real vertical-datum handling, cubic clamping, and an
actual validator all address places where the upstream scripts are silent or
approximate. On **ease of use** it is also ahead for a non-expert (GUI,
one-command CLI, automatic validation, wrong-input guard), at the cost of
being a much larger codebase to maintain. The upstream project's advantage is
simplicity — two short scripts are easier to read end-to-end and audit at a
glance. For producing deliveries you intend to *trust as DGED*, this tool is
the more accurate and the easier to use; keep the upstream repo as the
conceptual reference it is.

---

## 4. How this was verified

**Static:** full read of all core modules; DGIWG 250 tables extracted from the
PDF and diffed against the code; `audit_pure.py` (GDAL-free logic +
version-consistency across 12 files) → 0 problems; all modules byte-compile;
the new helpers and the TIFF-predictor reader unit-tested.

**End-to-end** (`verify.bat` → `run_verification.py`, real GDAL 3.13,
your DEMs under `DEM/` + synthetic latitude coverage): **19 / 19 steps PASS.**

| Area | Result |
|---|---|
| audit_pure + resampling self-test | PASS |
| GEO Int16 (L1) / Float32 cubic (L4b) / optimize | struct-clean, predictors 2/3 |
| GEO L2 bilinear near-native, **Section H gated** | source-accuracy FAIL **0** (was 6 @ ~25 m before the geoid fix) |
| UTM equatorial zero-padding + northing clamp | `33N0000`, struct-clean |
| GEO longitude factors @ 55°/65°/75° | pixel ratio **1.5000 / 2.0000 / 3.0000** exact |
| Southern hemisphere GEO / UTM | `…35S…` / `…33S6100…` (EPSG 327xx), struct-clean |
| Real EGM96→EGM2008 vertical transform | ran, struct-clean |
| Aspect sanity-check (block + `--skip` override) | PASS |
| GeoTIFF predictor Int16→2 / Float32→3, LZW | PASS |
| Standalone validator + `-src` on accurate run | exit 0 |

The harness ships with the tool (`run_verification.py`, `verify.bat`)
so the delivery can be re-verified at any time with `conda activate DGED &&
verify.bat`.
