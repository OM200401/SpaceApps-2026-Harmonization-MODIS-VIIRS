"""Daily table -> (1) sensor outage days, (2) monthly cell table on matched days.

Outage day: a satellite's worldwide count falls below OUT_FRAC x its centred 31-day median.
For the overlap years, a day is dropped for every sensor when Terra, Aqua or S-NPP is out, so the
monthly MODIS and S-NPP totals always cover the same days. Daily-level nonlinear sums (sqrt, max,
active days) are kept as monthly features.

Usage: python experiments/v2/build_month.py
       python experiments/v2/build_month.py --daily data/experiments_v2/daily_terra --out month_terra.parquet --reuse-days
       python experiments/v2/build_month.py --daily data/experiments_v2/daily_modis --out month_modis.parquet --modis-era
"""
import argparse
import duckdb

ap = argparse.ArgumentParser()
ap.add_argument("--daily", default="data/experiments_v2/daily")
ap.add_argument("--out", default="month.parquet")
ap.add_argument("--reuse-days", action="store_true", help="use the outage days already written by the main build")
ap.add_argument("--modis-era", action="store_true", help="2000-2012 tables: Terra/Aqua outages only, plus an exposure table")
a = ap.parse_args()
D = "data/experiments_v2"
OUT_FRAC = 0.5
PAIR_FRAC = 0.6
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET threads=8; SET temp_directory='{D}/tmp'; SET preserve_insertion_order=false")
con.execute(f"CREATE VIEW daily AS SELECT * FROM read_parquet('{a.daily}/y*.parquet')")

if a.reuse_days:
    con.execute(f"CREATE TABLE days AS SELECT * FROM '{D}/days.parquet'")
elif a.modis_era:
    # MODIS era (no S-NPP): Terra or Aqua is out when below OUT_FRAC x its 31-day median or 0.3 x its 181-day
    # median (the second catches long outages such as Terra, 15 Jun - 3 Jul 2001). Aqua only counts from July 2002.
    con.execute(f"""
    CREATE TABLE days AS
    WITH g AS (SELECT acq_date, sum(t_n) t, sum(a_n) a FROM daily GROUP BY 1),
    cal AS (SELECT CAST(d AS DATE) acq_date FROM generate_series((SELECT min(acq_date) FROM g),
            (SELECT max(acq_date) FROM g), INTERVAL 1 DAY) x(d)),
    f AS (SELECT acq_date, coalesce(t, 0) t, coalesce(a, 0) a FROM cal LEFT JOIN g USING (acq_date)),
    r AS (SELECT *, median(t) OVER w mt, median(a) OVER w ma, median(t) OVER l lt, median(a) OVER l la
          FROM f WINDOW w AS (ORDER BY acq_date ROWS BETWEEN 15 PRECEDING AND 15 FOLLOWING),
                        l AS (ORDER BY acq_date ROWS BETWEEN 90 PRECEDING AND 90 FOLLOWING))
    SELECT acq_date, t, a, 0 AS s, 0 AS j,
           t < {OUT_FRAC} * mt OR t < 0.3 * lt AS t_out,
           acq_date >= DATE '2002-07-04' AND (a < {OUT_FRAC} * ma OR a < 0.3 * la) AS a_out,
           false AS s_out, false AS j_out
    FROM r""")
    con.execute(f"COPY days TO '{D}/days_modis.parquet' (FORMAT parquet)")
    # exposure: share of each month's days kept, to scale estimates back to the full month
    con.execute(f"""COPY (SELECT CAST(year(acq_date) AS INTEGER) AS "year", CAST(month(acq_date) AS INTEGER) AS "month",
                         count(*) n_days, count(*) FILTER (WHERE NOT (t_out OR a_out)) kept FROM days GROUP BY ALL ORDER BY ALL)
                    TO '{D}/exposure_modis.parquet' (FORMAT parquet)""")
    print(con.sql(f"SELECT year, sum(n_days - kept) dropped FROM '{D}/exposure_modis.parquet' GROUP BY 1 ORDER BY 1").df().to_string(index=False))
