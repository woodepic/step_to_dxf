/* plynest browser client: upload, configure, nest, preview, export. */
'use strict';

const MM_PER_IN = 25.4;
const $ = (id) => document.getElementById(id);

const state = {
  uploadId: null,
  runId: null,
  layout: null,
  sheet: 0,
  view: { x: 0, y: 0, scale: 1 },
  unit: 'in',
};

/* ---------- units ---------------------------------------------------- */
const toMm = (v) => (state.unit === 'in' ? v * MM_PER_IN : v);
const fromMm = (v) => (state.unit === 'in' ? v / MM_PER_IN : v);
const fmt = (mm, dp) => fromMm(mm).toFixed(dp === undefined ? (state.unit === 'in' ? 3 : 1) : dp);

/* Fields that hold a length, so a unit switch can rewrite them all. */
const LENGTH_FIELDS = ['sheet-w', 'sheet-h', 'kerf', 'keepout', 'label-h', 'label-d',
                       'label-margin', 'label-clear'];

const DEFAULTS_MM = {
  'sheet-w': 48 * MM_PER_IN, 'sheet-h': 96 * MM_PER_IN,
  'kerf': 6.35, 'keepout': 25.4,
  'label-h': 6.0, 'label-d': 1.0, 'label-margin': 6.0, 'label-clear': 1.5,
};

function decimalsFor(id) {
  if (state.unit === 'mm') return ['kerf', 'label-d', 'label-clear'].includes(id) ? 2 : 1;
  return ['label-d', 'kerf'].includes(id) ? 4 : 3;
}

function writeLengths(valuesMm) {
  LENGTH_FIELDS.forEach((id) => {
    $(id).value = Number(fromMm(valuesMm[id]).toFixed(decimalsFor(id)));
    $(id).step = state.unit === 'in' ? 0.001 : 0.1;
  });
}

function readLengthsMm() {
  const out = {};
  LENGTH_FIELDS.forEach((id) => { out[id] = toMm(parseFloat($(id).value) || 0); });
  return out;
}

function setUnit(next) {
  const current = readLengthsMm();
  state.unit = next;
  writeLengths(current);
  render();
}

/* ---------- settings -------------------------------------------------- */
function collectSettings() {
  const mm = readLengthsMm();
  return {
    nest: {
      kerf_mm: mm['kerf'],
      edge_keepout_mm: mm['keepout'],
      rotation: $('rotation').value,
      attempts: parseInt($('attempts').value, 10) || 6,
      sheet: { width_mm: mm['sheet-w'], height_mm: mm['sheet-h'] },
    },
    labels: {
      enabled: $('labels-on').checked,
      style: $('label-style').value,
      height_mm: mm['label-h'],
      depth_mm: mm['label-d'],
      corner: $('label-corner').value,
      margin_mm: mm['label-margin'],
      clearance_mm: mm['label-clear'],
      uppercase: $('label-upper').checked,
    },
    export: { unit: $('ex-unit').value },
  };
}

/* ---------- upload ---------------------------------------------------- */
async function uploadFile(file) {
  const info = $('upload-info');
  info.className = 'hint';
  info.textContent = `Uploading ${file.name}…`;
  const body = new FormData();
  body.append('file', file);
  try {
    const res = await fetch('/api/upload', { method: 'POST', body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
    state.uploadId = data.upload_id;
    info.textContent = `${data.filename} — ${(data.bytes / 1048576).toFixed(1)} MB`;
    $('drop-text').textContent = data.filename;
    $('run').disabled = false;
  } catch (err) {
    info.className = 'hint err';
    info.textContent = err.message;
  }
}

/* ---------- run ------------------------------------------------------- */
async function startRun() {
  if (!state.uploadId) return;
  $('run').disabled = true;
  $('progress').hidden = false;
  $('export-card').hidden = true;
  setProgress('Starting…', 0.01);

  const res = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ upload_id: state.uploadId, settings: collectSettings() }),
  });
  const data = await res.json();
  if (!res.ok) { fail(data.detail || 'Could not start the run'); return; }
  state.runId = data.run_id;
  poll();
}

function setProgress(stage, frac) {
  $('bar').style.width = `${Math.round(frac * 100)}%`;
  $('stage').textContent = stage;
}

