"""Genera el informe: informe.md (texto, para subir a un Proyecto de Claude) e informe.html (con gráficas)."""
from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

NAMES = {
    "BUY & HOLD": "Comprar y aguantar",
    "WALK-FORWARD (elige la mejor cada año)": "Optimizador: elige la mejor cada año",
    "wf:sma_trend": "Precio vs. promedio móvil",
    "wf:sma_cross": "Cruce de promedios",
    "wf:tsmom": "Momentum (rendimiento pasado > 0)",
    "wf:donchian": "Ruptura de canal (Donchian)",
    "wf:rsi_reversion": "Reversión a la media (RSI)",
    "wf:trend_ensemble": "Tendencia promediada",
    "wf:trend_ensemble_vt": "Tendencia promediada + control de volatilidad",
    "wf:ml_model": "Machine learning (logística / boosting)",
}


def nice(name: str) -> str:
    if name.startswith("CANDIDATA"):
        return "Regla candidata: tendencia promediada 20/50/100/200"
    return NAMES.get(name, name)


def pct(x, d=0, sign=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    if abs(x) < 0.5 * 10 ** (-(d + 2)):
        x = 0.0  # evita "−0.0%"
    s = f"{x:+.{d}%}" if sign else f"{x:.{d}%}"
    return s.replace("-", "−")


def money(x):
    return f"${x:,.0f}"


# ---------------------------------------------------------------- SVG helpers
W, H = 900, 300
ML, MR, MT, MB = 58, 16, 14, 30


def _x_scale(n):
    return lambda i: ML + (W - ML - MR) * i / max(1, n - 1)


def svg_lines(dates, series, log=False, height=H, yfmt=lambda v: f"{v:g}", yticks=None,
              chart_id="c", zero_line=False):
    """series: list of (name, values, css_var). Devuelve SVG con escala única."""
    n = len(dates)
    allv = np.concatenate([np.asarray(v, float) for _, v, _ in series])
    lo, hi = np.nanmin(allv), np.nanmax(allv)
    if log:
        lo, hi = np.log(lo * 0.92), np.log(hi * 1.08)
        fy = lambda v: np.log(v)  # noqa: E731
    else:
        pad = (hi - lo) * 0.06
        lo, hi = lo - pad, max(hi + pad, 0 if zero_line else hi + pad)
        fy = lambda v: v  # noqa: E731
    ys = lambda v: MT + (height - MT - MB) * (1 - (fy(v) - lo) / (hi - lo))  # noqa: E731
    xs = _x_scale(n)
    out = [f'<svg viewBox="0 0 {W} {height}" class="chart" role="img" id="{chart_id}" '
           f'preserveAspectRatio="xMidYMid meet">']
    for t in (yticks or []):
        y = ys(t)
        if MT - 1 <= y <= height - MB + 1:
            out.append(f'<line x1="{ML}" x2="{W-MR}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                       f'<text x="{ML-8}" y="{y+4:.1f}" class="tick" text-anchor="end">{yfmt(t)}</text>')
    years = pd.DatetimeIndex(dates).year
    for i in range(1, n):
        if years[i] != years[i - 1]:
            x = xs(i)
            out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{height-MB}" y2="{height-MB+5}" class="axis"/>'
                       f'<text x="{x:.1f}" y="{height-MB+19}" class="tick" text-anchor="middle">{years[i]}</text>')
    out.append(f'<line x1="{ML}" x2="{W-MR}" y1="{height-MB}" y2="{height-MB}" class="axis"/>')
    for name, vals, var in series:
        pts = " ".join(f"{xs(i):.1f},{ys(v):.1f}" for i, v in enumerate(vals))
        out.append(f'<polyline points="{pts}" fill="none" stroke="var({var})" stroke-width="2" '
                   f'stroke-linejoin="round" stroke-linecap="round"><title>{html.escape(name)}</title></polyline>')
    out.append(f'<line class="xhair" x1="0" x2="0" y1="{MT}" y2="{height-MB}" visibility="hidden"/>')
    out.append(f'<rect class="hit" x="{ML}" y="{MT}" width="{W-ML-MR}" height="{height-MT-MB}" fill="transparent"/>')
    out.append("</svg>")
    return "".join(out)


def svg_hist(values, marker, marker_label, var="--series-1", height=240):
    counts, edges = np.histogram(values, bins=36)
    lo, hi = min(edges[0], marker - 0.05), max(edges[-1], marker + 0.05)
    xs = lambda v: ML + (W - ML - MR) * (v - lo) / (hi - lo)  # noqa: E731
    cmax = counts.max()
    ys = lambda c: MT + (height - MT - MB) * (1 - c / (cmax * 1.1))  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {height}" class="chart" role="img" preserveAspectRatio="xMidYMid meet">']
    for t in np.arange(np.ceil(lo * 4) / 4, hi, 0.25):
        x = xs(t)
        out.append(f'<text x="{x:.1f}" y="{height-MB+19}" class="tick" text-anchor="middle">{t:.2f}</text>')
    out.append(f'<line x1="{ML}" x2="{W-MR}" y1="{height-MB}" y2="{height-MB}" class="axis"/>')
    for c, a, b in zip(counts, edges[:-1], edges[1:]):
        x0, x1 = xs(a) + 1, xs(b) - 1
        y = ys(c)
        out.append(f'<rect x="{x0:.1f}" y="{y:.1f}" width="{max(0.5, x1-x0):.1f}" height="{height-MB-y:.1f}" '
                   f'rx="2" class="neutral-bar"><title>Sharpe {a:.2f}–{b:.2f}: {c} versiones al azar</title></rect>')
    xm = xs(marker)
    out.append(f'<line x1="{xm:.1f}" x2="{xm:.1f}" y1="{MT}" y2="{height-MB}" stroke="var({var})" stroke-width="2.5"/>'
               f'<text x="{xm-8:.1f}" y="{MT+14}" class="lbl" text-anchor="end">{html.escape(marker_label)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_ranges(rows, ref, height=170):
    """rows: (label, p5, p25, p50, p75, p95, css_var). Caja 25–75, bigote 5–95, punto = mediana."""
    lo = min(r[1] for r in rows + [("", ref, 0, 0, 0, 0, "")]) * 0.9
    hi = max(r[5] for r in rows) * 1.05
    left = 170
    xs = lambda v: left + (W - left - MR - 20) * (v - lo) / (hi - lo)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {height}" class="chart" role="img" preserveAspectRatio="xMidYMid meet">']
    step = 5000 if hi < 60000 else 10000
    for t in np.arange(np.ceil(lo / step) * step, hi, step):
        x = xs(t)
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{MT}" y2="{height-MB}" class="grid"/>'
                   f'<text x="{x:.1f}" y="{height-MB+19}" class="tick" text-anchor="middle">{money(t)}</text>')
    xr = xs(ref)
    out.append(f'<line x1="{xr:.1f}" x2="{xr:.1f}" y1="{MT-4}" y2="{height-MB}" class="ref"/>')
    band = (height - MT - MB) / len(rows)
    for k, (lab, p5, p25, p50, p75, p95, var) in enumerate(rows):
        yc = MT + band * (k + 0.5)
        out.append(f'<text x="{left-14}" y="{yc+4:.1f}" class="lbl" text-anchor="end">{html.escape(lab)}</text>')
        out.append(f'<line x1="{xs(p5):.1f}" x2="{xs(p95):.1f}" y1="{yc:.1f}" y2="{yc:.1f}" stroke="var({var})" stroke-width="2"/>')
        out.append(f'<rect x="{xs(p25):.1f}" y="{yc-9:.1f}" width="{xs(p75)-xs(p25):.1f}" height="18" rx="4" '
                   f'fill="var({var})" fill-opacity="0.28" stroke="var({var})" stroke-width="1.5">'
                   f'<title>{lab}: 50% de los casos entre {money(p25)} y {money(p75)}</title></rect>')
        out.append(f'<circle cx="{xs(p50):.1f}" cy="{yc:.1f}" r="5" fill="var({var})" stroke="var(--surface)" stroke-width="2">'
                   f'<title>Mediana {money(p50)}</title></circle>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- informe
def verdict(res):
    o = res["oos"]
    cand = next(v for k, v in o.items() if k.startswith("CANDIDATA"))
    bh = o["BUY & HOLD"]
    wf = o["WALK-FORWARD (elige la mejor cada año)"]
    pl = res["placebo"]["candidate"]
    bs = res["bootstrap_vs_buyhold"]["candidate"]
    mc = res["monte_carlo_12m"]["candidate"]
    lines = []
    lines.append(
        f"De {res['settings']['oos_start_year']} a hoy, fuera de muestra, la regla candidata rindió "
        f"{pct(cand['cagr'])} anual contra {pct(bh['cagr'])} de solo tener BTC, con una caída máxima de "
        f"{pct(cand['max_dd'])} contra {pct(bh['max_dd'])}.")
    if pl["p_value"] < 0.05:
        lines.append(f"Su timing supera al azar (p = {pl['p_value']:.3f}): es una ventaja medible en el pasado, no un accidente.")
    else:
        lines.append(f"Su timing no se distingue del azar (p = {pl['p_value']:.3f}).")
    lines.append(
        f"Lo que más aporta es reducir el daño en los desplomes: la probabilidad de que tenga menos caída que comprar y "
        f"aguantar es {pct(bs['p_drawdown_smaller'])}, pero la de que gane MÁS dinero es solo {pct(bs['p_return_better'])}.")
    if wf["cagr"] < cand["cagr"]:
        lines.append(
            f"El optimizador que cada año cambia a la estrategia que mejor venía funcionando rindió {pct(wf['cagr'])}: "
            f"buscar la regla más lista empeoró el resultado frente a dejar una regla fija.")
    else:
        lines.append(f"El optimizador que cambia de estrategia cada año rindió {pct(wf['cagr'])}.")
    lines.append(
        f"En cualquier periodo de 12 meses hay alrededor de {pct(mc['p_loss'])} de probabilidad de terminar con pérdida.")
    return lines


def write_report(res: dict, extras: dict, out_dir: Path) -> None:
    out_dir.mkdir(exist_ok=True)
    (out_dir / "informe.md").write_text(markdown(res))
    (out_dir / "informe.html").write_text(html_page(res, extras))


def _oos_rows(res):
    order = ["BUY & HOLD"] + [k for k in res["oos"] if k.startswith("CANDIDATA")] + \
            ["WALK-FORWARD (elige la mejor cada año)"] + \
            sorted([k for k in res["oos"] if k.startswith("wf:")], key=lambda k: -res["oos"][k]["sharpe"])
    return [(k, res["oos"][k]) for k in order]


def markdown(res: dict) -> str:
    S = res["settings"]
    L = [f"# Informe del laboratorio de trading BTC",
         f"Datos {res['data']['btc_first']} a {res['data']['btc_last']} · costo por operación "
         f"{S['cost_per_side']:.2%} por lado · fuera de muestra desde {S['oos_start_year']}.", "",
         "## Veredicto", ""]
    L += [f"- {x}" for x in verdict(res)]
    L += ["", f"## Resultados fuera de muestra ({S['oos_start_year']}–hoy)", "",
          "| Estrategia | Rend. anual | Sharpe | Caída máx. | Tiempo dentro | Operaciones/año |",
          "|---|---:|---:|---:|---:|---:|"]
    for k, p in _oos_rows(res):
        L.append(f"| {nice(k)} | {pct(p['cagr'],1)} | {p['sharpe']:.2f} | {pct(p['max_dd'])} | "
                 f"{pct(p['exposure'])} | {p['trades_per_year']:.0f} |")
    ib = res["in_sample_best"]
    pl, bs = res["placebo"], res["bootstrap_vs_buyhold"]
    zd, eth, rc, ml = res["zero_drift"], res["eth_check"], res["recent"], res["ml"]
    L += ["", "## ¿Ventaja real o suerte?", "",
          f"- **Pruebas múltiples:** se probaron {ib['dsr_vs_zero']['n_trials']} variantes. La mejor en todo el periodo "
          f"fue `{ib['name']}` (Sharpe {ib['sharpe']:.2f}). Sharpe deflactado contra cero: "
          f"{ib['dsr_vs_zero']['dsr']:.3f}; contra comprar y aguantar: {ib['dsr_active_vs_buyhold']['dsr']:.3f}. "
          "Es decir: le gana a no invertir, pero no hay evidencia de que gane más dinero que solo tener BTC.",
          f"- **Placebo (posiciones desfasadas al azar):** candidata Sharpe {pl['candidate']['actual_sharpe']:.2f} vs "
          f"mediana al azar {pl['candidate']['placebo_median']:.2f} (p = {pl['candidate']['p_value']:.3f}); "
          f"optimizador p = {pl['walk_forward']['p_value']:.3f}.",
          f"- **Bootstrap contra comprar y aguantar (candidata):** P(mejor Sharpe) {pct(bs['candidate']['p_sharpe_better'])}, "
          f"P(más rendimiento) {pct(bs['candidate']['p_return_better'])}, P(menor caída) {pct(bs['candidate']['p_drawdown_smaller'])}.",
          f"- **BTC sin tendencia anual** (cada año termina donde empezó): candidata {pct(zd['candidate']['cagr'],1)} anual "
          f"vs {pct(zd['buy_hold']['cagr'],1)} de comprar y aguantar.",
          f"- **ETH, sin re-optimizar:** candidata {pct(eth['candidate']['cagr'],1)} anual, caída máx. {pct(eth['candidate']['max_dd'])}; "
          f"comprar y aguantar {pct(eth['buy_hold']['cagr'],1)}, caída máx. {pct(eth['buy_hold']['max_dd'])}.",
          f"- **Desde {rc['since'][:4]} (mercado más maduro):** candidata {pct(rc['candidate']['cagr'],1)} anual, caída "
          f"{pct(rc['candidate']['max_dd'])}; comprar y aguantar {pct(rc['buy_hold']['cagr'],1)}, caída {pct(rc['buy_hold']['max_dd'])}.",
          f"- **Machine learning:** AUC fuera de muestra al predecir si BTC sube en 5 días: logística "
          f"{ml['logistic']['auc']:.3f}, boosting {ml['gbm']['auc']:.3f} (0.5 = moneda al aire).", "",
          "## Sensibilidad a comisiones (rendimiento anual fuera de muestra)", "",
          "| Costo por lado | Candidata | Optimizador | Comprar y aguantar |", "|---|---:|---:|---:|"]
    for c, v in res["cost_sensitivity"].items():
        L.append(f"| {c} | {pct(v['candidate_cagr'],1)} | {pct(v['walk_forward_cagr'],1)} | {pct(v['buy_hold_cagr'],1)} |")
    L += ["", "## Año por año", "", "| Año | Comprar y aguantar | Candidata | Optimizador |", "|---|---:|---:|---:|"]
    for y, v in res["yearly"].items():
        L.append(f"| {y} | {pct(v['buy_hold'],0,True)} | {pct(v['candidate'],0,True)} | {pct(v['walk_forward'],0,True)} |")
    mc = res["monte_carlo_12m"]
    L += ["", f"## Riesgo a 12 meses con {money(mc['candidate']['capital'])} (Monte Carlo por bloques)", "",
          "| | Peor 5% | Mediana | Mejor 5% | P(pérdida) | P(caída >30% en el camino) | P(caída >50%) |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for k, lab in (("candidate", "Candidata"), ("buy_hold", "Comprar y aguantar")):
        m = mc[k]
        L.append(f"| {lab} | {money(m['final_p5'])} | {money(m['final_median'])} | {money(m['final_p95'])} | "
                 f"{pct(m['p_loss'])} | {pct(m['p_dd_30'])} | {pct(m['p_dd_50'])} |")
    k = res["kelly_candidate_oos"]
    L += ["", "## Tamaño de posición", "",
          f"Kelly estimado de la candidata: {k['kelly']:.2f} (intervalo ±2σ: {k['kelly_low']:.2f} a {k['kelly_high']:.2f}). "
          f"El rendimiento esperado anual va de {pct(k['mu_annual_low'])} a {pct(k['mu_annual_high'])} con el mismo intervalo. "
          "Esa incertidumbre es la razón para NO usar apalancamiento y operar solo capital que puedas perder.", "",
          "## Señal de hoy", "",
          f"Cierre {res['today']['date']}: {money(res['today']['close'])} USD. Exposición objetivo de la candidata: "
          f"{pct(res['today']['candidate_target'])}.", "",
          "## Qué supone este análisis", "",
          "- Precios diarios de cierre (CoinMetrics + Kraken). Se decide al cierre y se ejecuta al siguiente precio.",
          "- Sin cortos ni apalancamiento. El efectivo no genera intereses (en la vida real podría estar en CETES).",
          "- El pasado de BTC incluye una subida de cientos de veces que no se va a repetir; los números absolutos "
          "están inflados por eso. La comparación relevante es contra comprar y aguantar.",
          "- Impuestos, tipo de cambio MXN/USD y fallas del exchange no están modelados."]
    return "\n".join(L) + "\n"


CSS = """
:root{--bg:#f5f6f7;--surface:#ffffff;--ink:#101418;--ink-2:#434b55;--muted:#6c7581;--rule:#dfe3e8;
--grid:#e9ecef;--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--neutral-mark:#b9c0c8;
--good:#0ca30c;--critical:#d03b3b;--chip:#eef1f4}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111315;--surface:#1a1c1f;
--ink:#f2f4f6;--ink-2:#c3c8ce;--muted:#8e969f;--rule:#2d3136;--grid:#25292d;--series-1:#3987e5;--series-2:#d95926;
--series-3:#199e70;--neutral-mark:#4a5058;--chip:#24282c}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111315;--surface:#1a1c1f;--ink:#f2f4f6;--ink-2:#c3c8ce;--muted:#8e969f;
--rule:#2d3136;--grid:#25292d;--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--neutral-mark:#4a5058;--chip:#24282c}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:15px/1.6 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
padding-inline:16px;padding-block:32px 64px}
.wrap{max-width:960px;margin:0 auto;display:grid;gap:40px}
.prose{max-width:68ch}
h1,h2{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",system-ui,sans-serif;text-wrap:balance;margin:0;line-height:1.15}
h1{font-size:clamp(28px,5vw,42px);font-weight:600;letter-spacing:-.01em}
h2{font-size:22px;font-weight:600}
p{margin:0}
.eyebrow{font:500 12px/1.4 "IBM Plex Mono",ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.mono,td.n,.stat b{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
header{display:grid;gap:10px}
header p{color:var(--ink-2);max-width:68ch}
section{display:grid;gap:14px}
.verdict{background:var(--surface);border:1px solid var(--rule);border-radius:10px;padding:22px;display:grid;gap:18px}
.verdict ul{margin:0;padding-left:1.1em;display:grid;gap:8px;max-width:72ch}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.stat{border-top:2px solid var(--rule);padding-top:10px;display:grid;gap:2px}
.stat b{font-size:26px;font-weight:500}
.stat span{color:var(--muted);font-size:13px}
.stat .vs{color:var(--ink-2);font-size:13px}
.panel{background:var(--surface);border:1px solid var(--rule);border-radius:10px;padding:16px 16px 8px}
.chart{width:100%;height:auto;display:block;overflow:visible}
.chart .grid{stroke:var(--grid);stroke-width:1}
.chart .axis{stroke:var(--muted);stroke-width:1}
.chart .ref{stroke:var(--ink-2);stroke-width:1.5}
.chart .xhair{stroke:var(--muted);stroke-width:1}
.chart .tick{fill:var(--muted);font:12px "IBM Plex Mono",ui-monospace,monospace}
.chart .lbl{fill:var(--ink-2);font:13px "IBM Plex Sans",system-ui,sans-serif}
.chart .neutral-bar{fill:var(--neutral-mark)}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--ink-2);margin-bottom:8px}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px}
.tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--rule);border-radius:8px;
padding:8px 10px;font-size:12.5px;box-shadow:0 4px 16px rgba(0,0,0,.12);z-index:5;min-width:190px}
.tip div{display:flex;justify-content:space-between;gap:14px}
.tip .d{color:var(--muted);font-family:"IBM Plex Mono",monospace;margin-bottom:4px}
.caption{color:var(--muted);font-size:13px;max-width:72ch}
.tbl{overflow-x:auto;background:var(--surface);border:1px solid var(--rule);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--rule);white-space:nowrap}
th{font-weight:500;color:var(--muted);font-size:12.5px}
td.n,th.n{text-align:right}
tr:last-child td{border-bottom:0}
tr.hl td{font-weight:600}
.neg{color:var(--critical)}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;font-size:12px;color:var(--ink-2)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:10px;padding:16px;display:grid;gap:6px}
.card b{font-family:"IBM Plex Mono",monospace;font-size:20px;font-weight:500}
.card p{color:var(--ink-2);font-size:14px}
ol.rules{margin:0;padding-left:1.3em;display:grid;gap:8px;max-width:72ch}
a{color:var(--series-1)}
:focus-visible{outline:2px solid var(--series-1);outline-offset:2px}
"""

JS = """
(function(){
const D=JSON.parse(document.getElementById('eqdata').textContent);
const tip=document.createElement('div');tip.className='tip';tip.hidden=true;document.body.appendChild(tip);
function attach(id,key,fmt){
  const svg=document.getElementById(id);if(!svg)return;
  const hit=svg.querySelector('.hit'),xh=svg.querySelector('.xhair');
  const x0=+hit.getAttribute('x'),w=+hit.getAttribute('width'),n=D.dates.length;
  function move(ev){
    const r=svg.getBoundingClientRect(),vx=(ev.clientX-r.left)*(900/r.width);
    const i=Math.max(0,Math.min(n-1,Math.round((vx-x0)/w*(n-1))));
    const px=x0+w*i/(n-1);xh.setAttribute('x1',px);xh.setAttribute('x2',px);xh.setAttribute('visibility','visible');
    let h='<div class="d">'+D.dates[i]+'</div>';
    D.series.forEach(s=>{h+='<div><span><i style="display:inline-block;width:10px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle;background:var('+s.var+')"></i>'+s.name+'</span><b class="mono">'+fmt(s[key][i])+'</b></div>'});
    tip.innerHTML=h;tip.hidden=false;
    const tx=Math.min(ev.clientX+14,window.innerWidth-tip.offsetWidth-8);tip.style.left=tx+'px';tip.style.top=(ev.clientY+14)+'px';
  }
  function out(){tip.hidden=true;xh.setAttribute('visibility','hidden')}
  hit.addEventListener('pointermove',move);hit.addEventListener('pointerleave',out);
}
attach('eq','eq',v=>'×'+v.toFixed(2));
attach('dd','dd',v=>(v*100).toFixed(0).replace('-','−')+'%');
})();
"""


def html_page(res: dict, extras: dict) -> str:
    S = res["settings"]
    oos = extras["oos"]
    cand_name = next(k for k in oos if k.startswith("CANDIDATA"))
    wf_name = "WALK-FORWARD (elige la mejor cada año)"
    show = [("Regla candidata", cand_name, "--series-1"), ("Comprar y aguantar", "BUY & HOLD", "--series-2"),
            ("Optimizador anual", wf_name, "--series-3")]
    weekly = {}
    for lab, k, var in show:
        r = oos[k]["ret"]
        eq = (1 + r).cumprod()
        dd = eq / eq.cummax() - 1
        weekly[lab] = (eq.resample("W").last(), dd.resample("W").min())
    dates = weekly[show[0][0]][0].index
    eq_series = [(lab, weekly[lab][0].values, var) for lab, _, var in show]
    dd_series = [(lab, weekly[lab][1].values, var) for lab, _, var in show]
    eq_ticks = [0.25, 0.5, 1, 2, 4, 8, 16]
    eq_svg = svg_lines(dates, eq_series, log=True, yticks=eq_ticks, yfmt=lambda v: f"×{v:g}", chart_id="eq")
    dd_svg = svg_lines(dates, dd_series, height=210, yticks=[0, -0.2, -0.4, -0.6, -0.8],
                       yfmt=lambda v: pct(v), chart_id="dd", zero_line=True)
    eqdata = {"dates": [d.strftime("%Y-%m-%d") for d in dates],
              "series": [{"name": lab, "var": var, "eq": [round(float(x), 4) for x in weekly[lab][0].values],
                          "dd": [round(float(x), 4) for x in weekly[lab][1].values]} for lab, _, var in show]}
    legend = "".join(f'<span><i style="background:var({v})"></i>{lab}</span>' for lab, _, v in show)

    pl = res["placebo"]["candidate"]
    hist_svg = svg_hist(extras["placebo_sims"], pl["actual_sharpe"], f"Regla real: {pl['actual_sharpe']:.2f}")
    mc = res["monte_carlo_12m"]
    rng_svg = svg_ranges([
        ("Regla candidata", mc["candidate"]["final_p5"], mc["candidate"]["final_p25"], mc["candidate"]["final_median"],
         mc["candidate"]["final_p75"], mc["candidate"]["final_p95"], "--series-1"),
        ("Comprar y aguantar", mc["buy_hold"]["final_p5"], mc["buy_hold"]["final_p25"], mc["buy_hold"]["final_median"],
         mc["buy_hold"]["final_p75"], mc["buy_hold"]["final_p95"], "--series-2")], mc["candidate"]["capital"])

    cand, bh, wf = res["oos"][cand_name], res["oos"]["BUY & HOLD"], res["oos"][wf_name]
    bs = res["bootstrap_vs_buyhold"]["candidate"]
    stats = [
        (pct(cand["cagr"]), "rendimiento anual de la regla", f"vs {pct(bh['cagr'])} comprando y aguantando"),
        (pct(cand["max_dd"]), "peor caída desde un máximo", f"vs {pct(bh['max_dd'])} comprando y aguantando"),
        (pct(mc["candidate"]["p_loss"]), "probabilidad de perder en 12 meses", f"vs {pct(mc['buy_hold']['p_loss'])} comprando y aguantando"),
        (pct(bs["p_return_better"]), "probabilidad de ganar más que BTC", "bootstrap por bloques, 2018–hoy"),
    ]
    stats_html = "".join(f'<div class="stat"><b>{html.escape(a)}</b><span>{html.escape(b)}</span>'
                         f'<span class="vs">{html.escape(c)}</span></div>' for a, b, c in stats)
    verdict_html = "".join(f"<li>{html.escape(x)}</li>" for x in verdict(res))

    rows = []
    for k, p in _oos_rows(res):
        hl = ' class="hl"' if k.startswith("CANDIDATA") or k == "BUY & HOLD" else ""
        rows.append(f"<tr{hl}><td>{html.escape(nice(k))}</td><td class='n'>{pct(p['cagr'],1)}</td>"
                    f"<td class='n'>{p['sharpe']:.2f}</td><td class='n'>{pct(p['max_dd'])}</td>"
                    f"<td class='n'>{pct(p['exposure'])}</td><td class='n'>{p['trades_per_year']:.0f}</td></tr>")
    oos_table = ("<div class='tbl'><table><thead><tr><th>Estrategia</th><th class='n'>Rend. anual</th><th class='n'>Sharpe</th>"
                 "<th class='n'>Caída máx.</th><th class='n'>Tiempo dentro</th><th class='n'>Operaciones/año</th></tr></thead><tbody>"
                 + "".join(rows) + "</tbody></table></div>")

    yrows = []
    for y, v in res["yearly"].items():
        cells = "".join(f"<td class='n{' neg' if (v[c] or 0) < 0 else ''}'>{pct(v[c],0,True)}</td>"
                        for c in ("buy_hold", "candidate", "walk_forward"))
        yrows.append(f"<tr><td class='mono'>{y}</td>{cells}</tr>")
    year_table = ("<div class='tbl'><table><thead><tr><th>Año</th><th class='n'>Comprar y aguantar</th>"
                  "<th class='n'>Candidata</th><th class='n'>Optimizador</th></tr></thead><tbody>" + "".join(yrows) +
                  "</tbody></table></div>")

    crows = "".join(f"<tr><td class='mono'>{c}</td><td class='n'>{pct(v['candidate_cagr'],1)}</td>"
                    f"<td class='n'>{pct(v['walk_forward_cagr'],1)}</td><td class='n'>{pct(v['buy_hold_cagr'],1)}</td></tr>"
                    for c, v in res["cost_sensitivity"].items())
    cost_table = ("<div class='tbl'><table><thead><tr><th>Costo por lado</th><th class='n'>Candidata</th>"
                  "<th class='n'>Optimizador</th><th class='n'>Comprar y aguantar</th></tr></thead><tbody>" + crows +
                  "</tbody></table></div>")

    ib, zd, eth, rc, ml = (res["in_sample_best"], res["zero_drift"], res["eth_check"], res["recent"], res["ml"])
    k = res["kelly_candidate_oos"]
    cards = [
        (f"p = {pl['p_value']:.3f}", "Placebo",
         f"De 1,000 versiones con las mismas posiciones desfasadas en el tiempo, {pct(pl['p_value'],1)} "
         "igualaron o superaron a la regla real. "
         + ("El momento de entrar y salir sí aporta." if pl["p_value"] < 0.05
            else "No se distingue del azar.")),
        (f"{pct(zd['candidate']['cagr'],1)} anual", "BTC sin tendencia",
         "Si cada año BTC terminara donde empezó (misma volatilidad, sin subida neta), la regla rendiría "
         f"{pct(zd['candidate']['cagr'],1)} anual y comprar y aguantar {pct(zd['buy_hold']['cagr'],1)}. "
         + ("Parte de la ganancia viene del timing, no solo de que BTC subió." if zd["candidate"]["cagr"] > 0.02
            else "Casi toda la ganancia venía de que BTC subió.")),
        (f"{pct(eth['candidate']['cagr'],1)} vs {pct(eth['buy_hold']['cagr'],1)}", "ETH sin re-optimizar",
         f"Misma regla en otro activo: caída máxima {pct(eth['candidate']['max_dd'])} contra {pct(eth['buy_hold']['max_dd'])}."),
        (f"{ib['dsr_active_vs_buyhold']['dsr']:.3f}", "Sharpe deflactado vs. BTC",
         f"Tras probar {ib['dsr_vs_zero']['n_trials']} variantes, la mejor no demuestra ganar más que solo tener BTC "
         "(se necesitaría ≥ 0.95)."),
        (f"AUC {ml['logistic']['auc']:.2f}", "Machine learning",
         f"Predecir si BTC sube en 5 días: logística {ml['logistic']['auc']:.3f}, boosting {ml['gbm']['auc']:.3f}. "
         "0.50 es una moneda al aire."),
        (f"{pct(rc['candidate']['cagr'],1)} vs {pct(rc['buy_hold']['cagr'],1)}", f"Desde {rc['since'][:4]}",
         f"Rendimiento anual de la regla contra comprar y aguantar en el mercado más reciente; caída máxima "
         f"{pct(rc['candidate']['max_dd'])} contra {pct(rc['buy_hold']['max_dd'])}."),
    ]
    cards_html = "".join(f"<div class='card'><span class='eyebrow'>{html.escape(t)}</span><b>{html.escape(v)}</b>"
                         f"<p>{html.escape(d)}</p></div>" for v, t, d in cards)

    today = res["today"]
    return f"""<title>Laboratorio BTC</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <span class="eyebrow">BTC/USD · diario · datos {res['data']['btc_first'][:4]} a {res['data']['btc_last']} · costo {S['cost_per_side']:.2%} por lado</span>
  <h1>¿Un bot de tendencia le gana a solo tener Bitcoin?</h1>
  <p>Se probaron {ib['dsr_vs_zero']['n_trials']} variantes de 8 familias de estrategias, se eligió una regla antes de ver los resultados
  y todo se midió fuera de muestra desde {S['oos_start_year']}, con comisiones y deslizamiento incluidos.</p>
</header>

<section class="verdict" aria-labelledby="v">
  <h2 id="v">Veredicto</h2>
  <div class="stats">{stats_html}</div>
  <ul>{verdict_html}</ul>
</section>

<section>
  <h2>Crecimiento de $1 desde {S['oos_start_year']}</h2>
  <div class="panel"><div class="legend">{legend}</div>{eq_svg}</div>
  <div class="panel"><div class="legend">{legend}</div>{dd_svg}</div>
  <p class="caption">Escala logarítmica arriba; abajo, qué tan lejos estaba cada una de su máximo previo. Pasa el cursor para ver valores semanales.
  El optimizador cambia de estrategia cada enero según cuál tuvo mejor Sharpe en los años anteriores.</p>
</section>

<section>
  <h2>Todas las familias, fuera de muestra</h2>
  <p class="caption">Cada familia se optimizó con walk-forward: sus parámetros se eligen solo con datos del pasado.</p>
  {oos_table}
</section>

<section>
  <h2>¿Ventaja o suerte?</h2>
  <div class="panel">{hist_svg}</div>
  <p class="caption">Sharpe de 1,000 versiones placebo de la regla: mismas posiciones y mismo número de operaciones, pero desfasadas al azar contra los precios.</p>
  <div class="grid2">{cards_html}</div>
</section>

<section>
  <h2>Qué pasa si las comisiones suben</h2>
  <p class="caption">La regla opera seguido, así que el costo por operación decide si la ventaja sobrevive. Por API en Bitso la comisión taker de BTC/MXN es de 0.098% en el nivel más bajo de volumen; compras por otras vías pueden incluir un diferencial mayor, así que mide el costo real de tus primeras operaciones.</p>
  {cost_table}
</section>

<section>
  <h2>Año por año</h2>
  {year_table}
</section>

<section>
  <h2>Los próximos 12 meses con {money(mc['candidate']['capital'])} MXN</h2>
  <div class="panel">{rng_svg}</div>
  <p class="caption">Monte Carlo con 5,000 trayectorias armadas con bloques de 30 días del periodo fuera de muestra. Caja: la mitad central de los casos; línea: del peor 5% al mejor 5%; punto: mediana; línea vertical: tu capital inicial.
  Probabilidad de una caída mayor a 30% en el camino: {pct(mc['candidate']['p_dd_30'])} con la regla, {pct(mc['buy_hold']['p_dd_30'])} solo con BTC.
  Supone que el futuro se parece a 2018–2026, lo cual es optimista.</p>
</section>

<section class="prose">
  <h2>Cómo usar esto sin quemarte</h2>
  <ol class="rules">
    <li>Primero 4 a 8 semanas en modo simulado. El diario del bot debe coincidir con lo que dice el backtest.</li>
    <li>Luego solo capital que aceptes perder completo. Con esta regla, una caída de 30% en un año es normal.</li>
    <li>Opera por API o Bitso Alpha. Con costos arriba de 0.5% por lado la ventaja desaparece.</li>
    <li>Sin apalancamiento. El Kelly estimado va de {k['kelly_low']:.2f} a {k['kelly_high']:.2f}: no sabemos lo suficiente para apostar más de lo que tienes.</li>
    <li>No cambies la regla porque tuvo un mal mes. Cambiar cada año a lo que venía funcionando rindió {pct(wf['cagr'])} anual contra {pct(cand['cagr'])} de la regla fija.</li>
    <li>La llave de API sin permiso de retiro, y guarda cada operación para el SAT.</li>
  </ol>
  <p class="caption">Señal al cierre del {today['date']} (BTC en {money(today['close'])} USD): exposición objetivo {pct(today['candidate_target'])}. Cambia a diario; el bot la recalcula.</p>
  <p class="caption">Supuestos: cierres diarios de CoinMetrics y Kraken; se decide al cierre y se ejecuta al siguiente precio; sin cortos ni apalancamiento; el efectivo no genera intereses; no incluye impuestos ni tipo de cambio. No es asesoría financiera.</p>
</section>
</div>
<script type="application/json" id="eqdata">{json.dumps(eqdata)}</script>
<script>{JS}</script>
"""
