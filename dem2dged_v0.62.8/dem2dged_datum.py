#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# Version: 0.62.8
"""Suggest the vertical datum of a source DEM from EVIDENCE (never silently).

WHY THIS EXISTS
---------------
DEM2DGED holds a conversion when the source has no vertical reference
("Conversion held ... verified vertical reference"). Many DEM GeoTIFFs carry
only a horizontal CRS, so the operator had to find the datum by hand and type
its EPSG code into Advanced > Source vertical.

This module looks for the datum in the places a person would look, and reports
WHERE each hint came from and HOW RELIABLE it is:

    embedded_crs       a vertical CRS inside the file (EPSG code or name)    high
    gdal_metadata      a datum named in the GeoTIFF/GDAL metadata tags       high / medium
    sidecar_file       a datum named in a text/XML/JSON file next to the TIF medium / low
    filename_convention  the file name follows a known provider's tile
                       naming (NRCan HRDEM, USGS 3DEP)                       medium

WHAT IT DOES NOT DO
-------------------
* It never changes the source raster and never uses the network.
* It never decides for the operator. The GUI pre-fills the box only when the
  evidence of high/medium reliability agrees on ONE datum, and only after the
  operator presses "Use". Conflicting or weak evidence is shown, not applied.
* It cannot infer a datum from the height values themselves.
* PDF documents next to the data are not searched; read them yourself.

COMMAND LINE
------------
    python dem2dged_datum.py my_dem.tif [more.tif ...] [--json]
"""

import argparse
import json
import os
import re
import sys

VERSION = "0.62.8"

MAX_TEXT_BYTES = 2_000_000          # larger side files are skipped
MAX_FILES_PER_FOLDER = 30           # side files scanned per folder
TEXT_SUFFIXES = {".xml", ".txt", ".json", ".md", ".html", ".htm", ".prj",
                 ".met", ".csv", ".yml", ".yaml", ".ini", ".hdr", ".rtf"}
TEXT_NAME_PREFIXES = ("readme", "metadata")

# Datums this tool can name. EPSG codes are the vertical CRS codes the tool
# accepts in Advanced > Source vertical.
DATUMS = [
    {"key": "CGVD2013", "epsg": "6647",
     "name": "CGVD2013 height (Canadian Geodetic Vertical Datum of 2013)",
     "regex": r"CGVD[\s_-]*2013|CGG[\s_-]*2013|CGVD13"},
    {"key": "CGVD28", "epsg": "5713",
     "name": "CGVD28 height (Canadian Geodetic Vertical Datum of 1928)",
     "regex": r"CGVD[\s_-]*(?:19)?28(?!\d)"},
    {"key": "EGM2008", "epsg": "3855",
     "name": "EGM2008 height",
     "regex": r"EGM[\s_-]*2008|EGM08"},
    {"key": "EGM96", "epsg": "5773",
     "name": "EGM96 height",
     "regex": r"EGM[\s_-]*96|EGM[\s_-]*1996"},
    {"key": "NAVD88", "epsg": "5703",
     "name": "NAVD88 height (North American Vertical Datum of 1988)",
     "regex": r"NAVD[\s_-]*(?:19)?88(?!\d)"},
    {"key": "NGVD29", "epsg": "5702",
     "name": "NGVD29 height (National Geodetic Vertical Datum of 1929)",
     "regex": r"NGVD[\s_-]*(?:19)?29(?!\d)"},
]
_BY_KEY = {d["key"]: d for d in DATUMS}
_KEY_BY_EPSG = {d["epsg"]: d["key"] for d in DATUMS}
_COMPILED = [(d["key"], re.compile(d["regex"], re.I)) for d in DATUMS]
_CODE_RE = re.compile(
    r"EPSG[\"'\s:,\[\]]{0,8}(%s)(?!\d)" % "|".join(sorted(_KEY_BY_EPSG)), re.I)
_CONTEXT_RE = re.compile(r"vertical|datum|height|elevation|geoid|orthometric", re.I)

# File-name conventions of providers whose products have a published datum.
_HRDEM_NAME = re.compile(
    r"^[a-z]+(?:_[a-z]+)*_\d+(?:\.\d+)?m_utm\d{1,2}_[ew]_\d+_\d+", re.I)
_3DEP_NAME = re.compile(r"^USGS_(?:1M|13|1|2)_", re.I)

