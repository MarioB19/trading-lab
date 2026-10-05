"use strict";
const el = (id) => document.getElementById(id);
const numeric = (value) => {
  if (value == null || typeof value === "boolean" || (typeof value === "string" && !value.trim())) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
};
const formatMoney = (value, currency = "USD", signed = false) => {
  const amount = numeric(value);
  if (amount === null) return "—";
  return new Intl.NumberFormat("es-MX", {style: "currency", currency, currencyDisplay: "code",
    maximumFractionDigits: 2, signDisplay: signed ? "exceptZero" : "auto"}).format(amount);
};
let selectedCurrency = "MXN";
try {
  if (localStorage.getItem("trading-lab-currency") === "USD") selectedCurrency = "USD";
} catch (_) { /* Storage can be disabled; MXN remains the default. */ }
let lastPerformance = null;
let lastOperating = null;
let refreshing = false;
const currentRate = () => {
  const rate = numeric(lastPerformance?.fx?.rate);
  return rate !== null && rate > 0 ? rate : null;
};
const money = (usd, signed = false) => {
  if (numeric(usd) === null) return "—";
  if (selectedCurrency === "USD") return formatMoney(usd, "USD", signed);
  const rate = currentRate();
  return rate === null ? "Sin tipo de cambio" : formatMoney(Number(usd) * rate, "MXN", signed);
};
const moneyWithReference = (usd, signed = false) => {
  const value = money(usd, signed);
  return selectedCurrency === "MXN" && numeric(usd) !== null
    ? `${value} · ${formatMoney(usd, "USD", signed)}` : value;
};
// Historical and P&L MXN values are calculated by the server, never with today's FX.
const gainMoney = (usd, mxn) => {
  if (selectedCurrency === "USD") return formatMoney(usd, "USD", true);
  if (numeric(mxn) !== null) return formatMoney(mxn, "MXN", true);
  return numeric(usd) === null ? "—" : `Sin tipo de cambio · ${formatMoney(usd, "USD", true)}`;
};
const date = (value) => {
  if (!value) return "—";
  let stamp = String(value).trim();
  if (/[+-]\d{2}:\d{2}$/.test(stamp) && !stamp.endsWith("+00:00")) {
    const parsed = new Date(stamp);
    if (Number.isFinite(parsed.getTime())) stamp = parsed.toISOString();
  }
  return `${stamp.replace("T", " ").replace(/\.\d+/, "").replace(/(?:Z|\+00:00|\s+UTC)$/, "")} UTC`;
};
const text = (tag, value, cls) => {
  const node = document.createElement(tag);
  node.textContent = value ?? "—";
  if (cls) node.className = cls;
  return node;
};

function rows(id, items, columns) {
  const target = el(id);
  target.replaceChildren();
  if (!items.length) {
    const tr = document.createElement("tr");
    const td = text("td", "Sin registros.");
    td.colSpan = columns.length;
    tr.append(td);
    target.append(tr);
    return;
  }
  for (const item of items) {
    const tr = document.createElement("tr");
    for (const col of columns) tr.append(text("td", col(item)));
    target.append(tr);
  }
}

function sleeves(status) {
  const target = el("sleeves");
  target.replaceChildren();
  const snapshot = status.snapshot?.sleeves || {};
  const live = status.live?.sleeves || {};
  for (const name of new Set([...Object.keys(snapshot), ...Object.keys(live)])) {
    const base = snapshot[name] || {};
    const latest = live[name] || {};
    const valuation = lastPerformance?.current?.by_sleeve?.[name];
    const selectedDocument = valuation?.source === "snapshot" ? status.snapshot : status.live;
    const data = valuation?.source === "snapshot" ? base : latest;
    const sourceCutoff = data.prices_as_of_utc || data.updated_utc || data.last_run_utc
      || selectedDocument?.updated_utc || selectedDocument?.generated_utc;
    const sameCutoff = Boolean(valuation?.as_of_utc) && valuation.as_of_utc === sourceCutoff;
    const detailVerified = numeric(valuation?.equity_usd) !== null && sameCutoff;
    const card = text("article", null, "sleeve");
    card.replaceChildren(text("h3", data.label || base.label || name));
    const dl = document.createElement("dl");
    for (const [label, value] of [
      ["Patrimonio", moneyWithReference(valuation?.equity_usd)], ["Efectivo", moneyWithReference(detailVerified ? data.cash : null)],
      ["Caída reportada", !detailVerified || data.drawdown == null ? "—" : `${(data.drawdown * 100).toFixed(2)}%`],
      ["Kill switch", data.kill_switch ? "ACTIVADO" : "No activado"],
      ["Ejecución diaria", base.status || "—"], ["Observación", latest.status || "—"],
      ["Corte UTC", date(valuation?.as_of_utc)]
    ]) dl.append(text("dt", label), text("dd", value));
    card.append(dl);
    const positions = detailVerified ? (data.positions || data.assets?.filter(a => Number(a.qty) > 0) || []) : [];
    if (!detailVerified) card.append(text("p", "Detalle de efectivo y posiciones pendiente de coincidir con una valoración válida del mismo corte."));
    if (positions.length) card.append(text("p", positions.map(p =>
      `${p.asset}: ${Number(p.qty).toLocaleString("es-MX", {maximumFractionDigits: 6})}`).join(" · ")));
    const notes = new Set([...(base.notes || []), ...(latest.notes || []), ...(data.alerts || [])]);
    if (notes.size) card.append(text("p", "Notas del cierre y observación · importes en USD", "note-label"));
    for (const note of notes) card.append(text("p", note));
    target.append(card);
  }
  if (!target.children.length) target.append(text("p", "Pendiente de importar el estado.", "empty"));

}

