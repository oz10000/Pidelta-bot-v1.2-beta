# main.py
import os
import time
import logging
from datetime import datetime

import config
from data.ohlcv import fetch_ohlcv
from strategy.engine import compute_signal_for_asset
from execution.client import OKXClient
from risk.sizing import calculate_contracts
from utils.telemetry import log_event
from utils.position_guard import PositionGuard
from utils.reconciliation import ReconciliationEngine

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/trading.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("PideltaBot")

# ============================================================
# DATOS
# ============================================================
def fetch_all_data(assets, limit=200):
    data = {}
    for asset in assets:
        try:
            symbol = asset.replace(":USDT", "")
            df = fetch_ohlcv(symbol, timeframe=config.TIMEFRAME, limit=limit)
            if df is not None and not df.empty:
                data[asset] = df
        except Exception as e:
            logger.error(f"fetch error {asset}: {e}")
    return data

# ============================================================
# SEÑALES
# ============================================================
def compute_all_signals(data, assets):
    required = set(assets)
    if not required.issubset(set(data.keys())):
        return []

    df_btc = data["BTC/USDT:USDT"]
    df_eth = data["ETH/USDT:USDT"]
    df_sol = data["SOL/USDT:USDT"]

    macro_map = {
        "BTC/USDT:USDT": (df_eth, df_sol),
        "ETH/USDT:USDT": (df_btc, df_sol),
        "SOL/USDT:USDT": (df_btc, df_eth),
    }

    signals = []
    for asset in assets:
        df_self = data.get(asset)
        if df_self is None or df_self.empty:
            continue
        macro_a, macro_b = macro_map[asset]
        sig = compute_signal_for_asset(
            df_self,
            macro_a,
            macro_b,
            config.SCORE_THRESHOLD
        )
        sig["asset"] = asset
        signals.append(sig)

    return signals


def select_best(signals):
    best = None
    best_score = 0.0
    for s in signals:
        if s["signal"] == "none":
            continue
        if abs(s["score"]) > abs(best_score):
            best = s
            best_score = s["score"]
    return best

# ============================================================
# EJECUCIÓN DE TRADES
# ============================================================
def execute_trade(client, signal, price, equity):
    side = "buy" if signal["signal"] == "long" else "sell"
    direction = "long" if signal["signal"] == "long" else "short"
    asset = signal["asset"]

    cfg = config.ASSET_CONFIG.get(asset, {})
    sl_mult = cfg.get("sl_atr", 1.5)
    atr = signal["atr"]

    sl_price = price - sl_mult * atr if signal["signal"] == "long" else price + sl_mult * atr

    contracts = calculate_contracts(
        client.exchange,
        asset,
        equity,
        config.RISK_PER_TRADE,
        price,
        sl_price,
        config.MAX_LEVERAGE
    )
    if contracts <= 0:
        return False

    if config.MODE == "paper":
        logger.info(f"[PAPER] {signal}")
        return True

    order = client.place_market_order(asset, side, contracts)
    if not order:
        log_event("trade_open_failed", {"asset": asset, "error": "market_order_failed"})
        return False

    log_event("trade_open_success", {
        "asset": asset,
        "direction": direction,
        "contracts": contracts,
        "price": price,
        "score": signal["score"],
        "atr": atr,
        "adx": signal["adx"],
        "leverage": config.MAX_LEVERAGE,
        "equity": equity
    })

    position_guard.register_trade(asset, {
        "entry_price": price,
        "side": direction,
        "size": contracts,
        "atr": atr,
        "score": signal["score"],
        "adx": signal["adx"]
    })

    trail_callback = cfg.get("trail_callback", 0.50)
    trail_order = client.place_trailing_stop(
        asset,
        "sell" if signal["signal"] == "long" else "buy",
        contracts,
        trail_callback,
        client_order_id=f"trail_{asset}_{int(time.time())}"
    )
    if trail_order:
        log_event("trailing_stop_created", {
            "asset": asset,
            "callback_rate": trail_callback,
            "order_id": trail_order.get("id")
        })
    else:
        sl_order = client.place_stop_loss(asset, side, contracts, sl_price)
        if sl_order:
            log_event("stop_loss_created", {"asset": asset, "price": sl_price, "fallback": True})

    tp_mult = cfg.get("tp_atr", 1.2)
    tp_price = price + tp_mult * atr if signal["signal"] == "long" else price - tp_mult * atr
    tp_order = client.place_take_profit(
        asset,
        "sell" if signal["signal"] == "long" else "buy",
        contracts,
        tp_price,
        client_order_id=f"tp_{asset}_{int(time.time())}"
    )
    if tp_order:
        log_event("take_profit_created", {"asset": asset, "price": tp_price, "order_id": tp_order.get("id")})

    logger.info(f"TRADE EXECUTED {signal}")
    return True

# ============================================================
# MAIN LOOP
# ============================================================
def main():
    client = OKXClient()

    global position_guard
    position_guard = PositionGuard(client)

    reconciliation = ReconciliationEngine(client, position_guard)

    log_event("bot_started", {"mode": config.MODE.upper()})

    logger.info("Running startup reconciliation...")
    results = reconciliation.reconcile()
    for symbol, ok in results.items():
        logger.info(f"[Reconciliation] {symbol}: {'OK' if ok else 'FAILED'}")

    logger.info("Bot started in mode " + config.MODE.upper())

    try:
        client.fetch_balance()
        log_event("exchange_connected", {"status": "ok"})
    except Exception as e:
        log_event("exchange_connected", {"status": "failed", "error": str(e)})
        logger.error("No se pudo conectar a OKX. Abortando.")
        return

    last_candle = None

    while True:
        try:
            position_guard.check_all()

            ref = fetch_ohlcv("BTC/USDT", config.TIMEFRAME, 2)
            if ref is None or ref.empty:
                time.sleep(10)
                continue

            candle_time = ref.iloc[-1]["timestamp"]
            if candle_time == last_candle:
                time.sleep(10)
                continue
            last_candle = candle_time

            hour = datetime.utcnow().hour
            if not (config.TRADE_HOURS_START <= hour < config.TRADE_HOURS_END):
                time.sleep(60)
                continue

            data = fetch_all_data(config.ASSETS)
            if not data:
                time.sleep(30)
                continue

            signals = compute_all_signals(data, config.ASSETS)
            best = select_best(signals)
            if not best or abs(best["score"]) < config.SCORE_THRESHOLD:
                continue

            log_event("signal_selected", {
                "asset": best["asset"],
                "signal": best["signal"],
                "score": best["score"]
            })

            if client.has_open_position(best["asset"]):
                log_event("position_detected", {"asset": best["asset"]})
                continue

            equity = client.fetch_balance()
            ticker = client.fetch_ticker(best["asset"])
            if ticker is None:
                continue
            price = ticker["last"]

            success = execute_trade(client, best, price, equity)
            log_event("trade_result", {"success": success, "asset": best["asset"]})

            time.sleep(10)

        except Exception as e:
            log_event("exception", {"error": str(e)})
            logger.exception("Unhandled exception in main loop")
            time.sleep(60)


if __name__ == "__main__":
    main()
