"""Google Sheets Logging System for market state and trade journal.

Replaces CSV logging with Google Sheets integration.
Uses gspread with service account credentials.

Setup:
    1. Create a Google Cloud project and enable Sheets API
    2. Create a service account and download the JSON key
    3. Save the key as config/service_account.json
    4. Share both Google Sheets with the service account email (Editor access)
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials
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

# Google Sheets URLs (extract spreadsheet IDs)
TRADE_JOURNAL_SHEET_ID = "1MIKec5np0pAVjRhPoMnwFOE8yJ-02cXjD8nbxKGk3-k"
MARKET_STATE_SHEET_ID = "1_RdWTNPBJ5g6o60OHVwGnKfCdYQq5F49dmO6_bRAoM8"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsLogger:
    """Handles Google Sheets logging for market state and trade journal."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self._client: gspread.Client | None = None
        self._trade_journal_sheet: gspread.Worksheet | None = None
        self._market_state_sheet: gspread.Worksheet | None = None
        self._last_market_state_log: datetime | None = None
        self._market_state_interval = 60  # Log every 60 seconds (1 minute)
        self._connect()

    def _connect(self) -> None:
        """Connect to Google Sheets using service account credentials."""
        creds_path = Path("config/service_account.json")
        if not creds_path.exists():
            logger.error(
                f"Service account credentials not found at {creds_path}. "
                "Google Sheets logging disabled."
            )
            return

        try:
            credentials = Credentials.from_service_account_file(
                str(creds_path), scopes=SCOPES
            )
            self._client = gspread.authorize(credentials)

            # Open trade journal sheet
            trade_journal_spreadsheet = self._client.open_by_key(TRADE_JOURNAL_SHEET_ID)
            self._trade_journal_sheet = trade_journal_spreadsheet.sheet1
            self._ensure_headers(self._trade_journal_sheet, TRADE_JOURNAL_COLUMNS)

            # Open market state sheet
            market_state_spreadsheet = self._client.open_by_key(MARKET_STATE_SHEET_ID)
            self._market_state_sheet = market_state_spreadsheet.sheet1
            self._ensure_headers(self._market_state_sheet, MARKET_STATE_COLUMNS)

            logger.info("Google Sheets connected successfully.")
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            self._client = None

    def _ensure_headers(self, sheet: gspread.Worksheet, columns: list[str]) -> None:
        """Ensure the first row has the correct headers."""
        try:
            existing = sheet.row_values(1)
            if existing != columns:
                sheet.update("A1", [columns])
                logger.info(f"Headers updated on sheet: {sheet.title}")
        except Exception:
            sheet.update("A1", [columns])

    def log_market_state(self, state: MarketState) -> None:
        """Append a market state row to the Google Sheet (throttled to 1 per minute)."""
        if self._market_state_sheet is None:
            return

        # Throttle: only log once per minute
        now = datetime.now()
        if self._last_market_state_log is not None:
            elapsed = (now - self._last_market_state_log).total_seconds()
            if elapsed < self._market_state_interval:
                return

        self._last_market_state_log = now

        data = state.to_dict()
        row = [str(data.get(col, "")) for col in MARKET_STATE_COLUMNS]

        try:
            self._market_state_sheet.append_row(row, value_input_option="RAW")
        except Exception as e:
            logger.error(f"Failed to log market state to Google Sheets: {e}")
            self._try_reconnect()

    def log_trade(self, trade: TradeRecord) -> None:
        """Append a trade record to the trade journal Google Sheet."""
        if self._trade_journal_sheet is None:
            return

        data = trade.to_dict()
        row = [str(data.get(col, "")) for col in TRADE_JOURNAL_COLUMNS]

        try:
            self._trade_journal_sheet.append_row(row, value_input_option="RAW")
            logger.info(f"Trade logged to Google Sheets: {trade.trade_id}")
        except Exception as e:
            logger.error(f"Failed to log trade to Google Sheets: {e}")
            self._try_reconnect()

    def reset_market_state(self) -> None:
        """Clear market state sheet data (keep headers) for new day."""
        if self._market_state_sheet is None:
            return

        try:
            row_count = self._market_state_sheet.row_count
            if row_count > 1:
                self._market_state_sheet.delete_rows(2, row_count)
                logger.info("Market state sheet cleared for new day.")
        except Exception as e:
            logger.error(f"Failed to reset market state sheet: {e}")

    def _try_reconnect(self) -> None:
        """Attempt to reconnect to Google Sheets on failure."""
        logger.warning("Attempting to reconnect to Google Sheets...")
        try:
            self._connect()
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
