/**
 * Graph Utility Module
 * Shared Dygraph helpers used across visualization pages.
 */

import * as STAApi from "./sta-api.js";
import { escapeHtml, showModal } from "./utils.js";

let modalShown = false;

/**
 * Creates a bar chart plotter export function for Dygraph
 * @param {number} barWidth - Width of each bar in pixels
 * @returns {Function} Dygraph plotter function
 */
export function barChartPlotter(barWidth) {
  return function (e) {
    const ctx = e.drawingContext;
    const points = e.points;
    ctx.globalAlpha = 1;

    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      const centerX = p.canvasx;
      const centerY = p.canvasy;
      const height = e.dygraph.toDomYCoord(0) - centerY;
      ctx.fillRect(centerX - barWidth / 2, centerY, barWidth, height);
      ctx.strokeRect(centerX - barWidth / 2, centerY, barWidth, height);
    }
  };
}

// ============================================================================
// Data transformation
// ============================================================================

/**
 * Transforms a SensorThings DataArray response into Dygraph-compatible format.
 * Handles component order detection (phenomenonTime can be at any index,
 * because some STA don't respect the $select order).
 * @param {Object} dataArrayResponse - Response from STAApi.fetchSTA() with dataArray format
 * @param {Array} dataArrayResponse.dataArray - Raw data rows
 * @param {Array} dataArrayResponse.components - Column names
 * @returns {Array<Array>} Array of [Date, number] pairs
 */
export function transformDataArray(dataArrayResponse) {
  const { dataArray, components } = dataArrayResponse;
  if (!dataArray || dataArray.length === 0) return [];

  const phenomenonTimeIndex = components.indexOf("phenomenonTime");
  const resultIndex = components.indexOf("result");

  return dataArray.map((row) => {
    // Archive : result = [brut, QF, corrigé] -> on trace la valeur brute [0].
    const v = row[resultIndex];
    return [new Date(row[phenomenonTimeIndex]), Array.isArray(v) ? v[0] : v];
  });
}

// QF (Argo) -> couleur de fond. Fallback par défaut uniquement : la map réelle
// vient du descripteur de config (champ `qfColors`, dérivé côté serveur de la
// source unique app/data/qualification/qf_flags.json) via setQfColors().
export const ARCHIVE_QF_COLORS = {
  14: "rgba(255,0,0,.40)",
  13: "rgba(240,164,22,.40)",
  9: "rgba(90,90,90,.40)",
  6: "rgba(150,100,230,.40)",
  5: "rgba(40,130,220,.40)",
  12: "rgba(85,204,112,.22)",
};

// Map QF -> couleur effective (par défaut = fallback ci-dessus). Remplacée au
// chargement de la config par setQfColors(config.qfColors) — voir app-init.js.
let qfColors = { ...ARCHIVE_QF_COLORS };

/**
 * Définit la map QF -> couleur depuis le descripteur de config (source unique
 * serveur). Sans appel (ou map vide), on garde ARCHIVE_QF_COLORS par défaut.
 * @param {Object<string,string>} map - { code: "rgba(...)" }
 */
export function setQfColors(map) {
  if (map && typeof map === "object" && Object.keys(map).length)
    qfColors = { ...map };
}

/**
 * Regroupe les points en plages contiguës de même QF (result[1]).
 * @param {Object} dataArrayResponse - {dataArray, components} (result = [brut, QF, corrigé])
 * @returns {Array<{start:number, end:number, qf:number}>}
 */
export function buildQfRanges(dataArrayResponse) {
  const { dataArray, components } = dataArrayResponse || {};
  if (!dataArray || !dataArray.length) return [];
  const ti = components.indexOf("phenomenonTime");
  const ri = components.indexOf("result");
  const ranges = [];
  let cur = null,
    start = null;
  for (const row of dataArray) {
    const t = new Date(row[ti]).getTime();
    const v = row[ri];
    const qf = Array.isArray(v) ? v[1] : null;
    if (qf !== cur) {
      if (cur != null && qfColors[cur] !== undefined)
        ranges.push({ start, end: t, qf: cur });
      cur = qf;
      start = t;
    }
  }
  const last = dataArray[dataArray.length - 1];
  if (cur != null && qfColors[cur] !== undefined)
    ranges.push({ start, end: new Date(last[ti]).getTime(), qf: cur });
  return ranges;
}

/**
 * underlayCallback qui peint les bandes QF puis délègue à un underlay de base
 * (ex: seuils minValue/maxValue) — dygraph n'accepte qu'UN underlayCallback.
 * @param {Array} ranges - de buildQfRanges()
 * @param {Function} [baseUnderlay] - underlay existant à composer
 * @returns {Function} underlayCallback
 */
