"""Fair Value Gap (FVG) Detection Engine - ICT 2022."""

from datetime import datetime

import pandas as pd
from loguru import logger

from config.settings import TradingConfig
from core.data_models import Direction, FairValueGap


class FVGEngine:
    """Detects Fair Value Gaps using ICT 2022 three-candle methodology."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.fvg_list: list[FairValueGap] = []
        self.min_fvg_size = config.min_fvg_size_pips * config.pip_value

    def detect_fvg(self, df: pd.DataFrame) -> FairValueGap | None:
        """
        Detect Fair Value Gap on the most recent candles.

        Bullish FVG: Candle 1 High < Candle 3 Low (gap up)
        Bearish FVG: Candle 1 Low > Candle 3 High (gap down)
        """
        if len(df) < 3:
            return None

        # Use last 3 completed candles
        c1 = df.iloc[-3]  # First candle
        c2 = df.iloc[-2]  # Middle candle (displacement)
        c3 = df.iloc[-1]  # Third candle

        # Bullish FVG: gap between candle 1 high and candle 3 low
        if c1["high"] < c3["low"]:
            size = c3["low"] - c1["high"]
            if size >= self.min_fvg_size:
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
                    f"BULLISH FVG detected | Top: {fvg.top:.5f} | "
                    f"Bottom: {fvg.bottom:.5f} | Size: {size / self.config.pip_value:.1f} pips"
                )
                return fvg

        # Bearish FVG: gap between candle 1 low and candle 3 high
        if c1["low"] > c3["high"]:
            size = c1["low"] - c3["high"]
            if size >= self.min_fvg_size:
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
                    f"BEARISH FVG detected | Top: {fvg.top:.5f} | "
                    f"Bottom: {fvg.bottom:.5f} | Size: {size / self.config.pip_value:.1f} pips"
                )
                return fvg

        return None

    def scan_all_fvgs(self, df: pd.DataFrame) -> list[FairValueGap]:
        """Scan entire dataframe for all FVGs."""
        fvgs: list[FairValueGap] = []

        for i in range(2, len(df)):
            c1 = df.iloc[i - 2]
            c2 = df.iloc[i - 1]
            c3 = df.iloc[i]

            # Bullish FVG
            if c1["high"] < c3["low"]:
                size = c3["low"] - c1["high"]
                if size >= self.min_fvg_size:
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
                if size >= self.min_fvg_size:
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
