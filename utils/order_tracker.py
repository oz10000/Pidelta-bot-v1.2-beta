import time
from typing import Dict, Optional, List
from execution.client import OKXClient

class InFlightOrder:
    def __init__(self, symbol, side, size, order_id, cl_ord_id):
        self.symbol = symbol
        self.side = side
        self.size = size
        self.order_id = order_id
        self.cl_ord_id = cl_ord_id
        self.placed_at = time.time()
        self.filled = False
        self.cancelled = False

class OrderTracker:
    """
    Rastreador de órdenes en vuelo. DEPRECADO PARCIALMENTE en favor de EventStore,
    pero mantenido para compatibilidad.
    """
    def __init__(self, client: OKXClient):
        self.client = client
        self.orders: Dict[str, InFlightOrder] = {}

    def add(self, order: InFlightOrder):
        self.orders[order.order_id] = order

    def get(self, order_id) -> Optional[InFlightOrder]:
        return self.orders.get(order_id)

    def sync_with_exchange(self, symbol: str):
        """Sincroniza el tracker con el exchange (cancela si no existe)."""
        open_orders = self.client.fetch_open_orders(symbol)
        open_ids = {o["id"] for o in open_orders}
        for oid, tracked in list(self.orders.items()):
            if oid not in open_ids and not tracked.filled:
                tracked.cancelled = True
