# Harmonization experiments

These are the scripts that compared about 90 MODIS → S-NPP conversion rules and chose the one in
`pipeline/grid_calibrate.py` (issue #37). They are not part of the app pipeline. Their inputs and
results go to `data/experiments/` (git-ignored); set `EXP_DATA` to use another folder.

## Setup

```bash
pip install -r requirements.txt -r experiments/requirements.txt
gh release download data-v2 --repo OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS --dir data/derived
```

Run every command from the repo root.

## Run order

| Step | Command | Time | What it does |
|---|---|---|---|
| 1 | `python experiments/prep.py` | ~1 min | Extracts 8 regions (3 app presets + US West, Siberia, southern Africa, SE Asia, northern Australia) from the summary table |
| 2 | `python experiments/run_baseline.py` | ~30 s | Builds the region tables and **reproduces the old pipeline holdout** (Canada 19.55% / 16.91% global, Amazon 17.92%, Mediterranean 20.62%). If these don't match, stop. |
| 3 | `python experiments/run_suite.py A` (then `B`, `C`) | 5–30 min each | Ratio variants and per-area ratios; power law and Poisson regression; fire-size bins and gradient boosting |
| 4 | `python experiments/run_suite_d.py`, then `run_suite_e.py` | ~10 min each | Combined per-area ratio + power law sweep, then blend weights |
| 5 | `python experiments/run_conf.py` | ~5 min | Confidence-filter sensitivity (h / n+h / l+n+h) |
| 6 | `python experiments/run_final.py` | ~10 min | Shortlist: fixed holdout, extreme-month bias, error bands, 2011→2012 seam |
| 7 | `python experiments/run_nested.py 0.5`, `… 1`, `… 2`, then `… outer` | ~15 min | **Clean check:** choose block size, k and blend weight using only 2012–2020, then score once on the untouched 2021–2023 holdout |

Steps 3–6 append to or write `data/experiments/results*.csv`. Phases can run in parallel.

## How scoring works

- **Leave-one-year-out (steps 3–6):** for each test year from 2013 to 2025, fit on every other overlap year (Feb 2012 – 2025) and predict that year from MODIS alone. All test months are scored together.
- **Fixed holdout:** fit on 2012–2020 and predict 2021–2023. This is the same test as `pipeline/grid_validate.py`.
- **Metrics:** computed on region-month totals with S-NPP > 0.
  - MAPE: mean |error| ÷ actual
  - WAPE: Σ|error| ÷ Σ actual
  - bias: mean signed % error
  - 1° WAPE: the same as WAPE, on 1° block-months

**Caveat:** steps 3–6 used years that include 2021–2023, so the fixed-holdout numbers from those steps are not a clean out-of-sample result. Step 7 is the clean version: it chooses the settings without seeing 2021–2023.
