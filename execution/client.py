import ccxt
import config
import logging
import time
import re
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
        self._mode = None

    def _get_mode(self):
        if self._mode:
            return self._mode
        try:
            res = self.exchange.private_get_account_config()
            self._mode = res["data"][0]["posMode"]
        except Exception:
            self._mode = "long_short_mode"
        return self._mode

    def _pos_side(self, direction):
        mode = self._get_mode()
        if mode == "net_mode":
            return None
        return "long" if direction == "long" else "short"

    def _generate_cl_ord_id(self, prefix, symbol):
        """Genera un clOrdId válido para OKX (alfanumérico, comienza con letra, máx 32)."""
        clean_symbol = re.sub(r'[/:]', '_', symbol)
        base = f"{prefix}_{clean_symbol}_{int(time.time() * 1000)}"
        if not base[0].isalpha():
            base = f"p{base}"
        if len(base) > 32:
            base = base[:32]
        return base

    def _round_to_tick(self, price, symbol):
        """Redondea el precio al tick size del mercado."""
        market = self.exchange.market(symbol)
        tick_size = market.get("precision", {}).get("price", 0.01)
        return round(price / tick_size) * tick_size

    def _find_order_by_client_id(self, symbol, cl_ord_id):
        """Busca una orden existente por clOrdId."""
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            for order in orders:
                if order.get("clientOrderId") == cl_ord_id:
                    return order
        except Exception:
            pass
        return None

    def fetch_balance(self):
        return self.exchange.fetch_balance().get("USDT", {}).get("free", 0.0)

    def fetch_ticker(self, symbol):
        return self.exchange.fetch_ticker(symbol)

    def place_market_order(self, symbol, side, size):
        try:
            direction = "long" if side == "buy" else "short"
            pos_side = self._pos_side(direction)
            cl_ord_id = self._generate_cl_ord_id("mkt", symbol)

            params = {
                "tdMode": "isolated",
                "clOrdId": cl_ord_id,          # ✅ CORREGIDO: antes usaba "clientOrderId"
            }
            if pos_side:
                params["posSide"] = pos_side

            return self.exchange.create_order(symbol, "market", side, size, None, params)
        except Exception as e:
            logger.error(f"place_market_order error: {e}")
            return None

    def _place_protection(self, symbol: str, side: str, size: float, price: float,
                          px_key: str, ord_key: str, prefix: str) -> Optional[Dict]:
        """Coloca una orden de protección (TP o SL) con idempotencia."""
        cl_ord_id = self._generate_cl_ord_id(prefix, symbol)
        existing = self._find_order_by_client_id(symbol, cl_ord_id)
        if existing:
            return existing

        price = self._round_to_tick(price, symbol)
        direction = "long" if side == "sell" else "short"
        pos_side = self._pos_side(direction)

        params = {
            "tdMode": "isolated",
            "reduceOnly": True,
            "clOrdId": cl_ord_id,               # ✅ CORREGIDO: "clientOrderId" → "clOrdId"
            "ordType": "conditional",            # ✅ CORREGIDO: añadido ordType
            px_key: price,
            ord_key: price,
        }
        if pos_side:
            params["posSide"] = pos_side

        try:
            return self.exchange.create_order(symbol, "market", side, size, None, params)
        except Exception as e:
            logger.error(f"_place_protection error ({prefix}): {e}")
            return None

    def place_take_profit(self, symbol, side, size, price):
        return self._place_protection(symbol, side, size, price, "tpTriggerPx", "tpOrdPx", "tp")

    def place_stop_loss(self, symbol, side, size, price):
        return self._place_protection(symbol, side, size, price, "slTriggerPx", "slOrdPx", "sl")

    def place_trailing_stop(self, symbol, side, size, callback_rate, trigger_price=None):
        """Coloca un trailing stop usando orden condicional."""
        try:
            direction = "long" if side == "sell" else "short"
            pos_side = self._pos_side(direction)
            cl_ord_id = self._generate_cl_ord_id("trail", symbol)

            params = {
                "tdMode": "isolated",
                "reduceOnly": True,
                "clOrdId": cl_ord_id,               # ✅ CORREGIDO
                "ordType": "conditional",            # ✅ CORREGIDO: antes "trailing_stop"
                "callbackRate": str(callback_rate),
            }
            if trigger_price:
                params["triggerPx"] = str(trigger_price)
                params["triggerPxType"] = "last"   # o "mark"
            if pos_side:
                params["posSide"] = pos_side

            return self.exchange.create_order(symbol, "market", side, size, None, params)
        except Exception as e:
            logger.error(f"place_trailing_stop error: {e}")
            return None
