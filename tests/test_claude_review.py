"""La revisión de Claude toma la atribución de la API (una sola fórmula) y detecta alertas."""
import importlib.util
import json
import pathlib

from lab.attribution import windows

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("claude_review", ROOT / "scripts/claude/review.py")
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)
FIXTURE = json.loads((ROOT / "tests/fixtures/attribution_20261025.json").read_text())


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


def test_alerts():
    assert review.alerts(_snapshot()) == []
    found = " ".join(review.alerts(_snapshot(drawdown=-0.41, ready=False, mode="live")))
    assert "MODO" in found and "no listo" in found and "Kill switch crypto" in found
    assert review.alerts({"pilot": {}})[0].startswith("No se pudo leer")


def test_weekly_review_prints_the_api_attribution_without_recomputing_it():
    api = json.loads(json.dumps(windows(FIXTURE["equity"], FIXTURE["trades"], fx=FIXTURE["fx_usd_mxn"])))
    snap = {"pilot": {"attribution": {"http": 200, "data": api},
                      "performance": {"http": 200, "data": {"current": {"pnl_usd": -66.5}}}}}
    text = review.markdown(review.weekly(snap))
    assert "mercado -4.90 + estrategia -2.84 − costos 0.08" in text
    assert "| crypto | -7.94 |" in text and "28 días" in text
    assert not hasattr(review, "beta")  # una sola fórmula: la del servidor


def test_old_snapshot_without_attribution_is_rejected():
    assert "tl.py snapshot" in review.markdown(review.weekly({"pilot": {}}))
