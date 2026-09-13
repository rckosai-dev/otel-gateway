/* OTel Gateway — minimal, offline policy editor.
 * Composes routing rules visually against the conditions.json vocabulary and
 * exports routing-policy.yaml (→ PR) or a single-rule JSON (→ policyctl --from-json).
 * It deliberately does NOT compile OTTL: the authoritative OTTL/cost diff comes
 * from `policyctl compile --dry-run` and the dev pipeline. */
'use strict';

const REPO = '../../';
const PATHS = {
  conditions: REPO + 'policy-compiler/conditions.json',
  routing: REPO + 'policy/routing-policy.yaml',
  catalog: REPO + 'policy/service-catalog.yaml',
};

const state = {
  conditions: null,
  catalog: null,
  routingHeader: '',   // leading comment block of routing-policy.yaml, preserved on export
  version: 1,
  defaultDecision: 'warm',
  rules: [],           // editable model
  selected: 0,
};

let _uid = 0;
const uid = () => 'r' + (++_uid);

/* ------------------------------------------------------------------ load */

async function tryFetch(path, parser) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(path + ': ' + res.status);
  return parser(await res.text());
}

async function boot() {
  const setState = (cls, msg) => {
    const el = document.getElementById('loadState');
    el.className = 'load-state ' + cls; el.textContent = msg;
  };
  try {
    state.conditions = await tryFetch(PATHS.conditions, JSON.parse);
    const routingText = await (await fetch(PATHS.routing, { cache: 'no-store' })).text();
    ingestRouting(routingText);
    state.catalog = await tryFetch(PATHS.catalog, jsyaml.load);
    setState('ok', 'loaded from repo');
  } catch (e) {
    setState('err', 'manual load needed');
    document.getElementById('offlineNote').hidden = false;
    wireManualLoad();
    return;
  }
  render();
}

function ingestRouting(text) {
  const lines = text.split('\n');
  const header = [];
  for (const ln of lines) {
    if (ln.startsWith('#') || ln.trim() === '') header.push(ln);
    else break;
  }
  state.routingHeader = header.join('\n');
  const doc = jsyaml.load(text) || {};
  state.version = doc.version || 1;
  state.defaultDecision = doc.default_decision || 'warm';
  state.rules = (doc.rules || []).map(ruleToModel);
  state.selected = 0;
}

function wireManualLoad() {
  const read = (input, cb) => {
    input.addEventListener('change', () => {
      const f = input.files[0]; if (!f) return;
      const r = new FileReader();
      r.onload = () => { cb(r.result); maybeRender(); };
      r.readAsText(f);
    });
  };
  read(document.getElementById('fileConditions'), t => state.conditions = JSON.parse(t));
  read(document.getElementById('fileRouting'), ingestRouting);
  read(document.getElementById('fileCatalog'), t => state.catalog = jsyaml.load(t));
}
function maybeRender() {
  if (state.conditions && state.rules.length !== undefined && state.rules) {
    document.getElementById('offlineNote').hidden = state.catalog && state.rules.length >= 0;
    render();
  }
}

/* -------------------------------------------------- model <-> policy YAML */

function atomFromItem(item) {
  if (item === true) return { key: '__true__', value: true };
  const [k, v] = Object.entries(item)[0];
  return { key: k, value: v };
}
function parseWhen(when) {
  if (!when || Object.keys(when).length === 0) return { combine: 'and', atoms: [] };
  if (Array.isArray(when.any_of)) return { combine: 'any_of', atoms: when.any_of.map(atomFromItem) };
  if (Array.isArray(when.all_of)) return { combine: 'all_of', atoms: when.all_of.map(atomFromItem) };
  return { combine: 'and', atoms: Object.entries(when).map(([k, v]) => ({ key: k, value: v })) };
}
function ruleToModel(rule) {
  const w = parseWhen(rule.when);
  const byTier = rule.decision_by_tier || {};
  return {
    uid: uid(),
    id: rule.id || '',
    combine: w.combine,
    atoms: w.atoms,
    decisionMode: rule.decision_by_tier ? 'by_tier' : 'flat',
    decision: rule.decision || 'warm',
    byTier: {
      critical: byTier.critical || 'warm',
      standard: byTier.standard || 'warm',
      low: byTier.low || 'drop-candidate',
    },
    reason: rule.reason || '',
  };
}
function itemFromAtom(a) { return a.key === '__true__' ? true : { [a.key]: a.value }; }
function buildWhen(m) {
  const atoms = m.atoms.filter(a => a.key);
  if (atoms.length === 0) return {};
  if (m.combine === 'any_of' || m.combine === 'all_of') return { [m.combine]: atoms.map(itemFromAtom) };
  const o = {};
  atoms.forEach(a => { if (a.key !== '__true__') o[a.key] = a.value; });
  return o;
}
function modelToRule(m) {
  const r = { id: m.id, when: buildWhen(m) };
  if (m.decisionMode === 'by_tier') r.decision_by_tier = { ...m.byTier };
  else r.decision = m.decision;
  r.reason = m.reason;
  return r;
}
function buildRoutingDoc() {
  return { version: state.version, rules: state.rules.map(modelToRule), default_decision: state.defaultDecision };
}
function buildRoutingYaml() {
  const body = jsyaml.dump(buildRoutingDoc(), { sortKeys: false, lineWidth: 100 });
  return (state.routingHeader ? state.routingHeader.replace(/\n*$/, '\n\n') : '') + body;
}

