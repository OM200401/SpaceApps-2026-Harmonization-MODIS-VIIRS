"""Experiment harness: shared data, methods and scoring for MODIS -> S-NPP harmonization."""
import os, warnings
import duckdb, numpy as np, pandas as pd
from scipy.optimize import nnls
from sklearn.linear_model import PoissonRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Inputs and results live in data/experiments/ (git-ignored); override with EXP_DATA.
D = os.environ.get("EXP_DATA", os.path.join(ROOT, "data", "experiments")).replace("\\", "/")
os.makedirs(D, exist_ok=True)
LEVELS = [0.25, 0.5, 1, 2, 5, "region"]
SNPP_T0 = 2012 * 12 + 1  # Feb 2012 as t = year*12 + month-1


def load(conf=("n", "h")):
    c = "','".join(conf)
    df = duckdb.sql(f"""
      SELECT region, cell_lat, cell_lon, year, month, dn,
        coalesce(sum(hs) FILTER (WHERE sat='Terra'),0)::DOUBLE terra,
        coalesce(sum(hs) FILTER (WHERE sat='Aqua'),0)::DOUBLE aqua,
        coalesce(sum(hs) FILTER (WHERE sat='SNPP'),0)::DOUBLE snpp,
        coalesce(sum(frp) FILTER (WHERE sat='Terra'),0)::DOUBLE frp_t,
        coalesce(sum(frp) FILTER (WHERE sat='Aqua'),0)::DOUBLE frp_a
      FROM '{D}/cells.parquet' WHERE conf IN ('{c}') GROUP BY ALL""").df()
    df["modis"] = df.terra + df.aqua
    df["t"] = df.year * 12 + df.month - 1
    return df


def world():
    w = duckdb.sql(f"SELECT * FROM '{D}/world.parquet'").df()
    w = w.pivot_table(index=["year", "month", "dn"], columns="sat", values="hs", aggfunc="sum").fillna(0).reset_index()
    w["modis"] = w.Terra + w.Aqua
    w["snpp"] = w.SNPP
    return w


def tables(cells):
    """Aggregate one region's cells to every level. Units are (bla, blo, t, dn)."""
    T = {}
    for L in LEVELS:
        d = cells
        if L == "region":
            bla = blo = np.zeros(len(d))
        else:
            bla = np.floor(d.cell_lat.values / L + 1e-9) * L
            blo = np.floor(d.cell_lon.values / L + 1e-9) * L
        g = d.assign(bla=bla, blo=blo, ncell=(d.modis > 0).astype(float)).groupby(
            ["bla", "blo", "year", "month", "t", "dn"], as_index=False)[
            ["terra", "aqua", "modis", "snpp", "frp_t", "frp_a", "ncell"]].sum()
        g["L"] = L
        T[L] = g
    return T


# ---------- strata ----------
def strata(df, kind, peak=None):
    m, dn = df.month.values, df.dn.values
    if kind == "none":
        return pd.Series(np.full(len(df), "all"), index=df.index)
    if kind == "dn":
        return pd.Series(dn, index=df.index)
    if kind == "season_dn":
        s = np.where((m >= 5) & (m <= 9), "fire", "off")
    elif kind == "peak_dn":
        s = np.where(np.isin(m, peak), "fire", "off")
    elif kind == "month_dn":
        s = m.astype(str)
    else:
        raise ValueError(kind)
    return pd.Series(np.char.add(np.char.add(s.astype(str), "_"), dn.astype(str)), index=df.index)


def peak_months(tr, n=5):
    clim = tr.groupby("month").modis.sum()
    return clim.nlargest(n).index.values


def parent_key(k):
    """month_dn -> season_dn style parent for shrinkage"""
    mo, dn = k.split("_")
    return ("fire" if 5 <= int(mo) <= 9 else "off") + "_" + dn


