# utils/telemetry.py
import json
from datetime import datetime


def log_event(event, data=None):
    try:
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "event": event,
            "data": data or {}
        }
        print(json.dumps(entry), flush=True)
    except Exception:
        pass


# ============================================================
# FUNCIONES DE CONVENIENCIA PARA EVENTOS
# ============================================================

def log_trade_open(asset, direction, contracts, price, score, atr, adx, leverage, equity):
    log_event("trade_open", {
        "asset": asset,
        "direction": direction,
        "contracts": contracts,
        "price": price,
        "score": score,
        "atr": atr,
        "adx": adx,
        "leverage": leverage,
        "equity": equity
    })


def log_trade_close(asset, exit_price, pnl, pnl_pct, duration_min, reason):
    log_event("trade_close", {
        "asset": asset,
        "exit_price": exit_price,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "duration_min": duration_min,
        "reason": reason
    })


def log_break_even(asset, sl_price):
    log_event("break_even", {"asset": asset, "sl_price": sl_price})


def log_emergency_close(asset, reason):
    log_event("emergency_close", {"asset": asset, "reason": reason})
