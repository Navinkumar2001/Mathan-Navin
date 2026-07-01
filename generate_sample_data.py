"""Generate sample OHLC data for backtesting when no real data is available."""

import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def generate_forex_data(
    symbol: str = "EURUSD",
    days: int = 30,
    timeframe_minutes: int = 5,
    start_price: float = 1.0800,
    volatility: float = 0.0003,
    output_path: str = "data/sample_eurusd_m5.csv",
) -> pd.DataFrame:
    """
    Generate realistic synthetic forex OHLC data with market microstructure.

    Creates data with:
    - Trending behavior (trends last 20-100 candles)
    - Session-based volatility (higher during NY/London overlap)
    - Liquidity sweeps (engineered spikes past recent highs/lows)
    - Mean reversion
    """
    random.seed(42)
    np.random.seed(42)

    candles_per_day = (24 * 60) // timeframe_minutes
    total_candles = days * candles_per_day

    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []

    current_price = start_price
    trend_direction = 1  # 1 for up, -1 for down
    trend_strength = 0.0001
    trend_duration = random.randint(30, 80)
    trend_counter = 0

    start_time = datetime(2024, 1, 2, 0, 0)

    for i in range(total_candles):
        timestamp = start_time + timedelta(minutes=i * timeframe_minutes)

        # Skip weekends
        if timestamp.weekday() >= 5:
            continue

        # Session-based volatility multiplier
        hour = timestamp.hour
        if 8 <= hour <= 12:  # NY morning / London overlap
            vol_mult = 1.5
        elif 13 <= hour <= 16:  # NY afternoon
            vol_mult = 1.2
        elif 2 <= hour <= 7:  # London / Asian overlap
            vol_mult = 1.0
        else:  # Asian / quiet
            vol_mult = 0.6

        # Trend management
        trend_counter += 1
        if trend_counter >= trend_duration:
            trend_direction *= -1
            trend_strength = random.uniform(0.00005, 0.00020)
            trend_duration = random.randint(30, 100)
            trend_counter = 0

        # Generate candle
        drift = trend_direction * trend_strength
        noise = np.random.normal(0, volatility * vol_mult)

        open_price = current_price
        body = drift + noise
        close_price = open_price + body

        # Wicks
        upper_wick = abs(np.random.normal(0, volatility * vol_mult * 0.5))
        lower_wick = abs(np.random.normal(0, volatility * vol_mult * 0.5))

        high_price = max(open_price, close_price) + upper_wick
        low_price = min(open_price, close_price) - lower_wick

        # Occasional liquidity sweep spikes (2% chance)
        if random.random() < 0.02:
            spike = volatility * vol_mult * random.uniform(3, 6)
            if random.random() < 0.5:
                high_price += spike  # Buy-side sweep
                close_price = open_price - abs(noise)  # Reject back down
            else:
                low_price -= spike  # Sell-side sweep
                close_price = open_price + abs(noise)  # Reject back up

        # Occasional displacement candles (1.5% chance)
        if random.random() < 0.015:
            displacement = volatility * vol_mult * random.uniform(5, 10)
            if trend_direction > 0:
                close_price = open_price + displacement
                high_price = close_price + upper_wick * 0.3
            else:
                close_price = open_price - displacement
                low_price = close_price - lower_wick * 0.3

        timestamps.append(timestamp)
        opens.append(round(open_price, 5))
        highs.append(round(high_price, 5))
        lows.append(round(low_price, 5))
        closes.append(round(close_price, 5))

        current_price = close_price

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": np.random.randint(100, 5000, size=len(timestamps)),
    })

    # Save
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    print(f"Generated {len(df)} candles -> {output}")
    print(f"Date range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
    print(f"Price range: {df['low'].min():.5f} to {df['high'].max():.5f}")

    return df


if __name__ == "__main__":
    generate_forex_data()
