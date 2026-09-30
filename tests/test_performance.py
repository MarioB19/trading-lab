from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from lab.performance import build_performance
from lab.runtime import DATABASE_NAME
from lab.service import Reader, make_server
from lab.storage import SQLiteStore


def row(day, name, equity, flow="", fx=17.7):
    return {"date": day, "sleeve": name, "mode": "paper", "equity": equity,
            "flow": flow, "usd_mxn": fx}


@pytest.fixture
def sample():
    state = {"sleeves": {"crypto": {"mode": "paper", "capital_base": 500},
                         "stocks": {"mode": "paper", "capital_base": 700}}}
    snapshot = {"mode": "paper", "generated_utc": "2026-09-28 00:35", "sleeves": {
        "crypto": {"status": "ok", "equity": 506.98, "candle": "2026-09-27"},
        "stocks": {"status": "skip", "equity": 702.89, "candle": "2026-09-25"}},
        "fx": {"rate": 17.7395, "source": "snapshot", "time_utc": "2026-09-28 00:35"}}
    live = {"mode": "paper", "updated_utc": "2026-09-28 06:43", "sleeves": {
        "crypto": {"status": "ok", "equity": 498.49, "prices_as_of_utc": "2026-09-28 06:43"},
        "stocks": {"status": "ok", "equity": 702.89, "prices_as_of_utc": "2026-09-25 20:00"}},
        "fx": {"rate": 17.7645, "source": "Bitso USD/MXN", "time_utc": "2026-09-28 06:43"}}
    rows = [row("2026-09-24", "crypto", 299.34, fx=17.707),
            row("2026-09-24", "stocks", 699.65, fx=17.707),
            row("2026-09-25", "crypto", 306.01, fx=17.68),
            row("2026-09-25", "stocks", 702.89, fx=17.68),
            row("2026-09-26", "crypto", 306.72, fx=17.677),
            row("2026-09-27", "crypto", 506.98, 200, 17.7395)]
    config = {"sleeves": {"crypto": {"enabled": True, "capital": 500},
                           "stocks": {"enabled": True, "capital": 500}, "multi": {"enabled": False}}}
    return dict(state=state, snapshot=snapshot, live=live, equity_rows=rows, config=config)


def test_deposit_is_not_profit_and_config_is_not_applied_capital(sample):
    original = deepcopy(sample)
    result = build_performance(**sample)
    assert sample == original
    assert result["capital"]["target_usd"] == 1000
    assert result["capital"]["applied_usd"] == 1200
    assert result["capital"]["pending_flow_usd"] == -200
    assert result["capital"]["by_sleeve"]["crypto"]["initial_usd"] == 300
    assert result["capital"]["by_sleeve"]["crypto"]["initial_inferred"] is True
    assert result["current"]["equity_usd"] == 1201.38
    assert result["current"]["pnl_usd"] == 1.38
    assert result["current"]["pnl_mxn"] == 24.52
    daily = result["daily"][-1]
    assert daily["flow_usd"] == 200
    assert daily["pnl_usd"] == .26
    assert daily["pnl_mxn"] == 4.61
    assert result["in_progress"]["pnl_usd"] == -8.49
    assert result["in_progress"]["by_sleeve"]["stocks"]["pnl_usd"] == 0


def test_first_close_keeps_initial_commission_loss(sample):
    first = build_performance(**sample)["daily"][0]
    assert first["pnl_usd"] == -1.01
    assert first["pnl_mxn"] == -17.88  # Round once after summing unrounded conversions.
    assert first["by_sleeve"]["crypto"]["pnl_usd"] == -.66
    assert any("reconstruida" in note for note in first["notes"])


def test_balance_chart_keeps_deposit_in_capital_and_uses_each_historical_fx(sample):
    result = build_performance(**sample)
    assert [d["capital_usd"] for d in result["daily"]] == [1000, 1000, 1000, 1200]
    assert [d["by_sleeve"]["crypto"]["capital_usd"] for d in result["daily"]] == [300, 300, 300, 500]
    first, sunday = result["daily"][0], result["daily"][-1]
    assert first["equity_mxn"] == 17689.12
    assert first["capital_mxn"] == 17707
    assert sunday["equity_usd"] == 1209.87
    assert sunday["equity_mxn"] == 21420.67
    assert sunday["capital_mxn"] == 21245.75
    assert sunday["pnl_usd"] == .26  # The balance jump includes a deposit, not a trading gain.
    stock = sunday["by_sleeve"]["stocks"]
    assert stock["equity_fx_rate"] == 17.68
    assert stock["equity_fx_date"] == "2026-09-25"
    assert stock["equity_mxn"] == 12427.1
    assert stock["fx_rate"] is None  # P&L conversion semantics remain unchanged.
    assert stock["pnl_mxn"] == 0
    assert sunday["by_sleeve"]["crypto"]["equity_fx_date"] == "2026-09-27"
    sample["live"]["fx"]["rate"] = 9999
    assert build_performance(**sample)["daily"] == result["daily"]


