"""La revisión de Claude cuadra resultado = mercado + estrategia − costos y detecta alertas."""
import importlib.util
import pathlib

import pytest

SPEC = importlib.util.spec_from_file_location(
    "claude_review", pathlib.Path(__file__).resolve().parents[1] / "scripts/claude/review.py")
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def _snapshot(drawdown=-0.05, ready=True, mode="paper", flow_day=None):
    rows, trades = [], []
    eq, px = 500.0, 100.0
    for i in range(40):
        day = f"2026-10-{i + 1:02d}" if i < 31 else f"2026-11-{i - 30:02d}"
        move = 0.01 if i % 2 else -0.008
        px *= 1 + move
        flow = 100.0 if day == flow_day else 0.0
        eq = eq * (1 + 0.5 * move) + flow
        rows.append({"date": day, "sleeve": "crypto", "mode": "paper", "equity": eq,
                     "benchmark_price": px, "drawdown": drawdown, "flow": flow or ""})
        trades.append({"candle": day, "sleeve": "crypto", "asset": "BTC", "side": "buy", "status": "filled",
                       "value": 50.0, "fee": 0.15, "cost_bps": 40.0, "maker_value_usd": 10.0})
    ok = {"http": 200}
    return {"taken_at_utc": "20261109T120000Z", "pilot": {
        "status": ok | {"data": {"ready": ready, "mode": mode, "reason": "x",
                                 "storage": {"pending_orders": 0, "unknown_orders": 0},
                                 "runtime": {"last_success_utc": "2026-11-09 00:10"}}},
        "equity": ok | {"data": {"items": rows}},
        "trades": ok | {"data": {"items": trades}},
        "performance": ok | {"data": {"fx": {"rate": 18.0}, "current": {}}}}}


def test_weekly_identity_and_costs():
    w = review.weekly(_snapshot(flow_day="2026-11-05"), None, 7)
    s = w["sleeves"]["crypto"]
    assert s["flows"] == pytest.approx(100.0)
    assert s["costs_usd"] == pytest.approx(7 * 0.20)  # 40 pb de US$50 por día
    assert s["pnl_usd"] == pytest.approx(s["market_usd"] + s["strategy_usd"] - s["costs_usd"])
    assert s["beta"] == pytest.approx(0.5, abs=0.05)
    assert s["maker_share"] == pytest.approx(0.2)


def test_alerts():
    assert review.alerts(_snapshot()) == []
    found = " ".join(review.alerts(_snapshot(drawdown=-0.41, ready=False, mode="live")))
    assert "MODO" in found and "no listo" in found and "Kill switch crypto" in found
    assert review.alerts({"pilot": {}})[0].startswith("No se pudo leer")
