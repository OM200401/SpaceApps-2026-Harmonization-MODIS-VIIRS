#!/usr/bin/env python3
"""Whole-world record with the v2 rule (local experiment, see experiments/v2/README.md).

Starts from data/monthly_harmonized_global.parquet (build_global.py) so modis_count / viirs_count / total_count
stay the raw counts the app shows, and replaces harmonized_count:
  - Nov 2000 - Jan 2012: the v2 estimate (experiments/v2/apply_modis_era.py), which excludes gas flares.
    Cell-months the v2 rule fills where MODIS saw nothing get raw counts of 0.
  - Feb 2012 onward: observed S-NPP minus detections on persistent hot spots (gas flares and other
    industrial sources typed as vegetation fire), so both eras count the same thing.

Usage: python pipeline/build_global.py
       python pipeline/build_global_v2.py
       python pipeline/export_tiles.py --monthly data/monthly_harmonized_global_v2.parquet
"""
import argparse, os, time
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

D = "data/experiments_v2"
ERA = 201202
ARCHIVE_END_SNPP = "2026-07-31"   # export_json.ARCHIVE_END["SNPP"]; later rows are near-real-time


def flare_counts(raw, out):
    """S-NPP detections (pipeline filters) on the static-source mask, per 0.25-degree cell-month."""
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{os.environ.get('DUCK_MEM', '4GB')}'; SET threads=8; SET temp_directory='{D}/tmp'")
    con.execute(f"""
    COPY (
      SELECT round(floor(latitude / 0.25) * 0.25, 4) cell_lat, round(floor(longitude / 0.25) * 0.25, 4) cell_lon,
             CAST(year(acq_date) AS INTEGER) AS "year", CAST(month(acq_date) AS INTEGER) AS "month", count(*)::DOUBLE flare
      FROM read_parquet('{raw}/sensor=SV-C2/year=*/*.parquet', hive_partitioning = true) r
      WHERE lower(left(confidence, 1)) IN ('n', 'h')
        AND ((source = 'archive' AND type = 0) OR (source = 'nrt' AND acq_date > DATE '{ARCHIVE_END_SNPP}'))
        AND (EXISTS (SELECT 1 FROM '{D}/static.parquet' s WHERE s.fy = CAST(floor(latitude / 0.02) AS INTEGER)
                                                          AND s.fx = CAST(floor(longitude / 0.02) AS INTEGER))
          OR EXISTS (SELECT 1 FROM '{D}/static2.parquet' s WHERE s.cy = CAST(floor(latitude / 0.1) AS INTEGER)
                                                           AND s.cx = CAST(floor(longitude / 0.1) AS INTEGER)))
      GROUP BY ALL
    ) TO '{out}' (FORMAT parquet)""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="data/monthly_harmonized_global.parquet")
    ap.add_argument("--raw", default="../parquet")
    ap.add_argument("--out", default="data/monthly_harmonized_global_v2.parquet")
    a = ap.parse_args()
    t0 = time.time()
    flares = Path(f"{D}/flare_snpp_cells.parquet")
    if not flares.exists():
        flare_counts(a.raw, flares.as_posix())
        print(f"flare counts built ({time.time() - t0:.0f}s)", flush=True)
    key = ["cell_lat", "cell_lon", "year", "month"]
    m = pd.read_parquet(a.base)
    m["cell_lat"], m["cell_lon"] = m.cell_lat.round(4), m.cell_lon.round(4)
    old = m.harmonized_count.copy()
    v2 = pd.read_parquet(f"{D}/v2_modis_era_cells.parquet")
    v2["cell_lat"], v2["cell_lon"] = v2.cell_lat.round(4), v2.cell_lon.round(4)
    fl = pd.read_parquet(flares)
    fl["cell_lat"], fl["cell_lon"] = fl.cell_lat.round(4), fl.cell_lon.round(4)
    era = m.year * 100 + m.month < ERA

    # MODIS era: v2 estimate; outer join adds the cell-months MODIS never saw
    m = m.merge(v2, on=key, how="outer", indicator=True)
    new = m._merge == "right_only"
    era = m.year * 100 + m.month < ERA
    for c in ("modis_count", "viirs_count", "total_count"):
        m.loc[new, c] = 0
    m.loc[new, "cell_id"] = m.loc[new, "cell_lat"].astype(str) + "_" + m.loc[new, "cell_lon"].astype(str)
    m["harmonized_old"] = m.harmonized_count
    m.loc[era, "harmonized_count"] = m.loc[era, "harmonized_v2"].fillna(0.0)
    # S-NPP era: remove flare detections from the observed record
    m = m.merge(fl, on=key, how="left")
    snpp = ~era
    m.loc[snpp, "harmonized_count"] = (m.loc[snpp, "harmonized_count"] - m.loc[snpp, "flare"].fillna(0)).clip(lower=0)
    m = m.drop(columns=["_merge", "harmonized_v2", "flare"])
    for c in ("modis_count", "viirs_count", "total_count"):
        m[c] = m[c].fillna(0).astype(int)
    m.to_parquet(a.out, index=False)

    y = m.groupby("year")[["total_count", "harmonized_old", "harmonized_count"]].sum()
    print("\n== world by year: raw total, harmonized before (shipped rule), harmonized v2")
    print((y / 1e6).round(2).to_string())
    j = lambda c: y.loc[2012, c] / y.loc[2011, c] - 1
    print(f"\n2011->2012 jump, world: raw {j('total_count'):+.1%}, shipped {j('harmonized_old'):+.1%}, v2 {j('harmonized_count'):+.1%}")
    print(f"Wrote {a.out}: {len(m):,} cell-months ({new.sum():,} added), {m.cell_id.nunique():,} cells ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