def test_withdrawal_is_not_a_loss_and_monday_is_a_valid_session(sample):
    sample["state"]["sleeves"]["stocks"]["capital_base"] = 500
    sample["equity_rows"].extend([row("2026-09-28", "stocks", 503.89, -200),
                                  row("2026-09-28", "crypto", 507.98)])
    sample["live"]["updated_utc"] = "2026-09-29 01:00"
    sample["live"]["sleeves"]["stocks"].update(equity=503.89, prices_as_of_utc="2026-09-28 20:00")
    result = build_performance(**sample)
    assert result["capital"]["applied_usd"] == 1000
    assert result["capital"]["pending_flow_usd"] == 0
    last = result["daily"][-1]
    assert last["pnl_usd"] == 2
    assert last["flow_usd"] == -200
    assert last["by_sleeve"]["stocks"]["pnl_usd"] == 1
    assert last["by_sleeve"]["stocks"]["span_days"] == 3
    assert last["by_sleeve"]["stocks"]["reliable"] is True
    assert last["capital_usd"] == 1000
    assert last["capital_mxn"] == 17700
    assert last["equity_usd"] == 1011.87
    assert last["equity_mxn"] == 17910.1
    assert last["equity_usd"] - result["daily"][-2]["equity_usd"] == pytest.approx(-198)
    assert last["by_sleeve"]["stocks"]["equity_fx_date"] == "2026-09-28"


def test_weekend_carry_is_valuation_only_and_dates_remain_visible(sample):
    result = build_performance(**sample)
    saturday = result["daily"][2]
    stock = saturday["by_sleeve"]["stocks"]
    assert stock["has_close"] is False and stock["carried"] is True
    assert stock["equity_usd"] == 702.89 and stock["pnl_usd"] == 0
    assert saturday["pnl_usd"] == .71
    assert result["current"]["by_sleeve"]["stocks"]["as_of_utc"] == "2026-09-25 20:00"
    assert result["current"]["by_sleeve"]["crypto"]["as_of_utc"] == "2026-09-28 06:43"


@pytest.mark.parametrize("name,missing_day,next_day", [
    ("crypto", "2026-09-26", "2026-09-27"),
    ("stocks", "2026-09-25", "2026-09-28"),
])
def test_missing_expected_session_is_not_a_daily_return(sample, name, missing_day, next_day):
    sample["equity_rows"] = [r for r in sample["equity_rows"]
                              if not (r["sleeve"] == name and r["date"] == missing_day)]
    if name == "stocks":
        sample["equity_rows"].append(row(next_day, name, 704))
    days = {r["date"]: r for r in build_performance(**sample)["daily"]}
    assert days[missing_day]["by_sleeve"][name]["pnl_usd"] is None
    closing = days[next_day]["by_sleeve"][name]
    assert closing["has_close"] is True and closing["reliable"] is False
    assert closing["pnl_usd"] is None and closing["interval_pnl_usd"] is not None
    assert days[next_day]["pnl_usd"] is None
    assert days[missing_day]["by_sleeve"][name]["capital_usd"] is None
    assert closing["capital_usd"] is None  # A later close cannot recover an unrecorded flow's date.
    assert days[next_day]["capital_usd"] is None


def test_weekend_cannot_hide_a_missing_friday_close(sample):
    sample["equity_rows"] = [r for r in sample["equity_rows"]
                              if not (r["sleeve"] == "stocks" and r["date"] == "2026-09-25")]
    saturday = build_performance(**sample)["daily"][2]
    stock = saturday["by_sleeve"]["stocks"]
    assert stock["carried"] is True
    assert stock["equity_usd"] == 699.65
    assert stock["reliable"] is False
    assert stock["pnl_usd"] is None
    assert saturday["pnl_usd"] is None


