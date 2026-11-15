"""Phase E: tune the leading combination (blend weight, month-level strata)."""
import time, pickle, os
from harness import *
T = pickle.load(open(f"{D}/T_nh.pkl", "rb"))
R = ["canada", "amazon", "mediterranean", "us_west", "siberia", "s_africa", "se_asia", "n_australia"]
M = {}
for w in [0.3, 0.5, 0.7]:
    M[f"blend_w{w}_spatial1k200_spatialPLmonth"] = (1, lambda w=w: Blend(SpatialRatio(1, 200), SpatialPL(1, 200, "season_dn", "month_dn"), w))
for w in [0.3, 0.7]:
    M[f"blend_w{w}_spatial1k200_spatialPL"] = (1, lambda w=w: Blend(SpatialRatio(1, 200), SpatialPL(1, 200), w))
M["blend_w0.5_spatial1k50_spatialPL"] = (1, lambda: Blend(SpatialRatio(1, 50), SpatialPL(1, 50), 0.5))
M["blend_w0.5_spatial2k200_spatialPL"] = (2, lambda: Blend(SpatialRatio(2, 200), SpatialPL(2, 200), 0.5))
out = f"{D}/results.csv"
for name, (L, make) in M.items():
    for r in R:
        t0 = time.time()
        s, _ = evaluate(T[r], make, L, "loyo")
        row = {"phase": "E", "method": name, "level": L, "region": r, **{k: round(float(v), 5) for k, v in s.items()}, "sec": round(time.time() - t0, 1)}
        pd.DataFrame([row]).to_csv(out, mode="a", header=False, index=False)
    print(f"done {name}", flush=True)
print("PHASE E COMPLETE", flush=True)