export function makeQfUnderlay(ranges, baseUnderlay) {
  return function (canvas, area, g) {
    (ranges || []).forEach((r) => {
      canvas.fillStyle = qfColors[r.qf] || "rgba(150,150,150,.3)";
      const x1 = g.toDomXCoord(r.start),
        x2 = g.toDomXCoord(r.end);
      canvas.fillRect(x1, area.y, x2 - x1, area.h);
    });
    if (typeof baseUnderlay === "function") baseUnderlay(canvas, area, g);
  };
}

/**
 * underlayCallback à utiliser : bandes QF si (archive ET une seule série),
 * sinon l'underlay de base (seuils). Pour les pages multi-séries (métrologue,
 * téléchargement) où colorer le fond n'a de sens qu'avec une série affichée.
 * @param {Array} qfRanges - de buildQfRanges() (série unique)
 * @param {number} seriesCount - nb de séries affichées
 * @param {Function|null} baseUnderlay
 * @returns {Function|null}
 */
export function qfUnderlayIfSingle(qfRanges, seriesCount, baseUnderlay) {
  return STAApi.isArchive() && seriesCount === 1
    ? makeQfUnderlay(qfRanges, baseUnderlay)
    : baseUnderlay;
}

/**
 * Merges multiple single-series data arrays into one multi-series array for Dygraph.
 * Uses getTime() for reliable Date comparison. Missing values filled with null for prettier plot.
 * @param {Array<Array<[Date, number]>>} dataArrays - Array of series, each [[Date, value], ...]
 * @returns {Array<[Date, ...number]>} Merged [[Date, val1, val2, ...], ...] sorted by date
 */
export function mergeDataArrays(dataArrays) {
  if (dataArrays.length === 0) return [];

  const dateSet = new Set();
  //export unique date
  const dataMap = dataArrays.map((series) => {
    const map = new Map();
    series.forEach((row) => {
      const ts = row[0].getTime();
      map.set(ts, row[1]);
      dateSet.add(ts);
    });
    return map;
  });

  // Sort date ascending
  const allDates = Array.from(dateSet).sort((a, b) => a - b);

  return allDates.map((timestamp) => {
    const row = [new Date(timestamp)];
    dataMap.forEach((map) => {
      row.push(map.get(timestamp) !== undefined ? map.get(timestamp) : null);
    });
    return row;
  });
}

/**
 * Parses a graphDatas response from SensorThings API (stean mode).
 * Extracts dates and values from the "datas" string via regex (no eval).
 * @param {Object} response - {infos: "name|unitName|symbol", datas: "[new Date(...), val],..."}
 * @returns {{ data: Array<[Date, number | null]>, name: string, unitName: string, unitSymbol: string }}
 */
export function parseGraphDatas(response) {
  const [name, unitName, unitSymbol] = response.infos.split("|");
  const data = [];
  const regex = /new Date\("([^"]+)"\),\s*([\d.eE+-]+|null)/g;
  let match;
  while ((match = regex.exec(response.datas)) !== null) {
    const date = new Date(match[1]);
    const value = match[2] === "null" ? null : parseFloat(match[2]);
    data.push([date, value]);
  }
  return {
    data,
    name: name.trim(),
    unitName: unitName.trim(),
    unitSymbol: unitSymbol.trim(),
  };
}

// ============================================================================
// Aggregation
// ============================================================================

/**
 * Determines aggregation level based on observation count and
 * the width of the graph in px (only for Frost_Geosas mode).
 * @param {number} count - Number of observations
 * @returns {string|null} 'hour', 'day', or null (raw)
 */
export function determineAggregation(count) {
  const graphDiv = document.getElementById("graphDiv");
  const widthPx = graphDiv.clientWidth;
  const PIXELS_PER_POINT = 1;
  const maxPoints = widthPx / PIXELS_PER_POINT;

  if (count <= maxPoints) return null;

  if (count <= maxPoints * 24) return "hour";

  return "day";
}

/**
 * Returns 'bar' if the ObservedProperty is in the config's bar list, else 'line'.
 * @param {string|undefined} observedPropertyName
 * @param {string[]} barObservedProperties - from appConfig
 * @returns {'bar'|'line'}
 */
export function getGraphType(observedPropertyName, barObservedProperties = []) {
  return observedPropertyName && barObservedProperties.includes(observedPropertyName)
    ? "bar"
    : "line";
}

/**
 * Builds the $groupby parameter value for SensorThings aggregation.
 * Next improvement go to $ODATA !
 * @param {string} aggregation - 'hour' or 'day'
 * @param {string} graphType - 'bar' (SUM) or 'line' (MEAN)
 * @returns {string|null} groupby value, e.g., 'hour', 'day,SUM'
 */
