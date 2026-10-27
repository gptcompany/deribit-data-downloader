"""Data reconciliation against Deribit API.

Verifies data completeness by comparing local trade counts with API reported counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from deribit_data.config import DeribitConfig

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    """Result of reconciliation check."""

    currency: str
    date: datetime
    local_count: int
    api_count: int | None
    matched: bool
    difference: int
    difference_pct: float
    error: str | None = None

    @property
    def is_complete(self) -> bool:
        """Check if data is considered complete."""
        if self.api_count is None:
            return False
        # Allow 1% tolerance for timing differences
        return self.difference_pct <= 1.0


@dataclass
class ReconciliationReport:
    """Full reconciliation report."""

    currency: str
    start_date: datetime
    end_date: datetime
    total_days: int
    matched_days: int
    incomplete_days: int
    missing_days: int
    total_local_trades: int
    total_api_trades: int
    results: list[ReconciliationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def completeness_pct(self) -> float:
        """Calculate overall completeness percentage."""
        if self.total_api_trades == 0:
            return 100.0 if self.total_local_trades == 0 else 0.0
        return (self.total_local_trades / self.total_api_trades) * 100

    @property
    def is_complete(self) -> bool:
        """Check if overall data is complete (>= 99% with no missing days)."""
        return self.completeness_pct >= 99.0 and self.missing_days == 0

    def get_incomplete_dates(self) -> list[datetime]:
        """Get list of dates with incomplete data."""
        return [r.date for r in self.results if not r.is_complete]


class DataReconciler:
    """Reconciles local data against Deribit API.

    Features:
    - Daily trade count verification
    - Missing date detection
    - Completeness percentage calculation
    - Detailed mismatch reporting

    Note: Uses Deribit public API to get trade counts without downloading full data.
    """

    def __init__(self, config: DeribitConfig, catalog_path: Path) -> None:
        """Initialize reconciler.

        Args:
            config: Deribit configuration.
            catalog_path: Path to local data catalog.
        """
        self.config = config
        self.catalog_path = catalog_path
        self._client = httpx.Client(timeout=config.http_timeout)

    def close(self) -> None:
        """Close HTTP client."""
        self._client.close()

    def __enter__(self) -> DataReconciler:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get_api_trade_count(
        self,
        currency: str,
        start_date: datetime,
        end_date: datetime,
    ) -> int | None:
        """Get trade count from API for a date range.

        Uses the trades endpoint with count=1 to get has_more info,
        then estimates based on pagination.
        """
        url = f"{self.config.base_url}/get_last_trades_by_currency"

        start_ts = int(start_date.timestamp() * 1000)
        end_ts = int(end_date.timestamp() * 1000)

        params: dict[str, str | int] = {
            "currency": currency,
            "kind": "option",
            "count": 10000,  # Max batch
            "include_old": "true",
            "sorting": "asc",
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
        }

        try:
            total_count = 0
            page = 0
            max_pages = 1000  # Safety limit for reconciliation

            while page < max_pages:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                result = data.get("result", {})
                trades = result.get("trades", [])
                has_more = result.get("has_more", False)

                total_count += len(trades)

                if not has_more or not trades:
                    break

                # Update for next page
                last_ts = trades[-1].get("timestamp", 0)
                params["start_timestamp"] = last_ts + 1
                page += 1

            return total_count

        except Exception as e:
            logger.warning(f"API error for {currency} {start_date.date()}: {e}")
            return None

    def _get_local_trade_count(self, currency: str, date: datetime) -> int:
        """Get trade count from local parquet file."""
        file_path = self.catalog_path / currency / "trades" / f"{date.strftime('%Y-%m-%d')}.parquet"

        if not file_path.exists():
            return 0

        try:
            metadata = pq.read_metadata(file_path)
            return int(metadata.num_rows)
        except Exception as e:
            logger.warning(f"Error reading {file_path}: {e}")
            return 0

    def reconcile_date(
        self,
        currency: str,
        date: datetime,
    ) -> ReconciliationResult:
        """Reconcile data for a single date.

        Args:
            currency: Currency to check.
            date: Date to reconcile.

        Returns:
            ReconciliationResult for the date.
        """
        # Get local count
        local_count = self._get_local_trade_count(currency, date)

        # Get API count for the full day
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)

        api_count = self._get_api_trade_count(currency, start_of_day, end_of_day)

        if api_count is None:
            return ReconciliationResult(
                currency=currency,
                date=date,
                local_count=local_count,
                api_count=None,
                matched=False,
                difference=0,
                difference_pct=0.0,
                error="API error",
            )

        difference = api_count - local_count
        difference_pct = (abs(difference) / api_count * 100) if api_count > 0 else 0.0
        matched = difference_pct <= 1.0  # 1% tolerance

        return ReconciliationResult(
            currency=currency,
            date=date,
            local_count=local_count,
            api_count=api_count,
            matched=matched,
            difference=difference,
            difference_pct=difference_pct,
        )

    def reconcile_range(
        self,
        currency: str,
        start_date: datetime,
        end_date: datetime,
        sample_days: int | None = None,
    ) -> ReconciliationReport:
        """Reconcile data for a date range.

        Args:
            currency: Currency to check.
            start_date: Start date.
            end_date: End date.
            sample_days: If set, only check this many random days (faster).

        Returns:
            ReconciliationReport with full results.
        """
        # Generate date range
        dates: list[datetime] = []
        current = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=1)

        # Sample if requested
        if sample_days and sample_days < len(dates):
            import random

            dates = sorted(random.sample(dates, sample_days))

        # Initialize report
        report = ReconciliationReport(
            currency=currency,
            start_date=start_date,
            end_date=end_date,
            total_days=len(dates),
            matched_days=0,
            incomplete_days=0,
            missing_days=0,
            total_local_trades=0,
            total_api_trades=0,
        )

        # Reconcile each date
        for date in dates:
            result = self.reconcile_date(currency, date)
            report.results.append(result)

            report.total_local_trades += result.local_count
            if result.api_count is not None:
                report.total_api_trades += result.api_count

            if result.error:
                report.errors.append(f"{date.date()}: {result.error}")
            elif result.local_count == 0 and (result.api_count or 0) > 0:
                report.missing_days += 1
            elif result.is_complete:
                report.matched_days += 1
            else:
                report.incomplete_days += 1

        return report

    def quick_reconcile(
        self,
        currency: str,
        sample_days: int = 10,
    ) -> ReconciliationReport:
        """Quick reconciliation with random sampling.

        Checks random dates to estimate completeness without full scan.

        Args:
            currency: Currency to check.
            sample_days: Number of random days to check.

        Returns:
            ReconciliationReport (sampled).
        """
        # Find date range from local files
        trades_dir = self.catalog_path / currency / "trades"
        if not trades_dir.exists():
            return ReconciliationReport(
                currency=currency,
                start_date=datetime.now(UTC),
                end_date=datetime.now(UTC),
                total_days=0,
                matched_days=0,
                incomplete_days=0,
                missing_days=0,
                total_local_trades=0,
                total_api_trades=0,
                errors=["No local data found"],
            )

        files = sorted(trades_dir.glob("*.parquet"))
        if not files:
            return ReconciliationReport(
                currency=currency,
                start_date=datetime.now(UTC),
                end_date=datetime.now(UTC),
                total_days=0,
                matched_days=0,
                incomplete_days=0,
                missing_days=0,
                total_local_trades=0,
                total_api_trades=0,
                errors=["No parquet files found"],
            )

        start_date = datetime.strptime(files[0].stem, "%Y-%m-%d").replace(tzinfo=UTC)
        end_date = datetime.strptime(files[-1].stem, "%Y-%m-%d").replace(tzinfo=UTC)

        return self.reconcile_range(
            currency=currency,
            start_date=start_date,
            end_date=end_date,
            sample_days=sample_days,
        )
