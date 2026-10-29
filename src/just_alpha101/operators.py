"""Causal panel operators used by the published Alpha101 expressions.

Rows are dates and columns are securities. Rolling windows include today and
require every observation. Arg-extrema are one-based from the oldest day and
choose the first tie. ``signedpower`` follows the paper's literal x**a definition;
it is not the sign-preserving operator found in some later platforms.
"""
from __future__ import annotations

import builtins
import math

import numpy as np
import pandas as pd


def clean(value):
    """Represent undefined numeric results as NaN, never as infinity."""
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return value.replace([np.inf, -np.inf], np.nan)
    if np.isscalar(value):
        return value if np.isfinite(value) else np.nan
    return np.where(np.isfinite(value), value, np.nan)


def window(d, *, allow_zero=False):
    if not np.isscalar(d) or not np.isfinite(d) or d < 0:
        raise ValueError("A window/delay must be a finite nonnegative scalar")
    if allow_zero and d == 0:
        return 0
    return builtins.max(1, math.floor(d))


def _rolling(x, d):
    size = window(d)
    return clean(x).rolling(size, min_periods=size)


def rank(x, method="average"):
    return clean(x).rank(axis=1, method=method, pct=True, na_option="keep")


def delay(x, d):
    return clean(x).shift(window(d, allow_zero=True))


def delta(x, d):
    return clean(x - delay(x, d))


def correlation(x, y, d):
    result = _rolling(x, d).corr(clean(y), pairwise=False)
    valid = (stddev(x, d) > 0) & (stddev(y, d) > 0)
    return clean(result).where(valid)


def covariance(x, y, d):
    return clean(_rolling(x, d).cov(clean(y), pairwise=False, ddof=1))


def scale(x, a=1):
    x = clean(x)
    denominator = x.abs().sum(axis=1, min_count=1).replace(0, np.nan)
    return clean(x.div(denominator, axis=0) * a)


def signedpower(x, a):
    with np.errstate(all="ignore"):
        x, a = clean(x), clean(a)
        # NumPy treats NaN**0 and 1**NaN as one. A missing observation remains
        # unknown for research signals, regardless of these algebraic identities.
        base = float(x) if np.isscalar(x) else x
        result = clean(np.power(base, a))
        valid = pd.notna(x) & pd.notna(a)
        if isinstance(result, (pd.DataFrame, pd.Series)):
            return result.where(valid)
        return result if valid else np.nan


def decay_linear(x, d):
    size = window(d)
    weights = np.arange(1, size + 1, dtype=float)
    weights /= weights.sum()
    return clean(_rolling(x, size).apply(lambda values: np.dot(values, weights), raw=True))


def indneutralize(x, groups):
    """Demean each date within its observed group; missing labels stay missing."""
    if not isinstance(groups, pd.DataFrame) or not x.index.equals(groups.index) or not x.columns.equals(groups.columns):
        raise ValueError("Industry groups must be a DataFrame aligned with values")
    x = clean(x)
    result = pd.DataFrame(np.nan, index=x.index, columns=x.columns)
    for i in range(len(x)):
        row, labels = x.iloc[i], groups.iloc[i]
        group_mean = row.groupby(labels, dropna=True).transform("mean")
        result.iloc[i] = (row - group_mean).where(labels.notna())
    return clean(result)


def ts_min(x, d):
    return _rolling(x, d).min()


def ts_max(x, d):
    return _rolling(x, d).max()


def ts_argmin(x, d):
    return _rolling(x, d).apply(lambda values: np.argmin(values) + 1, raw=True)


def ts_argmax(x, d):
    return _rolling(x, d).apply(lambda values: np.argmax(values) + 1, raw=True)


def ts_rank(x, d, method="average"):
    return _rolling(x, d).rank(method=method, pct=True)


def sum(x, d):
    return clean(_rolling(x, d).sum())


def product(x, d):
    with np.errstate(all="ignore"):
        return clean(_rolling(x, d).apply(np.prod, raw=True))


def stddev(x, d):
    return clean(_rolling(x, d).std(ddof=1))


def log(x):
    with np.errstate(all="ignore"):
        return clean(np.log(x))


def abs(x):
    return clean(np.abs(x))


def sign(x):
    return clean(np.sign(x))


def minimum(x, y):
    return clean(np.minimum(x, y))


def maximum(x, y):
    return clean(np.maximum(x, y))


def min(x, other):
    """Paper's scalar-window form, overloaded for two panel expressions."""
    return ts_min(x, other) if np.isscalar(other) else minimum(x, other)


def max(x, other):
    return ts_max(x, other) if np.isscalar(other) else maximum(x, other)


def where(condition, yes, no):
    template = next((value for value in (condition, yes, no) if isinstance(value, pd.DataFrame)), None)
    if template is None:
        return np.nan if pd.isna(condition) else clean(yes if condition else no)
    mask = condition if isinstance(condition, pd.DataFrame) else pd.DataFrame(condition, index=template.index, columns=template.columns)
    selected = np.where(mask.fillna(0).astype(bool), yes, no)
    result = pd.DataFrame(selected, index=template.index, columns=template.columns)
    return clean(result).where(mask.notna())

