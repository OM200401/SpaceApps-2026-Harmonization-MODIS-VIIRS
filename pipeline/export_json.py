#!/usr/bin/env python3
"""monthly_harmonized.parquet -> app/data/monthly.json (region series + cell-month rows, compact)."""
import argparse, json
from pathlib import Path
import pandas as pd
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--monthly", required=True); ap.add_argument("--out", default="app/data/monthly.json"); a = ap.parse_args()
    m = pd.read_parquet(a.monthly)
    region = m.groupby(["year", "month"], as_index=False).agg(modis=("modis_count", "sum"), viirs=("viirs_count", "sum"), total=("total_count", "sum"), harmonized=("harmonized_count", "sum"), mean_frp=("mean_frp", "mean"))
    payload = {"region_monthly": region.round(2).to_dict("records"),
               "cells": m[["cell_lat", "cell_lon", "year", "month", "modis_count", "viirs_count", "total_count", "mean_frp", "harmonized_count"]].round(2).to_dict("records")}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(payload))
    print(f"Wrote {a.out}: {len(payload['cells']):,} cell-months, {len(payload['region_monthly'])} region-months, {Path(a.out).stat().st_size/1e6:.2f} MB")
