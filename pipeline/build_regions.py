#!/usr/bin/env python3
"""Harmonize every app preset region with its own S-NPP/MODIS ratios.

One pass over the 0.25° grid builds each region's staging rows plus worldwide totals.
Each region gets ratios from its own 2012-2020 overlap; a stratum with fewer than
MIN_MODIS MODIS detections uses the global ratio for that stratum instead.
Outputs data/regions/<name>_*.parquet, data/monthly_harmonized_all.parquet (all regions,
input for export_json.py) and data/calibration_regions.json; prints per-region holdout.

Usage: python pipeline/build_regions.py
       python pipeline/export_json.py --monthly data/monthly_harmonized_all.parquet
"""
import argparse, json
from pathlib import Path
import pandas as pd
from build_monthly_from_grid import grid_rows, build
from grid_calibrate import STRATA, MIN_MODIS, ratios, converted, harmonize
from grid_validate import holdout, top5

# W, S, E, N. Must cover the app presets; "Canada core fires" is inside "canada".
REGIONS = {
    "canada": (-140.0, 42.0, -52.0, 72.0),
    "amazon": (-75.0, -15.0, -45.0, 5.0),
    "mediterranean": (-10.0, 35.0, 30.0, 45.0),
}


def jump(m, col):
    y = m.groupby("year")[col].sum()
    return y.loc[2012] / y.loc[2011] - 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/derived/monthly_grid_025.parquet")
    ap.add_argument("--outdir", default="data/regions")
    ap.add_argument("--out", default="data/monthly_harmonized_all.parquet")
    ap.add_argument("--calibration-out", default="data/calibration_regions.json")
    a = ap.parse_args()

    raw, read_rows, kept_rows, world = grid_rows(a.input, REGIONS, global_totals=True)
    print(f"source rows read: {read_rows:,}; kept for regions: {kept_rows:,}")
    global_r = ratios(world)
    out_dir = Path(a.outdir); out_dir.mkdir(parents=True, exist_ok=True)
    calib = {"reference": "SNPP only", "calib_years": [2012, 2020], "holdout_years": [2021, 2023],
             "min_modis_hotspots": MIN_MODIS, "global": global_r.round(6).to_dict("records"), "regions": {}}
    harmonized, summary = [], []
    for name, bbox in REGIONS.items():
        s, monthly = build(raw[name])
        r = ratios(s, fallback=global_r)
        m = harmonize(s, converted(s, r), monthly)
        m = m.drop(columns=["modis_converted", "snpp_observed"])
        s.to_parquet(out_dir / f"{name}_staging.parquet", index=False)
        m.to_parquet(out_dir / f"{name}_harmonized.parquet", index=False)
        harmonized.append(m.assign(region=name))
        allm, x, _, _ = holdout(s, r)
        _, _, hits = top5(allm)
        calib["regions"][name] = {"bbox": bbox, "strata": r.round(6).to_dict("records")}
        summary.append({"region": name, "cells": m.cell_id.nunique(),
                        "modis_2012_20": int(r.modis.sum()), "fallback_strata": int(r.fallback.sum()),
                        "MAPE": round(x.ape.mean(), 4), "bias": round(x.bias.mean(), 4), "n": len(x),
                        "top5": f"{hits}/5", "raw_jump": f"{jump(m, 'total_count'):+.1%}",
                        "harm_jump": f"{jump(m, 'harmonized_count'):+.1%}"})
        print(f"\n== {name} {bbox}")
        print(r[[*STRATA, "modis", "terra", "snpp", "ratio", "ratio_terra", "fallback"]].round(3).to_string(index=False))

    print("\n== global fallback ratios")
    print(global_r[[*STRATA, "modis", "snpp", "ratio", "ratio_terra"]].round(3).to_string(index=False))
    all_m = pd.concat(harmonized, ignore_index=True)
    assert not all_m.duplicated(["cell_id", "year", "month"]).any(), "regions overlap"
    all_m.to_parquet(a.out, index=False)
    Path(a.calibration_out).write_text(json.dumps(calib, indent=2))
    print("\n== per-region holdout (calibrate 2012-2020, predict S-NPP 2021-2023 from MODIS)")
    print(pd.DataFrame(summary).to_string(index=False))
    print(f"Wrote {a.out} ({len(all_m):,} rows) and {a.calibration_out}")


if __name__ == "__main__":
    main()
