"""Compare saved leave-one-year-out predictions. Averages variants joined with '+'.

Usage: python report.py shipped gbm_lin gbm_lin+gbm_s1+gbm_s2 [--metric WAPE]
"""
import argparse
import pandas as pd
import h2

pd.set_option("display.width", 250)
KEY = ["region", "bla", "blo", "year", "month", "dn"]
METRICS = ("MAPE", "MAPE_main", "WAPE", "bias", "year_APE", "year_max")


def get(name):
    parts = [pd.read_parquet(f"{h2.D}/preds/{n}.parquet") for n in name.split("+")]
    if len(parts) == 1:
        return parts[0]
    p = parts[0].set_index(KEY)
    for q in parts[1:]:
        p["pred"] = p.pred.add(q.set_index(KEY).pred, fill_value=0)
    p["pred"] /= len(parts)
    return p.reset_index()


ap = argparse.ArgumentParser()
ap.add_argument("variants", nargs="+")
ap.add_argument("--metric", choices=METRICS, help="print only this metric")
a = ap.parse_args()
out = {n: h2.score_all(get(n)) * 100 for n in a.variants}
for m in [a.metric] if a.metric else METRICS:
    print(f"\n== {m} (%)")
    print(pd.DataFrame({n: s[m] for n, s in out.items()}).round(1).to_string())
