#!/usr/bin/env python3
"""Holdout validation (v2): ratios learned on calib years from cleaned detections predict
VIIRS region-month-stratum counts in holdout years from MODIS counts alone.
Reports per-stratum MAPE + bias, and raw vs harmonized 2011->2012 jump (monthly file).
Usage: python3 validate_holdout.py --cleaned data/cleaned_canada.parquet --monthly data/monthly_harmonized.parquet
"""
import argparse
import pandas as pd
from calibrate import compute_ratios_from_cleaned, frp_bin, season

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--cleaned", required=True); ap.add_argument("--monthly", required=True)
    ap.add_argument("--calib", default="2012-2020"); ap.add_argument("--holdout", default="2021-2023"); a = ap.parse_args()
    cy = tuple(int(x) for x in a.calib.split("-")); hy = tuple(int(x) for x in a.holdout.split("-"))
    c = pd.read_parquet(a.cleaned); ratios, gr = compute_ratios_from_cleaned(c, cy)
    rmap = {(r.frp_bin, r.season): r.ratio for r in ratios.itertuples()}
    d = c.copy(); d["year"] = pd.to_datetime(d["acq_date"]).dt.year; d["month"] = pd.to_datetime(d["acq_date"]).dt.month
    d = d[(d["year"] >= hy[0]) & (d["year"] <= hy[1])]
    d["frp_bin"] = d["frp"].apply(frp_bin); d["season"] = d["month"].apply(season)
    d["is_modis"] = (d["sensor"] == "MODIS").astype(int); d["is_viirs"] = d["sensor"].str.startswith("VIIRS").astype(int)
    g = d.groupby(["year", "month", "frp_bin", "season"], as_index=False).agg(modis=("is_modis", "sum"), viirs=("is_viirs", "sum"))
    g = g[(g["modis"] > 0) & (g["viirs"] > 0)]
    g["pred"] = [mo * rmap.get((b, s), gr) for mo, b, s in zip(g["modis"], g["frp_bin"], g["season"])]
    g["ape"] = (g["pred"] - g["viirs"]).abs() / g["viirs"]; g["bias"] = (g["pred"] - g["viirs"]) / g["viirs"]
    print(f"Holdout {hy[0]}-{hy[1]} (calib {cy[0]}-{cy[1]}), n month-strata={len(g)}")
    print(g.groupby(["frp_bin", "season"]).agg(n=("ape", "size"), MAPE=("ape", "mean"), bias=("bias", "mean")).round(3).to_string())
    print(f"OVERALL MAPE={g['ape'].mean():.3f} bias={g['bias'].mean():+.3f}")
    m = pd.read_parquet(a.monthly); t = m.groupby("year").agg(raw=("total_count", "sum"), harm=("harmonized_count", "sum"))
    try:
        print(f"Raw 2011->2012 jump: {(t.loc[2012,'raw']-t.loc[2011,'raw'])/t.loc[2011,'raw']:+.1%}")
        print(f"Harmonized 2011->2012 jump: {(t.loc[2012,'harm']-t.loc[2011,'harm'])/t.loc[2011,'harm']:+.1%}")
    except KeyError: pass