export function buildGroupByParam(aggregation, graphType) {
  if (!aggregation) return null;
  return graphType === "bar" ? `${aggregation},SUM` : aggregation;
}

/**
 * Returns a label describing the aggregation applied.
 * @param {string|null} aggregation - 'hour', 'day', or null
 * @param {string} graphType - 'bar' or 'line'
 * @returns {string} e.g., "Données brutes", "Moyenne/heure", "Cumul/jour"
 */
export function getAggregationLabel(aggregation, graphType) {
  if (!aggregation) return "Données brutes";
  if (aggregation === "moving_average") return "Moyenne mobile";
  if (graphType === "bar") {
    return aggregation === "hour" ? "Cumul/heure" : "Cumul/jour";
  }
  return aggregation === "hour" ? "Moyenne/heure" : "Moyenne/jour";
}

/**
 * Downloads observations for a datastream with automatic count-based aggregation.
 * Handles Frost_Geosas mode (server-side aggregation) and standard mode (raw + limit).
 * @param {Object} params
 * @param {string} params.baseUrl - SensorThings API base URL
 * @param {number|string} params.datastreamId - Datastream ID
 * @param {string} params.graphType - 'bar' or 'line'
 * @param {string|null} params.mode - Service mode ('Frost_Geosas' or other)
 * @param {Object} [params.dateRange=null] - {start: Date, end: Date}
 * @param {string|null} [params.aggregation=null] - Pre-computed aggregation level (skips count if provided)
 * @returns {Promise<{data: Array, aggregation: string|null, limitReached: boolean}>}
 */
export async function downloadObservations(params) {
  const {
    baseUrl,
    datastreamId,
    graphType,
    mode,
    dateRange = null,
    aggregation: precomputedAgg = null,
  } = params;
  const entity = `Datastreams(${datastreamId})/Observations`;

  const filter = dateRange
    ? `phenomenonTime ge ${dateRange.start.toISOString()} and phenomenonTime le ${dateRange.end.toISOString()}`
    : undefined;

  if (mode === "Frost_Geosas") {
    //maybe if else  would be more simple
    const aggregation =
      precomputedAgg ??
      determineAggregation(
        await STAApi.getCount(baseUrl, entity, filter || ""),
      );
    let url;
    if (aggregation) {
      url = STAApi.buildQuery(baseUrl, entity, {
        resultFormat: "dataArray",
        groupby: buildGroupByParam(aggregation, graphType),
        filter,
      });
    } else {
      url = STAApi.buildQuery(baseUrl, entity, {
        resultFormat: "dataArray",
        select: "phenomenonTime,result",
        orderby: "phenomenonTime asc",
        filter,
      });
    }

    const result = await STAApi.fetchSTA(url);
    return {
      data: transformDataArray(result),
      aggregation,
      limitReached: false,
      qfRanges: STAApi.isArchive() ? buildQfRanges(result) : [],
    };
  }

  // Standard mode: raw data with pagination limit
  const url = STAApi.buildQuery(baseUrl, entity, {
    resultFormat: "dataArray",
    select: "phenomenonTime,result",
    orderby: "phenomenonTime asc",
    top: 50000,
    filter,
  });

  const result = await STAApi.fetchSTA(url, { maxRecords: 100000 });
  return {
    data: transformDataArray(result),
    aggregation: null,
    limitReached: result.limitReached || false,
    qfRanges: STAApi.isArchive() ? buildQfRanges(result) : [],
  };
}

// ============================================================================
// Dygraph helpers
// ============================================================================

/**
 * Creates a Dygraph underlayCallback for threshold lines (minValue/maxValue).
 * @param {Object} thresholds
 * @param {number} thresholds.minValue - min value
 * @param {number} thresholds.maxValue - max value
 * @returns {Function|null} custom underlay callback or null if no thresholds
 */
export function createThresholdCallback(thresholds) {
  const { minValue = null, maxValue = null } = thresholds || {};
  if (minValue == null && maxValue == null) return null;

  return function (canvas, area, g) {
    [minValue, maxValue].forEach((threshold) => {
      if (threshold == null) return;
      const yPixel = g.toDomYCoord(threshold);
      canvas.beginPath();
      canvas.strokeStyle = "red";
      canvas.lineWidth = 3;
      canvas.setLineDash([4, 2]);
      canvas.moveTo(area.x, yPixel);
      canvas.lineTo(area.x + area.w, yPixel);
      canvas.stroke();
    });
    canvas.setLineDash([]);
  };
}

