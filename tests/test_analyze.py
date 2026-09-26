"""El conteo de operaciones ganadoras/perdedoras tiene que cuadrar a mano."""
import pandas as pd
import pytest

from lab.analyze import fifo, summarize


def T(rows):
    return pd.DataFrame(rows, columns=["sleeve", "asset", "side", "qty", "price", "fee", "candle", "status"])


def test_fifo_realized_and_unrealized():
    tr = T([
        ["crypto", "ETH", "buy", 1.0, 100.0, 0.1, "2026-01-01", "filled"],
        ["crypto", "ETH", "buy", 1.0, 200.0, 0.2, "2026-01-02", "filled"],
        ["crypto", "ETH", "sell", 1.5, 300.0, 0.45, "2026-01-03", "filled"],  # cierra lote 1 completo y medio lote 2
        ["crypto", "SOL", "buy", 2.0, 50.0, 0.1, "2026-01-01", "filled"],
        ["crypto", "SOL", "sell", 2.0, 40.0, 0.08, "2026-01-04", "filled"],   # pérdida
        ["stocks", "SPY", "buy", 1.0, 500.0, 0.0, "2026-01-01", "filled"],
        ["stocks", "SPY", "buy", 1.0, 510.0, 0.0, "2026-01-02", "failed"],    # fallida: no cuenta
    ])
    res = fifo(tr, {"crypto": {"ETH": 250.0}, "stocks": {"SPY": 520.0}})
    s = summarize(res)
    assert s["n_trades"] == 6 and s["n_sells"] == 2
    assert s["closed_lots"] == 3 and s["wins"] == 2 and s["losses"] == 1
    eth1 = 1.0 * (300 - 0.3) - 1.0 * (100 + 0.1)
    eth2 = 0.5 * (300 - 0.3) - 0.5 * (200 + 0.2)
    sol = 2.0 * (40 - 0.04) - 2.0 * (50 + 0.05)
    assert s["realized_pnl"] == pytest.approx(round(eth1 + eth2 + sol, 2))
    opens = {p["asset"]: p for p in res["open"]}
    assert opens["ETH"]["qty"] == pytest.approx(0.5)
    assert opens["ETH"]["pnl"] == pytest.approx(0.5 * 250 - 0.5 * 200.2)
    assert opens["SPY"]["pnl"] == pytest.approx(20.0)
    assert s["open_winning"] == 2 and s["open_losing"] == 0


def test_no_trades():
    s = summarize(fifo(T([]), {}))
    assert s["n_trades"] == 0 and s["win_rate"] is None and s["total_pnl"] == 0


def test_yahoo_fills_closed_session_bar(monkeypatch):
    """Si la sesión ya cerró pero la barra del día viene vacía, se usa el cierre oficial."""
    from lab import data

    class R:
        status_code = 200

        def __init__(self, reg_time):
            self.reg_time = reg_time

        def raise_for_status(self):
            pass

        def json(self):
            return {"chart": {"result": [{
                "timestamp": [1790170200, 1790256600],
                "meta": {"regularMarketPrice": 771.35, "regularMarketTime": self.reg_time,
                         "currentTradingPeriod": {"regular": {"start": 1790256600, "end": 1790280000}}},
                "indicators": {"quote": [{"close": [767.18, None]}], "adjclose": [{"adjclose": [767.18, None]}]}}]}}

    monkeypatch.setattr("requests.get", lambda *a, **k: R(1790280000))
    s = data.yahoo_daily("SPY", start="2026-09-20")
    assert len(s) == 2 and s.iloc[-1] == pytest.approx(771.35)
    monkeypatch.setattr("requests.get", lambda *a, **k: R(1790270000))  # sesión aún abierta
    assert len(data.yahoo_daily("SPY", start="2026-09-20")) == 1
