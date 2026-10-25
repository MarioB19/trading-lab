import json
from pathlib import Path

from lab.attribution import attribute, windows

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/attribution_20261025.json').read_text())


def cents(x):
    return round(x, 2)


def test_parity_with_weekly_review_of_25_oct():
    """Misma cifra que la revisión semanal del 25-oct (cierres 17→24-oct)."""
    w = attribute(FIXTURE['equity'], FIXTURE['trades'], days=7, fx=FIXTURE['fx_usd_mxn'])
    assert (w['start'], w['end']) == ('2026-10-17', '2026-10-24')
    total = w['total']
    assert (cents(total['market']), cents(total['strategy']), cents(total['costs'])) == (-4.90, -2.84, 0.08)
    assert cents(total['pnl']) == -7.81
    crypto, stocks = w['sleeves']['crypto'], w['sleeves']['stocks']
    assert (cents(crypto['market_usd']), cents(crypto['strategy_usd']), cents(crypto['costs_usd'])) == (-3.74, -4.13, 0.08)
    assert (cents(stocks['market_usd']), cents(stocks['strategy_usd']), cents(stocks['costs_usd'])) == (-1.16, 1.29, 0.0)


def test_parity_28_days_with_review():
    w = attribute(FIXTURE['equity'], FIXTURE['trades'], days=28)
    crypto, stocks = w['sleeves']['crypto'], w['sleeves']['stocks']
    assert (cents(crypto['market_usd']), cents(crypto['strategy_usd']), cents(crypto['costs_usd'])) == (-23.54, -42.11, 7.12)
    assert (cents(stocks['market_usd']), cents(stocks['strategy_usd']), cents(stocks['costs_usd'])) == (-4.84, 1.45, 0.10)


def test_identity_and_windows():
    w = windows(FIXTURE['equity'], FIXTURE['trades'])
    for key in ('week', 'days_28', 'since_start'):
        t = w[key]['total']
        assert abs(t['pnl'] - (t['market'] + t['strategy'] + t['unattributed'] - t['costs'])) < 1e-9
    assert w['since_start']['start'] == '2026-09-24'


def test_flows_are_not_returns_and_missing_beta_is_unattributed():
    rows = [{'sleeve': 'crypto', 'date': f'2026-10-{d:02d}', 'equity': 100 + d, 'benchmark_price': 100 + d}
            for d in range(1, 9)]
    rows[-1]['flow'] = 50
    rows[-1]['equity'] += 50
    w = attribute(rows, [], days=3)
    s = w['sleeves']['crypto']
    assert cents(s['pnl_usd']) == 3.0 and s['flows'] == 50
    assert s['market_usd'] is None and w['total']['unattributed'] == s['pnl_usd']  # < 10 cierres: sin beta


def test_identity_flows_costs_beta_and_maker_share():
    """Prueba de la fórmula que vivía en scripts/claude/review.py (trasladada sin cambios a lab)."""
    import pytest
    rows, trades = [], []
    eq, px = 500.0, 100.0
    for i in range(40):
        day = f"2026-10-{i + 1:02d}" if i < 31 else f"2026-11-{i - 30:02d}"
        move = 0.01 if i % 2 else -0.008
        px *= 1 + move
        flow = 100.0 if day == "2026-11-05" else 0.0
        eq = eq * (1 + 0.5 * move) + flow
        rows.append({"date": day, "sleeve": "crypto", "mode": "paper", "equity": eq,
                     "benchmark_price": px, "drawdown": -0.05, "flow": flow or ""})
        trades.append({"candle": day, "sleeve": "crypto", "asset": "BTC", "side": "buy", "status": "filled",
                       "value": 50.0, "fee": 0.15, "cost_bps": 40.0, "maker_value_usd": 10.0})
    s = attribute(rows, trades, days=7)["sleeves"]["crypto"]
    assert s["flows"] == pytest.approx(100.0)
    assert s["costs_usd"] == pytest.approx(7 * 0.20)  # 40 pb de US$50 por día
    assert s["pnl_usd"] == pytest.approx(s["market_usd"] + s["strategy_usd"] - s["costs_usd"])
    assert s["beta"] == pytest.approx(0.5, abs=0.05)
    assert s["maker_share"] == pytest.approx(0.2)
