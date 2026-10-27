"""SHA256 manifest management for data integrity verification."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


class ManifestEntry:
    """Single file entry in manifest."""

    def __init__(
        self,
        sha256: str,
        size_bytes: int,
        row_count: int,
        timestamp_range: tuple[str, str] | None = None,
    ) -> None:
        self.sha256 = sha256
        self.size_bytes = size_bytes
        self.row_count = row_count
        self.timestamp_range = timestamp_range

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "row_count": self.row_count,
            "timestamp_range": list(self.timestamp_range) if self.timestamp_range else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ManifestEntry:
        """Create from dictionary."""
        return cls(
            sha256=data["sha256"],
            size_bytes=data["size_bytes"],
            row_count=data["row_count"],
            timestamp_range=tuple(data["timestamp_range"]) if data.get("timestamp_range") else None,
        )


class ManifestManager:
    """Manages SHA256 manifest for data integrity verification.

    Manifest format:
    {
        "generated_at": "2026-02-05T12:00:00Z",
        "catalog_path": "/path/to/catalog",
        "files": {
            "BTC/trades/2024-01-01.parquet": {
                "sha256": "abc123...",
                "size_bytes": 1234567,
                "row_count": 15000,
                "timestamp_range": ["2024-01-01T00:00:00Z", "2024-01-01T23:59:59Z"]
            }
        }
    }
    """

    def __init__(self, catalog_path: Path) -> None:
        """Initialize manifest manager.

        Args:
            catalog_path: Root path for catalog.
        """
        self.catalog_path = catalog_path
        self.manifest_path = catalog_path / "manifest.json"
        self._manifest: dict[str, ManifestEntry] = {}
        self._load()

    def _load(self) -> None:
        """Load manifest from file if it exists."""
        if not self.manifest_path.exists():
            return

        try:
            data = json.loads(self.manifest_path.read_text())
            for rel_path, entry_data in data.get("files", {}).items():
                self._manifest[rel_path] = ManifestEntry.from_dict(entry_data)
            logger.debug(f"Loaded manifest with {len(self._manifest)} files")
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load manifest: {e}")

    def save(self) -> None:
        """Atomically save manifest to file."""
        tmp_path = self.manifest_path.with_suffix(".json.tmp")

        data = {
            "generated_at": datetime.now(UTC).isoformat(),
            "catalog_path": str(self.catalog_path.absolute()),
            "files": {path: entry.to_dict() for path, entry in sorted(self._manifest.items())},
        }

        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.rename(self.manifest_path)

        logger.debug(f"Saved manifest with {len(self._manifest)} files")

    def _compute_sha256(self, file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _get_timestamp_range(self, file_path: Path) -> tuple[str, str] | None:
        """Get timestamp range from Parquet file."""
        try:
            table = pq.read_table(file_path, columns=["timestamp"])
            if table.num_rows == 0:
                return None
            timestamps = table.column("timestamp").to_pylist()
            min_ts = min(timestamps).isoformat() if timestamps else None
            max_ts = max(timestamps).isoformat() if timestamps else None
            if min_ts and max_ts:
                return (min_ts, max_ts)
            return None
        except Exception:
            return None

    def update_file(self, file_path: Path) -> ManifestEntry:
        """Update manifest entry for a file.

        Computes SHA256 and extracts metadata.

        Args:
            file_path: Path to Parquet file.

        Returns:
            ManifestEntry for the file.
        """
        rel_path = str(file_path.relative_to(self.catalog_path))

        sha256 = self._compute_sha256(file_path)
        size_bytes = file_path.stat().st_size

        try:
            metadata = pq.read_metadata(file_path)
            row_count = metadata.num_rows
        except Exception:
            row_count = 0

        timestamp_range = self._get_timestamp_range(file_path)

        entry = ManifestEntry(
            sha256=sha256,
            size_bytes=size_bytes,
            row_count=row_count,
            timestamp_range=timestamp_range,
        )

        self._manifest[rel_path] = entry
        logger.debug(f"Updated manifest for {rel_path}: {sha256[:16]}...")

        return entry

    def verify_file(self, file_path: Path) -> bool:
        """Verify a file against manifest.

        Args:
            file_path: Path to Parquet file.

        Returns:
            True if file matches manifest, False otherwise.
        """
        rel_path = str(file_path.relative_to(self.catalog_path))

        if rel_path not in self._manifest:
            logger.warning(f"File not in manifest: {rel_path}")
            return False

        entry = self._manifest[rel_path]

        # Verify SHA256
        actual_sha256 = self._compute_sha256(file_path)
        if actual_sha256 != entry.sha256:
            logger.error(
                f"SHA256 mismatch for {rel_path}: expected {entry.sha256}, got {actual_sha256}"
            )
            return False

        # Verify size
        actual_size = file_path.stat().st_size
        if actual_size != entry.size_bytes:
            logger.error(
                f"Size mismatch for {rel_path}: expected {entry.size_bytes}, got {actual_size}"
            )
            return False

        return True

    def verify_all(self) -> tuple[int, int, list[str]]:
        """Verify all files in manifest.

        Returns:
            Tuple of (passed_count, failed_count, failed_files).
        """
        passed = 0
        failed = 0
        failed_files: list[str] = []

        for rel_path in self._manifest:
            file_path = self.catalog_path / rel_path

            if not file_path.exists():
                logger.error(f"Missing file: {rel_path}")
                failed += 1
                failed_files.append(rel_path)
                continue

            if self.verify_file(file_path):
                passed += 1
            else:
                failed += 1
                failed_files.append(rel_path)

        logger.info(f"Verification complete: {passed} passed, {failed} failed")
        return passed, failed, failed_files

    def get_entry(self, rel_path: str) -> ManifestEntry | None:
        """Get manifest entry for a file.

        Args:
            rel_path: Relative path from catalog root.

        Returns:
            ManifestEntry or None if not found.
        """
        return self._manifest.get(rel_path)

    def remove_file(self, file_path: Path) -> bool:
        """Remove file from manifest.

        Args:
            file_path: Path to file to remove.

        Returns:
            True if removed, False if not found.
        """
        rel_path = str(file_path.relative_to(self.catalog_path))
        if rel_path in self._manifest:
            del self._manifest[rel_path]
            return True
        return False

    @property
    def file_count(self) -> int:
        """Get number of files in manifest."""
        return len(self._manifest)

    @property
    def total_size(self) -> int:
        """Get total size of all files in manifest."""
        return sum(e.size_bytes for e in self._manifest.values())

    @property
    def total_rows(self) -> int:
        """Get total row count of all files in manifest."""
        return sum(e.row_count for e in self._manifest.values())
