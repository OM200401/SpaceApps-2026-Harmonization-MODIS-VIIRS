#!/usr/bin/env python3
"""Independent audit engine for the Murphy harmonization project.

Recomputes every published number from the rawest available artifacts and
compares it against a claims registry (pipeline/audit_claims.json) whose
values were fixed independently of the production pipeline.

Independence rules:
  * Never imports or copies pipeline/grid_calibrate.py, build_regions.py,
    export_json.py or calibrate.py. Aggregation over the raw grid is done in
    DuckDB SQL; the method refit is implemented here from the written spec
    in docs/VALIDATION.md.
  * Read-only against the repo: writes only docs/AUDIT_REPORT.md and
    pipeline/audit_results.json. Fault injection runs on in-memory copies.
  * Verdicts: PASS / FAIL / UNVERIFIABLE / BLOCKED. Nothing is rounded up.

Usage: python pipeline/audit_engine.py [--root .] [--grid PATH] [--selftest]
Exit: 0 = no science FAIL, 1 = science FAIL, 2 = layers BLOCKED (no FAIL).
"""
import argparse, copy, json, math, re, sys
from pathlib import Path
import numpy as np

PASS, FAIL, UNVER, BLOCKED, INFO = "PASS", "FAIL", "UNVERIFIABLE", "BLOCKED", "INFO"
SNPP_YM = 201202          # first full S-NPP month
AQUA_YM = 200207          # first Aqua month; earlier is Terra-only
CANADA = (-140.0, 42.0, -52.0, 72.0)

class Audit:
    def __init__(self):
        self.rows = []    # dicts: layer, id, claim, expected, actual, verdict, detail
    def add(self, layer, cid, claim, expected, actual, verdict, detail=""):
        self.rows.append({"layer": layer, "id": cid, "claim": claim,
                          "expected": expected, "actual": actual,
                          "verdict": verdict, "detail": detail})
    def check(self, layer, cid, claim, expected, actual, tol_abs=None, tol_rel=None):
        e, a = float(expected), float(actual)
        tol = tol_abs if tol_abs is not None else abs(e) * (tol_rel or 0.0)
        ok = abs(a - e) <= tol
        self.add(layer, cid, claim, expected, actual, PASS if ok else FAIL,
                 f"|diff|={abs(a-e):.6g} tol={tol:.6g}")
        return ok
    def fails(self, layer=None):
        return [r for r in self.rows if r["verdict"] == FAIL and (layer is None or r["layer"] == layer)]

# ---------------------------------------------------------------- decode ---
def decode_cells(c):
    """Own implementation of the compact cell format (see app decodeCells)."""
    lats, lons, nm = c["cell_lat"], c["cell_lon"], c["n_months"]
    n = len(c["t"])
    lat = np.empty(n); lon = np.empty(n); i = 0
    for k, cnt in enumerate(nm):
        lat[i:i+cnt] = lats[k]; lon[i:i+cnt] = lons[k]; i += cnt
    t = np.asarray(c["t"], dtype=np.int64)
    return {"lat": lat, "lon": lon,
            "year": c["t0_year"] + t // 12, "month": t % 12 + 1,
            "modis": np.asarray(c["modis_count"], dtype=np.int64),
            "viirs": np.asarray(c["viirs_count"], dtype=np.int64),
            "harm": np.asarray(c["harmonized_count"], dtype=float)}

def encode_cells(c, dec):
    """Re-encode decoded cells in original cell order; returns dict of arrays."""
    out = {"cell_lat": list(c["cell_lat"]), "cell_lon": list(c["cell_lon"]),
           "n_months": list(c["n_months"]), "t": [], "modis_count": [],
           "viirs_count": [], "harmonized_count": []}
    i = 0
    for cnt in c["n_months"]:
        sl = slice(i, i + cnt)
        out["t"].extend(((dec["year"][sl] - c["t0_year"]) * 12 + (dec["month"][sl] - 1)).tolist())
        out["modis_count"].extend(dec["modis"][sl].tolist())
        out["viirs_count"].extend(dec["viirs"][sl].tolist())
        out["harmonized_count"].extend(dec["harm"][sl].tolist())
        i += cnt
    return out

def load_ctx(root):
    data = json.loads((root / "app/data/monthly.json").read_text())
    docs = {}
    for rel in ["README.md", "SPEC.md", "docs/VALIDATION.md", "docs/PROJECT_PAGE.md",
                "docs/DEMO_SCRIPT.md", "docs/OM_TABLE_VERDICT.md", "app/index.html",
                "experiments/run_baseline.py"]:
        p = root / rel
        docs[rel] = p.read_text(errors="replace") if p.exists() else ""
    return {"data": data, "dec": decode_cells(data["cells"]), "docs": docs}

def ym(y, m): return y * 100 + m

