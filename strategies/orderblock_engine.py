"""Order Block Detection Engine - ICT 2022."""

from datetime import datetime

import pandas as pd
from loguru import logger

from config.settings import TradingConfig
from core.data_models import (
    Direction,
    FairValueGap,
    LiquiditySweep,
    MarketStructureShift,
    OrderBlock,
)


class OrderBlockEngine:
    """Detects Order Blocks based on ICT 2022 methodology."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.order_blocks: list[OrderBlock] = []
        self.min_displacement = config.min_displacement_pips * config.pip_value

    def detect_order_block(
        self,
        df: pd.DataFrame,
        sweep: LiquiditySweep | None,
        mss: MarketStructureShift | None,
    ) -> OrderBlock | None:
        """
        Detect Order Block.

        Bullish OB: Last bearish candle before bullish displacement
        Bearish OB: Last bullish candle before bearish displacement

        Requirements: Liquidity sweep + MSS + Displacement must exist.
        """
        if len(df) < 5 or sweep is None or mss is None:
            return None

        if mss.direction == Direction.BULLISH:
            ob = self._find_bullish_ob(df)
            if ob:
                self.order_blocks.append(ob)
                logger.info(
                    f"BULLISH OB detected | High: {ob.high:.5f} | Low: {ob.low:.5f}"
                )
                return ob

        elif mss.direction == Direction.BEARISH:
            ob = self._find_bearish_ob(df)
            if ob:
                self.order_blocks.append(ob)
                logger.info(
                    f"BEARISH OB detected | High: {ob.high:.5f} | Low: {ob.low:.5f}"
                )
                return ob

        return None

    def _find_bullish_ob(self, df: pd.DataFrame) -> OrderBlock | None:
        """Find the last bearish candle before bullish displacement."""
        # Look back from recent candles for displacement
        for i in range(len(df) - 1, max(len(df) - 10, 0), -1):
            candle = df.iloc[i]
            body = candle["close"] - candle["open"]

            # Found displacement candle (bullish)
            if body >= self.min_displacement:
                # Look for the last bearish candle before this displacement
                for j in range(i - 1, max(i - 5, 0), -1):
                    prev = df.iloc[j]
                    if prev["close"] < prev["open"]:  # Bearish candle
                        return OrderBlock(
                            direction=Direction.BULLISH,
                            high=prev["high"],
                            low=prev["low"],
                            timestamp=prev.get("timestamp", datetime.now()),
                            candle_index=j,
                        )
                break

        return None

    def _find_bearish_ob(self, df: pd.DataFrame) -> OrderBlock | None:
        """Find the last bullish candle before bearish displacement."""
        for i in range(len(df) - 1, max(len(df) - 10, 0), -1):
            candle = df.iloc[i]
            body = candle["open"] - candle["close"]

            # Found displacement candle (bearish)
            if body >= self.min_displacement:
                # Look for the last bullish candle before this displacement
                for j in range(i - 1, max(i - 5, 0), -1):
                    prev = df.iloc[j]
                    if prev["close"] > prev["open"]:  # Bullish candle
                        return OrderBlock(
                            direction=Direction.BEARISH,
                            high=prev["high"],
                            low=prev["low"],
                            timestamp=prev.get("timestamp", datetime.now()),
                            candle_index=j,
                        )
                break

        return None

    def check_retracement_into_ob(self, price: float, direction: Direction) -> OrderBlock | None:
        """Check if price has retraced into an unmitigated Order Block."""
        for ob in reversed(self.order_blocks):
            if ob.mitigated or ob.direction != direction:
                continue

            if ob.low <= price <= ob.high:
                logger.info(
                    f"Price retraced into {direction.value} OB | "
                    f"Price: {price:.5f} | OB: {ob.low:.5f}-{ob.high:.5f}"
                )
                return ob

        return None

    def check_ob_mitigation(self, current_price: float) -> None:
        """Mark OBs as mitigated if price has traded through them."""
        for ob in self.order_blocks:
            if ob.mitigated:
                continue
            if ob.direction == Direction.BULLISH:
                if current_price < ob.low:
                    ob.mitigated = True
            else:
                if current_price > ob.high:
                    ob.mitigated = True

    def get_latest_ob(self, direction: Direction | None = None) -> OrderBlock | None:
        """Get the most recent unmitigated Order Block."""
        if not self.order_blocks:
            return None
        active = [ob for ob in self.order_blocks if not ob.mitigated]
        if direction:
            active = [ob for ob in active if ob.direction == direction]
        return active[-1] if active else None

    def reset(self) -> None:
        """Reset order block data for new session."""
        self.order_blocks = []
