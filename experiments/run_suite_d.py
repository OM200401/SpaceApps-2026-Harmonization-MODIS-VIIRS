"""Phase D: combined spatial-ratio + power-law sweep, and blends, LOYO over all regions."""
import time, pickle, os
from harness import *
T = pickle.load(open(f"{D}/T_nh.pkl", "rb"))
R = ["canada", "amazon", "mediterranean", "us_west", "siberia", "s_africa", "se_asia", "n_australia"]
M = {}
for L in [0.5, 1, 2, 5]:
    for k in [50, 200, 1000]:
        M[f"spatialPL_L{L}_k{k}"] = (L, lambda L=L, k=k: SpatialPL(L, k))
    M[f"spatialPL_L{L}_k200_peakPL"] = (L, lambda L=L: SpatialPL(L, 200, "season_dn", "peak_dn"))
M["spatialPL_L1_k200_monthPL"] = (1, lambda: SpatialPL(1, 200, "season_dn", "month_dn"))
M["blend_spatial1k200_powerlawRegion"] = (1, lambda: Blend(SpatialRatio(1, 200), SpatialPL(1, 200), 0.5))
out = f"{D}/results.csv"
for name, (L, make) in M.items():
    for r in R:
        t0 = time.time()
        try:
            s, _ = evaluate(T[r], make, L, "loyo")
        except Exception as e:
            print(f"FAIL {name} {r}: {e!r}", flush=True); continue
        row = {"phase": "D", "method": name, "level": L, "region": r, **{k: round(float(v), 5) for k, v in s.items()}, "sec": round(time.time() - t0, 1)}
        pd.DataFrame([row]).to_csv(out, mode="a", header=not os.path.exists(out), index=False)
    print(f"done {name}", flush=True)
print("PHASE D COMPLETE", flush=True)
