import sqlite3

import pandas as pd
import streamlit as st

from backend.config import DATABASE_PATH


st.set_page_config(page_title="Cache Inspector", page_icon="🗄️", layout="wide")
st.title("Cache Inspector")
st.caption(f"Read-only view of `{DATABASE_PATH}`")

if not DATABASE_PATH.exists():
    st.info("The cache has not been created yet. Start the app and load a fund first.")
    st.stop()


def read_query(query: str, parameters: tuple = ()) -> pd.DataFrame:
    database_uri = f"{DATABASE_PATH.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        return pd.read_sql_query(query, connection, params=parameters)


summary = read_query(
    """
    SELECT
        f.ticker,
        f.name,
        CASE WHEN f.active = 1 THEN 'Yes' ELSE 'No' END AS active,
        COUNT(p.price_date) AS price_rows,
        MIN(p.price_date) AS first_date,
        MAX(p.price_date) AS latest_date
    FROM funds AS f
    LEFT JOIN prices AS p ON p.ticker = f.ticker
    GROUP BY f.ticker, f.name, f.active
    ORDER BY f.ticker
    """
)

metric_columns = st.columns(3)
metric_columns[0].metric("Funds", f"{len(summary):,}")
metric_columns[1].metric("Price rows", f"{int(summary['price_rows'].sum()):,}")
metric_columns[2].metric(
    "Database size", f"{DATABASE_PATH.stat().st_size / (1024 * 1024):.2f} MB"
)

st.subheader("Cached funds")
st.dataframe(summary, width="stretch", hide_index=True)

if summary.empty:
    st.info("The database exists, but it does not contain any funds.")
    st.stop()

ticker = st.selectbox("Inspect price history", summary["ticker"].tolist())
prices = read_query(
    """
    SELECT price_date, adjusted_close, daily_return
    FROM prices
    WHERE ticker = ?
    ORDER BY price_date DESC
    """,
    (ticker,),
)

st.write(f"Showing {len(prices):,} cached rows for **{ticker}**, newest first.")
st.dataframe(
    prices,
    width="stretch",
    hide_index=True,
    column_config={
        "adjusted_close": st.column_config.NumberColumn(format="$%.4f"),
        "daily_return": st.column_config.NumberColumn(format="%.6f"),
    },
)
st.download_button(
    "Download these rows as CSV",
    prices.to_csv(index=False).encode("utf-8"),
    file_name=f"{ticker}_cached_prices.csv",
    mime="text/csv",
)
