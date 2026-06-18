# execution/client.py
import ccxt
import config
import logging
import time
import random
from typing import Optional, Dict, List

logger = logging.getLogger("OKXClient")


class OKXClient:
    def __init__(self):
        self.exchange = ccxt.okx({
            "apiKey": config.API_KEY,
            "secret": config.SECRET_KEY,
            "password": config.PASSPHRASE,
            "enableRateLimit": True,
        })
        if config.MODE in ("demo", "paper"):
            self.exchange.set_sandbox_mode(True)
        else:
            self.exchange.set_sandbox_mode(False)

        self._mode = None
        self._position_mode = None
        self._instruments = {}

    # ------------------------------------------------------------------
    # ACCOUNT MODE DETECTION
    # ------------------------------------------------------------------
    def _get_account_mode(self) -> str:
        if self._mode:
            return self._mode
        try:
            res = self.exchange.private_get_account_config()
            self._mode = res["data"][0]["posMode"]
            logger.info(f"[OKX] Account mode: {self._mode}")
        except Exception as e:
            logger.warning(f"[OKX] Could not detect account mode: {e}. Assuming long_short_mode.")
            self._mode = "long_short_mode"
        return self._mode

    def _pos_side(self, direction: str) -> Optional[str]:
        mode = self._get_account_mode()
        if mode == "net_mode":
            return None
        return "long" if direction == "long" else "short"

    def _get_tick_size(self, symbol: str) -> float:
        if symbol not in self._instruments:
            market = self.exchange.market(symbol)
            self._instruments[symbol] = market.get("precision", {}).get("price", 0.01)
        return self._instruments[symbol]

    def _round_to_tick(self, price: float, symbol: str) -> float:
        tick = self._get_tick_size(symbol)
        return round(price / tick) * tick

    # ------------------------------------------------------------------
    # BALANCE & TICKER
    # ------------------------------------------------------------------
    def fetch_balance(self) -> float:
        try:
            return self.exchange.fetch_balance().get("USDT", {}).get("free", 0.0)
        except Exception as e:
            logger.error(f"[OKX] fetch_balance error: {e}")
            return 0.0

    def fetch_ticker(self, symbol: str) -> Optional[Dict]:
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"[OKX] fetch_ticker error: {e}")
            return None

    # ------------------------------------------------------------------
    # POSITIONS (HEDGE MODE SAFE)
    # ------------------------------------------------------------------
    def fetch_position(self, symbol: str) -> Optional[Dict]:
        try:
            positions = self.exchange.fetch_positions([symbol])
            net_size = 0.0
            entry_price = 0.0
            count = 0

            for p in positions:
                size = float(p.get("contracts", 0))
                if size == 0:
                    continue

                side = p.get("side")
                if side == "long":
                    net_size += size
                elif side == "short":
                    net_size -= size
                else:
                    net_size = size

                p_entry = float(p.get("entryPrice", 0))
                if p_entry > 0:
                    entry_price = (entry_price * count + p_entry) / (count + 1)
                    count += 1

            if net_size == 0:
                return None

            return {
                "side": "long" if net_size > 0 else "short",
                "size": abs(net_size),
                "entry_price": entry_price if entry_price > 0 else float(p.get("entryPrice", 0))
            }
        except Exception as e:
            logger.error(f"[OKX] fetch_position error: {e}")
            return None

    def has_open_position(self, symbol: str) -> bool:
        return self.fetch_position(symbol) is not None

    # ------------------------------------------------------------------
    # OPEN ORDERS (CONDITIONAL ORDERS SUPPORT)
    # ------------------------------------------------------------------
    def fetch_open_orders(self, symbol: str) -> List[Dict]:
        all_orders = []
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            all_orders.extend(orders)
        except Exception as e:
            logger.error(f"[OKX] fetch_open_orders (normal) error: {e}")

        try:
            params = {"ordType": "conditional"}
            cond_orders = self.exchange.fetch_open_orders(symbol, None, None, params)
            all_orders.extend(cond_orders)
        except Exception as e:
            logger.error(f"[OKX] fetch_open_orders (conditional) error: {e}")

        return all_orders

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            self.exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            logger.error(f"[OKX] cancel_order error: {e}")
            return False

    def cancel_all_orders(self, symbol: str) -> bool:
        try:
            orders = self.fetch_open_orders(symbol)
            for order in orders:
                self.cancel_order(order["id"], symbol)
            return True
        except Exception as e:
            logger.error(f"[OKX] cancel_all_orders error: {e}")
            return False

    # ------------------------------------------------------------------
    # MARKET ORDER (IDEMPOTENT)
    # ------------------------------------------------------------------
    def place_market_order(self, symbol: str, side: str, size: float,
                           client_order_id: Optional[str] = None) -> Optional[Dict]:
        if client_order_id is None:
            client_order_id = f"mkt_{symbol}_{int(time.time())}_{random.randint(1000,9999)}"

        direction = "long" if side == "buy" else "short"
        pos_side = self._pos_side(direction)

        params = {
            "tdMode": "isolated",
            "clientOrderId": client_order_id,
        }
        if pos_side:
            params["posSide"] = pos_side

        for attempt in range(3):
            try:
                order = self.exchange.create_order(
                    symbol, "market", side, size, None, params
                )
                if order and order.get("id"):
                    logger.info(f"[OKX] Market order placed: {order['id']}")
                    return order
            except Exception as e:
                logger.warning(f"[OKX] place_market_order attempt {attempt+1}: {e}")
                time.sleep(2 ** attempt)
        return None

    # ------------------------------------------------------------------
    # PROTECTION ORDERS (IDEMPOTENT, TICK-SIZE AWARE)
    # ------------------------------------------------------------------
    def place_stop_loss(self, symbol: str, side: str, size: float,
                        price: float, client_order_id: Optional[str] = None) -> Optional[Dict]:
        return self._place_protection(
            symbol, side, size, price, "slTriggerPx", "slOrdPx",
            client_order_id or f"sl_{symbol}_{int(time.time())}"
        )

    def place_take_profit(self, symbol: str, side: str, size: float,
                          price: float, client_order_id: Optional[str] = None) -> Optional[Dict]:
        return self._place_protection(
            symbol, side, size, price, "tpTriggerPx", "tpOrdPx",
            client_order_id or f"tp_{symbol}_{int(time.time())}"
        )

    def _place_protection(self, symbol: str, side: str, size: float,
                          price: float, px_key: str, ord_key: str,
                          client_order_id: str) -> Optional[Dict]:
        existing = self._find_order_by_client_id(symbol, client_order_id)
        if existing:
            logger.info(f"[OKX] Order {client_order_id} already exists, skipping")
            return existing

        price = self._round_to_tick(price, symbol)

        direction = "long" if side == "sell" else "short"
        pos_side = self._pos_side(direction)

        params = {
            "tdMode": "isolated",
            "reduceOnly": True,
            "clientOrderId": client_order_id,
            px_key: price,
            ord_key: price,
        }
        if pos_side:
            params["posSide"] = pos_side

        for attempt in range(3):
            try:
                order = self.exchange.create_order(
                    symbol, "market", side, size, None, params
                )
                if order and order.get("id"):
                    logger.info(f"[OKX] Protection order placed: {order['id']}")
                    return order
            except Exception as e:
                logger.warning(f"[OKX] _place_protection attempt {attempt+1}: {e}")
                time.sleep(2 ** attempt)
        return None

    def _find_order_by_client_id(self, symbol: str, client_order_id: str) -> Optional[Dict]:
        orders = self.fetch_open_orders(symbol)
        for order in orders:
            if order.get("clientOrderId") == client_order_id:
                return order
        return None

    # ------------------------------------------------------------------
    # TRAILING STOP (NATIVO OKX, IDEMPOTENT)
    # ------------------------------------------------------------------
    def place_trailing_stop(self, symbol: str, side: str, size: float,
                            callback_rate: float,
                            client_order_id: Optional[str] = None) -> Optional[Dict]:
        if client_order_id is None:
            client_order_id = f"trail_{symbol}_{int(time.time())}"

        existing = self._find_order_by_client_id(symbol, client_order_id)
        if existing:
            logger.info(f"[OKX] Trailing order {client_order_id} already exists, skipping")
            return existing

        direction = "long" if side == "sell" else "short"
        pos_side = self._pos_side(direction)

        params = {
            "tdMode": "isolated",
            "reduceOnly": True,
            "ordType": "trailing_stop",
            "callbackRate": str(callback_rate),
            "clientOrderId": client_order_id,
        }
        if pos_side:
            params["posSide"] = pos_side

        for attempt in range(3):
            try:
                order = self.exchange.create_order(
                    symbol, "market", side, size, None, params
                )
                if order and order.get("id"):
                    logger.info(f"[OKX] Trailing stop placed: {order['id']}")
                    return order
            except Exception as e:
                logger.warning(f"[OKX] place_trailing_stop attempt {attempt+1}: {e}")
                time.sleep(2 ** attempt)
        return None

    # ------------------------------------------------------------------
    # ORDER STATUS
    # ------------------------------------------------------------------
    def fetch_order(self, order_id: str, symbol: str) -> Optional[Dict]:
        try:
            return self.exchange.fetch_order(order_id, symbol)
        except Exception as e:
            logger.error(f"[OKX] fetch_order error: {e}")
            return None
