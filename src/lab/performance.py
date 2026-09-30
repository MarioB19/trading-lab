"""Read-only accounting of paper gains; contributions are never investment returns."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math


def _number(value, *, nonnegative=False):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and (not nonnegative or result >= 0) else None


def _money(value):
    return round(value, 2) if value is not None else None


def _total(values):
    values = list(values)
    return sum(values) if values and all(value is not None for value in values) else None


def _mxn(value, rate):
    return value * rate if value is not None and rate is not None else None


def _rate(value):
    value = _number(value)
    return value if value is not None and value > 0 else None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace(" UTC", "+00:00").replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except ValueError:
        return None


def _observed(document, sleeve):
    return sleeve.get("updated_utc") or sleeve.get("last_run_utc") or document.get("updated_utc") or document.get("generated_utc")


def _missing_session(name, previous, current):
    day = previous + timedelta(days=1)
    while day < current:
        if name != "stocks" or day.weekday() < 5:
            return True
        day += timedelta(days=1)
    return False


def build_performance(state, snapshot, live, equity_rows, config):
    """Calculate a single captured SQLite snapshot without fetching or changing data.

    Daily MXN is the USD profit converted at that row's historical FX, not an FX
    investment return. Blank legacy flow cells mean no recorded contribution.
    Missing market sessions are not silently replaced with zero returns.
    Historical balance/capital MXN use each block's own closing FX. A carried
    stock balance retains that closing FX and its date, not another block's FX.
    The capital line is inferred from the initial base plus recorded flows; an
    absent expected close makes subsequent capital history unconfirmed.
    """
    state, snapshot, live, config = map(_mapping, (state, snapshot, live, config))
    states = _mapping(state.get("sleeves"))
    configured = _mapping(config.get("sleeves"))
    names = sorted(set(states) | {name for name, item in configured.items()
                                 if isinstance(item, dict) and item.get("enabled", True)})
    notes = ["Simulado: las ganancias incluyen posiciones abiertas y no son ingresos realizados.",
             "MXN convierte el resultado en USD al tipo de cambio indicado; no mide rendimiento cambiario."]
    records = {name: {} for name in names}
    history_invalid = set()
    for raw in equity_rows:
        row = _mapping(raw)
        name = row.get("sleeve")
        if name not in records:
            notes.append("Hay un bloque histórico sin estado/configuración; el total no está conciliado.")
            history_invalid.update(names)
            continue
        try:
            day = date.fromisoformat(row.get("date", ""))
        except (TypeError, ValueError):
            history_invalid.add(name)
            notes.append(f"{name}: fecha histórica inválida; base inicial no inferible.")
            continue
        flow = 0.0 if row.get("flow") in (None, "") else _number(row.get("flow"))
        item = {"date": day, "equity": _number(row.get("equity"), nonnegative=True),
                "flow": flow, "fx": _rate(row.get("usd_mxn")), "invalid": False}
        if row.get("mode", "paper") != "paper":
            item.update(equity=None, flow=None, invalid=True)
        if day in records[name]:
            item.update(equity=None, flow=None, invalid=True)
            notes.append(f"{name}: cierre duplicado {day}; no se elige arbitrariamente uno.")
        records[name][day] = item
        if item["flow"] is None:
            history_invalid.add(name)

    capital = {}
    initials = {}
    for name in names:
        st, target = _mapping(states.get(name)), _mapping(configured.get(name))
        applied = _number(st.get("capital_base"), nonnegative=True)
        if st.get("mode") != "paper":
            applied = None
            notes.append(f"{name}: falta una base aplicada en modo paper verificable.")
        wanted = _number(target.get("capital"), nonnegative=True) if target.get("enabled", True) else None
        flows = _total(row["flow"] for row in records[name].values()) if records[name] else None
        initial = applied - flows if applied is not None and flows is not None and name not in history_invalid else None
        if initial is not None and initial < 0:
            initial = None
        initials[name] = initial
        capital[name] = {"target_usd": _money(wanted), "applied_usd": _money(applied),
                         "pending_flow_usd": _money(wanted - applied) if wanted is not None and applied is not None else None,
                         "initial_usd": _money(initial), "initial_inferred": initial is not None}

    fx_doc = live if live else snapshot
    fx_raw = _mapping(fx_doc.get("fx"))
    fx = {"rate": _rate(fx_raw.get("rate")), "source": fx_raw.get("source"), "time_utc": fx_raw.get("time_utc")}
    if fx["rate"] is None:
        notes.append("Tipo de cambio actual no disponible; se conservan los importes conocidos en USD.")

    current, progress = {}, {}
    observations = []
    for name in names:
        doc, source = live, "live"
        item = _mapping(_mapping(live.get("sleeves")).get(name))
        fallback = _mapping(_mapping(snapshot.get("sleeves")).get(name))
        live_time, snapshot_time = _time(_observed(live, item)), _time(_observed(snapshot, fallback))
        if not item or (live_time is not None and snapshot_time is not None and live_time < snapshot_time):
            doc, item, source = snapshot, fallback, "snapshot"
        observed = _observed(doc, item)
        as_of = item.get("prices_as_of_utc") or observed
        equity = _number(item.get("equity"), nonnegative=True)
        if (doc.get("mode") != "paper" or item.get("mode", "paper") != "paper"
                or item.get("status") not in {"ok", "skip"}):
            equity = None
        base = capital[name]["applied_usd"]
        pnl = equity - base if equity is not None and base is not None else None
        if equity is None:
            notes.append(f"{name}: valoración actual ausente o inválida; no se presenta un total parcial como completo.")
        if observed and _time(observed) is not None:
            observations.append(observed)
        current[name] = {"equity_usd": _money(equity), "pnl_usd": _money(pnl),
                         "pnl_mxn": _money(_mxn(pnl, fx["rate"])), "as_of_utc": as_of,
                         "source": source, "close_date": item.get("candle")}
        last = records[name][max(records[name])] if records[name] else None
        delta = equity - last["equity"] if equity is not None and last and last["equity"] is not None else None
        price_time = _time(as_of)
        if last and price_time is not None and price_time.date() < last["date"]:
            delta = None
        progress[name] = {"pnl_usd": _money(delta), "pnl_mxn": _money(_mxn(delta, fx["rate"])),
                          "as_of_utc": as_of, "last_close_date": last["date"].isoformat() if last else None}

    all_dates = sorted({day for rows in records.values() for day in rows})
    daily, previous = [], {}
    historical_capital = dict(initials)
    if all_dates:
        day = all_dates[0]
        while day <= all_dates[-1]:
            sleeves, day_notes = {}, []
            raw_totals = {key: [] for key in ("pnl_usd", "pnl_mxn", "flow_usd", "equity_usd",
                                             "equity_mxn", "capital_usd", "capital_mxn")}
            rates = {rows[day]["fx"] for rows in records.values() if day in rows and rows[day]["fx"] is not None}
            day_rate = next(iter(rates)) if len(rates) == 1 else None
            for name in names:
                row, prev = records[name].get(day), previous.get(name)
                pnl = interval = equity = flow = None
                day_capital = equity_fx = equity_fx_date = None
                span, carried, reliable = None, False, False
                sleeve_notes = []
                if row is not None:
                    equity, flow = row["equity"], row["flow"]
                    base = prev["equity"] if prev is not None else initials[name]
                    interval = equity - base - flow if equity is not None and base is not None and flow is not None else None
                    span = (day - prev["date"]).days if prev else None
                    reliable = interval is not None and (prev is None or not _missing_session(name, prev["date"], day))
                    pnl = interval if reliable else None
                    if prev is None:
                        sleeve_notes.append("Base inicial reconstruida del capital y los movimientos registrados; depende de la integridad del historial.")
                    elif not reliable and interval is not None:
                        sleeve_notes.append(f"Hueco de sesiones: variación de {span} días; no atribuible a un solo día.")
                    if equity is None or flow is None:
                        sleeve_notes.append("Cierre o flujo inválido; resultado diario no disponible.")
                    row_fx = row["fx"]
                    equity_fx, equity_fx_date = row_fx, day.isoformat()
                    prior_capital = historical_capital[name]
                    day_capital = (_number(prior_capital + flow, nonnegative=True)
                                   if prior_capital is not None and flow is not None else None)
                    historical_capital[name] = day_capital
                    pnl_mxn = _mxn(pnl, row_fx)
                    if row_fx is None:
                        sleeve_notes.append("Sin tipo de cambio histórico; ganancia en pesos no disponible.")
                    previous[name] = row
                elif prev is not None and name == "stocks" and day.weekday() >= 5:
                    equity, flow, pnl, pnl_mxn = prev["equity"], 0.0, 0.0, 0.0
                    carried, row_fx = True, None
                    equity_fx, equity_fx_date = prev["fx"], prev["date"].isoformat()
                    day_capital = historical_capital[name]
                    reliable = prev["equity"] is not None and not _missing_session(name, prev["date"], day)
                    sleeve_notes.append("Sin nuevo cierre: se arrastra la valoración; contribución de este bloque al cambio diario = 0.")
                    if not reliable:
                        pnl = pnl_mxn = None
                        sleeve_notes = ["Se conserva la última valoración, pero falta un cierre hábil previo; ganancia diaria no disponible."]
                else:
                    row_fx, pnl_mxn = None, None
                    sleeve_notes.append("Sin cierre para este día; no se presume una ganancia de cero.")
                    if prev is not None:
                        # A missing expected row could contain a capital flow. Do not
                        # carry an apparently certain capital baseline past this gap.
                        historical_capital[name] = None
                equity_mxn, capital_mxn = _mxn(equity, equity_fx), _mxn(day_capital, equity_fx)
                if day_capital is None:
                    sleeve_notes.append("Capital histórico no confirmado por datos incompletos.")
                sleeves[name] = {"pnl_usd": _money(pnl), "pnl_mxn": _money(pnl_mxn),
                                 "flow_usd": _money(flow), "equity_usd": _money(equity),
                                 "equity_mxn": _money(equity_mxn), "capital_usd": _money(day_capital),
                                 "capital_mxn": _money(capital_mxn), "equity_fx_rate": equity_fx,
                                 "equity_fx_date": equity_fx_date,
                                 "fx_rate": row_fx, "has_close": row is not None, "carried": carried,
                                 "reliable": reliable, "span_days": span,
                                 "interval_pnl_usd": _money(interval), "notes": sleeve_notes}
                for key, value in zip(raw_totals, (pnl, pnl_mxn, flow, equity,
                                                  equity_mxn, day_capital, capital_mxn)):
                    raw_totals[key].append(value)
                day_notes.extend(f"{name}: {note}" for note in sleeve_notes)
            if len(rates) > 1:
                day_notes.append("Los bloques registran tipos de cambio distintos; MXN suma cada conversión histórica.")
            daily.append({"date": day.isoformat(),
                          **{key: _money(_total(values)) for key, values in raw_totals.items()},
                          "fx_rate": day_rate, "by_sleeve": sleeves, "notes": day_notes})
            day += timedelta(days=1)
    else:
        notes.append("No hay cierres diarios: no se calcula una ganancia diaria ni progreso desde el cierre.")
    observed = max(observations, key=_time) if observations else None
    if len({s["as_of_utc"] for s in current.values()}) > 1:
        notes.append("Las valoraciones tienen fechas distintas; consulta el corte de cada bloque.")
    return {"fx": fx, "capital": {
                **{key: _money(_total(s[key] for s in capital.values()))
                   for key in ("target_usd", "applied_usd", "pending_flow_usd")}, "by_sleeve": capital},
            "current": {"equity_usd": _money(_total(s["equity_usd"] for s in current.values())),
                        "pnl_usd": _money(_total(s["pnl_usd"] for s in current.values())),
                        "pnl_mxn": _money(_mxn(_total(s["pnl_usd"] for s in current.values()), fx["rate"])),
                        "as_of_utc": observed, "by_sleeve": current},
            "daily": daily,
            "in_progress": {"pnl_usd": _money(_total(s["pnl_usd"] for s in progress.values())),
                            "pnl_mxn": _money(_mxn(_total(s["pnl_usd"] for s in progress.values()), fx["rate"])),
                            "as_of_utc": observed, "by_sleeve": progress}, "notes": notes}
