# config.py
import os

# ============================================================================
# MODO DE OPERACIÓN
# ============================================================================
MODE = "demo"  # paper | demo | live

# ============================================================================
# ACTIVOS
# ============================================================================
ASSETS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT"
]

# ============================================================================
# PARÁMETROS GLOBALES
# ============================================================================
TIMEFRAME = "5m"
SCORE_THRESHOLD = 0.20
RISK_PER_TRADE = 0.02
MAX_LEVERAGE = 9

# ============================================================================
# CONFIGURACIÓN POR ACTIVO (OPTIMIZADA)
# ============================================================================
BTC_CONFIG = {
    "sl_atr": 1.5,
    "tp_atr": 1.0,
    "be_trigger": 0.55,
    "be_offset": 0.20,
    "trail_callback": 0.28,
}

ETH_CONFIG = {
    "sl_atr": 1.5,
    "tp_atr": 1.2,
    "be_trigger": 0.50,
    "be_offset": 0.15,
    "trail_callback": 0.37,
}

SOL_CONFIG = {
    "sl_atr": 1.5,
    "tp_atr": 1.4,
    "be_trigger": 0.45,
    "be_offset": 0.20,
    "trail_callback": 0.58,
}

ASSET_CONFIG = {
    "BTC/USDT:USDT": BTC_CONFIG,
    "ETH/USDT:USDT": ETH_CONFIG,
    "SOL/USDT:USDT": SOL_CONFIG,
}

# ============================================================================
# FILTRO HORARIO
# ============================================================================
TRADE_HOURS_START = 12
TRADE_HOURS_END = 16

# ============================================================================
# CREDENCIALES OKX (variables de entorno)
# ============================================================================
API_KEY = os.getenv("OKX_API_KEY", "")
SECRET_KEY = os.getenv("OKX_SECRET", "")
PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")
