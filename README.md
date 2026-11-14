# Harmonization of MODIS and VIIRS Hot Spots

NASA Space Apps Challenge 2026. Team: Om, Ishan, Sparsh, Pratham.

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
summarise/          builds the monthly grid summary table from raw FIRMS data
  build_monthly_grid.py
  README.md         full column reference and caveats
requirements.txt
```

More folders (harmonization, backend, frontend) will be added as the work starts.

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
| Quill | Code and documentation |
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
