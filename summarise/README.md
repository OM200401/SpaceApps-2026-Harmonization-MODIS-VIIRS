# Monthly grid summary

`build_monthly_grid.py` turns the raw FIRMS hotspots (660M rows, ~10 GB, on
Hugging Face at `undeadphoenix/firms-fire-data`) into one small table: hotspot
counts per **0.25° grid cell per month**. The calendar, the API, the
harmonization work and the charts all read this table instead of the raw data.

Current build (`monthly_grid_025.parquet`): about 55M rows, 203k grid cells, 208 MB.
It covers Nov 2000 to Nov 2026 and accounts for all 660,744,059 raw detections.
The build takes about 3 minutes on a laptop.

## Columns

| column | type | meaning |
|---|---|---|
| `cell_lat`, `cell_lon` | double | south-west corner of the 0.25° cell |
| `year`, `month` | int | month of detection (UTC date) |
| `sensor` | text | `M-C61` (MODIS), `SV-C2` (VIIRS S-NPP), `J1V-C2` (VIIRS NOAA-20), `J2V-C2` (VIIRS NOAA-21) |
| `satellite` | text | `Terra`, `Aqua`, `SNPP`, `N20`, `N21` |
| `daynight` | text | `D` or `N` |
| `confidence` | text | `l` / `n` / `h`. MODIS 0 to 100 mapped as <30 → `l`, 30 to 79 → `n`, ≥80 → `h` |
| `is_vegetation` | bool | archive rows: FIRMS `type = 0`. Near-real-time rows have no `type`, so they count as vegetation unless they fall on a ~1 km cell the archive ever flagged as volcano, static or offshore source |
| `hotspots` | int | number of detections |
| `frp_sum` | float | summed fire radiative power (MW) |

## What the build already does

- Drops near-real-time rows dated on or before the last archive date for that satellite, so nothing is counted twice.
- Keeps every row otherwise. Cleaning choices (confidence threshold, vegetation only, which satellites) are filters you apply when you query, so nobody has to rebuild the table to try a different rule.

## Typical filter

```sql
SELECT year, month, sum(hotspots) AS hotspots
FROM 'monthly_grid_025.parquet'
WHERE is_vegetation
  AND confidence IN ('n', 'h')
  AND satellite = 'SNPP'                        -- one consistent VIIRS reference
  AND cell_lat BETWEEN 15.0 AND 22.0            -- area of interest
  AND cell_lon BETWEEN 72.0 AND 81.0
GROUP BY ALL ORDER BY ALL;
```

## Things to keep in mind

- **MODIS before 2003 is Terra only.** Aqua joined in mid-2002, so 2000 to 2002 counts are lower for that reason alone.
- **VIIRS gained satellites:** NOAA-20 from 2018, NOAA-21 from 2023. Summing all VIIRS satellites creates a fake upward trend; filter on one satellite.
- **The latest month is partial.** Compare it against the same number of days in past years, not against full months.

## Rebuilding

```bash
pip install -r requirements.txt
python -c "from huggingface_hub import snapshot_download; snapshot_download('undeadphoenix/firms-fire-data', repo_type='dataset', local_dir='data/firms', allow_patterns=['*.parquet'])"
python summarise/build_monthly_grid.py --cell 0.25
```
