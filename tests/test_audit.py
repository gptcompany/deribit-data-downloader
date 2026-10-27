"""Tests for audit log."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from deribit_data.audit import AuditEvent, AuditEventType, AuditLog


class TestAuditLog:
    """Test cases for AuditLog."""

    @pytest.fixture
    def temp_catalog(self, tmp_path: Path) -> Path:
        """Create temporary catalog directory."""
        return tmp_path / "catalog"

    @pytest.fixture
    def audit(self, temp_catalog: Path) -> AuditLog:
        """Create AuditLog instance."""
        return AuditLog(temp_catalog)

    def test_init_creates_directory(self, temp_catalog: Path, audit: AuditLog) -> None:
        """Test audit log creates _audit directory."""
        assert (temp_catalog / "_audit").exists()

    def test_log_event(self, audit: AuditLog) -> None:
        """Test logging a basic event."""
        event = AuditEvent(
            event_type=AuditEventType.BACKFILL_START,
            currency="BTC",
            details={"start_date": "2024-01-01"},
        )

        audit.log(event)

        # Verify file was created
        files = list(audit.audit_path.glob("audit_*.jsonl"))
        assert len(files) == 1

    def test_log_backfill_start(self, audit: AuditLog) -> None:
        """Test logging backfill start."""
        audit.log_backfill_start(
            currency="ETH",
            start_date=datetime(2024, 1, 1, tzinfo=UTC),
            end_date=datetime(2024, 12, 31, tzinfo=UTC),
        )

        events = audit.get_recent_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "backfill_start"
        assert events[0]["currency"] == "ETH"

    def test_log_backfill_complete(self, audit: AuditLog) -> None:
        """Test logging backfill completion."""
        audit.log_backfill_complete(
            currency="BTC",
            trades_count=1000000,
            files_count=500,
            duration_seconds=3600.5,
            dlq_failures=10,
        )

        events = audit.get_recent_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "backfill_complete"
        assert events[0]["trades_count"] == 1000000
        assert events[0]["dlq_failures"] == 10

    def test_log_backfill_error(self, audit: AuditLog) -> None:
        """Test logging backfill error."""
        audit.log_backfill_error("BTC", "Connection timeout")

        events = audit.get_recent_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "backfill_error"
        assert events[0]["error"] == "Connection timeout"

    def test_log_file_written(self, audit: AuditLog) -> None:
        """Test logging file write."""
        audit.log_file_written(
            currency="ETH",
            file_path=Path("/data/ETH/trades/2024-01-01.parquet"),
            rows=15000,
            sha256="abc123",
        )

        events = audit.get_recent_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "file_written"
        assert events[0]["rows"] == 15000

    def test_get_recent_events_with_filter(self, audit: AuditLog) -> None:
        """Test filtering recent events."""
        # Log multiple events
        audit.log_backfill_start(
            "BTC", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 12, 31, tzinfo=UTC)
        )
        audit.log_backfill_complete("BTC", 1000, 100, 60.0)
        audit.log_backfill_start(
            "ETH", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 12, 31, tzinfo=UTC)
        )

        # Filter by event type
        events = audit.get_recent_events(event_type=AuditEventType.BACKFILL_START)
        assert len(events) == 2

        # Filter by currency
        events = audit.get_recent_events(currency="ETH")
        assert len(events) == 1

    def test_get_summary(self, audit: AuditLog) -> None:
        """Test getting summary."""
        # Log multiple events
        audit.log_backfill_start(
            "BTC", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 12, 31, tzinfo=UTC)
        )
        audit.log_backfill_complete("BTC", 1000, 100, 60.0)
        audit.log_backfill_error("ETH", "Test error")

        summary = audit.get_summary()

        assert summary["total_events"] == 3
        assert "backfill_start" in summary["by_event_type"]
        assert "backfill_complete" in summary["by_event_type"]
        assert summary["by_currency"]["BTC"] == 2
        assert summary["by_currency"]["ETH"] == 1
        assert len(summary["recent_errors"]) == 1

    def test_empty_summary(self, audit: AuditLog) -> None:
        """Test summary with no events."""
        summary = audit.get_summary()

        assert summary["total_events"] == 0
        assert summary["total_files"] == 0

    def test_audit_event_to_json_line(self) -> None:
        """Test event serialization."""
        event = AuditEvent(
            event_type=AuditEventType.VALIDATION_RUN,
            currency="BTC",
            details={"passed": True, "issues_count": 5},
        )

        json_line = event.to_json_line()

        assert "validation_run" in json_line
        assert "BTC" in json_line
        assert "passed" in json_line
