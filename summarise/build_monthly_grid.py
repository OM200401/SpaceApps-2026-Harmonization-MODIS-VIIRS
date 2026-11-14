"""Build the monthly grid summary table from the raw FIRMS Parquet data.

Every hotspot is snapped to a square grid cell (0.25 deg by default) and counted
per month, sensor, satellite, day/night, confidence class and vegetation flag.

Usage:
    python summarise/build_monthly_grid.py
    python summarise/build_monthly_grid.py --input data/firms --cell 0.25 \
        --output data/derived/monthly_grid_025.parquet
"""

import argparse
import time
from pathlib import Path

import duckdb

# FIRMS MODIS confidence (0-100) -> the same l/n/h classes VIIRS uses.
# Thresholds follow the FIRMS MODIS user guide: <30 low, 30-79 nominal, >=80 high.
MODIS_LOW_MAX = 30
MODIS_HIGH_MIN = 80

# Resolution (deg) of the static-source mask used to flag near-real-time rows,
# which have no `type` column. About 1 km at the equator.
MASK_RES = 0.01


def build(input_dir: Path, output: Path, cell: float, temp_dir: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET temp_directory = '{temp_dir.as_posix()}'")
    con.execute("SET preserve_insertion_order = false")

    src = (input_dir / "sensor=*" / "year=*" / "*.parquet").as_posix()
    con.execute(f"""
        CREATE VIEW raw AS
        SELECT latitude, longitude, acq_date, satellite, confidence, frp,
               daynight, type, source, sensor
        FROM read_parquet('{src}', hive_partitioning = true)
    """)

    # 1. Archive cut-off per sensor and satellite. Near-real-time rows on or
    #    before the last archive date are duplicates of archive rows and dropped.
    con.execute("""
        CREATE TABLE archive_end AS
        SELECT sensor, satellite, max(acq_date) AS last_archive_date
        FROM raw WHERE source = 'archive'
        GROUP BY ALL
    """)

    # 2. Static-source mask: ~1 km cells where the archive ever flagged a
    #    volcano (1), static land source (2) or offshore source (3).
    con.execute(f"""
        CREATE TABLE static_mask AS
        SELECT DISTINCT
               CAST(floor(latitude  / {MASK_RES}) AS INTEGER) AS mlat,
               CAST(floor(longitude / {MASK_RES}) AS INTEGER) AS mlon
        FROM raw
        WHERE source = 'archive' AND type IN (1, 2, 3)
    """)

    # 3. Clean, classify and aggregate in one pass.
    con.execute(f"""
        COPY (
            WITH pts AS (
                SELECT r.*,
                       CAST(floor(r.latitude  / {MASK_RES}) AS INTEGER) AS mlat,
                       CAST(floor(r.longitude / {MASK_RES}) AS INTEGER) AS mlon
                FROM raw r
                LEFT JOIN archive_end a USING (sensor, satellite)
                WHERE r.source = 'archive'
                   OR a.last_archive_date IS NULL
                   OR r.acq_date > a.last_archive_date
            )
            SELECT
                round(floor(latitude  / {cell}) * {cell}, 4) AS cell_lat,
                round(floor(longitude / {cell}) * {cell}, 4) AS cell_lon,
                CAST(year(acq_date)  AS INTEGER) AS year,
                CAST(month(acq_date) AS INTEGER) AS month,
                sensor,
                satellite,
                daynight,
                CASE
                    WHEN sensor = 'M-C61' THEN
                        CASE WHEN TRY_CAST(confidence AS INTEGER) <  {MODIS_LOW_MAX}  THEN 'l'
                             WHEN TRY_CAST(confidence AS INTEGER) >= {MODIS_HIGH_MIN} THEN 'h'
                             ELSE 'n' END
                    ELSE lower(left(confidence, 1))
                END AS confidence,
                CASE
                    WHEN source = 'archive' THEN type = 0
                    ELSE m.mlat IS NULL
                END AS is_vegetation,
                CAST(count(*) AS INTEGER) AS hotspots,
                CAST(round(sum(frp), 1) AS FLOAT) AS frp_sum
            FROM pts
            LEFT JOIN static_mask m USING (mlat, mlon)
            GROUP BY ALL
            ORDER BY cell_lat, cell_lon, year, month, sensor
        ) TO '{output.as_posix()}'
        (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 250000)
    """)

    print(con.sql(f"""
        SELECT count(*) AS rows, sum(hotspots) AS hotspots,
               count(DISTINCT (cell_lat, cell_lon)) AS cells
        FROM '{output.as_posix()}'
    """))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", type=Path, default=Path("data/firms"))
    p.add_argument("--cell", type=float, default=0.25, help="grid cell size in degrees")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--temp", type=Path, default=Path("data/tmp"))
    args = p.parse_args()

    output = args.output or Path(
        f"data/derived/monthly_grid_{str(args.cell).replace('.', '')}.parquet"
    )
    t0 = time.time()
    build(args.input, output, args.cell, args.temp)
    size_mb = output.stat().st_size / 1e6
    print(f"Wrote {output} ({size_mb:.1f} MB) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
