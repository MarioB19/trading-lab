"""Synthetic execution tapes: no providers, real prices, network or real waits."""
import copy
from dataclasses import asdict
import json
import math

import pytest

from lab.broker_tape import BrokerTapeReplayError, PublicBrokerTape
from lab.brokers import BookSimBroker


class SyntheticExchange:
    def __init__(self):
        self.markets = {}
        self.book = {"bids": [[99., 20.]], "asks": [[101., 20.]]}
        self.calls = []

    def load_markets(self):
        self.calls.append("load_markets")
        self.markets = {"ETH/USD": {"active": True, "limits": {"cost": {"min": .5}}}}
        return self.markets

    def amount_to_precision(self, symbol, qty):
        self.calls.append("amount_to_precision")
        return f"{math.floor(qty * 1e6) / 1e6:.6f}"

    def milliseconds(self):
        self.calls.append("milliseconds")
        return 1_000_000

    def fetch_order_book(self, symbol, limit=100):
        self.calls.append("fetch_order_book")
        return self.book

    def fetch_trades(self, symbol, since=None, limit=100):
        self.calls.append("fetch_trades")
        return [{"id": "synthetic-trade", "timestamp": 1_000_001,
                 "price": 98., "amount": .5, "side": "sell"}]


def recording(exchange=None):
    moment = [0.]
    tape = PublicBrokerTape(clock=lambda: moment[0],
                            sleep=lambda seconds: moment.__setitem__(0, moment[0] + seconds))
    return tape, tape.recording_kwargs(exchange or SyntheticExchange())


def broker(ledger, kwargs, *, maker=True):
    return BookSimBroker(ledger, taker_fee=.0036, min_order_value=1.,
                         maker={"wait_s": 4., "poll_s": 1., "budget_s": 5., "fee": .003} if maker else None,
                         **kwargs)


def test_complete_mixed_maker_taker_replay_is_exact_and_never_calls_real_dependencies(monkeypatch):
    exchange = SyntheticExchange()
    tape, kwargs = recording(exchange)
    initial = {"cash": 1000., "positions": {}}
    ledger = copy.deepcopy(initial)
    recorded_broker = broker(ledger, kwargs)
    expected = [asdict(recorded_broker.execute("ETH", "buy", 2., 100.)) for _ in range(3)]
    payload = json.loads(json.dumps(tape.export(), allow_nan=False))
    assert payload["complete"] is True and payload["error"] is None
    assert payload["markets"] == {}
    assert payload["calls"][0]["markets"] == exchange.markets
    assert expected[0]["execution"]["maker_value_usd"] == 49.5
    assert expected[2]["execution"]["maker_value_usd"] == 0
    recorded_calls = list(exchange.calls)

    def forbidden(*args, **kwargs):
        raise AssertionError("replay consulted a live dependency")

    monkeypatch.setattr("lab.brokers.time.sleep", forbidden)
    monkeypatch.setattr("lab.brokers.time.monotonic", forbidden)
    monkeypatch.setattr("lab.data.make_exchange", forbidden)
    replay = PublicBrokerTape.from_payload(payload)
    replay_ledger = copy.deepcopy(initial)
    replay_broker = broker(replay_ledger, replay.replay_kwargs())
    actual = [asdict(replay_broker.execute("ETH", "buy", 2., 100.)) for _ in range(3)]
    replay.assert_consumed()
    assert actual == expected
    assert replay_ledger == ledger
    assert replay_broker._maker_left == recorded_broker._maker_left == 0
    assert exchange.calls == recorded_calls


def test_taker_cash_cap_and_dust_side_effect_replay_exactly():
    tape, kwargs = recording()
    initial = {"cash": 50.12345678901234, "positions": {"ETH": 1.0000005}}
    ledger = copy.deepcopy(initial)
    original = broker(ledger, kwargs, maker=False)
    sold = asdict(original.execute("ETH", "sell", 1.0000005, 100.))
    assert "ETH" not in ledger["positions"]
    bought = asdict(original.execute("ETH", "buy", 4., 100.))
    assert bought["status"] == "partial"
    replay = PublicBrokerTape.from_payload(tape.export())
    result = copy.deepcopy(initial)
    replay_broker = broker(result, replay.replay_kwargs(), maker=False)
    assert asdict(replay_broker.execute("ETH", "sell", 1.0000005, 100.)) == sold
    assert asdict(replay_broker.execute("ETH", "buy", 4., 100.)) == bought
    replay.assert_consumed()
    assert result == ledger


