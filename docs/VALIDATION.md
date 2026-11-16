# Validation: numbers are from runs, never hand-written

## Estimator definition (shipped, #37)
Harmonized count (S-NPP VIIRS-equivalent units) per 0.25° cell-month:
- From Feb 2012: harmonized = observed S-NPP count, zeros included (reference sensor; zero handling fixed in #3).
- Jul 2002 – Jan 2012: the optimised rule (`fit_rule` / `converted_rule` in `pipeline/grid_calibrate.py`):
  - **A = MODIS × block ratio.** Each 1° block has its own S-NPP/MODIS ratio per season × day/night, shrunk toward the region ratio: `(block S-NPP + 200 × region ratio) ÷ (block MODIS + 200)`.
  - **B = A × monthly factor.** The factor is a region-level power law `S-NPP = e^a × MODIS^b` (with smearing correction), fitted per calendar month × day/night on region-month totals, divided by the plain region ratio × region MODIS.
  - **Harmonized = 0.5 × A + 0.5 × B.**
- Before Jul 2002 (Terra only): Terra count × the region's own Terra-only ratio for its season × day/night (unchanged path).
- Each region is fitted on its own overlap, Feb 2012 – Dec 2025. Canada no longer uses global ratios.

Details:
- **Thin strata.** A region stratum with fewer than 50 MODIS detections uses the global ratio for that stratum, as under the old rule. No stratum is that thin in any of the 3 regions today.
- **Missed-fire uplift.** Each power-law fit is multiplied by `1 / (1 − missed)`, capped at 2×. `missed` is the share of S-NPP detections that fall in region-months where MODIS saw nothing, which a MODIS-based prediction can't reproduce. It is exactly 1.0 for all 24 month × day/night fits in all 3 regions today, so it changes no current number. It only matters for small or sparse regions.
- **No fit for a month.** If a month × day/night has no power-law fit (possible in a small new region), the factor is 1 and the estimate falls back to A.
- **Fit windows.** The shipped fit starts in Feb 2012, S-NPP's first full month. The holdout fit starts in Jan 2012, so its numbers stay comparable with the old-rule results below. Starting the holdout fit in Feb instead gives Canada 13.1% MAPE (bias −6.0%), against 13.6% (−6.5%).

## Optimised rule results (2026-11-14, data-v2, #37)
Command: `python pipeline/build_regions.py`, then `python pipeline/grid_validate.py --staging data/regions/canada_staging.parquet`.

### Holdout (fit 2012–2020, predict S-NPP 2021–2023 from MODIS only)
| Region | MAPE, old rule (own ratios) | MAPE, old rule (global ratios) | **MAPE, new rule** | WAPE, new rule | Bias, new rule | Top-5 months |
|---|---:|---:|---:|---:|---:|---:|
| Canada | 19.6% | 16.9% (was shipped) | **13.6%** | 11.3% | −6.5% | 5/5 |
| Amazon | 17.9% (was shipped) | 32.9% | **8.3%** | 7.4% | +4.5% | 5/5 |
| Mediterranean | 20.6% (was shipped) | 26.9% | **15.6%** | 15.9% | +3.5% | 4/5 |

### 2011→2012 sensor jump
| Region | Raw | Harmonized, old | **Harmonized, new** | MODIS alone |
|---|---:|---:|---:|---:|
| Canada | +785.4% | +55.9% | **+60.8%** | +60.5% |
| Amazon | +656.2% | +60.5% | **+62.4%** | +55.8% |
| Mediterranean | +496.0% | +29.0% | **+38.2%** | +33.8% |

### How the rule was chosen (leave-one-year-out, 8 regions)
About 90 variants were scored with the harness in `experiments/` (run order in `experiments/README.md`). Each one was fitted on every overlap year but one, predicted the held-out year (13 rounds, 2013–2025), and was scored on Canada, Amazon, Mediterranean, US West, Siberia, southern Africa, SE Asia and northern Australia. The harness first reproduced the old holdout numbers above exactly. Averages over the 8 regions, old → new rule:
- Total error (WAPE): 12.7% → 8.9%
- Monthly error (MAPE): 20.8% → 14.0%
- Mean |bias|: 10.4% → 4.2%
- Bias in the busiest 10% of months: +2.3% → −0.2%
- Error on 1° block-months: 30.1% → 25.2%

**Caveat:** these rounds included 2021–2023, so the holdout table above is not a clean out-of-sample result for the chosen settings.

### Clean check: settings chosen without seeing 2021–2023
`experiments/run_nested.py`. Block size (0.5°, 1°, 2°), k (50, 200, 1000) and blend weight (0.3, 0.5, 0.7) were chosen using only 2012–2020: leave-one-year-out over 2013–2020, averaged over the 8 regions. The chosen settings were then scored once on the untouched 2021–2023 holdout.
- **Best settings on 2012–2020 alone:** 2° blocks, k = 200, w = 0.5 (WAPE 7.0%). The shipped settings (1°, k = 200, w = 0.5) rank 8th of 27, at WAPE 7.3%. The old rule scores 11.3% on the same folds.
- **Untouched 2021–2023 holdout, chosen settings vs old rule (own ratios), mean over 8 regions:** MAPE **24.9% → 18.0%**, WAPE **14.3% → 11.0%**, bias −1.3% → +0.8%. Per region: Canada MAPE 19.6% → 13.7%, Amazon 17.9% → 8.6%, Mediterranean 20.6% → 15.7%. These are within 0.3 points of the shipped settings' numbers in the table above.
- **One exception:** Canada's 2021–2023 WAPE is higher under the new rule (8.8% → 11.0%) even though its MAPE and bias improve.
- The choice of method family itself (from about 90 variants) was still made with all years, so this check covers the settings but not that first choice.
- **Why 1° blocks still ship, not 2°:** 2° wins by only 0.3 points of WAPE on the inner folds, and on the untouched holdout the two are within 0.3 points of each other. 1° blocks follow the spatial pattern of fires more closely for the 0.25° cells the app shows, and every shipped number and check in this document was produced with 1°. Switching would change every MODIS-era cell for a gain inside that margin.

Tried and not adopted: global ratios, Aqua and Terra as separate predictors, MODIS-FRP bins, region-specific fire seasons, a power law fitted on small blocks, high-confidence-only counts, and gradient-boosted trees (similar error but more biased and slower).

### Effect on the shipped Canada record
Every month from Feb 2012 is unchanged (observed S-NPP). Every MODIS-era month changed. Yearly totals moved −3% to −15% for 2003–2011, and 2008 by +0.7%. 2001–2002 moved −26% and −11%, mainly because the Terra-only months now use Canada's own Terra ratios instead of the global ones. **That Terra-only path is not covered by any holdout**, because no data exists where only Terra and S-NPP overlap.

## Real-data results (2026-11-14, data-v2, Canada, own ratios)
> **Superseded.** This section documents the old single-ratio rule. See "Optimised rule results" above.

Input: `monthly_grid_025.parquet` (data-v2) → `build_monthly_from_grid.py` → 565,295 staging rows, 308,806 cell-months (vegetation fires, confidence n/h, Terra/Aqua/S-NPP, Nov 2026 excluded as partial).
Commands: `python pipeline/grid_calibrate.py` then `python pipeline/grid_validate.py`.

### Calibration ratios (2012–2020 overlap)
| Season | Day/night | MODIS | S-NPP | Ratio | Terra-only ratio |
|---|---|---:|---:|---:|---:|
| Fire (May–Sep) | Day | 350,630 | 1,295,054 | 3.69 | 8.75 |
| Fire (May–Sep) | Night | 189,832 | 1,597,769 | 8.42 | 11.63 |
| Off | Day | 107,773 | 245,431 | 2.28 | 5.60 |
| Off | Night | 10,615 | 147,904 | 13.93 | 17.07 |

All strata have ≥50 MODIS detections, so no fallback ratios were used.

### Holdout (calibrate 2012–2020, predict S-NPP for 2021–2023 from MODIS only)
- **Region-month MAPE 19.5%, bias −10.0%** (n = 36 months).
- **Top-5 busiest months matched 5/5**, in the same order:

| Rank | Actual month | Actual S-NPP | Predicted month | Predicted |
|---:|---|---:|---|---:|
| 1 | 2023-08 | 440,006 | 2023-08 | 409,755 |
| 2 | 2023-07 | 402,956 | 2023-07 | 388,837 |
| 3 | 2021-07 | 345,426 | 2021-07 | 382,886 |
| 4 | 2023-09 | 307,745 | 2023-09 | 286,444 |
| 5 | 2023-06 | 296,665 | 2023-06 | 277,645 |

By stratum (month × stratum level):

| Season | Day/night | n | MAPE | Bias |
|---|---|---:|---:|---:|
| Fire | Day | 15 | 17.5% | +9.3% |
| Fire | Night | 15 | 15.7% | +1.2% |
| Off | Day | 21 | 22.8% | −21.4% |
| Off | Night | 21 | 36.1% | −27.3% |

Error is lowest in fire season, where most detections are. Off-season, especially at night, is under-predicted: MODIS sees very few small, cool night fires, so ratios there rest on small counts.

### 2011→2012 sensor jump
- Raw (MODIS + S-NPP stitched): **+785.4%**
- Harmonized: **+59.1%** (+62.2% before #3 kept observed zero S-NPP counts)
- MODIS alone (same sensor both years, 48,859 → 78,438): **+60.5%**

So the harmonized change matches the real change measured by one consistent sensor, and the fake sensor-switch jump is gone.

## Per-region results, old single-ratio rule (2026-11-14, data-v2)
> **Superseded.** The old rule is kept here for comparison. Every region now ships with the optimised rule above.
Each app preset region is calibrated on its own 2012–2020 overlap. A stratum with fewer than 50 MODIS detections falls back to the global ratio for that stratum. "Canada core fires" lies inside the Canada box, so it uses Canada's ratios.
Command: `python pipeline/build_regions.py` (writes `data/monthly_harmonized_all.parquet` and `data/calibration_regions.json`).

### Ratios (S-NPP / MODIS, 2012–2020)
| Region (W,S,E,N) | Fire day | Fire night | Off day | Off night | Fallback strata |
|---|---:|---:|---:|---:|---:|
| Canada (−140,42,−52,72), own; ships with global | 3.69 | 8.42 | 2.28 | 13.93 | 0 |
| Amazon (−75,−15,−45,5) | 3.16 | 6.56 | 3.53 | 5.62 | 0 |
| Mediterranean (−10,35,30,45) | 2.90 | 6.01 | 2.86 | 10.76 | 0 |
| Global (fallback) | 3.46 | 8.53 | 3.55 | 9.47 | – |

Every regional stratum had at least 6,307 MODIS detections, so no fallback was needed. "Fire" is May–Sep for every region. That matches the northern-hemisphere seasons; for the Amazon it is just a fixed split of the year, still learned and applied consistently.

### Holdout (calibrate 2012–2020, predict S-NPP 2021–2023 from MODIS only)
| Region | Cells | MAPE, own ratios | MAPE, global ratios | **Shipped** | Shipped bias | Top-5 months |
|---|---:|---:|---:|---|---:|---:|
| Canada | 18,060 | 19.5% | 16.9% | **global, 16.9%** | −1.0% | 5/5 |
| Amazon | 8,400 | 17.9% | 32.9% | **own, 17.9%** | +14.9% | 5/5 |
| Mediterranean | 3,861 | 20.6% | 26.9% | **own, 20.6%** | −1.1% | 4/5 |

Each region ships with whichever ratios gave the lower holdout error. Regional ratios matter: global ratios alone nearly double the Amazon error. Canada was the exception and shipped with global ratios under the old rule (`RATIO_SOURCE`, removed in #38; every region now ships the optimised rule).

Canada with global ratios, by stratum:

| Season | Day/night | n | MAPE | Bias |
|---|---|---:|---:|---:|
| Fire | Day | 15 | 15.9% | +2.5% |
| Fire | Night | 15 | 16.2% | +2.5% |
| Off | Day | 21 | 23.6% | +22.6% |
| Off | Night | 21 | 50.6% | −50.6% |

Fire-season error and bias both improve over Canada's own ratios. Off-season nights get worse, because the global off-night ratio (9.47) is lower than Canada's (13.93), but those months carry few detections. The top-5 months still match 5/5: Aug 2023, Jul 2023, Jul 2021, Sep 2023, Jun 2023.
Old-rule check (Canada's own ratios): `python pipeline/grid_validate.py --staging data/regions/canada_staging.parquet --old-rule`.

### 2011→2012 sensor jump by region
| Region | Raw | Harmonized | MODIS alone |
|---|---:|---:|---:|
| Canada (shipped, global ratios) | +785.4% | +55.9% | +60.5% |
| Amazon | +656.2% | +60.5% | +55.8% |
| Mediterranean | +496.0% | +29.0% | +33.8% |

In every region the harmonized change is within 5 points of the single-sensor MODIS change, and the fake sensor-switch jump is gone. (Canada with its own ratios: +59.1%.)

## Cell-day counts vs detections (2026-11-14, #15): not adopted
**Test:** count each 0.05° cell (~5 km) at most once per day, per day/night and per satellite, instead of counting every detection. This removes repeat passes and VIIRS's extra detections of the same fire. Built from all 660M raw detections (the Hugging Face dataset downloaded to `data/firms`, laid out as `sensor=*/year=*/*.parquet`). Commands, with separate output paths so the shipped detection outputs are not overwritten:
```bash
python summarise/build_monthly_grid.py --input data/firms --cell-days 0.05   # -> data/derived/monthly_celldays_025.parquet
python pipeline/build_regions.py --input data/derived/monthly_celldays_025.parquet --outdir data/regions_celldays     --out data/monthly_harmonized_all_celldays.parquet --calibration-out data/calibration_regions_celldays.json     --app-out data/monthly_harmonized_celldays.parquet
``` Same filters as the detection grid (vegetation, confidence n/h, Terra/Aqua/S-NPP); 165M cell-days worldwide.

**Ratios shrink a lot:** Canada's fire-season night ratio drops from 8.42 to 2.65. In Canada one cell-day holds 4.4 detections on average, against 2.2 in the Amazon and 1.9 in the Mediterranean. So much of VIIRS's extra count is the same fire detected repeatedly, not extra fires.

**Holdout MAPE (calibrate 2012–2020, predict S-NPP 2021–2023)**
| Region | Detections, own | Detections, global | Cell-days, own | Cell-days, global | Best |
|---|---:|---:|---:|---:|---|
| Canada | 19.5% | **16.9%** | 27.9% | 48.9% | detections |
| Amazon | 17.9% | 32.9% | **17.3%** | 35.2% | cell-days, by 0.6 points |
| Mediterranean | **20.6%** | 26.9% | 25.7% | 25.4% | detections |

**2011→2012 jump, cell-day units, shipped ratio choice:** Canada −4.2% (MODIS cell-days alone +49.5%), Amazon +49.3% (+50.2%), Mediterranean +2.1% (+22.7%). With detections, every region was within 5 points of MODIS.

**Decision:** keep detection counts. Cell-days lower the error only in the Amazon, by 0.6 points, and make Canada and the Mediterranean clearly worse, including the 2012 jump. Mixing units across regions isn't worth 0.6 points. The `--cell-days` option stays in `build_monthly_grid.py` so the test can be repeated.

### Not yet done
- [ ] Coverage check per sensor-year (NRT vs standard-processing months, see #14)
- [ ] Export the extra regions to the app (#11): all three regions make `monthly.json` 17.9 MB instead of 4.2 MB
- [x] Cell-day counting (#15): tested above, not adopted
- [ ] NBAC 2023 correlation (`validate_nbac.py`, skips until the NBAC file is present)

## Pipeline test (synthetic data, NOT science results)
These runs checked that the pipeline recovers a planted ratio. Do not quote them as results.

### Synthetic ground-truth test (2026-11-14)
Synthetic data planted: VIIRS/MODIS ratio 2.8, 2023 = 3× normal, random locations in Canada bbox.
- Clean: 16,266 rows in → 16,266 cleaned (0 dropped: synthetic was pre-clean by construction; filter drops were verified separately in the planning chat's edge-case test: bbox, low-confidence, type≠0, dupes all dropped correctly there)
- Monthly aggregate: 16,181 cell-months (sparse because synthetic locations are random, real fires cluster)
- Recovered calibration: global ratio 2.664 vs planted 2.8 (within 5%); strata 2.27–2.84, except 100+ MW off-season 3.83 (n=6 MODIS, small-sample noise, flagged)
- Holdout (calib 2012–2020, test 2021–2023, month-strata): overall MAPE 0.550, bias +0.290, inflated by tiny synthetic month-stratum counts.
- Raw 2011→2012 jump +255.4% → harmonized +99.0% on synthetic.
- May 2023 anomaly on synthetic: 5.9× the 2001–2020 May median.

### Calibration v3 on the same synthetic data (2026-11-14)
Changes: S-NPP only as VIIRS reference, day/night strata, per-detection weights, Terra-only ratios before Aqua, era rule (S-NPP observed from Feb 2012).
- Global ratio 2.664 vs planted 2.8; Terra-only ratios ~5.6 (synthetic Terra is about half of MODIS, as expected)
- Holdout region-month MAPE 0.210, bias +0.046; top-5 busiest months matched 4/5
- Raw 2011->2012 jump +255.4% -> harmonized -7.2%

## Known flaw found and fixed during build
Calibration v1 computed ratios per grid cell-month requiring both sensors in the same
cell: too sparse, ratios collapsed to 1.0. v2 aggregates detections region-wide per
stratum. The v1 failure is why the synthetic ground-truth test exists.
