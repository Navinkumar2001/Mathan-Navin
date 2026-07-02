"""
ICT 2022 Trading Bot - Live Trading Runner (Windows + MetaTrader 5)

This connects to MT5, runs the ICT strategy in real-time, and executes trades.

REQUIREMENTS:
    - Windows OS with MetaTrader 5 installed and logged in
    - Python 3.10+
    - pip install MetaTrader5 pandas numpy pytz loguru python-dateutil

SETUP:
    1. Open MetaTrader 5 and log into your broker account
    2. Edit config/config.json with your MT5 credentials:
       - mt5_login: your account number
       - mt5_server: your broker server name
       - mt5_password: your account password
    3. Adjust symbol, risk, and session times in config.json

USAGE:
    python main_live.py                          # Run with default config
    python main_live.py --config config/config.json
    python main_live.py --symbol EURUSD
    python main_live.py --dry-run                # Paper trade (no real orders)
    python main_live.py --log-level DEBUG        # Verbose logging

NOTES:
    - Bot only trades during the configured NY session (default 08:30-15:00 ET)
    - Max 1 trade at a time (configurable)
    - Stops after max daily losses hit
    - Logs all market state and trades to CSV files in data/
    - Press Ctrl+C to stop gracefully
"""

import argparse
import signal
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pytz
from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import TradingConfig
from core.mt5_connector import MT5Connector
from core.risk_manager import RiskManager
from core.session_manager import SessionManager
from core.trade_engine import TradeEngine
from core.csv_logger import CSVLogger
from core.data_models import Direction, MarketState
from strategies.bias_engine import BiasEngine
from strategies.structure_engine import StructureEngine
from strategies.liquidity_engine import LiquidityEngine
from strategies.fvg_engine import FVGEngine
from strategies.orderblock_engine import OrderBlockEngine