# ---------- methods: fit(train units) / predict(test units) -> pred per test row ----------
class Ratio:
    """S-NPP = r(stratum) * MODIS. Optional shrinkage of fine strata toward a parent ratio."""
    def __init__(self, kind="season_dn", k=0.0, min_m=50, world_df=None, terra_only=False):
        self.kind, self.k, self.min_m, self.world, self.terra_only = kind, k, min_m, world_df, terra_only
        self.level = 1

    def _ratio_table(self, tr):
        key = strata(tr, self.kind, self.peak)
        g = tr.groupby(key)[["snpp", "modis"]].sum()
        r = g.snpp / g.modis.clip(lower=1)
        dn_r = tr.groupby("dn")[["snpp", "modis"]].sum()
        dn_r = dn_r.snpp / dn_r.modis.clip(lower=1)
        if self.kind == "month_dn" and self.k > 0:
            par = tr.assign(_s=strata(tr, "season_dn")).groupby("_s")[["snpp", "modis"]].sum()
            par = par.snpp / par.modis.clip(lower=1)
            rp = pd.Series([par.get(parent_key(i), np.nan) for i in g.index], index=g.index)
            r = (g.snpp + self.k * rp) / (g.modis + self.k)
        thin = g.modis < self.min_m
        if thin.any():
            r[thin] = [dn_r.get(i.split("_")[-1], r.mean()) for i in r.index[thin]]
        return r

    def fit(self, tr):
        self.peak = peak_months(tr) if self.kind == "peak_dn" else None
        if self.world is not None:  # global ratios from world totals for the same years
            w = self.world[self.world.year.isin(tr.year.unique())]
            w = w[w.year * 12 + w.month - 1 >= tr.t.min()]
            key = strata(w, self.kind)
            g = w.groupby(key)[["snpp", "modis"]].sum()
            self.r = g.snpp / g.modis
        else:
            self.r = self._ratio_table(tr)
        self.r_all = tr.snpp.sum() / max(tr.modis.sum(), 1)
        return self

    def predict(self, te):
        key = strata(te, self.kind, self.peak)
        return te.modis.values * key.map(self.r).fillna(self.r_all).values


class AquaTerra:
    """S-NPP = a*Aqua + b*Terra per stratum, non-negative least squares on region-month totals."""
    def __init__(self, kind="season_dn", weight="none"):
        self.kind, self.weight, self.level = kind, weight, 1

    def fit(self, tr):
        self.peak = peak_months(tr) if self.kind == "peak_dn" else None
        key = strata(tr, self.kind, self.peak)
        rm = tr.assign(_s=key).groupby(["_s", "t"])[["aqua", "terra", "snpp"]].sum().reset_index()
        self.coef = {}
        for s, g in rm.groupby("_s"):
            X, y = g[["aqua", "terra"]].values, g.snpp.values
            w = 1 / np.sqrt(y + 10) if self.weight == "rel" else np.ones(len(y))
            self.coef[s] = nnls(X * w[:, None], y * w)[0]
        tot = rm[["aqua", "terra"]].sum()
        self.fallback = np.array([rm.snpp.sum() / max(tot.sum(), 1)] * 2)
        return self

    def predict(self, te):
        key = strata(te, self.kind, self.peak)
        c = np.vstack([self.coef.get(s, self.fallback) for s in key])
        return c[:, 0] * te.aqua.values + c[:, 1] * te.terra.values


def uplift(tr, key):
    """Share of S-NPP in units with no MODIS (unpredictable from MODIS) -> multiplier per stratum."""
    g = tr.assign(_s=key, _z=tr.modis <= 0).groupby("_s").apply(
        lambda x: x.loc[x._z, "snpp"].sum() / max(x.snpp.sum(), 1), include_groups=False)
    return (1 / (1 - g.clip(upper=0.5)))


class PowerLaw:
    """log1p(S) = a + b*log(M) per stratum on units at a chosen level, smearing back-transform."""
    def __init__(self, level="region", kind="season_dn"):
        self.level, self.kind = level, kind

    def fit(self, tr):
        self.peak = peak_months(tr) if self.kind == "peak_dn" else None
        key = strata(tr, self.kind, self.peak)
        self.up = uplift(tr, key)
        A = tr[tr.modis > 0]; ka = key[tr.modis > 0]
        self.p = {}
        for s, idx in ka.groupby(ka).groups.items():
            x, y = np.log(A.loc[idx, "modis"].values), np.log1p(A.loc[idx, "snpp"].values)
            if len(x) < 5 or np.ptp(x) == 0:
                b, a = 1.0, np.log((A.loc[idx, "snpp"].sum() + 1) / A.loc[idx, "modis"].sum())
            else:
                b, a = np.polyfit(x, y, 1)
            res = y - (a + b * x)
            self.p[s] = (a, b, np.mean(np.exp(res)))
        self.default = (np.log(tr.snpp.sum() / max(tr.modis.sum(), 1)), 1.0, 1.0)
        return self

    def predict(self, te):
        key = strata(te, self.kind, self.peak)
        P = np.array([self.p.get(s, self.default) for s in key])
        m = te.modis.values
        pred = np.where(m > 0, np.exp(P[:, 0] + P[:, 1] * np.log(np.maximum(m, 1))) * P[:, 2] - 1, 0)
        return np.maximum(pred, 0) * key.map(self.up).fillna(1).values


