import logging
import time
from typing import Dict, Optional
from execution.client import OKXClient
from core.event_store import EventStore
from config import ASSET_CONFIG

logger = logging.getLogger("Reconciler")

class ReconciliationEngine:
    def __init__(self, client: OKXClient, store: EventStore):
        self.client = client
        self.store = store
        self.config = ASSET_CONFIG

    def reconcile_symbol(self, symbol: str) -> bool:
        """
        Reconciliación para un símbolo:
        1. Obtiene posición real.
        2. Obtiene órdenes abiertas (solo del bot).
        3. Repara SL/TP faltantes.
        4. Limpia órdenes huérfanas si no hay posición.
        """
        try:
            # 1. POSICIÓN
            position = self.client.fetch_position(symbol)

            # 2. ORDENES ABIERTAS DEL BOT
            all_orders = self.client.fetch_open_orders(symbol)
            bot_orders = [o for o in all_orders if self.client._is_my_order(o)]

            if position is None:
                # No hay posición → limpiar órdenes huérfanas del bot
                if bot_orders:
                    self.client.cancel_orders_by_prefix(symbol)
                # Marcar cierre en event store
                self.store.append("POSITION_CLOSED", {"symbol": symbol, "reason": "reconciled"})
                logger.info(f"Reconciler: Cleaned up {symbol} (no position)")
                return True

            # 3. HAY POSICIÓN: EXTRAER DATOS
            side = position.get("side")
            size = abs(float(position.get("contracts", 0)))
            entry = float(position.get("entryPrice", 0))

            # Clasificar órdenes existentes del bot
            sl_exists = any("sl" in o.get("clientOrderId", "") for o in bot_orders)
            tp_exists = any("tp" in o.get("clientOrderId", "") for o in bot_orders)
            trail_exists = any("trail" in o.get("clientOrderId", "") for o in bot_orders)

            # Obtener ATR (idealmente de datos reales, aquí placeholder)
            atr = 100.0  # TODO: Conectar con data/ohlcv.py para ATR real
            cfg = self.config.get(symbol, {})

            # 4. REPARAR SL (SI FALTA)
            if not sl_exists:
                sl_mult = cfg.get("sl_atr", 1.5)
                sl_side = "sell" if side == "long" else "buy"
                sl_price = entry - sl_mult * atr if side == "long" else entry + sl_mult * atr
                self.client.place_stop_loss(symbol, sl_side, size, sl_price)
                logger.warning(f"Reconciler: REPAIRED SL for {symbol}")

            # 5. REPARAR TP (SI FALTA)
            if not tp_exists:
                tp_mult = cfg.get("tp_atr", 1.0)
                tp_side = "sell" if side == "long" else "buy"
                tp_price = entry + tp_mult * atr if side == "long" else entry - tp_mult * atr
                self.client.place_take_profit(symbol, tp_side, size, tp_price)
                logger.warning(f"Reconciler: REPAIRED TP for {symbol}")

            # 6. REPARAR TRAILING (SI FALLA Y ESTÁ CONFIGURADO)
            trail_cb = cfg.get("trail_callback", 0.0)
            if trail_cb > 0 and not trail_exists:
                trail_side = "sell" if side == "long" else "buy"
                self.client.place_trailing_stop(symbol, trail_side, size, trail_cb)
                logger.warning(f"Reconciler: REPAIRED Trailing for {symbol}")

            # 7. ACTUALIZAR EVENT STORE
            self.store.append("POSITION_SYNC", {
                "symbol": symbol,
                "side": side,
                "size": size,
                "entry": entry
            })

            return True

        except Exception as e:
            logger.error(f"Reconciliation error for {symbol}: {e}")
            return False