# ------------------------------------------------------------------- L0 ----
def layer_L0(A, ctx, claims):
    d, dec, rm = ctx["data"], ctx["dec"], ctx["data"]["region_monthly"]
    cl = {c["id"]: c for c in claims}
    A.check("L0", "entries", "Shipped cell-month entries", cl["entries"]["expected"], len(dec["harm"]), tol_abs=0)
    A.add("L0", "n_months_sum", "sum(n_months) equals entry count", len(dec["harm"]),
          int(sum(d["cells"]["n_months"])), PASS if sum(d["cells"]["n_months"]) == len(dec["harm"]) else FAIL)
    A.check("L0", "cells", "Distinct cells", cl["cells"]["expected"], len(d["cells"]["cell_lat"]), tol_abs=0)
    A.check("L0", "region_months", "Region-month rows", cl["region_months"]["expected"], len(rm), tol_abs=0)
    bad = sum(1 for r in rm if r["total"] != r["modis"] + r["viirs"])
    A.add("L0", "totals_identity", "region_monthly total = modis + viirs, violations", 0, bad, PASS if bad == 0 else FAIL)
    finite = bool(np.isfinite(dec["harm"]).all() and (dec["harm"] >= 0).all()
                    and (dec["modis"] >= 0).all() and (dec["viirs"] >= 0).all())
    A.add("L0", "finite_nonneg", "All counts finite and non-negative", True, finite, PASS if finite else FAIL)
    months = {(r["year"], r["month"]) for r in rm}
    full = {(y, m) for y in range(2000, 2027) for m in range(1, 13) if (2000, 11) <= (y, m) <= (2026, 10)}
    A.add("L0", "span", "Region-months are exactly Nov 2000..Oct 2026 (no Nov 2026, no gaps)",
          312, len(months & full), PASS if months == full else FAIL,
          f"missing={sorted(full-months)[:4]} extra={sorted(months-full)[:4]}")
    cm = set(zip(dec["year"].tolist(), dec["month"].tolist()))
    A.add("L0", "cell_months_match", "Decoded cell months match region_monthly months",
          len(months), len(cm & months), PASS if cm == months else FAIL)
    w, s, e, n = CANADA
    out = int(((dec["lon"] < w) | (dec["lon"] > e) | (dec["lat"] < s) | (dec["lat"] > n)).sum())
    A.add("L0", "bbox", "Cell entries outside Canada bbox", 0, out, PASS if out == 0 else FAIL)
    enc = encode_cells(d["cells"], dec)
    rt = (enc["t"] == list(d["cells"]["t"]) and enc["modis_count"] == list(d["cells"]["modis_count"])
          and enc["viirs_count"] == list(d["cells"]["viirs_count"])
          and enc["harmonized_count"] == list(d["cells"]["harmonized_count"])
          and enc["cell_lat"] == list(d["cells"]["cell_lat"]) and enc["cell_lon"] == list(d["cells"]["cell_lon"]))
    A.add("L0", "roundtrip", "Decode -> re-encode reproduces the shipped arrays exactly",
          True, rt, PASS if rt else FAIL)

# ------------------------------------------------------------------- L1 ----
def layer_L1(A, ctx, claims):
    dec, rm = ctx["dec"], ctx["data"]["region_monthly"]
    cl = {c["id"]: c for c in claims}
    rmap = {(r["year"], r["month"]): r for r in rm}
    def tol(c): return {"tol_abs": c["tol_abs"]} if "tol_abs" in c else {"tol_rel": c["tol_rel"]}
    may = rmap[(2023, 5)]
    A.check("L1", "may23_modis", "May 2023 MODIS", cl["may23_modis"]["expected"], may["modis"], tol_abs=0)
    A.check("L1", "may23_viirs", "May 2023 VIIRS", cl["may23_viirs"]["expected"], may["viirs"], tol_abs=0)
    A.check("L1", "may23_harm", "May 2023 harmonized", cl["may23_harm"]["expected"], may["harmonized"], tol_abs=cl["may23_harm"]["tol_abs"])
    peak = max(rm, key=lambda r: r["harmonized"])
    A.add("L1", "peak_month", "Peak harmonized month is Aug 2023", "2023-08",
          f"{peak['year']}-{peak['month']:02d}", PASS if (peak["year"], peak["month"]) == (2023, 8) else FAIL)
    A.check("L1", "aug23_harm", "Aug 2023 harmonized", cl["aug23_harm"]["expected"], rmap[(2023, 8)]["harmonized"], **tol(cl["aug23_harm"]))
    # per-month cell sums vs region_monthly (rounding tolerance, as in verify_all)
    worst, viol = 0.0, 0
    for (y, m), r in rmap.items():
        sel = (dec["year"] == y) & (dec["month"] == m)
        s = float(dec["harm"][sel].sum()); tol_m = 0.005 * int(sel.sum()) + 0.01
        worst = max(worst, abs(s - r["harmonized"]) - tol_m)
        if abs(s - r["harmonized"]) > tol_m: viol += 1
    A.add("L1", "cell_rm_agree", "Cell harmonized sums agree with region_monthly every month",
          0, viol, PASS if viol == 0 else FAIL, f"max excess over tolerance={worst:.4f}")
    sel = (dec["lon"] >= -110) & (dec["lon"] <= -100) & (dec["lat"] >= 50) & (dec["lat"] <= 55) & (dec["year"] == 2023) & (dec["month"] == 5)
    A.check("L1", "prairies_harm", "Prairies May 2023 harmonized (cells)", cl["prairies_harm"]["expected"], float(dec["harm"][sel].sum()), tol_abs=cl["prairies_harm"]["tol_abs"])
    A.check("L1", "prairies_n", "Prairies May 2023 entries", cl["prairies_n"]["expected"], int(sel.sum()), tol_abs=0)
    raw = {y: sum(r["total"] for r in rm if r["year"] == y) for y in (2011, 2012)}
    har = {y: sum(r["harmonized"] for r in rm if r["year"] == y) for y in (2011, 2012)}
    mod = {y: sum(r["modis"] for r in rm if r["year"] == y) for y in (2011, 2012)}
    A.check("L1", "raw_2011", "Raw total 2011", cl["raw_2011"]["expected"], raw[2011], tol_abs=0)
    A.check("L1", "raw_2012", "Raw total 2012", cl["raw_2012"]["expected"], raw[2012], tol_abs=0)
    A.check("L1", "jump_raw", "Raw jump 2011->2012 (%)", cl["jump_raw"]["expected"], (raw[2012] / raw[2011] - 1) * 100, tol_abs=cl["jump_raw"]["tol_abs"])
    A.check("L1", "jump_harm", "Harmonized jump 2011->2012 (%)", cl["jump_harm"]["expected"], (har[2012] / har[2011] - 1) * 100, tol_abs=cl["jump_harm"]["tol_abs"])
    A.check("L1", "jump_modis", "MODIS-alone jump 2011->2012 (%)", cl["jump_modis"]["expected"], (mod[2012] / mod[2011] - 1) * 100, tol_abs=cl["jump_modis"]["tol_abs"])

