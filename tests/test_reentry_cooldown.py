"""H1b (sprint 03): bloqueo de recompra tras salida total. Pruebas mecánicas y de causalidad, sin afirmar ganancia."""
import numpy as np
import pandas as pd
import pytest

from lab.portfolio import PortfolioParams, listed_universe, target_weights
from lab.reentry import apply_reentry_cooldown


def cooled(P, days):
    return apply_reentry_cooldown(target_weights(P, listed_universe(P, 120), PortfolioParams(mom_windows=(30, 60, 90))), days)


def panel(n=420):
    rng = np.random.default_rng(912)
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.003, .03, (n, 7)), axis=0)),
                        index=pd.date_range("2020-01-01", periods=n),
                        columns=["BTC", "ETH", "SOL", "LINK", "UNI", "NEAR", "LTC"])


def test_cooldown_blocks_next_days_and_allows_reentry_after():
    W = np.array([[.3], [0], [.3], [.3], [0], [0], [0], [.2]])
    np.testing.assert_allclose(apply_reentry_cooldown(W, 2)[:, 0], [.3, 0, 0, .3, 0, 0, 0, .2])
    np.testing.assert_allclose(apply_reentry_cooldown(W, 3)[:, 0], [.3, 0, 0, 0, 0, 0, 0, .2])


def test_cooldown_of_zero_or_one_is_identity_and_cash_column_is_skipped():
    W = np.array([[.3, .7], [0, 1.], [.3, .7]])
    np.testing.assert_allclose(apply_reentry_cooldown(W, 1), W)
    out = apply_reentry_cooldown(np.array([[.3, .7], [0, 0], [.3, .7]]), 3, skip=1)
    np.testing.assert_allclose(out, [[.3, .7], [0, 0], [0, .7]])


def test_param_validation():
    with pytest.raises(ValueError):
        apply_reentry_cooldown(np.zeros((2, 2)), -1)


def test_default_reproduces_control_and_cooldown_only_removes_weight():
    P = panel()
    base = cooled(P, 0)
    cool = cooled(P, 3)
    assert (cool.values <= base.values + 1e-12).all()
    assert (cool.values < base.values - 1e-12).any(), "el panel sintético debería tener alguna recompra bloqueada"


def test_no_lookahead_future_prices_do_not_change_past_targets():
    P = panel()
    full = cooled(P, 2)
    cut = 330
    Q = P.copy()
    Q.iloc[cut:] = Q.iloc[cut:] * np.linspace(.3, 3., len(Q) - cut)[:, None]
    pd.testing.assert_frame_equal(full.iloc[:cut], cooled(Q, 2).iloc[:cut])
    pd.testing.assert_frame_equal(full.iloc[:cut], cooled(P.iloc[:cut], 2))
