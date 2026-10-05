"""Public exchange responses and timing for an exact offline broker replay.

Recording forwards the original objects and exceptions unchanged. A value that
cannot be represented as strict JSON makes the evidence unavailable, never the
broker operation. Replay accepts complete tapes only and checks every call.
Only the public methods needed by BookSimBroker are delegated by the proxy.
"""
from __future__ import annotations

import builtins
import copy
import json
import math
import time


_METHODS = frozenset({
    "load_markets", "amount_to_precision", "milliseconds", "fetch_order_book", "fetch_trades",
})
_ALL_METHODS = _METHODS | {"clock", "sleep"}


class BrokerTapeReplayError(BaseException):
    """A replay divergence must bypass the broker's ordinary Exception fallback.

    Verification callers may catch this class explicitly. Recorded exchange
    exceptions remain ordinary Exceptions and retain the normal broker behavior.
    """


class RecordedPublicBrokerError(Exception):
    """Base for exchange-specific exception names without importing a provider."""


def _json_value(value):
    """Detach public values without rounding or silently coercing invalid values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("non-string mapping key")
        return {key: _json_value(item) for key, item in value.items()}
    raise TypeError("unsupported public value type")


def _signature(method, args, kwargs):
    return json.dumps([method, args, kwargs], sort_keys=True, allow_nan=False,
                      separators=(",", ":"), ensure_ascii=False)


def _recorded_exception(value):
    name, message, args = value["type"], value["message"], value["args"]
    kind = getattr(builtins, name, None)
    if not isinstance(kind, type) or not issubclass(kind, Exception):
        kind = type(name, (RecordedPublicBrokerError,), {})
    try:
        result = kind(*args)
        if str(result) == message:
            return result
    except Exception:
        pass
    # Some errors format attributes outside args (for example OSError.filename).
    # Replay preserves the public error text without importing provider code.
    return type(name, (RecordedPublicBrokerError,), {"__str__": lambda self: message})(*args)


class _RecordingExchange:
    def __init__(self, tape, exchange):
        self._tape, self._exchange = tape, exchange

    @property
    def markets(self):
        # Do not substitute a copied market dict in the executing broker.
        return self._exchange.markets

    def __getattr__(self, method):
        if method not in _METHODS:
            raise AttributeError(method)

        def invoke(*args, **kwargs):
            return self._tape._record(method, args, kwargs,
                                      lambda: getattr(self._exchange, method)(*args, **kwargs))

        return invoke


class _ReplayExchange:
    def __init__(self, tape):
        self._tape = tape

    @property
    def markets(self):
        return self._tape._markets

    def __getattr__(self, method):
        if method not in _METHODS:
            raise AttributeError(method)

        def invoke(*args, **kwargs):
            return self._tape._replay(method, args, kwargs)

        return invoke


class PublicBrokerTape:
    """Capture one broker lifetime, including its shared maker time budget.

    ``tape.recording_kwargs(exchange)`` supplies the three constructor kwargs
    for BookSimBroker. For replay use ``from_payload(payload).replay_kwargs()``
    and call ``assert_consumed()`` after the same complete sequence of actions.
    Injectable recording clocks are useful for synthetic tests; replay never
    calls a clock, sleep function, exchange factory or network client.
    """

    def __init__(self, *, clock=None, sleep=None):
        self._clock = time.monotonic if clock is None else clock
        self._sleep = time.sleep if sleep is None else sleep
        self._calls = []
        self._markets = {}
        self._initial_markets = {}
        self._exchange = None
        self._recording_attached = False
        self._is_replay = False
        self._cursor = 0
        self._error = None
        self._failure = None

    def _unavailable(self, where, event=None):
        if self._error is None:
            self._error = "unavailable: " + where
        if event is not None:
            event.setdefault("unavailable", []).append(where)

    def _capture(self, value, where, event=None):
        try:
            return _json_value(value)
        except Exception:
            self._unavailable(where, event)
            return None

    def _capture_markets(self, event=None):
        try:
            raw = getattr(self._exchange, "markets", {})
        except Exception:
            self._unavailable("markets", event)
            return None
        return self._capture(raw, "markets", event)

    def recording_kwargs(self, exchange):
        if self._is_replay or self._recording_attached:
            raise ValueError("a tape records only one exchange instance")
        self._exchange = exchange
        self._recording_attached = True
        self._initial_markets = self._capture_markets()
        return {"exchange": _RecordingExchange(self, exchange),
                "clock": lambda: self._record("clock", (), {}, self._clock),
                "sleep": lambda seconds: self._record("sleep", (seconds,), {}, lambda: self._sleep(seconds))}

    def _record(self, method, args, kwargs, operation):
        event = {"method": method}
        self._calls.append(event)
        event["args"] = self._capture(args, "args", event)
        event["kwargs"] = self._capture(kwargs, "kwargs", event)
        try:
            result = operation()
        except Exception as exc:
            try:
                event["exception"] = {"type": type(exc).__name__, "message": str(exc),
                                      "args": self._capture(exc.args, "exception.args", event)}
            except Exception:
                self._unavailable("exception", event)
            if method == "load_markets":
                event["markets"] = self._capture_markets(event)
            raise
        else:
            event["return"] = self._capture(result, "return", event)
            if method == "load_markets":
                event["markets"] = self._capture_markets(event)
            return result

    def export(self):
        """Return detached JSON evidence; unavailable capture is never replayable."""
        if not self._recording_attached and not self._is_replay:
            self._unavailable("exchange was not attached")
        if any("return" not in event and "exception" not in event for event in self._calls):
            self._unavailable("unfinished call")
        return copy.deepcopy({"schema_version": 1, "markets": self._initial_markets,
                              "calls": self._calls, "complete": self._error is None,
                              "error": self._error})

    @classmethod
    def from_payload(cls, payload):
        """Validate and detach a tape before any broker construction."""
        try:
            saved = _json_value(payload)
        except Exception as exc:
            raise ValueError("broker tape is not strict JSON") from exc
        if not isinstance(saved, dict) or type(saved.get("schema_version")) is not int or saved["schema_version"] != 1:
            raise ValueError("unsupported broker tape schema")
        if saved.get("complete") is not True or saved.get("error") is not None:
            raise ValueError("broker tape capture is unavailable")
        if ("markets" not in saved or (saved["markets"] is not None and not isinstance(saved["markets"], dict))
                or not isinstance(saved.get("calls"), list)):
            raise ValueError("invalid broker tape markets or calls")
        for event in saved["calls"]:
            if (not isinstance(event, dict) or not isinstance(event.get("method"), str)
                    or event["method"] not in _ALL_METHODS
                    or not isinstance(event.get("args"), list) or not isinstance(event.get("kwargs"), dict)
                    or bool("return" in event) == bool("exception" in event) or "unavailable" in event):
                raise ValueError("invalid broker tape call")
            if (event["method"] == "load_markets"
                    and ("markets" not in event or (event["markets"] is not None and not isinstance(event["markets"], dict)))):
                raise ValueError("invalid broker tape market update")
            if "exception" in event:
                exc = event["exception"]
                if (not isinstance(exc, dict) or not isinstance(exc.get("type"), str)
                        or not exc["type"].isidentifier() or not isinstance(exc.get("message"), str)
                        or not isinstance(exc.get("args"), list)):
                    raise ValueError("invalid broker tape exception")
        result = cls()
        result._is_replay = True
        result._calls = saved["calls"]
        result._markets = copy.deepcopy(saved["markets"])
        result._initial_markets = saved["markets"]
        return result

    def replay_kwargs(self):
        if not self._is_replay:
            raise ValueError("create a replay tape with from_payload first")
        return {"exchange": _ReplayExchange(self),
                "clock": lambda: self._replay("clock", (), {}),
                "sleep": lambda seconds: self._replay("sleep", (seconds,), {})}

    def _fail(self, message):
        self._failure = self._failure or message
        raise BrokerTapeReplayError(self._failure)

    def _replay(self, method, args, kwargs):
        if self._failure:
            self._fail(self._failure)
        if self._cursor >= len(self._calls):
            self._fail(f"unexpected call {method} after tape end")
        event = self._calls[self._cursor]
        try:
            actual = _signature(method, _json_value(args), _json_value(kwargs))
            expected = _signature(event["method"], event["args"], event["kwargs"])
        except Exception:
            self._fail(f"invalid arguments at tape call {self._cursor}")
        if actual != expected:
            self._fail(f"call mismatch at {self._cursor}: expected {event['method']}, received {method}")
        self._cursor += 1
        if method == "load_markets":
            self._markets = copy.deepcopy(event["markets"])
        if "exception" in event:
            raise _recorded_exception(event["exception"])
        return copy.deepcopy(event["return"])

    def assert_consumed(self):
        if not self._is_replay:
            raise ValueError("consumption applies only to replay tapes")
        if self._failure:
            self._fail(self._failure)
        if self._cursor != len(self._calls):
            self._fail(f"unconsumed broker tape calls: {len(self._calls) - self._cursor}")
