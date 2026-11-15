"""Candidate MODIS -> S-NPP rules for the v2 harness. Each has fit(train units) and predict(test units)."""
import numpy as np, pandas as pd
import lightgbm as lgb

BK = ["region", "bla", "blo"]          # block key
TK = ["tla", "tlo"]                    # tile key


def _ratio(g, prior=None, k=0.0):
    if prior is None:
        return g.s_n / g.m.clip(lower=1)
    return (g.s_n + k * prior) / (g.m + k)


def _season(month):
    return np.where((month >= 5) & (month <= 9), "fire", "off")


# ---------------------------------------------------------------- old and shipped rules, per region
class OldRatio:
    """Single ratio per region x fixed season x day/night (the rule before issue #37)."""
    def fit(self, tr):
        g = tr.assign(se=_season(tr.month.values)).groupby(["region", "se", "dn"])[["s_n", "m"]].sum()
        self.r = _ratio(g)
        return self

    def predict(self, te):
        idx = pd.MultiIndex.from_arrays([te.region.values, _season(te.month.values), te.dn.values])
        return te.m.values * self.r.reindex(idx).fillna(self.r.mean()).values


class Shipped:
    """Issue #37 rule: 1-degree block ratio shrunk to the region ratio, blended 50/50 with the same
    estimate rescaled by a region power law per calendar month x day/night."""
    def __init__(self, k=200, w=0.5):
        self.k, self.w = k, w

    def fit(self, tr):
        d = tr.assign(se=_season(tr.month.values))
        reg = d.groupby(["region", "se", "dn"])[["s_n", "m"]].sum()
        self.rr = _ratio(reg)
        b = d.groupby([*BK, "se", "dn"])[["s_n", "m"]].sum()
        prior = self.rr.reindex(pd.MultiIndex.from_arrays(
            [b.index.get_level_values("region"), b.index.get_level_values("se"), b.index.get_level_values("dn")])).values
        self.rb = _ratio(b, prior, self.k)
        rm = d.groupby(["region", "year", "month", "dn"], as_index=False)[["s_n", "m"]].sum()
        self.pl = {}
        for key, g in rm.groupby(["region", "month", "dn"]):
            pos = g[g.m > 0]
            x, y = np.log(pos.m.values), np.log1p(pos.s_n.values)
            if len(pos) < 5 or np.ptp(x) == 0:
                b_, a_, sm = 1.0, float(np.log((pos.s_n.sum() + 1) / max(pos.m.sum(), 1))), 1.0
            else:
                b_, a_ = np.polyfit(x, y, 1)
                sm = float(np.mean(np.exp(y - (a_ + b_ * x))))
            self.pl[key] = (a_, b_, sm)
        return self

    def predict(self, te):
        se = _season(te.month.values)
        rr = self.rr.reindex(pd.MultiIndex.from_arrays([te.region.values, se, te.dn.values])).values
        rb = self.rb.reindex(pd.MultiIndex.from_arrays([te.region.values, te.bla.values, te.blo.values, se, te.dn.values])).values
        rb = np.where(np.isnan(rb), rr, rb)
        region_m = te.groupby(["region", "t", "dn"]).m.transform("sum").values
        P = np.array([self.pl.get(k, (np.nan, np.nan, np.nan)) for k in zip(te.region.values, te.month.values, te.dn.values)])
        plp = np.maximum(np.exp(P[:, 0] + P[:, 1] * np.log(np.maximum(region_m, 1))) * P[:, 2] - 1, 0)
        lin = rr * region_m
        fac = np.where(np.isnan(P[:, 0]) | ~(lin > 0), 1.0, plp / np.maximum(lin, 1e-9))
        fac = np.where(np.isfinite(fac), fac, 1.0)
        return te.m.values * rb * (self.w + (1 - self.w) * fac)


