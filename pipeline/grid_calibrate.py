"""Grid-path S-NPP calibration; leaves raw-detection calibrate.py untouched."""
import argparse, json
from pathlib import Path
import pandas as pd

KEYS = ["cell_lat", "cell_lon", "year", "month"]
# Mean FRP bins differ materially by sensor in the grid aggregate, so the
# shipped grid variant uses only the stable season × day/night strata.
STRATA = ["season", "daynight"]

def frp_bin(x):
    if x < 10: return "0-10"
    if x < 30: return "10-30"
    if x < 100: return "30-100"
    return "100+"
def season(month): return "fire" if 5 <= month <= 9 else "off"
def add_strata(d):
    d = d.copy(); d["frp_bin"] = d["mean_frp"].map(frp_bin); d["season"] = d["month"].map(season)
    return d
def ratios(staging, years=(2012, 2020)):
    d = add_strata(staging[staging.year.between(*years)])
    def sums(frame):
        return frame.groupby(STRATA, as_index=False).hotspots.sum()
    modis = sums(d[d.sensor == "MODIS"]).rename(columns={"hotspots":"modis"})
    terra = sums(d[d.satellite == "Terra"]).rename(columns={"hotspots":"terra"})
    snpp = sums(d[d.satellite == "SNPP"]).rename(columns={"hotspots":"snpp"})
    out = modis.merge(terra, on=STRATA, how="outer").merge(snpp, on=STRATA, how="outer").fillna(0)
    dn = d.groupby("daynight").apply(lambda x: pd.Series({"modis_dn": x.loc[x.sensor.eq("MODIS"),"hotspots"].sum(), "terra_dn": x.loc[x.satellite.eq("Terra"),"hotspots"].sum(), "snpp_dn": x.loc[x.satellite.eq("SNPP"),"hotspots"].sum()}), include_groups=False).reset_index()
    out = out.merge(dn, on="daynight", how="left")
    out["ratio"] = out.snpp / out.modis.clip(lower=1)
    out["ratio_terra"] = out.snpp / out.terra.clip(lower=1)
    out["fallback"] = out.modis < 50
    out.loc[out.fallback, "ratio"] = out.snpp_dn / out.modis_dn.clip(lower=1)
    out.loc[out.terra < 50, "ratio_terra"] = out.snpp_dn / out.terra_dn.clip(lower=1)
    return out
def converted(staging, ratio_table):
    d = add_strata(staging[staging.sensor.eq("MODIS")])
    d = d.merge(ratio_table[STRATA+["ratio","ratio_terra"]], on=STRATA, how="left")
    d["weight"] = d.hotspots * d.ratio
    early = d.year <= 2002
    d.loc[early, "weight"] = d.loc[early, "hotspots"] * d.loc[early, "ratio_terra"]
    return d
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--staging",default="data/cleaned_canada.parquet"); ap.add_argument("--monthly",default="data/monthly.parquet"); ap.add_argument("--out",default="data/monthly_harmonized.parquet"); ap.add_argument("--calibration-out",default="data/calibration_grid.json"); a=ap.parse_args()
    s=pd.read_parquet(a.staging); r=ratios(s); w=converted(s,r)
    conv=w.groupby(KEYS,as_index=False).weight.sum().rename(columns={"weight":"modis_converted"})
    actual=s[s.satellite.eq("SNPP")].groupby(KEYS,as_index=False).hotspots.sum().rename(columns={"hotspots":"snpp_observed"})
    m=pd.read_parquet(a.monthly).drop(columns=["harmonized_count"],errors="ignore").merge(conv,on=KEYS,how="left").merge(actual,on=KEYS,how="left")
    m[["modis_converted","snpp_observed"]]=m[["modis_converted","snpp_observed"]].fillna(0.0)
    m["harmonized_count"]=m.snpp_observed.where(m.snpp_observed.gt(0),m.modis_converted)
    m.drop(columns=["modis_converted","snpp_observed"]).to_parquet(a.out,index=False)
    Path(a.calibration_out).write_text(json.dumps({"reference":"SNPP only","calib_years":[2012,2020],"min_modis_hotspots":50,"strata":r.round(6).to_dict("records")},indent=2))
    print(r[[*STRATA,"modis","terra","snpp","ratio","ratio_terra","fallback"]].to_string(index=False)); print(f"Wrote {a.out} ({len(m):,} rows)")
if __name__=="__main__": main()
