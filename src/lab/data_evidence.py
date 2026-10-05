"""Prospective public-data evidence; never places orders or changes price bases.

Yahoo's Close is split-adjusted; Adj Close also includes distributions:
https://finance.yahoo.com/quote/SPY/history/
https://in.help.yahoo.com/kb/finance/adjusted-close-sln28256.html
Bitso available_books describes present books/limits, not historical listings:
https://docs.bitso.com/bitso-api/docs/list-available-books
Hashes identify captured content; they do not certify provider accuracy or fills.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
import math

import pandas as pd


SCHEMA_VERSION = 1
BITSO_BOOKS_URL = "https://bitso.com/api/v3/available_books/"
_active: ContextVar[MarketObservation | None] = ContextVar("market_observation", default=None)


def _utc(value=None) -> str:
    stamp = pd.Timestamp(value if value is not None else datetime.now(timezone.utc))
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.isoformat()


def _json_value(value):
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _json_value(value.item())
    raise TypeError("unsupported evidence value")


def canonical_bytes(value) -> bytes:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@dataclass
class MarketObservation:
    observed_at_utc: str
    records: list[dict] = field(default_factory=list)
    _seen_markets: set[str] = field(default_factory=set, repr=False)

    @property
    def digest(self) -> str:
        return _digest({"schema_version": SCHEMA_VERSION,
                        "observed_at_utc": self.observed_at_utc, "records": self.records})


@contextmanager
def market_observation(*, observed_at_utc=None):
    """Opt-in recorder. Nested/parallel contexts do not share their record lists."""
    observation = MarketObservation(_utc(observed_at_utc))
    token = _active.set(observation)
    try:
        yield observation
    finally:
        _active.reset(token)


def record_data(kind: str, **fields) -> None:
    """Telemetry failures never change the caller's trading/data behavior."""
    observation = _active.get()
    if observation is None:
        return
    try:
        observation.records.append(_json_value({"kind": kind,
            "observed_at_utc": observation.observed_at_utc, "captured_at_utc": _utc(), **fields}))
    except Exception as exc:
        observation.records.append({"kind": "capture_error", "source_kind": kind,
            "observed_at_utc": observation.observed_at_utc, "error_type": type(exc).__name__})


def record_provider_error(source: str, symbol: str, exc: Exception) -> None:
    # Exception text can contain URLs/headers. Record its type only.
    record_data("provider_error", source=source, symbol=symbol, error_type=type(exc).__name__)


def observe_exchange_markets(exchange) -> None:
    """Inspect already-loaded Bitso metadata once; never triggers a network call.

    A cached market has no verified retrieval time. active=None is unknown,
    and presence is not evidence of account-specific order eligibility.
    """
    observation = _active.get()
    if observation is None:
        return
    try:
        source = str(exchange.id)
        if source != "bitso" or source in observation._seen_markets:
            return
        markets = getattr(exchange, "markets", None)
        if not isinstance(markets, dict) or not markets:
            return
        observation._seen_markets.add(source)
        books = [{"symbol": symbol, "book": market.get("id"), "active": market.get("active"),
                  "limits": market.get("limits"), "precision": market.get("precision")}
                 for symbol, market in sorted(markets.items()) if market.get("quote") == "USD"]
        record_data("cached_markets", source=source, quote="USD", books=books,
                    provider_as_of_utc=None, fresh_response_verified=False,
                    historical_listing_verified=False)
    except Exception as exc:
        record_data("capture_error", source_kind="cached_markets", error_type=type(exc).__name__)


def record_crypto_series(exchange, symbol: str, series: pd.Series, *, days: int) -> None:
    if _active.get() is None:
        return
    try:
        raw = series.to_csv(index_label="date", date_format="%Y-%m-%d", float_format="%.17g")
        record_data("crypto_prices", source=str(exchange.id), symbol=symbol,
                    requested_rows=days, rows=len(series),
                    first_date=series.index.min().date().isoformat() if len(series) else None,
                    last_date=series.index.max().date().isoformat() if len(series) else None,
                    price_basis="exchange_daily_close", selected_source=True,
                    series_sha256=hashlib.sha256(raw.encode()).hexdigest())
        observe_exchange_markets(exchange)
    except Exception as exc:
        record_data("capture_error", source_kind="crypto_prices", error_type=type(exc).__name__)


