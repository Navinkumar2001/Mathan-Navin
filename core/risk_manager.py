"""Risk Management Module with ATR-based Stop Loss."""

import pandas as pd
from loguru import logger

from config.settings import TradingConfig
from core.data_models import TradeRecord


class RiskManager:
    """Manages position sizing, daily risk limits, and trade restrictions."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.daily_losses: int = 0
        self.daily_pnl: float = 0.0
        self.open_positions: int = 0
        self.trading_halted: bool = False
        self.halt_reason: str = ""
        self.atr_period: int = config.atr_period
        self.atr_multiplier: float = config.atr_multiplier

    def calculate_position_size(
        self, account_balance: float, stop_loss_pips: float
    ) -> float:
        """
        Calculate lot size based on risk percentage and stop loss distance.

        Formula: Lot Size = (Account Balance * Risk%) / (SL pips * Pip Value per lot)
        """
        if stop_loss_pips <= 0 or account_balance <= 0:
            return 0.0

        risk_amount = account_balance * (self.config.risk_percent / 100.0)

        # Standard lot pip value (approximate for most pairs)
        # For EURUSD: 1 standard lot = $10 per pip
        pip_value_per_lot = 10.0
        if "JPY" in self.config.symbol:
            pip_value_per_lot = 1000.0 / 100.0  # Approximate

        lot_size = risk_amount / (stop_loss_pips * pip_value_per_lot)

        # Round to 2 decimal places (0.01 minimum lot)
        lot_size = round(lot_size, 2)
        lot_size = max(0.01, lot_size)

        logger.debug(
            f"Position size: {lot_size} | Risk: ${risk_amount:.2f} | "
            f"SL: {stop_loss_pips:.1f} pips"
        )
        return lot_size

    def calculate_atr(self, df: pd.DataFrame, period: int | None = None) -> float:
        """
        Calculate Average True Range (ATR) for dynamic stop loss placement.

        ATR measures volatility using the greatest of:
        - Current High - Current Low
        - abs(Current High - Previous Close)
        - abs(Current Low - Previous Close)
        """
        if period is None:
            period = self.atr_period

        if len(df) < period + 1:
            # Fallback: use simple high-low range if not enough data
            if len(df) >= 2:
                return (df["high"] - df["low"]).tail(min(len(df), period)).mean()
            return 0.0

        high = df["high"]
        low = df["low"]
        close = df["close"]

        # True Range calculation
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # ATR is the smoothed average of True Range
        atr = true_range.rolling(window=period).mean().iloc[-1]

        return float(atr) if pd.notna(atr) else 0.0

    def calculate_atr_stop_loss(
        self, entry_price: float, direction: str, df: pd.DataFrame
    ) -> float:
        """
        Calculate stop loss using ATR-based strategy.

        Places SL at entry +/- (ATR * multiplier), giving the trade enough
        room to breathe based on current market volatility.

        Args:
            entry_price: The trade entry price
            direction: "BUY" or "SELL"
            df: Price dataframe for ATR calculation

        Returns:
            Stop loss price level
        """
        atr = self.calculate_atr(df)

        if atr <= 0:
            # Fallback to fixed pip buffer if ATR can't be calculated
            buffer = self.config.pip_value * 15
            if direction == "BUY":
                return entry_price - buffer
            return entry_price + buffer

        sl_distance = atr * self.atr_multiplier

        # Ensure minimum SL distance of 10 pips to avoid being too tight
        min_sl_distance = self.config.pip_value * 10
        sl_distance = max(sl_distance, min_sl_distance)

        if direction == "BUY":
            stop_loss = entry_price - sl_distance
        else:
            stop_loss = entry_price + sl_distance

        sl_pips = sl_distance / self.config.pip_value
        logger.info(
            f"ATR SL | ATR: {atr / self.config.pip_value:.1f} pips | "
            f"SL distance: {sl_pips:.1f} pips | SL: {stop_loss:.5f}"
        )
        return stop_loss

    def can_trade(self) -> tuple[bool, str]:
        """Check if trading is allowed based on risk limits."""
        if self.trading_halted:
            return False, self.halt_reason

        if self.daily_losses >= self.config.max_daily_losses:
            self.trading_halted = True
            self.halt_reason = f"Max daily losses reached ({self.daily_losses})"
            logger.warning(self.halt_reason)
            return False, self.halt_reason

        max_daily_risk_amount = self.config.max_daily_risk
        if abs(self.daily_pnl) >= max_daily_risk_amount:
            self.trading_halted = True
            self.halt_reason = f"Max daily risk reached ({self.daily_pnl:.2f}%)"
            logger.warning(self.halt_reason)
            return False, self.halt_reason

        if self.open_positions >= self.config.max_open_trades:
            return False, f"Max open positions reached ({self.open_positions})"

        return True, "OK"

    def check_spread(self, current_spread: float) -> bool:
        """Check if current spread is acceptable."""
        if current_spread > self.config.spread_limit:
            logger.debug(f"Spread too wide: {current_spread} > {self.config.spread_limit}")
            return False
        return True

    def record_trade_result(self, trade: TradeRecord) -> None:
        """Record a completed trade for daily tracking."""
        if trade.profit_loss < 0:
            self.daily_losses += 1
        self.daily_pnl += trade.profit_loss_percent

        logger.info(
            f"Trade recorded | P/L: {trade.profit_loss:.2f} | "
            f"Daily losses: {self.daily_losses} | Daily P/L: {self.daily_pnl:.2f}%"
        )

    def update_open_positions(self, count: int) -> None:
        """Update current open position count."""
        self.open_positions = count

    def calculate_stop_loss_pips(self, entry: float, sl: float) -> float:
        """Calculate stop loss in pips."""
        return abs(entry - sl) / self.config.pip_value

    def calculate_take_profit(
        self, entry: float, sl: float, direction: str
    ) -> list[float]:
        """Calculate TP levels at 1R, 2R, 3R."""
        risk = abs(entry - sl)
        tps = []

        for multiplier in [1.0, 2.0, 3.0]:
            if direction == "BUY":
                tps.append(entry + (risk * multiplier))
            else:
                tps.append(entry - (risk * multiplier))

        return tps

    def calculate_breakeven_price(self, entry: float, direction: str) -> float:
        """Calculate breakeven price (entry + spread buffer)."""
        spread_buffer = self.config.pip_value * 2  # 2 pip buffer
        if direction == "BUY":
            return entry + spread_buffer
        return entry - spread_buffer

    def reset_daily(self) -> None:
        """Reset daily counters for new trading day."""
        self.daily_losses = 0
        self.daily_pnl = 0.0
        self.trading_halted = False
        self.halt_reason = ""
        logger.info("Daily risk counters reset.")
