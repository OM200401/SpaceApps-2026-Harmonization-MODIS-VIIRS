#!/usr/bin/env python3
"""Harmonize every app preset region; this is the production calibration path.

One pass over the 0.25° grid builds each region's staging rows plus worldwide totals.
Each region gets ratios from its own 2012-2020 overlap (a stratum with fewer than
MIN_MODIS MODIS detections uses the global ratio for that stratum), unless
RATIO_SOURCE ships it with the global ratios because they score better in the holdout.
Outputs data/regions/<name>_*.parquet, data/monthly_harmonized_all.parquet (all regions,
input for the all-region export), data/monthly_harmonized.parquet (APP_REGION only, as before)
and data/calibration_regions.json; prints per-region holdout for own, global and shipped ratios.

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
# Which ratios each region ships with, picked by holdout MAPE: Canada scores 16.9% with
# global ratios vs 19.5% with its own (see docs/VALIDATION.md). Default is "own".
RATIO_SOURCE = {"canada": "global"}
APP_REGION = "canada"  # also written to data/monthly_harmonized.parquet, the app export input


def jump(m, col):
    y = m.groupby("year")[col].sum()
    return y.loc[2012] / y.loc[2011] - 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/derived/monthly_grid_025.parquet")
    ap.add_argument("--outdir", default="data/regions")
    ap.add_argument("--out", default="data/monthly_harmonized_all.parquet")
    ap.add_argument("--calibration-out", default="data/calibration_regions.json")
    ap.add_argument("--app-out", default="data/monthly_harmonized.parquet")
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
        own = ratios(s, fallback=global_r)
        source = RATIO_SOURCE.get(name, "own")
        r = global_r if source == "global" else own
        m = harmonize(s, converted(s, r), monthly)
        m = m.drop(columns=["modis_converted", "snpp_observed"])
        s.to_parquet(out_dir / f"{name}_staging.parquet", index=False)
        m.to_parquet(out_dir / f"{name}_harmonized.parquet", index=False)
        harmonized.append(m.assign(region=name))
        if name == APP_REGION:
            m.to_parquet(a.app_out, index=False)
        allm, x, _, _ = holdout(s, r)
        _, _, hits = top5(allm)
        mape_own = holdout(s, own)[1].ape.mean(); mape_global = holdout(s, global_r)[1].ape.mean()
        calib["regions"][name] = {"bbox": bbox, "ratio_source": source,
                                  "strata": r.round(6).to_dict("records"), "own_strata": own.round(6).to_dict("records")}
        summary.append({"region": name, "ratios": source, "cells": m.cell_id.nunique(),
                        "modis_2012_20": int(own.modis.sum()), "fallback_strata": int(own.fallback.sum()),
                        "MAPE_own": round(mape_own, 4), "MAPE_global": round(mape_global, 4),
                        "MAPE": round(x.ape.mean(), 4), "bias": round(x.bias.mean(), 4), "n": len(x),
                        "top5": f"{hits}/5", "raw_jump": f"{jump(m, 'total_count'):+.1%}",
                        "harm_jump": f"{jump(m, 'harmonized_count'):+.1%}"})
        print(f"\n== {name} {bbox}: own ratios (shipping {source})")
        print(own[[*STRATA, "modis", "terra", "snpp", "ratio", "ratio_terra", "fallback"]].round(3).to_string(index=False))

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