async function fetchJson(path) {
  const response = await fetch(path, {cache: "no-store", signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error("No se pudo leer el estado operativo");
  return response.json();
}

async function comparison() {
  const section = el("comparison-section");
  const target = el("comparison");
  target.replaceChildren();
  el("comparison-checks").textContent = "";
  el("comparison-paper").textContent = "";
  try {
    const data = await fetchJson("/api/comparison");
    const configured = [data.research, data.paper].some(value => value?.status && value.status !== "not_configured");
    section.hidden = !configured;
    if (!configured) return;
    const report = data.research?.report;
    el("comparison-status").textContent = report
      ? "Histórico del 1 ene 2021 al 26 sep 2026. Inicio: US$500 en cripto por cartera. Cifras después de costos; no garantizan ganancias futuras."
      : "Comparación histórica: " + (data.research?.status === "not_configured" ? "pendiente de enlazar el informe." : data.research?.status);
    if (report) {
      const base = report.metrics["0.0045"];
      for (const role of ["control", "aggressive"]) {
        const values = base?.[role]?.crypto;
        if (!values) continue;
        const card = text("article", null, "sleeve");
        card.replaceChildren(text("h3", role === "control" ? "Control · 5 criptos / volatilidad 40%" : "Agresiva · 3 criptos / volatilidad 60%"));
        const dl = document.createElement("dl");
        for (const [label, value] of [["Rentabilidad anualizada neta", `${(values.cagr * 100).toFixed(2)}%`],
          ["Caída máxima", `${(values.max_dd * 100).toFixed(2)}%`], ["Sharpe", values.sharpe.toFixed(3)],
          ["Capital final cripto · USD", formatMoney(values.final_equity_usd)], ["Costos modelados · USD", formatMoney(values.cost_usd)]]) {
          dl.append(text("dt", label), text("dd", value));
        }
        card.append(dl); target.append(card);
      }
      const labels = {cagr: "rentabilidad", sharpe: "retorno frente a variación", drawdown: "caída máxima",
        walk_forward: "ventanas anuales", bootstrap: "remuestreo", placebo: "placebo", cost_stress: "costos mayores"};
      const failed = Object.entries(report.checks).filter(([, passed]) => !passed).map(([name]) => labels[name] || name);
      el("comparison-checks").textContent = failed.length
        ? `Candidata rechazada y retirada de operación. Fallan: ${failed.join(", ")}. Se conserva como evidencia histórica.`
        : "Supera los criterios retrospectivos registrados. Aún requiere validación prospectiva y revisión humana.";
    }
    const paper = data.paper;
    el("comparison-paper").textContent = paper?.observed_days != null
      ? `Ensayo archivado: ${paper.observed_days} ${paper.observed_days === 1 ? "observación conservada" : "observaciones conservadas"}. Último ciclo: ${date(paper.health?.last_success || paper.generated_at)}. No se programa su continuación.`
      : "La investigación queda fuera de la operación diaria.";
  } catch (_) {
    section.hidden = false;
    el("comparison-status").textContent = "No se pudo verificar la comparación. Revisa los archivos y el servicio; no hay resultados confirmados disponibles.";
  }
}

function paintMetric(id, content, amount = null) {
  const node = el(id);
  node.textContent = content;
  node.classList.toggle("unavailable", content === "—" || content.startsWith("Sin tipo de cambio"));
  node.classList.toggle("gain-positive", numeric(amount) !== null && Number(amount) > 0);
  node.classList.toggle("gain-negative", numeric(amount) !== null && Number(amount) < 0);
}

function compactNotes(notes) {
  const grouped = new Map();
  const labels = {crypto: "Cripto", stocks: "ETF"};
  for (const raw of notes) {
    const note = String(raw);
    const name = Object.keys(labels).find(key => note.startsWith(`${key}: `));
    const body = name ? note.slice(name.length + 2) : note;
    if (!grouped.has(body)) grouped.set(body, []);
    if (name && !grouped.get(body).includes(labels[name])) grouped.get(body).push(labels[name]);
  }
  return [...grouped].map(([body, names]) => names.length ? `${names.join(" y ")}: ${body}` : body);
}

function dailyRows(items) {
  const target = el("daily");
  target.replaceChildren();
  if (!items.length) {
    const row = document.createElement("tr");
    const cell = text("td", "Sin cierres disponibles.");
    cell.colSpan = 6; row.append(cell); target.append(row); return;
  }
  for (const item of [...items].sort((a, b) => String(b.date).localeCompare(String(a.date)))) {
    const row = document.createElement("tr");
    row.append(text("td", item.date));
    for (const name of ["crypto", "stocks"]) {
      const block = item.by_sleeve?.[name];
      let label = "Sin cierre";
      if (block?.reliable === false) label = "Intervalo incompleto";
      else if (block?.carried && !block.has_close) label = "Sin nuevo cierre";
      else if (block?.has_close) label = gainMoney(block.pnl_usd, block.pnl_mxn);
      const amount = numeric(selectedCurrency === "MXN" ? block?.pnl_mxn : block?.pnl_usd);
      const cell = text("td", label, !block?.has_close || block?.reliable === false ? "missing-close" : "");
      if (block?.has_close && block?.reliable !== false && amount !== null) {
        cell.classList.toggle("gain-positive", amount > 0);
        cell.classList.toggle("gain-negative", amount < 0);
      }
      row.append(cell);
    }
    const total = text("td", gainMoney(item.pnl_usd, item.pnl_mxn), "gain-total");
    const totalAmount = numeric(selectedCurrency === "MXN" ? item.pnl_mxn : item.pnl_usd);
    total.classList.toggle("gain-positive", totalAmount !== null && totalAmount > 0);
    total.classList.toggle("gain-negative", totalAmount !== null && totalAmount < 0);
    row.append(total);
    const flow = numeric(item.flow_usd);
    const historicalRate = numeric(item.fx_rate);
    const flowMxn = flow !== null && historicalRate !== null && historicalRate > 0 ? flow * historicalRate : null;
    row.append(text("td", gainMoney(flow, flowMxn)));
    const notes = compactNotes(item.notes || []);
    if (selectedCurrency === "MXN" && historicalRate !== null && historicalRate > 0) {
      notes.push(`TC del cierre: ${historicalRate.toLocaleString("es-MX", {maximumFractionDigits: 6})} MXN/USD.`);
    }
    row.append(text("td", [...new Set(notes)].join(" ") || "—"));
    target.append(row);
  }
}

let balanceItems = [];
let balanceSelectedDate = null;
let balanceCursor = null;
let balanceX = () => 0;
const balanceBlock = item => el("balance-sleeve").value === "total"
  ? item : item.by_sleeve?.[el("balance-sleeve").value] || {};
const balanceValue = (item, field) => numeric(balanceBlock(item)[`${field}_${selectedCurrency.toLowerCase()}`]);
const svgNode = (tag, attributes, content) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes || {})) node.setAttribute(key, String(value));
  if (content != null) node.textContent = content;
  return node;
};

