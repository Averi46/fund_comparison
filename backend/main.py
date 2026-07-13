from fastapi import FastAPI, HTTPException, Query

from backend.cache_engine import InvalidTickerError, LazyCacheEngine
from backend.config import DATABASE_PATH, FUNDS_CSV
from backend.database import CacheDatabase
from backend.market_data import MarketDataError, YFinanceClient
from backend.metrics import (
    add_growth_of_10k,
    calculate_metrics,
    calculate_period_risk_metrics,
)


database = CacheDatabase(DATABASE_PATH, FUNDS_CSV)
database.initialize()
cache_engine = LazyCacheEngine(database, YFinanceClient())

app = FastAPI(
    title="Mutual Fund Lazy Cache API",
    version="0.1.0",
    description="On-demand historical mutual fund data backed by SQLite.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/funds")
def list_funds() -> dict[str, list[dict[str, str]]]:
    return {"funds": database.list_funds()}


@app.get("/funds/{ticker}/history")
def fund_history(
    ticker: str,
    benchmark: str | None = Query(
        default=None,
        description="Optional ticker used for daily-return correlation.",
    ),
) -> dict:
    try:
        result = cache_engine.get_fund_data(ticker)
        benchmark_result = (
            cache_engine.get_fund_data(benchmark)
            if benchmark and benchmark.strip().upper() != result.ticker
            else None
        )
    except InvalidTickerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Unable to load fund data: {exc}"
        ) from exc

    enriched = add_growth_of_10k(result.data)
    records = [
        {
            "date": index.strftime("%Y-%m-%d"),
            "adjusted_close": float(row["adjusted_close"]),
            "daily_return": (
                None
                if row["daily_return"] != row["daily_return"]
                else float(row["daily_return"])
            ),
            "growth_of_10000": float(row["growth_of_10000"]),
        }
        for index, row in enriched.iterrows()
    ]
    metrics = calculate_metrics(
        result.data,
        benchmark_result.data if benchmark_result else (
            result.data if benchmark else None
        ),
    )

    return {
        "ticker": result.ticker,
        "benchmark": benchmark.strip().upper() if benchmark else None,
        "metadata": result.metadata,
        "data": records,
        "metrics": metrics,
        "risk_metrics": calculate_period_risk_metrics(result.data),
        "request": {
            "source": result.source,
            "fetched_rows": result.fetched_rows,
            "elapsed_seconds": round(result.elapsed_seconds, 4),
            "latest_date": (
                result.latest_date.isoformat() if result.latest_date else None
            ),
            "benchmark_source": (
                benchmark_result.source if benchmark_result else None
            ),
            "metadata_source": result.metadata_source,
        },
    }
