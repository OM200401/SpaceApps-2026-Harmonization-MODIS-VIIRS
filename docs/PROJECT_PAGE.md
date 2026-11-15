# Project page draft: all 8 fields

Every number below comes from `docs/VALIDATION.md` or from `app/data/monthly.json`.
Items in [BRACKETS] still need a team member to fill in or confirm before submitting.

Images for the page: `docs/img/` has three screenshots of the app (map, the raw 2012 jump, the 2023
report). They are PNG and well under the page's 10 MB limit. They are real captures, not AI-generated,
so they need no watermark.

## 1. Project name

One Burning Calendar: Harmonized MODIS + VIIRS Fire Record (Team Murphy)

## 2. High-level project summary

Two NASA satellite sensors have watched Earth's fires for 25 years, but they don't count the same way. VIIRS (375 m pixels, from 2012) detects far more small fires than MODIS (1 km pixels, from 2000). Add the two raw records together and fire in Canada seems to jump +785% between 2011 and 2012. That jump is the satellite changing, not the fires.

One Burning Calendar converts MODIS counts into VIIRS units, using the years when both sensors were flying, and joins them into one monthly record from 2001 to today. In the harmonized record the 2011 to 2012 change is +60.8%, which matches the +60.5% that MODIS alone measured. Tested on three years it never saw (2021–2023), the conversion is off by 13.6% in a typical month and finds all five of the busiest months.

With the sensor change removed, real extremes stand out. May 2023, the start of Canada's record fire season, had 17.9 times the usual May activity. Fire managers, land managers and scientists get one baseline they can trust for the question "is this month unusual for my area?"

## 3. Link to project demo

[VIDEO of 30 seconds or less, or a deck of at most 7 slides. Public link. Om owns this.]

## 4. Link to final project

- Live app (no login): https://om200401.github.io/SpaceApps-2026-Harmonization-MODIS-VIIRS/app/
- Code and method: https://github.com/OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS

## 5. Detailed project description

**What it does.** The app has three pages.

- **Map.** Pick a preset area, draw a box, or type coordinates. Scrub or play through every month since 2001. A panel shows how the selected month compares with a typical one, for example "Far above normal, 17.9×".
- **Area report.** A one-sentence verdict for the chosen year, the season plotted against the normal range, a year × month calendar of every month since 2001 (harmonized, raw, or as a multiple of the median), the busiest months and years, a CSV download, a PNG of the chart, and a printable one-page brief.
- **Method.** A raw versus harmonized toggle that shows the 2012 jump appear and disappear, the conversion in three steps, the accuracy table, and the caveats.

**How the harmonization works.**

1. We count NASA FIRMS detections per 0.25° grid cell and month, by satellite and by day or night. We keep vegetation fires with nominal or high confidence.
2. S-NPP VIIRS is the reference sensor. From February 2012 the harmonized count is what S-NPP observed.
3. Before February 2012 we convert MODIS (Terra + Aqua) into S-NPP units. For each 1° block we learn the S-NPP to MODIS ratio by season and day or night over the overlap (February 2012 to December 2025). Blocks with few fires lean on the regional ratio. A second estimate rescales each month with a power law fitted per calendar month. The final value is the average of the two.
4. Before July 2002 only Terra was flying, so those months use Terra-only ratios.

**How we checked it.**

- **Holdout.** We fitted on 2012–2020 and predicted S-NPP for 2021–2023 from MODIS alone. Canada: monthly error (MAPE) 13.6%, bias −6.5%, 5 of the 5 busiest months found. The simpler single-ratio rule we started with scored 16.9%.
- **The 2012 seam.** Raw +785.4%, harmonized +60.8%, MODIS alone +60.5%.
- **Choosing the rule.** We compared about 90 conversion rules by hiding one year at a time across 8 world regions. A stricter check chose the settings without seeing 2021–2023 and gave results within 0.3 points.