# ------------------------------------------------------------------- L2 ----
def layer_L2(A, ctx, claims):
    dec, rm = ctx["dec"], ctx["data"]["region_monthly"]
    ymv = dec["year"] * 100 + dec["month"]
    era = ymv >= SNPP_YM
    bad_cell = int((era & (np.abs(dec["harm"] - dec["viirs"]) > 0.011)).sum())
    A.add("L2", "snpp_era_cells", "SNPP-era cells: harmonized != VIIRS observed, count",
          0, bad_cell, PASS if bad_cell == 0 else FAIL)
    bad_rm, exempt = 0, []
    for r in rm:
        if ym(r["year"], r["month"]) >= SNPP_YM:
            if r["viirs"] == 0: exempt.append(f"{r['year']}-{r['month']:02d}")
            elif abs(r["harmonized"] - r["viirs"]) > 0.011: bad_rm += 1
    A.add("L2", "snpp_era_months", "SNPP-era months: harmonized != VIIRS observed, count",
          0, bad_rm, PASS if bad_rm == 0 else FAIL,
          f"zero-VIIRS months (converted-MODIS exception path): {exempt or 'none'}")
    out_band = []
    for r in rm:
        v = ym(r["year"], r["month"])
        if AQUA_YM <= v < SNPP_YM and r["modis"] > 0:
            ratio = r["harmonized"] / r["modis"]
            if not (0.5 <= ratio <= 20.0): out_band.append((f"{r['year']}-{r['month']:02d}", round(ratio, 2)))
    A.add("L2", "modis_era_band", "MODIS-era months with conversion ratio outside [0.5, 20]",
          0, len(out_band), PASS if not out_band else FAIL, f"{out_band[:6]}")
    terra = [f"{r['year']}-{r['month']:02d}" for r in rm if ym(r["year"], r["month"]) < AQUA_YM]
    A.add("L2", "terra_era", "Terra-only months (before Jul 2002) have no holdout coverage",
          "unvalidated by design", f"{len(terra)} months: {terra[0]}..{terra[-1]}", INFO)

# ------------------------------------------------------------------- L5 ----
STALE_PATTERNS = [r"209,913", r"209913", r"14\.8\s*[x×]"]
METHOD_PATTERNS = [r"FRP-bin", r"FRP bin", r"FRP×season", r"fire intensity and season",
                   r"by fire size and season", r"stratified by fire intensity"]
PLACEHOLDER_PATTERNS = [r"\[X\]", r"\[TABLE\]", r"\[RESULT\]", r"\[MAPE", r"\[A\]%", r"\[B\]%"]
PUBLIC_FILES = ["README.md", "app/index.html", "docs/PROJECT_PAGE.md", "docs/DEMO_SCRIPT.md"]
METHOD_FILES = ["app/index.html", "docs/PROJECT_PAGE.md", "docs/DEMO_SCRIPT.md", "SPEC.md"]
PLACEHOLDER_FILES = ["docs/PROJECT_PAGE.md", "docs/DEMO_SCRIPT.md"]

def _hits(text, patterns):
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        for p in patterns:
            if re.search(p, line): out.append((ln, p, line.strip()[:110]))
    return out

def layer_L5(A, ctx, claims):
    docs = ctx["docs"]
    for f in PUBLIC_FILES:
        h = _hits(docs.get(f, ""), STALE_PATTERNS)
        A.add("L5", f"stale:{f}", f"Stale pre-v2 numbers in {f}", 0, len(h),
              PASS if not h else FAIL, "; ".join(f"L{ln} /{p}/" for ln, p, _ in h[:4]))
    for f in METHOD_FILES:
        h = _hits(docs.get(f, ""), METHOD_PATTERNS)
        A.add("L5", f"method:{f}", f"Rejected FRP-stratified method described as shipped in {f}",
              0, len(h), PASS if not h else FAIL,
              "; ".join(f"L{ln}: {txt}" for ln, _, txt in h[:3]))
    for f in METHOD_FILES:
        h = _hits(docs.get(f, ""), [r"2012[–-]2023 overlap"])
        if h:
            A.add("L5", f"window:{f}", f"Calibration window misstated as 2012-2023 overlap in {f}",
                  0, len(h), FAIL, "; ".join(f"L{ln}: {txt}" for ln, _, txt in h[:2]))
    for f in PLACEHOLDER_FILES:
        h = _hits(docs.get(f, ""), PLACEHOLDER_PATTERNS)
        A.add("L5", f"placeholders:{f}", f"Unfilled placeholders in {f}", 0, len(h),
              PASS if not h else FAIL, "; ".join(f"L{ln} /{p}/" for ln, p, _ in h[:6]))
    rb = docs.get("experiments/run_baseline.py", "")
    missing = [v for v in ["0.1955", "0.1691", "0.1792", "0.2062"] if v not in rb]
    A.add("L5", "baseline_expectations",
          "Experiments harness hard-codes the old-rule reproduction expectations "
          "(Canada own 0.1955, global 0.1691, Amazon 0.1792, Mediterranean 0.2062)",
          "all present", f"missing: {missing or 'none'}", PASS if not missing else FAIL)

