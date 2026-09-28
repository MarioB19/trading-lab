"use strict";
const el = (id) => document.getElementById(id);
const money = (value) => Number.isFinite(Number(value)) && value !== null && value !== ""
  ? new Intl.NumberFormat("es-MX", {style: "currency", currency: "USD", maximumFractionDigits: 2}).format(Number(value)) : "—";
const date = (value) => value ? String(value).replace("T", " ").replace(/\.\d+/, "").replace("+00:00", " UTC") : "—";
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
  let total = 0, valid = 0;
  for (const name of new Set([...Object.keys(snapshot), ...Object.keys(live)])) {
    const base = snapshot[name] || {};
    const latest = live[name] || {};
    const data = {...base, ...latest};
    const card = text("article", null, "sleeve");
    card.replaceChildren(text("h3", data.label || name));
    const dl = document.createElement("dl");
    for (const [label, value] of [
      ["Capital", money(data.equity)], ["Efectivo", money(data.cash)],
      ["Caída reportada", data.drawdown == null ? "—" : `${(data.drawdown * 100).toFixed(2)}%`],
      ["Kill switch", data.kill_switch ? "ACTIVADO" : "No activado"],
      ["Ejecución diaria", base.status || "—"], ["Observación", latest.status || "—"],
      ["Corte UTC", date(data.prices_as_of_utc || data.last_run_utc)]
    ]) dl.append(text("dt", label), text("dd", value));
    card.append(dl);
    const positions = data.positions || data.assets?.filter(a => Number(a.qty) > 0) || [];
    if (positions.length) card.append(text("p", positions.map(p =>
      `${p.asset}: ${Number(p.qty).toLocaleString("es-MX", {maximumFractionDigits: 6})}`).join(" · ")));
    const notes = new Set([...(base.notes || []), ...(latest.notes || []), ...(data.alerts || [])]);
    for (const note of notes) card.append(text("p", note));
    target.append(card);
    if (Number.isFinite(data.equity)) { total += data.equity; valid++; }
  }
  if (!target.children.length) target.append(text("p", "Pendiente de importar el estado.", "empty"));
  el("equity").textContent = valid ? money(total) : "—";
  const rate = status.live?.fx?.rate;
  el("fx").textContent = rate && valid
    ? `${new Intl.NumberFormat("es-MX", {style: "currency", currency: "MXN"}).format(total * rate)} MXN · tipo de cambio ${rate}`
    : "USD · revisar modo y corte de los datos";
}

async function fetchJson(path) {
  const response = await fetch(path, {cache: "no-store", signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error("No se pudo leer el estado operativo");
  return response.json();
}

async function comparison() {
  const target = el("comparison");
  target.replaceChildren();
  el("comparison-checks").textContent = "";
  el("comparison-paper").textContent = "";
  try {
    const data = await fetchJson("/api/comparison");
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
          ["Capital final cripto", money(values.final_equity_usd)], ["Costos modelados", money(values.cost_usd)]]) {
          dl.append(text("dt", label), text("dd", value));
        }
        card.append(dl); target.append(card);
      }
      const labels = {cagr: "rentabilidad", sharpe: "retorno frente a variación", drawdown: "caída máxima",
        walk_forward: "ventanas anuales", bootstrap: "remuestreo", placebo: "placebo", cost_stress: "costos mayores"};
      const failed = Object.entries(report.checks).filter(([, passed]) => !passed).map(([name]) => labels[name] || name);
      el("comparison-checks").textContent = failed.length
        ? `La candidata no supera todos los criterios. Fallan: ${failed.join(", ")}. No se promueve.`
        : "Supera los criterios retrospectivos registrados. Aún requiere validación prospectiva y revisión humana.";
    }
    const paper = data.paper;
    el("comparison-paper").textContent = paper?.observed_days != null
      ? `Seguimiento simulado: ${paper.observed_days} días observados de 28; ${paper.elapsed_days} días transcurridos. Último ciclo: ${date(paper.health?.last_success || paper.generated_at)}. Estado: ${paper.status}. Dinero real desactivado.`
      : "Seguimiento simulado futuro: todavía sin observaciones disponibles en este panel.";
    if (paper?.generated_at && Date.now() - Date.parse(paper.generated_at) > 36 * 3600 * 1000) {
      el("comparison-paper").append(text("strong", " Sin observación reciente; revisa el ejecutor."));
    }
  } catch (_) {
    el("comparison-status").textContent = "No se pudo verificar la comparación. Revisa los archivos y el servicio; no hay resultados confirmados disponibles.";
  }
}

async function refresh() {
  el("refresh").disabled = true;
  const comparisonUpdate = comparison();
  try {
    const [status, orders, trades, events] = await Promise.all([
      fetchJson("/api/status"), fetchJson("/api/orders"),
      fetchJson("/api/trades"), fetchJson("/api/events?limit=15")
    ]);
    el("mode").textContent = status.mode === "paper" ? "SIMULADO · PAPER" : "MODO NO VERIFICADO";
    el("status").textContent = status.reason;
    el("status").className = `status ${status.ready ? "ok" : ""}`;
    el("pending").textContent = status.storage?.pending_orders ?? "—";
    el("unknown").textContent = `${status.storage?.unknown_orders ?? 0} con resultado desconocido`;
    el("heartbeat").textContent = date(status.runtime?.last_success_utc);
    el("build").textContent = status.runtime?.build_id ? `Versión ${status.runtime.build_id.slice(0, 16)}` : "Sin ejecución verificada";
    el("backup").textContent = date(status.last_backup?.created_at_utc);
    sleeves(status);
    rows("orders", orders.items, [o => o.asset, o => o.side, o => o.status,
      o => o.filled_qty ?? o.applied_qty ?? 0, o => date(o.updated_at || o.created_at)]);
    rows("trades", trades.items, [t => date(t.run_at_utc), t => t.sleeve, t => t.asset,
      t => t.side, t => money(t.value), t => t.cost_bps ?? "—"]);
    el("events").replaceChildren();
    for (const event of events.items) {
      const li = document.createElement("li");
      li.append(text("span", event.kind), text("time", date(event.created_at)));
      el("events").append(li);
    }
    if (!events.items.length) el("events").append(text("li", "Sin eventos."));
    el("updated").textContent = `Panel actualizado ${new Date().toLocaleString("es-MX")}. Los cortes de mercado se indican por bloque.`;
  } catch (error) {
    el("status").textContent = `Conexión no disponible. ${error.message}. Los datos visibles pueden estar desactualizados.`;
    el("status").className = "status error";
  } finally {
    await comparisonUpdate;
    el("refresh").disabled = false;
  }
}
el("refresh").addEventListener("click", refresh);
refresh();
setInterval(refresh, 30000);
