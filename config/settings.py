"""Configuration loader and settings management."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TradingConfig:
    """Main configuration for the ICT Trading Bot."""

    # Symbol and timeframe
    symbol: str = "EURUSD"
    timeframe: str = "M5"

    # Risk management
    risk_percent: float = 1.0
    reward_ratio: float = 3.0
    max_daily_risk: float = 3.0
    max_daily_losses: int = 3
    max_open_trades: int = 1
    spread_limit: float = 3.0

    # MT5 credentials
    mt5_login: int = 0
    mt5_server: str = ""
    mt5_password: str = ""

    # Timezone and sessions (IST GMT+5:30)
    # Observation: IST 09:00-18:30 (NY 00:00-08:30, MT5/UTC+3 07:00-15:30)
    # Trading:     IST 18:30-23:30 (NY 08:30-14:00, MT5/UTC+3 15:30-21:00)
    timezone: str = "Asia/Kolkata"
    observation_start: str = "09:00"
    observation_end: str = "18:30"
    trading_start: str = "18:30"
    trading_end: str = "23:30"

    # ICT parameters
    min_displacement_pips: float = 10.0
    min_fvg_size_pips: float = 2.0
    swing_lookback: int = 10
    equal_level_tolerance_pips: float = 3.0

    # Trade management
    partial_tp1_percent: int = 50
    partial_tp2_percent: int = 30
    partial_tp3_percent: int = 20
    breakeven_at_rr: float = 1.0
    session_close_exit: bool = True

    # Dashboard
    enable_dashboard: bool = True
    dashboard_port: int = 8050

    # File paths
    csv_market_state_path: str = "data/current_market_state.csv"
    csv_trade_journal_path: str = "data/trade_journal.csv"

    # Logging
    log_level: str = "INFO"

    @classmethod
    def from_json(cls, config_path: str | Path) -> "TradingConfig":
        """Load configuration from JSON file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            data: dict[str, Any] = json.load(f)

        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_json(self, config_path: str | Path) -> None:
        """Save configuration to JSON file."""
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        from dataclasses import asdict
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=4)

    @property
    def pip_value(self) -> float:
        """Get pip value based on symbol."""
        if "JPY" in self.symbol:
            return 0.01
        return 0.0001
