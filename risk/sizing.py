# risk/sizing.py
import logging
logger = logging.getLogger("PideltaBot")

def get_step_size(exchange, symbol):
    try:
        market = exchange.market(symbol)
        step = market.get("limits", {}).get("amount", {}).get("step")
        if step is None:
            step = market.get("precision", {}).get("amount")
        if step is None:
            step = 0.001
        return float(step)
    except Exception as e:
        logger.warning(f"get_step_size fallback: {e}")
        return 0.001

def get_min_qty(exchange, symbol):
    try:
        market = exchange.market(symbol)
        min_qty = market.get("limits", {}).get("amount", {}).get("min")
        if min_qty is None:
            return 0.0
        return float(min_qty)
    except Exception:
        return 0.0

def calculate_contracts(exchange, symbol, equity, risk_per_trade, entry_price, sl_price, max_leverage):
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return 0.0

    risk_usd = equity * risk_per_trade
    contracts = risk_usd / sl_distance

    max_contracts = (equity * max_leverage) / entry_price
    contracts = min(contracts, max_contracts)

    try:
        market = exchange.market(symbol)
        max_qty = market.get("limits", {}).get("amount", {}).get("max")
        if max_qty is None:
            max_qty = float('inf')
        contracts = min(contracts, max_qty)
    except Exception:
        pass

    min_qty = get_min_qty(exchange, symbol)
    if min_qty > 0 and contracts < min_qty:
        return 0.0

    step = get_step_size(exchange, symbol)
    if step > 0:
        contracts = round(contracts - (contracts % step), 6)

    return max(0.0, contracts)
