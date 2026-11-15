# Audit Report — independent recomputation of the shipped Canada record

Artifact audited: `app/data/monthly.json` (md5 dbb934b1681e) — every value in it, per cell and per month, plus the Canada validation numbers in the claims registry. Engine: `pipeline/audit_engine.py`, which shares no code with the production pipeline (DuckDB SQL aggregation over the raw grid; method refit implemented from docs/VALIDATION.md). Claims and tolerances: `pipeline/audit_claims.json`.
Grid: `data\derived\monthly_grid_025.parquet` present; L3/L4 ran in full.

**NUMBERS verdict: PASS** — 54 checks passed, 0 failed, 1 unverifiable, 0 blocked.
**PUBLICATION verdict: FAIL** — 9 publication findings.

| Layer | Check | Published / expected | Recomputed | Verdict | Detail |
|---|---|---|---|---|---|
| L0 | Shipped cell-month entries | 308806 | 308806 | PASS | /diff/=0 tol=0 |
| L0 | sum(n_months) equals entry count | 308806 | 308806 | PASS |  |
| L0 | Distinct cells | 18060 | 18060 | PASS | /diff/=0 tol=0 |
| L0 | Region-month rows | 312 | 312 | PASS | /diff/=0 tol=0 |
| L0 | region_monthly total = modis + viirs, violations | 0 | 0 | PASS |  |
| L0 | All counts finite and non-negative | True | True | PASS |  |
| L0 | Region-months are exactly Nov 2000..Oct 2026 (no Nov 2026, no gaps) | 312 | 312 | PASS | missing=[] extra=[] |
| L0 | Decoded cell months match region_monthly months | 312 | 312 | PASS |  |
| L0 | Cell entries outside Canada bbox | 0 | 0 | PASS |  |
| L0 | Decode -> re-encode reproduces the shipped arrays exactly | True | True | PASS |  |
| L1 | May 2023 MODIS | 42442 | 42442 | PASS | /diff/=0 tol=0 |
| L1 | May 2023 VIIRS | 208476 | 208476 | PASS | /diff/=0 tol=0 |
| L1 | May 2023 harmonized | 208476.0 | 208476.0 | PASS | /diff/=0 tol=0.01 |
| L1 | Peak harmonized month is Aug 2023 | 2023-08 | 2023-08 | PASS |  |
| L1 | Aug 2023 harmonized | 440006.0 | 440006.0 | PASS | /diff/=0 tol=440.006 |
| L1 | Cell harmonized sums agree with region_monthly every month | 0 | 0 | PASS | max excess over tolerance=0.0000 |
| L1 | Prairies May 2023 harmonized (cells) | 4505.0 | 4505.0 | PASS | /diff/=0 tol=2 |
| L1 | Prairies May 2023 entries | 227 | 227 | PASS | /diff/=0 tol=0 |
| L1 | Raw total 2011 | 48859 | 48859 | PASS | /diff/=0 tol=0 |
| L1 | Raw total 2012 | 432574 | 432574 | PASS | /diff/=0 tol=0 |
| L1 | Raw jump 2011->2012 (%) | 785.35 | 785.351726396365 | PASS | /diff/=0.0017264 tol=0.1 |
| L1 | Harmonized jump 2011->2012 (%) | 60.76 | 60.75772425562342 | PASS | /diff/=0.00227574 tol=0.15 |
| L1 | MODIS-alone jump 2011->2012 (%) | 60.54 | 60.53951165598968 | PASS | /diff/=0.000488344 tol=0.1 |
| L2 | SNPP-era cells: harmonized != VIIRS observed, count | 0 | 0 | PASS |  |
| L2 | SNPP-era months: harmonized != VIIRS observed, count | 0 | 0 | PASS | zero-VIIRS months (converted-MODIS exception path): none |
| L2 | MODIS-era months with conversion ratio outside [0.5, 20] | 0 | 0 | PASS | [] |
| L2 | Terra-only months (before Jul 2002) have no holdout coverage | unvalidated by design | 20 months: 2000-11..2002-06 | INFO |  |
| L5 | Stale pre-v2 numbers in README.md | 0 | 0 | PASS |  |
| L5 | Stale pre-v2 numbers in app/index.html | 0 | 0 | PASS |  |
| L5 | Stale pre-v2 numbers in docs/PROJECT_PAGE.md | 0 | 0 | PASS |  |
| L5 | Stale pre-v2 numbers in docs/DEMO_SCRIPT.md | 0 | 0 | PASS |  |
| L5 | Rejected FRP-stratified method described as shipped in app/index.html | 0 | 2 | FAIL | L47: <p class="sub">Two NASA satellites, one trustworthy fire record. MODIS (1&nbsp;km, 2000+) and VIIRS (375&nbsp;; L99: <footer>Data: NASA FIRMS via NASA Earthdata — MODIS M-C61 (2000+), VIIRS SV-C2 (2012+), J1V-C2 (2018+), J2V-C2 |
| L5 | Rejected FRP-stratified method described as shipped in docs/PROJECT_PAGE.md | 0 | 3 | FAIL | L5: 2. High-level summary: Two NASA satellites have watched Earth's fires for 25 years, but they don't count the s; L5: 2. High-level summary: Two NASA satellites have watched Earth's fires for 25 years, but they don't count the s; L11: 5. Detailed description: [after real run: methods = shared-schema cleaning (bbox-first slice, nominal/high con |
| L5 | Rejected FRP-stratified method described as shipped in docs/DEMO_SCRIPT.md | 0 | 1 | FAIL | L6: 0:15 Toggle Harmonized — jump shrinks. "Calibrated on the 2012–2023 overlap, by fire size and season. Holdout  |
| L5 | Rejected FRP-stratified method described as shipped in SPEC.md | 0 | 3 | FAIL | L38: - Stratify by FRP bin (0–10, 10–30, 30–100, 100+ MW) as fire-size proxy, and by season (May–Sep boreal fire se; L38: - Stratify by FRP bin (0–10, 10–30, 30–100, 100+ MW) as fire-size proxy, and by season (May–Sep boreal fire se; L70: - D4 Stratification V1: FRP bin × season. Land-cover = stretch. |
| L5 | Calibration window misstated as 2012-2023 overlap in app/index.html | 0 | 1 | FAIL | L47: <p class="sub">Two NASA satellites, one trustworthy fire record. MODIS (1&nbsp;km, 2000+) and VIIRS (375&nbsp; |
| L5 | Calibration window misstated as 2012-2023 overlap in docs/PROJECT_PAGE.md | 0 | 1 | FAIL | L5: 2. High-level summary: Two NASA satellites have watched Earth's fires for 25 years, but they don't count the s |
| L5 | Calibration window misstated as 2012-2023 overlap in docs/DEMO_SCRIPT.md | 0 | 1 | FAIL | L6: 0:15 Toggle Harmonized — jump shrinks. "Calibrated on the 2012–2023 overlap, by fire size and season. Holdout  |
| L5 | Unfilled placeholders in docs/PROJECT_PAGE.md | 0 | 5 | FAIL | L5 /\[X\]/; L11 /\[TABLE\]/; L11 /\[RESULT\]/; L11 /\[A\]%/; L11 /\[B\]%/ |
| L5 | Unfilled placeholders in docs/DEMO_SCRIPT.md | 0 | 2 | FAIL | L6 /\[MAPE/; L7 /\[X\]/ |
| L5 | Experiments harness hard-codes the old-rule reproduction expectations (Canada own 0.1955, global 0.1691, Amazon 0.1792, Mediterranean 0.2062) | all present | missing: none | PASS |  |
| L6 | Fault injection caught: cell harmonized +1 in smallest MODIS-era month | >=1 new FAIL | ['cell_rm_agree'] | PASS |  |
| L6 | Fault injection caught: May 2023 region harmonized +100 | >=1 new FAIL | ['cell_rm_agree', 'may23_harm', 'snpp_era_months'] | PASS |  |
| L6 | Fault injection caught: Jun/Jul 2021 region harmonized swapped | >=1 new FAIL | ['cell_rm_agree', 'snpp_era_months'] | PASS |  |
| L6 | Fault injection caught: Nov 2026 region-month injected | >=1 new FAIL | ['cell_months_match', 'cell_rm_agree', 'region_months', 'span'] | PASS |  |
| L6 | Fault injection caught: region_monthly total != modis + viirs | >=1 new FAIL | ['totals_identity'] | PASS |  |
| L6 | Fault injection caught: SNPP-era cell harmonized set to MODIS x 3.69 | >=1 new FAIL | ['snpp_era_cells'] | PASS |  |
| L6 | Fault injection caught: cell longitude moved to -30 | >=1 new FAIL | ['bbox'] | PASS |  |
| L6 | Fault injection caught: stale 209,913 planted in README | >=1 new FAIL | ['stale:README.md'] | PASS |  |
| L6 | Fault-injection score | 8/8 | 8/8 | PASS |  |
| L3 | Rows in data-v2 grid parquet | 55093407 | 55093407 | PASS | /diff/=0 tol=0 |
| L3 | Rebuilt Canada cell-month rows (Nov 2026 excluded) | 308806 | 308806 | PASS | /diff/=0 tol=0 |
| L3 | Rebuilt cell-month MODIS/VIIRS inputs differing from shipped file | 0 | 0 | PASS |  |
| L3 | Months whose rebuilt MODIS/VIIRS totals differ from region_monthly | 0 | 0 | PASS |  |
| L3 | region_monthly mean_frp recomputed (mean of per-cell-month mean FRP), months off by >0.011 | 0 | 0 | PASS | max deviation within tolerance=0.0050 |
| L4 | Canada strata thin enough to need the global fallback | none | none | INFO |  |
| L4 | MODIS-era region-months reproduced by the refit within 0.05% | 100% within 0.05% (clean-file noise floor is 0.001%) | max deviation 0.0012% over 135 months | PASS |  |
| L4 | Per-cell harmonized values reproduced by the refit (all eras), cells off by >0.02 | 0 | 0 | PASS | max per-cell deviation=0.0050 over 308806 cells |
| L4 | Holdout months with S-NPP observed | 36 | 36 | PASS |  |
| L4 | Holdout MAPE, shipped rule (%) | 13.6 | 13.638903795856482 | PASS | /diff/=0.0389038 tol=0.5 |
| L4 | Holdout WAPE, shipped rule (%) | 11.3 | 11.324936601981008 | PASS | /diff/=0.0249366 tol=0.5 |
| L4 | Holdout bias, shipped rule (%) | -6.5 | -6.549698646334397 | PASS | /diff/=0.0496986 tol=1 |
| L4 | Holdout MAPE, old rule own ratios (%) | 19.6 | 19.545806879513652 | PASS | /diff/=0.0541931 tol=0.3 |
| L4 | Holdout MAPE, old rule global ratios (%) | 16.9 | 16.908425945690333 | PASS | /diff/=0.00842595 tol=0.3 |
| L4 | Holdout MAPE, Feb-2012 fit start (%) | 13.1 | 13.091082334047385 | PASS | /diff/=0.00891767 tol=0.5 |
| L4 | LOYO 8-region MAPE, old -> new (%) | 20.8 -> 14.0 | not recomputed | UNVERIFIABLE | Experiment result CSVs are gitignored and not in the repo; the audit can verify the harness code and its baseline expectations but not the LOYO outputs. |

## Known gaps (stated, not hidden)
- LOYO experiment averages are UNVERIFIABLE from the repo: the result CSVs are gitignored. The harness code and its hard-coded old-rule baseline expectations are in the repo (verified by check L5 baseline_expectations, and the Canada pair is numerically reproduced by L4), but the LOYO outputs themselves are not.
- Terra-only months (Nov 2000 - Jun 2002) have no holdout coverage by design; their harmonized values rest on the Terra-only ratios alone.
- Canada's untouched-holdout WAPE worsens under the shipped rule (8.8% -> 11.0%, nested check in docs/VALIDATION.md) even as MAPE improves; both figures belong in any honest summary.
- The shipped app's own method text is a publication finding of this audit (see L5): the calibration it describes is not the calibration that produced the data.
