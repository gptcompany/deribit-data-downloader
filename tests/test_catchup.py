"""Tests for the `catchup` command with a fake fetcher (no network)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from deribit_data import cli
from deribit_data.cli import main
from deribit_data.models import DVOLCandle, OptionTrade, OptionType, TradeDirection
from deribit_data.storage import ParquetStorage

LAST_TRADE = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
LAST_CANDLE = datetime(2026, 2, 5, 6, 0, 0, tzinfo=UTC)


def _trade(currency: str, trade_id: str, ts: datetime) -> OptionTrade:
    return OptionTrade(
        trade_id=trade_id,
        instrument_id=f"{currency}-27DEC26-100000-C",
        timestamp=ts,
        price=0.05,
        iv=0.65,
        amount=1.0,
        direction=TradeDirection.BUY,
        underlying=currency,
        strike=100000.0,
        expiry=datetime(2026, 12, 27, 8, 0, 0, tzinfo=UTC),
        option_type=OptionType.CALL,
    )


def _candle(ts: datetime) -> DVOLCandle:
    return DVOLCandle(timestamp=ts, open=50.0, high=52.0, low=48.0, close=51.0)


class FakeFetcher:
    """Serves a fixed upstream and records what catchup asked for."""

    upstream_trades: dict[str, list[OptionTrade]] = {}
    upstream_candles: dict[str, list[DVOLCandle]] = {}
    fail_trades_for: set[str] = set()
    crash_after_first_batch: set[str] = set()
    trade_starts: dict[str, datetime] = {}
    dvol_starts: dict[str, datetime] = {}

    def __init__(self, config: Any) -> None:
        pass

    def __enter__(self) -> "FakeFetcher":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def fetch_trades_streaming(
        self, currency: str, start_date: datetime, end_date: datetime, **kwargs: Any
    ) -> Iterator[list[OptionTrade]]:
        type(self).trade_starts[currency] = start_date
        if currency in self.fail_trades_for:
            raise RuntimeError("upstream 500")
        pending = [t for t in self.upstream_trades.get(currency, []) if t.timestamp >= start_date]
        for batch in ([t] for t in pending):  # one trade per batch, like a flush
            yield batch
            if currency in self.crash_after_first_batch:
                raise RuntimeError("crash after first batch")

    def fetch_dvol(
        self, currency: str, start_date: datetime, end_date: datetime
    ) -> list[DVOLCandle]:
        type(self).dvol_starts[currency] = start_date
        return [c for c in self.upstream_candles.get(currency, []) if c.timestamp >= start_date]


@pytest.fixture
def seeded(tmp_catalog: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[], ParquetStorage]:
    """Catalog with a stored tail, a fake upstream with newer data, no network."""
    storage = ParquetStorage(tmp_catalog)
    for cur in ("BTC", "ETH"):
        storage.save_trades([_trade(cur, f"{cur}-old", LAST_TRADE)], cur)
        storage.save_dvol([_candle(LAST_CANDLE)], cur)

    FakeFetcher.upstream_trades = {
        cur: [_trade(cur, f"{cur}-{i}", LAST_TRADE + timedelta(days=i)) for i in (1, 2)]
        for cur in ("BTC", "ETH")
    }
    FakeFetcher.upstream_candles = {
        cur: [_candle(LAST_CANDLE + timedelta(hours=h)) for h in (0, 17, 18)]
        for cur in ("BTC", "ETH")
    }
    FakeFetcher.fail_trades_for = set()
    FakeFetcher.crash_after_first_batch = set()
    FakeFetcher.trade_starts = {}
    FakeFetcher.dvol_starts = {}
    monkeypatch.setattr(cli, "DeribitFetcher", FakeFetcher)
    return lambda: ParquetStorage(tmp_catalog)


def _run(catalog: Path) -> Any:
    return CliRunner().invoke(main, ["catchup", "--catalog", str(catalog)])


def _trade_ids(storage: ParquetStorage, currency: str) -> list[str]:
    return sorted(storage.load_trades(currency).column("trade_id").to_pylist())


def test_catchup_resumes_trades_after_last_stored_trade(
    tmp_catalog: Path, seeded: Callable[[], ParquetStorage]
) -> None:
    result = _run(tmp_catalog)
    assert result.exit_code == 0, result.output
    for cur in ("BTC", "ETH"):
        assert FakeFetcher.trade_starts[cur] == LAST_TRADE + timedelta(seconds=1)
        assert _trade_ids(seeded(), cur) == sorted([f"{cur}-old", f"{cur}-1", f"{cur}-2"])


def test_catchup_resumes_dvol_from_midnight_of_last_candle_day(
    tmp_catalog: Path, seeded: Callable[[], ParquetStorage]
) -> None:
    result = _run(tmp_catalog)
    assert result.exit_code == 0, result.output
    for cur in ("BTC", "ETH"):
        assert FakeFetcher.dvol_starts[cur] == datetime(2026, 2, 5, tzinfo=UTC)
        stored = seeded().load_dvol(cur).column("timestamp").to_pylist()
        assert LAST_CANDLE + timedelta(hours=17) in stored


def test_catchup_exits_1_on_failed_step_but_runs_the_others(
    tmp_catalog: Path, seeded: Callable[[], ParquetStorage]
) -> None:
    FakeFetcher.fail_trades_for = {"BTC"}
    result = _run(tmp_catalog)
    assert result.exit_code == 1
    # BTC dvol and both ETH steps still ran and wrote.
    assert "BTC" in FakeFetcher.dvol_starts
    assert _trade_ids(seeded(), "ETH") == sorted(["ETH-old", "ETH-1", "ETH-2"])
    assert _trade_ids(seeded(), "BTC") == ["BTC-old"]


def test_catchup_after_crash_resumes_from_what_was_saved(
    tmp_catalog: Path, seeded: Callable[[], ParquetStorage]
) -> None:
    FakeFetcher.crash_after_first_batch = {"BTC"}
    first = _run(tmp_catalog)
    assert first.exit_code == 1
    assert _trade_ids(seeded(), "BTC") == sorted(["BTC-old", "BTC-1"])

    FakeFetcher.crash_after_first_batch = set()
    second = _run(tmp_catalog)
    assert second.exit_code == 0, second.output
    # Restart point is the trade saved before the crash, not the original tail.
    assert FakeFetcher.trade_starts["BTC"] == LAST_TRADE + timedelta(days=1, seconds=1)
    assert _trade_ids(seeded(), "BTC") == sorted(["BTC-old", "BTC-1", "BTC-2"])


def test_catchup_twice_does_not_duplicate_rows(
    tmp_catalog: Path, seeded: Callable[[], ParquetStorage]
) -> None:
    assert _run(tmp_catalog).exit_code == 0
    before = {cur: _trade_ids(seeded(), cur) for cur in ("BTC", "ETH")}
    dvol_before = {cur: seeded().load_dvol(cur).num_rows for cur in ("BTC", "ETH")}

    assert _run(tmp_catalog).exit_code == 0
    for cur in ("BTC", "ETH"):
        ids = _trade_ids(seeded(), cur)
        assert ids == before[cur]
        assert len(ids) == len(set(ids))
        assert seeded().load_dvol(cur).num_rows == dvol_before[cur]
