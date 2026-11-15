import time, pickle
from harness import *
t0 = time.time()
cells = load()
W = world()
T = {r: tables(cells[cells.region == r]) for r in cells.region.unique()}
pickle.dump(T, open(f"{D}/T_nh.pkl", "wb"))
print(f"tables built in {time.time()-t0:.0f}s")
print("Reproduce pipeline holdout (fit 2012-2020 incl. Jan 2012, test 2021-2023):")
for r in ["canada", "amazon", "mediterranean"]:
    s_own, _ = evaluate(T[r], lambda: Ratio("season_dn"), 1, "fixed", include_jan2012=True)
    s_glb, _ = evaluate(T[r], lambda: Ratio("season_dn", world_df=W), 1, "fixed", include_jan2012=True)
    print(f"  {r:14s} own MAPE={s_own['MAPE']:.4f} bias={s_own['bias']:+.4f} | global MAPE={s_glb['MAPE']:.4f} bias={s_glb['bias']:+.4f}")
print("expected: canada own 0.1955 / global 0.1691 (bias -0.0105), amazon own 0.1792, mediterranean own 0.2062")
