"""Finalists: fixed holdout (comparable with docs), extremes bias, error bands, and the 2011->2012 seam."""
import sys, time, pickle, os
from harness import *
T = pickle.load(open(f"{D}/T_nh.pkl", "rb"))
W = world()
R = ["canada", "amazon", "mediterranean", "us_west", "siberia", "s_africa", "se_asia", "n_australia"]
F = {
    "baseline_ratio_season_dn": (1, lambda: Ratio("season_dn")),
    "baseline_GLOBAL_ratio": (1, lambda: Ratio("season_dn", world_df=W)),
    "powerlaw_region": ("region", lambda: PowerLaw("region", "season_dn")),
    "spatial_L1_k200": (1, lambda: SpatialRatio(1, 200)),
    "spatialPL_L1_k200": (1, lambda: SpatialPL(1, 200)),
    "ratio_month_dn_k100": (1, lambda: Ratio("month_dn", k=100)),
    "WINNER_blend_spatial_spatialPLmonth": (1, lambda: Blend(SpatialRatio(1, 200), SpatialPL(1, 200, "season_dn", "month_dn"), 0.5)),
    "hgb_L2": (2, lambda: HGB(2)),
}
extra = sys.argv[1:]  # optional "name=L:k" spatialPL variants picked from the sweep
for e in extra:
    n, v = e.split("="); L, k = v.split(":"); L = float(L) if L != "region" else L
    F[n] = (L, lambda L=L, k=int(k): SpatialPL(L, k))
rows = []
for name, (L, make) in F.items():
    for r in R:
        fx, _ = evaluate(T[r], make, L, "fixed", include_jan2012=True)
        lo, P = evaluate(T[r], make, L, "loyo")
        rm = P.groupby("t")[["pred", "snpp"]].sum(); rm = rm[rm.snpp > 0]
        q90 = rm.snpp.quantile(0.9)
        big, small = rm[rm.snpp >= q90], rm[rm.snpp < rm.snpp.quantile(0.5)]
        lr = np.log(rm.pred.clip(lower=1) / rm.snpp)
        # seam: fit on all overlap (Feb 2012-2025), predict 2011 and Feb-Dec 2012 from MODIS
        import harness
        u = harness._UC[(id(T[r]), L)]
        tr = u[(u.t >= SNPP_T0) & (u.year <= 2025)]
        m = make().fit(tr)
        u11 = u[(u.year == 2011) & (u.month >= 2)]; u12 = u[(u.year == 2012) & (u.month >= 2)]
        h11 = m.predict(u11).sum(); s12 = u12.snpp.sum()
        jump_h = s12 / h11 - 1; jump_m = u12.modis.sum() / u11.modis.sum() - 1
        rows.append({"method": name, "region": r,
                     "fixed_MAPE": fx["MAPE"], "fixed_bias": fx["bias"],
                     "loyo_MAPE": lo["MAPE"], "loyo_WAPE": lo["WAPE"], "loyo_bias": lo["bias"], "loyo_bias_tot": lo["bias_tot"],
                     "year_APE": lo["year_APE"], "WAPE_1deg": lo["WAPE_1deg"],
                     "bias_top10pct_months": ((big.pred - big.snpp) / big.snpp).mean(),
                     "bias_bottom50pct_months": ((small.pred - small.snpp) / small.snpp).mean(),
                     "band80_lo": np.exp(lr.quantile(0.1)) - 1, "band80_hi": np.exp(lr.quantile(0.9)) - 1,
                     "seam_jump_harm": jump_h, "seam_jump_modis": jump_m})
        print(name, r, flush=True)
pd.DataFrame(rows).round(4).to_csv(f"{D}/results_final.csv", index=False)
print("FINAL COMPLETE", flush=True)
