#!/usr/bin/env python3
"""
clean_firms.py -- NASA Space Apps 2026, team Murphy
Clean FIRMS MODIS + VIIRS hotspot files into ONE shared schema, sliced to
Canada first so a 49 GB global download collapses before any heavy work.

What it does, in order (slice-first, per the Nov 14 team discussion):
  1. Read CSV and/or Parquet inputs in chunks (never loads the whole file).
  2. Slice to the Canada bbox FIRST: lon -140..-52, lat 42..72
     (the Canada-wide box verified Oct 9; narrow it once the team locks an AOI).
  3. Normalise columns to one schema (FIRMS archive CSVs use different
     brightness column names per sensor; see NOTES below).
  4. Unify confidence: MODIS 0-100 -> low <30, nominal 30-80, high >80;
     VIIRS low/nominal/high (or l/n/h) -> same three levels.
     Keep nominal + high only.
  5. Keep type == 0 (presumed vegetation fire) when a `type` column exists;
     if it is absent (some NRT files), keep everything and say so in the report.
  6. Dedupe on (lat, lon, acq_date, acq_time, satellite) -- same fire seen on
     overlapping passes.
  7. Write cleaned Parquet + a monthly grid-cell aggregate Parquet that the
     web app reads directly (no database server needed; DuckDB reads Parquet).

Outputs
  cleaned parquet columns:
    lat, lon, acq_date, acq_time, acq_datetime (UTC), sensor,
    satellite, frp, confidence (low/nominal/high), brightness_k
    sensor in {MODIS, VIIRS_SNPP, VIIRS_NOAA20, VIIRS_NOAA21}
  monthly aggregate columns:
    cell_id, cell_lat, cell_lon, year, month,
    modis_count, viirs_count, total_count, mean_frp, harmonized_count
    harmonized_count is left EMPTY until the calibration step (2012-2023
    overlap) fills it in -- it is NOT set equal to total_count here.

Usage
  # From Ishan's Hugging Face Parquet files (whole-global conversion):
  python3 clean_firms.py --input "hf_parquet/*.parquet" \
      --clean data/cleaned_canada.parquet --monthly data/monthly.parquet

  # From raw FIRMS archive CSVs (one per sensor per year):
  python3 clean_firms.py --input "raw/*.csv" \
      --clean data/cleaned_canada.parquet --monthly data/monthly.parquet

  # A tighter boreal box, or a different grid size:
  python3 clean_firms.py --input "raw/*.csv" --bbox -140,49,-52,70 --grid 0.25 \
      --clean data/cleaned_canada.parquet --monthly data/monthly.parquet

Requirements: pandas, pyarrow.  (pip install pandas pyarrow)
Tested 2026-11-14 on synthetic FIRMS-shaped MODIS + VIIRS CSVs (see the
validation report printed at the end of a run; real-data row counts will
differ, the schema and filters are what was tested).
"""

import argparse
import glob
import sys
from pathlib import Path

import pandas as pd

# Canada-wide box verified 2026-10-09 (west, south, east, north).
DEFAULT_BBOX = (-140.0, 42.0, -52.0, 72.0)
DEFAULT_GRID = 0.25

# FIRMS archive column names (lowercased on read). MODIS uses `brightness`
# / `bright_t31`; VIIRS uses `bright_ti4` / `bright_ti5`. Sources:
# https://www.earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs
RENAME = {
    "latitude": "lat",
    "longitude": "lon",
    "bright_ti4": "brightness_k",
    "brightness": "brightness_k",
    "bright_ti5": "brightness_t5_k",
    "bright_t31": "brightness_t5_k",
}

CLEAN_COLS = ["lat", "lon", "acq_date", "acq_time", "acq_datetime",
              "sensor", "satellite", "daynight", "frp", "confidence", "brightness_k"]

# Harmonization uses ONE VIIRS satellite (S-NPP, 2012-01-20 to 2026-11-02).
# Adding NOAA-20 (2018+) and NOAA-21 (2023+) on top would fake an upward trend.
REFERENCE_VIIRS = "VIIRS_SNPP"


