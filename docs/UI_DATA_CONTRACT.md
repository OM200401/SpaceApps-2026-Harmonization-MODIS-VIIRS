# UI data contract — for the pipeline (Codex) — UI reads ONLY this file
Path: app/data/monthly.json  (regenerate with pipeline/export_json.py, or any code that matches this shape)

{
  "region_monthly": [ {"year":2023,"month":5,"modis":132,"viirs":414,"total":546,"harmonized":752.1,"mean_frp":20.5}, ... ],
  "cells": [ {"cell_lat":50.0,"cell_lon":-110.25,"year":2023,"month":5,"modis_count":3,"viirs_count":9,"total_count":12,"mean_frp":24.1,"harmonized_count":9.0}, ... ]
}

Rules:
- harmonized_count must be FILLED (calibration applied) — null/NaN breaks the heatmap, map, and stat cards.
- cells grid = 0.25 degrees, cell_lat/cell_lon = cell's south-west corner (floor to grid).
- Years: MODIS era from 2000/2001 through 2025; months 1-12; missing month = omit the row (UI shows "·").
- total_count = modis_count + viirs_count (raw, uncorrected) — the Raw view and the 2012-jump card depend on it.
- Keep the file under ~5 MB: Canada-slice cell-months at 0.25° is fine; if it balloons, drop mean_frp from cells, never drop harmonized_count.
Current app/data/monthly.json is SYNTHETIC test data — replace it wholesale with the real export; no UI code changes needed.
