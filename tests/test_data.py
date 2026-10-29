import pandas as pd
import pytest
from just_alpha101.data import normalize_wiki, audit_data, make_panel, sessions


def sample():
    return pd.DataFrame({'ticker': ['AAA', 'AAA'], 'date': ['2010-01-04', '2010-01-05'],
        'open': [20., 22.], 'high': [24., 26.], 'low': [18., 20.], 'close': [22., 24.],
        'volume': [100., 200.], 'adj_open': [10., 11.], 'adj_high': [12., 13.],
        'adj_low': [9., 10.], 'adj_close': [11., 12.], 'adj_volume': [200., 400.]})


def test_calendar_accepts_nontrading_boundary_and_special_closure():
    dates = sessions('2007-01-01', '2007-01-06')
    assert list(dates.strftime('%Y-%m-%d')) == ['2007-01-03', '2007-01-04', '2007-01-05']


def test_normalization_preserves_adjusted_bars_and_explicit_dollar_proxy():
    result = normalize_wiki(sample())
    assert result.close.tolist() == [11., 12.]
    assert result.volume.tolist() == [200., 400.]
    assert result.dollar_volume.tolist() == [2200., 4800.]
    assert 'vwap' not in result
    assert 'cap' not in result


def test_duplicate_security_date_rejected():
    with pytest.raises(ValueError, match='duplicate'):
        normalize_wiki(pd.concat([sample(), sample().iloc[:1]]))


def test_impossible_bar_rejected():
    frame = sample()
    frame.loc[0, 'adj_high'] = 8
    with pytest.raises(ValueError, match='OHLC'):
        normalize_wiki(frame)


def test_audit_does_not_certify_daily_prices_as_paper_data():
    result = audit_data(normalize_wiki(sample()), {}, start='2010-01-04', end='2010-01-05')
    assert result['strict_data_ready'] is False
    assert result['checks']['true_vwap']['passed'] is False
    assert result['checks']['true_dollar_volume']['passed'] is False
    assert result['checks']['point_in_time_industry']['passed'] is False
    assert result['checks']['calendar']['passed'] is True


def test_missing_exchange_session_fails_calendar_audit():
    result = audit_data(normalize_wiki(sample().iloc[:1]), {}, start='2010-01-04', end='2010-01-05')
    assert result['checks']['calendar']['passed'] is False


def test_panel_does_not_fill_missing_stock_observation():
    data = normalize_wiki(sample())
    other = data.iloc[:1].copy()
    other['symbol'] = 'BBB'
    panel = make_panel(pd.concat([data, other]))
    assert pd.isna(panel['close'].loc['2010-01-05', 'BBB'])


def test_claimed_metadata_cannot_certify_empty_required_fields_or_fake_warmup():
    data = normalize_wiki(sample())
    old = data.iloc[:1].copy()
    old['date'] = pd.Timestamp('2007-01-03')
    data = pd.concat([old, data], ignore_index=True)
    for field in ['vwap', 'cap', 'sector', 'industry', 'subindustry']:
        data[field] = float('nan')
    flags = dict(vwap_is_trade_weighted=True, dollar_volume_is_actual=True,
                 cap_is_point_in_time=True, industry_is_point_in_time=True,
                 corporate_actions_documented=True, adjustments_point_in_time=True,
                 membership_and_delistings_verified=True)
    result = audit_data(data, flags, start='2010-01-04', end='2010-01-05')
    assert result['strict_data_ready'] is False
    assert result['checks']['true_vwap']['passed'] is False
    assert result['checks']['historical_market_cap']['passed'] is False
    assert result['checks']['point_in_time_industry']['passed'] is False
    assert result['checks']['warmup']['passed'] is False


def test_old_disconnected_history_does_not_satisfy_recent_warmup():
    data = normalize_wiki(sample())
    old = pd.concat([data.iloc[:1]] * 500, ignore_index=True)
    old['date'] = pd.bdate_range('2000-01-03', periods=500)
    result = audit_data(pd.concat([old, data]), {}, start='2010-01-04', end='2010-01-05')
    assert result['checks']['warmup']['passed'] is False