def parse_bbox(text):
    w, s, e, n = (float(x) for x in text.split(","))
    return (w, s, e, n)


def sensor_from_row(instrument, satellite):
    """Map FIRMS instrument/satellite values to the team's sensor labels."""
    inst = str(instrument).strip().upper() if pd.notna(instrument) else ""
    sat = str(satellite).strip() if pd.notna(satellite) else ""
    if "MODIS" in inst:
        return "MODIS"
    # Real FIRMS archive values: S-NPP rows have instrument "SNPP" (not "VIIRS"),
    # NOAA-20/21 rows have satellite "N20"/"N21".
    if "VIIRS" in inst or inst == "SNPP":
        s = sat.upper()
        if s in ("N", "SNPP", "S-NPP") or "SUOMI" in s:
            return "VIIRS_SNPP"
        if s in ("1", "N20") or "NOAA-20" in s or "NOAA 20" in s or "JPSS-1" in s:
            return "VIIRS_NOAA20"
        if s in ("2", "N21") or "NOAA-21" in s or "NOAA 21" in s or "JPSS-2" in s:
            return "VIIRS_NOAA21"
        return "VIIRS_UNKNOWN"
    return "UNKNOWN"


def sensor_from_filename(path):
    # HF layout is Hive-partitioned: sensor=M-C61/year=2012/data_0.parquet, so
    # check the full path, not just the file name (all files are data_0.parquet).
    full = str(path).upper()
    if "M-C61" in full or "MC61" in full:
        return "MODIS"
    if "SV-C2" in full or "SVC2" in full:
        return "VIIRS_SNPP"
    if "J1V-C2" in full or "J1VC2" in full:
        return "VIIRS_NOAA20"
    if "J2V-C2" in full or "J2VC2" in full:
        return "VIIRS_NOAA21"
    name = Path(path).name.upper()
    if "MODIS" in name:
        return "MODIS"
    if "SNPP" in name or "SUOMI" in name or "VNP14" in name:
        return "VIIRS_SNPP"
    if "NOAA20" in name or "NOAA-20" in name or "VJ114" in name:
        return "VIIRS_NOAA20"
    if "NOAA21" in name or "NOAA-21" in name or "VJ214" in name:
        return "VIIRS_NOAA21"
    return None


def unify_confidence(conf, sensor):
    """Return low/nominal/high, or None if unparseable."""
    if pd.isna(conf):
        return None
    # Word form first (VIIRS, or an already-cleaned file re-run through here).
    c = str(conf).strip().lower()
    if c in ("low", "l"):
        return "low"
    if c in ("nominal", "n"):
        return "nominal"
    if c in ("high", "h"):
        return "high"
    if sensor == "MODIS":
        try:
            v = float(conf)
        except (TypeError, ValueError):
            return None
        if v < 30:
            return "low"
        if v <= 80:
            return "nominal"
        return "high"
    return None


