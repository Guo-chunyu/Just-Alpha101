"""Download a historical WIKI archive and build an explicitly biased diagnostic panel.

Raw prices stay local. No credentials are needed for the currently public mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from just_alpha101.data import normalize_wiki, audit_data, sessions


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download(url, path):
    if path.exists() and zipfile.is_zipfile(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.part')
    with requests.get(url, stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        with temporary.open('wb') as output:
            for chunk in response.iter_content(1024 * 1024):
                output.write(chunk)
    if not zipfile.is_zipfile(temporary):
        raise ValueError('Download did not return a ZIP archive')
    temporary.replace(path)


def prepare(config):
    archive = ROOT / 'data/raw/wiki.zip'
    download(config['download_url'], archive)
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        names = [name for name in zf.namelist() if name.lower().endswith('.csv')]
        if len(names) != 1:
            raise ValueError(f'Expected exactly one CSV; found {names}')
        name = names[0]
        print(f'Reading {name}; selecting universe using 2009 only', flush=True)
        selection = []
        total_rows = 0
        for chunk in pd.read_csv(zf.open(name), chunksize=300_000,
                                 usecols=['ticker', 'date', 'close', 'volume']):
            total_rows += len(chunk)
            rows = chunk[chunk.date.between(config['selection_start'], config['selection_end'])].copy()
            rows['liquidity'] = rows.close * rows.volume
            selection.append(rows[['ticker', 'liquidity']])
        ranked = pd.concat(selection).groupby('ticker').liquidity.agg(['mean', 'count'])
        ranked = ranked[ranked['count'] >= config['min_selection_observations']]
        ranked = ranked.sort_values(['mean', 'ticker'], ascending=[False, True])
        chosen = ranked.head(config['max_symbols']).index.tolist()
        del selection
        columns = ['ticker', 'date', 'open', 'high', 'low', 'close', 'volume',
                   'adj_open', 'adj_high', 'adj_low', 'adj_close', 'adj_volume']
        pieces = []
        for chunk in pd.read_csv(zf.open(name), chunksize=300_000, usecols=columns):
            rows = chunk[chunk.ticker.isin(chosen) & chunk.date.between(config['input_start'], config['input_end'])]
            pieces.append(rows)
        raw = pd.concat(pieces, ignore_index=True)
    print(f'Loaded {len(raw):,} rows for {len(chosen)} preselected names', flush=True)
    # Preserve counts and identities of every quality exclusion. Do not silently
    # fill missing historical bars or use future return to change trade weights.
    prices = raw[['adj_open', 'adj_high', 'adj_low', 'adj_close']]
    tolerance = prices.abs().max(axis=1) * 1e-6
    valid = (np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
             & (raw.adj_high + tolerance >= prices.max(axis=1))
             & (raw.adj_low - tolerance <= prices.min(axis=1))
             & np.isfinite(raw.adj_volume) & (raw.adj_volume >= 0)
             & np.isfinite(raw.volume) & (raw.volume >= 0)
             & np.isfinite(raw.close) & (raw.close > 0))
    invalid_count = int((~valid).sum())
    invalid_by_symbol = raw.loc[~valid].groupby('ticker').size().to_dict()
    normalized = normalize_wiki(raw.loc[valid].copy())
    expected = sessions(config['input_start'], config['input_end'])
    # This deliberately introduces a known survivorship/continuity bias. The
    # whole dataset stays uncertified. It permits an honest software experiment
    # without inventing liquidation prices for unobserved delistings.
    observed = normalized[normalized.date.isin(expected)].groupby('symbol').date.nunique()
    complete = observed[observed == len(expected)].index.tolist()
    excluded = sorted(set(chosen) - set(complete))
    cohort = normalized[normalized.symbol.isin(complete) & normalized.date.isin(expected)].copy()
    if len(complete) < config['minimum_assets']:
        raise ValueError(f'Only {len(complete)} complete histories; cannot run configured experiment')
    processed = ROOT / 'data/processed'
    processed.mkdir(parents=True, exist_ok=True)
    output = processed / 'wiki_diagnostic.parquet'
    cohort.to_parquet(output, index=False)
    provenance = {
        'source': 'Nasdaq/Quandl WIKI historical end-of-day archive, third-party Kaggle mirror',
        'source_page': config['source_page'], 'download_url': config['download_url'],
        'downloaded_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
        'archive_sha256': digest(archive), 'archive_bytes': archive.stat().st_size,
        'archive_member': name, 'archive_total_rows': total_rows,
        'processed_sha256': digest(output),
        'adjustment': 'Use provider adj_open/adj_high/adj_low/adj_close and adj_volume; retrospective vintage',
        'corporate_actions_documented': True, 'adjustments_point_in_time': False,
        'vwap_is_trade_weighted': False, 'dollar_volume_is_actual': False,
        'dollar_volume_definition': 'raw close multiplied by raw volume; close-based proxy only',
        'cap_is_point_in_time': False, 'industry_is_point_in_time': False,
        'membership_and_delistings_verified': False,
        'universe': config['universe_method'],
        'preselected_symbols': chosen, 'retained_symbols': sorted(complete),
        'continuity_excluded_symbols': excluded, 'invalid_rows_removed': invalid_count,
        'invalid_rows_by_symbol': invalid_by_symbol,
        'expected_full_panel_sessions': len(expected),
        'data_redistribution': 'Raw and processed market data are excluded from this repository',
        'license_note': 'Original WIKI was described by Nasdaq as public-domain; Kaggle mirror metadata says Unknown. No independent warranty of mirror provenance or license; no raw data redistributed.',
    }
    audit = audit_data(cohort, provenance, start=config['evaluation_start'], end=config['evaluation_end'])
    (reports / 'data_audit.json').write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding='utf-8')
    counts = pd.DataFrame({'symbol': chosen}).join(ranked, on='symbol')
    counts['retained_complete_history'] = counts.symbol.isin(complete)
    counts.to_csv(reports / 'universe.csv', index=False)
    print(json.dumps({'rows': len(cohort), 'symbols': len(complete), 'excluded': len(excluded),
                      'strict_data_ready': audit['strict_data_ready'], 'data_file': str(output)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/experiment.json')
    args = parser.parse_args()
    prepare(json.loads(args.config.read_text(encoding='utf-8')))
