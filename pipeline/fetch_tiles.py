#!/usr/bin/env python3
"""Download the web app's map tiles from a GitHub release into app/data/.

The tiles (app/data/index.json, app/data/d/*.json, app/data/c/*.json) are too big to keep in git, so they
live as a zip on a release. The Pages workflow runs this before deploying; run it locally before serving
the app. After regenerating tiles (export_tiles.py), zip index.json, c/ and d/ from app/data/, upload
the zip to a new release, and set TILES_TAG below to that release's tag.

Usage: python pipeline/fetch_tiles.py [--tag tiles-v2] [--out app/data]
"""
import argparse, io, json, shutil, urllib.request, zipfile
from pathlib import Path

REPO = "OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS"
TILES_TAG = "tiles-v2"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=TILES_TAG)
    ap.add_argument("--out", default="app/data")
    a = ap.parse_args()
    url = f"https://github.com/{REPO}/releases/download/{a.tag}/{a.tag}.zip"
    print(f"downloading {url}", flush=True)
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
    out = Path(a.out)
    for lvl in ("c", "d"):
        shutil.rmtree(out / lvl, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(out)
    index = json.loads((out / "index.json").read_text())
    n = sum(len(v) for v in index["tiles"].values())
    print(f"unpacked {n} tiles into {out} ({len(data) / 1e6:.1f} MB zip); data through {index['end']}")


if __name__ == "__main__":
    main()