_RANK = {"high": 3, "medium": 2, "low": 1}


# ---------------------------------------------------------------------------
# text scanning
# ---------------------------------------------------------------------------

def _snippet(line, pos):
    start = max(0, pos - 70)
    text = line[start:pos + 110].strip()
    return ("..." if start else "") + text


def scan_text(text):
    """Return {datum_key: [snippet, ...]} for datum names/codes found in text."""
    found = {}
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        hits = {}
        for key, rx in _COMPILED:
            match = rx.search(stripped)
            if match:
                hits[key] = match.start()
        for match in _CODE_RE.finditer(stripped):
            hits.setdefault(_KEY_BY_EPSG[match.group(1)], match.start())
        for key, pos in hits.items():
            lines = found.setdefault(key, [])
            if len(lines) < 3:
                lines.append(_snippet(stripped, pos))
    return found


def _read_text(path):
    try:
        with open(path, "rb") as stream:
            data = stream.read(MAX_TEXT_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_TEXT_BYTES:
        return None
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def _evidence(kind, key, where, snippet, confidence, note=None):
    datum = _BY_KEY.get(key)
    if datum:
        epsg, name = datum["epsg"], datum["name"]
    else:                                   # an EPSG code this tool has no name for
        epsg = key.split(":", 1)[1] if key.startswith("EPSG:") else key
        name = "EPSG:%s" % epsg
    return {"kind": kind, "datum_key": key, "epsg": epsg, "name": name,
            "confidence": confidence, "where": where, "snippet": snippet,
            "note": note}


# ---------------------------------------------------------------------------
# evidence sources
# ---------------------------------------------------------------------------

def _embedded_evidence(path, evidence, notes):
    try:
        from osgeo import gdal, osr
    except Exception as exc:
        notes.append("GDAL is not available, so the embedded CRS and metadata tags "
                     "were not read (%s)." % exc)
        return
    gdal.UseExceptions()
    osr.UseExceptions()
    try:
        ds = gdal.Open(path)
    except Exception as exc:
        notes.append("could not open the raster: %s" % exc)
        return
    try:
        wkt = ds.GetProjection()
        if wkt:
            srs = osr.SpatialReference(wkt=wkt)
            for node in ("VERT_CS", "VERTCRS"):
                code = name = auth = None
                try:
                    code = srs.GetAuthorityCode(node)
                    auth = srs.GetAuthorityName(node) or "EPSG"
                except Exception:
                    code = None
                try:
                    name = srs.GetAttrValue(node)
                except Exception:
                    name = None
                if code:
                    key = _KEY_BY_EPSG.get(str(code), "EPSG:%s" % code)
                    evidence.append(_evidence(
                        "embedded_crs", key, "vertical CRS inside the file",
                        ("%s:%s %s" % (auth, code, name or "")).strip(), "high"))
                    break
                if name:
                    hits = scan_text(name)
                    for key in hits:
                        evidence.append(_evidence(
                            "embedded_crs", key,
                            "vertical CRS name inside the file (no EPSG code)",
                            name, "high"))
                    if not hits:
                        notes.append('the file has a vertical CRS named "%s" with no EPSG '
                                     "code this tool recognises." % name)
                    break
        domains = [""]
        try:
            skip = {"", "IMAGE_STRUCTURE", "SUBDATASETS", "DERIVED_SUBDATASETS",
                    "RPC", "IMAGERY"}
            domains += [d for d in (ds.GetMetadataDomainList() or []) if d not in skip]
        except Exception:
            pass
        items = []
        for domain in domains:
            try:
                metadata = ds.GetMetadata(domain)
            except Exception:
                continue
            prefix = ("%s:" % domain) if domain else ""
            if isinstance(metadata, dict):
                items += [(prefix + str(k), str(v)) for k, v in metadata.items()]
            elif isinstance(metadata, (list, tuple)):
                items += [(domain or "metadata", str(v)) for v in metadata]
        try:
            band = ds.GetRasterBand(1)
            items += [("band:" + str(k), str(v)) for k, v in (band.GetMetadata() or {}).items()]
            if band.GetDescription():
                items.append(("band description", str(band.GetDescription())))
        except Exception:
            pass
        for key_name, value in items:
            for key, lines in scan_text(value).items():
                strong = re.search(r"vert|datum|geoid|height", key_name, re.I)
                evidence.append(_evidence(
                    "gdal_metadata", key, "metadata tag %s" % key_name,
                    lines[0], "high" if strong else "medium"))
    finally:
        ds = None


def _catalog_datum(provider_fragment, fallback_key):
    """Datum key the reference catalog declares for a provider (offline)."""
    here = os.path.dirname(os.path.abspath(__file__))
    folders = [here]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        folders.append(meipass)
    for folder in folders:
        try:
            with open(os.path.join(folder, "reference_catalog.json"), "r",
                      encoding="utf-8") as stream:
                catalog = json.load(stream)
        except (OSError, ValueError):
            continue
        for source in catalog.get("sources", []):
            if provider_fragment.lower() in str(source.get("provider", "")).lower():
                keys = list(scan_text(str(source.get("vertical_datum", ""))))
                if len(keys) == 1:
                    return keys[0], "reference_catalog.json"
    return fallback_key, "built-in default"


def _filename_evidence(path, evidence, notes):
    base = os.path.basename(path)
    if _HRDEM_NAME.match(base):
        key, origin = _catalog_datum("Natural Resources Canada", "CGVD2013")
        evidence.append(_evidence(
            "filename_convention", key,
            "file name follows the NRCan HRDEM tile naming",
            base, "medium",
            "HRDEM products are published in this datum (%s). The file name is "
            "only a hint that the file came from HRDEM; confirm it against the "
            "product metadata." % origin))
    elif _3DEP_NAME.match(base):
        key, origin = _catalog_datum("USGS 3D Elevation", "NAVD88")
        evidence.append(_evidence(
            "filename_convention", key,
            "file name follows the USGS 3DEP tile naming",
            base, "medium",
            "3DEP products are published in this datum (%s); the geoid model "
            "varies by project. Confirm it against the product metadata." % origin))


def _sidecar_evidence(path, evidence, notes):
    here = os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    own = os.path.abspath(path)
    for level, folder in (("same-folder", here), ("parent-folder", os.path.dirname(here))):
        if level == "parent-folder" and folder == here:
            continue
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        pdfs = [n for n in names if n.lower().endswith(".pdf")]
        if pdfs and level == "same-folder":
            notes.append("%d PDF file(s) next to the data were not searched; read the "
                         "provider's PDF documentation yourself." % len(pdfs))
        candidates = []
        for name in names:
            full = os.path.join(folder, name)
            low = name.lower()
            if os.path.abspath(full) == own or not os.path.isfile(full):
                continue
            if (os.path.splitext(low)[1] not in TEXT_SUFFIXES
                    and not low.startswith(TEXT_NAME_PREFIXES)):
                continue
            same_stem = level == "same-folder" and low.startswith(stem)
            candidates.append((0 if same_stem else 1, name, full, same_stem))
        candidates.sort()
        for _order, name, full, same_stem in candidates[:MAX_FILES_PER_FOLDER]:
            text = _read_text(full)
            if text is None:
                continue
            hits = scan_text(text)
            if not hits:
                continue
            several = len(hits) > 1
            for key, lines in hits.items():
                note = None
                if several:
                    confidence = "low"
                    note = "this file names several datums, so none is taken as the answer"
                elif level == "parent-folder":
                    confidence = "low"
                    note = "found one folder up; it may describe other products"
                elif same_stem:
                    confidence = "medium"
                else:
                    confidence = "medium" if _CONTEXT_RE.search(lines[0]) else "low"
                evidence.append(_evidence(
                    "sidecar_file", key, "%s file %s" % (level, name),
                    lines[0], confidence, note))


# ---------------------------------------------------------------------------
# decision
# ---------------------------------------------------------------------------

def _decide(path, evidence, notes):
    result = {"source": path, "status": "none", "suggestion": None,
              "evidence": evidence, "notes": notes, "detector_version": VERSION}
    usable = [e for e in evidence if e["confidence"] in ("high", "medium")]
    keys = sorted({e["datum_key"] for e in usable})
    if len(keys) > 1:
        result["status"] = "conflict"
        notes.append("The evidence disagrees (%s). Nothing was pre-filled; decide from "
                     "the provider's documentation." % ", ".join(keys))
    elif len(keys) == 1:
        best = max(usable, key=lambda e: _RANK[e["confidence"]])
        result["status"] = "found"
        result["suggestion"] = {
            "epsg": best["epsg"], "datum_key": best["datum_key"], "name": best["name"],
            "confidence": best["confidence"],
            "basis": "; ".join(sorted({e["where"] for e in usable})),
        }
    elif evidence:
        result["status"] = "weak"
        notes.append("Only weak hints were found (listed below). Nothing was pre-filled.")
    else:
        notes.append("No vertical datum was found in the file, its metadata or the files "
                     "next to it. Check the provider's documentation.")
    return result


def detect_vertical_datum(path):
    """Collect evidence for the vertical datum of one raster. Never raises."""
    path = os.path.abspath(path)
    evidence, notes = [], []
    for step in (_embedded_evidence, _filename_evidence, _sidecar_evidence):
        try:
            step(path, evidence, notes)
        except Exception as exc:        # a detector problem must never stop the GUI
            notes.append("%s failed: %s" % (step.__name__.strip("_"), exc))
    return _decide(path, evidence, notes)


def combine(results):
    """Merge per-file results into one verdict for the Source vertical box."""
    results = list(results)
    out = {"status": "none", "suggestion": None, "message": ""}
    if not results:
        return out
    epsgs = {r["suggestion"]["epsg"] for r in results if r.get("suggestion")}
    statuses = {r["status"] for r in results}
    if all(r["status"] == "found" for r in results) and len(epsgs) == 1:
        weakest = min((r["suggestion"] for r in results),
                      key=lambda s: _RANK[s["confidence"]])
        out.update(status="found", suggestion=dict(weakest),
                   message="All %d file(s) point to the same datum." % len(results))
    elif "conflict" in statuses or len(epsgs) > 1:
        out.update(status="conflict",
                   message="The files or their evidence disagree. Nothing was pre-filled.")
    elif epsgs:
        out.update(status="partial",
                   message="Only some of the files have usable evidence. Nothing was "
                           "pre-filled, because one value applies to every file in this run.")
    elif "weak" in statuses:
        out.update(status="weak", message="Only weak hints were found. Nothing was pre-filled.")
    else:
        out.update(status="none", message="No datum evidence was found.")
    return out


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def format_report(results, combined=None):
    results = list(results)
    combined = combined or combine(results)
    lines = []
    suggestion = combined.get("suggestion")
    if suggestion:
        lines.append("SUGGESTION: EPSG:%s  %s" % (suggestion["epsg"], suggestion["name"]))
        lines.append("Reliability: %s.  %s" % (suggestion["confidence"].upper(),
                                              combined.get("message", "")))
        lines.append("")
        lines.append("This is a suggestion from the evidence below, not a verification.")
        lines.append("Confirm it against the provider's metadata before you press Use.")
    else:
        lines.append("NO DATUM WAS PRE-FILLED (%s). %s" % (combined["status"],
                                                          combined.get("message", "")))
        lines.append("Find the datum in the provider's documentation and type its EPSG "
                     "code into Source vertical:")
        lines.append("  CGVD2013 = 6647    CGVD28 = 5713    EGM2008 = 3855    NAVD88 = 5703")
    lines.append("")
    for result in results:
        lines.append("=" * 78)
        lines.append("FILE: %s" % result["source"])
        lines.append("Status: %s" % result["status"])
        if not result["evidence"]:
            lines.append("  (no evidence found)")
        for item in result["evidence"]:
            lines.append("  [%-6s] %-9s EPSG:%-5s %s" % (
                item["confidence"], item["datum_key"], item["epsg"], item["where"]))
            lines.append("           %s" % item["snippet"])
            if item.get("note"):
                lines.append("           note: %s" % item["note"])
        for note in result["notes"]:
            lines.append("  NOTE: %s" % note)
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Suggest the vertical datum of source DEM(s) from evidence.")
    parser.add_argument("sources", nargs="+", help="source DEM file(s)")
    parser.add_argument("--json", action="store_true", help="print the raw result as JSON")
    args = parser.parse_args(argv)
    results = [detect_vertical_datum(p) for p in args.sources]
    combined = combine(results)
    if args.json:
        print(json.dumps({"combined": combined, "results": results}, indent=2))
    else:
        print(format_report(results, combined))
    return 0 if combined["status"] == "found" else 2


if __name__ == "__main__":
    sys.exit(main())
