"""Session timing and management for ICT observation and trading windows.

Strategy Logic:
  - Observation (MT5 07:00-15:30 UTC+3): Track session High and Low, mark range boundaries.
  - Trading (MT5 15:30-21:00 UTC+3): If price crosses a boundary and re-enters the range:
      * Crossed HIGH boundary and came back inside → SELL
      * Crossed LOW boundary and came back inside → BUY

Timezone:
  All session times are in the configured timezone (default: Etc/GMT-3 = UTC+3 = MT5 server time).
"""

from datetime import datetime, time as dt_time
from typing import Any

import pytz
from loguru import logger

from config.settings import TradingConfig


class SessionManager:
    """Manages trading sessions, observation windows, and range tracking."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.session_tz = pytz.timezone(config.timezone)  # Configured timezone (UTC+3)
        self.mt5_tz = pytz.timezone("Etc/GMT-3")  # UTC+3

        # Parse session times (all in configured timezone - MT5 server time UTC+3)
        self.obs_start = self._parse_time(config.observation_start)  # 07:00 UTC+3
        self.obs_end = self._parse_time(config.observation_end)      # 15:30 UTC+3
        self.trade_start = self._parse_time(config.trading_start)    # 15:30 UTC+3
        self.trade_end = self._parse_time(config.trading_end)        # 21:00 UTC+3

        # Session range (built during observation)
        self.session_high: float = 0.0
        self.session_low: float = float("inf")
        self.session_open: float = 0.0
        self.session_candle_count: int = 0
        self.session_started: bool = False
        self.session_date: str = ""
        self.range_locked: bool = False  # True once observation ends

        # Range breakout tracking (used during trading session)
        self.broke_high: bool = False  # Price went above session_high
        self.broke_low: bool = False   # Price went below session_low

        # Previous day data
        self.previous_day_high: float = 0.0
        self.previous_day_low: float = 0.0
        self.previous_day_close: float = 0.0

    def _parse_time(self, time_str: str) -> dt_time:
        """Parse time string HH:MM to time object."""
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))

    def get_ist_time(self, utc_time: datetime | None = None) -> datetime:
        """Get current time in configured session timezone (NY)."""
        if utc_time is None:
            utc_time = datetime.now(pytz.utc)
        elif utc_time.tzinfo is None:
            utc_time = pytz.utc.localize(utc_time)
        return utc_time.astimezone(self.session_tz)

    def get_mt5_time(self, utc_time: datetime | None = None) -> datetime:
        """Get current MT5 time (UTC+3)."""
        if utc_time is None:
            utc_time = datetime.now(pytz.utc)
        elif utc_time.tzinfo is None:
            utc_time = pytz.utc.localize(utc_time)
        return utc_time.astimezone(self.mt5_tz)

    def get_ny_time(self, utc_time: datetime | None = None) -> datetime:
        """Get current NY time (for reference/logging)."""
        ny_tz = pytz.timezone("America/New_York")
        if utc_time is None:
            utc_time = datetime.now(pytz.utc)
        elif utc_time.tzinfo is None:
            utc_time = pytz.utc.localize(utc_time)
        return utc_time.astimezone(ny_tz)

    def is_observation_session(self, utc_time: datetime | None = None) -> bool:
        """Check if current time is within observation session (07:00 to 15:30 inclusive)."""
        now = self.get_ist_time(utc_time)
        current_time = now.time()
        return self.obs_start <= current_time <= self.obs_end

    def is_trading_session(self, utc_time: datetime | None = None) -> bool:
        """Check if current time is within trading session (after 15:30 up to 21:00)."""
        now = self.get_ist_time(utc_time)
        current_time = now.time()
        return self.trade_start < current_time <= self.trade_end

    def is_session_end(self, utc_time: datetime | None = None) -> bool:
        """Check if trading session is ending (within 5 minutes of close)."""
        now = self.get_ist_time(utc_time)
        current_time = now.time()
        end_minutes = self.trade_end.hour * 60 + self.trade_end.minute
        current_minutes = current_time.hour * 60 + current_time.minute
        return 0 <= (end_minutes - current_minutes) <= 5

    def update_session_data(self, candle: dict[str, Any], utc_time: datetime | None = None) -> None:
        """Update session statistics with new candle data."""
        now = self.get_ist_time(utc_time)
        current_date = now.strftime("%Y-%m-%d")

        # Reset session on new day
        if current_date != self.session_date:
            self._reset_session(current_date)

        # Only update range during observation window
        if self.is_observation_session(utc_time):
            high = candle.get("high", 0.0)
            low = candle.get("low", float("inf"))

            if high > self.session_high:
                self.session_high = high
            if low < self.session_low:
                self.session_low = low
            if self.session_candle_count == 0:
                self.session_open = candle.get("open", 0.0)

            self.session_candle_count += 1
            self.session_started = True
            self.range_locked = False

        elif self.is_trading_session(utc_time):
            # Lock the range once we enter trading window
            if not self.range_locked and self.session_started:
                self.range_locked = True
                logger.info(
                    f"RANGE LOCKED | High: {self.session_high:.5f} | "
                    f"Low: {self.session_low:.5f} | "
                    f"Range: {self.session_range:.5f}"
                )

    def check_range_breakout_reentry(self, current_price: float) -> str | None:
        """
        Check if price broke a range boundary and re-entered.

        Returns:
            "SELL" - if price broke above session_high and came back inside
            "BUY"  - if price broke below session_low and came back inside
            None   - no signal
        """
        if not self.range_locked:
            return None
        if self.session_high == 0 or self.session_low == float("inf"):
            return None

        # Track if price broke above the high
        if current_price > self.session_high:
            self.broke_high = True

        # Track if price broke below the low
        if current_price < self.session_low:
            self.broke_low = True

        # Check re-entry from above → SELL signal
        if self.broke_high and current_price <= self.session_high:
            self.broke_high = False  # Reset after signal
            logger.info(
                f"RANGE RE-ENTRY FROM HIGH → SELL | Price: {current_price:.5f} | "
                f"Session High: {self.session_high:.5f}"
            )
            return "SELL"

        # Check re-entry from below → BUY signal
        if self.broke_low and current_price >= self.session_low:
            self.broke_low = False  # Reset after signal
            logger.info(
                f"RANGE RE-ENTRY FROM LOW → BUY | Price: {current_price:.5f} | "
                f"Session Low: {self.session_low:.5f}"
            )
            return "BUY"

        return None

    def _reset_session(self, new_date: str) -> None:
        """Reset session data for new trading day."""
        # Store previous day data before reset
        if self.session_high > 0:
            self.previous_day_high = self.session_high
            self.previous_day_low = self.session_low if self.session_low != float("inf") else 0.0

        self.session_high = 0.0
        self.session_low = float("inf")
        self.session_open = 0.0
        self.session_candle_count = 0
        self.session_date = new_date
        self.session_started = False
        self.range_locked = False
        self.broke_high = False
        self.broke_low = False
        logger.info(f"Session reset for {new_date} | PDH: {self.previous_day_high:.5f} | PDL: {self.previous_day_low:.5f}")

    def set_previous_day_data(self, high: float, low: float, close: float) -> None:
        """Manually set previous day high/low/close from historical data."""
        self.previous_day_high = high
        self.previous_day_low = low
        self.previous_day_close = close
        logger.info(f"Previous day data set | High: {high:.5f} | Low: {low:.5f} | Close: {close:.5f}")

    @property
    def session_midpoint(self) -> float:
        """Calculate session midpoint."""
        if self.session_high == 0 or self.session_low == float("inf"):
            return 0.0
        return (self.session_high + self.session_low) / 2

    @property
    def session_range(self) -> float:
        """Calculate session range."""
        if self.session_high == 0 or self.session_low == float("inf"):
            return 0.0
        return self.session_high - self.session_low

    @property
    def has_sufficient_data(self) -> bool:
        """Check if enough session data has been collected for trading."""
        return self.session_candle_count >= 10 and self.session_started

    def get_session_state(self) -> dict[str, Any]:
        """Get current session state as dictionary."""
        return {
            "session_high": self.session_high,
            "session_low": self.session_low if self.session_low != float("inf") else 0.0,
            "session_midpoint": self.session_midpoint,
            "session_range": self.session_range,
            "session_candle_count": self.session_candle_count,
            "range_locked": self.range_locked,
            "broke_high": self.broke_high,
            "broke_low": self.broke_low,
            "previous_day_high": self.previous_day_high,
            "previous_day_low": self.previous_day_low,
            "is_observation": self.is_observation_session(),
            "is_trading": self.is_trading_session(),
            "session_time": self.get_ist_time().strftime("%Y-%m-%d %H:%M:%S"),
            "mt5_time": self.get_mt5_time().strftime("%Y-%m-%d %H:%M:%S"),
            "ny_time": self.get_ny_time().strftime("%Y-%m-%d %H:%M:%S"),
        }
