import ccxt
import hashlib
import time
import logging
from typing import Optional, Dict, List

import config  # Importa el módulo config global

logger = logging.getLogger("OKXClient")

class OKXClient:
    def __init__(self):
        self.ex = ccxt.okx({
            "apiKey": config.OKX_API_KEY,      # Usa OKX_API_KEY
            "secret": config.OKX_SECRET,
            "password": config.OKX_PASSPHRASE,
            "enableRateLimit": True,
            "options": {"defaultType": "future"}  # Asegura futuros swap
        })
        self.strategy_version = config.STRATEGY_VERSION
        self.session_id = config.SESSION_ID
        self.prefix = config.BOT_CL_ORD_PREFIX
        self._pos_mode = None

    # ========================================================================
    # 1. IDEMPOTENCIA Y DETERMINISMO
    # ========================================================================
    def _generate_cl_ord_id(self, symbol: str, side: str, kind: str) -> str:
        """
        Genera clOrdId DETERMINISTA.
        Basado en símbolo, lado, tipo y versión de estrategia.
        """
        raw = f"{symbol}:{side}:{kind}:{self.strategy_version}:{self.session_id}"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
        return f"{self.prefix}_{digest}"

    def _is_my_order(self, order: Dict) -> bool:
        """Verifica si la orden pertenece a este bot por el clOrdId."""
        cl = order.get("clientOrderId", "")
        return cl.startswith(f"{self.prefix}_")

    # ========================================================================
    # 2. HELPERS DE POSICIÓN Y MODO
    # ========================================================================
    def _get_pos_mode(self) -> str:
        if self._pos_mode:
            return self._pos_mode
        try:
            res = self.ex.private_get_account_config()
            self._pos_mode = res["data"][0]["posMode"]
        except Exception:
            self._pos_mode = "net_mode"
        return self._pos_mode

    def _pos_side(self, side: str) -> Optional[str]:
        mode = self._get_pos_mode()
        if mode == "net_mode":
            return None
        return "long" if side == "buy" else "short"

    def _round_contracts(self, symbol: str, size: float) -> int:
        market = self.ex.market(symbol)
        if market.get("linear"):
            lot = market.get("precision", {}).get("amount", 1)
            return max(1, int(round(size / lot) * lot))
        return max(1, int(round(size)))

    # ========================================================================
    # 3. FETCH Y SINCRONIZACIÓN
    # ========================================================================
    def fetch_balance(self) -> float:
        bal = self.ex.fetch_balance()
        return bal.get("USDT", {}).get("free", 0.0)

    def fetch_ticker(self, symbol: str) -> Dict:
        return self.ex.fetch_ticker(symbol)

    def fetch_position(self, symbol: str) -> Optional[Dict]:
        try:
            positions = self.ex.fetch_positions([symbol])
            for p in positions:
                if float(p.get("contracts", 0)) != 0:
                    return p
            return None
        except Exception as e:
            logger.error(f"Error fetching position {symbol}: {e}")
            return None

    def fetch_open_orders(self, symbol: str) -> List[Dict]:
        try:
            return self.ex.fetch_open_orders(symbol)
        except Exception as e:
            logger.error(f"Error fetching open orders {symbol}: {e}")
            return []

    def find_order_by_clord(self, symbol: str, cl_ord_id: str) -> Optional[Dict]:
        try:
            for o in self.fetch_open_orders(symbol):
                if o.get("clientOrderId") == cl_ord_id:
                    return o
            closed = self.ex.fetch_closed_orders(symbol, limit=100)
            for o in closed:
                if o.get("clientOrderId") == cl_ord_id:
                    return o
        except Exception as e:
            logger.debug(f"Find order error: {e}")
        return None

    # ========================================================================
    # 4. ORDEN MARKET CON ESPERA DE FILL
    # ========================================================================
    def place_market_order(self, symbol: str, side: str, size: float) -> Optional[Dict]:
        size = self._round_contracts(symbol, size)
        cl = self._generate_cl_ord_id(symbol, side, "entry")
        pos_side = self._pos_side(side)

        params = {
            "tdMode": "isolated",
            "clOrdId": cl,
            "reduceOnly": False,
        }
        if pos_side:
            params["posSide"] = pos_side

        logger.info(f"Market order: {symbol} {side} {size} | clOrdId={cl}")

        try:
            order = self.ex.create_order(symbol, "market", side, size, None, params)
            order_id = order.get("id")
            if not order_id:
                logger.error("Market order sent but no order ID returned")
                return order

            # Polling de fill
            start_time = time.time()
            while time.time() - start_time < config.FILL_TIMEOUT_SECONDS:
                try:
                    status = self.ex.fetch_order(order_id, symbol)
                    if status.get("status") == "closed":
                        filled = float(status.get("filled", 0))
                        if filled > 0:
                            logger.info(f"Market order FILLED: {filled} contracts")
                            return status
                    elif status.get("status") == "canceled":
                        logger.warning(f"Market order {order_id} was canceled")
                        return status
                    elif status.get("status") == "open":
                        logger.debug(f"Order {order_id} still open... waiting")
                    time.sleep(config.API_POLL_INTERVAL)
                except Exception as e:
                    logger.debug(f"Polling error: {e}")
                    time.sleep(config.API_POLL_INTERVAL)

            logger.error(f"Market order {order_id} NOT filled within {config.FILL_TIMEOUT_SECONDS}s")
            return order

        except Exception as e:
            logger.error(f"Error placing market order: {e}")
            return None

    # ========================================================================
    # 5. PROTECCIONES (SL/TP/TRAILING) CON PARÁMETROS OKX V5 CORRECTOS
    # ========================================================================
    def _place_conditional(
        self,
        symbol: str,
        side: str,
        size: float,
        kind: str,
        trigger_price: Optional[float] = None,
        callback_rate: Optional[float] = None
    ) -> Optional[Dict]:
        size = self._round_contracts(symbol, size)

        # Verificar posición
        position = self.fetch_position(symbol)
        if position is None:
            logger.warning(f"Cannot place {kind}: No position exists for {symbol}")
            return None

        # Idempotencia
        cl = self._generate_cl_ord_id(symbol, side, kind)
        existing = self.find_order_by_clord(symbol, cl)
        if existing:
            logger.info(f"{kind.upper()} already exists: {cl}")
            return existing

        pos_side = self._pos_side(side)
        params = {
            "tdMode": "isolated",
            "reduceOnly": True,
            "clOrdId": cl,
            "ordType": "conditional",
            "triggerPxType": "last",    # OKX requiere esto
            "ordPx": "-1",              # Ejecución a mercado
            "sz": str(size),
            "side": side,
        }
        if pos_side:
            params["posSide"] = pos_side

        if trigger_price is not None:
            params["triggerPx"] = str(round(trigger_price, 2))

        if callback_rate is not None:
            params["callbackRate"] = str(callback_rate)

        try:
            logger.info(f"Placing {kind}: {symbol} {side} | trig={trigger_price} cb={callback_rate} | cl={cl}")
            order = self.ex.create_order(symbol, "market", side, size, None, params)
            logger.info(f"{kind.upper()} placed: {order.get('id')}")
            return order
        except Exception as e:
            logger.error(f"Error placing {kind}: {e}")
            return None

    def place_stop_loss(self, symbol: str, side: str, size: float, price: float) -> Optional[Dict]:
        return self._place_conditional(symbol, side, size, "sl", trigger_price=price)

    def place_take_profit(self, symbol: str, side: str, size: float, price: float) -> Optional[Dict]:
        return self._place_conditional(symbol, side, size, "tp", trigger_price=price)

    def place_trailing_stop(self, symbol: str, side: str, size: float, callback_rate: float, trigger_price: Optional[float] = None) -> Optional[Dict]:
        return self._place_conditional(symbol, side, size, "trail", trigger_price=trigger_price, callback_rate=callback_rate)

    # ========================================================================
    # 6. CANCELACIÓN SEGURA (SOLO ÓRDENES DEL BOT)
    # ========================================================================
    def cancel_orders_by_prefix(self, symbol: str) -> int:
        orders = self.fetch_open_orders(symbol)
        cancelled = 0
        for o in orders:
            if self._is_my_order(o):
                try:
                    self.ex.cancel_order(o["id"], symbol)
                    cancelled += 1
                    logger.debug(f"Cancelled order {o['id']} ({o.get('clientOrderId')})")
                except Exception as e:
                    logger.warning(f"Error cancelling {o['id']}: {e}")
        if cancelled:
            logger.info(f"Cancelled {cancelled} bot orders for {symbol}")
        return cancelled
