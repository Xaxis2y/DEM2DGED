# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# PATCH_v0.56.0_gui.py
# Patch Script Version: 0.01
# Part 2 of the v0.55.0 -> v0.56.0 review fixes.
#
# Covers findings B1 (GUI capability gap: per-tile failure tolerance, the
# "no tiles produced" hard error, and -prefilter support), B5 (the resume
# check keyed only on the sidecar) and B6 (product extent counted tiles that
# were never delivered).
#
# Same contract as PATCH_v0.56.0.py: exact-match edits, all-or-nothing per
# file, re-runnable. Some edits deliberately apply to SEVERAL identical
# occurrences -- those declare an expected count and fail if it differs.
#
#     (DGED) C:\...> python PATCH_v0.56.0_gui.py           (dry run)
#     (DGED) C:\...> python PATCH_v0.56.0_gui.py --apply

from __future__ import annotations

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PATCHES = []


def P(fname, finding, desc, old, new, count=1, marker=None):
    """Register one edit.

    `marker` overrides the auto-derived re-run marker. Needed wherever the
    auto-derived one would COLLIDE with text another edit in this same file
    introduces -- the two converter signatures are the case in point: both
    gain the identical line `prefilter="none", prefilter_sigma="auto"):`, so
    applying it to convert_geo() made the convert_utm() edit look
    already-applied and it was silently skipped. Caught by pyflakes
    ("undefined name 'prefilter'"), not by this script, which is why the
    verification pass after patching is not optional.
    """
    PATCHES.append((fname, finding, desc, old, new, count, marker))


# ═══════════════════════════════════════════════════════════════════════════
#  dem2dged_gui.py -- B1
# ═══════════════════════════════════════════════════════════════════════════

P("dem2dged_gui.py", "B1",
  "add the pre-filter dropdown options",
  '''    ("cubic",    "Cubic Convolution"),
]''',
  '''    ("cubic",    "Cubic Convolution"),
]

# GUI anti-alias pre-filter dropdown (v0.56): (code, display label).
#
# The Gaussian pre-filter shipped in v0.49 as a CLI-only feature
# (-prefilter / -prefilter_sigma). The GUI never gained it, so the headline
# capability of that release was unreachable for every operator who works
# from the window rather than the prompt -- and nothing said so. "none" is
# the default here exactly as it is on the command line, so a GUI run that
# leaves this alone produces bit-identical tiles to every previous version.
PREFILTER_OPTIONS = [
    ("none",     "None  (default)"),
    ("gaussian", "Gaussian anti-alias  (for high-relief downsampling)"),
]''')

# ---- convert_geo ----------------------------------------------------------
P("dem2dged_gui.py", "B1",
  "convert_geo(): accept prefilter arguments",
  '''def convert_geo(src, out_dir, level, source_type, sec_class, prod_ver,
                log_fn, progress_fn, stop_event, source_vertical=None,
                resampling="auto", org="", abs_hacc="auto", abs_vacc="auto",
                lineage="", skip_sanity_check=False):''',
  '''def convert_geo(src, out_dir, level, source_type, sec_class, prod_ver,
                log_fn, progress_fn, stop_event, source_vertical=None,
                resampling="auto", org="", abs_hacc="auto", abs_vacc="auto",
                lineage="", skip_sanity_check=False,
                prefilter="none", prefilter_sigma="auto"):''',
  marker='''def convert_geo(src, out_dir, level, source_type, sec_class, prod_ver,
                log_fn, progress_fn, stop_event, source_vertical=None,
                resampling="auto", org="", abs_hacc="auto", abs_vacc="auto",
                lineage="", skip_sanity_check=False,
                prefilter="none", prefilter_sigma="auto"):''')

