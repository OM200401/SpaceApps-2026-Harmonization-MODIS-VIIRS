# UI data contract — what the web app reads

The app loads `app/data/index.json` first, then only the tiles an area needs.
The tiles are not in git. They are a zip on a release (`tiles-v2`); `python pipeline/fetch_tiles.py` unpacks
it into `app/data/`, and the Pages workflow (`.github/workflows/pages.yml`) does the same before deploying.
Regenerate everything with:

    python pipeline/build_global.py      # harmonize the whole world -> data/monthly_harmonized_global.parquet
    python pipeline/build_global_v2.py   # v2 rule (needs experiments/v2 outputs) -> data/monthly_harmonized_global_v2.parquet
    python pipeline/export_tiles.py --monthly data/monthly_harmonized_global_v2.parquet
                                         # -> app/data/index.json, app/data/d/*.json, app/data/c/*.json

then zip `index.json`, `c/` and `d/`, upload the zip to a new release, and set `TILES_TAG` in fetch_tiles.py.

index.json:
{
  "t0_year": 2000,
  "levels": {"d": {"cell": 0.25, "tile": 10}, "c": {"cell": 1.0, "tile": 30}},
  "tiles": {"d": {"40_-130": [cell_months, bytes], ...}, "c": {...}},   key = tile's south-west corner "lat_lon"
  "end": {"year": 2026, "month": 10},                                    last month with data
  "archive_end": {...}, "provisional_from": {"year": 2026, "month": 8}
}

Tiles: `app/data/d/<lat>_<lon>.json` holds 0.25-degree cells of one 10x10-degree tile;
`app/data/c/<lat>_<lon>.json` holds 1-degree cells (sums of 16 detail cells) of one 30x30-degree tile.
Each tile is a `cells` block in the layout below. The app uses detail tiles unless the tiles an area
touches hold more than 700,000 cell-months; then it switches to 1-degree cells (shared.js DETAIL_MAX).
harmonized_count is rounded to 1 dp in tiles.

---
Cells block layout (also the shape of the old single-file app/data/monthly.json, kept for reference):

{
  "region_monthly": [ {"year":2023,"month":5,"modis":132,"viirs":414,"total":546,"harmonized":752.1,"mean_frp":20.5}, ... ],
  "cells": {
    "t0_year": 2000,
    "cell_lat": [42.0, 42.0, ...],      one entry per grid cell
    "cell_lon": [-124.5, -124.25, ...],
    "n_months": [17, 4, ...],           how many cell-months belong to that cell
    "t":                [11, 21, ...],  one entry per cell-month, grouped by cell in the order above
    "modis_count":      [3, 4, ...],
    "viirs_count":      [0, 0, ...],
    "harmonized_count": [4.78, 6.37, ...]
  },
  "archive_end": {"Terra": "2026-08-31", "Aqua": "2026-08-31", "SNPP": "2026-07-31"},
  "provisional_from": {"year": 2026, "month": 8}
}

Decoding: walk the cells in order; cell k owns the next n_months[k] entries of t / modis_count /
viirs_count / harmonized_count. year = t0_year + floor(t / 12), month = t % 12 + 1.
The UI decodes this in decodeCells() (app/index.html) back into one object per cell-month.

Rules:
- harmonized_count must be FILLED (calibration applied) — null/NaN breaks the heatmap, map, and stat cards. Rounded to 2 dp.
- cells grid = 0.25 degrees, cell_lat/cell_lon = cell's south-west corner (floor to grid).
- Years: MODIS era from 2000/2001 through 2026; months 1-12; missing month = omit the entry (UI shows "·").
- total_count is not stored: the UI derives it as modis_count + viirs_count (raw, uncorrected) — the Raw view and the 2012-jump card depend on it.
- mean_frp is not stored per cell (only in region_monthly), to keep the file small.
- archive_end = last standard-processing (archive) date per satellite; later data is near-real-time. provisional_from = the first month containing any near-real-time day (earliest archive_end + 1 day). The UI marks that month and every later one "provisional". Update ARCHIVE_END in export_json.py whenever the grid is rebuilt.
- Keep the file under 5 MB (check_outputs.py json enforces it). Write JSON with compact separators.