def unit_features(u, region_tot=None):
    m = u.modis.values
    X = pd.DataFrame({
        "lm": np.log1p(m), "la": np.log1p(u.aqua.values), "lt": np.log1p(u.terra.values),
        "aqs": np.where(m > 0, u.aqua.values / np.maximum(m, 1), 0.5),
        "frp": np.log1p(np.where(m > 0, (u.frp_t.values + u.frp_a.values) / np.maximum(m, 1), 0)),
        "lnc": np.log1p(u.ncell.values),
        "dens": np.where(u.ncell.values > 0, m / np.maximum(u.ncell.values, 1), 0),
        "msin": np.sin(2 * np.pi * u.month.values / 12), "mcos": np.cos(2 * np.pi * u.month.values / 12),
        "night": (u.dn.values == "N").astype(float),
        "lat": u.bla.values, "lon": u.blo.values,
    }, index=u.index)
    if region_tot is not None:
        X["lreg"] = np.log1p(region_tot.values)
    return X


def add_context(u, L):
    """Neighbour MODIS (3x3 units incl. self) and region-wide MODIS for the same month/daynight."""
    u = u.copy()
    u["region_m"] = u.groupby(["t", "dn"]).modis.transform("sum")
    if L != "region":
        base = u[["bla", "blo", "t", "dn", "modis"]]
        acc = np.zeros(len(u))
        keyed = u[["bla", "blo", "t", "dn"]].reset_index()
        for dla in (-L, 0, L):
            for dlo in (-L, 0, L):
                sh = base.assign(bla=np.round(base.bla + dla, 4), blo=np.round(base.blo + dlo, 4))
                mg = keyed.assign(bla=np.round(keyed.bla, 4), blo=np.round(keyed.blo, 4)).merge(
                    sh, on=["bla", "blo", "t", "dn"], how="left")
                acc += mg.sort_values("index").modis.fillna(0).values
        u["nbr_m"] = acc
    else:
        u["nbr_m"] = u.modis
    return u


class PoissonGLM:
    """log E[S] = a + b*log(M) [+ extra terms] per stratum, Poisson likelihood (no back-transform bias)."""
    def __init__(self, level="region", kind="season_dn", extra=()):
        self.level, self.kind, self.extra = level, kind, list(extra)

    def _X(self, d):
        X = pd.DataFrame({"lm": np.log(np.maximum(d.modis.values, 1))}, index=d.index)
        if "aqs" in self.extra:
            X["aqs"] = d.aqua.values / np.maximum(d.modis.values, 1)
        if "frp" in self.extra:
            X["frp"] = np.log1p((d.frp_t.values + d.frp_a.values) / np.maximum(d.modis.values, 1))
        if "lreg" in self.extra:
            X["lreg"] = np.log1p(d.region_m.values)
        if "nbr" in self.extra:
            X["nbr"] = np.log1p(d.nbr_m.values)
        return X

    def fit(self, tr):
        self.peak = peak_months(tr) if self.kind == "peak_dn" else None
        key = strata(tr, self.kind, self.peak)
        self.up = uplift(tr, key)
        A = tr[tr.modis > 0]; ka = key[tr.modis > 0]
        self.m = {}
        for s, idx in ka.groupby(ka).groups.items():
            X, y = self._X(A.loc[idx]), A.loc[idx, "snpp"].values
            if len(y) < 10:
                continue
            mu, sd = X.mean(), X.std().replace(0, 1)
            self.m[s] = (PoissonRegressor(alpha=1e-4, max_iter=1000).fit((X - mu) / sd, y), mu, sd)
        self.r_all = tr.snpp.sum() / max(tr.modis.sum(), 1)
        return self

    def predict(self, te):
        key = strata(te, self.kind, self.peak)
        pred = te.modis.values * self.r_all
        X = self._X(te)
        for s, idx in key.groupby(key).groups.items():
            if s in self.m:
                mdl, mu, sd = self.m[s]
                pos = te.index.get_indexer(idx)
                pred[pos] = mdl.predict((X.loc[idx] - mu) / sd)
        pred = np.where(te.modis.values > 0, pred, 0)
        return pred * key.map(self.up).fillna(1).values


