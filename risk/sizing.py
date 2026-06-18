def calculate_contracts(exchange, symbol, equity, risk_per_trade, entry_price, stop_loss_price, max_leverage):
    """
    Calcula el número de contratos basado en el riesgo definido.
    """
    if stop_loss_price == entry_price:
        return 0
    risk_amount = equity * risk_per_trade
    price_diff = abs(entry_price - stop_loss_price)
    if price_diff == 0:
        return 0
    # Tamaño en dólares
    notional = risk_amount / (price_diff / entry_price)
    # Aplicar apalancamiento máximo
    max_notional = equity * max_leverage
    notional = min(notional, max_notional)
    # Obtener tamaño del contrato
    market = exchange.market(symbol)
    contract_size = market.get("contractSize", 1.0)
    # Calcular contratos
    contracts = notional / (entry_price * contract_size)
    # Ajustar a mínimo de contratos (entero para futuros)
    return max(1, int(contracts))
