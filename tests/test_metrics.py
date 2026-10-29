import numpy as np
import pandas as pd
import pytest


def test_summary_fixed_capital_arithmetic_and_initial_wealth_drawdown():
    from just_alpha101.metrics import summarize
    daily = pd.DataFrame({'gross_return': [.1, -.05, .02, np.nan],
                          'net_return': [.1, -.05, .02, np.nan],
                          'turnover': [1., .2, .1, 10.]})
    result = summarize(daily)
    assert result['n_observations'] == 3
    assert result['annual_return'] == pytest.approx(5.88)
    assert result['daily_volatility'] == pytest.approx(np.sqrt(.005633333333333334))
    assert result['turnover'] == pytest.approx(13 / 30)
    assert result['holding_period'] == pytest.approx(30 / 13)
    assert result['total_return_fixed_capital'] == pytest.approx(.07)
    assert result['max_drawdown_fixed_capital'] == pytest.approx(-.05 / 1.1)
    assert result['total_return_compounded'] == pytest.approx(.0659)


def test_first_loss_is_a_drawdown_and_zero_turnover_holding_is_undefined():
    from just_alpha101.metrics import summarize
    result = summarize(pd.DataFrame({'net_return': [-.1, .02], 'turnover': [0., 0.]}))
    assert result['max_drawdown_fixed_capital'] == pytest.approx(-.1)
    assert np.isnan(result['holding_period'])


def test_rank_ic_uses_cross_sectional_ranks_and_counts_finite_pairs():
    from just_alpha101.metrics import rank_ic
    signal = pd.DataFrame([[1., 2., 3., np.nan], [1., 1., 1., 1.]])
    forward = pd.DataFrame([[30., 20., 10., 100.], [1., 2., 3., 4.]])
    result = rank_ic(signal, forward, min_assets=3)
    assert result.ic.iloc[0] == pytest.approx(-1.)
    assert result.n_assets.tolist() == [3, 4]
    assert np.isnan(result.ic.iloc[1])


def test_paper_stats_excludes_negative_means_from_logs_without_abs():
    from just_alpha101.metrics import paper_stats
    returns = pd.DataFrame({'a': [.01, .03, .02, .04],
                            'b': [-.01, -.03, -.02, -.04],
                            'c': [.02, .04, .03, .05],
                            'd': [.01, .05, .02, .08]})
    turnover = pd.DataFrame(.5, index=returns.index, columns=returns.columns)
    result = paper_stats(returns, turnover)
    reg = result['regressions']['return_volatility']
    assert reg['n_total'] == 4
    assert reg['nobs'] == 3
    assert reg['excluded'] == 1
    assert result['n_alphas'] == 4
    assert result['correlations']['n_pairs'] == 6
    assert result['alpha_metrics']['b']['annual_return'] < 0


def test_log_return_volatility_regression_recovers_known_power_law():
    from just_alpha101.metrics import paper_stats
    # Symmetric shocks have mean zero and sample std one. Set mean = 2*vol^1.5.
    shock = np.array([-1., 0., 1.])
    scales = np.array([.01, .02, .04, .08, .16])
    returns = pd.DataFrame({str(i): 2 * v ** 1.5 + v * shock for i, v in enumerate(scales)})
    turnover = pd.DataFrame({str(i): [.2 + i * .1] * 3 for i in range(5)})
    result = paper_stats(returns, turnover)
    regression = result['regressions']['return_volatility']
    assert regression['status'] == 'ok'
    assert regression['coefficients']['log_daily_volatility']['estimate'] == pytest.approx(1.5)
    assert regression['coefficients']['intercept']['estimate'] == pytest.approx(np.log(2.))
    assert regression['r_squared'] == pytest.approx(1.)


def test_paper_stats_rejects_unaligned_turnover_instead_of_matching_positions():
    from just_alpha101.metrics import paper_stats
    returns = pd.DataFrame({'a': [.1, .2]}, index=[1, 2])
    turnover = pd.DataFrame({'a': [.2, .3]}, index=[2, 3])
    with pytest.raises(ValueError, match='index'):
        paper_stats(returns, turnover)


def test_summary_rejects_an_internal_missing_pnl_instead_of_skipping_it():
    from just_alpha101.metrics import summarize
    daily = pd.DataFrame({'net_return': [.1, np.nan, -.2], 'turnover': [1., .4, .2]})
    with pytest.raises(ValueError, match='internal missing'):
        summarize(daily)


def test_paper_log_regressions_handle_constant_and_all_cash_alphas():
    from just_alpha101.metrics import paper_stats
    returns = pd.DataFrame({'cash': [0., 0., 0.], 'constant': [.1, .1, .1]})
    turnover = pd.DataFrame({'cash': [0., 0., 0.], 'constant': [1., .1, .1]})
    result = paper_stats(returns, turnover)
    assert result['regressions']['return_volatility']['status'] == 'insufficient_or_singular'
    assert result['correlations']['n_pairs'] == 0
    assert result['n_nonpositive_mean_returns'] == 1
    assert result['alpha_metrics']['constant']['daily_volatility'] == 0.
    assert np.isnan(result['alpha_metrics']['constant']['sharpe'])


def test_correlation_regression_centers_both_pair_predictors():
    from just_alpha101.metrics import paper_stats
    returns = .01 + .001 * pd.DataFrame({
        'a': [-1., 0., 1., 0.], 'b': [0., -1., 0., 1.],
        'c': [-1., -1., 1., 1.], 'd': [-1., 1., 1., -1.],
    })
    turnover = pd.DataFrame({key: [value] * 4 for key, value in
                              zip(returns.columns, [.1, .2, .4, .8])})
    reg = paper_stats(returns, turnover)['regressions']['correlation_turnover']
    assert reg['status'] == 'ok'
    # The six unique correlations are 0, 1/sqrt(2), 1/sqrt(2),
    # 1/sqrt(2), -1/sqrt(2), 0. Centered predictors make intercept their mean.
    assert reg['coefficients']['intercept']['estimate'] == pytest.approx(np.sqrt(2) / 6)