def record_yahoo_response(symbol: str, result: dict, *, selected_basis: str,
                          last_bar_filled_from_meta: bool) -> None:
    """Keep both provider bases and events. No event changes cash or positions.

    The chart endpoint used by data.py is public, but not a contracted exchange
    feed. An event date is not assumed to be a payment date or announcement time.
    """
    if _active.get() is None:
        return
    try:
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        close = (indicators.get("quote") or [{}])[0].get("close") or []
        adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
        rows = [[stamp, close[i] if i < len(close) else None,
                 adjusted[i] if i < len(adjusted) else None] for i, stamp in enumerate(timestamps)]
        meta = result.get("meta") or {}
        keys = ("currency", "symbol", "exchangeName", "instrumentType", "timezone",
                "exchangeTimezoneName", "regularMarketPrice", "regularMarketTime", "currentTradingPeriod")
        record_data("yahoo_prices_and_events", source="yahoo_chart", symbol=symbol,
                    columns=["timestamp_utc_seconds", "provider_close_split_adjusted",
                             "provider_adjusted_close"], rows=rows,
                    events=result.get("events") or {}, metadata={k: meta[k] for k in keys if k in meta},
                    requested_event_types=["div", "split"], events_field_present="events" in result,
                    event_coverage_complete=False,
                    selected_price_basis=selected_basis,
                    last_bar_filled_from_meta=last_bar_filled_from_meta,
                    payload_sha256=_digest(result), hash_basis="canonical_decoded_json_result",
                    corporate_action_ledger_verified=False, event_payment_dates_verified=False)
    except Exception as exc:
        record_data("capture_error", source_kind="yahoo_prices_and_events", error_type=type(exc).__name__)


def record_bitso_available_books(payload: dict, *, received_at_utc=None) -> None:
    """Record a fresh response supplied by the caller; this helper makes no request."""
    if _active.get() is None:
        return
    try:
        if payload.get("success") is not True or not isinstance(payload.get("payload"), list):
            raise ValueError("invalid available_books response")
        books = payload["payload"]
        if not books or any(not isinstance(book, dict) or not isinstance(book.get("book"), str)
                            for book in books):
            raise ValueError("invalid books")
        record_data("available_books", source="bitso", endpoint=BITSO_BOOKS_URL,
                    received_at_utc=_utc(received_at_utc), books=books,
                    payload_sha256=_digest(payload), hash_basis="canonical_decoded_json_response",
                    observation_scope="presence_in_successful_current_response",
                    fresh_response_verified=True, provider_as_of_utc=None,
                    historical_listing_verified=False, account_tradability_verified=False)
    except Exception as exc:
        record_data("capture_error", source_kind="available_books", error_type=type(exc).__name__)


def _panel_evidence(frame: pd.DataFrame, expected_assets: list[str]) -> dict:
    csv = frame.to_csv(index_label="date", date_format="%Y-%m-%d", float_format="%.17g")
    coverage = {}
    for asset in expected_assets:
        values = frame[asset].dropna() if asset in frame else pd.Series(dtype=float)
        coverage[asset] = {"observations": len(values),
            "missing_rows": len(frame) - len(values),
            "first_date": values.index.min().date().isoformat() if len(values) else None,
            "last_date": values.index.max().date().isoformat() if len(values) else None,
            "nonpositive_or_nonfinite": sum(not math.isfinite(float(v)) or float(v) <= 0 for v in values)}
    return {"format": "csv_utf8_daily_dates_float17g", "csv": csv,
            "sha256": hashlib.sha256(csv.encode()).hexdigest(), "rows": len(frame),
            "assets": list(frame.columns), "dtypes": {str(k): str(v) for k, v in frame.dtypes.items()},
            "coverage": coverage,
            "missing_assets": [a for a in expected_assets if a not in frame],
            "continuous_market_history_verified": False}


def _panel_sources(records: list[dict], assets: list[str]) -> dict:
    sources = {asset: {"status": "not_captured", "source": None} for asset in assets}
    for record in records:
        if record["kind"] == "crypto_prices":
            asset = record["symbol"].split("/", 1)[0]
            basis = record["price_basis"]
        elif record["kind"] == "yahoo_prices_and_events":
            asset = record["symbol"]
            basis = record["selected_price_basis"]
        else:
            continue
        if asset in sources:
            sources[asset] = {"status": "observed", "source": record["source"], "price_basis": basis,
                             "observed_at_utc": record["observed_at_utc"],
                             "captured_at_utc": record.get("captured_at_utc")}
    return sources