P("dem2dged_gui.py", "B1",
  "convert_geo(): build the pre-filtered source, and count failed tiles",
  '''    resamp    = _pick_resampler(src, src_gsd_m, latres * 111320, resampling,
                                log_fn=log_fn)
    log_fn("  Resampler: %s%s" % (resamp, _resampler_note(resampling)))''',
  '''    resamp    = _pick_resampler(src, src_gsd_m, latres * 111320, resampling,
                                log_fn=log_fn)
    log_fn("  Resampler: %s%s" % (resamp, _resampler_note(resampling)))

    # -- Anti-alias pre-filter (v0.56 in the GUI; v0.49 on the CLI) -----------
    # Opt-in, and identical in effect to the CLI's -prefilter: a Gaussian-
    # smoothed COPY of the source is built once, and every tile is warped
    # from that copy instead of the original. Tile geometry, grid snapping
    # and the resampler are untouched -- only the elevations being sampled
    # change.
    #
    # Deliberately placed AFTER the resampler choice and BEFORE the clamp
    # scan below, and note the clamp block reads `src`, not `warp_input`, on
    # purpose: the overshoot clamp must use the ORIGINAL source's true
    # min/max, because it exists to catch a resampler inventing a physically
    # impossible elevation, and smoothing narrows the range rather than
    # widening it.
    prefilter = dl.validate_prefilter(prefilter)
    warp_input     = src
    prefilter_tmp  = None
    prefilter_note = "no anti-alias pre-filter"
    if prefilter == "gaussian":
        sigma_px = dl.gaussian_sigma_for_ratio(src_gsd_m, latres * 111320,
                                               prefilter_sigma)
        if sigma_px > 0:
            prefilter_tmp = dl.build_prefiltered_source(
                src, sigma_px, log_fn=lambda m: log_fn("  " + str(m)))
            warp_input = prefilter_tmp
            prefilter_note = ("Gaussian anti-alias pre-filter, sigma=%.3f "
                              "source pixels" % sigma_px)
            log_fn("  Pre-filter: %s" % prefilter_note)
        else:
            log_fn("  NOTE: Gaussian pre-filter requested but the target post "
                   "spacing is not coarser than the source, so there is "
                   "nothing to alias -- pre-filter skipped.")

    # v0.56: tiles whose warp raised. The GUI used to let a single failed
    # tile abort the whole file -- see the tile loop below.
    n_failed = 0''')

P("dem2dged_gui.py", "B1",
  "record the pre-filter in the lineage statement (both converters)",
  '''    lineage_text = lineage or (
        "Derived from source raster '%s' by dem2dged v%s; gdalwarp "
        "resampling=%s; %s." % (
            os.path.basename(src), dl.VERSION, resamp,
            "vertical datum transformed EPSG:%s -> EPSG:3855 (EGM2008)"
            % source_vertical if (source_vertical
                                  and str(source_vertical) != "3855")
            else "heights assumed EGM2008 (label only, no vertical transform)"))''',
  '''    # v0.56: the pre-filter changes the delivered elevations, so it belongs
    # in the lineage statement -- a downstream consumer must be able to tell
    # a smoothed product from an unsmoothed one from the metadata alone.
    # Same wording as the CLI converters have used since v0.49.
    lineage_text = lineage or (
        "Derived from source raster '%s' by dem2dged v%s; gdalwarp "
        "resampling=%s; %s; %s." % (
            os.path.basename(src), dl.VERSION, resamp, prefilter_note,
            "vertical datum transformed EPSG:%s -> EPSG:3855 (EGM2008)"
            % source_vertical if (source_vertical
                                  and str(source_vertical) != "3855")
            else "heights assumed EGM2008 (label only, no vertical transform)"))''',
  2)

P("dem2dged_gui.py", "B1",
  "convert_geo(): a failed tile is skipped and counted, not fatal",
  '''            log_fn("  Creating: %s" % bn)
            _warp_tile(src, tif, srs_str,
                       (te_xmin, te_ymin, te_xmax, te_ymax),
                       lonres, latres, gdal_dtype,
                       resample=resamp, src_srs_str=warp_src_srs)
            _fix_header(tif, retag_srs)''',
  '''            log_fn("  Creating: %s" % bn)
            # v0.56: _warp_tile() raises RuntimeError when gdal.Warp returns
            # None, and nothing caught it here -- so ONE bad tile aborted the
            # entire file, leaving a partial folder with no TABLE_OF_CONTENTS
            # and no collection metadata. The CLI has treated a failed warp
            # as a skippable per-tile problem since v0.42 (which it is: a
            # bad tile is not a bad run), and the GUI now matches it exactly,
            # including the "re-run to retry only the missing tiles" contract
            # that the resume path already supports.
            try:
                _warp_tile(warp_input, tif, srs_str,
                           (te_xmin, te_ymin, te_xmax, te_ymax),
                           lonres, latres, gdal_dtype,
                           resample=resamp, src_srs_str=warp_src_srs)
            except Exception as warp_err:
                log_fn("  ERROR: warp failed for %s (%s) -- tile skipped, "
                       "re-run to retry it." % (bn, warp_err))
                n_failed += 1
                progress_fn(pct)
                continue
            _fix_header(tif, retag_srs)''')

