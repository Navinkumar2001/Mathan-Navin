"""Capture all console output (print + loguru) to log files in console_logs/.

This module redirects stdout/stderr so that everything printed to the console
is also written to timestamped log files in the console_logs/ directory.
"""

import sys
import io
from datetime import datetime
from pathlib import Path

from loguru import logger


class TeeWriter:
    """Writes to both the original stream and a log file."""

    def __init__(self, original_stream, log_file: Path) -> None:
        self.original = original_stream
        self.log_file = log_file
        self._file_handle = open(log_file, "a", encoding="utf-8")

    def write(self, message: str) -> int:
        self.original.write(message)
        if message.strip():
            self._file_handle.write(message)
            self._file_handle.flush()
        return len(message)

    def flush(self) -> None:
        self.original.flush()
        self._file_handle.flush()

    def close(self) -> None:
        self._file_handle.close()


def setup_console_logging(prefix: str = "console") -> Path:
    """
    Set up console output capture to console_logs/ directory.

    All print() statements and loguru output will be mirrored to a log file.

    Args:
        prefix: Filename prefix (e.g., "live", "backtest")

    Returns:
        Path to the created log file.
    """
    log_dir = Path("console_logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"{prefix}_{timestamp}.log"

    # Tee stdout and stderr to log file
    sys.stdout = TeeWriter(sys.__stdout__, log_file)
    sys.stderr = TeeWriter(sys.__stderr__, log_file)

    # Also add loguru sink to console_logs
    logger.add(
        str(log_dir / f"{prefix}_{{time:YYYY-MM-DD}}.log"),
        rotation="10 MB",
        retention="30 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
    )

    return log_file
