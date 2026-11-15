"""Gradient-boosted MODIS -> S-NPP rule for the v2 harness."""
import numpy as np, pandas as pd
import lightgbm as lgb
from models import BK, TK, encodings, apply_enc


def _div(a, b):
    return a / np.maximum(b, 1)


def features(d, enc, clim=None, xenc=None):
    r_g, r_tile, r_blk, r_tm, r_bm = enc
    v = {c: d[c].values.astype(np.float64) for c in d.columns if d[c].dtype.kind in "fiu"}
    m, tn, an = v["m"], v["t_n"], v["a_n"]
    X = {
        "lm": np.log1p(m), "lt": np.log1p(tn), "la": np.log1p(an), "aq_share": _div(an, m),
        "frp_mean": np.log1p(_div(v["frp"], m)), "frp_t": np.log1p(_div(v["t_frp"], tn)), "frp_a": np.log1p(_div(v["a_frp"], an)),
        "lfrp": _div(v["m_lfrp"], m), "lmaxfrp": np.log1p(v["m_maxfrp"]),
        "lo_share": v["lo"] / np.maximum(m + v["lo"], 1), "hi_share": _div(v["m_hi"], m),
        "area": _div(v["m_area"], m), "dt": _div(v["m_dt"], m), "t31": _div(v["m_t31"], m), "hot": _div(v["m_hot"], m),
        "spread": _div(v["m_sub"], m), "sqrt_share": v["m_sqrt"] / np.sqrt(np.maximum(m, 1)),
        "days": v["m_days"], "t_days": v["t_days"], "a_days": v["a_days"], "per_day": _div(m, v["m_days"]),
        "peak_share": _div(v["m_max"], m), "lncell": np.log1p(v["ncell"]),
        # other half of the day, neighbours in time and space, 10-degree tile
        "lm_o": np.log1p(v["m_o"]), "dn_share": m / np.maximum(m + v["m_o"], 1), "frp_o": np.log1p(_div(v["frp_o"], v["m_o"])),
        "lfrp_o": _div(v["m_lfrp_o"], v["m_o"]), "lmaxfrp_o": np.log1p(v["m_maxfrp_o"]), "days_o": v["m_days_o"],
        "lo_o": np.log1p(v["lo_o"]), "hi_o": _div(v["m_hi_o"], v["m_o"]), "la_o": np.log1p(v["a_n_o"]), "lt_o": np.log1p(v["t_n_o"]),
        "lm_prev": np.log1p(v["m_prev"]), "lm_next": np.log1p(v["m_next"]),
        "now_share": m / np.maximum(m + v["m_prev"] + v["m_next"], 1),
        "lnbr": np.log1p(v["nbr_m"]), "nbr_share": m / np.maximum(v["nbr_m"], 1),
        "ltile": np.log1p(v["tile_m"]), "tile_share": m / np.maximum(v["tile_m"], 1),
        "tile_frp": np.log1p(_div(v["tile_frp"], v["tile_m"])), "tile_lo": v["tile_lo"] / np.maximum(v["tile_m"] + v["tile_lo"], 1),
        "tile_hi": _div(v["tile_m_hi"], v["tile_m"]), "ltile_o": np.log1p(v["tile_m_o"]),
        "lat": v["bla"], "abslat": np.abs(v["bla"]), "lon": v["blo"],
        "hsin": np.sin(2 * np.pi * v["hmonth"] / 12), "hcos": np.cos(2 * np.pi * v["hmonth"] / 12),
        "night": (d.dn.values == "N").astype(float),
        "e_g": np.log(r_g), "e_tile": np.log(r_tile / r_g), "e_blk": np.log(r_blk / r_tile),
        "e_tm": np.log(np.maximum(r_tm, 1e-3)), "e_bm": np.log(np.maximum(r_bm, 1e-3)),
    }
    for p_, n_ in (("t", tn), ("a", an)):
        for b in ("s1", "s2", "s4", "f1", "f2", "f4", "f5"):
            X[f"{p_}_{b}"] = _div(v[f"{p_}_{b}"], n_)
    for b in ("s1", "s4", "f1", "f5"):
        X[f"m_{b}"] = _div(v[f"t_{b}"] + v[f"a_{b}"], m)
    if clim is not None:
        c = clim.reindex(pd.MultiIndex.from_arrays([d[k].values for k in [*TK, "month", "dn"]])).values
        X["tile_anom"] = np.log1p(v["tile_m"]) - np.log1p(np.nan_to_num(c))
    if xenc is not None:
        X["lx"] = np.log1p(v["m_o"] * xenc)
    return pd.DataFrame(X, index=d.index)


RAW = ["lo_share", "hi_share", "area", "dt", "t31", "hot", "spread", "sqrt_share", "days", "t_days", "a_days", "per_day",
       "peak_share", "lfrp", "lmaxfrp", "m_s1", "m_s4", "m_f1", "m_f5"] + \
      [f"{p}_{b}" for p in "ta" for b in ("s1", "s2", "s4", "f1", "f2", "f4", "f5")]
CONTEXT = ["lm_o", "dn_share", "frp_o", "lfrp_o", "lmaxfrp_o", "days_o", "lo_o", "hi_o", "la_o", "lt_o", "lm_prev", "lm_next",
           "now_share", "lnbr", "nbr_share", "tile_frp", "tile_lo", "tile_hi", "ltile_o"]


