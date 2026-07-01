"""Daily Bias Engine - ICT 2022."""

from loguru import logger

from core.data_models import Direction, LiquiditySweep, LiquidityType, MarketStructureShift


class BiasEngine:
    """Determines daily directional bias using ICT 2022 concepts."""

    def __init__(self) -> None:
        self.current_bias: Direction = Direction.NEUTRAL
        self.bias_reason: str = ""
        self.bias_confirmed: bool = False

    def determine_bias(
        self,
        pdh: float,
        pdl: float,
        current_high: float,
        current_low: float,
        latest_sweep: LiquiditySweep | None,
        latest_mss: MarketStructureShift | None,
    ) -> Direction:
        """
        Determine daily bias.

        Bullish: PDL taken + Sell-side sweep + Bullish MSS + Displacement up
        Bearish: PDH taken + Buy-side sweep + Bearish MSS + Displacement down
        """
        # Check for bullish bias
        bullish_conditions = self._check_bullish_bias(
            pdl, current_low, latest_sweep, latest_mss
        )

        # Check for bearish bias
        bearish_conditions = self._check_bearish_bias(
            pdh, current_high, latest_sweep, latest_mss
        )

        if bullish_conditions:
            self.current_bias = Direction.BULLISH
            self.bias_confirmed = True
            self.bias_reason = "PDL taken + Sell-side sweep + Bullish MSS"
            logger.info(f"DAILY BIAS: BULLISH | {self.bias_reason}")
        elif bearish_conditions:
            self.current_bias = Direction.BEARISH
            self.bias_confirmed = True
            self.bias_reason = "PDH taken + Buy-side sweep + Bearish MSS"
            logger.info(f"DAILY BIAS: BEARISH | {self.bias_reason}")
        else:
            # Keep previous bias if no new confirmation
            if not self.bias_confirmed:
                self.current_bias = Direction.NEUTRAL

        return self.current_bias

    def _check_bullish_bias(
        self,
        pdl: float,
        current_low: float,
        sweep: LiquiditySweep | None,
        mss: MarketStructureShift | None,
    ) -> bool:
        """Check all conditions for bullish bias."""
        # PDL must be taken
        pdl_taken = current_low < pdl if pdl > 0 else False

        # Sell-side liquidity must be swept
        sell_side_swept = (
            sweep is not None and sweep.direction == LiquidityType.SELL_SIDE
        )

        # Bullish MSS must be confirmed
        bullish_mss = mss is not None and mss.direction == Direction.BULLISH

        return pdl_taken and sell_side_swept and bullish_mss

    def _check_bearish_bias(
        self,
        pdh: float,
        current_high: float,
        sweep: LiquiditySweep | None,
        mss: MarketStructureShift | None,
    ) -> bool:
        """Check all conditions for bearish bias."""
        # PDH must be taken
        pdh_taken = current_high > pdh if pdh > 0 else False

        # Buy-side liquidity must be swept
        buy_side_swept = (
            sweep is not None and sweep.direction == LiquidityType.BUY_SIDE
        )

        # Bearish MSS must be confirmed
        bearish_mss = mss is not None and mss.direction == Direction.BEARISH

        return pdh_taken and buy_side_swept and bearish_mss

    def reset(self) -> None:
        """Reset bias for new session."""
        self.current_bias = Direction.NEUTRAL
        self.bias_reason = ""
        self.bias_confirmed = False
