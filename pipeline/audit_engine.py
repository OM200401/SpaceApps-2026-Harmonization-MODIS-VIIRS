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
    (--pin is the one exception: it rewrites the claims registry, and only
    after every invariant has passed; see below.)
  * Verdicts: PASS / FAIL / UNVERIFIABLE / BLOCKED / STALE. Nothing is
    rounded up.

Change behaviour (v3.2):
  * The publication sweep DISCOVERS its files from the tree (app/, docs/,
    README, SPEC, experiments/) instead of a hard-coded list, so a new
    page or doc is swept from the day it appears. History documents
    (docs/VALIDATION.md, docs/OM_TABLE_VERDICT.md, experiments/) quote old
    numbers legitimately: their hits are INFO, never FAIL.
  * Claims split into INVARIANTS (identities, era rules, the grid refit:
    enforced in full no matter what) and ANCHORS (the recorded values of
    one specific artifact, pinned by its md5 in the registry). If the
    artifact changes, anchors that moved report STALE instead of FAIL,
    the recomputed values are printed, and invariants still run in full.
    --pin re-pins the anchors to the recomputed values after a human has
    reviewed the change; pinning is refused while any invariant fails,
    so a wrong number can never be pinned into truth.

  * Numbers stated in prose are reconciled too: a MAPE, WAPE, bias or
    detection total printed in a swept strict document must be one of the
    verified values, or it is a publication finding. Deleting a file the
    audit has always swept is a finding, not an improvement: additions
    are discovered automatically, deletions of known surfaces alarm.
  * Malformed inputs never produce a raw traceback or leave a stale
    green report behind: the audit writes an ABORTED report (one BLOCKED
    row naming the failure) and exits 3. Outputs are written atomically
    (temp file + rename), so the report and the results JSON can never
    be a mismatched pair from two different runs.

Usage: python pipeline/audit_engine.py [--root .] [--grid PATH]
       [--selftest] [--pin] [--strict]
