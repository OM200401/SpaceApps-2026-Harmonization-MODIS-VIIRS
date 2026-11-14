#!/usr/bin/env python3
"""
calibrate.py -- stratified VIIRS/MODIS ratios from the overlap, fill harmonized_count.

Method (v3, 2026-11-14):
- Reference sensor = VIIRS on S-NPP ONLY. NOAA-20/21 are never added in: summing
  satellites fakes an upward trend from 2018 and 2023.
- Strata = FRP bin x season x day/night. Day/night matters most: VIIRS sees ~4x
  MODIS by day but ~17x at night.
- Ratios are region-aggregated detection counts per stratum over the overlap years
  (v2 lesson: per-cell ratios are too sparse). Strata with too few MODIS detections
  fall back to their day/night-wide ratio.
- Conversion happens PER DETECTION, not per cell: each MODIS detection gets the
  ratio of its own stratum, and a cell-month's harmonized count is the sum of those
  weights. (v2 learned ratios per detection FRP but applied them by the cell's mean
  FRP, which mixes up the bins.)
- Before Aqua (2002-07-04) only Terra flew, so those months use ratios learned
  against Terra alone; otherwise the early years come out too low.
- Era rule: months from Feb 2012 (first full S-NPP month) use the observed S-NPP
  count; earlier months use converted MODIS.

Usage: python calibrate.py --cleaned data/cleaned_canada.parquet --monthly data/monthly.parquet \
  --out data/monthly_harmonized.parquet --calibration-out data/calibration.json [--calib-years 2012-2020]
"""
import argparse, json
from pathlib import Path
import pandas as pd

REFERENCE_VIIRS = "VIIRS_SNPP"
SNPP_ERA_START = (2012, 2)   # first full month of S-NPP data
AQUA_START = pd.Timestamp("2002-07-04")
MIN_MODIS = 30               # below this a stratum falls back to its day/night ratio
STRATA = ["frp_bin", "season", "daynight"]


def frp_bin(f):
    if pd.isna(f): return "unknown"
    if f < 10: return "0-10"
    if f < 30: return "10-30"
    if f < 100: return "30-100"
    return "100+"


def season(m): return "fire" if 5 <= m <= 9 else "off"


def add_strata(d):
    d = d.copy()
    dt = pd.to_datetime(d["acq_date"])
    d["year"], d["month"] = dt.dt.year, dt.dt.month
    d["frp_bin"] = d["frp"].apply(frp_bin)
    d["season"] = d["month"].apply(season)
    d["daynight"] = d["daynight"].fillna("D") if "daynight" in d.columns else "D"
    d["is_modis"] = (d["sensor"] == "MODIS").astype(int)
    d["is_terra"] = (d["is_modis"].astype(bool) & d["satellite"].astype(str).str.lower().eq("terra")).astype(int)
    d["is_viirs"] = (d["sensor"] == REFERENCE_VIIRS).astype(int)
    return d


def compute_ratios_from_cleaned(cleaned, calib_years):
    """Per-stratum S-NPP / MODIS ratios (and S-NPP / Terra for pre-Aqua months)."""
    d = add_strata(cleaned)
    d = d[(d["year"] >= calib_years[0]) & (d["year"] <= calib_years[1])
          & ((d["year"] * 100 + d["month"]) >= SNPP_ERA_START[0] * 100 + SNPP_ERA_START[1])]
    agg = dict(modis=("is_modis", "sum"), terra=("is_terra", "sum"), viirs=("is_viirs", "sum"))
    g = d.groupby(STRATA, as_index=False).agg(**agg)
    dn = d.groupby("daynight", as_index=False).agg(**agg)
    dn["dn_ratio"] = dn["viirs"] / dn["modis"].clip(lower=1)
    dn["dn_ratio_terra"] = dn["viirs"] / dn["terra"].clip(lower=1)
    g = g.merge(dn[["daynight", "dn_ratio", "dn_ratio_terra"]], on="daynight", how="left")
    g["ratio"] = g["viirs"] / g["modis"].clip(lower=1)
    g["ratio_terra"] = g["viirs"] / g["terra"].clip(lower=1)
    g["fallback"] = g["modis"] < MIN_MODIS
    g.loc[g["fallback"], "ratio"] = g["dn_ratio"]
    g.loc[g["terra"] < MIN_MODIS, "ratio_terra"] = g["dn_ratio_terra"]
    global_ratio = d["is_viirs"].sum() / max(d["is_modis"].sum(), 1)
    return g.drop(columns=["dn_ratio", "dn_ratio_terra"]), global_ratio


def modis_weights(cleaned, ratios, global_ratio):
    """One row per MODIS detection with its conversion weight (VIIRS-equivalent)."""
    d = add_strata(cleaned[cleaned["sensor"] == "MODIS"])
    d = d.merge(ratios[STRATA + ["ratio", "ratio_terra"]], on=STRATA, how="left")
    pre_aqua = pd.to_datetime(d["acq_date"]) < AQUA_START
    d["weight"] = d["ratio_terra"].where(pre_aqua, d["ratio"]).fillna(global_ratio)
    return d


def apply_ratios(monthly, cleaned, ratios, global_ratio, grid=0.25):
    w = modis_weights(cleaned, ratios, global_ratio)
    w["cell_lat"] = (w["lat"] // grid * grid).round(4)
    w["cell_lon"] = (w["lon"] // grid * grid).round(4)
    conv = w.groupby(["cell_lat", "cell_lon", "year", "month"], as_index=False)["weight"].sum()
    d = monthly.drop(columns=["harmonized_count"], errors="ignore").merge(
        conv.rename(columns={"weight": "modis_converted"}),
        on=["cell_lat", "cell_lon", "year", "month"], how="left")
    d["modis_converted"] = d["modis_converted"].fillna(0.0)
    snpp_era = (d["year"] * 100 + d["month"]) >= SNPP_ERA_START[0] * 100 + SNPP_ERA_START[1]
    d["harmonized_count"] = d["viirs_count"].astype(float).where(snpp_era, d["modis_converted"])
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleaned", required=True); ap.add_argument("--monthly", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--calibration-out", default="data/calibration.json"); ap.add_argument("--calib-years", default="2012-2020")
    ap.add_argument("--grid", type=float, default=0.25)
    a = ap.parse_args(); cy = tuple(int(x) for x in a.calib_years.split("-"))
    cleaned = pd.read_parquet(a.cleaned)
    ratios, gr = compute_ratios_from_cleaned(cleaned, cy)
    out = apply_ratios(pd.read_parquet(a.monthly), cleaned, ratios, gr, a.grid)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); out.to_parquet(a.out, index=False)
    cal = {"calib_years": list(cy), "global_ratio": round(float(gr), 4),
           "strata": ratios.round(4).to_dict("records"),
           "reference_sensor": "VIIRS S-NPP",
           "method": "per-detection weights from region-aggregated S-NPP/MODIS ratios per FRP-bin x season x day/night; Terra-only ratios before Aqua",
           "note": "MODIS-era harmonized = estimate of S-NPP-equivalent counts, incl. small fires MODIS missed"}
    Path(a.calibration_out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.calibration_out).write_text(json.dumps(cal, indent=2))
    print(ratios.to_string(index=False)); print(f"global ratio: {gr:.3f}")
    print(f"Wrote {a.out} ({len(out):,} rows) and {a.calibration_out}")
