"""Hand-calculated operator contracts: these catch axis, timing and mask errors."""
import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def op():
    try:
        return importlib.import_module("just_alpha101.operators")
    except ModuleNotFoundError:
        pytest.fail("The Alpha101 operator implementation is missing")


def frame(values):
    return pd.DataFrame(values, dtype=float)


def test_rank_is_cross_sectional_percentile_with_average_ties(op):
    actual = op.rank(frame([[3, 1, 1, np.nan], [8, 2, 5, 5]]))
    np.testing.assert_allclose(actual, [[1, .5, .5, np.nan], [1, .25, .625, .625]], equal_nan=True)


def test_ts_rank_ranks_latest_observation_and_requires_full_window(op):
    actual = op.ts_rank(frame([[3], [1], [1], [4], [np.nan], [2]]), 3)
    np.testing.assert_allclose(actual[0], [np.nan, np.nan, .5, 1, np.nan, np.nan], equal_nan=True)


def test_delay_delta_floor_fractional_windows_without_future_access(op):
    x = frame([[1], [3], [8], [10]])
    np.testing.assert_allclose(op.delay(x, 2.9)[0], [np.nan, np.nan, 1, 3], equal_nan=True)
    np.testing.assert_allclose(op.delta(x, 2.9)[0], [np.nan, np.nan, 7, 7], equal_nan=True)
    pd.testing.assert_frame_equal(op.delay(x, 0), x)
    with pytest.raises(ValueError):
        op.delay(x, -1)


def test_arg_extrema_use_one_based_oldest_index_and_first_tie(op):
    x = frame([[2], [5], [5], [1]])
    np.testing.assert_allclose(op.ts_argmax(x, 3)[0], [np.nan, np.nan, 2, 1], equal_nan=True)
    np.testing.assert_allclose(op.ts_argmin(x, 3)[0], [np.nan, np.nan, 1, 3], equal_nan=True)


def test_decay_weights_latest_day_most_and_does_not_fill_missing(op):
    x = frame([[1], [2], [6], [np.nan], [8]])
    np.testing.assert_allclose(op.decay_linear(x, 3)[0], [np.nan, np.nan, 23 / 6, np.nan, np.nan], equal_nan=True)


def test_covariance_stddev_use_sample_denominator_and_constant_corr_is_nan(op):
    x, y = frame([[1], [2], [4]]), frame([[2], [4], [8]])
    assert op.stddev(x, 3).iloc[-1, 0] == pytest.approx(np.sqrt(7 / 3))
    assert op.covariance(x, y, 3).iloc[-1, 0] == pytest.approx(14 / 3)
    assert op.correlation(x, y, 3).iloc[-1, 0] == pytest.approx(1)
    assert np.isnan(op.correlation(frame([[1], [1], [1]]), y, 3).iloc[-1, 0])
    assert np.isnan(op.stddev(x, 1).iloc[-1, 0])


def test_rolling_sum_product_extrema_require_all_observations(op):
    x = frame([[2], [3], [4], [np.nan], [5]])
    for name, expected in [("sum", 9), ("product", 24), ("ts_min", 2), ("ts_max", 4)]:
        actual = getattr(op, name)(x, 3)
        assert actual.iloc[2, 0] == expected
        assert actual.iloc[3:, 0].isna().all()


def test_scale_uses_row_l1_and_zero_row_is_undefined(op):
    actual = op.scale(frame([[2, -1, np.nan], [0, 0, 0]]), 3)
    np.testing.assert_allclose(actual.iloc[0], [2, -1, np.nan], equal_nan=True)
    assert actual.iloc[1].isna().all()


def test_industry_neutralization_is_date_specific_and_missing_group_stays_missing(op):
    x = frame([[1, 3, 10, 7], [1, 3, 10, 7]])
    groups = pd.DataFrame([["A", "A", "B", None], ["A", "B", "B", "A"]])
    actual = op.indneutralize(x, groups)
    np.testing.assert_allclose(actual, [[-1, 1, 0, np.nan], [-3, -3.5, 3.5, 3]], equal_nan=True)


def test_literal_power_and_invalid_math_do_not_emit_infinity(op):
    x = frame([[-2, 0, 2]])
    np.testing.assert_allclose(op.signedpower(x, 2), [[4, 0, 4]])
    np.testing.assert_allclose(op.log(x), [[np.nan, np.nan, np.log(2)]], equal_nan=True)
    np.testing.assert_allclose(op.sign(x), [[-1, 0, 1]])
    np.testing.assert_allclose(op.abs(x), [[2, 0, 2]])


def test_power_retains_unknown_operands_even_for_zero_exponent(op):
    base, exponent = frame([[np.nan, 1, -2]]), frame([[0, np.nan, .5]])
    assert op.signedpower(base, exponent).isna().all().all()


def test_elementwise_minmax_preserve_nan_and_overload_rolling_scalar(op):
    x, y = frame([[1, np.nan], [4, 2]]), frame([[2, 3], [1, 5]])
    np.testing.assert_allclose(op.minimum(x, y), [[1, np.nan], [1, 2]], equal_nan=True)
    np.testing.assert_allclose(op.maximum(x, y), [[2, np.nan], [4, 5]], equal_nan=True)
    pd.testing.assert_frame_equal(op.min(x, 2), op.ts_min(x, 2))
    pd.testing.assert_frame_equal(op.max(x, y), op.maximum(x, y))


def test_where_does_not_turn_unknown_condition_false_or_leak_unselected_branch(op):
    mask = frame([[1, 0, np.nan]])
    actual = op.where(mask, frame([[7, np.nan, 2]]), frame([[np.nan, 9, 3]]))
    np.testing.assert_allclose(actual, [[7, 9, np.nan]], equal_nan=True)

