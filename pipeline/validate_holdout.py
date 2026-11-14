#!/usr/bin/env python3
"""Holdout validation (v3): ratios learned on calib years predict holdout-year S-NPP counts
from MODIS detections alone (same per-detection weights as calibrate.py).
Reports region-month MAPE + bias (what the calendar shows), per-stratum error,
and raw vs harmonized 2011->2012 jump.
Usage: python validate_holdout.py --cleaned data/cleaned_canada.parquet --monthly data/monthly_harmonized.parquet
"""
import argparse
import pandas as pd
from calibrate import compute_ratios_from_cleaned, modis_weights, add_strata, STRATA

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--cleaned", required=True); ap.add_argument("--monthly", required=True)
    ap.add_argument("--calib", default="2012-2020"); ap.add_argument("--holdout", default="2021-2023"); a = ap.parse_args()
    cy = tuple(int(x) for x in a.calib.split("-")); hy = tuple(int(x) for x in a.holdout.split("-"))
    c = pd.read_parquet(a.cleaned)
    c = c[pd.to_datetime(c["acq_date"]).dt.year.between(*cy) | pd.to_datetime(c["acq_date"]).dt.year.between(*hy)]
    ratios, gr = compute_ratios_from_cleaned(c, cy)

    hold = c[pd.to_datetime(c["acq_date"]).dt.year.between(*hy)]
    pred = modis_weights(hold, ratios, gr)
    actual = add_strata(hold)
    actual = actual[actual["is_viirs"] == 1]
    keys = ["year", "month"] + STRATA

    # 1. Region-month totals: does the calendar tell the same story?
    pm = pred.groupby(["year", "month"])["weight"].sum().rename("pred")
    am = actual.groupby(["year", "month"]).size().rename("actual")
    m = pd.concat([pm, am], axis=1).fillna(0); m = m[m["actual"] > 0]
    m["ape"] = (m["pred"] - m["actual"]).abs() / m["actual"]; m["bias"] = (m["pred"] - m["actual"]) / m["actual"]
    print(f"Holdout {hy[0]}-{hy[1]} (calib {cy[0]}-{cy[1]}), region-months={len(m)}")
    print(f"REGION-MONTH MAPE={m['ape'].mean():.3f} bias={m['bias'].mean():+.3f}  (fire season only: "
          f"MAPE={m[m.index.get_level_values('month').isin(range(5, 10))]['ape'].mean():.3f})")
    top_p = set(m["pred"].nlargest(5).index); top_a = set(m["actual"].nlargest(5).index)
    print(f"top-5 busiest months matching: {len(top_p & top_a)}/5")

    # 2. Per stratum
    ps = pred.groupby(keys)["weight"].sum().rename("pred")
    as_ = actual.groupby(keys).size().rename("actual")
    s = pd.concat([ps, as_], axis=1).fillna(0); s = s[s["actual"] > 0].reset_index()
    s["ape"] = (s["pred"] - s["actual"]).abs() / s["actual"]; s["bias"] = (s["pred"] - s["actual"]) / s["actual"]
    print(s.groupby(STRATA).agg(n=("ape", "size"), MAPE=("ape", "mean"), bias=("bias", "mean")).round(3).to_string())

    # 3. The 2012 seam
    mo = pd.read_parquet(a.monthly); t = mo.groupby("year").agg(raw=("total_count", "sum"), harm=("harmonized_count", "sum"))
    try:
        print(f"Raw 2011->2012 jump: {(t.loc[2012,'raw']-t.loc[2011,'raw'])/t.loc[2011,'raw']:+.1%}")
        print(f"Harmonized 2011->2012 jump: {(t.loc[2012,'harm']-t.loc[2011,'harm'])/t.loc[2011,'harm']:+.1%}")
    except KeyError: pass
