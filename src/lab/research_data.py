"""Corrección declarada de disponibilidad histórica; nunca calcula rendimientos.

El caller verifica/pinea los bytes raw y el archivo de evidencia antes de usar
esta transformación pura. Un hash bien formado no certifica la evidencia: aquí
solo se registra su identidad. Los originales y el audit se conservan aparte.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .experiments import ResearchGateError


POLICY_KEYS = frozenset({"asset", "available_from", "evidence_sha256"})
AVAX_REFERENCE_SPOT_DATE = "2020-09-22"


def apply_availability_policy(prices: pd.DataFrame, policy: dict) -> tuple[pd.DataFrame, dict]:
    """En copia: AVAX anterior a 2020-09-22 se convierte a NaN, nunca a cero.

    ``policy`` tiene exactamente asset, available_from y evidence_sha256. Esta
    versión admite únicamente la corrección AVAX declarada. La fecha identifica
    un mercado spot de referencia verificado (Binance), no un listado de Bitso ni
    el primer mercado mundial. No transforma USDT a USD ni sustituye precios.
    """
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise ResearchGateError("policy requiere exactamente asset, available_from y evidence_sha256")
    if policy["asset"] != "AVAX" or policy["available_from"] != AVAX_REFERENCE_SPOT_DATE:
        raise ResearchGateError("esta corrección solo admite AVAX desde 2020-09-22")
    evidence_hash = policy["evidence_sha256"]
    if not isinstance(evidence_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", evidence_hash):
        raise ResearchGateError("evidence_sha256 debe ser un SHA256 hexadecimal completo en minúsculas")
    if not isinstance(prices, pd.DataFrame) or not prices.columns.is_unique or "AVAX" not in prices:
        raise ResearchGateError("el panel debe contener una columna AVAX única")
    idx = prices.index
    if (not isinstance(idx, pd.DatetimeIndex) or not idx.is_unique or not idx.is_monotonic_increasing
            or idx.tz is not None or not idx.equals(idx.normalize())):
        raise ResearchGateError("el panel requiere cierres diarios UTC sin zona, únicos y ordenados")
    raw = prices["AVAX"]
    if not pd.api.types.is_numeric_dtype(raw.dtype) or pd.api.types.is_bool_dtype(raw.dtype):
        raise ResearchGateError("AVAX debe contener precios numéricos o ausencias")
    values = raw.to_numpy(dtype=float, na_value=np.nan)
    present = ~np.isnan(values)
    if (not np.isfinite(values[present]).all()) or (values[present] <= 0).any():
        raise ResearchGateError("AVAX contiene precios infinitos o no positivos")

    before = idx < pd.Timestamp(policy["available_from"])
    quarantine = [
        {"date": str(day.date()), "asset": "AVAX", "original_value": float(value),
         "reason": "before_verified_reference_spot_availability"}
        for day, value in raw.loc[before & present].items()
    ]
    derived = prices.copy(deep=True)
    derived.loc[before, "AVAX"] = np.nan
    audit = {
        "policy": dict(policy),
        "method": "set_preavailability_observations_missing",
        "reference_venue": "Binance spot",
        "bitso_listing_verified": False,
        "evidence_verified_by_helper": False,
        "rows_before_cutoff": int(before.sum()),
        "missing_before": int(raw.isna().sum()),
        "missing_after": int(derived["AVAX"].isna().sum()),
        "quarantined_count": len(quarantine),
        "quarantine": quarantine,
        "raw_mutated": False,
        "interpolation": False,
        "price_currency_conversion": False,
    }
    return derived, audit
