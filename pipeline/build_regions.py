#!/usr/bin/env python3
"""Harmonize every app preset region; this is the production calibration path.

One pass over the 0.25° grid builds each region's staging rows plus worldwide totals.
Each region is harmonized with the optimised rule (grid_calibrate.fit_rule, issue #37), fitted
on its own overlap from Feb 2012 through 2025: 1-degree block ratios shrunk toward the region
ratio, blended 50/50 with the same estimate rescaled by a monthly region power law. A region
stratum with fewer than MIN_MODIS MODIS detections uses the global ratio for that stratum.
Outputs data/regions/<name>_*.parquet (incl. block ratios), data/monthly_harmonized_all.parquet
(all regions, input for the all-region export), data/monthly_harmonized.parquet (APP_REGION only)
and data/calibration_regions.json. Prints the 2021-2023 holdout for the new rule next to the old
single-ratio rule (own and global ratios), so the two can be compared directly.

Usage: python pipeline/build_regions.py
       python pipeline/export_json.py --monthly data/monthly_harmonized_all.parquet
"""
import argparse, json
from pathlib import Path
import pandas as pd
from build_monthly_from_grid import grid_rows, build
from grid_calibrate import (STRATA, MIN_MODIS, FIT_START, FIT_END_YEAR, ratios, harmonize,
                            fit_rule, converted_rule, rule_summary)
from grid_validate import holdout, holdout_rule, top5

# W, S, E, N. Must cover the app presets; "Canada core fires" is inside "canada".
REGIONS = {
    "canada": (-140.0, 42.0, -52.0, 72.0),
    "amazon": (-75.0, -15.0, -45.0, 5.0),
    "mediterranean": (-10.0, 35.0, 30.0, 45.0),
}
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
    global_r = ratios(world)  # 2012-2020, for the holdout and the old-rule comparison
    w_fit = world[world.year * 100 + world.month >= FIT_START[0] * 100 + FIT_START[1]]
    global_fit = ratios(w_fit, years=(FIT_START[0], FIT_END_YEAR))  # same window as the shipped fit
    out_dir = Path(a.outdir); out_dir.mkdir(parents=True, exist_ok=True)
    calib = {"reference": "SNPP only", "rule": "block ratio + monthly power law (issue #37)",
             "holdout_fit": [2012, 2020], "holdout_years": [2021, 2023],
             "min_modis_hotspots": MIN_MODIS, "global": global_fit.round(6).to_dict("records"),  # fallback used by the shipped fit
             "global_holdout": global_r.round(6).to_dict("records"),  # fallback used by the 2012-2020 holdout
             "regions": {}}
    harmonized, summary = [], []
    for name, bbox in REGIONS.items():
        s, monthly = build(raw[name])
        rule = fit_rule(s, fallback=global_fit)  # thin strata fall back to global ratios, as before
        m = harmonize(s, converted_rule(s, rule), monthly)
        m = m.drop(columns=["modis_converted", "snpp_observed"])
        s.to_parquet(out_dir / f"{name}_staging.parquet", index=False)
        m.to_parquet(out_dir / f"{name}_harmonized.parquet", index=False)
        rule["blocks"].to_parquet(out_dir / f"{name}_block_ratios.parquet", index=False)
        harmonized.append(m.assign(region=name))
        if name == APP_REGION:
            m.to_parquet(a.app_out, index=False)
        allm, x, _, _ = holdout(s, holdout_rule(s, fallback=global_r))
        _, _, hits = top5(allm)
        old_own, old_glb = holdout(s, ratios(s, fallback=global_r))[1], holdout(s, global_r)[1]
        calib["regions"][name] = {"bbox": bbox, **rule_summary(rule)}
        summary.append({"region": name, "cells": m.cell_id.nunique(), "blocks": len(rule["blocks"]),
                        "MAPE_old_own": round(old_own.ape.mean(), 4), "MAPE_old_global": round(old_glb.ape.mean(), 4),
                        "MAPE": round(x.ape.mean(), 4), "WAPE": round((x.pred - x.actual).abs().sum() / x.actual.sum(), 4),
                        "bias": round(x.bias.mean(), 4), "n": len(x),
                        "top5": f"{hits}/5", "raw_jump": f"{jump(m, 'total_count'):+.1%}",
                        "harm_jump": f"{jump(m, 'harmonized_count'):+.1%}"})
        print(f"\n== {name} {bbox}: region ratios (Feb 2012-2025) and monthly power law")
        print(rule["region"][[*STRATA, "modis", "terra", "snpp", "ratio", "ratio_terra", "fallback"]].round(3).to_string(index=False))
        print(rule["power_law"][["month", "daynight", "a", "b", "smear", "n_months"]].round(3).to_string(index=False))

    print("\n== global fallback ratios")
    print(global_fit[[*STRATA, "modis", "snpp", "ratio", "ratio_terra"]].round(3).to_string(index=False))
    all_m = pd.concat(harmonized, ignore_index=True)
    assert not all_m.duplicated(["cell_id", "year", "month"]).any(), "regions overlap"
    all_m.to_parquet(a.out, index=False)
    Path(a.calibration_out).write_text(json.dumps(calib, indent=2))
    print("\n== per-region holdout (fit 2012-2020, predict S-NPP 2021-2023 from MODIS); MAPE = new rule")
    print(pd.DataFrame(summary).to_string(index=False))
    print(f"Wrote {a.out} ({len(all_m):,} rows) and {a.calibration_out}")


if __name__ == "__main__":
    main()
