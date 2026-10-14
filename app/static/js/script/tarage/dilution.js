/* Discharge by salt dilution (/tarage/dilution).
   Config and translated strings come from window.TARAGE (set by the template). */
const API = window.TARAGE.api;
const T = window.TARAGE.i18n;

/* ══════════════════════════════════════════
   Range colour palette
══════════════════════════════════════════ */
const RANGE_FILL = [
    'rgba(50,  115, 220, 0.18)',
    'rgba(72,  199, 116, 0.18)',
    'rgba(241,  70, 104, 0.18)',
    'rgba(255, 183,  15, 0.18)',
    'rgba(130,  56, 220, 0.18)',
];
const RANGE_STROKE = ['#3273dc', '#48c774', '#f14668', '#ffb70f', '#8238dc'];


/* ══════════════════════════════════════════
   Global state
══════════════════════════════════════════ */
// Steps 1-3
let opId = null;
let datastreams = [];
let things = [];

// OpenLayers (Thing modal)
let olMap = null;
let olMarkerSrc = null;

// CSV modal
let csvData = [];       // [[Date, number], ...]
let csvRanges = [];     // [{start: Date, end: Date}, ...]
let lastDebits = [];    // results of the last calculation
let addingRange = false;
let pendingStart = null;   // Date, start point waiting for its end
let dyGraph = null;


/* ══════════════════════════════════════════
   Init
══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
    // Clear the inputs on load (the browser may restore them after F5)
    document.getElementById('calc-form').reset();

    setupThingModal();
    setupCsvModal();
    setupThingSelect();
    setupCalcForm();
    setupPublishBtn();
    updateStatusBar('normal');
    updateRangesList();
    stepInit();
});

// POST helper: JWT cookie + CSRF double-submit header
function postOptions(body, extraHeaders = {}) {
    const csrf = (document.cookie.match(/csrf_access_token=([^;]+)/) || [])[1];
    return {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRF-TOKEN': csrf, ...extraHeaders },
        body,
    };
}

// "{n}" / "{id}" placeholders of the translated strings
function fmt(str, values) {
    return str.replace(/\{(\w+)\}/g, (m, k) => (k in values ? values[k] : m));
}


/* ══════════════════════════════════════════
   STEPS 1+2: ObservedProperty & Datastreams
══════════════════════════════════════════ */
async function stepInit() {
    setProgress('step-1-progress', true);
    try {
        const resp = await fetch(`${API}/init`, { credentials: 'same-origin' });
        const data = await resp.json();
        setProgress('step-1-progress', false);

        if (!resp.ok) {
            setStepBadge(1, 'danger', T.error);
            setMsg('step-1-msg', data.error, 'danger');
            return;
        }

        opId = data.op_id;
        datastreams = data.datastreams;
        setStepBadge(1, 'success', fmt(T.opId, { id: opId }));

        await stepLoadThings();
        // No gauging site yet: start by creating one
        if (things.length === 0) {
            openThingModal();
        }
    } catch (e) {
        setProgress('step-1-progress', false);
        setStepBadge(1, 'danger', T.networkError);
        setMsg('step-1-msg', T.serverUnreachable, 'danger');
    }
}


/* ══════════════════════════════════════════
   STEP 2: load the Things
══════════════════════════════════════════ */
async function stepLoadThings() {
    reveal('step-2');
    const params = new URLSearchParams();
    datastreams.forEach(ds => params.append('ds_ids', ds['@iot.id']));
    try {
        const resp = await fetch(`${API}/things?${params}`, { credentials: 'same-origin' });
        const data = await resp.json();
        things = data.things || [];
        populateThingSelect(things);
    } catch (e) {
        const msg = document.getElementById('step-2-msg');
        msg.textContent = T.sitesLoadError;
        msg.classList.remove('is-hidden');
    }
}

function populateThingSelect(thingList, preselect = null) {
    const sel = document.getElementById('thing-select');
    sel.innerHTML = '';
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = T.chooseSite;
    sel.appendChild(empty);
    thingList.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.id;
        opt.textContent = t.name;
        sel.appendChild(opt);
    });
    if (preselect !== null) {
        sel.value = String(preselect);
        sel.dispatchEvent(new Event('change'));
    }
}

