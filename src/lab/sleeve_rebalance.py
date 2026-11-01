"""Rebalanceo entre bloques (H13): combina los rendimientos diarios de dos bloques en una sola cartera.

Cada bloque se capitaliza con su propio rendimiento. Al cierre del día t, si la regla lo pide, se devuelve el
peso del bloque A a ``target`` moviendo dinero del bloque sobrepesado al otro; el receptor recibe lo movido
menos la fricción. La decisión del día t usa solo rendimientos hasta t.

Sin regla (``band=None`` y ``annual=False``) es exactamente la suma de los dos bloques sin traspasos, que es
como corre hoy el piloto. Ver reports/sprint04_h13_rebalanceo_bloques_preregistro.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def combine_sleeves(ret_a: pd.Series, ret_b: pd.Series, *, target: float = 0.5, band: float | None = None,
                    annual: bool = False, friction: float = 0.0, capital: float = 1000.0) -> pd.DataFrame:
    """Cartera de dos bloques con traspasos opcionales.

    ret_a, ret_b: rendimientos diarios con el mismo índice (días de calendario; 0 si el bloque no opera ese día).
    band: traspasa si |peso de A − target| > band al cierre. annual: traspasa al cierre de cada 31 de diciembre.
    friction: fracción de lo movido que se pierde en el traspaso (costos de ambos bloques + plataforma).

    Devuelve por día: equity_a, equity_b, equity, ret (de la cartera, ya con la fricción del día), weight_a (tras
    el traspaso), transfer (US$ movidos; > 0 de A a B) y friction_usd.
    """
    if not ret_a.index.equals(ret_b.index):
        raise ValueError("los dos bloques necesitan el mismo índice")
    if not 0 < target < 1:
        raise ValueError("target debe estar entre 0 y 1")
    if band is not None and not 0 < band < min(target, 1 - target):
        raise ValueError("band fuera de rango")
    if not 0 <= friction < 1:
        raise ValueError("friction fuera de rango")
    ra = ret_a.to_numpy(dtype=float)
    rb = ret_b.to_numpy(dtype=float)
    if not (np.isfinite(ra).all() and np.isfinite(rb).all()):
        raise ValueError("rendimientos no finitos")
    idx = ret_a.index
    is_dec31 = np.asarray((idx.month == 12) & (idx.day == 31)) if annual else np.zeros(len(idx), bool)
    n = len(idx)
    ea_out, eb_out, w_out, tr_out, fr_out, ret_out = (np.empty(n) for _ in range(6))
    ea, eb = capital * target, capital * (1 - target)
    prev_total = capital
    for t in range(n):
        ea *= 1 + ra[t]
        eb *= 1 + rb[t]
        total = ea + eb
        w = ea / total if total > 0 else target
        move = 0.0
        if total > 0 and ((band is not None and abs(w - target) > band) or is_dec31[t]):
            move = ea - target * total  # > 0: A sobrepesado, se mueve de A a B
        lost = abs(move) * friction
        if move > 0:
            ea -= move
            eb += move - lost
        elif move < 0:
            eb += move
            ea += -move - lost
        total_after = ea + eb
        ea_out[t], eb_out[t], tr_out[t], fr_out[t] = ea, eb, move, lost
        w_out[t] = ea / total_after if total_after > 0 else target
        ret_out[t] = total_after / prev_total - 1 if prev_total > 0 else 0.0
        prev_total = total_after
    return pd.DataFrame({"equity_a": ea_out, "equity_b": eb_out, "equity": ea_out + eb_out, "ret": ret_out,
                         "weight_a": w_out, "transfer": tr_out, "friction_usd": fr_out}, index=idx)
