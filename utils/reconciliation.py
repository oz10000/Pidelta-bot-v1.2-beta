# utils/reconciliation.py
import logging
import time
from typing import Dict, Optional
from config import ASSET_CONFIG
from utils.telemetry import log_event

logger = logging.getLogger("Reconciliation")


class ReconciliationEngine:
    """
    Motor de reconciliación: exchange es la fuente de verdad.
    Basado en el patrón de NautilusTrader.
    """

    def __init__(self, client, position_guard):
        self.client = client
        self.position_guard = position_guard
        self.config = ASSET_CONFIG

    def reconcile(self) -> Dict[str, bool]:
        """
        Reconciliación completa al inicio.
        Retorna dict con estado por símbolo.
        """
        results = {}
        symbols = list(self.config.keys())

        logger.info("[Reconciliation] Starting state reconciliation...")

        for symbol in symbols:
            try:
                result = self._reconcile_symbol(symbol)
                results[symbol] = result
            except Exception as e:
                logger.error(f"[Reconciliation] Failed for {symbol}: {e}")
                results[symbol] = False

        logger.info("[Reconciliation] Complete.")
        return results

    def _reconcile_symbol(self, symbol: str) -> bool:
        """
        Reconciliación para un símbolo.
        Paso 1: Obtener posición real del exchange.
        Paso 2: Obtener órdenes reales del exchange.
        Paso 3: Alinear estado local.
        """
        position = self.client.fetch_position(symbol)

        if position is None:
            if self.position_guard.has_state(symbol):
                self.position_guard.clear_state(symbol)
                logger.info(f"[Reconciliation] Cleared local state for {symbol} (no position)")
            orders = self.client.fetch_open_orders(symbol)
            if orders:
                self.client.cancel_all_orders(symbol)
                logger.info(f"[Reconciliation] Cancelled {len(orders)} orphan orders for {symbol}")
            return True

        orders = self.client.fetch_open_orders(symbol)

        sl_orders = [o for o in orders if o.get("type") == "stop_market"]
        if not sl_orders:
            self._repair_sl(symbol, position)
            logger.warning(f"[Reconciliation] Repaired missing SL for {symbol}")

        tp_orders = [o for o in orders if o.get("type") == "take_profit_market"]
        if not tp_orders:
            self._repair_tp(symbol, position)
            logger.warning(f"[Reconciliation] Repaired missing TP for {symbol}")

        trail_orders = [o for o in orders if o.get("type") == "trailing_stop"]
        if not trail_orders and self._should_have_trailing(symbol):
            self._repair_trailing(symbol, position)
            logger.warning(f"[Reconciliation] Repaired missing trailing for {symbol}")

        self.position_guard.update_state(symbol, {
            "entry_price": position["entry_price"],
            "side": position["side"],
            "size": position["size"],
            "sl_price": sl_orders[0].get("stopPrice") if sl_orders else None,
            "tp_price": tp_orders[0].get("stopPrice") if tp_orders else None,
            "be_active": False
        })

        log_event("recovery_completed", {"symbol": symbol})
        return True

    def _repair_sl(self, symbol: str, position: Dict):
        cfg = self.config.get(symbol, {})
        sl_mult = cfg.get("sl_atr", 1.5)
        atr = self.position_guard.get_atr(symbol)
        if atr is None:
            logger.error(f"[Reconciliation] Cannot repair SL: no ATR for {symbol}")
            return

        sl_price = position["entry_price"] - sl_mult * atr if position["side"] == "long" else position["entry_price"] + sl_mult * atr
        side = "sell" if position["side"] == "long" else "buy"

        order = self.client.place_stop_loss(
            symbol, side, position["size"], sl_price,
            client_order_id=f"recon_sl_{symbol}_{int(time.time())}"
        )
        if order:
            log_event("sl_recreated", {"symbol": symbol, "price": sl_price, "reason": "reconciliation"})

    def _repair_tp(self, symbol: str, position: Dict):
        cfg = self.config.get(symbol, {})
        tp_mult = cfg.get("tp_atr", 1.2)
        atr = self.position_guard.get_atr(symbol)
        if atr is None:
            return

        tp_price = position["entry_price"] + tp_mult * atr if position["side"] == "long" else position["entry_price"] - tp_mult * atr
        side = "sell" if position["side"] == "long" else "buy"

        order = self.client.place_take_profit(
            symbol, side, position["size"], tp_price,
            client_order_id=f"recon_tp_{symbol}_{int(time.time())}"
        )
        if order:
            log_event("tp_recreated", {"symbol": symbol, "price": tp_price, "reason": "reconciliation"})

    def _repair_trailing(self, symbol: str, position: Dict):
        cfg = self.config.get(symbol, {})
        callback = cfg.get("trail_callback", 0.50)
        side = "sell" if position["side"] == "long" else "buy"

        order = self.client.place_trailing_stop(
            symbol, side, position["size"], callback,
            client_order_id=f"recon_trail_{symbol}_{int(time.time())}"
        )
        if order:
            log_event("trailing_recreated", {"symbol": symbol, "callback_rate": callback, "reason": "reconciliation"})

    def _should_have_trailing(self, symbol: str) -> bool:
        cfg = self.config.get(symbol, {})
        return cfg.get("trail_callback", 0) > 0
