"""Estrategia de PORTAFOLIO multi-activo (criptos o acciones/ETF).

Cada día, al cierre, para cada activo del universo:
  1. Tendencia: fracción de 4 promedios móviles (20/50/100/200) que el precio supera (0 a 1).
  2. Momentum ajustado por riesgo: promedio de rendimientos a 1, 3 y 6 meses dividido
     entre su volatilidad.
  3. Solo son candidatos los activos con tendencia >= 0.5 y momentum > 0.
     Se eligen los `top_k` de mayor momentum.
  4. Peso proporcional a tendencia / volatilidad (paridad de riesgo: un activo el doble de
     volátil recibe la mitad de dinero), con tope por activo.
  5. Filtro de régimen (cripto): si BTC no está en tendencia, no se compran altcoins.
  6. Volatilidad objetivo: con la matriz de covarianzas reciente se escala el portafolio
     para que su volatilidad anual esperada no pase de `vol_target`. El resto queda en efectivo.
  7. Freno por caída (en la simulación y en el bot): si el portafolio cae más de 10% desde su
     máximo de los últimos 6 meses, la exposición baja gradualmente hasta 25% a -30%.

Todo usa solo información hasta el cierre del día; el motor aplica los pesos al día siguiente.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


@dataclass
class PortfolioParams:
    top_k: int = 5
    vol_target: float | None = 0.40
    regime_asset: str | None = "BTC"
    dd_brake: bool = True
    max_weight: float = 0.40
    lookbacks: tuple = (20, 50, 100, 200)
    mom_windows: tuple = (30, 90, 180)
    vol_halflife: int = 20
    cov_window: int = 90
    min_trend: float = 0.5
    ann: int = 365
    dd_start: float = 0.10
    dd_full: float = 0.30
    dd_floor: float = 0.25
    dd_peak_window: int = 180
    cash_asset: str | None = None   # p. ej. "BIL": el efectivo no usado se estaciona en bonos del Tesoro
    rebalance: str = "daily"        # "monthly": solo se rebalancea el primer día hábil de cada mes
    cov_estimator: str = "sample"  # alternativa de investigación, opt-in: "ledoit_wolf"
    rotation_buffer: float = 0.0  # investigación: ventaja relativa necesaria para sustituir un activo

    def __post_init__(self):
        if not np.isfinite(self.rotation_buffer) or not 0 <= self.rotation_buffer < 1:
            raise ValueError("rotation_buffer debe estar entre 0 y 1 (exclusivo)")

    @classmethod
    def from_dict(cls, d: dict | None) -> "PortfolioParams":
        d = dict(d or {})
        for k in ("lookbacks", "mom_windows"):
            if k in d:
                d[k] = tuple(d[k])
        return cls(**d)

    def to_dict(self) -> dict:
        result = asdict(self)
        # Preserve the identity of frozen control/archived plans. Missing means 0.
        if self.rotation_buffer == 0:
            result.pop("rotation_buffer")
        return result


# ------------------------------------------------------------------ señales por activo
def clean(prices: pd.DataFrame) -> pd.DataFrame:
    """Precios <= 0 se tratan como faltantes; un hueco de hasta 5 días usa el último precio.

    Sin esto, un solo dato faltante borra el promedio de 200 días durante 200 días
    y pierde el rendimiento del día del hueco.
    """
    return prices.where(prices > 0).ffill(limit=5)


def signals(prices: pd.DataFrame, p: PortfolioParams) -> dict[str, pd.DataFrame]:
    prices = clean(prices)
    trend = sum((prices > prices.rolling(n, min_periods=n).mean()).astype(float)
                .where(prices.rolling(n, min_periods=n).mean().notna())
                for n in p.lookbacks) / len(p.lookbacks)
    logret = np.log(prices).diff()
    vol = logret.ewm(halflife=p.vol_halflife, min_periods=60).std() * np.sqrt(p.ann)
    mom = sum(prices.pct_change(w, fill_method=None) for w in p.mom_windows) / len(p.mom_windows)
    score = mom / vol
    return {"trend": trend, "vol": vol, "mom": mom, "score": score}


def cap_weights(w: np.ndarray, cap: float) -> np.ndarray:
    """Recorta pesos al tope y reparte el excedente entre los demás (si caben)."""
    w = w.copy()
    for _ in range(len(w) + 1):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        free = ~over & (w < cap - 1e-12)
        if not free.any():
            break
        w[free] += excess * w[free] / w[free].sum()
    return w


def select_ranked(score, eligible, previous, top_k, buffer=0.0):
    """Retain eligible incumbents unless a challenger exceeds their score by buffer.

    Eligibility and regime filters are applied before this function. The buffer
    never protects an asset that has lost its trend, positive momentum or listing.
    """
    ranked = np.flatnonzero(eligible)
    ranked = ranked[np.argsort(-score[ranked], kind="stable")]
    if buffer == 0:
        return ranked[:top_k]
    selected = [int(i) for i in previous if eligible[i]][:top_k]
    for challenger in ranked:
        if challenger in selected:
            continue
        if len(selected) < top_k:
            selected.append(int(challenger))
            continue
        weakest = min(selected, key=lambda i: (score[i], -i))
        if score[challenger] > score[weakest] * (1 + buffer):
            selected[selected.index(weakest)] = int(challenger)
    return np.array(sorted(selected, key=lambda i: (-score[i], i)), dtype=int)


def target_weights(prices: pd.DataFrame, eligible: pd.DataFrame | None,
                   p: PortfolioParams, return_signals: bool = False, last_only: bool = False):
    """Pesos objetivo por fecha (antes del freno por caída, que depende del capital).

    last_only=True calcula solo la última fila para la regla sin memoria. Con margen de
    sustitución reconstruye las decisiones previas; el último objetivo coincide con el
    cálculo completo. Tampoco se abrevia el rebalanceo mensual.
    """
    prices = clean(prices)
    sig = signals(prices, p)
    cols = list(prices.columns)
    elig = (eligible.reindex_like(prices).fillna(False).astype(bool).values
            if eligible is not None else np.ones(prices.shape, bool))
    trend, vol, score = sig["trend"].values, sig["vol"].values, sig["score"].values
    rets = np.log(prices).diff().values
    has_regime = p.regime_asset is not None and p.regime_asset in cols
    ci = cols.index(p.cash_asset) if p.cash_asset and p.cash_asset in cols else -1
    cash_ok = np.isfinite(clean(prices).values[:, ci]) if ci >= 0 else None
    ri = cols.index(p.regime_asset) if has_regime else -1
    W = np.zeros(prices.shape)
    # A stateful selector must replay prior decisions even for a last-row query.
    only_last = last_only and p.rebalance != "monthly" and p.rotation_buffer == 0
    previous = np.array([], dtype=int)
    for t in (range(len(prices) - 1, len(prices)) if only_last else range(len(prices))):
        tr, vo, sc = trend[t], vol[t], score[t]
        ok = elig[t] & (tr >= p.min_trend) & (sc > 0) & np.isfinite(vo) & (vo > 0) & np.isfinite(sc)
        if ci >= 0:
            ok[ci] = False  # el activo de efectivo nunca compite por tendencia
        if has_regime and not (np.isfinite(tr[ri]) and tr[ri] >= p.min_trend):
            mask = np.zeros(len(cols), bool)
            mask[ri] = True
            ok &= mask
        idx = select_ranked(sc, ok, previous, p.top_k, p.rotation_buffer)
        previous = idx
        if not len(idx):
            continue
        raw = tr[idx] / vo[idx]
        w = cap_weights(raw / raw.sum(), p.max_weight)
        if p.vol_target:
            window = rets[max(1, t - p.cov_window + 1): t + 1][:, idx]
            window = window[np.isfinite(window).all(axis=1)]
            if len(window) >= 30:
                if p.cov_estimator == "ledoit_wolf":
                    from sklearn.covariance import LedoitWolf

                    cov = LedoitWolf().fit(window).covariance_ * p.ann
                elif p.cov_estimator == "sample":
                    cov = np.cov(window, rowvar=False) * p.ann
                else:
                    raise ValueError(f"estimador de covarianza desconocido: {p.cov_estimator}")
                cov = np.atleast_2d(cov)
                sp = float(np.sqrt(max(w @ cov @ w, 1e-12)))
                w = w * min(1.0, p.vol_target / sp)
        W[t, idx] = w
    if ci >= 0:
        W[:, ci] = np.where(cash_ok, np.clip(1.0 - W.sum(axis=1), 0.0, 1.0), 0.0)
    out = pd.DataFrame(W, index=prices.index, columns=cols)
    if p.rebalance == "monthly":
        # la cartera se decide el primer día hábil del mes y se mantiene hasta el siguiente
        out.loc[~rebalance_days(prices.index)] = np.nan
        out = out.ffill().fillna(0.0)
    return (out, sig) if return_signals else out


def rebalance_days(index: pd.DatetimeIndex) -> np.ndarray:
    """True el primer día con datos de cada mes (se sabe sin mirar al futuro)."""
    m = np.asarray(index.month)
    out = np.zeros(len(index), bool)
    out[1:] = m[1:] != m[:-1]
    return out


def drawdown_multiplier(dd: float, p: PortfolioParams) -> float:
    """1.0 sin caída; baja linealmente de -dd_start a -dd_full hasta dd_floor."""
    if not p.dd_brake or dd > -p.dd_start:
        return 1.0
    frac = min(1.0, (-dd - p.dd_start) / (p.dd_full - p.dd_start))
    return 1.0 - frac * (1.0 - p.dd_floor)


# ------------------------------------------------------------------ simulación
def simulate_portfolio(prices: pd.DataFrame, weights: pd.DataFrame, p: PortfolioParams,
                       cost: float = 0.003, band: float = 0.02,
                       kill_dd: float | None = None, check=None, watch=None,
                       params_by_date: pd.Series | None = None) -> pd.DataFrame:
    """Backtest multi-activo con costos, banda de rebalanceo, deriva y freno por caída.

    Sirve para cualquier frecuencia de filas (diaria o por hora). La decisión tomada en la
    fila t-1 se aplica al tramo que termina en t.
      check: filas en las que el bot revisa y rebalancea (por omisión, todas). En las demás
             los pesos solo derivan con el precio.
      watch: filas en las que un vigía revisa sin rebalancear: recalcula el freno y el kill
             switch con el capital de ese momento y, si se aprietan, solo vende.
    El freno y el kill switch miden la caída con el capital observado en esas revisiones;
    `p.dd_peak_window` va en filas.
    params_by_date: parámetros conocidos al cierre de cada fila, con exactamente el
    mismo índice. Cambiar de variante NO reinicia cartera, capital, pico ni kill switch.
    La decisión y sus parámetros de t-1 se aplican al retorno de t.
    """
    R = clean(prices).pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0.0).values
    cols = list(prices.columns)
    clean_values = clean(prices).values
    Wt = weights.reindex_like(prices).fillna(0.0).values
    n, m = R.shape
    if n == 0:
        raise ValueError("la simulación necesita precios")
    if params_by_date is not None:
        if not params_by_date.index.equals(prices.index):
            raise ValueError("params_by_date debe tener exactamente el índice de precios")
        if not all(isinstance(x, PortfolioParams) for x in params_by_date):
            raise ValueError("faltan parámetros válidos por fecha")
        schedule = params_by_date.tolist()
    else:
        schedule = [p] * n
    chk = np.ones(n, bool) if check is None else np.asarray(check, bool)
    wat = np.zeros(n, bool) if watch is None else np.asarray(watch, bool) & ~chk
    w = np.zeros(m)
    eq_obs = np.full(n, np.nan)   # capital observado en cada revisión
    eq_obs[0] = 1.0
    out_ret, gross, turn, mult_arr = np.zeros(n), np.zeros(n), np.zeros(n), np.ones(n)
    held = np.zeros((n, m))
    equity, killed, all_peak = 1.0, False, 1.0
    rdays = rebalance_days(prices.index)
    prev_mult, mult = 1.0, 1.0
    last_target = np.zeros(m)
    no_trade = np.zeros(m, bool)
    for t in range(1, n):
        active = schedule[t - 1]
        changed = t > 1 and active != schedule[t - 2]
        monthly = active.rebalance == "monthly"
        ci = cols.index(active.cash_asset) if active.cash_asset in cols else -1
        trade, diff = no_trade, np.zeros(m)
        if chk[t - 1] or wat[t - 1]:
            eq_obs[t - 1] = equity
            all_peak = max(all_peak, equity)
            lo = max(0, t - active.dd_peak_window)
            peak = np.nanmax(eq_obs[lo:t])
            dd = equity / peak - 1
            if kill_dd is not None and equity / all_peak - 1 <= -kill_dd:
                killed = True
            new_mult = 0.0 if killed else drawdown_multiplier(dd, active)
            if chk[t - 1]:
                mult = new_mult
                last_target = Wt[t - 1]
                desired = last_target * mult
                if ci >= 0 and not killed and np.isfinite(clean_values[t - 1, ci]):
                    # el freno reduce solo lo riesgoso; lo liberado se estaciona en el activo de efectivo
                    desired[ci] = max(0.0, 1.0 - (desired.sum() - desired[ci]))
                diff = desired - w
                trade = (np.abs(diff) > band) | ((desired == 0) & (w > 0))
                if monthly and not (rdays[t - 1] or changed or killed or mult != prev_mult or w.sum() == 0):
                    trade = no_trade  # fuera del día de rebalanceo solo actúan el freno y el kill switch
                prev_mult = mult
            elif new_mult < mult - 1e-12:
                # vigía: el freno se apretó (o se activó el kill switch); solo se vende
                mult = new_mult
                desired = np.minimum(w, last_target * mult)
                diff = desired - w
                trade = (np.abs(diff) > band) | ((desired == 0) & (w > 0))
        tv = np.abs(diff[trade]).sum()
        if trade.any():
            w = np.where(trade, desired, w)
        port = float(w @ R[t])
        growth = (1 - tv * cost) * (1 + port)
        out_ret[t], gross[t], turn[t], mult_arr[t] = growth - 1, w.sum(), tv, mult
        held[t] = w
        equity *= growth
        w = w * (1 + R[t]) / (1 + port) if (1 + port) > 0 else np.zeros(m)
    df = pd.DataFrame({"ret": out_ret, "position": gross, "turnover": turn, "brake": mult_arr},
                      index=prices.index)
    df.attrs["held"] = pd.DataFrame(held, index=prices.index, columns=prices.columns)
    return df


def simulate_funded_portfolio(prices: pd.DataFrame, weights: pd.DataFrame, p: PortfolioParams,
                              cost: float = 0.0045, band: float = 0.02,
                              kill_dd: float | None = 0.45, initial_capital: float = 500.0,
                              min_order_value: float = 5.0, start=None) -> pd.DataFrame:
    """Opt-in research ledger with USD cash, funded purchases and minimum orders.

    The t-1 signal trades at the t-1 close proxy; one-way ``cost`` is charged in
    cash on each fill, then quantities receive the price move ending at t. Buys
    share available cash proportionally after sales and their costs. There are
    no book fills, interest, dividends, splits, lot sizes or execution forecasts.

    ``start`` is the first evaluated return, not a signal warmup boundary. A new
    flat ledger begins there, using the preceding close when one is supplied.
    Missing raw prices prohibit trading. Existing positions can be marked using
    at most five forward-filled rows; beyond that the simulation fails closed.
    ``held`` and ``position`` describe exposure after fees, before the t return.
    This leaves the frozen legacy simulator and operational execution unchanged.
    """
    if (prices.empty or not prices.index.is_unique or not prices.index.is_monotonic_increasing
            or not isinstance(prices.index, pd.DatetimeIndex) or prices.index.hasnans
            or not prices.columns.is_unique):
        raise ValueError("precios vacíos o índice/activos inválidos")
    if not weights.index.equals(prices.index) or set(weights.columns) != set(prices.columns) or not weights.columns.is_unique:
        raise ValueError("pesos y precios deben tener las mismas fechas y activos")
    for name, value in (("cost", cost), ("band", band), ("initial_capital", initial_capital),
                        ("min_order_value", min_order_value)):
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"{name} debe ser finito y no negativo")
    if initial_capital <= 0 or cost >= 1 or band > 1:
        raise ValueError("capital positivo, costo menor a 1 y banda no mayor a 1 requeridos")
    if kill_dd is not None and (not np.isfinite(kill_dd) or not 0 < kill_dd <= 1):
        raise ValueError("kill_dd debe estar entre 0 y 1")
    if p.dd_peak_window < 1:
        raise ValueError("dd_peak_window debe ser positivo")
    raw = prices.astype(float).where(lambda frame: np.isfinite(frame) & (frame > 0))
    marks = clean(raw).to_numpy()  # Exactly one application of the five-row fill policy.
    fresh = raw.notna().to_numpy()
    targets = weights.reindex(columns=prices.columns).to_numpy(dtype=float)
    if (not np.isfinite(targets).all() or (targets < 0).any()
            or (targets.sum(axis=1) > 1 + 1e-12).any()):
        raise ValueError("pesos deben ser finitos, largos y sumar como máximo 1")
    first = 0 if start is None else int(prices.index.searchsorted(pd.Timestamp(start)))
    if first >= len(prices):
        raise ValueError("start no contiene retornos de evaluación")
    cash = float(initial_capital)
    quantities = np.zeros(len(prices.columns))
    equity, peak, killed = cash, cash, False
    observed = [equity]
    previous_brake = 1.0
    month_days = rebalance_days(prices.index)
    cash_index = prices.columns.get_loc(p.cash_asset) if p.cash_asset in prices.columns else None
    rows, held = [], []

    def values(at):
        owned = quantities > 0
        if (owned & ~np.isfinite(marks[at])).any():
            assets = ", ".join(str(asset) for asset in prices.columns[owned & ~np.isfinite(marks[at])])
            raise ValueError(f"sin precio para posición abierta en {prices.index[at]}: {assets}")
        return quantities * np.where(owned, marks[at], 0.0)

    for t in range(first, len(prices)):
        before = equity
        fees, notional, brake = 0.0, 0.0, previous_brake
        exposure = np.zeros(len(quantities))
        if t > 0:
            decision = t - 1
            market_values = values(decision)
            decision_equity = cash + float(market_values.sum())
            peak = max(peak, decision_equity)
            rolling_peak = max(observed[-p.dd_peak_window:])
            if kill_dd is not None and decision_equity / peak - 1 <= -kill_dd:
                killed = True
            brake = 0.0 if killed else drawdown_multiplier(decision_equity / rolling_peak - 1, p)
            desired = targets[decision].copy() * brake
            if cash_index is not None and not killed and np.isfinite(marks[decision, cash_index]):
                desired[cash_index] = max(0.0, 1.0 - (desired.sum() - desired[cash_index]))
            current = market_values / decision_equity if decision_equity > 0 else np.zeros(len(quantities))
            diff = desired - current
            trade = fresh[decision] & ((np.abs(diff) > band) | ((desired == 0) & (quantities > 0)))
            if p.rebalance == "monthly" and not (
                    month_days[decision] or killed or brake != previous_brake or quantities.sum() == 0):
                trade[:] = False
            previous_brake = brake
            for asset in np.flatnonzero(trade & (diff < 0)):
                px = marks[decision, asset]
                qty = quantities[asset] if desired[asset] == 0 else min(
                    quantities[asset], -diff[asset] * decision_equity / px)
                amount = qty * px
                if amount < min_order_value:
                    continue
                quantities[asset] -= qty
                cash += amount * (1 - cost)
                fees += amount * cost
                notional += amount
            purchases = np.where(trade & (diff > 0), diff * decision_equity, 0.0)
            purchases[purchases < min_order_value] = 0.0
            need = float(purchases.sum()) * (1 + cost)
            if need > 0:
                purchases *= min(1.0, cash / need)
            for asset in np.flatnonzero(purchases > 0):
                amount = purchases[asset]
                if amount < min_order_value:
                    continue
                quantities[asset] += amount / marks[decision, asset]
                cash -= amount * (1 + cost)
                fees += amount * cost
                notional += amount
            if cash < -1e-10 or (quantities < 0).any():
                raise ValueError("la ejecución excedió el efectivo o inventario disponible")
            cash = max(0.0, cash)  # Absorb floating-point residuals only (bound checked above).
            invested = values(decision)
            after_fees = cash + float(invested.sum())
            exposure = invested / after_fees if after_fees > 0 else np.zeros(len(quantities))
            equity = cash + float(values(t).sum())
            observed.append(equity)
        rows.append({"ret": equity / before - 1, "equity": equity, "cash": cash,
                     "position": float(exposure.sum()), "turnover": notional / before,
                     "cost_usd": fees, "brake": brake, "killed": killed})
        held.append(exposure)
    result = pd.DataFrame(rows, index=prices.index[first:])
    result.attrs["held"] = pd.DataFrame(held, index=result.index, columns=prices.columns)
    result.attrs["execution_model"] = "funded_prior_close_proxy_v1"
    result.attrs["valuation_ffill_rows"] = 5
    result.attrs["initial_capital_usd"] = float(initial_capital)
    return result


def with_provisional_close(daily: pd.DataFrame, prices_now: pd.Series, day: pd.Timestamp,
                           window_days: int | None = None) -> pd.DataFrame:
    """Cierres diarios COMPLETOS antes de `day` + una fila para `day` con los precios de este momento.

    Es lo que ve una revisión a media sesión: el precio actual hace de cierre provisional del día.
    Si `day` ya cerró, la fila provisional es exactamente su cierre.
    """
    base = daily.loc[: day - pd.Timedelta(days=1)]
    if window_days:
        base = base.loc[day - pd.Timedelta(days=window_days):]
    row = pd.DataFrame([prices_now.reindex(daily.columns).astype(float).values], index=[day], columns=daily.columns)
    return pd.concat([base, row])


# ------------------------------------------------------------------ corto plazo (velas por hora)
# Probadas en reports/corto_plazo_preregistro.md. Solo compras; lo no invertido queda en efectivo.
def _hourly_eligible(H: pd.DataFrame, min_history: int) -> np.ndarray:
    return ((H.notna().cumsum() >= min_history) & H.notna()).values


def reversal_weights(H: pd.DataFrame, every: int = 4, k: int = 3, lookback: int = 24,
                     threshold: float | None = None, min_history: int = 720) -> pd.DataFrame:
    """Cada `every` horas compra en partes iguales (1/k cada una) las k criptos que más cayeron en
    `lookback` horas; con `threshold`, solo las que cayeron más que eso. Entre revisiones se mantiene."""
    Hc = clean(H)
    r = (Hc / Hc.shift(lookback) - 1).values
    elig = _hourly_eligible(H, min_history)
    hours = np.asarray(H.index.hour)
    W = np.full(H.shape, np.nan)
    for t in range(len(H)):
        if hours[t] % every:
            continue
        row = np.zeros(H.shape[1])
        ok = elig[t] & np.isfinite(r[t])
        if threshold is not None:
            ok &= r[t] < -threshold
        idx = np.flatnonzero(ok)
        if len(idx):
            row[idx[np.argsort(r[t][idx], kind="stable")][:k]] = 1.0 / k
        W[t] = row
    return pd.DataFrame(W, index=H.index, columns=H.columns).ffill().fillna(0.0)


def breakout_weights(H: pd.DataFrame, entry: int = 24, exit: int = 12, slots: int = 5,
                     min_history: int = 720) -> pd.DataFrame:
    """Entra si el precio supera el máximo de las `entry` horas anteriores; sale si baja del mínimo
    de las `exit` horas anteriores. Peso 1/slots por cripto (partes iguales si hay más de `slots`)."""
    Hc = clean(H)
    hi = Hc.shift(1).rolling(entry, min_periods=entry).max().values
    lo = Hc.shift(1).rolling(exit, min_periods=exit).min().values
    px = Hc.values
    elig = _hourly_eligible(H, min_history)
    inside = np.zeros(H.shape[1], bool)
    W = np.zeros(H.shape)
    for t in range(len(H)):
        p = px[t]
        enter = elig[t] & np.isfinite(p) & np.isfinite(hi[t]) & (p > hi[t])
        leave = ~elig[t] | ~np.isfinite(p) | (np.isfinite(lo[t]) & (p < lo[t]))
        inside = (inside | enter) & ~leave
        n = inside.sum()
        if n:
            W[t, inside] = 1.0 / max(n, slots)
    return pd.DataFrame(W, index=H.index, columns=H.columns)


# ------------------------------------------------------------------ universos
def crypto_universe(mcap: pd.DataFrame, prices: pd.DataFrame, top_n: int = 15,
                    min_history: int = 250) -> pd.DataFrame:
    """Elegibles en cada fecha: top N por capitalización DE ESE DÍA y con historia suficiente.

    Así el backtest solo "conoce" las criptos que en ese momento eran grandes,
    incluidas las que después se desplomaron.
    """
    hist = prices.notna().cumsum() >= min_history
    ranks = mcap.where(prices.notna()).rank(axis=1, ascending=False, method="first")
    return (ranks <= top_n) & hist & prices.notna()


def listed_universe(prices: pd.DataFrame, min_history: int = 250) -> pd.DataFrame:
    return (prices.notna().cumsum() >= min_history) & prices.notna()


# ------------------------------------------------------------------ referencias
def equal_weight_buy_hold(prices: pd.DataFrame, eligible: pd.DataFrame,
                          rebalance: str = "ME") -> pd.DataFrame:
    """Referencia pasiva: pesos iguales entre los elegibles, rebalanceo mensual."""
    W = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    month_end = prices.index.to_series().groupby(prices.index.to_period("M")).transform("max")
    current = None
    for d in prices.index:
        if current is None or d == month_end[d]:
            e = eligible.loc[d]
            current = e.astype(float) / max(1, e.sum())
        W.loc[d] = current.values
    return W


def fixed_weights(prices: pd.DataFrame, mix: dict[str, float]) -> pd.DataFrame:
    W = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    for k, v in mix.items():
        W[k] = v
    return W.where(prices.notna(), 0.0)


# Four-family paper arena: shared causal signals, also available to research.
def arena_directional_signal(variant, rows, wallet, ts):
    """Pure causal decision; rows are closed candles, not current live prices."""
    family = variant['id']
    closes = pd.Series([r[4] for r in rows], dtype=float)
    price = closes.iloc[-1]
    if family == 'swing-v1':
        if len(rows) < 250:
            return None, 'Calentando: necesita 250 cierres diarios'
        index = pd.to_datetime([r[0] for r in rows], unit='ms')
        panel = pd.DataFrame({'BTC': closes.values}, index=index)
        params = PortfolioParams(top_k=1, vol_target=variant['vol_target'], max_weight=variant['max_weight'], regime_asset='BTC')
        weight = float(target_weights(panel, None, params, last_only=True).iloc[-1, 0])
        return weight, 'Tendencia diaria y momentum con ajuste por volatilidad'
    if len(rows) < 30:
        return None, 'Calentando: necesita 30 cierres completos'
    holding = wallet['qty'] * price >= 5.0
    if holding:
        entry_price = wallet['cost_basis'] / wallet['qty']
        held = ts - (wallet['entry_ms'] or ts)
        change = price / entry_price - 1
        if change <= -variant['stop_loss']:
            return 0., 'Salida: pérdida por posición'
        if held >= variant['max_hold_seconds'] * 1000:
            return 0., 'Salida: tiempo máximo'
        if family == 'scalping-v1' and change >= variant['take_profit']:
            return 0., 'Salida: objetivo de precio'
    if family == 'scalping-v1':
        fast = closes.ewm(span=variant['ema_fast'], adjust=False).mean().iloc[-1]
        slow = closes.ewm(span=variant['ema_slow'], adjust=False).mean().iloc[-1]
        if holding:
            if fast < slow or wallet.get('entry_day') != pd.Timestamp(ts, unit='ms', tz='UTC').date().isoformat():
                return 0., 'Salida: tendencia o fin de sesión UTC'
            return None, 'Mantiene posición intradía'
        breakout = max(r[2] for r in rows[-variant['breakout_bars']-1:-1])
        if fast > slow and price > breakout and wallet['entries_today'] < variant['max_entries_per_day']:
            return variant['allocation'], 'Entrada: ruptura de 20 velas y EMA9 > EMA21'
        return None, 'Espera ruptura confirmada'
    window = closes.iloc[-variant['lookback']:]
    std = float(window.std(ddof=0))
    z = (price - float(window.mean())) / std if std > 0 else 0.
    if holding:
        return (0., 'Salida: regreso a la media') if z >= variant['exit_z'] else (None, 'Espera regreso a la media')
    return (variant['allocation'], 'Entrada: desviación bajo −2σ') if z <= variant['entry_z'] else (None, 'Espera desviación bajo −2σ')
