"""Checkpoint management for crash recovery.

Provides atomic save/load operations for download state.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from deribit_data.models import CheckpointState

logger = logging.getLogger(__name__)


def _parse_isoformat(dt_str: str) -> datetime:
    """Parse ISO format string with 'Z' suffix support for Python < 3.11."""
    if dt_str.endswith("Z"):
        dt_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(dt_str)


class CheckpointManager:
    """Manages checkpoint files for crash recovery.

    Uses atomic writes (tmp + rename) to prevent corruption on crash.
    """

    def __init__(self, checkpoint_dir: Path) -> None:
        """Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory for checkpoint files.
        """
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Clean up stale temp files on init
        self._cleanup_stale_temps()

    def _cleanup_stale_temps(self) -> None:
        """Remove any stale .tmp files from previous crashes."""
        for tmp_file in self.checkpoint_dir.glob("*.tmp"):
            logger.info(f"Cleaning up stale temp file: {tmp_file}")
            tmp_file.unlink()

    def _get_checkpoint_path(self, currency: str) -> Path:
        """Get checkpoint file path for a currency."""
        return self.checkpoint_dir / f"{currency.lower()}_checkpoint.json"

    def save(self, state: CheckpointState) -> None:
        """Atomically save checkpoint state.

        Uses tmp file + rename pattern for crash safety.

        Args:
            state: Checkpoint state to save.
        """
        file_path = self._get_checkpoint_path(state.currency)
        tmp_path = file_path.with_suffix(".tmp")

        # Serialize state
        data = state.model_dump(mode="json")

        # Convert datetime to ISO format
        if isinstance(data.get("started_at"), datetime):
            data["started_at"] = data["started_at"].isoformat()
        if isinstance(data.get("last_flush_at"), datetime):
            data["last_flush_at"] = data["last_flush_at"].isoformat()

        # Write to temp file
        tmp_path.write_text(json.dumps(data, indent=2))

        # Atomic rename (POSIX guarantees atomicity)
        tmp_path.rename(file_path)

        logger.debug(f"Saved checkpoint for {state.currency}: page={state.last_page}")

    def load(self, currency: str) -> CheckpointState | None:
        """Load checkpoint state if it exists.

        Args:
            currency: Currency to load checkpoint for.

        Returns:
            CheckpointState if found, None otherwise.
        """
        file_path = self._get_checkpoint_path(currency)

        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text())

            # Parse datetime strings
            if isinstance(data.get("started_at"), str):
                data["started_at"] = _parse_isoformat(data["started_at"])
            if isinstance(data.get("last_flush_at"), str):
                data["last_flush_at"] = _parse_isoformat(data["last_flush_at"])

            state = CheckpointState(**data)
            logger.info(
                f"Loaded checkpoint for {currency}: "
                f"page={state.last_page}, trades={state.trades_fetched}"
            )
            return state

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Invalid checkpoint file for {currency}: {e}")
            return None

    def delete(self, currency: str) -> bool:
        """Delete checkpoint file after successful completion.

        Args:
            currency: Currency checkpoint to delete.

        Returns:
            True if deleted, False if not found.
        """
        file_path = self._get_checkpoint_path(currency)

        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted checkpoint for {currency}")
            return True

        return False

    def exists(self, currency: str) -> bool:
        """Check if a checkpoint exists for a currency.

        Args:
            currency: Currency to check.

        Returns:
            True if checkpoint exists.
        """
        return self._get_checkpoint_path(currency).exists()

    def create_initial(self, currency: str) -> CheckpointState:
        """Create initial checkpoint state for a new download.

        Args:
            currency: Currency to start downloading.

        Returns:
            New CheckpointState.
        """
        return CheckpointState(
            currency=currency,
            last_timestamp_ms=0,
            last_page=0,
            trades_fetched=0,
            started_at=datetime.now(timezone.utc),
            last_flush_at=None,
            files_written=[],
        )
