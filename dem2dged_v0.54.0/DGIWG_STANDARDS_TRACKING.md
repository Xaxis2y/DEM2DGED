# DGIWG Standards Tracking — dem2dged

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

**Tracking doc version: 1.1**  
**Last checked: 2026-08-19** (official DGIWG sources checked on this date)
**Purpose:** a living record of whether dem2dged still matches the current DGIWG DGED profile, and what's moving in DGIWG's pipeline that could eventually require changes here. Re-check the sources below periodically — at minimum before any release that touches tiling, warp extents, or output encoding — and bump the version/date above each time this file is refreshed.

---

## 1. Current published standard — we are current

| DGIWG # | Document | Edition | Edition date | Status |
|---|---|---|---|---|
| 250 | Defence Gridded Elevation Data (DGED) Product Implementation Profile | **1.2.1** | 2020-10-02 | **Current** (not deprecated) |
| 116-3-2 | DGIWG GeoTIFF Standard for Elevation Data | **1.1.1** | 2023-11-22 | **Current** |
| 108 | Elevation Surface Model Standardized Profile | **2.3.1** | current published edition | **Current** |
| 250 | (same, prior edition) | 1.2.0 | 2018-05-03 | Deprecated |
| 250 | (same, prior edition) | 1.1.0 | 2017-12-21 | Deprecated |
| 250 | (same, prior edition) | 1.0.0 | 2016-06-02 | Deprecated |

`dem2dged_lib.py` and every sidecar template cite "DGIWG 250 DGED Product Implementation Profile Ed. 1.2.1" throughout (tile naming spec 12.1, edge-sharing spec 6.3, tiling scheme spec 13.2, security classification 13.4, collection metadata 6.6/Annex B). Confirmed directly against DGIWG's own standards page that 1.2.1 remains the current edition — **as of the last-checked date above, dem2dged is not behind the published spec.**

Source: https://dgiwg.org/dgiwg-standards/250

### GeoTIFF elevation profile checks used in v0.54.0

The validator treats point registration (`PixelIsPoint`), horizontal and
vertical CRS identification, vertical units, and a declared void value
(`GDAL_NODATA=-32767` in this implementation) as hard product checks. Level
0-2 output is signed Int16; level 3 and finer output is Float32. These checks
cover the automated parts of DGIWG 116-3-2 that can be established from the
delivery itself. Full accuracy still needs independent evidence.

Sources: https://portal.dgiwg.org/files/71215 and
https://portal.dgiwg.org/files/71219

## 2. Scope choice, not a gap: GeoTIFF only

DGED permits three encodings — GeoTIFF, GMLJP2, and NSIF. dem2dged implements GeoTIFF only. This is a deliberate, spec-compliant scope decision (documented in README.md), not missing coverage. Worth remembering if a future requirement ever calls for GMLJP2 or NSIF delivery — that would be new scope, not a bug fix.

## 3. Watch list — active DGIWG work that could affect this tool

Pulled from DGIWG's 2026–2027 Programme of Work. Their standard lifecycle has 12 stages across four phases: **Planning** (1 New Requirement → 2 Requirement Acceptance → 3 Assign Panel), **Development** (4 Working Draft → 5 Technical Review/VD1 → 6 Client Validation → 7 Finalise FD), **Publication** (8 Ballot → 9 Publication Draft → 10 Publish), **Maintenance** (11 Review → 12 Retain/Revise/Retire). Nothing below has reached Publication, so none of it is implementable yet — but this is the honest "future profile" picture, ranked by relevance to dem2dged.

### HIGH relevance — DGED Revision (new tiling scheme)
- **Panel:** P2 Image and Gridded Data
- **Description (verbatim):** "To revise Defence Geospatial Elevation Data (DGED) Standard to include new Tiling Scheme"
- **Stage:** 04 Develop Working Draft
- **Why it matters here:** the tiling scheme — shared-post, half-pixel-expanded warp extents (spec 6.3/13.2) — is the architectural core of this tool (`tile_warp_extent()`, `reconcile_tile_edges()`, `geo_tile_basename()`/`utm_tile_basename()`). If/when this revision publishes, it could mean real rework, not a patch.
- **Action now:** none possible — DGIWG working drafts sit behind the member portal (portal.dgiwg.org). Just watch for this to move past stage 7 (Finalise FD) toward Ballot/Publication.

### MEDIUM relevance — GeoTIFF Profile Revision
- **Panel:** P2 Image and Gridded Data
- **Description (verbatim):** "To revise the DGIWG GeoTIFF Profile to support Cloud Optimized GeoTIFF (COG) and BigTIFF and additional compression algorithms encodings (LERC/ZSTD/LZW) and guidance."
- **Stage:** 04 Develop Working Draft
- **Why it matters here:** dem2dged's only output encoding is GeoTIFF (LZW/PREDICTOR=2/TILED=YES today). A published revision could add or recommend COG structure / new compression options.

### LOW relevance (too early) — ESM Standardized Profile review
- **Panel:** P2 Image and Gridded Data
- **Description (verbatim):** "To review Elevation Surface Model (ESM) Standardized Profile."
- **Stage:** 01 New Requirement Identified (earliest possible stage)
- **Why it matters here:** DGED is itself an implementation profile *of* ESM, so a future ESM change could cascade into DGED eventually. At stage 1 of 12 this is not yet a real signal.

Source: https://dgiwg.org/activities/2025-2026-programme-of-work/

## 4. Provenance check

dem2dged's code traces back to the small open-source `lethorable/dem2dged` (GPL, ~37 commits, no tagged releases, last known state has no separate DGIWG-revision tracking of its own). This project is already substantially more complete than that upstream, so there is no more-current public reference implementation to reconcile against — DGIWG's own site is the only authority that matters here.

Source: https://github.com/lethorable/dem2dged

## 5. How to re-check this file

1. Refetch https://dgiwg.org/dgiwg-standards/250 — if the "Downloads" row's Edition is no longer 1.2.1, or 1.2.1 moves to the "Deprecated" table, that's the trigger to re-audit this whole codebase against the new edition.
2. Refetch the current DGIWG Programme of Work page (URL/year in the path changes annually, e.g. `2025-2026-programme-of-work`, `2026-2027-programme-of-work`) — check whether "DGED Revision" (Section 3 above) has moved stages, especially past 07 Finalise FD.
3. Update the table/sections above, bump **Tracking doc version**, update **Last checked**, and add a dated line to the changelog below.

## Changelog

- **1.1 (2026-08-19):** Rechecked the official standards list; added DGIWG
  116-3-2 and the v0.54.0 evidence distinction between structural GeoTIFF
  compliance, conversion fidelity and independent product accuracy.
- **1.0 (2026-07-20):** Initial version. Confirmed DGIWG 250 Ed. 1.2.1 (2020-10-02) is current. Identified the "DGED Revision" (new tiling scheme), "GeoTIFF Profile Revision," and "ESM" review as the relevant items in DGIWG's active pipeline, all pre-publication.
