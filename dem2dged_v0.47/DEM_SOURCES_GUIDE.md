# DEM Download Guide for Testing dem2dged

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

Testing the auto-resolution detection feature requires DEMs of different resolutions.  
This guide lists free sources organized by spatial resolution.

---

## Resolution Quick Reference

| Resolution | Use Case | Best Source | Download Time |
|------------|----------|------------|----------------|
| **30m** | Testing standard level 2 | SRTM 1-Arc | 5-10 min |
| **90m** | Testing level 1 | SRTM 3-Arc | 2-5 min |
| **1m** | Testing high-res level 6 | OpenTopography | 10-30 min |
| **2m** | Testing level 5 | Copernicus GLO-30 | 5-15 min |

---

## 1. SRTM (30m and 90m) - RECOMMENDED FOR TESTING

**Website**: https://www.usgs.gov/  
**Resolution**: 
- SRTM 1-Arc Second = 30m (best for testing)
- SRTM 3-Arc Second = 90m

**Coverage**: Global (except polar regions)  
**License**: Public Domain - Free to use

### How to Download SRTM

**Option A: USGS Earth Explorer (Easiest)**
1. Go to: https://earthexplorer.usgs.gov/
2. Search for your location on the map
3. Click "Data Sets" on the left
4. Check "Digital Elevation"
5. Select "SRTM 1 Arc-Second Global" or "SRTM 3 Arc-Second Global"
6. Click "Results" and download

**Option B: OpenDEM (Fast)**
1. Go to: https://opendem.info/
2. Select your region
3. Choose SRTM (30m or 90m)
4. Download GeoTIFF

**What You'll Get**:
- Format: GeoTIFF (.tif)
- Projection: WGS84 (EPSG:4326)
- Resolution: 30m or 90m per pixel
- Size: 5-50 MB depending on area

**Perfect For Testing**:
- ✓ Common resolution
- ✓ Wide coverage
- ✓ Easy to download
- ✓ Most commonly used DEM source

---

## 2. Copernicus DEM (2m and 30m)

**Website**: https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM

**Resolution**:
- GLO-30 = 30m (global)
- GLO-90 = 90m (global)

**Coverage**: Global  
**License**: Free (Creative Commons Attribution 4.0)

### How to Download Copernicus DEM

1. Go to: https://browser.dataspace.copernicus.eu/
2. Search for your area
3. Select "Copernicus DEM 30m" or "Copernicus DEM 90m"
4. Download GeoTIFF

**What You'll Get**:
- Format: GeoTIFF (.tif)
- Projection: WGS84 (EPSG:4326)
- Resolution: 30m or 90m
- Size: 5-50 MB

**Perfect For Testing**:
- ✓ Recent data (2026 updates)
- ✓ Good quality
- ✓ Easy download
- ✓ Same resolution as SRTM 30m for comparison

---

## 3. NASA Earthdata (2m High-Resolution)

**Website**: https://www.earthdata.nasa.gov/topics/land-surface/digital-elevation-terrain-model-dem

**Resolution**: 2m (high-resolution)  
**Coverage**: Non-polar regions  
**License**: Free

### How to Download NASA 2m DEM

1. Go to: https://earthdata.nasa.gov/
2. Create free NASA account if needed
3. Search "NASADEM" or "ASTER"
4. Select your area
5. Download GeoTIFF

**What You'll Get**:
- Format: GeoTIFF (.tif)
- Projection: WGS84
- Resolution: 2m per pixel
- Size: 50-200 MB (larger due to fine resolution)
- File name: HGT format or GeoTIFF

**Perfect For Testing**:
- ✓ Very high resolution (2m)
- ✓ Tests fine-resolution levels (6, 7, 8)
- ✓ Tests upsampling detection
- ⚠ Larger files (slower download)

---

## 4. ASTER GDEM (30m)

**Website**: https://lpdaac.usgs.gov/products/astgtmv003/

**Resolution**: 30m  
**Coverage**: 83°N to 83°S  
**License**: Free

### How to Download ASTER GDEM

1. Go to: https://lpdaac.usgs.gov/
2. Search for "ASTGTM"
3. Select "ASTER Global DEM"
4. Choose your region
5. Download

