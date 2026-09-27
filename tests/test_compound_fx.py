"""Interés compuesto en cuentas externas (Alpaca / real) y tipo de cambio USD/MXN."""
from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest

from lab import bot
from lab.brokers import SimBroker


class FakeAlpaca(SimBroker):
    """Cuenta externa: trae mucho más dinero del que el bloque tiene asignado."""


def _stocks_sc(**over):
    sc = copy.deepcopy(bot.DEFAULT_CONFIG["sleeves"]["stocks"])
    sc["universe"] = ["SPY", "IEF"]
    sc.update(over)
    return sc


def _prices(n=300, last_mult=1.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    P = pd.DataFrame({"SPY": np.linspace(100, 120, n), "IEF": np.linspace(90, 95, n)}, index=idx)
    P.iloc[-1] = P.iloc[-2] * last_mult  # el último día todo se mueve igual
    return P


def _two_days(monkeypatch, last_mult, account_cash=100_000.0, **over):
    monkeypatch.setattr(bot, "SimBroker", type("Otro", (), {}))  # que cuente como cuenta externa
    sc = _stocks_sc(**over)
    P = _prices(last_mult=last_mult)
    st: dict = {}
    br = FakeAlpaca({"cash": account_cash, "positions": {}}, 0.0, 0.0, 1.0)
    eq = pd.Series(dtype=float)
    r1 = bot.run_sleeve("stocks", sc, P.iloc[:-1], br, st, P.index[-2] + pd.Timedelta(days=1, hours=2), "paper", eq, 10.0)
    eq.loc[P.index[-2]] = r1["equity_row"]["equity"]
    r2 = bot.run_sleeve("stocks", sc, P, br, st, P.index[-1] + pd.Timedelta(days=1, hours=2), "paper", eq, 10.0)
    return sc, st, br, r1, r2


def test_external_account_sees_its_own_losses(monkeypatch):
    """Con $100k en la cuenta, una caída de 40% del bloque debe verse y activar el kill switch."""
    sc, st, br, r1, r2 = _two_days(monkeypatch, last_mult=0.6)
    assert r1["equity_row"]["equity"] == pytest.approx(700, rel=0.01)
    assert st["kill_switch"]  # antes se valuaba en min($100k, $700) = $700 y nunca se activaba
    assert all(t["side"] == "sell" for t in r2["trades"])
    assert r2["equity_row"]["equity"] < 450


def test_compound_reinvests_gains(monkeypatch):
    sc, st, br, r1, r2 = _two_days(monkeypatch, last_mult=1.3)
    held = sum(q * float(_prices(last_mult=1.3).iloc[-1][a]) for a, q in br.positions().items())
    assert r2["equity_row"]["equity"] > 850
    assert held > 850  # la ganancia sigue invertida


def test_without_compound_gains_above_capital_stay_in_cash(monkeypatch):
    sc, st, br, r1, r2 = _two_days(monkeypatch, last_mult=1.3, compound=False)
    held = sum(q * float(_prices(last_mult=1.3).iloc[-1][a]) for a, q in br.positions().items())
    assert r2["equity_row"]["equity"] == pytest.approx(700, rel=0.01)
    assert held == pytest.approx(700 * 0.997, rel=0.02)  # vendió lo que pasaba del tope


def test_sleeve_never_spends_more_than_the_account_has(monkeypatch):
    sc, st, br, r1, r2 = _two_days(monkeypatch, last_mult=1.0, account_cash=200.0)
    spent = sum(t["value"] for t in r1["trades"] if t["side"] == "buy")
    assert spent <= 200 and br.cash() >= 0  # sin apalancamiento


# ------------------------------------------------------------ tipo de cambio
def test_equity_rows_record_usd_mxn(monkeypatch, tmp_path):
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    idx = pd.date_range(end=today - pd.Timedelta(days=1), periods=400, freq="D")
    rng = np.random.default_rng(1)
    P = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, (400, 3)), axis=0)), index=idx,
                     columns=["BTC", "ETH", "SOL"])
    monkeypatch.setattr(bot, "fetch_prices", lambda name, sc, now, notes: P)
    monkeypatch.setattr(bot, "usd_mxn_now", lambda: {"rate": 17.5, "source": "prueba", "time_utc": "x"})
    monkeypatch.setattr(bot, "usd_mxn_daily", lambda days=30: pd.Series({idx[-1]: 17.25}))
    conf = tmp_path / "c.yaml"
    st = tmp_path / "state"
    conf.write_text(
        "sleeves:\n  stocks: {enabled: false}\n  crypto:\n    paper_broker: sim\n    universe: [BTC, ETH, SOL]\n"
        f"paths: {{state: '{st}/state.json', trades: '{st}/trades.csv', equity: '{st}/equity.csv', "
        f"snapshot: '{st}/snapshot.json'}}\n")
    assert bot.main(["--config", str(conf)]) == 0
    eq = pd.read_csv(st / "equity.csv")
    assert eq["usd_mxn"].iloc[-1] == pytest.approx(17.25)  # cierre del día de la vela
    assert json.loads((st / "snapshot.json").read_text())["fx"]["rate"] == 17.5
