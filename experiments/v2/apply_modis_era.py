"""Fit the v2 rule on all stable overlap years and estimate S-NPP for every 0.25-degree cell, Nov 2000 - Jan 2012.

- Full model (Terra + Aqua) for July 2002 onward; Terra-only model (fitted with Aqua removed) before.
- Estimates are made per 1-degree block x month x day/night, scaled up for MODIS outage days, then split to
  0.25-degree cells:
    MODIS seen in that half of the day       -> by each cell's MODIS detections
    MODIS only in the other half / low conf. -> by each cell's other-half and low-confidence detections
    no MODIS evidence (climatology)          -> by each cell's share of the block's S-NPP in 2012-2021
- Cell values under MIN_NEW in cell-months with no MODIS row are dropped (about 0.25% of the total), to keep the app tiles small.

Needs: units_L1.parquet, units_terra.parquet, month.parquet (run_all.sh) and month_modis.parquet, exposure_modis.parquet
(build_daily.py --years 2000-2012 --out data/experiments_v2/daily_modis; build_month.py --modis-era ...).
Writes data/experiments_v2/v2_modis_era_cells.parquet (cell_lat, cell_lon, year, month, harmonized_v2)
and data/experiments_v2/models/ (LightGBM files of the two fitted models).

Usage: python apply_modis_era.py
"""
import os, pickle, time
import duckdb, numpy as np, pandas as pd
import h2
from gbm import GBM

ERA_END = 2012 * 12 + 1           # t of Feb 2012: observed S-NPP from here on
AQUA_T = 2002 * 12 + 6            # t of July 2002
MIN_NEW = 0.5
BK = ["region", "bla", "blo"]
UK = [*BK, "year", "month", "dn"]
make = lambda: GBM(params=dict(linear_tree=True, linear_lambda=1.0))
t0 = time.time()
os.makedirs(f"{h2.D}/models", exist_ok=True)


def fit(units, name):
    tr = units[units.year.between(*h2.STABLE)]
    m = make().fit(tr)
    m.main.save_model(f"{h2.D}/models/{name}_main.txt"); m.zero.save_model(f"{h2.D}/models/{name}_zero.txt")
    with open(f"{h2.D}/models/{name}_tables.pkl", "wb") as f:
        pickle.dump({k: getattr(m, k) for k in ("E", "XE", "z", "clim", "c0", "cols")}, f)
    print(f"fitted {name} on {len(tr):,} units ({time.time() - t0:.0f}s)", flush=True)
    return m


full = fit(h2.load(1.0), "full")
terra = fit(pd.read_parquet(f"{h2.D}/units_terra.parquet"), "terra")

# ---- MODIS-era units and block estimates
u = h2.load(1.0, src=f"{h2.D}/month_modis.parquet", cache=False, first=200011)
u = u[u.t < ERA_END].reset_index(drop=True)
parts = []
for model, sel in ((terra, u.t < AQUA_T), (full, u.t >= AQUA_T)):
    te = u[sel]
    p = te.assign(pred=model.predict(te))
    p["kind"] = np.where(p.m > 0, "main", np.where(p.ev, "zero", "none"))
    parts.append(p[[*UK, "pred", "kind"]])
    z = model.zero_rows(te)
    if z is not None:
        parts.append(z.assign(kind="none")[[*UK, "pred", "kind"]])
b = pd.concat(parts, ignore_index=True)
ex = pd.read_parquet(f"{h2.D}/exposure_modis.parquet")
ex["scale"] = ex.n_days / ex.kept.clip(lower=1)
b = b.merge(ex[["year", "month", "scale"]], on=["year", "month"], how="left")
b["pred"] *= b.scale.fillna(1.0)
print("block estimates:", b.groupby("kind").pred.sum().round(0).to_dict(), f"({time.time() - t0:.0f}s)", flush=True)

# ---- cell weights
case = " ".join(f"WHEN cell_lon BETWEEN {w} AND {e} AND cell_lat BETWEEN {s} AND {n} THEN '{k}'"
                for k, (w, s, e, n) in h2.REGIONS.items())