Exit: 0 = no science FAIL, 1 = science FAIL, 2 = layers BLOCKED (no FAIL),
3 = inputs unreadable (ABORTED report written).
--strict also exits 1 when publication findings exist or the record is
STALE (for CI).
"""
import argparse, copy, json, math, os, re, sys
from pathlib import Path
import numpy as np

PASS, FAIL, UNVER, BLOCKED, INFO, STALE = "PASS", "FAIL", "UNVERIFIABLE", "BLOCKED", "INFO", "STALE"
SNPP_YM = 201202          # first full S-NPP month
AQUA_YM = 200207          # first Aqua month; earlier is Terra-only
CANADA = (-140.0, 42.0, -52.0, 72.0)

ANCHOR_IDS = {"entries", "cells", "region_months", "may23_modis", "may23_viirs",
              "may23_harm", "aug23_harm", "prairies_harm", "prairies_n",
              "raw_2011", "raw_2012", "jump_raw", "jump_harm", "jump_modis",
              "grid_rows", "holdout_mape", "holdout_wape", "holdout_bias",
              "holdout_old_own", "holdout_old_global", "holdout_feb_start",
              "peak_month"}

class Audit:
    def __init__(self, stale_mode=False, anchor_ids=()):
        self.rows = []    # dicts: layer, id, claim, expected, actual, verdict, detail
        self.stale_mode = stale_mode
        self.anchor_ids = set(anchor_ids)
    def add(self, layer, cid, claim, expected, actual, verdict, detail=""):
        if self.stale_mode and verdict == FAIL and cid in self.anchor_ids:
            verdict = STALE
            detail = (detail + " | anchor moved: artifact differs from the pinned "
                      "record; value shown is the recomputation").strip(" |")
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

HISTORY_FILES = {"docs/VALIDATION.md", "docs/OM_TABLE_VERDICT.md"}
EXCLUDED_FILES = {"docs/AUDIT_REPORT.md", "pipeline/audit_results.json"}
SUBMISSION_FILES = ["docs/PROJECT_PAGE.md", "docs/DEMO_SCRIPT.md"]
# Files the audit sweeps on the reference tree. Discovery below finds new
# files automatically; this list exists so that DELETING a known surface
# alarms instead of silently improving the report. Remove a line here, in
# the same PR that deletes the file, when a deletion is deliberate.
EXPECTED_FILES = ["README.md", "SPEC.md", "app/how-it-works.html", "app/index.html",
                  "app/report.html", "app/shared.css", "app/shared.js",
                  "docs/DEMO_SCRIPT.md", "docs/OM_TABLE_VERDICT.md",
                  "docs/PROJECT_PAGE.md", "docs/UI_DATA_CONTRACT.md",
                  "docs/VALIDATION.md", "experiments/README.md",
                  "experiments/harness.py", "experiments/prep.py",
                  "experiments/run_baseline.py", "experiments/run_conf.py",
                  "experiments/run_final.py", "experiments/run_nested.py",
                  "experiments/run_suite.py", "experiments/run_suite_d.py",
                  "experiments/run_suite_e.py"]

def _role_for(rel, first_line):
    if "audit: history" in first_line:
        return "history"
    if rel in HISTORY_FILES or rel.startswith("experiments/"):
        return "history"
    return "strict"

def discover_docs(root):
    """Find every public text surface in the tree, sorted, with a role.

    Swept: every .md/.txt anywhere (prose a reader can meet, in any
    folder), the app and docs code surfaces (.html/.js/.css), and the
    experiments code. Roles: "strict" (publication rules enforced as
    FAIL) and "history" (documents that quote old numbers legitimately:
    hits are INFO) — history comes from HISTORY_FILES, the experiments/
    tree, or a first line containing "audit: history" (self-declared, so
    visible in the file itself). The audit's own outputs are excluded so
    the sweep never reads its own report.
    """
    swept = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if rel in EXCLUDED_FILES:
            continue
        ext = p.suffix.lower()
        prose = ext in {".md", ".txt"}
        surface = rel.startswith(("app/", "docs/")) and ext in {".html", ".js", ".css"}
        experiment = rel.startswith("experiments/") and ext in {".py", ".md", ".txt"}
        if not (prose or surface or experiment):
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            text = p.read_text(errors="replace")
        except OSError:
            continue
        first = text.splitlines()[0] if text.splitlines() else ""
        swept[rel] = {"role": _role_for(rel, first)}
    docs = {rel: (root / rel).read_text(errors="replace") for rel in swept}
    return docs, swept

def load_ctx(root):
    data = json.loads((root / "app/data/monthly.json").read_text())
    docs, swept = discover_docs(root)
    return {"data": data, "dec": decode_cells(data["cells"]),
            "docs": docs, "swept": swept}

def artifact_md5(root):
    import hashlib
    mj = root / "app/data/monthly.json"
    return hashlib.md5(mj.read_bytes()).hexdigest() if mj.exists() else 'missing'

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
    js = ctx["docs"].get("app/shared.js", "")
    presets = re.findall(r'\{\s*id:\s*"([^"]+)",\s*name:\s*"([^"]+)",\s*bbox:\s*'
                         r'"(-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)"', js)
    if presets:
        lats = np.asarray(ctx["data"]["cells"]["cell_lat"], dtype=float)
        lons = np.asarray(ctx["data"]["cells"]["cell_lon"], dtype=float)
        parts = []
        for pid, name, w, s, e, n in presets:
            cnt = int(((lons >= float(w)) & (lons <= float(e))
                       & (lats >= float(s)) & (lats <= float(n))).sum())
            parts.append(f"{name}={cnt}")
        A.add("L2", "preset_coverage",
              "App region presets vs shipped cell coverage (distinct cells)",
              "coverage stated", "; ".join(parts), INFO,
              "Presets with 0 cells lie outside the Canada export; the app shows an "
              "honest no-data state for them. Stated so a preset change is never silent.")

# ------------------------------------------------------------------- L5 ----
STALE_PATTERNS = [r"209,913", r"209913", r"14\.8\s*[x×]"]
METHOD_PATTERNS = [r"FRP-bin", r"FRP bin", r"FRP×season", r"fire intensity and season",
                   r"by fire size and season", r"stratified by fire intensity"]
WINDOW_PATTERNS = [r"2012[–-]2023 overlap"]
PLACEHOLDER_PATTERNS = [r"\[X\]", r"\[TABLE\]", r"\[RESULT\]", r"\[MAPE", r"\[A\]%", r"\[B\]%"]

def _hits(text, patterns):
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        for p in patterns:
            if re.search(p, line): out.append((ln, p, line.strip()[:110]))
    return out

def _swept_of(ctx):
    if "swept" in ctx:
        return ctx["swept"]
    return {k: {"role": "history" if (k in HISTORY_FILES
                                      or k.startswith("experiments/")) else "strict"}
            for k in ctx["docs"]}

PROSE_METRIC_PATTERNS = [
    ("MAPE", re.compile(r"MAPE[^0-9]{0,24}?(\d+(?:\.\d+)?)\s*(?:%|percent\b|per\s?cent\b)"), "mape"),
    ("WAPE", re.compile(r"WAPE[^0-9]{0,24}?(\d+(?:\.\d+)?)\s*(?:%|percent\b|per\s?cent\b)"), "wape"),
    ("bias", re.compile(r"bias[^0-9\-]{0,24}?(-?\d+(?:\.\d+)?)\s*(?:%|percent\b|per\s?cent\b)"), "bias"),
]
PROSE_DETECTIONS = re.compile(r"(\d{1,3}(?:,\d{3})+)\s+detections")
# Verified values that are not registry claims: the regional holdouts from
# docs/VALIDATION.md (Amazon 8.3, Mediterranean 15.6) and the nested-check
# WAPEs (8.8 baseline, 11.0 shipped on the untouched holdout).
REGIONAL_VALUES = {"mape": {8.3, 15.6}, "wape": {8.8, 11.0}, "bias": set()}

def _prose_violations(text, claims):
    cl = {c["id"]: c for c in claims}
    allowed = {
        "mape": {float(cl[k]["expected"]) for k in
                 ("holdout_mape", "holdout_old_own", "holdout_old_global",
                  "holdout_feb_start")} | REGIONAL_VALUES["mape"],
        "wape": {float(cl["holdout_wape"]["expected"])} | REGIONAL_VALUES["wape"],
        "bias": {float(cl["holdout_bias"]["expected"])} | REGIONAL_VALUES["bias"],
    }
    det_allowed = {f"{int(float(cl[k]['expected'])):,}" for k in
                   ("may23_viirs", "may23_harm", "aug23_harm", "raw_2011", "raw_2012")}
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        for name, pat, key in PROSE_METRIC_PATTERNS:
            for m in pat.finditer(line):
                v = float(m.group(1))
                if all(abs(v - av) > 0.051 for av in allowed[key]):
                    out.append(f"L{ln}: {name} {v}% is not a verified value "
                               f"({sorted(allowed[key])})")
        for m in PROSE_DETECTIONS.finditer(line):
            if m.group(1) not in det_allowed:
                out.append(f"L{ln}: {m.group(1)} detections is not a verified total")
    return out

def layer_L5(A, ctx, claims):
    docs = ctx["docs"]
    swept = _swept_of(ctx)
    kinds = [("stale", STALE_PATTERNS, "Stale pre-v2 numbers"),
             ("method", METHOD_PATTERNS,
              "Rejected FRP-stratified method described as shipped"),
             ("window", WINDOW_PATTERNS,
              "Calibration window misstated as 2012-2023 overlap")]
    for f in sorted(swept):
        role = swept[f]["role"]
        text = docs.get(f, "")
        for kind, pats, label in kinds:
            h = _hits(text, pats)
            if role == "history":
                A.add("L5", f"{kind}:{f}", f"{label} in {f} (history doc: quoted context)",
                      0, len(h), INFO if h else PASS,
                      "; ".join(f"L{ln} /{p}/" for ln, p, _ in h[:4]))
            else:
                A.add("L5", f"{kind}:{f}", f"{label} in {f}", 0, len(h),
                      PASS if not h else FAIL,
                      "; ".join(f"L{ln}: {txt}" for ln, _, txt in h[:3]))
        if role == "strict":
            v = _prose_violations(text, claims)
            A.add("L5", f"prose:{f}",
                  f"Numbers stated in prose in {f} match the verified values",
                  0, len(v), PASS if not v else FAIL, "; ".join(v[:4]))
    for f in EXPECTED_FILES:
        if f not in docs:
            A.add("L5", f"missing:{f}", f"Expected swept file {f} is missing",
                  "present", "missing", FAIL,
                  "A file the audit has always swept disappeared. Deleting it must be a "
                  "deliberate, reviewed change (remove it from EXPECTED_FILES in the same "
                  "PR), never a silent improvement to this report.")
    for f in SUBMISSION_FILES:
        if f in docs:
            h = _hits(docs[f], PLACEHOLDER_PATTERNS)
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

def _run_shallow_rows(ctx, claims):
    A = Audit()
    layer_L0(A, ctx, claims); layer_L1(A, ctx, claims)
    layer_L2(A, ctx, claims); layer_L5(A, ctx, claims)
    return A.rows

def _new_or_worse(base_rows, mut_rows):
    """FAIL ids in mut_rows that are new, or whose numeric actual grew.

    Delta-by-id alone mis-scores the simulations in a dirty tree: if the
    real tree already fails the very check a mutation targets, the
    mutation is invisible by id but visible by count."""
    base = {r["id"]: r for r in base_rows if r["verdict"] == FAIL}
    out = set()
    for r in mut_rows:
        if r["verdict"] != FAIL:
            continue
        b = base.get(r["id"])
        if b is None:
            out.add(r["id"])
        else:
            try:
                if float(r["actual"]) > float(b["actual"]):
                    out.add(r["id"])
            except (TypeError, ValueError):
                pass
    return out

def layer_L6(A, ctx, claims):
    base_rows = _run_shallow_rows(ctx, claims)
    dec = ctx["dec"]
    def mutated(fn):
        c2 = {"data": copy.deepcopy(ctx["data"]), "docs": dict(ctx["docs"]),
              "swept": {k: dict(v) for k, v in _swept_of(ctx).items()}}
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
        new_fails = _new_or_worse(base_rows, _run_shallow_rows(mutated(fn), claims))
        ok = len(new_fails) > 0
        caught += ok
        A.add("L6", f"mutation:{name}", f"Fault injection caught: {name}",
              ">=1 new FAIL", f"{sorted(new_fails) if new_fails else 'NOT CAUGHT'}",
              PASS if ok else FAIL)
    A.add("L6", "score", "Fault-injection score", "8/8", f"{caught}/8",
          PASS if caught == 8 else FAIL)

# ------------------------------------------------------------------- L7 ----
def layer_L7(A, ctx, claims):
    """Change simulations: prove the audit adapts to a changing project.

    Each simulation mutates an in-memory copy the way a real change would
    (a new page appears, a doc is deleted, text moves into a script file)
    and asserts the sweep reacts correctly. C5 asserts the anchor/pin
    semantics directly. Nothing here touches the disk.
    """
    base_rows = _run_shallow_rows(ctx, claims)
    base_fail_ids = {r["id"] for r in base_rows if r["verdict"] == FAIL}
    def mutated_docs(fn):
        c2 = {"data": ctx["data"], "dec": ctx["dec"],
              "docs": dict(ctx["docs"]),
              "swept": {k: dict(v) for k, v in _swept_of(ctx).items()}}
        fn(c2)
        return c2
    tests = []
    def c1(c2):
        c2["docs"]["app/zz_new_page.html"] = "<p>Peak month: 209,913 detections.</p>"
        c2["swept"]["app/zz_new_page.html"] = {"role": "strict"}
    tests.append(("new app page with a stale number is caught", c1,
                  {"stale:app/zz_new_page.html"}))
    def c2(c2):
        c2["docs"]["app/zz_new_page.html"] = "<p>A new, clean page.</p>"
        c2["swept"]["app/zz_new_page.html"] = {"role": "strict"}
    tests.append(("new clean app page adds no finding", c2, set()))
    def c3(c2):
        c2["docs"]["docs/zz_new_doc.md"] = "Calibrated, stratified by fire intensity and season."
        c2["swept"]["docs/zz_new_doc.md"] = {"role": "strict"}
    tests.append(("new doc with the rejected method text is caught", c3,
                  {"method:docs/zz_new_doc.md"}))
    def c4(c2):
        del c2["docs"]["docs/PROJECT_PAGE.md"]
        del c2["swept"]["docs/PROJECT_PAGE.md"]
    tests.append(("deleted submission doc is a finding, not a pass", c4,
                  {"missing:docs/PROJECT_PAGE.md"}))
    def c7(c2):
        c2["docs"]["app/shared.js"] = c2["docs"].get("app/shared.js", "") + "\n// calibrated by FRP bin and season\n"
    tests.append(("method text moved into app/shared.js is caught", c7,
                  {"method:app/shared.js"}))
    def c8(c2):
        c2["docs"]["docs/VALIDATION.md"] = c2["docs"].get("docs/VALIDATION.md", "") + "\nOld peak was 209,913.\n"
    tests.append(("stale number quoted in a history doc is INFO, not FAIL", c8, set()))
    def c9(c2):
        c2["docs"]["README.md"] = c2["docs"].get("README.md", "") + "\nHoldout MAPE 9.1%.\n"
    tests.append(("wrong metric in README prose is caught", c9, {"prose:README.md"}))
    def c10(c2):
        target = next((f for f in EXPECTED_FILES if f in c2["docs"]), None)
        c2["_deleted"] = target
        if target:
            del c2["docs"][target]
            c2["swept"].pop(target, None)
    tests.append(("deleted swept file alarms instead of improving the report", c10,
                  lambda c2: {f"missing:{c2['_deleted']}"} if c2.get("_deleted") else set()))
    def c11(c2):
        c2["docs"]["app/notes.txt"] = "Peak: 209,913 detections."
        c2["swept"]["app/notes.txt"] = {"role": "strict"}
    tests.append(("stale number in a new .txt file is caught", c11,
                  {"stale:app/notes.txt"}))
    caught = 0
    for name, fn, expect in tests:
        c2 = mutated_docs(fn)
        mut_rows = _run_shallow_rows(c2, claims)
        new_fails = {r["id"] for r in mut_rows if r["verdict"] == FAIL} - base_fail_ids
        exp = expect(c2) if callable(expect) else expect
        if exp:
            ok = exp <= _new_or_worse(base_rows, mut_rows)
        else:
            ok = (new_fails == set()) and not _new_or_worse(base_rows, mut_rows)
        caught += bool(ok)
        A.add("L7", f"change:{name}", f"Change simulation: {name}",
              f"new FAILs {sorted(exp) if exp else 'none'}",
              f"new FAILs {sorted(new_fails)}", PASS if ok else FAIL)
    # C5: anchor semantics under a changed artifact (stale mode mapping)
    A5 = Audit(stale_mode=True, anchor_ids=ANCHOR_IDS)
    c5 = {"data": copy.deepcopy(ctx["data"]), "docs": ctx["docs"], "swept": ctx.get("swept", {})}
    for r in c5["data"]["region_monthly"]:
        if (r["year"], r["month"]) == (2023, 5): r["harmonized"] += 500.0
    c5["dec"] = decode_cells(c5["data"]["cells"])
    layer_L1(A5, c5, claims)
    row = [r for r in A5.rows if r["id"] == "may23_harm"]
    ok = bool(row) and row[0]["verdict"] == STALE
    caught += bool(ok)
    A.add("L7", "change:anchor semantics", "Change simulation: moved anchor reports STALE "
          "under a changed artifact (not PASS, not a science FAIL)",
          "STALE", row[0]["verdict"] if row else "row missing", PASS if ok else FAIL)
    A.add("L7", "score", "Change-simulation score", "10/10", f"{caught}/10",
          PASS if caught == 10 else FAIL)

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
def write_report(A, root, grid_note, record):
    digest = artifact_md5(root)[:12]
    sci_layers = ["L0", "L1", "L2", "L3", "L4", "L6", "L7"]
    sci_fail = [r for r in A.rows if r["verdict"] == FAIL and r["layer"] in sci_layers]
    pub_fail = [r for r in A.rows if r["verdict"] == FAIL and r["layer"] == "L5"]
    blocked = [r for r in A.rows if r["verdict"] == BLOCKED]
    unver = [r for r in A.rows if r["verdict"] == UNVER]
    stale = [r for r in A.rows if r["verdict"] == STALE and r["layer"] != "LP"]
    passes = [r for r in A.rows if r["verdict"] == PASS]
    numbers_verdict = "FAIL" if sci_fail else ("INCOMPLETE" if blocked else "PASS")
    if record["status"] == "ABORTED":
        numbers_line = "**NUMBERS verdict: NOT EVALUATED** — the audit did not run."
        pub_line = "**PUBLICATION verdict: NOT EVALUATED** — the audit did not run."
    else:
        numbers_line = (f"**NUMBERS verdict: {numbers_verdict}** — {len(passes)} checks passed, "
                        f"{len(sci_fail)} failed, {len(unver)} unverifiable, {len(blocked)} blocked.")
        pub_line = (f"**PUBLICATION verdict: {'FAIL' if pub_fail else 'PASS'}** — "
                    f"{len(pub_fail)} publication findings.")
    lines = ["# Audit Report — independent recomputation of the shipped Canada record",
             "",
             f"Artifact audited: `app/data/monthly.json` (md5 {digest}) — every value in it, per cell and "
             "per month, plus the Canada validation numbers in the claims registry. Engine: "
             "`pipeline/audit_engine.py`, which shares no code with the production pipeline (DuckDB SQL "
             "aggregation over the raw grid; method refit implemented from docs/VALIDATION.md). "
             "Claims and tolerances: `pipeline/audit_claims.json`.",
             f"Grid: {grid_note}",
             f"**RECORD: {record['status']}** — {record['detail']}",
             "",
             numbers_line,
             pub_line,
             ""]
    if stale:
        lines += ["## What changed since the pinned record",
                  "The artifact no longer matches the md5 pinned in the claims registry. "
                  "Anchors below moved; each shows the pinned value and the independent "
                  "recomputation. Invariants, the era rules and the grid refit above are "
                  "unaffected and were enforced in full. After reviewing this table, "
                  "re-pin with `python pipeline/audit_engine.py --pin`.",
                  "",
                  "| Anchor | Pinned | Recomputed |",
                  "|---|---|---|"]
        for r in stale:
            lines.append(f"| {r['claim']} | {str(r['expected']).replace('|', '/')} | "
                         f"{str(r['actual']).replace('|', '/')} |")
        lines += [""]
    lines += ["| Layer | Check | Published / expected | Recomputed | Verdict | Detail |",
              "|---|---|---|---|---|---|"]
    for r in A.rows:
        exp = str(r["expected"]).replace("|", "/")
        act = str(r["actual"]).replace("|", "/")
        det = str(r["detail"]).replace("|", "/")
        lines.append(f"| {r['layer']} | {r['claim']} | {exp} | {act} | {r['verdict']} | {det} |")
    pub_files = sorted({r["id"].split(":", 1)[-1] for r in pub_fail})
    lines += ["", "## Known gaps (stated, not hidden)",
              "- LOYO experiment averages are UNVERIFIABLE from the repo: the result CSVs are gitignored. "
              "The harness code and its hard-coded old-rule baseline expectations are in the repo (verified "
              "by check L5 baseline_expectations, and the Canada pair is numerically reproduced by L4), "
              "but the LOYO outputs themselves are not.",
              "- Terra-only months (Nov 2000 - Jun 2002) have no holdout coverage by design; their "
              "harmonized values rest on the Terra-only ratios alone.",
              "- Canada's untouched-holdout WAPE worsens under the shipped rule (8.8% -> 11.0%, nested check "
              "in docs/VALIDATION.md) even as MAPE improves; both figures belong in any honest summary.",
              "- Anchor values are pinned to one artifact md5 in the claims registry. If the artifact "
              "changes, moved anchors report STALE (never a silent pass) until a human reviews the "
              "recomputation and re-pins with --pin; pinning is refused while any invariant fails."]
    if pub_fail:
        lines.append(f"- Publication findings are open in: {', '.join(pub_files)}. "
                     "They are errors in the project's own text, not in the data.")
    lines += [""]
    _atomic_write(root / "docs/AUDIT_REPORT.md", "\n".join(lines))
    _atomic_write(root / "pipeline/audit_results.json", json.dumps(
        {"artifact_md5": digest, "rows": A.rows}, indent=1, sort_keys=True))
    return sci_fail, pub_fail, blocked

def _atomic_write(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)

def do_pin(A, root, meta, cur_md5):
    """Re-pin anchors to the recomputed values. Refused unless every
    invariant passed: a FAIL outside L5, or any BLOCKED row, stops it."""
    blockers = [r for r in A.rows if r["verdict"] == BLOCKED
                or (r["verdict"] == FAIL and r["layer"] != "L5")]
    if blockers:
        print(f"\nPIN REFUSED: {len(blockers)} invariant/blocked rows are not clean. "
              "Fix the record first; pinning a broken record is not allowed.")
        return False
    rows_by_id = {r["id"]: r for r in A.rows}
    moved, code_moved = [], []
    for c in meta["claims"]:
        r = rows_by_id.get(c["id"])
        if r is None:
            continue
        new = r["actual"]
        if isinstance(new, (int, float)) and isinstance(c["expected"], (int, float)):
            if float(new) == float(c["expected"]):
                continue
        elif str(new) == str(c["expected"]):
            continue
        moved.append((c["id"], c["expected"], new))
        c["expected"] = new
    r = rows_by_id.get("peak_month")
    if r is not None and r["verdict"] == STALE:
        code_moved.append(("peak_month (code anchor in layer_L1)", r["expected"], r["actual"]))
    if not moved and not code_moved and meta.get("pinned_artifact_md5") == cur_md5:
        print("\nPIN: registry already matches the artifact; nothing to do.")
        return True
    meta["pinned_artifact_md5"] = cur_md5
    _atomic_write(root / "pipeline/audit_claims.json",
                  json.dumps(meta, indent=1, sort_keys=True) + "\n")
    print(f"\nPINNED: registry now pins artifact md5 {cur_md5[:12]}")
    for cid, old, new in moved:
        print(f"  anchor {cid}: {old} -> {new}")
    for cid, old, new in code_moved:
        print(f"  anchor {cid}: {old} -> {new}  (update the code anchor if this change is legitimate)")
    print("Review the diff of pipeline/audit_claims.json before committing it.")
    return True

def run_audit(a):
    root = Path(a.root)
    meta = json.loads((root / "pipeline/audit_claims.json").read_text())
    claims = meta["claims"]
    ctx = load_ctx(root)
    cur_md5 = artifact_md5(root)
    pin_md5 = meta.get("pinned_artifact_md5")
    stale_mode = pin_md5 is not None and cur_md5 != pin_md5
    A = Audit(stale_mode=stale_mode, anchor_ids=ANCHOR_IDS)
    if pin_md5 is None:
        A.add("LP", "pin", "Record pin", "pinned_artifact_md5 in registry", "absent", INFO,
              "Registry carries no pin; anchors are enforced as FAIL. Run --pin to adopt pinning.")
        record = {"status": "UNPINNED", "detail": "the registry carries no pinned artifact md5."}
    elif stale_mode:
        A.add("LP", "pin", "Record pin", f"artifact md5 {pin_md5[:12]}",
              f"artifact md5 {cur_md5[:12]}", STALE,
              "Artifact changed since the anchors were pinned. Moved anchors report STALE; "
              "invariants and the grid refit are enforced in full regardless.")
        record = {"status": "STALE",
                  "detail": f"artifact md5 {cur_md5[:12]} differs from the pinned {pin_md5[:12]}. "
                            "See 'What changed since the pinned record' below."}
    else:
        A.add("LP", "pin", "Record pin", f"artifact md5 {pin_md5[:12]}",
              f"artifact md5 {cur_md5[:12]}", PASS, "Artifact matches the pinned record.")
        record = {"status": "CURRENT", "detail": f"artifact md5 {cur_md5[:12]} matches the pinned record."}
    layer_L0(A, ctx, claims); layer_L1(A, ctx, claims); layer_L2(A, ctx, claims); layer_L5(A, ctx, claims)
    if a.selftest:
        try:
            layer_L6(A, ctx, claims)
            layer_L7(A, ctx, claims)
        except Exception as exc:
            A.add("L7", "selftest_crash", "Fault-injection and change simulations completed",
                  "no exception", f"{type(exc).__name__}: {exc}", BLOCKED,
                  "A simulation crashed; the audit itself completed. Fix the simulation.")
    grid = Path(a.grid) if a.grid else root / "data/derived/monthly_grid_025.parquet"
    if grid.exists():
        try:
            st, world = layer_L3(A, ctx, claims, str(grid))
            layer_L4(A, ctx, claims, st, world)
            grid_note = f"`{grid}` present; L3/L4 ran in full."
        except Exception as exc:
            for lid, name in [("L3", "Raw-input recomputation"), ("L4", "Method refit and holdout")]:
                A.add(lid, "blocked", name, "readable grid parquet",
                      f"{type(exc).__name__}: {exc}", BLOCKED,
                      "The grid exists but could not be read; fix its permissions or format and re-run.")
            grid_note = f"`{grid}` present but UNREADABLE; L3/L4 BLOCKED."
    else:
        for lid, name in [("L3", "Raw-input recomputation"), ("L4", "Method refit and holdout")]:
            A.add(lid, "blocked", name, "grid parquet present", f"{grid} not found", BLOCKED,
                  "Place the data-v2 monthly_grid_025.parquet at data/derived/ and re-run.")
        grid_note = f"`{grid}` NOT found; L3/L4 BLOCKED."
    sci_fail, pub_fail, blocked = write_report(A, root, grid_note, record)
    stale_rows = [r for r in A.rows if r["verdict"] == STALE and r["layer"] != "LP"]
    for r in A.rows:
        print(f"{r['layer']:3} {r['verdict']:12} {r['claim']}  [{r['actual']}]  {r['detail']}")
    print(f"\nNUMBERS: {'FAIL' if sci_fail else ('INCOMPLETE' if blocked else 'PASS')} ({len(sci_fail)} failed)  "
          f"PUBLICATION: {'FAIL' if pub_fail else 'PASS'} ({len(pub_fail)} findings)  "
          f"BLOCKED: {len(blocked)}  RECORD: {record['status']}"
          + (f" ({len(stale_rows)} anchors moved)" if stale_rows else ""))
    if a.pin:
        do_pin(A, root, meta, cur_md5)
    code = 1 if sci_fail else (2 if blocked else 0)
    if a.strict and code == 0 and (pub_fail or stale_mode):
        code = 1
    sys.exit(code)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--grid", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--pin", action="store_true",
                    help="after a clean run, re-pin registry anchors to the recomputed values")
    ap.add_argument("--strict", action="store_true",
                    help="also fail (exit 1) on publication findings or a STALE record")
    a = ap.parse_args()
    try:
        run_audit(a)
    except SystemExit:
        raise
    except Exception as exc:
        # Malformed inputs (bad JSON, a deleted claim, an unreadable file)
        # must never surface as a raw traceback or leave the previous
        # run's green report standing. Write an honest ABORTED report.
        root = Path(a.root)
        A = Audit()
        A.add("L0", "inputs", "Audit inputs readable and complete",
              "valid monthly.json and claims registry",
              f"{type(exc).__name__}: {exc}", BLOCKED,
              "The audit could not run. This report replaces the previous one so "
              "stale results are never mistaken for current ones.")
        record = {"status": "ABORTED",
                  "detail": f"the audit did not run: {type(exc).__name__}: {exc}"}
        try:
            write_report(A, root, "not reached; the inputs failed first.", record)
        except Exception:
            pass
        print(f"AUDIT ABORTED: {type(exc).__name__}: {exc}")
        sys.exit(3)

if __name__ == "__main__":
    main()