function setupThingSelect() {
    document.getElementById('thing-select').addEventListener('change', function () {
        if (this.value) reveal('step-3');
        else document.getElementById('step-3').classList.add('is-hidden');
    });
}


/* ══════════════════════════════════════════
   MASSES: single value vs one per range
══════════════════════════════════════════ */
function isMultiMassMode() {
    return document.getElementById('toggle-masses-multi').checked;
}

function renderMassInputs() {
    const multiWrap = document.getElementById('masses-multi-wrap');
    const uniqueWrap = document.getElementById('masse-unique-wrap');
    const multi = isMultiMassMode();

    uniqueWrap.classList.toggle('is-hidden', multi);
    document.getElementById('masse-sel').required = !multi;
    multiWrap.classList.toggle('is-hidden', !multi);

    if (!multi) return;

    const singleVal = document.getElementById('masse-sel').value;
    multiWrap.innerHTML = csvRanges.length === 0
        ? `<p class="is-size-7 has-text-grey">${T.defineRangesFirst}</p>`
        : csvRanges.map((r, i) => `
            <div class="field is-grouped is-align-items-center mb-2">
                <span class="tag mr-2"
                      style="background:${RANGE_STROKE[i % RANGE_STROKE.length]};color:white;min-width:70px;">
                    ${fmt(T.range, { n: i + 1 })}
                </span>
                <div class="control" style="flex:1;max-width:180px;">
                    <input class="input is-small" type="number" step="0.1" placeholder="500"
                           id="masse-plage-${i}" value="${singleVal}" required>
                </div>
                <span class="is-size-7 has-text-grey ml-2">g</span>
            </div>
        `).join('');
}

function getMassesList() {
    if (!isMultiMassMode()) {
        const v = parseFloat(document.getElementById('masse-sel').value);
        return csvRanges.map(() => v);
    }
    return csvRanges.map((_, i) => {
        const el = document.getElementById(`masse-plage-${i}`);
        return el ? parseFloat(el.value) : 0;
    });
}


/* ══════════════════════════════════════════
   STEP 3: calculation form
══════════════════════════════════════════ */
function setupCalcForm() {
    document.getElementById('toggle-masses-multi').addEventListener('change', renderMassInputs);

    // Open the CSV modal as soon as a file is selected
    document.getElementById('csv-file').addEventListener('change', function () {
        if (!this.files[0]) return;
        const reader = new FileReader();
        reader.onload = e => {
            csvData = parseCsvData(e.target.result);
            if (csvData.length === 0) {
                alert(T.csvReadError);
                this.value = '';
                return;
            }
            csvRanges = [];
            openCsvModal();
        };
        reader.readAsText(this.files[0]);
    });

    document.getElementById('btn-edit-ranges').addEventListener('click', openCsvModal);

    document.getElementById('calc-form').addEventListener('submit', async e => {
        e.preventDefault();
        const btn = document.getElementById('calc-btn');
        const result = document.getElementById('calc-result');
        btn.classList.add('is-loading');
        result.classList.add('is-hidden');

        const formData = new FormData();
        formData.append('thing_id', document.getElementById('thing-select').value);
        formData.append('masse_sel', JSON.stringify(getMassesList()));
        formData.append('delta_t', document.getElementById('delta-t').value);
        formData.append('csv_file', document.getElementById('csv-file').files[0]);
        formData.append('ranges', JSON.stringify(
            csvRanges.map(r => ({ start: toLocalISOString(r.start), end: toLocalISOString(r.end) }))
        ));

        try {
            const resp = await fetch(`${API}/calculate`, postOptions(formData));
            const data = await resp.json();
            result.className = '';   // reset classes
            if (resp.ok) {
                result.innerHTML = buildResultsHTML(data);
                lastDebits = data.debit;
                reveal('step-4');
            } else {
                result.classList.add('notification', 'is-danger');
                result.textContent = data.error || T.calcError;
            }
        } catch (err) {
            result.className = 'notification is-danger';
            result.textContent = T.networkErrorDot;
        } finally {
            btn.classList.remove('is-loading');
        }
    });
}


