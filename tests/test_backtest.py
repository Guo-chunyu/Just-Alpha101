import numpy as np
import pandas as pd
import pytest


def panels():
    dates = pd.date_range('2013-12-27', periods=4, freq='B')
    signal = pd.DataFrame([[3., 1.]] * 4, index=dates, columns=['A', 'B'])
    prices = pd.DataFrame([[10., 20.], [10., 20.], [11., 18.], [11., 18.]],
                          index=dates, columns=signal.columns)
    return signal, prices, prices.copy()


def test_causal_next_open_pnl_and_drift_corrected_turnover():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    result = run_backtest(signal, opening, closing, min_assets=2, cost_bps=10)
    # First row has no prior signal. Next row is +0.5 A / -0.5 B.
    assert result.gross_return.iloc[:3].tolist() == pytest.approx([0., .1, 0.])
    # Positions drift to +.55 / -.45 before resetting to +.5 / -.5.
    assert result.turnover.iloc[:3].tolist() == pytest.approx([0., 1., .1])
    assert result.net_return.iloc[:3].tolist() == pytest.approx([0., .099, -.0001])
    assert np.isnan(result.gross_return.iloc[-1])
    assert result.gross_exposure.iloc[1] == pytest.approx(1.)
    assert result.n_assets.iloc[1] == 2


def test_future_signals_cannot_change_prior_targets_or_returns():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    original = run_backtest(signal, opening, closing, min_assets=2)
    signal.iloc[1:] *= -1
    changed = run_backtest(signal, opening, closing, min_assets=2)
    pd.testing.assert_series_equal(original.iloc[1], changed.iloc[1])


def test_missing_held_exit_fails_instead_of_dropping_or_renormalizing():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    opening.iloc[2, 0] = np.nan
    with pytest.raises(ValueError, match='exit'):
        run_backtest(signal, opening, closing, min_assets=2)


def test_missing_held_entry_fails_even_with_a_valid_future_price():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    opening.iloc[1, 0] = np.nan
    with pytest.raises(ValueError, match='entry'):
        run_backtest(signal, opening, closing, min_assets=2)


def test_start_resets_to_cash_but_retains_lagged_signal():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    result = run_backtest(signal, opening, closing, min_assets=2, start=opening.index[2])
    assert result.index[0] == opening.index[2]
    assert result.turnover.iloc[0] == pytest.approx(1.)


def test_final_requested_day_uses_next_open_outside_requested_window():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    result = run_backtest(signal, opening, closing, min_assets=2,
                          start=opening.index[1], end=opening.index[1])
    assert len(result) == 1
    assert result.gross_return.iloc[0] == pytest.approx(.1)


def test_insufficient_assets_means_cash_and_costs_actual_exit():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    signal.iloc[1, 0] = np.nan
    result = run_backtest(signal, opening, closing, min_assets=2, cost_bps=10)
    assert result.n_assets.iloc[2] == 0
    assert result.turnover.iloc[2] == pytest.approx(1.)
    assert result.net_return.iloc[2] == pytest.approx(-.001)


def test_execution_lag_zero_rejected():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    with pytest.raises(ValueError, match='execution_lag'):
        run_backtest(signal, opening, closing, execution_lag=0)


def test_unknown_days_and_misaligned_prices_are_not_silently_filled():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    with pytest.raises(ValueError, match='index'):
        run_backtest(signal, opening.iloc[:-1], closing, min_assets=2)


def test_zero_signal_stays_cash_even_if_unheld_prices_are_missing():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    signal.loc[:, :] = 7.
    opening.iloc[2, 0] = np.nan
    result = run_backtest(signal, opening, closing, min_assets=2)
    assert result.gross_exposure.sum() == 0
    assert result.turnover.sum() == 0
    assert result.gross_return.iloc[:-1].tolist() == [0., 0., 0.]


def test_shift_two_uses_two_sessions_earlier_and_no_close_to_open_pnl():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    closing.loc[:, :] = 999.
    result = run_backtest(signal, opening, closing, min_assets=2, execution_lag=2)
    assert result.turnover.iloc[:3].tolist() == pytest.approx([0., 0., 1.])
    assert result.gross_return.iloc[:3].tolist() == pytest.approx([0., 0., 0.])


def test_unsorted_dates_and_duplicate_assets_are_rejected():
    from just_alpha101.backtest import run_backtest
    signal, opening, closing = panels()
    with pytest.raises(ValueError, match='increasing'):
        run_backtest(signal.iloc[::-1], opening.iloc[::-1], closing.iloc[::-1])
    signal.columns = ['A', 'A']
    with pytest.raises(ValueError, match='unique'):
        run_backtest(signal, opening, closing)

