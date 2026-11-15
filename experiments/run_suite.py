"""Run one phase of the method grid with leave-one-year-out CV over all regions. Appends to results.csv."""
import sys, time, pickle, os
from harness import *
phase = sys.argv[1]
T = pickle.load(open(f"{D}/T_nh.pkl", "rb"))
W = world()
R = ["canada", "amazon", "mediterranean", "us_west", "siberia", "s_africa", "se_asia", "n_australia"]
M = {}
if phase == "A":  # ratio family, strata, shrinkage, global, Aqua/Terra, spatial ratios
    for k in ["none", "dn", "season_dn", "peak_dn"]:
        M[f"ratio_{k}"] = (1, lambda k=k: Ratio(k))
    for kk in [0, 100, 500, 2000]:
        M[f"ratio_month_dn_k{kk}"] = (1, lambda kk=kk: Ratio("month_dn", k=kk))
    M["ratio_season_dn_GLOBAL"] = (1, lambda: Ratio("season_dn", world_df=W))
    for kind in ["season_dn", "peak_dn", "month_dn"]:
        for wt in ["none", "rel"]:
            M[f"aquaterra_{kind}_{wt}"] = (1, lambda kind=kind, wt=wt: AquaTerra(kind, wt))
    for L in [0.5, 1, 2, 5]:
        for k in [50, 200, 1000, 5000]:
            M[f"spatial_L{L}_k{k}"] = (L, lambda L=L, k=k: SpatialRatio(L, k))
elif phase == "B":  # power law and Poisson GLM at several aggregation levels
    for L in ["region", 5, 2, 1, 0.5]:
        M[f"powerlaw_L{L}_season_dn"] = (L, lambda L=L: PowerLaw(L, "season_dn"))
        M[f"powerlaw_L{L}_peak_dn"] = (L, lambda L=L: PowerLaw(L, "peak_dn"))
    for L in ["region", 5, 1]:
        for ex in [(), ("aqs",), ("frp",), ("lreg",), ("aqs", "frp", "lreg")]:
            M[f"poisson_L{L}_{'+'.join(ex) or 'base'}"] = (L, lambda L=L, ex=ex: PoissonGLM(L, "season_dn", ex))
    M["poisson_L1_nbr+lreg"] = (1, lambda: PoissonGLM(1, "season_dn", ("nbr", "lreg")))
    M["poisson_Lregion_peak_dn"] = (L, lambda: PoissonGLM("region", "peak_dn"))
    M["poisson_Lregion_peak_dn"] = ("region", lambda: PoissonGLM("region", "peak_dn"))
elif phase == "C":  # fire-size bins and gradient boosting
    for L in [0.25, 1]:
        M[f"frpbins_L{L}"] = (L, lambda L=L: FRPBins(L))
    for L in [2, 1, 0.5]:
        M[f"hgb_L{L}"] = (L, lambda L=L: HGB(L))
    M["hgb_L1_nolatlon"] = (1, lambda: HGB(1, use_latlon=False))
out = f"{D}/results.csv"
for name, (L, make) in M.items():
    for r in R:
        t0 = time.time()
        try:
            s, _ = evaluate(T[r], make, L, "loyo")
        except Exception as e:
            print(f"FAIL {name} {r}: {e!r}", flush=True); continue
        row = {"phase": phase, "method": name, "level": L, "region": r, **{k: round(v, 5) for k, v in s.items()}, "sec": round(time.time() - t0, 1)}
        pd.DataFrame([row]).to_csv(out, mode="a", header=not os.path.exists(out), index=False)
    print(f"done {name}", flush=True)
print("PHASE", phase, "COMPLETE", flush=True)
