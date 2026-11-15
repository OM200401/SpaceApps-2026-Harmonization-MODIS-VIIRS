#!/usr/bin/env python3
"""monthly_harmonized_global.parquet -> app/data/ tiles the web app loads on demand.

  app/data/index.json            tile sizes, last month, provisional month, archive dates
  app/data/d/<lat>_<lon>.json    0.25-degree cells in 10x10-degree tiles (regional views)
  app/data/c/<lat>_<lon>.json    1-degree cells in 30x30-degree chunks (continent and world views)

<lat>_<lon> is the tile's south-west corner. Each tile uses the column layout of the old monthly.json
cells block: cell_lat/cell_lon/n_months have one entry per cell, and the next n_months entries of
t/modis_count/viirs_count/harmonized_count belong to it; t = (year - t0_year) * 12 + (month - 1).
A 1-degree cell is the sum of its sixteen 0.25-degree cells; its cell_lat/cell_lon is the south-west corner.
See docs/UI_DATA_CONTRACT.md.
"""
import argparse, json, shutil
from pathlib import Path
import numpy as np
import pandas as pd
from export_json import T0_YEAR, ARCHIVE_END

LEVELS = {"d": {"cell": 0.25, "tile": 10}, "c": {"cell": 1.0, "tile": 30}}


def cells_block(m):
    m = m.sort_values(["cell_lat", "cell_lon", "year", "month"])
    per = m.groupby(["cell_lat", "cell_lon"], sort=False).size().reset_index(name="n_months")
    return {"t0_year": T0_YEAR, "cell_lat": per.cell_lat.round(4).tolist(), "cell_lon": per.cell_lon.round(4).tolist(),
            "n_months": per.n_months.tolist(), "t": ((m.year - T0_YEAR) * 12 + m.month - 1).tolist(),
            "modis_count": m.modis_count.astype(int).tolist(), "viirs_count": m.viirs_count.astype(int).tolist(),
            "harmonized_count": m.harmonized_count.round(1).tolist()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monthly", default="data/monthly_harmonized_global.parquet")
    ap.add_argument("--out", default="app/data")
    a = ap.parse_args()
    cols = ["cell_lat", "cell_lon", "year", "month", "modis_count", "viirs_count", "harmonized_count"]
    m = pd.read_parquet(a.monthly, columns=cols)
    out = Path(a.out)
    index = {"t0_year": T0_YEAR, "levels": LEVELS, "archive_end": ARCHIVE_END, "tiles": {}}
    end = (m.year * 12 + m.month).max()  # y*12+m of the last month with data
    index["end"] = {"year": int((end - 1) // 12), "month": int((end - 1) % 12 + 1)}
    first_nrt = pd.Timestamp(min(ARCHIVE_END.values())) + pd.Timedelta(days=1)
    index["provisional_from"] = {"year": first_nrt.year, "month": first_nrt.month}
    total_bytes = 0
    for lvl, spec in LEVELS.items():
        d = m
        if spec["cell"] != 0.25:
            d = (m.assign(cell_lat=np.floor(m.cell_lat / spec["cell"]) * spec["cell"], cell_lon=np.floor(m.cell_lon / spec["cell"]) * spec["cell"])
                   .groupby(["cell_lat", "cell_lon", "year", "month"], as_index=False)[["modis_count", "viirs_count", "harmonized_count"]].sum())
        tl = spec["tile"]
        d = d.assign(tla=(np.floor(d.cell_lat / tl) * tl).astype(int), tlo=(np.floor(d.cell_lon / tl) * tl).astype(int))
        shutil.rmtree(out / lvl, ignore_errors=True); (out / lvl).mkdir(parents=True)
        index["tiles"][lvl] = {}
        for (la, lo), g in d.groupby(["tla", "tlo"]):
            p = out / lvl / f"{la}_{lo}.json"
            p.write_text(json.dumps(cells_block(g), separators=(",", ":")))
            index["tiles"][lvl][f"{la}_{lo}"] = [len(g), p.stat().st_size]
            total_bytes += p.stat().st_size
        sz = [v[1] for v in index["tiles"][lvl].values()]
        print(f"{lvl}: {len(sz)} tiles, {len(d):,} cell-months, {sum(sz)/1e6:.1f} MB total, largest {max(sz)/1e6:.2f} MB")
    (out / "index.json").write_text(json.dumps(index, separators=(",", ":")))
    print(f"Wrote {out}/index.json; data through {index['end']}; provisional from {index['provisional_from']}; {total_bytes/1e6:.1f} MB of tiles")


if __name__ == "__main__":
    main()
