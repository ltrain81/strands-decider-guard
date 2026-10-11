// Policy console: overview, policy editor, test, logs, alerts, history.
// Strings: i18n.js · rule templates and samples: samples.js · charts: charts.js

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clone = o => JSON.parse(JSON.stringify(o));
const state = { cfg: null, meta: null, saved: null, draft: null, lang: 'en', alerts: null, logs: [], autoTimer: null };

// ---------- i18n helpers ----------
const T = (key, vars = {}) => (I18N[state.lang][key] ?? I18N.en[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '');
const locale = () => (state.lang === 'ko' ? 'ko-KR' : 'en-US');
const fmtTime = v => v ? new Date(v).toLocaleString(locale()) : '-';
const fmtNum = n => (n == null ? '–' : Number(n).toLocaleString(locale()));
const actionLabel = a => T('act_' + a);
const sensLabel = id => state.meta.sensitivities.find(s => s.id === id)?.label || id;
const catLabel = key => key.startsWith('rule:') ? T('rule_prefix') + key.slice(5)
  : state.meta.categories.find(c => c.id === key)?.label || state.meta.labels[key] || key;
const clientLabel = k => CLIENT_LABEL[k] || (k && k !== '-' ? k : T('other'));

function applyStatic() {
  document.documentElement.lang = state.lang;
  document.title = T('title');
  $$('[data-i18n]').forEach(el => el.textContent = T(el.dataset.i18n));
  $$('[data-i18n-html]').forEach(el => el.innerHTML = T(el.dataset.i18nHtml));
  $$('[data-i18n-ph]').forEach(el => el.placeholder = T(el.dataset.i18nPh));
  $$('#lang button').forEach(b => b.classList.toggle('on', b.dataset.lang === state.lang));
  $('#tpl').innerHTML = TEMPLATES[state.lang].map((t, i) => `<button data-t="${i}">+ ${esc(t.name)}</button>`).join('');
  $('#samples').innerHTML = SAMPLES[state.lang].map((s, i) => `<button data-s="${i}">${esc(s.label)}</button>`).join('');
  if (state.cfg?.mode !== 'cognito') $('#who').textContent = T('local_mode');
}

async function setLang(lang) {
  state.lang = lang;
  localStorage.setItem('lang', lang);
  applyStatic();
  if (!state.saved) return;
  state.meta = (await api('/api/policy')).meta;
  fillLogFilters();
  renderPolicy();
  showTab(currentTab());
}

// ---------- auth (Cognito hosted UI, authorization code + PKCE) ----------
const b64url = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const jwtClaims = t => JSON.parse(decodeURIComponent(escape(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))));

async function login() {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
  sessionStorage.setItem('pkce', verifier);
  const challenge = b64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)));
  const q = new URLSearchParams({ response_type: 'code', client_id: state.cfg.clientId, redirect_uri: state.cfg.redirectUri,
    scope: 'openid email', code_challenge_method: 'S256', code_challenge: challenge });
  location.href = `${state.cfg.cognitoDomain}/oauth2/authorize?${q}`;
  return new Promise(() => {});
}

async function ensureLogin() {
  if (state.cfg.mode !== 'cognito') return;
  const code = new URLSearchParams(location.search).get('code');
  if (code) {
    const r = await fetch(`${state.cfg.cognitoDomain}/oauth2/token`, { method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ grant_type: 'authorization_code', client_id: state.cfg.clientId, code, redirect_uri: state.cfg.redirectUri,
        code_verifier: sessionStorage.getItem('pkce') || '' }) });
    const t = await r.json();
    if (t.id_token) sessionStorage.setItem('id_token', t.id_token);
    history.replaceState({}, '', state.cfg.redirectUri);
  }
  const tok = sessionStorage.getItem('id_token');
  if (!tok || jwtClaims(tok).exp * 1000 < Date.now() + 30000) return login();
  $('#who').textContent = jwtClaims(tok).email || '';
  $('#logout').hidden = false;
  $('#logout').onclick = () => {
    sessionStorage.removeItem('id_token');
    location.href = `${state.cfg.cognitoDomain}/logout?${new URLSearchParams({ client_id: state.cfg.clientId, logout_uri: state.cfg.redirectUri })}`;
  };
}

