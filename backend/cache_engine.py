import re
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import pandas_market_calendars as mcal

from backend.database import CacheDatabase
from backend.market_data import (
    MarketDataError,
    YFinanceClient,
    apply_metadata_overrides,
)


class InvalidTickerError(ValueError):
    """Raised when a ticker string is empty or malformed."""


@dataclass(frozen=True)
class CacheResult:
    ticker: str
    data: pd.DataFrame
    source: str
    fetched_rows: int
    elapsed_seconds: float
    latest_date: date | None
    metadata: dict
    metadata_source: str


def last_completed_trading_day(now: pd.Timestamp | None = None) -> date:
    current = now or pd.Timestamp.now(tz="America/New_York")
    if current.tzinfo is None:
        current = current.tz_localize("America/New_York")
    else:
        current = current.tz_convert("America/New_York")

    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(
        start_date=(current - pd.Timedelta(days=14)).date(),
        end_date=current.date(),
    )
    completed = schedule[
        schedule["market_close"] <= current.tz_convert("UTC")
    ]
    if completed.empty:
        raise RuntimeError("Could not determine the last completed trading day")
    return completed.index[-1].date()


class LazyCacheEngine:
    def __init__(
        self,
        database: CacheDatabase,
        market_data: YFinanceClient,
    ) -> None:
        self.database = database
        self.market_data = market_data
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def get_fund_data(self, ticker: str) -> CacheResult:
        started = time.perf_counter()
        normalized = ticker.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.^=-]{1,20}", normalized):
            raise InvalidTickerError(
                "Ticker must contain 1–20 letters, numbers, or . ^ = - characters"
            )

        with self._ticker_lock(normalized):
            latest = self.database.latest_date(normalized)
            expected = last_completed_trading_day()

            if latest is None:
                fetched = self.market_data.fetch_history(normalized)
                if fetched.empty:
                    raise MarketDataError(
                        f"No historical price data found for {normalized}"
                    )
                prepared = self._with_returns(fetched)
                self.database.register_discovered_fund(normalized)
                self.database.upsert_prices(normalized, prepared)
                source = "yfinance_full"
                fetched_rows = len(prepared)
            elif latest.date() < expected:
                delta = self.market_data.fetch_history(
                    normalized,
                    start=latest.date() + timedelta(days=1),
                    end=expected + timedelta(days=1),
                )
                if not delta.empty:
                    cached = self.database.read_prices(normalized)
                    combined_prices = pd.concat(
                        [cached[["adjusted_close"]], delta]
                    )
                    combined_prices = combined_prices[
                        ~combined_prices.index.duplicated(keep="last")
                    ].sort_index()
                    prepared_delta = self._with_returns(combined_prices).loc[
                        delta.index
                    ]
                    self.database.upsert_prices(normalized, prepared_delta)
                source = "yfinance_delta"
                fetched_rows = len(delta)
            else:
                source = "cache"
                fetched_rows = 0

            data = self.database.read_prices(normalized)
            metadata_record = self.database.read_metadata(normalized)
            metadata_stale = (
                metadata_record is None
                or pd.Timestamp.now(tz="UTC") - metadata_record[1]
                > pd.Timedelta(days=30)
            )
            if metadata_stale:
                try:
                    metadata = self.market_data.fetch_metadata(normalized)
                    self.database.upsert_metadata(
                        normalized,
                        metadata,
                        pd.Timestamp.now(tz="UTC"),
                    )
                    metadata_source = "yfinance"
                except MarketDataError:
                    metadata = metadata_record[0] if metadata_record else {}
                    metadata_source = "cache_stale" if metadata_record else "unavailable"
            else:
                metadata = metadata_record[0]
                metadata_source = "cache"
            metadata = apply_metadata_overrides(normalized, metadata)

        elapsed = time.perf_counter() - started
        final_latest = data.index.max().date() if not data.empty else None
        return CacheResult(
            ticker=normalized,
            data=data,
            source=source,
            fetched_rows=fetched_rows,
            elapsed_seconds=elapsed,
            latest_date=final_latest,
            metadata=metadata,
            metadata_source=metadata_source,
        )

    def _ticker_lock(self, ticker: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(ticker, threading.Lock())

    @staticmethod
    def _with_returns(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame[["adjusted_close"]].copy()
        result["daily_return"] = result["adjusted_close"].pct_change(
            fill_method=None
        )
        return result