def collect_market_observation(cfg: dict, *, now=None) -> dict:
    """Capture public data plus a frozen-input signal replay, including non-trading days.

    No broker/state/order construction. One explicit public available_books
    request; fetch_prices may also load its usual exchange metadata. The replay
    calls the same signal function on original and restored inputs: it proves
    reproducibility only, not independent strategy or execution equivalence.
    """
    import requests
    from .bot import compute_targets, fetch_prices, latest_closed_candle

    stamp = pd.Timestamp(_utc(now))
    panels, signals, errors = {}, {}, []
    with market_observation(observed_at_utc=stamp) as observation:
        try:
            response = requests.get(BITSO_BOOKS_URL, timeout=20, allow_redirects=False)
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("unexpected available_books status")
            record_bitso_available_books(response.json(), received_at_utc=datetime.now(timezone.utc))
        except Exception as exc:
            record_provider_error("bitso_available_books", "*", exc)
        for name, sc in cfg.get("sleeves", {}).items():
            if not sc.get("enabled"):
                continue
            notes = []
            try:
                first_record = len(observation.records)
                frame = fetch_prices(name, sc, stamp, notes)
                panel = _panel_evidence(frame, list(sc["universe"]))
                panel["sources"] = _panel_sources(observation.records[first_record:], list(sc["universe"]))
                cutoff = latest_closed_candle(sc, stamp.tz_localize(None)).date().isoformat()
                panel["expected_latest_candle_from_runtime"] = cutoff
                panel["exchange_holiday_calendar_verified"] = False
                panel["latest_candle_unconfirmed_assets"] = [
                    asset for asset, row in panel["coverage"].items() if row["last_date"] != cutoff]
                panels[name] = panel
                if any(source["status"] != "observed" for source in panel["sources"].values()):
                    errors.append({"sleeve": name, "kind": "source_evidence_missing"})
                if notes or panel["missing_assets"] or any(
                        not row["observations"] or row["nonpositive_or_nonfinite"]
                        for row in panel["coverage"].values()):
                    errors.append({"sleeve": name, "kind": "incomplete_price_coverage",
                                   "provider_notes_count": len(notes)})
                if panel["latest_candle_unconfirmed_assets"]:
                    errors.append({"sleeve": name, "kind": "latest_candle_unconfirmed",
                                   "possible_exchange_holiday": sc["data"]["source"] != "ccxt"})
                restored = pd.read_csv(io.StringIO(panel["csv"]), index_col=0, parse_dates=True,
                                       float_precision="round_trip", dtype=panel["dtypes"])
                first, first_table = compute_targets(sc, frame.copy(deep=True))
                second, second_table = compute_targets(sc, restored.copy(deep=True))
                same_input = frame.equals(restored)
                same_signal = first.equals(second) and first_table.equals(second_table)
                valid_signal = (len(first) > 0 and all(math.isfinite(float(v)) and float(v) >= -1e-12 for v in first)
                                and float(first.sum()) <= 1. + 1e-9)
                signals[name] = {"method": "frozen_input_signal_replay",
                    "input_sha256": panel["sha256"], "input_roundtrip_equal": same_input,
                    "targets_and_diagnostics_equal": same_signal,
                    "signal_values_valid": bool(valid_signal),
                    "passed": bool(same_input and same_signal and valid_signal),
                    "target_weights": _json_value(first.to_dict()),
                    "execution_equivalence_verified": False, "independent_implementation": False}
                if not signals[name]["passed"]:
                    errors.append({"sleeve": name, "kind": "signal_replay_mismatch"})
            except Exception as exc:
                errors.append({"sleeve": name, "kind": "observation_failed", "error_type": type(exc).__name__})
        errors.extend({"kind": record["kind"], "source": record.get("source", record.get("source_kind")),
                       "symbol": record.get("symbol"), "error_type": record["error_type"]}
                      for record in observation.records if record["kind"] in {"provider_error", "capture_error"})
    payload = {"schema_version": SCHEMA_VERSION, "observed_at_utc": observation.observed_at_utc,
               "status": "error" if not panels else "partial" if errors else "ok",
               "records": observation.records, "records_digest": observation.digest,
               "panels": panels, "signal_replay": signals, "errors": errors,
               "historical_listing_verified": False, "execution_equivalence_verified": False,
               "corporate_action_ledger_verified": False, "live_authorized": False}
    payload["digest"] = _digest(payload)
    return payload
