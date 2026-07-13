import math

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 252


def add_growth_of_10k(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["growth_of_10000"] = (
        10_000 * (1 + result["daily_return"].fillna(0)).cumprod()
    )
    return result


def calculate_metrics(
    frame: pd.DataFrame,
    benchmark: pd.DataFrame | None = None,
) -> dict[str, float | None]:
    returns = frame["daily_return"].dropna()
    if returns.empty:
        return {
            "sharpe_ratio": None,
            "daily_volatility": None,
            "daily_standard_deviation": None,
            "annualized_volatility": None,
            "correlation": None,
        }

    daily_std = float(returns.std(ddof=1))
    sharpe = (
        float(returns.mean() / daily_std * math.sqrt(TRADING_DAYS_PER_YEAR))
        if daily_std > 0
        else None
    )

    correlation = None
    if benchmark is not None:
        aligned = pd.concat(
            [
                returns.rename("fund"),
                benchmark["daily_return"].dropna().rename("benchmark"),
            ],
            axis=1,
            join="inner",
        ).dropna()
        if len(aligned) >= 2:
            value = aligned["fund"].corr(aligned["benchmark"])
            correlation = float(value) if np.isfinite(value) else None

    return {
        "sharpe_ratio": sharpe,
        "daily_volatility": daily_std,
        "daily_standard_deviation": daily_std,
        "annualized_volatility": daily_std * math.sqrt(TRADING_DAYS_PER_YEAR),
        "correlation": correlation,
    }


def calculate_period_risk_metrics(frame: pd.DataFrame) -> list[dict]:
    """Calculate trailing risk metrics from daily total returns."""
    if frame.empty:
        return []

    latest = frame.index.max()
    output = []
    for years in (1, 3, 5):
        cutoff = latest - pd.DateOffset(years=years)
        window = frame.loc[frame.index >= cutoff, "daily_return"].dropna()
        has_full_period = (
            not window.empty
            and window.index.min() <= cutoff + pd.Timedelta(days=14)
        )
        if not has_full_period:
            output.append(
                {
                    "period_years": years,
                    "observations": len(window),
                    "annualized_return": None,
                    "annualized_standard_deviation": None,
                    "sharpe_ratio": None,
                    "maximum_drawdown": None,
                }
            )
            continue

        daily_std = float(window.std(ddof=1))
        cumulative = (1 + window).cumprod()
        annualized_return = float(
            cumulative.iloc[-1] ** (TRADING_DAYS_PER_YEAR / len(window)) - 1
        )
        output.append(
            {
                "period_years": years,
                "observations": len(window),
                "annualized_return": annualized_return,
                "annualized_standard_deviation": (
                    daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)
                ),
                "sharpe_ratio": (
                    float(
                        window.mean()
                        / daily_std
                        * math.sqrt(TRADING_DAYS_PER_YEAR)
                    )
                    if daily_std > 0
                    else None
                ),
                "maximum_drawdown": float(
                    (cumulative / cumulative.cummax() - 1).min()
                ),
            }
        )
    return output