function selectBalanceDay(index) {
  const item = balanceItems[index];
  if (!item) return;
  balanceSelectedDate = item.date;
  const block = balanceBlock(item);
  const slider = el("balance-day");
  slider.value = String(index);
  slider.setAttribute("aria-valuetext", `${item.date}: saldo ${formatMoney(balanceValue(item, "equity"), selectedCurrency)}`);
  el("balance-selected-date").textContent = `${item.date} UTC`;
  if (balanceCursor) {
    balanceCursor.setAttribute("x1", balanceX(index));
    balanceCursor.setAttribute("x2", balanceX(index));
  }
  const detail = el("balance-detail");
  detail.replaceChildren();
  for (const [label, value, amount] of [
    ["Saldo al cierre", formatMoney(balanceValue(item, "equity"), selectedCurrency)],
    ["Capital aportado neto", formatMoney(balanceValue(item, "capital"), selectedCurrency)],
    ["Ganancia del día", gainMoney(block.pnl_usd, block.pnl_mxn), balanceValue(item, "pnl")],
    ["Aportes / retiros · USD", formatMoney(block.flow_usd, "USD", true)]
  ]) {
    const cell = document.createElement("div");
    cell.append(text("span", label), text("strong", value,
      numeric(amount) === null ? "" : amount > 0 ? "gain-positive" : amount < 0 ? "gain-negative" : ""));
    detail.append(cell);
  }
  const blocks = el("balance-sleeve").value === "total"
    ? Object.entries(item.by_sleeve || {}) : [[el("balance-sleeve").value, block]];
  const notes = [];
  for (const [name, data] of blocks) {
    const label = name === "crypto" ? "Cripto" : "ETF";
    if (data.carried) notes.push(`${label}: se conserva la valoración del ${data.equity_fx_date || "último cierre"}.`);
    if (selectedCurrency === "MXN" && numeric(data.equity_fx_rate) !== null) {
      notes.push(`${label}: TC ${data.equity_fx_rate} del ${data.equity_fx_date}.`);
    }
  }
  if (balanceValue(item, "equity") === null) notes.push("Saldo completo no disponible; no se sustituye por cero.");
  if (balanceValue(item, "capital") === null) notes.push("Capital histórico no verificable para este cierre.");
  if (numeric(block.flow_usd)) notes.push("El movimiento de capital modifica el saldo; no es ganancia ni pérdida.");
  notes.push(...compactNotes(block.notes || []));
  if (notes.length) detail.append(text("p", [...new Set(notes)].join(" "), "balance-day-notes"));
}