# ------------------------------------------------------------------- L6 ----
def _run_shallow(ctx, claims):
    """Run L0/L1/L2/L5 against an arbitrary context; return list of FAIL rows."""
    A = Audit()
    layer_L0(A, ctx, claims); layer_L1(A, ctx, claims)
    layer_L2(A, ctx, claims); layer_L5(A, ctx, claims)
    return [r for r in A.rows if r["verdict"] == FAIL]

def layer_L6(A, ctx, claims):
    base_fail_ids = {r["id"] for r in _run_shallow(ctx, claims)}
    dec = ctx["dec"]
    def mutated(fn):
        c2 = {"data": copy.deepcopy(ctx["data"]), "docs": dict(ctx["docs"])}
        fn(c2)
        c2["dec"] = decode_cells(c2["data"]["cells"])
        return c2
    tests = []
    # 1. +1 harmonized on one cell in the smallest MODIS-era month
    def m1(c2):
        counts = {}
        for y, m in zip(dec["year"].tolist(), dec["month"].tolist()): counts[(y, m)] = counts.get((y, m), 0) + 1
        cand = sorted([(n, k) for k, n in counts.items() if AQUA_YM <= ym(*k) < SNPP_YM])
        (y, m) = cand[0][1]
        i = int(np.where((dec["year"] == y) & (dec["month"] == m))[0][0])
        c2["data"]["cells"]["harmonized_count"][i] += 1.0
    tests.append(("cell harmonized +1 in smallest MODIS-era month", m1))
    # 2. May 2023 region total altered
    def m2(c2):
        for r in c2["data"]["region_monthly"]:
            if (r["year"], r["month"]) == (2023, 5): r["harmonized"] += 100.0
    tests.append(("May 2023 region harmonized +100", m2))
    # 3. two adjacent region months swapped
    def m3(c2):
        rm = c2["data"]["region_monthly"]
        idx = [i for i, r in enumerate(rm) if (r["year"], r["month"]) == (2021, 6)][0]
        rm[idx]["harmonized"], rm[idx + 1]["harmonized"] = rm[idx + 1]["harmonized"], rm[idx]["harmonized"]
    tests.append(("Jun/Jul 2021 region harmonized swapped", m3))
    # 4. Nov 2026 injected
    def m4(c2):
        c2["data"]["region_monthly"].append({"year": 2026, "month": 11, "modis": 5, "viirs": 0,
                                             "total": 5, "harmonized": 10.0, "mean_frp": 1.0})
    tests.append(("Nov 2026 region-month injected", m4))
    # 5. totals identity broken
    def m5(c2): c2["data"]["region_monthly"][10]["total"] += 1
    tests.append(("region_monthly total != modis + viirs", m5))
    # 6. SNPP-era cell replaced by a converted-style value
    def m6(c2):
        i = int(np.where((dec["year"] == 2023) & (dec["month"] == 5) & (dec["modis"] > 0))[0][0])
        c2["data"]["cells"]["harmonized_count"][i] = float(dec["modis"][i]) * 3.69
    tests.append(("SNPP-era cell harmonized set to MODIS x 3.69", m6))
    # 7. cell moved outside the bbox
    def m7(c2): c2["data"]["cells"]["cell_lon"][0] = -30.0
    tests.append(("cell longitude moved to -30", m7))
    # 8. stale number planted in a public doc
    def m8(c2): c2["docs"]["README.md"] = c2["docs"]["README.md"] + "\nPeak month: 209,913 detections.\n"
    tests.append(("stale 209,913 planted in README", m8))
    caught = 0
    for name, fn in tests:
        new_fails = {r["id"] for r in _run_shallow(mutated(fn), claims)} - base_fail_ids
        ok = len(new_fails) > 0
        caught += ok
        A.add("L6", f"mutation:{name}", f"Fault injection caught: {name}",
              ">=1 new FAIL", f"{sorted(new_fails) if new_fails else 'NOT CAUGHT'}",
              PASS if ok else FAIL)
    A.add("L6", "score", "Fault-injection score", "8/8", f"{caught}/8",
          PASS if caught == 8 else FAIL)

# ----------------------------------------------------------------- L3/L4 ---
def grid_aggregates(grid_path):
    """DuckDB SQL over the raw grid: the audit's own aggregation path."""
    import duckdb
    con = duckdb.connect()
    p = f"read_parquet('{grid_path}')"
    filt = ("is_vegetation AND confidence IN ('n','h') "
            "AND satellite IN ('Terra','Aqua','SNPP')")
    total = con.execute(f"SELECT COUNT(*) FROM {p}").fetchone()[0]
    staging = con.execute(f"""
        SELECT cell_lat, cell_lon, year, month, satellite, daynight,
               SUM(hotspots) AS hotspots
        FROM {p} WHERE {filt}
          AND cell_lon BETWEEN -140 AND -52 AND cell_lat BETWEEN 42 AND 72
        GROUP BY ALL ORDER BY cell_lat, cell_lon, year, month, satellite, daynight
    """).df()
    world = con.execute(f"""
        SELECT year, month, satellite, daynight, SUM(hotspots) AS hotspots
        FROM {p} WHERE {filt} GROUP BY ALL
    """).df()
    frp = con.execute(f"""
        WITH cm AS (
          SELECT year, month, cell_lat, cell_lon, SUM(frp_sum)/SUM(hotspots) AS cell_frp
          FROM {p} WHERE {filt}
            AND cell_lon BETWEEN -140 AND -52 AND cell_lat BETWEEN 42 AND 72
          GROUP BY ALL)
        SELECT year, month, AVG(cell_frp) AS mean_frp FROM cm GROUP BY ALL
    """).df()
    con.close()
    return int(total), staging, world, {(int(r.year), int(r.month)): float(r.mean_frp)
                                        for r in frp.itertuples()}

