# Om monthly-grid table verdict

> Early decision note. The last bullet is superseded: mean FRP per cell differs too much between the
> sensors, so those strata were dropped. See `docs/VALIDATION.md` and `experiments/v2/README.md`.

## Decision

Use Om's GitHub Release `data-v2` asset, `monthly_grid_025.parquet`, as the
pipeline source. Download it to `data/derived/`. This workflow does not begin
from the raw Hugging Face FIRMS dataset.

## Required interpretation

- MODIS is Terra plus Aqua.
- VIIRS reference is SNPP only; do not add NOAA-20 or NOAA-21.
- Keep vegetation rows with confidence `n` or `h`, summing day and night.
- Slice Canada to cell longitude -140 through -52 and cell latitude 42 through
  72.
- Use 2003 to 2020 as the anomaly baseline because 2000 to 2002 are Terra-only.
- Exclude partial November 2026 from headline statistics.
- Form calibration strata from cell-month mean FRP (`frp_sum / hotspots`) bins
  crossed with season; sum each sensor's hotspots region-wide inside a stratum
  before dividing to calculate its ratio.