P("dem2dged_gui.py", "B1",
  "convert_geo(): clean up the scratch raster and report a partial or empty run",
  '''            pending.append(dict(bn=bn, tif=tif, xml=xml,
                                 pw=pw, ps=ps, pe=pe, pn=pn))
            tile_basenames.append(bn)
            progress_fn(pct)

    # -- Phase 2: reconcile shared edges (v0.37, Finding 1) --------------------''',
  '''            pending.append(dict(bn=bn, tif=tif, xml=xml,
                                 pw=pw, ps=ps, pe=pe, pn=pn))
            tile_basenames.append(bn)
            progress_fn(pct)

    # v0.56: every tile has been warped (or the Stop button cut the batch
    # short), so the pre-filter scratch raster -- which can be several
    # hundred MB in the system temp folder -- is no longer needed. Removed
    # BEFORE the no-tiles error below, so a failed run cleans up after
    # itself too.
    dl.cleanup_prefiltered_source(prefilter_tmp, log_fn=log_fn)

    # v0.56: a run in which EVERY warp failed used to fall straight through
    # to writing delivery metadata for an empty folder, and the GUI then
    # auto-validated it. Nothing produced is a hard failure; a partial run
    # says so plainly and continues, because the tiles that DID warp are
    # still valid deliverables. Same rule as the CLI converters since v0.42.
    if not tile_basenames and not stopped:
        raise RuntimeError(
            "No tiles were produced (%d warp call(s) failed). Nothing was "
            "written to %s. The usual causes are a source raster GDAL cannot "
            "read, a full disk, or a source that does not overlap the "
            "requested area at all." % (n_failed, out_dir))
    if n_failed:
        log_fn("  WARNING: %d tile(s) failed to warp and are MISSING from "
               "the delivery. Re-run this exact job to retry only the "
               "missing tiles (existing tiles are skipped)." % n_failed)

    # -- Phase 2: reconcile shared edges (v0.37, Finding 1) --------------------''')

# ---- convert_utm ----------------------------------------------------------
P("dem2dged_gui.py", "B1",
  "convert_utm(): accept prefilter arguments",
  '''def convert_utm(src, out_dir, level, zone_str, source_type, sec_class,
                prod_ver, log_fn, progress_fn, stop_event, source_vertical=None,
                resampling="auto", org="", abs_hacc="auto", abs_vacc="auto",
                lineage="", skip_sanity_check=False):''',
  '''def convert_utm(src, out_dir, level, zone_str, source_type, sec_class,
                prod_ver, log_fn, progress_fn, stop_event, source_vertical=None,
                resampling="auto", org="", abs_hacc="auto", abs_vacc="auto",
                lineage="", skip_sanity_check=False,
                prefilter="none", prefilter_sigma="auto"):''',
  marker='''def convert_utm(src, out_dir, level, zone_str, source_type, sec_class,
                prod_ver, log_fn, progress_fn, stop_event, source_vertical=None,
                resampling="auto", org="", abs_hacc="auto", abs_vacc="auto",
                lineage="", skip_sanity_check=False,
                prefilter="none", prefilter_sigma="auto"):''')

P("dem2dged_gui.py", "B1",
  "convert_utm(): build the pre-filtered source, and count failed tiles",
  '''    resamp    = _pick_resampler(src, src_gsd_m, gsd, resampling, log_fn=log_fn)
    log_fn("  Resampler: %s%s" % (resamp, _resampler_note(resampling)))''',
  '''    resamp    = _pick_resampler(src, src_gsd_m, gsd, resampling, log_fn=log_fn)
    log_fn("  Resampler: %s%s" % (resamp, _resampler_note(resampling)))

    # -- Anti-alias pre-filter (v0.56 in the GUI) ----------------------------
    # See the identical block and rationale in convert_geo() above.
    prefilter = dl.validate_prefilter(prefilter)
    warp_input     = src
    prefilter_tmp  = None
    prefilter_note = "no anti-alias pre-filter"
    if prefilter == "gaussian":
        sigma_px = dl.gaussian_sigma_for_ratio(src_gsd_m, gsd, prefilter_sigma)
        if sigma_px > 0:
            prefilter_tmp = dl.build_prefiltered_source(
                src, sigma_px, log_fn=lambda m: log_fn("  " + str(m)))
            warp_input = prefilter_tmp
            prefilter_note = ("Gaussian anti-alias pre-filter, sigma=%.3f "
                              "source pixels" % sigma_px)
            log_fn("  Pre-filter: %s" % prefilter_note)
        else:
            log_fn("  NOTE: Gaussian pre-filter requested but the target post "
                   "spacing is not coarser than the source, so there is "
                   "nothing to alias -- pre-filter skipped.")

    n_failed = 0''')

