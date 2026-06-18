# utils/order_tracker.py
import logging
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger("OrderTracker")


class InFlightOrder:
    """Estado de una orden en vuelo (similar a Hummingbot InFlightOrder)."""

    def __init__(self, order_id: str, symbol: str, side: str, order_type: str,
                 size: float, price: float = None, client_order_id: str = None):
        self.order_id = order_id
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.size = size
        self.price = price
        self.client_order_id = client_order_id
        self.status = "open"
        self.filled = 0.0
        self.remaining = size
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def update(self, status: str, filled: float = None, remaining: float = None):
        self.status = status
        if filled is not None:
            self.filled = filled
        if remaining is not None:
            self.remaining = remaining
        self.updated_at = datetime.utcnow()

    def is_active(self) -> bool:
        return self.status in ("open", "pending", "submitted")

    def is_closed(self) -> bool:
        return self.status in ("closed", "filled", "canceled", "rejected")


class OrderTracker:
    """
    Rastrea órdenes en vuelo (similar a ClientOrderTracker de Hummingbot).
    Permite detección de duplicados y reconciliación.
    """

    def __init__(self):
        self._orders: Dict[str, InFlightOrder] = {}
        self._client_order_map: Dict[str, str] = {}  # clientOrderId → orderId

    def add_order(self, order: InFlightOrder):
        self._orders[order.order_id] = order
        if order.client_order_id:
            self._client_order_map[order.client_order_id] = order.order_id

    def get_order(self, order_id: str) -> Optional[InFlightOrder]:
        return self._orders.get(order_id)

    def get_by_client_id(self, client_order_id: str) -> Optional[InFlightOrder]:
        order_id = self._client_order_map.get(client_order_id)
        if order_id:
            return self._orders.get(order_id)
        return None

    def update_order(self, order_id: str, status: str, filled: float = None,
                     remaining: float = None):
        order = self._orders.get(order_id)
        if order:
            order.update(status, filled, remaining)

    def remove_order(self, order_id: str):
        order = self._orders.pop(order_id, None)
        if order and order.client_order_id:
            self._client_order_map.pop(order.client_order_id, None)

    def get_active_orders(self) -> List[InFlightOrder]:
        return [o for o in self._orders.values() if o.is_active()]

    def has_active_order_for_symbol(self, symbol: str) -> bool:
        return any(o.symbol == symbol and o.is_active() for o in self._orders.values())

    def reconcile_with_exchange(self, exchange_orders: List[Dict]):
        """
        Reconciliación: alinea el estado local con las órdenes del exchange.
        """
        exchange_order_ids = {o.get("id") for o in exchange_orders}

        for order_id in list(self._orders.keys()):
            if order_id not in exchange_order_ids:
                logger.info(f"[OrderTracker] Removing stale order: {order_id}")
                self.remove_order(order_id)

        for ex_order in exchange_orders:
            order_id = ex_order.get("id")
            status = ex_order.get("status")
            filled = float(ex_order.get("filled", 0))
            remaining = float(ex_order.get("remaining", 0))
            if order_id in self._orders:
                self.update_order(order_id, status, filled, remaining)