function renderBalance(data) {
  const target = el("balance-chart");
  target.replaceChildren();
  balanceCursor = null;
  const all = [...(data?.daily || [])].sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const period = el("balance-period").value;
  const end = all.length ? Date.parse(`${all[all.length - 1].date}T00:00:00Z`) : 0;
  balanceItems = period === "all" ? all : all.filter(item =>
    Date.parse(`${item.date}T00:00:00Z`) >= end - (Number(period) - 1) * 86400000);
  el("balance-empty").hidden = balanceItems.length > 0;
  el("balance-navigation").hidden = !balanceItems.length;
  el("balance-detail").hidden = !balanceItems.length;
  el("balance-note").textContent = `Cierres UTC en ${selectedCurrency}; la observación actual aparece arriba. `
    + (selectedCurrency === "MXN" ? "Cada bloque usa el tipo de cambio de su valoración histórica; el cambio de saldo también refleja divisas. " : "")
    + "El saldo incluye aportaciones y retiros; la ganancia del día los excluye. Eje vertical ajustado al rango visible. Los datos ausentes dejan huecos.";
  if (!balanceItems.length) return;
  const width = Math.max(300, target.clientWidth || 900), height = 280;
  const pad = {left: 78, right: 24, top: 22, bottom: 38};
  const values = balanceItems.flatMap(item => [balanceValue(item, "equity"), balanceValue(item, "capital")])
    .filter(value => value !== null);
  const svg = svgNode("svg", {viewBox: `0 0 ${width} ${height}`, role: "img", "aria-labelledby": "balance-svg-title balance-svg-desc"});
  svg.append(svgNode("title", {id: "balance-svg-title"}, `Balance diario en ${selectedCurrency}`),
    svgNode("desc", {id: "balance-svg-desc"}, "Línea continua: saldo. Línea discontinua: capital aportado neto. Los círculos dorados señalan movimientos de capital. Usa el selector de día para consultar los importes exactos."));
  target.append(svg);
  if (values.length) {
    const min = Math.min(...values), max = Math.max(...values);
    const margin = Math.max((max - min) * .18, max * .005, 1);
    const low = Math.max(0, min - margin), high = max + margin;
    balanceX = i => pad.left + (balanceItems.length === 1 ? .5 : i / (balanceItems.length - 1)) * (width - pad.left - pad.right);
    const y = value => height - pad.bottom - (value - low) / (high - low) * (height - pad.top - pad.bottom);
    const axisMoney = value => new Intl.NumberFormat("es-MX", {maximumFractionDigits: 0}).format(value);
    for (let i = 0; i <= 4; i++) {
      const value = low + (high - low) * i / 4;
      svg.append(svgNode("line", {x1: pad.left, x2: width - pad.right, y1: y(value), y2: y(value), class: "chart-grid"}),
        svgNode("text", {x: pad.left - 12, y: y(value) + 4, "text-anchor": "end", class: "chart-label"}, axisMoney(value)));
    }
    svg.append(svgNode("text", {x: pad.left - 12, y: 12, "text-anchor": "end", class: "chart-label"}, selectedCurrency));
    const labelCount = width < 480 ? 3 : 6;
    const step = Math.max(1, Math.ceil((balanceItems.length - 1) / (labelCount - 1)));
    balanceItems.forEach((item, i) => {
      if (i % step === 0 || i === balanceItems.length - 1) {
        svg.append(svgNode("text", {x: balanceX(i), y: height - 12, "text-anchor": i === balanceItems.length - 1 ? "end" : i === 0 ? "start" : "middle", class: "chart-label"}, item.date.slice(5)));
      }
    });
    for (const field of ["capital", "equity"]) {
      let path = "", connected = false;
      balanceItems.forEach((item, i) => {
        const value = balanceValue(item, field);
        if (value === null) { connected = false; return; }
        path += `${connected ? " L" : " M"}${balanceX(i)},${y(value)}`;
        connected = true;
      });
      svg.append(svgNode("path", {d: path, class: `chart-line chart-${field}`}));
    }
    balanceCursor = svgNode("line", {x1: 0, x2: 0, y1: pad.top, y2: height - pad.bottom, class: "chart-cursor"});
    svg.append(balanceCursor);
    balanceItems.forEach((item, i) => {
      const value = balanceValue(item, "equity");
      if (value === null) return;
      const flow = numeric(balanceBlock(item).flow_usd);
      const point = svgNode("circle", {cx: balanceX(i), cy: y(value), r: flow ? 6 : 4,
        class: `chart-point${flow ? " chart-flow" : ""}`});
      point.append(svgNode("title", {}, `${item.date}: ${formatMoney(value, selectedCurrency)}; movimiento ${formatMoney(flow, "USD", true)}`));
      const hit = svgNode("circle", {cx: balanceX(i), cy: y(value), r: 13, class: "chart-hit"});
      hit.addEventListener("pointerenter", () => selectBalanceDay(i));
      hit.addEventListener("click", () => selectBalanceDay(i));
      svg.append(point, hit);
    });
  } else {
    svg.append(svgNode("text", {x: width / 2, y: height / 2, "text-anchor": "middle", class: "chart-label"}, "Sin saldos verificables en esta moneda"));
  }
  const selected = balanceItems.findIndex(item => item.date === balanceSelectedDate);
  el("balance-day").max = String(balanceItems.length - 1);
  el("balance-day").disabled = balanceItems.length === 1;
  selectBalanceDay(selected < 0 ? balanceItems.length - 1 : selected);
}