class SpatialRatio:
    """Per-unit ratio at a block level, shrunk toward the region ratio of the same stratum."""
    def __init__(self, level=1, k=200, kind="season_dn"):
        self.level, self.k, self.kind = level, k, kind

    def fit(self, tr):
        key = strata(tr, self.kind)
        reg = tr.groupby(key)[["snpp", "modis"]].sum()
        self.rr = reg.snpp / reg.modis.clip(lower=1)
        g = tr.assign(_s=key).groupby(["bla", "blo", "_s"])[["snpp", "modis"]].sum()
        rp = g.index.get_level_values("_s").map(self.rr).values
        self.rb = (g.snpp + self.k * rp) / (g.modis + self.k)
        return self

    def predict(self, te):
        key = strata(te, self.kind)
        idx = pd.MultiIndex.from_arrays([te.bla.values, te.blo.values, key.values])
        r = self.rb.reindex(idx).values
        r = np.where(np.isnan(r), key.map(self.rr).values, r)
        return te.modis.values * r


class FRPBins:
    """Ratio by stratum x MODIS mean-FRP bin, at a chosen level, plus MODIS-zero uplift."""
    def __init__(self, level=0.25, kind="season_dn", edges=(10, 20, 40, 80)):
        self.level, self.kind, self.edges = level, kind, edges

    def _bin(self, d):
        f = (d.frp_t.values + d.frp_a.values) / np.maximum(d.modis.values, 1)
        return pd.Series(np.digitize(f, self.edges).astype(str), index=d.index)

    def fit(self, tr):
        key = strata(tr, self.kind)
        self.up = uplift(tr, key)
        A = tr[tr.modis > 0]
        k2 = key[tr.modis > 0] + "|" + self._bin(A)
        g = A.groupby(k2)[["snpp", "modis"]].sum()
        g = g[g.modis >= 50]
        self.r = g.snpp / g.modis
        reg = A.groupby(key[tr.modis > 0])[["snpp", "modis"]].sum()
        self.rs = reg.snpp / reg.modis.clip(lower=1)
        return self

    def predict(self, te):
        key = strata(te, self.kind)
        k2 = key + "|" + self._bin(te)
        r = k2.map(self.r).values
        r = np.where(np.isnan(r), key.map(self.rs).values, r)
        return te.modis.values * r * key.map(self.up).fillna(1).values


class HGB:
    """Gradient-boosted trees, Poisson loss, MODIS-only features (incl. neighbours and region activity)."""
    def __init__(self, level=1, params=None, use_latlon=True):
        self.level, self.use_latlon = level, use_latlon
        self.params = dict(loss="poisson", learning_rate=0.06, max_iter=300, max_leaf_nodes=31,
                           min_samples_leaf=40, l2_regularization=1.0, random_state=0)
        self.params.update(params or {})

    def _X(self, d):
        X = unit_features(d, d.region_m)
        X["lnbr"] = np.log1p(d.nbr_m.values)
        if not self.use_latlon:
            X = X.drop(columns=["lat", "lon"])
        return X

    def fit(self, tr):
        self.up = uplift(tr, strata(tr, "season_dn"))
        A = tr[tr.modis > 0]
        self.m = HistGradientBoostingRegressor(**self.params).fit(self._X(A), A.snpp.values)
        return self

    def predict(self, te):
        p = np.where(te.modis.values > 0, self.m.predict(self._X(te)), 0)
        return p * strata(te, "season_dn").map(self.up).fillna(1).values


class SpatialPL:
    """Per-area shrunk ratios for *where*, rescaled each month by a region-level power law for *how much*.
    pred_unit = spatial_pred_unit * PL(region MODIS) / (r_region * region MODIS), per stratum and month."""
    def __init__(self, level=1, k=200, kind="season_dn", pl_kind=None):
        self.level, self.k, self.kind = level, k, kind
        self.pl_kind = pl_kind or kind

    def fit(self, tr):
        self.sp = SpatialRatio(self.level, self.k, self.kind).fit(tr)
        rm = tr.groupby(["t", "dn", "year", "month"], as_index=False)[["modis", "snpp", "terra", "aqua", "frp_t", "frp_a", "ncell"]].sum()
        self.pl = PowerLaw("region", self.pl_kind).fit(rm)
        return self

    def predict(self, te):
        sp = self.sp.predict(te)
        key = strata(te, self.kind)
        rr = key.map(self.sp.rr).values
        rm = te[["t", "dn", "year", "month", "region_m"]].drop_duplicates(["t", "dn"]).rename(columns={"region_m": "modis"})
        rm = rm.assign(terra=0.0, aqua=0.0, snpp=0.0, frp_t=0.0, frp_a=0.0, ncell=0.0).reset_index(drop=True)
        rm["plp"] = self.pl.predict(rm)
        f = te[["t", "dn"]].merge(rm[["t", "dn", "plp", "modis"]], on=["t", "dn"], how="left")
        lin = rr * f.modis.values
        fac = np.where(lin > 0, f.plp.values / np.maximum(lin, 1e-9), 1.0)
        return sp * fac


