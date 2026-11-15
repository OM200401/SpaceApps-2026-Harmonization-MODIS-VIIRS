/* One Burning Calendar: the explore page.
   One selection (area, month) drives everything: the map, the calendar (grid, ridges or clock) and the briefing cards.
   Hovering a calendar month previews it on the map; clicking selects it. Data helpers live in shared.js (window.OBC). */
(function () {
  const O = window.OBC, $ = id => document.getElementById(id);
  O.renderHeader("index.html", `<select id="preset" aria-label="Area"></select>
    <button id="draw" class="toggle" aria-pressed="false">Draw area</button>
    <details class="coords" id="coords"><summary>Coordinates</summary><div class="pop panel">
      <input id="bbox" aria-label="Area as west, south, east, north" aria-describedby="bbox-error"><button id="apply">Apply</button>
      <small>West, south, east, north in degrees.</small><span id="bbox-error" class="field-error" role="alert"></span></div></details>
    <button id="csv" title="One row per grid cell and month in the chosen years, with estimate and provisional flags">CSV</button>
    <button id="png" title="The calendar as a one-page image">PNG</button>`);

  const VIEWS = ["grid", "ridges", "clock"], MODES = ["harmonized", "total", "anomaly"];
  const STORIES = [{ label: "Canada 2023", preset: "canada", year: 2023 }, { label: "US West 2020", preset: "us-west", year: 2020 },
    { label: "Siberia 2021", preset: "siberia", year: 2021 }, { label: "Amazon 2007", preset: "amazon", year: 2007 }, { label: "Whole world", preset: "world", year: null }];
  const S0 = O.getState(), Q = S0.q;
  const A = { bbox: S0.bbox, cells: [], cellDeg: .25, level: "d", byT: new Map(), by: new Map(), stats: {}, med: {}, loaded: false, loadId: 0,
    y: null, m: null, hover: null, mode: MODES.includes(Q.mode) ? Q.mode : "harmonized", view: VIEWS.includes(Q.view) ? Q.view : "grid",
    y0: O.FIRST_YEAR, y1: null, ref: 1, timer: null, pendingYear: null, geo: null };
  const body = $("cal-body"), END = () => O.state.END;
  const endT = () => O.tOf(END().year, END().month);
  const years = () => { const a = []; for (let y = A.y0; y <= A.y1; y++) a.push(y); return a; };
  const selT = () => A.y == null ? null : O.tOf(A.y, A.m);
  const shown = () => A.hover || (A.y == null ? null : { y: A.y, m: A.m });

  // ---- values and colours ----
  function metric(y, m) {
    if (O.isPartial(y, m)) return null;
    const r = A.by.get(O.tOf(y, m)), h = r ? r.harmonized : 0, raw = r ? r.total : 0, med = A.med[m] || 0;
    return { h, raw, modis: r ? r.modis : 0, viirs: r ? r.viirs : 0, v: A.mode === "total" ? raw : h, med, ratio: med > 0 ? h / med : null };
  }
  function scaleMax() { let mx = 0; for (const y of years()) for (let m = 1; m <= 12; m++) { const k = metric(y, m); if (k && k.v > mx) mx = k.v; } return mx; }
  // 0.2x typical -> -1, typical -> 0, 5x typical -> +1 (log scale, so half and double sit the same distance from typical)
  const divT = ratio => Math.max(-1, Math.min(1, Math.log(Math.max(ratio, .04)) / Math.log(5)));
  function fillRGB(k, max, dark) {
    if (!k) return null;
    if (A.mode === "anomaly") return k.ratio == null ? null : O.divRGB(divT(k.ratio), dark);
    return k.v > 0 ? O.rampRGB(Math.pow(k.v / Math.max(max, 1), O.POW), dark) : null;
  }
  function yearTotal(y) { let v = 0, n = 0; for (let m = 1; m <= 12; m++) { const k = metric(y, m); if (k) { v += k.v; n++; } } return { v, n }; }
  function peakMonth(y) { let b = 1, bv = -1; for (let m = 1; m <= 12; m++) { const k = metric(y, m); if (k && k.h > bv) { bv = k.h; b = m; } } return b; }
  const upToFor = y => y === END().year ? END().month : 12;

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

  // ---- selection and hover ----
  function setSel(y, m) {
    y = Math.max(A.y0, Math.min(A.y1, y)); m = Math.max(1, Math.min(upToFor(y), m));
    A.y = y; A.m = m; O.setState({ year: y, month: m });
    markSel(); renderVerdict(); renderBrief(); drawMap();
  }
  function setHover(h, ev) {
    const same = (!h && !A.hover) || (h && A.hover && h.y === A.hover.y && h.m === A.hover.m);
    A.hover = h;
    if (h && ev) showTip(tipHTML(h.y, h.m), ev.clientX, ev.clientY); else hideTip();
    if (!same) { drawMap(); if (A.view === "clock") clockCentre(); }
  }
  function markSel() {
    if (A.view !== "grid") return renderCal();
    body.querySelectorAll(".c.sel").forEach(e => { e.classList.remove("sel"); e.tabIndex = -1; });
    body.querySelectorAll(".cur").forEach(e => e.classList.remove("cur"));
    const el = body.querySelector(`.c[data-y="${A.y}"][data-m="${A.m}"]`);
    if (el) { el.classList.add("sel"); el.tabIndex = 0; el.parentElement.classList.add("cur"); }
    const mb = body.querySelector(`.mb[data-mo="${A.m}"]`); if (mb) mb.classList.add("cur");
  }
  // Which month is under the pointer. Grid and clock cells carry data-y / data-m; ridges are picked by geometry,
  // front ridge first, so pointing at a tall peak selects that year and not the one it overlaps.
  function cellAt(ev) {
    const el = ev.target.closest && ev.target.closest("[data-y][data-m]");
    if (el) return { y: +el.dataset.y, m: +el.dataset.m };
    if (A.view !== "ridges" || !A.geo) return null;
    const r = body.getBoundingClientRect(), g = A.geo, x = ev.clientX - r.left, yy = ev.clientY - r.top, ys = years();
    const m = Math.floor((x - g.padL) / g.colW) + 1; if (m < 1 || m > 12) return null;
    const fx = (x - g.padL) / g.colW - .5;
    for (let i = ys.length - 1; i >= 0; i--) {
      const base = g.top + (i + 1) * g.rowH, row = g.ys[i]; if (yy > base || !row.length) continue;
      const a = Math.max(0, Math.min(row.length - 1, Math.floor(fx))), b = Math.min(row.length - 1, a + 1), f = Math.max(0, Math.min(1, fx - a));
      if (yy >= row[a] + (row[b] - row[a]) * f) return { y: ys[i], m };
    }
    return { y: ys[Math.max(0, Math.min(ys.length - 1, Math.ceil((yy - g.top) / g.rowH - 1)))], m };
  }
  body.addEventListener("pointermove", ev => { if (ev.pointerType === "touch") return; const c = cellAt(ev); setHover(c && !O.isPartial(c.y, c.m) ? c : null, ev); });
  body.addEventListener("pointerleave", () => setHover(null));
  body.addEventListener("click", ev => {
    const c = cellAt(ev), yt = ev.target.closest("[data-year]");
    if (c && !O.isPartial(c.y, c.m)) { stop(); setSel(c.y, c.m); }
    else if (yt) { stop(); const y = +yt.dataset.year; setSel(y, peakMonth(y)); }
  });
  body.addEventListener("focusin", ev => {
    const el = ev.target.closest(".c[data-y]"); if (!el || el.classList.contains("partial")) return;
    const y = +el.dataset.y, m = +el.dataset.m; if (y !== A.y || m !== A.m) setSel(y, m);
  });
  body.addEventListener("keydown", ev => {
    const mv = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }[ev.key]; if (!mv || A.y == null) return;
    ev.preventDefault(); stop();
    const y = A.y + mv[0], m = A.m + mv[1]; if (m < 1 || m > 12 || y < A.y0 || y > A.y1 || O.isPartial(y, m)) return;
    setSel(y, m);
    if (A.view === "grid") { const el = body.querySelector(`.c[data-y="${y}"][data-m="${m}"]`); if (el) el.focus(); }
  });

  // ---- calendar: three shapes of the same year-by-month record ----
  function renderCal() {
    body.className = "v-" + A.view; body.tabIndex = A.view === "grid" ? -1 : 0;
    if (!A.loaded) { body.innerHTML = `<p class="muted small">Loading the fire record…</p>`; return; }
    ({ grid: renderGrid, ridges: renderRidges, clock: renderClock })[A.view]();
    renderScale();
  }
  const calLabel = () => `Burning activity calendar for ${O.areaName(A.bbox)}, ${A.y0} to ${A.y1}`;

  function renderGrid() {
    const ys = years(), max = scaleMax(), tot = ys.map(yearTotal), tmax = Math.max(1, ...tot.map(t => t.v));
    const medMax = Math.max(1, ...Object.values(A.med));
    let h = `<div class="cal" role="grid" aria-label="${calLabel()}. Arrow keys move between months." style="--n:${ys.length}">
      <div class="cal-row cal-head" role="row"><span role="columnheader">Year</span>${O.MO.map((m, j) => `<span role="columnheader" aria-label="${O.MONTH[j]}"><span class="m3">${m}</span><span class="m1">${m[0]}</span></span>`).join("")}<span role="columnheader">${A.mode === "total" ? "Raw total" : "Year total"}</span></div>`;
    ys.forEach((y, i) => {
      const cur = y === A.y;
      h += `<div class="cal-row${y < 2012 && A.mode !== "total" ? " est" : ""}${y === 2012 && i > 0 && A.mode !== "total" ? " snpp" : ""}${cur ? " cur" : ""}" role="row"><span class="yl" role="rowheader">${y}</span>`;
      for (let m = 1; m <= 12; m++) {
        const k = metric(y, m), c = fillRGB(k, max), sel = cur && m === A.m;
        h += `<div role="gridcell" class="c${!k ? " partial" : ""}${k && O.isProv(y, m) ? " prov" : ""}${sel ? " sel" : ""}" data-y="${y}" data-m="${m}" tabindex="${sel ? 0 : -1}" aria-label="${O.describe(A.by, A.med, y, m)}"${c ? ` style="background:rgb(${c})"` : ""}></div>`;
      }
      h += `<span class="yt" data-year="${y}" title="${y}: ${O.fmt(tot[i].v)}${tot[i].n < 12 ? ` (${tot[i].n} months)` : ""}"><i style="width:${(tot[i].v / tmax * 46).toFixed(1)}px"></i><b>${O.fmtK(tot[i].v)}</b></span></div>`;
    });
    h += `<div class="cal-row cal-typ" aria-hidden="true"><span class="yl">Typical<br>year</span>${O.MO.map((_, j) => `<span class="mb${j + 1 === A.m ? " cur" : ""}" data-mo="${j + 1}" title="Typical ${O.MONTH[j]}: ${O.fmt(A.med[j + 1] || 0)}"><i style="height:${((A.med[j + 1] || 0) / medMax * 100).toFixed(1)}%"></i></span>`).join("")}<span></span></div></div>`;
    body.innerHTML = h;
  }

  // Monotone cubic through the points: smooth, but never overshoots below a neighbour (so no ridge dips under its baseline).
  function smooth(p) {
    const n = p.length, f = v => v.toFixed(1); if (!n) return "";
    let d = `M${f(p[0][0])},${f(p[0][1])}`;
    if (n < 3) { for (let i = 1; i < n; i++) d += `L${f(p[i][0])},${f(p[i][1])}`; return d; }
    const s = [], t = []; for (let i = 0; i < n - 1; i++) s.push((p[i + 1][1] - p[i][1]) / (p[i + 1][0] - p[i][0] || 1));
    t[0] = s[0]; t[n - 1] = s[n - 2]; for (let i = 1; i < n - 1; i++) t[i] = s[i - 1] * s[i] <= 0 ? 0 : 2 * s[i - 1] * s[i] / (s[i - 1] + s[i]);
    for (let i = 0; i < n - 1; i++) { const dx = (p[i + 1][0] - p[i][0]) / 3; d += `C${f(p[i][0] + dx)},${f(p[i][1] + t[i] * dx)} ${f(p[i + 1][0] - dx)},${f(p[i + 1][1] - t[i + 1] * dx)} ${f(p[i + 1][0])},${f(p[i + 1][1])}`; }
    return d;
  }
  function renderRidges() {
    const W = Math.max(body.clientWidth, 280), H = Math.max(body.clientHeight, 300), ys = years(), n = ys.length, padL = 38, padR = 6, padT = 6, padB = 20;
    const OV = Math.min(5, Math.max(1.6, n / 5));   // the busiest month rises this many rows
    const rows = ys.map(y => { const v = []; for (let m = 1; m <= 12; m++) { const k = metric(y, m); if (!k) break; v.push(k.v); } return v; });
    const max = Math.max(1, ...rows.map(v => Math.max(0, ...v)));
    let hr = .3; rows.forEach((v, i) => { hr = Math.max(hr, Math.max(0, ...v) / max * OV - i - 1); });   // head-room rows above the first year
    const rowH = (H - padT - padB) / (n + hr), top = padT + hr * rowH, colW = (W - padL - padR) / 12, X = j => padL + (j + .5) * colW;
    const tot = ys.map(yearTotal), tmax = Math.max(1, ...tot.map(t => t.v)), every = rowH < 10 ? 5 : rowH < 13 ? 2 : 1;
    let h = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${calLabel()}, one ridge per year. Arrow keys move between months; the Grid view reads out every month.">`, dot = "";
    O.MO.forEach((mo, j) => { h += `<text x="${X(j).toFixed(1)}" y="${H - 5}" text-anchor="middle">${mo}</text>`; });
    if (A.y != null) h += `<line class="guide" x1="${X(A.m - 1).toFixed(1)}" x2="${X(A.m - 1).toFixed(1)}" y1="${padT}" y2="${H - padB}"/>`;
    const geoYs = [];
    ys.forEach((y, i) => {
      const v = rows[i], base = top + (i + 1) * rowH, pts = v.map((val, j) => [X(j), base - val / max * OV * rowH]);
      geoYs.push(pts.map(p => p[1]));
      const cur = y === A.y, lab = cur || i === 0 || i === n - 1 || y % every === 0;
      h += `<g class="ridge${y < 2012 && A.mode !== "total" ? " est" : ""}${cur ? " cur" : ""}">`;
      if (pts.length) {
        const right = pts[pts.length - 1][0] + colW / 2, line = smooth([[padL, pts[0][1]], ...pts, [right, pts[pts.length - 1][1]]]);
        const area = `M${padL},${base.toFixed(1)}L${line.slice(1)}L${right.toFixed(1)},${base.toFixed(1)}Z`;
        const c = A.mode === "anomaly" ? (() => { const r = O.verdict(A.by, y, upToFor(y)).ratio; return r == null ? null : O.divRGB(divT(r)); })() : tot[i].v > 0 ? O.rampRGB(Math.pow(tot[i].v / tmax, .6)) : null;
        h += `<path d="${area}" fill="var(--card)"/><path class="area" d="${area}" fill="${c ? `rgb(${c})` : "var(--cell-empty)"}" fill-opacity=".9"/><path class="line" d="${line}"/>`;
        if (cur && pts[A.m - 1]) dot = `<circle class="dot" cx="${pts[A.m - 1][0].toFixed(1)}" cy="${pts[A.m - 1][1].toFixed(1)}" r="5"/>`;
      }
      if (lab) h += `<text x="${padL - 6}" y="${(base - 2).toFixed(1)}" text-anchor="end">${y}</text>`;
      h += `</g>`;
    });
    body.innerHTML = h + dot + `</svg>`;
    A.geo = { padL, colW, top, rowH, ys: geoYs };
  }

  function renderClock() {
    const ys = years(), n = ys.length, R1 = 226, R0 = n > 14 ? 80 : 104, th = (R1 - R0) / n, max = scaleMax(), gap = th > 5 ? .8 : .3;
    const P = (r, a) => `${(r * Math.cos(a * Math.PI / 180)).toFixed(1)},${(r * Math.sin(a * Math.PI / 180)).toFixed(1)}`;
    let h = `<svg class="clock" viewBox="-262 -262 524 524" role="img" aria-label="${calLabel()}, as a clock: months go round, years go outward. Arrow keys move between months; the Grid view reads out every month.">`, selPath = "";
    ys.forEach((y, i) => {
      const ri = R0 + i * th, ro = ri + th - gap;
      for (let m = 1; m <= 12; m++) {
        const a0 = (m - 1) * 30 - 90 + .6, a1 = m * 30 - 90 - .6, k = metric(y, m), c = fillRGB(k, max), sel = y === A.y && m === A.m;
        const p = `<path d="M${P(ro, a0)}A${ro.toFixed(1)},${ro.toFixed(1)} 0 0 1 ${P(ro, a1)}L${P(ri, a1)}A${ri.toFixed(1)},${ri.toFixed(1)} 0 0 0 ${P(ri, a0)}Z" data-y="${y}" data-m="${m}" class="${!k ? "partial" : !c ? "none" : ""}${sel ? " sel" : ""}"${c ? ` fill="rgb(${c})"` : ""}/>`;
        if (sel) selPath = p; else h += p;
      }
    });
    h += selPath;
    if (A.y0 < 2012 && A.y1 >= 2012 && A.mode !== "total") h += `<circle class="guide" r="${(R0 + (2012 - A.y0) * th - gap / 2).toFixed(1)}" fill="none" pointer-events="none"/>`;
    O.MO.forEach((mo, j) => { h += `<text x="${P(R1 + 16, (j + .5) * 30 - 90).split(",")[0]}" y="${P(R1 + 16, (j + .5) * 30 - 90).split(",")[1]}" text-anchor="middle" dominant-baseline="central">${mo}</text>`; });
    const step = n > 18 ? 5 : n > 8 ? 2 : 1;
    ys.forEach((y, i) => { if (i === 0 || i === n - 1 || (y % step === 0 && i > 1 && i < n - 2)) h += `<text class="halo" x="0" y="${(-(R0 + i * th + th / 2)).toFixed(1)}" text-anchor="middle" dominant-baseline="central" pointer-events="none" style="fill:var(--ink)">${y}</text>`; });
    body.innerHTML = h + `<g id="clock-c"></g></svg>`;
    clockCentre();
  }
  function clockCentre() {
    const g = document.getElementById("clock-c"), s = shown(); if (!g || !s) return;
    const k = metric(s.y, s.m), ratio = k && A.mode !== "total" && k.ratio != null;
    g.innerHTML = `<text class="c-mo" y="-24" text-anchor="middle">${O.MO[s.m - 1]} ${s.y}</text>
      <text class="c-big" y="8" text-anchor="middle">${!k ? "—" : ratio ? k.ratio.toFixed(1) + "×" : O.fmtK(k.v)}</text>
      <text class="c-sub" y="27" text-anchor="middle">${!k ? "" : ratio ? "a typical " + O.MO[s.m - 1] : A.mode === "total" ? "raw detections" : "detections"}</text>
      <text class="c-sub" y="41" text-anchor="middle">${k && ratio ? O.fmtK(k.h) + " detections" : ""}</text>`;
  }

  function renderScale() {
    const max = scaleMax(), an = A.mode === "anomaly";
    const stops = Array.from({ length: 11 }, (_, i) => an ? `rgb(${O.divRGB(i / 5 - 1)})` : O.ramp(i / 10)).join(",");
    const ticks = an ? ["≤0.2×", "typical", "≥5×"] : [0, .25, .5, .75, 1].map(t => O.fmtK(max * Math.pow(t, 1 / O.POW)));
    const what = an ? "Times a typical month (2003–2020 median)" : A.mode === "total" ? "Raw detections per month" : "Harmonized detections per month";
    $("scale").innerHTML = `<span class="lab">${A.view === "ridges" ? "Ridge height = detections; colour = " + (an ? "year vs typical" : "year total") : what}</span><div class="bar"><div class="grad" style="background:linear-gradient(to right,${stops})"></div><div class="ticks">${(A.view === "ridges" && !an ? ["quiet year", "busiest year"] : ticks).map(t => `<span>${t}</span>`).join("")}</div></div>`;
    const keys = [];
    if (A.view !== "ridges") keys.push(`<span><i></i>${an ? "No baseline" : "No fire detected"}</span>`);
    if (A.y0 < 2012 && A.mode !== "total") keys.push(`<span><i class="k-est"></i>${{ grid: "Above the line", ridges: "Dashed outline", clock: "Inside the dashed ring" }[A.view]}: estimated from MODIS</span>`);
    if (A.view === "grid" && O.state.PROV && A.y1 >= O.state.PROV.year) keys.push(`<span><i class="k-prov"></i>Provisional</span>`);
    if (A.view !== "ridges" && A.y1 === END().year && END().month < 12) keys.push(`<span><i class="k-part"></i>Not in the record yet</span>`);
    $("keys").innerHTML = keys.join("");
  }

  // ---- verdict line and the sensor-switch proof ----
  function renderVerdict() {
    $("area-name").textContent = O.areaName(A.bbox);
    if (!A.loaded || A.y == null) return;
    if (!A.cells.length) { $("verdict").textContent = "No vegetation fires were detected in this area since 2000."; return; }
    $("verdict").innerHTML = O.verdict(A.by, A.y, upToFor(A.y)).sentence.replace(/^(\d{4}(?: so far)?)/, "<b>$1</b>");
  }
  function renderJump() {
    const sum = y => { const o = { raw: 0, h: 0, mo: 0 }; for (let m = 1; m <= 12; m++) { const r = A.by.get(O.tOf(y, m)); if (r) { o.raw += r.total; o.h += r.harmonized; o.mo += r.modis; } } return o; };
    const a = sum(2011), b = sum(2012), el = $("jump"), pc = (x, y) => { const p = (y / x - 1) * 100; return (p >= 0 ? "+" : "") + p.toFixed(0) + "%"; };
    if (!(a.raw > 0 && a.h > 0 && a.mo > 0)) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = A.mode === "total"
      ? `<b>Raw counts jump ${pc(a.raw, b.raw)} from 2011 to 2012.</b> That is the VIIRS satellite arriving, not the fires. Switch to Harmonized to remove it. <a href="${O.pageLink("how-it-works.html")}">How it works</a>`
      : `<b>2011 → 2012: ${pc(a.h, b.h)} harmonized</b>, against ${pc(a.raw, b.raw)} in the raw counts. MODIS alone, one steady instrument, shows ${pc(a.mo, b.mo)}. <a href="${O.pageLink("how-it-works.html")}">How it works</a>`;
  }

  // ---- briefing cards ----
  function renderBrief() {
    if (!A.loaded || A.y == null) return;
    if (!A.cells.length) { ["q1", "q2", "q3"].forEach(id => $(id).innerHTML = `<p class="line">No fire detections in this area.</p>`); return; }
    renderQ1(); renderQ2(); renderQ3();
  }
  function renderQ1() {
    const y = A.y, m = A.m, k = metric(y, m), st = O.status(k.ratio), s = A.stats[m], W = 250;
    const vals = []; for (let yy = O.FIRST_YEAR; yy <= END().year; yy++) { const kk = metric(yy, m); if (kk) vals.push({ y: yy, v: kk.h }); }
    const mx = Math.max(1, s.p90, ...vals.map(o => o.v)) * 1.03, X = v => 7 + v / mx * (W - 14), xs = X(k.h), xm = X(s.p50);
    const anchor = x => x < 34 ? "start" : x > W - 34 ? "end" : "middle";
    const svg = `<svg viewBox="0 0 ${W} 48" role="img" aria-label="${O.MONTH[m - 1]} in every year since ${O.FIRST_YEAR}: ${y} against the normal range.">
      <line x1="7" x2="${W - 7}" y1="22" y2="22" stroke="var(--line-2)"/>
      <rect x="${X(s.p10).toFixed(1)}" y="14" width="${Math.max(2, X(s.p90) - X(s.p10)).toFixed(1)}" height="16" rx="4" fill="var(--blue-soft)"/>
      <line x1="${xm.toFixed(1)}" x2="${xm.toFixed(1)}" y1="10" y2="34" stroke="var(--blue)" stroke-width="2"/>
      ${vals.filter(o => o.y !== y).map(o => `<circle class="hit" data-y="${o.y}" data-m="${m}" cx="${X(o.v).toFixed(1)}" cy="22" r="4" fill="var(--ink-3)" fill-opacity=".5" stroke="var(--card)" stroke-width="1"/>`).join("")}
      <circle class="dot" cx="${xs.toFixed(1)}" cy="22" r="6"/>
      <text x="${xs.toFixed(1)}" y="8" text-anchor="${anchor(xs)}" style="fill:var(--ink);font-weight:600">${y}</text>
      <text x="${xm.toFixed(1)}" y="46" text-anchor="${anchor(xm)}">normal range · median ${O.fmtK(s.p50)}</text></svg>`;
    const flags = [O.isEst(y, m) && "≈ estimated from MODIS", O.isProv(y, m) && "provisional"].filter(Boolean).join(" · ");
    const p = O.presetFor(A.bbox), acc = p && O.ACCURACY[p.id];
    $("q1").innerHTML = `<div class="hero"><span class="big">${k.ratio == null ? "—" : k.ratio.toFixed(1) + "×"}</span><span class="pill status-${st.key}">${st.label}</span></div>
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
      <p class="line" style="display:flex;gap:14px;margin-bottom:6px"><span><span class="swatch" style="background:var(--bar)"></span> Typical month</span><span><span class="swatch" style="background:var(--ember);height:3px;vertical-align:middle"></span> ${A.y}</span></p>${svg}</svg>`;
  }
  function renderQ3() {
    const mode = A.mode; A.mode = "harmonized";   // rank on the harmonized record whatever the calendar is coloured by
    const list = years().map(y => ({ y, ...yearTotal(y) })).filter(o => o.n).sort((a, b) => b.v - a.v); A.mode = mode;
    const mx = Math.max(1, list.length ? list[0].v : 1), at = list.findIndex(o => o.y === A.y), show = at > 4 ? [...list.slice(0, 4), list[at]] : list.slice(0, 5);
    const row = o => { const rk = list.indexOf(o) + 1; return `${rk === at + 1 && at > 4 ? `<li class="gap" aria-hidden="true">⋮</li>` : ""}<li><button data-year="${o.y}" class="${o.y === A.y ? "cur" : ""}" title="Select ${o.y}"><span class="rk num">${rk}</span><span class="yr num">${o.y}${o.n < 12 ? "*" : ""}</span><span class="tr" style="width:${(o.v / mx * 100).toFixed(1)}%"></span><span class="v num">${O.fmtK(o.v)}</span></button></li>`; };
    $("q3").innerHTML = `<ol class="ranks">${show.map(row).join("")}</ol>${show.some(o => o.n < 12) ? `<p class="acc">* ${END().year} through ${O.MO[END().month - 1]} only</p>` : ""}
      <p class="acc">${A.y0}–${A.y1} · harmonized detections${A.y0 < 2012 ? " · before 2012 estimated" : ""}</p>`;
  }
  document.querySelector(".brief").addEventListener("click", ev => {
    const hit = ev.target.closest("[data-y][data-m]"), yr = ev.target.closest("[data-year]");
    if (hit) { stop(); setSel(+hit.dataset.y, +hit.dataset.m); } else if (yr) { stop(); const y = +yr.dataset.year; setSel(y, peakMonth(y)); }
  });
  document.querySelector(".brief").addEventListener("pointermove", ev => { const hit = ev.target.closest("[data-y][data-m]"); if (hit && ev.pointerType !== "touch") showTip(tipHTML(+hit.dataset.y, +hit.dataset.m), ev.clientX, ev.clientY); else hideTip(); });
  document.querySelector(".brief").addEventListener("pointerleave", hideTip);

  // ---- map: basemap, one canvas of fire cells, place names on top ----
  let MAP = null, FIRE = null, TILES = null, LABELS = null, BOX = null, DRAWING = false, exitDraw = () => {};
  const LUT = { dark: null, c: [] };
  function lut() { const d = O.isDark(); if (LUT.dark !== d) { LUT.dark = d; LUT.c = Array.from({ length: 48 }, (_, i) => O.ramp((d ? .14 : .26) + (d ? .86 : .74) * i / 47)); } return LUT.c; }
  let TOAST_T = null;
  function toast(msg, ms) { clearTimeout(TOAST_T); $("toast").textContent = msg; if (msg && ms) TOAST_T = setTimeout(() => $("toast").textContent = "", ms); }
  const tileURL = kind => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${O.isDark() ? "Dark" : "Light"}_Gray_${kind}/MapServer/tile/{z}/{y}/{x}`;
  function fitArea() { if (MAP) MAP.fitBounds([[A.bbox.south, A.bbox.west], [A.bbox.north, A.bbox.east]], { paddingTopLeft: [16, 56], paddingBottomRight: [16, 72] }); }
  function syncBox() {
    if (!MAP) return;
    const b = [[A.bbox.south, A.bbox.west], [A.bbox.north, A.bbox.east]], style = { color: O.colors().ink, weight: 1.5, dashArray: "5 4", fill: false, interactive: false };
    if (BOX) { BOX.setBounds(b); BOX.setStyle(style); } else BOX = L.rectangle(b, style).addTo(MAP);
  }
  function drawMap() {
    const s = shown();
    $("map-month").textContent = s ? `${O.MONTH[s.m - 1]} ${s.y}` : "—";
    $("map-month").style.color = A.hover ? "var(--ember-ink)" : "";
    if (!FIRE) return;
    const size = MAP.getSize(), dpr = window.devicePixelRatio || 1;
    if (FIRE.width !== Math.round(size.x * dpr) || FIRE.height !== Math.round(size.y * dpr)) { FIRE.width = Math.round(size.x * dpr); FIRE.height = Math.round(size.y * dpr); FIRE.style.width = size.x + "px"; FIRE.style.height = size.y + "px"; }
    L.DomUtil.setPosition(FIRE, MAP.containerPointToLayerPoint([0, 0]));
    const x = FIRE.getContext("2d"); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, size.x, size.y);
    const list = s ? A.byT.get(O.tOf(s.y, s.m)) || [] : []; if (!list.length) return;
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
    if (!window.L) { $("map").innerHTML = `<p class="muted small" style="padding:70px 16px">The map could not load. The calendar still works: choose an area from the list or with Coordinates.</p>`; return; }
    MAP = L.map("map", { zoomControl: false, worldCopyJump: true, zoomSnap: .25, minZoom: 1.5, maxZoom: 12 });
    L.control.zoom({ position: "bottomright" }).addTo(MAP);
    TILES = L.tileLayer(tileURL("Base"), { maxZoom: 16, attribution: 'Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors' }).addTo(MAP);
    const fp = MAP.createPane("fire"); fp.style.zIndex = 350; fp.style.pointerEvents = "none";
    FIRE = L.DomUtil.create("canvas", "leaflet-zoom-animated", fp);
    const lp = MAP.createPane("labels"); lp.style.zIndex = 650; lp.style.pointerEvents = "none";
    LABELS = L.tileLayer(tileURL("Reference"), { maxZoom: 16, pane: "labels" }).addTo(MAP);
    fitArea();
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

  // ---- area ----
  function setArea(next, { fit = true } = {}) {
    if (DRAWING) exitDraw(false);
    A.bbox = { west: +(+next.west).toFixed(4), south: +(+next.south).toFixed(4), east: +(+next.east).toFixed(4), north: +(+next.north).toFixed(4) };
    $("bbox").value = O.formatBBox(A.bbox); $("bbox-error").textContent = ""; $("coords").open = false;
    O.presetOptions($("preset"), A.bbox); O.setState({ bbox: A.bbox });
    $("area-name").textContent = O.areaName(A.bbox);
    syncBox(); if (fit) fitArea();
    const id = ++A.loadId, slow = setTimeout(() => { if (id === A.loadId) toast("Loading fire data for this area…"); }, 250);
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
    }).catch(err => { if (id === A.loadId) { clearTimeout(slow); console.error(err); toast("Couldn't load fire data for this area. Try again."); } });
  }
  function renderAll() { renderVerdict(); renderJump(); renderCal(); renderBrief(); drawMap(); }
  function applyField() { const b = O.parseBBox($("bbox").value); if (!b) { $("bbox-error").textContent = "Enter W,S,E,N as numbers, with W < E and S < N."; return; } setArea(b); }
  $("preset").onchange = e => setArea(O.parseBBox(e.target.value));
  $("apply").onclick = applyField;
  $("bbox").addEventListener("keydown", e => { if (e.key === "Enter") applyField(); });
  STORIES.forEach(s => {
    const b = document.createElement("button"); b.className = "chip"; b.textContent = s.label;
    b.onclick = () => { stop(); const p = O.PRESETS.find(p => p.id === s.preset); A.pendingYear = s.year || END().year; if (s.year && (s.year < A.y0 || s.year > A.y1)) { A.y0 = O.FIRST_YEAR; A.y1 = END().year; syncRange(); } setArea(O.parseBBox(p.bbox)); };
    $("stories").appendChild(b);
  });

  // ---- play ----
  function stop() { if (!A.timer) return; clearInterval(A.timer); A.timer = null; const p = $("play"); p.setAttribute("aria-pressed", "false"); p.textContent = "▶"; p.setAttribute("aria-label", "Play through months"); }
  $("play").onclick = () => {
    if (A.timer) return stop();
    if (A.y == null) return;
    const last = Math.min(endT(), O.tOf(A.y1, 12));
    if (selT() >= last) setSel(A.y0, 1);
    const p = $("play"); p.setAttribute("aria-pressed", "true"); p.textContent = "❚❚"; p.setAttribute("aria-label", "Pause");
    A.timer = setInterval(() => { const t = selT() + 1; if (t > last) return stop(); setSel(Math.floor(t / 12), t % 12 + 1); }, 240);
  };

  // ---- view, colour mode, year range ----
  function seg(id, key, attr) {
    const el = $(id), sync = () => el.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset[attr] === A[key])));
    el.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; A[key] = b.dataset[attr]; O.setState({ [key]: A[key] }); sync(); if (key === "mode") { renderJump(); drawMap(); } renderCal(); });
    sync();
  }
  function syncRange() { $("y0").value = A.y0; $("y1").value = A.y1; }
  function rangeChanged() {
    let a = +$("y0").value, b = +$("y1").value; if (a > b) [a, b] = [b, a];
    A.y0 = a; A.y1 = b; syncRange(); stop();
    if (A.y != null) { A.y = Math.max(a, Math.min(b, A.y)); A.m = Math.min(A.m, upToFor(A.y)); O.setState({ year: A.y, month: A.m }); }
    renderAll();
  }
  $("y0").onchange = rangeChanged; $("y1").onchange = rangeChanged;

  // ---- downloads ----
  $("csv").onclick = () => O.downloadCSV(A.cells.filter(c => c.year >= A.y0 && c.year <= A.y1), `fire-cells-${(O.presetFor(A.bbox) || { id: "custom-area" }).id}-${A.y0}-${A.y1}.csv`);
  // The PNG is a one-page fact sheet: always light (it gets printed and pasted into reports), with the numbers written in.
  $("png").onclick = () => {
    if (!A.loaded) return;
    const ys = years(), cw = 86, ch = 30, gx = 92, gy = 178, W = gx + 12 * (cw + 3) + 150, H = gy + ys.length * (ch + 3) + 92, max = scaleMax();
    const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
    const x = cv.getContext("2d"), F = (w, s, mono) => { x.font = `${w} ${s}px ${mono ? '"IBM Plex Mono",monospace' : '"IBM Plex Sans",sans-serif'}`; };
    x.fillStyle = "#fff"; x.fillRect(0, 0, W, H); x.textBaseline = "middle";
    x.fillStyle = "#1a1714"; F(600, 30); x.fillText(`${O.areaName(A.bbox)} · burning activity calendar`, 32, 46);
    x.fillStyle = "#4e4a44"; F(400, 17); x.fillText($("verdict").textContent, 32, 86);
    const what = A.mode === "anomaly" ? "Times a typical month (2003–2020 median)" : A.mode === "total" ? "Raw detections (MODIS + VIIRS, uncorrected)" : "Harmonized detections (VIIRS-equivalent)";
    x.fillStyle = "#77726a"; F(400, 14); x.fillText(`${what} · ${A.y0}–${A.y1} · ≈ estimated from MODIS before Feb 2012 · * provisional`, 32, 118);
    F(600, 13); x.textAlign = "center"; O.MO.forEach((m, j) => x.fillText(m, gx + j * (cw + 3) + cw / 2, gy - 16)); x.fillText(A.mode === "total" ? "Raw total" : "Year total", gx + 12 * (cw + 3) + 60, gy - 16);
    ys.forEach((y, i) => {
      const cy = gy + i * (ch + 3);
      x.textAlign = "right"; x.fillStyle = "#4e4a44"; F(500, 14, true); x.fillText(y, gx - 12, cy + ch / 2);
      for (let m = 1; m <= 12; m++) {
        const k = metric(y, m), c = fillRGB(k, max, false), cx = gx + (m - 1) * (cw + 3);
        x.fillStyle = c ? `rgb(${c})` : "#f0ede8"; x.fillRect(cx, cy, cw, ch);
        if (!k) continue;
        x.textAlign = "center"; x.fillStyle = c ? O.inkFor(c) : "#77726a"; F(500, 12.5, true);
        x.fillText(A.mode === "anomaly" ? (k.ratio == null ? "–" : k.ratio.toFixed(1) + "×") : `${O.isEst(y, m) && A.mode !== "total" ? "≈" : ""}${k.v > 0 ? O.fmtK(k.v) : "·"}${O.isProv(y, m) ? "*" : ""}`, cx + cw / 2, cy + ch / 2 + 1);
      }
      const t = yearTotal(y); x.textAlign = "left"; x.fillStyle = "#1a1714"; F(500, 14, true); x.fillText(O.fmtK(t.v) + (t.n < 12 ? "*" : ""), gx + 12 * (cw + 3) + 24, cy + ch / 2);
    });
    x.textAlign = "left"; x.fillStyle = "#77726a"; F(400, 13);
    x.fillText(`NASA FIRMS MODIS C6.1 (Terra, Aqua) + VIIRS S-NPP 375 m · harmonized by Team Murphy, NASA Space Apps 2026 · data through ${O.MONTH[END().month - 1]} ${END().year}`, 32, H - 52);
    x.fillText(`Area (W,S,E,N): ${O.formatBBox(A.bbox)} · detections are satellite hotspots, not separate fires`, 32, H - 28);
    O.downloadCanvas(cv, `burning-calendar-${(O.presetFor(A.bbox) || { id: "custom-area" }).id}-${A.y0}-${A.y1}.png`);
  };

  // ---- theme, resize ----
  function paintLegend() { $("map-grad").style.background = `linear-gradient(to right,${lut().filter((_, i) => i % 8 === 0 || i === 47).join(",")})`; }
  O.onTheme(() => { if (MAP) { TILES.setUrl(tileURL("Base")); LABELS.setUrl(tileURL("Reference")); syncBox(); } paintLegend(); renderAll(); });
  let RAF = 0;
  if (window.ResizeObserver) new ResizeObserver(() => { if (A.view !== "ridges" || !A.loaded) return; cancelAnimationFrame(RAF); RAF = requestAnimationFrame(renderRidges); }).observe(body);
  document.addEventListener("click", e => { const d = $("coords"); if (d.open && !d.contains(e.target)) d.open = false; });

  // ---- start ----
  paintLegend(); seg("view", "view", "v"); seg("mode", "mode", "m"); renderCal();
  O.loadData().then(() => {
    O.setDataThrough();
    const end = END().year, opts = Array.from({ length: end - O.FIRST_YEAR + 1 }, (_, i) => `<option>${O.FIRST_YEAR + i}</option>`).join("");
    $("y0").innerHTML = opts; $("y1").innerHTML = opts; A.y1 = end; syncRange();
    A.y = S0.year && S0.year >= O.FIRST_YEAR && S0.year <= end ? S0.year : end;
    A.m = Math.min(S0.month || END().month, upToFor(A.y));
    if (S0.year && !S0.month) A.pendingYear = A.y;   // a link with a year but no month opens on that year's peak month
    initMap(); setArea(A.bbox, { fit: false });
  }).catch(err => { console.error(err); $("verdict").textContent = "Couldn't load the fire data. Try reloading the page."; body.innerHTML = ""; });
})();
