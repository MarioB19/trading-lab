import copy
import json

import pandas as pd
import pytest

from lab.bot import DEFAULT_CONFIG, make_broker, run_sleeve
from lab.brokers import BookSimBroker, SimBroker
from lab.execution_evidence import ExecutionCapture, digest, replay_capture


def case(cash=500., positions=None, **config):
    sc = copy.deepcopy(DEFAULT_CONFIG["sleeves"]["stocks"])
    sc.update(capital=500., universe=["SPY", "IEF"], **config)
    prices = pd.DataFrame({"SPY": 100., "IEF": 100.}, index=pd.date_range("2025-01-01", periods=300, freq="B"))
    state = {"capital_base": 500., "mode": "paper",
             "ledger": {"cash": cash, "positions": positions or {}}}
    now = prices.index[-1] + pd.Timedelta(days=1, hours=2)
    hist = pd.Series(dtype=float)
    return sc, prices, state, now, hist


def capture_case(sc, prices, state, now, hist, broker=None):
    capture = ExecutionCapture("stocks", sc, prices, now, "paper", hist, .4)
    broker = broker or SimBroker(state["ledger"], sc["fee"], sc["slippage"], sc["min_order_value"])
    capture.begin(broker, state)
    result = run_sleeve("stocks", sc, prices, broker, state, now, "paper", hist, .4, evidence=capture)
    return capture.finish(result, state), result


def test_simulation_replays_exact_requests_fees_and_balances_without_fetch(monkeypatch):
    sc, prices, state, now, hist = case(fee=.001, slippage=.0007)
    monkeypatch.setattr("lab.bot.make_broker", lambda *a, **k: pytest.fail("replay constructed a current broker"))
    monkeypatch.setattr("lab.bot.fetch_prices", lambda *a, **k: pytest.fail("replay fetched current data"))
    before = copy.deepcopy(state)
    payload, result = capture_case(sc, prices, state, now, hist)
    assert payload["status"] == "verified"
    assert all(payload["checks"].values())
    assert payload["inputs"]["state"] == before
    assert len(payload["outputs"]["requests"]) == 2
    assert payload["outputs"]["fills"][0]["fee"] != result["trades"][0]["fee"]
    assert payload["outputs"]["ledger"] == state["ledger"]
    assert payload["replay"]["complete_execution_equivalence_verified"] is False
    saved = json.loads(json.dumps(payload, allow_nan=False))
    assert replay_capture(saved)["status"] == "verified"
    assert state == payload["outputs"]["state"]  # replay did not mutate original state


@pytest.mark.parametrize("cash,positions,extra", [
    (-.1, {"SPY": 3., "IEF": 2.}, {}),
    (0., {"SPY": 3., "IEF": 2.}, {"peak": 1000.}),
    (0., {"SPY": 3., "IEF": 2.}, {}),
])
def test_recovery_kill_and_no_order_decision_preserve_runtime_behavior(cash, positions, extra):
    sc, prices, state, now, hist = case(cash=cash, positions=positions)
    state.update(extra)
    original = copy.deepcopy(state)
    baseline_broker = SimBroker(original["ledger"], sc["fee"], sc["slippage"], sc["min_order_value"])
    baseline = run_sleeve("stocks", sc, prices, baseline_broker, original, now, "paper", hist, .4)
    payload, result = capture_case(sc, prices, state, now, hist)
    assert result == baseline and state == original
    assert payload["status"] in ("verified", "verified_no_orders")
    assert all(payload["checks"].values())


def test_missing_price_stays_missing_and_blocked_gate_replays():
    sc, prices, state, now, hist = case(cash=0., positions={"SPY": 3., "IEF": 2.})
    prices.loc[prices.index[-7]:, "SPY"] = float("nan")
    payload, result = capture_case(sc, prices, state, now, hist)
    assert result["status"] == "blocked"
    assert payload["status"] == "verified_no_orders"
    assert payload["replay"]["decision_status"] == "blocked"
    assert payload["inputs"]["prices"]["values"][-1][0] is None
    json.dumps(payload, allow_nan=False)


def test_hash_detects_tampering_and_replay_detects_changed_expected_cash():
    payload, _ = capture_case(*case())
    changed = copy.deepcopy(payload)
    changed["outputs"]["ledger"]["cash"] += 1
    with pytest.raises(ValueError, match="hash mismatch"):
        replay_capture(changed)
    changed["capture_id"] = digest({k: changed[k] for k in ("sleeve", "candle", "inputs", "outputs")})
    outcome = replay_capture(changed)
    assert outcome["status"] == "mismatch" and outcome["checks"]["ledger"] is False


def test_capture_identity_is_stable_across_json_roundtrip():
    first, _ = capture_case(*case())
    second, _ = capture_case(*case())
    assert first["capture_id"] == second["capture_id"]


def test_evidence_hook_failure_does_not_change_trading_result():
    sc, prices, state, now, hist = case()
    baseline = copy.deepcopy(state)
    br = SimBroker(state["ledger"], sc["fee"], sc["slippage"], sc["min_order_value"])
    other = SimBroker(baseline["ledger"], sc["fee"], sc["slippage"], sc["min_order_value"])
    class BrokenSink:
        def __getattr__(self, name):
            raise RuntimeError("evidence unavailable")
    actual = run_sleeve("stocks", sc, prices, br, state, now, "paper", hist, .4, evidence=BrokenSink())
    expected = run_sleeve("stocks", sc, prices, other, baseline, now, "paper", hist, .4)
    assert actual == expected and state == baseline


