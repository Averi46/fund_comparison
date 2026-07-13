# Mutual Fund Lazy-Cache PoC

A lightweight FastAPI + Streamlit application that calculates mutual fund daily
total returns from yfinance data only when needed and caches them in SQLite.

## How it works

1. `funds.csv` provides a baseline fund list and is synchronized into SQLite
   when the API starts.
2. A fund with no cached prices triggers a full-history yfinance request.
3. A stale fund triggers a request beginning on the day after its newest
   cached observation.
4. A fund current through the last completed NYSE trading day is served
   entirely from SQLite.

The SQLite database is created automatically at `data/fund_cache.db`.

## Setup and launch

Python 3.12 or 3.13 is recommended. The launcher also configures a safe PyArrow
memory allocator for Python 3.14 on macOS.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

The dashboard opens at <http://localhost:8501>. The FastAPI API and interactive
documentation are available at <http://127.0.0.1:8000> and
<http://127.0.0.1:8000/docs>.

Use the **Cache Inspector** page in the dashboard sidebar for a read-only view
of the funds and price rows stored in `data/fund_cache.db`. You can filter by
ticker and download the displayed rows as CSV.

To run the services separately:

```bash
python -m uvicorn backend.main:app --reload
ARROW_DEFAULT_MEMORY_POOL=system python -m streamlit run frontend/dashboard.py
```

Set `FUND_API_HOST`, `FUND_API_PORT`, or `FUND_API_URL` to override the local
defaults.

## Fund list

Edit `funds.csv` using this format, then restart the API:

```csv
ticker,name
QLEIX,AQR Large Cap Defensive Style Fund Class I
MAMBX,BlackRock Mid-Cap Value Fund Investor A
AQMIX,AQR Managed Futures Strategy Fund Class I
```

The dashboard accepts any valid ticker string; entries do not need to be in the
CSV. Successfully fetched tickers are registered in SQLite and become normal
cache hits on later requests. Invalid tickers produce a clear upstream-data
error and do not create empty cache records.

## Dashboard metrics

- Growth of $10,000 uses compounded daily total returns.
- Cumulative total return shows the same performance as a percentage.
- Grouped risk charts compare trailing 1-, 3-, and 5-year annualized returns,
  annualized daily standard deviation, maximum drawdown, and Sharpe ratio.
- Sharpe ratio uses 252 trading days and a 0% risk-free rate.
- Correlation uses overlapping daily returns for the selected benchmark.
- Fund facts are fetched from Yahoo and cached for 30 days. Missing Yahoo
  fields are displayed as `N/A`.
- Known Yahoo metadata errors can be corrected in
  `fund_metadata_overrides.csv`; local values take precedence over the cache.

## API

- `GET /health`
- `GET /funds`
- `GET /funds/{ticker}/history?benchmark=QLEIX`

The history response includes fund metadata, prices, returns, growth, trailing
risk metrics, cache source, fetched row count, elapsed time, and latest date.

## Tests

Tests use an in-memory-style temporary SQLite database and a fake market-data
client, so they do not call yfinance:

```bash
python -m pytest
```

This is a local PoC. It does not include authentication, distributed locking,
or production deployment configuration.
