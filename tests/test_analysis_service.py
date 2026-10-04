"""FIFO must follow the current durable ledger without repairing its evidence."""
from __future__ import annotations

import copy

import pandas as pd
import pytest

from lab.analyze import build_analysis, fifo, summarize
from lab.runtime import DATABASE_NAME
from lab.service import Reader
from lab.storage import SQLiteStore


def trade(side="buy", qty=2, price=100, fee=2, day="2026-01-01", **changes):
    return {"sleeve": "crypto", "asset": "ETH", "side": side, "qty": qty, "price": price,
            "fee": fee, "candle": day, "run_at_utc": day + " 01:00", "status": "filled",
            "mode": "paper", **changes}


def documents(cash=298, qty=2, price=110, day="2026-01-01", capital=500):
    state = {"sleeves": {"crypto": {"mode": "paper", "capital_base": capital,
                                    "ledger": {"cash": cash, "positions": {"ETH": qty}}}}}
    snapshot = {"mode": "paper", "analysis": {"n_trades": 777, "total_pnl": 99999},
                "sleeves": {"crypto": {"mode": "paper", "candle": day,
                                       "assets": [{"asset": "ETH", "price": price}]}}}
    return state, snapshot


def test_reader_refreshes_fifo_after_committed_fills_without_rewriting_snapshot(tmp_path):
    store = SQLiteStore(tmp_path / DATABASE_NAME)
    state, snapshot = documents()
    store.commit_run(state, [trade()], [], snapshot)
    reader = Reader(tmp_path)
    first = reader.status()
    assert first["analysis"]["valid"] is True
    assert first["analysis"]["summary"]["total_pnl"] == 18
    assert first["snapshot"]["analysis"]["n_trades"] == 1
    assert store.read_document("snapshot") == snapshot

    state, snapshot = documents(cash=417, qty=1, price=130, day="2026-01-02")
    store.commit_run(state, [trade("sell", 1, 120, 1, "2026-01-02")], [], snapshot)
    result = reader.status()["analysis"]
    assert result["source"] == "sqlite_ledger"
    assert result["price_source"] == "snapshot_close"
    assert result["prices_as_of"] == {"crypto": "2026-01-02"}
    assert result["valid"] is True
    assert result["summary"]["n_trades"] == 2
    assert result["summary"]["realized_pnl"] == 18
    assert result["summary"]["unrealized_pnl"] == 29
    assert result["summary"]["total_pnl"] == 47
    rec = result["reconciliation"]["by_sleeve"]["crypto"]
    assert rec["ledger_pnl"] == rec["fifo_pnl"] == 47
    assert rec["quantities"]["ETH"]["matches"] is True
    assert store.read_document("snapshot") == snapshot
    assert store.read_document("state") == state
    assert len(store.rows("trades")) == 2


def test_reader_keeps_same_sqlite_snapshot_when_writer_commits_during_read(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / DATABASE_NAME)
    state, snapshot = documents()
    store.commit_run(state, [trade()], [], snapshot)
    reader = Reader(tmp_path)
    connect = reader.connect
    committed = []

    def connect_with_writer():
        db = connect()

        def trace(sql):
            if "SELECT payload FROM trades" in sql and not committed:
                committed.append(True)
                state, snapshot = documents(cash=417, qty=1, price=130, day="2026-01-02")
                store.commit_run(state, [trade("sell", 1, 120, 1, "2026-01-02")], [], snapshot)

        db.set_trace_callback(trace)
        return db

    monkeypatch.setattr(reader, "connect", connect_with_writer)
    first = reader.status()["analysis"]
    second = reader.status()["analysis"]
    assert committed and first["valid"] and second["valid"]
    assert first["summary"]["n_trades"] == 1 and first["summary"]["total_pnl"] == 18
    assert second["summary"]["n_trades"] == 2 and second["summary"]["total_pnl"] == 47


@pytest.mark.parametrize("price", [None, 0, -100, float("nan"), float("inf"), "missing"])
def test_missing_price_never_becomes_zero_or_a_partial_total(price):
    state, snapshot = documents(price=price)
    result = build_analysis([trade()], snapshot, state)
    assert result["valid"] is False
    assert result["open"][0]["value"] is None
    assert result["summary"]["realized_pnl"] == 0
    assert result["summary"]["unrealized_pnl"] is None
    assert result["summary"]["total_pnl"] is None
    assert result["summary"]["unpriced_positions"] == 1
    assert any(issue["code"] == "missing_price" for issue in result["issues"])


