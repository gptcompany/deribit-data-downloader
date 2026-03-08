"""Tests for fetcher module."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from deribit_data.config import DeribitConfig
from deribit_data.fetcher import DeribitFetcher


class TestDeribitFetcher:
    """Tests for DeribitFetcher."""

    @pytest.fixture
    def mock_config(self) -> DeribitConfig:
        """Create mock config for testing."""
        return DeribitConfig(
            http_timeout=5.0,
            max_retries=2,
            rate_limit_delay=0.0,  # No delay in tests
            batch_size=100,
            flush_every_pages=10,  # Minimum is 10
            max_pages=100,  # Minimum is 100
        )

    def test_parse_instrument_call(self, mock_config: DeribitConfig) -> None:
        """Test parsing call option instrument."""
        fetcher = DeribitFetcher(mock_config)

        result = fetcher._parse_instrument("BTC-27DEC24-100000-C")

        assert result is not None
        assert result["underlying"] == "BTC"
        assert result["strike"] == 100000.0
        assert result["option_type"].value == "call"
        assert result["expiry"].year == 2024
        assert result["expiry"].month == 12
        assert result["expiry"].day == 27

    def test_parse_instrument_put(self, mock_config: DeribitConfig) -> None:
        """Test parsing put option instrument."""
        fetcher = DeribitFetcher(mock_config)

        result = fetcher._parse_instrument("ETH-15MAR24-5000-P")

        assert result is not None
        assert result["underlying"] == "ETH"
        assert result["strike"] == 5000.0
        assert result["option_type"].value == "put"

    def test_parse_instrument_invalid(self, mock_config: DeribitConfig) -> None:
        """Test parsing invalid instrument."""
        fetcher = DeribitFetcher(mock_config)

        result = fetcher._parse_instrument("INVALID-INSTRUMENT")

        assert result is None

    def test_parse_trade(self, mock_config: DeribitConfig) -> None:
        """Test parsing trade data."""
        fetcher = DeribitFetcher(mock_config)

        trade_data = {
            "trade_id": "12345",
            "instrument_name": "BTC-27DEC24-100000-C",
            "timestamp": 1704067200000,  # 2024-01-01 00:00:00 timezone.utc
            "price": 0.05,
            "iv": 65.0,  # 65%
            "amount": 1.0,
            "direction": "buy",
            "index_price": 45000.0,
            "mark_price": 0.051,
        }

        trade, error = fetcher._parse_trade(trade_data)

        assert trade is not None
        assert error is None
        assert trade.trade_id == "12345"
        assert trade.instrument_id == "BTC-27DEC24-100000-C"
        assert trade.price == 0.05
        assert trade.iv == 0.65  # Converted to decimal
        assert trade.amount == 1.0
        assert trade.direction.value == "buy"

    def test_parse_trade_no_iv(self, mock_config: DeribitConfig) -> None:
        """Test parsing trade without IV (should still work)."""
        fetcher = DeribitFetcher(mock_config)

        trade_data = {
            "trade_id": "12345",
            "instrument_name": "BTC-27DEC24-100000-C",
            "timestamp": 1704067200000,
            "price": 0.05,
            "iv": None,  # No IV
            "amount": 1.0,
            "direction": "buy",
        }

        trade, error = fetcher._parse_trade(trade_data)

        assert trade is not None
        assert error is None
        assert trade.iv is None

    def test_parse_trade_invalid_instrument(self, mock_config: DeribitConfig) -> None:
        """Test parsing trade with invalid instrument returns error."""
        fetcher = DeribitFetcher(mock_config)

        trade_data = {
            "trade_id": "12345",
            "instrument_name": "INVALID-INSTRUMENT",
            "timestamp": 1704067200000,
            "price": 0.05,
            "amount": 1.0,
            "direction": "buy",
        }

        trade, error = fetcher._parse_trade(trade_data)

        assert trade is None
        assert error is not None
        assert "Invalid instrument format" in error

    def test_context_manager(self, mock_config: DeribitConfig) -> None:
        """Test context manager."""
        with DeribitFetcher(mock_config) as fetcher:
            assert fetcher is not None

    @patch("deribit_data.fetcher.httpx.Client")
    def test_fetch_trades_streaming(
        self, mock_client_class: MagicMock, mock_config: DeribitConfig
    ) -> None:
        """Test streaming fetch yields batches."""
        # Setup mock
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock response with trades
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "trades": [
                    {
                        "trade_id": f"trade_{i}",
                        "instrument_name": "BTC-27DEC24-100000-C",
                        "timestamp": 1704067200000 + i * 1000,
                        "price": 0.05,
                        "iv": 65.0,
                        "amount": 1.0,
                        "direction": "buy",
                    }
                    for i in range(10)
                ],
                "has_more": False,
            }
        }
        mock_client.get.return_value = mock_response

        with DeribitFetcher(mock_config) as fetcher:
            batches = list(
                fetcher.fetch_trades_streaming(
                    currency="BTC",
                    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
                )
            )

        assert len(batches) == 1
        assert len(batches[0]) == 10

    @patch("deribit_data.fetcher.httpx.Client")
    def test_fetch_dvol(self, mock_client_class: MagicMock, mock_config: DeribitConfig) -> None:
        """Test fetching DVOL data."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "data": [
                    [1704067200000, 50.0, 52.0, 48.0, 51.0],
                    [1704070800000, 51.0, 53.0, 49.0, 52.0],
                ]
            }
        }
        mock_client.get.return_value = mock_response

        with DeribitFetcher(mock_config) as fetcher:
            candles = fetcher.fetch_dvol(
                currency="BTC",
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
            )

        assert len(candles) == 2
        assert candles[0].open == 50.0
        assert candles[0].close == 51.0