async function api(path, opts = {}) {
  const headers = { 'content-type': 'application/json', 'x-lang': state.lang };
  if (state.cfg.mode === 'cognito') headers.authorization = `Bearer ${sessionStorage.getItem('id_token')}`;
  const r = await fetch(state.cfg.apiBase.replace(/\/$/, '') + path, { ...opts, headers });
  if (r.status === 401) return login();
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || body.message || `HTTP ${r.status}`);
  return body;
}

function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(toast.h); toast.h = setTimeout(() => t.style.display = 'none', 3000);
}

const status = (kind, label) => `<span class="status ${kind}"><i>${{ good: '✓', warning: '!', critical: '✕', muted: '–' }[kind]}</i>${esc(label)}</span>`;
const decisionPill = d => `<span class="pill"><span class="dot ${d}"></span>${T('v_' + d)}</span>`;

// ---------- overview ----------
async function loadOverview() {
  const hours = $('#ov-hours').value;
  try {
    const o = await api(`/api/overview?hours=${hours}`);
    renderHealth(o.health);
    const t = o.totals, pct = n => (t.checks ? Math.round(n / t.checks * 1000) / 10 : 0);
    $('#kpis').innerHTML = [
      [T('kpi_checks'), fmtNum(t.checks), ''],
      [`<span class="dot block"></span>${T('kpi_blocked')}`, fmtNum(t.block), T('kpi_rate', { p: pct(t.block) })],
      [`<span class="dot ask"></span>${T('kpi_asked')}`, fmtNum(t.ask), T('kpi_rate', { p: pct(t.ask) })],
      [T('kpi_p95'), t.p95 == null ? '–' : fmtNum(Math.round(t.p95)), t.p95 == null ? '' : 'ms'],
      [T('kpi_errors'), t.errors == null ? '–' : fmtNum(t.errors), ''],
    ].map(([k, v, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}${s ? `<small>${s}</small>` : ''}</div></div>`).join('');
    $('#ch-decisions-sub').textContent = T('ch_decisions_sub', { bin: T('bin_' + o.bin_seconds) });
    lineChart($('#ch-decisions'), { rows: o.series, binSeconds: o.bin_seconds, locale: locale(), format: fmtNum, empty: T('no_chart'),
      series: [{ key: 'allow', label: T('s_allow'), color: 'var(--good)' }, { key: 'ask', label: T('s_ask'), color: 'var(--warning)' },
               { key: 'block', label: T('s_block'), color: 'var(--critical)' }] });
    lineChart($('#ch-latency'), { rows: o.latency, binSeconds: o.bin_seconds, locale: locale(), format: v => fmtNum(Math.round(v)), empty: T('no_chart'),
      series: [{ key: 'p50', label: T('s_p50'), color: 'var(--series-1)' }, { key: 'p95', label: T('s_p95'), color: 'var(--series-2)' }] });
    bars($('#by-cat'), o.by_category, catLabel);
    bars($('#by-client'), o.by_client, clientLabel);
    $('#recent').innerHTML = logTable(o.recent, false);
    if (o.partial) toast(T('partial'));
  } catch (e) { $('#kpis').innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

function renderHealth(h) {
  const g = h.guard, host = h.host, al = h.alerts, p = h.policy;
  const hostKind = { running: 'good', local: 'good', stopped: 'critical', pending: 'warning', stopping: 'warning' }[host.state] || 'muted';
  const alertCell = !al.available ? status('muted', T('st_alerts_na'))
    : al.in_alarm?.length ? status('critical', T('st_alarm', { n: al.in_alarm.length }))
    : al.configured ? status('good', T('st_alerts_ok', { n: al.configured })) : status('muted', T('st_alerts_none'));
  $('#health').innerHTML = [
    [T('health_guard'), g.ok ? status('good', T('st_ok')) : status('critical', T('st_down')), g.ok ? `${g.model} · ${g.device}` : g.error],
    [T('health_host'), status(hostKind, T('st_' + host.state) || host.state), host.type || ''],
    [T('health_policy'), p.updated_at ? status('good', T('st_saved', { t: fmtTime(p.updated_at) })) : status('muted', T('st_default_policy')), p.updated_by || ''],
    [T('health_alerts'), alertCell, al.in_alarm?.length ? al.in_alarm.map(n => T('r_' + n) || n).join(', ') : ''],
  ].map(([k, v, d]) => `<div class="health"><div class="k">${k}</div>${v}<div class="d" title="${esc(d)}">${esc(d)}</div></div>`).join('');
}

function bars(el, rows, labelOf) {
  if (!rows.length) { el.innerHTML = `<p class="empty">${T('no_chart')}</p>`; return; }
  const max = Math.max(...rows.map(r => r.n));
  el.innerHTML = rows.map(r => `<div class="b" data-tip="${esc(labelOf(r.key))}: ${esc(T('count', { n: fmtNum(r.n) }))}">
    <span class="name">${esc(labelOf(r.key))}</span><span class="track"><span class="fill" style="width:${(r.n / max * 100).toFixed(1)}%"></span></span>
    <span class="num">${fmtNum(r.n)}</span></div>`).join('');
}

function setAutoRefresh(on) {
  clearInterval(state.autoTimer);
  state.autoTimer = on ? setInterval(() => currentTab() === 'overview' && loadOverview(), 60000) : null;
}

// ---------- policy tab ----------
const comparable = p => { const c = clone(p); delete c.updated_at; delete c.updated_by; return JSON.stringify(c); };

function renderPolicy() {
  const d = state.draft, m = state.meta;
  $('#sens').innerHTML = m.sensitivities.map(s => `
    <div class="choice ${d.sensitivity === s.id ? 'on' : ''}" data-sens="${s.id}" role="radio" aria-checked="${d.sensitivity === s.id}" tabindex="0">
      <b>${esc(s.label)}</b><span>${esc(T('sens_' + s.id))}</span></div>`).join('');
  $('#cats').innerHTML = m.categories.map(c => `
    <div class="cat"><div class="info"><b>${esc(c.label)}</b><span>${esc(c.desc)}</span></div>
      <div class="seg" data-cat="${c.id}" role="radiogroup" aria-label="${esc(c.label)}">${['block', 'ask', 'allow'].map(v =>
        `<button data-v="${v}" class="${d.categories[c.id] === v ? 'on' : ''}" aria-pressed="${d.categories[c.id] === v}">${T('act_' + v)}</button>`).join('')}</div></div>`).join('');
  $('#rules').innerHTML = d.custom_rules.length ? d.custom_rules.map((r, i) => `
    <div class="rule ${r.enabled ? '' : 'off'}" data-i="${i}">
      <div class="row">
        <label class="check"><input type="checkbox" data-k="enabled" ${r.enabled ? 'checked' : ''}> ${T('rule_on')}</label>
        <input type="text" data-k="name" value="${esc(r.name)}" placeholder="${esc(T('rule_name_ph'))}">
        <select data-k="action">${['block', 'ask'].map(v => `<option value="${v}" ${r.action === v ? 'selected' : ''}>${T('act_' + v)}</option>`).join('')}</select>
        <select data-k="sensitivity">${m.sensitivities.map(s => `<option value="${s.id}" ${r.sensitivity === s.id ? 'selected' : ''}>${esc(T('rule_sens', { s: s.label }))}</option>`).join('')}</select>
        <button class="btn ghost" data-del>${T('delete')}</button>
      </div>
      <textarea data-k="question" rows="2" placeholder="${esc(T('rule_q_ph'))}">${esc(r.question)}</textarea>
    </div>`).join('') : `<p class="empty">${T('no_rules')}</p>`;
  for (const el of $$('#t-policy .chips')) {
    const key = el.dataset.list;
    $$('.chip', el).forEach(c => c.remove());
    el.insertAdjacentHTML('afterbegin', d.allow[key].map((v, i) => `<span class="chip">${esc(v)}<button data-rm="${i}" aria-label="${T('delete')}">×</button></span>`).join(''));
  }
  if (document.activeElement !== $('#message')) $('#message').value = d.message || '';
  $('#ver').textContent = state.saved.updated_at
    ? T('last_saved', { t: fmtTime(state.saved.updated_at), by: state.saved.updated_by ? ' · ' + state.saved.updated_by : '' })
    : T('default_policy');
  markDirty();
}

function markDirty() {
  $('#savebar').classList.toggle('on', comparable(state.draft) !== comparable(state.saved));
}

function bindPolicy() {
  $('#sens').addEventListener('click', e => { const c = e.target.closest('[data-sens]'); if (!c) return; state.draft.sensitivity = c.dataset.sens; renderPolicy(); });
  $('#sens').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.dataset.sens) { e.preventDefault(); e.target.click(); } });
  $('#cats').addEventListener('click', e => { const b = e.target.closest('button[data-v]'); if (!b) return; state.draft.categories[b.parentElement.dataset.cat] = b.dataset.v; renderPolicy(); });
  $('#tpl').addEventListener('click', e => { const b = e.target.closest('[data-t]'); if (b) addRule(TEMPLATES[state.lang][b.dataset.t]); });
  $('#add-rule').onclick = () => addRule({ name: '', question: '' });
  const rules = $('#rules');
  rules.addEventListener('input', e => {
    const k = e.target.dataset.k, i = e.target.closest('[data-i]')?.dataset.i; if (!k || i == null) return;
    state.draft.custom_rules[i][k] = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    if (k === 'enabled') e.target.closest('.rule').classList.toggle('off', !e.target.checked);
    markDirty();
  });
  rules.addEventListener('click', e => { if (!e.target.hasAttribute('data-del')) return; state.draft.custom_rules.splice(e.target.closest('[data-i]').dataset.i, 1); renderPolicy(); });
  for (const el of $$('#t-policy .chips')) bindChips(el, () => state.draft.allow[el.dataset.list], renderPolicy);
  $('#message').addEventListener('input', e => { state.draft.message = e.target.value; markDirty(); });
  $('#discard').onclick = () => { state.draft = clone(state.saved); $('#loaded-banner').classList.remove('on'); renderPolicy(); };
  $('#save').onclick = save;
}

function bindChips(el, list, rerender) {
  const input = $('input', el);
  input.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
      e.preventDefault();
      const v = input.value.trim().replace(/^@/, '');
      if (!list().includes(v)) list().push(v);
      input.value = ''; rerender(); $('input', el).focus();
    }
  });
  el.addEventListener('click', e => { if (e.target.dataset.rm == null) return input.focus(); list().splice(e.target.dataset.rm, 1); rerender(); });
}

function addRule(t) {
  state.draft.custom_rules.push({ id: 'r' + Date.now().toString(36), name: t.name, question: t.question, action: 'block', sensitivity: 'balanced', enabled: true });
  renderPolicy();
  $$('#rules textarea').at(-1)?.focus();
}

async function save() {
  $('#save').disabled = true;
  try {
    const r = await api('/api/policy', { method: 'PUT', body: JSON.stringify({ policy: state.draft }) });
    state.saved = r.policy; state.draft = clone(r.policy);
    $('#loaded-banner').classList.remove('on');
    renderPolicy();
    toast(T('saved_toast'));
  } catch (e) { toast(T('save_failed', { e: e.message })); }
  $('#save').disabled = false;
}

// ---------- test tab ----------
function friendlyReason(f) {
  const L = state.meta.labels, pct = x => Math.round(x * 100);
  if (f.source === 'rule') return T('r_rule', { name: esc(f.name), p: pct(f.p) });
  if (f.source === 'regex') return T('r_regex', { label: esc(L[f.type] || f.type), sample: esc(f.sample) });
  return T('r_model', { label: esc(L[f.type] || f.type), s: pct(f.kind_confidence), n: pct(f.p_named) });
}

async function runTest() {
  const box = $('#test-result');
  box.hidden = false; box.innerHTML = `<p class="empty">${T('checking')}</p>`;
  try {
    const r = await api('/api/test', { method: 'POST', body: JSON.stringify({ text: $('#test-text').value, policy: state.draft }) });
    const res = r.results[0] || { findings: [], latency_ms: 0 };
    const icon = { block: '✕', ask: '!', allow: '✓' }[r.decision];
    const findings = r.decision === 'allow' ? [] : res.findings;
    box.innerHTML = `<div class="verdict ${r.decision}"><i>${icon}</i>${T('v_' + r.decision)}</div>
      ${findings.length ? `<ul class="reasons">${findings.map(f => `<li>${friendlyReason(f)}</li>`).join('')}</ul>` : `<p class="sub" style="margin-top:12px">${T('nothing_found')}</p>`}
      <p class="hint">${T('took', { ms: Math.round(res.latency_ms) })}${r.decision === 'ask' ? T('ask_note') : ''}</p>`;
  } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

// ---------- logs tab ----------
function fillLogFilters() {
  const keep = id => $(id).value;
  const client = keep('#lg-client'), cat = keep('#lg-category');
  $('#lg-client').innerHTML = `<option value="">${T('f_tool_all')}</option>` +
    ['claude', 'codex', 'kiro', 'litellm'].map(k => `<option value="${k}">${CLIENT_LABEL[k]}</option>`).join('');
  $('#lg-category').innerHTML = `<option value="">${T('f_cat_all')}</option>` +
    state.meta.categories.map(c => `<option value="${c.id}">${esc(c.label)}</option>`).join('') +
    (state.draft?.custom_rules || []).map(r => `<option value="rule:${esc(r.name)}">${esc(T('rule_prefix') + r.name)}</option>`).join('');
  $('#lg-client').value = client; $('#lg-category').value = cat;
}

function logTable(rows, detail = true) {
  if (!rows.length) return `<p class="empty">${T('no_logs')}</p>`;
  return `<table><thead><tr><th>${T('col_time')}</th><th>${T('col_decision')}</th><th>${T('col_tool')}</th><th>${T('col_target')}</th>
    <th>${T('col_reason')}</th>${detail ? `<th class="num">${T('col_chars')}</th>` : ''}<th class="num">ms</th></tr></thead><tbody>
    ${rows.map((e, i) => `<tr class="${detail ? 'clickable' : ''}" data-row="${i}"><td>${esc(fmtTime(e.ts))}</td><td>${decisionPill(e.decision)}</td>
      <td>${esc(clientLabel(e.client))}</td><td>${esc(e.sources || '')}</td>
      <td>${esc((e.categories || '').split(',').filter(Boolean).map(catLabel).join(', '))}</td>
      ${detail ? `<td class="num">${fmtNum(e.chars)}</td>` : ''}<td class="num">${fmtNum(e.ms)}</td></tr>`).join('')}
    </tbody></table>`;
}

async function loadLogs() {
  const q = new URLSearchParams({ hours: $('#lg-hours').value, decision: $('#lg-decision').value, client: $('#lg-client').value,
    category: $('#lg-category').value, q: $('#lg-q').value.trim(), limit: '300' });
  $('#logs').innerHTML = `<p class="empty">${T('loading')}</p>`;
  try {
    const r = await api(`/api/logs?${q}`);
    state.logs = r.rows;
    $('#logs').innerHTML = `<p class="hint">${T('rows_shown', { n: fmtNum(r.rows.length) })}${r.truncated ? ' · ' + T('truncated', { n: r.rows.length }) : ''}</p>` + logTable(r.rows);
    if (r.partial) toast(T('partial'));
  } catch (e) { $('#logs').innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  loadActivity();
}

function toggleLogDetail(tr) {
  const next = tr.nextElementSibling;
  if (next?.classList.contains('detail')) { next.remove(); return; }
  const e = state.logs[tr.dataset.row];
  tr.insertAdjacentHTML('afterend', `<tr class="detail"><td colspan="7"><pre>${esc(JSON.stringify(e, null, 2))}</pre></td></tr>`);
}

function exportCsv() {
  const cols = ['ts', 'decision', 'client', 'sources', 'categories', 'chars', 'ms', 'request_id'];
  const cell = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const csv = [cols.join(','), ...state.logs.map(r => cols.map(c => cell(r[c])).join(','))].join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `decider-guard-log-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '')}.csv`;
  a.click();
}

function renderChange(c) {
  const act = v => T('act_' + v), list = l => T('list_' + l);
  switch (c.kind) {
    case 'sensitivity': return T('ch_sensitivity', { from: esc(sensLabel(c.from)), to: esc(sensLabel(c.to)) });
    case 'category': return T('ch_category', { label: esc(catLabel(c.id)), from: act(c.from), to: act(c.to) });
    case 'rule_added': return T('ch_rule_added', { name: esc(c.name) });
    case 'rule_removed': return T('ch_rule_removed', { name: esc(c.name) });
    case 'rule_changed': return T('ch_rule_changed', { name: esc(c.name), fields: esc(c.fields.join(', ')) });
    case 'allow_added': return T('ch_allow_added', { list: list(c.list), value: esc(c.value) });
    case 'allow_removed': return T('ch_allow_removed', { list: list(c.list), value: esc(c.value) });
    case 'message': return T('ch_message');
    case 'email_added': return T('ch_email_added', { value: esc(c.value) });
    case 'email_removed': return T('ch_email_removed', { value: esc(c.value) });
    case 'rule': return T('ch_alert_rule', { name: T('r_' + c.id), state: (c.enabled ? T('on') : T('off')) +
      (c.threshold ? ` · ${c.threshold}` : '') + (c.threshold_ms ? ` · ${c.threshold_ms} ms` : '') });
    default: return esc(c.kind);
  }
}

const changeList = changes => changes?.length ? `<ul class="changes">${changes.map(c => `<li>${renderChange(c)}</li>`).join('')}</ul>` : `<span class="hint">${T('no_changes')}</span>`;

async function loadActivity() {
  const el = $('#activity');
  el.innerHTML = `<p class="empty">${T('loading')}</p>`;
  try {
    const { rows } = await api(`/api/activity?hours=${Math.max(168, +$('#lg-hours').value)}`);
    el.innerHTML = rows.length ? `<table><thead><tr><th>${T('col_time')}</th><th>${T('col_by')}</th><th>${T('col_action')}</th><th>${T('col_changes')}</th></tr></thead><tbody>
      ${rows.map(r => `<tr><td>${esc(fmtTime(r.ts))}</td><td>${esc(r.by || '-')}</td><td>${esc(actionLabel(r.action))}</td><td>${changeList(r.detail)}</td></tr>`).join('')}
      </tbody></table>` : `<p class="empty">${T('no_activity')}</p>`;
  } catch (e) { el.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

// ---------- alerts tab ----------
const ALERT_RULES = ['guard_down', 'guard_errors', 'block_spike', 'latency'];

async function loadAlerts() {
  const el = $('#alerts');
  el.innerHTML = `<p class="empty">${T('loading')}</p>`;
  try {
    state.alerts = await api('/api/alerts');
    renderAlerts();
  } catch (e) { el.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

function renderAlerts() {
  const a = state.alerts, el = $('#alerts');
  if (!a.available) { el.innerHTML = `<div class="notice">${T('al_na')}</div>`; return; }
  const subState = s => s === 'confirmed' ? status('good', T('al_confirmed')) : s === 'pending' ? status('warning', T('al_pending')) : status('muted', T('al_missing'));
  const alarmState = r => !r.enabled ? status('muted', T('al_state_off'))
    : r.state === 'ALARM' ? status('critical', T('al_state_ALARM')) : r.state === 'OK' ? status('good', T('al_state_OK'))
    : status('warning', T('al_state_INSUFFICIENT_DATA'));
  el.innerHTML = `
    <label class="f">${T('al_recipients')}</label>
    <div class="chips" id="al-emails">${a.emails.map((e, i) => `<span class="chip">${esc(e.email)} ${subState(e.status)}<button data-rm="${i}" aria-label="${T('delete')}">×</button></span>`).join('')}
      <input placeholder="${esc(T('al_recipients_ph'))}"></div>
    <p class="hint">${T('al_confirm_note')}</p>
    <h2 style="margin-top:20px">${T('al_rules')}</h2>
    ${ALERT_RULES.map(id => { const r = a.rules[id]; return `
      <div class="alert-rule" data-rule="${id}">
        <label class="switch"><input type="checkbox" data-k="enabled" ${r.enabled ? 'checked' : ''}><span></span></label>
        <div class="info"><b>${T('r_' + id)}</b><span>${T('r_' + id + '_d')}</span></div>
        ${'threshold' in r ? `<label class="check">${T('threshold')} <input type="number" data-k="threshold" min="1" value="${r.threshold}"> ${T('blocks_unit')}</label>` : ''}
        ${'threshold_ms' in r ? `<label class="check">${T('threshold')} <input type="number" data-k="threshold_ms" min="100" step="100" value="${r.threshold_ms}"> ${T('ms_unit')}</label>` : ''}
        <span style="min-width:120px;text-align:right">${alarmState(r)}</span>
      </div>`; }).join('')}
    <div class="toolbar" style="margin-top:18px"><button class="btn primary" id="al-save">${T('al_save')}</button><button class="btn" id="al-test">${T('al_test')}</button></div>`;
  const emails = () => a.emails;
  const chips = $('#al-emails');
  const input = $('input', chips);
  input.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
      e.preventDefault();
      const v = input.value.trim();
      if (!emails().some(x => x.email === v)) emails().push({ email: v, status: 'missing' });
      renderAlerts(); $('#al-emails input').focus();
    }
  });
  chips.addEventListener('click', e => { if (e.target.dataset.rm == null) return input.focus(); emails().splice(e.target.dataset.rm, 1); renderAlerts(); });
  $$('.alert-rule').forEach(row => row.addEventListener('input', e => {
    const k = e.target.dataset.k; if (!k) return;
    a.rules[row.dataset.rule][k] = e.target.type === 'checkbox' ? e.target.checked : +e.target.value;
  }));
  $('#al-save').onclick = saveAlerts;
  $('#al-test').onclick = async () => {
    try { await api('/api/alerts/test', { method: 'POST', body: '{}' }); toast(T('al_test_sent')); } catch (e) { toast(e.message); }
  };
}

async function saveAlerts() {
  const a = state.alerts;
  const body = { alerts: { emails: a.emails.map(e => e.email), rules: Object.fromEntries(ALERT_RULES.map(id => {
    const { state: _s, since: _t, ...cfg } = a.rules[id]; return [id, cfg]; })) } };
  $('#al-save').disabled = true;
  try { state.alerts = await api('/api/alerts', { method: 'PUT', body: JSON.stringify(body) }); renderAlerts(); toast(T('al_saved')); }
  catch (e) { toast(e.message); $('#al-save').disabled = false; }
}

// ---------- history tab ----------
async function loadHistory() {
  const el = $('#versions');
  el.innerHTML = `<p class="empty">${T('loading')}</p>`;
  try {
    const { versions } = await api('/api/history');
    el.innerHTML = versions.length ? `<table><thead><tr><th>${T('col_saved')}</th><th>${T('col_by')}</th><th></th></tr></thead><tbody>
      ${versions.map((v, i) => `<tr><td>${esc(fmtTime(v.saved_at))}${i === 0 ? ` <span class="hint">${T('current')}</span>` : ''}</td><td>${esc(v.by || '-')}</td>
        <td style="text-align:right">${i === 0 ? '' : `<button class="btn small" data-compare="${esc(v.version_id)}">${T('compare')}</button>
          <button class="btn small" data-load="${esc(v.version_id)}" data-when="${esc(v.saved_at)}">${T('load')}</button>`}</td></tr>`).join('')}
      </tbody></table>` : `<p class="empty">${T('no_versions')}</p>`;
  } catch (e) { el.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

async function compareVersion(btn) {
  const tr = btn.closest('tr'), next = tr.nextElementSibling;
  if (next?.classList.contains('detail')) { next.remove(); return; }
  try {
    const { changes } = await api(`/api/history/${encodeURIComponent(btn.dataset.compare)}`);
    tr.insertAdjacentHTML('afterend', `<tr class="detail"><td colspan="3"><b>${T('changes_if_loaded')}</b>${changeList(changes)}</td></tr>`);
  } catch (e) { toast(T('load_failed', { e: e.message })); }
}

async function loadVersion(id, when) {
  try {
    const { policy, changes } = await api(`/api/history/${encodeURIComponent(id)}`);
    state.draft = clone(policy);
    showTab('policy'); renderPolicy();
    const b = $('#loaded-banner');
    b.innerHTML = esc(T('loaded_banner', { t: fmtTime(when) })) + changeList(changes);
    b.classList.add('on');
  } catch (e) { toast(T('load_failed', { e: e.message })); }
}

// ---------- shell ----------
const currentTab = () => $('#tabs button.on')?.dataset.t || 'overview';
const LOADERS = { overview: loadOverview, logs: loadLogs, alerts: loadAlerts, history: loadHistory };

function showTab(t) {
  $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === t));
  $$('section.tab').forEach(s => s.classList.toggle('on', s.id === 't-' + t));
  history.replaceState({}, '', location.pathname + location.search + '#' + t);
  LOADERS[t]?.();
}

function bindTooltips() {
  const tip = $('#tip');
  document.addEventListener('mousemove', e => {
    if (e.target.closest('.chart')) return;   // charts manage the tooltip themselves
    const el = e.target.closest('[data-tip]');
    if (!el) { tip.style.display = 'none'; return; }
    tip.textContent = el.dataset.tip; tip.style.display = 'block';
    tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8) + 'px'; tip.style.top = (e.clientY + 14) + 'px';
  });
}

async function main() {
  const q = new URLSearchParams(location.search).get('lang');
  state.lang = [q, localStorage.getItem('lang'), (navigator.language || '').slice(0, 2)].find(l => l in I18N) || 'en';
  state.cfg = await (await fetch('config.json', { cache: 'no-store' })).json();
  applyStatic();
  await ensureLogin();
  const r = await api('/api/policy');
  state.meta = r.meta; state.saved = r.policy; state.draft = clone(r.policy);
  bindPolicy(); renderPolicy(); bindTooltips(); fillLogFilters();
  $('#lang').addEventListener('click', e => { const b = e.target.closest('[data-lang]'); if (b) setLang(b.dataset.lang); });
  $('#tabs').addEventListener('click', e => { const b = e.target.closest('button[data-t]'); if (b) showTab(b.dataset.t); });
  $('#samples').addEventListener('click', e => { const b = e.target.closest('[data-s]'); if (b) $('#test-text').value = SAMPLES[state.lang][b.dataset.s].text; });
  $('#run-test').onclick = runTest;
  $('#ov-refresh').onclick = loadOverview; $('#ov-hours').onchange = loadOverview;
  $('#ov-auto').onchange = e => setAutoRefresh(e.target.checked);
  $('#ov-to-logs').onclick = () => { $('#lg-decision').value = ''; $('#lg-hours').value = $('#ov-hours').value; showTab('logs'); };
  $('#lg-search').onclick = loadLogs; $('#lg-export').onclick = exportCsv;
  $('#lg-q').addEventListener('keydown', e => { if (e.key === 'Enter') loadLogs(); });
  $('#logs').addEventListener('click', e => { const tr = e.target.closest('tr.clickable'); if (tr) toggleLogDetail(tr); });
  $('#versions').addEventListener('click', e => {
    const c = e.target.closest('[data-compare]'); if (c) return compareVersion(c);
    const b = e.target.closest('[data-load]'); if (b) loadVersion(b.dataset.load, b.dataset.when);
  });
  addEventListener('beforeunload', e => { if (comparable(state.draft) !== comparable(state.saved)) e.preventDefault(); });
  const first = location.hash.slice(1);
  showTab(first in LOADERS || ['policy', 'test'].includes(first) ? first : 'overview');
}
main().catch(e => { document.querySelector('main').innerHTML = `<div class="card"><p class="err">${esc(e.message)}</p></div>`; });
