"""Catalog freshness: DVOL resume point and Prometheus textfile metrics.

A stalled sync used to stay silent for months (trades stopped 2026-06-30, DVOL
2026-02-05). The metrics describe the catalog content, not the last run, so a
timer that never fires is seen as ageing data and a missing file as absent().
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from deribit_data.storage import ParquetStorage

logger = logging.getLogger(__name__)


def last_dvol_timestamp(storage: ParquetStorage, currency: str) -> datetime | None:
    """Return the newest DVOL candle timestamp, or None if the file is empty or absent."""
    table = storage.load_dvol(currency)
    if table.num_rows == 0:
        return None
    timestamps: list[datetime] = table.column("timestamp").to_pylist()
    return max(timestamps)


def dvol_resume_start(storage: ParquetStorage, currency: str, fallback: datetime) -> datetime:
    """First day to download so the DVOL series continues without gap.

    Re-downloading the whole last day is harmless: save_dvol deduplicates.
    """
    last = last_dvol_timestamp(storage, currency)
    if last is None:
        return fallback
    return datetime(last.year, last.month, last.day, tzinfo=UTC) + timedelta(days=1)


def render_metrics(storage: ParquetStorage, currencies: Sequence[str], now: datetime) -> str:
    """Render the catalog freshness in Prometheus text format.

    Series with no data are omitted rather than set to 0, so alerts use absent().
    """
    lines = [
        "# HELP deribit_catalog_last_trade_timestamp_seconds Newest trade in the catalog.",
        "# TYPE deribit_catalog_last_trade_timestamp_seconds gauge",
    ]
    for currency in currencies:
        ts = storage.get_last_trade_timestamp(currency)
        if ts is not None:
            lines.append(
                f'deribit_catalog_last_trade_timestamp_seconds{{currency="{currency}"}} '
                f"{ts.timestamp():.0f}"
            )
    lines += [
        "# HELP deribit_catalog_last_dvol_timestamp_seconds Newest DVOL candle in the catalog.",
        "# TYPE deribit_catalog_last_dvol_timestamp_seconds gauge",
    ]
    for currency in currencies:
        ts = last_dvol_timestamp(storage, currency)
        if ts is not None:
            lines.append(
                f'deribit_catalog_last_dvol_timestamp_seconds{{currency="{currency}"}} '
                f"{ts.timestamp():.0f}"
            )
    lines += [
        "# HELP deribit_catalog_scan_timestamp_seconds End of the last catalog scan.",
        "# TYPE deribit_catalog_scan_timestamp_seconds gauge",
        f"deribit_catalog_scan_timestamp_seconds {now.timestamp():.0f}",
    ]
    return "\n".join(lines) + "\n"


def write_metrics(path: Path, text: str) -> None:
    """Write the textfile atomically: node_exporter must never read a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)  # node_exporter runs as another user
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    logger.info("metrics written to %s", path)