class LiveTradingBot:
    """Main live trading orchestrator."""

    def __init__(self, config: TradingConfig, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self.running = False
        self.current_date: date | None = None

        # Core components
        self.mt5 = MT5Connector(config)
        self.risk_manager = RiskManager(config)
        self.session_manager = SessionManager(config)
        self.trade_engine = TradeEngine(config, self.risk_manager)
        self.csv_logger = CSVLogger(config)

        # Strategy engines
        self.bias_engine = BiasEngine()
        self.structure_engine = StructureEngine(config)
        self.liquidity_engine = LiquidityEngine(config)
        self.fvg_engine = FVGEngine(config)
        self.ob_engine = OrderBlockEngine(config)

        # State tracking
        self.last_candle_time: datetime | None = None
        self.account_balance: float = 0.0

    def start(self) -> None:
        """Start the live trading bot."""
        logger.info("=" * 60)
        logger.info("  ICT 2022 LIVE TRADING BOT")
        logger.info(f"  Symbol: {self.config.symbol}")
        logger.info(f"  Timeframe: {self.config.timeframe}")
        logger.info(f"  Risk: {self.config.risk_percent}% per trade")
        logger.info(f"  Reward Ratio: {self.config.reward_ratio}R")
        logger.info(f"  Dry Run: {self.dry_run}")
        logger.info("=" * 60)

        # Connect to MT5
        if not self.mt5.connect():
            logger.critical("Failed to connect to MetaTrader 5. Exiting.")
            sys.exit(1)

        # Get account info
        account = self.mt5.get_account_info()
        if account:
            self.account_balance = account["balance"]
            logger.info(
                f"Account: {account['login']} | Balance: ${account['balance']:,.2f} | "
                f"Leverage: 1:{account['leverage']}"
            )
        else:
            logger.critical("Cannot retrieve account info. Exiting.")
            self.mt5.disconnect()
            sys.exit(1)

        # Load previous day data from D1 candle
        self._load_previous_day_data()

        self.running = True
        logger.info("Bot started. Waiting for trading signals...")
        logger.info(f"Trading session: {self.config.trading_start_ny} - {self.config.trading_end_ny} NY time")

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("Shutdown requested by user (Ctrl+C).")
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
        finally:
            self._shutdown()

    def _main_loop(self) -> None:
        """Main trading loop - runs every candle interval."""
        # Calculate sleep interval based on timeframe
        tf_seconds = self._timeframe_to_seconds(self.config.timeframe)
        poll_interval = min(tf_seconds, 30)  # Poll at most every 30 seconds

        while self.running:
            try:
                # Ensure MT5 connection
                if not self.mt5.ensure_connection():
                    logger.error("Lost MT5 connection. Retrying in 60s...")
                    time.sleep(60)
                    continue

                # Check for new day -> reset daily counters
                self._check_new_day()

                # Get current session state
                ny_time = self.session_manager.get_ny_time()
                is_observation = self.session_manager.is_observation_session()
                is_trading = self.session_manager.is_trading_session()
                is_session_end = self.session_manager.is_session_end()

                # Get latest candles
                df = self.mt5.get_candles(count=200)
                if df.empty:
                    time.sleep(poll_interval)
                    continue

                # Check if we have a new candle
                latest_time = df.iloc[-1]["timestamp"]
                if self.last_candle_time == latest_time:
                    # No new candle yet, just manage existing trade
                    if self.trade_engine.has_active_trade:
                        tick = self.mt5.get_current_tick()
                        if tick:
                            current_price = tick["bid"]
                            closed = self.trade_engine.manage_trade(current_price, datetime.now(pytz.utc))
                            if closed:
                                self._on_trade_closed(closed)
                    time.sleep(poll_interval)
                    continue

                self.last_candle_time = latest_time

                # Update session data
                latest_candle = df.iloc[-1].to_dict()
                self.session_manager.update_session_data(latest_candle)
                current_price = latest_candle["close"]

                # Log current state
                logger.debug(
                    f"NY: {ny_time.strftime('%H:%M')} | Price: {current_price:.5f} | "
                    f"Obs: {is_observation} | Trading: {is_trading}"
                )

                # --- OBSERVATION PHASE ---
                if is_observation:
                    self._run_observation(df, current_price)

                # --- TRADING PHASE ---
                if is_trading:
                    self._run_trading(df, current_price, ny_time)

                # --- SESSION END ---
                if is_session_end and self.config.session_close_exit:
                    if self.trade_engine.has_active_trade:
                        logger.info("Session ending - closing active trade.")
                        closed = self.trade_engine.session_exit(current_price, datetime.now(pytz.utc))
                        if closed:
                            self._on_trade_closed(closed)
                            if not self.dry_run:
                                self._close_mt5_position()

                # Log market state to CSV
                self._log_market_state(latest_candle, ny_time)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(poll_interval)

            time.sleep(poll_interval)

    def _run_observation(self, df, current_price: float) -> None:
        """Run observation phase analysis (pre-market)."""
        # Detect liquidity levels
        self.liquidity_engine.detect_liquidity_levels(
            df,
            pdh=self.session_manager.previous_day_high,
            pdl=self.session_manager.previous_day_low,
        )

        # Detect sweeps
        sweep = self.liquidity_engine.detect_sweep(df)

        # Detect MSS
        if sweep:
            mss = self.structure_engine.detect_mss(df, sweep)

        # Detect FVGs
        self.fvg_engine.detect_fvg(df)

        # Update bias
        latest_sweep = self.liquidity_engine.get_latest_sweep()
        latest_mss = self.structure_engine.get_latest_mss()

        self.bias_engine.determine_bias(
            pdh=self.session_manager.previous_day_high,
            pdl=self.session_manager.previous_day_low,
            current_high=self.session_manager.session_high,
            current_low=self.session_manager.session_low if self.session_manager.session_low != float("inf") else 0,
            latest_sweep=latest_sweep,
            latest_mss=latest_mss,
        )

    def _run_trading(self, df, current_price: float, ny_time) -> None:
        """Run trading phase - look for entries and manage positions."""
        # Manage existing trade
        if self.trade_engine.has_active_trade:
            closed = self.trade_engine.manage_trade(current_price, datetime.now(pytz.utc))
            if closed:
                self._on_trade_closed(closed)
                if not self.dry_run:
                    self._close_mt5_position()
            return

        # Check spread
        tick = self.mt5.get_current_tick()
        if tick and not self.risk_manager.check_spread(tick["spread"]):
            return

        # Run strategy detection on latest data
        sweep = self.liquidity_engine.detect_sweep(df)
        latest_sweep = self.liquidity_engine.get_latest_sweep()

        if latest_sweep:
            mss = self.structure_engine.detect_mss(df, latest_sweep)

        latest_mss = self.structure_engine.get_latest_mss()

        # Detect FVG and OB
        fvg = self.fvg_engine.detect_fvg(df)
        latest_fvg = self.fvg_engine.get_latest_fvg(self.bias_engine.current_bias)

        ob = self.ob_engine.detect_order_block(df, latest_sweep, latest_mss)
        latest_ob = self.ob_engine.get_latest_ob(self.bias_engine.current_bias)

        # Check for retracement into FVG/OB
        if latest_fvg is None:
            latest_fvg = self.fvg_engine.check_retracement_into_fvg(
                current_price, self.bias_engine.current_bias
            )
        if latest_ob is None:
            latest_ob = self.ob_engine.check_retracement_into_ob(
                current_price, self.bias_engine.current_bias
            )

        # Update bias
        self.bias_engine.determine_bias(
            pdh=self.session_manager.previous_day_high,
            pdl=self.session_manager.previous_day_low,
            current_high=self.session_manager.session_high,
            current_low=self.session_manager.session_low if self.session_manager.session_low != float("inf") else 0,
            latest_sweep=latest_sweep,
            latest_mss=latest_mss,
        )

        # Evaluate trade setup
        setup = self.trade_engine.evaluate_setup(
            bias=self.bias_engine.current_bias,
            sweep=latest_sweep,
            mss=latest_mss,
            fvg=latest_fvg,
            ob=latest_ob,
            current_price=current_price,
            is_trading_session=True,
        )

        # Execute trade if valid setup found
        if setup and setup.valid:
            # Refresh account balance
            account = self.mt5.get_account_info()
            if account:
                self.account_balance = account["balance"]

            trade = self.trade_engine.execute_trade(setup, self.account_balance)
            if trade:
                logger.info(f"{'[DRY RUN] ' if self.dry_run else ''}TRADE SIGNAL EXECUTED!")
                if not self.dry_run:
                    self._place_mt5_order(trade)
                self.csv_logger.log_trade(trade)

    def _place_mt5_order(self, trade) -> None:
        """Place actual order on MT5."""
        tick = self.mt5.get_current_tick()
        if not tick:
            logger.error("Cannot get tick for order placement.")
            return

        price = tick["ask"] if trade.trade_type == "BUY" else tick["bid"]

        result = self.mt5.place_order(
            order_type=trade.trade_type,
            volume=trade.lot_size,
            price=price,
            sl=trade.stop_loss,
            tp=trade.take_profit,
            comment=f"ICT_{trade.trade_id}",
        )

        if result:
            trade.ticket = result["ticket"]
            logger.info(f"MT5 Order placed | Ticket: {result['ticket']}")
        else:
            logger.error("MT5 Order FAILED - trade recorded but not executed on broker.")

    def _close_mt5_position(self) -> None:
        """Close any open MT5 positions for this bot."""
        positions = self.mt5.get_open_positions()
        for pos in positions:
            self.mt5.close_position(pos["ticket"], comment="ICT_BOT_EXIT")

    def _on_trade_closed(self, trade) -> None:
        """Handle trade close event."""
        logger.info(
            f"Trade closed | {trade.trade_result} | P/L: {trade.profit_loss:.1f} pips | "
            f"Reason: {trade.exit_reason}"
        )
        self.csv_logger.log_trade(trade)

        # Update account balance
        account = self.mt5.get_account_info()
        if account:
            self.account_balance = account["balance"]

    def _load_previous_day_data(self) -> None:
        """Load previous day high/low/close from MT5 D1 candle."""
        import MetaTrader5 as mt5

        rates = mt5.copy_rates_from_pos(self.config.symbol, mt5.TIMEFRAME_D1, 1, 1)
        if rates is not None and len(rates) > 0:
            prev_day = rates[0]
            self.session_manager.set_previous_day_data(
                high=prev_day["high"],
                low=prev_day["low"],
                close=prev_day["close"],
            )
            logger.info(
                f"Previous day loaded | H: {prev_day['high']:.5f} | "
                f"L: {prev_day['low']:.5f} | C: {prev_day['close']:.5f}"
            )
        else:
            logger.warning("Could not load previous day data from MT5.")

    def _check_new_day(self) -> None:
        """Reset daily counters on new trading day."""
        today = date.today()
        if self.current_date != today:
            if self.current_date is not None:
                logger.info(f"New trading day: {today}")
                self.risk_manager.reset_daily()
                self.bias_engine.reset()
                self.structure_engine.reset()
                self.liquidity_engine.reset()
                self.fvg_engine.reset()
                self.ob_engine.reset()
                self.csv_logger.reset_market_state()
                self._load_previous_day_data()
            self.current_date = today

    def _log_market_state(self, candle: dict, ny_time) -> None:
        """Log current market state to CSV."""
        tick = self.mt5.get_current_tick()
        state = MarketState(
            timestamp=datetime.now(pytz.utc),
            ny_time=ny_time.strftime("%Y-%m-%d %H:%M:%S"),
            ist_time=self.session_manager.get_ist_time().strftime("%Y-%m-%d %H:%M:%S"),
            symbol=self.config.symbol,
            open=candle.get("open", 0),
            high=candle.get("high", 0),
            low=candle.get("low", 0),
            close=candle.get("close", 0),
            bid=tick["bid"] if tick else 0,
            ask=tick["ask"] if tick else 0,
            spread=tick["spread"] if tick else 0,
            session_high=self.session_manager.session_high,
            session_low=self.session_manager.session_low if self.session_manager.session_low != float("inf") else 0,
            session_midpoint=self.session_manager.session_midpoint,
            daily_bias=self.bias_engine.current_bias.value,
            sweep_detected=len(self.liquidity_engine.sweeps) > 0,
            sweep_type=self.liquidity_engine.sweeps[-1].direction.value if self.liquidity_engine.sweeps else "",
            mss_detected=len(self.structure_engine.mss_list) > 0,
            mss_direction=self.structure_engine.mss_list[-1].direction.value if self.structure_engine.mss_list else "",
            fvg_detected=len(self.fvg_engine.fvg_list) > 0,
            ob_detected=len(self.ob_engine.order_blocks) > 0,
            entry_signal=self.trade_engine.current_setup is not None,
            current_trade_status="OPEN" if self.trade_engine.has_active_trade else "NONE",
        )
        self.csv_logger.log_market_state(state)

    def _shutdown(self) -> None:
        """Graceful shutdown."""
        self.running = False
        logger.info("Shutting down...")

        # Close any open position if configured
        if self.trade_engine.has_active_trade and not self.dry_run:
            logger.info("Closing active trade before shutdown...")
            self._close_mt5_position()

        self.mt5.disconnect()
        logger.info("Bot stopped. Goodbye.")

    @staticmethod
    def _timeframe_to_seconds(tf: str) -> int:
        """Convert timeframe string to seconds."""
        mapping = {
            "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
            "H1": 3600, "H4": 14400, "D1": 86400,
        }
        return mapping.get(tf, 300)


def setup_logging(level: str = "INFO") -> None:
    """Configure loguru logging."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level=level,
    )
    logger.add(
        "logs/live_{time:YYYY-MM-DD}.log",
        rotation="10 MB",
        retention="30 days",
        level="DEBUG",
    )


def main() -> None:
    """Entry point for live trading."""
    parser = argparse.ArgumentParser(description="ICT 2022 Trading Bot - Live Trading")
    parser.add_argument("--config", type=str, default="config/config.json", help="Path to config file")
    parser.add_argument("--symbol", type=str, default=None, help="Override trading symbol")
    parser.add_argument("--dry-run", action="store_true", help="Paper trade mode (no real orders)")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level (DEBUG/INFO/WARNING)")
    args = parser.parse_args()

    setup_logging(args.log_level)

    # Load config
    config_path = Path(args.config)
    if config_path.exists():
        config = TradingConfig.from_json(config_path)
        logger.info(f"Config loaded from {config_path}")
    else:
        config = TradingConfig()
        logger.warning(f"Config not found at {config_path}, using defaults.")

    if args.symbol:
        config.symbol = args.symbol

    # Validate MT5 credentials
    if not args.dry_run and config.mt5_login == 0:
        logger.warning(
            "MT5 login not configured in config.json. "
            "Set mt5_login, mt5_server, mt5_password or use --dry-run."
        )

    # Register signal handler for graceful shutdown
    bot = LiveTradingBot(config, dry_run=args.dry_run)
    signal.signal(signal.SIGINT, lambda s, f: setattr(bot, "running", False))

    bot.start()


if __name__ == "__main__":
    main()