function renderPerformance(data) {
  const current = data?.current || {};
  const capital = data?.capital || {};
  const progress = data?.in_progress || {};
  const rate = currentRate();
  const fx = data?.fx || {};
  el("fx").textContent = rate !== null
    ? `Tipo de cambio actual: 1 USD = ${rate.toLocaleString("es-MX", {maximumFractionDigits: 6})} MXN · ${fx.source || "Fuente no indicada"} · corte ${date(fx.time_utc)}. ${selectedCurrency === "MXN" ? "Patrimonio y capital convertidos con esta tasa." : "Vista USD: importes principales sin conversión."}`
    : "Sin tipo de cambio. Se conservan las referencias USD; no se supone una tasa de conversión.";
  paintMetric("equity", money(current.equity_usd));
  el("equity-reference").textContent = `${formatMoney(current.equity_usd)} · dinero simulado observado`;
  el("equity-cutoff").textContent = `Corte: ${date(current.as_of_utc)}`;
  paintMetric("pnl", gainMoney(current.pnl_usd, current.pnl_mxn), selectedCurrency === "MXN" ? current.pnl_mxn : current.pnl_usd);
  el("pnl-reference").textContent = `${formatMoney(current.pnl_usd, "USD", true)} · aportaciones y retiros excluidos`;
  paintMetric("capital-target", money(capital.target_usd));
  el("capital-target-reference").textContent = `${formatMoney(capital.target_usd)} · objetivo configurado`;
  el("capital-applied").textContent = `Aplicado: ${moneyWithReference(capital.applied_usd)}.`;
  const pending = numeric(capital.pending_flow_usd);
  const pendingBlocks = Object.entries(capital.by_sleeve || {}).filter(([, block]) => {
    const value = numeric(block?.pending_flow_usd);
    return value !== null && Math.abs(value) >= 0.0000001;
  });
  if (pendingBlocks.length) {
    const labels = {crypto: "Cripto", stocks: "ETF"};
    const details = pendingBlocks.map(([name, block]) =>
      `${labels[name] || name}: ${moneyWithReference(block.pending_flow_usd, true)}`).join("; ");
    const heading = pending === null ? "Total de ajuste sin verificar. "
      : Math.abs(pending) < 0.0000001 ? "Ajustes entre bloques, sin cambio de capital total. "
        : `${pending < 0 ? "Retiro" : "Aporte"} pendiente total: ${moneyWithReference(pending, true)}. `;
    el("capital-pending").textContent = `${heading}${details}. Próximo ciclo diario; aún no aplicado.`;
  } else {
    el("capital-pending").textContent = pending === null
      ? "Ajuste pendiente sin verificar; el objetivo no es el patrimonio actual."
      : Math.abs(pending) < 0.0000001 ? "Sin ajuste de capital pendiente."
        : `${pending < 0 ? "Retiro" : "Aporte"} pendiente: ${moneyWithReference(pending, true)}. Próximo ciclo diario; aún no aplicado.`;
  }
  paintMetric("in-progress", gainMoney(progress.pnl_usd, progress.pnl_mxn), selectedCurrency === "MXN" ? progress.pnl_mxn : progress.pnl_usd);
  el("in-progress-reference").textContent = `${formatMoney(progress.pnl_usd, "USD", true)} · incluida en la acumulada; aún fuera del diario de cierres`;
  el("in-progress-cutoff").textContent = `Observación: ${date(progress.as_of_utc)}. Cada bloque se compara con su último cierre.`;
  el("daily-currency-note").textContent = selectedCurrency === "MXN"
    ? "Ganancias MXN reportadas con el tipo de cambio de cada cierre, sin usar la tasa actual. Los periodos incompletos se indican en las notas."
    : "Ganancias USD por cierre UTC. Los aportes y retiros se muestran aparte; los periodos incompletos se indican en las notas.";
  dailyRows(data?.daily || []);
  renderBalance(data);
  const notes = el("performance-notes");
  notes.replaceChildren();
  for (const note of data?.notes || []) notes.append(text("li", note));
  notes.hidden = !notes.children.length;
  renderEconomics();
}