P("dem2dged_gui.py", "B1",
  "convert_utm(): a failed tile is skipped and counted, not fatal",
  '''            log_fn("  Creating: %s" % bn)
            _warp_tile(src, tif, srs_str,
                       (te_xmin, te_ymin, te_xmax, te_ymax), gsd, gsd, gdal_dtype,
                       resample=resamp, src_srs_str=warp_src_srs)
            _fix_header(tif, retag_srs)''',
  '''            log_fn("  Creating: %s" % bn)
            # v0.56: skip and count instead of aborting the file -- see the
            # matching block and rationale in convert_geo() above.
            try:
                _warp_tile(warp_input, tif, srs_str,
                           (te_xmin, te_ymin, te_xmax, te_ymax), gsd, gsd,
                           gdal_dtype,
                           resample=resamp, src_srs_str=warp_src_srs)
            except Exception as warp_err:
                log_fn("  ERROR: warp failed for %s (%s) -- tile skipped, "
                       "re-run to retry it." % (bn, warp_err))
                n_failed += 1
                progress_fn(pct)
                continue
            _fix_header(tif, retag_srs)''')

P("dem2dged_gui.py", "B1",
  "convert_utm(): clean up the scratch raster and report a partial or empty run",
  '''                                 t_miny=t_miny, tmx=tmx, tmy=tmy))
            tile_basenames.append(bn)
            progress_fn(pct)

    # -- Phase 2: reconcile shared edges (v0.37, Finding 1) --------------------''',
  '''                                 t_miny=t_miny, tmx=tmx, tmy=tmy))
            tile_basenames.append(bn)
            progress_fn(pct)

    # v0.56: see the matching block in convert_geo() above.
    dl.cleanup_prefiltered_source(prefilter_tmp, log_fn=log_fn)

    if not tile_basenames and not stopped:
        raise RuntimeError(
            "No tiles were produced (%d warp call(s) failed). Nothing was "
            "written to %s. The usual causes are a source raster GDAL cannot "
            "read, a full disk, or a source that does not overlap the "
            "requested UTM zone at all." % (n_failed, out_dir))
    if n_failed:
        log_fn("  WARNING: %d tile(s) failed to warp and are MISSING from "
               "the delivery. Re-run this exact job to retry only the "
               "missing tiles (existing tiles are skipped)." % n_failed)

    # -- Phase 2: reconcile shared edges (v0.37, Finding 1) --------------------''')

# ---- GUI control + wiring --------------------------------------------------
P("dem2dged_gui.py", "B1",
  "add the pre-filter row to the window",
  '''        tk.Label(rrow,
                 text="  Auto = average (downsampling) / bilinear.  "
                      "Optimize = tests Nearest/Bilinear/Cubic and keeps "
                      "the most accurate (slower).",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY).pack(side="left")''',
  '''        tk.Label(rrow,
                 text="  Auto = average (downsampling) / bilinear.  "
                      "Optimize = tests Nearest/Bilinear/Cubic and keeps "
                      "the most accurate (slower).",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY).pack(side="left")

        # ── Anti-alias pre-filter (v0.56) ─────────────────────────────────────
        # Reaches dl.build_prefiltered_source() through convert_geo/convert_utm,
        # the same path the CLI's -prefilter takes. Default "none" keeps every
        # existing GUI job bit-identical.
        prow = tk.Frame(inner, bg=LIGHT); prow.pack(fill="x", pady=4)
        tk.Label(prow, text="Pre-filter:", width=12, anchor="w",
                 bg=LIGHT, font=("Segoe UI",10)).pack(side="left")
        self.prefilter_var = tk.StringVar(value=PREFILTER_OPTIONS[0][1])
        self.prefilter_cb = ttk.Combobox(prow, textvariable=self.prefilter_var,
                                         state="readonly", width=32,
                                         font=("Segoe UI",10))
        self.prefilter_cb["values"] = [lbl for _, lbl in PREFILTER_OPTIONS]
        self.prefilter_cb.current(0)   # default: None
        self.prefilter_cb.pack(side="left")
        tk.Label(prow,
                 text="  Low-passes the source before warping, to stop "
                      "short-wavelength terrain aliasing back in when "
                      "downsampling. A bias/variance trade -- verify on "
                      "your own data.",
                 font=("Segoe UI",9), bg=LIGHT, fg=GRAY).pack(side="left")''')

