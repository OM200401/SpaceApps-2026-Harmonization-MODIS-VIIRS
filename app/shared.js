/* One Burning Calendar: data loading, harmonization display rules and page chrome shared by all pages.
   Exposes window.OBC. The data contract is docs/UI_DATA_CONTRACT.md (app/data/index.json + tiles). */
(function () {
  const MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const MONTH = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const BASE = [2003, 2020];          // baseline years: both MODIS satellites flying all year
  const FIRST_YEAR = 2001;            // first full year shown
  const SNPP_T = 2012 * 12 + 2;       // y*12+m: harmonized values before Feb 2012 are MODIS-based estimates
  const POW = 0.35;                   // colour-scale compression for counts
  const PRESETS = [
    { id: "canada", name: "Canada boreal", bbox: "-140,42,-52,72" },
    { id: "canada-core", name: "Canada core fires", bbox: "-125,49,-60,65" },
    { id: "amazon", name: "Amazon", bbox: "-75,-15,-45,5" },
    { id: "mediterranean", name: "Mediterranean", bbox: "-10,35,30,45" },
    { id: "us-west", name: "US West", bbox: "-125,31,-102,49" },
    { id: "siberia", name: "Siberia", bbox: "90,50,140,70" },
    { id: "southern-africa", name: "Southern Africa", bbox: "12,-20,40,-5" },
    { id: "se-asia", name: "SE Asia", bbox: "92,10,110,25" },
    { id: "n-australia", name: "Northern Australia", bbox: "120,-20,150,-11" },
    { id: "world", name: "Whole world", bbox: "-180,-60,180,80" },
  ];
  const DEFAULT_BBOX = { west: -140, south: 42, east: -52, north: 72 };

  // Cividis (colour-blind safe, perceptually uniform), reversed so low = light and high = dark.
  const CIVIDIS = [[255, 234, 70], [208, 190, 103], [182, 169, 113], [158, 150, 119], [135, 132, 121], [114, 115, 116], [94, 98, 110], [72, 82, 107], [42, 64, 108], [0, 48, 111], [0, 32, 77]];
  function rampRGB(t) { t = Math.min(1, Math.max(0, t)); const x = t * (CIVIDIS.length - 1), i = Math.min(CIVIDIS.length - 2, Math.floor(x)), f = x - i; return CIVIDIS[i].map((v, j) => Math.round(v + (CIVIDIS[i + 1][j] - v) * f)); }
  function ramp(t) { const c = rampRGB(t); return `rgb(${c[0]},${c[1]},${c[2]})`; }
  // Black or white text, whichever has the higher WCAG contrast on a ramp colour (always >= 4.5:1).
  function inkFor(c) { const L = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }), l = 0.2126 * L[0] + 0.7152 * L[1] + 0.0722 * L[2]; return (l + 0.05) / 0.05 >= 1.05 / (l + 0.05) ? "#000" : "#fff"; }

  const fmt = v => Math.round(v).toLocaleString();
  const fmtK = v => v >= 1e6 ? (v / 1e6).toFixed(2) + "M" : v >= 1e4 ? Math.round(v / 1e3) + "k" : v >= 1e3 ? (v / 1e3).toFixed(1) + "k" : String(Math.round(v));
  const ordinal = n => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"));
  const tOf = (y, m) => y * 12 + (m - 1);

  // ---- data ----
  // index.json lists the tiles; areaCells() fetches only the tiles an area needs (see docs/UI_DATA_CONTRACT.md).
  // "d" = 0.25-degree cells in 10-degree tiles, "c" = 1-degree cells in 30-degree tiles.
  const DETAIL_MAX = 700000;          // above this many cell-months an area is shown with 1-degree cells
  const state = { INDEX: null, END: { year: 0, month: 12 }, PROV: null };
  const TILE_CACHE = new Map();
  function decodeCells(c, size) {
    const out = []; let i = 0;
    c.n_months.forEach((n, k) => { for (const end = i + n; i < end; i++) { const t = c.t[i], modis = c.modis_count[i], viirs = c.viirs_count[i]; out.push({ cell_lat: c.cell_lat[k], cell_lon: c.cell_lon[k], size, year: c.t0_year + Math.floor(t / 12), month: t % 12 + 1, modis_count: modis, viirs_count: viirs, total_count: modis + viirs, harmonized_count: c.harmonized_count[i] }); } });
    return out;
  }
  async function loadData() {
    const r = await fetch("data/index.json");
    if (!r.ok) throw new Error("index.json " + r.status);
    const d = await r.json();
    state.INDEX = d; state.END = d.end; state.PROV = d.provisional_from || null;
    return state;
  }
  function tileKeys(lvl, b) {
    const t = state.INDEX.levels[lvl].tile, have = state.INDEX.tiles[lvl], keys = [];
    for (let la = Math.floor(b.south / t) * t; la <= b.north; la += t)
      for (let lo = Math.floor(b.west / t) * t; lo <= b.east; lo += t) { const k = `${la}_${lo}`; if (have[k]) keys.push(k); }
    return keys;
  }
  function fetchTile(lvl, key) {
    const id = lvl + "/" + key;
    if (!TILE_CACHE.has(id)) TILE_CACHE.set(id, fetch(`data/${id}.json`).then(r => { if (!r.ok) throw new Error(id + " " + r.status); return r.json(); })
      .then(c => decodeCells(c, state.INDEX.levels[lvl].cell)).catch(e => { TILE_CACHE.delete(id); throw e; }));
    return TILE_CACHE.get(id);
  }
  // Level an area will use: detail unless its tiles hold more than DETAIL_MAX cell-months.
  const levelFor = b => tileKeys("d", b).reduce((s, k) => s + state.INDEX.tiles.d[k][0], 0) <= DETAIL_MAX ? "d" : "c";
  // Cells for an area. Detail keeps cells whose south-west corner is inside the box (as before); 1-degree
  // cells are kept when the whole cell is inside, so whole-degree areas are exact and others round inward.
  async function areaCells(b) {
    const lvl = levelFor(b), parts = await Promise.all(tileKeys(lvl, b).map(k => fetchTile(lvl, k)));
    const cells = [].concat(...parts);
    const keep = lvl === "d" ? c => c.cell_lon >= b.west && c.cell_lon <= b.east && c.cell_lat >= b.south && c.cell_lat <= b.north
      : c => c.cell_lon >= b.west - 1e-9 && c.cell_lon + 1 <= b.east + 1e-9 && c.cell_lat >= b.south - 1e-9 && c.cell_lat + 1 <= b.north + 1e-9;
    return { cells: cells.filter(keep), level: lvl, cellDeg: state.INDEX.levels[lvl].cell };
  }
  const isPartial = (y, m) => tOf(y, m) > tOf(state.END.year, state.END.month);
  const isProv = (y, m) => !!state.PROV && tOf(y, m) >= tOf(state.PROV.year, state.PROV.month) && !isPartial(y, m);
  const isEst = (y, m) => y * 12 + m < SNPP_T;

  // ---- areas ----
  function parseBBox(text) {
    const p = String(text || "").split(",").map(v => Number(v.trim()));
    if (p.length !== 4 || p.some(v => !Number.isFinite(v))) return null;
    const [west, south, east, north] = p;
    if (west >= east || south >= north || west < -180 || east > 180 || south < -90 || north > 90) return null;
    return { west, south, east, north };
  }
  const formatBBox = b => [b.west, b.south, b.east, b.north].map(v => +(+v).toFixed(4)).join(",");
  const presetFor = b => PRESETS.find(p => p.bbox === formatBBox(b)) || null;
  const areaName = b => { const p = presetFor(b); return p ? p.name : `Custom area (${formatBBox(b)})`; };

  // ---- monthly series for an area ----
  function seriesFor(cells) {
    const byT = new Map();
    cells.forEach(c => { const t = tOf(c.year, c.month); let r = byT.get(t); if (!r) { r = { year: c.year, month: c.month, t, harmonized: 0, total: 0, modis: 0, viirs: 0 }; byT.set(t, r); } r.harmonized += c.harmonized_count; r.total += c.total_count; r.modis += c.modis_count; r.viirs += c.viirs_count; });
    return byT;
  }
  // Harmonized value for a month (0 when no fire was detected; null when the month is not in the record yet).
  const val = (byT, y, m, key = "harmonized") => isPartial(y, m) ? null : (byT.get(tOf(y, m)) || {})[key] || 0;
  function quantile(arr, p) { const s = [...arr].sort((a, b) => a - b); if (!s.length) return 0; const i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return s[lo] + (s[hi] - s[lo]) * (i - lo); }
  const baseYears = () => { const ys = []; for (let y = BASE[0]; y <= BASE[1]; y++) ys.push(y); return ys; };
  function monthStats(byT) {
    const out = {};
    for (let m = 1; m <= 12; m++) { const v = baseYears().map(y => val(byT, y, m)); out[m] = { p10: quantile(v, .1), p50: quantile(v, .5), p90: quantile(v, .9) }; }
    return out;
  }
  function status(ratio) {
    if (ratio == null || !isFinite(ratio)) return { key: "none", label: "No baseline" };
    if (ratio >= 2) return { key: "far", label: "Far above normal" };
    if (ratio >= 1.25) return { key: "above", label: "Above normal" };
    if (ratio > 0.8) return { key: "near", label: "Near normal" };
    return { key: "below", label: "Below normal" };
  }
  // Year-to-date verdict: Jan..upTo of `year` against the median Jan..upTo of the baseline years.
  function verdict(byT, year, upTo, y0, y1) {
    const sum = y => { let s = 0; for (let m = 1; m <= upTo; m++) s += val(byT, y, m) || 0; return s; };
    const sofar = sum(year), typical = quantile(baseYears().map(sum), .5);
    const years = []; for (let y = y0 || FIRST_YEAR; y <= (y1 || state.END.year); y++) if (!isPartial(y, upTo)) years.push({ y, v: sum(y) });
    years.sort((a, b) => b.v - a.v);
    const rank = years.findIndex(o => o.y === year) + 1, ratio = typical > 0 ? sofar / typical : null, st = status(ratio);
    let peak = null; for (let m = 1; m <= upTo; m++) { const v = val(byT, year, m); if (v != null && (!peak || v > peak.v)) peak = { m, v }; }
    const span = upTo === 12 ? "year" : `Jan–${MO[upTo - 1]}`;
    const word = { far: "far above", above: "above", near: "close to", below: "below", none: "without a baseline for" }[st.key];
    const est = isEst(year, upTo) ? " (estimated from MODIS)" : "";
    const sentence = ratio == null ? `No fire was detected here in the ${BASE[0]}–${BASE[1]} baseline, so ${year} can't be compared yet.`
      : `${year}${upTo < 12 ? " so far" : ""} is ${word} normal: ${ratio.toFixed(1)}× a typical ${span === "year" ? "year" : span}${est}${years.length > 1 ? `, the ${rank === 1 ? "" : ordinal(rank) + " "}busiest of ${years.length} years` : ""}.`;
    return { sofar, typical, ratio, rank, nYears: years.length, status: st, peak, span, sentence };
  }
  function describe(byT, med, y, m) {
    const name = `${MO[m - 1]} ${y}`;
    if (isPartial(y, m)) return tOf(y, m) === tOf(state.END.year, state.END.month) + 1 ? `${name}: partial month, not shown.` : `${name}: no data yet.`;
    const r = byT.get(tOf(y, m));
    if (!r) return `${name}: no fire detections in this area.`;
    const parts = [`${name}: ${fmt(r.harmonized)} harmonized detections (S-NPP VIIRS-equivalent)`, `raw ${fmt(r.total)} (MODIS + S-NPP, uncorrected)`];
    if (med && med[m]) parts.push(`${(r.harmonized / med[m]).toFixed(1)}× the ${BASE[0]}–${BASE[1]} ${MO[m - 1]} median`);
    let s = parts.join("; ") + ".";
    if (isEst(y, m)) s += " Estimate: converted from MODIS, because observed S-NPP data begins in Feb 2012.";
    if (isProv(y, m)) s += " Provisional: near-real-time data, may change.";
    return s;
  }

  // ---- URL state: area and month travel between pages ----
  function getState() {
    const q = new URLSearchParams(location.search);
    const bbox = parseBBox(q.get("bbox")) || { ...DEFAULT_BBOX };
    const y = parseInt(q.get("year"), 10), m = parseInt(q.get("month"), 10);
    const f = parseInt(q.get("from"), 10), t = parseInt(q.get("to"), 10);
    return { bbox, year: Number.isFinite(y) ? y : null, month: m >= 1 && m <= 12 ? m : null, from: Number.isFinite(f) ? f : null, to: Number.isFinite(t) ? t : null };
  }
  function setState(s) {
    const q = new URLSearchParams(location.search);
    if (s.bbox) q.set("bbox", formatBBox(s.bbox));
    ["year", "month", "from", "to"].forEach(k => { if (k in s) { if (s[k] == null) q.delete(k); else q.set(k, s[k]); } });
    history.replaceState(null, "", location.pathname + "?" + q.toString());
    updateNavLinks();
  }
  function pageLink(page, extra) { const q = new URLSearchParams(location.search); Object.entries(extra || {}).forEach(([k, v]) => v == null ? q.delete(k) : q.set(k, v)); const s = q.toString(); return page + (s ? "?" + s : ""); }
  function updateNavLinks() { document.querySelectorAll("[data-page-link]").forEach(a => { a.href = pageLink(a.dataset.pageLink); }); }

  // ---- theme: system by default; the header toggle stores an explicit choice (each page sets it early in <head>) ----
  const THEME_KEY = "obc-theme";
  const sysDark = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : { matches: false, addEventListener() {} };
  const isDark = () => { const t = document.documentElement.dataset.theme; return t ? t === "dark" : sysDark.matches; };
  const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  // Colours for canvas charts, which can't read CSS variables themselves.
  const colors = () => ({ ink: cssVar("--ink"), ink2: cssVar("--ink-2"), ink3: cssVar("--ink-3"), grid: cssVar("--grid"), spark: cssVar("--spark"),
    ember: cssVar("--ember"), blue: cssVar("--blue"), blueSoft: cssVar("--blue-soft"), card: cssVar("--card"), cellEmpty: cssVar("--cell-empty"), canvasBg: cssVar("--canvas-bg") });
  function themeChanged() { updateThemeToggle(); document.dispatchEvent(new CustomEvent("obc-theme")); }
  function setTheme(t) { document.documentElement.dataset.theme = t; try { localStorage.setItem(THEME_KEY, t); } catch (e) { } themeChanged(); }
  function updateThemeToggle() {
    const b = document.getElementById("theme-toggle"); if (!b) return;
    const dark = isDark();
    b.innerHTML = dark ? '<span class="ico" aria-hidden="true">☀</span>' : '<span class="ico" aria-hidden="true">☾</span>';
    b.title = dark ? "Light theme" : "Dark theme";
    b.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    b.setAttribute("aria-pressed", String(dark));
  }
  sysDark.addEventListener && sysDark.addEventListener("change", () => { if (!document.documentElement.dataset.theme) themeChanged(); });
  // Charts get the card colour painted behind them, so exported PNGs match the theme instead of being transparent.
  if (window.Chart) Chart.register({ id: "obcBackground", beforeDraw(c) { const x = c.ctx; x.save(); x.globalCompositeOperation = "destination-over"; x.fillStyle = cssVar("--card"); x.fillRect(0, 0, c.width, c.height); x.restore(); } });
  const onTheme = fn => document.addEventListener("obc-theme", fn);

  // ---- chrome ----
  const FLAME = '<svg viewBox="0 0 24 24" fill="#fff" aria-hidden="true"><path d="M12 2c1 3.5-1.5 5-1.5 7.5 0 1.4 1 2.5 2.3 2.5 1.6 0 2.4-1.4 2.2-3 2 1.6 3.5 4 3.5 6.6C18.5 19.5 15.6 22 12 22s-6.5-2.5-6.5-6.4C5.5 10.4 10.6 7.6 12 2z"/></svg>';
  function renderHeader(active) {
    const el = document.getElementById("site-header"); if (!el) return;
    const link = (page, label) => `<a data-page-link="${page}" href="${page}"${active === page ? ' aria-current="page"' : ""}>${label}</a>`;
    el.className = "site-header";
    el.innerHTML = `<div class="wrap"><a class="brand" data-page-link="index.html" href="index.html"><span class="brand-mark">${FLAME}</span>One Burning Calendar</a>
      <nav class="nav" aria-label="Main">${link("index.html", "Map")}${link("report.html", "Calendar")}${link("how-it-works.html", "Method")}</nav>
      <span class="header-meta" id="data-through"></span>
      <button class="theme-toggle" id="theme-toggle" type="button"></button></div>`;
    document.getElementById("theme-toggle").onclick = () => setTheme(isDark() ? "light" : "dark");
    updateThemeToggle(); updateNavLinks();
  }
  function setDataThrough() { const el = document.getElementById("data-through"); if (el && state.END.year) el.textContent = `Data through ${MONTH[state.END.month - 1]} ${state.END.year}`; }
  function renderFooter() {
    const el = document.getElementById("site-footer"); if (!el) return;
    el.className = "site-footer";
    el.innerHTML = `<div class="wrap">NASA FIRMS MODIS C6.1 + VIIRS S-NPP C2 · counts in S-NPP VIIRS units, pre-2012 estimated · Team Murphy, NASA Space Apps 2026
      <span class="no-print">· <a href="https://github.com/OM200401/SpaceApps-2026-Harmonization-MODIS-VIIRS">GitHub</a></span></div>`;
  }
  function presetOptions(selectEl, bbox) {
    const cur = formatBBox(bbox);
    selectEl.innerHTML = PRESETS.map(p => `<option value="${p.bbox}"${p.bbox === cur ? " selected" : ""}>${p.name}</option>`).join("") + (presetFor(bbox) ? "" : `<option value="${cur}" selected>Custom area</option>`);
  }
  function download(name, blob) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
  function downloadCSV(cells, name) {
    const rows = [["cell_lat", "cell_lon", "cell_deg", "year", "month", "modis_count", "viirs_count", "total_count", "harmonized_count", "estimate", "provisional"],
      ...cells.map(c => [c.cell_lat, c.cell_lon, c.size, c.year, c.month, c.modis_count, c.viirs_count, c.total_count, c.harmonized_count, isEst(c.year, c.month) ? 1 : 0, isProv(c.year, c.month) ? 1 : 0])];
    download(name, new Blob([rows.map(r => r.join(",")).join("\n")], { type: "text/csv" }));
  }
  function downloadCanvas(canvas, name) { canvas.toBlob(b => download(name, b), "image/png"); }

  window.OBC = { MO, MONTH, BASE, FIRST_YEAR, SNPP_T, POW, PRESETS, DEFAULT_BBOX, state, rampRGB, ramp, inkFor, fmt, fmtK, ordinal, tOf,
    loadData, areaCells, levelFor, isPartial, isProv, isEst, parseBBox, formatBBox, presetFor, areaName, seriesFor, val, quantile, monthStats,
    status, verdict, describe, getState, setState, pageLink, updateNavLinks, renderHeader, renderFooter, setDataThrough, presetOptions,
    downloadCSV, downloadCanvas, isDark, setTheme, colors, onTheme };
})();
