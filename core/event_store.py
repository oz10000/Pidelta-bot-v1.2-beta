import json
import time
import os
from typing import List, Dict, Optional

class EventStore:
    """
    Event Store persistente en JSONL.
    Cada evento es append-only, permitiendo reconstruir el estado exacto post-crash.
    """

    def __init__(self, filepath: str = "data/events.jsonl"):
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self._cache: List[Dict] = []
        self._load()

    def _load(self) -> None:
        """Carga eventos existentes en memoria caché."""
        try:
            with open(self.filepath, "r") as f:
                for line in f:
                    if line.strip():
                        self._cache.append(json.loads(line))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def append(self, event_type: str, payload: Dict) -> Dict:
        """Guarda un evento y lo persiste inmediatamente en disco."""
        event = {
            "ts": time.time(),
            "type": event_type,
            "payload": payload
        }
        self._cache.append(event)
        with open(self.filepath, "a") as f:
            f.write(json.dumps(event) + "\n")
        return event

    def get_events(self) -> List[Dict]:
        """Retorna todos los eventos (replay)."""
        return self._cache.copy()

    def get_latest_by_type(self, event_type: str) -> Optional[Dict]:
        """Obtiene el último evento de un tipo específico."""
        for e in reversed(self._cache):
            if e["type"] == event_type:
                return e
        return None

    def get_positions(self) -> List[Dict]:
        """
        Reconstruye las posiciones actuales basado en eventos.
        Retorna las posiciones que están OPEN y no han sido CLOSED.
        """
        positions = {}
        for e in self._cache:
            if e["type"] == "POSITION_OPEN":
                key = e["payload"]["symbol"]
                positions[key] = e["payload"]
            elif e["type"] == "POSITION_CLOSED":
                key = e["payload"]["symbol"]
                if key in positions:
                    del positions[key]
        return list(positions.values())
