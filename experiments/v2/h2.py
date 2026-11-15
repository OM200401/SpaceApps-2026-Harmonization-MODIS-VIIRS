"""v2 harness: block-month units built from the matched-day monthly table, fold runner and scoring.

Units are (region, bla, blo, year, month, dn) at L degrees. `region` is one of the 8 scoring boxes or
'rest'; WORLD scores use every unit. Every block-month has both a day and a night row, so a night
estimate can lean on daytime MODIS. Context for models comes from fixed TILE-degree tiles, not from
the scoring boxes, so the same rule works anywhere on Earth.
"""
import os, warnings
import duckdb, numpy as np, pandas as pd
warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = os.path.join(ROOT, "data", "experiments_v2").replace("\\", "/")
REGIONS = {"canada": (-140, 42, -52, 72), "amazon": (-75, -15, -45, 5), "mediterranean": (-10, 35, 30, 45),
           "us_west": (-125, 31, -102, 49), "siberia": (90, 50, 140, 70), "s_africa": (12, -20, 40, -5),
           "se_asia": (92, 10, 110, 25), "n_australia": (120, -20, 150, -11)}
STABLE = (2012, 2021)   # Terra/Aqua overpass times are steady through 2021, then drift
FIRST = 201206          # S-NPP ran low in its first months (Mar 2012: -20% against MODIS); start in June 2012
TILE = 10.0
BINS = [f"{p}_s{i}" for p in "ta" for i in range(1, 5)] + [f"{p}_f{i}" for p in "ta" for i in range(1, 6)]
SUM = ["t_n", "a_n", "t_frp", "a_frp", "t_lo", "a_lo", "m_hi", *BINS, "m_lfrp", "m_area", "m_dt", "m_t31", "m_hot",
       "m_sub", "s_n", "s_frp", "s_lo", "m_sqrt", "t_sqrt", "a_sqrt", "t_days", "a_days", "m_days", "j_n", "s_n_j"]
MAX = ["m_maxfrp", "m_max"]
KEY = ["region", "bla", "blo", "year", "month"]
CROSS = ["m", "t_n", "a_n", "frp", "lo", "m_days", "m_maxfrp", "m_hi", "m_lfrp"]


def load(L=1.0, src=None, cache=True, first=FIRST):
    """Block-month units at L degrees from first (yyyymm) onward, day and night rows for every block-month."""
    src = src or f"{D}/month.parquet"
    cpath = f"{D}/units_L{L:g}.parquet"
    if cache and src.endswith("/month.parquet") and os.path.exists(cpath) and os.path.getmtime(cpath) > os.path.getmtime(src):
        return pd.read_parquet(cpath)
    case = " ".join(f"WHEN cell_lon BETWEEN {w} AND {e} AND cell_lat BETWEEN {s} AND {n} THEN '{k}'"
                    for k, (w, s, e, n) in REGIONS.items())
    have = set(duckdb.sql(f"DESCRIBE SELECT * FROM '{src}'").df().column_name)
    def agg(c, f): return f"{f}({c})::FLOAT AS {c}" if c in have else f"0::FLOAT AS {c}"
    u = duckdb.sql(f"""
      SELECT coalesce(CASE {case} END, 'rest') AS region,
             floor(cell_lat / {L} + 1e-9) * {L} AS bla, floor(cell_lon / {L} + 1e-9) * {L} AS blo,
             year, month, dn, {", ".join(agg(c, "sum") for c in SUM)},
             {", ".join(agg(c, "max") for c in MAX)},
             count(*) FILTER (WHERE t_n + a_n > 0)::FLOAT AS ncell
      FROM '{src}' WHERE year * 100 + month >= {first} GROUP BY ALL""").df()
    u = finish(u, L)
    if cache and src.endswith("/month.parquet"):
        u.to_parquet(cpath, index=False)
    return u


