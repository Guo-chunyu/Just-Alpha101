"""Causal daily, fixed-capital, dollar-neutral research backtests.

Prices must already share a consistent corporate-action adjustment convention.
The data source must include a session after the desired final entry session.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def run_backtest(
    signal: pd.DataFrame,
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    *,
    cost_bps: float = 0.0,
    execution_lag: int = 1,
    start=None,
    end=None,
    min_assets: int = 10,
) -> pd.DataFrame:
    """Trade lagged signals at the open and mark them at the following open.

    Rows are labeled by ENTRY date. Target weights use only finite signals and
    positive closing prices on the signal date, demeaned and normalized to unit
    gross exposure. Fewer than ``min_assets`` eligible names, or a constant
    signal, means cash. Entry/exit prices never determine target membership.

    Turnover is the sum of absolute traded dollars divided by constant gross
    capital, including the first entry. Pre-trade positions reflect price drift;
    there is no one-half convention and no compounding of the capital budget.
    Costs are proportional to this turnover. Missing prices for held positions
    fail explicitly; no forward fill or hindsight reweighting is performed.

    ``start`` resets holdings to cash but retains earlier rows for signal lag.
    ``end`` selects entry dates; their following-open exits may be outside it.
    The last data row has unavailable forward P&L (NaN), with no invented exit.
    """
    frames = {'signal': signal, 'open_prices': open_prices, 'close_prices': close_prices}
    for name, frame in frames.items():
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f'{name} must be a DataFrame')
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise ValueError(f'{name} index must be a DatetimeIndex')
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError(f'{name} index must be unique and increasing')
        if not frame.columns.is_unique:
            raise ValueError(f'{name} columns must be unique')
        if not frame.index.equals(signal.index):
            raise ValueError('signal and price index must match exactly')
        if set(frame.columns) != set(signal.columns):
            raise ValueError('signal and price asset columns must match exactly')
    if isinstance(execution_lag, bool) or not isinstance(execution_lag, (int, np.integer)) or execution_lag < 1:
        raise ValueError('execution_lag must be an integer of at least 1')
    if isinstance(min_assets, bool) or not isinstance(min_assets, (int, np.integer)) or min_assets < 2:
        raise ValueError('min_assets must be an integer of at least 2')
    if not np.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError('cost_bps must be finite and nonnegative')
    if start is not None and end is not None and pd.Timestamp(start) > pd.Timestamp(end):
        raise ValueError('start must not be after end')

    dates, names = signal.index, signal.columns
    opening = open_prices.reindex(columns=names).to_numpy(dtype=float)
    closing = close_prices.reindex(columns=names).to_numpy(dtype=float)
    signals = signal.to_numpy(dtype=float)
    selected = np.ones(len(dates), dtype=bool)
    if start is not None:
        selected &= dates >= pd.Timestamp(start)
    if end is not None:
        selected &= dates <= pd.Timestamp(end)
    pretrade = np.zeros(len(names))
    rows = []

    for i in np.flatnonzero(selected):
        target = np.zeros(len(names))
        source = i - execution_lag
        eligible_count = 0
        if source >= 0:
            eligible = np.isfinite(signals[source]) & np.isfinite(closing[source]) & (closing[source] > 0)
            eligible_count = int(eligible.sum())
            if eligible_count >= min_assets:
                centered = signals[source, eligible] - signals[source, eligible].mean()
                gross = np.abs(centered).sum()
                if gross > 0 and np.isfinite(gross):
                    target[eligible] = centered / gross

        held = target != 0
        traded = np.abs(target - pretrade) > 0
        bad_entry = (held | traded) & (~np.isfinite(opening[i]) | (opening[i] <= 0))
        if bad_entry.any():
            raise ValueError(f'Invalid entry price on {dates[i].date()} for {list(names[bad_entry])}')
        turnover = float(np.abs(target - pretrade).sum())
        cost = turnover * cost_bps / 10_000.0
        pnl = np.nan
        if i + 1 < len(dates):
            bad_exit = held & (~np.isfinite(opening[i + 1]) | (opening[i + 1] <= 0))
            if bad_exit.any():
                raise ValueError(f'Invalid exit price on {dates[i + 1].date()} for {list(names[bad_exit])}')
            asset_return = np.zeros(len(names))
            asset_return[held] = opening[i + 1, held] / opening[i, held] - 1.0
            pnl = float(np.dot(target, asset_return))
            pretrade = target * (1.0 + asset_return)
        rows.append({
            'date': dates[i], 'gross_return': pnl, 'net_return': pnl - cost,
            'turnover': turnover, 'cost_return': cost,
            'gross_exposure': float(np.abs(target).sum()),
            'net_exposure': float(target.sum()), 'n_assets': int(held.sum()),
            'eligible_assets': eligible_count,
        })
    columns = ['gross_return', 'net_return', 'turnover', 'cost_return',
               'gross_exposure', 'net_exposure', 'n_assets', 'eligible_assets']
    if rows:
        result = pd.DataFrame(rows).set_index('date')
    else:
        result = pd.DataFrame(columns=columns, index=pd.DatetimeIndex([], name='date'))
    result.attrs.update({
        'return_interval': 'entry open to following session open',
        'capital_convention': 'constant gross capital; arithmetic daily P&L',
        'turnover_convention': 'sum absolute traded dollars / constant gross capital',
        'execution_lag': int(execution_lag), 'cost_bps': float(cost_bps),
        'terminal_liquidation': False,
    })
    return result
