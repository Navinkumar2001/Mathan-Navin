"""Telegram Notification Module for ICT Trading Bot.

Sends alerts to Telegram via TWO bots (different users):
- Both bots receive ALL notifications:
  - Trade triggered (open)
  - Trade closed (with P/L)
  - Hourly session status update
  - End-of-day summary report
  - On-demand status when user sends /status

Each bot has its own token and chat_id for its respective user.

All API calls are asynchronous using aiohttp for concurrent execution.
"""

import asyncio
import threading
from datetime import datetime, date
from typing import Any, Callable

import aiohttp
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
        self._daily_report_sent: bool = False

        # For /status command polling
        self._status_callback: Callable[[], dict] | None = None
        self._last_update_ids: dict[str, int] = {}  # track last update_id per bot
        self._polling_active = False
        self._poll_thread: threading.Thread | None = None

        # Async event loop for background operations
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: aiohttp.ClientSession | None = None

    def _get_or_create_loop(self) -> asyncio.AbstractEventLoop:
        """Get the running event loop or create a new one for the current thread."""
        try:
            loop = asyncio.get_running_loop()
            return loop
        except RuntimeError:
            pass

        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def _run_async(self, coro) -> None:
        """Run an async coroutine from synchronous context."""
        try:
            loop = asyncio.get_running_loop()
            # We're already inside an event loop, schedule as task
            asyncio.ensure_future(coro, loop=loop)
        except RuntimeError:
            # No running loop, create one and run
            loop = self._get_or_create_loop()
            loop.run_until_complete(coro)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    async def _send_to_all_async(self, text: str, parse_mode: str = "HTML") -> None:
        """Send a message to all configured bots concurrently."""
        tasks = [
            self._send_message_async(bot["token"], bot["chat_id"], text, parse_mode)
            for bot in self.bots
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_message_async(
        self, bot_token: str, chat_id: str, text: str, parse_mode: str = "HTML"
    ) -> bool:
        """Send a message via Telegram Bot API asynchronously."""
        if not bot_token or not chat_id:
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    return True
                else:
                    body = await response.text()
                    logger.error(
                        f"Telegram API error: {response.status} - {body}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    # --- Trade Alerts ---

    def notify_trade_opened(self, trade: Any) -> None:
        """Send alert when a trade is triggered (to both bots)."""
        self._track_trade_date()

        # Track opened trade for daily report
        self._daily_trades.append({
            "type": trade.trade_type,
            "result": "OPEN",
            "pnl_pips": 0.0,
            "rr": trade.risk_reward,
            "exit_reason": "",
            "entry_price": trade.entry_price,
            "status": "OPEN",
        })

        emoji = "🟢" if trade.trade_type == "BUY" else "🔴"
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
        self._run_async(self._send_to_all_async(msg))

    def notify_trade_closed(self, trade: Any) -> None:
        """Send alert when a trade is closed (to both bots)."""
        self._track_trade_date()

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
        self._run_async(self._send_to_all_async(msg))

        # Update the matching OPEN trade entry or add a new closed entry
        updated = False
        for t in self._daily_trades:
            if (
                t.get("status") == "OPEN"
                and t["type"] == trade.trade_type
                and t.get("entry_price") == trade.entry_price
            ):
                t["result"] = trade.trade_result
                t["pnl_pips"] = trade.profit_loss
                t["rr"] = trade.risk_reward
                t["exit_reason"] = trade.exit_reason
                t["status"] = "CLOSED"
                updated = True
                break

        if not updated:
            # Trade was opened before tracker started (e.g. bot restart), add it
            self._daily_trades.append({
                "type": trade.trade_type,
                "result": trade.trade_result,
                "pnl_pips": trade.profit_loss,
                "rr": trade.risk_reward,
                "exit_reason": trade.exit_reason,
                "entry_price": trade.entry_price,
                "status": "CLOSED",
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
        self._run_async(self._send_to_all_async(msg))

    # --- End of Day Report ---

    def send_daily_report(
        self,
        symbol: str,
        session_high: float,
        session_low: float,
        account_balance: float = 0.0,
    ) -> None:
        """Send end-of-day summary report to both bots (only once per day)."""
        # Prevent sending the report multiple times in the same day
        if self._daily_report_sent:
            return

        # Only count closed trades for statistics
        closed_trades = [t for t in self._daily_trades if t.get("status") == "CLOSED"]
        total_trades = len(self._daily_trades)  # All trades (open + closed)
        total_closed = len(closed_trades)
        wins = sum(1 for t in closed_trades if t["result"] == "WIN")
        losses = sum(1 for t in closed_trades if t["result"] == "LOSS")
        breakevens = total_closed - wins - losses
        still_open = total_trades - total_closed
        total_pnl = sum(t["pnl_pips"] for t in closed_trades)
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0

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
            )
            if still_open > 0:
                msg += f"🔄 Still Open: {still_open}\n"
            msg += (
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

        self._run_async(self._send_to_all_async(msg))
        self._daily_report_sent = True

    def _track_trade_date(self) -> None:
        """Reset daily trade list if it's a new day."""
        today = date.today()
        if self._current_date != today:
            self._daily_trades = []
            self._current_date = today
            self._daily_report_sent = False

    # --- On-demand /status command ---

    def start_command_listener(self, status_callback: Callable[[], dict]) -> None:
        """
        Start background thread that polls for /status commands from users.

        Args:
            status_callback: Function that returns current bot state as a dict with keys:
                symbol, session_high, session_low, current_price,
                is_observation, is_trading, has_active_trade, daily_bias, account_balance
        """
        self._status_callback = status_callback
        self._polling_active = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        logger.info("Telegram command listener started. Users can send /status for updates.")

    def stop_command_listener(self) -> None:
        """Stop the polling thread and cleanup aiohttp session."""
        self._polling_active = False
        # Close aiohttp session
        if self._session and not self._session.closed:
            try:
                loop = self._get_or_create_loop()
                loop.run_until_complete(self._session.close())
            except Exception:
                pass

    def _poll_loop(self) -> None:
        """Background loop that checks for incoming /status messages every 5 seconds."""
        import time

        # Create a dedicated event loop for polling thread
        poll_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(poll_loop)

        while self._polling_active:
            try:
                poll_loop.run_until_complete(self._poll_all_bots())
            except Exception as e:
                logger.debug(f"Telegram poll error: {e}")
            time.sleep(5)

        poll_loop.close()

    async def _poll_all_bots(self) -> None:
        """Poll all bots for commands concurrently."""
        tasks = [
            self._check_commands_async(bot["token"], bot["chat_id"])
            for bot in self.bots
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_commands_async(self, bot_token: str, chat_id: str) -> None:
        """Check for new messages on a bot and respond to /status."""
        offset = self._last_update_ids.get(bot_token, 0)
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        params = {"offset": offset + 1, "timeout": 0, "limit": 10}

        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()

            if not data.get("ok"):
                return

            for update in data.get("result", []):
                update_id = update["update_id"]
                self._last_update_ids[bot_token] = update_id

                message = update.get("message", {})
                text = message.get("text", "").strip().lower()
                msg_chat_id = str(message.get("chat", {}).get("id", ""))

                if text == "/status" and msg_chat_id == chat_id:
                    await self._send_status_reply_async(bot_token, chat_id)

        except Exception:
            pass

    async def _send_status_reply_async(self, bot_token: str, chat_id: str) -> None:
        """Send current status as reply to /status command."""
        if self._status_callback is None:
            await self._send_message_async(bot_token, chat_id, "⚠️ Bot not fully initialized yet.")
            return

        try:
            state = self._status_callback()
        except Exception as e:
            await self._send_message_async(bot_token, chat_id, f"⚠️ Error getting status: {e}")
            return

        session_high = state.get("session_high", 0.0)
        session_low = state.get("session_low", 0.0)
        if session_low == float("inf"):
            session_low = 0.0
        current_price = state.get("current_price", 0.0)
        session_range = session_high - session_low if session_high > 0 else 0.0

        is_obs = state.get("is_observation", False)
        is_trade = state.get("is_trading", False)
        phase = "🔍 Observation" if is_obs else "⚡ Trading" if is_trade else "💤 Off-hours"
        trade_status = "🟢 Active" if state.get("has_active_trade", False) else "⚪ None"

        msg = (
            f"📊 <b>CURRENT STATUS</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🕐 Time: {datetime.now().strftime('%H:%M:%S')} | {phase}\n"
            f"📈 Symbol: <b>{state.get('symbol', 'N/A')}</b>\n"
            f"💵 Price: <b>{current_price:.5f}</b>\n"
            f"⬆️ High: {session_high:.5f}\n"
            f"⬇️ Low: {session_low:.5f}\n"
            f"📏 Range: {session_range:.5f}\n"
            f"🧭 Bias: {state.get('daily_bias', 'NEUTRAL')}\n"
            f"📋 Trade: {trade_status}\n"
        )

        balance = state.get("account_balance", 0.0)
        if balance > 0:
            msg += f"💼 Balance: ${balance:,.2f}\n"

        msg += f"━━━━━━━━━━━━━━━"
        await self._send_message_async(bot_token, chat_id, msg)
