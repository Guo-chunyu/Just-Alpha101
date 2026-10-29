"""Formula-level checks independent of the operator implementation."""

import importlib

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def formulas():
    try:
        return importlib.import_module("just_alpha101.formulas")
    except ModuleNotFoundError:
        pytest.fail("The Alpha101 mathematical formula registry is missing")


@pytest.fixture
def engine_module():
    try:
        return importlib.import_module("just_alpha101.engine")
    except ModuleNotFoundError:
        pytest.fail("The Alpha101 formula engine is missing")


def panel(values):
    return pd.DataFrame(values, dtype=float)


def test_registry_covers_every_published_alpha(formulas):
    assert set(formulas.FORMULAS) == set(range(1, 102))
    assert formulas.DELAY_ZERO == {42, 48, 53, 54}


def test_alpha101_intraday_momentum_has_paper_denominator(engine_module):
    data = {
        "open": panel([[10, 12, 5]]),
        "close": panel([[12, 10, 5]]),
        "high": panel([[14, 13, 5]]),
        "low": panel([[9, 8, 5]]),
    }
    actual = engine_module.FormulaEngine(data).compute(101)
    np.testing.assert_allclose(actual, [[2 / 5.001, -2 / 5.001, 0]])


def test_alpha12_volume_direction_reverses_price_change(engine_module):
    data = {
        "close": panel([[10, 10, 10], [12, 7, 14], [11, 5, 10]]),
        "volume": panel([[20, 20, 20], [25, 15, 20], [24, 17, 19]]),
    }
    actual = engine_module.FormulaEngine(data).compute(12)
    np.testing.assert_allclose(
        actual, [[np.nan] * 3, [-2, -3, 0], [-1, 2, -4]], equal_nan=True
    )


def test_alpha41_geometric_midpoint_minus_vwap(engine_module):
    data = {"high": panel([[16, 25]]), "low": panel([[4, 9]]), "vwap": panel([[9, 14]])}
    np.testing.assert_allclose(engine_module.FormulaEngine(data).compute(41), [[-1, 1]])


def test_alpha1_conditional_volatility_argmax_and_centering(engine_module):
    close = pd.DataFrame(np.tile([200.0, 2.0, 2.0], (25, 1)))
    close.iloc[-5:] = [[100, 7, 9], [90, 4, 3], [8, 9, 4], [4, 6, 2], [7, 5, 5]]
    original = close.copy(deep=True)
    actual = engine_module.FormulaEngine({"close": close}).compute(1)
    # A's declining closes become volatility < 1; its last rising close peaks
    # on day 5. B peaks on day 3 and C on day 1: ranks are 1, 2/3, 1/3.
    np.testing.assert_allclose(actual.iloc[-1], [.5, 1 / 6, -1 / 6])
    pd.testing.assert_frame_equal(close, original)


def test_alpha29_uses_five_day_minimum_not_elementwise_cap(engine_module):
    t = np.arange(12, dtype=float)
    close = pd.DataFrame({"A": 100 + t**2, "B": 100 + 10*t, "C": 1000 - t**2})
    actual = engine_module.FormulaEngine({"close": close}).compute(29)
    # A and B swap five-day change ranks at t=8. The outer five-day minima
    # at t=11 are [1/3, 1/3, 1]; delayed negative-return ranks are [.2, 1, 1].
    np.testing.assert_allclose(actual.iloc[-1], [8 / 15, 4 / 3, 2])


@pytest.fixture(scope="module")
def synthetic_fields():
    rng = np.random.default_rng(101)
    index = pd.date_range("2019-01-01", periods=340, freq="B")
    columns = [f"STOCK{i:02d}" for i in range(12)]

    def frame(values):
        return pd.DataFrame(values, index=index, columns=columns)

    # Deliberately varied cross-sectional order and oscillating dollar volumes
    # give nested rank-correlations (especially #96) a nonconstant test domain.
    close = frame(30 * np.exp(rng.normal(0, .1, (340, 12))))
    opened = close * frame(np.exp(rng.normal(0, .015, (340, 12))))
    high = np.maximum(close, opened) * frame(1 + rng.uniform(.002, .04, (340, 12)))
    low = np.minimum(close, opened) * frame(1 - rng.uniform(.002, .04, (340, 12)))
    fields = {
        "close": close,
        "open": opened,
        "high": high,
        "low": low,
        "vwap": (high + low + close) / 3,
        "cap": close * frame(np.broadcast_to(np.arange(1, 13) * 1e7, (340, 12))),
    }
    fields["dollar_volume"] = frame(1e7 * (2 + np.sin(np.arange(340)[:, None] * 2 * np.pi / 3.5 + np.arange(12)[None, :])))
    fields["volume"] = fields["dollar_volume"] / fields["vwap"]
    for name, size in [("sector", 6), ("industry", 4), ("subindustry", 3)]:
        fields[name] = frame(np.broadcast_to(np.arange(12) // size, (340, 12))).astype(str)
    return fields


def test_every_alpha_evaluates_to_aligned_nonempty_finite_signals(engine_module, formulas, synthetic_fields):
    engine = engine_module.FormulaEngine(synthetic_fields)
    for alpha_id in formulas.FORMULAS:
        actual = engine.compute(alpha_id)
        assert isinstance(actual, pd.DataFrame), alpha_id
        assert actual.shape == (340, 12), alpha_id
        pd.testing.assert_index_equal(actual.index, synthetic_fields["close"].index)
        pd.testing.assert_index_equal(actual.columns, synthetic_fields["close"].columns)
        assert actual.notna().any().any(), f"Alpha {alpha_id} has no valid observations"
        assert not np.isinf(actual.to_numpy()).any(), alpha_id


def test_all_alphas_are_causal_and_leave_input_panels_unchanged(engine_module, formulas, synthetic_fields):
    original = {key: value.copy(deep=True) for key, value in synthetic_fields.items()}
    altered = {key: value.copy(deep=True) for key, value in synthetic_fields.items()}
    for key, value in altered.items():
        if key in {"sector", "industry", "subindustry"}:
            value.iloc[310:] = "CHANGED"
        else:
            value.iloc[310:] *= np.linspace(.1, 20, 30)[:, None]
    before = engine_module.FormulaEngine(synthetic_fields)
    after = engine_module.FormulaEngine(altered)
    for alpha_id in formulas.FORMULAS:
        pd.testing.assert_frame_equal(before.compute(alpha_id).iloc[:310], after.compute(alpha_id).iloc[:310])
    for key, value in synthetic_fields.items():
        pd.testing.assert_frame_equal(value, original[key])


@pytest.mark.parametrize("alpha_id,missing", [(56, "cap"), (48, "subindustry"), (58, "sector"), (59, "industry")])
def test_fundamental_and_industry_alphas_require_real_inputs(engine_module, synthetic_fields, alpha_id, missing):
    incomplete = {key: value for key, value in synthetic_fields.items() if key != missing}
    with pytest.raises(engine_module.MissingFieldError) as caught:
        engine_module.FormulaEngine(incomplete).compute(alpha_id)
    assert missing in caught.value.missing_fields