def clean_chunk(df, bbox, counts):
    """Clean one chunk; returns the cleaned frame (may be empty)."""
    counts["in"] += len(df)
    if df.empty:
        return df.iloc[0:0]
    df = df.rename(columns={c: RENAME.get(c, c) for c in df.columns})
    df.columns = [c.lower() for c in df.columns]

    for col in ("lat", "lon"):
        if col not in df.columns:
            raise ValueError(f"missing required column: {col}")
    df = df.dropna(subset=["lat", "lon"])
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"])

    # 1. Slice to Canada FIRST, before any other work.
    w, s, e, n = bbox
    before = len(df)
    df = df[(df["lon"] >= w) & (df["lon"] <= e)
            & (df["lat"] >= s) & (df["lat"] <= n)]
    counts["after_bbox"] += len(df)
    counts["dropped_bbox"] += before - len(df)
    if df.empty:
        return df.iloc[0:0]

    # Sensor label: a cleaned `sensor` column already in the input (re-running on
    # cleaned Parquet) is preserved; then the file path (HF layout sensor=SV-C2/...,
    # most reliable); then per row from instrument/satellite.
    if "sensor" in df.columns and df["sensor"].astype(str).str.match(r"^(MODIS|VIIRS_)").all():
        df["sensor"] = df["sensor"].astype(str)
    elif counts.get("_file_sensor"):
        df["sensor"] = counts["_file_sensor"]
    elif "instrument" in df.columns or "satellite" in df.columns:
        inst = df.get("instrument", pd.Series([None] * len(df), index=df.index))
        sat = df.get("satellite", pd.Series([None] * len(df), index=df.index))
        df["sensor"] = [sensor_from_row(i, sa) for i, sa in zip(inst, sat)]
    else:
        df["sensor"] = counts.get("_file_sensor") or "UNKNOWN"
    df["satellite"] = df["satellite"].astype(str) if "satellite" in df.columns else ""

    # 2. Confidence -> one scale, keep nominal + high.
    if "confidence" not in df.columns:
        raise ValueError("missing required column: confidence")
    df["confidence"] = [unify_confidence(c, sn)
                        for c, sn in zip(df["confidence"], df["sensor"])]
    before = len(df)
    df = df[df["confidence"].isin(["nominal", "high"])]
    counts["dropped_confidence"] += before - len(df)
    counts["after_confidence"] += len(df)
    if df.empty:
        return df.iloc[0:0]

    # 3. Type 0 = vegetation fire, when the column exists.
    if "type" in df.columns:
        before = len(df)
        df = df[pd.to_numeric(df["type"], errors="coerce") == 0]
        counts["dropped_type"] += before - len(df)
    else:
        counts["no_type_column"] = True

    # 4. Timestamps: acq_time is HHMM as an int, so 130 means 01:30.
    df["acq_date"] = pd.to_datetime(df["acq_date"], errors="coerce").dt.date
    df = df.dropna(subset=["acq_date"])
    t = pd.to_numeric(df["acq_time"], errors="coerce").fillna(0).astype(int)
    df["acq_time"] = t.apply(lambda v: f"{v:04d}")
    df["acq_datetime"] = pd.to_datetime(
        df["acq_date"].astype(str) + " "
        + df["acq_time"].str.slice(0, 2) + ":"
        + df["acq_time"].str.slice(2, 4), utc=True, errors="coerce")
    df = df.dropna(subset=["acq_datetime"])

    # Day/night matters a lot: VIIRS/MODIS ratio is ~4x by day but ~17x at night.
    df["daynight"] = (df["daynight"].astype(str).str.strip().str.upper().str[:1]
                      if "daynight" in df.columns else "D")
    df["frp"] = pd.to_numeric(df["frp"], errors="coerce") if "frp" in df.columns else None
    df["brightness_k"] = (pd.to_numeric(df["brightness_k"], errors="coerce")
                          if "brightness_k" in df.columns else None)

    # 5. Dedupe overlapping passes.
    before = len(df)
    df = df.drop_duplicates(
        subset=["lat", "lon", "acq_date", "acq_time", "satellite"])
    counts["dropped_dupes"] += before - len(df)
    counts["out"] += len(df)
    return df[[c for c in CLEAN_COLS if c in df.columns]]


def read_chunks(path, chunksize=200_000):
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        yield from pd.read_csv(path, chunksize=chunksize, low_memory=False)
    elif suffix == ".parquet":
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=chunksize):
            yield batch.to_pandas()
    else:
        raise ValueError(f"unsupported input type: {path}")


