"""Reference numbers: the VIIRS-vs-VIIRS noise floor, and both rules under the old holdout protocol.

Usage: python run_base.py [--floor-only]
"""
import sys
import numpy as np, pandas as pd
import h2
from models import Shipped, encodings, apply_enc
from gbm import GBM

pd.set_option("display.width", 250)
u = h2.load(1.0)
ov = u[u.year.between(*h2.STABLE)]
for dn in "DN":
    d = ov[ov.dn == dn]
    print(f"{dn}: S-NPP share in block-months with no MODIS in that half of the day {d.loc[d.m <= 0, 's_n'].sum() / d.s_n.sum():.1%}, "
          f"with no MODIS evidence at all {d.loc[~d.ev, 's_n'].sum() / d.s_n.sum():.1%}")

# Floor: predict S-NPP from NOAA-20 (same instrument, about 50 minutes apart) with block ratios,
# leave-one-year-out over 2019-2025. No MODIS-based rule can be expected to beat this.
j = u[(u.year >= 2019) & (u.year <= 2025)]   # NOAA-20 fire data starts during 2018; use full years only
out = []
for ty in range(2019, 2026):
    tr, te = j[j.year != ty], j[j.year == ty]
    out.append(te.assign(pred=te.j_n.values * apply_enc(te, encodings(tr, cols=("s_n_j", "j_n")))[2]))
floor = pd.concat(out)
s = h2.score_all(floor, actual="s_n_j") * 100
print("\n== FLOOR: NOAA-20 -> S-NPP, block ratios, leave-one-year-out 2019-2025"); print(s.round(1).to_string())
s.assign(variant="floor_n20").to_csv(f"{h2.D}/results.csv", mode="a", header=False)

if "--floor-only" in sys.argv:
    sys.exit()

# Old protocol (fit 2012-2020, test 2021-2023): the test years include the Terra/Aqua orbit drift.
for name, make in (("shipped", Shipped), ("gbm_lin", lambda: GBM(params=dict(linear_tree=True, linear_lambda=1.0)))):
    p = h2.fixed(u, make, range(2012, 2021), range(2021, 2024))
    h2.show(f"{name}, old protocol (fit 2012-2020, test 2021-2023, drift years)", p)
    p = h2.fixed(u, make, range(2012, 2019), range(2019, 2022))
    h2.show(f"{name}, forward holdout inside stable years (fit 2012-2018, test 2019-2021)", p)
