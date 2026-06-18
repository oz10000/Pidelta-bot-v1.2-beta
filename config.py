import os

# ============================================================================
# MODO DE OPERACIÓN
# ============================================================================
MODE = "paper"  # paper | demo | live

# ============================================================================
# ACTIVOS Y TIMEFRAME
# ============================================================================
ASSETS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
TIMEFRAME = "5m"

# ============================================================================
# GESTIÓN DE RIESGO
# ============================================================================
RISK_PER_TRADE = 0.02
MAX_LEVERAGE = 10

# ============================================================================
# IDENTIDAD DEL BOT (DETERMINISTA PARA CLORDID)
# ============================================================================
STRATEGY_VERSION = "v2_deterministic"
SESSION_ID = os.getenv("SESSION_ID", "local")
BOT_CL_ORD_PREFIX = "p"  # Prefijo para filtrar órdenes propias

# ============================================================================
# TIMEOUTS (EVITA BLOQUEOS)
# ============================================================================
FILL_TIMEOUT_SECONDS = 10      # Tiempo máximo esperando fill de market order
RECONCILIATION_TIMEOUT = 5     # Timeout por símbolo en reconciliación
API_POLL_INTERVAL = 0.25       # Intervalo de polling para chequeo de fills

# ============================================================================
# CONFIGURACIÓN POR ACTIVO (SL/TP/TRAILING)
# ============================================================================
ASSET_CONFIG = {
    "BTC/USDT:USDT": {"sl_atr": 1.5, "tp_atr": 1.0, "trail_callback": 0.28},
    "ETH/USDT:USDT": {"sl_atr": 1.5, "tp_atr": 1.2, "trail_callback": 0.37},
    "SOL/USDT:USDT": {"sl_atr": 1.5, "tp_atr": 1.4, "trail_callback": 0.58},
}

# ============================================================================
# CREDENCIALES OKX (VARIABLES DE ENTORNO)
# ============================================================================
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_SECRET")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