/* ══════════════════════════════════════════
   CSV PARSING
══════════════════════════════════════════ */
function parseCsvData(text) {
    const lines = text.trim().split(/\r?\n/);
    if (lines.length < 2) return [];

    // Column order detected from the header
    const headers = lines[0].split(',').map(h => h.trim().replace(/"/g, '').toLowerCase());
    const dateIdx = headers.findIndex(h => h === 'date' || h === 'time' || h === 'datetime');
    const resultIdx = headers.findIndex(h => h === 'result' || h === 'value' || h === 'valeur');

    // Fallback: column 0 = date, column 1 = result
    const iDate = dateIdx >= 0 ? dateIdx : 0;
    const iResult = resultIdx >= 0 ? resultIdx : (iDate === 0 ? 1 : 0);

    const data = [];
    for (let i = 1; i < lines.length; i++) {
        const parts = lines[i].split(',');
        if (parts.length < 2) continue;
        const dateStr = parts[iDate].trim().replace(/"/g, '');
        const val = parseFloat(parts[iResult].trim().replace(/"/g, ''));
        const date = autoParseDate(dateStr);
        if (date && !isNaN(val)) data.push([date, val]);
    }
    return data.sort((a, b) => a[0] - b[0]);
}

function autoParseDate(str) {
    // DD/MM/YYYY HH:MM or DD/MM/YYYY HH:MM:SS
    let m = str.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?$/);
    if (m) return new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5], +(m[6] || 0));

    // YYYY-MM-DD HH:MM or ISO
    const d = new Date(str);
    return isNaN(d) ? null : d;
}


/* ══════════════════════════════════════════
   CSV MODAL: open / close
══════════════════════════════════════════ */
function setupCsvModal() {
    document.getElementById('csv-modal-close').addEventListener('click', closeCsvModal);
    document.getElementById('csv-modal-cancel').addEventListener('click', closeCsvModal);
    document.getElementById('csv-modal-validate').addEventListener('click', validateCsvRanges);
    document.getElementById('btn-add-range').addEventListener('click', toggleAddingRange);
    document.getElementById('btn-reset-ranges').addEventListener('click', resetRanges);
    document.getElementById('btn-manual-add').addEventListener('click', addManualRange);
}

function openCsvModal() {
    document.getElementById('modal-csv').classList.add('is-active');
    document.body.style.overflow = 'hidden';
    cancelAddingRange();
    updateStatusBar('normal');
    updateRangesList();
    // Dygraph needs a visible container to compute its size
    setTimeout(() => initDygraph(csvData), 60);
}

function closeCsvModal() {
    document.getElementById('modal-csv').classList.remove('is-active');
    document.body.style.overflow = '';
    cancelAddingRange();
}

function validateCsvRanges() {
    if (csvRanges.length === 0) {
        setStatusBar('warning', T.atLeastOneRange);
        return;
    }
    closeCsvModal();
    updateRangesSummary();
}


/* ══════════════════════════════════════════
   DYGRAPH
══════════════════════════════════════════ */
function initDygraph(data) {
    if (dyGraph) { dyGraph.destroy(); dyGraph = null; }

    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    dyGraph = new Dygraph(
        document.getElementById('csv-chart'),
        data,
        {
            labels: ['Date', T.conductivity],
            ylabel: T.conductivityAxis,
            axisLabelFontSize: 11,
            strokeWidth: 1.5,
            color: '#5b9cf6',
            highlightCircleSize: 1,
            axisLabelColor: dark ? '#cccccc' : '#363636',
            axisLineColor: dark ? 'rgba(255,255,255,0.4)' : 'black',
            gridLineColor: dark ? 'rgba(255,255,255,0.12)' : 'rgb(128,128,128)',
            clickCallback: onChartClick,
            underlayCallback: drawRangeBands,
        }
    );
}

function onChartClick(event, x /*, points */) {
    if (!addingRange) return;
    const clicked = new Date(x);

    if (pendingStart === null) {
        // First click: start of the range
        pendingStart = clicked;
        updateStatusBar('waiting-end');
        dyGraph.updateOptions({});  // redraw the start marker
    } else {
        // Second click: end of the range
        const start = pendingStart < clicked ? pendingStart : clicked;
        const end = pendingStart < clicked ? clicked : pendingStart;
        csvRanges.push({ start, end });

        pendingStart = null;
        addingRange = false;
        document.getElementById('csv-chart').style.cursor = '';
        const btn = document.getElementById('btn-add-range');
        btn.textContent = T.addRange;
        btn.classList.remove('is-warning');
        btn.classList.add('is-primary');

        updateStatusBar('normal');
        updateRangesList();
        dyGraph.updateOptions({});
    }
}

function drawRangeBands(canvas, area, g) {
    // One coloured band per validated range
    csvRanges.forEach((r, i) => {
        const x1 = g.toDomXCoord(r.start.getTime());
        const x2 = g.toDomXCoord(r.end.getTime());
        canvas.fillStyle = RANGE_FILL[i % RANGE_FILL.length];
        canvas.fillRect(x1, area.y, x2 - x1, area.h);
    });

    // Dashed line for the pending start
    if (pendingStart !== null) {
        const x = g.toDomXCoord(pendingStart.getTime());
        canvas.save();
        canvas.strokeStyle = '#f14668';
        canvas.lineWidth = 2;
        canvas.setLineDash([5, 3]);
        canvas.beginPath();
        canvas.moveTo(x, area.y);
        canvas.lineTo(x, area.y + area.h);
        canvas.stroke();
        canvas.restore();
    }
}


/* ══════════════════════════════════════════
   RANGE MANAGEMENT
══════════════════════════════════════════ */
function toggleAddingRange() {
    if (addingRange) {
        cancelAddingRange();
    } else {
        addingRange = true;
        pendingStart = null;
        const btn = document.getElementById('btn-add-range');
        btn.textContent = T.cancel;
        btn.classList.remove('is-primary');
        btn.classList.add('is-warning');
        document.getElementById('csv-chart').style.cursor = 'crosshair';
        updateStatusBar('waiting-start');
    }
}

function cancelAddingRange() {
    addingRange = false;
    pendingStart = null;
    const btn = document.getElementById('btn-add-range');
    if (btn) {
        btn.textContent = T.addRange;
        btn.classList.remove('is-warning');
        btn.classList.add('is-primary');
    }
    const chart = document.getElementById('csv-chart');
    if (chart) chart.style.cursor = '';
    if (dyGraph) dyGraph.updateOptions({});
}

function deleteRange(idx) {
    csvRanges.splice(idx, 1);
    updateRangesList();
    if (dyGraph) dyGraph.updateOptions({});
}

function resetRanges() {
    csvRanges = [];
    cancelAddingRange();
    updateRangesList();
}

function addManualRange() {
    const startVal = document.getElementById('manual-start').value;
    const endVal = document.getElementById('manual-end').value;
    const errEl = document.getElementById('manual-range-error');
    errEl.classList.add('is-hidden');

    if (!startVal || !endVal) {
        errEl.textContent = T.enterStartEnd;
        errEl.classList.remove('is-hidden');
        return;
    }
    const start = new Date(startVal);
    const end = new Date(endVal);
    if (start >= end) {
        errEl.textContent = T.endAfterStart;
        errEl.classList.remove('is-hidden');
        return;
    }
    csvRanges.push({ start, end });
    document.getElementById('manual-start').value = '';
    document.getElementById('manual-end').value = '';
    updateRangesList();
    if (dyGraph) dyGraph.updateOptions({});
}


/* ══════════════════════════════════════════
   UI UPDATES
══════════════════════════════════════════ */
function updateRangesList() {
    const container = document.getElementById('ranges-list');
    const validateBtn = document.getElementById('csv-modal-validate');

    if (csvRanges.length === 0) {
        container.innerHTML = `<p class="has-text-grey is-size-7 mb-3">${T.noRange}</p>`;
        validateBtn.textContent = T.validate;
        return;
    }

    container.innerHTML = csvRanges.map((r, i) => `
        <div class="p-2 mb-2" style="border-left:3px solid ${RANGE_STROKE[i % RANGE_STROKE.length]};
             background:${RANGE_FILL[i % RANGE_FILL.length]}; border-radius:3px;">
            <div class="is-flex is-justify-content-space-between is-align-items-center mb-1">
                <span class="tag is-small"
                      style="background:${RANGE_STROKE[i % RANGE_STROKE.length]}; color:white;">
                    ${fmt(T.measurement, { n: i + 1 })}
                </span>
                <button class="delete is-small" onclick="deleteRange(${i})"></button>
            </div>
            <p class="is-size-7 mb-0">
                <strong>${T.start}</strong>: ${formatDateFull(r.start)}<br>
                <strong>${T.end}</strong>: ${formatDateFull(r.end)}
            </p>
        </div>
    `).join('');

    const n = csvRanges.length;
    validateBtn.textContent = n > 1 ? fmt(T.validateMany, { n }) : T.validateOne;
}

function updateRangesSummary() {
    const wrap = document.getElementById('ranges-summary-wrap');
    const summary = document.getElementById('ranges-summary');
    const calcBtn = document.getElementById('calc-btn');
    const noRangesMsg = document.getElementById('calc-no-ranges-msg');

    if (csvRanges.length === 0) {
        wrap.classList.add('is-hidden');
        calcBtn.disabled = true;
        noRangesMsg.classList.remove('is-hidden');
        renderMassInputs();
        return;
    }

    summary.innerHTML = csvRanges.map((r, i) => `
        <span class="tag mb-1"
              style="background:${RANGE_STROKE[i % RANGE_STROKE.length]}; color:white;">
            ${fmt(T.measurement, { n: i + 1 })}: ${formatTimeShort(r.start)} → ${formatTimeShort(r.end)}
        </span>
    `).join(' ');

    wrap.classList.remove('is-hidden');
    calcBtn.disabled = false;
    noRangesMsg.classList.add('is-hidden');
    renderMassInputs();
}

function updateStatusBar(mode) {
    setStatusBar(
        mode === 'waiting-start' ? 'warning' :
            mode === 'waiting-end' ? 'danger' : 'info',
        mode === 'waiting-start' ? T.statusStart :
            mode === 'waiting-end' ? T.statusEnd : T.statusNormal
    );
}

function setStatusBar(type, htmlMsg) {
    const bar = document.getElementById('csv-status-bar');
    bar.className = `notification is-${type} is-light py-2 px-3 mb-3`;
    document.getElementById('csv-status-msg').innerHTML = htmlMsg;
}


/* ══════════════════════════════════════════
   MODAL: create a Thing
══════════════════════════════════════════ */
function setupThingModal() {
    document.getElementById('modal-close').addEventListener('click', closeThingModal);
    document.getElementById('modal-cancel').addEventListener('click', closeThingModal);
    document.getElementById('modal-submit').addEventListener('click', submitThing);
    ['thing-lng', 'thing-lat'].forEach(id => {
        document.getElementById(id).addEventListener('change', syncInputsToMap);
    });
    document.getElementById('btn-create-thing-step2').addEventListener('click', () => openThingModal());
}

function openThingModal() {
    document.getElementById('modal-thing').classList.add('is-active');
    setTimeout(initOlMap, 50);
}

function closeThingModal() {
    document.getElementById('modal-thing').classList.remove('is-active');
}

async function submitThing() {
    const name = document.getElementById('thing-name').value.trim();
    const desc = document.getElementById('thing-desc').value.trim();
    const lng = parseFloat(document.getElementById('thing-lng').value);
    const lat = parseFloat(document.getElementById('thing-lat').value);
    const errEl = document.getElementById('modal-error');
    errEl.classList.add('is-hidden');

    if (!name) {
        errEl.textContent = T.siteNameRequired;
        errEl.classList.remove('is-hidden');
        return;
    }
    if (isNaN(lng) || isNaN(lat)) {
        errEl.textContent = T.missingCoords;
        errEl.classList.remove('is-hidden');
        return;
    }

    const btn = document.getElementById('modal-submit');
    btn.classList.add('is-loading');
    try {
        const resp = await fetch(`${API}/thing`, postOptions(
            JSON.stringify({ name, description: desc || name, lng, lat }),
            { 'Content-Type': 'application/json' }
        ));
        const data = await resp.json();
        if (!resp.ok) {
            errEl.textContent = data.error || T.siteCreateError;
            errEl.classList.remove('is-hidden');
            return;
        }
        closeThingModal();
        things.push({ id: data.thing_id, name });
        populateThingSelect(things, data.thing_id);
    } catch (e) {
        errEl.textContent = T.networkErrorDot;
        errEl.classList.remove('is-hidden');
    } finally {
        btn.classList.remove('is-loading');
    }
}


/* ══════════════════════════════════════════
   OPENLAYERS
══════════════════════════════════════════ */
function initOlMap() {
    if (olMap) { olMap.updateSize(); return; }
    olMarkerSrc = new ol.source.Vector();
    olMap = new ol.Map({
        target: 'ol-map',
        layers: [
            new ol.layer.Tile({ source: new ol.source.OSM() }),
            new ol.layer.Vector({
                source: olMarkerSrc,
                style: new ol.style.Style({
                    image: new ol.style.Circle({
                        radius: 7,
                        fill: new ol.style.Fill({ color: '#3273dc' }),
                        stroke: new ol.style.Stroke({ color: 'white', width: 2 }),
                    }),
                }),
            }),
        ],
        view: new ol.View({ center: ol.proj.fromLonLat([-1.68, 48.11]), zoom: 9 }),
    });
    olMap.on('click', e => {
        olMarkerSrc.clear();
        olMarkerSrc.addFeature(new ol.Feature({ geometry: new ol.geom.Point(e.coordinate) }));
        const [lng, lat] = ol.proj.toLonLat(e.coordinate);
        document.getElementById('thing-lng').value = lng.toFixed(6);
        document.getElementById('thing-lat').value = lat.toFixed(6);
    });
}

function syncInputsToMap() {
    const lng = parseFloat(document.getElementById('thing-lng').value);
    const lat = parseFloat(document.getElementById('thing-lat').value);
    if (isNaN(lng) || isNaN(lat) || !olMap) return;
    const coord = ol.proj.fromLonLat([lng, lat]);
    olMarkerSrc.clear();
    olMarkerSrc.addFeature(new ol.Feature({ geometry: new ol.geom.Point(coord) }));
    olMap.getView().animate({ center: coord, zoom: 13, duration: 400 });
}


/* ══════════════════════════════════════════
   STEP 4: PUBLICATION
══════════════════════════════════════════ */
function setupPublishBtn() {
    document.getElementById('btn-publish').addEventListener('click', publishData);
}

async function publishData() {
    const btn = document.getElementById('btn-publish');
    const progress = document.getElementById('step-4-progress');
    const result = document.getElementById('step-4-result');

    btn.classList.add('is-loading');
    progress.classList.remove('is-hidden');
    result.classList.add('is-hidden');

    const thingId = document.getElementById('thing-select').value;
    const thing = things.find(t => String(t.id) === thingId);

    const formData = new FormData();
    formData.append('thing_id', thingId);
    formData.append('thing_name', thing ? thing.name : '');
    formData.append('masse_sel', JSON.stringify(getMassesList()));
    formData.append('ranges', JSON.stringify(
        csvRanges.map(r => ({ start: toLocalISOString(r.start), end: toLocalISOString(r.end) }))
    ));
    formData.append('debits', JSON.stringify(lastDebits));
    formData.append('csv_file', document.getElementById('csv-file').files[0]);

    try {
        const resp = await fetch(`${API}/publish`, postOptions(formData));
        const data = await resp.json();

        progress.classList.add('is-hidden');
        result.classList.remove('is-hidden');

        if (resp.ok) {
            result.className = 'notification is-success mt-3';
            result.innerHTML = `
                <p class="mb-2"><strong>${T.publishSuccess}</strong></p>
                <ul>
                    <li>${fmt(T.nCondObs, { n: data.n_conductivity_obs })}
                        → MultiDatastream <strong>#${data.cond_ds_id}</strong></li>
                    <li>${fmt(T.nDischargeObs, { n: data.n_discharge_obs })}
                        → MultiDatastream <strong>#${data.sf_ds_id}</strong></li>
                </ul>`;
            setStepBadge(4, 'success', T.published);
            btn.disabled = true;
            await renderDischargeChart(data.sf_ds_id, data.discharge_obs);
            reveal('step-5');
        } else {
            result.className = 'notification is-danger mt-3';
            result.textContent = data.error || T.publishError;
        }
    } catch (e) {
        progress.classList.add('is-hidden');
        result.className = 'notification is-danger mt-3';
        result.textContent = T.networkErrorDot;
        result.classList.remove('is-hidden');
    } finally {
        btn.classList.remove('is-loading');
    }
}


/* ══════════════════════════════════════════
   RESULTS DISPLAY
══════════════════════════════════════════ */
function buildResultsHTML(data) {
    const debits = data.debit;
    const incertitude = data.incertitude;          // relative u, %
    const incertAbs = data.incertitude_abs;        // absolute u, L/s
    const units = data.units || 'L/s';
    const n = debits.length;
    const mean = debits.reduce((a, b) => a + b, 0) / n;
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    // ── theme-aware colours ─────────────────────────────────────────────
    const textColor = dark ? '#e0e0e0' : '#363636';
    const axisColor = dark ? 'rgba(255,255,255,0.2)' : '#dbdbdb';
    const bandColor = 'rgba(50,115,220,0.18)';
    const meanColor = '#3273dc';

    // ── SVG strip chart ─────────────────────────────────────────────────
    const W = 520, H = 90;
    const mL = 50, mR = 50, mT = 22, mB = 22;
    const plotW = W - mL - mR;
    const midY = mT + (H - mT - mB) / 2;

    const bandHalf = mean * incertitude / 100;
    const xMin = Math.min(...debits, mean - bandHalf) * 0.92;
    const xMax = Math.max(...debits, mean + bandHalf) * 1.08;
    const xs = v => mL + ((v - xMin) / (xMax - xMin)) * plotW;

    // Uncertainty band
    const bx1 = xs(mean - bandHalf), bx2 = xs(mean + bandHalf);
    const bw = bx2 - bx1;

    // X axis ticks (-u, mean, +u)
    const ticks = [
        { v: mean - bandHalf, label: (mean - bandHalf).toFixed(2) },
        { v: mean, label: mean.toFixed(2), isMean: true },
        { v: mean + bandHalf, label: (mean + bandHalf).toFixed(2) },
    ];
    const ticksSVG = ticks.map(t => `
        <line x1="${xs(t.v)}" y1="${midY + 14}" x2="${xs(t.v)}" y2="${midY + 18}"
              stroke="${t.isMean ? meanColor : axisColor}" stroke-width="1"/>
        <text x="${xs(t.v)}" y="${H - 2}" text-anchor="middle"
              font-size="9" fill="${t.isMean ? meanColor : textColor}">${t.label}</text>
    `).join('');

    // One dot per measurement
    const dotsSVG = debits.map((d, i) => `
        <circle cx="${xs(d)}" cy="${midY}" r="7"
                fill="${RANGE_STROKE[i % RANGE_STROKE.length]}"
                stroke="${dark ? '#222' : 'white'}" stroke-width="2">
            <title>${fmt(T.measurement, { n: i + 1 })}: ${d} ${units}</title>
        </circle>
        <text x="${xs(d)}" y="${midY - 11}" text-anchor="middle"
              font-size="9" font-weight="bold"
              fill="${RANGE_STROKE[i % RANGE_STROKE.length]}">M${i + 1}</text>
    `).join('');

    const svg = `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px;display:block;">
        <line x1="${mL}" y1="${midY + 14}" x2="${W - mR}" y2="${midY + 14}"
              stroke="${axisColor}" stroke-width="1"/>
        <rect x="${bx1}" y="${midY - 13}" width="${bw}" height="26"
              fill="${bandColor}" rx="4"/>
        <line x1="${xs(mean)}" y1="${midY - 22}" x2="${xs(mean)}" y2="${midY + 14}"
              stroke="${meanColor}" stroke-width="2" stroke-dasharray="4,2"/>
        ${ticksSVG}
        ${dotsSVG}
        <text x="${mL - 4}" y="${H - 2}" text-anchor="end"
              font-size="9" fill="${textColor}">${units}</text>
    </svg>`;

    // ── detail table ────────────────────────────────────────────────────
    const rows = debits.map((d, i) => {
        const deviation = ((d - mean) / mean * 100);
        const sign = deviation >= 0 ? '+' : '';
        return `<tr>
            <td>
                <span class="tag" style="background:${RANGE_STROKE[i % RANGE_STROKE.length]};color:white;">
                    ${fmt(T.measurement, { n: i + 1 })}
                </span>
            </td>
            <td class="has-text-right"><strong>${d.toFixed(2)}</strong></td>
            <td class="has-text-right has-text-grey">${sign}${deviation.toFixed(1)} %</td>
        </tr>`;
    }).join('');

    // ── uncertainty badge (< 5 % green, <= 10 % orange, > 10 % red) ─────
    const incClass = incertitude < 5 ? 'is-success'
        : incertitude <= 10 ? 'is-warning'
            : 'is-danger';

    return `
    <div class="box">
        <div class="columns is-mobile is-vcentered mb-2">
            <div class="column has-text-centered">
                <p class="heading">${T.meanDischarge}</p>
                <p class="title is-2">${mean.toFixed(2)}
                    <span class="is-size-5 has-text-grey-light">${units}</span>
                </p>
            </div>
            <div class="column has-text-centered">
                <p class="heading">${T.uncertainty}</p>
                <p class="title is-2 mb-1">
                    <span class="tag ${incClass} is-large" style="font-size:1.6rem;padding:1rem 1.2rem;">
                        ${incertitude} %
                    </span>
                </p>
                <p class="is-size-7 has-text-grey">
                    u = ${incertAbs !== undefined ? incertAbs.toFixed(3) : '—'} ${units}
                </p>
            </div>
            <div class="column has-text-centered">
                <p class="heading">${T.nMeasurements}</p>
                <p class="title is-2">${n}</p>
            </div>
        </div>

        <p class="heading mb-1">${T.distribution} ± ${incertAbs !== undefined ? incertAbs.toFixed(3) + ' ' + units : ''} (± ${incertitude} %)</p>
        <div style="overflow-x:auto; margin-bottom:1rem;">${svg}</div>

        <table class="table is-narrow is-fullwidth is-hoverable">
            <thead>
                <tr>
                    <th>${T.measurementCol}</th>
                    <th class="has-text-right">${T.dischargeCol} (${units})</th>
                    <th class="has-text-right">${T.deviationCol}</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
            <tfoot>
                <tr>
                    <th>${T.mean}</th>
                    <th class="has-text-right">${mean.toFixed(2)}</th>
                    <th class="has-text-right">—</th>
                </tr>
            </tfoot>
        </table>
    </div>`;
}


/* ══════════════════════════════════════════
   UTILITIES
══════════════════════════════════════════ */
function reveal(id) {
    const el = document.getElementById(id);
    el.classList.remove('is-hidden');
    setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
}

function setProgress(id, visible) {
    document.getElementById(id).style.display = visible ? '' : 'none';
}

function setMsg(id, text, type) {
    const el = document.getElementById(id);
    el.textContent = text;
    el.className = `help is-${type}`;
}

function setStepBadge(num, type, text) {
    document.getElementById(`step-${num}-num`).className = `step-num is-${type}`;
    const tag = document.getElementById(`step-${num}-tag`);
    tag.textContent = text;
    tag.className = `tag is-${type} is-light`;
}

function formatDateFull(d) {
    const p = n => String(n).padStart(2, '0');
    return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function formatTimeShort(d) {
    const p = n => String(n).padStart(2, '0');
    return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function renderDischargeChart(ds_id, newObs = []) {
    const container = document.getElementById('discharge-chart');
    container.classList.remove('is-hidden');
    container.innerHTML = `<p class="has-text-grey is-size-7">${T.loadingObs}</p>`;

    // phenomenonTimes just published, to tell them apart
    const newTimes = new Set(newObs.map(([t]) => t));

    try {
        const resp = await fetch(`${API}/observations?ds_id=${ds_id}`, { credentials: 'same-origin' });
        const data = await resp.json();

        if (!resp.ok || !data.observations.length) {
            container.innerHTML = `<p class="has-text-grey is-size-7">${T.noObs}</p>`;
            return;
        }

        // Two series: [Date, history|null, new|null]
        const chartData = data.observations.map(o => {
            const t = new Date(o.phenomenonTime);
            const q = o.result;
            return newTimes.has(o.phenomenonTime) ? [t, null, q] : [t, q, null];
        });

        const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        container.innerHTML = '';

        chartData.sort((a, b) => a[0] - b[0]);

        new Dygraph(container, chartData, {
            labels: ['Date', T.history, T.newObs],
            ylabel: T.dischargeAxis,
            colors: ['#48c774', '#5b9cf6'],
            drawPoints: true,
            pointSize: 7,
            strokeWidth: 1.5,
            axisLabelFontSize: 11,
            axisLabelColor: dark ? '#cccccc' : '#363636',
            axisLineColor: dark ? 'rgba(255,255,255,0.4)' : 'black',
            gridLineColor: dark ? 'rgba(255,255,255,0.12)' : 'rgb(128,128,128)',
            series: {
                [T.newObs]: { pointSize: 9, strokeWidth: 0 },
            },
        });
    } catch (e) {
        container.innerHTML = `<p class="has-text-danger is-size-7">${T.chartError}</p>`;
    }
}

function toLocalISOString(d) {
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
        `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
