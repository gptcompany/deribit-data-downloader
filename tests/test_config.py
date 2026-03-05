"""Tests for configuration module."""
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from deribit_data.config import DeribitConfig, ValidationConfig


class TestValidationConfig:
    """Tests for ValidationConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = ValidationConfig()
        assert config.iv_min == 0.01
        assert config.iv_max == 5.0
        assert config.gap_critical_days == 7
        assert config.duplicate_threshold == 5.0

    def test_custom_values(self) -> None:
        """Test custom values."""
        config = ValidationConfig(
            iv_min=0.05,
            iv_max=3.0,
            gap_critical_days=14,
        )
        assert config.iv_min == 0.05
        assert config.iv_max == 3.0
        assert config.gap_critical_days == 14


class TestDeribitConfig:
    """Tests for DeribitConfig."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = DeribitConfig()
        assert config.base_url == "https://history.deribit.com/api/v2/public"
        assert config.http_timeout == 30.0
        assert config.max_retries == 5
        assert config.batch_size == 10000
        assert config.compression == "zstd"
        assert config.currencies == ["BTC", "ETH"]
        assert config.historical_start_date == date(2016, 1, 1)

    def test_frozen(self) -> None:
        """Test config is immutable."""
        config = DeribitConfig()
        with pytest.raises(ValidationError):  # Pydantic raises ValidationError
            config.http_timeout = 60.0  # type: ignore

    def test_validation_nested(self) -> None:
        """Test nested validation config."""
        config = DeribitConfig()
        assert isinstance(config.validation, ValidationConfig)
        assert config.validation.iv_min == 0.01

    def test_from_env(self, monkeypatch) -> None:
        """Test loading from environment variables."""
        monkeypatch.setenv("DERIBIT_HTTP_TIMEOUT", "60.0")
        monkeypatch.setenv("DERIBIT_MAX_RETRIES", "5")
        monkeypatch.setenv("DERIBIT_COMPRESSION", "snappy")
        monkeypatch.setenv("DERIBIT_CURRENCIES", "BTC,ETH,SOL")
        monkeypatch.setenv("DERIBIT_CATALOG_PATH", "/tmp/test_catalog")

        config = DeribitConfig.from_env()

        assert config.http_timeout == 60.0
        assert config.max_retries == 5
        assert config.compression == "snappy"
        assert config.currencies == ["BTC", "ETH", "SOL"]
        assert config.catalog_path == Path("/tmp/test_catalog")

    def test_from_env_partial(self, monkeypatch) -> None:
        """Test partial env var loading (uses defaults for missing)."""
        monkeypatch.setenv("DERIBIT_HTTP_TIMEOUT", "45.0")

        config = DeribitConfig.from_env()

        assert config.http_timeout == 45.0
        assert config.max_retries == 5  # default

    def test_from_file_json(self, tmp_path: Path) -> None:
        """Test loading from JSON file."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            """{
            "http_timeout": 45.0,
            "max_retries": 5,
            "compression": "gzip"
        }"""
        )

        config = DeribitConfig.from_file(config_file)

        assert config.http_timeout == 45.0
        assert config.max_retries == 5
        assert config.compression == "gzip"

    def test_model_copy(self) -> None:
        """Test creating modified copy."""
        config = DeribitConfig()
        modified = config.model_copy(update={"http_timeout": 60.0})

        assert config.http_timeout == 30.0  # original unchanged
        assert modified.http_timeout == 60.0
