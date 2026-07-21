"""Fair Value Gap (FVG) Detection Engine - ICT 2022 with Full Confirmation."""

from datetime import datetime

import pandas as pd
from loguru import logger

from config.settings import TradingConfig
from core.data_models import Direction, FairValueGap


class FVGEngine:
    """Detects Fair Value Gaps using ICT 2022 three-candle methodology with full confirmation."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.fvg_list: list[FairValueGap] = []
        self.min_fvg_size = config.min_fvg_size_pips * config.pip_value

    def _is_displacement_candle(self, candle: pd.Series) -> bool:
        """
        Check if the middle candle (candle 2) is a strong displacement candle.
        A displacement candle should have a large body relative to its range,
        indicating strong momentum that creates the gap.
        """
        body = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]

        if total_range <= 0:
            return False

        # Body must be at least 60% of total candle range (strong momentum)
        body_ratio = body / total_range
        if body_ratio < 0.6:
            return False

        # Candle range must be meaningful (at least min_displacement_pips)
        min_displacement = self.config.min_displacement_pips * self.config.pip_value
        if total_range < min_displacement:
            return False

        return True

    def _is_fvg_confirmed(
        self, c1: pd.Series, c2: pd.Series, c3: pd.Series, direction: Direction
    ) -> bool:
        """
        Confirm FVG is 100% valid by checking all three candles.

        For a confirmed FVG:
        - Bullish: c2 must be bullish, c3 must close above FVG bottom (c1 high)
        - Bearish: c2 must be bearish, c3 must close below FVG top (c1 low)

        This ensures the gap is respected and not just a wick anomaly.
        """
        if direction == Direction.BULLISH:
            # Middle candle must be bullish (close > open)
            if c2["close"] <= c2["open"]:
                return False
            # Candle 3 must close above the FVG bottom - gap is held
            if c3["close"] <= c1["high"]:
                return False
            # Candle 3 body should be bullish for confirmation
            if c3["close"] < c3["open"]:
                return False
        else:
            # Middle candle must be bearish (close < open)
            if c2["close"] >= c2["open"]:
                return False
            # Candle 3 must close below the FVG top - gap is held
            if c3["close"] >= c1["low"]:
                return False
            # Candle 3 body should be bearish for confirmation
            if c3["close"] > c3["open"]:
                return False

        return True

    def detect_fvg(self, df: pd.DataFrame) -> FairValueGap | None:
        """
        Detect a 100% confirmed Fair Value Gap on the most recent 3 candles.

        Confirmation criteria:
        1. Three-candle gap structure (c1 high < c3 low for bullish)
        2. Middle candle (c2) must be a strong displacement candle
        3. Candle 3 must confirm the gap is held (close respects the FVG zone)
        4. Gap size must meet minimum threshold
        """
        if len(df) < 3:
            return None

        c1 = df.iloc[-3]
        c2 = df.iloc[-2]
        c3 = df.iloc[-1]

        # Check displacement on middle candle first
        if not self._is_displacement_candle(c2):
            return None

        # Bullish FVG: gap between candle 1 high and candle 3 low
        if c1["high"] < c3["low"]:
            size = c3["low"] - c1["high"]
            if size < self.min_fvg_size:
                return None

            # Full confirmation check
            if not self._is_fvg_confirmed(c1, c2, c3, Direction.BULLISH):
                return None

            fvg = FairValueGap(
                direction=Direction.BULLISH,
                top=c3["low"],
                bottom=c1["high"],
                size=size,
                timestamp=c3.get("timestamp", datetime.now()),
                candle_index=len(df) - 2,
            )
            self.fvg_list.append(fvg)
            logger.info(
                f"CONFIRMED BULLISH FVG | Top: {fvg.top:.5f} | "
                f"Bottom: {fvg.bottom:.5f} | Size: {size / self.config.pip_value:.1f} pips"
            )
            return fvg

        # Bearish FVG: gap between candle 1 low and candle 3 high
        if c1["low"] > c3["high"]:
            size = c1["low"] - c3["high"]
            if size < self.min_fvg_size:
                return None

            # Full confirmation check
            if not self._is_fvg_confirmed(c1, c2, c3, Direction.BEARISH):
                return None

            fvg = FairValueGap(
                direction=Direction.BEARISH,
                top=c1["low"],
                bottom=c3["high"],
                size=size,
                timestamp=c3.get("timestamp", datetime.now()),
                candle_index=len(df) - 2,
            )
            self.fvg_list.append(fvg)
            logger.info(
                f"CONFIRMED BEARISH FVG | Top: {fvg.top:.5f} | "
                f"Bottom: {fvg.bottom:.5f} | Size: {size / self.config.pip_value:.1f} pips"
            )
            return fvg

        return None

    def scan_all_fvgs(self, df: pd.DataFrame) -> list[FairValueGap]:
        """Scan entire dataframe for all confirmed FVGs."""
        fvgs: list[FairValueGap] = []

        for i in range(2, len(df)):
            c1 = df.iloc[i - 2]
            c2 = df.iloc[i - 1]
            c3 = df.iloc[i]

            # Check displacement on middle candle
            body = abs(c2["close"] - c2["open"])
            total_range = c2["high"] - c2["low"]
            if total_range <= 0:
                continue
            body_ratio = body / total_range
            min_displacement = self.config.min_displacement_pips * self.config.pip_value
            if body_ratio < 0.6 or total_range < min_displacement:
                continue

            # Bullish FVG
            if c1["high"] < c3["low"]:
                size = c3["low"] - c1["high"]
                if size < self.min_fvg_size:
                    continue
                if not self._is_fvg_confirmed(c1, c2, c3, Direction.BULLISH):
                    continue
                fvgs.append(FairValueGap(
                    direction=Direction.BULLISH,
                    top=c3["low"],
                    bottom=c1["high"],
                    size=size,
                    timestamp=c3.get("timestamp", datetime.now()),
                    candle_index=i - 1,
                ))

            # Bearish FVG
            elif c1["low"] > c3["high"]:
                size = c1["low"] - c3["high"]
                if size < self.min_fvg_size:
                    continue
                if not self._is_fvg_confirmed(c1, c2, c3, Direction.BEARISH):
                    continue
                fvgs.append(FairValueGap(
                    direction=Direction.BEARISH,
                    top=c1["low"],
                    bottom=c3["high"],
                    size=size,
                    timestamp=c3.get("timestamp", datetime.now()),
                    candle_index=i - 1,
                ))

        self.fvg_list = fvgs
        return fvgs

    def check_fvg_fill(self, current_price: float) -> None:
        """Mark FVGs as filled if price has traded through them."""
        for fvg in self.fvg_list:
            if fvg.filled:
                continue
            if fvg.direction == Direction.BULLISH:
                if current_price <= fvg.bottom:
                    fvg.filled = True
            else:
                if current_price >= fvg.top:
                    fvg.filled = True

    def check_retracement_into_fvg(self, price: float, direction: Direction) -> FairValueGap | None:
        """Check if price has retraced into an unfilled FVG."""
        for fvg in reversed(self.fvg_list):
            if fvg.filled or fvg.direction != direction:
                continue

            if fvg.bottom <= price <= fvg.top:
                logger.info(
                    f"Price retraced into {direction.value} FVG | "
                    f"Price: {price:.5f} | FVG: {fvg.bottom:.5f}-{fvg.top:.5f}"
                )
                return fvg

        return None

    def get_latest_fvg(self, direction: Direction | None = None) -> FairValueGap | None:
        """Get the most recent unfilled FVG."""
        if not self.fvg_list:
            return None
        unfilled = [f for f in self.fvg_list if not f.filled]
        if direction:
            unfilled = [f for f in unfilled if f.direction == direction]
        return unfilled[-1] if unfilled else None

    def reset(self) -> None:
        """Reset FVG data for new session."""
        self.fvg_list = []
