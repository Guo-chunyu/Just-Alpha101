"""Run the frozen candidate grid; retain every candidate, skip missing fields explicitly."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from just_alpha101.data import make_panel, sessions
from just_alpha101.engine import FormulaEngine, MissingFieldError
from just_alpha101.formulas import FORMULAS, DELAY_ZERO
from just_alpha101.backtest import run_backtest
from just_alpha101.metrics import summarize, paper_stats, rank_ic


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def write_json(path, value):
    path.write_text(json.dumps(clean_json(value), indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def run(config, selected_ids=None, grid=True, *, data_path=None, output_dir=None, overwrite=False):
    started = time.monotonic()
    costs = config['cost_bps']
    if not costs or any(not np.isfinite(value) or value < 0 for value in costs):
        raise ValueError('cost_bps must contain finite nonnegative values')
    folder = Path(output_dir) if output_dir is not None else ROOT / 'reports'
    folder.mkdir(parents=True, exist_ok=True)
    generated = [folder / name for name in ('metrics.csv', 'factor_coverage.csv', 'paper_comparison.json',
                                            'baseline_correlation.csv', 'run_manifest.json')]
    generated.extend(folder.glob('daily_*.csv.gz'))
    previous = [path for path in generated if path.exists()]
    if previous and not overwrite:
        raise FileExistsError('Output already contains experiment results. Use a separate --output or explicitly --overwrite.')
    for path in previous:
        # Individual known generated files only; never touch the data audit or user files.
        if path.resolve().parent != folder.resolve():
            raise ValueError('Generated output resolves outside the output directory')
        path.unlink()
    data_path = Path(data_path) if data_path is not None else ROOT / 'data/processed/wiki_diagnostic.parquet'
    data = pd.read_parquet(data_path) if data_path.suffix == '.parquet' else pd.read_csv(data_path, parse_dates=['date'])
    data['date'] = pd.to_datetime(data['date'], errors='raise')
    panel = make_panel(data, sessions(config['input_start'], config['input_end']))
    engine_fields = {key: panel[key] for key in ('open', 'high', 'low', 'close', 'volume', 'dollar_volume',
                                               'vwap', 'cap', 'sector', 'industry', 'subindustry') if key in panel}
    lag = config['execution_lag']
    next_session = pd.Series(panel['open'].index, index=panel['open'].index).shift(-1)
    # On signal date t, the aligned forward return runs open[t+lag] -> open[t+lag+1].
    forward = panel['open'].shift(-(lag + 1)) / panel['open'].shift(-lag) - 1
    ids = selected_ids or sorted(FORMULAS)
    scales = config['window_scales'] if grid else [1.0]
    bases = config['adv_bases'] if grid else ['dollar']
    all_metrics, coverage = [], []
    baseline_returns, baseline_turnover = {}, {}
    for basis in bases:
        for multiplier in scales:
            engine = FormulaEngine(engine_fields, adv_basis=basis, window_scale=multiplier)
            label = f'{basis}_w{multiplier:g}'
            day_results = []
            print(f'Running {label}', flush=True)
            for alpha_id in ids:
                start = time.monotonic()
                try:
                    signal = engine.compute(alpha_id)
                except MissingFieldError as exc:
                    coverage.append(dict(candidate=label, alpha=alpha_id, status='missing_fields',
                                         missing_fields=','.join(sorted(exc.missing_fields))))
                    continue
                daily = run_backtest(signal, panel['open'], panel['close'],
                                     start=config['evaluation_start'], end=config['evaluation_end'],
                                     execution_lag=config['execution_lag'], min_assets=config['minimum_assets'])
                coverage.append(dict(candidate=label, alpha=alpha_id, status='computed', missing_fields='',
                                     mean_signal_coverage=float(signal.loc[config['evaluation_start']:config['evaluation_end']].notna().mean().mean()),
                                     active_days=int((daily.gross_exposure > 0).sum()),
                                     paper_delay=0 if alpha_id in DELAY_ZERO else 1,
                                     experiment_delay=config['execution_lag']))
                ic = rank_ic(signal, forward, min_assets=config['minimum_assets'])
                # Split by BOTH entry and exit dates. Purge the interval that
                # enters in 2012 and exits in 2013 from development statistics.
                exit_dates = next_session.reindex(daily.index)
                masks = {
                    'full_2010_2013': np.ones(len(daily), dtype=bool),
                    'development_2010_2012': (exit_dates <= pd.Timestamp(config['development_end'])).to_numpy(),
                    'holdout_2013': (daily.index >= pd.Timestamp(config['holdout_start'])),
                }
                for period, mask in masks.items():
                    subset = daily.loc[mask]
                    # IC signals are labeled t; intervals follow configured lag.
                    ic_start = pd.Timestamp(config['evaluation_start']) if period != 'holdout_2013' else pd.Timestamp(config['holdout_start'])
                    ic_end = pd.Timestamp(config['development_end']) if period == 'development_2010_2012' else pd.Timestamp(config['evaluation_end'])
                    entry = next_session.shift(-(lag - 1))
                    exit_ic = next_session.shift(-lag)
                    ic_mask = (entry >= ic_start) & (entry <= ic_end)
                    if period == 'development_2010_2012':
                        ic_mask &= exit_ic <= ic_end
                    ic_values = ic.loc[ic_mask, 'ic'].dropna()
                    for cost in config['cost_bps']:
                        after_cost = subset.copy()
                        after_cost['net_return'] = after_cost.gross_return - after_cost.turnover * cost / 10000
                        metrics = summarize(after_cost)
                        all_metrics.append(dict(candidate=label, alpha=alpha_id, window_scale=multiplier,
                                                adv_basis=basis, period=period, cost_bps=cost,
                                                rank_ic_mean=float(ic_values.mean()), rank_ic_days=len(ic_values),
                                                **metrics))
                daily['alpha'] = alpha_id
                day_results.append(daily.reset_index())
                if basis == 'dollar' and multiplier == 1.0:
                    baseline_returns[str(alpha_id)] = daily.gross_return
                    baseline_turnover[str(alpha_id)] = daily.turnover
                print(f'  alpha {alpha_id:03}: {time.monotonic()-start:.1f}s; active {int((daily.gross_exposure>0).sum())}/{len(daily)}', flush=True)
            if day_results:
                pd.concat(day_results, ignore_index=True).to_csv(folder / f'daily_{label}.csv.gz', index=False, compression='gzip')
            # Incremental results retain work if an external interruption occurs.
            pd.DataFrame(all_metrics).to_csv(folder / 'metrics.csv', index=False)
            pd.DataFrame(coverage).to_csv(folder / 'factor_coverage.csv', index=False)
    if baseline_returns:
        returns = pd.DataFrame(baseline_returns)
        turnover = pd.DataFrame(baseline_turnover)
        write_json(folder / 'paper_comparison.json', paper_stats(returns, turnover))
        returns.corr().to_csv(folder / 'baseline_correlation.csv')
    config_bytes = json.dumps(config, sort_keys=True).encode()
    code_files = sorted((ROOT / 'src').rglob('*.py')) + [Path(__file__), ROOT / 'scripts/prepare_data.py']
    code_hash = hashlib.sha256()
    for file in code_files:
        code_hash.update(str(file.relative_to(ROOT)).replace('\\', '/').encode())
        code_hash.update(file.read_bytes())
    write_json(folder / 'run_manifest.json', {
        'completed_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
        'elapsed_seconds': time.monotonic()-started,
        'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__,
        'config_sha256': hashlib.sha256(config_bytes).hexdigest(), 'code_sha256': code_hash.hexdigest(),
        'config': config, 'data_audit_file': 'data_audit.json', 'selected_ids': ids,
        'input_file': data_path.name,
        'mode': 'full_predeclared_grid' if grid else 'baseline_only',
        'strict_paper_reproduction': False,
        'scope': 'Available-input factors only. No substitute VWAP, cap or industry.',
        'period_boundary': 'Development excludes any interval ending in 2013. Full/holdout last entry 2013-12-31 exits 2014-01-02.',
        'window_interpretation': 'Only temporal operator windows and ADV windows are scaled; arithmetic constants/divisors are fixed.',
        'portfolio': 'Demean signal, unit L1 gross, next-open entry, following-open return, constant capital. No terminal liquidation.',
        'holdout_note': 'Project-local holdout; original formulas were published after this period.',
    })
    print(f'Finished {len(all_metrics)} metric rows in {time.monotonic()-started:.1f}s', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/experiment.json')
    parser.add_argument('--alphas', help='Comma-separated subset for debugging; do not mix with full-run output')
    parser.add_argument('--baseline-only', action='store_true')
    parser.add_argument('--data', type=Path, help='Standard long-table CSV/Parquet with optional true VWAP/cap/industry fields')
    parser.add_argument('--output', type=Path, help='Separate directory for custom data or debug runs')
    parser.add_argument('--overwrite', action='store_true', help='Replace only known experiment output files')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    run(config, [int(x) for x in args.alphas.split(',')] if args.alphas else None,
        not args.baseline_only, data_path=args.data, output_dir=args.output, overwrite=args.overwrite)
