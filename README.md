# Harmonization of MODIS and VIIRS Hot Spots

NASA Space Apps Challenge 2026. Team: Om, Ishan, Sparsh, Pratham.

**Live app:** https://om200401.github.io/SpaceApps-2026-Harmonization-MODIS-VIIRS/app/
(GitHub Pages, published from the root of `main` and rebuilt on every merge.)

## The challenge

Satellites have recorded active fire hotspots for more than 20 years, but the
record is split between two sensor families that can't be compared directly:

- **MODIS** (Terra and Aqua): the long historical record from 2000, now near the end of its life.
- **VIIRS** (S-NPP, NOAA-20, NOAA-21): from 2012 on, with finer 375 m pixels and higher sensitivity, so it detects many more hotspots.

The two differ in spatial resolution, sensitivity and overpass times. Putting
their counts side by side therefore gives a misleading picture of when and where burning happened.

Our task is to build a **web application with a harmonized burning-activity
calendar** for any area a user selects. The challenge comes in two parts:

1. **Harmonization.** Combine NASA FIRMS hotspots from MODIS and VIIRS into one
   consistent monthly series from the early 2000s to today, so the sensor of
   origin no longer matters.
2. **Web application.** The user picks an area (draws it on a map or enters
   lat/lon) and a date range. The app then shows:
   - a year × month calendar of hotspot counts, using an accessible colour ramp
   - the busiest months and years
   - how the current month compares with the historical median (anomalies)
   - a CSV download of the hotspots found

The intended users are emergency responders, fire managers, land managers and scientists.

## Repository layout

```
index.html              redirects the Pages root URL to app/
app/                    the web app (static HTML/JS, no build step)
  index.html            homepage: map, month scrubber, "how unusual is this month?" status
  report.html           area report: verdict, season vs normal range, calendar, downloads
  how-it-works.html     raw vs harmonized, method, accuracy and caveats
  shared.js, shared.css data loading, display rules and page chrome used by all three pages
  data/monthly.json     harmonized data the app reads (made by pipeline/export_json.py)
pipeline/               harmonization: summary table -> calibrated monthly data -> app JSON
  build_regions.py        production path: harmonizes every preset region, prints holdout scores
  build_monthly_from_grid.py, grid_calibrate.py, grid_validate.py
                          slicing, ratio and holdout code that build_regions.py uses
  export_json.py          writes app/data/monthly.json
  verify_all.py           checks the harmonized data and the app JSON agree
  check_outputs.py        stage-by-stage output checks
  audit_engine.py         independent audit: recomputes every shipped number from the raw grid
  audit_claims.json       the audit's claims registry (expected values and tolerances)
  clean_firms.py, calibrate.py, validate_holdout.py
                          earlier path that works from raw FIRMS detections
  make_synthetic.py       synthetic test data (pipeline tests only, never results)
  validate_nbac.py        optional check against Canada's NBAC burned area
summarise/              builds the monthly grid summary table from raw FIRMS data
  build_monthly_grid.py
  README.md             full column reference and caveats
docs/                   validation results, audit report, UI data contract, demo script, project page draft
SPEC.md                 product spec and decisions log
requirements.txt
```

The app is live at https://om200401.github.io/SpaceApps-2026-Harmonization-MODIS-VIIRS/app/.
To run it locally, serve the repo root with any static server (for example
`python -m http.server`) and open `/app/`.

## Running the pipeline

This rebuilds `app/data/monthly.json` from the published summary table, in about a minute.
Run every command from the repo root.

**1. Install the dependencies**

```bash
pip install -r requirements.txt
```

**2. Download the summary table** into `data/derived/`

```bash
gh release download data-v2 --repo OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS --dir data/derived
```

**3. Calibrate and harmonize each preset region**

```bash
python pipeline/build_regions.py
```