def test_summarize_does_not_sum_only_positions_with_prices():
    result = fifo(pd.DataFrame([trade(), trade(asset="BTC")]), {"crypto": {"ETH": 110}})
    summary = summarize(result)
    assert summary["open_winning"] == 1
    assert summary["unpriced_positions"] == 1
    assert summary["unrealized_pnl"] is None
    assert summary["total_pnl"] is None
    assert summary["by_sleeve"]["crypto"]["unrealized_pnl"] is None


def test_fifo_sorts_actual_execution_times_stably_and_preserves_old_cost_basis():
    rows = [trade(qty=1, price=200, fee=0, day="2026-01-02"),
            trade("sell", 1, 300, 0, "2026-01-03"), trade(qty=1, fee=0)]
    result = fifo(pd.DataFrame(rows), {"crypto": {"ETH": 250}})
    assert result["closed"][0]["buy_price"] == 100
    assert result["open"][0]["cost"] == 200
    assert summarize(result)["total_pnl"] == 250
    # Candle can be older than execution: use the execution time when provided.
    rows[0]["candle"] = "2025-12-31"
    assert fifo(pd.DataFrame(rows), {"crypto": {"ETH": 250}})["closed"][0]["buy_price"] == 100


@pytest.mark.parametrize("rows", [
    [trade("sell", 1, 120, 1)],
    [trade("sell", 1, 120, 1), trade()],  # Same timestamp retains ledger order.
    [trade("sell", 1, 120, 1), trade(day="2026-01-02")],
    [trade(), trade("sell", 3, 120, 1, "2026-01-02")],
])
def test_unmatched_sale_is_explicit_and_has_no_fabricated_profit(rows):
    state, snapshot = documents()
    result = build_analysis(rows, snapshot, state)
    assert result["valid"] is False
    assert result["summary"]["realized_pnl"] is None
    assert result["summary"]["total_pnl"] is None
    assert "Venta sin compra" in result["issues"][0]["message"]


def test_mode_filter_excludes_live_fills_and_reports_missing_mode():
    state, snapshot = documents()
    result = build_analysis([trade(), trade("sell", 50, 120, 1, mode="live")], snapshot, state)
    assert result["valid"] and result["summary"]["n_trades"] == 1
    assert result["summary"]["total_pnl"] == 18
    assert not build_analysis([trade(), trade(mode=None)], snapshot, state)["valid"]


@pytest.mark.parametrize("day", [None, "unknown", "2025-12-31"])
def test_unverifiable_or_older_price_date_is_not_current_profit(day):
    state, snapshot = documents(day=day)
    result = build_analysis([trade()], snapshot, state)
    assert not result["valid"] and result["summary"]["total_pnl"] is None
    assert any(issue["code"] == "stale_price_date" for issue in result["issues"])


def test_inventory_and_cash_reconciliation_fail_visibly():
    state, snapshot = documents(qty=1.5)
    result = build_analysis([trade()], snapshot, state)
    assert not result["valid"]
    assert any(issue["code"] == "position_mismatch" for issue in result["issues"])
    assert result["summary"]["total_pnl"] is None
    state, snapshot = documents(cash=300)
    result = build_analysis([trade()], snapshot, state)
    assert not result["valid"]
    assert any(issue["code"] == "pnl_mismatch" for issue in result["issues"])


def test_net_contribution_is_not_counted_as_profit_and_inputs_stay_unchanged():
    state, snapshot = documents(cash=498, capital=700)
    originals = copy.deepcopy((state, snapshot))
    result = build_analysis([trade()], snapshot, state)
    assert result["valid"] and result["summary"]["total_pnl"] == 18
    assert (state, snapshot) == originals


def test_recorded_quantity_precision_has_a_bounded_reconciliation_tolerance():
    state, snapshot = documents(qty=2.000000004, cash=297.9999996)
    result = build_analysis([trade()], snapshot, state)
    assert result["valid"]
    assert result["reconciliation"]["by_sleeve"]["crypto"]["quantities"]["ETH"]["tolerance"] < 1e-8
    state["sleeves"]["crypto"]["ledger"]["positions"]["ETH"] = 2.00001
    assert not build_analysis([trade()], snapshot, state)["valid"]
