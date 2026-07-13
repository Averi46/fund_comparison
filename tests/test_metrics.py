import pandas as pd
import pytest

from backend.metrics import (
    add_growth_of_10k,
    calculate_metrics,
    calculate_period_risk_metrics,
)


def test_growth_and_metrics():
    frame = pd.DataFrame(
        {
            "adjusted_close": [100.0, 110.0, 99.0],
            "daily_return": [None, 0.10, -0.10],
        },
        index=pd.date_range("2024-01-01", periods=3),
    )

    enriched = add_growth_of_10k(frame)
    metrics = calculate_metrics(frame, frame)

    assert enriched["growth_of_10000"].iloc[-1] == pytest.approx(9_900)
    assert metrics["daily_standard_deviation"] == pytest.approx(
        metrics["daily_volatility"]
    )
    assert metrics["correlation"] == pytest.approx(1.0)


def test_trailing_risk_metrics_use_full_periods():
    index = pd.bdate_range("2020-01-01", "2026-01-02")
    returns = pd.Series(
        [0.001 if position % 2 else -0.0005 for position in range(len(index))],
        index=index,
    )
    frame = pd.DataFrame(
        {
            "adjusted_close": 100 * (1 + returns).cumprod(),
            "daily_return": returns,
        }
    )

    metrics = calculate_period_risk_metrics(frame)

    assert [item["period_years"] for item in metrics] == [1, 3, 5]
    assert all(item["annualized_standard_deviation"] for item in metrics)
    assert all(item["sharpe_ratio"] is not None for item in metrics)
