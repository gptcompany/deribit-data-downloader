"""Streaming fetcher for Deribit historical data.

Yields batches of trades instead of accumulating all in memory.
Supports checkpointing for crash recovery.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Generator
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from deribit_data.models import (
    DVOLCandle,
    FailedTrade,
    OptionTrade,
    OptionType,
    TradeDirection,
)

if TYPE_CHECKING:
    from deribit_data.config import DeribitConfig
    from deribit_data.dead_letter import DeadLetterQueue

logger = logging.getLogger(__name__)


class DeribitFetcher:
    """Streaming fetcher for Deribit historical data.

    Features:
    - Generator-based streaming (no RAM accumulation)
    - Configurable retry with exponential backoff
    - Rate limiting
    - DVOL index support

    Example:
        ```python
        config = DeribitConfig.from_env()
        fetcher = DeribitFetcher(config)

        # Streaming fetch
        for batch in fetcher.fetch_trades_streaming("ETH", start_date, end_date):
            storage.save_trades(batch, "ETH")
            checkpoint.save(state)
        ```
    """

    # Instrument pattern: BTC-27DEC24-100000-C
    INSTRUMENT_PATTERN = re.compile(
        r"^(?P<underlying>[A-Z]+)-"
        r"(?P<expiry>\d{1,2}[A-Z]{3}\d{2})-"
        r"(?P<strike>\d+)-"
        r"(?P<type>[CP])$"
    )

    def __init__(self, config: DeribitConfig) -> None:
        """Initialize fetcher.

        Args:
            config: Deribit configuration.
        """
        self.config = config
        self._client = httpx.Client(timeout=config.http_timeout)
        self._last_request_time: float = 0.0

    def close(self) -> None:
        """Close HTTP client."""
        self._client.close()

    def __enter__(self) -> DeribitFetcher:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        if self.config.rate_limit_delay > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.config.rate_limit_delay:
                time.sleep(self.config.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def _request_with_backoff(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Make API request with exponential backoff.

        Args:
            url: API endpoint URL.
            params: Query parameters.

        Returns:
            JSON response data.

        Raises:
            RuntimeError: After max retries exceeded.
        """
        for attempt in range(self.config.max_retries):
            self._rate_limit()

            try:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                result: dict[str, Any] = response.json()
                return result

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limited
                    wait_time = self.config.backoff_base ** (attempt + 1)
                    logger.warning(
                        f"Rate limited, waiting {wait_time:.1f}s "
                        f"(attempt {attempt + 1}/{self.config.max_retries})"
                    )
                    time.sleep(wait_time)
                elif e.response.status_code >= 500:  # Server error
                    wait_time = self.config.backoff_base**attempt
                    logger.warning(
                        f"Server error {e.response.status_code}, retrying in {wait_time:.1f}s"
                    )
                    time.sleep(wait_time)
                elif e.response.status_code == 400:  # Bad request - may be transient
                    wait_time = self.config.backoff_base ** (attempt + 1)
                    logger.warning(
                        f"Bad request 400, retrying in {wait_time:.1f}s "
                        f"(attempt {attempt + 1}/{self.config.max_retries})"
                    )
                    time.sleep(wait_time)
                else:
                    raise

            except httpx.RequestError as e:
                wait_time = self.config.backoff_base**attempt
                logger.warning(f"Request error: {e}, retrying in {wait_time:.1f}s")
                time.sleep(wait_time)

        raise RuntimeError(f"Max retries ({self.config.max_retries}) exceeded for {url}")

    def _parse_instrument(self, instrument_name: str) -> dict[str, Any] | None:
        """Parse instrument name to extract details."""
        match = self.INSTRUMENT_PATTERN.match(instrument_name)
        if not match:
            return None

        groups = match.groupdict()

        # Parse expiry: DDMMMYY -> datetime (08:00 timezone.utc)
        try:
            expiry = datetime.strptime(groups["expiry"], "%d%b%y")
            expiry = expiry.replace(hour=8, minute=0, second=0, tzinfo=timezone.utc)
        except ValueError:
            return None

        return {
            "underlying": groups["underlying"],
            "expiry": expiry,
            "strike": float(groups["strike"]),
            "option_type": OptionType.CALL if groups["type"] == "C" else OptionType.PUT,
        }

    def _parse_trade(self, trade_data: dict[str, Any]) -> tuple[OptionTrade | None, str | None]:
        """Parse raw trade data into OptionTrade.

        Returns:
            Tuple of (trade, error). If trade is None, error contains the reason.
        """
        instrument_name = trade_data.get("instrument_name", "")
        parsed = self._parse_instrument(instrument_name)
        if not parsed:
            return None, f"Invalid instrument format: {instrument_name}"

        # IV may be None for some trades
        iv = trade_data.get("iv")
        iv_decimal = iv / 100.0 if iv and iv > 0 else None

        trade_id = str(trade_data.get("trade_id", trade_data.get("timestamp", "")))

        try:
            trade = OptionTrade(
                trade_id=trade_id,
                instrument_id=instrument_name,
                timestamp=datetime.fromtimestamp(trade_data["timestamp"] / 1000, tz=timezone.utc),
                price=float(trade_data["price"]),
                iv=iv_decimal,
                amount=float(trade_data["amount"]),
                direction=TradeDirection(trade_data["direction"]),
                underlying=parsed["underlying"],
                strike=parsed["strike"],
                expiry=parsed["expiry"],
                option_type=parsed["option_type"],
                index_price=trade_data.get("index_price"),
                mark_price=trade_data.get("mark_price"),
            )
            return trade, None
        except (KeyError, ValueError, TypeError) as e:
            return None, f"Parse error: {e}"

    def fetch_trades_streaming(
        self,
        currency: str,
        start_date: datetime,
        end_date: datetime,
        resume_from_ms: int | None = None,
        dead_letter_queue: DeadLetterQueue | None = None,
    ) -> Generator[list[OptionTrade], None, None]:
        """Fetch trades as a generator (streaming).

        Yields batches of trades instead of accumulating all in memory.
        Each yield contains approximately flush_every_pages * batch_size trades.

        Args:
            currency: Currency (BTC, ETH).
            start_date: Start date (timezone.utc).
            end_date: End date (timezone.utc).
            resume_from_ms: Resume from this timestamp (milliseconds).
            dead_letter_queue: Optional DLQ for failed trade parsing.

        Yields:
            Batches of OptionTrade objects.
        """
        url = f"{self.config.base_url}/get_last_trades_by_currency"

        start_ts = int(start_date.timestamp() * 1000)
        end_ts = int(end_date.timestamp() * 1000)

        # Resume from checkpoint if provided
        if resume_from_ms and resume_from_ms > start_ts:
            start_ts = resume_from_ms + 1
            logger.info(f"Resuming from timestamp {resume_from_ms}")

        params: dict[str, Any] = {
            "currency": currency,
            "kind": "option",
            "count": self.config.batch_size,
            "include_old": "true",
            "sorting": "asc",
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
        }

        page = 0
        batch: list[OptionTrade] = []
        has_more = True

        while has_more:
            logger.debug(f"Fetching page {page}")

            response = self._request_with_backoff(url, params)
            result = response.get("result", {})
            trades_data = result.get("trades", [])
            has_more = result.get("has_more", False)

            if not trades_data:
                break

            for trade_data in trades_data:
                trade, error = self._parse_trade(trade_data)
                if trade:
                    batch.append(trade)
                elif error and dead_letter_queue:
                    dead_letter_queue.add(
                        FailedTrade(raw_data=trade_data, error=error, currency=currency)
                    )

            # Update pagination
            if has_more and trades_data:
                last_ts = trades_data[-1].get("timestamp", 0)
                params["start_timestamp"] = last_ts + 1

            page += 1

            # Yield batch every N pages
            if page % self.config.flush_every_pages == 0 and batch:
                logger.info(
                    f"Page {page}: yielding {len(batch)} trades "
                    f"(last: {batch[-1].timestamp.isoformat()})"
                )
                yield batch
                batch = []

            # Safety limit
            if page > self.config.max_pages:
                logger.warning(f"Reached page limit ({self.config.max_pages})")
                break

        # Yield remaining trades
        if batch:
            logger.info(f"Final batch: {len(batch)} trades")
            yield batch

    def fetch_dvol(
        self,
        currency: str,
        start_date: datetime,
        end_date: datetime,
        resolution: int = 3600,
    ) -> list[DVOLCandle]:
        """Fetch DVOL (Deribit Volatility Index) data with pagination.

        Deribit DVOL API returns the most recent data first and uses a
        continuation token for backward pagination.

        Args:
            currency: Currency (BTC, ETH).
            start_date: Start date (timezone.utc).
            end_date: End date (timezone.utc).
            resolution: Candle resolution in seconds (default: 1 hour).

        Returns:
            List of DVOLCandle objects sorted by timestamp ascending.
        """
        # DVOL endpoint on main API
        url = "https://www.deribit.com/api/v2/public/get_volatility_index_data"

        start_ts = int(start_date.timestamp() * 1000)
        current_end_ts = int(end_date.timestamp() * 1000)

        all_candles: list[DVOLCandle] = []
        page = 0
        max_pages = 100  # Safety limit (~100K candles max)

        while page < max_pages:
            params = {
                "currency": currency,
                "start_timestamp": start_ts,
                "end_timestamp": current_end_ts,
                "resolution": resolution,
            }

            response = self._request_with_backoff(url, params)
            result = response.get("result", {})
            data = result.get("data", [])
            continuation = result.get("continuation")

            if not data:
                break

            batch_candles: list[DVOLCandle] = []
            for row in data:
                # row format: [timestamp, open, high, low, close]
                try:
                    candle = DVOLCandle(
                        timestamp=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                    )
                    batch_candles.append(candle)
                except (IndexError, ValueError, TypeError) as e:
                    logger.debug(f"Failed to parse DVOL candle: {e}")

            if not batch_candles:
                break

            all_candles.extend(batch_candles)
            page += 1

            logger.info(
                f"DVOL page {page}: fetched {len(batch_candles)} candles, total {len(all_candles)}"
            )

            # Use continuation token as new end_timestamp for backward pagination
            if not continuation or continuation <= start_ts:
                break

            current_end_ts = continuation

        # Sort by timestamp ascending (data comes newest-first)
        all_candles.sort(key=lambda c: c.timestamp)

        logger.info(f"Fetched {len(all_candles)} DVOL candles for {currency}")
        return all_candles

    def get_currencies(self) -> list[str]:
        """Get available currencies.

        Returns:
            List of currency codes.
        """
        url = f"{self.config.base_url}/get_currencies"
        response = self._request_with_backoff(url, {})
        result = response.get("result", [])
        return [c.get("currency", "") for c in result if c.get("currency")]