def _prep(st):
    st = st.copy()
    st["sensor"] = np.where(st["satellite"].isin(["Terra", "Aqua"]), "MODIS", "VIIRS_SNPP")
    st["season"] = np.where(st["month"].between(5, 9), "fire", "off")
    return st

STRATA4 = [("fire", "D"), ("fire", "N"), ("off", "D"), ("off", "N")]

def ratios_calc(st, years, fallback=None):
    """Spec: S-NPP/MODIS per season x day/night from summed overlap counts.
    Thin strata (<50 MODIS) take the fallback table's ratio, else the pooled
    day/night ratio. Implemented from docs/VALIDATION.md, not copied."""
    import pandas as pd
    d = st[st["year"].between(*years)]
    def ssum(mask):
        g = d[mask].groupby(["season", "daynight"])["hotspots"].sum()
        return {(s, dn): float(g.get((s, dn), 0.0)) for s, dn in STRATA4}
    modis, terra, snpp = ssum(d["sensor"] == "MODIS"), ssum(d["satellite"] == "Terra"), ssum(d["satellite"] == "SNPP")
    dn_pool = {}
    for dn in ("D", "N"):
        sub = d[d["daynight"] == dn]
        dn_pool[dn] = (float(sub.loc[sub["satellite"] == "SNPP", "hotspots"].sum()),
                       float(sub.loc[sub["sensor"] == "MODIS", "hotspots"].sum()),
                       float(sub.loc[sub["satellite"] == "Terra", "hotspots"].sum()))
    rows = {}
    for k in STRATA4:
        mo, te, sn = modis[k], terra[k], snpp[k]
        ratio = sn / max(mo, 1.0); ratio_t = sn / max(te, 1.0)
        thin, thin_t = mo < 50, te < 50
        if thin or thin_t:
            if fallback is not None:
                if thin: ratio = fallback[k][0]
                if thin_t: ratio_t = fallback[k][1]
            else:
                sdn, mdn, tdn = dn_pool[k[1]]
                if thin: ratio = sdn / max(mdn, 1.0)
                if thin_t: ratio_t = sdn / max(tdn, 1.0)
        rows[k] = {"modis": mo, "terra": te, "snpp": sn, "ratio": ratio,
                   "ratio_terra": ratio_t, "fallback": thin}
    return rows

def _block(x): return np.floor(x + 1e-9)

def fit_rule_calc(st, start, end_year, fallback=None):
    """Spec: block ratios shrunk k=200 toward region ratios; monthly power law
    per calendar month x day/night with smearing correction and missed-fire
    uplift capped at 2x. Fit window: ym >= start, year <= end_year."""
    d = st[((st["year"] * 100 + st["month"]) >= start[0] * 100 + start[1]) & (st["year"] <= end_year)].copy()
    region = ratios_calc(d, (start[0], end_year), fallback)
    d["m"] = np.where(d["sensor"] == "MODIS", d["hotspots"], 0)
    d["s"] = np.where(d["satellite"] == "SNPP", d["hotspots"], 0)
    d["bla"] = _block(d["cell_lat"].astype(float)); d["blo"] = _block(d["cell_lon"].astype(float))
    bg = d.groupby(["bla", "blo", "season", "daynight"])[["m", "s"]].sum()
    blocks = {}
    for (bla, blo, ssn, dn), r in bg.iterrows():
        rr = region[(ssn, dn)]["ratio"]
        blocks[(bla, blo, ssn, dn)] = (float(r["s"]) + 200.0 * rr) / (float(r["m"]) + 200.0)
    rm = d.groupby(["year", "month", "daynight"])[["m", "s"]].sum().reset_index()
    pl = {}
    for (mo, dn), g in rm.groupby(["month", "daynight"]):
        pos = g[g["m"] > 0]
        x, y = np.log(pos["m"].astype(float).values), np.log1p(pos["s"].astype(float).values)
        if len(pos) < 5 or np.ptp(x) == 0:
            b, a, smear = 1.0, float(np.log((pos["s"].sum() + 1) / max(pos["m"].sum(), 1))), 1.0
        else:
            b, a = np.polyfit(x, y, 1)
            smear = float(np.mean(np.exp(y - (a + b * x))))
        missed = float(g.loc[g["m"] <= 0, "s"].sum()) / max(float(g["s"].sum()), 1.0)
        pl[(int(mo), dn)] = {"a": float(a), "b": float(b), "smear": smear,
                             "uplift": float(1 / (1 - min(missed, 0.5)))}
    return {"region": region, "blocks": blocks, "pl": pl}

def _season_of(month): return "fire" if 5 <= int(month) <= 9 else "off"

