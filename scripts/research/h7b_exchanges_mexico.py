"""H7b: el bloque cripto vigente con la comisión de cada exchange usable desde México (simulación, no en vivo).

    PYTHONPATH=src python scripts/research/h7b_exchanges_mexico.py

Escenarios fijados antes de correr (1-nov-2026). Costo por lado = comisión del nivel más bajo + medio spread
supuesto (1 pb en Bitso BTC/ETH; 2 pb en exchanges globales, como H7 del 25-oct). Entrada y salida en pesos se cobran
una vez sobre el capital. Escribe reports/h7b_exchanges_mexico.json. No cambia config.yaml ni el bot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprint02_costo_ejecucion import BASE, CAPITAL, END, KILL, START, summary  # noqa: E402

from lab.data import load_crypto_panel  # noqa: E402
from lab.portfolio import PortfolioParams, listed_universe, simulate_funded_portfolio, target_weights  # noqa: E402
from lab.research_multi import BITSO_TRADABLE  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MIN_ORDER, BAND, STRESS = 25.0, 0.02, 1.5
# id: (etiqueta, costo por lado, entrada en pesos, salida a pesos)
SCENARIOS = {
    "bitso-usd-taker": ("Bitso USD, taker (modelo vigente)", 0.0037, 0.0078, 0.0078),
    "bitso-usd-medido": ("Bitso USD, costo medido del piloto (49 pb)", 0.0049, 0.0078, 0.0078),
    "bitso-usd-maker": ("Bitso USD, 100% maker", 0.0031, 0.0078, 0.0078),
    "bitso-mxn-taker": ("Bitso en pesos, taker", 0.0080, 0.0, 0.0),
    "kraken-taker": ("Kraken Pro nivel 1, taker", 0.0082, 0.01, 0.01),
    "kraken-maker": ("Kraken Pro nivel 1, maker", 0.0042, 0.01, 0.01),
    "global-010": ("Global a 0.10% (Binance, OKX, Bybit, Bitget)", 0.0012, 0.01, 0.01),
    "binance-bnb": ("Binance con descuento BNB (0.075%)", 0.00095, 0.01, 0.01),
}


def main():
    P, _ = load_crypto_panel(False)
    P = P[[a for a in BITSO_TRADABLE if a in P.columns]]
    p = PortfolioParams.from_dict(BASE)
    W = target_weights(P, listed_universe(P), p)
    res = {"experiment_id": "h7b-exchanges-mexico", "window": [START, END], "min_order_value": MIN_ORDER,
           "capital": CAPITAL, "scenarios": {}}
    for sid, (label, cost, entry, exit_) in SCENARIOS.items():
        bt = simulate_funded_portfolio(P, W, p, cost, BAND, kill_dd=KILL, initial_capital=CAPITAL,
                                       min_order_value=MIN_ORDER, start=START)
        bts = simulate_funded_portfolio(P, W, p, cost * STRESS, BAND, kill_dd=KILL, initial_capital=CAPITAL,
                                        min_order_value=MIN_ORDER, start=START)
        s, st = summary(bt, cost), summary(bts, cost * STRESS)
        years = len(bt) / 365
        final = CAPITAL * s["final_multiple"]
        final_mxn_path = CAPITAL * (1 - entry) * s["final_multiple"] * (1 - exit_)
        res["scenarios"][sid] = {
            "label": label, "cost_per_side": cost, "entry": entry, "exit": exit_, "base": s, "stress": st,
            "fees_usd": s.get("fees_usd_total"), "final_usd": final, "final_usd_after_peso_in_out": final_mxn_path,
            "cagr_after_peso_in_out": (final_mxn_path / CAPITAL) ** (1 / years) - 1,
            "kill_hit": bool(s["max_dd"] <= -KILL)}
    (ROOT / "reports" / "h7b_exchanges_mexico.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    for sid, r in res["scenarios"].items():
        s = r["base"]
        print(f"{sid:18s} {r['cost_per_side']*100:.3f}% CAGR {s['cagr']:+.1%} Sharpe {s['sharpe']:.2f} DD {s['max_dd']:.1%} "
              f"costo/año {s['cost_per_year']*100:.1f}% comisiones ${r['fees_usd'] or 0:,.0f} final ${r['final_usd']:,.0f} "
              f"con pesos ${r['final_usd_after_peso_in_out']:,.0f} ({r['cagr_after_peso_in_out']:+.1%}) estrés {r['stress']['cagr']:+.1%} "
              f"kill {r['kill_hit']}")
        print("   años", {y: round(x * 100, 1) for y, x in s["years"].items()})


if __name__ == "__main__":
    main()
