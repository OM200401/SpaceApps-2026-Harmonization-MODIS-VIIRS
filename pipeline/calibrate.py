#!/usr/bin/env python3
"""
calibrate.py -- stratified VIIRS/MODIS ratios from the overlap, fill harmonized_count.
Method (v2, fixed 2026-11-14): ratios are computed from CLEANED DETECTIONS aggregated
over the whole region per stratum (FRP bin x season), NOT per grid cell. Per-cell
intersection is too sparse - MODIS and VIIRS rarely hit the same 0.25deg cell-month
with the same mean-FRP bin, which collapsed v1 ratios to 1.0 on synthetic tests.
Strata: FRP bin of the individual detection (0-10, 10-30, 30-100, 100+ MW) x season
(fire May-Sep vs off). Reference sensor = VIIRS.
Monthly application: a MODIS-only cell-month gets ratio of its (mean_frp bin, season);
VIIRS-present cell-months keep viirs_count as harmonized (observed, reference sensor).
Usage: python3 calibrate.py --cleaned data/cleaned_canada.parquet --monthly data/monthly.parquet \
  --out data/monthly_harmonized.parquet --calibration-out data/calibration.json [--calib-years 2012-2020]
"""
import argparse, json
from pathlib import Path
import pandas as pd

def frp_bin(f):
    if pd.isna(f): return "unknown"
    if f < 10: return "0-10"
    if f < 30: return "10-30"
    if f < 100: return "30-100"
    return "100+"
def season(m): return "fire" if 5 <= m <= 9 else "off"

def compute_ratios_from_cleaned(cleaned, calib_years):
    d = cleaned.copy()
    d["year"] = pd.to_datetime(d["acq_date"]).dt.year; d["month"] = pd.to_datetime(d["acq_date"]).dt.month
    d = d[(d["year"] >= calib_years[0]) & (d["year"] <= calib_years[1])]
    d["frp_bin"] = d["frp"].apply(frp_bin); d["season"] = d["month"].apply(season)
    d["is_modis"] = (d["sensor"] == "MODIS").astype(int); d["is_viirs"] = d["sensor"].str.startswith("VIIRS").astype(int)
    g = d.groupby(["frp_bin", "season"], as_index=False).agg(modis=("is_modis", "sum"), viirs=("is_viirs", "sum"))
    g = g[(g["modis"] > 0) & (g["viirs"] > 0)]; g["ratio"] = g["viirs"] / g["modis"]
    global_ratio = g["viirs"].sum() / g["modis"].sum() if g["modis"].sum() else 1.0
    return g, global_ratio

def apply_ratios(monthly, ratios, global_ratio):
    d = monthly.copy()
    d["frp_bin"] = d["mean_frp"].apply(frp_bin); d["season"] = d["month"].apply(season)
    rmap = {(r.frp_bin, r.season): r.ratio for r in ratios.itertuples()}
    d["ratio_applied"] = [rmap.get((b, s), global_ratio) for b, s in zip(d["frp_bin"], d["season"])]
    d["harmonized_count"] = [float(v) if v > 0 else float(mo * ra) for v, mo, ra in zip(d["viirs_count"], d["modis_count"], d["ratio_applied"])]
    return d.drop(columns=["frp_bin", "season"])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleaned", required=True); ap.add_argument("--monthly", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--calibration-out", default="data/calibration.json"); ap.add_argument("--calib-years", default="2012-2020")
    a = ap.parse_args(); cy = tuple(int(x) for x in a.calib_years.split("-"))
    ratios, gr = compute_ratios_from_cleaned(pd.read_parquet(a.cleaned), cy)
    out = apply_ratios(pd.read_parquet(a.monthly), ratios, gr)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); out.to_parquet(a.out, index=False)
    cal = {"calib_years": list(cy), "global_ratio": round(float(gr), 4),
           "strata": ratios.assign(ratio=ratios["ratio"].round(4)).to_dict("records"),
           "reference_sensor": "VIIRS", "method": "region-aggregated detection counts per FRP-bin x season stratum",
           "note": "MODIS-era harmonized = estimate of VIIRS-equivalent counts, incl. small fires MODIS missed"}
    Path(a.calibration_out).write_text(json.dumps(cal, indent=2))
    print(ratios.to_string(index=False)); print(f"global ratio: {gr:.3f}")
    print(f"Wrote {a.out} ({len(out):,} rows) and {a.calibration_out}")