P("dem2dged_gui.py", "B1",
  "resolve the selected pre-filter code",
  '''        resample_label = self.resample_var.get()
        resample_code  = "auto"
        for code, lbl in RESAMPLING_OPTIONS:
            if lbl == resample_label:
                resample_code = code
                break''',
  '''        resample_label = self.resample_var.get()
        resample_code  = "auto"
        for code, lbl in RESAMPLING_OPTIONS:
            if lbl == resample_label:
                resample_code = code
                break

        # ── Pre-filter selection (v0.56) ────────────────────────────────────
        prefilter_label = self.prefilter_var.get()
        prefilter_code  = "none"
        for code, lbl in PREFILTER_OPTIONS:
            if lbl == prefilter_label:
                prefilter_code = code
                break''')

P("dem2dged_gui.py", "B1",
  "pass the pre-filter through to both converters",
  '''                                            lineage=lineage,
                                            skip_sanity_check=
                                                self.skip_sanity_var.get())''',
  '''                                            lineage=lineage,
                                            skip_sanity_check=
                                                self.skip_sanity_var.get(),
                                            prefilter=prefilter_code)''',
  2)


# ═══════════════════════════════════════════════════════════════════════════
#  B5 -- the resume check must see the TILE, not only the sidecar
# ═══════════════════════════════════════════════════════════════════════════

_B5_NOTE = '''            # v0.56: the .tif is checked too. Phase 3 writes sidecars only
            # after every warp completes, so an .xml without its .tif is
            # unusual -- but a tile deleted or corrupted after delivery, beside
            # a surviving sidecar, was silently accepted as "done" and could
            # never be regenerated by re-running. It then reached the validator
            # as a missing or unreadable file.
'''

P("dem2dged_geo.py", "B5",
  "resume: require both the tile and its sidecar",
  '''            if os.path.isfile(xml_path):
                print("Skip (exists): %s" % xml_path)''',
  _B5_NOTE + '''            if os.path.isfile(xml_path) and os.path.isfile(tif_path):
                print("Skip (exists): %s" % xml_path)''')

P("dem2dged_utm.py", "B5",
  "resume: require both the tile and its sidecar",
  '''            if os.path.isfile(xml_path):
                print("Skip (exists): %s" % xml_path)''',
  _B5_NOTE + '''            if os.path.isfile(xml_path) and os.path.isfile(tif_path):
                print("Skip (exists): %s" % xml_path)''')

P("dem2dged_gui.py", "B5",
  "resume: require both the tile and its sidecar (both converters)",
  '''            if os.path.isfile(xml):
                log_fn("  Skip (exists): %s" % bn)''',
  _B5_NOTE + '''            if os.path.isfile(xml) and os.path.isfile(tif):
                log_fn("  Skip (exists): %s" % bn)''',
  2)


# ═══════════════════════════════════════════════════════════════════════════
#  B6 -- the product extent must cover only tiles that were DELIVERED
# ═══════════════════════════════════════════════════════════════════════════

P("dem2dged_geo.py", "B6",
  "product extent: stop counting tiles that failed to warp",
  '''            # Track product extent (post extent, not the expanded warp extent)
            pw, ps = t_minlon, t_minlat
            pe, pn = t_minlon + tiledim, t_minlat + tiledim
            prod_west  = pw if prod_west  is None else min(prod_west, pw)
            prod_south = ps if prod_south is None else min(prod_south, ps)
            prod_east  = pe if prod_east  is None else max(prod_east, pe)
            prod_north = pn if prod_north is None else max(prod_north, pn)''',
  '''            # Track product extent (post extent, not the expanded warp extent).
            # v0.56: the four min/max updates used to run HERE, at the top of
            # the loop body -- before the skip branch and before the warp --
            # so a run whose outer tiles all failed to warp still reported
            # their extent as the collection's bounding box. They now run in
            # _note_delivered(), called only where a tile actually joins the
            # delivery.
            pw, ps = t_minlon, t_minlat
            pe, pn = t_minlon + tiledim, t_minlat + tiledim''')

