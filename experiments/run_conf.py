"""Sensitivity to the confidence filter (which detections are counted, for both sensors)."""
import time, os
from harness import *
R = ["canada", "amazon", "mediterranean", "us_west", "siberia", "s_africa", "se_asia", "n_australia"]
rows = []
for tag, conf in [("h", ("h",)), ("nh", ("n", "h")), ("lnh", ("l", "n", "h"))]:
    cells = load(conf)
    for r in R:
        T = tables(cells[cells.region == r])
        for name, L, make in [("ratio_season_dn", 1, lambda: Ratio("season_dn")),
                              ("spatialPL_L1_k200", 1, lambda: SpatialPL(1, 200))]:
            s, _ = evaluate(T, make, L, "loyo")
            rows.append({"conf": tag, "region": r, "method": name, **{k: round(float(v), 5) for k, v in s.items()}})
        print(tag, r, flush=True)
pd.DataFrame(rows).to_csv(f"{D}/results_conf.csv", index=False)
print("CONF COMPLETE", flush=True)
