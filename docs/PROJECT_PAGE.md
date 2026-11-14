# Project page draft — all 8 fields (fill [BRACKETS] after real-data run)

1. Project name: One Burning Calendar — Harmonized MODIS + VIIRS Fire Record (Team Murphy)

2. High-level summary: Two NASA satellites have watched Earth's fires for 25 years, but they don't count the same way — VIIRS (375 m, 2012+) sees far more small fires than MODIS (1 km, 2000+), so the raw record shows a fake jump in 2012. We calibrated the two sensors against each other over their 2012–2023 overlap, stratified by fire intensity and season, and fused them into one harmonized burning-activity calendar for Canada's boreal forests. In the harmonized record the sensor change disappears and real extremes stand out: May 2023, Canada's record fire season, burns at [X]× the 20-year May median.

3. Link to project demo: [VIDEO ≤30s URL or ≤7-slide deck URL — Om owns]

4. Link to final project: [PUBLIC GITHUB REPO URL] — run instructions in README (pipeline: 4 Python commands; app: open app/index.html via any static host).

5. Detailed description: [after real run: methods = shared-schema cleaning (bbox-first slice, nominal/high confidence only, type 0, dedupe on lat/lon/date/time/satellite, HHMM timestamp parsing); 0.25° cell × month aggregation; stratified calibration FRP-bin × season, VIIRS as reference; MODIS-era harmonized counts are estimates of VIIRS-equivalent counts including small fires MODIS missed; holdout validation calib 2012–2020 / test 2021–2023 with per-stratum MAPE/bias: [TABLE]; raw vs harmonized 2011→2012 jump: [A]% → [B]%; NBAC independent check: [RESULT]. Tools: Python, pandas, pyarrow, Parquet, vanilla HTML/CSS/JS, DuckDB for ad-hoc queries. No ML training in the core — harmonization is measurement.]

6. Use of Super Intelligence (AI) disclosure: AI assistants (Claude/Quill) were used to accelerate coding, documentation, and test-data generation under human direction. The project idea, challenge selection, and harmonization method were developed by the team and documented on Oct 6, 2026, before the build. Synthetic test data used only for pipeline verification is AI-generated and clearly labeled; all science data is NASA FIRMS. No AI-generated images or video are used in the demo [update if that changes — watermark rule].

7. NASA Data used: NASA FIRMS active fire detections via NASA Earthdata — MODIS (M-C61) and VIIRS S-NPP / NOAA-20 / NOAA-21 (V-C2 / J1V-C2 / J2V-C2) products, 2001–2025, Canada extent. [Confirm NRT vs SP per coverage check and name the exact product used in the final run.]

8. Space Agency Partner Data and Other References: Canadian National Fire Database / National Burned Area Composite (NBAC) via Canadian Wildland Fire Information System (validation); pandas, pyarrow (open source); FIRMS data documentation (NASA Earthdata); Canadian Fire Spread Dataset methodology (Nature Scientific Data, 2024) as design precedent.
