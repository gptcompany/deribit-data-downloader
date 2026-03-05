"""Pytest fixtures for deribit-data-downloader tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from deribit_data.config import DeribitConfig, ValidationConfig
from deribit_data.models import DVOLCandle, OptionTrade, OptionType, TradeDirection


@pytest.fixture
def tmp_catalog(tmp_path: Path) -> Path:
    """Create temporary catalog directory."""
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    return catalog


@pytest.fixture
def tmp_checkpoint_dir(tmp_path: Path) -> Path:
    """Create temporary checkpoint directory."""
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    return checkpoint_dir


@pytest.fixture
def config(tmp_catalog: Path, tmp_checkpoint_dir: Path) -> DeribitConfig:
    """Create test configuration."""
    return DeribitConfig(
        catalog_path=tmp_catalog,
        checkpoint_dir=tmp_checkpoint_dir,
        flush_every_pages=2,
        batch_size=100,
        max_retries=2,
    )


@pytest.fixture
def validation_config() -> ValidationConfig:
    """Create validation configuration."""
    return ValidationConfig(
        iv_min=0.01,
        iv_max=5.0,
        duplicate_threshold=5.0,
    )


@pytest.fixture
def sample_trade() -> OptionTrade:
    """Create sample option trade."""
    return OptionTrade(
        trade_id="12345",
        instrument_id="BTC-27DEC24-100000-C",
        timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
        price=0.0500,
        iv=0.65,
        amount=1.0,
        direction=TradeDirection.BUY,
        underlying="BTC",
        strike=100000.0,
        expiry=datetime(2024, 12, 27, 8, 0, 0, tzinfo=UTC),
        option_type=OptionType.CALL,
        index_price=45000.0,
        mark_price=0.0510,
    )


@pytest.fixture
def sample_trades() -> list[OptionTrade]:
    """Create list of sample trades across multiple days."""
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    trades = []
    for i in range(10):
        # Spread trades across 3 days
        day_offset = i // 4
        hour_offset = i % 24
        timestamp = base_time.replace(
            day=1 + day_offset,
            hour=hour_offset,
        )
        trades.append(
            OptionTrade(
                trade_id=f"trade_{i}",
                instrument_id="ETH-27DEC24-5000-P",
                timestamp=timestamp,
                price=0.1 + i * 0.01,
                iv=0.5 + i * 0.01,
                amount=1.0 + i * 0.1,
                direction=TradeDirection.SELL if i % 2 else TradeDirection.BUY,
                underlying="ETH",
                strike=5000.0,
                expiry=datetime(2024, 12, 27, 8, 0, 0, tzinfo=UTC),
                option_type=OptionType.PUT,
            )
        )
    return trades


@pytest.fixture
def sample_dvol_candles() -> list[DVOLCandle]:
    """Create sample DVOL candles."""
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    return [
        DVOLCandle(
            timestamp=base_time.replace(hour=i),
            open=50.0 + i,
            high=52.0 + i,
            low=48.0 + i,
            close=51.0 + i,
        )
        for i in range(24)
    ]
