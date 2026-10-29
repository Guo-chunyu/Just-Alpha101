"""Validated daily bars and explicit evidence checks; no missing-field imputation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import exchange_calendars as xcals

PRICE_FIELDS = ('open', 'high', 'low', 'close')


def validate_bars(frame: pd.DataFrame) -> None:
    required = {'date', 'symbol', 'volume', *PRICE_FIELDS}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f'Missing columns: {sorted(missing)}')
    if frame.empty:
        raise ValueError('No price observations')
    if frame[['date', 'symbol']].isna().any().any():
        raise ValueError('Missing date or symbol')
    if frame.duplicated(['date', 'symbol']).any():
        raise ValueError('duplicate security/date rows')
    prices = frame[list(PRICE_FIELDS)]
    if not np.isfinite(prices.to_numpy(dtype=float)).all() or (prices <= 0).any().any():
        raise ValueError('Nonpositive or nonfinite OHLC')
    tolerance = prices.abs().max(axis=1) * 1e-6
    if ((frame.high + tolerance < prices.max(axis=1)) |
            (frame.low - tolerance > prices.min(axis=1))).any():
        raise ValueError('Inconsistent OHLC range')
    volume = frame.volume.to_numpy(dtype=float)
    if not np.isfinite(volume).all() or (volume < 0).any():
        raise ValueError('Negative or nonfinite volume')


def normalize_wiki(frame: pd.DataFrame) -> pd.DataFrame:
    """Use source-adjusted prices/volume, retain raw bars for diagnostics.

    dollar_volume is *explicitly a proxy*: raw close times raw volume. It is not
    total traded dollar volume and cannot certify the literal paper ADV input.
    """
    needed = {'ticker', 'date', 'volume', 'adj_volume', *PRICE_FIELDS,
              *(f'adj_{field}' for field in PRICE_FIELDS)}
    if missing := needed - set(frame):
        raise ValueError(f'Missing WIKI columns: {sorted(missing)}')
    out = pd.DataFrame({'date': pd.to_datetime(frame.date), 'symbol': frame.ticker.astype(str)})
    for field in PRICE_FIELDS:
        out[field] = pd.to_numeric(frame[f'adj_{field}'])
        out[f'raw_{field}'] = pd.to_numeric(frame[field])
    out['volume'] = pd.to_numeric(frame.adj_volume)
    out['raw_volume'] = pd.to_numeric(frame.volume)
    out['dollar_volume'] = out.raw_close * out.raw_volume
    validate_bars(out)
    return out.sort_values(['date', 'symbol']).reset_index(drop=True)


def sessions(start: str, end: str) -> pd.DatetimeIndex:
    calendar = xcals.get_calendar('XNYS', start=pd.Timestamp(start) - pd.Timedelta(days=366),
                                 end=pd.Timestamp(end) + pd.Timedelta(days=366))
    return calendar.sessions_in_range(start, end).tz_localize(None)


def make_panel(frame: pd.DataFrame, dates=None) -> dict[str, pd.DataFrame]:
    validate_bars(frame)
    fields = [x for x in frame if x not in ('date', 'symbol')]
    panel = {name: frame.pivot(index='date', columns='symbol', values=name).sort_index()
             for name in fields}
    if dates is not None:
        panel = {name: values.reindex(dates) for name, values in panel.items()}
    return panel


def audit_data(frame: pd.DataFrame, provenance: dict, *, start='2010-01-04', end='2013-12-31') -> dict:
    validate_bars(frame)
    expected = sessions(start, end)
    in_period = frame[frame.date.between(pd.Timestamp(start), pd.Timestamp(end))]
    observed = pd.DatetimeIndex(in_period.date.unique()).sort_values()
    checks = {}

    def check(name, passed, detail):
        checks[name] = {'passed': bool(passed), 'detail': detail}

    def positive_field(name):
        if name not in frame:
            return False
        values = pd.to_numeric(frame[name], errors='coerce').to_numpy()
        return np.isfinite(values).all() and (values > 0).all()

    check('calendar', observed.equals(expected),
          f'{len(observed)} observed sessions, {len(expected)} expected XNYS sessions')
    per_symbol = in_period.groupby('symbol').date.nunique().reindex(frame.symbol.unique(), fill_value=0)
    check('complete_panel', (per_symbol == len(expected)).all(),
          'Conservative full-panel requirement; incomplete or changing membership needs a separately audited membership-aware adapter')
    check('true_vwap', positive_field('vwap') and provenance.get('vwap_is_trade_weighted') is True,
          'Requires actual daily trade-volume weighted price; OHLC proxies do not qualify')
    check('true_dollar_volume', positive_field('dollar_volume') and provenance.get('dollar_volume_is_actual') is True,
          'Raw close times volume is explicitly a proxy, not actual traded dollar value')
    check('historical_market_cap', positive_field('cap') and provenance.get('cap_is_point_in_time') is True,
          'Historical market capitalization is required for Alpha 56')
    groups = {'sector', 'industry', 'subindustry'}
    groups_complete = groups.issubset(frame) and all(
        frame[name].notna().all() and frame[name].astype(str).str.strip().ne('').all() for name in groups)
    check('point_in_time_industry', groups_complete and provenance.get('industry_is_point_in_time') is True,
          'Historical sector/industry/subindustry needed for 18 neutralized formulas')
    check('corporate_actions', provenance.get('corporate_actions_documented') is True,
          'Source-adjusted OHLCV must have documented split/dividend conventions')
    check('membership_and_delistings', provenance.get('membership_and_delistings_verified') is True,
          'No complete delisting coverage is inferred merely from a large symbol count')
    check('point_in_time_adjustments', provenance.get('adjustments_point_in_time') is True,
          'Retrospectively adjusted data are not proof of as-known-on-date input values')
    recent = sessions(str((pd.Timestamp(start) - pd.Timedelta(days=1200)).date()),
                      str((pd.Timestamp(start) - pd.Timedelta(days=1)).date()))[-500:]
    prior = frame[frame.date.isin(recent)].groupby('symbol').date.nunique()
    prior = prior.reindex(frame.symbol.unique(), fill_value=0)
    check('warmup', (prior >= 500).all(),
          f'Last 500 XNYS sessions immediately before evaluation required per symbol; minimum observed {int(prior.min())}; each factor also enforces full rolling windows')
    return {'strict_data_ready': all(item['passed'] for item in checks.values()),
            'exact_paper_replication_verifiable': False,
            'reason': 'Original universe, holdings mapping and execution details are not fully disclosed',
            'rows': len(frame), 'symbols': int(frame.symbol.nunique()),
            'start': str(frame.date.min().date()), 'end': str(frame.date.max().date()),
            'checks': checks, 'provenance': provenance}


def load_audited_data(path, provenance_path=None, *, start='2010-01-04', end='2013-12-31'):
    """Read one input and bind its audit to the exact bytes used in the experiment.

    A matching checksum establishes file identity, not truth of vendor claims.
    A custom input never inherits another dataset's evidence implicitly.
    """
    path = Path(path)
    with path.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    metadata = {}
    if provenance_path is not None:
        metadata = json.loads(Path(provenance_path).read_text(encoding='utf-8'))
        if not isinstance(metadata, dict):
            raise ValueError('Data provenance must be a JSON object')
        metadata = metadata.get('provenance', metadata)
        if not isinstance(metadata, dict):
            raise ValueError('Data provenance must be a JSON object')
    expected = metadata.get('processed_sha256')
    if expected is not None and expected != checksum:
        raise ValueError('Data provenance hash does not match the input file')
    data = pd.read_parquet(path) if path.suffix.lower() == '.parquet' else pd.read_csv(path)
    data['date'] = pd.to_datetime(data['date'], errors='raise')
    audit = audit_data(data, metadata, start=start, end=end)
    audit['input_file'] = path.name
    audit['input_sha256'] = checksum
    audit['checks']['provenance_file_binding'] = {
        'passed': expected == checksum,
        'detail': 'The source metadata processed_sha256 must identify this exact input; claims still need source verification',
    }
    audit['strict_data_ready'] = audit['strict_data_ready'] and expected == checksum
    return data, audit
