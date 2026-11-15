"""Comparable grid-path holdout: region-month MAPE and bias.
The holdout fits on 2012-2020 and predicts S-NPP for 2021-2023 from MODIS alone. It starts in Jan 2012
(S-NPP's partial first month) so old- and new-rule numbers stay comparable with earlier docs; the
production fit starts in Feb 2012 (grid_calibrate.FIT_START). Starting the holdout fit in Feb instead
lowers Canada's new-rule MAPE from 13.6% to 13.1% (see docs/VALIDATION.md)."""
import argparse, pandas as pd
from grid_calibrate import KEYS, STRATA, add_strata, ratios, convert, fit_rule
HOLDOUT_FIT = ((2012, 1), 2020)
def holdout_rule(s, fallback=None, start=HOLDOUT_FIT[0]):
 """The optimised rule fitted only on the holdout's calibration years."""
 return fit_rule(s, start=start, end_year=HOLDOUT_FIT[1], fallback=fallback)
def holdout(s, r, years=(2021, 2023)):
 """Predict S-NPP for the holdout years from MODIS alone. `r` is a fitted rule (dict) or an old ratio table.
 Returns all months, months with S-NPP (with ape/bias), MODIS rows, S-NPP rows."""
 h=s[s.year.between(*years)]; p=convert(h,r); actual=add_strata(h[h.satellite.eq("SNPP")])
 pm=p.groupby(["year","month"]).weight.sum(); am=actual.groupby(["year","month"]).hotspots.sum(); allm=pd.concat([pm.rename("pred"),am.rename("actual")],axis=1).fillna(0); x=allm[allm.actual.gt(0)].copy(); x["ape"]=(x.pred-x.actual).abs()/x.actual; x["bias"]=(x.pred-x.actual)/x.actual
 return allm,x,p,actual
def top5(allm):
 # Rank unfiltered months so a busy prediction for a zero-actual month still counts as a miss.
 top_a=allm.actual.nlargest(5); top_p=allm.pred.nlargest(5)
 return top_a,top_p,len(set(top_a.index)&set(top_p.index))
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--staging",default="data/cleaned_canada.parquet"); ap.add_argument("--monthly",default="data/monthly_harmonized.parquet"); ap.add_argument("--old-rule",action="store_true",help="score the previous single-ratio rule instead"); a=ap.parse_args()
 s=pd.read_parquet(a.staging); r=ratios(s) if a.old_rule else holdout_rule(s); allm,x,p,actual=holdout(s,r)
 print(f"RULE={'old single ratio' if a.old_rule else 'optimised (block ratio + monthly power law)'}")
 print(f"REGION-MONTH MAPE={x.ape.mean():.6f} WAPE={(x.pred-x.actual).abs().sum()/x.actual.sum():.6f} bias={x.bias.mean():+.6f} n={len(x)}")
 top_a,top_p,hits=top5(allm); fmt=lambda i: f"{i[0]}-{i[1]:02d}"
 print(f"TOP-5 months matched {hits}/5"); print(pd.DataFrame({"actual_month":[fmt(i) for i in top_a.index],"actual":top_a.values.round(0),"pred_month":[fmt(i) for i in top_p.index],"pred":top_p.values.round(0)}).to_string(index=False))
 ps=p.groupby(["year","month",*STRATA]).weight.sum(); ac=actual.groupby(["year","month",*STRATA]).hotspots.sum(); z=pd.concat([ps.rename("pred"),ac.rename("actual")],axis=1).fillna(0); z=z[z.actual.gt(0)].reset_index(); z["ape"]=(z.pred-z.actual).abs()/z.actual; z["bias"]=(z.pred-z.actual)/z.actual; print(z.groupby(STRATA).agg(n=("ape","size"),MAPE=("ape","mean"),bias=("bias","mean")).round(6).to_string())
 m=pd.read_parquet(a.monthly); y=m.groupby("year").agg(raw=("total_count","sum"),harm=("harmonized_count","sum")); print(f"Raw 2011->2012 jump={(y.loc[2012,'raw']/y.loc[2011,'raw']-1):+.6%}"); print(f"Harmonized 2011->2012 jump={(y.loc[2012,'harm']/y.loc[2011,'harm']-1):+.6%}")
if __name__=="__main__": main()
