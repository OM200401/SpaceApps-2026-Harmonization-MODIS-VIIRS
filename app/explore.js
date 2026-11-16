/* Ignis Almanac: the main page.
   The calendar fills the screen (Year and All years views); the Map button swaps it for the map.
   One selection (area, month) drives the calendar, the map and the three key numbers on the left.
   Data helpers live in shared.js (window.OBC). */
(function () {
  const O = window.OBC, $ = id => document.getElementById(id);
  O.renderHeader("index.html", `<select id="preset" aria-label="Area" data-tip="Pick a region. For your own area use Coordinates, or Draw area on the map"></select>
    <details class="menu coords" id="coords"><summary class="btnlike" data-tip="Type your own area as west, south, east, north in degrees">Coordinates</summary><div class="pop panel">
      <input id="bbox" aria-label="Area as west, south, east, north" aria-describedby="bbox-error"><button id="apply">Apply</button>
      <small>West, south, east, north in degrees.</small><span id="bbox-error" class="field-error" role="alert"></span></div></details>
    <details class="menu dl" id="dl"><summary class="btnlike" data-tip="Download hotspot counts for this area as CSV: one row per grid cell and month">↓ Hotspot counts CSV</summary><div class="pop panel" role="group" aria-label="Download hotspot counts as CSV">
      <p>One row per grid cell and month with at least one hotspot: location, MODIS, VIIRS, raw and harmonized counts, estimate and provisional flags.</p>
      <button data-dl="month">Selected month <small id="dl-month"></small></button>
      <button data-dl="year">Selected year <small id="dl-year"></small></button>
      <button data-dl="range">Whole date range <small id="dl-range"></small></button></div></details>`);

  const MODES = ["harmonized", "total", "anomaly"], CVIEWS = ["year", "all"];
  const S0 = O.getState(), Q = S0.q;
  const A = { bbox: S0.bbox, cells: [], cellDeg: .25, level: "d", byT: new Map(), by: new Map(), stats: {}, med: {}, loaded: false, loadId: 0,
    y: null, m: null, mode: MODES.includes(Q.mode) ? Q.mode : "harmonized", cview: CVIEWS.includes(Q.cv) ? Q.cv : "year", view: Q.v === "map" ? "map" : "cal",
    y0: O.FIRST_YEAR, y1: null, ref: 1, timer: null, pendingYear: null };
  const body = $("cal-body"), END = () => O.state.END;
  const endT = () => O.tOf(END().year, END().month);
  const years = () => { const a = []; for (let y = A.y0; y <= A.y1; y++) a.push(y); return a; };
  const selT = () => A.y == null ? null : O.tOf(A.y, A.m);
  const upToFor = y => y === END().year ? END().month : 12;

  // ---- values and colours ----
  function metric(y, m) {
    if (O.isPartial(y, m)) return null;
    const r = A.by.get(O.tOf(y, m)), h = r ? r.harmonized : 0, raw = r ? r.total : 0, med = A.med[m] || 0;
    return { h, raw, modis: r ? r.modis : 0, viirs: r ? r.viirs : 0, v: A.mode === "total" ? raw : h, med, ratio: med > 0 ? h / med : null };
  }
  function scaleMax(ys = years(), ms = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]) { let mx = 0; for (const y of ys) for (const m of ms) { const k = metric(y, m); if (k && k.v > mx) mx = k.v; } return mx; }
  // 0.2x typical -> -1, typical -> 0, 5x typical -> +1 (log scale, so half and double sit the same distance from typical)
  const divT = ratio => Math.max(-1, Math.min(1, Math.log(Math.max(ratio, .04)) / Math.log(5)));
  function fillRGB(k, max) {
    if (!k) return null;
    if (A.mode === "anomaly") return k.ratio == null ? null : O.divRGB(divT(k.ratio));
    return k.v > 0 ? O.rampRGB(Math.pow(k.v / Math.max(max, 1), O.POW)) : null;
  }
  function yearTotal(y) { let v = 0, n = 0; for (let m = 1; m <= 12; m++) { const k = metric(y, m); if (k) { v += k.v; n++; } } return { v, n }; }
  function peakMonth(y) { let b = 1, bv = -1; for (let m = 1; m <= 12; m++) { const k = metric(y, m); if (k && k.h > bv) { bv = k.h; b = m; } } return b; }
  const cellText = k => A.mode === "anomaly" ? (k.ratio == null ? "–" : k.ratio.toFixed(1) + "×") : k.v > 0 ? O.fmtK(k.v) : "·";
  const styleFor = c => c ? ` style="background:rgb(${c});color:${O.inkFor(c)}"` : "";

  // ---- tooltip ----
  const tip = $("tip");
  function showTip(html, x, y) {
    tip.innerHTML = html; tip.hidden = false;
    const r = tip.getBoundingClientRect(); let l = x + 16, t = y + 16;
    if (l + r.width > innerWidth - 8) l = x - r.width - 16;
    if (t + r.height > innerHeight - 8) t = y - r.height - 16;
    tip.style.left = Math.max(8, l) + "px"; tip.style.top = Math.max(8, t) + "px";
  }
  const hideTip = () => { tip.hidden = true; };
  function tipHTML(y, m) {
    const k = metric(y, m), name = `${O.MONTH[m - 1]} ${y}`;
    if (!k) return `<b>${name}</b><span class="tn">Not in the record yet.</span>`;
    const est = O.isEst(y, m), prov = O.isProv(y, m), raw = A.mode === "total";
    let h = `<b>${name}</b><span class="tv">${est && !raw ? "≈ " : ""}${O.fmt(raw ? k.raw : k.h)}</span>${raw ? "raw detections (uncorrected)" : "harmonized detections"}`;
    if (k.ratio != null) h += `<br>${k.ratio.toFixed(1)}× a typical ${O.MONTH[m - 1]} (${O.fmt(k.med)})`;
    h += `<span class="tn">${raw ? `Harmonized: ${O.fmt(k.h)}` : `Raw: ${O.fmt(k.raw)}`} · MODIS ${O.fmt(k.modis)} + VIIRS ${O.fmt(k.viirs)}`;
    if (est) h += `<br>Estimated from MODIS (before VIIRS, Feb 2012)`;
    if (prov) h += `<br>Provisional near-real-time data`;
    return h + "</span>";
  }

  // ---- selection ----
  function setSel(y, m, { keepFocus } = {}) {
    y = Math.max(A.y0, Math.min(A.y1, y)); m = Math.max(1, Math.min(12, m));
    if (O.isPartial(y, m)) { if (y > A.y0) y--; else m = upToFor(y); }   // a month not in the record yet: same month a year earlier
    const yearChanged = y !== A.y;
    A.y = y; A.m = m; O.setState({ year: y, month: m });
    // Year view redraws when the year changes; otherwise only the highlight moves.
    if (A.cview === "year" && yearChanged) renderCal(); else markSel();
    syncNav(); renderVerdict(); renderBrief(); drawMap(); syncDl(); syncMapPick();
    if (keepFocus) { const el = body.querySelector(`.c[data-y="${y}"][data-m="${m}"]`); if (el) el.focus(); }
  }
  function markSel() {
    body.querySelectorAll(".c.sel").forEach(e => { e.classList.remove("sel"); e.tabIndex = -1; });
    body.querySelectorAll(".cur").forEach(e => e.classList.remove("cur"));
    const el = body.querySelector(`.c[data-y="${A.y}"][data-m="${A.m}"]`);
    if (el) { el.classList.add("sel"); el.tabIndex = 0; if (el.parentElement.classList.contains("cal-row")) el.parentElement.classList.add("cur"); }
    const mb = body.querySelector(`.mb[data-mo="${A.m}"]`); if (mb) mb.classList.add("cur");
  }
  const cellAt = ev => { const el = ev.target.closest && ev.target.closest(".c[data-y][data-m]"); return el ? { y: +el.dataset.y, m: +el.dataset.m } : null; };
  body.addEventListener("pointermove", ev => { if (ev.pointerType === "touch") return; const c = cellAt(ev); if (c && !O.isPartial(c.y, c.m)) showTip(tipHTML(c.y, c.m), ev.clientX, ev.clientY); else hideTip(); });
  body.addEventListener("pointerleave", hideTip);
  body.addEventListener("click", ev => {
    const c = cellAt(ev), yt = ev.target.closest("[data-year]");
    if (c && !O.isPartial(c.y, c.m)) { stop(); setSel(c.y, c.m); }
    else if (yt) { stop(); const y = +yt.dataset.year; setSel(y, peakMonth(y)); }
  });
  body.addEventListener("keydown", ev => {
    const mv = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }[ev.key]; if (!mv || A.y == null) return;
    ev.preventDefault(); stop();
    let y = A.y, m = A.m;
    if (A.cview === "all") { y += mv[0]; m += mv[1]; }
    else {
      // Tile views: step through the tiles in reading order, a row at a time for up/down.
      const tiles = [...body.querySelectorAll(".c[data-y]")], cols = getComputedStyle(body.firstElementChild).gridTemplateColumns.split(" ").length;
      const i = tiles.findIndex(e => +e.dataset.y === A.y && +e.dataset.m === A.m), t = tiles[i + mv[1] + mv[0] * cols];
      if (!t) return; y = +t.dataset.y; m = +t.dataset.m;
    }
    if (m < 1 || m > 12 || y < A.y0 || y > A.y1 || O.isPartial(y, m)) return;
    setSel(y, m, { keepFocus: true });
  });

  // ---- calendar ----
  function renderCal() {
    if (!A.loaded) { body.innerHTML = `<p class="muted small">Loading the fire record…</p>`; return; }
    if (A.y == null) return;
    if (A.cview === "all") renderGrid(); else renderYear();
    renderScale(); renderJump(); syncNav();
  }
  const calLabel = () => `Burning activity calendar for ${O.areaName(A.bbox)}, ${A.y0} to ${A.y1}`;
  const flagCls = (k, y, m) => `${!k ? " partial" : ""}${k && O.isProv(y, m) ? " prov" : ""}`;

  // All years: years down, months across, colour only unless "numbers in cells" is on.
  function renderGrid() {
    const ys = years(), max = scaleMax(), tot = ys.map(yearTotal), tmax = Math.max(1, ...tot.map(t => t.v)), medMax = Math.max(1, ...Object.values(A.med)), nums = O.a11y.numbers;
    let h = `<div class="cal" role="grid" aria-label="${calLabel()}. Arrow keys move between months." style="--n:${ys.length}">
      <div class="cal-row cal-head" role="row"><span role="columnheader">Year</span>${O.MO.map((m, j) => `<span role="columnheader" aria-label="${O.MONTH[j]}"><span class="m3">${m}</span><span class="m1">${m[0]}</span></span>`).join("")}<span role="columnheader">${A.mode === "total" ? "Raw total" : "Year total"}</span></div>`;
    ys.forEach((y, i) => {
      const cur = y === A.y;
      h += `<div class="cal-row${y < 2012 && A.mode !== "total" ? " est" : ""}${y === 2012 && i > 0 && A.mode !== "total" ? " snpp" : ""}${cur ? " cur" : ""}" role="row"><span class="yl" role="rowheader">${y}</span>`;
      for (let m = 1; m <= 12; m++) {
        const k = metric(y, m), c = fillRGB(k, max), sel = cur && m === A.m;
        h += `<div role="gridcell" class="c${flagCls(k, y, m)}${sel ? " sel" : ""}" data-y="${y}" data-m="${m}" tabindex="${sel ? 0 : -1}" aria-label="${O.describe(A.by, A.med, y, m)}"${styleFor(c)}>${nums && k ? cellText(k) : ""}</div>`;
      }
      h += `<span class="yt" data-year="${y}" title="${y}: ${O.fmt(tot[i].v)}${tot[i].n < 12 ? ` (${tot[i].n} months)` : ""}"><i style="width:${(tot[i].v / tmax * 46).toFixed(1)}px"></i><b>${O.fmtK(tot[i].v)}</b></span></div>`;
    });
    h += `<div class="cal-row cal-typ" aria-hidden="true"><span class="yl">Typical<br>year</span>${O.MO.map((_, j) => `<span class="mb${j + 1 === A.m ? " cur" : ""}" data-mo="${j + 1}" title="Typical ${O.MONTH[j]}: ${O.fmt(A.med[j + 1] || 0)}"><i style="height:${((A.med[j + 1] || 0) / medMax * 100).toFixed(1)}%"></i></span>`).join("")}<span></span></div></div>`;
    body.innerHTML = h;
  }
  // One tile with its numbers written in, for the Year view.
  function tile(y, m, title, max) {
    const k = metric(y, m), c = fillRGB(k, max), sel = y === A.y && m === A.m, est = O.isEst(y, m) && A.mode !== "total";
    let inner = `<span class="tn">${title}${k && O.isProv(y, m) ? "<em>provisional</em>" : est ? "<em>≈ est.</em>" : ""}</span>`;
    if (!k) inner += `<span class="tr">Not in the record yet</span>`;
    else {
      const st = O.status(k.ratio);
      inner += `<span class="tv">${A.mode === "anomaly" ? cellText(k) : (est ? "≈" : "") + (k.v > 0 ? O.fmt(k.v) : "0")}</span>
        <span class="tr">${A.mode === "anomaly" ? `${O.fmt(k.h)} detections` : k.ratio == null ? "no baseline" : `${k.ratio.toFixed(1)}× typical`}${O.a11y.symbols && k.ratio != null ? ` · ${O.statusText(st)}` : ""}</span>`;
    }
    return `<div role="gridcell" class="c tile${flagCls(k, y, m)}${sel ? " sel" : ""}" data-y="${y}" data-m="${m}" tabindex="${sel ? 0 : -1}" aria-label="${O.describe(A.by, A.med, y, m)}"${styleFor(c)}>${inner}</div>`;
  }
  // Year: the twelve months of the selected year. Colours are scaled on the whole date range, so years compare.
  function renderYear() {
    const max = scaleMax();
    body.innerHTML = `<div class="tiles year" role="grid" aria-label="${O.areaName(A.bbox)}, ${A.y}, month by month. Arrow keys move between months.">${O.MONTH.map((n, j) => tile(A.y, j + 1, n, max)).join("")}</div>`;
  }

  function renderScale() {
    const an = A.mode === "anomaly", max = scaleMax();
    const stops = Array.from({ length: 11 }, (_, i) => an ? `rgb(${O.divRGB(i / 5 - 1)})` : O.ramp(i / 10)).join(",");
    const ticks = an ? ["≤0.2×", "typical", "≥5×"] : [0, .25, .5, .75, 1].map(t => O.fmtK(max * Math.pow(t, 1 / O.POW)));
    const what = an ? "Times a typical month (2003–2020 median)" : A.mode === "total" ? "Raw detections per month" : "Harmonized detections per month";
    $("scale").innerHTML = `<span class="lab">${what}</span><div class="bar"><div class="grad" style="background:linear-gradient(to right,${stops})"></div><div class="ticks">${ticks.map(t => `<span>${t}</span>`).join("")}</div></div>`;
    const keys = [`<span><i></i>${an ? "No baseline" : "No fire detected"}</span>`];
    if (A.cview === "all" && A.y0 < 2012 && A.mode !== "total") keys.push(`<span><i class="k-est"></i>Above the line: estimated from MODIS</span>`);
    if (A.cview !== "all" && A.mode !== "total") keys.push(`<span>≈ estimated from MODIS (before Feb 2012)</span>`);
    if (O.state.PROV && A.y1 >= O.state.PROV.year) keys.push(`<span><i class="k-prov"></i>Provisional</span>`);
    if (A.y1 === END().year && END().month < 12) keys.push(`<span><i class="k-part"></i>Not in the record yet</span>`);
    $("keys").innerHTML = keys.join("");
  }
  function syncNav() {
    const nv = $("navy"); nv.hidden = A.cview === "all"; if (A.y == null) return;
    $("nav-label").textContent = String(A.y);
    $("nav-prev").disabled = A.y <= A.y0;
    $("nav-next").disabled = A.y >= A.y1;
  }
  $("nav-prev").onclick = () => { stop(); setSel(A.y - 1, A.m); };
  $("nav-next").onclick = () => { stop(); setSel(A.y + 1, A.m); };

  // ---- verdict line and the sensor-switch proof ----
  function renderVerdict() {
    $("area-name").textContent = O.areaName(A.bbox);
    if (!A.loaded || A.y == null) return;
    if (!A.cells.length) { $("verdict").textContent = "No vegetation fires were detected in this area since 2000."; return; }
    $("verdict").innerHTML = O.verdict(A.by, A.y, upToFor(A.y), A.y0, A.y1).sentence.replace(/^(\d{4}(?: so far)?)/, "<b>$1</b>");
  }
  function renderJump() {
    const el = $("jump");
    const sum = y => { const o = { raw: 0, h: 0, mo: 0 }; for (let m = 1; m <= 12; m++) { const r = A.by.get(O.tOf(y, m)); if (r) { o.raw += r.total; o.h += r.harmonized; o.mo += r.modis; } } return o; };
    const a = sum(2011), b = sum(2012), pc = (x, y) => { const p = (y / x - 1) * 100; return (p >= 0 ? "+" : "") + p.toFixed(0) + "%"; };
    if (A.cview !== "all" || A.y0 > 2011 || A.y1 < 2012 || !(a.raw > 0 && a.h > 0 && a.mo > 0)) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = A.mode === "total"
      ? `<b>Raw counts jump ${pc(a.raw, b.raw)} from 2011 to 2012.</b> That is the VIIRS satellite arriving, not the fires. Switch to Harmonized to remove it. <a href="${O.pageLink("how-it-works.html")}">How it works</a>`
      : `<b>2011 → 2012: ${pc(a.h, b.h)} harmonized</b>, against ${pc(a.raw, b.raw)} in the raw counts. MODIS alone, one steady instrument, shows ${pc(a.mo, b.mo)}. <a href="${O.pageLink("how-it-works.html")}">How it works</a>`;
  }

  // ---- the three key numbers ----
  function renderBrief() {
    if (!A.loaded || A.y == null) return;
    if (!A.cells.length) { ["q1", "q2", "q3"].forEach(id => $(id).innerHTML = `<p class="line">No fire detections in this area.</p>`); return; }
    renderQ1(); renderQ2(); renderQ3();
  }
  function renderQ1() {
    const y = A.y, m = A.m, k = metric(y, m), st = O.status(k.ratio), s = A.stats[m], W = 250;
    const vals = []; for (let yy = O.FIRST_YEAR; yy <= END().year; yy++) { const kk = metric(yy, m); if (kk) vals.push({ y: yy, v: kk.h }); }
    const mx = Math.max(1, s.p90, ...vals.map(o => o.v)) * 1.03, X = v => 7 + v / mx * (W - 14), xs = X(k.h), xm = X(s.p50);
    const anchor = (x, half = 34) => x < half ? "start" : x > W - half ? "end" : "middle";   // half = half the label width, so it stays inside the chart
    const svg = `<svg viewBox="0 0 ${W} 48" role="img" aria-label="${O.MONTH[m - 1]} in every year since ${O.FIRST_YEAR}: ${y} against the normal range.">
      <line x1="7" x2="${W - 7}" y1="22" y2="22" stroke="var(--line-2)"/>
      <rect x="${X(s.p10).toFixed(1)}" y="14" width="${Math.max(2, X(s.p90) - X(s.p10)).toFixed(1)}" height="16" rx="4" fill="var(--blue-soft)"/>
      <line x1="${xm.toFixed(1)}" x2="${xm.toFixed(1)}" y1="10" y2="34" stroke="var(--blue)" stroke-width="2"/>
      ${vals.filter(o => o.y !== y).map(o => `<circle class="hit" data-y="${o.y}" data-m="${m}" cx="${X(o.v).toFixed(1)}" cy="22" r="4" fill="var(--ink-3)" fill-opacity=".5" stroke="var(--card)" stroke-width="1"/>`).join("")}
      <circle class="dot" cx="${xs.toFixed(1)}" cy="22" r="6"/>
      <text x="${xs.toFixed(1)}" y="8" text-anchor="${anchor(xs)}" style="fill:var(--ink);font-weight:600">${y}</text>
      <text x="${xm.toFixed(1)}" y="46" text-anchor="${anchor(xm, 66)}">normal range · median ${O.fmtK(s.p50)}</text></svg>`;
    const flags = [O.isEst(y, m) && "≈ estimated from MODIS", O.isProv(y, m) && "provisional"].filter(Boolean).join(" · ");
    const p = O.presetFor(A.bbox), acc = p && O.ACCURACY[p.id];
    $("q1").innerHTML = `<div class="hero"><span class="big">${k.ratio == null ? "—" : k.ratio.toFixed(1) + "×"}</span><span class="pill status-${st.key}">${O.statusText(st)}</span></div>
      <p class="line"><b>${O.fmt(k.h)}</b> detections in ${O.MONTH[m - 1]} ${y}${flags ? ` (${flags})` : ""}</p>${svg}
      <p class="acc">${acc ? `Tested error here: ±${acc}% per month` : "Accuracy varies by place"} · <a data-page-link="how-it-works.html" href="${O.pageLink("how-it-works.html")}">how we know</a></p>`;
  }
  function seasonText() {
    const p = []; for (let m = 1; m <= 12; m++) p.push(A.stats[m].p50);
    const tot = p.reduce((a, b) => a + b, 0); if (!(tot > 0)) return "Fire is too rare here for a typical season.";
    let best = -1, bi = 0; for (let i = 0; i < 12; i++) { const s = p[i] + p[(i + 1) % 12] + p[(i + 2) % 12]; if (s > best) { best = s; bi = i; } }
    return `Peaks in <b>${O.MONTH[p.indexOf(Math.max(...p))]}</b>. ${Math.round(best / tot * 100)}% of a typical year burns ${O.MO[bi]}–${O.MO[(bi + 2) % 12]}.`;
  }
  function renderQ2() {
    const p50 = [], yr = []; for (let m = 1; m <= 12; m++) { p50.push(A.stats[m].p50); const k = metric(A.y, m); yr.push(k ? k.h : null); }
    const W = 250, H = 78, base = H - 14, mx = Math.max(1, ...p50, ...yr.filter(v => v != null)), bw = (W - 8) / 12, X = j => 4 + (j + .5) * bw, Y = v => base - v / mx * (base - 8);
    const pts = yr.map((v, j) => v == null ? null : [X(j), Y(v)]).filter(Boolean);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Typical fire by month against ${A.y}.">`;
    p50.forEach((v, j) => { svg += `<rect x="${(4 + j * bw + 2).toFixed(1)}" y="${Y(v).toFixed(1)}" width="${(bw - 4).toFixed(1)}" height="${Math.max(1, base - Y(v)).toFixed(1)}" rx="2" fill="var(--bar)"/><text x="${X(j).toFixed(1)}" y="${H - 2}" text-anchor="middle"${j + 1 === A.m ? ' style="fill:var(--ink);font-weight:600"' : ""}>${O.MO[j][0]}</text>`; });
    svg += `<path d="${pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join("")}" fill="none" stroke="var(--ember)" stroke-width="2" stroke-linejoin="round"/>`;
    pts.forEach((p, j) => { svg += `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${j + 1 === A.m ? 5 : 2.5}" ${j + 1 === A.m ? 'class="dot"' : 'fill="var(--ember)"'}/>`; });
    yr.forEach((v, j) => { if (v != null) svg += `<rect class="hit" data-y="${A.y}" data-m="${j + 1}" x="${(4 + j * bw).toFixed(1)}" y="0" width="${bw.toFixed(1)}" height="${H}" fill="transparent"/>`; });
    $("q2").innerHTML = `<p class="line" style="margin-top:0">${seasonText()}</p>
      <p class="line" style="display:flex;gap:14px;margin-bottom:0"><span><span class="swatch" style="background:var(--bar)"></span> Typical month</span><span><span class="swatch" style="background:var(--ember);height:3px;vertical-align:middle"></span> ${A.y}</span></p>${svg}</svg>`;
  }
  function renderQ3() {
    const mode = A.mode; A.mode = "harmonized";   // rank on the harmonized record whatever the calendar is coloured by
    const list = years().map(y => ({ y, ...yearTotal(y) })).filter(o => o.n).sort((a, b) => b.v - a.v); A.mode = mode;
    const mx = Math.max(1, list.length ? list[0].v : 1), at = list.findIndex(o => o.y === A.y), show = at > 4 ? [...list.slice(0, 4), list[at]] : list.slice(0, 5);
    const row = o => { const rk = list.indexOf(o) + 1; return `${rk === at + 1 && at > 4 ? `<li class="gap" aria-hidden="true">⋮</li>` : ""}<li><button data-year="${o.y}" class="${o.y === A.y ? "cur" : ""}" title="Select ${o.y}"><span class="rk num">${rk}</span><span class="yr num">${o.y}${o.n < 12 ? "*" : ""}</span><span class="tr" style="width:${(o.v / mx * 100).toFixed(1)}%"></span><span class="v num">${O.fmtK(o.v)}</span></button></li>`; };
    $("q3").innerHTML = `<ol class="ranks">${show.map(row).join("")}</ol>${show.some(o => o.n < 12) ? `<p class="acc">* ${END().year} through ${O.MO[END().month - 1]} only</p>` : ""}
      <p class="acc">${A.y0}–${A.y1} · harmonized detections${A.y0 < 2012 ? " · before 2012 estimated" : ""}</p>`;
  }
  const metricsEl = $("metrics");
  metricsEl.addEventListener("click", ev => {
    const hit = ev.target.closest("[data-y][data-m]"), yr = ev.target.closest("[data-year]");
    if (hit) { stop(); setSel(+hit.dataset.y, +hit.dataset.m); } else if (yr) { stop(); const y = +yr.dataset.year; setSel(y, peakMonth(y)); }
  });
  metricsEl.addEventListener("pointermove", ev => { const hit = ev.target.closest("[data-y][data-m]"); if (hit && ev.pointerType !== "touch") showTip(tipHTML(+hit.dataset.y, +hit.dataset.m), ev.clientX, ev.clientY); else hideTip(); });
  metricsEl.addEventListener("pointerleave", hideTip);

  // ---- map: basemap, one canvas of fire cells, place names on top. Built the first time the map is shown. ----
  let MAP = null, FIRE = null, TILES = null, LABELS = null, BOX = null, DRAWING = false, exitDraw = () => {};
  const LUT = { key: null, c: [] };
  function lut() { const d = O.isDark(), key = d + O.a11y.palette; if (LUT.key !== key) { LUT.key = key; LUT.c = Array.from({ length: 48 }, (_, i) => O.ramp((d ? .14 : .26) + (d ? .86 : .74) * i / 47)); } return LUT.c; }
  let TOAST_T = null;
  function toast(msg, ms) { clearTimeout(TOAST_T); $("toast").textContent = msg; if (msg && ms) TOAST_T = setTimeout(() => $("toast").textContent = "", ms); }
  const tileURL = kind => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${O.isDark() ? "Dark" : "Light"}_Gray_${kind}/MapServer/tile/{z}/{y}/{x}`;
  const wide = () => matchMedia("(min-width:1001px)").matches;
  // Leave room on the left for the floating key numbers.
  function fitArea() { if (MAP) MAP.fitBounds([[A.bbox.south, A.bbox.west], [A.bbox.north, A.bbox.east]], wide() ? { paddingTopLeft: [Math.min(360, metricsEl.offsetWidth + 40), 60], paddingBottomRight: [24, 90] } : { padding: [16, 16] }); }
  function syncBox() {
    if (!MAP) return;
    const b = [[A.bbox.south, A.bbox.west], [A.bbox.north, A.bbox.east]], style = { color: O.colors().ink, weight: 1.5, dashArray: "5 4", fill: false, interactive: false };
    if (BOX) { BOX.setBounds(b); BOX.setStyle(style); } else BOX = L.rectangle(b, style).addTo(MAP);
  }
  function drawMap() {
    if (A.y != null) $("map-month").textContent = `${O.MONTH[A.m - 1]} ${A.y}`;
    if (!FIRE || A.view !== "map") return;
    const size = MAP.getSize(), dpr = window.devicePixelRatio || 1;
    if (FIRE.width !== Math.round(size.x * dpr) || FIRE.height !== Math.round(size.y * dpr)) { FIRE.width = Math.round(size.x * dpr); FIRE.height = Math.round(size.y * dpr); FIRE.style.width = size.x + "px"; FIRE.style.height = size.y + "px"; }
    L.DomUtil.setPosition(FIRE, MAP.containerPointToLayerPoint([0, 0]));
    const x = FIRE.getContext("2d"); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, size.x, size.y);
    const list = A.y == null ? [] : A.byT.get(selT()) || []; if (!list.length) return;
    const b = MAP.getBounds(), d = A.cellDeg, w = b.getWest() - d, e = b.getEast(), so = b.getSouth() - d, n = b.getNorth(), C = lut(), key = A.mode === "total" ? "total_count" : "harmonized_count";
    x.globalAlpha = .94;
    for (const c of list) {
      if (c.cell_lon < w || c.cell_lon > e || c.cell_lat < so || c.cell_lat > n) continue;
      const v = c[key]; if (!(v > 0)) continue;
      const p = MAP.latLngToContainerPoint([c.cell_lat + d, c.cell_lon]), q = MAP.latLngToContainerPoint([c.cell_lat, c.cell_lon + d]);
      x.fillStyle = C[Math.min(47, Math.floor(Math.pow(Math.min(1, v / A.ref), .4) * 47.99))];
      x.fillRect(p.x, p.y, Math.max(1.6, q.x - p.x + .4), Math.max(1.6, q.y - p.y + .4));
    }
  }
  function initMap() {
    if (!window.L) { $("map").innerHTML = `<p class="muted small" style="padding:70px 16px 0 380px">The map could not load. The calendar still works: choose an area from the list or with Coordinates.</p>`; return; }
    MAP = L.map("map", { zoomControl: false, worldCopyJump: true, zoomSnap: .25, minZoom: 1.5, maxZoom: 12 });
    L.control.zoom({ position: "bottomright" }).addTo(MAP);
    TILES = L.tileLayer(tileURL("Base"), { maxZoom: 16, attribution: 'Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors' }).addTo(MAP);
    const fp = MAP.createPane("fire"); fp.style.zIndex = 350; fp.style.pointerEvents = "none";
    FIRE = L.DomUtil.create("canvas", "leaflet-zoom-animated", fp);
    const lp = MAP.createPane("labels"); lp.style.zIndex = 650; lp.style.pointerEvents = "none";
    LABELS = L.tileLayer(tileURL("Reference"), { maxZoom: 16, pane: "labels" }).addTo(MAP);
    syncBox(); fitArea();
    MAP.on("move zoomend resize", drawMap);
    // Keep the fire canvas glued to the basemap while a zoom animates (same trick Leaflet's own canvas renderer uses).
    MAP.on("zoomanim", e => L.DomUtil.setTransform(FIRE, MAP._latLngBoundsToNewLayerBounds(MAP.getBounds(), e.zoom, e.center).min, MAP.getZoomScale(e.zoom)));
    // Draw a box with pointer events, so mouse, pen and touch all work. Shift+drag box zoom also selects.
    let start = null, draft = null, upHandled = false; const el = MAP.getContainer();
    exitDraw = cancel => { DRAWING = false; start = null; MAP.dragging.enable(); el.style.cursor = ""; if (draft) { draft.remove(); draft = null; } $("draw").setAttribute("aria-pressed", "false"); $("draw").textContent = "Draw area"; toast(cancel ? "Drawing cancelled." : "", 2500); };
    const ok = b => b.getWest() < b.getEast() && b.getSouth() < b.getNorth();
    const use = b => setArea({ west: Math.max(-180, b.getWest()), south: Math.max(-90, b.getSouth()), east: Math.min(180, b.getEast()), north: Math.min(90, b.getNorth()) }, { fit: false });
    L.DomEvent.on(el, "pointerdown", e => { if (!DRAWING) return; L.DomEvent.stop(e); upHandled = false; start = MAP.mouseEventToLatLng(e); draft = L.rectangle([start, start], { color: O.colors().ember, weight: 2, fillOpacity: .1, interactive: false }).addTo(MAP); });
    L.DomEvent.on(el, "pointermove", e => { if (DRAWING && start && draft) { L.DomEvent.stop(e); draft.setBounds(L.latLngBounds(start, MAP.mouseEventToLatLng(e))); } });
    L.DomEvent.on(el, "pointerup", e => { if (!DRAWING) return; upHandled = true; L.DomEvent.stop(e); if (start) { const b = L.latLngBounds(start, MAP.mouseEventToLatLng(e)); if (ok(b)) use(b); } exitDraw(false); });
    L.DomEvent.on(document, "pointerup", () => { if (DRAWING && start && !upHandled) exitDraw(true); upHandled = false; });
    L.DomEvent.on(document, "keydown", e => { if (DRAWING && e.key === "Escape") exitDraw(true); });
    MAP.on("boxzoomend", e => { if (ok(e.boxZoomBounds)) use(e.boxZoomBounds); });
  }
  $("draw").onclick = () => {
    if (!MAP) return toast("The map isn't available. Use Coordinates instead.", 4000);
    if (DRAWING) return exitDraw(true);
    DRAWING = true; MAP.dragging.disable(); MAP.getContainer().style.cursor = "crosshair";
    $("draw").setAttribute("aria-pressed", "true"); $("draw").textContent = "Cancel";
    toast("Drag on the map to draw an area · Esc cancels");
  };

  // ---- map month and year pickers ----
  function syncMapPick() {
    if (A.y == null || A.y1 == null) return;
    const ys = $("map-y"), ms = $("map-m");
    if (ys.dataset.range !== `${A.y0}-${A.y1}`) { ys.dataset.range = `${A.y0}-${A.y1}`; ys.innerHTML = years().slice().reverse().map(y => `<option value="${y}">${y}${y < 2012 ? " (est.)" : ""}</option>`).join(""); }
    if (!ms.options.length) ms.innerHTML = O.MONTH.map((n, j) => `<option value="${j + 1}">${n}</option>`).join("");
    [...ms.options].forEach(o => o.disabled = O.isPartial(A.y, +o.value));   // months not in the record yet
    ys.value = A.y; ms.value = A.m;
  }
  $("map-y").onchange = e => { stop(); setSel(+e.target.value, A.m); };
  $("map-m").onchange = e => { stop(); setSel(A.y, +e.target.value); };

  // ---- calendar <-> map ----
  function setView(v, { focus } = {}) {
    A.view = v; O.setState({ v: v === "map" ? "map" : null });
    $("work").classList.toggle("view-map", v === "map"); $("work").classList.toggle("view-cal", v !== "map");
    $("calview").hidden = v === "map"; $("mapview").hidden = v !== "map";
    if (v === "map") { if (!MAP) initMap(); else { MAP.invalidateSize(); syncBox(); } drawMap(); if (focus) $("to-cal").focus(); }
    else { stop(); if (DRAWING) exitDraw(false); if (focus) $("to-map").focus(); }
  }
  $("to-map").onclick = () => setView("map", { focus: true });
  $("to-cal").onclick = () => setView("cal", { focus: true });

  // ---- area ----
  function setArea(next, { fit = true } = {}) {
    if (DRAWING) exitDraw(false);
    A.bbox = { west: +(+next.west).toFixed(4), south: +(+next.south).toFixed(4), east: +(+next.east).toFixed(4), north: +(+next.north).toFixed(4) };
    $("bbox").value = O.formatBBox(A.bbox); $("bbox-error").textContent = ""; $("coords").open = false;
    O.presetOptions($("preset"), A.bbox); O.setState({ bbox: A.bbox });
    $("area-name").textContent = O.areaName(A.bbox);
    syncBox(); if (fit) fitArea();
    const id = ++A.loadId, slow = setTimeout(() => { if (id === A.loadId) { toast("Loading fire data for this area…"); $("verdict").textContent = "Loading the fire record…"; } }, 250);
    O.areaCells(A.bbox).then(r => {
      if (id !== A.loadId) return;   // a newer area was chosen while this one loaded
      clearTimeout(slow); toast(r.level === "c" ? "Large area: shown with 1° cells." : "", 3500);
      A.cells = r.cells; A.cellDeg = r.cellDeg; A.level = r.level; A.loaded = true;
      A.byT = new Map(); for (const c of A.cells) { const t = O.tOf(c.year, c.month); let a = A.byT.get(t); if (!a) A.byT.set(t, a = []); a.push(c); }
      A.by = O.seriesFor(A.cells); A.stats = O.monthStats(A.by); A.med = {}; for (let m = 1; m <= 12; m++) A.med[m] = A.stats[m].p50;
      // One colour scale for the whole record of this area (99.9th percentile cell), so quiet months look quiet when played.
      const v = Float32Array.from(A.cells, c => c.harmonized_count).sort(); A.ref = Math.max(1, v.length ? v[Math.floor((v.length - 1) * .999)] : 1);
      $("map-unit").textContent = `More fire per ${A.cellDeg === 1 ? "1°" : "0.25°"} cell`;
      if (A.pendingYear) { A.y = Math.max(A.y0, Math.min(A.y1, A.pendingYear)); A.m = peakMonth(A.y); A.pendingYear = null; O.setState({ year: A.y, month: A.m }); }
      renderAll();
    }).catch(err => { if (id === A.loadId) { clearTimeout(slow); console.error(err); toast("Couldn't load fire data for this area. Try again."); $("verdict").textContent = "Couldn't load fire data for this area. Try again."; } });
  }
  function renderAll() { renderVerdict(); renderCal(); renderBrief(); drawMap(); syncDl(); syncMapPick(); }
  function applyField() { const b = O.parseBBox($("bbox").value); if (!b) { $("bbox-error").textContent = "Enter W,S,E,N as numbers, with W < E and S < N."; return; } setArea(b); }
  $("preset").onchange = e => setArea(O.parseBBox(e.target.value));
  $("apply").onclick = applyField;
  $("bbox").addEventListener("keydown", e => { if (e.key === "Enter") applyField(); });

  // ---- play (map view) and month steps ----
  function stop() { if (!A.timer) return; clearInterval(A.timer); A.timer = null; const p = $("play"); p.setAttribute("aria-pressed", "false"); p.textContent = "▶"; p.setAttribute("aria-label", "Play through months"); }
  const stepMonth = d => { if (A.y == null) return; const t = Math.max(O.tOf(A.y0, 1), Math.min(Math.min(endT(), O.tOf(A.y1, 12)), selT() + d)); setSel(Math.floor(t / 12), t % 12 + 1); };
  $("m-prev").onclick = () => { stop(); stepMonth(-1); };
  $("m-next").onclick = () => { stop(); stepMonth(1); };
  $("play").onclick = () => {
    if (A.timer) return stop();
    if (A.y == null) return;
    const last = Math.min(endT(), O.tOf(A.y1, 12));
    if (selT() >= last) setSel(A.y0, 1);
    const p = $("play"); p.setAttribute("aria-pressed", "true"); p.textContent = "❚❚"; p.setAttribute("aria-label", "Pause");
    A.timer = setInterval(() => { const t = selT() + 1; if (t > last) return stop(); setSel(Math.floor(t / 12), t % 12 + 1); }, 240);
  };

  // ---- calendar view, colour mode, year range ----
  function seg(id, key, attr, urlKey) {
    const el = $(id), sync = () => el.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset[attr] === A[key])));
    el.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; A[key] = b.dataset[attr]; O.setState({ [urlKey]: A[key] }); sync(); renderCal(); if (key === "mode") drawMap(); });
    sync();
  }
  function syncRange() { $("y0").value = A.y0; $("y1").value = A.y1; }
  function rangeChanged() {
    let a = +$("y0").value, b = +$("y1").value; if (a > b) [a, b] = [b, a];
    A.y0 = a; A.y1 = b; syncRange(); stop();
    O.setState({ from: a === O.FIRST_YEAR ? null : a, to: b === END().year ? null : b });
    if (A.y != null) { A.y = Math.max(a, Math.min(b, A.y)); if (O.isPartial(A.y, A.m)) A.m = upToFor(A.y); O.setState({ year: A.y, month: A.m }); }
    renderAll();
  }
  $("y0").onchange = rangeChanged; $("y1").onchange = rangeChanged;

  // ---- hotspot CSV for the current search (area + month, year or date range) ----
  const areaId = () => (O.presetFor(A.bbox) || { id: "custom-area" }).id;
  const DL = {
    month: () => ({ cells: A.cells.filter(c => c.year === A.y && c.month === A.m), tag: `${A.y}-${String(A.m).padStart(2, "0")}` }),
    year: () => ({ cells: A.cells.filter(c => c.year === A.y), tag: String(A.y) }),
    range: () => ({ cells: A.cells.filter(c => c.year >= A.y0 && c.year <= A.y1), tag: `${A.y0}-${A.y1}` }),
  };
  const hot = cs => cs.reduce((n, c) => n + (c.total_count > 0 || c.harmonized_count > 0 ? 1 : 0), 0);
  function syncDl() {
    if (!A.loaded || A.y == null) return;
    $("dl-month").textContent = `${O.MO[A.m - 1]} ${A.y} · ${O.fmt(hot(DL.month().cells))} rows`;
    $("dl-year").textContent = `${A.y} · ${O.fmt(hot(DL.year().cells))} rows`;
    $("dl-range").textContent = `${A.y0}–${A.y1} · ${O.fmt(hot(DL.range().cells))} rows`;
  }
  $("dl").addEventListener("click", e => {
    const b = e.target.closest("[data-dl]"); if (!b || !A.loaded || A.y == null) return;
    const { cells, tag } = DL[b.dataset.dl](); O.downloadCSV(cells, `hotspot-counts-${areaId()}-${tag}.csv`); $("dl").open = false;
  });

  // ---- theme and accessibility settings: recolour everything ----
  function paintLegend() { $("map-grad").style.background = `linear-gradient(to right,${lut().filter((_, i) => i % 8 === 0 || i === 47).join(",")})`; }
  O.onTheme(() => { if (MAP) { TILES.setUrl(tileURL("Base")); LABELS.setUrl(tileURL("Reference")); syncBox(); } paintLegend(); renderAll(); });
  O.onA11y(() => { paintLegend(); renderAll(); });

  // ---- start ----
  if ("cv" in Q && !CVIEWS.includes(Q.cv)) O.setState({ cv: null });   // links from when the calendar had a Month view
  paintLegend(); seg("cview", "cview", "v", "cv"); seg("mode", "mode", "m", "mode"); renderCal();
  O.loadData().then(() => {
    O.setDataThrough();
    const end = END().year, ok = y => y != null && y >= O.FIRST_YEAR && y <= end, opts = Array.from({ length: end - O.FIRST_YEAR + 1 }, (_, i) => `<option>${O.FIRST_YEAR + i}</option>`).join("");
    $("y0").innerHTML = opts; $("y1").innerHTML = opts;
    A.y0 = ok(S0.from) ? S0.from : O.FIRST_YEAR; A.y1 = ok(S0.to) ? S0.to : end; if (A.y0 > A.y1) [A.y0, A.y1] = [A.y1, A.y0];
    A.y = ok(S0.year) ? Math.max(A.y0, Math.min(A.y1, S0.year)) : A.y1;
    A.m = Math.min(S0.month || END().month, upToFor(A.y));
    if (S0.year && !S0.month) A.pendingYear = A.y;   // a link with a year but no month opens on that year's peak month
    syncRange();
    setView(A.view); setArea(A.bbox, { fit: false });
  }).catch(err => { console.error(err); $("verdict").textContent = "Couldn't load the fire data. Try reloading the page."; body.innerHTML = ""; });
})();