function fail(message) {
  setProgress(message, 1);
  $('stage').style.color = 'var(--cut)';
  $('run').disabled = false;
}

async function poll() {
  const res = await fetch(`/api/run/${state.runId}`);
  const data = await res.json();
  if (data.stage === 'error') { fail(data.error); return; }
  setProgress(data.stage, data.progress);
  if (data.stage !== 'done') { setTimeout(poll, 350); return; }

  const layout = await (await fetch(`/api/run/${state.runId}/layout`)).json();
  state.layout = layout;
  state.sheet = 0;
  $('run').disabled = false;
  $('export-card').hidden = false;
  $('progress').hidden = true;
  buildTabs();
  // Defer the first fit: adding the sheet tabs can wrap the toolbar onto a
  // second row, which changes the height we are fitting into.
  requestAnimationFrame(fitView);
  showWarnings(layout.warnings.concat(
    layout.unplaced.map((u) => `${u.label}: NOT PLACED — ${u.reason}`)));
}

/* ---------- viewer ---------------------------------------------------- */
function buildTabs() {
  const tabs = $('sheet-tabs');
  tabs.innerHTML = '';
  state.layout.sheets.forEach((sheet, i) => {
    const b = document.createElement('button');
    b.className = 'tab' + (i === state.sheet ? ' on' : '');
    b.textContent = `${i + 1} · ${fmt(sheet.thickness_mm, state.unit === 'in' ? 3 : 1)}${state.unit}`;
    b.onclick = () => { state.sheet = i; buildTabs(); fitView(); };
    tabs.appendChild(b);
  });
}

function currentSheet() {
  return state.layout ? state.layout.sheets[state.sheet] : null;
}

function fitView() {
  const sheet = currentSheet();
  if (!sheet) return;
  const wrap = $('stage-wrap').getBoundingClientRect();
  const pad = 26;
  const scale = Math.min((wrap.width - pad * 2) / sheet.width_mm,
                         (wrap.height - pad * 2) / sheet.height_mm);
  state.view.scale = scale;
  state.view.x = (wrap.width - sheet.width_mm * scale) / 2;
  state.view.y = (wrap.height - sheet.height_mm * scale) / 2;
  render();
}

const svgNS = 'http://www.w3.org/2000/svg';
function el(name, attrs) {
  const node = document.createElementNS(svgNS, name);
  for (const k in attrs) node.setAttribute(k, attrs[k]);
  return node;
}
const path = (ring, close) =>
  ring.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join(' ')
  + (close ? ' Z' : '');

function render() {
  const svg = $('svg');
  svg.innerHTML = '';
  const sheet = currentSheet();
  if (!sheet) return;

  const { x, y, scale } = state.view;
  const wrap = $('stage-wrap').getBoundingClientRect();
  // Flip Y so the DXF's Y-up geometry reads the right way round on screen.
  const g = el('g', {
    transform: `translate(${x} ${y + sheet.height_mm * scale}) scale(${scale} ${-scale})`,
  });
  svg.setAttribute('viewBox', `0 0 ${wrap.width} ${wrap.height}`);

  g.appendChild(el('rect', {
    class: 'sheet-rect', x: 0, y: 0, width: sheet.width_mm, height: sheet.height_mm,
  }));
  if ($('v-keepout').checked) {
    const [kx0, ky0, kx1, ky1] = sheet.usable;
    g.appendChild(el('rect', {
      class: 'keepout-rect', x: kx0, y: ky0, width: kx1 - kx0, height: ky1 - ky0,
    }));
  }

  const showPockets = $('v-pockets').checked;
  const showHoles = $('v-holes').checked;
  const showLabels = $('v-labels').checked;

  sheet.parts.forEach((part) => {
    const node = el('path', { class: 'part', d: path(part.outline, true) });
    node.appendChild(el('title', {})).textContent =
      `${part.label}\n${fmt(part.width_mm)} × ${fmt(part.height_mm)} ${state.unit}`
      + `\nrotated ${part.angle}°${part.flipped ? ' · flipped face-up' : ''}`;
    g.appendChild(node);

    if (showPockets) {
      part.pockets.forEach((pocket) => {
        const d = pocket.rings.map((r) => path(r, true)).join(' ');
        const p = el('path', { class: 'pocket', d, 'fill-rule': 'evenodd' });
        p.appendChild(el('title', {})).textContent =
          `${part.label} — pocket ${fmt(pocket.depth)} ${state.unit} deep`;
        g.appendChild(p);
      });
    }
    if (showHoles) {
      part.holes.forEach((hole) => g.appendChild(el('path', { class: 'hole', d: path(hole, true) })));
    }
    if (showLabels) {
      part.label_strokes.forEach((s) =>
        g.appendChild(el('path', { class: 'labelstroke', d: path(s, false) })));
    }
  });

  svg.appendChild(g);

  const s = state.layout.summary;
  $('sheet-info').textContent =
    `Sheet ${state.sheet + 1} of ${sheet_count()} · ${sheet.parts.length} parts · `
    + `${fmt(sheet.thickness_mm, state.unit === 'in' ? 3 : 1)} ${state.unit} stock · `
    + `${(sheet.utilisation * 100).toFixed(1)}% used`
    + (sheet.pocket_depths.length
        ? ` · pocket depths ${sheet.pocket_depths.map((d) => fmt(d)).join(', ')} ${state.unit}`
        : '')
    + ` — job total ${s.parts} parts, ${s.sheets} sheets, ${(s.utilisation * 100).toFixed(1)}% material used`;
}

