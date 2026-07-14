import html
import os
from datetime import date

import plotly.graph_objects as go
import requests
import streamlit as st


API_URL = os.getenv("FUND_API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT_SECONDS = 120

st.set_page_config(page_title="Alternative Fund Comparison", page_icon="📈", layout="wide")
st.title("Alternative Fund Comparison")
st.caption("Enter two ticker symbols to compare their total-return histories.")


def get_history(ticker: str, benchmark: str | None = None) -> dict:
    params = {"benchmark": benchmark} if benchmark else None
    response = requests.get(
        f"{API_URL}/funds/{ticker}/history",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(detail)
    return response.json()


def format_number_or_dash(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def format_percent_or_dash(value: float | None) -> str:
    return "-" if value is None else f"{value:.2%}"


def format_bps(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f} bps"


def format_assets(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    return f"${value:,.0f}"


def format_date(value: str | None) -> str:
    if not value:
        return "N/A"
    try:
        return date.fromisoformat(value).strftime("%m/%d/%Y")
    except ValueError:
        return value


def render_table(headers: list[str], rows: list[list[str]]) -> None:
    header_html = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    row_html = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape(str(value))}</td>" for value in row)
        + "</tr>"
        for row in rows
    )
    st.markdown(
        f"""
        <table style="width:100%; border-collapse:collapse; margin-bottom:1rem">
          <thead><tr>{header_html}</tr></thead>
          <tbody>{row_html}</tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )


def source_message(payload: dict) -> str:
    request_info = payload["request"]
    source_labels = {
        "cache": "Cache",
        "yfinance_full": "yfinance API (full history)",
        "yfinance_delta": "yfinance API (delta update)",
    }
    source = source_labels.get(request_info["source"], request_info["source"])
    if request_info["source"] == "cache":
        detail = f"hit in {request_info['elapsed_seconds']:.2f}s"
    else:
        detail = (
            f"fetched {request_info['fetched_rows']:,} rows and updated the cache "
            f"in {request_info['elapsed_seconds']:.2f}s"
        )
    return (
        f"**{payload['ticker']}** — Source: {source} ({detail}). "
        f"Latest observation: {request_info['latest_date']}."
    )


with st.form("fund_comparison"):
    input_columns = st.columns(2)
    ticker_one = input_columns[0].text_input(
        "First fund ticker",
        value="QLEIX",
        placeholder="e.g. QLEIX",
    )
    ticker_two = input_columns[1].text_input(
        "Second fund ticker",
        value="AQMIX",
        placeholder="e.g. AQMIX",
    )
    submitted = st.form_submit_button("Compare funds", type="primary")

if submitted:
    tickers = [ticker_one.strip().upper(), ticker_two.strip().upper()]
    errors: dict[str, str] = {}
    results: dict[str, dict] = {}

    if not tickers[0] or not tickers[1]:
        errors["Input"] = "Enter both ticker symbols."
    elif tickers[0] == tickers[1]:
        errors["Input"] = "Enter two different ticker symbols."
    else:
        progress = st.status("Checking the cache and loading fund data…", expanded=True)
        for ticker in tickers:
            try:
                progress.write(f"Checking {ticker}…")
                results[ticker] = get_history(ticker)
            except requests.RequestException:
                errors[ticker] = (
                    f"The API is not reachable at {API_URL}. Start the app with "
                    "`python run.py` and try again."
                )
            except RuntimeError as exc:
                errors[ticker] = str(exc)

        if not errors:
            try:
                comparison = get_history(tickers[0], benchmark=tickers[1])
                results[tickers[0]]["metrics"]["correlation"] = comparison[
                    "metrics"
                ]["correlation"]
            except (requests.RequestException, RuntimeError) as exc:
                errors["Correlation"] = str(exc)

        progress.update(
            label="Comparison ready" if not errors else "Comparison could not be completed",
            state="complete" if not errors else "error",
            expanded=bool(errors),
        )

    st.session_state["comparison"] = {
        "tickers": tickers,
        "results": results,
        "errors": errors,
    }

comparison_state = st.session_state.get("comparison")
if not comparison_state:
    st.info("Enter two fund tickers above, then select **Compare funds**.")
    st.stop()

required_response_fields = {
    "metadata",
    "risk_metrics",
    "performance",
    "rolling_risk",
}
outdated_payloads = [
    ticker
    for ticker, payload in comparison_state["results"].items()
    if not required_response_fields.issubset(payload)
]
if outdated_payloads:
    st.session_state.pop("comparison", None)
    st.error(
        "The dashboard is connected to an older backend process. Stop the "
        "current app with Ctrl+C, restart it with `python run.py`, and submit "
        "the comparison again."
    )
    st.stop()

for label, message in comparison_state["errors"].items():
    st.error(f"{label}: {message}")

if comparison_state["errors"]:
    st.stop()

tickers = comparison_state["tickers"]
results = comparison_state["results"]

st.subheader("Overview")
metadata = [results[ticker].get("metadata", {}) for ticker in tickers]
render_table(
    ["Fund detail", tickers[0], tickers[1]],
    [
        [
            "Full fund name",
            metadata[0].get("full_name") or "-",
            metadata[1].get("full_name") or "-",
        ],
        [
            "Net expense ratio",
            format_bps(metadata[0].get("net_expense_ratio_bps")),
            format_bps(metadata[1].get("net_expense_ratio_bps")),
        ],
        [
            "Gross expense ratio",
            format_bps(metadata[0].get("gross_expense_ratio_bps")),
            format_bps(metadata[1].get("gross_expense_ratio_bps")),
        ],
        [
            "Morningstar category",
            metadata[0].get("morningstar_category") or "-",
            metadata[1].get("morningstar_category") or "-",
        ],
        [
            "Fund assets",
            format_assets(metadata[0].get("fund_assets")),
            format_assets(metadata[1].get("fund_assets")),
        ],
        [
            "Share class assets",
            format_assets(metadata[0].get("share_class_assets")),
            format_assets(metadata[1].get("share_class_assets")),
        ],
        [
            "12-month yield (%)",
            format_percent_or_dash(metadata[0].get("twelve_month_yield")),
            format_percent_or_dash(metadata[1].get("twelve_month_yield")),
        ],
        [
            "30-day SEC yield (%)",
            format_percent_or_dash(metadata[0].get("thirty_day_sec_yield")),
            format_percent_or_dash(metadata[1].get("thirty_day_sec_yield")),
        ],
        [
            "Unsubsidized SEC yield (%)",
            format_percent_or_dash(metadata[0].get("unsubsidized_sec_yield")),
            format_percent_or_dash(metadata[1].get("unsubsidized_sec_yield")),
        ],
        [
            "Investment style",
            metadata[0].get("investment_style") or "-",
            metadata[1].get("investment_style") or "-",
        ],
        [
            "Inception date",
            format_date(metadata[0].get("inception_date")),
            format_date(metadata[1].get("inception_date")),
        ],
    ],
)

for ticker in tickers:
    st.info(source_message(results[ticker]))

st.subheader("Performance")


def grouped_bar_chart(
    title: str,
    x_values: list[str],
    values_by_ticker: dict[str, list[float | None]],
    y_axis_title: str,
    percentage: bool = False,
) -> go.Figure:
    figure = go.Figure()
    for ticker in tickers:
        values = values_by_ticker[ticker]
        if percentage:
            values = [value * 100 if value is not None else None for value in values]
        figure.add_trace(go.Bar(x=x_values, y=values, name=ticker))
    figure.update_layout(
        title=title,
        xaxis_title="Period",
        yaxis_title=y_axis_title,
        barmode="group",
        legend_title="Fund",
    )
    if percentage:
        figure.update_yaxes(ticksuffix="%", tickformat=",.2f")
    else:
        figure.update_yaxes(tickformat=",.2f")
    return figure


performance_periods = [
    item["period"] for item in results[tickers[0]]["performance"]["period_returns"]
]
performance_chart = grouped_bar_chart(
    "Annualized Total Returns",
    performance_periods,
    {
        ticker: [
            item["return"]
            for item in results[ticker]["performance"]["period_returns"]
        ]
        for ticker in tickers
    },
    "Total return (%)",
    percentage=True,
)
st.plotly_chart(performance_chart, width="stretch")
st.caption(
    "YTD and any since-inception period shorter than one year are cumulative "
    "total returns and are not annualized. Periods of one year or longer are "
    "annualized from daily total returns."
)

calendar_years = [
    str(item["year"])
    for item in results[tickers[0]]["performance"]["calendar_year_returns"]
]
calendar_chart = grouped_bar_chart(
    "Calendar Year Total Returns",
    calendar_years,
    {
        ticker: [
            item["return"]
            for item in results[ticker]["performance"]["calendar_year_returns"]
        ]
        for ticker in tickers
    },
    "Total return (%)",
    percentage=True,
)
st.plotly_chart(calendar_chart, width="stretch")

for ticker in tickers:
    table_data = results[ticker]["performance"]["annualized_return_table"]
    st.markdown(f"**{ticker} annualized returns**")
    render_table(
        [
            "Period",
            "Total return",
            "Load-adjusted total return",
            "Market-price total return",
        ],
        [
            [
                item["period"],
                format_percent_or_dash(item["total_return"]),
                format_percent_or_dash(item["load_adjusted_total_return"]),
                format_percent_or_dash(item["market_price_total_return"]),
            ]
            for item in table_data
        ],
    )

growth_figure = go.Figure()
returns_figure = go.Figure()
for ticker in tickers:
    records = results[ticker]["data"]
    dates = [row["date"] for row in records]
    growth_figure.add_trace(
        go.Scatter(
            x=dates,
            y=[row["growth_of_10000"] for row in records],
            mode="lines",
            name=ticker,
        )
    )
    returns_figure.add_trace(
        go.Scatter(
            x=dates,
            y=[
                (row["growth_of_10000"] / 10_000 - 1) * 100
                for row in records
            ],
            mode="lines",
            name=ticker,
        )
    )

growth_figure.update_layout(
    title="Growth of $10,000",
    xaxis_title="Date",
    yaxis_title="Portfolio value ($)",
    hovermode="x unified",
    legend_title="Fund",
)
growth_figure.update_yaxes(tickprefix="$", tickformat=",.0f")
st.plotly_chart(growth_figure, width="stretch")

returns_figure.update_layout(
    title="Cumulative Total Returns",
    xaxis_title="Date",
    yaxis_title="Cumulative total return (%)",
    hovermode="x unified",
    legend_title="Fund",
)
returns_figure.update_yaxes(ticksuffix="%", tickformat=",.2f", zeroline=True)
st.plotly_chart(returns_figure, width="stretch")

st.subheader("Risk")
risk_by_ticker = {
    ticker: {
        item["period_years"]: item for item in results[ticker]["risk_metrics"]
    }
    for ticker in tickers
}
risk_periods = ["1Y", "3Y", "5Y"]
risk_columns = st.columns(2)
risk_columns[0].plotly_chart(
    grouped_bar_chart(
        "Annualized Standard Deviation",
        risk_periods,
        {
            ticker: [
                risk_by_ticker[ticker][year][
                    "annualized_standard_deviation"
                ]
                for year in (1, 3, 5)
            ]
            for ticker in tickers
        },
        "Annualized standard deviation (%)",
        percentage=True,
    ),
    width="stretch",
)
risk_columns[1].plotly_chart(
    grouped_bar_chart(
        "Annualized Downside Standard Deviation",
        risk_periods,
        {
            ticker: [
                risk_by_ticker[ticker][year][
                    "annualized_downside_deviation"
                ]
                for year in (1, 3, 5)
            ]
            for ticker in tickers
        },
        "Annualized downside deviation (%)",
        percentage=True,
    ),
    width="stretch",
)

rolling_figure = go.Figure()
for ticker in tickers:
    rolling = results[ticker]["rolling_risk"]
    rolling_figure.add_trace(
        go.Scatter(
            x=[item["date"] for item in rolling],
            y=[item["standard_deviation"] * 100 for item in rolling],
            mode="lines",
            name=ticker,
        )
    )
rolling_figure.update_layout(
    title="Rolling 3-Year Annualized Standard Deviation",
    xaxis_title="Date",
    yaxis_title="Annualized standard deviation (%)",
    hovermode="x unified",
    legend_title="Fund",
)
rolling_figure.update_yaxes(ticksuffix="%", tickformat=",.2f")
st.plotly_chart(rolling_figure, width="stretch")

st.plotly_chart(
    grouped_bar_chart(
        "Annualized Sharpe Ratio",
        risk_periods,
        {
            ticker: [
                risk_by_ticker[ticker][year]["sharpe_ratio"]
                for year in (1, 3, 5)
            ]
            for ticker in tickers
        },
        "Sharpe ratio",
    ),
    width="stretch",
)
st.caption(
    "Risk statistics are calculated from daily total returns using 252 trading "
    "days per year and a 0% risk-free rate. Sharpe and Sortino are unitless ratios."
)

st.markdown("### Ex post risk analysis")
for ticker in tickers:
    st.markdown(f"**{ticker} ex post risk**")
    render_table(
        [
            "Period",
            "Avg gain (%)",
            "Gain frequency (%)",
            "Avg loss (%)",
            "Loss frequency (%)",
            "Max drawdown (%)",
        ],
        [
            [
                f"{years} Yr",
                format_percent_or_dash(
                    risk_by_ticker[ticker][years]["average_gain"]
                ),
                format_percent_or_dash(
                    risk_by_ticker[ticker][years]["gain_frequency"]
                ),
                format_percent_or_dash(
                    risk_by_ticker[ticker][years]["average_loss"]
                ),
                format_percent_or_dash(
                    risk_by_ticker[ticker][years]["loss_frequency"]
                ),
                format_percent_or_dash(
                    risk_by_ticker[ticker][years]["maximum_drawdown"]
                ),
            ]
            for years in (1, 3, 5)
        ],
    )

render_table(
    ["3-Year Risk / Return", tickers[0], tickers[1]],
    [
        [
            "Sharpe ratio",
            format_number_or_dash(risk_by_ticker[tickers[0]][3]["sharpe_ratio"]),
            format_number_or_dash(risk_by_ticker[tickers[1]][3]["sharpe_ratio"]),
        ],
        [
            "Sortino ratio",
            format_number_or_dash(risk_by_ticker[tickers[0]][3]["sortino_ratio"]),
            format_number_or_dash(risk_by_ticker[tickers[1]][3]["sortino_ratio"]),
        ],
    ],
)