/* --------------------------------------------------------------- validate */

function valueType(key) {
  if (key === '__true__') return null;
  const spec = state.conditions.conditions[key];
  return spec ? spec.value.type : null;
}
function validateRule(m, allIds) {
  const errs = [];
  if (!m.id.trim()) errs.push('id is required');
  else if (allIds.filter(x => x === m.id).length > 1) errs.push('id must be unique');
  if (!m.reason.trim()) errs.push('reason is required (audit)');
  m.atoms.forEach(a => {
    if (!a.key) { errs.push('an unset condition'); return; }
    if (a.key === '__true__') return;
    const spec = state.conditions.conditions[a.key];
    if (!spec) { errs.push('unknown condition ' + a.key); return; }
    const t = spec.value.type;
    if (t === 'array' && (!Array.isArray(a.value) || a.value.length === 0)) errs.push(a.key + ' needs a value');
    else if ((t === 'integer' || t === 'number') && (a.value === '' || a.value === null || isNaN(a.value))) errs.push(a.key + ' needs a number');
    else if (t === 'string' && !a.value) errs.push(a.key + ' needs a value');
  });
  if (m.decisionMode === 'flat' && !m.decision) errs.push('decision required');
  return errs;
}

/* ----------------------------------------------------------------- render */

function el(tag, props = {}, children = []) {
  const e = document.createElement(tag);
  Object.entries(props).forEach(([k, v]) => {
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) e.setAttribute(k, v);
  });
  (Array.isArray(children) ? children : [children]).forEach(c => {
    if (c == null) return;
    e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  });
  return e;
}
function option(value, label, selected) {
  return el('option', { value, ...(selected ? { selected: 'selected' } : {}) }, label || value);
}
function pillClass(dec) { return ['hot', 'warm', 'drop'].includes(dec) ? dec : 'other'; }

function conditionKeys() {
  // authoring keys: exclude compile-time/negate keys from the picker (they belong
  // to the budget circuit-breaker rule), but keep them if already present.
  return Object.entries(state.conditions.conditions)
    .filter(([, s]) => !s.compile_time && !s.negates_family)
    .map(([k]) => k);
}

function renderAtom(m, a, ai) {
  const keySel = el('select', {
    onchange: e => { a.key = e.target.value; a.value = defaultValueFor(a.key); render(); },
  }, [
    option('', '— condition —', !a.key),
    option('__true__', '(always match)', a.key === '__true__'),
    ...conditionKeys().map(k => option(k, k, a.key === k)),
  ]);

  const nodes = [keySel];
  if (a.key && a.key !== '__true__') {
    const spec = state.conditions.conditions[a.key];
    nodes.push(el('span', { class: 'sig' }, spec.signals.join('/')));
    nodes.push(renderValueInput(spec, a));
  }
  nodes.push(el('button', { class: 'btn icon danger', title: 'remove condition',
    onclick: () => { m.atoms.splice(ai, 1); render(); } }, '×'));
  return el('div', { class: 'atom' }, nodes);
}