def converted_calc(st_modis, rule):
    """Spec: weight = hotspots x block_ratio x (0.5 + 0.5 x monthly factor);
    Terra-only months use ratio_terra. Input: MODIS staging rows only.
    The monthly factor is constant within a (year, month, day/night) group
    because season is a function of the calendar month."""
    d = st_modis.copy()
    d["bla"] = _block(d["cell_lat"].astype(float)); d["blo"] = _block(d["cell_lon"].astype(float))
    skeys = list(zip(d["season"], d["daynight"]))
    reg_ratio = np.array([rule["region"][k]["ratio"] for k in skeys])
    reg_terra = np.array([rule["region"][k]["ratio_terra"] for k in skeys])
    bkeys = list(zip(d["bla"], d["blo"], d["season"], d["daynight"]))
    br = np.array([rule["blocks"].get(k, rr) for k, rr in zip(bkeys, reg_ratio)])
    region_m = d.groupby(["year", "month", "daynight"])["hotspots"].sum()
    factor_map = {}
    for (y, mo, dn), rmv in region_m.items():
        p = rule["pl"].get((int(mo), dn))
        lin = rule["region"][(_season_of(mo), dn)]["ratio"] * float(rmv)
        if p is None or not (lin > 0):
            factor_map[(y, mo, dn)] = 1.0
            continue
        pred = math.exp(p["a"] + p["b"] * math.log(max(float(rmv), 1.0))) * p["smear"] - 1.0 if rmv > 0 else 0.0
        pred = max(pred, 0.0) * p["uplift"]
        f = pred / max(lin, 1e-9)
        factor_map[(y, mo, dn)] = f if math.isfinite(f) else 1.0
    factor = np.array([factor_map[k] for k in zip(d["year"], d["month"], d["daynight"])])
    w = d["hotspots"].astype(float).values * br * (0.5 + 0.5 * factor)
    early = (d["year"] * 100 + d["month"]).values < AQUA_YM
    d["weight"] = np.where(early, d["hotspots"].astype(float).values * reg_terra, w)
    return d

def converted_old_calc(st_modis, table):
    d = st_modis.copy()
    skeys = list(zip(d["season"], d["daynight"]))
    ratio = np.array([table[k]["ratio"] for k in skeys])
    terra = np.array([table[k]["ratio_terra"] for k in skeys])
    w = d["hotspots"].astype(float).values * ratio
    early = (d["year"] * 100 + d["month"]).values < AQUA_YM
    d["weight"] = np.where(early, d["hotspots"].astype(float).values * terra, w)
    return d

def layer_L3(A, ctx, claims, grid_path):
    cl = {c["id"]: c for c in claims}
    total, staging, world, frp = grid_aggregates(grid_path)
    A.check("L3", "grid_rows", "Rows in data-v2 grid parquet", cl["grid_rows"]["expected"], total, tol_abs=0)
    st = _prep(staging)
    import pandas as pd
    st["modis_c"] = np.where(st["sensor"] == "MODIS", st["hotspots"], 0)
    st["viirs_c"] = np.where(st["satellite"] == "SNPP", st["hotspots"], 0)
    monthly = st.groupby(["cell_lat", "cell_lon", "year", "month"])[["modis_c", "viirs_c"]].sum().reset_index()
    monthly = monthly[~((monthly["year"] == 2026) & (monthly["month"] == 11))]
    A.check("L3", "rebuilt_rows", "Rebuilt Canada cell-month rows (Nov 2026 excluded)",
            cl["entries"]["expected"], len(monthly), tol_abs=0)
    dec = ctx["dec"]
    ship = {(round(float(la), 4), round(float(lo), 4), int(y), int(m)): (int(mo), int(vi))
            for la, lo, y, m, mo, vi in zip(dec["lat"], dec["lon"], dec["year"], dec["month"], dec["modis"], dec["viirs"])}
    mism = 0
    for r in monthly.itertuples():
        key = (round(float(r.cell_lat), 4), round(float(r.cell_lon), 4), int(r.year), int(r.month))
        if ship.get(key) != (int(r.modis_c), int(r.viirs_c)): mism += 1
    A.add("L3", "rowlevel_inputs", "Rebuilt cell-month MODIS/VIIRS inputs differing from shipped file",
          0, mism + abs(len(ship) - len(monthly)), PASS if mism == 0 and len(ship) == len(monthly) else FAIL)
    rm = {(r["year"], r["month"]): r for r in ctx["data"]["region_monthly"]}
    bad = 0
    for (y, m), g in monthly.groupby(["year", "month"]):
        r = rm.get((int(y), int(m)))
        if r is None or int(g["modis_c"].sum()) != r["modis"] or int(g["viirs_c"].sum()) != r["viirs"]: bad += 1
    A.add("L3", "monthly_inputs", "Months whose rebuilt MODIS/VIIRS totals differ from region_monthly",
          0, bad, PASS if bad == 0 else FAIL)
    bad_frp, worst_frp = 0, 0.0
    for r in ctx["data"]["region_monthly"]:
        v = frp.get((r["year"], r["month"]))
        if v is None or abs(v - r["mean_frp"]) > 0.011: bad_frp += 1
        elif abs(v - r["mean_frp"]) > worst_frp: worst_frp = abs(v - r["mean_frp"])
    A.add("L3", "mean_frp", "region_monthly mean_frp recomputed (mean of per-cell-month mean FRP), months off by >0.011",
          0, bad_frp, PASS if bad_frp == 0 else FAIL, f"max deviation within tolerance={worst_frp:.4f}")
    return st, _prep(world)

def _holdout_scores(st, convert_fn):
    test = st[st["year"].between(2021, 2023)]
    pred = convert_fn(test[test["sensor"] == "MODIS"]).groupby(["year", "month"])["weight"].sum()
    act = test[test["satellite"] == "SNPP"].groupby(["year", "month"])["hotspots"].sum()
    import pandas as pd
    both = pd.concat([pred.rename("pred"), act.rename("actual")], axis=1).fillna(0.0)
    x = both[both["actual"] > 0]
    ape = (x["pred"] - x["actual"]).abs() / x["actual"]
    return {"mape": float(ape.mean() * 100), "wape": float((x["pred"] - x["actual"]).abs().sum() / x["actual"].sum() * 100),
            "bias": float(((x["pred"] - x["actual"]) / x["actual"]).mean() * 100), "n": int(len(x))}

