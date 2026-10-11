// Minimal SVG line chart with a crosshair tooltip, a legend and direct end labels. No dependencies.
//
//   lineChart(el, { rows: [{t, a, b}], series: [{key: 'a', label: 'A', color: 'var(--series-1)'}],
//                   binSeconds: 3600, locale: 'en-US', format: v => v, empty: 'No data' })
//
// Marks follow the console's data-viz rules: 2px lines, recessive grid, one y axis starting at 0,
// legend + direct labels for 2-4 series, text in ink colors (never the series color).

const SVG_NS = 'http://www.w3.org/2000/svg';
const charts = new Map();   // element -> options, for redraw on resize

function lineChart(el, opts) {
  charts.set(el, opts);
  drawChart(el, opts);
}

function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  return [1, 2, 2.5, 5, 10].map(m => m * p).find(m => m >= v);
}

function timeLabel(t, binSeconds, locale) {
  const d = new Date(t * 1000);
  if (binSeconds < 3600) return d.toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' });
  if (binSeconds < 3600 * 6) return d.toLocaleTimeString(locale, { hour: 'numeric' });
  if (binSeconds < 86400) return d.toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit' });
  return d.toLocaleDateString(locale, { month: 'numeric', day: 'numeric' });
}

function svg(tag, attrs, parent) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}

function drawChart(el, { rows, series, binSeconds, locale = 'en-US', format = v => v, empty = 'No data' }) {
  el.innerHTML = '';
  el.classList.add('chart');
  const values = rows.flatMap(r => series.map(s => r[s.key])).filter(v => v != null);
  if (!rows.length || !values.some(v => v > 0)) { el.innerHTML = `<p class="empty">${empty}</p>`; return; }

  if (series.length > 1) {
    const legend = document.createElement('div');
    legend.className = 'chart-legend';
    legend.innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.label}</span>`).join('');
    el.appendChild(legend);
  }
  const W = Math.max(el.clientWidth, 320), H = 220, M = { l: 46, r: series.length > 1 ? 74 : 16, t: 10, b: 26 };
  const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': series.map(s => s.label).join(', ') }, el);
  const max = niceMax(Math.max(...values));
  const x = i => M.l + (rows.length === 1 ? (W - M.l - M.r) / 2 : i * (W - M.l - M.r) / (rows.length - 1));
  const y = v => M.t + (H - M.t - M.b) * (1 - v / max);

  const grid = svg('g', { class: 'grid' }, root), axis = svg('g', { class: 'axis' }, root);
  for (let k = 0; k <= 4; k++) {
    const v = max * k / 4, yy = y(v);
    svg('line', { x1: M.l, x2: W - M.r, y1: yy, y2: yy }, grid);
    svg('text', { x: M.l - 8, y: yy + 4, 'text-anchor': 'end' }, axis).textContent = format(Math.round(v * 10) / 10);
  }
  const ticks = Math.min(5, rows.length);
  for (let k = 0; k < ticks; k++) {
    const i = Math.round(k * (rows.length - 1) / Math.max(1, ticks - 1));
    svg('text', { x: x(i), y: H - 6, 'text-anchor': k === 0 ? 'start' : k === ticks - 1 ? 'end' : 'middle' }, axis)
      .textContent = timeLabel(rows[i].t, binSeconds, locale);
  }

  const lines = svg('g', { class: 'series' }, root);
  const ends = [];
  for (const s of series) {
    let d = '', pen = false, last = null;
    rows.forEach((r, i) => {
      const v = r[s.key];
      if (v == null) { pen = false; return; }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true; last = { i, v };
    });
    svg('path', { d, stroke: s.color }, lines);
    if (last && series.length > 1) ends.push({ s, y: y(last.v) });
  }
  // Direct labels at the right edge, nudged apart so they never overlap.
  ends.sort((a, b) => a.y - b.y);
  for (let k = 1; k < ends.length; k++) ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 13);
  for (const e of ends) svg('text', { x: W - M.r + 8, y: Math.min(e.y, H - M.b) + 4, fill: 'var(--text-2)', 'font-size': 11 }, axis).textContent = e.s.label;

  // Hover layer: crosshair, markers and a shared tooltip; the hit area is the whole plot, not the thin lines.
  const cross = svg('line', { class: 'cross', y1: M.t, y2: H - M.b, visibility: 'hidden' }, root);
  const markers = series.map(s => svg('circle', { class: 'marker', r: 4, fill: s.color, visibility: 'hidden' }, root));
  const hit = svg('rect', { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: 'transparent' }, root);
  const tip = document.getElementById('tip');
  hit.addEventListener('mousemove', ev => {
    const box = root.getBoundingClientRect(), px = (ev.clientX - box.left) * W / box.width;
    const i = Math.max(0, Math.min(rows.length - 1, Math.round((px - M.l) / ((W - M.l - M.r) / Math.max(1, rows.length - 1)))));
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
    series.forEach((s, k) => {
      const v = rows[i][s.key];
      markers[k].setAttribute('visibility', v == null ? 'hidden' : 'visible');
      if (v != null) { markers[k].setAttribute('cx', x(i)); markers[k].setAttribute('cy', y(v)); }
    });
    tip.innerHTML = `<div>${timeLabel(rows[i].t, binSeconds, locale)}</div>` + series.map(s =>
      `<div class="row"><span class="dot" style="background:${s.color}"></span>${s.label}<b>${rows[i][s.key] == null ? '–' : format(rows[i][s.key])}</b></div>`).join('');
    tip.style.display = 'block';
    tip.style.left = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8) + 'px';
    tip.style.top = (ev.clientY + 14) + 'px';
  });
  hit.addEventListener('mouseleave', () => {
    cross.setAttribute('visibility', 'hidden'); markers.forEach(m => m.setAttribute('visibility', 'hidden')); tip.style.display = 'none';
  });
}

let resizeTimer;
addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => charts.forEach((opts, el) => el.isConnected && el.offsetParent && drawChart(el, opts)), 150);
});