function defaultValueFor(key) {
  const t = valueType(key);
  if (t === 'boolean') return true;
  if (t === 'array') return [];
  if (t === 'integer' || t === 'number') return 500;
  if (t === 'string') return (state.conditions.conditions[key].value.enum || [''])[0];
  return true;
}
function renderValueInput(spec, a) {
  const t = spec.value.type;
  if (t === 'boolean') {
    return el('select', { onchange: e => { a.value = e.target.value === 'true'; refreshSide(); } },
      [option('true', 'true', a.value === true), option('false', 'false', a.value === false)]);
  }
  if (t === 'integer' || t === 'number') {
    return el('input', { type: 'number', value: a.value ?? '', style: 'width:90px',
      oninput: e => { a.value = e.target.value === '' ? '' : Number(e.target.value); refreshSide(); } });
  }
  if (t === 'string') {
    return el('select', { onchange: e => { a.value = e.target.value; refreshSide(); } },
      (spec.value.enum || []).map(v => option(v, v, a.value === v)));
  }
  if (t === 'array') {
    const cur = Array.isArray(a.value) ? a.value : [];
    const sel = el('select', { multiple: 'multiple', size: Math.min(4, (spec.value.item_enum || []).length),
      onchange: e => { a.value = [...e.target.selectedOptions].map(o => o.value); refreshSide(); } },
      (spec.value.item_enum || []).map(v => option(v, v, cur.includes(v))));
    return sel;
  }
  return el('span');
}

function renderDecision(m) {
  const modeRow = el('div', { class: 'dec-mode' }, [
    el('label', {}, [el('input', { type: 'radio', name: 'dm-' + m.uid, ...(m.decisionMode === 'flat' ? { checked: 'checked' } : {}),
      onchange: () => { m.decisionMode = 'flat'; render(); } }), ' flat']),
    el('label', {}, [el('input', { type: 'radio', name: 'dm-' + m.uid, ...(m.decisionMode === 'by_tier' ? { checked: 'checked' } : {}),
      onchange: () => { m.decisionMode = 'by_tier'; render(); } }), ' by tier']),
  ]);
  let body;
  if (m.decisionMode === 'flat') {
    body = el('select', { onchange: e => { m.decision = e.target.value; refreshSide(); } },
      state.conditions.decisions.flat.map(d => option(d, d, m.decision === d)));
  } else {
    body = el('div', { class: 'by-tier' }, state.conditions.tiers.map(t =>
      el('div', {}, [el('label', {}, t),
        el('select', { onchange: e => { m.byTier[t] = e.target.value; refreshSide(); } },
          state.conditions.decisions.by_tier.map(d => option(d, d, m.byTier[t] === d)))])));
  }
  return el('div', { class: 'field' }, [el('label', {}, 'decision'), modeRow, body]);
}

function ruleSummary(m) {
  const parts = m.atoms.filter(a => a.key).map(a => {
    if (a.key === '__true__') return 'always';
    const v = Array.isArray(a.value) ? a.value.join('/') : String(a.value);
    return `${a.key}=${v}`;
  });
  const cond = parts.length ? `${m.combine === 'and' ? 'all' : m.combine.replace('_', ' ')} of [${parts.join(', ')}]` : 'always';
  const dec = m.decisionMode === 'flat'
    ? m.decision
    : state.conditions.tiers.map(t => `${t}:${m.byTier[t]}`).join(', ');
  const signals = new Set();
  m.atoms.forEach(a => { const s = state.conditions.conditions[a.key]; if (s) s.signals.forEach(x => signals.add(x)); });
  const sig = signals.size && signals.size < 3 ? ` (affects ${[...signals].join('/')} only)` : '';
  return `IF ${cond} → ${dec}${sig}`;
}

function renderRule(m, idx, allIds) {
  const errs = validateRule(m, allIds);
  const dec = m.decisionMode === 'flat' ? m.decision : 'by-tier';
  const head = el('div', { class: 'rule-head' }, [
    el('span', { class: 'rule-idx' }, String(idx + 1)),
    el('input', { class: 'id', value: m.id, placeholder: 'rule-id',
      oninput: e => { m.id = e.target.value; refreshSide(); } }),
    el('span', { class: 'pill ' + pillClass(dec) }, dec),
    el('div', { class: 'rule-actions' }, [
      el('button', { class: 'btn icon', title: 'move up', onclick: () => move(idx, -1) }, '↑'),
      el('button', { class: 'btn icon', title: 'move down', onclick: () => move(idx, 1) }, '↓'),
      el('button', { class: 'btn icon danger', title: 'delete', onclick: () => { state.rules.splice(idx, 1); render(); } }, '🗑'),
    ]),
  ]);

  const combineSel = el('div', { class: 'combine-row' }, [
    el('span', { class: 'hint' }, 'match'),
    el('select', { onchange: e => { m.combine = e.target.value; refreshSide(); } }, [
      option('and', 'all of (AND)', m.combine === 'and'),
      option('any_of', 'any of (OR)', m.combine === 'any_of'),
      option('all_of', 'all of (explicit)', m.combine === 'all_of'),
    ]),
    el('button', { class: 'btn icon', onclick: () => { m.atoms.push({ key: '', value: null }); render(); } }, '+ condition'),
  ]);
  const whenBox = el('div', { class: 'when-box' }, [combineSel, ...m.atoms.map((a, ai) => renderAtom(m, a, ai))]);

  const reason = el('div', { class: 'field' }, [el('label', {}, 'reason (audit)'),
    el('textarea', { oninput: e => { m.reason = e.target.value; refreshSide(); } }, m.reason)]);

  const summary = el('div', { class: 'summary', id: 'sum-' + m.uid }, ruleSummary(m));
  const errBox = el('div', { class: 'err-text', id: 'err-' + m.uid }, errs.join(' · '));

  const rule = el('div', {
    class: 'rule' + (idx === state.selected ? ' selected' : '') + (errs.length ? ' invalid' : ''),
    onclick: () => { state.selected = idx; markSelected(); },
  }, [head, el('div', { class: 'field' }, [el('label', {}, 'when'), whenBox]), renderDecision(m), reason, summary, errBox]);
  return rule;
}

