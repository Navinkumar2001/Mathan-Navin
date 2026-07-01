"""
ICT 2022 Trading Bot - Backtest Runner

This is the main entry point for backtesting the ICT strategy on historical data.
Works on Linux without MetaTrader 5.

Usage:
    python main_backtest.py                    # Run with sample data
    python main_backtest.py --data path/to/data.csv  # Run with your own data
    python main_backtest.py --balance 50000    # Custom starting balance
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import TradingConfig
from backtests.backtest_engine import BacktestEngine
from charts.dashboard import TradingDashboard
from generate_sample_data import generate_forex_data


def setup_logging(level: str = "INFO") -> None:
    """Configure loguru logging."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level=level,
    )
    logger.add(
        "logs/backtest_{time:YYYY-MM-DD}.log",
        rotation="10 MB",
        retention="30 days",
        level="DEBUG",
    )


def print_report(report: dict) -> None:
    """Pretty print the backtest report."""
    print("\n" + "=" * 60)
    print("        ICT 2022 STRATEGY - BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Total Trades:        {report.get('total_trades', 0)}")
    print(f"  Wins:                {report.get('wins', 0)}")
    print(f"  Losses:              {report.get('losses', 0)}")
    print(f"  Win Rate:            {report.get('win_rate', 0):.1f}%")
    print(f"  Profit Factor:       {report.get('profit_factor', 0):.2f}")
    print(f"  Sharpe Ratio:        {report.get('sharpe_ratio', 0):.2f}")
    print(f"  Max Drawdown:        {report.get('max_drawdown_percent', 0):.2f}%")
    print(f"  Average R:R:         {report.get('average_rr', 0):.2f}")
    print(f"  Expectancy:          ${report.get('expectancy', 0):.2f}")
    print("-" * 60)
    print(f"  Initial Balance:     ${report.get('initial_balance', 0):,.2f}")
    print(f"  Final Balance:       ${report.get('final_balance', 0):,.2f}")
    print(f"  Net Profit:          ${report.get('net_profit', 0):,.2f}")
    print(f"  Return:              {report.get('return_percent', 0):.2f}%")
    print("=" * 60)
    print()


def main() -> None:
    """Main backtest execution."""
    parser = argparse.ArgumentParser(description="ICT 2022 Trading Bot - Backtester")
    parser.add_argument("--data", type=str, default=None, help="Path to CSV data file")
    parser.add_argument("--config", type=str, default="config/config.json", help="Path to config")
    parser.add_argument("--balance", type=float, default=10000.0, help="Starting balance")
    parser.add_argument("--symbol", type=str, default=None, help="Override symbol")
    parser.add_argument("--days", type=int, default=30, help="Days of sample data to generate")
    parser.add_argument("--no-chart", action="store_true", help="Skip chart generation")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")
    args = parser.parse_args()

    setup_logging(args.log_level)

    # Load config
    config_path = Path(args.config)
    if config_path.exists():
        config = TradingConfig.from_json(config_path)
        logger.info(f"Config loaded from {config_path}")
    else:
        config = TradingConfig()
        logger.info("Using default config")

    if args.symbol:
        config.symbol = args.symbol

    # Load or generate data
    if args.data:
        data_path = Path(args.data)
        if not data_path.exists():
            logger.error(f"Data file not found: {data_path}")
            sys.exit(1)
    else:
        logger.info(f"No data file specified. Generating {args.days} days of sample data...")
        data_path = Path("data/sample_eurusd_m5.csv")
        generate_forex_data(
            symbol=config.symbol,
            days=args.days,
            output_path=str(data_path),
        )

    # Initialize and run backtest
    engine = BacktestEngine(config)
    data = engine.load_data(data_path)

    logger.info("Starting backtest...")
    report = engine.run(data, initial_balance=args.balance)

    # Print results
    print_report(report)

    # Generate charts
    if not args.no_chart and report.get("total_trades", 0) > 0:
        logger.info("Generating charts...")
        dashboard = TradingDashboard(symbol=config.symbol)

        # Prepare FVG/OB zones for chart
        fvg_zones = [
            {"top": f.top, "bottom": f.bottom, "direction": f.direction.value}
            for f in engine.fvg_engine.fvg_list[-30:]
        ]
        ob_zones = [
            {"high": ob.high, "low": ob.low, "direction": ob.direction.value}
            for ob in engine.ob_engine.order_blocks[-20:]
        ]
        sweep_data = [
            {"time": s.sweep_time, "price": s.sweep_price, "direction": s.direction.value}
            for s in engine.liquidity_engine.sweeps[-20:]
        ]

        dashboard.create_backtest_chart(
            data=data,
            trades=engine.all_trades,
            fvg_zones=fvg_zones,
            ob_zones=ob_zones,
            sweeps=sweep_data,
            session_high=engine.session_manager.session_high,
            session_low=engine.session_manager.session_low if engine.session_manager.session_low != float("inf") else None,
        )

        dashboard.create_performance_summary(report)
        print("Charts saved to charts/ directory. Open the HTML files in your browser.")
    elif report.get("total_trades", 0) == 0:
        print("No trades were executed. Try adjusting parameters in config.json:")
        print("  - Lower min_displacement_pips")
        print("  - Lower min_fvg_size_pips")
        print("  - Increase data duration (--days)")

    print(f"\nOutput files:")
    print(f"  Market state:  {config.csv_market_state_path}")
    print(f"  Trade journal: {config.csv_trade_journal_path}")
    print(f"  Report:        reports/performance_report.csv")
    print(f"  Chart:         charts/backtest_chart.html")


if __name__ == "__main__":
    main()