function renderEconomics() {
  const base = numeric(lastPerformance?.capital?.applied_usd);
  const cost = numeric(el("monthly-cost").value);
  const income = numeric(el("monthly-income").value);
  const output = el("economics-result");
  if (base === null || base <= 0) {
    output.textContent = "Sin base aplicada verificada; no se calcula un rendimiento necesario.";
    return;
  }
  if (cost === null || income === null || cost < 0 || income < 0 || !Number.isFinite(cost + income)) {
    output.textContent = "Introduce importes válidos de cero o más dólares.";
    return;
  }
  const required = cost + income;
  output.textContent = `Sobre una base de ${formatMoney(base)}, cubrir ${formatMoney(cost)} de gastos y obtener ${formatMoney(income)} requiere ${formatMoney(required)} al mes después del trading: ${(required / base * 100).toFixed(2)}% de la base cada mes. Sólo el gasto suma ${formatMoney(cost * 12)} al año (${(cost * 12 / base * 100).toFixed(2)}% de la base). Es una necesidad aritmética, no una rentabilidad esperada.`;
}

function renderAnalysis(status) {
  const analysis = status?.analysis;
  const summary = analysis?.summary || {};
  const valid = analysis?.valid === true;
  paintMetric("analysis-realized", money(valid ? summary.realized_pnl : null, true), valid ? summary.realized_pnl : null);
  paintMetric("analysis-unrealized", money(valid ? summary.unrealized_pnl : null, true), valid ? summary.unrealized_pnl : null);
  paintMetric("analysis-fees", money(summary.fees));
  el("analysis-count").textContent = summary.n_trades ?? "—";
  el("analysis-status").textContent = !analysis ? "Análisis no disponible para esta versión."
    : valid ? "Resultado recalculado con las operaciones registradas y los precios de cierre indicados. Puede diferir del patrimonio actual por los movimientos posteriores al cierre."
      : `Análisis incompleto: ${(analysis.issues || []).map(item => item.message).join("; ") || "faltan datos para conciliar"}. No se presenta una ganancia total verificada.`;
  const labels = {crypto: "Cripto", stocks: "ETF"};
  el("analysis-cutoff").textContent = Object.entries(analysis?.prices_as_of || {})
    .map(([name, value]) => `${labels[name] || name}: ${value || "sin cierre"}`).join(" · ") || "Sin cortes verificados.";
  if (selectedCurrency === "MXN") el("analysis-cutoff").textContent += " MXN convertido con la tasa actual disponible.";
  const alerts = el("accounting-alerts");
  alerts.replaceChildren();
  for (const [name, sleeve] of Object.entries(status?.live?.sleeves || {})) {
    const cash = numeric(sleeve.cash);
    if (cash !== null && cash < -.00000001) {
      alerts.append(text("li", `${labels[name] || name}: efectivo negativo ${moneyWithReference(cash)}. Pendiente de recuperación mediante ventas simuladas registradas en el próximo cierre elegible; no se añade capital para ocultarlo.`));
    }
  }
  alerts.hidden = !alerts.children.length;
}

