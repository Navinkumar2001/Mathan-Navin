"""CSV Logging System for market state and trade journal."""

import csv
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import TradingConfig
from core.data_models import MarketState, TradeRecord


MARKET_STATE_COLUMNS = [
    "timestamp", "ny_time", "ist_time", "symbol", "open", "high", "low", "close",
    "bid", "ask", "spread", "session_high", "session_low", "session_midpoint",
    "daily_bias", "liquidity_type", "liquidity_price", "sweep_detected", "sweep_type",
    "mss_detected", "mss_direction", "fvg_detected", "fvg_top", "fvg_bottom",
    "ob_detected", "ob_type", "entry_signal", "current_trade_status",
]

TRADE_JOURNAL_COLUMNS = [
    "trade_id", "ticket", "symbol", "entry_time", "exit_time", "entry_price",
    "exit_price", "trade_type", "lot_size", "stop_loss", "take_profit",
    "risk_reward", "profit_loss", "profit_loss_percent", "daily_bias",
    "liquidity_type", "sweep_type", "mss_direction", "fvg_direction", "ob_type",
    "trade_result", "exit_reason",
]


class CSVLogger:
    """Handles CSV file creation and logging for market state and trade journal."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.market_state_path = Path(config.csv_market_state_path)
        self.trade_journal_path = Path(config.csv_trade_journal_path)
        self._initialize_files()

    def _initialize_files(self) -> None:
        """Create CSV files with headers if they don't exist."""
        self.market_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.trade_journal_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.market_state_path.exists():
            self._write_header(self.market_state_path, MARKET_STATE_COLUMNS)
            logger.info(f"Created market state CSV: {self.market_state_path}")

        if not self.trade_journal_path.exists():
            self._write_header(self.trade_journal_path, TRADE_JOURNAL_COLUMNS)
            logger.info(f"Created trade journal CSV: {self.trade_journal_path}")

    def _write_header(self, path: Path, columns: list[str]) -> None:
        """Write CSV header row."""
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)

    def log_market_state(self, state: MarketState) -> None:
        """Append a market state row to the CSV."""
        data = state.to_dict()
        row = [data.get(col, "") for col in MARKET_STATE_COLUMNS]

        with open(self.market_state_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def log_trade(self, trade: TradeRecord) -> None:
        """Append a trade record to the trade journal CSV."""
        data = trade.to_dict()
        row = [data.get(col, "") for col in TRADE_JOURNAL_COLUMNS]

        with open(self.trade_journal_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)

        logger.info(f"Trade logged to journal: {trade.trade_id}")

    def reset_market_state(self) -> None:
        """Reset market state CSV (new day)."""
        self._write_header(self.market_state_path, MARKET_STATE_COLUMNS)