**What You'll Get**:
- Format: HDF5 or GeoTIFF
- Resolution: 30m
- Coverage: Global (except poles)

**Note**: Requires conversion from HDF5 to GeoTIFF (use GDAL)

---

## 5. ALOS World 3D (30m)

**Website**: https://www.eorc.jaxa.jp/ALOS/en/aw3d30/

**Resolution**: 30m (DSM - Digital Surface Model)  
**Coverage**: Global  
**License**: Free

### How to Download ALOS World 3D

1. Go to: https://www.eorc.jaxa.jp/ALOS/en/aw3d30/
2. Download data for your region
3. Unzip and convert if needed

**What You'll Get**:
- Format: GeoTIFF
- Resolution: 30m
- High quality surface model

---

## 6. OpenTopography (High-Resolution LiDAR)

**Website**: https://cloud.sdsc.edu/v1/AUTH_opentopography/

**Resolution**: Variable (0.5m - 5m from LiDAR)  
**Coverage**: Regional (selected areas)  
**License**: Free for research

### How to Download OpenTopography

1. Go to: https://cloud.sdsc.edu/v1/AUTH_opentopography/
2. Browse available LiDAR datasets
3. Select region
4. Download high-resolution DEM

**What You'll Get**:
- Format: GeoTIFF
- Resolution: 0.5m - 5m (varies by location)
- Very high quality
- Large file sizes (100MB - 1GB+)

**Perfect For Testing**:
- ✓ Ultra-high resolution (tests Level 7, 8, 9)
- ✓ Tests downsampling
- ✓ Tests large file handling
- ⚠ Large downloads
- ⚠ Limited geographic coverage

---

## Testing Strategy: Resolution Range

To test your auto-detection feature, download one DEM from each resolution category:

### Minimum Test Set (4 files - ~50MB total)
```
Resolution    Source              Level Test    Download Size
────────────────────────────────────────────────────────────
90m      →    SRTM 3-Arc      →   Level 1      2-5 MB
30m      →    SRTM 1-Arc      →   Level 2      5-10 MB
2m       →    NASA 2m DEM     →   Level 5      50-200 MB
1m       →    OpenTopography  →   Level 6      100-500 MB
```

### Recommended Test Set (6 files - ~200MB total)
```
Resolution    Source              Level Test    Download Size
────────────────────────────────────────────────────────────
90m      →    SRTM 3-Arc      →   Level 1      2-5 MB
30m      →    Copernicus 30m  →   Level 2      5-10 MB
30m      →    SRTM 1-Arc      →   Level 2      5-10 MB (compare sources)
2m       →    NASA 2m DEM     →   Level 5      50-200 MB
1m       →    OpenTopography  →   Level 6      100-500 MB
0.5m     →    LiDAR (if avail)→   Level 8      200-500 MB
```

---

## Quick Start: Download Your First Test DEM

### For 30m Resolution (Most Common - Start Here!)

**Step 1: Go to USGS Earth Explorer**
- URL: https://earthexplorer.usgs.gov/
- Create free account

**Step 2: Select Area**
- Click on map to choose location
- Or search by coordinates
- Or draw rectangle around area of interest

**Step 3: Choose Data**
- Click "Data Sets" on left panel
- Expand "Digital Elevation"
- Check "SRTM 1 Arc-Second Global"

**Step 4: Download**
- Click "Results"
- Select tiles you want
- Click "Download Options" → "GeoTIFF"
- Download will start

**Result**: You'll have a .tif file ready for testing!

---

## Sample DEM Coordinates by Country/Region

Use these coordinates to test downloading:

### South Korea
- Coordinates: 37.5665°N, 126.9780°E (Seoul area)
- Resolution to download: 30m (Level 2)
- Expected file: ~5-10 MB

### USA
- Coordinates: 40.7128°N, 74.0060°W (New York)
- Resolution to download: 30m (Level 2)
- Expected file: ~5-10 MB

### Japan
- Coordinates: 35.6762°N, 139.6503°E (Tokyo)
- Resolution to download: 30m (Level 2)
- Expected file: ~5-10 MB

