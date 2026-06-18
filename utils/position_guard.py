import logging
from typing import Dict, Optional
from core.event_store import EventStore

logger = logging.getLogger("PositionGuard")

class PositionGuard:
    """
    Caché de estado local. La fuente de verdad es el exchange + EventStore.
    Se usa para reducir llamadas API durante el ciclo principal.
    """
    def __init__(self, store: EventStore):
        self.store = store
        self._cache: Dict[str, Dict] = {}

    def update(self, symbol: str, data: Dict) -> None:
        """Actualiza caché (normalmente llamado tras reconciliación)."""
        self._cache[symbol] = data
        # También guarda un evento para trazabilidad
        self.store.append("STATE_CACHE_UPDATE", {"symbol": symbol, "data": data})

    def get(self, symbol: str) -> Optional[Dict]:
        """Obtiene estado del caché, o intenta desde el event store."""
        if symbol in self._cache:
            return self._cache[symbol]
        # Reconstruir desde event store
        latest = self.store.get_latest_by_type("POSITION_SYNC")
        if latest and latest["payload"]["symbol"] == symbol:
            return latest["payload"]
        return None

    def clear(self, symbol: str) -> None:
        if symbol in self._cache:
            del self._cache[symbol]