def test_missing_historical_fx_does_not_use_current_fx(sample):
    sample["equity_rows"][-1]["usd_mxn"] = ""
    result = build_performance(**sample)
    assert result["fx"]["rate"] == 17.7645
    assert result["daily"][-1]["pnl_usd"] == .26
    assert result["daily"][-1]["pnl_mxn"] is None
    assert result["daily"][-1]["fx_rate"] is None
    assert result["daily"][-1]["equity_usd"] == 1209.87
    assert result["daily"][-1]["equity_mxn"] is None
    assert result["daily"][-1]["capital_usd"] == 1200
    assert result["daily"][-1]["capital_mxn"] is None
    sample["live"]["fx"]["rate"] = None
    result = build_performance(**sample)
    assert result["current"]["pnl_usd"] == 1.38
    assert result["current"]["pnl_mxn"] is None
    assert result["daily"][0]["pnl_mxn"] == -17.88


def test_different_historical_fx_is_converted_per_sleeve(sample):
    sample["equity_rows"][0]["usd_mxn"] = 10
    sample["equity_rows"][1]["usd_mxn"] = 20
    first = build_performance(**sample)["daily"][0]
    assert first["pnl_mxn"] == -13.6
    assert first["fx_rate"] is None
    assert first["equity_mxn"] == 16986.4
    assert first["capital_mxn"] == 17000


def test_carried_balance_does_not_skip_a_close_with_missing_fx(sample):
    sample["equity_rows"][3]["usd_mxn"] = None  # Friday stocks; Thursday FX is known.
    saturday = build_performance(**sample)["daily"][2]
    stock = saturday["by_sleeve"]["stocks"]
    assert saturday["fx_rate"] == 17.677  # Known crypto FX cannot replace stocks' closing FX.
    assert stock["equity_fx_rate"] is None
    assert stock["equity_fx_date"] == "2026-09-25"
    assert stock["equity_usd"] == 702.89 and stock["capital_usd"] == 700
    assert stock["equity_mxn"] is None and stock["capital_mxn"] is None
    assert saturday["equity_mxn"] is None and saturday["capital_mxn"] is None


def test_balance_conversion_sums_before_rounding(sample):
    sample["equity_rows"][0].update(equity=300.003, usd_mxn=1)
    sample["equity_rows"][1].update(equity=700.003, usd_mxn=1)
    first = build_performance(**sample)["daily"][0]
    assert first["by_sleeve"]["crypto"]["equity_mxn"] == 300
    assert first["by_sleeve"]["stocks"]["equity_mxn"] == 700
    assert first["equity_mxn"] == 1000.01


@pytest.mark.parametrize("bad", [None, "", "bad", float("nan"), float("inf"), -1, True])
def test_invalid_live_equity_is_not_replaced_with_an_old_close_or_zero(sample, bad):
    sample["live"]["sleeves"]["crypto"]["equity"] = bad
    result = build_performance(**sample)
    assert result["current"]["equity_usd"] is None
    assert result["current"]["pnl_usd"] is None
    assert result["in_progress"]["pnl_usd"] is None
    assert result["current"]["by_sleeve"]["stocks"]["pnl_usd"] == 2.89
    json.dumps(result, allow_nan=False)


def test_absent_live_sleeve_falls_back_to_snapshot(sample):
    del sample["live"]["sleeves"]["crypto"]
    result = build_performance(**sample)
    assert result["current"]["by_sleeve"]["crypto"]["source"] == "snapshot"
    assert result["current"]["pnl_usd"] == 9.87
    assert result["in_progress"]["by_sleeve"]["crypto"]["pnl_usd"] == 0


def test_new_snapshot_is_used_instead_of_live_valuation_before_a_capital_flow(sample):
    sample["live"]["updated_utc"] = "2026-09-27 21:42"
    sample["live"]["sleeves"]["crypto"].update(equity=307.6, prices_as_of_utc="2026-09-27 21:42")
    result = build_performance(**sample)
    assert result["current"]["by_sleeve"]["crypto"]["source"] == "snapshot"
    assert result["current"]["by_sleeve"]["crypto"]["pnl_usd"] == 6.98


def test_missing_daily_equity_makes_interval_and_progress_unknown(sample):
    sample["equity_rows"][-1]["equity"] = None
    result = build_performance(**sample)
    assert result["daily"][-1]["pnl_usd"] is None
    assert result["daily"][-1]["equity_usd"] is None
    assert result["daily"][-1]["equity_mxn"] is None
    assert result["in_progress"]["pnl_usd"] is None


