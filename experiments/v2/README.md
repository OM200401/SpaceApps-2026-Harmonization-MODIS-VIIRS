# v2 harmonization

Goal: MODIS → S-NPP conversion error under 5% in every region and worldwide.
Result: reached for **annual totals everywhere** and for **monthly totals in 6 of 8 regions and worldwide**.
Canada and the Mediterranean stay above 5% on monthly totals (6.5%, 7.3%).

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
Errors are on monthly totals (day + night) of all 1° blocks inside each preset's bounds; the presets overlap
(Canada and US West share 42–49° N), so each is scored over its whole box.
The old and shipped rules are fitted as in production: Canada, Amazon, Mediterranean, and 30° boxes everywhere
else, with the global ratio for thin strata (`pipeline/build_global.py`).

**Monthly totals, total-weighted (WAPE = Σ|error| ÷ Σ actual)**

| Region | Old single ratio | Shipped rule | **New** | Floor* |
|---|---:|---:|---:|---:|
| Canada | 15.4% | 11.3% | **6.5%** | 2.5% |
| Amazon | 4.8% | 2.8% | **2.6%** | 1.7% |
| Mediterranean | 10.8% | 7.9% | **7.3%** | 4.0% |
| US West | 13.7% | 8.8% | **4.4%** | 2.8% |
| Siberia | 10.8% | 8.5% | **4.5%** | 1.8% |
| Southern Africa | 6.8% | 2.8% | **2.0%** | 1.1% |
| SE Asia | 9.2% | 4.8% | **3.9%** | 1.8% |
| N Australia | 10.1% | 6.7% | **3.3%** | 2.3% |
| World | 3.6% | 2.1% | **1.5%** | 0.7% |

\* Floor = NOAA-20 predicting S-NPP with block ratios (same instrument, 50 minutes apart, 2019–2025).

**Other views of the new rule**

| Region | Annual total error (mean) | Worst year | Mean monthly error, main months† | Mean monthly error, all months | Bias |
|---|---:|---:|---:|---:|---:|
| Canada | 4.3% | 14.5% | 5.8% | 6.9% | −2.3% |
| Amazon | 1.2% | 2.8% | 3.9% | 4.2% | +0.5% |
| Mediterranean | 3.6% | 8.8% | 9.7% | 13.2% | +2.2% |
| US West | 2.6% | 6.5% | 5.5% | 6.5% | −0.6% |
| Siberia | 2.2% | 5.2% | 5.0% | 33.3% | +0.6% |
| Southern Africa | 1.2% | 2.9% | 2.3% | 4.6% | +0.1% |
| SE Asia | 2.4% | 5.3% | 4.4% | 9.6% | +1.5% |
| N Australia | 1.2% | 3.6% | 3.9% | 5.8% | −0.7% |
| World | 0.7% | 1.4% | 1.5% | 1.5% | −0.1% |

† Months holding at least 1% of an average year's detections.

**Checks**

- Forward holdout inside the stable years (fit 2012–2018, predict 2019–2021): WAPE Canada 6.7%, Amazon 2.7%,
  Mediterranean 6.9%, US West 6.1%, Siberia 4.2%, world 1.7%, against the shipped rule's 15.2%, 2.5%, 6.5%,
  12.1%, 8.7%, 2.8%.
- Old protocol (fit 2012–2020, predict 2021–2023, drift years): new rule WAPE Canada 5.8%, Amazon 4.0%,
  Mediterranean 8.4%, US West 4.1%, world 2.9% against the shipped rule's 9.7%, 4.0%, 9.9%, 12.9%, 3.7%. On mean
  monthly error the new rule is worse for the Amazon (6.3% vs 5.1%) and the Mediterranean (15.2% vs 12.9%):
  it uses Terra and Aqua separately, so it is more exposed to the drift.
- Three seeds averaged: no change beyond 0.1 points.
- The flare mask is built from all of 2012–2021, so a held-out year's own S-NPP helps decide which spots are
  masked. Rebuilding the mask without each held-out year changes the mask status of 0.2–0.4% of that year's
  S-NPP detections (at most 0.5% in a region, SE Asia). That bounds the effect on the scores at about half a
  point; the full per-fold rebuild (about 5 hours) was not run.

**Terra-only path (months before July 2002)**, tested by dropping Aqua from 2012–2021:

| Region | Shipped Terra ratio | New, Terra-only |
|---|---:|---:|
| Canada | 14.1% | 7.9% |
| Amazon | 9.7% | 5.6% |
| Mediterranean | 11.5% | 9.2% |
| US West | 11.4% | 5.8% |
| Siberia | 12.3% | 5.4% |
| Southern Africa | 8.2% | 4.0% |
| SE Asia | 18.2% | 7.3% |
| N Australia | 16.5% | 5.6% |
| World | 6.4% | 2.7% |

## Why two regions stay above 5%

- **Megafire months.** In Canada, six months carry about 60% of all the error (NWT July 2014: −24%, BC August
  2018: −11%). There S-NPP/MODIS jumps from about 5 to 10–29 per block: smoke and smouldering ground that MODIS
  misses. Leave-one-year-out hides the only comparable event from the fit, so this number is pessimistic for a
  final fit on all ten years, but that can't be shown.
- **Small fires MODIS never sees.** In the Mediterranean 8% of S-NPP detections fall in block-months with no
  same-time MODIS detection. Quiet winter months are mostly this, which is why the all-months average is 13%.
- The NOAA-20 floor shows the months themselves are predictable (2–5% mean monthly error with an equal sensor).
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
   swaps in the v2 estimates before Feb 2012; from Feb 2012 the record is observed S-NPP (`viirs_count`) minus
   flare detections, counted from the raw data with the base grid's archive / near-real-time rules.
4. `pipeline/export_tiles.py --monthly data/monthly_harmonized_global_v2.parquet`, then zip `index.json`, `c/`
   and `d/` from `app/data/` and upload it as a release (currently `tiles-v2`, read by `pipeline/fetch_tiles.py`).

World 2011→2012 harmonized jump: shipped +6.8%, v2 +5.6%. Canada preset: +59.8% against +60.5% for MODIS alone.

## Not done

- `app/data/monthly.json` (Canada only, read by the check scripts) is not regenerated.
- `docs/VALIDATION.md` and the project page still describe the shipped rule.
- Biome prior (MCD12C1 land cover): tested earlier, no out-of-sample gain over block ratios. Dropped.
- MODIS burned area (MCD64A1) as an extra input for megafire months: not tried, needs a new download.
- The flare mask is built from S-NPP 2012–2021 and applied to all sensors and years, including the app's
  observed S-NPP months (−1.3% worldwide, more in oil fields). Raw counts are unchanged.

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
