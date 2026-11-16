#!/usr/bin/env python3
"""Harmonize the whole world with the optimised rule (issue #37).

The three validated regions (Canada, Amazon, Mediterranean) keep exactly their own fit, as in
build_regions.py. Every other 0.25-degree cell belongs to a 30x30-degree calibration box, and each box
is fitted the same way on its own Feb 2012-2025 overlap: 1-degree block ratios shrunk toward the box
ratio, blended 50/50 with the monthly power law. Thin strata fall back to global ratios.
Each box also gets the 2021-2023 holdout (fit 2012-2020) so accuracy can be reported worldwide.

Outputs data/monthly_harmonized_global.parquet (one row per cell-month, with its calibration region)
and data/calibration_global.json (per-region rule summary and holdout scores).

Usage: python pipeline/build_global.py
       python pipeline/export_tiles.py
"""
import argparse, json, time
from pathlib import Path
import duckdb
import pandas as pd
from build_monthly_from_grid import build
from build_regions import REGIONS
from grid_calibrate import FIT_START, FIT_END_YEAR, ratios, harmonize, fit_rule, converted_rule, rule_summary
from grid_validate import holdout, holdout_rule, top5

BOX_DEG = 30


def region_sql():
    """SQL CASE assigning each cell to a validated region (same inclusive bounds as grid_rows) or a box."""
    named = " ".join(f"WHEN cell_lon BETWEEN {w} AND {e} AND cell_lat BETWEEN {s} AND {n} THEN '{k}'"
                     for k, (w, s, e, n) in REGIONS.items())
    box = (f"'box_' || CAST(CAST(floor(cell_lat / {BOX_DEG}) * {BOX_DEG} AS INT) AS VARCHAR) || '_' || "
           f"CAST(CAST(floor(cell_lon / {BOX_DEG}) * {BOX_DEG} AS INT) AS VARCHAR)")
    return f"CASE {named} ELSE {box} END"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/derived/monthly_grid_025.parquet")
    ap.add_argument("--staging", default="data/tmp/global_staging.parquet")
    ap.add_argument("--out", default="data/monthly_harmonized_global.parquet")
    ap.add_argument("--calibration-out", default="data/calibration_global.json")
    a = ap.parse_args()
    t0 = time.time()
    con = duckdb.connect()
    Path(a.staging).parent.mkdir(parents=True, exist_ok=True)
    # Same filters as grid_rows: vegetation fires, nominal/high confidence, Terra/Aqua/S-NPP only.
    con.execute(f"""COPY (SELECT {region_sql()} AS region, cell_lat, cell_lon, year, month, satellite, daynight,
                         sum(hotspots) AS hotspots, sum(frp_sum) AS frp_sum
                  FROM '{a.input}'
                  WHERE is_vegetation AND confidence IN ('n','h') AND satellite IN ('Terra','Aqua','SNPP')
                  GROUP BY ALL) TO '{a.staging}' (FORMAT parquet)""")
    world = con.execute(f"SELECT year, month, satellite, daynight, sum(hotspots) AS hotspots, sum(frp_sum) AS frp_sum "
                        f"FROM '{a.staging}' GROUP BY ALL").df()
    world["sensor"] = world.satellite.map({"Terra": "MODIS", "Aqua": "MODIS", "SNPP": "VIIRS_SNPP"})
    world["mean_frp"] = world.frp_sum / world.hotspots
    global_r = ratios(world)
    w_fit = world[world.year * 100 + world.month >= FIT_START[0] * 100 + FIT_START[1]]
    global_fit = ratios(w_fit, years=(FIT_START[0], FIT_END_YEAR))
    sizes = con.execute(f"SELECT region, count(*) n FROM '{a.staging}' GROUP BY 1 ORDER BY n DESC").df()
    print(f"staging built in {time.time()-t0:.0f}s: {sizes.n.sum():,} rows in {len(sizes)} calibration regions")

    out, calib, summary = [], {"rule": "block ratio + monthly power law (issue #37)", "box_deg": BOX_DEG,
                               "validated_regions": {k: v for k, v in REGIONS.items()},
                               "holdout_fit": [2012, 2020], "holdout_years": [2021, 2023],
                               "global": global_fit.round(6).to_dict("records"), "regions": {}}, []
    for region in sizes.region:
        raw = con.execute(f"SELECT cell_lat, cell_lon, year, month, satellite, daynight, hotspots, frp_sum "
                          f"FROM '{a.staging}' WHERE region = ?", [region]).df()
        s, monthly = build(raw)
        rule = fit_rule(s, fallback=global_fit)
        m = harmonize(s, converted_rule(s, rule), monthly).drop(columns=["modis_converted", "snpp_observed"])
        out.append(m.assign(region=region))
        row = {"region": region, "cells": m.cell_id.nunique(), "cell_months": len(m), "modis": int(m.modis_count.sum())}
        try:  # holdout needs S-NPP months in 2021-2023; tiny boxes may have none
            allm, x, _, _ = holdout(s, holdout_rule(s, fallback=global_r))
            if len(x):
                row.update(MAPE=round(x.ape.mean(), 4), WAPE=round((x.pred - x.actual).abs().sum() / x.actual.sum(), 4),
                           bias=round(x.bias.mean(), 4), n=len(x), top5=f"{top5(allm)[2]}/5")
        except Exception as e:  # noqa: BLE001 - record and continue; the fit itself succeeded
            row["holdout_error"] = str(e)[:80]
        calib["regions"][region] = {**{k: v for k, v in row.items() if k != "region"}, **rule_summary(rule)}
        summary.append(row)
        print(f"{region:>16} {row['cell_months']:>9,} cell-months  MAPE={row.get('MAPE', '–')}  ({time.time()-t0:.0f}s)", flush=True)

    allm = pd.concat(out, ignore_index=True)
    assert not allm.duplicated(["cell_id", "year", "month"]).any(), "a cell landed in two regions"
    allm.to_parquet(a.out, index=False)
    Path(a.calibration_out).write_text(json.dumps(calib, indent=1, default=float))
    df = pd.DataFrame(summary)
    print("\n== holdout by calibration region (fit 2012-2020, predict S-NPP 2021-2023 from MODIS)")
    print(df.to_string(index=False))
    w = df.dropna(subset=["MAPE"])
    print(f"\nMODIS-weighted MAPE over {len(w)} regions: {(w.MAPE * w.modis).sum() / w.modis.sum():.4f}")
    print(f"Wrote {a.out} ({len(allm):,} rows, {allm.cell_id.nunique():,} cells) in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
