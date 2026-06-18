import pandas as pd
import numpy as np
from typing import Optional

def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calcula el Average True Range (ATR) de un DataFrame OHLCV."""
    if df is None or len(df) < period + 1:
        return 100.0  # Default conservador

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
