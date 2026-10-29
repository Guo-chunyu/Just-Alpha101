"""Runner integration: real bars, formulas, backtests, reports and period splits."""

import importlib.util
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