function renderOperating(values) {
  const [status, orders, trades, events] = values;
  el("mode").textContent = status.mode === "paper" ? "SIMULADO · PAPER" : "MODO NO VERIFICADO";
  el("status").textContent = status.reason;
  el("status").className = `status ${status.ready ? "ok" : ""}`;
  el("pending").textContent = status.storage?.pending_orders ?? "—";
  el("unknown").textContent = `${status.storage?.unknown_orders ?? 0} con resultado desconocido`;
  el("heartbeat").textContent = date(status.runtime?.last_success_utc);
  el("build").textContent = status.runtime?.build_id ? `Versión ${status.runtime.build_id.slice(0, 16)}` : "Sin ejecución verificada";
  el("backup").textContent = date(status.last_backup?.created_at_utc);
  sleeves(status);
  renderAnalysis(status);
  rows("orders", orders.items, [o => o.asset, o => o.side, o => o.status,
    o => o.filled_qty ?? o.applied_qty ?? 0, o => date(o.updated_at || o.created_at)]);
  rows("trades", trades.items, [t => date(t.run_at_utc), t => t.sleeve, t => t.asset,
    t => t.side, t => moneyWithReference(t.value), t => t.cost_bps ?? "—"]);
  el("trade-value-title").textContent = `Valor ${selectedCurrency}`;
  el("trade-currency-note").textContent = selectedCurrency === "MXN"
    ? "Valores MXN convertidos con el tipo de cambio actual disponible; no son la conversión histórica del día de la operación. Se conserva la referencia USD."
    : "Valores originales en USD; la conversión opcional a MXN usa el tipo de cambio actual disponible.";
  el("events").replaceChildren();
  for (const event of events.items) {
    const li = document.createElement("li");
    li.append(text("span", event.kind), text("time", date(event.created_at)));
    el("events").append(li);
  }
  if (!events.items.length) el("events").append(text("li", "Sin eventos."));
}

function renderExecutionQuality(data) {
  const crypto = data.by_sleeve?.crypto || {};
  const cost = numeric(crypto.book_cost_bps);
  el("execution-status").textContent = `Diagnóstico actualizado ${date(data.as_of_utc)}. La regla vigente continúa; la variante de menor rotación espera validación.`;
  el("execution-cost").textContent = cost === null ? "Sin dato" : `${cost.toFixed(1)} bps`;
  el("execution-cost-coverage").textContent = `${crypto.book_cost_trades || 0} operaciones medidas · ${crypto.assumed_cost_trades || 0} con costo supuesto`;
  const maker = numeric(crypto.maker_share);
  el("execution-maker").textContent = maker === null ? "Sin dato" : `${(maker * 100).toFixed(1)}%`;
  el("execution-maker-coverage").textContent = `${crypto.maker_known_trades || 0} operaciones con importes maker/taker registrados`;
  el("execution-reentries").textContent = String(crypto.reentries_48h?.length || 0);
  el("execution-liquidity").textContent = crypto.liquidity_known_trades ? `${crypto.liquidity_warnings} alertas` : "Sin dato";
  const wait = numeric(crypto.mean_execution_wait_s);
  el("execution-wait").textContent = wait === null ? "Sin medición de tiempo de ejecución" : `${wait.toFixed(1)} s por ejecución · ${crypto.liquidity_known_trades} libros medidos`;
}

async function refreshExecutionQuality() {
  try {
    renderExecutionQuality(await fetchJson("/api/execution-quality"));
  } catch (_) {
    el("execution-status").textContent = "No se pudo actualizar el diagnóstico. Los valores visibles pueden estar desactualizados.";
  }
}

