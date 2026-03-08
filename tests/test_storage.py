"""Tests for storage module."""

from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from deribit_data.models import DVOLCandle, OptionTrade, OptionType, TradeDirection
from deribit_data.storage import ParquetStorage


class TestParquetStorage:
    """Tests for ParquetStorage."""

    def test_init_creates_directory(self, tmp_path: Path) -> None:
        """Test initialization creates catalog directory."""
        catalog = tmp_path / "catalog"
        assert not catalog.exists()

        ParquetStorage(catalog)

        assert catalog.exists()

    def test_save_trades_creates_partitions(
        self, tmp_catalog: Path, sample_trades: list[OptionTrade]
    ) -> None:
        """Test trades are saved with daily partitioning."""
        storage = ParquetStorage(tmp_catalog)

        written = storage.save_trades(sample_trades, "ETH")

        assert len(written) > 0
        for file_path in written:
            assert file_path.exists()
            assert file_path.suffix == ".parquet"

    def test_save_trades_deduplicates(self, tmp_catalog: Path) -> None:
        """Test duplicate trades are removed on save."""
        storage = ParquetStorage(tmp_catalog)

        trade = OptionTrade(
            trade_id="unique_id",
            instrument_id="BTC-27DEC24-100000-C",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            price=0.05,
            iv=0.65,
            amount=1.0,
            direction=TradeDirection.BUY,
            underlying="BTC",
            strike=100000.0,
            expiry=datetime(2024, 12, 27, 8, 0, 0, tzinfo=timezone.utc),
            option_type=OptionType.CALL,
        )

        # Save same trade twice
        storage.save_trades([trade], "BTC")
        storage.save_trades([trade], "BTC")

        # Load and check no duplicates
        table = storage.load_trades("BTC")
        assert table.num_rows == 1

    def test_save_trades_empty_list(self, tmp_catalog: Path) -> None:
        """Test saving empty list returns empty."""
        storage = ParquetStorage(tmp_catalog)

        written = storage.save_trades([], "BTC")

        assert written == []

    def test_load_trades_nonexistent(self, tmp_catalog: Path) -> None:
        """Test loading from nonexistent currency returns empty table."""
        storage = ParquetStorage(tmp_catalog)

        table = storage.load_trades("SOL")

        assert table.num_rows == 0

    def test_load_trades_date_filter(
        self, tmp_catalog: Path, sample_trades: list[OptionTrade]
    ) -> None:
        """Test loading trades with date filter."""
        storage = ParquetStorage(tmp_catalog)
        storage.save_trades(sample_trades, "ETH")

        # Load only first day
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 1, 23, 59, 59, tzinfo=timezone.utc)

        table = storage.load_trades("ETH", start_date=start, end_date=end)

        assert table.num_rows > 0
        # All timestamps should be on 2024-01-01
        timestamps = table.column("timestamp").to_pylist()
        for ts in timestamps:
            assert ts.date() == start.date()

    def test_save_dvol(self, tmp_catalog: Path, sample_dvol_candles: list[DVOLCandle]) -> None:
        """Test saving DVOL candles."""
        storage = ParquetStorage(tmp_catalog)

        file_path = storage.save_dvol(sample_dvol_candles, "BTC")

        assert file_path.exists()
        table = pq.read_table(file_path)
        assert table.num_rows == len(sample_dvol_candles)

    def test_load_dvol(self, tmp_catalog: Path, sample_dvol_candles: list[DVOLCandle]) -> None:
        """Test loading DVOL candles."""
        storage = ParquetStorage(tmp_catalog)
        storage.save_dvol(sample_dvol_candles, "BTC")

        table = storage.load_dvol("BTC")

        assert table.num_rows == len(sample_dvol_candles)
        assert "open" in table.column_names
        assert "close" in table.column_names

    def test_get_last_trade_timestamp(
        self, tmp_catalog: Path, sample_trades: list[OptionTrade]
    ) -> None:
        """Test getting last trade timestamp."""
        storage = ParquetStorage(tmp_catalog)
        storage.save_trades(sample_trades, "ETH")

        last_ts = storage.get_last_trade_timestamp("ETH")

        assert last_ts is not None
        expected_max = max(t.timestamp for t in sample_trades)
        assert last_ts == expected_max

    def test_get_last_trade_timestamp_no_data(self, tmp_catalog: Path) -> None:
        """Test getting last timestamp when no data exists."""
        storage = ParquetStorage(tmp_catalog)

        last_ts = storage.get_last_trade_timestamp("BTC")

        assert last_ts is None

    def test_get_stats(self, tmp_catalog: Path, sample_trades: list[OptionTrade]) -> None:
        """Test getting catalog stats."""
        storage = ParquetStorage(tmp_catalog)
        storage.save_trades(sample_trades, "ETH")

        stats = storage.get_stats("ETH")

        assert stats["row_count"] == len(sample_trades)
        assert stats["file_count"] > 0
        assert stats["size_bytes"] > 0
        assert stats["date_range"] is not None

    def test_compression_zstd(self, tmp_catalog: Path, sample_trades: list[OptionTrade]) -> None:
        """Test zstd compression is applied."""
        storage = ParquetStorage(tmp_catalog, compression="zstd")

        written = storage.save_trades(sample_trades, "ETH")

        # Check compression in metadata
        metadata = pq.read_metadata(written[0])
        # Parquet metadata should show compression
        assert metadata.num_row_groups > 0

    def test_atomic_write_no_temp_files(
        self, tmp_catalog: Path, sample_trades: list[OptionTrade]
    ) -> None:
        """Test no temp files remain after write."""
        storage = ParquetStorage(tmp_catalog)
        storage.save_trades(sample_trades, "ETH")

        # No .tmp files should exist
        tmp_files = list(tmp_catalog.rglob("*.tmp"))
        assert len(tmp_files) == 0
