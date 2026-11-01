import numpy as np
import pandas as pd
import pytest

from lab.fixed_costs import with_fixed_cost


def test_sin_costo_no_cambia_nada():
    r = pd.Series(np.random.default_rng(3).normal(0.001, 0.02, 400), index=pd.date_range("2020-01-01", periods=400))
    pd.testing.assert_series_equal(with_fixed_cost(r, 1000, 0.0), r, check_names=False)


def test_resta_el_costo_diario_en_dolares():
    r = pd.Series(0.0, index=pd.date_range("2020-01-01", periods=365))
    out = with_fixed_cost(r, 1000, 60.0)
    assert np.isclose(1000 * (1 + out).prod(), 940.0)


def test_pesa_menos_con_mas_capital():
    r = pd.Series(0.0005, index=pd.date_range("2020-01-01", periods=730))
    small = (1 + with_fixed_cost(r, 1000, 60.0)).prod()
    big = (1 + with_fixed_cost(r, 10000, 60.0)).prod()
    assert small < big < (1 + r).prod()


def test_no_baja_de_cero():
    r = pd.Series(0.0, index=pd.date_range("2020-01-01", periods=40))
    out = with_fixed_cost(r, 10, 365.0)  # US$1 al día con US$10
    assert np.isclose(10 * (1 + out).prod(), 0.0)
    assert (out.iloc[11:] == 0).all()


def test_valida():
    r = pd.Series([0.0, 0.01])
    with pytest.raises(ValueError):
        with_fixed_cost(r, 0, 60)
