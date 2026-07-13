import csv
from datetime import date

import pandas as pd
import yfinance as yf

from backend.config import METADATA_OVERRIDES_CSV


class MarketDataError(RuntimeError):
    """Raised when market data cannot be fetched or validated."""


def apply_metadata_overrides(ticker: str, metadata: dict) -> dict:
    result = metadata.copy()
    if not METADATA_OVERRIDES_CSV.exists():
        return result
    with METADATA_OVERRIDES_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (row.get("ticker") or "").strip().upper() == ticker:
                for key, value in row.items():
                    if key != "ticker" and value and value.strip():
                        result[key] = value.strip()
                break
    return result


class YFinanceClient:
    def fetch_history(
        self,
        ticker: str,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        try:
            history = yf.Ticker(ticker).history(
                period="max" if start is None else None,
                start=start,
                end=end,
                auto_adjust=False,
                actions=False,
                raise_errors=True,
            )
        except Exception as exc:
            raise MarketDataError(
                f"yfinance request failed for {ticker}: {exc}"
            ) from exc

        if history.empty:
            return pd.DataFrame(
                columns=["adjusted_close"],
                index=pd.DatetimeIndex([], name="date"),
            )

        adjusted_close = self._adjusted_close_column(history)
        frame = adjusted_close.to_frame(name="adjusted_close")
        frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
        frame = frame[~frame.index.duplicated(keep="last")]
        frame = frame.dropna().sort_index()
        frame.index.name = "date"
        return frame

    def fetch_metadata(self, ticker: str) -> dict:
        try:
            fund = yf.Ticker(ticker)
            info = fund.info
        except Exception as exc:
            raise MarketDataError(
                f"yfinance metadata request failed for {ticker}: {exc}"
            ) from exc

        overview: dict = {}
        asset_classes: dict = {}
        try:
            overview = fund.funds_data.fund_overview or {}
            asset_classes = fund.funds_data.asset_classes or {}
        except Exception:
            # Some valid funds do not expose the extended fund-data endpoint.
            pass

        inception = info.get("fundInceptionDate")
        inception_date = (
            pd.Timestamp(inception, unit="s", tz="UTC").date().isoformat()
            if inception
            else None
        )
        category = info.get("category") or overview.get("categoryName")
        investment_style = overview.get("legalType") or category
        if not investment_style and asset_classes:
            positive_assets = {
                key.removesuffix("Position"): value
                for key, value in asset_classes.items()
                if isinstance(value, (int, float)) and value > 0
            }
            if positive_assets:
                dominant = max(positive_assets, key=positive_assets.get)
                investment_style = f"{dominant.title()} focused"

        return apply_metadata_overrides(ticker, {
            "full_name": info.get("longName") or info.get("shortName") or ticker,
            "gross_expense_ratio": info.get("annualReportExpenseRatio"),
            "morningstar_category": category,
            "total_net_assets": info.get("netAssets") or info.get("totalAssets"),
            "investment_style": investment_style or category,
            "inception_date": inception_date,
        })

    @staticmethod
    def _adjusted_close_column(history: pd.DataFrame) -> pd.Series:
        if "Adj Close" in history.columns:
            result = history["Adj Close"]
        elif "Close" in history.columns:
            result = history["Close"]
        else:
            raise MarketDataError(
                "yfinance response did not contain Adjusted Close or Close"
            )

        if isinstance(result, pd.DataFrame):
            if result.shape[1] != 1:
                raise MarketDataError("Ambiguous yfinance price response")
            result = result.iloc[:, 0]
        return result.astype(float)