cells = duckdb.sql(f"""
  WITH c AS (SELECT cell_lat, cell_lon, year, month, dn, (t_n + a_n)::DOUBLE m, (t_lo + a_lo)::DOUBLE lo
             FROM '{h2.D}/month_modis.parquet' WHERE year * 12 + month - 1 < {ERA_END}),
  k AS (SELECT DISTINCT cell_lat, cell_lon, year, month FROM c),
  f AS (SELECT k.*, d.dn FROM k CROSS JOIN (VALUES ('D'), ('N')) d(dn))
  SELECT coalesce(CASE {case} END, 'rest') region, floor(f.cell_lat) bla, floor(f.cell_lon) blo, f.cell_lat, f.cell_lon,
         f.year, f.month, f.dn, coalesce(a.m, 0) m, coalesce(a.lo, 0) lo, coalesce(o.m, 0) m_o, coalesce(o.lo, 0) lo_o
  FROM f LEFT JOIN c a USING (cell_lat, cell_lon, year, month, dn)
         LEFT JOIN c o ON o.cell_lat = f.cell_lat AND o.cell_lon = f.cell_lon AND o.year = f.year AND o.month = f.month
                       AND o.dn <> f.dn""").df()
cells["w_main"] = cells.m
cells["w_zero"] = cells.m_o + cells.lo + cells.lo_o
share = duckdb.sql(f"""
  SELECT coalesce(CASE {case} END, 'rest') region, floor(cell_lat) bla, floor(cell_lon) blo, cell_lat, cell_lon, month, dn,
         sum(s_n)::DOUBLE w
  FROM '{h2.D}/month.parquet' WHERE year BETWEEN {h2.STABLE[0]} AND {h2.STABLE[1]} AND year * 100 + month >= {h2.FIRST}
  GROUP BY ALL HAVING sum(s_n) > 0""").df()


def split(blocks, weights, wcol, keys):
    j = blocks.merge(weights[[*keys, "cell_lat", "cell_lon", wcol]], on=keys, how="inner")
    j = j[j[wcol] > 0]
    j["cell_pred"] = j.pred * j[wcol] / j.groupby([*UK])[wcol].transform("sum")
    lost = blocks.pred.sum() - j.cell_pred.sum()
    return j[["cell_lat", "cell_lon", "year", "month", "dn", "cell_pred"]], lost


out, lost = [], {}
for kind, w, keys, wt in (("main", "w_main", UK, cells), ("zero", "w_zero", UK, cells),
                          ("none", "w", [*BK, "month", "dn"], share)):
    part, lost[kind] = split(b[b.kind == kind], wt, w, keys)
    out.append(part)
c = pd.concat(out).groupby(["cell_lat", "cell_lon", "year", "month"], as_index=False).cell_pred.sum()
c = c.rename(columns={"cell_pred": "harmonized_v2"})
has_modis = cells.groupby(["cell_lat", "cell_lon", "year", "month"]).agg(any_m=("m", "sum"), any_lo=("lo", "sum")).reset_index()
c = c.merge(has_modis, on=["cell_lat", "cell_lon", "year", "month"], how="left").fillna({"any_m": 0, "any_lo": 0})
small = (c.any_m + c.any_lo <= 0) & (c.harmonized_v2 < MIN_NEW)
print(f"not placed in a cell: { {k: round(v) for k, v in lost.items()} }; dropped tiny new cell-months: "
      f"{small.sum():,} rows, {c.harmonized_v2[small].sum():.0f} of {c.harmonized_v2.sum():.0f}")
c = c[~small][["cell_lat", "cell_lon", "year", "month", "harmonized_v2"]]
c.to_parquet(f"{h2.D}/v2_modis_era_cells.parquet", index=False)
print(f"wrote {len(c):,} cell-months, total {c.harmonized_v2.sum():,.0f} ({time.time() - t0:.0f}s)")
