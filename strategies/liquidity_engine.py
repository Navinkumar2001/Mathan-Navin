"""Liquidity Detection and Sweep Engine - ICT 2022."""

from datetime import datetime

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import TradingConfig
from core.data_models import Direction, LiquidityLevel, LiquiditySweep, LiquidityType


class LiquidityEngine:
    """Detects buy-side and sell-side liquidity levels and sweeps."""

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.liquidity_levels: list[LiquidityLevel] = []
        self.sweeps: list[LiquiditySweep] = []
        self.swing_lookback = config.swing_lookback
        self.equal_tolerance = config.equal_level_tolerance_pips * config.pip_value

    def detect_liquidity_levels(
        self, df: pd.DataFrame, pdh: float, pdl: float
    ) -> list[LiquidityLevel]:
        """Detect all liquidity levels from price data."""
        self.liquidity_levels = []

        # Previous Day High/Low
        if pdh > 0:
            self.liquidity_levels.append(
                LiquidityLevel(
                    price=pdh,
                    liquidity_type=LiquidityType.BUY_SIDE,
                    source="PDH",
                )
            )
        if pdl > 0:
            self.liquidity_levels.append(
                LiquidityLevel(
                    price=pdl,
                    liquidity_type=LiquidityType.SELL_SIDE,
                    source="PDL",
                )
            )

        # Swing Highs and Lows
        swing_highs = self._detect_swing_highs(df)
        swing_lows = self._detect_swing_lows(df)

        for sh in swing_highs:
            self.liquidity_levels.append(
                LiquidityLevel(
                    price=sh["price"],
                    liquidity_type=LiquidityType.BUY_SIDE,
                    source="SWING_HIGH",
                    timestamp=sh["time"],
                )
            )

        for sl in swing_lows:
            self.liquidity_levels.append(
                LiquidityLevel(
                    price=sl["price"],
                    liquidity_type=LiquidityType.SELL_SIDE,
                    source="SWING_LOW",
                    timestamp=sl["time"],
                )
            )

        # Equal Highs and Lows
        equal_highs = self._detect_equal_levels(df, "high")
        equal_lows = self._detect_equal_levels(df, "low")

        for eh in equal_highs:
            self.liquidity_levels.append(
                LiquidityLevel(
                    price=eh["price"],
                    liquidity_type=LiquidityType.BUY_SIDE,
                    source="EQUAL_HIGH",
                    timestamp=eh["time"],
                )
            )

        for el in equal_lows:
            self.liquidity_levels.append(
                LiquidityLevel(
                    price=el["price"],
                    liquidity_type=LiquidityType.SELL_SIDE,
                    source="EQUAL_LOW",
                    timestamp=el["time"],
                )
            )

        return self.liquidity_levels

    def detect_sweep(self, df: pd.DataFrame) -> LiquiditySweep | None:
        """Detect if a liquidity sweep has occurred on the latest candles."""
        if len(df) < 3 or not self.liquidity_levels:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # Check buy-side sweep (price goes above level then rejects)
        for level in self.liquidity_levels:
            if level.swept:
                continue

            if level.liquidity_type == LiquidityType.BUY_SIDE:
                # Price exceeded the level and then closed below it (rejection)
                if latest["high"] > level.price and latest["close"] < level.price:
                    level.swept = True
                    level.sweep_time = latest.get("timestamp", datetime.now())
                    sweep = LiquiditySweep(
                        direction=LiquidityType.BUY_SIDE,
                        sweep_price=latest["high"],
                        sweep_time=latest.get("timestamp", datetime.now()),
                        level_swept=level.price,
                        rejection=True,
                    )
                    self.sweeps.append(sweep)
                    logger.info(
                        f"BUY-SIDE SWEEP detected | Level: {level.price} | "
                        f"High: {latest['high']} | Source: {level.source}"
                    )
                    return sweep

            elif level.liquidity_type == LiquidityType.SELL_SIDE:
                # Price went below the level and then closed above it (rejection)
                if latest["low"] < level.price and latest["close"] > level.price:
                    level.swept = True
                    level.sweep_time = latest.get("timestamp", datetime.now())
                    sweep = LiquiditySweep(
                        direction=LiquidityType.SELL_SIDE,
                        sweep_price=latest["low"],
                        sweep_time=latest.get("timestamp", datetime.now()),
                        level_swept=level.price,
                        rejection=True,
                    )
                    self.sweeps.append(sweep)
                    logger.info(
                        f"SELL-SIDE SWEEP detected | Level: {level.price} | "
                        f"Low: {latest['low']} | Source: {level.source}"
                    )
                    return sweep

        return None

    def get_latest_sweep(self, direction: LiquidityType | None = None) -> LiquiditySweep | None:
        """Get the most recent sweep, optionally filtered by direction."""
        if not self.sweeps:
            return None
        if direction is None:
            return self.sweeps[-1]
        filtered = [s for s in self.sweeps if s.direction == direction]
        return filtered[-1] if filtered else None

    def _detect_swing_highs(self, df: pd.DataFrame) -> list[dict]:
        """Detect swing highs using lookback period."""
        swing_highs = []
        lookback = self.swing_lookback

        if len(df) < lookback * 2 + 1:
            return swing_highs

        highs = df["high"].values
        for i in range(lookback, len(highs) - lookback):
            is_swing = True
            for j in range(1, lookback + 1):
                if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                    is_swing = False
                    break
            if is_swing:
                swing_highs.append({
                    "price": highs[i],
                    "time": df.iloc[i].get("timestamp", None),
                    "index": i,
                })

        return swing_highs[-5:]  # Keep last 5

    def _detect_swing_lows(self, df: pd.DataFrame) -> list[dict]:
        """Detect swing lows using lookback period."""
        swing_lows = []
        lookback = self.swing_lookback

        if len(df) < lookback * 2 + 1:
            return swing_lows

        lows = df["low"].values
        for i in range(lookback, len(lows) - lookback):
            is_swing = True
            for j in range(1, lookback + 1):
                if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                    is_swing = False
                    break
            if is_swing:
                swing_lows.append({
                    "price": lows[i],
                    "time": df.iloc[i].get("timestamp", None),
                    "index": i,
                })

        return swing_lows[-5:]  # Keep last 5

    def _detect_equal_levels(self, df: pd.DataFrame, col: str) -> list[dict]:
        """Detect equal highs or equal lows within tolerance."""
        equal_levels = []
        values = df[col].values

        if len(values) < 10:
            return equal_levels

        for i in range(len(values) - 5, max(0, len(values) - 50), -1):
            for j in range(i - 1, max(0, i - 20), -1):
                if abs(values[i] - values[j]) <= self.equal_tolerance:
                    equal_levels.append({
                        "price": (values[i] + values[j]) / 2,
                        "time": df.iloc[i].get("timestamp", None),
                    })
                    break
            if len(equal_levels) >= 3:
                break

        return equal_levels

    def reset(self) -> None:
        """Reset all liquidity data for new session."""
        self.liquidity_levels = []
        self.sweeps = []