def finish(u, L):
    """Complete day/night pairs and add cross day/night, lag, neighbour and tile context columns."""
    keys = u[KEY].drop_duplicates()
    full = pd.concat([keys.assign(dn="D"), keys.assign(dn="N")], ignore_index=True)
    u = full.merge(u, on=[*KEY, "dn"], how="left")
    num = [c for c in u.columns if c not in (*KEY, "dn")]
    u[num] = u[num].fillna(0).astype(np.float32)
    u = u.sort_values([*KEY, "dn"]).reset_index(drop=True)          # D row then N row for each block-month
    u["m"] = u.t_n + u.a_n
    u["frp"] = u.t_frp + u.a_frp
    u["lo"] = u.t_lo + u.a_lo
    for c in CROSS:                                                  # the other half of the day
        v = u[c].values.reshape(-1, 2)
        u[c + "_o"] = v[:, ::-1].reshape(-1)
    u["ev"] = (u.m + u.lo + u.m_o + u.lo_o) > 0                      # any MODIS evidence this block-month
    u["t"] = (u.year * 12 + u.month - 1).astype(np.int32)
    u["tla"] = (np.floor(u.bla / TILE) * TILE).astype(np.float32)
    u["tlo"] = (np.floor(u.blo / TILE) * TILE).astype(np.float32)
    u["hmonth"] = np.where(u.bla < 0, (u.month + 5) % 12 + 1, u.month).astype(np.int8)  # 1 = local midwinter
    g = u.groupby(["bla", "blo", "t", "dn"], as_index=False).m.sum()
    for name, dt in (("m_prev", 1), ("m_next", -1)):                 # same block, month before / after
        sh = g.assign(t=g.t + dt).rename(columns={"m": name})
        u = u.merge(sh, on=["bla", "blo", "t", "dn"], how="left")
    acc = np.zeros(len(u), np.float32)
    for dla in (-L, 0, L):                                           # 3x3 blocks incl. self
        for dlo in (-L, 0, L):
            sh = g.assign(bla=np.round(g.bla + dla, 4), blo=np.round(g.blo + dlo, 4)).rename(columns={"m": "_n"})
            acc += u[["bla", "blo", "t", "dn"]].merge(sh, on=["bla", "blo", "t", "dn"], how="left")._n.fillna(0).values
    u["nbr_m"] = acc
    tk = ["tla", "tlo", "t", "dn"]
    for c in ("m", "frp", "lo", "m_o", "m_hi"):
        u["tile_" + c] = u.groupby(tk)[c].transform("sum")
    u[["m_prev", "m_next"]] = u[["m_prev", "m_next"]].fillna(0).astype(np.float32)
    return u.reset_index(drop=True)


def score_frame(d, pred_col="pred", actual="s_n"):
    """Metrics on monthly totals (day + night) of one area."""
    rm = d.groupby("t")[[pred_col, actual]].sum()
    rm = rm[rm[actual] > 0]
    e = rm[pred_col] - rm[actual]
    yr = d.groupby("year")[[pred_col, actual]].sum()
    big = rm[rm[actual] >= 0.01 * rm[actual].sum() / max(len(rm), 1) * 12]  # months with >= 1% of a mean year
    eb = big[pred_col] - big[actual]
    return {"MAPE": (e.abs() / rm[actual]).mean(), "MAPE_main": (eb.abs() / big[actual]).mean(),
            "WAPE": e.abs().sum() / rm[actual].sum(), "bias": rm[pred_col].sum() / rm[actual].sum() - 1,
            "year_APE": ((yr[pred_col] - yr[actual]).abs() / yr[actual]).mean(),
            "year_max": ((yr[pred_col] - yr[actual]).abs() / yr[actual]).max(), "n": len(rm)}


def score_all(p, pred_col="pred", actual="s_n"):
    rows = {r: score_frame(p[p.region == r], pred_col, actual) for r in REGIONS}
    rows["WORLD"] = score_frame(p, pred_col, actual)
    return pd.DataFrame(rows).T


def _predict(model, te):
    p = te.assign(pred=model.predict(te))
    extra = model.zero_rows(te) if hasattr(model, "zero_rows") else None
    return p if extra is None else pd.concat([p, extra], ignore_index=True)


def loyo(u, make, years=None, verbose=False):
    """Leave-one-year-out inside the stable-orbit years. Returns test rows with `pred`."""
    lo, hi = STABLE
    pool = u[u.year.between(lo, hi)]
    out = []
    for ty in years or list(range(lo, hi + 1)):
        out.append(_predict(make().fit(pool[pool.year != ty]), pool[pool.year == ty]))
        if verbose:
            print(ty, "done", flush=True)
    return pd.concat(out)


def fixed(u, make, fit_years, test_years):
    tr, te = u[u.year.isin(list(fit_years))], u[u.year.isin(list(test_years))]
    return _predict(make().fit(tr), te)


def show(name, p, cols=("MAPE", "MAPE_main", "WAPE", "bias", "year_APE", "year_max")):
    s = score_all(p)[list(cols)] * 100
    print(f"\n== {name}")
    print(s.round(1).to_string())
    return s