def monthly_aggregate(cleaned, grid):
    """One row per grid cell x month, the table the web app reads."""
    if cleaned.empty:
        return pd.DataFrame(columns=["cell_id", "cell_lat", "cell_lon", "year",
                                     "month", "modis_count", "viirs_count",
                                     "total_count", "mean_frp",
                                     "harmonized_count"])
    d = cleaned.copy()
    d["cell_lat"] = (d["lat"] // grid * grid).round(4)
    d["cell_lon"] = (d["lon"] // grid * grid).round(4)
    d["year"] = pd.to_datetime(d["acq_date"]).dt.year
    d["month"] = pd.to_datetime(d["acq_date"]).dt.month
    d["is_modis"] = (d["sensor"] == "MODIS").astype(int)
    # viirs_count = S-NPP only (the reference satellite), never the sum of all VIIRS.
    d["is_viirs"] = (d["sensor"] == REFERENCE_VIIRS).astype(int)
    g = (d.groupby(["cell_lat", "cell_lon", "year", "month"], as_index=False)
           .agg(modis_count=("is_modis", "sum"),
                viirs_count=("is_viirs", "sum"),
                mean_frp=("frp", "mean")))
    g["total_count"] = g["modis_count"] + g["viirs_count"]
    g = g[g["total_count"] > 0]  # drop cell-months seen only by NOAA-20/21
    g["cell_id"] = (g["cell_lat"].astype(str) + "_" + g["cell_lon"].astype(str))
    g["harmonized_count"] = pd.NA  # filled by the calibration step, not here
    return g[["cell_id", "cell_lat", "cell_lon", "year", "month",
              "modis_count", "viirs_count", "total_count", "mean_frp",
              "harmonized_count"]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, nargs="+",
                    help="CSV and/or Parquet files, or globs, e.g. 'raw/*.csv'")
    ap.add_argument("--clean", required=True, help="cleaned Parquet output path")
    ap.add_argument("--monthly", required=True, help="monthly aggregate Parquet output path")
    ap.add_argument("--bbox", default=",".join(map(str, DEFAULT_BBOX)),
                    help="west,south,east,north (default Canada-wide)")
    ap.add_argument("--grid", type=float, default=DEFAULT_GRID,
                    help="grid cell size in degrees (default 0.25)")
    args = ap.parse_args(argv)
    bbox = parse_bbox(args.bbox)

    files = []
    for pat in args.input:
        files.extend(sorted(glob.glob(pat)))
    if not files:
        print(f"No input files matched: {args.input}", file=sys.stderr)
        return 2

    counts = {"in": 0, "after_bbox": 0, "dropped_bbox": 0, "after_confidence": 0,
              "dropped_confidence": 0, "dropped_type": 0, "dropped_dupes": 0,
              "out": 0, "no_type_column": False}
    frames = []
    for path in files:
        counts["_file_sensor"] = sensor_from_filename(path)
        print(f"Reading {path} ...")
        for chunk in read_chunks(path):
            frames.append(clean_chunk(chunk, bbox, counts))
    counts.pop("_file_sensor", None)

    cleaned = (pd.concat(frames, ignore_index=True) if frames
               else pd.DataFrame(columns=CLEAN_COLS))
    # Dedupe again across file boundaries (same fire in two yearly files).
    before = len(cleaned)
    cleaned = cleaned.drop_duplicates(
        subset=["lat", "lon", "acq_date", "acq_time", "satellite"])
    counts["dropped_dupes"] += before - len(cleaned)
    counts["out"] = len(cleaned)

    for out_path, frame in ((args.clean, cleaned),
                            (args.monthly, monthly_aggregate(cleaned, args.grid))):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(out_path, index=False)
        print(f"Wrote {out_path} ({len(frame):,} rows)")

    print("\n--- Validation report ---")
    print(f"rows read:            {counts['in']:,}")
    print(f"after Canada slice:   {counts['after_bbox']:,}"
          f"  (dropped {counts['dropped_bbox']:,})")
    print(f"after confidence:     {counts['after_confidence']:,}"
          f"  (dropped {counts['dropped_confidence']:,})")
    print(f"dropped type != 0:    {counts['dropped_type']:,}")
    if counts["no_type_column"]:
        print("NOTE: no `type` column found in at least one input -- "
              "nothing was filtered on fire type for those files.")
    print(f"dropped duplicates:   {counts['dropped_dupes']:,}")
    print(f"cleaned rows:         {counts['out']:,}")
    if not cleaned.empty:
        print("by sensor:")
        print(cleaned["sensor"].value_counts().to_string())
        print(f"date range: {cleaned['acq_date'].min()} to {cleaned['acq_date'].max()}")
        print(f"lat range: {cleaned['lat'].min():.2f} to {cleaned['lat'].max():.2f}, "
              f"lon range: {cleaned['lon'].min():.2f} to {cleaned['lon'].max():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
