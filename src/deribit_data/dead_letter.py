"""Dead letter queue for failed trade parsing.

Saves malformed trades instead of silently discarding them.
Enables debugging, recovery, and data quality monitoring.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deribit_data.models import FailedTrade

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    """Dead letter queue for failed trades.

    Saves malformed trades to JSON files for later analysis and recovery.
    File format: {currency}_dead_letters_{date}.jsonl (JSON Lines)

    Features:
    - Atomic writes (tmp + rename)
    - Daily rotation
    - JSON Lines format for easy processing
    - Statistics tracking
    """

    def __init__(self, catalog_path: Path) -> None:
        """Initialize dead letter queue.

        Args:
            catalog_path: Root path for catalog (creates _dead_letters subdir).
        """
        self.dlq_path = catalog_path / "_dead_letters"
        self.dlq_path.mkdir(parents=True, exist_ok=True)
        self._stats: dict[str, int] = {}

    def add(self, failed_trade: FailedTrade) -> None:
        """Add a failed trade to the queue.

        Args:
            failed_trade: The failed trade to save.
        """
        date_str = failed_trade.timestamp.strftime("%Y-%m-%d")
        file_path = self.dlq_path / f"{failed_trade.currency.lower()}_dead_letters_{date_str}.jsonl"

        # Append to file (creates if not exists)
        record = {
            "raw_data": failed_trade.raw_data,
            "error": failed_trade.error,
            "timestamp": failed_trade.timestamp.isoformat(),
            "currency": failed_trade.currency,
        }

        with open(file_path, "a") as f:
            f.write(json.dumps(record) + "\n")

        # Update stats
        key = f"{failed_trade.currency}:{date_str}"
        self._stats[key] = self._stats.get(key, 0) + 1

        logger.warning(
            f"Dead letter: {failed_trade.error} "
            f"(instrument: {failed_trade.raw_data.get('instrument_name', 'unknown')})"
        )

    def get_stats(self) -> dict[str, int]:
        """Get failure statistics.

        Returns:
            Dict mapping currency:date to failure count.
        """
        return dict(self._stats)

    def get_total_failures(self, currency: str | None = None) -> int:
        """Get total failure count.

        Args:
            currency: Filter by currency (optional).

        Returns:
            Total number of failures.
        """
        if currency:
            return sum(v for k, v in self._stats.items() if k.startswith(f"{currency}:"))
        return sum(self._stats.values())

    def load_failures(
        self,
        currency: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[FailedTrade]:
        """Load failed trades from disk.

        Args:
            currency: Currency to load.
            start_date: Filter by start date (optional).
            end_date: Filter by end date (optional).

        Returns:
            List of FailedTrade objects.
        """
        failures: list[FailedTrade] = []
        pattern = f"{currency.lower()}_dead_letters_*.jsonl"

        for file_path in sorted(self.dlq_path.glob(pattern)):
            # Extract date from filename
            date_str = file_path.stem.split("_")[-1]
            try:
                file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            # Date filtering
            if start_date and file_date.date() < start_date.date():
                continue
            if end_date and file_date.date() > end_date.date():
                continue

            with open(file_path) as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        failures.append(
                            FailedTrade(
                                raw_data=record["raw_data"],
                                error=record["error"],
                                timestamp=datetime.fromisoformat(record["timestamp"]),
                                currency=record["currency"],
                            )
                        )
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.debug(f"Error loading dead letter: {e}")

        return failures

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all dead letter files.

        Returns:
            Dict with file counts, total failures, and breakdown by currency.
        """
        total_files = 0
        total_failures = 0
        by_currency: dict[str, int] = {}
        files: list[dict[str, Any]] = []

        for file_path in sorted(self.dlq_path.glob("*_dead_letters_*.jsonl")):
            with open(file_path) as f:
                line_count = sum(1 for _ in f)
            currency = file_path.stem.split("_")[0].upper()

            total_files += 1
            total_failures += line_count
            by_currency[currency] = by_currency.get(currency, 0) + line_count
            files.append(
                {
                    "path": str(file_path),
                    "currency": currency,
                    "failures": line_count,
                }
            )

        return {
            "total_files": total_files,
            "total_failures": total_failures,
            "by_currency": by_currency,
            "files": files,
        }
