"""Cross-check grid harmonized parquet and exported UI JSON."""
import json
from pathlib import Path
import pandas as pd

m=pd.read_parquet("data/monthly_harmonized.parquet")
assert len(m)>0 and not m.harmonized_count.isna().any(), "missing harmonized values"
assert (m.total_count==m.modis_count+m.viirs_count).all(), "bad raw totals"
assert not ((m.year==2026)&(m.month==11)).any(), "partial November 2026 present"
j=json.loads(Path("app/data/monthly.json").read_text())
c=j["cells"]
assert len(c["t"])==len(m)==sum(c["n_months"]), "cell row mismatch"
expected=m.groupby(["year","month"]).harmonized_count.sum().round(2)
actual=pd.DataFrame(j["region_monthly"]).set_index(["year","month"]).harmonized.round(2)
assert expected.equals(actual), "region harmonized total mismatch"
# The app sums cells itself, so the compact cell columns must add up to the same totals (2 dp rounding per cell).
cm=pd.DataFrame({"t":c["t"],"harmonized":c["harmonized_count"]})
cm["year"]=c["t0_year"]+cm.t//12; cm["month"]=cm.t%12+1
from_cells=cm.groupby(["year","month"]).harmonized.sum()
tolerance=0.005*m.groupby(["year","month"]).size()+0.01
assert (from_cells-expected).abs().le(tolerance).all(), "cell harmonized totals mismatch"
print(f"PASS: {len(m):,} cell-months; {len(actual):,} region-months; JSON totals agree")