async function refreshEvidence() {
  const labels = {crypto: "Cripto", stocks: "ETF"};
  try {
    const data = await fetchJson("/api/evidence");
    const states = {pending: "Esperando la primera captura.", collecting: "Registro de datos activo.",
      partial: "Registro parcial: hay datos o comprobaciones pendientes.", stale: "La última captura de datos está vencida.",
      error: "La integridad de la evidencia requiere revisión."};
    el("evidence-status").textContent = states[data.status] || "Evidencia sin verificar.";
    el("evidence-market-count").textContent = String(data.counts?.market || 0);
    el("evidence-cutoff").textContent = data.market ? `Última captura ${date(data.market.observed_at_utc)}` : "Sin captura verificada";
    el("evidence-replay-count").textContent = String(data.counts?.execution || 0);
    el("evidence-replay-note").textContent = "Decisiones archivadas; el resultado de reproducción se muestra por bloque.";
    el("evidence-details").replaceChildren();
    for (const [name, check] of Object.entries(data.market?.signal_replay || {})) {
      const passed = check.passed === true || check.status === "passed" || check.status === "ok";
      el("evidence-details").append(text("li", `${labels[name] || name}: señal sobre datos congelados ${passed ? "reproducida" : "pendiente de verificar"}.`));
    }
    for (const [name, capture] of Object.entries(data.execution || {})) {
      const descriptions = {verified: "reproducción verificada", verified_no_orders: "reproducción verificada sin órdenes",
        mismatch: "reproducción con diferencias; requiere revisión", unavailable: "reproducción pendiente por falta de evidencia"};
      el("evidence-details").append(text("li", `${labels[name] || name}: decisión del ${capture.candle || "cierre sin identificar"}, ${descriptions[capture.status] || "reproducción pendiente"}.`));
      if (["blocked", "pending", "error"].includes(capture.replay?.decision_status)) {
        el("evidence-details").append(text("li", `${labels[name] || name}: la decisión original requiere revisión operativa (${capture.replay.decision_status}). Reproducirla no elimina ese pendiente.`));
      }
    }
    if (!Object.keys(data.execution || {}).length) {
      el("evidence-details").append(text("li", "La primera reproducción de operaciones se registrará cuando el bot procese su siguiente cierre elegible."));
    }
    if (data.last_collection?.status === "error") {
      el("evidence-details").append(text("li", "La última recolección falló; el sistema reintenta sin generar órdenes."));
    }
    el("evidence-limitations").replaceChildren();
    for (const note of data.limitations || []) el("evidence-limitations").append(text("li", note));
  } catch (_) {
    el("evidence-status").textContent = "No se pudo actualizar la evidencia. Los valores visibles pueden estar desactualizados.";
  }
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  el("refresh").disabled = true;
  const comparisonUpdate = comparison();
  const executionUpdate = refreshExecutionQuality();
  const evidenceUpdate = refreshEvidence();
  try {
    const [operating, performance] = await Promise.allSettled([
      Promise.all([fetchJson("/api/status"), fetchJson("/api/orders"), fetchJson("/api/trades"), fetchJson("/api/events?limit=15")]),
      fetchJson("/api/performance")
    ]);
    if (performance.status === "fulfilled") {
      lastPerformance = performance.value;
      el("performance-status").hidden = true;
    } else {
      el("performance-status").hidden = false;
      el("performance-status").textContent = lastPerformance
        ? "No se pudieron actualizar las ganancias. Los valores financieros visibles pertenecen a la última lectura y pueden estar desactualizados."
        : "No se pudieron leer las ganancias ni el capital. El estado operativo se consulta por separado.";
    }
    renderPerformance(lastPerformance);
    if (operating.status === "fulfilled") {
      lastOperating = operating.value;
      renderOperating(lastOperating);
      el("updated").textContent = `Estado operativo actualizado ${new Date().toLocaleString("es-MX")}. Los cortes financieros y de mercado se indican por separado.`;
    } else {
      el("status").textContent = "Conexión operativa no disponible. Los datos de salud, órdenes y posiciones visibles pueden estar desactualizados.";
      el("status").className = "status error";
    }
  } finally {
    await comparisonUpdate;
    await executionUpdate;
    await evidenceUpdate;
    el("refresh").disabled = false;
    refreshing = false;
  }
}
el("currency").value = selectedCurrency;
el("currency").addEventListener("change", () => {
  selectedCurrency = el("currency").value === "USD" ? "USD" : "MXN";
  try { localStorage.setItem("trading-lab-currency", selectedCurrency); } catch (_) { /* Optional preference. */ }
  renderPerformance(lastPerformance);
  if (lastOperating) {
    // Reformat only currency-sensitive content; preserve any stale-data status warning.
    sleeves(lastOperating[0]);
    renderAnalysis(lastOperating[0]);
    rows("trades", lastOperating[2].items, [t => date(t.run_at_utc), t => t.sleeve, t => t.asset,
      t => t.side, t => moneyWithReference(t.value), t => t.cost_bps ?? "—"]);
    el("trade-value-title").textContent = `Valor ${selectedCurrency}`;
    el("trade-currency-note").textContent = selectedCurrency === "MXN"
      ? "Valores MXN convertidos con el tipo de cambio actual disponible; no son la conversión histórica del día de la operación. Se conserva la referencia USD."
      : "Valores originales en USD; la conversión opcional a MXN usa el tipo de cambio actual disponible.";
  }
});
el("refresh").addEventListener("click", refresh);
el("monthly-cost").addEventListener("input", renderEconomics);
el("monthly-income").addEventListener("input", renderEconomics);
el("balance-sleeve").addEventListener("change", () => renderBalance(lastPerformance));
el("balance-period").addEventListener("change", () => renderBalance(lastPerformance));
el("balance-day").addEventListener("input", () => selectBalanceDay(Number(el("balance-day").value)));
let balanceResizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(balanceResizeTimer);
  balanceResizeTimer = setTimeout(() => renderBalance(lastPerformance), 150);
});
refresh();
setInterval(refresh, 30000);
