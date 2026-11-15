"""Find persistent hot spots that FIRMS types as vegetation fire (gas flares, industry, coal seams).

A 0.02-degree (~2 km) cell is 'static' when S-NPP sees it burning in most calendar months, in many
separate months overall, and at least half the time at night. Vegetation fires are seasonal and mostly
seen by day, so they don't do that (year-round farm burning in central Africa fails the night test).
Oil fields flare from wells that move around, so a second, coarser tier flags 0.1-degree cells that
burn year-round and at least 75% at night. Outputs: static.parquet with (fy, fx) = floor(lat / 0.02),
floor(lon / 0.02), and static2.parquet with (cy, cx) = floor(lat / 0.1), floor(lon / 0.1).

Usage: python experiments/v2/build_static.py [--raw ../parquet]
"""
import argparse, os
import duckdb

ap = argparse.ArgumentParser()
ap.add_argument("--raw", default="../parquet")
ap.add_argument("--min-cal", type=int, default=8, help="distinct calendar months (of 12)")
ap.add_argument("--min-months", type=int, default=15, help="distinct year-months, 2012-2021")
ap.add_argument("--min-night", type=float, default=0.5, help="share of detections at night; flares burn all day, crop and savanna fires mostly by day")
a = ap.parse_args()
D = "data/experiments_v2"
con = duckdb.connect()
con.execute(f"SET memory_limit='{os.environ.get('DUCK_MEM', '4GB')}'; SET threads={os.environ.get('DUCK_THREADS', '6')}; "
            f"SET temp_directory='{D}/tmp'; SET preserve_insertion_order=false")
os.makedirs(f"{D}/static_tmp", exist_ok=True)
for y in range(2012, 2022):
    con.execute(f"""
    COPY (SELECT CAST(floor(latitude / 0.02) AS INTEGER) fy, CAST(floor(longitude / 0.02) AS INTEGER) fx,
                 CAST(month(acq_date) AS TINYINT) mo, CAST(count(*) AS INTEGER) n,
                 CAST(count(*) FILTER (WHERE daynight = 'N') AS INTEGER) n_night
          FROM read_parquet('{a.raw}/sensor=SV-C2/year={y}/*.parquet')
          WHERE source = 'archive' AND type = 0 AND lower(left(confidence, 1)) IN ('n', 'h')
          GROUP BY ALL) TO '{D}/static_tmp/y{y}.parquet' (FORMAT parquet)""")
    print(y, "done", flush=True)
con.execute(f"""
CREATE TABLE fine AS
SELECT fy, fx, count(*) nmon, count(DISTINCT mo) ncal, sum(n) n, sum(n_night) n_night
FROM read_parquet('{D}/static_tmp/y*.parquet', filename = true) GROUP BY ALL""")
con.execute(f"COPY (SELECT * FROM fine WHERE nmon >= 12) TO '{D}/fine_persist.parquet' (FORMAT parquet)")
con.execute(f"""COPY (SELECT fy, fx, nmon, ncal, n, n_night FROM fine WHERE ncal >= {a.min_cal} AND nmon >= {a.min_months} AND n_night >= {a.min_night} * n)
                TO '{D}/static.parquet' (FORMAT parquet)""")
print(con.sql(f"""SELECT count(*) cells, sum(n) detections, sum(n_night) night,
                  (SELECT sum(n) FROM fine) all_detections FROM '{D}/static.parquet'""").df().to_string(index=False))

# tier 2: 0.1-degree cells dominated by night-time, year-round sources (oil and gas fields)
con.execute(f"""
COPY (
  WITH f AS (SELECT floor(fy / 5.0)::INTEGER cy, floor(fx / 5.0)::INTEGER cx, regexp_extract(filename, 'y([0-9]+)', 1) yr, mo,
                    sum(n) n, sum(n_night) nn
             FROM read_parquet('{D}/static_tmp/y*.parquet', filename = true) GROUP BY ALL)
  SELECT cy, cx, count(*) nmon, count(DISTINCT mo) ncal, sum(n) n, sum(nn) n_night FROM f GROUP BY ALL
  HAVING count(*) >= 30 AND count(DISTINCT mo) >= 10 AND sum(nn) >= 0.75 * sum(n)
) TO '{D}/static2.parquet' (FORMAT parquet)""")
print(con.sql(f"SELECT count(*) cells, sum(n) detections FROM '{D}/static2.parquet'").df().to_string(index=False))
