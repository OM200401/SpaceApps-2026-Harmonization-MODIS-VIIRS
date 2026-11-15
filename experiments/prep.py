"""Prepare experiment data: per region, 0.25 deg cell x month x day/night x satellite x confidence."""
import os, sys, duckdb
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
GRID = sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/data/derived/monthly_grid_025.parquet"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("EXP_DATA", f"{ROOT}/data/experiments").replace("\\", "/")
os.makedirs(OUT, exist_ok=True)
REGIONS = {  # W, S, E, N (same inclusive cell filter as pipeline)
    "canada": (-140, 42, -52, 72), "amazon": (-75, -15, -45, 5), "mediterranean": (-10, 35, 30, 45),
    # robustness regions (not app presets): different biomes and fire regimes
    "us_west": (-125, 31, -102, 49), "siberia": (90, 50, 140, 70), "s_africa": (12, -20, 40, -5),
    "se_asia": (92, 10, 110, 25), "n_australia": (120, -20, 150, -11),
}
cases = " ".join(f"WHEN cell_lon BETWEEN {w} AND {e} AND cell_lat BETWEEN {s} AND {n} THEN '{k}'"
                 for k, (w, s, e, n) in REGIONS.items())
con = duckdb.connect()
con.execute(f"""
COPY (
  SELECT CASE {cases} END AS region, cell_lat, cell_lon, year, month, daynight AS dn, satellite AS sat,
         confidence AS conf, sum(hotspots)::INT AS hs, sum(frp_sum)::DOUBLE AS frp
  FROM '{GRID}'
  WHERE is_vegetation AND satellite IN ('Terra','Aqua','SNPP')
    AND NOT (year = 2026 AND month = 11)
    AND (CASE {cases} END) IS NOT NULL
  GROUP BY ALL
) TO '{OUT}/cells.parquet' (FORMAT parquet)""")
# world totals per stratum-level unit, for "global" ratios (vegetation, n/h)
con.execute(f"""
COPY (
  SELECT year, month, daynight AS dn, satellite AS sat, sum(hotspots)::BIGINT AS hs
  FROM '{GRID}' WHERE is_vegetation AND confidence IN ('n','h') AND satellite IN ('Terra','Aqua','SNPP')
    AND NOT (year = 2026 AND month = 11)
  GROUP BY ALL
) TO '{OUT}/world.parquet' (FORMAT parquet)""")
print(con.sql(f"SELECT region, count(*) n_rows, sum(hs) hotspots FROM '{OUT}/cells.parquet' GROUP BY 1 ORDER BY 1").fetchall())
