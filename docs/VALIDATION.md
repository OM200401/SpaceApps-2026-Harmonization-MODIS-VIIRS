# Validation — numbers are from runs, never hand-written

## Estimator definition
Harmonized count (VIIRS-equivalent units) per cell-month:
- VIIRS present in cell-month: harmonized = viirs_count (observed, reference sensor)
- MODIS only: harmonized = modis_count × ratio(FRP-bin × season stratum)
Ratios are region-aggregated detection-count ratios from the overlap (calibrate.py v2).

## Synthetic ground-truth test (2026-11-14, pipeline verification — NOT science results)
Synthetic data planted: VIIRS/MODIS ratio 2.8, 2023 = 3× normal, random locations in Canada bbox.
- Clean: 16,266 rows in → 16,266 cleaned (0 dropped: synthetic was pre-clean by construction; filter drops were verified separately in the planning chat's edge-case test: bbox, low-confidence, type≠0, dupes all dropped correctly there)
- Monthly aggregate: 16,181 cell-months (sparse because synthetic locations are random, real fires cluster)
- Recovered calibration: global ratio 2.664 vs planted 2.8 (within 5%); strata 2.27–2.84, except 100+ MW off-season 3.83 (n=6 MODIS, small-sample noise, flagged)
- Holdout (calib 2012–2020, test 2021–2023, month-strata): overall MAPE 0.550, bias +0.290 — inflated by tiny synthetic month-stratum counts; re-run on real data before quoting.
- Raw 2011→2012 jump +255.4% → harmonized +99.0% on synthetic. Direction correct, magnitude will change on real data.
- May 2023 anomaly on synthetic: 5.9× the 2001–2020 May median.

## Calibration v3 on the same synthetic data (2026-11-14, pipeline verification, NOT science results)
Changes: S-NPP only as VIIRS reference, day/night strata, per-detection weights, Terra-only ratios before Aqua, era rule (S-NPP observed from Feb 2012).
- Global ratio 2.664 vs planted 2.8; Terra-only ratios ~5.6 (synthetic Terra is about half of MODIS, as expected)
- Holdout region-month MAPE 0.210, bias +0.046; top-5 busiest months matched 4/5
- Raw 2011->2012 jump +255.4% -> harmonized -7.2%

## Real-data validation (PENDING — runs when Ishan's HF Parquet lands)
- [ ] Coverage check per sensor-year (SPEC D1, NRT vs SP gate)
- [ ] Cleaning validation report (rows in / after bbox / after confidence / type / dupes)
- [ ] Calibration ratios + holdout MAPE/bias on real data → replace synthetic numbers above in a dated section
- [ ] Raw vs harmonized 2011→2012 jump on real data
- [ ] NBAC 2023 correlation (validate_nbac.py, graceful-skip until NBAC file present)

## Known flaw found and fixed during build
Calibration v1 computed ratios per grid cell-month requiring both sensors in the same
cell — too sparse, ratios collapsed to 1.0. v2 aggregates detections region-wide per
stratum. The v1 failure is why the synthetic ground-truth test exists.