# ---------------------------------------------------------------- shared encodings
def encodings(tr, k_blk=200, k_tile=2000, k_mon=500, cols=("s_n", "m")):
    """Ratio tables from training rows: world x dn -> tile x dn -> block x dn, plus a month profile."""
    s, m = cols
    f = tr[[*BK, *TK, "dn", "hmonth", s, m]].rename(columns={s: "s_n", m: "m"})
    g = f.groupby("dn")[["s_n", "m"]].sum(); r_g = _ratio(g)
    tile = f.groupby([*TK, "dn"])[["s_n", "m"]].sum()
    r_tile = _ratio(tile, r_g.reindex(tile.index.get_level_values("dn")).values, k_tile)
    blk = f.groupby([*BK, *TK, "dn"])[["s_n", "m"]].sum()
    pri = r_tile.reindex(pd.MultiIndex.from_arrays([blk.index.get_level_values(c) for c in [*TK, "dn"]])).values
    r_blk = _ratio(blk, pri, k_blk).droplevel(TK)
    tm = f.groupby([*TK, "hmonth", "dn"])[["s_n", "m"]].sum()
    pri = r_tile.reindex(pd.MultiIndex.from_arrays([tm.index.get_level_values(c) for c in [*TK, "dn"]])).values
    r_tm = _ratio(tm, pri, k_mon) / pri
    gm = f.groupby(["hmonth", "dn"])[["s_n", "m"]].sum()
    r_gm = _ratio(gm) / r_g.reindex(gm.index.get_level_values("dn")).values
    bm = f.groupby([*BK, "hmonth", "dn"])[["s_n", "m"]].sum()
    pri = r_blk.reindex(pd.MultiIndex.from_arrays([bm.index.get_level_values(c) for c in [*BK, "dn"]])).values
    r_bm = _ratio(bm, pri, k_blk) / pri
    return {"g": r_g, "tile": r_tile, "blk": r_blk, "tm": r_tm, "gm": r_gm, "bm": r_bm}


def apply_enc(d, E):
    def get(tab, keys):
        return tab.reindex(pd.MultiIndex.from_arrays([d[c].values for c in keys])).values
    r_g = E["g"].reindex(d.dn.values).values
    r_tile = get(E["tile"], [*TK, "dn"]); r_tile = np.where(np.isnan(r_tile), r_g, r_tile)
    r_blk = get(E["blk"], [*BK, "dn"]); r_blk = np.where(np.isnan(r_blk), r_tile, r_blk)
    r_gm = get(E["gm"], ["hmonth", "dn"]); r_gm = np.where(np.isnan(r_gm), 1.0, r_gm)
    r_tm = get(E["tm"], [*TK, "hmonth", "dn"]); r_tm = np.where(np.isnan(r_tm), r_gm, r_tm)
    r_bm = get(E["bm"], [*BK, "hmonth", "dn"]); r_bm = np.where(np.isnan(r_bm), 1.0, r_bm)
    return r_g, r_tile, r_blk, r_tm, r_bm


def oof_enc(tr, **kw):
    """Encodings for training rows computed without their own year (so the model can't lean on leakage)."""
    out = [np.empty(len(tr)) for _ in range(5)]
    for y in np.unique(tr.year.values):
        mask = tr.year.values == y
        vals = apply_enc(tr[mask], encodings(tr[~mask], **kw))
        for o, v in zip(out, vals):
            o[mask] = v
    return out


class Hier:
    """Ratio family with the weak spots fixed: hemisphere-aware month profile instead of a fixed season,
    world -> tile -> block shrinkage instead of hand-drawn boxes."""
    def __init__(self, k_blk=200, k_tile=2000, k_mon=500, month="tile"):
        self.kw, self.month = dict(k_blk=k_blk, k_tile=k_tile, k_mon=k_mon), month

    def fit(self, tr):
        self.E = encodings(tr, **self.kw); return self

    def predict(self, te):
        r_g, r_tile, r_blk, r_tm, r_bm = apply_enc(te, self.E)
        mon = {"none": 1.0, "tile": r_tm, "block": r_bm}[self.month]
        return te.m.values * r_blk * mon
