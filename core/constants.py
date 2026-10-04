# core/constants.py
"""
Constantes globales del sistema.

Este módulo centraliza todos los valores constantes utilizados en la aplicación:
- Rutas y configuración por defecto.
- Colores y etiquetas de los objetos detectables.
- Dimensiones y tamaños de la interfaz.
- Rangos de tiempo para filtros.

Organización:
1. Imports necesarios.
2. Rutas y configuración por defecto.
3. Colores y etiquetas de objetos.
4. Dimensiones de la interfaz.
5. Rangos de tiempo.
"""

# =============================================================================
# 1. IMPORTS
# =============================================================================
from pathlib import Path
from PySide6.QtCore import QSize

# =============================================================================
# 2. RUTAS Y CONFIGURACIÓN POR DEFECTO
# =============================================================================

# Archivo de configuración persistente
CONFIG_FILE = Path("config.ini")

# Carpeta por defecto para guardar capturas
DEFAULT_SAVE_PATH = Path.home() / "Pictures"

# Lista central de objetos detectables
DETECTABLE_OBJECTS = ("person", "car", "boat", "helicopter")

# Configuración por defecto de detección para cada objeto
DEFAULT_DETECTION_CONFIG = {
    "person": {"enabled": True, "confidence": 0.50},
    "car": {"enabled": True, "confidence": 0.50},
    "boat": {"enabled": True, "confidence": 0.50},
    "helicopter": {"enabled": True, "confidence": 0.50},
}

# Valores por defecto de la aplicación
# Estos valores se usan si no existe config.ini o si faltan claves
DEFAULT_SETTINGS = {
    # Configuración de detección para cada tipo de objeto
    "detections": DEFAULT_DETECTION_CONFIG,
    # Fuente de video inicial
    "video_source": "Cámara Local (0)",
    # Alertas activadas por defecto
    "alerts": {
        "detection": True,      # Sonido al detectar objeto
        "connection": True,     # Sonido al perder/conectar cámara
        "low_battery": True,   # Sonido de batería baja
    },
    # Ruta de guardado de capturas
    "save_path": DEFAULT_SAVE_PATH,
    # Contador global de capturas (se incrementa con cada captura)
    "capture_counter": 0,
    # Estado de la cámara al cerrar la app (para restaurar)
    "camera_was_active": False,
    # Configuración de mejora visual
    "optics": {
        "clahe": False,                     # Mejora de contraste
        "zoom": 1.0,                        # Zoom digital inicial
        "upscale": False,                   # Superresolución
        "performance": "Balanceado (Estandar)",  # Perfil de rendimiento
        "threads": 4,                       # Hilos de CPU para procesamiento
    },
}

# =============================================================================
# 3. COLORES Y ETIQUETAS DE OBJETOS
# =============================================================================

# Colores para cada tipo de objeto detectable
# Se usan para dibujar bounding boxes y para indicadores visuales
OBJ_COLORS = {
    "person": {
        "border": "#ff5252",                            # Rojo
        "bg": "rgba(255,82,82,0.10)",                   # Fondo translúcido
        "text": "#ff5252"                               # Color del texto
    },
    "car": {
        "border": "#8bc34a",                            # Verde
        "bg": "rgba(139,195,74,0.10)",
        "text": "#8bc34a"
    },
    "boat": {
        "border": "#4fc3f7",                            # Azul claro
        "bg": "rgba(79,195,247,0.10)",
        "text": "#4fc3f7"
    },
    "helicopter": {
        "border": "#ffb74d",                            # Naranja
        "bg": "rgba(255,183,77,0.10)",
        "text": "#ffb74d"
    },
}

# Etiquetas cortas para mostrar en la interfaz y en logs
OBJ_LABEL = {
    "person": "PERSON",
    "car": "CAR",
    "boat": "BOAT",
    "helicopter": "HELI",
}

# =============================================================================
# COLORES DE LA NOTIFICACIÓN TOAST
# =============================================================================

# Colores usados por el toast para mantener coherencia con el tema oscuro
TOAST_BG = "#2d2d2d"          # Fondo del toast (gris oscuro)
TOAST_BORDER = "#555555"      # Borde del toast (gris medio)
TOAST_TEXT = "#f0f0f0"        # Texto del toast (blanco hueso)

# =============================================================================
# 4. DIMENSIONES DE LA INTERFAZ
# =============================================================================

# Tamaño de las miniaturas en la galería de capturas (en píxeles)
THUMBNAIL_SIZE = 200

# Ancho de las barras de navegación laterales (iconos verticales)
NAV_BAR_WIDTH = 44

# Ancho del panel izquierdo cuando está expandido
LEFT_PANEL_WIDTH = 280

# Ancho del panel derecho cuando está expandido
RIGHT_PANEL_WIDTH = 364

# Tamaño estándar de iconos en botones de navegación
ICON_SIZE = QSize(20, 20)

# Tamaño fijo de botones de navegación (alto y ancho)
TOOLBUTTON_SIZE = 36

# =============================================================================
# 5. RANGOS DE TIEMPO PARA FILTROS
# =============================================================================

# Rangos de horas para filtrar capturas por momento del día
TIME_RANGES = {
    'morning': range(6, 12),      # 6:00 - 11:59
    'afternoon': range(12, 18),   # 12:00 - 17:59
    'evening': range(18, 24)      # 18:00 - 23:59
}