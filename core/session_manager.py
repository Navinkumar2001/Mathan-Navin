"""Session timing and management for ICT observation and trading windows."""

from datetime import datetime, time as dt_time
from typing import Any

import pytz
from loguru import logger

from config.settings import TradingConfig


class SessionManager:
    """Manages trading sessions, observation windows, and session statistics."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.ny_tz = pytz.timezone("America/New_York")
        self.ist_tz = pytz.timezone("Asia/Kolkata")

        # Parse session times
        self.obs_start = self._parse_time(config.observation_start_ny)
        self.obs_end = self._parse_time(config.observation_end_ny)
        self.trade_start = self._parse_time(config.trading_start_ny)
        self.trade_end = self._parse_time(config.trading_end_ny)

        # Session state
        self.session_high: float = 0.0
        self.session_low: float = float("inf")
        self.session_open: float = 0.0
        self.session_candle_count: int = 0
        self.session_started: bool = False
        self.session_date: str = ""

        # Previous day data
        self.previous_day_high: float = 0.0
        self.previous_day_low: float = 0.0
        self.previous_day_close: float = 0.0

    def _parse_time(self, time_str: str) -> dt_time:
        """Parse time string HH:MM to time object."""
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))

    def get_ny_time(self, utc_time: datetime | None = None) -> datetime:
        """Get current New York time."""
        if utc_time is None:
            utc_time = datetime.now(pytz.utc)
        elif utc_time.tzinfo is None:
            utc_time = pytz.utc.localize(utc_time)
        return utc_time.astimezone(self.ny_tz)

    def get_ist_time(self, utc_time: datetime | None = None) -> datetime:
        """Get current IST time."""
        if utc_time is None:
            utc_time = datetime.now(pytz.utc)
        elif utc_time.tzinfo is None:
            utc_time = pytz.utc.localize(utc_time)
        return utc_time.astimezone(self.ist_tz)

    def is_observation_session(self, utc_time: datetime | None = None) -> bool:
        """Check if current time is within observation session (NY 00:00-08:30)."""
        ny_now = self.get_ny_time(utc_time)
        current_time = ny_now.time()
        return self.obs_start <= current_time <= self.obs_end

    def is_trading_session(self, utc_time: datetime | None = None) -> bool:
        """Check if current time is within active trading session."""
        ny_now = self.get_ny_time(utc_time)
        current_time = ny_now.time()
        return self.trade_start <= current_time <= self.trade_end

    def is_session_end(self, utc_time: datetime | None = None) -> bool:
        """Check if trading session is ending (within 5 minutes of close)."""
        ny_now = self.get_ny_time(utc_time)
        current_time = ny_now.time()
        end_minutes = self.trade_end.hour * 60 + self.trade_end.minute
        current_minutes = current_time.hour * 60 + current_time.minute
        return 0 <= (end_minutes - current_minutes) <= 5

    def update_session_data(self, candle: dict[str, Any]) -> None:
        """Update session statistics with new candle data."""
        ny_now = self.get_ny_time()
        current_date = ny_now.strftime("%Y-%m-%d")

        # Reset session on new day
        if current_date != self.session_date:
            self._reset_session(current_date)

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

    def _reset_session(self, new_date: str) -> None:
        """Reset session data for new trading day."""
        # Store previous day data before reset
        if self.session_high > 0:
            self.previous_day_high = self.session_high
            self.previous_day_low = self.session_low

        self.session_high = 0.0
        self.session_low = float("inf")
        self.session_open = 0.0
        self.session_candle_count = 0
        self.session_date = new_date
        self.session_started = False
        logger.info(f"Session reset for {new_date} | PDH: {self.previous_day_high} | PDL: {self.previous_day_low}")

    def set_previous_day_data(self, high: float, low: float, close: float) -> None:
        """Manually set previous day high/low/close from historical data."""
        self.previous_day_high = high
        self.previous_day_low = low
        self.previous_day_close = close
        logger.info(f"Previous day data set | High: {high} | Low: {low} | Close: {close}")

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
            "previous_day_high": self.previous_day_high,
            "previous_day_low": self.previous_day_low,
            "is_observation": self.is_observation_session(),
            "is_trading": self.is_trading_session(),
            "ny_time": self.get_ny_time().strftime("%Y-%m-%d %H:%M:%S"),
            "ist_time": self.get_ist_time().strftime("%Y-%m-%d %H:%M:%S"),
        }