def test_unloaded_markets_are_preserved_until_load_markets_sets_them():
    exchange = SyntheticExchange()
    exchange.markets = None
    tape, kwargs = recording(exchange)
    broker({"cash": 500., "positions": {}}, kwargs)
    assert tape.export()["markets"] is None
    replay = PublicBrokerTape.from_payload(tape.export())
    replay_kwargs = replay.replay_kwargs()
    assert replay_kwargs["exchange"].markets is None
    replay_broker = broker({"cash": 500., "positions": {}}, replay_kwargs)
    assert replay_broker.ex.markets == exchange.markets
    replay.assert_consumed()


def test_failed_constructor_replays_the_same_error_with_unloaded_markets():
    class Failed(SyntheticExchange):
        def load_markets(self):
            raise TimeoutError("synthetic markets unavailable")

    exchange = Failed()
    exchange.markets = None
    tape, kwargs = recording(exchange)
    with pytest.raises(TimeoutError, match="synthetic markets unavailable"):
        broker({"cash": 500., "positions": {}}, kwargs)
    assert tape.export()["complete"] is True
    replay = PublicBrokerTape.from_payload(tape.export())
    with pytest.raises(TimeoutError, match="synthetic markets unavailable"):
        broker({"cash": 500., "positions": {}}, replay.replay_kwargs())
    replay.assert_consumed()


@pytest.mark.parametrize("error", [TimeoutError("synthetic timeout"), KeyError("synthetic missing book"),
                                   OSError(2, "synthetic missing file", "synthetic-path"),
                                   type("NetworkError", (Exception,), {})("synthetic network failure")])
def test_recorded_exception_preserves_original_operation_and_replays_fallback(error):
    class Unavailable(SyntheticExchange):
        def fetch_order_book(self, symbol, limit=100):
            raise error

    tape, kwargs = recording(Unavailable())
    ledger = {"cash": 500., "positions": {}}
    original = broker(ledger, kwargs)
    expected = asdict(original.execute("ETH", "buy", 1., 100.))
    assert expected["execution"]["execution_source"] == "assumed_simulation"
    assert str(error) in expected["note"]
    assert tape.export()["complete"] is True
    replay = PublicBrokerTape.from_payload(tape.export())
    result = {"cash": 500., "positions": {}}
    assert asdict(broker(result, replay.replay_kwargs()).execute("ETH", "buy", 1., 100.)) == expected
    replay.assert_consumed()
    assert result == ledger


def test_recording_returns_raw_objects_keeps_live_markets_and_adds_no_exchange_calls():
    exchange = SyntheticExchange()
    tape, kwargs = recording(exchange)
    proxy = kwargs["exchange"]
    assert exchange.calls == []
    assert proxy.markets is exchange.markets
    result = proxy.load_markets()
    assert result is exchange.markets and proxy.markets is exchange.markets
    book = proxy.fetch_order_book("ETH/USD", limit=5)
    assert book is exchange.book
    assert exchange.calls == ["load_markets", "fetch_order_book"]
    snapshot = tape.export()
    exchange.book["asks"][0][0] = 999.
    snapshot["calls"][1]["return"]["asks"][0][0] = -1.
    assert tape.export()["calls"][1]["return"]["asks"][0][0] == 101.
    with pytest.raises(AttributeError):
        proxy.create_order("ETH/USD")
    with pytest.raises(AttributeError):
        _ = proxy.apiKey


@pytest.mark.parametrize("invalid", [object(), float("nan"), {1: "not a string key"}])
def test_unserializable_result_is_returned_unchanged_but_cannot_be_replayed(invalid):
    class Unserializable(SyntheticExchange):
        def fetch_order_book(self, symbol, limit=100):
            return invalid

    tape, kwargs = recording(Unserializable())
    assert kwargs["exchange"].fetch_order_book("ETH/USD") is invalid
    payload = tape.export()
    assert payload["complete"] is False
    assert payload["error"] == "unavailable: return"
    assert payload["calls"][0]["unavailable"] == ["return"]
    json.dumps(payload, allow_nan=False)
    with pytest.raises(ValueError, match="unavailable"):
        PublicBrokerTape.from_payload(payload)


def test_unserializable_args_and_markets_do_not_change_forwarded_operation():
    exchange = SyntheticExchange()
    exchange.markets = {"bad": object()}
    tape, kwargs = recording(exchange)
    marker = object()
    assert kwargs["exchange"].fetch_order_book(marker) is exchange.book
    assert exchange.calls == ["fetch_order_book"]
    payload = tape.export()
    assert payload["complete"] is False
    assert payload["calls"][0]["unavailable"] == ["args"]
    json.dumps(payload, allow_nan=False)


