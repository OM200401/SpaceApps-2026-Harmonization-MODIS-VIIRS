"""Cross-check grid harmonized parquet and exported UI JSON."""
import json
from pathlib import Path
import pandas as pd

m=pd.read_parquet("data/monthly_harmonized.parquet")
assert len(m)>0 and not m.harmonized_count.isna().any(), "missing harmonized values"
assert (m.total_count==m.modis_count+m.viirs_count).all(), "bad raw totals"
assert not ((m.year==2026)&(m.month==11)).any(), "partial November 2026 present"
j=json.loads(Path("app/data/monthly.json").read_text())
assert len(j["cells"])==len(m), "cell row mismatch"
expected=m.groupby(["year","month"]).harmonized_count.sum().round(2)
actual=pd.DataFrame(j["region_monthly"]).set_index(["year","month"]).harmonized.round(2)
assert expected.equals(actual), "region harmonized total mismatch"
print(f"PASS: {len(m):,} cell-months; {len(actual):,} region-months; JSON totals agree")