const sheet_count = () => state.layout.sheets.length;

/* pan and zoom */
(function panZoom() {
  const svg = $('svg');
  let dragging = false, lastX = 0, lastY = 0;
  svg.addEventListener('mousedown', (e) => {
    dragging = true; lastX = e.clientX; lastY = e.clientY; svg.classList.add('drag');
  });
  addEventListener('mouseup', () => { dragging = false; svg.classList.remove('drag'); });
  addEventListener('mousemove', (e) => {
    if (!dragging) return;
    state.view.x += e.clientX - lastX;
    state.view.y += e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    render();
  });
  svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = svg.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const k = Math.exp(-e.deltaY * 0.0015);
    state.view.x = mx - (mx - state.view.x) * k;
    state.view.y = my - (my - state.view.y) * k;
    state.view.scale *= k;
    render();
  }, { passive: false });
})();

/* ---------- export ---------------------------------------------------- */
async function doExport() {
  const info = $('export-info');
  info.className = 'hint';
  info.textContent = 'Writing DXF…';
  const settings = {
    unit: $('ex-unit').value,
    mode: $('ex-mode').value,
    include_labels: $('ex-labels').checked,
    include_sheet_outline: $('ex-outline').checked,
    include_keepout: $('ex-keepout').checked,
  };
  const res = await fetch(`/api/run/${state.runId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings }),
  });
  const data = await res.json();
  if (!res.ok) { info.className = 'hint err'; info.textContent = data.detail; return; }
  info.textContent = `${data.files.length} file(s) ready — downloading ${data.zip}`;
  location.href = data.download;
}

/* ---------- warnings -------------------------------------------------- */
function showWarnings(list) {
  const box = $('warnings');
  if (!list.length) { box.hidden = true; return; }
  $('warn-list').innerHTML = '';
  list.forEach((w) => {
    const li = document.createElement('li');
    li.textContent = w;
    $('warn-list').appendChild(li);
  });
  box.hidden = false;
}

/* ---------- wiring ---------------------------------------------------- */
(function init() {
  writeLengths(DEFAULTS_MM);
  $('attempts').value = 6;

  const drop = $('drop');
  drop.onclick = () => $('file').click();
  $('file').onchange = (e) => e.target.files[0] && uploadFile(e.target.files[0]);
  ['dragenter', 'dragover'].forEach((t) =>
    drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((t) =>
    drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => e.dataTransfer.files[0] && uploadFile(e.dataTransfer.files[0]));

  $('unit').onchange = (e) => { setUnit(e.target.value); $('ex-unit').value = e.target.value; };
  $('run').onclick = startRun;
  $('export').onclick = doExport;
  $('fit').onclick = fitView;
  $('warn-close').onclick = () => { $('warnings').hidden = true; };
  $('labels-on').onchange = (e) => { $('label-opts').style.opacity = e.target.checked ? 1 : .45; };
  ['v-labels', 'v-pockets', 'v-holes', 'v-keepout'].forEach((id) => { $(id).onchange = render; });
  addEventListener('resize', () => state.layout && render());
})();
