# Validation — numbers are from runs, never hand-written

## Estimator definition
Harmonized count (S-NPP VIIRS-equivalent units) per 0.25° cell-month:
- From Feb 2012: harmonized = observed S-NPP count, zeros included (reference sensor; zero handling fixed in #3).
- Before that: harmonized = MODIS count × ratio for its season × day/night stratum. Terra-only ratios apply before Aqua's July 2002 start.
- Ratios are region-wide S-NPP / MODIS detection ratios over the 2012–2020 overlap (`pipeline/grid_calibrate.py`).

## Real-data results (2026-11-14, data-v2, Canada)
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

## Per-region results (2026-11-14, data-v2)
Each app preset region is calibrated on its own 2012–2020 overlap. A stratum with fewer than 50 MODIS detections falls back to the global ratio for that stratum. "Canada core fires" lies inside the Canada box, so it uses Canada's ratios.
Command: `python pipeline/build_regions.py` (writes `data/monthly_harmonized_all.parquet` and `data/calibration_regions.json`).

### Ratios (S-NPP / MODIS, 2012–2020)
| Region (W,S,E,N) | Fire day | Fire night | Off day | Off night | Fallback strata |
|---|---:|---:|---:|---:|---:|
| Canada (−140,42,−52,72) | 3.69 | 8.42 | 2.28 | 13.93 | 0 |
| Amazon (−75,−15,−45,5) | 3.16 | 6.56 | 3.53 | 5.62 | 0 |
| Mediterranean (−10,35,30,45) | 2.90 | 6.01 | 2.86 | 10.76 | 0 |
| Global (fallback) | 3.46 | 8.53 | 3.55 | 9.47 | — |

Every regional stratum had at least 6,307 MODIS detections, so no fallback was needed. "Fire" is May–Sep for every region. That matches the northern-hemisphere seasons; for the Amazon it is just a fixed split of the year, still learned and applied consistently.

### Holdout (calibrate 2012–2020, predict S-NPP 2021–2023 from MODIS only)
| Region | Cells | MAPE, own ratios | Bias, own ratios | MAPE, global ratios only | Top-5 months |
|---|---:|---:|---:|---:|---:|
| Canada | 18,060 | **19.5%** | −10.0% | 16.9% | 5/5 |
| Amazon | 8,400 | **17.9%** | +14.9% | 32.9% | 5/5 |
| Mediterranean | 3,861 | **20.6%** | −1.1% | 26.9% | 4/5 |

Regional ratios matter: global ratios alone nearly double the Amazon error. Canada is the exception: global ratios do slightly better there than its own (16.9% vs 19.5%), even though Canada's own ratios come from 659k MODIS detections.

### 2011→2012 sensor jump by region
| Region | Raw | Harmonized | MODIS alone |
|---|---:|---:|---:|
| Canada | +785.4% | +59.1% | +60.5% |
| Amazon | +656.2% | +60.5% | +55.8% |
| Mediterranean | +496.0% | +29.0% | +33.8% |

In every region the harmonized change is within 5 points of the single-sensor MODIS change, and the fake sensor-switch jump is gone.

### Not yet done
- [ ] Coverage check per sensor-year (NRT vs standard-processing months, see #14)
- [ ] Export the extra regions to the app (#11): all three regions make `monthly.json` 17.9 MB instead of 4.2 MB
- [ ] Cell-day counting, kept only if it lowers the MAPE above (#15)
- [ ] NBAC 2023 correlation (`validate_nbac.py`, skips until the NBAC file is present)

## Pipeline test (synthetic data, NOT science results)
These runs checked that the pipeline recovers a planted ratio. Do not quote them as results.

### Synthetic ground-truth test (2026-11-14)
Synthetic data planted: VIIRS/MODIS ratio 2.8, 2023 = 3× normal, random locations in Canada bbox.
- Clean: 16,266 rows in → 16,266 cleaned (0 dropped: synthetic was pre-clean by construction; filter drops were verified separately in the planning chat's edge-case test: bbox, low-confidence, type≠0, dupes all dropped correctly there)
- Monthly aggregate: 16,181 cell-months (sparse because synthetic locations are random, real fires cluster)
- Recovered calibration: global ratio 2.664 vs planted 2.8 (within 5%); strata 2.27–2.84, except 100+ MW off-season 3.83 (n=6 MODIS, small-sample noise, flagged)
- Holdout (calib 2012–2020, test 2021–2023, month-strata): overall MAPE 0.550, bias +0.290 — inflated by tiny synthetic month-stratum counts.
- Raw 2011→2012 jump +255.4% → harmonized +99.0% on synthetic.
- May 2023 anomaly on synthetic: 5.9× the 2001–2020 May median.

### Calibration v3 on the same synthetic data (2026-11-14)
Changes: S-NPP only as VIIRS reference, day/night strata, per-detection weights, Terra-only ratios before Aqua, era rule (S-NPP observed from Feb 2012).
- Global ratio 2.664 vs planted 2.8; Terra-only ratios ~5.6 (synthetic Terra is about half of MODIS, as expected)
- Holdout region-month MAPE 0.210, bias +0.046; top-5 busiest months matched 4/5
- Raw 2011->2012 jump +255.4% -> harmonized -7.2%

## Known flaw found and fixed during build
Calibration v1 computed ratios per grid cell-month requiring both sensors in the same
cell — too sparse, ratios collapsed to 1.0. v2 aggregates detections region-wide per
stratum. The v1 failure is why the synthetic ground-truth test exists.