**What to keep in mind.** Counts before 2012 are estimates and are marked ≈ in the app. 2000–2002 are the least certain, because no period exists where Terra alone overlaps with VIIRS. Months from August 2026 use near-real-time data and are marked provisional. A detection is not a fire: one large fire produces many detections. The app data covers Canada; the pipeline also harmonizes and validates the Amazon and the Mediterranean (holdout MAPE 8.3% and 15.6%).

**Accessibility.** Colour-blind-safe colour ramps (cividis and inferno), a calendar that works from the keyboard and reads each cell out to screen readers, light and dark themes, and a phone layout.

**Tools.** Python (pandas, NumPy, pyarrow, DuckDB) for the pipeline. Plain HTML, CSS and JavaScript with Leaflet and Chart.js for the app, hosted on GitHub Pages with no build step and no server.

## 6. Use of Super Intelligence (SI)

We used AI assistants to speed up building this project. The team directed and reviewed all of it. Claude (Anthropic) helped write code (the summary-table build script, and parts of the pipeline and app), check the FIRMS data tables, and write documentation. Codex (OpenAI) helped write pipeline code. Muse Code helped write documentation. GitHub Copilot Autofix made one fix in the app (median calculation). [Confirm this tool list matches the README table.]

Choosing the challenge, the product idea, and the harmonization method choices are the team's own. They include S-NPP as the reference sensor, season × day/night ratios, and the 2012–2020 calibration with 2021–2023 holdout. The project idea, challenge selection and harmonization method were documented by the team on Oct 6, 2026, before the build.

Every result comes from NASA FIRMS data run through our scripts. AI-assisted synthetic test data was used only to check the pipeline; it is labelled as synthetic and never shown as a result. No images or video in the app or demo are AI-generated. [Update if that changes: AI-made images and video need a visible watermark.]

## 7. NASA data

NASA FIRMS (Fire Information for Resource Management System, LANCE / EOSDIS) active fire detections, https://firms.modaps.eosdis.nasa.gov/:

- MODIS Collection 6.1 (Terra and Aqua), November 2000 to October 2026
- VIIRS 375 m Collection 2, S-NPP, 2012 to October 2026

Standard-processing (archive) data is used up to 31 August 2026 for MODIS and 31 July 2026 for S-NPP, and near-real-time data after that. VIIRS NOAA-20 and NOAA-21 detections are in our raw data mirror but are not used in any result.

## 8. Space Agency Partner Data and other references

No Space Agency Partner data is used. [The optional NBAC burned-area check (`pipeline/validate_nbac.py`) was never run, so NBAC is not listed. Add it here only if a result is reported.]

- Giglio, L., Schroeder, W., & Justice, C. O. (2016). The collection 6 MODIS active fire detection algorithm and fire products. Remote Sensing of Environment, 178, 31–41. https://doi.org/10.1016/j.rse.2016.02.054
- Schroeder, W., Oliva, P., Giglio, L., & Csiszar, I. A. (2014). The New VIIRS 375 m active fire detection data product: Algorithm description and initial assessment. Remote Sensing of Environment, 143, 85–96. https://doi.org/10.1016/j.rse.2013.12.008
- Canadian Fire Spread Dataset methodology (Nature Scientific Data, 2024), as a design precedent. [Confirm this was used, and add the full citation.]
- Open-source software: Leaflet 1.9.4 (BSD 2-Clause), Chart.js 4.4.1 (MIT), DuckDB (MIT), pandas and NumPy (BSD 3-Clause), Apache Arrow / pyarrow (Apache 2.0), huggingface_hub (Apache 2.0), scikit-learn and SciPy (BSD 3-Clause, experiments only).
- Basemap tiles: Esri World Light/Dark Gray Base and Reference (Esri, HERE, Garmin, OpenStreetMap contributors).
- Colour maps: cividis (Nuñez, Anderton & Renslow, 2018, https://doi.org/10.1371/journal.pone.0199239) and inferno (matplotlib, CC0).
- Hosting: GitHub Pages (app), GitHub Releases (monthly grid), Hugging Face (raw FIRMS mirror).
- Our own code is under the MIT License.
