"""Grid-path S-NPP calibration; leaves raw-detection calibrate.py untouched.

The shipped rule (issue #37) is fit_rule() + converted_rule():
  A = MODIS x block ratio   (1-degree block ratio, shrunk toward the region ratio)
  B = A x monthly factor    (region power law for that calendar month and day/night,
                             divided by the plain region ratio)
  harmonized MODIS-era count = BLEND_W * A + (1 - BLEND_W) * B
ratios() and converted() are the previous single-ratio rule, kept for comparison and for the
Terra-only months before Aqua. Run standalone, this fits the rule on Canada's staging rows."""
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

KEYS = ["cell_lat", "cell_lon", "year", "month"]
# Mean FRP bins differ materially by sensor in the grid aggregate, so the
# shipped grid variant uses only the stable season × day/night strata.
STRATA = ["season", "daynight"]
# Aqua's first detections are July 2002; earlier months are Terra-only and use ratio_terra.
AQUA_START = (2002, 7)
SNPP_START = (2012, 2)  # first full month of S-NPP VIIRS

def frp_bin(x):
    if x < 10: return "0-10"
    if x < 30: return "10-30"
    if x < 100: return "30-100"
    return "100+"
def season(month): return "fire" if 5 <= month <= 9 else "off"
def add_strata(d):
    d = d.copy(); d["frp_bin"] = d["mean_frp"].map(frp_bin); d["season"] = d["month"].map(season)
    return d
MIN_MODIS = 50  # below this many MODIS detections a stratum's own ratio is too noisy
def ratios(staging, years=(2012, 2020), fallback=None):
    """S-NPP/MODIS ratios per stratum. Thin strata use `fallback` (e.g. global ratios) if given,
    else this region's pooled day/night ratio."""
    d = add_strata(staging[staging.year.between(*years)])
    def sums(frame):
        return frame.groupby(STRATA, as_index=False).hotspots.sum()
    modis = sums(d[d.sensor == "MODIS"]).rename(columns={"hotspots":"modis"})
    terra = sums(d[d.satellite == "Terra"]).rename(columns={"hotspots":"terra"})
    snpp = sums(d[d.satellite == "SNPP"]).rename(columns={"hotspots":"snpp"})
    out = modis.merge(terra, on=STRATA, how="outer").merge(snpp, on=STRATA, how="outer")
    # Every stratum gets a row, even with no overlap detections, so converted() never meets a missing ratio.
    every = pd.MultiIndex.from_product([["fire", "off"], ["D", "N"]], names=STRATA).to_frame(index=False)
    out = every.merge(out, on=STRATA, how="left").fillna(0)
    dn =d.groupby("daynight").apply(lambda x: pd.Series({"modis_dn": x.loc[x.sensor.eq("MODIS"),"hotspots"].sum(), "terra_dn": x.loc[x.satellite.eq("Terra"),"hotspots"].sum(), "snpp_dn": x.loc[x.satellite.eq("SNPP"),"hotspots"].sum()}), include_groups=False).reset_index()
    out = out.merge(dn, on="daynight", how="left")
    out["ratio"] = out.snpp / out.modis.clip(lower=1)
    out["ratio_terra"] = out.snpp / out.terra.clip(lower=1)
    out["fallback"] = out.modis < MIN_MODIS
    thin_terra = out.terra < MIN_MODIS
    if fallback is not None:
        f = out[STRATA].merge(fallback[STRATA+["ratio","ratio_terra"]], on=STRATA, how="left")
        out.loc[out.fallback, "ratio"] = f.loc[out.fallback, "ratio"].values
        out.loc[thin_terra, "ratio_terra"] = f.loc[thin_terra, "ratio_terra"].values
    else:
        out.loc[out.fallback, "ratio"] = out.snpp_dn / out.modis_dn.clip(lower=1)
        out.loc[thin_terra, "ratio_terra"] = out.snpp_dn / out.terra_dn.clip(lower=1)
    return out
def converted(staging, ratio_table):
    d = add_strata(staging[staging.sensor.eq("MODIS")])
    d = d.merge(ratio_table[STRATA+["ratio","ratio_terra"]], on=STRATA, how="left")
    d["weight"] = d.hotspots * d.ratio
    early = d.year * 100 + d.month < AQUA_START[0] * 100 + AQUA_START[1]
    d.loc[early, "weight"] = d.loc[early, "hotspots"] * d.loc[early, "ratio_terra"]
    return d
