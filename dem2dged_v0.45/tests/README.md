# dem2dged test suite

Three layers, all runnable from an **Anaconda Prompt** in a **dedicated**
conda environment. Never install GDAL into `base` — it is the most reliable
way to produce dependency conflicts that are then very hard to unpick.

```bat
:: one-time setup
conda create -n DGED python=3.11 -c conda-forge
conda activate DGED
conda install -c conda-forge gdal numpy pytest

:: every time
conda activate DGED
cd /d <this project folder>
```

## The three layers

| Layer | Command | Needs | What it proves |
|---|---|---|---|
| 1. Static self-audit | `python audit_pure.py` | nothing (GDAL is stubbed) | Naming round-trips, tile geometry, converter↔validator agreement, template placeholders, sanity-check and auto-optimize logic, version consistency. Expect `RESULT: 0 problem(s)`. |
| 2. Unit tests | `pytest tests/test_lib.py tests/test_validator.py -v` | `osgeo` importable | The DGED tables, tile naming, warp extents, resampler policy, the v0.42 pre-flight guards, and every named validator regression. |
| 3. Integration tests | `pytest tests/test_converters.py -v` | `gdalwarp` **executable** on PATH | Real GEO/UTM conversions, then inspection of what landed on disk: pairing, name↔georeferencing agreement, header profile, level-aware data type, tile dimensions, bit-identical shared edges, sidecar well-formedness, the cubic clamp, the negative-northing clamp, and the tool's own validator run against the tool's own output. |

Everything at once:

```bat
pytest -q
```

Or the whole release gate, which wraps all three plus a real end-to-end CLI
run and writes a log per step:

```bat
python RELEASE_CHECK_v0.45.py
```

## Reading the result

`pytest -q` ends with a line like `352 passed, 0 skipped`.

**A skip is not a pass.** If you see skips, they are the integration layer
reporting that `gdalwarp` is not on PATH — meaning no real conversion was
exercised at all. If you are cutting a release, that number must be 0. Check
with:

```bat
where gdalwarp
```

If it prints nothing, you are in the wrong environment (almost always
`base` instead of `DGED`).

## Notes for anyone adding a test

**`main()` takes a raw argv list, not a Namespace.** `dem2dged_geo.main()`
and `dem2dged_utm.main()` call `parse_args(args[1:])` themselves, so element
0 must be the program name. Use the `_geo_argv` / `_utm_argv` helpers in
`test_converters.py`. Passing a parsed `Namespace` is what made all 22
integration tests error identically with `TypeError: 'Namespace' object is
not subscriptable` the first time they were ever run (v0.41 finding 12).

**`output_dir` is per-test, and must stay that way.** It returns a fresh
`tempfile.mkdtemp()` for every test that asks for one. It used to be a
single session-wide directory, so one test's leftover tiles were still
present when the next globbed `*.tif` — and
`test_utm_names_are_zero_padded` failed on a leftover GEO-named file rather
than on anything wrong with UTM naming (v0.38). A shared output directory
turns "test A is broken" into "test B fails", which is the most expensive
kind of test bug.

**Do not assert on `band.ComputeRasterMinMax()`.** Its behaviour on an
all-NoData band varies with the GDAL version and the exception setting. Use
`dem2dged_lib.compute_tile_stats()`, which is NoData-aware and is what the
tool itself uses.

**No external data, ever.** Every source DEM is generated with GDAL in a
temp directory by a fixture in `conftest.py`. A test that needs a new shape
of input should add a fixture there rather than depend on a file that has
to be shipped or downloaded.