P("dem2dged_geo.py", "B6",
  "product extent: add the delivered-tile helper",
  '''    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below
    n_failed = 0      # v0.42: tiles whose gdalwarp call returned non-zero''',
  '''    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below
    n_failed = 0      # v0.42: tiles whose gdalwarp call returned non-zero

    def _note_delivered(w, s, e, n):
        """Extend the product extent by one tile (v0.56).

        Called ONLY from the points where a tile actually becomes part of the
        delivery -- resumed, direct-copied or freshly warped -- so a tile that
        failed to warp can no longer widen the collection bounding box it is
        absent from.
        """
        nonlocal prod_west, prod_south, prod_east, prod_north
        prod_west  = w if prod_west  is None else min(prod_west, w)
        prod_south = s if prod_south is None else min(prod_south, s)
        prod_east  = e if prod_east  is None else max(prod_east, e)
        prod_north = n if prod_north is None else max(prod_north, n)''')

# NOTE: the three call sites sit at three different indentation levels, so
# each gets its own edit with enough surrounding context to be unambiguous.
# A single 12-space pattern would also match as a SUFFIX of the 16- and
# 20-space lines and insert the call at the wrong depth -- which is exactly
# what the first cut of this patch did.
P("dem2dged_geo.py", "B6",
  "product extent: record a resumed tile",
  '''                print("Skip (exists): %s" % xml_path)
                tile_basenames.append(basename)
                continue''',
  '''                print("Skip (exists): %s" % xml_path)
                tile_basenames.append(basename)
                _note_delivered(pw, ps, pe, pn)
                continue''')

P("dem2dged_geo.py", "B6",
  "product extent: record a direct-copied tile",
  '''                    tile_basenames.append(basename)
                    print("%d%% done" % pct)
                    continue''',
  '''                    tile_basenames.append(basename)
                    _note_delivered(pw, ps, pe, pn)
                    print("%d%% done" % pct)
                    continue''')

P("dem2dged_geo.py", "B6",
  "product extent: record a freshly warped tile",
  '''            tile_basenames.append(basename)
            print("%d%% done" % pct)''',
  '''            tile_basenames.append(basename)
            _note_delivered(pw, ps, pe, pn)
            print("%d%% done" % pct)''')

P("dem2dged_utm.py", "B6",
  "product extent: stop counting tiles that failed to warp",
  '''            # Track product extent (post extent, not the expanded warp extent)
            prod_minx = t_minx if prod_minx is None else min(prod_minx, t_minx)
            prod_miny = t_miny if prod_miny is None else min(prod_miny, t_miny)
            tmx, tmy = t_minx + tiledim, t_miny + tiledim
            prod_maxx = tmx if prod_maxx is None else max(prod_maxx, tmx)
            prod_maxy = tmy if prod_maxy is None else max(prod_maxy, tmy)''',
  '''            # Track product extent (post extent, not the expanded warp extent).
            # v0.56: moved into _note_delivered() -- see the identical change
            # and rationale in dem2dged_geo.py.
            tmx, tmy = t_minx + tiledim, t_miny + tiledim''')

P("dem2dged_utm.py", "B6",
  "product extent: add the delivered-tile helper",
  '''    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below
    n_failed = 0      # v0.42: tiles whose gdalwarp call returned non-zero''',
  '''    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below
    n_failed = 0      # v0.42: tiles whose gdalwarp call returned non-zero

    def _note_delivered(x0, y0, x1, y1):
        """Extend the product extent by one tile (v0.56).

        See the identical helper and rationale in dem2dged_geo.py.
        """
        nonlocal prod_minx, prod_miny, prod_maxx, prod_maxy
        prod_minx = x0 if prod_minx is None else min(prod_minx, x0)
        prod_miny = y0 if prod_miny is None else min(prod_miny, y0)
        prod_maxx = x1 if prod_maxx is None else max(prod_maxx, x1)
        prod_maxy = y1 if prod_maxy is None else max(prod_maxy, y1)''')

P("dem2dged_utm.py", "B6",
  "product extent: record a resumed tile",
  '''                print("Skip (exists): %s" % xml_path)
                tile_basenames.append(basename)
                continue''',
  '''                print("Skip (exists): %s" % xml_path)
                tile_basenames.append(basename)
                _note_delivered(t_minx, t_miny, tmx, tmy)
                continue''')

P("dem2dged_utm.py", "B6",
  "product extent: record a direct-copied tile",
  '''                    tile_basenames.append(basename)
                    print("%d%% done" % pct)
                    continue''',
  '''                    tile_basenames.append(basename)
                    _note_delivered(t_minx, t_miny, tmx, tmy)
                    print("%d%% done" % pct)
                    continue''')

