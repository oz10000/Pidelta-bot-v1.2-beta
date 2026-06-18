import time
import logging
from config import ASSETS, TIMEFRAME, ASSET_CONFIG
from execution.client import OKXClient
from core.event_store import EventStore
from engine.execution import ExecutionEngine
from utils.reconciliation import ReconciliationEngine
from utils.position_guard import PositionGuard
from strategy.engine import compute_signal_for_asset
from data.ohlcv import fetch_ohlcv
from risk.sizing import calculate_contracts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("logs/bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger("Main")

def main():
    # =====================================================================
    # INICIALIZACIÓN DE CAPAS
    # =====================================================================
    client = OKXClient()
    store = EventStore("data/events.jsonl")
    guard = PositionGuard(store)
    reconciler = ReconciliationEngine(client, store)
    executor = ExecutionEngine(client, store)

    logger.info("PIDELTA BOT v2 - Deterministic & Fault Tolerant")
    logger.info("Running initial reconciliation...")

    # Reconciliación completa al inicio
    for symbol in ASSETS:
        reconciler.reconcile_symbol(symbol)

    logger.info("Reconciliation complete. Starting main loop.")

    # =====================================================================
    # LOOP PRINCIPAL
    # =====================================================================
    while True:
        try:
            for symbol in ASSETS:
                # 1. Reconciliación periódica (cada ciclo)
                reconciler.reconcile_symbol(symbol)

                # 2. Datos OHLCV
                df = fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
                if df.empty:
                    logger.warning(f"No data for {symbol}")
                    continue

                # 3. Señal
                # Nota: compute_signal_for_asset requiere 3 dataframes (self, macro1, macro2)
                # Simulación simple para este ejemplo. Asumimos que la función existe.
                # Si no, se debe adaptar al prototipo.
                try:
                    # Placeholder: si la función requiere 3 DF, los pasamos.
                    # Para simplificar, asumimos que tenemos una versión que acepta solo df.
                    # En tu repositorio original, `engine.py` usa 3 DF.
                    # Aquí invocamos una señal simple (ejemplo).
                    # Reemplazar con la lógica real de strategy/engine.py
                    from strategy.engine import compute_signal_for_asset
                    # Necesitamos los macros, los obtenemos (simplificado)
                    macro_symbols = [a for a in ASSETS if a != symbol]
                    df_macro1 = fetch_ohlcv(macro_symbols[0], timeframe=TIMEFRAME, limit=100)
                    df_macro2 = fetch_ohlcv(macro_symbols[1], timeframe=TIMEFRAME, limit=100)
                    signal = compute_signal_for_asset(df, df_macro1, df_macro2, 0.2)
                except Exception as e:
                    logger.error(f"Signal error {symbol}: {e}")
                    continue

                if signal["signal"] == "none":
                    continue

                # 4. Cálculo de tamaño (Risk)
                price = df.iloc[-1]["close"]
                equity = client.fetch_balance()
                atr = 100.0  # Placeholder: debería ser ATR real
                sl_mult = ASSET_CONFIG.get(symbol, {}).get("sl_atr", 1.5)
                sl_price = price - sl_mult * atr if signal["signal"] == "long" else price + sl_mult * atr
                size = calculate_contracts(client.ex, symbol, equity, 0.02, price, sl_price, 10)

                if size <= 0:
                    logger.warning(f"Size <= 0 for {symbol}")
                    continue

                # 5. Preparar señal para ejecución
                signal_payload = {
                    "symbol": symbol,
                    "side": signal["signal"],
                    "size": size,
                    "atr": atr,
                    "config": ASSET_CONFIG.get(symbol, {})
                }

                # 6. Ejecutar entrada
                success = executor.execute_entry(signal_payload, price, equity)
                if success:
                    logger.info(f"Entry executed for {symbol} {signal['signal']}")

            # Esperar 5 minutos
            time.sleep(300)

        except KeyboardInterrupt:
            logger.info("Shutdown requested.")
            break
        except Exception as e:
            logger.error(f"Fatal loop error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