def layer_L4(A, ctx, claims, st, world):
    cl = {c["id"]: c for c in claims}
    global_fit = ratios_calc(world[(world["year"] * 100 + world["month"]) >= SNPP_YM], (2012, 2025))
    global_r = ratios_calc(world, (2012, 2020))
    # --- production refit (Feb 2012 - Dec 2025, global fallback as shipped) ---
    rule = fit_rule_calc(st, (2012, 2), 2025, fallback={k: (v["ratio"], v["ratio_terra"]) for k, v in global_fit.items()})
    thin = [f"{k}" for k, v in rule["region"].items() if v["fallback"]]
    A.add("L4", "thin_strata", "Canada strata thin enough to need the global fallback",
          "none", f"{thin or 'none'}", INFO)
    conv = converted_calc(st[st["sensor"] == "MODIS"], rule)
    conv_m = conv.groupby(["cell_lat", "cell_lon", "year", "month"])["weight"].sum().rename("conv")
    act_m = st[st["satellite"] == "SNPP"].groupby(["cell_lat", "cell_lon", "year", "month"])["hotspots"].sum().rename("obs")
    import pandas as pd
    keys = st.groupby(["cell_lat", "cell_lon", "year", "month"]).size().reset_index()[["cell_lat", "cell_lon", "year", "month"]]
    keys = keys[~((keys["year"] == 2026) & (keys["month"] == 11))]
    m = keys.merge(conv_m, on=["cell_lat", "cell_lon", "year", "month"], how="left").merge(act_m, on=["cell_lat", "cell_lon", "year", "month"], how="left").fillna(0.0)
    month_obs = m.groupby(["year", "month"])["obs"].transform("sum")
    era = (m["year"] * 100 + m["month"]) >= SNPP_YM
    m["harm_refit"] = np.where(era & (month_obs > 0), m["obs"], m["conv"])
    mm = m.groupby(["year", "month"])["harm_refit"].sum()
    rm = {(r["year"], r["month"]): r["harmonized"] for r in ctx["data"]["region_monthly"]}
    devs = []
    for (y, mo), v in mm.items():
        if ym(int(y), int(mo)) < SNPP_YM and rm.get((int(y), int(mo))):
            devs.append(abs(float(v) - rm[(int(y), int(mo))]) / max(rm[(int(y), int(mo))], 1e-9) * 100)
    devs = np.array(devs)
    maxdev = float(devs.max()) if len(devs) else float("nan")
    A.add("L4", "refit_months", "MODIS-era region-months reproduced by the refit within 0.05%",
          "100% within 0.05% (clean-file noise floor is 0.001%)",
          f"max deviation {maxdev:.4f}% over {len(devs)} months",
          PASS if len(devs) and maxdev <= 0.05 else FAIL)
    refit_map = {(round(float(r.cell_lat), 4), round(float(r.cell_lon), 4), int(r.year), int(r.month)): float(r.harm_refit)
                 for r in m.itertuples()}
    dec = ctx["dec"]
    cell_dev = np.array([abs(refit_map.get((round(float(la), 4), round(float(lo), 4), int(y), int(mo)), float("nan")) - h)
                         for la, lo, y, mo, h in zip(dec["lat"], dec["lon"], dec["year"], dec["month"], dec["harm"])])
    n_bad = int((~(cell_dev <= 0.02)).sum())
    A.add("L4", "refit_cells", "Per-cell harmonized values reproduced by the refit (all eras), cells off by >0.02",
          0, n_bad, PASS if n_bad == 0 else FAIL,
          f"max per-cell deviation={np.nanmax(cell_dev):.4f} over {len(cell_dev)} cells")
    # --- holdouts ---
    hr = fit_rule_calc(st, (2012, 1), 2020, fallback={k: (v["ratio"], v["ratio_terra"]) for k, v in global_r.items()})
    sc = _holdout_scores(st, lambda rows: converted_calc(rows, hr))
    A.add("L4", "holdout_n", "Holdout months with S-NPP observed", 36, sc["n"], PASS if sc["n"] == 36 else FAIL)
    A.check("L4", "holdout_mape", "Holdout MAPE, shipped rule (%)", cl["holdout_mape"]["expected"], sc["mape"], tol_abs=cl["holdout_mape"]["tol_abs"])
    A.check("L4", "holdout_wape", "Holdout WAPE, shipped rule (%)", cl["holdout_wape"]["expected"], sc["wape"], tol_abs=cl["holdout_wape"]["tol_abs"])
    A.check("L4", "holdout_bias", "Holdout bias, shipped rule (%)", cl["holdout_bias"]["expected"], sc["bias"], tol_abs=cl["holdout_bias"]["tol_abs"])
    own = ratios_calc(st, (2012, 2020), fallback={k: (v["ratio"], v["ratio_terra"]) for k, v in global_r.items()})
    sc_own = _holdout_scores(st, lambda rows: converted_old_calc(rows, own))
    A.check("L4", "holdout_old_own", "Holdout MAPE, old rule own ratios (%)", cl["holdout_old_own"]["expected"], sc_own["mape"], tol_abs=cl["holdout_old_own"]["tol_abs"])
    sc_glb = _holdout_scores(st, lambda rows: converted_old_calc(rows, global_r))
    A.check("L4", "holdout_old_global", "Holdout MAPE, old rule global ratios (%)", cl["holdout_old_global"]["expected"], sc_glb["mape"], tol_abs=cl["holdout_old_global"]["tol_abs"])
    hr2 = fit_rule_calc(st, (2012, 2), 2020, fallback={k: (v["ratio"], v["ratio_terra"]) for k, v in global_r.items()})
    sc_feb = _holdout_scores(st, lambda rows: converted_calc(rows, hr2))
    A.check("L4", "holdout_feb_start", "Holdout MAPE, Feb-2012 fit start (%)", cl["holdout_feb_start"]["expected"], sc_feb["mape"], tol_abs=cl["holdout_feb_start"]["tol_abs"])
    for c in claims:
        if c.get("verdict_forced") == UNVER:
            A.add("L4", c["id"], c["claim"], c["expected"], "not recomputed", UNVER, c.get("why", ""))