class GBM:
    """LightGBM (Poisson) in three parts:
    main - block-months with MODIS in this half of the day: a multiplicative correction to MODIS x block ratio;
    zero - no MODIS in this half of the day but some MODIS evidence (other half, or low confidence);
    none - no MODIS evidence at all: the block's average S-NPP under that condition (climatology)."""
    def __init__(self, params=None, rounds=400, drop=(), enc_kw=None, zero_rounds=200, seed=0):
        self.params = dict(objective="poisson", learning_rate=0.05, num_leaves=31, min_data_in_leaf=100,
                           feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
                           max_bin=255, verbose=-1, num_threads=12, seed=seed)
        self.params.update(params or {})
        self.rounds, self.zero_rounds, self.drop, self.enc_kw = rounds, zero_rounds, list(drop), enc_kw or {}

    def _xenc(self, tr):
        """S-NPP per other-half MODIS detection, for rows with no MODIS in their own half."""
        z = tr[(tr.m <= 0) & (tr.m_o > 0)]
        return encodings(z, cols=("s_n", "m_o"), k_blk=50, k_tile=500)

    def _X(self, d, enc, xr):
        X = features(d, enc, self.clim, xr)
        return X.drop(columns=[c for c in self.drop if c in X.columns])

    def fit(self, tr):
        self.clim = tr.groupby([*TK, "year", "month", "dn"]).m.sum().groupby(level=[0, 1, 3, 4]).mean()
        years = np.unique(tr.year.values)
        enc = [np.empty(len(tr)) for _ in range(5)]; xr = np.empty(len(tr))
        for y in years:                                   # encodings without the row's own year
            mk = tr.year.values == y
            for o, val in zip(enc, apply_enc(tr[mk], encodings(tr[~mk], **self.enc_kw))):
                o[mk] = val
            xr[mk] = apply_enc(tr[mk], self._xenc(tr[~mk]))[2]
        xr = np.nan_to_num(xr)
        X = self._X(tr, enc, xr)
        self.cols = list(X.columns)
        Xv = X.values.astype(np.float32); del X
        pos = (tr.m > 0).values
        base = np.log(np.maximum(tr.m.values[pos].astype(np.float64) * enc[2][pos], 1e-6))
        self.main = lgb.train(self.params, lgb.Dataset(Xv[pos], label=tr.s_n.values[pos], init_score=base,
                              feature_name=self.cols), num_boost_round=self.rounds)
        zr = ((tr.m <= 0) & tr.ev).values
        only_lo = zr & (tr.m_o.values <= 0)
        self.c0 = max(float(tr.s_n.values[only_lo].mean()) if only_lo.any() else 0.05, 1e-3)
        base0 = np.log(tr.m_o.values[zr].astype(np.float64) * xr[zr] + self.c0)
        zp = dict(self.params, num_leaves=15, min_data_in_leaf=200)
        self.zero = lgb.train(zp, lgb.Dataset(Xv[zr], label=tr.s_n.values[zr], init_score=base0,
                              feature_name=self.cols), num_boost_round=self.zero_rounds)
        self.E, self.XE = encodings(tr, **self.enc_kw), self._xenc(tr)
        # No-evidence climatology: mean S-NPP over the training years in which this block x month x day/night
        # had no MODIS evidence (years with no row at all count as 0; years with evidence are left out).
        zk = [*BK, "month", "dn"]
        s_none = tr[~tr.ev].groupby(zk).s_n.sum()
        n_ev = tr[tr.ev].groupby(zk).size().reindex(s_none.index).fillna(0).values
        n_all = tr[["year", "month"]].drop_duplicates().groupby("month").size().reindex(s_none.index.get_level_values("month")).values
        z = s_none / np.maximum(n_all - n_ev, 1)
        self.z = z[z > 0]
        return self

    def predict(self, te):
        enc = apply_enc(te, self.E); xr = np.nan_to_num(apply_enc(te, self.XE)[2])
        X = self._X(te, enc, xr)[self.cols].values.astype(np.float32)
        m = te.m.values.astype(np.float64)
        main = m * enc[2] * np.exp(self.main.predict(X, raw_score=True))
        zero = (te.m_o.values * xr + self.c0) * np.exp(self.zero.predict(X, raw_score=True))
        z = self.z.reindex(pd.MultiIndex.from_arrays([te[c].values for c in [*BK, "month", "dn"]])).fillna(0).values
        return np.where(m > 0, main, np.where(te.ev.values, zero, z))

    def zero_rows(self, te):
        """Block-months with no row at all in the test year still get their expected S-NPP."""
        z = self.z.reset_index(name="pred")
        out = []
        for (y, mo), g in te.groupby(["year", "month"]):
            have = set(zip(g.region, g.bla, g.blo, g.dn))
            zz = z[z.month == mo]
            keep = [k not in have for k in zip(zz.region, zz.bla, zz.blo, zz.dn)]
            out.append(zz[keep].assign(year=y, t=y * 12 + mo - 1, s_n=0.0, m=0.0))
        return pd.concat(out) if out else None
