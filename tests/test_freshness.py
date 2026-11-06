"""Tests for freshness metrics and DVOL resume point."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from click.testing import CliRunner

from deribit_data.cli import main
from deribit_data.freshness import dvol_resume_start, render_metrics, write_metrics
from deribit_data.models import DVOLCandle, OptionTrade
from deribit_data.storage import ParquetStorage

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)


def _candle(ts: datetime) -> DVOLCandle:
    return DVOLCandle(timestamp=ts, open=50.0, high=52.0, low=48.0, close=51.0)


def test_dvol_resume_start_empty_catalog_uses_fallback(tmp_catalog: Path) -> None:
    storage = ParquetStorage(tmp_catalog)
    fallback = datetime(2021, 3, 1, tzinfo=UTC)
    assert dvol_resume_start(storage, "BTC", fallback) == fallback


def test_dvol_resume_start_is_day_after_last_candle(tmp_catalog: Path) -> None:
    storage = ParquetStorage(tmp_catalog)
    storage.save_dvol([_candle(datetime(2026, 2, 5, 23, 0, tzinfo=UTC))], "BTC")
    got = dvol_resume_start(storage, "BTC", datetime(2021, 3, 1, tzinfo=UTC))
    assert got == datetime(2026, 2, 6, tzinfo=UTC)


def test_render_metrics_reports_last_timestamps(
    tmp_catalog: Path, sample_trades: list[OptionTrade]
) -> None:
    storage = ParquetStorage(tmp_catalog)
    storage.save_trades(sample_trades, "ETH")
    storage.save_dvol([_candle(datetime(2026, 2, 5, 23, 0, tzinfo=UTC))], "BTC")

    text = render_metrics(storage, ["BTC", "ETH"], NOW)

    last_eth = max(t.timestamp for t in sample_trades).timestamp()
    assert f'deribit_catalog_last_trade_timestamp_seconds{{currency="ETH"}} {last_eth:.0f}' in text
    assert 'deribit_catalog_last_dvol_timestamp_seconds{currency="BTC"} 1770332400' in text
    assert f"deribit_catalog_scan_timestamp_seconds {NOW.timestamp():.0f}" in text


def test_render_metrics_omits_series_without_data(tmp_catalog: Path) -> None:
    # Nessuna serie finta a 0: l'assenza deve far scattare absent() nell'allarme.
    text = render_metrics(ParquetStorage(tmp_catalog), ["BTC"], NOW)
    assert "last_trade_timestamp_seconds{" not in text
    assert "last_dvol_timestamp_seconds{" not in text
    assert "deribit_catalog_scan_timestamp_seconds" in text


def test_write_metrics_is_atomic_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "out" / "deribit_catalog.prom"
    write_metrics(target, "a 1\n")
    write_metrics(target, "a 2\n")
    assert target.read_text() == "a 2\n"
    assert [p.name for p in target.parent.iterdir()] == ["deribit_catalog.prom"]


def test_metrics_command_writes_file(tmp_catalog: Path, tmp_path: Path) -> None:
    ParquetStorage(tmp_catalog).save_dvol([_candle(NOW - timedelta(days=1))], "ETH")
    out = tmp_path / "deribit_catalog.prom"
    result = CliRunner().invoke(
        main, ["metrics", "--catalog", str(tmp_catalog), "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert 'deribit_catalog_last_dvol_timestamp_seconds{currency="ETH"}' in out.read_text()
