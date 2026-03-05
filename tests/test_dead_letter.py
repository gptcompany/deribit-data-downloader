"""Tests for dead letter queue."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from deribit_data.dead_letter import DeadLetterQueue
from deribit_data.models import FailedTrade


class TestDeadLetterQueue:
    """Test cases for DeadLetterQueue."""

    @pytest.fixture
    def temp_catalog(self, tmp_path: Path) -> Path:
        """Create temporary catalog directory."""
        return tmp_path / "catalog"

    @pytest.fixture
    def dlq(self, temp_catalog: Path) -> DeadLetterQueue:
        """Create DeadLetterQueue instance."""
        return DeadLetterQueue(temp_catalog)

    def test_init_creates_directory(self, temp_catalog: Path, dlq: DeadLetterQueue) -> None:
        """Test DLQ creates _dead_letters directory."""
        assert (temp_catalog / "_dead_letters").exists()

    def test_add_failed_trade(self, dlq: DeadLetterQueue) -> None:
        """Test adding failed trade."""
        failed = FailedTrade(
            raw_data={"instrument_name": "INVALID-INST", "price": 0.05},
            error="Invalid instrument format",
            currency="BTC",
        )

        dlq.add(failed)

        assert dlq.get_total_failures() == 1
        assert dlq.get_total_failures("BTC") == 1
        assert dlq.get_total_failures("ETH") == 0

    def test_add_multiple_failures(self, dlq: DeadLetterQueue) -> None:
        """Test adding multiple failures."""
        for i in range(5):
            failed = FailedTrade(
                raw_data={"trade_id": f"fail_{i}"},
                error=f"Error {i}",
                currency="ETH",
            )
            dlq.add(failed)

        assert dlq.get_total_failures() == 5
        assert dlq.get_total_failures("ETH") == 5

    def test_load_failures(self, dlq: DeadLetterQueue) -> None:
        """Test loading failures from disk."""
        # Add some failures
        for i in range(3):
            failed = FailedTrade(
                raw_data={"trade_id": f"fail_{i}"},
                error=f"Error {i}",
                currency="BTC",
            )
            dlq.add(failed)

        # Load back
        failures = dlq.load_failures("BTC")

        assert len(failures) == 3
        assert failures[0].raw_data["trade_id"] == "fail_0"
        assert "Error 0" in failures[0].error

    def test_get_stats(self, dlq: DeadLetterQueue) -> None:
        """Test getting stats."""
        failed = FailedTrade(
            raw_data={"trade_id": "fail_1"},
            error="Test error",
            currency="BTC",
        )
        dlq.add(failed)

        stats = dlq.get_stats()

        assert len(stats) == 1
        # Key format is "CURRENCY:YYYY-MM-DD"
        assert any("BTC" in k for k in stats)

    def test_get_summary(self, dlq: DeadLetterQueue) -> None:
        """Test getting summary."""
        # Add failures for different currencies
        for currency in ["BTC", "ETH"]:
            for i in range(2):
                failed = FailedTrade(
                    raw_data={"trade_id": f"{currency}_fail_{i}"},
                    error=f"Error {i}",
                    currency=currency,
                )
                dlq.add(failed)

        summary = dlq.get_summary()

        assert summary["total_failures"] == 4
        assert summary["by_currency"]["BTC"] == 2
        assert summary["by_currency"]["ETH"] == 2
        assert summary["total_files"] == 2

    def test_load_with_date_filter(self, dlq: DeadLetterQueue) -> None:
        """Test loading with date filter."""
        # Add failure with specific timestamp
        failed = FailedTrade(
            raw_data={"trade_id": "test"},
            error="Test error",
            timestamp=datetime(2024, 1, 15, tzinfo=UTC),
            currency="BTC",
        )
        dlq.add(failed)

        # Load with filter that excludes it
        failures = dlq.load_failures(
            "BTC",
            start_date=datetime(2024, 2, 1, tzinfo=UTC),
        )

        assert len(failures) == 0

        # Load with filter that includes it
        failures = dlq.load_failures(
            "BTC",
            start_date=datetime(2024, 1, 1, tzinfo=UTC),
            end_date=datetime(2024, 1, 31, tzinfo=UTC),
        )

        assert len(failures) == 1

    def test_empty_summary(self, dlq: DeadLetterQueue) -> None:
        """Test summary with no failures."""
        summary = dlq.get_summary()

        assert summary["total_failures"] == 0
        assert summary["total_files"] == 0
        assert summary["by_currency"] == {}
