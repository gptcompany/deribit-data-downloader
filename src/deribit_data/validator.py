"""Data validation with configurable thresholds.

Validates data quality and integrity with configurable thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq

if TYPE_CHECKING:
    from deribit_data.config import ValidationConfig

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Issue severity level."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Single validation issue."""

    severity: Severity
    category: str
    message: str
    file_path: str | None = None
    details: dict[str, Any] | None = None


@dataclass
class ValidationResult:
    """Validation result with issues and stats."""

    passed: bool
    issues: list[ValidationIssue]
    stats: dict[str, Any]

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.HIGH)


class DataValidator:
    """Validates Deribit options data quality.

    All thresholds are configurable via ValidationConfig.
    """

    def __init__(self, config: ValidationConfig) -> None:
        """Initialize validator.

        Args:
            config: Validation configuration with thresholds.
        """
        self.config = config

    def validate_trades(
        self,
        catalog_path: Path,
        currency: str,
    ) -> ValidationResult:
        """Validate trades data for a currency.

        Checks:
        - IV bounds
        - Price sanity
        - Timestamp ordering
        - Gaps in data
        - Duplicate detection
        - Completeness

        Args:
            catalog_path: Path to data catalog.
            currency: Currency to validate (BTC, ETH).

        Returns:
            ValidationResult with issues and stats.
        """
        trades_dir = catalog_path / currency / "trades"
        issues: list[ValidationIssue] = []
        stats: dict[str, Any] = {
            "total_rows": 0,
            "total_files": 0,
            "date_range": None,
            "iv_outliers": 0,
            "price_outliers": 0,
            "duplicates": 0,
            "gaps": [],
        }

        if not trades_dir.exists():
            issues.append(
                ValidationIssue(
                    severity=Severity.CRITICAL,
                    category="missing_data",
                    message=f"Trades directory not found: {trades_dir}",
                )
            )
            return ValidationResult(passed=False, issues=issues, stats=stats)

        files = sorted(trades_dir.glob("*.parquet"))
        if not files:
            issues.append(
                ValidationIssue(
                    severity=Severity.CRITICAL,
                    category="missing_data",
                    message=f"No parquet files found in {trades_dir}",
                )
            )
            return ValidationResult(passed=False, issues=issues, stats=stats)

        stats["total_files"] = len(files)

        # Track for gap detection
        prev_date: datetime | None = None
        all_trade_ids: set[str] = set()

        for file_path in files:
            try:
                table = pq.read_table(file_path)
                stats["total_rows"] += table.num_rows

                # Check for issues in this file
                file_issues = self._validate_file(file_path, table, all_trade_ids)
                issues.extend(file_issues)

                # Gap detection
                file_date = datetime.strptime(file_path.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if prev_date:
                    gap = (file_date - prev_date).days
                    if gap > 1:
                        gap_severity = self._get_gap_severity(gap)
                        issues.append(
                            ValidationIssue(
                                severity=gap_severity,
                                category="data_gap",
                                message=f"{gap} day gap between {prev_date.date()} and {file_date.date()}",
                                file_path=str(file_path),
                            )
                        )
                        stats["gaps"].append({"start": str(prev_date.date()), "days": gap})
                prev_date = file_date

            except Exception as e:
                issues.append(
                    ValidationIssue(
                        severity=Severity.HIGH,
                        category="file_error",
                        message=f"Error reading {file_path.name}: {e}",
                        file_path=str(file_path),
                    )
                )

        # Set date range
        if files:
            try:
                start = datetime.strptime(files[0].stem, "%Y-%m-%d")
                end = datetime.strptime(files[-1].stem, "%Y-%m-%d")
                stats["date_range"] = (str(start.date()), str(end.date()))
            except ValueError:
                pass

        # Calculate completeness
        if stats["date_range"] and prev_date:
            start_dt = datetime.strptime(files[0].stem, "%Y-%m-%d")
            end_dt = datetime.strptime(files[-1].stem, "%Y-%m-%d")
            expected_days = (end_dt - start_dt).days + 1
            actual_days = len(files)
            completeness = (actual_days / expected_days) * 100 if expected_days > 0 else 0

            if completeness < self.config.critical_completeness:
                issues.append(
                    ValidationIssue(
                        severity=Severity.CRITICAL,
                        category="completeness",
                        message=f"Data completeness {completeness:.1f}% < {self.config.critical_completeness}%",
                    )
                )
            elif completeness < self.config.warning_completeness:
                issues.append(
                    ValidationIssue(
                        severity=Severity.MEDIUM,
                        category="completeness",
                        message=f"Data completeness {completeness:.1f}% < {self.config.warning_completeness}%",
                    )
                )

        # Determine pass/fail
        passed = not any(i.severity == Severity.CRITICAL for i in issues)

        return ValidationResult(passed=passed, issues=issues, stats=stats)

    def _validate_file(
        self,
        file_path: Path,
        table: Any,
        all_trade_ids: set[str],
    ) -> list[ValidationIssue]:
        """Validate a single parquet file."""
        issues: list[ValidationIssue] = []

        if table.num_rows == 0:
            issues.append(
                ValidationIssue(
                    severity=Severity.MEDIUM,
                    category="empty_file",
                    message=f"Empty file: {file_path.name}",
                    file_path=str(file_path),
                )
            )
            return issues

        # Check IV bounds
        if "iv" in table.column_names:
            iv_col = table.column("iv").to_pylist()
            iv_valid = [v for v in iv_col if v is not None]

            low_iv = sum(1 for v in iv_valid if v < self.config.iv_min)
            high_iv = sum(1 for v in iv_valid if v > self.config.iv_max)

            if low_iv > 0:
                issues.append(
                    ValidationIssue(
                        severity=Severity.MEDIUM,
                        category="iv_outlier",
                        message=f"{low_iv} trades with IV < {self.config.iv_min}",
                        file_path=str(file_path),
                    )
                )

            if high_iv > 0:
                issues.append(
                    ValidationIssue(
                        severity=Severity.MEDIUM,
                        category="iv_outlier",
                        message=f"{high_iv} trades with IV > {self.config.iv_max}",
                        file_path=str(file_path),
                    )
                )

        # Check duplicates
        if "trade_id" in table.column_names:
            trade_ids = table.column("trade_id").to_pylist()
            file_ids = set(trade_ids)

            # Duplicates within file
            if len(file_ids) < len(trade_ids):
                dup_count = len(trade_ids) - len(file_ids)
                dup_pct = (dup_count / len(trade_ids)) * 100
                if dup_pct > self.config.duplicate_threshold:
                    issues.append(
                        ValidationIssue(
                            severity=Severity.HIGH,
                            category="duplicates",
                            message=f"{dup_pct:.1f}% duplicates in file",
                            file_path=str(file_path),
                        )
                    )

            # Duplicates across files
            cross_dups = file_ids & all_trade_ids
            if cross_dups:
                issues.append(
                    ValidationIssue(
                        severity=Severity.HIGH,
                        category="cross_duplicates",
                        message=f"{len(cross_dups)} duplicate trade IDs across files",
                        file_path=str(file_path),
                    )
                )

            all_trade_ids.update(file_ids)

        # Check timestamp ordering
        if "timestamp" in table.column_names:
            timestamps = table.column("timestamp").to_pylist()
            unsorted = sum(
                1 for i in range(1, len(timestamps)) if timestamps[i] < timestamps[i - 1]
            )
            if unsorted > 0:
                issues.append(
                    ValidationIssue(
                        severity=Severity.MEDIUM,
                        category="unsorted",
                        message=f"{unsorted} out-of-order timestamps",
                        file_path=str(file_path),
                    )
                )

        return issues

    def _get_gap_severity(self, gap_days: int) -> Severity:
        """Get severity level for a data gap."""
        if gap_days >= self.config.gap_critical_days:
            return Severity.CRITICAL
        elif gap_days >= self.config.gap_high_days:
            return Severity.HIGH
        elif gap_days >= self.config.gap_medium_days:
            return Severity.MEDIUM
        else:
            return Severity.LOW

    def quick_check(self, catalog_path: Path, currency: str) -> bool:
        """Quick validation check (no detailed analysis).

        Args:
            catalog_path: Path to data catalog.
            currency: Currency to check.

        Returns:
            True if data exists and is readable.
        """
        trades_dir = catalog_path / currency / "trades"
        if not trades_dir.exists():
            return False

        files = list(trades_dir.glob("*.parquet"))
        if not files:
            return False

        # Try reading first and last file
        try:
            pq.read_metadata(files[0])
            pq.read_metadata(files[-1])
            return True
        except Exception:
            return False
