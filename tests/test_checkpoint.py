"""Tests for checkpoint module."""

from datetime import datetime, timezone
from pathlib import Path

from deribit_data.checkpoint import CheckpointManager
from deribit_data.models import CheckpointState


class TestCheckpointManager:
    """Tests for CheckpointManager."""

    def test_init_creates_directory(self, tmp_path: Path) -> None:
        """Test initialization creates checkpoint directory."""
        checkpoint_dir = tmp_path / "checkpoints"
        assert not checkpoint_dir.exists()

        CheckpointManager(checkpoint_dir)

        assert checkpoint_dir.exists()

    def test_cleanup_stale_temps(self, tmp_path: Path) -> None:
        """Test stale temp files are cleaned up on init."""
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        # Create stale temp file
        stale_tmp = checkpoint_dir / "btc_checkpoint.tmp"
        stale_tmp.write_text("stale")

        CheckpointManager(checkpoint_dir)

        assert not stale_tmp.exists()

    def test_save_and_load(self, tmp_checkpoint_dir: Path) -> None:
        """Test saving and loading checkpoint."""
        mgr = CheckpointManager(tmp_checkpoint_dir)

        state = CheckpointState(
            currency="BTC",
            last_timestamp_ms=1704067200000,
            last_page=100,
            trades_fetched=1000000,
            started_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            last_flush_at=datetime(2024, 1, 1, 1, 0, 0, tzinfo=timezone.utc),
            files_written=["2024-01-01.parquet"],
        )

        mgr.save(state)

        loaded = mgr.load("BTC")
        assert loaded is not None
        assert loaded.currency == "BTC"
        assert loaded.last_timestamp_ms == 1704067200000
        assert loaded.last_page == 100
        assert loaded.trades_fetched == 1000000
        assert "2024-01-01.parquet" in loaded.files_written

    def test_load_nonexistent(self, tmp_checkpoint_dir: Path) -> None:
        """Test loading nonexistent checkpoint returns None."""
        mgr = CheckpointManager(tmp_checkpoint_dir)

        loaded = mgr.load("ETH")
        assert loaded is None

    def test_exists(self, tmp_checkpoint_dir: Path) -> None:
        """Test exists check."""
        mgr = CheckpointManager(tmp_checkpoint_dir)

        assert not mgr.exists("BTC")

        state = mgr.create_initial("BTC")
        mgr.save(state)

        assert mgr.exists("BTC")

    def test_delete(self, tmp_checkpoint_dir: Path) -> None:
        """Test deleting checkpoint."""
        mgr = CheckpointManager(tmp_checkpoint_dir)

        state = mgr.create_initial("ETH")
        mgr.save(state)
        assert mgr.exists("ETH")

        result = mgr.delete("ETH")
        assert result is True
        assert not mgr.exists("ETH")

    def test_delete_nonexistent(self, tmp_checkpoint_dir: Path) -> None:
        """Test deleting nonexistent checkpoint."""
        mgr = CheckpointManager(tmp_checkpoint_dir)

        result = mgr.delete("SOL")
        assert result is False

    def test_create_initial(self, tmp_checkpoint_dir: Path) -> None:
        """Test creating initial checkpoint."""
        mgr = CheckpointManager(tmp_checkpoint_dir)

        state = mgr.create_initial("BTC")

        assert state.currency == "BTC"
        assert state.last_timestamp_ms == 0
        assert state.last_page == 0
        assert state.trades_fetched == 0
        assert state.files_written == []

    def test_atomic_write(self, tmp_checkpoint_dir: Path) -> None:
        """Test writes are atomic (tmp + rename)."""
        mgr = CheckpointManager(tmp_checkpoint_dir)

        state = mgr.create_initial("BTC")
        mgr.save(state)

        # No tmp files should remain
        tmp_files = list(tmp_checkpoint_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

        # Checkpoint file should exist
        checkpoint_files = list(tmp_checkpoint_dir.glob("*_checkpoint.json"))
        assert len(checkpoint_files) == 1


class TestCheckpointState:
    """Tests for CheckpointState model."""

    def test_update_progress(self) -> None:
        """Test updating progress."""
        state = CheckpointState(
            currency="ETH",
            last_timestamp_ms=1000,
            last_page=10,
            trades_fetched=100,
            started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        updated = state.update_progress(
            timestamp_ms=2000,
            page=20,
            trades_count=50,
            file_written="2024-01-01.parquet",
        )

        assert updated.last_timestamp_ms == 2000
        assert updated.last_page == 20
        assert updated.trades_fetched == 150  # 100 + 50
        assert "2024-01-01.parquet" in updated.files_written
        assert updated.last_flush_at is not None

    def test_update_progress_no_duplicate_files(self) -> None:
        """Test updating progress doesn't duplicate file names."""
        state = CheckpointState(
            currency="ETH",
            started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            files_written=["file1.parquet"],
        )

        updated = state.update_progress(
            timestamp_ms=1000,
            page=1,
            trades_count=10,
            file_written="file1.parquet",  # Same file
        )

        assert updated.files_written == ["file1.parquet"]
