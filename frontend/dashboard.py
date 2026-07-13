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


def format_percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3%}"


def format_number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def format_assets(value: float | None) -> str:
    if value is None:
        return "N/A"
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

required_response_fields = {"metadata", "risk_metrics"}
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

st.subheader("Fund information")
metadata = [results[ticker].get("metadata", {}) for ticker in tickers]
render_table(
    ["Fund detail", tickers[0], tickers[1]],
    [
        ["Full fund name", metadata[0].get("full_name") or "N/A", metadata[1].get("full_name") or "N/A"],
        [
            "Gross expense ratio",
            format_percent(metadata[0].get("gross_expense_ratio")),
            format_percent(metadata[1].get("gross_expense_ratio")),
        ],
        [
            "Morningstar category",
            metadata[0].get("morningstar_category") or "N/A",
            metadata[1].get("morningstar_category") or "N/A",
        ],
        [
            "Total net assets",
            format_assets(metadata[0].get("total_net_assets")),
            format_assets(metadata[1].get("total_net_assets")),
        ],
        [
            "Investment style",
            metadata[0].get("investment_style") or "N/A",
            metadata[1].get("investment_style") or "N/A",
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

st.subheader("Risk")
risk_by_ticker = {}
for ticker in tickers:
    risk_by_ticker[ticker] = {
        item["period_years"]: item for item in results[ticker]["risk_metrics"]
    }


def risk_bar_chart(
    metric: str,
    title: str,
    y_axis_title: str,
    percentage: bool = False,
) -> go.Figure:
    figure = go.Figure()
    periods = [1, 3, 5]
    for ticker in tickers:
        values = [risk_by_ticker[ticker][year][metric] for year in periods]
        if percentage:
            values = [value * 100 if value is not None else None for value in values]
        figure.add_trace(
            go.Bar(
                x=[f"{year}Y" for year in periods],
                y=values,
                name=ticker,
            )
        )
    figure.update_layout(
        title=title,
        xaxis_title="Trailing period",
        yaxis_title=y_axis_title,
        barmode="group",
        legend_title="Fund",
    )
    if percentage:
        figure.update_yaxes(ticksuffix="%", tickformat=",.2f")
    else:
        figure.update_yaxes(tickformat=",.2f")
    return figure


risk_chart_rows = st.columns(2), st.columns(2)
risk_charts = [
    risk_bar_chart(
        "annualized_return",
        "Annualized Return",
        "Annualized return (%)",
        percentage=True,
    ),
    risk_bar_chart(
        "annualized_standard_deviation",
        "Annualized Standard Deviation",
        "Annualized standard deviation (%)",
        percentage=True,
    ),
    risk_bar_chart(
        "maximum_drawdown",
        "Maximum Drawdown",
        "Maximum drawdown (%)",
        percentage=True,
    ),
    risk_bar_chart("sharpe_ratio", "Sharpe Ratio", "Sharpe ratio"),
]
for chart, column in zip(
    risk_charts,
    [
        risk_chart_rows[0][0],
        risk_chart_rows[0][1],
        risk_chart_rows[1][0],
        risk_chart_rows[1][1],
    ],
):
    column.plotly_chart(chart, width="stretch")

st.caption(
    "Risk statistics use daily total returns and 252 trading days per year. "
    "Sharpe ratios assume a 0% risk-free rate; N/A indicates insufficient history."
)

st.metric(
    f"Daily-return correlation: {tickers[0]} vs. {tickers[1]}",
    format_number(results[tickers[0]]["metrics"]["correlation"]),
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
