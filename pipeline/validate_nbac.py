#!/usr/bin/env python3
"""NBAC validation (optional): if data/external/nbac_2023.csv exists with columns
month,burned_area_ha, correlate with harmonized region counts for 2023.
Skips gracefully - absence never blocks the build."""
import sys
from pathlib import Path
import pandas as pd
p = Path("data/external/nbac_2023.csv")
if not p.exists():
    print("NBAC file not present (data/external/nbac_2023.csv) - skipping. App and calibration are unaffected.")
    sys.exit(0)
nbac = pd.read_csv(p); m = pd.read_parquet("data/monthly_harmonized.parquet")
r = m[m["year"] == 2023].groupby("month")["harmonized_count"].sum().reset_index()
j = r.merge(nbac, on="month")
print(j); print(f"Pearson r (harmonized count vs NBAC burned area, 2023 months): {j['harmonized_count'].corr(j['burned_area_ha']):.3f}")
