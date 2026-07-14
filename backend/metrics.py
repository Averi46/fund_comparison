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
                    "annualized_downside_deviation": None,
                    "sharpe_ratio": None,
                    "sortino_ratio": None,
                    "average_gain": None,
                    "gain_frequency": None,
                    "average_loss": None,
                    "loss_frequency": None,
                    "maximum_drawdown": None,
                }
            )
            continue

        daily_std = float(window.std(ddof=1))
        downside = window.clip(upper=0)
        annualized_downside = float(
            math.sqrt(float((downside**2).mean()))
            * math.sqrt(TRADING_DAYS_PER_YEAR)
        )
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
                "annualized_downside_deviation": annualized_downside,
                "sharpe_ratio": (
                    float(
                        window.mean()
                        / daily_std
                        * math.sqrt(TRADING_DAYS_PER_YEAR)
                    )
                    if daily_std > 0
                    else None
                ),
                "sortino_ratio": (
                    float(window.mean() * TRADING_DAYS_PER_YEAR / annualized_downside)
                    if annualized_downside > 0
                    else None
                ),
                "average_gain": (
                    float(window[window > 0].mean())
                    if (window > 0).any()
                    else None
                ),
                "gain_frequency": float((window > 0).mean()),
                "average_loss": (
                    float(window[window < 0].mean())
                    if (window < 0).any()
                    else None
                ),
                "loss_frequency": float((window < 0).mean()),
                "maximum_drawdown": float(
                    (cumulative / cumulative.cummax() - 1).min()
                ),
            }
        )
    return output


def calculate_performance_metrics(frame: pd.DataFrame) -> dict:
    returns = frame["daily_return"].dropna()
    if returns.empty:
        return {
            "period_returns": [],
            "calendar_year_returns": [],
            "annualized_return_table": [],
        }

    latest = returns.index.max()
    ytd = returns.loc[returns.index.year == latest.year]
    period_returns = [
        {
            "period": "YTD",
            "return": _compound(ytd),
            "annualized": False,
        }
    ]
    for years in (1, 3, 5):
        window = _full_period_window(returns, latest, years)
        period_returns.append(
            {
                "period": f"{years} Yr",
                "return": _annualized_return(window) if window is not None else None,
                "annualized": True,
            }
        )

    inception_years = (latest - returns.index.min()).days / 365.25
    period_returns.append(
        {
            "period": "Since Inception",
            "return": (
                _annualized_return(returns)
                if inception_years >= 1
                else _compound(returns)
            ),
            "annualized": inception_years >= 1,
        }
    )

    calendar_year_returns = []
    for year in range(latest.year - 3, latest.year):
        year_returns = returns.loc[returns.index.year == year]
        calendar_year_returns.append(
            {
                "year": year,
                "return": _compound(year_returns) if not year_returns.empty else None,
            }
        )

    return_table = []
    for years in (1, 3, 5, 10):
        window = _full_period_window(returns, latest, years)
        return_table.append(
            {
                "period": f"{years} Yr",
                "total_return": (
                    _annualized_return(window) if window is not None else None
                ),
                "load_adjusted_total_return": None,
                "market_price_total_return": None,
            }
        )
    return_table.append(
        {
            "period": "Since Inception",
            "total_return": (
                _annualized_return(returns)
                if inception_years >= 1
                else _compound(returns)
            ),
            "load_adjusted_total_return": None,
            "market_price_total_return": None,
        }
    )
    return {
        "period_returns": period_returns,
        "calendar_year_returns": calendar_year_returns,
        "annualized_return_table": return_table,
    }


def calculate_rolling_risk(frame: pd.DataFrame) -> list[dict]:
    returns = frame["daily_return"].dropna()
    rolling = returns.rolling(TRADING_DAYS_PER_YEAR * 3).std(ddof=1)
    annualized = rolling * math.sqrt(TRADING_DAYS_PER_YEAR)
    return [
        {"date": index.strftime("%Y-%m-%d"), "standard_deviation": float(value)}
        for index, value in annualized.dropna().items()
    ]


def _full_period_window(
    returns: pd.Series,
    latest: pd.Timestamp,
    years: int,
) -> pd.Series | None:
    cutoff = latest - pd.DateOffset(years=years)
    window = returns.loc[returns.index >= cutoff]
    if window.empty or window.index.min() > cutoff + pd.Timedelta(days=14):
        return None
    return window


def _compound(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    return float((1 + returns).prod() - 1)


def _annualized_return(returns: pd.Series | None) -> float | None:
    if returns is None or returns.empty:
        return None
    return float(
        (1 + returns).prod() ** (TRADING_DAYS_PER_YEAR / len(returns)) - 1
    )