# ---------------------------------------------------------------- report ---
def write_report(A, root, grid_note):
    import hashlib
    mj = root / "app/data/monthly.json"
    digest = hashlib.md5(mj.read_bytes()).hexdigest()[:12] if mj.exists() else "missing"
    sci_layers = ["L0", "L1", "L2", "L3", "L4", "L6"]
    sci_fail = [r for r in A.rows if r["verdict"] == FAIL and r["layer"] in sci_layers]
    pub_fail = [r for r in A.rows if r["verdict"] == FAIL and r["layer"] == "L5"]
    blocked = [r for r in A.rows if r["verdict"] == BLOCKED]
    unver = [r for r in A.rows if r["verdict"] == UNVER]
    passes = [r for r in A.rows if r["verdict"] == PASS]
    numbers_verdict = "FAIL" if sci_fail else ("INCOMPLETE" if blocked else "PASS")
    lines = ["# Audit Report — independent recomputation of the shipped Canada record",
             "",
             f"Artifact audited: `app/data/monthly.json` (md5 {digest}) — every value in it, per cell and "
             "per month, plus the Canada validation numbers in the claims registry. Engine: "
             "`pipeline/audit_engine.py`, which shares no code with the production pipeline (DuckDB SQL "
             "aggregation over the raw grid; method refit implemented from docs/VALIDATION.md). "
             "Claims and tolerances: `pipeline/audit_claims.json`.",
             f"Grid: {grid_note}",
             "",
             f"**NUMBERS verdict: {numbers_verdict}** — {len(passes)} checks passed, "
             f"{len(sci_fail)} failed, {len(unver)} unverifiable, {len(blocked)} blocked.",
             f"**PUBLICATION verdict: {'FAIL' if pub_fail else 'PASS'}** — {len(pub_fail)} publication findings.",
             "",
             "| Layer | Check | Published / expected | Recomputed | Verdict | Detail |",
             "|---|---|---|---|---|---|"]
    for r in A.rows:
        exp = str(r["expected"]).replace("|", "/")
        act = str(r["actual"]).replace("|", "/")
        det = str(r["detail"]).replace("|", "/")
        lines.append(f"| {r['layer']} | {r['claim']} | {exp} | {act} | {r['verdict']} | {det} |")
    lines += ["", "## Known gaps (stated, not hidden)",
              "- LOYO experiment averages are UNVERIFIABLE from the repo: the result CSVs are gitignored. "
              "The harness code and its hard-coded old-rule baseline expectations are in the repo (verified "
              "by check L5 baseline_expectations, and the Canada pair is numerically reproduced by L4), "
              "but the LOYO outputs themselves are not.",
              "- Terra-only months (Nov 2000 - Jun 2002) have no holdout coverage by design; their "
              "harmonized values rest on the Terra-only ratios alone.",
              "- Canada's untouched-holdout WAPE worsens under the shipped rule (8.8% -> 11.0%, nested check "
              "in docs/VALIDATION.md) even as MAPE improves; both figures belong in any honest summary.",
              "- The shipped app's own method text is a publication finding of this audit (see L5): the "
              "calibration it describes is not the calibration that produced the data.",
              ""]
    (root / "docs/AUDIT_REPORT.md").write_text("\n".join(lines))
    (root / "pipeline/audit_results.json").write_text(json.dumps(
        {"artifact_md5": digest, "rows": A.rows}, indent=1, sort_keys=True))
    return sci_fail, pub_fail, blocked

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--grid", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    root = Path(a.root)
    claims = json.loads((root / "pipeline/audit_claims.json").read_text())["claims"]
    ctx = load_ctx(root)
    A = Audit()
    layer_L0(A, ctx, claims); layer_L1(A, ctx, claims); layer_L2(A, ctx, claims); layer_L5(A, ctx, claims)
    if a.selftest:
        layer_L6(A, ctx, claims)
    grid = Path(a.grid) if a.grid else root / "data/derived/monthly_grid_025.parquet"
    if grid.exists():
        st, world = layer_L3(A, ctx, claims, str(grid))
        layer_L4(A, ctx, claims, st, world)
        grid_note = f"`{grid}` present; L3/L4 ran in full."
    else:
        for lid, name in [("L3", "Raw-input recomputation"), ("L4", "Method refit and holdout")]:
            A.add(lid, "blocked", name, "grid parquet present", f"{grid} not found", BLOCKED,
                  "Place the data-v2 monthly_grid_025.parquet at data/derived/ and re-run.")
        grid_note = f"`{grid}` NOT found; L3/L4 BLOCKED."
    sci_fail, pub_fail, blocked = write_report(A, root, grid_note)
    for r in A.rows:
        print(f"{r['layer']:3} {r['verdict']:12} {r['claim']}  [{r['actual']}]  {r['detail']}")
    print(f"\nNUMBERS: {'FAIL' if sci_fail else ('INCOMPLETE' if blocked else 'PASS')} ({len(sci_fail)} failed)  "
          f"PUBLICATION: {'FAIL' if pub_fail else 'PASS'} ({len(pub_fail)} findings)  "
          f"BLOCKED: {len(blocked)}")
    sys.exit(1 if sci_fail else (2 if blocked else 0))

if __name__ == "__main__":
    main()
