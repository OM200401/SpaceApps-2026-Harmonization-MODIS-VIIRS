# v2 harmonization

Goal: MODIS → S-NPP conversion error under 5% in every region and worldwide.
Result: reached for **annual totals everywhere** and for **monthly totals in 5 of 8 regions and worldwide**.
Canada, the Mediterranean and US West stay above 5% on monthly totals (6.5%, 7.5%, 5.2%).

These scripts rebuild their own tables from the raw FIRMS detections (`../parquet`) into
`data/experiments_v2/` (git-ignored). `pipeline/build_global_v2.py` feeds the result to the app (see below).

## What changed against the shipped rule (issue #37)

**Data (found by going back to raw detections)**

| Problem | Evidence | Fix |
|---|---|---|
| Terra and Aqua orbits drift after 2021 | Mean overpass time is flat through 2021, then Terra 10:33 → 09:26 and Aqua 13:36 → 14:45 by 2025 | Fit and test on 2012–2021 only. The shipped fit (Feb 2012–2025) and its 2021–2023 holdout both include drift years, which don't represent 2000–2011 |
| Sensor outage days | Aqua out 16 Aug–2 Sep 2020, S-NPP 16 days in 2022 and 25 in 2024, Terra 11 days in Feb 2016 | Drop a day for every sensor when Terra, Aqua or S-NPP is out (`build_month.py`) |
| Gas flares typed as vegetation fire | Permian, Bakken, Gulf states, Algeria: S-NPP sees them at night, MODIS barely | Persistence mask: burns year-round and mostly at night (`build_static.py`). Removes about 1.7% of S-NPP detections |
| S-NPP ran low in its first months | March 2012 S-NPP/MODIS is 20% below the 2013–2019 mean | Start in June 2012 |

**Rule (`gbm.py`)**, one model for the whole world, at 1° block × month × day/night:

1. *MODIS seen in this half of the day:* MODIS × block ratio, times a correction learned by gradient boosting
   (LightGBM, Poisson, linear leaves). Block ratios shrink world → 10° tile → block.
2. *No MODIS in this half of the day, but MODIS evidence in the other half or at low confidence:* a second
   small model. This is about 4% of night-time S-NPP.
3. *No MODIS evidence at all:* the block's average S-NPP under that condition.

Inputs are MODIS-only: counts by satellite, FRP mix, scan angle, confidence mix, hot-pixel share, active
days, the other half of the day, the months before and after, neighbouring blocks, the 10° tile.

**Weak spots from the review, and what happened to each**

| Weak spot | Now |
|---|---|
| Fixed May–Sep season | Hemisphere-aware month position, learned |
| Ratio of sums leans on big months | Poisson fit on block-months, corrections learned from intensity features |
| 4 season strata vs 24 monthly power laws | One model |
| Hand-drawn region boxes | Fixed 10° tiles for context; regions are only used for scoring |
| Constant over time | Drift years removed; no time term needed inside 2012–2021 |
| One shrink strength | Kept (k = 200) as the starting point; the model corrects it |
| Terra-only path had no test | Tested by removing Aqua from the overlap years (below) |

## Results

Leave-one-year-out over 2012–2021 (fit on nine years, predict the tenth), same cleaned data for every rule.
Errors are on region-month totals, day + night.

**Monthly totals, total-weighted (WAPE = Σ|error| ÷ Σ actual)**

| Region | Old single ratio | Shipped rule | **New** | Floor* |
|---|---:|---:|---:|---:|
| Canada | 15.4% | 11.3% | **6.5%** | 2.5% |
| Amazon | 4.9% | 2.9% | **2.7%** | 1.8% |
| Mediterranean | 11.3% | 8.2% | **7.5%** | 4.1% |
| US West | 8.6% | 6.3% | **5.2%** | 3.2% |
| Siberia | 10.7% | 8.6% | **4.4%** | 1.8% |
| Southern Africa | 8.2% | 2.4% | **2.0%** | 1.1% |
| SE Asia | 8.7% | 4.6% | **3.9%** | 1.8% |
| N Australia | 10.1% | 6.0% | **3.3%** | 2.3% |
| World | 4.1% | 2.1% | **1.5%** | 0.7% |

\* Floor = NOAA-20 predicting S-NPP with block ratios (same instrument, 50 minutes apart, 2019–2025).

**Other views of the new rule**

| Region | Annual total error (mean) | Worst year | Mean monthly error, main months† | Mean monthly error, all months | Bias |
|---|---:|---:|---:|---:|---:|
| Canada | 4.3% | 14.5% | 5.8% | 6.9% | −2.3% |
| Amazon | 1.3% | 2.9% | 4.1% | 4.4% | +0.5% |
| Mediterranean | 3.6% | 9.3% | 9.6% | 13.0% | +2.3% |
| US West | 3.0% | 9.2% | 7.4% | 8.1% | −1.2% |
| Siberia | 2.2% | 5.2% | 5.0% | 33.1% | +0.5% |
| Southern Africa | 1.3% | 3.0% | 2.3% | 4.6% | 0.0% |
| SE Asia | 2.4% | 5.4% | 4.4% | 9.5% | +1.5% |
| N Australia | 1.2% | 3.6% | 4.0% | 5.8% | −0.7% |
| World | 0.7% | 1.4% | 1.5% | 1.5% | −0.1% |

