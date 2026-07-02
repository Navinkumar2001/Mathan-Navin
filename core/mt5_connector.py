"""MetaTrader 5 connection and order management."""

import time
from datetime import datetime
from typing import Any

import MetaTrader5 as mt5
import pandas as pd
from loguru import logger

from config.settings import TradingConfig


class MT5Connector:
    """Handles all MetaTrader 5 operations including connection, orders, and data retrieval."""

    TIMEFRAME_MAP: dict[str, int] = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.connected: bool = False
        self.reconnect_attempts: int = 5
        self.reconnect_delay: float = 5.0

    def connect(self) -> bool:
        """Initialize and login to MetaTrader 5."""
        if not mt5.initialize():
            logger.error(f"MT5 initialization failed: {mt5.last_error()}")
            return False

        if self.config.mt5_login > 0:
            authorized = mt5.login(
                login=self.config.mt5_login,
                server=self.config.mt5_server,
                password=self.config.mt5_password,
            )
            if not authorized:
                logger.error(f"MT5 login failed: {mt5.last_error()}")
                mt5.shutdown()
                return False

        self.connected = True
        account_info = mt5.account_info()
        if account_info:
            logger.info(
                f"Connected to MT5 | Account: {account_info.login} | "
                f"Balance: {account_info.balance} | Server: {account_info.server}"
            )
        return True

    def ensure_connection(self) -> bool:
        """Ensure MT5 connection is active, reconnect if needed."""
        if self.connected and mt5.terminal_info() is not None:
            return True

        logger.warning("MT5 connection lost. Attempting reconnect...")
        self.connected = False

        for attempt in range(1, self.reconnect_attempts + 1):
            logger.info(f"Reconnect attempt {attempt}/{self.reconnect_attempts}")
            if self.connect():
                logger.info("Reconnection successful.")
                return True
            time.sleep(self.reconnect_delay)

        logger.critical("Failed to reconnect to MT5 after all attempts.")
        return False

    def disconnect(self) -> None:
        """Shutdown MT5 connection."""
        mt5.shutdown()
        self.connected = False
        logger.info("MT5 disconnected.")

    def get_account_info(self) -> dict[str, Any] | None:
        """Get current account information."""
        if not self.ensure_connection():
            return None
        info = mt5.account_info()
        if info is None:
            return None
        return {
            "login": info.login,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "profit": info.profit,
            "leverage": info.leverage,
            "currency": info.currency,
        }

    def get_candles(self, count: int = 500, timeframe: str | None = None) -> pd.DataFrame:
        """Retrieve historical candle data."""
        if not self.ensure_connection():
            return pd.DataFrame()

        tf = self.TIMEFRAME_MAP.get(timeframe or self.config.timeframe, mt5.TIMEFRAME_M5)
        rates = mt5.copy_rates_from_pos(self.config.symbol, tf, 0, count)

        if rates is None or len(rates) == 0:
            logger.warning(f"No candle data received for {self.config.symbol}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"time": "timestamp"}, inplace=True)
        return df

    def get_current_tick(self) -> dict[str, float] | None:
        """Get current bid/ask prices."""
        if not self.ensure_connection():
            return None
        tick = mt5.symbol_info_tick(self.config.symbol)
        if tick is None:
            return None
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": round((tick.ask - tick.bid) / self.config.pip_value, 1),
            "time": datetime.fromtimestamp(tick.time),
        }

    def get_symbol_info(self) -> dict[str, Any] | None:
        """Get symbol information."""
        if not self.ensure_connection():
            return None
        info = mt5.symbol_info(self.config.symbol)
        if info is None:
            return None
        return {
            "point": info.point,
            "digits": info.digits,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "trade_contract_size": info.trade_contract_size,
        }

    def _get_filling_mode(self, symbol_info) -> int:
        """Determine the supported filling mode for a symbol."""
        filling = symbol_info.filling_mode
        if filling & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        elif filling & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        else:
            return mt5.ORDER_FILLING_RETURN

    def place_order(
        self,
        order_type: str,
        volume: float,
        price: float,
        sl: float,
        tp: float,
        comment: str = "ICT_BOT",
    ) -> dict[str, Any] | None:
        """Place a market order."""
        if not self.ensure_connection():
            return None

        symbol_info = mt5.symbol_info(self.config.symbol)
        if symbol_info is None:
            logger.error(f"Symbol {self.config.symbol} not found.")
            return None

        if not symbol_info.visible:
            if not mt5.symbol_select(self.config.symbol, True):
                logger.error(f"Failed to select symbol {self.config.symbol}")
                return None

        mt5_order_type = mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL

        # Determine supported filling mode for this symbol
        filling_mode = self._get_filling_mode(symbol_info)

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.config.symbol,
            "volume": volume,
            "type": mt5_order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 202200,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        result = mt5.order_send(request)
        if result is None:
            logger.error(f"Order send returned None: {mt5.last_error()}")
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(
                f"Order failed | Retcode: {result.retcode} | "
                f"Comment: {result.comment}"
            )
            return None

        logger.info(
            f"Order placed | Ticket: {result.order} | Type: {order_type} | "
            f"Volume: {volume} | Price: {price} | SL: {sl} | TP: {tp}"
        )

        return {
            "ticket": result.order,
            "volume": volume,
            "price": result.price,
            "sl": sl,
            "tp": tp,
            "order_type": order_type,
            "comment": comment,
        }

    def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> bool:
        """Modify an existing position's SL/TP."""
        if not self.ensure_connection():
            return False

        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            logger.warning(f"Position {ticket} not found for modification.")
            return False

        pos = position[0]
        new_sl = sl if sl is not None else pos.sl
        new_tp = tp if tp is not None else pos.tp

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.config.symbol,
            "position": ticket,
            "sl": new_sl,
            "tp": new_tp,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Position modify failed for ticket {ticket}: {mt5.last_error()}")
            return False

        logger.info(f"Position {ticket} modified | SL: {new_sl} | TP: {new_tp}")
        return True

    def close_position(self, ticket: int, comment: str = "ICT_BOT_CLOSE") -> bool:
        """Close an existing position."""
        if not self.ensure_connection():
            return False

        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            logger.warning(f"Position {ticket} not found for closing.")
            return False

        pos = position[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(self.config.symbol)
        if tick is None:
            return False

        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.config.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 202200,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Close position failed for ticket {ticket}: {mt5.last_error()}")
            return False

        logger.info(f"Position {ticket} closed at {price} | Reason: {comment}")
        return True

    def partial_close(self, ticket: int, volume: float, comment: str = "PARTIAL_CLOSE") -> bool:
        """Partially close a position."""
        if not self.ensure_connection():
            return False

        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            return False

        pos = position[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(self.config.symbol)
        if tick is None:
            return False

        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.config.symbol,
            "volume": volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 202200,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Partial close failed for ticket {ticket}")
            return False

        logger.info(f"Partial close {ticket} | Volume: {volume} | Price: {price}")
        return True

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Get all open positions for the symbol."""
        if not self.ensure_connection():
            return []

        positions = mt5.positions_get(symbol=self.config.symbol)
        if positions is None:
            return []

        return [
            {
                "ticket": pos.ticket,
                "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "time": datetime.fromtimestamp(pos.time),
                "comment": pos.comment,
            }
            for pos in positions
            if pos.magic == 202200
        ]

    def get_trade_history(self, days: int = 30) -> list[dict[str, Any]]:
        """Get closed trade history."""
        if not self.ensure_connection():
            return []

        from datetime import timedelta
        date_from = datetime.now() - timedelta(days=days)
        date_to = datetime.now()

        deals = mt5.history_deals_get(date_from, date_to, group=f"*{self.config.symbol}*")
        if deals is None:
            return []

        return [
            {
                "ticket": deal.ticket,
                "order": deal.order,
                "time": datetime.fromtimestamp(deal.time),
                "type": "BUY" if deal.type == 0 else "SELL",
                "volume": deal.volume,
                "price": deal.price,
                "profit": deal.profit,
                "commission": deal.commission,
                "swap": deal.swap,
                "comment": deal.comment,
            }
            for deal in deals
            if deal.magic == 202200
        ]