def test_replay_failure_returns_unavailable_without_mutating_actual_output(monkeypatch):
    sc, prices, state, now, hist = case()
    def broken(_):
        raise RuntimeError("deliberate replay failure")
    monkeypatch.setattr("lab.execution_evidence.replay_capture", broken)
    payload, result = capture_case(sc, prices, state, now, hist)
    assert result["status"] == "ok" and len(result["trades"]) == 2
    assert payload["status"] == "unavailable"
    assert "deliberate replay failure" in payload["replay"]["reason"]
    assert payload["outputs"]["state"] == state


class Exchange:
    def __init__(self):
        self.markets = {f"{asset}/USD": {"active": True, "limits": {"cost": {"min": 1.}}}
                        for asset in ("SPY", "IEF")}
    def load_markets(self):
        return self.markets
    def amount_to_precision(self, symbol, qty):
        return f"{qty:.6f}"
    def fetch_order_book(self, symbol, limit):
        return {"bids": [[99., 100.]], "asks": [[101., 100.]]}


def test_book_replay_uses_captured_exchange_and_retains_sim_broker_type(monkeypatch):
    sc, prices, state, now, hist = case(fee=.0036, slippage=.001, paper_broker="bitso_book",
                                         execution={"maker_first": False})
    monkeypatch.setattr("lab.bot.make_exchange", lambda _: Exchange())
    capture = ExecutionCapture("stocks", sc, prices, now, "paper", hist, .4)
    broker = make_broker("stocks", sc, "paper", state, [], evidence=capture)
    assert isinstance(broker, SimBroker) and isinstance(broker, BookSimBroker)
    capture.begin(broker, state)
    result = run_sleeve("stocks", sc, prices, broker, state, now, "paper", hist, .4, evidence=capture)
    monkeypatch.setattr("lab.bot.make_exchange", lambda _: pytest.fail("replay must not fetch"))
    payload = capture.finish(result, state)
    assert payload["status"] == "verified", payload["replay"]
    assert payload["inputs"]["public_tape"]["complete"] is True
    assert replay_capture(json.loads(json.dumps(payload)))["status"] == "verified"


def test_external_broker_is_explicitly_unsupported():
    sc, prices, state, now, hist = case()
    capture = ExecutionCapture("stocks", sc, prices, now, "paper", hist, .4)
    capture.begin(object(), state)
    payload = capture.finish({"status": "ok"}, state)
    assert payload["status"] == "unavailable"
    assert "only internal" in payload["replay"]["reason"]


def test_failed_public_broker_constructor_replays_the_actual_simulator_fallback(monkeypatch):
    sc, prices, state, now, hist = case(paper_broker="bitso_book")
    class UnavailableExchange(Exchange):
        def load_markets(self):
            raise RuntimeError("public markets unavailable")
    monkeypatch.setattr("lab.bot.make_exchange", lambda _: UnavailableExchange())
    capture = ExecutionCapture("stocks", sc, prices, now, "paper", hist, .4)
    notes = []
    broker = make_broker("stocks", sc, "paper", state, notes, evidence=capture)
    assert type(broker) is SimBroker and notes
    capture.begin(broker, state)
    result = run_sleeve("stocks", sc, prices, broker, state, now, "paper", hist, .4, evidence=capture)
    payload = capture.finish(result, state)
    assert payload["status"] == "verified", payload["replay"]
    assert payload["checks"]["tape_consumed"] is True


@pytest.mark.parametrize("broken_finish", [False, True])
def test_main_persists_exact_decision_and_provenance_without_breaking_on_capture_failure(tmp_path, monkeypatch, broken_finish):
    import yaml
    from lab import bot
    from lab.data_evidence import record_data
    from lab.storage import SQLiteStore

    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["sleeves"]["crypto"]["enabled"] = False
    cfg["sleeves"]["stocks"].update(capital=500., paper_broker="sim", universe=["SPY", "IEF"])
    cfg["paths"] = {name: str(tmp_path / filename) for name, filename in {
        "state": "state.json", "trades": "trades.csv", "equity": "equity.csv",
        "snapshot": "snapshot.json", "database": "trading.sqlite3"}.items()}
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(cfg))
    end = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    prices = pd.DataFrame({"SPY": 100., "IEF": 100.}, index=pd.date_range(end=end, periods=300))
    def fetch(*args):
        record_data("synthetic_provider", source="fixture", selected_price_basis="fixture_close")
        return prices
    monkeypatch.setattr(bot, "fetch_prices", fetch)
    monkeypatch.setattr(bot, "load_env", lambda *a: None)
    monkeypatch.setattr(bot, "usd_mxn_now", lambda: {})
    monkeypatch.setattr(bot, "usd_mxn_daily", lambda *a: pd.Series(dtype=float))
    if broken_finish:
        def broken(*a):
            raise RuntimeError("capture-only failure")
        monkeypatch.setattr(ExecutionCapture, "finish", broken)
    assert bot.main(["--config", str(config)]) == 0
    store = SQLiteStore(cfg["paths"]["database"])
    assert len(store.rows("trades")) == 2
    assert store.read_document("snapshot")["sleeves"]["stocks"]["status"] == "ok"
    with store.connect() as db:
        raw = db.execute("SELECT payload FROM documents WHERE name LIKE 'evidence.capture.execution.%'").fetchone()
    payload = json.loads(raw[0])
    if broken_finish:
        assert payload["status"] == "unavailable"
    else:
        assert payload["status"] == "verified"
        assert payload["inputs"]["prices_provenance"]["records"][0]["source"] == "fixture"
        assert replay_capture(payload)["status"] == "verified"
        assert payload["outputs"]["state"] == store.read_document("state")["sleeves"]["stocks"]