# ---- Optimised rule (issue #37): per-area ratios + monthly power law ----
BLOCK_DEG = 1.0        # block size for per-area ratios
SHRINK_K = 200         # pseudo-count of MODIS detections pulling a block toward its region ratio
BLEND_W = 0.5          # weight on A (block ratio); the rest goes to B (A x monthly factor)
FIT_START = (2012, 2)  # first full S-NPP month
FIT_END_YEAR = 2025    # last full year; 2026 is partial and partly near-real-time

def _ym(d): return d.year * 100 + d.month
def _block(x): return np.floor(x / BLOCK_DEG + 1e-9) * BLOCK_DEG
def _sensor_cols(d):
    return d.assign(m=np.where(d.sensor.eq("MODIS"), d.hotspots, 0),
                    s=np.where(d.satellite.eq("SNPP"), d.hotspots, 0))

def fit_rule(staging, start=FIT_START, end_year=FIT_END_YEAR, fallback=None):
    """Fit the optimised rule on overlap months from `start` (year, month) through `end_year`.
    `fallback` (e.g. global ratios) replaces a region stratum with fewer than MIN_MODIS detections,
    as before; without it a thin stratum uses the region's pooled day/night ratio."""
    d = staging[(_ym(staging) >= start[0] * 100 + start[1]) & (staging.year <= end_year)]
    region = ratios(d, years=(start[0], end_year), fallback=fallback)
    d = _sensor_cols(add_strata(d)).assign(bla=lambda x: _block(x.cell_lat), blo=lambda x: _block(x.cell_lon))
    # Per-area ratios: each block's S-NPP/MODIS, shrunk toward the region ratio of the same stratum.
    blocks = d.groupby(["bla", "blo", *STRATA], as_index=False)[["m", "s"]].sum()
    blocks = blocks.merge(region[STRATA + ["ratio"]], on=STRATA, how="left")
    blocks["block_ratio"] = (blocks.s + SHRINK_K * blocks.ratio) / (blocks.m + SHRINK_K)
    # Monthly factor: power law S-NPP = e^a * MODIS^b on region-month totals, one fit per calendar month x day/night.
    rm = d.groupby(["year", "month", "daynight"], as_index=False)[["m", "s"]].sum()
    pl = []
    for (mo, dn), g in rm.groupby(["month", "daynight"]):
        pos = g[g.m > 0]
        x, y = np.log(pos.m.values), np.log1p(pos.s.values)
        if len(pos) < 5 or np.ptp(x) == 0:
            b, a, smear = 1.0, float(np.log((pos.s.sum() + 1) / max(pos.m.sum(), 1))), 1.0
        else:
            b, a = np.polyfit(x, y, 1)
            smear = float(np.mean(np.exp(y - (a + b * x))))  # back-transform bias correction
        # Uplift: S-NPP detected in region-months where MODIS saw nothing cannot come from a MODIS-based
        # prediction, so scale predictions up by 1/(1 - that share), capped at 2x. It is 1.0 whenever
        # MODIS saw at least one fire in every region-month of this month x day/night (all 3 regions today).
        missed = g.loc[g.m <= 0, "s"].sum() / max(g.s.sum(), 1)
        pl.append({"month": mo, "daynight": dn, "a": float(a), "b": float(b), "smear": smear,
                   "uplift": float(1 / (1 - min(missed, 0.5))), "n_months": int(len(pos))})
    return {"region": region, "blocks": blocks[["bla", "blo", *STRATA, "m", "s", "block_ratio"]],
            "power_law": pd.DataFrame(pl), "fit": {"start": list(start), "end_year": end_year}}

