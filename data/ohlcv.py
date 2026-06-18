import ccxt
import pandas as pd
import numpy as np
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 1. FUNCIÓN ORIGINAL: OBTENER OHLCV DESDE OKX
# ----------------------------------------------------------------------
def fetch_ohlcv(symbol: str, timeframe: str = "5m", limit: int = 200) -> pd.DataFrame:
    """
    Obtiene velas OHLCV desde OKX y las retorna como DataFrame.
    Parámetros:
        symbol: par (ej. 'BTC/USDT:USDT')
        timeframe: intervalo (ej. '5m', '1h')
        limit: número de velas
    Retorna:
        DataFrame con columnas: timestamp, open, high, low, close, volume
    """
    try:
        exchange = ccxt.okx({
            "enableRateLimit": True,
            "options": {"defaultType": "future"}  # swap perpetuo
        })
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol}: {e}")
        return pd.DataFrame()

# ----------------------------------------------------------------------
# 2. FUNCIÓN NUEVA: CÁLCULO DE ATR (para sizing y SL/TP dinámicos)
# ----------------------------------------------------------------------
def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calcula el Average True Range (ATR) a partir de un DataFrame OHLCV.
    Retorna un valor flotante, o un default conservador si falla.
    """
    if df is None or len(df) < period + 1:
        return 100.0  # valor por defecto (evita errores)

    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean().iloc[-1]

    if np.isnan(atr) or atr <= 0:
        return 100.0
    return round(atr, 2)
