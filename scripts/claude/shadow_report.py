#!/usr/bin/env python3
"""Lee la sombra de exchanges (H7c) de un snapshot del panel y la imprime para la revisión.

Uso: python3 scripts/claude/shadow_report.py <snapshot.json>
La regla de decisión es la preregistrada (`reports/h7c_sombra_exchanges_preregistro.md`) y vive en
`lab.exchange_shadow.summarize`; este script solo la muestra, más el resumen del último panel de spreads.
"""
from __future__ import annotations

import json
import statistics
import sys


def main(path: str) -> int:
    snap = json.load(open(path, encoding="utf-8"))
    block = (snap.get("pilot") or {}).get("exchange-shadow") or {}
    if block.get("http") != 200 or not isinstance(block.get("data"), dict) or "summary" not in block["data"]:
        print("Sombra de exchanges: sin dato en este snapshot (endpoint no disponible).")
        return 1
    data = block["data"]
    s = data["summary"]
    w = s["window"]
    print(f"Sombra de exchanges H7c — desde {w['from_utc'] or 'sin órdenes aún'}; regla al {w['end_utc']} UTC "
          f"(≥{w['min_orders']} órdenes, umbral {w['threshold_bps']:.0f} pb). Órdenes con sombra: "
          f"{s['orders_recorded']}; paneles: {s['panels_recorded']}.")
    for venue, v in s["venues"].items():
        avail = "—" if v["availability"] is None else f"{v['availability']:.0%}"
        print(f"\n{venue}: disponibilidad {avail} de {v['quotes']} cotizaciones · veredicto: {v['verdict']}")
        for fee, f in v["by_fee"].items():
            if f["mean_diff_bps"] is None:
                print(f"  {fee}: sin órdenes emparejadas aún")
                continue
            ci = f["ci90_bps"]
            ci_txt = f"IC90 [{ci[0]:.0f}, {ci[1]:.0f}] pb" if ci else "IC90 sin dato (menos de 2 días)"
            print(f"  {fee}: {f['n_orders']} órdenes en {f['n_days']} días, US${f['value_usd']:,.2f} operados; "
                  f"Bitso cuesta {f['mean_diff_bps']:.1f} pb más por orden ({ci_txt}); "
                  f"ahorro US${f['saving_usd']:.2f} (≈US${f['saving_usd_per_year']:.0f} al año a este ritmo)")
    panels = data.get("panels") or []
    if panels:
        last = panels[-1]
        print(f"\nÚltimo panel ({last.get('trigger')}, {last.get('observed_utc')} UTC, US${last.get('usd'):.0f}):")
        by = {}
        for r in last.get("rows", []):
            by.setdefault(r.get("venue"), []).append(r)
        for venue, rows in by.items():
            ok = [r for r in rows if r.get("status") == "ok"]
            errs = sorted({r.get("error") for r in rows if r.get("status") != "ok"})
            if ok:
                cost = statistics.median(r["impact_bps"] for r in ok)
                worst = max(ok, key=lambda r: r["impact_bps"])
                print(f"  {venue}: {len({r['asset'] for r in ok})} monedas con libro; costo de recorrer US$100 "
                      f"(sin comisión) mediana {cost:.1f} pb, peor {worst['asset']} {worst['impact_bps']:.1f} pb"
                      + (f"; errores: {', '.join(e for e in errs if e)}" if errs else ""))
            else:
                print(f"  {venue}: sin libro ({', '.join(e for e in errs if e) or 'sin detalle'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else (print(__doc__) or 2))
