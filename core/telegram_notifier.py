"""Telegram Notification Module for ICT Trading Bot.

Sends alerts to Telegram via TWO bots (different users):
- Both bots receive ALL notifications:
  - Trade triggered (open)
  - Trade closed (with P/L)
  - Hourly session status update
  - End-of-day summary report

Each bot has its own token and chat_id for its respective user.
"""

from datetime import datetime, date
from typing import Any

import requests
from loguru import logger


class TelegramNotifier:
    """Sends trading notifications to two Telegram bots (different users)."""

    def __init__(
        self,
        trade_bot_token: str,
        trade_bot_chat_id: str,
        update_bot_token: str,
        update_bot_chat_id: str,
    ) -> None:
        self.bots = []
        if trade_bot_token and trade_bot_chat_id:
            self.bots.append({"token": trade_bot_token, "chat_id": trade_bot_chat_id})
        if update_bot_token and update_bot_chat_id:
            self.bots.append({"token": update_bot_token, "chat_id": update_bot_chat_id})

        self._last_hourly_update: datetime | None = None
        self._hourly_interval = 3600  # 1 hour in seconds
        self._daily_trades: list[dict] = []
        self._current_date: date | None = None

    def _send_to_all(self, text: str, parse_mode: str = "HTML") -> None:
        """Send a message to all configured bots."""
        for bot in self.bots:
            self._send_message(bot["token"], bot["chat_id"], text, parse_mode)

    def _send_message(
        self, bot_token: str, chat_id: str, text: str, parse_mode: str = "HTML"
    ) -> bool:
        """Send a message via Telegram Bot API."""
        if not bot_token or not chat_id:
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                return True
            else:
                logger.error(
                    f"Telegram API error: {response.status_code} - {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    # --- Trade Alerts ---

    def notify_trade_opened(self, trade: Any) -> None:
        """Send alert when a trade is triggered (to both bots)."""
        self._track_trade_date()

        emoji = "�R" if trade.trade_type == "BUY" else "🔴"
        msg = (
            f"{emoji} <b>TRADE OPENED</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Symbol: <b>{trade.symbol}</b>\n"
            f"📌 Type: <b>{trade.trade_type}</b>\n"
            f"💰 Entry: <b>{trade.entry_price:.5f}</b>\n"
            f"🛑 SL: {trade.stop_loss:.5f}\n"
            f"🎯 TP: {trade.take_profit:.5f}\n"
            f"📐 R:R: {trade.risk_reward:.1f}\n"
            f"📦 Lot: {trade.lot_size}\n"
            f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━"
        )
        self._send_to_all(msg)

    def notify_trade_closed(self, trade: Any) -> None:
        """Send alert when a trade is closed (to both bots)."""
        if trade.trade_result == "WIN":
            emoji = "✅"
        elif trade.trade_result == "LOSS":
            emoji = "❌"
        else:
            emoji = "⚖️"

        msg = (
            f"{emoji} <b>TRADE CLOSED - {trade.trade_result}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Symbol: <b>{trade.symbol}</b>\n"
            f"📌 Type: {trade.trade_type}\n"
            f"💰 Entry: {trade.entry_price:.5f}\n"
            f"💰 Exit: {trade.exit_price:.5f}\n"
            f"📈 P/L: <b>{trade.profit_loss:.1f} pips</b>\n"
            f"📐 R:R: {trade.risk_reward:.2f}\n"
            f"📝 Reason: {trade.exit_reason}\n"
            f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━"
        )
        self._send_to_all(msg)

        # Track for daily report
        self._daily_trades.append({
            "type": trade.trade_type,
            "result": trade.trade_result,
            "pnl_pips": trade.profit_loss,
            "rr": trade.risk_reward,
            "exit_reason": trade.exit_reason,
        })

    # --- Hourly Session Update ---

    def send_hourly_update(
        self,
        session_high: float,
        session_low: float,
        current_price: float,
        is_observation: bool,
        is_trading: bool,
        has_active_trade: bool,
        daily_bias: str,
        symbol: str,
    ) -> None:
        """Send hourly session status update to both bots (throttled to once/hour)."""
        now = datetime.now()

        if self._last_hourly_update is not None:
            elapsed = (now - self._last_hourly_update).total_seconds()
            if elapsed < self._hourly_interval:
                return

        self._last_hourly_update = now

        session_low_display = session_low if session_low != float("inf") else 0.0
        session_range = session_high - session_low_display if session_high > 0 else 0.0

        phase = (
            "🔍 Observation" if is_observation
            else "⚡ Trading" if is_trading
            else "💤 Off-hours"
        )
        trade_status = "🟢 Active" if has_active_trade else "⚪ None"

        msg = (
            f"📊 <b>HOURLY SESSION UPDATE</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🕐 Time: {now.strftime('%H:%M')} | Phase: {phase}\n"
            f"📈 Symbol: <b>{symbol}</b>\n"
            f"💵 Current: <b>{current_price:.5f}</b>\n"
            f"⬆️ Session High: {session_high:.5f}\n"
            f"⬇️ Session Low: {session_low_display:.5f}\n"
            f"📏 Range: {session_range:.5f}\n"
            f"🧭 Bias: {daily_bias}\n"
            f"📋 Trade: {trade_status}\n"
            f"━━━━━━━━━━━━━━━"
        )
        self._send_to_all(msg)

    # --- End of Day Report ---

    def send_daily_report(
        self,
        symbol: str,
        session_high: float,
        session_low: float,
        account_balance: float = 0.0,
    ) -> None:
        """Send end-of-day summary report to both bots."""
        total_trades = len(self._daily_trades)
        wins = sum(1 for t in self._daily_trades if t["result"] == "WIN")
        losses = sum(1 for t in self._daily_trades if t["result"] == "LOSS")
        breakevens = total_trades - wins - losses
        total_pnl = sum(t["pnl_pips"] for t in self._daily_trades)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        session_low_display = session_low if session_low != float("inf") else 0.0

        if total_trades > 0:
            msg = (
                f"📋 <b>END OF DAY REPORT</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📅 Date: {date.today().strftime('%Y-%m-%d')}\n"
                f"📊 Symbol: <b>{symbol}</b>\n\n"
                f"<b>Session Summary:</b>\n"
                f"⬆️ High: {session_high:.5f}\n"
                f"⬇️ Low: {session_low_display:.5f}\n"
                f"📏 Range: {session_high - session_low_display:.5f}\n\n"
                f"<b>Trade Summary:</b>\n"
                f"📈 Total Trades: {total_trades}\n"
                f"✅ Wins: {wins}\n"
                f"❌ Losses: {losses}\n"
                f"⚖️ Breakeven: {breakevens}\n"
                f"🎯 Win Rate: {win_rate:.0f}%\n"
                f"💰 Total P/L: <b>{total_pnl:.1f} pips</b>\n"
            )
            if account_balance > 0:
                msg += f"💼 Balance: ${account_balance:,.2f}\n"
            msg += f"━━━━━━━━━━━━━━━"
        else:
            msg = (
                f"📋 <b>END OF DAY REPORT</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📅 Date: {date.today().strftime('%Y-%m-%d')}\n"
                f"📊 Symbol: <b>{symbol}</b>\n\n"
                f"<b>Session Summary:</b>\n"
                f"⬆️ High: {session_high:.5f}\n"
                f"⬇️ Low: {session_low_display:.5f}\n"
                f"📏 Range: {session_high - session_low_display:.5f}\n\n"
                f"📝 No trades executed today.\n"
                f"━━━━━━━━━━━━━━━"
            )

        self._send_to_all(msg)

        # Reset daily trades for next day
        self._daily_trades = []

    def _track_trade_date(self) -> None:
        """Reset daily trade list if it's a new day."""
        today = date.today()
        if self._current_date != today:
            self._daily_trades = []
            self._current_date = today
