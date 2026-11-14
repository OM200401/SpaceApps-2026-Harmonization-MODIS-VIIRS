#!/usr/bin/env python3
"""monthly_harmonized.parquet -> app/data/monthly.json (region series + cell-month columns, compact).
Cells are column arrays grouped by cell: cell_lat/cell_lon/n_months have one entry per cell, and the
next n_months entries of t/modis_count/viirs_count/harmonized_count belong to it. Month index
t = (year - t0_year) * 12 + (month - 1). total_count = modis_count + viirs_count. See docs/UI_DATA_CONTRACT.md."""
import argparse, json
from pathlib import Path
import pandas as pd
T0_YEAR = 2000
# Last standard-processing (archive) date per satellite in the FIRMS data behind data-v2. Later detections
# are near-real-time (NRT) and get replaced when NASA reprocesses them, so the app marks those months
# provisional. data-v2 has no source column: these dates were read from the raw Hugging Face files
# (max acq_date where source = 'archive') and must be updated whenever the grid is rebuilt.
ARCHIVE_END = {"Terra": "2026-08-31", "Aqua": "2026-08-31", "SNPP": "2026-07-31"}
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--monthly", required=True); ap.add_argument("--out", default="app/data/monthly.json"); a = ap.parse_args()
    m = pd.read_parquet(a.monthly)
    region = m.groupby(["year", "month"], as_index=False).agg(modis=("modis_count", "sum"), viirs=("viirs_count", "sum"), total=("total_count", "sum"), harmonized=("harmonized_count", "sum"), mean_frp=("mean_frp", "mean"))
    m = m.sort_values(["cell_lat", "cell_lon", "year", "month"])
    per_cell = m.groupby(["cell_lat", "cell_lon"], sort=False).size().reset_index(name="n_months")
    cells = {"t0_year": T0_YEAR,
             "cell_lat": per_cell["cell_lat"].round(4).tolist(), "cell_lon": per_cell["cell_lon"].round(4).tolist(), "n_months": per_cell["n_months"].tolist(),
             "t": ((m["year"] - T0_YEAR) * 12 + m["month"] - 1).tolist(),
             "modis_count": m["modis_count"].tolist(), "viirs_count": m["viirs_count"].tolist(), "harmonized_count": m["harmonized_count"].round(2).tolist()}
    first_nrt = pd.Timestamp(min(ARCHIVE_END.values())) + pd.Timedelta(days=1)  # first month containing any NRT day
    payload = {"region_monthly": region.round(2).to_dict("records"), "cells": cells,
               "archive_end": ARCHIVE_END, "provisional_from": {"year": first_nrt.year, "month": first_nrt.month}}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(payload, separators=(",", ":")))
    print(f"Wrote {a.out}: {len(cells['t']):,} cell-months in {len(cells['n_months']):,} cells, {len(payload['region_monthly'])} region-months, {Path(a.out).stat().st_size/1e6:.2f} MB; provisional from {first_nrt:%Y-%m}")
