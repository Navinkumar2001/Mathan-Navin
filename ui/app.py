"""
ICT Trading Bot - Dashboard UI

A Streamlit-based dashboard that displays backtest reports with
tables, charts, and KPI indicators.

Usage:
    streamlit run ui/app.py
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# --- Page Config ---
st.set_page_config(
    page_title="ICT Trading Bot - Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Constants ---
REPORTS_DIR = Path(__file__).parent.parent / "reports"
DATA_DIR = Path(__file__).parent.parent / "data"

PERFORMANCE_REPORT_PATH = REPORTS_DIR / "performance_report.csv"
TRADES_PATH = REPORTS_DIR / "backtest_trades.csv"
TRADE_JOURNAL_PATH = DATA_DIR / "trade_journal.csv"


# --- Helper Functions ---
@st.cache_data
def load_performance_report() -> dict | None:
    """Load performance report from CSV as a dict."""
    if not PERFORMANCE_REPORT_PATH.exists():
        return None
    df = pd.read_csv(PERFORMANCE_REPORT_PATH)
    return dict(zip(df["Metric"], df["Value"]))


@st.cache_data
def load_trades() -> pd.DataFrame | None:
    """Load backtest trades from CSV."""
    # Try backtest_trades.csv first, then trade_journal.csv
    for path in [TRADES_PATH, TRADE_JOURNAL_PATH]:
        if path.exists():
            df = pd.read_csv(path)
            if not df.empty:
                # Parse datetime columns
                for col in ["entry_time", "exit_time"]:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col], errors="coerce")
                return df
    return None


def format_currency(value: float) -> str:
    """Format a number as currency."""
    return f"${value:,.2f}"


def format_percent(value: float) -> str:
    """Format a number as percentage."""
    return f"{value:.2f}%"


# --- Sidebar ---
st.sidebar.title("📈 ICT Trading Bot")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    ["Overview", "Trade Journal", "Performance Charts", "Risk Analysis"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.caption("ICT 2022 Model Strategy")

# --- Load Data ---
report = load_performance_report()
trades_df = load_trades()

# Check if data exists
if report is None and trades_df is None:
    st.warning(
        "⚠️ No report data found. Run a backtest first:\n\n"
        "```bash\npython main_backtest.py\n```"
    )
    st.stop()


# ============================================================
# PAGE: Overview
# ============================================================
if page == "Overview":
    st.title("📊 Strategy Performance Overview")
    st.markdown("---")

    if report:
        # KPI Cards Row 1
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Trades", int(float(report.get("total_trades", 0))))
        with col2:
            wr = float(report.get("win_rate", 0))
            st.metric("Win Rate", format_percent(wr))
        with col3:
            pf = float(report.get("profit_factor", 0))
            st.metric("Profit Factor", f"{pf:.2f}")
        with col4:
            ret = float(report.get("return_percent", 0))
            st.metric("Return", format_percent(ret), delta=format_percent(ret))

        # KPI Cards Row 2
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Net Profit", format_currency(float(report.get("net_profit", 0))))
        with col2:
            st.metric("Sharpe Ratio", f"{float(report.get('sharpe_ratio', 0)):.2f}")
        with col3:
            dd = float(report.get("max_drawdown_percent", 0))
            st.metric("Max Drawdown", format_percent(dd), delta=f"-{dd:.1f}%", delta_color="inverse")
        with col4:
            st.metric("Avg R:R", f"{float(report.get('average_rr', 0)):.2f}")

        st.markdown("---")

        # Performance Table
        st.subheader("📋 Full Performance Report")
        report_df = pd.DataFrame(
            {"Metric": list(report.keys()), "Value": list(report.values())}
        )
        st.dataframe(report_df, use_container_width=True, hide_index=True)

    # Win/Loss Pie Chart
    if report:
        st.markdown("---")
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("🎯 Win/Loss Distribution")
            wins = int(float(report.get("wins", 0)))
            losses = int(float(report.get("losses", 0)))
            if wins + losses > 0:
                fig_pie = px.pie(
                    names=["Wins", "Losses"],
                    values=[wins, losses],
                    color_discrete_sequence=["#26a69a", "#ef5350"],
                    hole=0.4,
                )
                fig_pie.update_layout(
                    template="plotly_dark",
                    height=350,
                    margin=dict(t=30, b=30),
                )
                st.plotly_chart(fig_pie, use_container_width=True)

        with col_right:
            st.subheader("💰 Profit vs Loss")
            total_profit = float(report.get("total_profit", 0))
            total_loss = float(report.get("total_loss", 0))
            fig_bar = px.bar(
                x=["Total Profit", "Total Loss"],
                y=[total_profit, total_loss],
                color=["Profit", "Loss"],
                color_discrete_map={"Profit": "#26a69a", "Loss": "#ef5350"},
            )
            fig_bar.update_layout(
                template="plotly_dark",
                height=350,
                showlegend=False,
                yaxis_title="Amount ($)",
                xaxis_title="",
                margin=dict(t=30, b=30),
            )
            st.plotly_chart(fig_bar, use_container_width=True)


# ============================================================
# PAGE: Trade Journal
# ============================================================
elif page == "Trade Journal":
    st.title("📒 Trade Journal")
    st.markdown("---")

    if trades_df is not None and not trades_df.empty:
        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            if "trade_result" in trades_df.columns:
                result_filter = st.multiselect(
                    "Filter by Result",
                    options=trades_df["trade_result"].dropna().unique().tolist(),
                    default=trades_df["trade_result"].dropna().unique().tolist(),
                )
            else:
                result_filter = []
        with col2:
            if "trade_type" in trades_df.columns:
                type_filter = st.multiselect(
                    "Filter by Type",
                    options=trades_df["trade_type"].dropna().unique().tolist(),
                    default=trades_df["trade_type"].dropna().unique().tolist(),
                )
            else:
                type_filter = []
        with col3:
            if "exit_reason" in trades_df.columns:
                reason_filter = st.multiselect(
                    "Filter by Exit Reason",
                    options=trades_df["exit_reason"].dropna().unique().tolist(),
                    default=trades_df["exit_reason"].dropna().unique().tolist(),
                )
            else:
                reason_filter = []

        # Apply filters
        filtered_df = trades_df.copy()
        if result_filter and "trade_result" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["trade_result"].isin(result_filter)]
        if type_filter and "trade_type" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["trade_type"].isin(type_filter)]
        if reason_filter and "exit_reason" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["exit_reason"].isin(reason_filter)]

        st.dataframe(filtered_df, use_container_width=True, hide_index=True)
        st.caption(f"Showing {len(filtered_df)} of {len(trades_df)} trades")

        # Download button
        csv_data = filtered_df.to_csv(index=False)
        st.download_button(
            "📥 Download Filtered Trades",
            csv_data,
            "filtered_trades.csv",
            "text/csv",
        )
    else:
        st.info("No trade data available. Run a backtest to generate trades.")


# ============================================================
# PAGE: Performance Charts
# ============================================================
elif page == "Performance Charts":
    st.title("📈 Performance Charts")
    st.markdown("---")

    if trades_df is not None and not trades_df.empty:
        # --- Equity Curve ---
        st.subheader("💹 Equity Curve")
        if "profit_loss" in trades_df.columns:
            initial_balance = float(report.get("initial_balance", 10000)) if report else 10000.0
            equity = [initial_balance]
            for pnl in trades_df["profit_loss"].fillna(0):
                equity.append(equity[-1] + float(pnl))

            equity_df = pd.DataFrame({
                "Trade #": list(range(len(equity))),
                "Balance": equity,
            })

            fig_equity = px.line(
                equity_df, x="Trade #", y="Balance",
                title="Account Equity Over Time",
            )
            fig_equity.update_layout(
                template="plotly_dark",
                height=400,
                yaxis_title="Balance ($)",
            )
            fig_equity.update_traces(
                line_color="#00bcd4",
                fill="tozeroy",
                fillcolor="rgba(0, 188, 212, 0.1)",
            )
            st.plotly_chart(fig_equity, use_container_width=True)

        st.markdown("---")

        # --- P/L Per Trade Bar Chart ---
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("📊 P/L Per Trade")
            if "profit_loss" in trades_df.columns:
                pnl_df = trades_df[["profit_loss"]].copy().reset_index(drop=True)
                pnl_df["Trade #"] = range(1, len(pnl_df) + 1)
                pnl_df["Color"] = pnl_df["profit_loss"].apply(
                    lambda x: "Win" if x >= 0 else "Loss"
                )

                fig_pnl = px.bar(
                    pnl_df, x="Trade #", y="profit_loss", color="Color",
                    color_discrete_map={"Win": "#26a69a", "Loss": "#ef5350"},
                )
                fig_pnl.update_layout(
                    template="plotly_dark",
                    height=350,
                    yaxis_title="Profit/Loss ($)",
                    showlegend=False,
                )
                st.plotly_chart(fig_pnl, use_container_width=True)

        with col_right:
            st.subheader("📊 Cumulative P/L")
            if "profit_loss" in trades_df.columns:
                cum_pnl = trades_df["profit_loss"].fillna(0).cumsum()
                cum_df = pd.DataFrame({
                    "Trade #": range(1, len(cum_pnl) + 1),
                    "Cumulative P/L": cum_pnl.values,
                })

                fig_cum = px.area(
                    cum_df, x="Trade #", y="Cumulative P/L",
                    title="Cumulative Profit/Loss",
                )
                fig_cum.update_layout(
                    template="plotly_dark",
                    height=350,
                    yaxis_title="Cumulative P/L ($)",
                )
                fig_cum.update_traces(
                    line_color="#7c4dff",
                    fillcolor="rgba(124, 77, 255, 0.1)",
                )
                st.plotly_chart(fig_cum, use_container_width=True)

        st.markdown("---")

        # --- Exit Reason & Trade Type Breakdown ---
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("🚪 Exit Reasons")
            if "exit_reason" in trades_df.columns:
                exit_counts = trades_df["exit_reason"].value_counts()
                fig_exit = px.pie(
                    names=exit_counts.index,
                    values=exit_counts.values,
                    hole=0.35,
                )
                fig_exit.update_layout(
                    template="plotly_dark",
                    height=350,
                    margin=dict(t=30, b=30),
                )
                st.plotly_chart(fig_exit, use_container_width=True)

        with col_right:
            st.subheader("📊 Trade Direction")
            if "trade_type" in trades_df.columns:
                type_counts = trades_df["trade_type"].value_counts()
                fig_type = px.bar(
                    x=type_counts.index,
                    y=type_counts.values,
                    color=type_counts.index,
                    color_discrete_map={"BUY": "#26a69a", "SELL": "#ef5350"},
                )
                fig_type.update_layout(
                    template="plotly_dark",
                    height=350,
                    showlegend=False,
                    yaxis_title="Count",
                    xaxis_title="Direction",
                )
                st.plotly_chart(fig_type, use_container_width=True)

        # --- Monthly Returns ---
        if "entry_time" in trades_df.columns and "profit_loss" in trades_df.columns:
            st.markdown("---")
            st.subheader("📅 Monthly Returns")
            monthly_df = trades_df.copy()
            monthly_df["month"] = monthly_df["entry_time"].dt.to_period("M").astype(str)
            monthly_returns = monthly_df.groupby("month")["profit_loss"].sum().reset_index()
            monthly_returns.columns = ["Month", "P/L"]
            monthly_returns["Color"] = monthly_returns["P/L"].apply(
                lambda x: "Positive" if x >= 0 else "Negative"
            )

            fig_monthly = px.bar(
                monthly_returns, x="Month", y="P/L", color="Color",
                color_discrete_map={"Positive": "#26a69a", "Negative": "#ef5350"},
            )
            fig_monthly.update_layout(
                template="plotly_dark",
                height=350,
                showlegend=False,
                yaxis_title="Monthly P/L ($)",
            )
            st.plotly_chart(fig_monthly, use_container_width=True)
    else:
        st.info("No trade data available.")


# ============================================================
# PAGE: Risk Analysis
# ============================================================
elif page == "Risk Analysis":
    st.title("⚠️ Risk Analysis")
    st.markdown("---")

    if trades_df is not None and not trades_df.empty and "profit_loss" in trades_df.columns:
        # Drawdown chart
        st.subheader("📉 Drawdown Analysis")
        initial_balance = float(report.get("initial_balance", 10000)) if report else 10000.0
        equity = [initial_balance]
        for pnl in trades_df["profit_loss"].fillna(0):
            equity.append(equity[-1] + float(pnl))

        equity_series = pd.Series(equity)
        peak = equity_series.cummax()
        drawdown = (peak - equity_series) / peak * 100

        dd_df = pd.DataFrame({
            "Trade #": range(len(drawdown)),
            "Drawdown (%)": drawdown.values,
        })

        fig_dd = px.area(
            dd_df, x="Trade #", y="Drawdown (%)",
            title="Portfolio Drawdown",
        )
        fig_dd.update_layout(
            template="plotly_dark",
            height=350,
            yaxis_title="Drawdown (%)",
            yaxis_autorange="reversed",
        )
        fig_dd.update_traces(
            line_color="#ff5252",
            fillcolor="rgba(255, 82, 82, 0.2)",
        )
        st.plotly_chart(fig_dd, use_container_width=True)

        st.markdown("---")

        # Risk/Reward Distribution
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("📊 R:R Distribution")
            if "risk_reward" in trades_df.columns:
                rr_data = trades_df["risk_reward"].dropna()
                rr_data = rr_data[rr_data > 0]
                if not rr_data.empty:
                    fig_rr = px.histogram(
                        rr_data, nbins=20,
                        title="Risk/Reward Ratio Distribution",
                        labels={"value": "R:R Ratio", "count": "Frequency"},
                    )
                    fig_rr.update_layout(
                        template="plotly_dark",
                        height=350,
                        showlegend=False,
                    )
                    fig_rr.update_traces(marker_color="#7c4dff")
                    st.plotly_chart(fig_rr, use_container_width=True)

        with col_right:
            st.subheader("📊 P/L Distribution")
            fig_hist = px.histogram(
                trades_df["profit_loss"].dropna(), nbins=25,
                title="Profit/Loss Distribution",
                labels={"value": "P/L ($)", "count": "Frequency"},
            )
            fig_hist.update_layout(
                template="plotly_dark",
                height=350,
                showlegend=False,
            )
            fig_hist.update_traces(marker_color="#00bcd4")
            st.plotly_chart(fig_hist, use_container_width=True)

        st.markdown("---")

        # Consecutive wins/losses
        st.subheader("🔥 Streak Analysis")
        if "trade_result" in trades_df.columns:
            results = trades_df["trade_result"].tolist()
            max_win_streak = 0
            max_loss_streak = 0
            current_streak = 0
            current_type = None

            for r in results:
                if r == current_type:
                    current_streak += 1
                else:
                    current_type = r
                    current_streak = 1
                if r == "WIN":
                    max_win_streak = max(max_win_streak, current_streak)
                elif r == "LOSS":
                    max_loss_streak = max(max_loss_streak, current_streak)

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Max Win Streak", max_win_streak)
            with col2:
                st.metric("Max Loss Streak", max_loss_streak)
            with col3:
                avg_pnl = trades_df["profit_loss"].mean()
                st.metric("Avg Trade P/L", format_currency(avg_pnl))

        # Summary stats table
        st.subheader("📋 Risk Metrics Summary")
        if report:
            risk_metrics = {
                "Max Drawdown (%)": report.get("max_drawdown_percent", "N/A"),
                "Sharpe Ratio": report.get("sharpe_ratio", "N/A"),
                "Profit Factor": report.get("profit_factor", "N/A"),
                "Expectancy ($)": report.get("expectancy", "N/A"),
                "Win Rate (%)": report.get("win_rate", "N/A"),
                "Average R:R": report.get("average_rr", "N/A"),
            }
            risk_df = pd.DataFrame(
                {"Metric": list(risk_metrics.keys()), "Value": list(risk_metrics.values())}
            )
            st.dataframe(risk_df, use_container_width=True, hide_index=True)
    else:
        st.info("No trade data available for risk analysis.")
