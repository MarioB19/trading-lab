"use strict";
// Pestañas del panel único (F3): Piloto (atribución), Investigación y Arena (archivo). Solo lectura.
(() => {
  const $ = (id) => document.getElementById(id);
  const num = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v)) ? null : Number(v));
  const usd = (v, signed = true) => {
    const n = num(v);
    if (n === null) return "sin dato";
    return new Intl.NumberFormat("es-MX", {style: "currency", currency: "USD", currencyDisplay: "code",
      maximumFractionDigits: 2, signDisplay: signed ? "exceptZero" : "auto"}).format(n);
  };
  const pct = (v) => (num(v) === null ? "sin dato" : new Intl.NumberFormat("es-MX", {style: "percent",
    maximumFractionDigits: 2, signDisplay: "exceptZero"}).format(Number(v)));
  const cell = (tag, value, cls) => {
    const node = document.createElement(tag);
    node.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
    if (cls) node.className = cls;
    return node;
  };
  const tone = (v) => (num(v) === null || Number(v) === 0 ? "" : Number(v) > 0 ? "gain-positive" : "gain-negative");
  const fill = (id, rows, empty, cols) => {
    const body = $(id);
    body.replaceChildren();
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = cell("td", empty);
      td.colSpan = cols;
      tr.append(td);
      body.append(tr);
      return;
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      for (const item of row) tr.append(Array.isArray(item) ? cell("td", item[0], item[1]) : cell("td", item));
      body.append(tr);
    }
  };
  const getJSON = async (path) => {
    const response = await fetch(path, {credentials: "same-origin", cache: "no-store"});
    if (!response.ok) throw new Error(`${path} respondió ${response.status}`);
    return response.json();
  };
  const isoDay = (stamp) => (stamp ? String(stamp).replace("T", " ").replace(/\.\d+/, "").replace(/(\+00:00|Z)$/, "") : "—");

  // ---- Pestañas -------------------------------------------------------------------------
  const loaded = {};
  const tabs = ["resumen", "operaciones", "investigacion", "sistema", "arena"];
  const loaders = {resumen: loadResumen, operaciones: async () => {}, investigacion: loadResearch, sistema: async () => {}, arena: loadArena};
  function show(name, focus) {
    if (name === "piloto") name = "resumen";
    if (!tabs.includes(name)) name = "resumen";
    for (const tab of tabs) {
      const button = $(`tab-btn-${tab}`), panel = $(`tab-${tab}`);
      const active = tab === name;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      panel.hidden = !active;
      if (active && focus) button.focus();
    }
    if (!loaded[name]) {
      loaded[name] = true;
      loaders[name]().catch(() => { loaded[name] = false; });
    }
  }
  document.querySelectorAll(".tabs [role=tab]").forEach((button) => {
    button.addEventListener("click", () => { history.replaceState(null, "", `#${button.dataset.tab}`); show(button.dataset.tab); });
    button.addEventListener("keydown", (event) => {
      const i = tabs.indexOf(button.dataset.tab);
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        const next = tabs[(i + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        history.replaceState(null, "", `#${next}`);
        show(next, true);
        event.preventDefault();
      }
    });
  });
  window.addEventListener("hashchange", () => show(location.hash.slice(1)));
  document.querySelectorAll("[data-goto]").forEach((link) => {
    link.addEventListener("click", (event) => { event.preventDefault(); history.replaceState(null, "", `#${link.dataset.goto}`); show(link.dataset.goto, true); window.scrollTo({top: 0}); });
  });

  // ---- Resumen: atribución + qué está en prueba -----------------------------------------
  async function loadResumen() {
    await loadAttribution();
    loadTesting().catch(() => {});
  }
  async function loadTesting() {
    const status = $("testing-status"), box = $("testing");
    box.replaceChildren();
    try {
      const data = await getJSON("/api/research");
      const b = data.backlog || {};
      const active = (b.hipotesis || []).filter((h) => /^(✅|🔬)/.test(String(h.estado || "")));
      const cards = active.map((h) => ({tag: String(h.estado).includes("DEC-0") ? (String(h.estado).match(/DEC-\d+/) || ["En el piloto"])[0] : "En el piloto",
        tone: "ok", title: h.titulo || h.idea, note: h.estado}));
      if (b.siguiente) cards.push({tag: "Siguiente sprint", tone: "wait", title: `${b.siguiente.id} · ${b.siguiente.titulo || b.siguiente.idea}`, note: b.siguiente.idea || ""});
      for (const c of cards) {
        const article = document.createElement("article");
        article.className = "testing-card";
        article.append(cell("span", c.tag, `pill ${c.tone}`), cell("strong", c.title), cell("p", c.note, "chart-note"));
        box.append(article);
      }
      status.hidden = true;
      if (!cards.length) { status.hidden = false; status.textContent = "Nada en prueba ahora mismo."; }
    } catch (error) {
      status.textContent = "No se pudo leer el backlog.";
    }
  }

  // ---- Piloto: atribución ---------------------------------------------------------------
  async function loadAttribution() {
    const status = $("attribution-status");
    try {
      const data = await getJSON("/api/attribution");
      const labels = {week: "Semana", days_28: "28 días", since_start: "Desde el primer cierre"};
      const names = {crypto: "Cripto", stocks: "ETFs"};
      const refs = {crypto: "BTC", stocks: "SPY"};
      const rows = [];
      for (const key of ["week", "days_28", "since_start"]) {
        const w = data[key];
        if (!w || w.error) continue;
        const period = `${labels[key]} (${w.start} → ${w.end})`;
        for (const [sleeve, s] of Object.entries(w.sleeves || {})) {
          if (s.error) { rows.push([period, names[sleeve] || sleeve, s.error, "", "", "", "", ""]); continue; }
          rows.push([period, names[sleeve] || sleeve, [usd(s.pnl_usd), tone(s.pnl_usd)],
            `${refs[sleeve] || "ref."} ${pct(s.benchmark_return)}`, [usd(s.market_usd), tone(s.market_usd)],
            [usd(s.strategy_usd), tone(s.strategy_usd)], [usd(-s.costs_usd), tone(-s.costs_usd)], s.trades]);
        }
        const t = w.total;
        const fx = num(w.fx_usd_mxn);
        const mxn = fx ? ` · MXN ${new Intl.NumberFormat("es-MX", {maximumFractionDigits: 0, signDisplay: "exceptZero"}).format(t.pnl * fx)}` : "";
        rows.push([[period, "gain-total"], ["Total", "gain-total"], [`${usd(t.pnl)}${mxn}`, `gain-total ${tone(t.pnl)}`], "",
          [usd(t.market), tone(t.market)], [usd(t.strategy), tone(t.strategy)], [usd(-t.costs), tone(-t.costs)], ""]);
      }
      fill("attribution", rows, "Sin cierres suficientes.", 8);
      status.hidden = true;
    } catch (error) {
      status.textContent = "No se pudo leer la atribución. El resto del panel sigue disponible.";
      throw error;
    }
  }

  // ---- Investigación -------------------------------------------------------------------
  const light = {ok: ["cumple", "ok"], falla: ["no cumple", "fail"], parcial: ["parcial", "wait"],
                 sin_dato: ["sin dato", "wait"], en_curso: ["en curso", "wait"], informativa: ["informativa", ""]};
  async function loadResearch() {
    const status = $("research-status");
    try {
      const data = await getJSON("/api/research");
      const sem = data.semaforo;
      if (sem) {
        $("semaforo-state").textContent = sem.estado === "propuesta" ? `Propuesta · preregistro ${sem.preregistro}` : sem.estado;
        $("semaforo-verdict").textContent = `Control: ${sem.veredicto_control}`;
        $("semaforo-note").textContent = `Banco de prueba: ${sem.banco}`;
        const body = $("semaforo");
        body.replaceChildren();
        for (const m of sem.metricas || []) {
          const tr = document.createElement("tr");
          tr.append(cell("td", m.id), cell("td", m.nombre), cell("td", m.umbral), cell("td", m.control));
          const td = document.createElement("td");
          const [label, cls] = light[m.estado] || [m.estado, ""];
          td.append(cell("span", label, `pill ${cls}`));
          tr.append(td);
          body.append(tr);
        }
      }
      const b = data.backlog;
      if (b) {
        $("backlog-updated").textContent = `Actualizado ${b.actualizado || "—"} · fuente research/backlog.yaml`;
        $("backlog-next").textContent = b.siguiente ? `Siguiente: ${b.siguiente.id} — ${b.siguiente.titulo || b.siguiente.idea}` : "Sin hipótesis pendientes.";
        fill("backlog", (b.hipotesis || []).map((h) => [h.orden, h.id, h.tipo, h.titulo || h.idea,
          h.pausada ? `${h.estado} (en pausa)` : h.estado]), "Sin hipótesis.", 5);
        fill("discarded", (b.descartadas || []).map((h) => [h.id, h.idea, h.motivo]), "Sin descartes.", 3);
        fill("sprints", (b.bitacora || []).map((s) => [s.sprint, s.fecha, s.hipotesis, s.resultado, s.decision]),
          "Sin sprints registrados.", 5);
      }
      status.textContent = data.errors && data.errors.length ? `Datos incompletos: ${data.errors.join(", ")}` : "Investigación al día.";
      status.className = data.errors && data.errors.length ? "status error" : "status ok";
    } catch (error) {
      status.textContent = "No se pudo leer la investigación.";
      status.className = "status error";
      throw error;
    }
    loadCandidates().catch(() => {});
  }

  async function loadCandidates() {
    const status = $("candidates-status"), box = $("candidates");
    box.replaceChildren();
    try {
      const data = await getJSON("/api/candidates");
      const lanes = data.lanes || [];
      const states = {vacio: "vacío", activo: "activo", pausado: "en pausa", cerrado: "cerrado"};
      status.textContent = `${data.active || 0} de ${data.max_active || 2} carriles activos (US$${data.capital_usd || 500} ficticios cada uno). ${data.note || ""}`;
      for (const lane of lanes) {
        const article = document.createElement("article");
        article.className = "sleeve";
        article.append(cell("h3", `${lane.id} · ${states[lane.status] || lane.status || ""}${lane.hypothesis ? ` · ${lane.hypothesis}` : ""}`));
        const dl = document.createElement("dl");
        for (const [k, v] of [["Desde", lane.started_at], ["Patrimonio", usd(lane.equity_usd, false)],
                              ["Contra el control", usd(lane.vs_control_usd)], ["Costos", usd(lane.costs_usd, false)]]) {
          dl.append(cell("dt", k), cell("dd", v));
        }
        article.append(dl);
        box.append(article);
      }
    } catch (error) {
      status.textContent = "Carriles de candidatas no disponibles.";
    }
  }

  // ---- Arena (archivo) -----------------------------------------------------------------
  const NAMES = {"scalping-v1": "Day trading / scalping", "swing-v1": "Swing / tendencias",
                 "mean-reversion-v1": "Reversión a la media", "market-making-v1": "Creación de mercado"};
  async function loadArena() {
    const status = $("arena-status");
    try {
      const data = await getJSON("/api/arena-archive");
      const r = data.summary || {}, total = r.total || {};
      const metrics = $("arena-metrics");
      metrics.replaceChildren();
      for (const [label, value, note] of [["Patrimonio final", usd(total.equity_usd, false), `de ${usd(total.initial_usd, false)} ficticios`],
                                           ["Resultado", usd(total.pnl_usd), "4 estrategias juntas"],
                                           ["Comisiones pagadas", usd(total.fees_usd, false), "ya incluidas en el resultado"],
                                           ["Operaciones", total.fills ?? "—", "todas las del periodo"]]) {
        const article = document.createElement("article");
        article.append(cell("span", label), cell("strong", value), cell("small", note));
        metrics.append(article);
      }
      const period = data.manifest && data.manifest.period;
      $("arena-period").textContent = period ? `${isoDay(period.first_capture_iso)} → ${isoDay(period.last_capture_iso)} UTC` : "—";
      fill("arena-strategies", (r.strategies || []).map((s) => [s.name || NAMES[s.id] || s.id, usd(s.equity_usd, false),
        [usd(s.pnl_usd), tone(s.pnl_usd)], usd(s.fees_usd, false), s.fills, `${s.maker_fills ?? "—"} / ${s.taker_fills ?? "—"}`]),
        "Sin estrategias.", 6);
      drawCurve(data.curve || []);
      drawAudit(data.daily || null);
      $("arena-fills-count").textContent = `${total.fills ?? "—"} operaciones`;
      const src = data.manifest && data.manifest.source;
      $("arena-source").textContent = src ? `Origen: respaldo ${String(src.backup_sha256 || "").slice(0, 12)}… (${src.method || "lab.arena.backup"}), restaurado y auditado. Las capturas crudas de mercado se quedan en el respaldo de la USB.` : "";
      status.textContent = "Archivo fijo de la arena. No hay controles: la arena ya no opera.";
      status.className = "status ok";
    } catch (error) {
      status.textContent = "No se pudo leer el archivo de la arena.";
      status.className = "status error";
      throw error;
    }
  }

  function drawCurve(points) {
    const host = $("arena-chart"), legend = $("arena-legend");
    host.replaceChildren();
    legend.replaceChildren();
    const series = {};
    for (const p of points) (series[p.strategy] ||= []).push([Date.parse(p.ts_iso), num(p.pnl)]);
    const ids = Object.keys(series);
    if (!ids.length) { host.append(cell("p", "Sin curva en el archivo.", "empty")); return; }
    const all = ids.flatMap((id) => series[id]).filter((p) => Number.isFinite(p[0]) && p[1] !== null);
    const x0 = Math.min(...all.map((p) => p[0])), x1 = Math.max(...all.map((p) => p[0]));
    const y0 = Math.min(0, ...all.map((p) => p[1])), y1 = Math.max(0, ...all.map((p) => p[1]));
    const W = 1000, H = 280, L = 56, R = 10, T = 10, B = 26;
    const sx = (x) => L + (x - x0) / Math.max(1, x1 - x0) * (W - L - R);
    const sy = (y) => T + (y1 - y) / Math.max(1e-9, y1 - y0) * (H - T - B);
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Resultado acumulado por estrategia de la arena");
    const line = (x, y, x2, y2, cls) => {
      const l = document.createElementNS(ns, "line");
      Object.entries({x1: x, y1: y, x2, y2}).forEach(([k, v]) => l.setAttribute(k, v));
      l.setAttribute("class", cls);
      svg.append(l);
    };
    const ticks = [];
    for (const v of [y1, 0, (y0 + y1) / 2, y0]) {
      if (ticks.some((u) => Math.abs(sy(u) - sy(v)) < 18)) continue;  // sin etiquetas encimadas
      ticks.push(v);
      line(L, sy(v), W - R, sy(v), "chart-grid");
      const t = document.createElementNS(ns, "text");
      t.setAttribute("x", 4); t.setAttribute("y", sy(v) + 4); t.setAttribute("class", "chart-label");
      t.textContent = usd(v);
      svg.append(t);
    }
    ids.forEach((id, i) => {
      const path = document.createElementNS(ns, "polyline");
      path.setAttribute("points", series[id].filter((p) => p[1] !== null).map((p) => `${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" "));
      path.setAttribute("class", `chart-line series-${i % 4}`);
      svg.append(path);
      const item = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.className = `swatch series-${i % 4}`;
      item.append(swatch, document.createTextNode(NAMES[id] || id));
      legend.append(item);
    });
    host.append(svg);
  }

  function drawAudit(audit) {
    const head = $("arena-audit-head");
    head.replaceChildren();
    const tr = document.createElement("tr");
    for (const label of ["Día (CDMX)", "Patrimonio al abrir", "Patrimonio al cerrar", "Resultado", "Comisiones", "Operaciones", "Notas"]) {
      const th = cell("th", label);
      th.scope = "col";
      tr.append(th);
    }
    head.append(tr);
    const days = (audit && audit.days) || [];
    fill("arena-audit", days.map((d) => [d.date, usd(d.opening_equity, false), usd(d.closing_equity, false),
      [usd(d.net_pnl), tone(d.net_pnl)], usd(d.fees, false), d.operations,
      [d.no_data ? "sin datos" : d.partial_start ? "día parcial (arranque)" : d.error_count ? `${d.error_count} errores de lectura` : "", ""]]),
      "Sin auditoría diaria en el archivo.", 7);
  }

  $("arena-fills-load").addEventListener("click", async () => {
    const button = $("arena-fills-load");
    button.disabled = true;
    try {
      const data = await getJSON("/api/arena-archive/fills");
      fill("arena-fills", (data.items || []).map((f) => [isoDay(f.ts_iso || f.time || f.ts), NAMES[f.strategy] || f.strategy,
        f.side === "buy" ? "Compra" : f.side === "sell" ? "Venta" : f.side, num(f.qty)?.toFixed(6), usd(f.price, false),
        usd(f.value, false), usd(f.fee, false), f.liquidity]), "Sin operaciones.", 8);
      $("arena-fills-wrap").hidden = false;
      button.hidden = true;
    } catch (error) {
      button.disabled = false;
      button.textContent = "No se pudieron leer; reintentar";
    }
  });

  show(location.hash.slice(1) || "piloto");
})();
