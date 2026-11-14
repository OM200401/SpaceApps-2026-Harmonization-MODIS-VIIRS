# Validation — numbers are from runs, never hand-written

## Estimator definition
Harmonized count (S-NPP VIIRS-equivalent units) per 0.25° cell-month:
- From Feb 2012: harmonized = observed S-NPP count, zeros included (reference sensor; zero handling fixed in #3).
- Before that: harmonized = MODIS count × ratio for its season × day/night stratum. Terra-only ratios apply before Aqua's July 2002 start.
- Ratios are region-wide S-NPP / MODIS detection ratios over the 2012–2020 overlap. Each region uses its own ratios, or the global ones where those score better in the holdout. Canada ships with global ratios (`pipeline/build_regions.py`, see Per-region results).

## Real-data results (2026-11-14, data-v2, Canada, own ratios)
> **Superseded for the shipped data.** This section fits Canada's own ratios. Canada now ships with global ratios, which give a lower holdout error (16.9% vs 19.5%); see Per-region results below.

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
| Canada (−140,42,−52,72), own; ships with global | 3.69 | 8.42 | 2.28 | 13.93 | 0 |
| Amazon (−75,−15,−45,5) | 3.16 | 6.56 | 3.53 | 5.62 | 0 |
| Mediterranean (−10,35,30,45) | 2.90 | 6.01 | 2.86 | 10.76 | 0 |
| Global (fallback) | 3.46 | 8.53 | 3.55 | 9.47 | — |

Every regional stratum had at least 6,307 MODIS detections, so no fallback was needed. "Fire" is May–Sep for every region. That matches the northern-hemisphere seasons; for the Amazon it is just a fixed split of the year, still learned and applied consistently.

### Holdout (calibrate 2012–2020, predict S-NPP 2021–2023 from MODIS only)
| Region | Cells | MAPE, own ratios | MAPE, global ratios | **Shipped** | Shipped bias | Top-5 months |
|---|---:|---:|---:|---|---:|---:|
| Canada | 18,060 | 19.5% | 16.9% | **global, 16.9%** | −1.0% | 5/5 |
| Amazon | 8,400 | 17.9% | 32.9% | **own, 17.9%** | +14.9% | 5/5 |
| Mediterranean | 3,861 | 20.6% | 26.9% | **own, 20.6%** | −1.1% | 4/5 |

Each region ships with whichever ratios gave the lower holdout error. Regional ratios matter: global ratios alone nearly double the Amazon error. Canada is the exception, so it ships with global ratios (`RATIO_SOURCE` in `build_regions.py`).

Canada with global ratios, by stratum:

| Season | Day/night | n | MAPE | Bias |
|---|---|---:|---:|---:|
| Fire | Day | 15 | 15.9% | +2.5% |
| Fire | Night | 15 | 16.2% | +2.5% |
| Off | Day | 21 | 23.6% | +22.6% |
| Off | Night | 21 | 50.6% | −50.6% |

Fire-season error and bias both improve over Canada's own ratios. Off-season nights get worse, because the global off-night ratio (9.47) is lower than Canada's (13.93), but those months carry few detections. The top-5 months still match 5/5: Aug 2023, Jul 2023, Jul 2021, Sep 2023, Jun 2023.
Check: `python pipeline/grid_validate.py --ratios data/calibration_regions.json`.

### 2011→2012 sensor jump by region
| Region | Raw | Harmonized | MODIS alone |
|---|---:|---:|---:|
| Canada (shipped, global ratios) | +785.4% | +55.9% | +60.5% |
| Amazon | +656.2% | +60.5% | +55.8% |
| Mediterranean | +496.0% | +29.0% | +33.8% |

In every region the harmonized change is within 5 points of the single-sensor MODIS change, and the fake sensor-switch jump is gone. (Canada with its own ratios: +59.1%.)

## Cell-day counts vs detections (2026-11-14, #15) — not adopted
**Test:** count each 0.05° cell (~5 km) at most once per day, per day/night and per satellite, instead of counting every detection. This removes repeat passes and VIIRS's extra detections of the same fire. Built from all 660M raw detections with `python summarise/build_monthly_grid.py --input <raw parquet> --cell-days 0.05 --output data/derived/monthly_celldays_025.parquet`, then `build_regions.py --input` on that file. Same filters as the detection grid (vegetation, confidence n/h, Terra/Aqua/S-NPP); 165M cell-days worldwide.

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
