"""Backtesting Engine - Simulates ICT 2022 strategy on historical data."""

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import TradingConfig
from core.sheets_logger import SheetsLogger
from core.data_models import (
    Direction,
    ExitReason,
    LiquidityType,
    MarketState,
    TradeRecord,
)
from core.risk_manager import RiskManager
from core.session_manager import SessionManager
from core.trade_engine import TradeEngine
from strategies.bias_engine import BiasEngine
from strategies.fvg_engine import FVGEngine
from strategies.liquidity_engine import LiquidityEngine
from strategies.orderblock_engine import OrderBlockEngine
from strategies.structure_engine import StructureEngine


class BacktestEngine:
    """
    Backtesting engine that replays historical data through the ICT strategy.

    Supports CSV input with OHLC data. Simulates session timing, all ICT detections,
    trade execution, and risk management exactly as the live engine would.
    """

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.session_manager = SessionManager(config)
        self.risk_manager = RiskManager(config)
        self.trade_engine = TradeEngine(config, self.risk_manager)
        self.liquidity_engine = LiquidityEngine(config)
        self.structure_engine = StructureEngine(config)
        self.fvg_engine = FVGEngine(config)
        self.ob_engine = OrderBlockEngine(config)
        self.bias_engine = BiasEngine()
        self.sheets_logger = SheetsLogger(config)

        # Backtest state
        self.initial_balance: float = 10000.0
        self.current_balance: float = self.initial_balance
        self.equity_curve: list[float] = []
        self.all_trades: list[TradeRecord] = []
        self.daily_results: dict[str, float] = {}

    def load_data(self, csv_path: str | Path) -> pd.DataFrame:
        """
        Load historical OHLC data from CSV.

        Expected columns: timestamp (or time/date), open, high, low, close
        Optional: volume, tick_volume
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Data file not found: {path}")

        df = pd.read_csv(path)

        # Normalize column names
        df.columns = df.columns.str.lower().str.strip()

        # Handle various timestamp column names
        time_cols = ["timestamp", "time", "date", "datetime"]
        time_col = None
        for col in time_cols:
            if col in df.columns:
                time_col = col
                break

        if time_col is None:
            raise ValueError(f"No timestamp column found. Expected one of: {time_cols}")

        df["timestamp"] = pd.to_datetime(df[time_col])
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Ensure required columns
        required = ["open", "high", "low", "close"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        logger.info(
            f"Loaded {len(df)} candles from {path.name} | "
            f"Range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}"
        )
        return df

    def run(self, data: pd.DataFrame, initial_balance: float = 10000.0) -> dict[str, Any]:
        """
        Run backtest on historical data.

        Processes each candle sequentially, simulating the full ICT workflow:
        1. Update session data
        2. Detect liquidity levels
        3. Check for sweeps
        4. Detect MSS
        5. Detect FVGs
        6. Detect Order Blocks
        7. Determine bias
        8. Evaluate trade setups
        9. Manage active trades
        """
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.equity_curve = [initial_balance]
        self.all_trades = []

        logger.info(
            f"=== BACKTEST START === | Symbol: {self.config.symbol} | "
            f"Balance: ${initial_balance} | Candles: {len(data)}"
        )

        # Process previous day data from first day
        current_day = None
        day_high = 0.0
        day_low = float("inf")

        window_size = 50  # Minimum candles for analysis

        for i in range(window_size, len(data)):
            candle = data.iloc[i]
            candle_time = candle["timestamp"]

            # Handle day transitions
            candle_date = candle_time.strftime("%Y-%m-%d") if isinstance(candle_time, datetime) else str(candle_time)[:10]

            if current_day is None:
                current_day = candle_date
                day_high = candle["high"]
                day_low = candle["low"]
            elif candle_date != current_day:
                # New day - set previous day data
                self.session_manager.set_previous_day_data(day_high, day_low, data.iloc[i - 1]["close"])
                self.risk_manager.reset_daily()
                self.liquidity_engine.reset()
                self.bias_engine.reset()
                current_day = candle_date
                day_high = candle["high"]
                day_low = candle["low"]
            else:
                day_high = max(day_high, candle["high"])
                day_low = min(day_low, candle["low"])

            # Determine IST time from candle timestamp for session checks
            # If data has timezone-aware timestamps, convert; otherwise assume UTC
            if isinstance(candle_time, datetime):
                if candle_time.tzinfo is None:
                    import pytz
                    utc_time = pytz.utc.localize(candle_time)
                else:
                    utc_time = candle_time
            else:
                import pytz
                utc_time = pytz.utc.localize(pd.Timestamp(candle_time).to_pydatetime())

            # Update session manager with proper UTC time for IST conversion
            self.session_manager.update_session_data(
                {
                    "high": candle["high"],
                    "low": candle["low"],
                    "open": candle["open"],
                    "close": candle["close"],
                },
                utc_time=utc_time,
            )

            # Get window of data for analysis
            window = data.iloc[max(0, i - window_size):i + 1].copy()

            # Use IST-based session checks
            is_observation = self.session_manager.is_observation_session(utc_time)
            is_trading = self.session_manager.is_trading_session(utc_time)

            # During observation: detect ICT structures for confluence
            if is_observation:
                self.liquidity_engine.detect_liquidity_levels(
                    window,
                    self.session_manager.previous_day_high,
                    self.session_manager.previous_day_low,
                )
                sweep = self.liquidity_engine.detect_sweep(window)
                latest_sweep = self.liquidity_engine.get_latest_sweep()
                if latest_sweep:
                    mss = self.structure_engine.detect_mss(window, latest_sweep)
                fvg = self.fvg_engine.detect_fvg(window)
                latest_mss = self.structure_engine.get_latest_mss()
                ob = self.ob_engine.detect_order_block(window, latest_sweep, latest_mss)

                self.bias_engine.determine_bias(
                    self.session_manager.previous_day_high,
                    self.session_manager.previous_day_low,
                    self.session_manager.session_high,
                    self.session_manager.session_low,
                    latest_sweep,
                    latest_mss,
                )

            # Step: Manage active trade (any time)
            if self.trade_engine.has_active_trade:
                closed = self.trade_engine.manage_trade(candle["close"], candle_time)
                if closed:
                    self._record_backtest_trade(closed)

                # Session end exit (IST 23:25+)
                if self.session_manager.is_session_end(utc_time) and self.config.session_close_exit:
                    closed = self.trade_engine.session_exit(candle["close"], candle_time)
                    if closed:
                        self._record_backtest_trade(closed)

            # During trading session: check for range breakout re-entry
            elif is_trading and not self.trade_engine.has_active_trade:
                current_price = candle["close"]

                # PRIMARY: Range breakout re-entry signal
                signal = self.session_manager.check_range_breakout_reentry(current_price)

                if signal:
                    session_low = self.session_manager.session_low
                    if session_low == float("inf"):
                        session_low = 0

                    setup = self.trade_engine.evaluate_range_reentry(
                        signal=signal,
                        current_price=current_price,
                        session_high=self.session_manager.session_high,
                        session_low=session_low,
                        is_trading_session=True,
                    )

                    if setup and setup.valid:
                        trade = self.trade_engine.execute_trade(setup, self.current_balance)
                        if trade:
                            trade.entry_time = candle_time

            # Update equity curve
            self.equity_curve.append(self.current_balance)

            # Log market state
            bias = self.bias_engine.current_bias
            latest_sweep = self.liquidity_engine.get_latest_sweep()
            latest_mss = self.structure_engine.get_latest_mss()
            fvg = self.fvg_engine.get_latest_fvg(bias)
            ob = self.ob_engine.get_latest_ob(bias)
            self._log_state(candle, bias, latest_sweep, latest_mss, fvg, ob)

        # Close any remaining trade
        if self.trade_engine.has_active_trade:
            last_candle = data.iloc[-1]
            closed = self.trade_engine.session_exit(
                last_candle["close"], last_candle["timestamp"]
            )
            if closed:
                self._record_backtest_trade(closed)

        # Generate report
        report = self.generate_report()
        logger.info(f"=== BACKTEST COMPLETE === | Trades: {report['total_trades']}")
        return report

    def _record_backtest_trade(self, trade: TradeRecord) -> None:
        """Record a completed backtest trade and update balance."""
        # Approximate P/L in account currency
        pnl_pips = trade.profit_loss
        # Simple P/L calculation: pips * lot_size * pip_value_in_currency
        pnl_currency = pnl_pips * trade.lot_size * 10  # $10 per pip per lot for EURUSD
        self.current_balance += pnl_currency
        trade.profit_loss = pnl_currency
        trade.profit_loss_percent = (pnl_currency / self.initial_balance) * 100

        self.all_trades.append(trade)
        self.sheets_logger.log_trade(trade)

    def _log_state(
        self, candle: Any, bias: Direction, sweep: Any, mss: Any, fvg: Any, ob: Any
    ) -> None:
        """Log current market state to CSV."""
        state = MarketState(
            timestamp=candle.get("timestamp", datetime.now()) if isinstance(candle, dict) else candle["timestamp"],
            symbol=self.config.symbol,
            open=candle["open"],
            high=candle["high"],
            low=candle["low"],
            close=candle["close"],
            session_high=self.session_manager.session_high,
            session_low=self.session_manager.session_low if self.session_manager.session_low != float("inf") else 0,
            session_midpoint=self.session_manager.session_midpoint,
            daily_bias=bias.value,
            sweep_detected=sweep is not None,
            sweep_type=sweep.direction.value if sweep else "",
            mss_detected=mss is not None,
            mss_direction=mss.direction.value if mss else "",
            fvg_detected=fvg is not None,
            fvg_top=fvg.top if fvg else 0,
            fvg_bottom=fvg.bottom if fvg else 0,
            ob_detected=ob is not None,
            ob_type=ob.direction.value if ob else "",
            entry_signal=self.trade_engine.current_setup is not None,
            current_trade_status="OPEN" if self.trade_engine.has_active_trade else "NONE",
        )
        self.sheets_logger.log_market_state(state)

    def generate_report(self) -> dict[str, Any]:
        """Generate comprehensive performance report."""
        if not self.all_trades:
            return {"total_trades": 0, "message": "No trades executed."}

        wins = [t for t in self.all_trades if t.trade_result == "WIN"]
        losses = [t for t in self.all_trades if t.trade_result == "LOSS"]

        total_profit = sum(t.profit_loss for t in wins)
        total_loss = abs(sum(t.profit_loss for t in losses))

        # Equity curve analysis
        equity = np.array(self.equity_curve)
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_drawdown = float(np.max(drawdown)) * 100 if len(drawdown) > 0 else 0

        # Sharpe ratio (simplified daily)
        returns = np.diff(equity) / equity[:-1]
        sharpe = 0.0
        if len(returns) > 0 and np.std(returns) > 0:
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252)

        # Profit factor
        profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

        # Average RR
        rrs = [t.risk_reward for t in self.all_trades if t.risk_reward > 0]
        avg_rr = sum(rrs) / len(rrs) if rrs else 0

        # Expectancy
        win_rate = len(wins) / len(self.all_trades) if self.all_trades else 0
        avg_win = total_profit / len(wins) if wins else 0
        avg_loss_val = total_loss / len(losses) if losses else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss_val)

        report = {
            "total_trades": len(self.all_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate * 100, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_percent": round(max_drawdown, 2),
            "average_rr": round(avg_rr, 2),
            "expectancy": round(expectancy, 2),
            "total_profit": round(total_profit, 2),
            "total_loss": round(total_loss, 2),
            "net_profit": round(total_profit - total_loss, 2),
            "initial_balance": self.initial_balance,
            "final_balance": round(self.current_balance, 2),
            "return_percent": round(((self.current_balance - self.initial_balance) / self.initial_balance) * 100, 2),
        }

        # Save report
        self._save_report(report)
        return report

    def _save_report(self, report: dict[str, Any]) -> None:
        """Save performance report to CSV."""
        report_path = Path("reports/performance_report.csv")
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Metric", "Value"])
            for key, value in report.items():
                writer.writerow([key, value])

        logger.info(f"Performance report saved to {report_path}")

        # Also save trade list
        trades_path = Path("reports/backtest_trades.csv")
        if self.all_trades:
            with open(trades_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.all_trades[0].to_dict().keys())
                writer.writeheader()
                for trade in self.all_trades:
                    writer.writerow(trade.to_dict())
            logger.info(f"Trade list saved to {trades_path}")
