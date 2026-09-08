# Building a native .atbx from DGED_Load_Tool_script.py

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

`DGED_Loader.pyt` (in this same folder) already is a complete, ready-to-run
ArcGIS Pro toolbox -- most people don't need anything below this line. Use
this guide only if you specifically need the tool packaged as a literal
`.atbx` file (for distribution, an internal policy, etc.).

ArcGIS Pro builds the `.atbx` container itself when you go through this
wizard, so the result is guaranteed valid -- unlike a hand-built `.atbx`,
which risks Pro flagging it as corrupt since Esri doesn't publish the
format's internal schema. This takes about two minutes.

## Steps (ArcGIS Pro 3.7)

1. **Catalog pane > right-click a folder connection > New > Toolbox.**
   Rename it, e.g. `DGED Loader.atbx`. Save/create it directly inside
   this `DGED_Loader` folder so everything stays together.

2. **Right-click the new toolbox > New > Script.**

3. On the **General** page of the New Script dialog:
   - **Name:** `LoadDGEDTiles`
   - **Label:** `Load DGED Tiles`
   - **Description:** *(optional)* "Loads DEM2DGED .tif tiles into the
     active map without a mosaic dataset."
   - **Script File:** browse to `DGED_Load_Tool_script.py` in this
     folder.
   - Leave **"Run Python script as background process"** UNCHECKED.
     The tool needs the foreground `CURRENT` project/map reference;
     running in the background can lose access to it.

4. On the **Parameters** page, add the six rows below **in this exact
   top-to-bottom order** -- the script reads them by position (1st row =
   parameter 0, 2nd row = parameter 1, and so on), not by name:

   | # | Display Name | Data Type | Type | Direction | MultiValue | Default |
   |---|---|---|---|---|---|---|
   | 1 | Main DGED Folder | Folder | Optional | Input | No | *(none)* |
   | 2 | Specific Subfolders | Folder | Optional | Input | **Yes** | *(none)* |
   | 3 | Search All Nested Subfolders | Boolean | Optional | Input | No | Checked |
   | 4 | Group Loaded Tiles Into a Layer Group | Boolean | Optional | Input | No | Checked |
   | 5 | Group Layer Name | String | Optional | Input | No | `DGED Tiles` |
   | 6 | Build Pyramids After Loading | Boolean | Optional | Input | No | Unchecked |

   To set MultiValue on row 2: select the row, and either check its
   **MultiValue** column cell or open the parameter's Properties and set
   **MultiValue = Yes** (the exact control varies slightly by Pro build,
   but every 3.x version exposes this per parameter).

   To set a default: click the **Default** cell for that row -- a
   checkbox for Boolean rows, a text box for the String row.

5. Click **OK** / finish the wizard to save the tool.

6. Keep `DGED_Load_Tool_script.py` in this same folder going forward.
   Depending on your settings, Pro either embeds a copy of the script
   into the `.atbx` or keeps a live link to this file -- keeping the
   source here works either way.

7. **Test it:** open a map, double-click **Load DGED Tiles** in your new
   toolbox, set a folder, and run. You should see the same messages and
   progress bar as `DGED_Loader.pyt` produces, because it's the same
   logic.

## If something doesn't validate

- **Parameters appear in the wrong order:** the script matches
  parameters by position, not name -- drag the rows in the Parameters
  grid back into the order in the table above.
- **"No active map" when you run it:** open a map view first; the script
  needs `arcpy.mp.ArcGISProject("CURRENT").activeMap`, which only
  resolves when a map is open and the tool runs in the foreground (see
  step 3's background-process note).
- **Still doesn't work:** fall back to `DGED_Loader.pyt` -- it's the
  same tool, needs no wizard, and is what this guide's script was
  derived from.
