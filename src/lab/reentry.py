"""H1b (sprint 03, descartada): bloqueo de recompra tras una salida total.

Vive fuera de `lab.portfolio` porque no entró al bot (el archivo de la arena congela el hash de
`portfolio.py`). Si algún día se aprueba, se mueve a `PortfolioParams` para que bot y backtest la compartan.
Ver reports/sprint03_h1b_recompra_resultado.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def apply_reentry_cooldown(W, days: int, skip: int = -1):
    """Tras una salida total el día e (objetivo efectivo > 0 el día e-1 y 0 el día e), el objetivo se
    fuerza a 0 hasta e + days - 1: la primera recompra posible es e + days. Solo usa filas pasadas.
    El peso bloqueado queda en efectivo (no se reparte). `skip`: columna del activo de efectivo.
    Acepta un arreglo o un DataFrame de pesos objetivo (devuelve el mismo tipo)."""
    if not (isinstance(days, (int, np.integer)) and days >= 0):
        raise ValueError("days debe ser un entero no negativo")
    frame = W if isinstance(W, pd.DataFrame) else None
    out = np.array(frame.to_numpy() if frame is not None else W, dtype=float, copy=True)
    if days > 1 and out.size:
        blocked_until = np.full(out.shape[1], -1)
        for t in range(1, len(out)):
            exited = (out[t - 1] > 0) & (out[t] <= 0)
            blocked_until = np.where(exited, t + days - 1, blocked_until)
            mask = blocked_until >= t
            if skip >= 0:
                mask[skip] = False
            out[t, mask & ~exited] = 0.0
    return pd.DataFrame(out, index=frame.index, columns=frame.columns) if frame is not None else out