class Blend:
    """Weighted average of two fitted methods' predictions."""
    def __init__(self, a, b, w=0.5, level=1):
        self.a, self.b, self.w, self.level = a, b, w, level

    def fit(self, tr):
        self.a.fit(tr); self.b.fit(tr); return self

    def predict(self, te):
        return self.w * self.a.predict(te) + (1 - self.w) * self.b.predict(te)


# ---------- scoring ----------
def to_1deg(T, L, te_units, pred):
    """Prediction per 1-degree block-month for block metrics."""
    if L in (0.25, 0.5, 1):
        d = te_units.assign(pred=pred, b1a=np.floor(te_units.bla + 1e-9), b1o=np.floor(te_units.blo + 1e-9))
        return d.groupby(["b1a", "b1o", "t"]).pred.sum()
    one = T[1][T[1].t.isin(te_units.t.unique())].copy()
    if L == "region":
        one["ua"] = 0.0; one["uo"] = 0.0
    else:
        one["ua"] = np.floor(one.bla / L + 1e-9) * L; one["uo"] = np.floor(one.blo / L + 1e-9) * L
    up = te_units.assign(pred=pred, ua=te_units.bla.round(4), uo=te_units.blo.round(4))
    one["ua"] = one.ua.round(4); one["uo"] = one.uo.round(4)
    one["um"] = one.groupby(["ua", "uo", "t", "dn"]).modis.transform("sum")
    one = one.merge(up[["ua", "uo", "t", "dn", "pred"]], on=["ua", "uo", "t", "dn"], how="left")
    one["p"] = one.pred.fillna(0) * np.where(one.um > 0, one.modis / one.um.clip(lower=1), 0)
    return one.assign(b1a=one.bla, b1o=one.blo).groupby(["b1a", "b1o", "t"]).p.sum()


def score(T, L, te_units, pred):
    d = te_units.assign(pred=pred)
    rm = d.groupby("t")[["pred", "snpp"]].sum()
    rm = rm[rm.snpp > 0]
    e = rm.pred - rm.snpp
    yr = d.assign(y=d.t // 12).groupby("y")[["pred", "snpp"]].sum()
    b1p = to_1deg(T, L, te_units, pred)
    b1a = T[1][T[1].t.isin(te_units.t.unique())].groupby(["bla", "blo", "t"]).snpp.sum()
    b1a.index = b1a.index.set_names(["b1a", "b1o", "t"])
    j = pd.concat([b1p.rename("p"), b1a.rename("a")], axis=1).fillna(0)
    return {"MAPE": (e.abs() / rm.snpp).mean(), "WAPE": e.abs().sum() / rm.snpp.sum(),
            "bias": (e / rm.snpp).mean(), "bias_tot": rm.pred.sum() / rm.snpp.sum() - 1,
            "year_APE": ((yr.pred - yr.snpp).abs() / yr.snpp).mean(),
            "WAPE_1deg": (j.p - j.a).abs().sum() / max(j.a.sum(), 1), "n": len(rm)}


def prep_units(T, L, need_context):
    u = T[L]
    if need_context:
        u = add_context(u, L)
    return u.reset_index(drop=True)


_UC = {}
def evaluate(T, make, L, protocol="loyo", include_jan2012=False, years=range(2013, 2026), folds=None):
    ck = (id(T), L)
    if ck not in _UC:
        _UC[ck] = prep_units(T, L, True)
    u = _UC[ck]
    lo = 2012 * 12 + (0 if include_jan2012 else 1)
    overlap = u[(u.t >= lo) & (u.year <= 2025)]
    if folds is None:
        folds = [(range(2012, 2021), range(2021, 2024))] if protocol == "fixed" else [
            ([y for y in range(2012, 2026) if y != ty], [ty]) for ty in years]
    rows, preds = [], []
    for tr_y, te_y in folds:
        tr = overlap[overlap.year.isin(list(tr_y))]
        te = overlap[overlap.year.isin(list(te_y))]
        m = make().fit(tr)
        p = m.predict(te)
        preds.append(te.assign(pred=p))
    allp = pd.concat(preds)
    return score(T, L, allp.drop(columns="pred"), allp.pred.values), allp
