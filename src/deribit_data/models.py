"""Data models for Deribit options data.

Provides Pydantic models for option trades, DVOL candles, and checkpoint state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class OptionType(str, Enum):
    """Option type enum."""

    CALL = "call"
    PUT = "put"


class TradeDirection(str, Enum):
    """Trade direction enum."""

    BUY = "buy"
    SELL = "sell"


class OptionTrade(BaseModel):
    """Single option trade from Deribit History API.

    Attributes:
        trade_id: Unique trade identifier.
        instrument_id: Deribit instrument name (e.g., BTC-27DEC24-100000-C).
        timestamp: Trade execution timestamp (timezone.utc).
        price: Trade price in USD.
        iv: Implied volatility at execution (0.0-10.0 range).
        amount: Trade size in contracts.
        direction: Trade direction (buy/sell).
        underlying: Underlying asset (BTC, ETH).
        strike: Strike price in USD.
        expiry: Option expiration timestamp (timezone.utc).
        option_type: Call or put.
        index_price: Underlying index price at trade time.
        mark_price: Mark price at trade time.
    """

    model_config = {"frozen": True}

    trade_id: str
    instrument_id: str
    timestamp: datetime
    price: float = Field(ge=0)
    iv: float | None = Field(default=None, ge=0, le=10.0)
    amount: float = Field(gt=0)
    direction: TradeDirection
    underlying: str
    strike: float = Field(gt=0)
    expiry: datetime
    option_type: OptionType
    index_price: float | None = Field(default=None, ge=0)
    mark_price: float | None = Field(default=None, ge=0)

    @field_validator("underlying")
    @classmethod
    def validate_underlying(cls, v: str) -> str:
        """Validate underlying is a known currency."""
        allowed = {"BTC", "ETH", "SOL", "USDC"}
        if v not in allowed:
            raise ValueError(f"Unknown underlying: {v}, expected one of {allowed}")
        return v


class DVOLCandle(BaseModel):
    """DVOL (Deribit Volatility Index) OHLC candle.

    Attributes:
        timestamp: Candle open timestamp (timezone.utc).
        open: Opening IV value.
        high: Highest IV value.
        low: Lowest IV value.
        close: Closing IV value.
    """

    model_config = {"frozen": True}

    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)

    @field_validator("high")
    @classmethod
    def high_gte_low(cls, v: float, info: ValidationInfo) -> float:
        """Validate high >= low."""
        if "low" in info.data and v < info.data["low"]:
            raise ValueError(f"high ({v}) must be >= low ({info.data['low']})")
        return v


class FailedTrade(BaseModel):
    """Failed trade for dead letter queue.

    Captures malformed trades that couldn't be parsed for debugging and recovery.

    Attributes:
        raw_data: Original JSON data from API.
        error: Error message describing parse failure.
        timestamp: When the failure occurred.
        currency: Currency being processed.
    """

    raw_data: dict
    error: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    currency: str


class CheckpointState(BaseModel):
    """Checkpoint state for crash recovery.

    Attributes:
        currency: Currency being downloaded (BTC, ETH).
        last_timestamp_ms: Last trade timestamp in milliseconds.
        last_page: Last completed page number.
        trades_fetched: Total trades fetched so far.
        started_at: Download start timestamp.
        last_flush_at: Last flush to disk timestamp.
        files_written: List of files written so far.
    """

    currency: str
    last_timestamp_ms: int = 0
    last_page: int = 0
    trades_fetched: int = 0
    started_at: datetime
    last_flush_at: datetime | None = None
    files_written: list[str] = Field(default_factory=list)

    def update_progress(
        self,
        timestamp_ms: int,
        page: int,
        trades_count: int,
        file_written: str | None = None,
    ) -> CheckpointState:
        """Create updated checkpoint with new progress."""
        files = list(self.files_written)
        if file_written and file_written not in files:
            files.append(file_written)

        return CheckpointState(
            currency=self.currency,
            last_timestamp_ms=timestamp_ms,
            last_page=page,
            trades_fetched=self.trades_fetched + trades_count,
            started_at=self.started_at,
            last_flush_at=datetime.now(timezone.utc),
            files_written=files,
        )
