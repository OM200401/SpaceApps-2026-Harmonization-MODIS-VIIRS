#!/usr/bin/env python3
"""Whole-world record with the v2 rule (see experiments/v2/README.md).

Starts from data/monthly_harmonized_global.parquet (build_global.py) so modis_count / viirs_count / total_count
stay the raw counts the app shows, and replaces harmonized_count:
  - Nov 2000 - Jan 2012: the v2 estimate (experiments/v2/apply_modis_era.py), which excludes gas flares.
    Cell-months the v2 rule fills where MODIS saw nothing get raw counts of 0.
  - Feb 2012 onward: observed S-NPP (viirs_count) minus detections on persistent hot spots (gas flares and
    other industrial sources typed as vegetation fire), so both eras count the same thing. This is the
    observed record in every cell-month, including those where the base table fell back to converted MODIS.

Flare counts are recomputed from the raw detections on every run, with the same archive / near-real-time
and vegetation rules as summarise/build_monthly_grid.py, so they are always a subset of viirs_count.

Usage: python pipeline/build_global.py
       python pipeline/build_global_v2.py
       python pipeline/export_tiles.py --monthly data/monthly_harmonized_global_v2.parquet
"""
import argparse, os, time
import duckdb
import pandas as pd

D = "data/experiments_v2"
ERA = 201202
MASK_RES = 0.01   # summarise/build_monthly_grid.py: static-source mask for near-real-time rows


def flare_counts(raw):
    """S-NPP detections that the base grid counts as nominal/high vegetation fire and that lie on the v2
    static-source mask, per 0.25-degree cell-month."""
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{os.environ.get('DUCK_MEM', '4GB')}'; SET threads=8; SET temp_directory='{D}/tmp'")
    src = f"{raw}/sensor=*/year=*/*.parquet"
    # Same as build_monthly_grid.py: near-real-time rows count only after the last archive date of their
    # sensor and satellite, and are vegetation unless they fall on a ~1 km cell the archive ever flagged
    # as volcano, static land source or offshore (type 1-3, any sensor).
    con.execute(f"""CREATE TABLE archive_end AS SELECT max(acq_date) d
                    FROM read_parquet('{raw}/sensor=SV-C2/year=*/*.parquet') WHERE source = 'archive'""")
    con.execute(f"""CREATE TABLE nrt_mask AS SELECT DISTINCT CAST(floor(latitude / {MASK_RES}) AS INTEGER) mlat,
                           CAST(floor(longitude / {MASK_RES}) AS INTEGER) mlon
                    FROM read_parquet('{src}', hive_partitioning = true) WHERE source = 'archive' AND type IN (1, 2, 3)""")
    return con.execute(f"""
      WITH r AS (SELECT * FROM read_parquet('{raw}/sensor=SV-C2/year=*/*.parquet', hive_partitioning = true)
                 WHERE lower(left(confidence, 1)) IN ('n', 'h')
                   AND (source = 'archive' OR acq_date > (SELECT d FROM archive_end)))
      SELECT round(floor(latitude / 0.25) * 0.25, 4) cell_lat, round(floor(longitude / 0.25) * 0.25, 4) cell_lon,
             CAST(year(acq_date) AS INTEGER) AS "year", CAST(month(acq_date) AS INTEGER) AS "month", count(*)::DOUBLE flare
      FROM r
      WHERE CASE WHEN source = 'archive' THEN type = 0
                 ELSE NOT EXISTS (SELECT 1 FROM nrt_mask n WHERE n.mlat = CAST(floor(latitude / {MASK_RES}) AS INTEGER)
                                                           AND n.mlon = CAST(floor(longitude / {MASK_RES}) AS INTEGER)) END
        AND (EXISTS (SELECT 1 FROM '{D}/static.parquet' s WHERE s.fy = CAST(floor(latitude / 0.02) AS INTEGER)
                                                          AND s.fx = CAST(floor(longitude / 0.02) AS INTEGER))
          OR EXISTS (SELECT 1 FROM '{D}/static2.parquet' s WHERE s.cy = CAST(floor(latitude / 0.1) AS INTEGER)
                                                           AND s.cx = CAST(floor(longitude / 0.1) AS INTEGER)))
      GROUP BY ALL""").df()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="data/monthly_harmonized_global.parquet")
    ap.add_argument("--raw", default="../parquet")
    ap.add_argument("--out", default="data/monthly_harmonized_global_v2.parquet")
    a = ap.parse_args()
    t0 = time.time()
    key = ["cell_lat", "cell_lon", "year", "month"]
    fl = flare_counts(a.raw)
    print(f"flare counts: {fl.flare.sum():,.0f} S-NPP detections ({time.time() - t0:.0f}s)", flush=True)
    m = pd.read_parquet(a.base)
    v2 = pd.read_parquet(f"{D}/v2_modis_era_cells.parquet")
    for d in (m, v2, fl):
        d["cell_lat"], d["cell_lon"] = d.cell_lat.round(4), d.cell_lon.round(4)

    # MODIS era: v2 estimate; outer join adds the cell-months MODIS never saw
    m = m.merge(v2, on=key, how="outer", indicator=True)
    new = m._merge == "right_only"
    era = m.year * 100 + m.month < ERA
    for c in ("modis_count", "viirs_count", "total_count"):
        m.loc[new, c] = 0
    m.loc[new, "cell_id"] = m.loc[new, "cell_lat"].astype(str) + "_" + m.loc[new, "cell_lon"].astype(str)
    m["harmonized_old"] = m.harmonized_count
    m.loc[era, "harmonized_count"] = m.loc[era, "harmonized_v2"].fillna(0.0)
    # S-NPP era: the observed record without flare detections
    m = m.merge(fl, on=key, how="left")
    snpp = ~era
    over = (m.flare.fillna(0) > m.viirs_count) & snpp
    assert not over.any(), f"{over.sum()} cell-months with more flare detections than S-NPP detections"
    m.loc[snpp, "harmonized_count"] = (m.loc[snpp, "viirs_count"] - m.loc[snpp, "flare"].fillna(0)).astype(float)
    m = m.drop(columns=["_merge", "harmonized_v2", "flare"])
    for c in ("modis_count", "viirs_count", "total_count"):
        m[c] = m[c].fillna(0).astype(int)
    m.to_parquet(a.out, index=False)

    y = m.groupby("year")[["total_count", "harmonized_old", "harmonized_count"]].sum()
    print("\n== world by year (millions): raw total, harmonized before (shipped rule), harmonized v2")
    print((y / 1e6).round(2).to_string())
    j = lambda c: y.loc[2012, c] / y.loc[2011, c] - 1
    print(f"\n2011->2012 jump, world: raw {j('total_count'):+.1%}, shipped {j('harmonized_old'):+.1%}, v2 {j('harmonized_count'):+.1%}")
    print(f"Wrote {a.out}: {len(m):,} cell-months ({new.sum():,} added), {m.cell_id.nunique():,} cells ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