P("dem2dged_utm.py", "B6",
  "product extent: record a freshly warped tile",
  '''            tile_basenames.append(basename)
            print("%d%% done" % pct)''',
  '''            tile_basenames.append(basename)
            _note_delivered(t_minx, t_miny, tmx, tmy)
            print("%d%% done" % pct)''')

P("dem2dged_gui.py", "B6",
  "convert_geo(): product extent counts only delivered tiles",
  '''            # Track product extent (post extent, not the expanded warp extent)
            pw, ps = t_minlon, t_minlat
            pe, pn = t_minlon+tiledim, t_minlat+tiledim
            prod_west  = pw if prod_west  is None else min(prod_west, pw)
            prod_south = ps if prod_south is None else min(prod_south, ps)
            prod_east  = pe if prod_east  is None else max(prod_east, pe)
            prod_north = pn if prod_north is None else max(prod_north, pn)''',
  '''            # Track product extent (post extent, not the expanded warp extent).
            # v0.56: recorded only where a tile joins the delivery -- see the
            # identical change in dem2dged_geo.py.
            pw, ps = t_minlon, t_minlat
            pe, pn = t_minlon+tiledim, t_minlat+tiledim''')

P("dem2dged_gui.py", "B6",
  "convert_geo(): add the delivered-tile helper",
  '''    tile_basenames = []
    prod_west = prod_east = prod_south = prod_north = None
    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below''',
  '''    tile_basenames = []
    prod_west = prod_east = prod_south = prod_north = None
    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below

    def _note_delivered(w, s, e, n):
        """Extend the product extent by one delivered tile (v0.56)."""
        nonlocal prod_west, prod_south, prod_east, prod_north
        prod_west  = w if prod_west  is None else min(prod_west, w)
        prod_south = s if prod_south is None else min(prod_south, s)
        prod_east  = e if prod_east  is None else max(prod_east, e)
        prod_north = n if prod_north is None else max(prod_north, n)''')

P("dem2dged_gui.py", "B6",
  "convert_utm(): product extent counts only delivered tiles",
  '''            # Track product extent (post extent, not the expanded warp extent)
            tmx, tmy = t_minx+tiledim, t_miny+tiledim
            prod_minx = t_minx if prod_minx is None else min(prod_minx, t_minx)
            prod_miny = t_miny if prod_miny is None else min(prod_miny, t_miny)
            prod_maxx = tmx    if prod_maxx is None else max(prod_maxx, tmx)
            prod_maxy = tmy    if prod_maxy is None else max(prod_maxy, tmy)''',
  '''            # Track product extent (post extent, not the expanded warp extent).
            # v0.56: recorded only where a tile joins the delivery -- see the
            # identical change in dem2dged_geo.py.
            tmx, tmy = t_minx+tiledim, t_miny+tiledim''')

P("dem2dged_gui.py", "B6",
  "convert_utm(): add the delivered-tile helper",
  '''    tile_basenames = []
    prod_minx = prod_miny = prod_maxx = prod_maxy = None
    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below''',
  '''    tile_basenames = []
    prod_minx = prod_miny = prod_maxx = prod_maxy = None
    tile_grid = {}    # (yy, xx) -> tif_path, tiles created in THIS run only
    pending = []      # per-tile info needed for the stats/sidecar pass below

    def _note_delivered(x0, y0, x1, y1):
        """Extend the product extent by one delivered tile (v0.56)."""
        nonlocal prod_minx, prod_miny, prod_maxx, prod_maxy
        prod_minx = x0 if prod_minx is None else min(prod_minx, x0)
        prod_miny = y0 if prod_miny is None else min(prod_miny, y0)
        prod_maxx = x1 if prod_maxx is None else max(prod_maxx, x1)
        prod_maxy = y1 if prod_maxy is None else max(prod_maxy, y1)''')

# The two GUI converters use different extent variable names, so each gets
# its own recording edit. convert_geo's two kept-tile points carry
# pw/ps/pe/pn; convert_utm's carry t_minx/t_miny/tmx/tmy.
P("dem2dged_gui.py", "B6",
  "convert_geo(): record every delivered tile",
  '''                tile_basenames.append(bn)
                progress_fn(pct); continue

            log_fn("  Creating: %s" % bn)
            # v0.56: _warp_tile() raises RuntimeError when gdal.Warp returns''',
  '''                tile_basenames.append(bn)
                _note_delivered(pw, ps, pe, pn)
                progress_fn(pct); continue

            log_fn("  Creating: %s" % bn)
            # v0.56: _warp_tile() raises RuntimeError when gdal.Warp returns''')