def test_original_exception_instance_is_not_wrapped_when_recording():
    original = ValueError("synthetic precision error")

    class Failed(SyntheticExchange):
        def amount_to_precision(self, *args):
            raise original

    tape, kwargs = recording(Failed())
    with pytest.raises(ValueError) as raised:
        kwargs["exchange"].amount_to_precision("ETH/USD", 0.)
    assert raised.value is original
    replay = PublicBrokerTape.from_payload(tape.export())
    with pytest.raises(ValueError, match="synthetic precision error"):
        replay.replay_kwargs()["exchange"].amount_to_precision("ETH/USD", 0.)
    replay.assert_consumed()


def test_unserializable_exception_args_preserve_original_exception_and_block_replay():
    original = ValueError(object())

    class Failed(SyntheticExchange):
        def fetch_order_book(self, *args):
            raise original

    tape, kwargs = recording(Failed())
    with pytest.raises(ValueError) as raised:
        kwargs["exchange"].fetch_order_book("ETH/USD")
    assert raised.value is original
    assert tape.export()["complete"] is False
    assert tape.export()["error"] == "unavailable: exception.args"
    with pytest.raises(ValueError, match="unavailable"):
        PublicBrokerTape.from_payload(tape.export())


def test_call_argument_and_order_mismatches_and_unconsumed_events_fail_closed():
    tape, kwargs = recording()
    kwargs["exchange"].fetch_order_book("ETH/USD", limit=5)
    for operation in [lambda x: x["exchange"].fetch_order_book("ETH/USD", limit=100),
                      lambda x: x["exchange"].fetch_trades("ETH/USD", limit=5)]:
        replay = PublicBrokerTape.from_payload(tape.export())
        with pytest.raises(BrokerTapeReplayError, match="call mismatch"):
            operation(replay.replay_kwargs())
        with pytest.raises(BrokerTapeReplayError):
            replay.assert_consumed()
    replay = PublicBrokerTape.from_payload(tape.export())
    with pytest.raises(BrokerTapeReplayError, match="unconsumed"):
        replay.assert_consumed()
    replay = PublicBrokerTape.from_payload(tape.export())
    replay_kwargs = replay.replay_kwargs()
    replay_kwargs["exchange"].fetch_order_book("ETH/USD", limit=5)
    replay.assert_consumed()
    with pytest.raises(BrokerTapeReplayError, match="after tape end"):
        replay_kwargs["clock"]()


def test_divergence_is_not_swallowed_as_assumed_broker_execution():
    tape, kwargs = recording()
    original = broker({"cash": 500., "positions": {}}, kwargs, maker=False)
    original.execute("ETH", "buy", 1., 100.)
    replay = PublicBrokerTape.from_payload(tape.export())
    replay_broker = broker({"cash": 500., "positions": {}}, replay.replay_kwargs(), maker=False)
    with pytest.raises(BrokerTapeReplayError, match="call mismatch"):
        replay_broker.execute("ETH", "buy", 2., 100.)


def test_precision_and_numeric_argument_types_are_preserved():
    tape, kwargs = recording()
    qty = .12345678901234568
    kwargs["exchange"].amount_to_precision("ETH/USD", qty)
    payload = json.loads(json.dumps(tape.export(), allow_nan=False))
    assert payload["calls"][0]["args"][1] == qty
    replay = PublicBrokerTape.from_payload(payload)
    assert replay.replay_kwargs()["exchange"].amount_to_precision("ETH/USD", qty) == "0.123456"
    replay.assert_consumed()
    tape, kwargs = recording()
    kwargs["sleep"](1.)
    replay = PublicBrokerTape.from_payload(tape.export())
    with pytest.raises(BrokerTapeReplayError):
        replay.replay_kwargs()["sleep"](1)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(schema_version=2),
    lambda p: p.update(complete=False),
    lambda p: p.update(error="unavailable"),
    lambda p: p.update(markets=[]),
    lambda p: p["calls"][0].update(method="create_order"),
    lambda p: p["calls"][0].update(args=None),
    lambda p: p["calls"][0].update(exception={"type": "TimeoutError", "message": "both outcomes"}),
])
def test_invalid_payload_is_rejected_before_broker_construction(mutation):
    tape, kwargs = recording()
    kwargs["clock"]()
    payload = tape.export()
    mutation(payload)
    with pytest.raises(ValueError):
        PublicBrokerTape.from_payload(payload)