† Months holding at least 1% of an average year's detections.

**Checks**

- Forward holdout inside the stable years (fit 2012–2018, predict 2019–2021): WAPE Canada 6.7%, Amazon 2.8%,
  Mediterranean 6.8%, US West 6.9%, Siberia 4.2%, world 1.7%. In line with the table above.
- Old protocol (fit 2012–2020, predict 2021–2023, drift years): new rule WAPE Canada 5.8%, Amazon 3.9%,
  Mediterranean 8.3% against the shipped rule's 9.7%, 3.9%, 10.0%. On mean monthly error the new rule is better
  for Canada (7.3% vs 12.9%) but worse for the Amazon (6.6% vs 5.2%) and the Mediterranean (14.7% vs 13.2%):
  it uses Terra and Aqua separately, so it is more exposed to the drift.
- Three seeds averaged: no change beyond 0.2 points.

**Terra-only path (months before July 2002)**, tested by dropping Aqua from 2012–2021:

| Region | Shipped Terra ratio | New, Terra-only |
|---|---:|---:|
| Canada | 14.0% | 7.9% |
| Amazon | 9.8% | 5.7% |
| Mediterranean | 12.2% | 9.4% |
| US West | 10.5% | 6.6% |
| Siberia | 12.0% | 5.3% |
| Southern Africa | 7.1% | 4.1% |
| SE Asia | 16.1% | 7.5% |
| N Australia | 15.9% | 5.6% |
| World | 5.8% | 2.7% |

## Why three regions stay above 5%

- **Megafire months.** In Canada, six months carry about 60% of all the error (NWT July 2014: −24%, BC August
  2018: −11%). There S-NPP/MODIS jumps from about 5 to 10–29 per block: smoke and smouldering ground that MODIS
  misses. Leave-one-year-out hides the only comparable event from the fit, so this number is pessimistic for a
  final fit on all ten years, but that can't be shown.
- **Small fires MODIS never sees.** In the Mediterranean 8% of S-NPP detections fall in block-months with no
  same-time MODIS detection. Quiet winter months are mostly this, which is why the all-months average is 13%.
- The NOAA-20 floor shows the months themselves are predictable (3–5% mean monthly error with an equal sensor).
  The gap is MODIS sensitivity, not noise.

## Applied to 2000–2011 and the app (on top of PR #43)

1. `build_daily.py --years 2000-2012 --out data/experiments_v2/daily_modis`, then
   `build_month.py --daily data/experiments_v2/daily_modis --out month_modis.parquet --modis-era`
   (Terra/Aqua outage days dropped, e.g. Terra 15 Jun – 3 Jul 2001; months scaled back up by days kept).
2. `apply_modis_era.py`: fits the full and Terra-only models on June 2012 – 2021, estimates every 1° block-month
   for Nov 2000 – Jan 2012 (Terra-only model before July 2002), splits to 0.25° cells by MODIS detections, or by
   the cell's 2012–2021 S-NPP share where MODIS saw nothing. Fill values under 0.5 in cells with no MODIS are
   dropped (0.24% of the total) to keep tiles small.
3. `pipeline/build_global.py` (PR #43, shipped rule) for the raw counts, then `pipeline/build_global_v2.py`:
   swaps in the v2 estimates before Feb 2012 and removes flare detections from observed S-NPP after.
4. `pipeline/export_tiles.py --monthly data/monthly_harmonized_global_v2.parquet`.

World 2011→2012 harmonized jump: shipped +6.8%, v2 +5.4%. Canada preset: +59.8% against +60.5% for MODIS alone.

## Not done

- `app/data/monthly.json` (Canada only, read by the check scripts) is not regenerated.
- `docs/VALIDATION.md` and the project page still describe the shipped rule.
- Biome prior (MCD12C1 land cover): tested earlier, no out-of-sample gain over block ratios. Dropped.
- MODIS burned area (MCD64A1) as an extra input for megafire months: not tried, needs a new download.
- The flare mask is built from S-NPP 2012–2021 and applied to all sensors and years. It changes what counts as
  a fire, so the app's observed S-NPP months would need the same mask.

## Run order

From the repo root, with the raw Parquet in `../parquet` and the venv in `../.venv`:

```bash
bash experiments/v2/run_all.sh          # ~50 min: mask, daily and monthly tables, Terra-only tables, scores
cd experiments/v2
python run_base.py                      # noise floor, old-protocol and forward-holdout checks
python report.py old shipped gbm_lin    # comparison tables from saved predictions
```

| File | Does |
|---|---|
| `build_static.py` | Persistent hot-spot mask (two tiers) |
| `build_daily.py` | Raw detections → daily 0.25° table with per-detection features |
| `build_month.py` | Outage days, then monthly table on matched days |
| `h2.py` | Block-month units, leave-one-year-out runner, scoring |
| `models.py` | Old ratio, shipped rule, ratio encodings |
| `gbm.py` | The new rule |
| `run_gbm.py`, `run_base.py`, `report.py` | Runs and tables |