def test_duplicate_close_is_not_arbitrarily_selected_or_double_counted(sample):
    sample["equity_rows"].append(row("2026-09-27", "crypto", 506.98, 0))
    result = build_performance(**sample)
    assert result["capital"]["by_sleeve"]["crypto"]["initial_usd"] is None
    assert result["daily"][-1]["pnl_usd"] is None
    assert result["daily"][-1]["flow_usd"] is None
    assert all(day["capital_usd"] is None and day["capital_mxn"] is None for day in result["daily"])


def test_no_history_does_not_invent_daily_or_progress_profit(sample):
    sample["equity_rows"] = []
    result = build_performance(**sample)
    assert result["daily"] == []
    assert result["in_progress"]["pnl_usd"] is None
    assert result["current"]["pnl_usd"] == 1.38


def populate(tmp_path, sample):
    store = SQLiteStore(tmp_path / DATABASE_NAME)
    store.commit_run(sample["state"], [], sample["equity_rows"], sample["snapshot"])
    store.commit_live(sample["live"], [])
    config = tmp_path / "explicit.yaml"
    config.write_text("sleeves:\n  crypto: {enabled: true, capital: 500}\n  stocks: {enabled: true, capital: 500}\n")
    return store, config


def test_reader_loads_all_history_and_sorts_without_modifying_database(tmp_path, sample):
    start = date(2020, 1, 1)
    sample["equity_rows"] = [row((start + timedelta(days=i)).isoformat(), "crypto", 300 + i, 200 if i == 550 else 0)
                              for i in reversed(range(601))]
    store, config = populate(tmp_path, sample)
    before = store.rows("equity")
    result = Reader(tmp_path, config).performance()
    assert len(result["daily"]) == 601
    assert result["daily"][0]["date"] == "2020-01-01"
    assert result["daily"][-1]["date"] == (start + timedelta(days=600)).isoformat()
    assert result["capital"]["by_sleeve"]["crypto"]["initial_usd"] == 300
    assert store.rows("equity") == before


def test_reader_uses_one_read_transaction_during_concurrent_writer(tmp_path, sample, monkeypatch):
    store, config = populate(tmp_path, sample)
    reader = Reader(tmp_path, config)
    original = reader.document
    changed = False

    def read_then_update(db, name, default=None):
        nonlocal changed
        result = original(db, name, default)
        if name == "state" and not changed:
            changed = True
            newer = deepcopy(sample)
            newer["state"]["sleeves"]["crypto"]["capital_base"] = 700
            newer["live"]["sleeves"]["crypto"]["equity"] = 698.49
            newer["equity_rows"].append(row("2026-09-28", "crypto", 706.98, 200))
            with store.transaction() as writer:
                store._write(writer, "state", newer["state"])
                store._write(writer, "live", newer["live"])
                store._rows(writer, "equity", newer["equity_rows"])
        return result

    monkeypatch.setattr(reader, "document", read_then_update)
    result = reader.performance()
    assert changed
    assert result["capital"]["applied_usd"] == 1200
    assert result["current"]["equity_usd"] == 1201.38
    assert len(result["daily"]) == 4
    assert Reader(tmp_path, config).performance()["capital"]["applied_usd"] == 1400


def test_performance_http_is_read_only_and_config_is_explicit(tmp_path, sample):
    _, config = populate(tmp_path, sample)
    server = make_server(tmp_path, port=0, config_path=config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/performance"
    try:
        with urlopen(url + "?limit=1") as response:
            body = json.load(response)
            assert body["capital"]["target_usd"] == 1000
            assert len(body["daily"]) == 4  # The generic row endpoint limit cannot truncate accounting.
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url, data=b"{}", method="POST"))
        assert error.value.code == 405
        config.write_text("sleeves: [broken]\n")
        with pytest.raises(HTTPError) as error:
            urlopen(url)
        assert error.value.code == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_uninitialized_performance_does_not_create_database_or_make_up_zeroes(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("sleeves:\n  crypto: {capital: 500}\n  stocks: {capital: 500}\n")
    destination = tmp_path / "absent"
    result = Reader(destination, config).performance()
    assert result["capital"]["target_usd"] == 1000
    assert result["capital"]["applied_usd"] is None
    assert result["current"]["equity_usd"] is None
    assert result["daily"] == []
    assert not destination.exists()
