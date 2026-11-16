# Project page draft: all 8 fields

Every number below comes from `experiments/v2/README.md` (accuracy) or from the app's own data (the 2012 jump, May 2023).

Images for the page: `docs/img/` has three screenshots of the app (map, the raw 2012 jump, the 2023
calendar). They are PNG and well under the page's 10 MB limit. They are real captures, not AI-generated,
so they need no watermark.

## 1. Project name

One Burning Calendar: Harmonized MODIS + VIIRS Fire Record (Team Murphy)

## 2. High-level project summary

Two NASA satellite sensors have watched Earth's fires for 25 years, but they don't count the same way. VIIRS (375 m pixels, from 2012) detects far more small fires than MODIS (1 km pixels, from 2000). Add the two raw records together and fire worldwide seems to jump +407% between 2011 and 2012, and +785% in Canada. That jump is the satellite changing, not the fires.

One Burning Calendar converts MODIS counts into VIIRS units with one model for the whole world, learned from the years when both sensors were flying, and joins them into one monthly record from 2001 to today. In the harmonized record the worldwide 2011 to 2012 change is +5.6%, close to the +5.2% that MODIS alone measured. Tested by hiding one year at a time, the converted monthly totals are off by 1.5% worldwide and 6.5% in Canada.

With the sensor change removed, real extremes stand out. May 2023, the start of Canada's record fire season, had 19.1 times the usual May activity. Fire managers, land managers and scientists get one baseline they can trust, for any area on Earth, for the question "is this month unusual here?"

## 3. Link to project demo

[VIDEO of 30 seconds or less, or a deck of at most 7 slides. Public link. Om owns this.]

## 4. Link to final project

- Live app (no login): https://om200401.github.io/SpaceApps-2026-Harmonization-MODIS-VIIRS/app/
- Code and method: https://github.com/OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS

## 5. Detailed project description

**What it does.** The app covers the whole world and has three pages.

- **Map.** Pick one of ten preset areas (among them Canada, the Amazon, the Mediterranean, US West, Siberia, southern Africa, SE Asia, northern Australia and the whole world), draw a box, or type coordinates. Scrub or play through every month since 2001. A panel shows how the selected month compares with a typical one, for example "Far above normal, 19.1×".
- **Calendar.** A year × month calendar of every month since 2001 (harmonized, raw, or as a multiple of the median), a date range to narrow it, a one-sentence verdict for the chosen year, the season plotted against the normal range, the busiest months and years, a CSV download, a PNG of the chart, and a printable one-page brief.
- **Method.** A raw versus harmonized toggle that shows the 2012 jump appear and disappear, the conversion in three steps, the accuracy table, and the caveats.

**How the harmonization works.**

1. We count NASA FIRMS detections per 0.25° grid cell and month, by satellite and by day or night. We keep vegetation fires with nominal or high confidence.
2. We learn only from clean overlap years, June 2012 to 2021. The MODIS satellites' orbits drift after 2021, so later years don't represent 2000–2011. We drop days when any satellite was down, and we mask gas flares, which the fire data counts as vegetation fires.
3. S-NPP VIIRS is the reference sensor. From February 2012 the harmonized count is what S-NPP observed, minus gas flares.
4. Before February 2012 we convert MODIS (Terra + Aqua) into S-NPP units with one worldwide model. For each 1° block, month and day or night, it starts from a local S-NPP to MODIS ratio and applies a correction learned by gradient boosting (LightGBM) from MODIS-only inputs: how intense and how spread out the fires were, the other half of the day, the months around it and the neighbouring blocks. Where MODIS saw nothing, it adds the small fires VIIRS usually finds there.
5. Before July 2002 only Terra was flying, so those months use a Terra-only version of the model.

**How we checked it.**

- **Hidden years.** We hid one year of 2012–2021 at a time, predicted it from MODIS alone, and compared with what S-NPP really saw. Monthly error (total absolute error over all months ÷ total fire): world 1.5%, Canada 6.5%, Amazon 2.6%, Mediterranean 7.3%, US West 4.4%, Siberia 4.5%, southern Africa 2.0%, SE Asia 3.9%, northern Australia 3.3%. Yearly totals: world 0.7%, Canada 4.3%.
- **Against our previous method** (per-area ratios plus a monthly power law), on the same data: world 2.1% → 1.5%, Canada 11.3% → 6.5%.
- **Forward test.** Fitting on 2012–2018 and predicting 2019–2021 gives similar numbers: Canada 6.7%, world 1.7%.
- **Terra-only years.** Hiding Aqua in 2012–2021 to imitate 2000–2002: world 2.7%, against 6.4% for the previous Terra ratio.
- **The best any conversion could do.** Predicting S-NPP from NOAA-20, an identical VIIRS instrument, gives 0.7% for the world and 2.5% for Canada.
- **The 2012 seam.** World: raw +407.2%, harmonized +5.6%, MODIS alone +5.2%. Canada: raw +785.4%, harmonized +59.8%, MODIS alone +60.5%.
- **Independent audit.** A separate audit engine, sharing no code with the pipeline, recomputes the Canada record built with our previous method from the raw grid and checks every published number against it (`docs/AUDIT_REPORT.md`).

