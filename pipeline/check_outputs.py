#!/usr/bin/env python3
"""Mechanical output verifier — the anti-'trust me, it works' gate.
Usage: python3 pipeline/check_outputs.py clean|calibrate|json
Exits 1 and prints FAIL lines when an output does not meet the contract.
Codex must run this after each stage (AGENTS.md proof rules). Do not edit to pass."""
import json, sys
from pathlib import Path
import pandas as pd

def fail(msg): print(f"FAIL: {msg}"); return 1
def ok(msg): print(f"OK: {msg}"); return 0

def stage_clean():
    rc = 0
    p = Path("data/cleaned_canada.parquet"); m = Path("data/monthly.parquet")
    if not p.exists(): return fail("data/cleaned_canada.parquet missing")
    d = pd.read_parquet(p)
    need = {"lat","lon","acq_date","sensor","frp","confidence"}
    rc |= ok("cleaned rows: "+f"{len(d):,}") if len(d) > 0 else fail("cleaned is empty")
    rc |= ok("schema complete") if need <= set(d.columns) else fail(f"missing columns: {need - set(d.columns)}")
    rc |= ok("sensors: "+str(sorted(d['sensor'].unique()))) if set(d["sensor"].unique()) <= {"MODIS","VIIRS_SNPP","VIIRS_NOAA20","VIIRS_NOAA21"} else fail(f"bad sensor labels: {sorted(d['sensor'].unique())}")
    rc |= ok("all 4 sensors present") if len(set(d["sensor"].unique())) == 4 else fail("not all 4 sensors present")
    rc |= ok("confidence nominal/high only") if set(d["confidence"].unique()) <= {"nominal","high"} else fail(f"confidence values: {set(d['confidence'].unique())}")
    inb = d["lon"].between(-140,-52).all() and d["lat"].between(42,72).all()
    rc |= ok("all rows inside Canada bbox") if inb else fail("rows outside Canada bbox - slice did not run first")
    yrs = pd.to_datetime(d["acq_date"]).dt.year
    rc |= ok(f"date span {yrs.min()}-{yrs.max()}") if yrs.min() <= 2001 and yrs.max() >= 2025 else fail(f"date span {yrs.min()}-{yrs.max()} - coverage gate failed")
    if not m.exists(): rc |= fail("data/monthly.parquet missing")
    else:
        mm = pd.read_parquet(m); rc |= ok(f"monthly rows: {len(mm):,}") if len(mm) > 0 else fail("monthly is empty")
    return rc

def stage_calibrate():
    rc = stage_clean_quiet()
    p = Path("data/monthly_harmonized.parquet")
    if not p.exists(): return fail("data/monthly_harmonized.parquet missing")
    d = pd.read_parquet(p)
    if "harmonized_count" not in d.columns: return fail("harmonized_count column missing")
    rc |= fail(f"harmonized_count has {int(d['harmonized_count'].isna().sum())} nulls") if d["harmonized_count"].isna().any() else ok("harmonized_count fully filled")
    c = Path("data/calibration.json")
    if not c.exists(): rc |= fail("data/calibration.json missing")
    else:
        cal = json.loads(c.read_text()); s = cal.get("strata", [])
        rc |= ok(f"calibration strata: {len(s)}, global ratio {cal.get('global_ratio')}") if len(s) >= 4 else fail(f"only {len(s)} strata")
        bad = [x for x in s if not (0.5 <= x.get("ratio", 0) <= 6.0)]
        rc |= fail(f"ratios outside sane band 0.5-6.0: {bad}") if bad else ok("all strata ratios in sane band 0.5-6.0")
    t = d.groupby("year").agg(raw=("total_count","sum"), harm=("harmonized_count","sum"))
    try:
        rj = (t.loc[2012,"raw"]-t.loc[2011,"raw"])/t.loc[2011,"raw"]; hj = (t.loc[2012,"harm"]-t.loc[2011,"harm"])/t.loc[2011,"harm"]
        print(f"INFO: raw 2011->2012 jump {rj:+.1%}; harmonized {hj:+.1%}")
        rc |= ok("harmonized jump smaller than raw jump") if abs(hj) < abs(rj) else fail("harmonized jump NOT smaller than raw - calibration is not doing its job")
    except KeyError: rc |= fail("2011/2012 missing from harmonized table")
    return rc

def stage_clean_quiet():
    p = Path("data/cleaned_canada.parquet")
    return 0 if p.exists() and len(pd.read_parquet(p, columns=["lat"])) > 0 else 1

def stage_json():
    rc = stage_calibrate()
    p = Path("app/data/monthly.json")
    if not p.exists(): return fail("app/data/monthly.json missing")
    size = p.stat().st_size
    rc |= ok(f"monthly.json size {size/1e6:.2f} MB") if size < 5_000_000 else fail(f"monthly.json {size/1e6:.1f} MB > 5 MB")
    d = json.loads(p.read_text())
    rc |= ok(f"cells {len(d.get('cells',[])):,}, region months {len(d.get('region_monthly',[]))}") if d.get("cells") and d.get("region_monthly") else fail("json missing cells or region_monthly")
    may = [r for r in d["region_monthly"] if r["year"] == 2023 and r["month"] == 5]
    rc |= ok(f"May 2023 harmonized region total: {may[0]['harmonized']:.0f}") if may else fail("May 2023 missing from region_monthly")
    return rc

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"clean": stage_clean, "calibrate": stage_calibrate, "json": stage_json}.get(stage)
    if fn is None: print("usage: check_outputs.py clean|calibrate|json"); sys.exit(2)
    rc = fn(); print("RESULT:", "PASS" if rc == 0 else "FAIL"); sys.exit(rc)
