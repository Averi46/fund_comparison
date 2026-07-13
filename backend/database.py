import csv
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd


class CacheDatabase:
    def __init__(self, database_path: Path, funds_csv: Path) -> None:
        self.database_path = database_path
        self.funds_csv = funds_csv

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS funds (
                    ticker TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(funds)").fetchall()
            }
            if "active" not in columns:
                connection.execute(
                    "ALTER TABLE funds ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS prices (
                    ticker TEXT NOT NULL,
                    price_date TEXT NOT NULL,
                    adjusted_close REAL NOT NULL,
                    daily_return REAL,
                    PRIMARY KEY (ticker, price_date),
                    FOREIGN KEY (ticker) REFERENCES funds(ticker)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_prices_ticker_date "
                "ON prices(ticker, price_date)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fund_metadata (
                    ticker TEXT PRIMARY KEY,
                    metadata_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    FOREIGN KEY (ticker) REFERENCES funds(ticker)
                )
                """
            )
        self.sync_funds_from_csv()

    def sync_funds_from_csv(self) -> None:
        if not self.funds_csv.exists():
            raise FileNotFoundError(f"Fund list not found: {self.funds_csv}")

        with self.funds_csv.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "ticker" not in reader.fieldnames:
                raise ValueError("funds.csv must contain a 'ticker' column")
            funds = []
            for row in reader:
                ticker = (row.get("ticker") or "").strip().upper()
                if ticker:
                    funds.append((ticker, (row.get("name") or ticker).strip()))

        if not funds:
            raise ValueError("funds.csv must contain at least one ticker")

        with self.connect() as connection:
            connection.execute("UPDATE funds SET active = 0")
            connection.executemany(
                """
                INSERT INTO funds(ticker, name, active) VALUES (?, ?, 1)
                ON CONFLICT(ticker) DO UPDATE SET
                    name = excluded.name,
                    active = 1
                """,
                funds,
            )

    def list_funds(self) -> list[dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT ticker, name FROM funds WHERE active = 1 ORDER BY ticker"
            ).fetchall()
        return [dict(row) for row in rows]

    def has_fund(self, ticker: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM funds WHERE ticker = ? AND active = 1", (ticker,)
            ).fetchone()
        return row is not None

    def register_discovered_fund(self, ticker: str) -> None:
        """Register a successfully fetched ticker without adding it to the CSV list."""
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO funds(ticker, name, active) VALUES (?, ?, 0)
                ON CONFLICT(ticker) DO NOTHING
                """,
                (ticker, ticker),
            )

    def latest_date(self, ticker: str) -> pd.Timestamp | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT MAX(price_date) AS latest FROM prices WHERE ticker = ?",
                (ticker,),
            ).fetchone()
        return pd.Timestamp(row["latest"]) if row and row["latest"] else None

    def read_metadata(self, ticker: str) -> tuple[dict, pd.Timestamp] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT metadata_json, fetched_at
                FROM fund_metadata
                WHERE ticker = ?
                """,
                (ticker,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["metadata_json"]), pd.Timestamp(row["fetched_at"])

    def upsert_metadata(
        self,
        ticker: str,
        metadata: dict,
        fetched_at: pd.Timestamp,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO fund_metadata(ticker, metadata_json, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    metadata_json = excluded.metadata_json,
                    fetched_at = excluded.fetched_at
                """,
                (ticker, json.dumps(metadata), fetched_at.isoformat()),
            )

    def read_prices(self, ticker: str) -> pd.DataFrame:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT price_date, adjusted_close, daily_return
                FROM prices
                WHERE ticker = ?
                ORDER BY price_date
                """,
                (ticker,),
            ).fetchall()

        if not rows:
            return pd.DataFrame(
                columns=["adjusted_close", "daily_return"],
                index=pd.DatetimeIndex([], name="date"),
            )

        frame = pd.DataFrame(rows, columns=rows[0].keys())
        frame["price_date"] = pd.to_datetime(frame["price_date"])
        return frame.set_index("price_date").rename_axis("date")

    def upsert_prices(self, ticker: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        records = [
            (
                ticker,
                index.strftime("%Y-%m-%d"),
                float(row["adjusted_close"]),
                None if pd.isna(row["daily_return"]) else float(row["daily_return"]),
            )
            for index, row in frame.iterrows()
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO prices(ticker, price_date, adjusted_close, daily_return)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker, price_date) DO UPDATE SET
                    adjusted_close = excluded.adjusted_close,
                    daily_return = excluded.daily_return
                """,
                records,
            )