P("dem2dged_gui.py", "B6",
  "convert_geo(): record every freshly warped tile",
  '''            pending.append(dict(bn=bn, tif=tif, xml=xml,
                                 pw=pw, ps=ps, pe=pe, pn=pn))
            tile_basenames.append(bn)
            progress_fn(pct)''',
  '''            pending.append(dict(bn=bn, tif=tif, xml=xml,
                                 pw=pw, ps=ps, pe=pe, pn=pn))
            tile_basenames.append(bn)
            _note_delivered(pw, ps, pe, pn)
            progress_fn(pct)''')

P("dem2dged_gui.py", "B6",
  "convert_utm(): record every delivered tile",
  '''                tile_basenames.append(bn)
                progress_fn(pct); continue

            log_fn("  Creating: %s" % bn)
            # v0.56: skip and count instead of aborting the file -- see the''',
  '''                tile_basenames.append(bn)
                _note_delivered(t_minx, t_miny, tmx, tmy)
                progress_fn(pct); continue

            log_fn("  Creating: %s" % bn)
            # v0.56: skip and count instead of aborting the file -- see the''')

P("dem2dged_gui.py", "B6",
  "convert_utm(): record every freshly warped tile",
  '''                                 t_miny=t_miny, tmx=tmx, tmy=tmy))
            tile_basenames.append(bn)
            progress_fn(pct)''',
  '''                                 t_miny=t_miny, tmx=tmx, tmy=tmy))
            tile_basenames.append(bn)
            _note_delivered(t_minx, t_miny, tmx, tmy)
            progress_fn(pct)''')


# ═══════════════════════════════════════════════════════════════════════════
#  runner
# ═══════════════════════════════════════════════════════════════════════════


def main():
    ap = argparse.ArgumentParser(
        description="Part 2 of the v0.56.0 review fixes (GUI, resume, extent).")
    ap.add_argument("--apply", action="store_true",
                    help="write the files (without this it is a dry run)")
    args = ap.parse_args()

    by_file = {}
    for fname, finding, desc, old, new, count, marker in PATCHES:
        by_file.setdefault(fname, []).append(
            (finding, desc, old, new, count, marker))

    print("=" * 74)
    print("dem2dged  v0.56.0 review fixes, part 2   (%s)"
          % ("APPLY" if args.apply else "DRY RUN -- nothing will be written"))
    print("=" * 74)

    total_applied = total_skipped = total_failed = 0

    for fname in by_file:
        path = os.path.join(HERE, fname)
        print("")
        print("-- %s" % fname)
        if not os.path.isfile(path):
            print("   [FAIL] file not found")
            total_failed += len(by_file[fname])
            continue

        text = io.open(path, encoding="utf-8", newline="").read()
        working = text
        applied, skipped, failed = [], [], []

        for finding, desc, old, new, count, marker in by_file[fname]:
            # See PATCH_v0.56.0.py for why this tests the full replacement
            # text, first, rather than the absence of `old` or a single
            # marker line.
            if working.count(new) >= 1:
                skipped.append((finding, desc))
                continue
            n = working.count(old)
            if n == count:
                working = working.replace(old, new)
                applied.append((finding, desc, count))
            elif n == 0:
                failed.append((finding, desc, "no match"))
            else:
                failed.append((finding, desc,
                               "%d match(es), expected %d" % (n, count)))

        for finding, desc, count in applied:
            suffix = "  (x%d)" % count if count != 1 else ""
            print("   [ OK ] %-4s %s%s" % (finding, desc, suffix))
        for finding, desc in skipped:
            print("   [SKIP] %-4s %s  (already applied)" % (finding, desc))
        for finding, desc, why in failed:
            print("   [FAIL] %-4s %s  (%s)" % (finding, desc, why))

        total_applied += len(applied)
        total_skipped += len(skipped)
        total_failed += len(failed)

        if failed:
            print("   -> %d edit(s) did not match; %s LEFT UNCHANGED."
                  % (len(failed), fname))
            continue

        if applied and args.apply:
            with io.open(path, "w", encoding="utf-8", newline="") as f:
                f.write(working)
            print("   -> written (%d edit(s))" % len(applied))
        elif applied:
            print("   -> %d edit(s) would be written" % len(applied))

    print("")
    print("=" * 74)
    print("applied=%d  already-applied=%d  failed=%d"
          % (total_applied, total_skipped, total_failed))
    if not args.apply and total_applied:
        print("Dry run. Re-run with --apply to write the files.")
    print("=" * 74)
    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(main())
