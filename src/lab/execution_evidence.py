"""Exact, offline replay evidence for an observed internal-paper decision.

This verifies the captured software execution, not exchange queue priority,
real fills, historical data quality, or future profitability.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
import math
import os

import numpy as np
import pandas as pd

from .brokers import BookSimBroker, SimBroker
from .broker_tape import BrokerTapeReplayError, PublicBrokerTape


LIMITATIONS = [
    "Reproduces one captured internal-paper decision; does not validate real exchange fills or queue priority.",
    "Does not establish historical point-in-time data coverage, strategy superiority, or future profitability.",
    "The frozen research observer and its execution-equivalence flags remain unchanged.",
]


def json_value(value):
    """Lossless finite numeric JSON; missing panel observations stay missing."""
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"unsupported evidence value: {type(value).__name__}")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def panel_payload(prices):
    return {"index": [x.isoformat() for x in prices.index],
            "columns": list(prices.columns), "values": json_value(prices.to_numpy().tolist())}


class ExecutionTrace:
    """Optional hooks; hook failures must never change order execution."""

    def __init__(self):
        self.requests = []
        self.fills = []
        self.errors = []

    def unavailable(self, reason):
        self.errors.append(str(reason)[:400])

    def record_request(self, asset, side, qty, ref_price):
        try:
            self.requests.append(json_value({"asset": asset, "side": side, "qty": qty,
                                             "ref_price": ref_price}))
        except Exception as exc:
            self.unavailable(f"request capture: {type(exc).__name__}")

    def record_fill(self, fill):
        try:
            self.fills.append(json_value(asdict(fill)))
        except Exception as exc:
            self.unavailable(f"fill capture: {type(exc).__name__}")


class ExecutionCapture(ExecutionTrace):
    def __init__(self, sleeve, sc, prices, now, mode, eq_hist, max_jump):
        super().__init__()
        self.sleeve = sleeve
        self.observed_at = pd.Timestamp(now).isoformat()
        self.candle = prices.index[-1].date().isoformat()
        self.inputs = json_value({
            "schema_version": 1, "sleeve": sleeve, "config": copy.deepcopy(sc),
            "prices": panel_payload(prices), "now": self.observed_at, "mode": mode,
            "eq_hist": {"index": [pd.Timestamp(x).isoformat() for x in eq_hist.index],
                        "values": eq_hist.tolist()}, "max_jump": max_jump,
        })
        self.tape = None
        self.broker = None

    def book_kwargs(self, exchange):
        try:
            self.tape = PublicBrokerTape()
            return self.tape.recording_kwargs(exchange)
        except Exception as exc:
            self.unavailable(f"public tape initialization: {type(exc).__name__}")
            return {"exchange": exchange}

    def begin(self, broker, state):
        try:
            if self.inputs["mode"] != "paper" or type(broker) not in (SimBroker, BookSimBroker):
                self.unavailable("only internal SimBroker/BookSimBroker paper execution is supported")
                return
            self.broker = broker
            self.inputs["state"] = json_value(copy.deepcopy(state))
            self.inputs["broker"] = json_value({
                "kind": type(broker).__name__, "name": broker.name,
                "fee": broker.fee, "slippage": broker.slip, "min_order_value": broker.min_order_value,
                "quote": getattr(broker, "quote", None), "maker": getattr(broker, "maker", None),
                "maker_left": getattr(broker, "_maker_left", None),
            })
        except Exception as exc:
            self.unavailable(f"initial state capture: {type(exc).__name__}")

    def finish(self, result, state):
        """Return JSON evidence even when capture/replay failed; never raise."""
        payload = {"capture_id": "", "sleeve": self.sleeve, "observed_at": self.observed_at,
                   "candle": self.candle, "status": "unavailable", "checks": {},
                   "limitations": list(LIMITATIONS), "inputs": self.inputs, "outputs": {},
                   "replay": {}, "build_id": os.environ.get("TRADING_LAB_BUILD_ID", "local-uncommitted")}
        try:
            if self.tape is not None:
                self.inputs["public_tape"] = self.tape.export()
            payload["outputs"] = json_value({
                "result": result, "state": copy.deepcopy(state),
                "ledger": copy.deepcopy(getattr(self.broker, "l", None)),
                "maker_left": getattr(self.broker, "_maker_left", None),
                "requests": self.requests, "fills": self.fills,
            })
            payload["capture_id"] = digest({k: payload[k] for k in ("sleeve", "candle", "inputs", "outputs")})
            if self.errors:
                raise ValueError("; ".join(self.errors))
            replay = replay_capture(payload)
            payload.update(status=replay["status"], checks=replay["checks"], replay=replay)
        except (Exception, BrokerTapeReplayError) as exc:
            payload["replay"] = {"status": "unavailable", "reason": str(exc)[:600],
                                 "complete_execution_equivalence_verified": False}
            if not payload["capture_id"]:
                payload["capture_id"] = digest({"sleeve": self.sleeve, "candle": self.candle,
                                                "inputs": self.inputs, "reason": str(exc)[:600]})
        return payload


def replay_capture(payload):
    """Run the same decision on isolated copies and a strict dependency tape.

    No make_broker/fetch_prices/environment loader is called here. A book capture
    cannot silently fall back to a current exchange or an assumed execution.
    """
    from .bot import run_sleeve

    expected_id = digest({k: payload[k] for k in ("sleeve", "candle", "inputs", "outputs")})
    if payload.get("capture_id") != expected_id:
        raise ValueError("capture content hash mismatch")
    inp = payload["inputs"]
    if inp.get("schema_version") != 1 or inp.get("mode") != "paper":
        raise ValueError("unsupported evidence schema or mode")
    state = copy.deepcopy(inp["state"])
    description = inp["broker"]
    ledger = state["ledger"]
    kwargs = {"ledger": ledger, "fee": description["fee"], "slippage": description["slippage"],
              "min_order_value": description["min_order_value"]}
    tape = None
    if description["kind"] == "BookSimBroker":
        tape = PublicBrokerTape.from_payload(inp["public_tape"])
        broker = BookSimBroker(ledger, description["fee"], description["quote"],
                               description["min_order_value"], description["slippage"],
                               maker=description["maker"], **tape.replay_kwargs())
        if broker._maker_left != description["maker_left"]:
            raise ValueError("initial maker budget mismatch")
    elif description["kind"] == "SimBroker":
        if inp.get("public_tape") is not None:
            # A failed public-book constructor can legitimately resolve to the
            # assumed simulator. Prove that captured failure instead of silently
            # ignoring its tape and claiming it was consumed.
            tape = PublicBrokerTape.from_payload(inp["public_tape"])
            execution = inp["config"].get("execution") or {}
            maker = ({"wait_s": execution.get("wait_s", 120), "poll_s": execution.get("poll_s", 15),
                      "budget_s": execution.get("budget_s", 480), "fee": execution.get("maker_fee", .003)}
                     if execution.get("maker_first") else None)
            try:
                BookSimBroker(ledger, description["fee"], inp["config"]["quote"],
                              description["min_order_value"], description["slippage"],
                              maker=maker, **tape.replay_kwargs())
            except Exception:
                pass
            else:
                raise ValueError("captured public broker fallback did not recur")
        broker = SimBroker(**kwargs)
    else:
        raise ValueError("unsupported broker; replay never opens an external account")
    broker.name = description["name"]
    panel = inp["prices"]
    prices = pd.DataFrame(panel["values"], index=pd.DatetimeIndex(panel["index"]),
                          columns=panel["columns"], dtype=float)
    history = inp["eq_hist"]
    eq_hist = pd.Series(history["values"], index=pd.DatetimeIndex(history["index"]), dtype=float)
    trace = ExecutionTrace()
    result = run_sleeve(inp["sleeve"], inp["config"], prices, broker, state,
                       pd.Timestamp(inp["now"]), "paper", eq_hist, inp["max_jump"], evidence=trace)
    if tape is not None:
        tape.assert_consumed()
    expected = payload["outputs"]
    actual = json_value({"result": result, "state": state, "ledger": ledger,
                         "maker_left": getattr(broker, "_maker_left", None),
                         "requests": trace.requests, "fills": trace.fills})
    checks = {key: actual[key] == expected[key] for key in actual}
    checks.update(input_integrity=True, tape_consumed=True, trace_complete=not trace.errors)
    passed = all(checks.values())
    status = "verified" if passed else "mismatch"
    if passed and not trace.requests:
        status = "verified_no_orders"
    return {"status": status, "checks": checks, "requests": len(trace.requests),
            "fills": len(trace.fills), "scope": "captured_internal_paper_decision",
            "decision_status": result["status"], "broker_kind": description["kind"],
            "complete_execution_equivalence_verified": False}
