# UI data contract — for the pipeline (Codex) — UI reads ONLY this file
Path: app/data/monthly.json  (regenerate with pipeline/export_json.py, or any code that matches this shape)

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
  }
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
- Keep the file under 5 MB (check_outputs.py json enforces it). Write JSON with compact separators.