This writes `data/regions/`, `data/monthly_harmonized.parquet` (Canada, the app's region),
`data/monthly_harmonized_all.parquet` (all regions) and `data/calibration_regions.json`.
It also prints each region's ratios and holdout scores. They should match `docs/VALIDATION.md`.

**4. Export the app data**

```bash
python pipeline/export_json.py --monthly data/monthly_harmonized.parquet
```

**5. Check the result**

```bash
python pipeline/verify_all.py
```

It should print `PASS`. If you rebuilt from `data-v2` without changing any code,
`git status` should also show `app/data/monthly.json` unchanged.

**Optional: rerun the Canada holdout on its own**

```bash
python pipeline/grid_validate.py --staging data/regions/canada_staging.parquet
```

## Independent audit

Do not take our word for any number in this project. The audit engine recomputes all of them from the raw data, with completely separate code, and shows its work.

```bash
python pipeline/audit_engine.py --selftest
```

The production pipeline is pandas. The audit rebuilds the data from the 55M-row grid in SQL (DuckDB), refits the harmonization rule from the written spec in `docs/VALIDATION.md`, and compares everything against expected values that were written down in advance (`pipeline/audit_claims.json`). The full report is `docs/AUDIT_REPORT.md`.

On the shipped record, it verifies:

- 308,806 cell-months rebuilt from the grid, zero differences
- May 2023 = 208,476, and the 2011 to 2012 jump: +785.4% raw, +60.8% harmonized
- every cell's harmonized value, refit independently, largest difference 0.005, which is the file's own rounding
- the holdout: fit 2012 to 2020, predict 2021 to 2023, MAPE 13.6%
- itself: it corrupts copies of the data 8 ways (quiet drift, swapped values, planted stale numbers) and must catch all 8. It does.

One limit, stated plainly: the audit certifies the Canada record the app ships, and the Terra-only months before July 2002 have no holdout coverage, here or anywhere in the project.

## Data

| Dataset | What it is | Size | Where |
|---|---|---|---|
| Raw FIRMS hotspots | All 660M detections, every sensor, Nov 2000 to Nov 2026, Parquet | ~10 GB | Hugging Face: [`undeadphoenix/firms-fire-data`](https://huggingface.co/datasets/undeadphoenix/firms-fire-data) |
| **Monthly grid summary** | Hotspot counts per 0.25° cell per month | 208 MB | GitHub Release: [`data-v2`](https://github.com/OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS/releases/tag/data-v2) |

**Use the monthly grid summary for almost everything:** the calendar,
harmonization, anomalies and charts. Only the CSV export of individual
hotspots needs the raw data.

### Accessing the summary table

**1. Install the dependencies (once)**

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

**2a. Query it straight from the URL (no download)**

DuckDB reads only the parts of the file it needs, so this takes about a second:

```python
import duckdb

GRID = "https://github.com/OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS/releases/download/data-v2/monthly_grid_025.parquet"

duckdb.sql(f"""
    SELECT year, month, sum(hotspots) AS hotspots
    FROM '{GRID}'
    WHERE is_vegetation
      AND confidence IN ('n', 'h')
      AND satellite = 'SNPP'
      AND cell_lat BETWEEN 29.5 AND 32.25      -- example: Punjab, India
      AND cell_lon BETWEEN 73.75 AND 76.75
    GROUP BY ALL ORDER BY ALL
""").df()
```

**2b. Or download it once and work locally**

```bash
gh release download data-v2 --repo OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS --dir data/derived
```

Without the GitHub CLI, download `monthly_grid_025.parquet` from the
[release page](https://github.com/OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS/releases/tag/data-v2)
into `data/derived/`. Then query `'data/derived/monthly_grid_025.parquet'` the same way.
pandas works too: `pd.read_parquet(path)`. The file has 55M rows, though, so it's usually faster to filter in DuckDB first.

### Columns at a glance

`cell_lat`, `cell_lon` (south-west corner of the 0.25° cell) · `year` · `month` ·
`sensor` · `satellite` (`Terra`, `Aqua`, `SNPP`, `N20`, `N21`) · `daynight` ·
`confidence` (`l`/`n`/`h`) · `is_vegetation` · `hotspots` · `frp_sum`

The full definitions, and how MODIS confidence and the vegetation flag were derived, are in [summarise/README.md](summarise/README.md).

### Before you analyse: three traps

- **MODIS is Terra-only before mid-2002.** Aqua joined in 2002, so the early years look low for that reason alone.
- **VIIRS gained satellites:** NOAA-20 from 2018 and NOAA-21 from 2023. Summing all of them creates a fake upward trend, so pick one satellite (`SNPP` covers 2012 to today).
- **November 2026 is a partial month.** Compare it with the same days in earlier years.

### Rebuilding the summary

You only need this if the grid size or cleaning logic changes. It needs ~10 GB of disk and about 4 minutes:

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download('undeadphoenix/firms-fire-data', repo_type='dataset', local_dir='data/firms', allow_patterns=['*.parquet'])"
python summarise/build_monthly_grid.py --cell 0.25
```

Publish a new version as a new release (`data-v3`, ...) so nobody's code breaks underneath them.

## Ground rules

- **Never commit data.** `.gitignore` blocks Parquet, CSV, ZIP and `data/`. Large files go to Hugging Face or a GitHub Release.
- **Never commit secrets.** FIRMS MAP_KEY and Hugging Face tokens go in `.env`, which is ignored.
- **Commit messages are one short line.**

## Use of AI

We used AI assistants to speed up building this project. The team directed and reviewed all of it.

| Tool | Used for |
|---|---|
| Claude (Anthropic) | Code (`summarise/build_monthly_grid.py`, parts of `pipeline/` and `app/`), data checks on the FIRMS tables, and documentation (READMEs, `docs/`) |
| Codex (OpenAI) | Code in `pipeline/` |
| Muse Code | Documentation |
| GitHub Copilot Autofix | One fix in `app/index.html` (median calculation) |

- **Ideas and method:** choosing the challenge, the product idea, and the harmonization method choices are the team's own. They include S-NPP as the reference sensor, season × day/night ratios, and the 2012–2020 calibration with 2021–2023 holdout.
- **Data:** every result comes from NASA FIRMS data run through this repo's scripts. `pipeline/make_synthetic.py` generates AI-assisted **synthetic** test data, used only to check that the pipeline recovers a planted ratio. It is labelled as synthetic everywhere it appears (`data/synthetic/`, the "Pipeline test" section of `docs/VALIDATION.md`) and is never shown as a result.
- **Images and video:** none in the app or demo are AI-generated. If any are added, they will carry a visible watermark, as the Space Apps rules require.

## Deadline

Project submission closes **Sunday, November 15, 11:59 p.m.** local event time.
The demo is either up to 7 slides or a video of 30 seconds or less. Every link must be public, with no login needed.

## Data source

NASA FIRMS (Fire Information for Resource Management System), LANCE / EOSDIS:
<https://firms.modaps.eosdis.nasa.gov/>. MODIS Collection 6.1 and VIIRS 375 m Collection 2 active fire products.
