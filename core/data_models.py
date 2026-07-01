"""Data models for ICT trading concepts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Direction(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class LiquidityType(Enum):
    BUY_SIDE = "BUY_SIDE"
    SELL_SIDE = "SELL_SIDE"
    NONE = "NONE"


class TradeStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    BREAKEVEN = "BREAKEVEN"
    PARTIAL = "PARTIAL"


class ExitReason(Enum):
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    SESSION_END = "SESSION_END_EXIT"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    BREAKEVEN = "BREAKEVEN_EXIT"
    MAX_LOSS = "MAX_DAILY_LOSS"


@dataclass
class LiquidityLevel:
    """Represents a liquidity level (PDH, PDL, swing high/low, equal levels)."""
    price: float
    liquidity_type: LiquidityType
    source: str  # "PDH", "PDL", "SWING_HIGH", "SWING_LOW", "EQUAL_HIGH", "EQUAL_LOW"
    timestamp: datetime | None = None
    swept: bool = False
    sweep_time: datetime | None = None


@dataclass
class LiquiditySweep:
    """Represents a detected liquidity sweep."""
    direction: LiquidityType
    sweep_price: float
    sweep_time: datetime
    level_swept: float
    rejection: bool = True


@dataclass
class MarketStructureShift:
    """Represents a Market Structure Shift (MSS)."""
    direction: Direction
    price: float
    timestamp: datetime
    displacement_size: float = 0.0
    confirmed: bool = True


@dataclass
class FairValueGap:
    """Represents a Fair Value Gap (FVG)."""
    direction: Direction
    top: float
    bottom: float
    size: float
    timestamp: datetime
    filled: bool = False
    candle_index: int = 0


@dataclass
class OrderBlock:
    """Represents an Order Block (OB)."""
    direction: Direction
    high: float
    low: float
    timestamp: datetime
    mitigated: bool = False
    candle_index: int = 0


@dataclass
class TradeSetup:
    """Complete ICT trade setup with all confirmations."""
    direction: Direction
    daily_bias: Direction
    liquidity_sweep: LiquiditySweep | None = None
    mss: MarketStructureShift | None = None
    fvg: FairValueGap | None = None
    order_block: OrderBlock | None = None
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward: float = 0.0
    valid: bool = False

    def validate(self) -> bool:
        """Check if all ICT confirmations are present."""
        self.valid = all([
            self.daily_bias != Direction.NEUTRAL,
            self.liquidity_sweep is not None,
            self.mss is not None,
            self.fvg is not None,
            self.order_block is not None,
            self.entry_price > 0,
            self.stop_loss > 0,
            self.take_profit > 0,
        ])
        return self.valid


@dataclass
class TradeRecord:
    """Complete record of a trade for journaling."""
    trade_id: str = ""
    ticket: int = 0
    symbol: str = ""
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    trade_type: str = ""
    lot_size: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward: float = 0.0
    profit_loss: float = 0.0
    profit_loss_percent: float = 0.0
    daily_bias: str = ""
    liquidity_type: str = ""
    sweep_type: str = ""
    mss_direction: str = ""
    fvg_direction: str = ""
    ob_type: str = ""
    trade_result: str = ""
    exit_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for CSV export."""
        return {
            "trade_id": self.trade_id,
            "ticket": self.ticket,
            "symbol": self.symbol,
            "entry_time": self.entry_time.isoformat() if self.entry_time else "",
            "exit_time": self.exit_time.isoformat() if self.exit_time else "",
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "trade_type": self.trade_type,
            "lot_size": self.lot_size,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "profit_loss": self.profit_loss,
            "profit_loss_percent": self.profit_loss_percent,
            "daily_bias": self.daily_bias,
            "liquidity_type": self.liquidity_type,
            "sweep_type": self.sweep_type,
            "mss_direction": self.mss_direction,
            "fvg_direction": self.fvg_direction,
            "ob_type": self.ob_type,
            "trade_result": self.trade_result,
            "exit_reason": self.exit_reason,
        }


@dataclass
class MarketState:
    """Current market state snapshot for CSV logging."""
    timestamp: datetime | None = None
    ny_time: str = ""
    ist_time: str = ""
    symbol: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0
    session_high: float = 0.0
    session_low: float = 0.0
    session_midpoint: float = 0.0
    daily_bias: str = "NEUTRAL"
    liquidity_type: str = "NONE"
    liquidity_price: float = 0.0
    sweep_detected: bool = False
    sweep_type: str = ""
    mss_detected: bool = False
    mss_direction: str = ""
    fvg_detected: bool = False
    fvg_top: float = 0.0
    fvg_bottom: float = 0.0
    ob_detected: bool = False
    ob_type: str = ""
    entry_signal: bool = False
    current_trade_status: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for CSV export."""
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else "",
            "ny_time": self.ny_time,
            "ist_time": self.ist_time,
            "symbol": self.symbol,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "bid": self.bid,
            "ask": self.ask,
            "spread": self.spread,
            "session_high": self.session_high,
            "session_low": self.session_low,
            "session_midpoint": self.session_midpoint,
            "daily_bias": self.daily_bias,
            "liquidity_type": self.liquidity_type,
            "liquidity_price": self.liquidity_price,
            "sweep_detected": self.sweep_detected,
            "sweep_type": self.sweep_type,
            "mss_detected": self.mss_detected,
            "mss_direction": self.mss_direction,
            "fvg_detected": self.fvg_detected,
            "fvg_top": self.fvg_top,
            "fvg_bottom": self.fvg_bottom,
            "ob_detected": self.ob_detected,
            "ob_type": self.ob_type,
            "entry_signal": self.entry_signal,
            "current_trade_status": self.current_trade_status,
        }
