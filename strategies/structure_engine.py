"""Market Structure Shift (MSS) Detection Engine - ICT 2022."""

from datetime import datetime

import pandas as pd
from loguru import logger

from config.settings import TradingConfig
from core.data_models import Direction, LiquiditySweep, LiquidityType, MarketStructureShift


class StructureEngine:
    """Detects Market Structure Shifts based on ICT 2022 methodology."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.mss_list: list[MarketStructureShift] = []
        self.min_displacement = config.min_displacement_pips * config.pip_value
        self.structure_highs: list[float] = []
        self.structure_lows: list[float] = []

    def update_structure(self, df: pd.DataFrame) -> None:
        """Update internal market structure from candle data."""
        if len(df) < 5:
            return

        # Track recent structure points
        self.structure_highs = []
        self.structure_lows = []

        highs = df["high"].values
        lows = df["low"].values

        # Find structure highs (lower highs in bearish, higher highs in bullish)
        for i in range(2, min(len(df), 30)):
            if i < len(highs) - 1:
                if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                    self.structure_highs.append(highs[i])
            if i < len(lows) - 1:
                if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                    self.structure_lows.append(lows[i])

    def detect_mss(
        self, df: pd.DataFrame, latest_sweep: LiquiditySweep | None
    ) -> MarketStructureShift | None:
        """
        Detect Market Structure Shift.

        Bullish MSS: Sell-side liquidity taken + bullish displacement + break of bearish structure
        Bearish MSS: Buy-side liquidity taken + bearish displacement + break of bullish structure
        """
        if len(df) < 5 or latest_sweep is None:
            return None

        self.update_structure(df)

        latest = df.iloc[-1]
        prev_candles = df.iloc[-5:-1]

        # Bullish MSS conditions
        if latest_sweep.direction == LiquidityType.SELL_SIDE:
            displacement = self._check_bullish_displacement(df)
            if displacement:
                structure_break = self._check_bullish_structure_break(df)
                if structure_break:
                    mss = MarketStructureShift(
                        direction=Direction.BULLISH,
                        price=latest["close"],
                        timestamp=latest.get("timestamp", datetime.now()),
                        displacement_size=displacement,
                        confirmed=True,
                    )
                    self.mss_list.append(mss)
                    logger.info(
                        f"BULLISH MSS detected | Price: {mss.price} | "
                        f"Displacement: {displacement / self.config.pip_value:.1f} pips"
                    )
                    return mss

        # Bearish MSS conditions
        elif latest_sweep.direction == LiquidityType.BUY_SIDE:
            displacement = self._check_bearish_displacement(df)
            if displacement:
                structure_break = self._check_bearish_structure_break(df)
                if structure_break:
                    mss = MarketStructureShift(
                        direction=Direction.BEARISH,
                        price=latest["close"],
                        timestamp=latest.get("timestamp", datetime.now()),
                        displacement_size=displacement,
                        confirmed=True,
                    )
                    self.mss_list.append(mss)
                    logger.info(
                        f"BEARISH MSS detected | Price: {mss.price} | "
                        f"Displacement: {displacement / self.config.pip_value:.1f} pips"
                    )
                    return mss

        return None

    def _check_bullish_displacement(self, df: pd.DataFrame) -> float:
        """Check for strong bullish displacement (large body candle up)."""
        if len(df) < 3:
            return 0.0

        # Check last 3 candles for displacement
        for i in range(-3, 0):
            candle = df.iloc[i]
            body = candle["close"] - candle["open"]
            if body >= self.min_displacement:
                return body

        return 0.0

    def _check_bearish_displacement(self, df: pd.DataFrame) -> float:
        """Check for strong bearish displacement (large body candle down)."""
        if len(df) < 3:
            return 0.0

        for i in range(-3, 0):
            candle = df.iloc[i]
            body = candle["open"] - candle["close"]
            if body >= self.min_displacement:
                return body

        return 0.0

    def _check_bullish_structure_break(self, df: pd.DataFrame) -> bool:
        """Check if price broke above recent bearish structure (lower high)."""
        if len(df) < 10 or not self.structure_highs:
            return False

        latest_close = df.iloc[-1]["close"]

        # Check if current close is above a recent structure high
        for sh in sorted(self.structure_highs)[-3:]:
            if latest_close > sh:
                return True

        return False

    def _check_bearish_structure_break(self, df: pd.DataFrame) -> bool:
        """Check if price broke below recent bullish structure (higher low)."""
        if len(df) < 10 or not self.structure_lows:
            return False

        latest_close = df.iloc[-1]["close"]

        # Check if current close is below a recent structure low
        for sl in sorted(self.structure_lows, reverse=True)[-3:]:
            if latest_close < sl:
                return True

        return False

    def get_latest_mss(self, direction: Direction | None = None) -> MarketStructureShift | None:
        """Get the most recent MSS, optionally filtered by direction."""
        if not self.mss_list:
            return None
        if direction is None:
            return self.mss_list[-1]
        filtered = [m for m in self.mss_list if m.direction == direction]
        return filtered[-1] if filtered else None

    def reset(self) -> None:
        """Reset structure data for new session."""
        self.mss_list = []
        self.structure_highs = []
        self.structure_lows = []
