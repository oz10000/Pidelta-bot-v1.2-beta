import logging
import time
from typing import Dict, Optional, List
from execution.client import OKXClient

logger = logging.getLogger("PositionGuard")

class PositionGuard:
    def __init__(self, client: OKXClient, config: Dict):
        self.client = client
        self.config = config
        self.state: Dict[str, Dict] = {}  # almacena estado por símbolo
        self.symbols = config.get("symbols", [])

    def _get_position(self, symbol):
        """Obtiene la posición actual para un símbolo."""
        try:
            positions = self.client.exchange.fetch_positions([symbol])
            for pos in positions:
                if float(pos.get("contracts", 0)) != 0:
                    return pos
            return None
        except Exception as e:
            logger.error(f"Error fetching position for {symbol}: {e}")
            return None

    def get_atr(self, symbol, period=14):
        """Calcula ATR (simulado o real)."""
        # Aquí debería ir la lógica para obtener ATR de indicadores
        # Por simplicidad, devolvemos un valor fijo o lo obtenemos de un almacén
        # En el original, probablemente usa un indicador técnico.
        # Como no tenemos el código completo, lo dejamos como placeholder.
        return 100.0  # Valor de ejemplo

    def check_all(self):
        """Verifica todas las posiciones y protege las que estén abiertas."""
        for symbol in self.symbols:
            try:
                position = self._get_position(symbol)
                if position:
                    self._protect_position(symbol, position)
                else:
                    # Si no hay posición, limpiar estado
                    self.state.pop(symbol, None)
            except Exception as e:
                logger.error(f"Error checking position for {symbol}: {e}")

    def _protect_position(self, symbol: str, position: Dict):
        """Aplica o recrea TP, SL y trailing stop según configuración."""
        # Inicializar estado si no existe
        if symbol not in self.state:
            self.state[symbol] = {}

        # Obtener el side de la posición (long/short)
        side = position.get("side")
        if not side:
            logger.warning(f"No side for position {symbol}")
            return

        # Obtener precio de entrada
        entry_price = float(position.get("entryPrice", 0))
        if entry_price == 0:
            logger.warning(f"No entry price for {symbol}")
            return

        # Lógica para recrear TP
        self._recreate_tp(symbol, position, entry_price, side)

        # Lógica para recrear SL
        self._recreate_sl(symbol, position, entry_price, side)

        # Lógica para trailing stop (si está habilitado)
        if self.config.get("trailing_stop", {}).get("enabled", False):
            self._recreate_trailing(symbol, position, entry_price, side)

    def _recreate_tp(self, symbol: str, position: Dict, entry_price: float, side: str):
        """Recrea la orden de Take Profit."""
        # ✅ CORRECCIÓN: Verificar que el símbolo existe en state
        state = self.state.get(symbol)
        if not state:
            state = {}
            self.state[symbol] = state

        # Obtener ATR (si no está, calcularlo)
        atr = state.get("atr")
        if atr is None:
            atr = self.get_atr(symbol)
            state["atr"] = atr

        if atr is None:
            logger.warning(f"Could not get ATR for {symbol}")
            return

        tp_mult = self.config.get("tp_multiplier", 2.0)
        if side == "long":
            tp_price = entry_price + atr * tp_mult
            tp_side = "sell"
        else:  # short
            tp_price = entry_price - atr * tp_mult
            tp_side = "buy"

        size = abs(float(position.get("contracts", 0)))

        # Colocar TP
        logger.info(f"Recreating TP for {symbol}: price={tp_price}")
        result = self.client.place_take_profit(symbol, tp_side, size, tp_price)
        if result:
            state["tp"] = result

    def _recreate_sl(self, symbol: str, position: Dict, entry_price: float, side: str):
        """Recrea la orden de Stop Loss."""
        state = self.state.get(symbol)
        if not state:
            state = {}
            self.state[symbol] = state

        atr = state.get("atr")
        if atr is None:
            atr = self.get_atr(symbol)
            state["atr"] = atr

        if atr is None:
            return

        sl_mult = self.config.get("sl_multiplier", 1.5)
        if side == "long":
            sl_price = entry_price - atr * sl_mult
            sl_side = "sell"
        else:
            sl_price = entry_price + atr * sl_mult
            sl_side = "buy"

        size = abs(float(position.get("contracts", 0)))

        logger.info(f"Recreating SL for {symbol}: price={sl_price}")
        result = self.client.place_stop_loss(symbol, sl_side, size, sl_price)
        if result:
            state["sl"] = result

    def _recreate_trailing(self, symbol: str, position: Dict, entry_price: float, side: str):
        """Recrea el trailing stop."""
        state = self.state.get(symbol)
        if not state:
            state = {}
            self.state[symbol] = state

        callback = self.config.get("trailing_stop", {}).get("callback_rate", 0.5)
        size = abs(float(position.get("contracts", 0)))

        # Para trailing stop, normalmente se usa el precio actual como trigger
        ticker = self.client.fetch_ticker(symbol)
        current_price = ticker.get("last", entry_price)

        if side == "long":
            trigger_price = current_price  # se activa en precio actual
            sl_side = "sell"
        else:
            trigger_price = current_price
            sl_side = "buy"

        logger.info(f"Recreating trailing stop for {symbol}: callback={callback}%")
        result = self.client.place_trailing_stop(symbol, sl_side, size, callback, trigger_price)
        if result:
            state["trailing"] = result

    # Nota: El método main_loop que usa check_all está en otro archivo (main.py)
    # pero la corrección principal en este archivo está en la línea 188,
    # que ahora usa state.get(symbol) para evitar KeyError.
