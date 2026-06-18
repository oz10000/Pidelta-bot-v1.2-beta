import logging
from typing import Dict, Optional
from execution.client import OKXClient
from core.event_store import EventStore

logger = logging.getLogger("ExecutionEngine")

class ExecutionEngine:
    def __init__(self, client: OKXClient, store: EventStore):
        self.client = client
        self.store = store

    def execute_entry(self, signal: Dict, price: float, equity: float) -> bool:
        """
        Ejecuta una orden de entrada y coloca las protecciones.
        Retorna True si la operación fue exitosa.
        """
        symbol = signal["symbol"]
        side = "buy" if signal["side"] == "long" else "sell"
        size = signal.get("size", 0.0)
        config = signal.get("config", {})
        atr = signal.get("atr", 100.0)

        # === 1. VERIFICAR QUE NO HAY POSICIÓN (PREVIENE DUPLICACIÓN) ===
        if self.client.fetch_position(symbol) is not None:
            logger.warning(f"Position already exists for {symbol}. Skipping entry.")
            return False

        if size <= 0:
            logger.error(f"Invalid size {size} for {symbol}")
            return False

        # === 2. MARKET ORDER CON ESPERA DE FILL ===
        order = self.client.place_market_order(symbol, side, size)
        if not order or order.get("status") != "closed":
            logger.error(f"Market order failed or not filled for {symbol}")
            return False

        # === 3. VERIFICAR POSICIÓN REAL POST-FILL ===
        position = self.client.fetch_position(symbol)
        if position is None:
            logger.error(f"Position not found after fill for {symbol}")
            return False

        entry_price = float(position.get("entryPrice", price))
        logger.info(f"Position opened: {symbol} {side} @ {entry_price}")

        # === 4. COLOCAR PROTECCIONES ===
        self._place_protections(symbol, side, size, entry_price, config, atr)

        # === 5. EVENT SOURCING ===
        self.store.append("POSITION_OPEN", {
            "symbol": symbol,
            "side": signal["side"],
            "price": entry_price,
            "size": size
        })

        return True

    def _place_protections(self, symbol: str, side: str, size: float, entry_price: float, config: Dict, atr: float):
        """Coloca TP, SL y Trailing con los parámetros configurados."""
        # Take Profit
        tp_mult = config.get("tp_atr", 1.0)
        tp_price = entry_price + tp_mult * atr if side == "buy" else entry_price - tp_mult * atr
        tp_side = "sell" if side == "buy" else "buy"
        self.client.place_take_profit(symbol, tp_side, size, tp_price)

        # Stop Loss
        sl_mult = config.get("sl_atr", 1.5)
        sl_price = entry_price - sl_mult * atr if side == "buy" else entry_price + sl_mult * atr
        sl_side = "sell" if side == "buy" else "buy"
        self.client.place_stop_loss(symbol, sl_side, size, sl_price)

        # Trailing Stop
        trail_cb = config.get("trail_callback", 0.0)
        if trail_cb > 0:
            trail_side = "sell" if side == "buy" else "buy"
            self.client.place_trailing_stop(symbol, trail_side, size, trail_cb)
            logger.info(f"Trailing stop placed: {symbol} callback={trail_cb}%")
