"""Runner integration: real bars, formulas, backtests, reports and period splits."""

import importlib.util
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from just_alpha101.data import sessions


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "scripts" / "run_experiments.py"
    spec = importlib.util.spec_from_file_location("alpha101_experiment_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    runner_copy = scripts / "run_experiments.py"
    runner_copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (scripts / "prepare_data.py").write_text("# Fixture provenance preparation\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(runner_copy))

    dates = sessions("2012-12-24", "2013-01-04")
    # Intraday Alpha101 ordering and the next-open return ordering alternate.
    # A two-session signal delay matches that ordering exactly: IC must be +1.
    # A one-session delay reverses it, so an accidental hardcoded lag gives -1.
    asset_direction = np.array([1.0, 0.0, -1.0])
    opening = np.full((len(dates), 3), 100.0)
    for row in range(1, len(dates)):
        opening[row] = opening[row - 1] * (1 + .02 * (-1)**(row - 1) * asset_direction)
    closing = opening * (1 + .01 * (-1.0)**np.arange(len(dates))[:, None] * asset_direction)
    rows = []
    for row, date in enumerate(dates):
        for col, symbol in enumerate(["A", "B", "C"]):
            rows.append({"date": date, "symbol": symbol, "open": opening[row, col],
                         "close": closing[row, col], "high": max(opening[row, col], closing[row, col]) * 1.02,
                         "low": min(opening[row, col], closing[row, col]) * .98,
                         "volume": 1000.0, "dollar_volume": opening[row, col] * 1000})
    data_path = tmp_path / "data" / "processed"
    data_path.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(data_path / "wiki_diagnostic.parquet", index=False)
    config = {
        "input_start": "2012-12-24", "input_end": "2013-01-04",
        "evaluation_start": "2012-12-27", "evaluation_end": "2013-01-03",
        "development_end": "2012-12-31", "holdout_start": "2013-01-02",
        "window_scales": [1.0, 1.2], "adv_bases": ["dollar", "shares"],
        "cost_bps": [0, 5], "execution_lag": 2, "minimum_assets": 3,
    }
    return module, config, tmp_path


def test_runner_ic_horizon_follows_configured_execution_lag(experiment):
    module, config, root = experiment
    module.run(config, selected_ids=[101], grid=False)
    report = pd.read_csv(root / "reports" / "metrics.csv")
    np.testing.assert_allclose(report.rank_ic_mean, 1.0)
    observed_days = report.groupby("period").rank_ic_days.first().to_dict()
    assert observed_days == {"full_2010_2013": 5, "development_2010_2012": 2, "holdout_2013": 2}


def test_runner_purges_cross_boundary_pnl_and_retains_every_grid_case(experiment):
    module, config, root = experiment
    module.run(config, selected_ids=[101, 56], grid=True)
    report = pd.read_csv(root / "reports" / "metrics.csv")
    coverage = pd.read_csv(root / "reports" / "factor_coverage.csv")
    assert len(report) == 4 * 3 * 2  # Four candidates, three periods, two costs.
    assert report.alpha.unique().tolist() == [101]
    assert len(coverage) == 8
    assert set(coverage.loc[coverage.alpha == 56, "status"]) == {"missing_fields"}
    assert set(coverage.loc[coverage.alpha == 56, "missing_fields"]) == {"cap"}
    counts = report.groupby("period").n_observations.first().to_dict()
    # Dec31 -> Jan2 is neither development nor holdout, but is in full history.
    assert counts == {"full_2010_2013": 5, "development_2010_2012": 2, "holdout_2013": 2}
    for _, group in report.groupby(["candidate", "period"]):
        gross = group.loc[group.cost_bps == 0].iloc[0]
        charged = group.loc[group.cost_bps == 5].iloc[0]
        assert charged.daily_return == pytest.approx(gross.daily_return - gross.turnover * .0005)
    manifest = json.loads((root / "reports" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["strict_paper_reproduction"] is False


@pytest.mark.parametrize("cost", [-5, np.nan, np.inf])
def test_runner_rejects_invalid_cost_grid_instead_of_reporting_rebates(experiment, cost):
    module, config, _ = experiment
    config["cost_bps"] = [cost]
    with pytest.raises(ValueError):
        module.run(config, selected_ids=[101], grid=False)


def test_parquet_string_dates_cannot_silently_become_an_all_cash_backtest(experiment):
    module, config, root = experiment
    data_path = root / "data" / "processed" / "wiki_diagnostic.parquet"
    bars = pd.read_parquet(data_path)
    bars["date"] = bars.date.dt.strftime("%Y-%m-%d")
    bars.to_parquet(data_path, index=False)
    module.run(config, selected_ids=[101], grid=False)
    coverage = pd.read_csv(root / "reports" / "factor_coverage.csv")
    assert coverage.active_days.tolist() == [5]


def test_existing_results_require_explicit_overwrite_and_do_not_survive_missing_inputs(experiment):
    module, config, root = experiment
    module.run(config, selected_ids=[101], grid=False)
    old = root / 'reports' / 'paper_comparison.json'
    assert old.exists()
    with pytest.raises(FileExistsError):
        module.run(config, selected_ids=[56], grid=False)
    module.run(config, selected_ids=[56], grid=False, overwrite=True)
    assert not old.exists()
    assert not (root / 'reports' / 'daily_dollar_w1.csv.gz').exists()
    coverage = pd.read_csv(root / 'reports' / 'factor_coverage.csv')
    assert coverage.status.tolist() == ['missing_fields']


def test_strict_data_gate_rejects_incomplete_inputs_before_replacing_results(experiment):
    module, config, root = experiment
    folder = root / 'reports'
    folder.mkdir()
    saved = folder / 'metrics.csv'
    saved.write_text('previous verified results', encoding='utf-8')
    with pytest.raises(ValueError, match='Strict data requirements failed'):
        module.run(config, selected_ids=[101], grid=False, overwrite=True, require_strict_data=True)
    assert saved.read_text(encoding='utf-8') == 'previous verified results'


def test_custom_input_records_its_own_hash_and_audit_not_an_unrelated_default(experiment):
    module, config, root = experiment
    source = root / 'data' / 'processed' / 'wiki_diagnostic.parquet'
    output = root / 'reports' / 'custom'
    module.run(config, selected_ids=[101], grid=False, data_path=source, output_dir=output)
    manifest = json.loads((output / 'run_manifest.json').read_text(encoding='utf-8'))
    audit = json.loads((output / 'data_audit.json').read_text(encoding='utf-8'))
    assert manifest['input_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert manifest['strict_data_ready'] is False
    assert audit['strict_data_ready'] is False
    assert audit['rows'] == len(pd.read_parquet(source))


def test_provenance_for_different_file_is_rejected_without_destroying_outputs(experiment):
    module, config, root = experiment
    metadata = root / 'wrong_source.json'
    metadata.write_text(json.dumps({'processed_sha256': '0' * 64}), encoding='utf-8')
    output = root / 'reports'
    output.mkdir()
    saved = output / 'metrics.csv'
    saved.write_text('keep', encoding='utf-8')
    with pytest.raises(ValueError, match='provenance.*hash'):
        module.run(config, selected_ids=[101], grid=False, overwrite=True, provenance_path=metadata)
    assert saved.read_text(encoding='utf-8') == 'keep'


def test_strict_gate_can_accept_a_complete_bound_fixture_without_claiming_paper_replication(experiment):
    module, config, root = experiment
    source = root / 'data' / 'processed' / 'wiki_diagnostic.parquet'
    data = pd.read_parquet(source)
    history = sessions('2010-01-01', '2012-12-26')[-500:]
    first = data.groupby('symbol').head(1).copy()
    copies = [first.assign(date=date) for date in history]
    data = pd.concat([*copies, data[data.date >= config['evaluation_start']]], ignore_index=True)
    data['vwap'] = data.close
    data['cap'] = 1_000_000.0
    for group in ('sector', 'industry', 'subindustry'):
        data[group] = 'synthetic-test-group'
    data.to_parquet(source, index=False)
    config['input_start'] = str(history[0].date())
    metadata = root / 'fixture_evidence.json'
    metadata.write_text(json.dumps(dict(
        source='Synthetic test only: no empirical evidence',
        processed_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        vwap_is_trade_weighted=True, dollar_volume_is_actual=True,
        cap_is_point_in_time=True, industry_is_point_in_time=True,
        corporate_actions_documented=True, adjustments_point_in_time=True,
        membership_and_delistings_verified=True)), encoding='utf-8')
    module.run(config, selected_ids=[101], grid=False, provenance_path=metadata, require_strict_data=True)
    manifest = json.loads((root / 'reports' / 'run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['strict_data_ready'] is True
    assert manifest['strict_data_required'] is True
    assert manifest['strict_paper_reproduction'] is False
