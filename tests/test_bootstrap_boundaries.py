"""Synthetic boundary regressions; no market results are recomputed.

Historical reports keep their original sampling engine. Reevaluating their
quantitative conclusions requires a new preregistration and a separate run.
"""
import numpy as np
import pytest

from lab.validation import _block_indices


class LastStartRng:
    """Choose the largest start allowed by the RNG's exclusive upper bound."""

    def integers(self, low, high, size):
        return np.full(size, high - 1, dtype=int)


def test_last_complete_block_includes_final_observation():
    indices = _block_indices(n=10, length=4, block=4, rng=LastStartRng())

    np.testing.assert_array_equal(indices, [6, 7, 8, 9])


@pytest.mark.parametrize("block", [1, 4, 30])
def test_entire_sample_can_be_the_only_valid_block(block):
    indices = _block_indices(n=block, length=block, block=block,
                             rng=np.random.default_rng(31))

    np.testing.assert_array_equal(indices, np.arange(block))


@pytest.mark.parametrize("length", [1, 4, 5, 17, 43])
def test_resampled_length_and_indices_stay_within_observed_data(length):
    indices = _block_indices(n=17, length=length, block=5,
                             rng=np.random.default_rng(71))

    assert indices.shape == (length,)
    assert np.issubdtype(indices.dtype, np.integer)
    assert (indices >= 0).all()
    assert (indices < 17).all()


def test_repeating_the_only_block_truncates_to_requested_length():
    indices = _block_indices(n=3, length=8, block=3,
                             rng=np.random.default_rng(19))

    np.testing.assert_array_equal(indices, [0, 1, 2, 0, 1, 2, 0, 1])
