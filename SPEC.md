# Murphy — Harmonized MODIS + VIIRS Burning Calendar
NASA Space Apps Challenge 2026 | Challenge: Harmonization of MODIS and VIIRS Hot Spots
Team Murphy: Pratham Shah (Toronto), Om Mistry (owner, Calgary), Sparsh Khanna, Ishan
Deadline: Sun Nov 15, 2026 11:59 PM MT (Om, Calgary) = Mon Nov 16 01:59 AM ET. Target submit: Sun evening ET.

## Problem
MODIS (1 km, 2000+) and VIIRS (375 m, 2012+) see the same fires differently.
VIIRS detects many more small fires. Splicing the raw records creates a fake
jump in 2012. Users cannot tell real trends from sensor change.

## Product
Web app that fuses both records into ONE harmonized monthly burning-activity
calendar, 2001–2025, for a user-selected bbox (showcase: Canada boreal,
-140,42,-52,72). Sensor of origin no longer matters in the harmonized view.

Views (acceptance in brackets):
1. Calendar heatmap: year × month grid, value = harmonized_count (also raw toggle).
   [renders from data/monthly.json; 2023 row visibly hottest; accessible ramp + numeric tooltip]
2. Raw vs Harmonized toggle. [same cell/month, two values; 2012 discontinuity visible in raw, reduced in harmonized]
3. Anomaly view: cell/month or region/month vs 2001–2020 median for that month; May 2023 flagged.
   [region aggregate shows May 2023 anomaly ratio computed from data, not hard-coded]
4. Region + date inputs: preset Canada Boreal + lat/lon bbox inputs + year range. [filter re-aggregates client-side]
5. CSV download: hotspots aggregate for current selection. [download is valid CSV with header, matches filtered rows]
6. Analytics download: current chart as PNG via canvas / SVG export button. [file downloads]

## Data contract
Cleaned schema (pipeline/clean_firms.py, already tested):
lat, lon, acq_date, acq_time (HHMM string, zero-padded), acq_datetime UTC,
sensor ∈ {MODIS, VIIRS_SNPP, VIIRS_NOAA20, VIIRS_NOAA21}, satellite, frp,
confidence ∈ {nominal, high} (kept), brightness_k
Filters: bbox FIRST; type==0 when present; dedupe (lat,lon,acq_date,acq_time,satellite);
drop missing lat/lon/date/FRP-null kept for counts.
Monthly aggregate: cell_lat, cell_lon (0.25° grid), year, month,
modis_count, viirs_count, total_count, mean_frp, harmonized_count (calibration fills).

## Calibration (measurement, not ML)
- Overlap: 2012–2023. Train/calibration split: 2012–2021. Holdout: 2022–2023 + spot 2024–25 if data allows (brief said 2024–25 holdout; we implement configurable split, default calib 2012–2020, holdout 2021–2023 so holdout is fully inside overlap — LOGGED DECISION D3).
- Stratify by FRP bin (0–10, 10–30, 30–100, 100+ MW) as fire-size proxy, and by season (May–Sep boreal fire season vs off-season). Land-cover stratification is stretch (needs a land-cover raster we do not yet have) — LOGGED D4: FRP×season is V1; land-cover added only if a raster lands by Sun noon.
- Per stratum: ratio r = VIIRS_count / MODIS_count in overlap (aggregated per cell-month, then median ratio, robust to zero cells: use sum ratio with +1 smoothing, report both).
- Harmonized count for a MODIS-era month = modis_count × r(stratum of that cell-month, using its mean_frp bin). For VIIRS era, harmonized = viirs_count (VIIRS is reference sensor).
- Pre-2012 harmonized is therefore an ESTIMATE of what VIIRS would have seen, including small fires MODIS missed. State this wording exactly in the app + submission.
- Output: pipeline/calibration.json with per-stratum ratios + counts.

## Validation
1. Holdout: apply ratios learned on calibration years to holdout years' MODIS counts; compare predicted VIIRS vs actual VIIRS per stratum. Report MAPE + bias per stratum in docs/VALIDATION.md. [script prints table; numbers come from run, never hand-written]
2. NBAC: for 2023, correlate region-month harmonized counts vs NBAC burned area if NBAC file is present in data/external/. [optional at runtime; absence does not block app] Script: pipeline/validate_nbac.py, skips gracefully.
3. Sanity: harmonized 2011→2012 year-over-year jump must be smaller in absolute % than raw jump, on real data. Report both.

## NRT vs SP — DECISION D1 (blocker flagged)
Ishan's download is NRT product files. Prep specified SP for the long record.
Risk: NRT archive files downloaded via FIRMS archive download ARE the full
historical record for those products in many distributions (archive download
serves standard-quality for old dates), but file naming alone does not prove it.
Acceptance check BEFORE trusting: after HF link lands, inspect per-sensor
year coverage in the Canada slice: MODIS must span ~2001–2025, VIIRS_SNPP
2012–2025. If any sensor-year is missing/thin (<50% of neighbouring years
outside known low-fire years), THEN re-pull that sensor's Canada slice from SP
via FIRMS API (5-day chunks, key verified Oct 9). Do NOT re-download global.

## Stack
Python (pandas, pyarrow) pipeline → Parquet + JSON. App: zero-build static
HTML/CSS/JS (no framework, no build step, runs from file:// or any static host,
GitHub Pages ready). DuckDB optional for ad-hoc queries over Parquet; app
itself reads monthly.json (< a few MB) so judges need nothing installed.

## Decisions log
- D1 NRT vs SP: verify-by-coverage first (above), re-pull SP Canada slice only if check fails.
- D2 Storage: Parquet + JSON export; DuckDB optional, not a server. (team agreed DB-after-cleaning)
- D3 Holdout split: calib 2012–2020, holdout 2021–2023 (fully verifiable inside overlap). Brief's 2024–25 test is run as secondary if VIIRS+MODIS both present then.
- D4 Stratification V1: FRP bin × season. Land-cover = stretch.
- D5 App: static, no build. Copilot: OUT for V1 unless all above done by Sun 12:00 ET.
