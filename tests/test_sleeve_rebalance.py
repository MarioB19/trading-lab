import numpy as np
import pandas as pd
import pytest

from lab.sleeve_rebalance import combine_sleeves


def _rets(seed=1, n=800):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-01-01", periods=n, freq="D")
    a = pd.Series(rng.normal(0.001, 0.03, n), index=idx)
    b = pd.Series(rng.normal(0.0003, 0.007, n), index=idx)
    return a, b


def test_sin_regla_es_la_suma_de_los_bloques_sin_traspasos():
    a, b = _rets()
    out = combine_sleeves(a, b, capital=1000.0)
    expected = 500 * (1 + a).cumprod() + 500 * (1 + b).cumprod()
    assert np.allclose(out["equity"].to_numpy(), expected.to_numpy())
    assert (out["transfer"] == 0).all() and (out["friction_usd"] == 0).all()
    assert np.isclose((1 + out["ret"]).prod() * 1000, out["equity"].iloc[-1])


def test_banda_devuelve_a_50_50_y_cobra_friccion():
    a, b = _rets()
    out = combine_sleeves(a, b, band=0.10, friction=0.01)
    moved = out[out["transfer"] != 0]
    assert len(moved) > 0
    # tras cada traspaso el peso queda en 50% salvo la fricción
    assert np.allclose(moved["weight_a"], 0.5, atol=0.01)
    assert np.allclose(moved["friction_usd"], moved["transfer"].abs() * 0.01)
    # entre traspasos el peso nunca sale de la banda al cierre (después de decidir)
    assert (out["weight_a"].sub(0.5).abs() <= 0.10 + 1e-12).all()


def test_anual_solo_el_31_de_diciembre():
    a, b = _rets()
    out = combine_sleeves(a, b, annual=True)
    days = out.index[out["transfer"] != 0]
    assert len(days) >= 2
    assert all(d.month == 12 and d.day == 31 for d in days)


def test_sin_mirar_al_futuro():
    a, b = _rets(seed=7)
    cut = 400
    base = combine_sleeves(a, b, band=0.15, friction=0.0142)
    a2, b2 = a.copy(), b.copy()
    a2.iloc[cut + 1:] = -a2.iloc[cut + 1:] * 3
    b2.iloc[cut + 1:] = 0.02
    alt = combine_sleeves(a2, b2, band=0.15, friction=0.0142)
    pd.testing.assert_frame_equal(base.iloc[:cut + 1], alt.iloc[:cut + 1])


def test_valida_entradas():
    a, b = _rets(n=10)
    with pytest.raises(ValueError):
        combine_sleeves(a, b.iloc[1:])
    with pytest.raises(ValueError):
        combine_sleeves(a, b, band=0.6)
    with pytest.raises(ValueError):
        combine_sleeves(a, b, friction=1.0)