**What to keep in mind.** Counts before 2012 are estimates and are marked ≈ in the app. Megafire months are the hardest: smoke hides fire from MODIS, so those months can come out 10–25% low. Canada and the Mediterranean stay above 5% monthly error. Outside the tested regions accuracy varies, and sparse places (the Arctic, deserts, small islands) are much less certain. 2000–2002 are less certain, because only Terra was flying. Months from August 2026 use near-real-time data and are marked provisional. A detection is not a fire: one large fire produces many detections.

**Accessibility.** Colour-blind-safe colour ramps (cividis and inferno), a calendar that works from the keyboard and reads each cell out to screen readers, light and dark themes, and a phone layout.

**Tools.** Python (pandas, NumPy, pyarrow, DuckDB, LightGBM) for the pipeline. Plain HTML, CSS and JavaScript with Leaflet and Chart.js for the app, hosted on GitHub Pages with no build step and no server.

## 6. Use of Super Intelligence (SI)

We used AI assistants to speed up building this project. The team directed and reviewed all of it. Claude (Anthropic) helped write code (the summary-table build script, and parts of the pipeline and app), check the FIRMS data tables, and write documentation. Codex (OpenAI) helped write pipeline code. Muse Code helped write documentation. GitHub Copilot Autofix made one fix in the app (median calculation).

Machine learning is part of the method itself: the estimates before February 2012 come from a gradient-boosted model (LightGBM) that we trained only on NASA FIRMS data. The app marks every one of those values with ≈.

Choosing the challenge, the product idea, and the harmonization method choices are the team's own. They include S-NPP as the reference sensor, learning the conversion only from June 2012 to 2021 (before the MODIS orbits drift), and testing it by hiding one year at a time.

Every result comes from NASA FIRMS data run through our scripts. AI-assisted synthetic test data was used only to check the pipeline; it is labelled as synthetic and never shown as a result. No images or video in the app or demo are AI-generated.

## 7. NASA data

NASA FIRMS (Fire Information for Resource Management System, LANCE / EOSDIS) active fire detections, https://firms.modaps.eosdis.nasa.gov/:

- MODIS Collection 6.1 (Terra and Aqua), November 2000 to October 2026, worldwide
- VIIRS 375 m Collection 2, S-NPP, 2012 to October 2026, worldwide
- VIIRS 375 m Collection 2, NOAA-20, 2019 to 2025, used only for the "best any conversion could do" benchmark

Standard-processing (archive) data is used up to 31 August 2026 for MODIS and 31 July 2026 for S-NPP, and near-real-time data after that. VIIRS NOAA-21 detections are in our raw data mirror but are not used in any result.

## 8. Space Agency Partner Data and other references

No Space Agency Partner data is used.

- Giglio, L., Schroeder, W., & Justice, C. O. (2016). The collection 6 MODIS active fire detection algorithm and fire products. Remote Sensing of Environment, 178, 31–41. https://doi.org/10.1016/j.rse.2016.02.054
- Schroeder, W., Oliva, P., Giglio, L., & Csiszar, I. A. (2014). The New VIIRS 375 m active fire detection data product: Algorithm description and initial assessment. Remote Sensing of Environment, 143, 85–96. https://doi.org/10.1016/j.rse.2013.12.008
- Barber, Q. E., Jain, P., Whitman, E., Thompson, D. K., Guindon, L., Parks, S. A., Wang, X., Hethcoat, M. G., & Parisien, M.-A. (2024). The Canadian Fire Spread Dataset. Scientific Data, 11, 764. https://doi.org/10.1038/s41597-024-03436-4 (methodology used as a design precedent).
- Open-source software: Leaflet 1.9.4 (BSD 2-Clause), Chart.js 4.4.1 (MIT), DuckDB (MIT), LightGBM (MIT), pandas and NumPy (BSD 3-Clause), Apache Arrow / pyarrow (Apache 2.0), huggingface_hub (Apache 2.0), scikit-learn and SciPy (BSD 3-Clause, experiments only).
- Basemap tiles: Esri World Light/Dark Gray Base and Reference (Esri, HERE, Garmin, OpenStreetMap contributors).
- Colour maps: cividis (Nuñez, Anderton & Renslow, 2018, https://doi.org/10.1371/journal.pone.0199239) and inferno (matplotlib, CC0).
- Hosting: GitHub Pages (app), GitHub Releases (monthly grid and map tiles), Hugging Face (raw FIRMS mirror).
- Our own code is under the MIT License.
