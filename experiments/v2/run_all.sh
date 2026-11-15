#!/usr/bin/env bash
# Rebuild the v2 tables from the raw FIRMS Parquet and score the rules. Run from the repo root.
# Needs ../parquet (raw detections) and ../.venv; logs and data go to data/experiments_v2/ (git-ignored).
set -e
PY=${PY:-../.venv/Scripts/python.exe}
OUT=data/experiments_v2
export PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
mkdir -p $OUT
[ -f $OUT/static.parquet ] || $PY experiments/v2/build_static.py > $OUT/static_build.log 2>&1
$PY experiments/v2/build_daily.py --years 2012-2025 > $OUT/daily_build.log 2>&1
$PY experiments/v2/build_month.py > $OUT/month_build.log 2>&1
$PY experiments/v2/build_daily.py --years 2012-2021 --no-aqua --out $OUT/daily_terra > $OUT/terra_build.log 2>&1
$PY experiments/v2/build_month.py --daily $OUT/daily_terra --out month_terra.parquet --reuse-days > $OUT/terra_month.log 2>&1
cd experiments/v2
PY2=../../$PY
$PY2 -c "import h2; u = h2.load(1.0, src=h2.D + '/month_terra.parquet', cache=False); u.to_parquet(h2.D + '/units_terra.parquet', index=False)" > ../../$OUT/terra_units.log 2>&1
$PY2 run_gbm.py old shipped gbm_lin > ../../$OUT/batch_main.log 2>&1
$PY2 run_gbm.py old gbm_lin --units ../../$OUT/units_terra.parquet --tag _terra > ../../$OUT/batch_terra.log 2>&1
echo CHAIN_DONE
