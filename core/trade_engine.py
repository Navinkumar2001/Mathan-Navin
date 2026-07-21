"""Trade Entry and Management Engine - ICT 2022."""

import uuid
from datetime import datetime
from typing import Any

import pandas as pd
from loguru import logger

from config.settings import TradingConfig
from core.data_models import (
    Direction,
    ExitReason,
    FairValueGap,
    LiquiditySweep,
    LiquidityType,
    MarketStructureShift,
    OrderBlock,
    TradeRecord,
    TradeSetup,
    TradeStatus,
)
from core.risk_manager import RiskManager


class TradeEngine:
    """Manages trade setup validation, entry, and position management."""

    def __init__(self, config: TradingConfig, risk_manager: RiskManager) -> None:
        self.config = config
        self.risk_manager = risk_manager
        self.active_trade: TradeRecord | None = None
        self.trade_history: list[TradeRecord] = []
        self.current_setup: TradeSetup | None = None
        self.breakeven_applied: bool = False
        self.partial_tp1_hit: bool = False
        self.partial_tp2_hit: bool = False

    def evaluate_range_reentry(
        self,
        signal: str,
        current_price: float,
        session_high: float,
        session_low: float,
        is_trading_session: bool,
        df: pd.DataFrame | None = None,
    ) -> TradeSetup | None:
        """
        Evaluate a range breakout re-entry signal.

        This is the primary entry methodology:
        - During IST 09:00-18:30 we observe and mark session High/Low.
        - During IST 18:30-23:30, if price crosses a boundary and comes back inside:
          * Crossed HIGH -> came back inside -> SELL (reversal from premium)
          * Crossed LOW -> came back inside -> BUY (reversal from discount)

        Args:
            signal: "BUY" or "SELL" from SessionManager.check_range_breakout_reentry()
            current_price: Current market price
            session_high: Observation session high (range top)
            session_low: Observation session low (range bottom)
            is_trading_session: Whether we are in the trading window
            df: Price dataframe for ATR-based stop loss calculation
        """
        if not is_trading_session:
            return None

        if self.active_trade is not None:
            return None

        can_trade, reason = self.risk_manager.can_trade()
        if not can_trade:
            return None

        session_range = session_high - session_low
        if session_range <= 0:
            return None

        # Minimum risk distance: at least 5 pips between entry and SL
        min_risk_pips = 5.0
        min_risk = min_risk_pips * self.config.pip_value

        if signal == "BUY":
            # Use ATR-based stop loss if dataframe is available
            if df is not None and len(df) >= 15:
                stop_loss = self.risk_manager.calculate_atr_stop_loss(
                    current_price, "BUY", df
                )
            else:
                stop_loss = session_low - (self.config.pip_value * 15)  # 15 pip buffer fallback

            risk = current_price - stop_loss

            # Skip if risk is too small (price barely inside the range)
            if risk < min_risk:
                logger.debug(
                    f"BUY setup rejected: risk too small ({risk / self.config.pip_value:.1f} pips)"
                )
                return None

            take_profit = current_price + (risk * self.config.reward_ratio)

            setup = TradeSetup(
                direction=Direction.BULLISH,
                daily_bias=Direction.BULLISH,
                liquidity_sweep=None,
                mss=None,
                fvg=None,
                order_block=None,
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_reward=self.config.reward_ratio,
            )
            setup.valid = True  # Range re-entry is the confirmation itself
            self.current_setup = setup

            logger.info(
                f"RANGE RE-ENTRY BUY SETUP | Entry: {current_price:.5f} | "
                f"SL: {stop_loss:.5f} | TP: {take_profit:.5f} | RR: {self.config.reward_ratio}"
            )
            return setup

        elif signal == "SELL":
            # Use ATR-based stop loss if dataframe is available
            if df is not None and len(df) >= 15:
                stop_loss = self.risk_manager.calculate_atr_stop_loss(
                    current_price, "SELL", df
                )
            else:
                stop_loss = session_high + (self.config.pip_value * 15)  # 15 pip buffer fallback

            risk = stop_loss - current_price

            # Skip if risk is too small (price barely inside the range)
            if risk < min_risk:
                logger.debug(
                    f"SELL setup rejected: risk too small ({risk / self.config.pip_value:.1f} pips)"
                )
                return None

            take_profit = current_price - (risk * self.config.reward_ratio)

            setup = TradeSetup(
                direction=Direction.BEARISH,
                daily_bias=Direction.BEARISH,
                liquidity_sweep=None,
                mss=None,
                fvg=None,
                order_block=None,
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_reward=self.config.reward_ratio,
            )
            setup.valid = True  # Range re-entry is the confirmation itself
            self.current_setup = setup

            logger.info(
                f"RANGE RE-ENTRY SELL SETUP | Entry: {current_price:.5f} | "
                f"SL: {stop_loss:.5f} | TP: {take_profit:.5f} | RR: {self.config.reward_ratio}"
            )
            return setup

        return None

    def evaluate_setup(
        self,
        bias: Direction,
        sweep: LiquiditySweep | None,
        mss: MarketStructureShift | None,
        fvg: FairValueGap | None,
        ob: OrderBlock | None,
        current_price: float,
        is_trading_session: bool,
        df: pd.DataFrame | None = None,
    ) -> TradeSetup | None:
        """
        Evaluate if all ICT confirmations are present for a valid trade setup.
        (Secondary/confluence method - range re-entry is the primary signal.)

        Long: Bullish bias + Sell-side sweep + Bullish MSS + Bullish FVG + Bullish OB + Retracement
        Short: Bearish bias + Buy-side sweep + Bearish MSS + Bearish FVG + Bearish OB + Retracement
        """
        if not is_trading_session:
            return None

        if self.active_trade is not None:
            return None

        can_trade, reason = self.risk_manager.can_trade()
        if not can_trade:
            return None

        if bias == Direction.NEUTRAL:
            return None

        # Validate long setup
        if bias == Direction.BULLISH:
            return self._evaluate_long_setup(sweep, mss, fvg, ob, current_price, df)

        # Validate short setup
        if bias == Direction.BEARISH:
            return self._evaluate_short_setup(sweep, mss, fvg, ob, current_price, df)

        return None

    def _evaluate_long_setup(
        self,
        sweep: LiquiditySweep | None,
        mss: MarketStructureShift | None,
        fvg: FairValueGap | None,
        ob: OrderBlock | None,
        current_price: float,
        df: pd.DataFrame | None = None,
    ) -> TradeSetup | None:
        """Evaluate bullish trade setup with ATR-based stop loss."""
        # All confirmations required
        if not all([
            sweep and sweep.direction == LiquidityType.SELL_SIDE,
            mss and mss.direction == Direction.BULLISH,
            fvg and fvg.direction == Direction.BULLISH,
            ob and ob.direction == Direction.BULLISH,
        ]):
            return None

        # Check retracement into FVG or OB
        in_fvg = fvg and fvg.bottom <= current_price <= fvg.top
        in_ob = ob and ob.low <= current_price <= ob.high

        if not (in_fvg or in_ob):
            return None

        # Calculate SL using ATR strategy
        if df is not None and len(df) >= 15:
            stop_loss = self.risk_manager.calculate_atr_stop_loss(
                current_price, "BUY", df
            )
            # Also consider structural levels - use the lower of ATR SL and structure
            sl_candidates = [stop_loss]
            if sweep:
                sl_candidates.append(sweep.sweep_price - (self.config.pip_value * 3))
            if ob:
                sl_candidates.append(ob.low - (self.config.pip_value * 3))
            # Use the lowest (most conservative) stop loss
            stop_loss = min(sl_candidates)
        else:
            # Fallback: structural SL with wider buffer
            sl_candidates = []
            if sweep:
                sl_candidates.append(sweep.sweep_price)
            if ob:
                sl_candidates.append(ob.low)
            stop_loss = min(sl_candidates) - (self.config.pip_value * 10)

        # Calculate TP at configured R:R
        risk = current_price - stop_loss
        take_profit = current_price + (risk * self.config.reward_ratio)

        setup = TradeSetup(
            direction=Direction.BULLISH,
            daily_bias=Direction.BULLISH,
            liquidity_sweep=sweep,
            mss=mss,
            fvg=fvg,
            order_block=ob,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=self.config.reward_ratio,
        )
        setup.validate()

        if setup.valid:
            self.current_setup = setup
            logger.info(
                f"VALID LONG SETUP | Entry: {current_price:.5f} | "
                f"SL: {stop_loss:.5f} | TP: {take_profit:.5f} | RR: {self.config.reward_ratio}"
            )

        return setup if setup.valid else None

    def _evaluate_short_setup(
        self,
        sweep: LiquiditySweep | None,
        mss: MarketStructureShift | None,
        fvg: FairValueGap | None,
        ob: OrderBlock | None,
        current_price: float,
        df: pd.DataFrame | None = None,
    ) -> TradeSetup | None:
        """Evaluate bearish trade setup with ATR-based stop loss."""
        if not all([
            sweep and sweep.direction == LiquidityType.BUY_SIDE,
            mss and mss.direction == Direction.BEARISH,
            fvg and fvg.direction == Direction.BEARISH,
            ob and ob.direction == Direction.BEARISH,
        ]):
            return None

        # Check retracement into FVG or OB
        in_fvg = fvg and fvg.bottom <= current_price <= fvg.top
        in_ob = ob and ob.low <= current_price <= ob.high

        if not (in_fvg or in_ob):
            return None

        # Calculate SL using ATR strategy
        if df is not None and len(df) >= 15:
            stop_loss = self.risk_manager.calculate_atr_stop_loss(
                current_price, "SELL", df
            )
            # Also consider structural levels - use the higher of ATR SL and structure
            sl_candidates = [stop_loss]
            if sweep:
                sl_candidates.append(sweep.sweep_price + (self.config.pip_value * 3))
            if ob:
                sl_candidates.append(ob.high + (self.config.pip_value * 3))
            # Use the highest (most conservative) stop loss
            stop_loss = max(sl_candidates)
        else:
            # Fallback: structural SL with wider buffer
            sl_candidates = []
            if sweep:
                sl_candidates.append(sweep.sweep_price)
            if ob:
                sl_candidates.append(ob.high)
            stop_loss = max(sl_candidates) + (self.config.pip_value * 10)

        # Calculate TP
        risk = stop_loss - current_price
        take_profit = current_price - (risk * self.config.reward_ratio)

        setup = TradeSetup(
            direction=Direction.BEARISH,
            daily_bias=Direction.BEARISH,
            liquidity_sweep=sweep,
            mss=mss,
            fvg=fvg,
            order_block=ob,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=self.config.reward_ratio,
        )
        setup.validate()

        if setup.valid:
            self.current_setup = setup
            logger.info(
                f"VALID SHORT SETUP | Entry: {current_price:.5f} | "
                f"SL: {stop_loss:.5f} | TP: {take_profit:.5f} | RR: {self.config.reward_ratio}"
            )

        return setup if setup.valid else None

    def execute_trade(self, setup: TradeSetup, account_balance: float) -> TradeRecord | None:
        """Execute a trade based on validated setup (for backtesting, records entry)."""
        if not setup.valid:
            return None

        # Use fixed lot size from config
        lot_size = self.config.lot_size

        if lot_size <= 0:
            return None

        trade = TradeRecord(
            trade_id=str(uuid.uuid4())[:8],
            ticket=0,
            symbol=self.config.symbol,
            entry_time=datetime.now(),
            entry_price=setup.entry_price,
            trade_type="BUY" if setup.direction == Direction.BULLISH else "SELL",
            lot_size=lot_size,
            stop_loss=setup.stop_loss,
            take_profit=setup.take_profit,
            risk_reward=setup.risk_reward,
            daily_bias=setup.daily_bias.value,
            liquidity_type=setup.liquidity_sweep.direction.value if setup.liquidity_sweep else "",
            sweep_type=setup.liquidity_sweep.direction.value if setup.liquidity_sweep else "",
            mss_direction=setup.mss.direction.value if setup.mss else "",
            fvg_direction=setup.fvg.direction.value if setup.fvg else "",
            ob_type=setup.order_block.direction.value if setup.order_block else "",
        )

        self.active_trade = trade
        self.breakeven_applied = False
        self.partial_tp1_hit = False
        self.partial_tp2_hit = False
        self.risk_manager.update_open_positions(1)

        logger.info(
            f"TRADE EXECUTED | {trade.trade_type} | Entry: {trade.entry_price:.5f} | "
            f"Lot: {trade.lot_size} | SL: {trade.stop_loss:.5f} | TP: {trade.take_profit:.5f}"
        )
        return trade

    def manage_trade(self, current_price: float, current_time: datetime) -> TradeRecord | None:
        """
        Manage active trade: check SL/TP, breakeven, partials.
        Returns trade record if trade is closed.
        """
        if self.active_trade is None:
            return None

        trade = self.active_trade

        # Check stop loss
        if trade.trade_type == "BUY":
            if current_price <= trade.stop_loss:
                return self._close_trade(current_price, current_time, ExitReason.SL_HIT)

            # Check take profit
            if current_price >= trade.take_profit:
                return self._close_trade(current_price, current_time, ExitReason.TP_HIT)

            # Check breakeven
            risk = trade.entry_price - trade.stop_loss
            if not self.breakeven_applied and current_price >= trade.entry_price + risk:
                be_price = self.risk_manager.calculate_breakeven_price(
                    trade.entry_price, "BUY"
                )
                trade.stop_loss = be_price
                self.breakeven_applied = True
                logger.info(f"BREAKEVEN applied | New SL: {be_price:.5f}")

        else:  # SELL
            if current_price >= trade.stop_loss:
                return self._close_trade(current_price, current_time, ExitReason.SL_HIT)

            if current_price <= trade.take_profit:
                return self._close_trade(current_price, current_time, ExitReason.TP_HIT)

            # Check breakeven
            risk = trade.stop_loss - trade.entry_price
            if not self.breakeven_applied and current_price <= trade.entry_price - risk:
                be_price = self.risk_manager.calculate_breakeven_price(
                    trade.entry_price, "SELL"
                )
                trade.stop_loss = be_price
                self.breakeven_applied = True
                logger.info(f"BREAKEVEN applied | New SL: {be_price:.5f}")

        return None

    def session_exit(self, current_price: float, current_time: datetime) -> TradeRecord | None:
        """Close trade at session end."""
        if self.active_trade is None:
            return None
        return self._close_trade(current_price, current_time, ExitReason.SESSION_END)

    def _close_trade(
        self, exit_price: float, exit_time: datetime, reason: ExitReason
    ) -> TradeRecord:
        """Close the active trade and calculate P/L."""
        trade = self.active_trade
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.exit_reason = reason.value

        # Calculate P/L
        if trade.trade_type == "BUY":
            trade.profit_loss = (exit_price - trade.entry_price) / self.config.pip_value
        else:
            trade.profit_loss = (trade.entry_price - exit_price) / self.config.pip_value

        # Determine result
        if trade.profit_loss > 0:
            trade.trade_result = "WIN"
        elif trade.profit_loss < 0:
            trade.trade_result = "LOSS"
        else:
            trade.trade_result = "BREAKEVEN"

        # Calculate P/L percent (approximate)
        risk_pips = abs(trade.entry_price - trade.stop_loss) / self.config.pip_value
        if risk_pips > 0:
            trade.profit_loss_percent = (trade.profit_loss / risk_pips) * self.config.risk_percent
        trade.risk_reward = abs(trade.profit_loss / risk_pips) if risk_pips > 0 else 0

        self.trade_history.append(trade)
        self.risk_manager.record_trade_result(trade)
        self.risk_manager.update_open_positions(0)

        logger.info(
            f"TRADE CLOSED | {trade.trade_result} | P/L: {trade.profit_loss:.1f} pips | "
            f"Reason: {reason.value} | RR: {trade.risk_reward:.2f}"
        )

        self.active_trade = None
        self.current_setup = None
        return trade

    @property
    def has_active_trade(self) -> bool:
        return self.active_trade is not None

    def reset(self) -> None:
        """Reset trade engine state."""
        self.active_trade = None
        self.current_setup = None
        self.breakeven_applied = False
        self.partial_tp1_hit = False
        self.partial_tp2_hit = False