else:
    # A sensor is out on a day when (a) its worldwide count drops below OUT_FRAC x its centred 31-day median, or
    # (b) it is low against BOTH other sensors, each compared with the 181-day median of that pair's ratio.
    # (b) catches outages longer than two weeks, which drag the 31-day median down with them
    # (Aqua, 16 Aug - 2 Sep 2020), and days with most orbits missing.
    con.execute(f"""
    CREATE TABLE days AS
    WITH g AS (SELECT acq_date, sum(t_n) t, sum(a_n) a, sum(s_n) s, sum(j_n) j FROM daily GROUP BY 1),
    cal AS (SELECT CAST(d AS DATE) acq_date FROM generate_series((SELECT min(acq_date) FROM g),
            (SELECT max(acq_date) FROM g), INTERVAL 1 DAY) x(d)),
    f AS (SELECT acq_date, coalesce(t, 0) t, coalesce(a, 0) a, coalesce(s, 0) s, coalesce(j, 0) j FROM cal LEFT JOIN g USING (acq_date)),
    q AS (SELECT *, t / nullif(s, 0) ts, a / nullif(s, 0) a_s, t / nullif(a, 0) ta, j / nullif(s, 0) js FROM f),
    r AS (SELECT *, median(t) OVER w mt, median(a) OVER w ma, median(s) OVER w ms, median(j) OVER w mj,
                 median(ts) OVER l mts, median(a_s) OVER l mas, median(ta) OVER l mta, median(js) OVER l mjs
          FROM q WINDOW w AS (ORDER BY acq_date ROWS BETWEEN 15 PRECEDING AND 15 FOLLOWING),
                        l AS (ORDER BY acq_date ROWS BETWEEN 90 PRECEDING AND 90 FOLLOWING))
    SELECT acq_date, t, a, s, j,
           t < {OUT_FRAC} * mt OR coalesce(ts < {PAIR_FRAC} * mts AND ta < {PAIR_FRAC} * mta, false) AS t_out,
           a < {OUT_FRAC} * ma OR coalesce(a_s < {PAIR_FRAC} * mas AND ta > mta / {PAIR_FRAC}, false) AS a_out,
           s < {OUT_FRAC} * ms OR coalesce(ts > mts / {PAIR_FRAC} AND a_s > mas / {PAIR_FRAC}, false) AS s_out,
           (mj > 0 AND j < {OUT_FRAC} * mj) OR coalesce(js < {PAIR_FRAC} * mjs, false) AS j_out
    FROM r""")
    con.execute(f"COPY days TO '{D}/days.parquet' (FORMAT parquet)")
    print(con.sql("""SELECT year(acq_date) y, sum(t_out::INT) terra_out, sum(a_out::INT) aqua_out, sum(s_out::INT) snpp_out,
                     sum(j_out::INT) n20_out, sum((t_out OR a_out OR s_out)::INT) dropped FROM days GROUP BY 1 ORDER BY 1""").df().to_string(index=False))

BINS = [f"{p}_s{i}" for p in "ta" for i in range(1, 5)] + [f"{p}_f{i}" for p in "ta" for i in range(1, 6)]
SUMS = ["t_n", "a_n", "t_frp", "a_frp", "t_lo", "a_lo", "m_hi", *BINS, "m_lfrp", "m_area", "m_dt", "m_t31", "m_hot",
        "m_sub", "s_n", "s_frp", "s_lo"]
sums = ", ".join(f"CAST(sum({c}) AS FLOAT) AS {c}" for c in SUMS)
con.execute(f"""
COPY (
  SELECT cell_lat, cell_lon, CAST(year(acq_date) AS INTEGER) AS year, CAST(month(acq_date) AS INTEGER) AS month,
         daynight AS dn, {sums},
         CAST(max(m_maxfrp) AS FLOAT) AS m_maxfrp,
         CAST(sum(sqrt(t_n + a_n)) AS FLOAT) AS m_sqrt,
         CAST(sum(sqrt(t_n)) AS FLOAT) AS t_sqrt, CAST(sum(sqrt(a_n)) AS FLOAT) AS a_sqrt,
         CAST(max(t_n + a_n) AS FLOAT) AS m_max,
         CAST(count(*) FILTER (WHERE t_n > 0) AS FLOAT) AS t_days,
         CAST(count(*) FILTER (WHERE a_n > 0) AS FLOAT) AS a_days,
         CAST(count(*) FILTER (WHERE t_n + a_n > 0) AS FLOAT) AS m_days,
         -- NOAA-20 on days it and S-NPP both ran, with the matching S-NPP count, for the VIIRS-vs-VIIRS floor
         CAST(sum(j_n) FILTER (WHERE NOT j_out) AS FLOAT) AS j_n,
         CAST(sum(s_n) FILTER (WHERE NOT j_out) AS FLOAT) AS s_n_j
  FROM daily JOIN days USING (acq_date)
  WHERE NOT (t_out OR a_out OR s_out)
  GROUP BY ALL
) TO '{D}/{a.out}' (FORMAT parquet, COMPRESSION zstd)""")
print(con.sql(f"SELECT count(*) n, sum(t_n + a_n) modis, sum(s_n) snpp, min(year) y0, max(year) y1 FROM '{D}/{a.out}'").df().to_string(index=False))
