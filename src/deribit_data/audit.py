"""Audit logging for data operations.

Provides persistent logging of all download operations for compliance and debugging.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuditEventType(StrEnum):
    """Types of audit events."""

    BACKFILL_START = "backfill_start"
    BACKFILL_COMPLETE = "backfill_complete"
    BACKFILL_ERROR = "backfill_error"
    BACKFILL_RESUME = "backfill_resume"
    SYNC_START = "sync_start"
    SYNC_COMPLETE = "sync_complete"
    SYNC_ERROR = "sync_error"
    DVOL_DOWNLOAD = "dvol_download"
    VALIDATION_RUN = "validation_run"
    FILE_WRITTEN = "file_written"
    CHECKPOINT_SAVE = "checkpoint_save"
    DLQ_FAILURE = "dlq_failure"


class AuditEvent(BaseModel):
    """Single audit event."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: AuditEventType
    currency: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    def to_json_line(self) -> str:
        """Convert to JSON line format."""
        data = {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "currency": self.currency,
            **self.details,
        }
        return json.dumps(data)


class AuditLog:
    """Persistent audit log for data operations.

    Writes to JSON Lines format for easy processing.
    File format: audit_YYYY-MM.jsonl (monthly rotation)

    Features:
    - Append-only log
    - Monthly rotation
    - Queryable history
    - Compliance ready
    """

    def __init__(self, catalog_path: Path) -> None:
        """Initialize audit log.

        Args:
            catalog_path: Root path for catalog (creates _audit subdir).
        """
        self.audit_path = catalog_path / "_audit"
        self.audit_path.mkdir(parents=True, exist_ok=True)

    def _get_current_file(self) -> Path:
        """Get current audit log file (monthly rotation)."""
        month_str = datetime.now(UTC).strftime("%Y-%m")
        return self.audit_path / f"audit_{month_str}.jsonl"

    def log(self, event: AuditEvent) -> None:
        """Log an audit event.

        Args:
            event: The event to log.
        """
        file_path = self._get_current_file()
        with open(file_path, "a") as f:
            f.write(event.to_json_line() + "\n")
        logger.debug(f"Audit: {event.event_type} - {event.currency or 'N/A'}")

    def log_backfill_start(
        self,
        currency: str,
        start_date: datetime,
        end_date: datetime,
        resume: bool = False,
    ) -> None:
        """Log backfill start event."""
        event_type = AuditEventType.BACKFILL_RESUME if resume else AuditEventType.BACKFILL_START
        self.log(
            AuditEvent(
                event_type=event_type,
                currency=currency,
                details={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
            )
        )

    def log_backfill_complete(
        self,
        currency: str,
        trades_count: int,
        files_count: int,
        duration_seconds: float,
        dlq_failures: int = 0,
    ) -> None:
        """Log backfill completion."""
        self.log(
            AuditEvent(
                event_type=AuditEventType.BACKFILL_COMPLETE,
                currency=currency,
                details={
                    "trades_count": trades_count,
                    "files_count": files_count,
                    "duration_seconds": round(duration_seconds, 2),
                    "dlq_failures": dlq_failures,
                },
            )
        )

    def log_backfill_error(self, currency: str, error: str) -> None:
        """Log backfill error."""
        self.log(
            AuditEvent(
                event_type=AuditEventType.BACKFILL_ERROR,
                currency=currency,
                details={"error": error},
            )
        )

    def log_sync_start(self, currency: str, from_timestamp: datetime) -> None:
        """Log sync start event."""
        self.log(
            AuditEvent(
                event_type=AuditEventType.SYNC_START,
                currency=currency,
                details={"from_timestamp": from_timestamp.isoformat()},
            )
        )

    def log_sync_complete(self, currency: str, trades_count: int, duration_seconds: float) -> None:
        """Log sync completion."""
        self.log(
            AuditEvent(
                event_type=AuditEventType.SYNC_COMPLETE,
                currency=currency,
                details={
                    "trades_count": trades_count,
                    "duration_seconds": round(duration_seconds, 2),
                },
            )
        )

    def log_file_written(
        self,
        currency: str,
        file_path: Path,
        rows: int,
        sha256: str | None = None,
    ) -> None:
        """Log file write event."""
        self.log(
            AuditEvent(
                event_type=AuditEventType.FILE_WRITTEN,
                currency=currency,
                details={
                    "file_path": str(file_path),
                    "rows": rows,
                    "sha256": sha256,
                },
            )
        )

    def log_validation_run(
        self,
        currency: str,
        passed: bool,
        issues_count: int,
        stats: dict,
    ) -> None:
        """Log validation run."""
        self.log(
            AuditEvent(
                event_type=AuditEventType.VALIDATION_RUN,
                currency=currency,
                details={
                    "passed": passed,
                    "issues_count": issues_count,
                    "stats": stats,
                },
            )
        )

    def log_dlq_failure(self, currency: str, error: str, instrument: str | None) -> None:
        """Log dead letter queue failure."""
        self.log(
            AuditEvent(
                event_type=AuditEventType.DLQ_FAILURE,
                currency=currency,
                details={"error": error, "instrument": instrument},
            )
        )

    def get_recent_events(
        self,
        limit: int = 100,
        event_type: AuditEventType | None = None,
        currency: str | None = None,
    ) -> list[dict]:
        """Get recent audit events.

        Args:
            limit: Maximum events to return.
            event_type: Filter by event type (optional).
            currency: Filter by currency (optional).

        Returns:
            List of event dicts (most recent first).
        """
        events: list[dict] = []

        # Read from most recent files first
        for file_path in sorted(self.audit_path.glob("audit_*.jsonl"), reverse=True):
            with open(file_path) as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())

                        # Apply filters
                        if event_type and event.get("event_type") != event_type.value:
                            continue
                        if currency and event.get("currency") != currency:
                            continue

                        events.append(event)

                        if len(events) >= limit:
                            break
                    except json.JSONDecodeError:
                        continue

            if len(events) >= limit:
                break

        # Sort by timestamp descending
        events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return events[:limit]

    def get_summary(self) -> dict:
        """Get audit log summary.

        Returns:
            Summary dict with counts and recent activity.
        """
        summary = {
            "total_files": 0,
            "total_events": 0,
            "by_event_type": {},
            "by_currency": {},
            "recent_errors": [],
        }

        for file_path in self.audit_path.glob("audit_*.jsonl"):
            summary["total_files"] += 1

            with open(file_path) as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        summary["total_events"] += 1

                        # Count by type
                        etype = event.get("event_type", "unknown")
                        summary["by_event_type"][etype] = summary["by_event_type"].get(etype, 0) + 1

                        # Count by currency
                        currency = event.get("currency", "N/A")
                        if currency:
                            summary["by_currency"][currency] = (
                                summary["by_currency"].get(currency, 0) + 1
                            )

                        # Track recent errors
                        if "error" in etype.lower() and len(summary["recent_errors"]) < 10:
                            summary["recent_errors"].append(event)

                    except json.JSONDecodeError:
                        continue

        return summary