### Europe (Alps)
- Coordinates: 47.0°N, 10.0°E
- Resolution: 30m recommended
- Expected file: ~5-10 MB

---

## Format Information

### Common DEM Formats

**GeoTIFF (.tif, .tiff)**
- ✓ Best for dem2dged
- ✓ Contains geospatial metadata
- ✓ Universally supported
- Size: Medium (5-200 MB typical)

**HGT (.hgt)**
- Format used by SRTM originally
- Needs conversion to GeoTIFF
- Conversion: `gdal_translate file.hgt file.tif`

**HDF5 (.h5)**
- Used by ASTER GDEM
- Needs conversion to GeoTIFF
- Conversion: `gdalwarp file.h5 file.tif`

**NetCDF (.nc)**
- Scientific format
- Needs conversion to GeoTIFF
- Conversion: `gdal_translate file.nc file.tif`

**Recommendation**: Always convert to **GeoTIFF** format for dem2dged

---

## Conversion to GeoTIFF

If you download non-GeoTIFF formats, convert them using GDAL:

```batch
:: Activate DGED environment
conda activate DGED

:: Convert HGT to GeoTIFF
gdal_translate input.hgt output.tif

:: Convert HDF5 to GeoTIFF
gdalwarp input.h5 output.tif

:: Convert NetCDF to GeoTIFF
gdal_translate input.nc output.tif
```

---

## Testing Workflow

### Day 1: Download Test Data
1. Download 30m DEM from SRTM (easy start)
2. Download 90m DEM from SRTM 3-Arc (for comparison)
3. Download 2m DEM from NASA Earthdata (if available in your region)

### Day 2: Test Resolution Auto-Detection
1. Load each DEM into dem2dged
2. Verify detected resolution is correct
3. Verify auto-selected level matches
4. Log results

### Day 3: Build Validation Report
1. Run conversions with auto-selected levels
2. Verify validation report shows detailed table
3. Check pass/warn/fail status for each tile

---

## Troubleshooting

### Issue: Download Link Not Working
**Solution**: Check alternate sources
- USGS Earth Explorer down? Try OpenDEM
- OpenDEM down? Try Copernicus
- All down? Try NASA Earthdata

### Issue: File is HGT/HDF5, Not GeoTIFF
**Solution**: Convert using GDAL (included in DGED environment)
```bash
conda activate DGED
gdal_translate input.hgt output.tif
```

### Issue: File Too Large
**Solution**: Download smaller region
- Split into smaller tiles
- Use "Download Options" to select specific tiles
- Start with 1° × 1° area (manageable size)

### Issue: Projection Not WGS84
**Solution**: Reproject using GDAL
```bash
gdalwarp -t_srs EPSG:4326 input.tif output.tif
```

### Issue: No Data in Selected Area
**Solution**: Try different location
- Polar regions not covered by SRTM (use Copernicus)
- Mountains in clouds (try multiple sources)
- Check coverage maps on download websites

---

## Storage Organization

Organize downloaded DEMs by resolution:

```
DEM_Test_Data/
├─ 30m/
│  ├─ srtm_30m_korea.tif
│  ├─ copernicus_30m_alps.tif
│  └─ aster_30m_usa.tif
├─ 90m/
│  ├─ srtm_90m_korea.tif
│  └─ srtm_90m_global.tif
├─ 2m/
│  ├─ nasa_2m_newyork.tif
│  └─ dem_2m_highres.tif
└─ 1m/
   └─ lidar_1m_california.tif
```

This makes it easy to test each resolution!

---

## Summary: Best Sources by Use Case

| Goal | Best Source | Resolution |
|------|-------------|-----------|
| Quick test | SRTM 1-Arc | 30m |
| Global coverage | Copernicus | 30m or 90m |
| High resolution | NASA 2m | 2m |
| Best quality | OpenTopography LiDAR | 0.5-5m |
| Multiple sources comparison | SRTM + Copernicus | 30m |

---

## Next Steps

1. **Today**: Download 1-2 sample DEMs from SRTM or Copernicus
2. **Tomorrow**: Test auto-resolution detection with downloaded data
3. **Later**: Build the detailed validation report feature

Downloaded DEMs are ready whenever you want to test a conversion.

