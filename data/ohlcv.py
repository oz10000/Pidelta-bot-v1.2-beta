# data/ohlcv.py
import ccxt
import pandas as pd
import time

_exchange = ccxt.okx({"enableRateLimit": True})

def fetch_ohlcv(symbol: str, timeframe: str = "5m", limit: int = 200):
    for attempt in range(3):
        try:
            ohlcv = _exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            return df
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2)
    return None
