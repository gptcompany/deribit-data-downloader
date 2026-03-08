"""Parquet storage with atomic writes and daily partitioning.

Provides crash-safe writes using tmp + rename pattern.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq

from deribit_data.models import DVOLCandle, OptionTrade
from deribit_data.schema import DVOL_SCHEMA_V1, TRADES_SCHEMA_V1

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class ParquetStorage:
    """Parquet storage with atomic writes and daily partitioning.

    Features:
    - Atomic writes using tmp + rename pattern
    - Configurable compression (zstd, snappy, gzip)
    - Daily partitioning for trades
    - Single file for DVOL
    """

    def __init__(
        self,
        catalog_path: Path,
        compression: Literal["zstd", "snappy", "gzip", "none"] = "zstd",
        compression_level: int = 3,
    ) -> None:
        """Initialize storage.

        Args:
            catalog_path: Root path for catalog.
            compression: Compression codec.
            compression_level: Compression level (zstd: 1-22).
        """
        self.catalog_path = catalog_path
        self.compression = compression if compression != "none" else None
        self.compression_level = compression_level

        # Create catalog directory
        self.catalog_path.mkdir(parents=True, exist_ok=True)

    def _get_trades_dir(self, currency: str) -> Path:
        """Get trades directory for a currency."""
        return self.catalog_path / currency / "trades"

    def _get_dvol_dir(self, currency: str) -> Path:
        """Get DVOL directory for a currency."""
        return self.catalog_path / currency / "dvol"

    def _get_trade_file_path(self, currency: str, date: datetime) -> Path:
        """Get file path for trades on a specific date."""
        dir_path = self._get_trades_dir(currency)
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"{date.strftime('%Y-%m-%d')}.parquet"

    def _get_dvol_file_path(self, currency: str) -> Path:
        """Get DVOL file path for a currency."""
        dir_path = self._get_dvol_dir(currency)
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / "dvol.parquet"

    def _atomic_write(self, table: pa.Table, file_path: Path) -> None:
        """Atomically write Parquet table using tmp + rename.

        Args:
            table: PyArrow table to write.
            file_path: Target file path.
        """
        tmp_path = file_path.with_suffix(".parquet.tmp")

        # Write to temp file
        write_kwargs: dict[str, Any] = {"compression": self.compression}
        if self.compression == "zstd":
            write_kwargs["compression_level"] = self.compression_level
        pq.write_table(table, tmp_path, **write_kwargs)

        # Atomic rename
        tmp_path.rename(file_path)

        logger.debug(f"Wrote {table.num_rows} rows to {file_path}")

    def _trades_to_table(self, trades: Sequence[OptionTrade]) -> pa.Table:
        """Convert trades to PyArrow table.

        Args:
            trades: Sequence of OptionTrade objects.

        Returns:
            PyArrow table with trades schema.
        """
        if not trades:
            # Create empty table with correct schema
            return TRADES_SCHEMA_V1.empty_table()

        data = {
            "timestamp": [t.timestamp for t in trades],
            "trade_id": [t.trade_id for t in trades],
            "instrument_id": [t.instrument_id for t in trades],
            "underlying": [t.underlying for t in trades],
            "strike": [t.strike for t in trades],
            "expiry": [t.expiry for t in trades],
            "option_type": [t.option_type.value for t in trades],
            "price": [t.price for t in trades],
            "iv": [t.iv for t in trades],
            "amount": [t.amount for t in trades],
            "direction": [t.direction.value for t in trades],
            "index_price": [t.index_price for t in trades],
            "mark_price": [t.mark_price for t in trades],
        }

        return pa.table(data, schema=TRADES_SCHEMA_V1)

    def _dvol_to_table(self, candles: Sequence[DVOLCandle]) -> pa.Table:
        """Convert DVOL candles to PyArrow table.

        Args:
            candles: Sequence of DVOLCandle objects.

        Returns:
            PyArrow table with DVOL schema.
        """
        if not candles:
            return DVOL_SCHEMA_V1.empty_table()

        data = {
            "timestamp": [c.timestamp for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
        }

        return pa.table(data, schema=DVOL_SCHEMA_V1)

    def save_trades(
        self,
        trades: Sequence[OptionTrade],
        currency: str,
    ) -> list[Path]:
        """Save trades with daily partitioning.

        Partitions trades by date and writes each partition atomically.

        Args:
            trades: Trades to save.
            currency: Currency (BTC, ETH).

        Returns:
            List of file paths written.
        """
        if not trades:
            return []

        # Group trades by date
        by_date: dict[str, list[OptionTrade]] = {}
        for trade in trades:
            date_key = trade.timestamp.strftime("%Y-%m-%d")
            if date_key not in by_date:
                by_date[date_key] = []
            by_date[date_key].append(trade)

        # Write each partition
        written_files: list[Path] = []
        for date_str, date_trades in sorted(by_date.items()):
            date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            file_path = self._get_trade_file_path(currency, date)

            # If file exists, merge with existing data
            if file_path.exists():
                existing_table = pq.read_table(file_path)
                new_table = self._trades_to_table(date_trades)
                merged = pa.concat_tables([existing_table, new_table])

                # Deduplicate by trade_id
                # Convert to pandas for dedup, then back to arrow
                df = merged.to_pandas()
                df = df.drop_duplicates(subset=["trade_id"], keep="last")
                df = df.sort_values("timestamp")
                merged = pa.Table.from_pandas(df, schema=TRADES_SCHEMA_V1, preserve_index=False)
            else:
                merged = self._trades_to_table(date_trades)

            self._atomic_write(merged, file_path)
            written_files.append(file_path)

        return written_files

    def save_dvol(self, candles: Sequence[DVOLCandle], currency: str) -> Path:
        """Save DVOL candles.

        Merges with existing data if file exists.

        Args:
            candles: DVOL candles to save.
            currency: Currency (BTC, ETH).

        Returns:
            File path written.
        """
        file_path = self._get_dvol_file_path(currency)

        if file_path.exists():
            existing_table = pq.read_table(file_path)
            new_table = self._dvol_to_table(candles)
            merged = pa.concat_tables([existing_table, new_table])

            # Deduplicate by timestamp
            df = merged.to_pandas()
            df = df.drop_duplicates(subset=["timestamp"], keep="last")
            df = df.sort_values("timestamp")
            merged = pa.Table.from_pandas(df, schema=DVOL_SCHEMA_V1, preserve_index=False)
        else:
            merged = self._dvol_to_table(candles)

        self._atomic_write(merged, file_path)
        return file_path

    def load_trades(
        self,
        currency: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> pa.Table:
        """Load trades for a currency and date range.

        Args:
            currency: Currency (BTC, ETH).
            start_date: Start date (inclusive).
            end_date: End date (inclusive).

        Returns:
            PyArrow table with trades.
        """
        trades_dir = self._get_trades_dir(currency)
        if not trades_dir.exists():
            return TRADES_SCHEMA_V1.empty_table()

        # Find matching files
        files = sorted(trades_dir.glob("*.parquet"))

        if start_date or end_date:
            filtered_files = []
            for f in files:
                try:
                    file_date = datetime.strptime(f.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if start_date and file_date < start_date:
                        continue
                    if end_date and file_date > end_date:
                        continue
                    filtered_files.append(f)
                except ValueError:
                    continue
            files = filtered_files

        if not files:
            return TRADES_SCHEMA_V1.empty_table()

        # Read and concatenate
        tables = [pq.read_table(f) for f in files]
        return pa.concat_tables(tables)

    def load_dvol(self, currency: str) -> pa.Table:
        """Load DVOL data for a currency.

        Args:
            currency: Currency (BTC, ETH).

        Returns:
            PyArrow table with DVOL data.
        """
        file_path = self._get_dvol_file_path(currency)
        if not file_path.exists():
            return DVOL_SCHEMA_V1.empty_table()
        return pq.read_table(file_path)

    def get_last_trade_timestamp(self, currency: str) -> datetime | None:
        """Get timestamp of last trade for a currency.

        Useful for incremental syncs.

        Args:
            currency: Currency (BTC, ETH).

        Returns:
            Last trade timestamp or None if no data.
        """
        trades_dir = self._get_trades_dir(currency)
        if not trades_dir.exists():
            return None

        files = sorted(trades_dir.glob("*.parquet"), reverse=True)
        if not files:
            return None

        # Read last file and get max timestamp
        table = pq.read_table(files[0])
        if table.num_rows == 0:
            return None

        timestamps: list[datetime] = table.column("timestamp").to_pylist()
        return max(timestamps)

    def get_stats(self, currency: str) -> dict[str, Any]:
        """Get statistics for a currency's data.

        Args:
            currency: Currency (BTC, ETH).

        Returns:
            Dict with row_count, file_count, date_range, size_bytes.
        """
        trades_dir = self._get_trades_dir(currency)
        if not trades_dir.exists():
            return {
                "row_count": 0,
                "file_count": 0,
                "date_range": None,
                "size_bytes": 0,
            }

        files = sorted(trades_dir.glob("*.parquet"))
        total_rows = 0
        total_size = 0

        for f in files:
            metadata = pq.read_metadata(f)
            total_rows += metadata.num_rows
            total_size += f.stat().st_size

        date_range = None
        if files:
            try:
                start = datetime.strptime(files[0].stem, "%Y-%m-%d")
                end = datetime.strptime(files[-1].stem, "%Y-%m-%d")
                date_range = (start, end)
            except ValueError:
                pass

        return {
            "row_count": total_rows,
            "file_count": len(files),
            "date_range": date_range,
            "size_bytes": total_size,
        }
