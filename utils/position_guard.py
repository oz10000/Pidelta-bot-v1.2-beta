# utils/position_guard.py
import time
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

from config import ASSET_CONFIG
from utils.telemetry import log_event
from data.ohlcv import fetch_ohlcv
from strategy.engine import atr

logger = logging.getLogger("PositionGuard")


class PositionGuard:
    """
    Responsable de:
    - Verificar la existencia de TP/SL/trailing (cada 30s)
    - Recrear órdenes faltantes (máx 3 intentos)
    - Activar break-even (trigger + offset por activo)
    - Cerrar posición de emergencia si la protección falla
    - Persistencia de estado en JSON (cache, no source of truth)
    """

    def __init__(self, client, state_path="state/position_state.json"):
        self.client = client
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        self.last_check = 0
        self.interval = 30
        self.max_retries = 3
        self.retry_count = {}
        self._atr_cache = {}

        self._load_state()

    def _load_state(self):
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    self.state = json.load(f)
                return
            except Exception:
                pass
        self.state = {}

    def _save_state(self):
        try:
            with open(self.state_path, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"State save error: {e}")

    def has_state(self, symbol: str) -> bool:
        return symbol in self.state

    def clear_state(self, symbol: str):
        self.state.pop(symbol, None)
        self._save_state()

    def update_state(self, symbol: str, data: Dict):
        self.state[symbol] = data
        self._save_state()

    def get_atr(self, symbol: str) -> Optional[float]:
        if symbol in self._atr_cache:
            return self._atr_cache[symbol]

        try:
            binance_symbol = symbol.replace(":USDT", "")
            df = fetch_ohlcv(binance_symbol, timeframe="5m", limit=100)
            if df is None or df.empty:
                return None
            atr_val = atr(df, period=14).iloc[-1]
            self._atr_cache[symbol] = atr_val
            return atr_val
        except Exception as e:
            logger.error(f"ATR error for {symbol}: {e}")
            return None

    def register_trade(self, symbol: str, position_data: Dict):
        self.state[symbol] = {
            "be_active": False,
            "entry_price": position_data["entry_price"],
            "side": position_data["side"],
            "size": position_data["size"],
            "atr": position_data["atr"],
            "score": position_data["score"],
            "adx": position_data["adx"],
            "entry_time": datetime.utcnow().isoformat(),
            "sl_price": None,
            "tp_price": None,
            "trail_callback": None,
        }
        self._save_state()
        log_event("trade_registered", {"symbol": symbol, "atr": position_data["atr"]})

    def check_all(self):
        now = time.time()
        if now - self.last_check < self.interval:
            return
        self.last_check = now

        for symbol in list(self.state.keys()):
            self._protect_position(symbol)

    def _protect_position(self, symbol: str):
        if symbol not in self.state:
            return

        position = self.client.fetch_position(symbol)
        if position is None:
            self.state.pop(symbol, None)
            self._save_state()
            return

        orders = self.client.fetch_open_orders(symbol)

        sl_order = self._find_order(orders, "stop_market")
        if sl_order is None:
            self._recreate_sl(symbol, position)
        else:
            self.retry_count.pop(symbol + "_sl", None)
            self.state[symbol]["sl_price"] = sl_order.get("stopPrice")

        tp_order = self._find_order(orders, "take_profit_market")
        if tp_order is None:
            self._recreate_tp(symbol, position)
        else:
            self.retry_count.pop(symbol + "_tp", None)
            self.state[symbol]["tp_price"] = tp_order.get("stopPrice")

        trail_order = self._find_order(orders, "trailing_stop")
        if trail_order is None:
            self._recreate_trailing(symbol, position)
        else:
            self.retry_count.pop(symbol + "_trail", None)

        self._check_break_even(symbol, position)

        self._save_state()

    def _find_order(self, orders, order_type):
        for o in orders:
            if o.get("type") == order_type and o.get("reduceOnly"):
                return o
        return None

    def _recreate_sl(self, symbol: str, position: Dict):
        key = symbol + "_sl"
        self.retry_count[key] = self.retry_count.get(key, 0) + 1
        if self.retry_count[key] > self.max_retries:
            self._emergency_close(symbol, position, "sl_retry_exceeded")
            return

        cfg = ASSET_CONFIG.get(symbol, {})
        sl_mult = cfg.get("sl_atr", 1.5)
        atr = self.state[symbol].get("atr") or self.get_atr(symbol)
        if atr is None:
            return

        sl_price = position["entry_price"] - sl_mult * atr if position["side"] == "long" else position["entry_price"] + sl_mult * atr
        side = "sell" if position["side"] == "long" else "buy"

        order = self.client.place_stop_loss(
            symbol, side, position["size"], sl_price,
            client_order_id=f"pg_sl_{symbol}_{int(time.time())}"
        )
        if order:
            log_event("sl_recreated", {"symbol": symbol, "price": sl_price})
            self.state[symbol]["sl_price"] = sl_price
            self.retry_count[key] = 0
        else:
            log_event("sl_recreation_failed", {"symbol": symbol, "attempt": self.retry_count[key]})

    def _recreate_tp(self, symbol: str, position: Dict):
        key = symbol + "_tp"
        self.retry_count[key] = self.retry_count.get(key, 0) + 1
        if self.retry_count[key] > self.max_retries:
            self._emergency_close(symbol, position, "tp_retry_exceeded")
            return

        cfg = ASSET_CONFIG.get(symbol, {})
        tp_mult = cfg.get("tp_atr", 1.2)
        atr = self.state[symbol].get("atr") or self.get_atr(symbol)
        if atr is None:
            return

        tp_price = position["entry_price"] + tp_mult * atr if position["side"] == "long" else position["entry_price"] - tp_mult * atr
        side = "sell" if position["side"] == "long" else "buy"

        order = self.client.place_take_profit(
            symbol, side, position["size"], tp_price,
            client_order_id=f"pg_tp_{symbol}_{int(time.time())}"
        )
        if order:
            log_event("tp_recreated", {"symbol": symbol, "price": tp_price})
            self.state[symbol]["tp_price"] = tp_price
            self.retry_count[key] = 0
        else:
            log_event("tp_recreation_failed", {"symbol": symbol, "attempt": self.retry_count[key]})

    def _recreate_trailing(self, symbol: str, position: Dict):
        key = symbol + "_trail"
        self.retry_count[key] = self.retry_count.get(key, 0) + 1
        if self.retry_count[key] > self.max_retries:
            self._emergency_close(symbol, position, "trail_retry_exceeded")
            return

        cfg = ASSET_CONFIG.get(symbol, {})
        callback = cfg.get("trail_callback", 0.50)
        side = "sell" if position["side"] == "long" else "buy"

        order = self.client.place_trailing_stop(
            symbol, side, position["size"], callback,
            client_order_id=f"pg_trail_{symbol}_{int(time.time())}"
        )
        if order:
            log_event("trailing_recreated", {"symbol": symbol, "callback_rate": callback})
            self.state[symbol]["trail_callback"] = callback
            self.retry_count[key] = 0
        else:
            log_event("trailing_recreation_failed", {"symbol": symbol, "attempt": self.retry_count[key]})

    def _check_break_even(self, symbol: str, position: Dict):
        if self.state.get(symbol, {}).get("be_active", False):
            return

        cfg = ASSET_CONFIG.get(symbol, {})
        be_trigger = cfg.get("be_trigger", 0.50)
        be_offset = cfg.get("be_offset", 0.10)
        sl_atr = cfg.get("sl_atr", 1.5)

        ticker = self.client.fetch_ticker(symbol)
        if ticker is None:
            return
        price = ticker["last"]
        entry = position["entry_price"]
        atr = self.state[symbol].get("atr") or self.get_atr(symbol)
        if atr is None:
            return

        r = sl_atr * atr
        distance = be_trigger * r

        if position["side"] == "long" and price >= entry + distance:
            self._activate_break_even(symbol, position, be_offset, sl_atr, atr)
        elif position["side"] == "short" and price <= entry - distance:
            self._activate_break_even(symbol, position, be_offset, sl_atr, atr)

    def _activate_break_even(self, symbol: str, position: Dict, offset: float, sl_atr: float, atr: float):
        entry = position["entry_price"]
        r = sl_atr * atr
        offset_price = offset * r

        if position["side"] == "long":
            sl_price = entry + offset_price
        else:
            sl_price = entry - offset_price

        sl_price = self.client._round_to_tick(sl_price, symbol)

        orders = self.client.fetch_open_orders(symbol)
        sl_order = self._find_order(orders, "stop_market")
        if sl_order:
            self.client.cancel_order(sl_order["id"], symbol)

        side = "sell" if position["side"] == "long" else "buy"
        order = self.client.place_stop_loss(
            symbol, side, position["size"], sl_price,
            client_order_id=f"be_{symbol}_{int(time.time())}"
        )
        if order:
            self.state[symbol]["be_active"] = True
            self.state[symbol]["sl_price"] = sl_price
            log_event("break_even_activated", {"symbol": symbol, "sl_price": sl_price})
        else:
            log_event("break_even_failed", {"symbol": symbol})

    def _emergency_close(self, symbol: str, position: Dict, reason: str):
        side = "sell" if position["side"] == "long" else "buy"
        self.client.place_market_order(symbol, side, position["size"])
        log_event("emergency_close", {"symbol": symbol, "reason": reason})
        for key in list(self.retry_count.keys()):
            if key.startswith(symbol):
                del self.retry_count[key]
        self.state.pop(symbol, None)
        self._save_state()
