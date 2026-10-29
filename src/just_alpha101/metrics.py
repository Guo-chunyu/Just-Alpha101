"""Transparent fixed-capital metrics and descriptive paper-style regressions."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def _aligned(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    if not left.index.equals(right.index):
        raise ValueError('DataFrame index must match exactly')
    if not left.index.is_unique or not left.columns.is_unique or not right.columns.is_unique:
        raise ValueError('DataFrame index and columns must be unique')
    if set(left.columns) != set(right.columns):
        raise ValueError('DataFrame columns must match exactly')
    return right.reindex(columns=left.columns)


def summarize(daily: pd.DataFrame, *, return_column: str = 'net_return') -> dict:
    """Summarize finite daily P&L, aligning turnover to the observed returns.

    Annual return is mean daily fixed-capital P&L times 252, never CAGR.
    Drawdowns include initial wealth 1. Compounded results are separately named
    hypothetical diagnostics and are not used for the paper-style statistics.
    """
    raw = daily[return_column].astype(float)
    if np.isinf(raw.to_numpy()).any():
        raise ValueError('returns contain infinity')
    valid = raw.notna()
    observed_positions = np.flatnonzero(valid)
    if len(observed_positions) and not valid.iloc[observed_positions[0]:observed_positions[-1] + 1].all():
        raise ValueError('returns contain an internal missing P&L observation')
    returns = raw[valid]
    turnover = daily.loc[valid, 'turnover'].astype(float)
    if (~np.isfinite(turnover) | (turnover < 0)).any():
        raise ValueError('observed-return days require finite nonnegative turnover')
    n = len(returns)
    mean = float(returns.mean()) if n else np.nan
    volatility = (float(returns.std(ddof=1)) if returns.nunique() > 1 else 0.0) if n > 1 else np.nan
    turn = float(turnover.mean()) if n else np.nan
    fixed = np.r_[1.0, 1.0 + returns.to_numpy().cumsum()]
    compounded = np.r_[1.0, np.cumprod(1.0 + returns.to_numpy())]
    return {
        'n_observations': n, 'n_missing': int((~valid).sum()),
        'daily_return': mean, 'annual_return': mean * 252,
        'daily_volatility': volatility, 'annual_volatility': volatility * np.sqrt(252),
        'sharpe': float(mean / volatility * np.sqrt(252)) if volatility > 0 else np.nan,
        'turnover': turn, 'holding_period': 1.0 / turn if turn > 0 else np.nan,
        'total_return_fixed_capital': float(fixed[-1] - 1) if n else np.nan,
        'max_drawdown_fixed_capital': float(np.min(fixed / np.maximum.accumulate(fixed) - 1)) if n else np.nan,
        'total_return_compounded': float(compounded[-1] - 1) if n else np.nan,
        'max_drawdown_compounded': float(np.min(compounded / np.maximum.accumulate(compounded) - 1)) if n else np.nan,
        'cents_per_share': np.nan,
        'cents_per_share_status': 'unavailable: requires unadjusted execution prices and share quantities',
    }


def rank_ic(signal: pd.DataFrame, forward_returns: pd.DataFrame, *, min_assets: int = 10) -> pd.DataFrame:
    """Datewise Spearman IC with pair counts; forward returns are supplied by caller."""
    forward_returns = _aligned(signal, forward_returns)
    if min_assets < 2:
        raise ValueError('min_assets must be at least 2')
    paired = np.isfinite(signal) & np.isfinite(forward_returns)
    ranks_signal = signal.where(paired).rank(axis=1)
    ranks_returns = forward_returns.where(paired).rank(axis=1)
    count = paired.sum(axis=1)
    centered_signal = ranks_signal.sub(ranks_signal.mean(axis=1), axis=0)
    centered_returns = ranks_returns.sub(ranks_returns.mean(axis=1), axis=0)
    numerator = (centered_signal * centered_returns).sum(axis=1)
    denominator = np.sqrt((centered_signal ** 2).sum(axis=1) * (centered_returns ** 2).sum(axis=1))
    ic = (numerator / denominator.where(denominator > 0)).where(count >= min_assets)
    return pd.DataFrame({'ic': ic, 'n_assets': count})


def _summary(values) -> dict:
    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data)]
    if not len(data):
        return dict(n=0, minimum=np.nan, q25=np.nan, median=np.nan, mean=np.nan, q75=np.nan, maximum=np.nan)
    return dict(n=len(data), minimum=float(data.min()), q25=float(np.quantile(data, .25)),
                median=float(np.median(data)), mean=float(data.mean()),
                q75=float(np.quantile(data, .75)), maximum=float(data.max()))


def _ols(y, predictors: dict[str, np.ndarray], *, n_total: int) -> dict:
    y = np.asarray(y, dtype=float)
    x = np.column_stack([np.ones(len(y)), *[np.asarray(v, dtype=float) for v in predictors.values()]])
    keep = np.isfinite(y) & np.isfinite(x).all(axis=1)
    y, x = y[keep], x[keep]
    n, p = x.shape
    base = {'nobs': n, 'n_total': int(n_total), 'excluded': int(n_total - n),
            'df_model': p - 1, 'df_resid': n - p}
    if n <= p or np.linalg.matrix_rank(x) < p:
        return {**base, 'status': 'insufficient_or_singular', 'coefficients': {}}
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    residual = y - x @ beta
    sse = float(residual @ residual)
    sst = float((y - y.mean()) @ (y - y.mean()))
    df = n - p
    variance = sse / df
    covariance = variance * np.linalg.pinv(x.T @ x)
    standard_error = np.sqrt(np.maximum(np.diag(covariance), 0))
    t = np.divide(beta, standard_error, out=np.full(p, np.nan), where=standard_error > 0)
    r_squared = 1 - sse / sst if sst > 0 else np.nan
    f_statistic = ((sst - sse) / (p - 1)) / variance if variance > 0 and p > 1 else np.nan
    names = ['intercept', *predictors]
    coefficients = {name: {'estimate': float(beta[i]), 'std_error': float(standard_error[i]),
                           't': float(t[i]), 'p_value': float(2 * stats.t.sf(abs(t[i]), df))}
                    for i, name in enumerate(names)}
    return {**base, 'status': 'ok', 'coefficients': coefficients, 'r_squared': float(r_squared),
            'adjusted_r_squared': float(1 - (1 - r_squared) * (n - 1) / df),
            'f_statistic': float(f_statistic), 'f_p_value': float(stats.f.sf(f_statistic, p - 1, df))}


def paper_stats(returns: pd.DataFrame, turnover: pd.DataFrame) -> dict:
    """Compute Table-1-style summaries and four descriptive cross-sectional OLS fits.

    Input returns should be GROSS daily P&L for comparison with the paper, whose
    reported results exclude transaction costs. Negative/zero mean returns are
    counted and excluded from log-return fits, never replaced by absolute values.
    Return means/volatilities use each alpha's observed contiguous interval;
    internal missing P&L fails. Pairwise correlations use pairwise complete
    observations, with counts disclosed. OLS standard errors are conventional,
    descriptive values; correlation pairs are dependent observations.
    """
    turnover = _aligned(returns, turnover)
    if np.isinf(returns.to_numpy(dtype=float)).any():
        raise ValueError('returns contain infinity')
    metrics = {str(name): summarize(pd.DataFrame({'net_return': returns[name], 'turnover': turnover[name]}))
               for name in returns.columns}
    alpha = pd.DataFrame.from_dict(metrics, orient='index')
    if not len(alpha):
        return {'n_alphas': 0, 'alpha_metrics': {}, 'summary': {}, 'correlations': {'n_pairs': 0}, 'regressions': {}}
    summary = {key: _summary(alpha[key]) for key in
               ['sharpe', 'turnover', 'holding_period', 'daily_volatility', 'annual_return']}
    corr = returns.corr(min_periods=2)
    valid = returns.notna().to_numpy(dtype=np.int64)
    pair_counts = valid.T @ valid
    lower = np.tril_indices(len(corr), k=-1)
    correlation_values = corr.to_numpy()[lower]
    finite_pairs = np.isfinite(correlation_values)
    summary['pair_correlation'] = _summary(correlation_values)
    correlations = {
        'n_pairs': int(finite_pairs.sum()), 'n_possible_pairs': len(correlation_values),
        'min_pair_observations': int(pair_counts[lower][finite_pairs].min()) if finite_pairs.any() else 0,
        'max_pair_observations': int(pair_counts[lower][finite_pairs].max()) if finite_pairs.any() else 0,
        'matrix': {str(name): {str(other): float(value) for other, value in row.items()} for name, row in corr.to_dict().items()},
    }
    # Mask before logarithm: this avoids inventing positive returns or log warnings.
    log_return = np.log(alpha.daily_return.where(alpha.daily_return > 0).astype(float)).to_numpy()
    log_vol = np.log(alpha.daily_volatility.where(alpha.daily_volatility > 0).astype(float)).to_numpy()
    log_turn = np.log(alpha.turnover.where(alpha.turnover > 0).astype(float)).to_numpy()
    n = len(alpha)
    regressions = {
        'return_volatility': _ols(log_return, {'log_daily_volatility': log_vol}, n_total=n),
        'return_volatility_turnover': _ols(log_return, {'log_daily_volatility': log_vol, 'log_turnover': log_turn}, n_total=n),
        'volatility_turnover': _ols(log_vol, {'log_turnover': log_turn}, n_total=n),
    }
    positive_turn = np.isfinite(log_turn)
    normalized_turn = log_turn - log_turn[positive_turn].mean() if positive_turn.any() else log_turn
    i, j = lower
    pair_sum = normalized_turn[i] + normalized_turn[j]
    pair_product = normalized_turn[i] * normalized_turn[j]
    valid_predictors = np.isfinite(correlation_values) & np.isfinite(pair_sum) & np.isfinite(pair_product)
    if valid_predictors.any():
        pair_sum -= pair_sum[valid_predictors].mean()
        pair_product -= pair_product[valid_predictors].mean()
    regressions['correlation_turnover'] = _ols(correlation_values, {
        'log_turnover_sum': pair_sum,
        'log_turnover_product': pair_product,
    }, n_total=len(correlation_values))
    return {
        'n_alphas': n, 'alpha_metrics': metrics, 'summary': summary, 'correlations': correlations,
        'regressions': regressions,
        'n_nonpositive_mean_returns': int((alpha.annual_return <= 0).sum()),
        'observation_policy': 'per-alpha contiguous observed intervals; pairwise complete correlations',
        'inference_note': 'OLS standard errors are descriptive; alpha correlation pairs are dependent observations',
        'cents_per_share_status': 'unavailable: raw execution share quantities are not supplied',
    }
