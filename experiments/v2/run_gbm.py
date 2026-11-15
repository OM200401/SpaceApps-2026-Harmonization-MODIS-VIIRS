"""Run named variants under leave-one-year-out (stable years); save test predictions and scores.

Usage: python run_gbm.py <variant> [<variant> ...] [--units PATH] [--tag SUFFIX]
"""
import sys, time, os
import numpy as np, pandas as pd
import h2
from models import OldRatio, Shipped, Hier
from gbm import GBM, RAW, CONTEXT

pd.set_option("display.width", 250)
V = {
    "old": OldRatio,
    "shipped": Shipped,
    "hier_tile": Hier,
    "gbm": GBM,
    "gbm_s1": lambda: GBM(seed=1),
    "gbm_s2": lambda: GBM(seed=2),
    "gbm_lin": lambda: GBM(params=dict(linear_tree=True, linear_lambda=1.0)),
    "gbm_lin_s1": lambda: GBM(params=dict(linear_tree=True, linear_lambda=1.0), seed=1),
    "gbm_lin_s2": lambda: GBM(params=dict(linear_tree=True, linear_lambda=1.0), seed=2),
    "gbm_big": lambda: GBM(params=dict(num_leaves=63, min_data_in_leaf=50, learning_rate=0.03), rounds=900),
    "gbm_small": lambda: GBM(params=dict(num_leaves=15, min_data_in_leaf=300, lambda_l2=20.0), rounds=300),
    "gbm_slow": lambda: GBM(params=dict(learning_rate=0.02, min_data_in_leaf=200, lambda_l2=20.0, feature_fraction=0.6), rounds=800),
    "gbm_noraw": lambda: GBM(drop=RAW),
    "gbm_noctx": lambda: GBM(drop=CONTEXT),
    "gbm_noloc": lambda: GBM(drop=["lat", "lon"]),
}
args = sys.argv[1:]
units = args[args.index("--units") + 1] if "--units" in args else None
tag = args[args.index("--tag") + 1] if "--tag" in args else ""
names = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--units", "--tag"))]
u = pd.read_parquet(units) if units else h2.load(1.0)
os.makedirs(f"{h2.D}/preds", exist_ok=True)
for name in names:
    t0 = time.time()
    p = h2.loyo(u, V[name])
    p[["region", "bla", "blo", "year", "month", "dn", "t", "m", "s_n", "pred"]].to_parquet(f"{h2.D}/preds/{name}{tag}.parquet", index=False)
    s = h2.show(f"{name}{tag}: LOYO {h2.STABLE[0]}-{h2.STABLE[1]} ({time.time() - t0:.0f}s)", p)
    s.assign(variant=name + tag).to_csv(f"{h2.D}/results.csv", mode="a", header=not os.path.exists(f"{h2.D}/results.csv"))
    sys.stdout.flush()