/**
 * Creates a Dygraph instance with standard options.
 * @param {HTMLElement} graphDiv - Graph container element
 * @param {HTMLElement} legendDiv - Legend container element
 * @param {Object} [extraOptions={}] - Additional Dygraph options
 * @returns {Dygraph} Configured Dygraph instance
 */
export function createDygraph(graphDiv, legendDiv, extraOptions = {}) {
  return new Dygraph(graphDiv, [], {
    drawPoints: true,
    connectSeparatedPoints: false,//better for see gap but not for multiplot
    digitsAfterDecimal: 3,
    legend: "always",
    labelsDiv: legendDiv,
    ...extraOptions,
  });
}

// ============================================================================
// Statistics
// ============================================================================

/**
 * Calculates summary statistics from visible graph data.
 * For 'bar' series: sum. For 'line' series: mean.
 * @param {Dygraph} dygraph - Dygraph instance
 * @param {Object} seriesTypeDict - {seriesLabel: 'bar'|'line'}
 * @returns {Object} {seriesLabel: {value: number, color: string}}
 */
export function calculStatGraph(dygraph, seriesTypeDict) {
  const data = dygraph.file_;
  if (!data || data.length === 0) return {};

  const colors = dygraph.getColors();
  const series = dygraph.getLabels().slice(1);
  const [xmin, xmax] = dygraph.xAxisRange();

  const sums = new Array(series.length).fill(0);
  const counts = new Array(series.length).fill(0);
  if (!modalShown && data.length > 500000) {
    modalShown = true;
    showModal({
      title: "⚠️ Attention",
      body: `Il y a beaucoup de données : ${data.length} observations, 
            votre navigateur  va peut-être subir des ralentissement.
            Ce message ne s'affichera plus.`,
      buttons: [
        {
          text: "Continuer",
          class: "is-success",
        },
      ],
    });
  }
  data.forEach((row) => {
    const x = row[0];
    //only visible row -> betwen xmin and xmax
    if (x >= xmin && x <= xmax) {
      series.forEach((_, index) => {
        const y = row[index + 1];
        if (y !== null && !isNaN(y)) {
          sums[index] += y;
          counts[index]++;
        }
      });
    }
  });

  const result = {};
  for (let i = 0; i < series.length; i++) {
    const type = seriesTypeDict[series[i]];
    result[series[i]] = {
      value:
        type === "bar"
          ? Math.round(sums[i] * 100) / 100
          : counts[i] > 0
            ? Math.round((sums[i] / counts[i]) * 100) / 100
            : 0,
      color: colors[i],
    };
  }
  return result;
}

/**
 * Renders a statistics table into a container.
 * @param {Array<string>} selectedKeys - Series keys (datastream names)
 * @param {Object} statistique - From calculStatGraph()
 * @param {HTMLElement} container - Target DOM element
 * @param {Object} seriesDataDict - {key: {unit, graph, aggregation}}
 * @param {Object} aggregationDict - {key: 'hour'|'day'|null}
 */
export function renderStatisticsTable(
  selectedKeys,
  statistique,
  container,
  seriesDataDict,
  aggregationDict,
) {
  const table = document.createElement("table");
  table.className = "table is-striped is-bordered is-fullwidth";
  table.innerHTML = `
        <thead>
            <tr>
                <th>Variable</th>
                <th>Fréquence</th>
                <th>Aggrégation (visuelle)</th>
                <th>Statistique sur la période affichée</th>
            </tr>
        </thead>
        <tbody></tbody>
    `;

  const tbody = table.querySelector("tbody");

  for (const key of selectedKeys) {
    if (!seriesDataDict[key]) continue;

    const aggLabel = getAggregationLabel(
      aggregationDict[key],
      seriesDataDict[key].graph,
    );
    const unit = seriesDataDict[key].unit;
    const statKey = key + " " + unit;
    const statGeneral =
      seriesDataDict[key].graph === "bar" ? "Cumul" : "Moyenne";

    // frequency est un objet {value, unit} (config STA) ; on l'affiche "20 min".
    const freqRaw = seriesDataDict[key]?.properties?.frequency;
    const frequency =
      freqRaw && typeof freqRaw === "object"
        ? `${freqRaw.value} ${freqRaw.unit ?? ""}`.trim()
        : (freqRaw ?? "Non renseignée");

    const row = document.createElement("tr");
    row.innerHTML = `
            <td style="color:${statistique[statKey]?.color || "black"}"><b>${escapeHtml(key)}</b></td>
            <td>${frequency}</td>
            <td><b>${aggLabel}</b></td>
            <td>${statGeneral}: ${statistique[statKey]?.value || 0} ${escapeHtml(unit)}</td>
        `;
    tbody.appendChild(row);
  }

  container.innerHTML = "";
  container.appendChild(table);
}
