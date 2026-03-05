#!/usr/bin/env python3
"""Example: Daily sync cron job.

This script performs an incremental sync of Deribit options data.
Run daily via cron or systemd timer.

Cron example:
    0 6 * * * /path/to/venv/bin/python /path/to/daily_sync.py

Systemd timer example:
    [Unit]
    Description=Deribit data daily sync

    [Timer]
    OnCalendar=*-*-* 06:00:00
    Persistent=true

    [Install]
    WantedBy=timers.target
"""

import logging
import sys
from datetime import UTC, datetime, timedelta

from deribit_data.config import DeribitConfig
from deribit_data.fetcher import DeribitFetcher
from deribit_data.manifest import ManifestManager
from deribit_data.storage import ParquetStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def sync_currency(config: DeribitConfig, currency: str) -> int:
    """Sync a single currency.

    Args:
        config: Configuration.
        currency: Currency to sync.

    Returns:
        Number of new trades fetched.
    """
    storage = ParquetStorage(
        config.catalog_path,
        config.compression,
        config.compression_level,
    )
    manifest = ManifestManager(config.catalog_path)

    # Get last timestamp
    last_ts = storage.get_last_trade_timestamp(currency)
    if not last_ts:
        logger.warning(f"No existing data for {currency}. Run backfill first.")
        return 0

    start_date = last_ts + timedelta(seconds=1)
    end_date = datetime.now(UTC)

    logger.info(f"Syncing {currency} from {start_date.isoformat()}")

    total_trades = 0
    with DeribitFetcher(config) as fetcher:
        for batch in fetcher.fetch_trades_streaming(
            currency=currency,
            start_date=start_date,
            end_date=end_date,
        ):
            written_files = storage.save_trades(batch, currency)
            for f in written_files:
                manifest.update_file(f)
            total_trades += len(batch)
            logger.info(f"  Saved {len(batch)} trades ({total_trades} total)")

    manifest.save()
    logger.info(f"Sync complete: {total_trades} new trades for {currency}")

    return total_trades


def main() -> int:
    """Run daily sync for all currencies."""
    config = DeribitConfig.from_env()

    logger.info(f"Starting daily sync at {datetime.now(UTC).isoformat()}")
    logger.info(f"Catalog: {config.catalog_path}")
    logger.info(f"Currencies: {config.currencies}")

    total = 0
    for currency in config.currencies:
        try:
            total += sync_currency(config, currency)
        except Exception as e:
            logger.error(f"Failed to sync {currency}: {e}")

    logger.info(f"Daily sync complete: {total} new trades total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
