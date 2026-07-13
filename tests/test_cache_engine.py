from datetime import date

import pandas as pd
import pytest

import backend.cache_engine as cache_module
from backend.cache_engine import InvalidTickerError, LazyCacheEngine
from backend.database import CacheDatabase


class FakeMarketData:
    def __init__(self, responses: list[pd.DataFrame]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def fetch_history(self, ticker, start=None, end=None):
        self.calls.append({"ticker": ticker, "start": start, "end": end})
        return self.responses.pop(0).copy()

    def fetch_metadata(self, ticker):
        return {"full_name": f"{ticker} Fund"}


def price_frame(dates: list[str], prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"adjusted_close": prices},
        index=pd.DatetimeIndex(dates, name="date"),
    )


@pytest.fixture
def database(tmp_path):
    csv_path = tmp_path / "funds.csv"
    csv_path.write_text("ticker,name\nTEST,Test Fund\n", encoding="utf-8")
    result = CacheDatabase(tmp_path / "cache.db", csv_path)
    result.initialize()
    return result


def test_cache_miss_then_fresh_hit(database, monkeypatch):
    monkeypatch.setattr(
        cache_module, "last_completed_trading_day", lambda: date(2024, 1, 3)
    )
    market_data = FakeMarketData(
        [price_frame(["2024-01-02", "2024-01-03"], [100, 101])]
    )
    engine = LazyCacheEngine(database, market_data)

    miss = engine.get_fund_data("test")
    hit = engine.get_fund_data("TEST")

    assert miss.source == "yfinance_full"
    assert miss.fetched_rows == 2
    assert hit.source == "cache"
    assert hit.fetched_rows == 0
    assert len(market_data.calls) == 1
    assert hit.data.loc[pd.Timestamp("2024-01-03"), "daily_return"] == pytest.approx(
        0.01
    )


def test_stale_cache_fetches_only_delta(database, monkeypatch):
    expected_day = date(2024, 1, 3)
    monkeypatch.setattr(
        cache_module, "last_completed_trading_day", lambda: expected_day
    )
    market_data = FakeMarketData(
        [
            price_frame(["2024-01-02", "2024-01-03"], [100, 101]),
            price_frame(["2024-01-04", "2024-01-05"], [102, 104]),
        ]
    )
    engine = LazyCacheEngine(database, market_data)
    engine.get_fund_data("TEST")

    expected_day = date(2024, 1, 5)
    updated = engine.get_fund_data("TEST")

    assert updated.source == "yfinance_delta"
    assert updated.fetched_rows == 2
    assert market_data.calls[1]["start"] == date(2024, 1, 4)
    assert market_data.calls[1]["end"] == date(2024, 1, 6)
    assert updated.data.loc[
        pd.Timestamp("2024-01-04"), "daily_return"
    ] == pytest.approx(102 / 101 - 1)
    assert len(updated.data) == 4


def test_fetches_and_caches_ticker_not_in_csv(database, monkeypatch):
    monkeypatch.setattr(
        cache_module, "last_completed_trading_day", lambda: date(2024, 1, 3)
    )
    market_data = FakeMarketData(
        [price_frame(["2024-01-02", "2024-01-03"], [50, 51])]
    )
    engine = LazyCacheEngine(database, market_data)

    miss = engine.get_fund_data("NEWFX")
    hit = engine.get_fund_data("NEWFX")

    assert miss.source == "yfinance_full"
    assert hit.source == "cache"
    assert len(market_data.calls) == 1


def test_rejects_malformed_ticker(database):
    engine = LazyCacheEngine(database, FakeMarketData([]))

    with pytest.raises(InvalidTickerError):
        engine.get_fund_data("not a ticker")
