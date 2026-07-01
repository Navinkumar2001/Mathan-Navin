"""Plotly Visualization Dashboard for ICT Trading Bot."""

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from loguru import logger


class TradingDashboard:
    """Generates interactive charts showing ICT analysis and trade results."""

    def __init__(self, symbol: str = "EURUSD") -> None:
        self.symbol = symbol

    def create_backtest_chart(
        self,
        data: pd.DataFrame,
        trades: list[Any],
        fvg_zones: list[dict] | None = None,
        ob_zones: list[dict] | None = None,
        sweeps: list[dict] | None = None,
        session_high: float | None = None,
        session_low: float | None = None,
        save_path: str = "charts/backtest_chart.html",
    ) -> go.Figure:
        """Create comprehensive backtest visualization chart."""
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[0.75, 0.25],
            subplot_titles=[f"{self.symbol} - ICT Analysis", "Equity Curve"],
        )

        # Candlestick chart
        fig.add_trace(
            go.Candlestick(
                x=data["timestamp"],
                open=data["open"],
                high=data["high"],
                low=data["low"],
                close=data["close"],
                name="Price",
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
            ),
            row=1, col=1,
        )

        # Session High/Low lines
        if session_high:
            fig.add_hline(
                y=session_high, line_dash="dash", line_color="blue",
                annotation_text="Session High", row=1, col=1,
            )
        if session_low:
            fig.add_hline(
                y=session_low, line_dash="dash", line_color="blue",
                annotation_text="Session Low", row=1, col=1,
            )

        # FVG zones
        if fvg_zones:
            for fvg in fvg_zones[-20:]:  # Last 20 FVGs
                color = "rgba(0, 255, 0, 0.1)" if fvg.get("direction") == "BULLISH" else "rgba(255, 0, 0, 0.1)"
                fig.add_hrect(
                    y0=fvg["bottom"], y1=fvg["top"],
                    fillcolor=color,
                    line_width=0,
                    annotation_text="FVG",
                    row=1, col=1,
                )

        # Order Block zones
        if ob_zones:
            for ob in ob_zones[-10:]:  # Last 10 OBs
                color = "rgba(0, 100, 255, 0.15)" if ob.get("direction") == "BULLISH" else "rgba(255, 100, 0, 0.15)"
                fig.add_hrect(
                    y0=ob["low"], y1=ob["high"],
                    fillcolor=color,
                    line_width=1,
                    line_color="rgba(100,100,100,0.3)",
                    annotation_text="OB",
                    row=1, col=1,
                )

        # Liquidity sweeps
        if sweeps:
            for s in sweeps[-15:]:
                marker_color = "red" if s.get("direction") == "BUY_SIDE" else "green"
                fig.add_trace(
                    go.Scatter(
                        x=[s.get("time")],
                        y=[s.get("price")],
                        mode="markers",
                        marker=dict(symbol="x", size=12, color=marker_color),
                        name=f"Sweep {s.get('direction', '')}",
                        showlegend=False,
                    ),
                    row=1, col=1,
                )

        # Trade entries and exits
        if trades:
            for trade in trades:
                # Entry marker
                entry_color = "lime" if trade.trade_type == "BUY" else "red"
                entry_symbol = "triangle-up" if trade.trade_type == "BUY" else "triangle-down"

                if trade.entry_time:
                    fig.add_trace(
                        go.Scatter(
                            x=[trade.entry_time],
                            y=[trade.entry_price],
                            mode="markers",
                            marker=dict(symbol=entry_symbol, size=14, color=entry_color),
                            name=f"Entry {trade.trade_type}",
                            showlegend=False,
                        ),
                        row=1, col=1,
                    )

                # Exit marker
                if trade.exit_time and trade.exit_price:
                    exit_color = "green" if trade.trade_result == "WIN" else "red"
                    fig.add_trace(
                        go.Scatter(
                            x=[trade.exit_time],
                            y=[trade.exit_price],
                            mode="markers",
                            marker=dict(symbol="square", size=10, color=exit_color),
                            name=f"Exit {trade.trade_result}",
                            showlegend=False,
                        ),
                        row=1, col=1,
                    )

                    # Line connecting entry to exit
                    fig.add_trace(
                        go.Scatter(
                            x=[trade.entry_time, trade.exit_time],
                            y=[trade.entry_price, trade.exit_price],
                            mode="lines",
                            line=dict(color=exit_color, width=1, dash="dot"),
                            showlegend=False,
                        ),
                        row=1, col=1,
                    )

        # Equity curve (subplot 2)
        if trades:
            balance = 10000.0
            equity_x = []
            equity_y = [balance]
            equity_x.append(data["timestamp"].iloc[0])

            for trade in trades:
                balance += trade.profit_loss
                if trade.exit_time:
                    equity_x.append(trade.exit_time)
                    equity_y.append(balance)

            fig.add_trace(
                go.Scatter(
                    x=equity_x,
                    y=equity_y,
                    mode="lines",
                    line=dict(color="cyan", width=2),
                    name="Equity",
                    fill="tozeroy",
                    fillcolor="rgba(0, 255, 255, 0.05)",
                ),
                row=2, col=1,
            )

        # Layout
        fig.update_layout(
            title=f"ICT 2022 Backtest - {self.symbol}",
            template="plotly_dark",
            height=900,
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend=dict(x=0, y=1.1, orientation="h"),
        )

        fig.update_xaxes(title_text="Time", row=2, col=1)
        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Balance ($)", row=2, col=1)

        # Save to HTML
        output_path = Path(save_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(output_path))
        logger.info(f"Chart saved to {output_path}")

        return fig

    def create_performance_summary(
        self, report: dict[str, Any], save_path: str = "charts/performance_summary.html"
    ) -> go.Figure:
        """Create a performance metrics summary visualization."""
        metrics = list(report.keys())
        values = list(report.values())

        fig = go.Figure()

        # Key metrics as indicator cards
        fig.add_trace(go.Indicator(
            mode="number+delta",
            value=report.get("win_rate", 0),
            title={"text": "Win Rate (%)"},
            domain={"x": [0, 0.25], "y": [0.6, 1.0]},
            number={"suffix": "%"},
        ))

        fig.add_trace(go.Indicator(
            mode="number",
            value=report.get("profit_factor", 0),
            title={"text": "Profit Factor"},
            domain={"x": [0.25, 0.5], "y": [0.6, 1.0]},
        ))

        fig.add_trace(go.Indicator(
            mode="number",
            value=report.get("sharpe_ratio", 0),
            title={"text": "Sharpe Ratio"},
            domain={"x": [0.5, 0.75], "y": [0.6, 1.0]},
        ))

        fig.add_trace(go.Indicator(
            mode="number+delta",
            value=report.get("return_percent", 0),
            title={"text": "Return (%)"},
            domain={"x": [0.75, 1.0], "y": [0.6, 1.0]},
            number={"suffix": "%"},
        ))

        # Table of all metrics
        fig.add_trace(go.Table(
            header=dict(values=["Metric", "Value"], fill_color="rgb(30,30,30)", font=dict(color="white")),
            cells=dict(
                values=[metrics, [str(v) for v in values]],
                fill_color="rgb(50,50,50)",
                font=dict(color="white"),
            ),
            domain={"x": [0, 1], "y": [0, 0.55]},
        ))

        fig.update_layout(
            title="ICT 2022 Strategy - Performance Summary",
            template="plotly_dark",
            height=700,
        )

        output_path = Path(save_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(output_path))
        logger.info(f"Performance summary saved to {output_path}")

        return fig
