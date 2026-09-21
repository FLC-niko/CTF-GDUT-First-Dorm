"""State persistence and recovery for competition state and challenge queues.

Atomic writes prevent corruption on abrupt termination, and sensitive fields
(credentials, raw authorization tokens) are excluded or redacted.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _sanitize_for_persistence(obj: Any) -> Any:
    if is_dataclass(obj):
        return _sanitize_for_persistence(asdict(obj))
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            key_str = str(k).lower()
            if any(s in key_str for s in ("password", "secret", "api_key", "cookie")) or (
                "token" in key_str and not key_str.endswith("tokens")
            ):
                sanitized[k] = "<redacted>"
            else:
                sanitized[k] = _sanitize_for_persistence(v)
        return sanitized
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_persistence(item) for item in obj]
    return obj


class StatePersistence:
    """Manages atomic saving and loading of competition state to disk."""

    def __init__(self, state_file: str | Path) -> None:
        self.state_file = Path(state_file).resolve()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def save(self, state_data: dict[str, Any]) -> None:
        """Atomically write state data to disk."""
        sanitized = _sanitize_for_persistence(state_data)
        serialized = json.dumps(sanitized, indent=2, ensure_ascii=False)
        dir_name = self.state_file.parent
        temp_file = tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8")
        try:
            temp_file.write(serialized)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_file.close()
            Path(temp_file.name).replace(self.state_file)
            logger.debug("State saved to %s", self.state_file)
        except BaseException as exc:
            temp_path = Path(temp_file.name)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            logger.error("Failed to save state: %s", exc)
            raise

    def load(self) -> dict[str, Any] | None:
        """Load state data from disk if it exists, otherwise return None."""
        if not self.state_file.is_file():
            return None
        try:
            raw = self.state_file.read_text(encoding="utf-8")
            if not raw.strip():
                return None
            data = json.loads(raw)
            if not isinstance(data, dict):
                logger.warning("Invalid state file content in %s (not a dict)", self.state_file)
                return None
            return data
        except Exception as exc:
            logger.warning("Could not load state from %s: %s", self.state_file, exc)
            return None

    def exists(self) -> bool:
        return self.state_file.is_file()