def converted_rule(staging, rule):
    """MODIS rows with `weight` = predicted S-NPP-equivalent detections under the optimised rule."""
    d = add_strata(staging[staging.sensor.eq("MODIS")]).assign(bla=lambda x: _block(x.cell_lat), blo=lambda x: _block(x.cell_lon))
    d = d.merge(rule["blocks"][["bla", "blo", *STRATA, "block_ratio"]], on=["bla", "blo", *STRATA], how="left")
    d = d.merge(rule["region"][STRATA + ["ratio", "ratio_terra"]], on=STRATA, how="left")
    d["block_ratio"] = d.block_ratio.fillna(d.ratio)  # blocks with no overlap history use the region ratio
    # Region MODIS total for the same month and day/night drives the monthly factor.
    d["region_m"] = d.groupby(["year", "month", "daynight"]).hotspots.transform("sum")
    d = d.merge(rule["power_law"], on=["month", "daynight"], how="left")
    pl = np.where(d.region_m > 0, np.exp(d.a + d.b * np.log(d.region_m.clip(lower=1))) * d.smear - 1, 0)
    pl = np.maximum(pl, 0) * d.uplift
    lin = d.ratio * d.region_m
    # No power-law fit for this month x day/night (e.g. a small region with no overlap data there):
    # factor 1, so the estimate falls back to A instead of silently becoming NaN.
    no_fit = d.a.isna().values
    factor = np.where(no_fit | ~(lin > 0), 1.0, pl / np.maximum(lin.fillna(0), 1e-9))
    factor = np.where(np.isfinite(factor), factor, 1.0)
    d["weight"] = d.hotspots * d.block_ratio * (BLEND_W + (1 - BLEND_W) * factor)
    early = _ym(d) < AQUA_START[0] * 100 + AQUA_START[1]
    d.loc[early, "weight"] = d.loc[early, "hotspots"] * d.loc[early, "ratio_terra"]  # Terra-only path unchanged
    return d.drop(columns=["a", "b", "smear", "uplift", "n_months"])

def convert(staging, r):
    """Dispatch: a fitted rule (dict) uses the optimised rule, a ratio table the old single-ratio rule."""
    return converted_rule(staging, r) if isinstance(r, dict) else converted(staging, r)

def rule_summary(rule):
    """JSON-friendly parameters of a fitted rule."""
    return {"block_deg": BLOCK_DEG, "shrink_k": SHRINK_K, "blend_w": BLEND_W, "fit": rule["fit"],
            "region_strata": rule["region"].round(6).to_dict("records"),
            "power_law": rule["power_law"].round(6).to_dict("records"),
            "blocks": int(len(rule["blocks"]))}

def harmonize(s, w, monthly):
    """Staging rows s, converted MODIS rows w, monthly cell table -> monthly with harmonized_count."""
    conv=w.groupby(KEYS,as_index=False).weight.sum().rename(columns={"weight":"modis_converted"})
    actual=s[s.satellite.eq("SNPP")].groupby(KEYS,as_index=False).hotspots.sum().rename(columns={"hotspots":"snpp_observed"})
    m=monthly.drop(columns=["harmonized_count"],errors="ignore").merge(conv,on=KEYS,how="left").merge(actual,on=KEYS,how="left")
    m[["modis_converted","snpp_observed"]]=m[["modis_converted","snpp_observed"]].fillna(0.0)
    # From SNPP_START, observed SNPP is the record, zeros included; MODIS fills only months with no SNPP data region-wide.
    snpp_era = m.year * 100 + m.month >= SNPP_START[0] * 100 + SNPP_START[1]
    snpp_has_data = m.groupby(["year", "month"]).snpp_observed.transform("sum").gt(0)
    m["harmonized_count"]=m.snpp_observed.where(snpp_era & snpp_has_data, m.modis_converted)
    return m
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--staging",default="data/cleaned_canada.parquet"); ap.add_argument("--monthly",default="data/monthly.parquet"); ap.add_argument("--out",default="data/monthly_harmonized.parquet"); ap.add_argument("--calibration-out",default="data/calibration_grid.json"); a=ap.parse_args()
    s=pd.read_parquet(a.staging); rule=fit_rule(s); w=converted_rule(s,rule)
    m=harmonize(s,w,pd.read_parquet(a.monthly))
    m.drop(columns=["modis_converted","snpp_observed"]).to_parquet(a.out,index=False)
    # Top-level "strata" (region ratios) is what check_outputs.py reads; "rule" holds the full parameters.
    Path(a.calibration_out).write_text(json.dumps({"reference":"SNPP only","strata":rule["region"].round(6).to_dict("records"),"rule":rule_summary(rule)},indent=2))
    print(rule["region"][[*STRATA,"modis","terra","snpp","ratio","ratio_terra","fallback"]].to_string(index=False)); print(f"Wrote {a.out} ({len(m):,} rows)")
if __name__=="__main__": main()
