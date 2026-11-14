"""Comparable grid-path holdout: region-month MAPE and bias."""
import argparse, pandas as pd
from grid_calibrate import KEYS, STRATA, add_strata, ratios, converted
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--staging",default="data/cleaned_canada.parquet"); ap.add_argument("--monthly",default="data/monthly_harmonized.parquet"); a=ap.parse_args()
 s=pd.read_parquet(a.staging); r=ratios(s); h=s[s.year.between(2021,2023)]; p=converted(h,r); actual=add_strata(h[h.satellite.eq("SNPP")])
 pm=p.groupby(["year","month"]).weight.sum(); am=actual.groupby(["year","month"]).hotspots.sum(); x=pd.concat([pm.rename("pred"),am.rename("actual")],axis=1).fillna(0); x=x[x.actual.gt(0)]; x["ape"]=(x.pred-x.actual).abs()/x.actual; x["bias"]=(x.pred-x.actual)/x.actual
 print(f"REGION-MONTH MAPE={x.ape.mean():.6f} bias={x.bias.mean():+.6f} n={len(x)}")
 ps=p.groupby(["year","month",*STRATA]).weight.sum(); ac=actual.groupby(["year","month",*STRATA]).hotspots.sum(); z=pd.concat([ps.rename("pred"),ac.rename("actual")],axis=1).fillna(0); z=z[z.actual.gt(0)].reset_index(); z["ape"]=(z.pred-z.actual).abs()/z.actual; z["bias"]=(z.pred-z.actual)/z.actual; print(z.groupby(STRATA).agg(n=("ape","size"),MAPE=("ape","mean"),bias=("bias","mean")).round(6).to_string())
 m=pd.read_parquet(a.monthly); y=m.groupby("year").agg(raw=("total_count","sum"),harm=("harmonized_count","sum")); print(f"Raw 2011->2012 jump={(y.loc[2012,'raw']/y.loc[2011,'raw']-1):+.6%}"); print(f"Harmonized 2011->2012 jump={(y.loc[2012,'harm']/y.loc[2011,'harm']-1):+.6%}")
if __name__=="__main__": main()
