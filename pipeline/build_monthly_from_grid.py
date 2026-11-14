#!/usr/bin/env python3
"""Build Canada monthly UI inputs from Om's 0.25-degree monthly grid."""
import argparse
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

CANADA = (-140.0, 42.0, -52.0, 72.0)


def grid_rows(path):
    pf = pq.ParquetFile(path)
    cols = ["cell_lat", "cell_lon", "year", "month", "satellite",
            "daynight", "confidence", "is_vegetation", "hotspots", "frp_sum"]
    parts = []
    read_rows = kept_rows = 0
    for batch in pf.iter_batches(batch_size=262_144, columns=cols):
        read_rows += batch.num_rows
        mask = pc.and_(batch.column("is_vegetation"), pc.is_in(
            batch.column("confidence"), value_set=pa.array(["n", "h"])))
        mask = pc.and_(mask, pc.greater_equal(batch.column("cell_lon"), CANADA[0]))
        mask = pc.and_(mask, pc.less_equal(batch.column("cell_lon"), CANADA[2]))
        mask = pc.and_(mask, pc.greater_equal(batch.column("cell_lat"), CANADA[1]))
        mask = pc.and_(mask, pc.less_equal(batch.column("cell_lat"), CANADA[3]))
        mask = pc.and_(mask, pc.is_in(batch.column("satellite"),
                                      value_set=pa.array(["Terra", "Aqua", "SNPP"])))
        filtered = batch.filter(mask)
        kept_rows += filtered.num_rows
        if filtered.num_rows:
            parts.append(filtered.to_pandas())
    return (pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols),
            read_rows, kept_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/derived/monthly_grid_025.parquet")
    ap.add_argument("--staging", default="data/cleaned_canada.parquet")
    ap.add_argument("--monthly", default="data/monthly.parquet")
    args = ap.parse_args()

    rows, read_rows, kept_rows = grid_rows(args.input)
    if rows.empty:
        raise SystemExit("No rows passed the required grid filters")
    rows = (rows.groupby(["cell_lat", "cell_lon", "year", "month", "satellite", "daynight"],
                         as_index=False, sort=False)
                 .agg(hotspots=("hotspots", "sum"), frp_sum=("frp_sum", "sum")))
    rows["sensor"] = rows["satellite"].map(
        {"Terra": "MODIS", "Aqua": "MODIS", "SNPP": "VIIRS_SNPP"})
    rows["mean_frp"] = rows["frp_sum"] / rows["hotspots"]
    rows = rows[["cell_lat", "cell_lon", "year", "month", "sensor", "satellite", "daynight",
                 "hotspots", "frp_sum", "mean_frp"]]

    key = ["cell_lat", "cell_lon", "year", "month"]
    monthly = rows[key].drop_duplicates().copy()
    modis = rows.loc[rows["sensor"] == "MODIS"].groupby(key)["hotspots"].sum()
    viirs = rows.loc[rows["sensor"] == "VIIRS_SNPP"].groupby(key)["hotspots"].sum()
    frp = rows.groupby(key)["frp_sum"].sum()
    monthly = monthly.merge(modis.rename("modis_count"), on=key, how="left")
    monthly = monthly.merge(viirs.rename("viirs_count"), on=key, how="left")
    monthly = monthly.merge(frp.rename("frp_sum"), on=key, how="left")
    monthly[["modis_count", "viirs_count"]] = monthly[["modis_count", "viirs_count"]].fillna(0).astype("int64")
    monthly["total_count"] = monthly["modis_count"] + monthly["viirs_count"]
    monthly["mean_frp"] = monthly["frp_sum"] / monthly["total_count"]
    monthly["cell_id"] = monthly["cell_lat"].astype(str) + "_" + monthly["cell_lon"].astype(str)
    monthly["harmonized_count"] = float("nan")
    monthly = monthly[["cell_id", "cell_lat", "cell_lon", "year", "month",
                       "modis_count", "viirs_count", "total_count", "mean_frp",
                       "harmonized_count"]]

    # November 2026 is incomplete in the source release and is not emitted.
    monthly = monthly.loc[~((monthly["year"] == 2026) & (monthly["month"] == 11))]
    for output, frame in ((args.staging, rows), (args.monthly, monthly)):
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(output, index=False)
    print(f"source rows read: {read_rows:,}")
    print(f"rows after filters and satellite selection: {kept_rows:,}")
    print(f"staging rows: {len(rows):,}")
    print(f"monthly rows: {len(monthly):,}")
    print("satellite/year hotspot totals:")
    print(rows.groupby(["satellite", "year"])["hotspots"].sum().to_string())
    print(f"monthly date range: {monthly['year'].min()}-{monthly['month'].min():02d} to "
          f"{monthly['year'].max()}-{monthly['month'].max():02d}")
    print("excluded partial month: 2026-11")


if __name__ == "__main__":
    main()
