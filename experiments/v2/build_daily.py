"""Daily 0.25-degree feature table from the raw FIRMS detections (archive rows, vegetation fires).

One row per cell x date x day/night. MODIS columns keep per-detection information the monthly grid
drops (scan angle, FRP mix, confidence, sub-cell spread); S-NPP and NOAA-20 columns are targets.
Counts use the pipeline's filters (type = 0, confidence nominal/high) unless the name says otherwise.

Usage: python experiments/v2/build_daily.py [--raw ../parquet] [--out data/experiments_v2/daily]
"""
import argparse, time
from pathlib import Path
import duckdb

ap = argparse.ArgumentParser()
ap.add_argument("--raw", default="../parquet")
ap.add_argument("--out", default="data/experiments_v2/daily")
ap.add_argument("--years", default="2000-2025")
ap.add_argument("--no-static", action="store_true", help="keep persistent hot spots (gas flares etc.)")
ap.add_argument("--no-aqua", action="store_true", help="drop Aqua, to imitate the Terra-only months before July 2002")
a = ap.parse_args()
y0, y1 = map(int, a.years.split("-"))
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
import os
con.execute(f"SET memory_limit='{os.environ.get('DUCK_MEM', '6GB')}'; SET threads={os.environ.get('DUCK_THREADS', '12')}; SET preserve_insertion_order=false")
con.execute(f"SET temp_directory='{(out.parent / 'tmp').as_posix()}'")

M = "sensor = 'M-C61'"
OK = "TRY_CAST(confidence AS INTEGER) >= 30"          # MODIS nominal + high
T, A = f"{M} AND satellite = 'Terra'", f"{M} AND satellite = 'Aqua'"
V = "lower(left(confidence, 1)) IN ('n', 'h')"         # VIIRS nominal + high
def cnt(cond): return f"CAST(count(*) FILTER (WHERE {cond}) AS INTEGER)"
def sm(expr, cond): return f"CAST(coalesce(sum({expr}) FILTER (WHERE {cond}), 0) AS FLOAT)"

SCAN = ["scan <= 1.2", "scan > 1.2 AND scan <= 1.8", "scan > 1.8 AND scan <= 3.0", "scan > 3.0"]
FRP = ["frp < 8", "frp >= 8 AND frp < 20", "frp >= 20 AND frp < 60", "frp >= 60 AND frp < 200", "frp >= 200"]
bins = ", ".join(
    [f"{cnt(f'{sat} AND {OK} AND {c}')} AS {p}_s{i + 1}" for p, sat in (("t", T), ("a", A)) for i, c in enumerate(SCAN)] +
    [f"{cnt(f'{sat} AND {OK} AND {c}')} AS {p}_f{i + 1}" for p, sat in (("t", T), ("a", A)) for i, c in enumerate(FRP)]) + ","

static, static2 = out.parent / "static.parquet", out.parent / "static2.parquet"
mask = "" if a.no_static or not static.exists() else (
    f"AND NOT EXISTS (SELECT 1 FROM '{static.as_posix()}' s WHERE s.fy = CAST(floor(latitude / 0.02) AS INTEGER) "
    f"AND s.fx = CAST(floor(longitude / 0.02) AS INTEGER)) "
    f"AND NOT EXISTS (SELECT 1 FROM '{static2.as_posix()}' s WHERE s.cy = CAST(floor(latitude / 0.1) AS INTEGER) "
    f"AND s.cx = CAST(floor(longitude / 0.1) AS INTEGER))")
print("static-source mask:", "on" if mask else "off", flush=True)
no_aqua = "AND satellite <> 'Aqua'" if a.no_aqua else ""
for y in range(y0, y1 + 1):
    t0 = time.time()
    src = f"{a.raw}/sensor=*/year={y}/*.parquet"
    con.execute(f"""
    COPY (
      SELECT round(floor(latitude / 0.25) * 0.25, 4) AS cell_lat,
             round(floor(longitude / 0.25) * 0.25, 4) AS cell_lon,
             acq_date, daynight,
             {cnt(f"{T} AND {OK}")} AS t_n, {cnt(f"{A} AND {OK}")} AS a_n,
             {sm("frp", f"{T} AND {OK}")} AS t_frp, {sm("frp", f"{A} AND {OK}")} AS a_frp,
             {cnt(f"{T} AND NOT ({OK})")} AS t_lo, {cnt(f"{A} AND NOT ({OK})")} AS a_lo,
             {cnt(f"{M} AND TRY_CAST(confidence AS INTEGER) >= 80")} AS m_hi,
             {bins}
             {sm("ln(1 + greatest(frp, 0))", f"{M} AND {OK}")} AS m_lfrp,
             {sm("scan * track", f"{M} AND {OK}")} AS m_area,
             {sm("brightness - bright_t31", f"{M} AND {OK}")} AS m_dt,
             {sm("bright_t31", f"{M} AND {OK}")} AS m_t31,
             {cnt(f"{M} AND {OK} AND brightness >= 340")} AS m_hot,
             CAST(coalesce(max(frp) FILTER (WHERE {M} AND {OK}), 0) AS FLOAT) AS m_maxfrp,
             CAST(count(DISTINCT CASE WHEN {M} AND {OK} THEN
                  (floor(latitude / 0.05), floor(longitude / 0.05)) END) AS INTEGER) AS m_sub,
             {cnt(f"sensor = 'SV-C2' AND {V}")} AS s_n,
             {sm("frp", f"sensor = 'SV-C2' AND {V}")} AS s_frp,
             {cnt("sensor = 'SV-C2' AND lower(left(confidence, 1)) = 'l'")} AS s_lo,
             {cnt(f"sensor = 'J1V-C2' AND {V}")} AS j_n
      FROM read_parquet('{src}', hive_partitioning = true)
      WHERE source = 'archive' AND type = 0 AND sensor IN ('M-C61', 'SV-C2', 'J1V-C2') {no_aqua} {mask}
      GROUP BY ALL
    ) TO '{(out / f"y{y}.parquet").as_posix()}' (FORMAT parquet, COMPRESSION zstd)""")
    n, tn, an, sn = con.execute(f"SELECT count(*), sum(t_n), sum(a_n), sum(s_n) FROM '{(out / f'y{y}.parquet').as_posix()}'").fetchone()
    print(f"{y}: {n:,} rows, Terra {tn:,}, Aqua {an:,}, S-NPP {sn:,} ({time.time() - t0:.0f}s)", flush=True)
