"""Engine tests use tiny expressions to isolate masking and causality contracts."""
import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def engine_module(monkeypatch):
    # The formula registry is authored independently. A temporary registry is only
    # needed when this test is run before that file arrives; no fake factor values.
    if importlib.util.find_spec("just_alpha101.formulas") is None:
        registry = types.ModuleType("just_alpha101.formulas")
        registry.FORMULAS = {}
        monkeypatch.setitem(sys.modules, "just_alpha101.formulas", registry)
    try:
        module = importlib.import_module("just_alpha101.engine")
    except ModuleNotFoundError:
        pytest.fail("The Alpha101 formula engine is missing")
    monkeypatch.setattr(module, "FORMULAS", {})
    return module


def fields():
    index = pd.date_range("2010-01-01", periods=6)
    close = pd.DataFrame([[1, 6], [2, 5], [3, 4], [4, 3], [5, 2], [6, 1]], index=index, columns=["A", "B"], dtype=float)
    return {"close": close, "open": close - .5, "volume": close * 10, "vwap": close + .5}


def prepare(module, expression, data=None, **kwargs):
    module.FORMULAS[999] = expression
    return module.FormulaEngine(fields() if data is None else data, **kwargs)


def test_arithmetic_comparisons_and_where_preserve_unknowns(engine_module):
    data = fields()
    data["close"].iloc[0, 0] = np.nan
    result = prepare(engine_module, "where(close > 3, close, -close)", data).compute(999)
    assert np.isnan(result.iloc[0, 0])
    assert result.iloc[1, 0] == -2
    assert result.iloc[-1, 0] == 6
    divided = prepare(engine_module, "close / (close-close)").compute(999)
    assert divided.isna().all().all()


def test_unknown_mask_is_preserved_through_logical_or(engine_module):
    result = prepare(engine_module, "where((delay(close, 1) > 2) | (close > 0), 1, 0)").compute(999)
    assert result.iloc[0].isna().all()
    assert (result.iloc[1:] == 1).all().all()


def test_power_does_not_make_missing_observations_valid(engine_module):
    result = prepare(engine_module, "delay(close, 1) ** 0").compute(999)
    assert result.iloc[0].isna().all()
    assert (result.iloc[1:] == 1).all().all()
    result = prepare(engine_module, "(-1) ** 0.5").compute(999)
    assert result.isna().all().all()


def test_where_ignores_invalid_unselected_branch(engine_module):
    result = prepare(engine_module, "where(close > 0, close, log(-close))").compute(999)
    pd.testing.assert_frame_equal(result, fields()["close"])


def test_returns_never_forward_fill_a_missing_price(engine_module):
    data = fields()
    data["close"].iloc[2, 0] = np.nan
    result = prepare(engine_module, "returns", data).compute(999)
    assert result.iloc[1, 0] == 1
    assert result.iloc[2:4, 0].isna().all()
    assert result.iloc[4, 0] == .25


def test_adv_basis_uses_dollars_or_shares_explicitly(engine_module):
    dollar = prepare(engine_module, "adv2").compute(999)
    shares = prepare(engine_module, "adv2", adv_basis="share").compute(999)
    assert dollar.iloc[1, 0] == 32.5  # (1.5*10 + 2.5*20)/2
    assert shares.iloc[1, 0] == 15
    data = fields()
    data["dollar_volume"] = data["volume"] * 7
    result = prepare(engine_module, "adv2", data).compute(999)
    assert result.iloc[1, 0] == 105


def test_requirements_resolve_derived_inputs_and_do_not_invent_industry(engine_module):
    engine = prepare(engine_module, "indneutralize(returns * cap, subindustry) + adv20")
    assert engine.requirements(999) == {"close", "cap", "subindustry", "volume", "vwap"}
    with pytest.raises(engine_module.MissingFieldError) as caught:
        engine.compute(999)
    assert caught.value.missing_fields == {"cap", "subindustry"}
    assert "subindustry" in str(caught.value)


def test_window_scale_floors_windows_but_does_not_change_constants(engine_module):
    result = prepare(engine_module, "sum(close, 3.9) + 2", window_scale=.5).compute(999)
    np.testing.assert_allclose(result, fields()["close"] + 2)
    doubled = prepare(engine_module, "delta(close, 2) + 2", window_scale=2).compute(999)
    assert doubled.iloc[:4].isna().all().all()
    assert doubled.iloc[4, 0] == 6


def test_signals_are_causal_and_do_not_mutate_inputs(engine_module):
    expression = "rank(delta(close, 1)) + ts_rank(volume, 3) + correlation(close, vwap, 3)"
    data = fields()
    before = {key: value.copy(deep=True) for key, value in data.items()}
    first = prepare(engine_module, expression, data).compute(999)
    for key in data:
        pd.testing.assert_frame_equal(data[key], before[key])
    changed = {key: value.copy(deep=True) for key, value in data.items()}
    for value in changed.values():
        value.iloc[4:] *= 100
    second = prepare(engine_module, expression, changed).compute(999)
    pd.testing.assert_frame_equal(first.iloc[:4], second.iloc[:4])


@pytest.mark.parametrize("expression", ["__import__('os')", "close.iloc[0]", "[x for x in close]", "open.__class__", "delay(close, -1)"])
def test_unsafe_syntax_and_negative_delay_are_rejected(engine_module, expression):
    with pytest.raises(ValueError):
        prepare(engine_module, expression).compute(999)


def test_misaligned_or_unsorted_fields_fail_instead_of_silent_alignment(engine_module):
    data = fields()
    data["volume"] = data["volume"].iloc[:-1]
    with pytest.raises(ValueError):
        engine_module.FormulaEngine(data)
    with pytest.raises(ValueError):
        engine_module.FormulaEngine({"close": fields()["close"].iloc[::-1]})


def test_invalid_configuration_and_unknown_alpha_fail(engine_module):
    for kwargs in [{"window_scale": 0}, {"window_scale": np.nan}, {"adv_basis": "guess"}]:
        with pytest.raises(ValueError):
            engine_module.FormulaEngine(fields(), **kwargs)
    with pytest.raises(KeyError):
        engine_module.FormulaEngine(fields()).compute(123456)
