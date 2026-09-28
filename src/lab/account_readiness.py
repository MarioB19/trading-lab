"""Read account connectivity without trading or changing local state.

Only fixed GET endpoints are available. Default is offline; --connect explicitly
queries the selected account environment. Credentials use a separate audit prefix,
never dotenv or the operational broker variables. No order endpoint is queried.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
import re
import secrets
import time

import requests

ENDPOINTS = {
    ("alpaca", "paper"): ("https://paper-api.alpaca.markets", {"account": "/v2/account", "positions": "/v2/positions"}),
    ("alpaca", "real"): ("https://api.alpaca.markets", {"account": "/v2/account", "positions": "/v2/positions"}),
    ("bitso", "real"): ("https://bitso.com", {"account": "/api/v3/account_status/", "balances": "/api/v3/balance/"}),
}
CREDENTIALS = {
    "alpaca": ("TRADING_AUDIT_ALPACA_KEY_ID", "TRADING_AUDIT_ALPACA_SECRET_KEY"),
    "bitso": ("TRADING_AUDIT_BITSO_API_KEY", "TRADING_AUDIT_BITSO_API_SECRET"),
}
ALPACA_OAUTH = "TRADING_AUDIT_ALPACA_OAUTH_TOKEN"
BLOCKERS = [
    "El runtime y despliegue preparado admiten exclusivamente paper.",
    "Este diagnóstico no registra efectivo ni posiciones como propiedad del bot.",
    "No existe migración aprobada de inversiones existentes al ledger del bot.",
    "La adopción y los cambios de asignación externa requieren conciliación y migración explícitas.",
    "No se consultaron órdenes ni movimientos; conciliación, liquidación de efectivo y permisos de escritura no verificados.",
    "La operación real requiere pruebas externas, observación paper y autorización manual independiente.",
]


def bitso_nonce_v2() -> str:
    """Official Nonce v2: epoch milliseconds plus six random digits (19 digits)."""
    return f"{time.time_ns() // 1_000_000}{100000 + secrets.randbelow(900000)}"


def stable_account_key(broker_name: str, provider_id) -> str:
    """Opaque account identity, stable across API-key rotation; never hash the key."""
    if isinstance(provider_id, bool) or not isinstance(provider_id, (str, int)):
        raise ValueError("el proveedor no devolvió un identificador de cuenta válido")
    identifier = str(provider_id).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
        raise ValueError("el proveedor no devolvió un identificador de cuenta válido")
    digest = hashlib.sha256((broker_name + ":" + identifier).encode()).hexdigest()
    return broker_name + ":account-id-v1:" + digest


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("dato numérico ausente o inválido")
    text = str(value)
    if len(text) > 80:
        raise ValueError("dato numérico demasiado largo")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("dato numérico inválido") from exc
    if (not number.is_finite() or not -30 <= number.as_tuple().exponent <= 30
            or number.copy_abs() > Decimal("1e30")):
        raise ValueError("dato numérico fuera de rango")
    return format(number, "f")


def _symbol(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9./_-]{1,25}", value):
        raise ValueError("símbolo de activo inválido")
    return value.upper()


def _boolean(value):
    return value if isinstance(value, bool) else None


def _request_json(transport, url, headers, *, bitso):
    """Transport has exactly one operation: GET. No redirects or response-body logs."""
    try:
        response = transport(url, headers=headers, timeout=20, allow_redirects=False)
    except requests.Timeout:
        return None, {"kind": "timeout"}
    except requests.RequestException:
        return None, {"kind": "network_error"}
    except Exception:
        return None, {"kind": "transport_error"}
    code = response.status_code
    if not isinstance(code, int) or code != 200:
        return None, {"kind": "http_error", "http_status": code if isinstance(code, int) else None}
    try:
        data = response.json()
        if bitso:
            if not isinstance(data, dict) or data.get("success") is not True:
                # Raw provider messages may include personal data; expose no message text.
                return None, {"kind": "provider_rejected_request"}
            data = data.get("payload")
        if data is None:
            return None, {"kind": "invalid_response_schema"}
        return data, None
    except (ValueError, TypeError):
        return None, {"kind": "invalid_json"}


def _credentials(broker, environ):
    names = CREDENTIALS[broker]
    pair = [environ.get(name, "") for name in names]
    token = environ.get(ALPACA_OAUTH, "") if broker == "alpaca" else ""
    if token and any(pair):
        return None, "ambiguous_credentials", []
    if token:
        values, method, missing = [token], "oauth_token", []
    else:
        values, method = pair, "api_key"
        missing = [name for name, value in zip(names, values) if not value]
    if missing:
        return None, "missing_credentials", missing
    if any(not isinstance(v, str) or not v.strip() or len(v) > 8192 or re.search(r"[\r\n\x00]", v) for v in values):
        return None, "invalid_credentials", []
    return values, method, []


def _alpaca(report, payloads):
    account, positions = payloads.get("account"), payloads.get("positions")
    if account is not None:
        try:
            if not isinstance(account, dict):
                raise ValueError("account schema")
            name = "alpaca paper" if report["environment"] == "paper" else "alpaca real"
            report["account"]["identity"] = {"verified": True, "source_field": "account.id",
                "key": stable_account_key(name, account.get("id"))}
            raw_status = str(account.get("status", "unknown")).upper()
            report["account"]["status"] = raw_status if raw_status in {
                "ACTIVE", "ONBOARDING", "SUBMISSION_FAILED", "SUBMITTED", "ACCOUNT_UPDATED",
                "APPROVAL_PENDING", "REJECTED", "DISABLED", "CLOSED"} else "UNKNOWN"
            report["account"]["currency"] = _symbol(account.get("currency"))
            report["account"]["cash"] = _number(account.get("cash"))
            report["account"]["flags"] = {key: _boolean(account.get(key)) for key in
                ("trading_blocked", "account_blocked", "trade_suspended_by_user", "shorting_enabled")}
            if account.get("multiplier") is not None:
                report["account"]["buying_power_multiplier"] = _number(account["multiplier"])
            if raw_status != "ACTIVE":
                report["blockers"].append("La cuenta Alpaca no declara estado ACTIVE.")
            if any(report["account"]["flags"][key] is not False for key in
                   ("trading_blocked", "account_blocked", "trade_suspended_by_user")):
                report["blockers"].append("Hay un bloqueo de cuenta/operación o falta verificar esos flags.")
            if Decimal(report["account"]["cash"]) < 0:
                report["blockers"].append("La cuenta informa efectivo negativo.")
            if report["account"]["currency"] != "USD":
                report["blockers"].append("La moneda de la cuenta no coincide con la contabilidad USD.")
            if account.get("multiplier") is None or Decimal(str(account["multiplier"])) > 1:
                report["blockers"].append("Uso exclusivo de efectivo sin margen no acreditado; buying_power no es capital propio.")
        except (ValueError, TypeError, InvalidOperation):
            report["errors"].append({"endpoint": "account", "kind": "invalid_account_schema"})
    if positions is not None:
        if not isinstance(positions, list):
            report["errors"].append({"endpoint": "positions", "kind": "invalid_positions_schema"})
            return
        report["holdings"]["response_count"] = len(positions)
        for row in positions:
            try:
                symbol, qty = _symbol(row["symbol"]), _number(row["qty"])
                if Decimal(qty) == 0:
                    continue
                item = {"asset": symbol, "quantity": qty, "owned_by_bot": False}
                for field in ("qty_available", "market_value"):
                    if row.get(field) is not None:
                        item[field] = _number(row[field])
                report["holdings"]["items"].append(item)
                if Decimal(qty) < 0:
                    report["blockers"].append("Existen posiciones cortas: incompatibles con el alcance del bot.")
            except (ValueError, TypeError, KeyError):
                report["errors"].append({"endpoint": "positions", "kind": "invalid_position_row"})


def _bitso(report, payloads):
    account, balances = payloads.get("account"), payloads.get("balances")
    if account is not None:
        try:
            if not isinstance(account, dict):
                raise ValueError("account schema")
            report["account"]["identity"] = {"verified": True, "source_field": "account_status.client_id",
                "key": stable_account_key("bitso real", account.get("client_id"))}
            status = account.get("status")
            report["account"]["status"] = status if status in ("active", "inactive") else "unknown"
            currency = account.get("preferred_currency") or account.get("user_default_fiat_currency")
            report["account"]["display_currency"] = _symbol(currency) if currency is not None else None
            report["account"]["currency"] = "multi_currency"
            if status != "active":
                report["blockers"].append("La cuenta Bitso no declara estado active.")
        except (ValueError, TypeError):
            report["errors"].append({"endpoint": "account", "kind": "invalid_account_schema"})
    if balances is not None:
        if not isinstance(balances, dict) or not isinstance(balances.get("balances"), list):
            report["errors"].append({"endpoint": "balances", "kind": "invalid_balances_schema"})
            return
        report["holdings"]["response_count"] = len(balances["balances"])
        usd = None
        for row in balances["balances"]:
            try:
                currency = _symbol(row["currency"])
                total, free, locked = (_number(row[key]) for key in ("total", "available", "locked"))
                if any(Decimal(n) < 0 for n in (total, free, locked)):
                    raise ValueError("negative balance")
                if abs(Decimal(total) - Decimal(free) - Decimal(locked)) > Decimal("0.00000001"):
                    raise ValueError("inconsistent balance")
                if currency == "USD":
                    usd = free
                if Decimal(total) != 0:
                    report["holdings"]["items"].append({"asset": currency, "total": total,
                        "available": free, "locked": locked, "owned_by_bot": False})
            except (ValueError, TypeError, KeyError):
                report["errors"].append({"endpoint": "balances", "kind": "invalid_balance_row"})
        report["account"]["available_usd"] = usd
        if usd is None or Decimal(usd) <= 0:
            report["blockers"].append("No hay saldo USD disponible verificado; MXN, USDC y otros saldos no se convierten ni se equiparan automáticamente.")
    report["blockers"].append("Bitso: una orden enviada sin ID remoto requiere conciliación manual; no reenviar a ciegas.")


def inspect_account(broker: str, environment: str, *, connect: bool = False,
                    environ=None, transport=None) -> dict:
    """Return a sanitized, non-mutating preflight. Never calls bot/runtime/storage."""
    if broker not in CREDENTIALS or environment not in ("paper", "real"):
        raise ValueError("broker/entorno de consulta desconocido")
    report = {"schema_version": 1, "broker": broker, "environment": environment,
        "generated_at": datetime.now(timezone.utc).isoformat(), "status": "not_connected",
        "authentication": {"verified": False}, "account": {"identity": {"verified": False}, "status": "unknown"},
        "holdings": {"response_count": None, "nonzero_count": 0, "items": [],
                     "ownership": "external_observed_only", "adopted_by_bot": False},
        "capabilities": {"scope": "this_diagnostic_only", "account_read": False, "holdings_read": False,
                         "credential_read_only_verified": False, "order_permissions": "not_tested",
                         "orders_queried": False, "can_send_orders": False, "can_transfer": False,
                         "can_adopt_holdings": False},
        "required_credentials": list(CREDENTIALS[broker]), "missing_credentials": [],
        "requests": [], "errors": [], "blockers": list(BLOCKERS),
        "read_only_connection_ready": False, "ready_for_trading": False, "live_authorized": False}
    endpoint = ENDPOINTS.get((broker, environment))
    if endpoint is None:
        report.update(status="unsupported_environment")
        report["blockers"].append("Bitso paper usa simulación interna/libro público; este diagnóstico no incorpora sandbox privado.")
        return report
    base, paths = endpoint
    report["endpoint"] = base
    report["allowed_get_paths"] = list(paths.values())
    env = os.environ if environ is None else environ
    credentials, method, missing = _credentials(broker, env)
    report["missing_credentials"] = missing
    report["authentication"]["method"] = method
    report["authentication"]["credentials_present"] = credentials is not None
    if broker == "alpaca":
        report["alternative_read_credentials"] = ALPACA_OAUTH
    if not connect:
        return report
    if credentials is None:
        report["status"] = method
        return report
    session = None
    if transport is None:
        session = requests.Session()
        session.trust_env = False  # no implicit .netrc credentials or environment proxies
        transport = session.get
    payloads = {}
    try:
        for label, path in paths.items():
            headers = {"Accept": "application/json"}
            if broker == "alpaca":
                headers.update({"Authorization": "Bearer " + credentials[0]} if method == "oauth_token" else
                               {"APCA-API-KEY-ID": credentials[0], "APCA-API-SECRET-KEY": credentials[1]})
            else:
                nonce = bitso_nonce_v2()
                signature = hmac.new(credentials[1].encode(), (nonce + "GET" + path).encode(), hashlib.sha256).hexdigest()
                headers["Authorization"] = f"Bitso {credentials[0]}:{nonce}:{signature}"
            data, error = _request_json(transport, base + path, headers, bitso=broker == "bitso")
            report["requests"].append({"method": "GET", "path": path, "ok": error is None})
            if error:
                report["errors"].append({"endpoint": label, **error})
            else:
                report["authentication"]["verified"] = True
                payloads[label] = data
            # No automatic retry or repeated private calls after denied access/rate limits.
            if error and error.get("http_status") in (401, 429):
                break
    finally:
        if session is not None:
            session.close()
    (_alpaca if broker == "alpaca" else _bitso)(report, payloads)
    invalid = {error["endpoint"] for error in report["errors"]}
    report["capabilities"]["account_read"] = "account" in payloads and "account" not in invalid
    holdings_label = "positions" if broker == "alpaca" else "balances"
    report["capabilities"]["holdings_read"] = holdings_label in payloads and holdings_label not in invalid
    report["holdings"]["nonzero_count"] = len(report["holdings"]["items"])
    if report["holdings"]["nonzero_count"]:
        report["blockers"].append("La cuenta contiene patrimonio existente: observado, sin asignación ni permiso de venta por el bot.")
    if not report["account"]["identity"]["verified"]:
        report["blockers"].append("No se pudo verificar un ID estable del proveedor; no usar una huella de API key como identidad de cuenta.")
    complete = (not report["errors"] and report["account"]["identity"]["verified"]
                and report["capabilities"]["account_read"] and report["capabilities"]["holdings_read"])
    report["read_only_connection_ready"] = complete
    report["status"] = "connected_read_only" if complete else "partial_or_failed_connection"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", required=True, choices=("alpaca", "bitso"))
    parser.add_argument("--environment", required=True, choices=("paper", "real"),
                        help="entorno que se consulta; no cambia el modo del bot")
    parser.add_argument("--connect", action="store_true", help="ejecuta únicamente las consultas GET permitidas")
    args = parser.parse_args(argv)
    report = inspect_account(args.broker, args.environment, connect=args.connect)
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return 0 if report["status"] == "not_connected" or report["read_only_connection_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
