import os

# ============================================================================
# 1. MODO DE OPERACIÓN
# ============================================================================
# paper   = simulación (sin órdenes reales, solo logs)
# demo    = conexión a OKX demo (requiere credenciales de demo)
# live    = conexión a OKX real (requiere credenciales de producción)
MODE = "paper"  # paper | demo | live

# ============================================================================
# 2. ACTIVOS Y TIMEFRAME
# ============================================================================
# Símbolos de futuros perpetuos (swap) en OKX
ASSETS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT"
]

TIMEFRAME = "5m"  # intervalo de velas para el análisis

# ============================================================================
# 3. GESTIÓN DE RIESGO
# ============================================================================
RISK_PER_TRADE = 0.02      # 2% del equity por operación
MAX_LEVERAGE = 10          # apalancamiento máximo permitido

# ============================================================================
# 4. IDENTIDAD DEL BOT (para clOrdId determinista)
# ============================================================================
STRATEGY_VERSION = "v2_deterministic"   # versión de la estrategia
SESSION_ID = os.getenv("SESSION_ID", "local")  # identificador de sesión (cambiar en producción)
BOT_CL_ORD_PREFIX = "p"                 # prefijo para filtrar órdenes propias

# ============================================================================
# 5. TIMEOUTS Y POLLING
# ============================================================================
FILL_TIMEOUT_SECONDS = 10      # tiempo máximo esperando que una orden market se llene
RECONCILIATION_TIMEOUT = 5     # timeout por símbolo en reconciliación
API_POLL_INTERVAL = 0.25       # intervalo entre consultas de estado de orden (segundos)

# ============================================================================
# 6. CONFIGURACIÓN POR ACTIVO (SL, TP, TRAILING)
# ============================================================================
ASSET_CONFIG = {
    "BTC/USDT:USDT": {
        "sl_atr": 1.5,          # multiplicador de ATR para Stop Loss
        "tp_atr": 1.0,          # multiplicador de ATR para Take Profit
        "trail_callback": 0.28  # callback rate para trailing stop (%)
    },
    "ETH/USDT:USDT": {
        "sl_atr": 1.5,
        "tp_atr": 1.2,
        "trail_callback": 0.37
    },
    "SOL/USDT:USDT": {
        "sl_atr": 1.5,
        "tp_atr": 1.4,
        "trail_callback": 0.58
    },
}

# ============================================================================
# 7. MODO DE POSICIÓN EN OKX
# ============================================================================
# net_mode → una sola posición por símbolo (larga o corta)
# hedge   → permite posiciones largas y cortas simultáneas
POS_MODE = "net_mode"   # ajustar según la configuración de tu cuenta

# ============================================================================
# 8. CREDENCIALES OKX (obtenidas desde variables de entorno)
# ============================================================================
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_SECRET")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")

# Alias para compatibilidad con módulos que usen nombres antiguos
API_KEY = OKX_API_KEY
SECRET_KEY = OKX_SECRET
PASSPHRASE = OKX_PASSPHRASE

# ============================================================================
# 9. VALIDACIÓN DE CREDENCIALES (evita errores silenciosos en producción)
# ============================================================================
if MODE in ("demo", "live") and (not OKX_API_KEY or not OKX_SECRET or not OKX_PASSPHRASE):
    raise EnvironmentError(
        "Faltan credenciales de OKX. "
        "Asegúrate de configurar las variables de entorno:\n"
        "  OKX_API_KEY\n"
        "  OKX_SECRET\n"
        "  OKX_PASSPHRASE\n"
        "O ajusta MODE='paper' para simulación sin credenciales."
    )

# ============================================================================
# 10. FILTRO HORARIO (opcional)
# ============================================================================
# Permitir trading solo en ciertas horas (formato 0-23)
TRADE_HOURS_START = 0   # 0 = medianoche
TRADE_HOURS_END = 23    # 23 = 11 PM (trading 24h)

# ============================================================================
# 11. OTROS PARÁMETROS GLOBALES (ajustables)
# ============================================================================
# Umbral de score para generar señal (0.0 a 1.0)
SCORE_THRESHOLD = 0.20

# ATR por defecto (si falla el cálculo real, se usa este valor)
DEFAULT_ATR = 100.0