function move(idx, d) {
  const j = idx + d;
  if (j < 0 || j >= state.rules.length) return;
  [state.rules[idx], state.rules[j]] = [state.rules[j], state.rules[idx]];
  if (state.selected === idx) state.selected = j;
  render();
}
function markSelected() {
  [...document.querySelectorAll('.rule')].forEach((r, i) => r.classList.toggle('selected', i === state.selected));
}

function renderCatalog() {
  const box = document.getElementById('catalog');
  box.innerHTML = '';
  if (!state.catalog) return;
  const rows = state.catalog.services.map(s => el('tr', {}, [
    el('td', {}, s.name),
    el('td', { class: 'tier-' + s.tier }, s.tier),
    el('td', {}, s.team),
    el('td', {}, s.compliance_hold ? '🔒' : ''),
  ]));
  box.appendChild(el('table', {}, [
    el('tr', {}, [el('th', {}, 'service'), el('th', {}, 'tier'), el('th', {}, 'team'), el('th', {}, 'hold')]),
    ...rows,
  ]));
}

function refreshSide() {
  // preview + validation + per-rule summaries, without a full re-render (keeps focus)
  document.getElementById('yamlPreview').textContent = buildRoutingYaml();
  const allIds = state.rules.map(r => r.id);
  let bad = 0;
  state.rules.forEach(m => {
    const errs = validateRule(m, allIds);
    if (errs.length) bad++;
    const s = document.getElementById('sum-' + m.uid); if (s) s.textContent = ruleSummary(m);
    const er = document.getElementById('err-' + m.uid); if (er) er.textContent = errs.join(' · ');
  });
  const badge = document.getElementById('validBadge');
  badge.className = 'valid ' + (bad ? 'bad' : 'ok');
  badge.textContent = bad ? `${bad} rule(s) with issues` : 'valid';
}

function render() {
  const host = document.getElementById('rules');
  host.innerHTML = '';
  const allIds = state.rules.map(r => r.id);
  state.rules.forEach((m, i) => host.appendChild(renderRule(m, i, allIds)));

  const dd = document.getElementById('defaultDecision');
  dd.innerHTML = '';
  ['hot', 'warm', 'drop'].forEach(d => dd.appendChild(option(d, d, state.defaultDecision === d)));
  dd.onchange = e => { state.defaultDecision = e.target.value; refreshSide(); };

  renderCatalog();
  refreshSide();
}

/* ----------------------------------------------------------------- export */

function download(name, text) {
  const blob = new Blob([text], { type: 'text/yaml' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  URL.revokeObjectURL(a.href);
}
async function copy(text, btn) {
  try { await navigator.clipboard.writeText(text); flash(btn, 'copied ✓'); }
  catch { flash(btn, 'copy failed'); }
}
function flash(btn, msg) {
  const old = btn.textContent; btn.textContent = msg;
  setTimeout(() => { btn.textContent = old; }, 1400);
}

function wireExport() {
  document.getElementById('addRule').addEventListener('click', () => {
    state.rules.push(ruleToModel({ id: '', when: {}, decision: 'warm', reason: '' }));
    state.selected = state.rules.length - 1;
    render();
  });
  document.getElementById('downloadYaml').addEventListener('click', () => download('routing-policy.yaml', buildRoutingYaml()));
  document.getElementById('copyYaml').addEventListener('click', e => copy(buildRoutingYaml(), e.target));
  document.getElementById('copyRuleJson').addEventListener('click', e => {
    const m = state.rules[state.selected];
    if (!m) return;
    copy(JSON.stringify(modelToRule(m), null, 2), e.target);
  });
}

wireExport();
boot();
