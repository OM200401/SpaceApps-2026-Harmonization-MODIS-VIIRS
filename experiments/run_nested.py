"""Clean (nested) check: choose block size, shrinkage k and blend weight using ONLY 2012-2020
(leave-one-year-out inside 2013-2020), then score the chosen settings once on the untouched 2021-2023 holdout."""
import sys, time, pickle, os, itertools
from harness import *
R = ["canada", "amazon", "mediterranean", "us_west", "siberia", "s_africa", "se_asia", "n_australia"]
T = pickle.load(open(f"{D}/T_nh.pkl", "rb"))
part = sys.argv[1] if len(sys.argv) > 1 else "all"
inner = [([y for y in range(2012, 2021) if y != ty], [ty]) for ty in range(2013, 2021)]


def rule(L, k, w):
    return lambda: Blend(SpatialRatio(L, k), SpatialPL(L, k, "season_dn", "month_dn"), w)


if part in ("0.5", "1", "2"):
    L = float(part) if part != "1" and part != "2" else int(part)
    out = f"{D}/nested_inner_L{part}.csv"
    rows = []
    for k, w in itertools.product([50, 200, 1000], [0.3, 0.5, 0.7]):
        for r in R:
            s, _ = evaluate(T[r], rule(L, k, w), L, folds=inner)
            rows.append({"L": L, "k": k, "w": w, "region": r, **{m: float(s[m]) for m in ["MAPE", "WAPE", "bias"]}})
        print("done", L, k, w, flush=True)
    for r in R:  # old rule on the same inner folds, for reference
        s, _ = evaluate(T[r], lambda: Ratio("season_dn"), 1, folds=inner)
        rows.append({"L": "old", "k": "", "w": "", "region": r, **{m: float(s[m]) for m in ["MAPE", "WAPE", "bias"]}})
    pd.DataFrame(rows).to_csv(out, index=False)
    print("INNER COMPLETE", part, flush=True)
elif part == "outer":
    inn = pd.concat([pd.read_csv(f"{D}/nested_inner_L{p}.csv") for p in ["0.5", "1", "2"]])
    inn = inn[inn.L.astype(str) != "old"]
    g = inn.groupby(["L", "k", "w"]).agg(WAPE=("WAPE", "mean"), MAPE=("MAPE", "mean"), absbias=("bias", lambda x: x.abs().mean())).reset_index()
    g = g.sort_values(["WAPE", "MAPE"])
    print("Inner (2013-2020 LOYO, training on 2012-2020 only), top 5 settings by mean WAPE over 8 regions:")
    print(g.head(5).round(4).to_string(index=False))
    best = g.iloc[0]; L = float(best.L); L = int(L) if L in (1.0, 2.0) else L
    print(f"\nChosen without seeing 2021-2023: L={L} k={int(best.k)} w={best.w}")
    rows = []
    for r in R:
        sn, _ = evaluate(T[r], rule(L, int(best.k), float(best.w)), L, "fixed", include_jan2012=True)
        so, _ = evaluate(T[r], lambda: Ratio("season_dn"), 1, "fixed", include_jan2012=True)
        rows.append({"region": r, "old_MAPE": so["MAPE"], "new_MAPE": sn["MAPE"], "old_WAPE": so["WAPE"], "new_WAPE": sn["WAPE"], "old_bias": so["bias"], "new_bias": sn["bias"]})
    o = pd.DataFrame(rows)
    print("\nOuter: untouched 2021-2023 holdout (fit 2012-2020), chosen settings vs old rule (own ratios):")
    print(o.round(4).to_string(index=False))
    print("\nMean over 8 regions:", o.drop(columns="region").mean().round(4).to_dict())
    o.to_csv(f"{D}/nested_outer.csv", index=False)
