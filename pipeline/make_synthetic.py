#!/usr/bin/env python3
"""Synthetic FIRMS-shaped data with a KNOWN ground truth, for pipeline tests.
Planted truth: in fire season VIIRS sees RATIO x MODIS counts; 2023 is 3x normal.
If calibration recovers ~RATIO, the method works. NOT real data - never submit as real.
"""
import argparse, random
from pathlib import Path
import pandas as pd

RATIO = 2.8
random.seed(42)

def gen(sensor, years, out):
    rows = []
    for y in years:
        for m in range(1, 13):
            season = 1.0 if 5 <= m <= 9 else 0.15
            base = 40 * season * random.uniform(0.7, 1.3)
            if y == 2023 and 5 <= m <= 8:
                base *= 3.0
            n_modis = max(0, int(base))
            n = n_modis if sensor == "MODIS" else int(n_modis * RATIO)
            for _ in range(n):
                lat = round(random.uniform(49, 65), 4); lon = round(random.uniform(-125, -60), 4)
                frp = round(random.lognormvariate(2.5, 1.0), 1)
                day = random.randint(1, 28)
                if sensor == "MODIS":
                    rows.append(dict(latitude=lat, longitude=lon, brightness=300+frp, scan=1, track=1,
                        acq_date=f"{y}-{m:02d}-{day:02d}", acq_time=random.choice([130, 1030, 2230]),
                        satellite=random.choice(["Terra", "Aqua"]), instrument="MODIS",
                        confidence=random.choice([55, 72, 90, 95]), version="6.1", bright_t31=290,
                        daynight="D", frp=frp, type=0))
                else:
                    rows.append(dict(latitude=lat, longitude=lon, bright_ti4=300+frp, scan=0.4, track=0.4,
                        acq_date=f"{y}-{m:02d}-{day:02d}", acq_time=random.choice([130, 1030, 2230]),
                        satellite="N", instrument="VIIRS", confidence=random.choice(["n", "h"]),
                        version="2", bright_ti5=290, daynight="D", frp=frp, type=0))
    df = pd.DataFrame(rows)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"{out}: {len(df):,} rows (planted VIIRS/MODIS ratio={RATIO}, 2023=3x)")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--outdir", default="data/synthetic"); a = ap.parse_args()
    gen("MODIS", range(2001, 2026), f"{a.outdir}/fire_nrt_M-C61_synthetic.csv")
    gen("VIIRS", range(2012, 2026), f"{a.outdir}/fire_nrt_V-C2_synthetic.csv")
