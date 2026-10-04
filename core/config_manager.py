# core/config_manager.py
"""
Gestor de configuración persistente.

Este módulo maneja la lectura, escritura y acceso a la configuración
almacenada en config.ini. Proporciona una interfaz tipada para obtener
y establecer valores de configuración con valores por defecto.

Características:
- Carga automática al instanciar.
- Creación de archivo con valores por defecto si no existe.
- Métodos tipados: get, getint, getboolean, getfloat.
- Manejo de listas (para cámaras detectadas).
- Guardado diferido (save=False) para optimizar escrituras.

Dependencias:
- core.constants (DEFAULT_SAVE_PATH, DEFAULT_SETTINGS, CONFIG_FILE)
"""

import configparser
from pathlib import Path

from core.constants import (
    DEFAULT_SAVE_PATH,
    CONFIG_FILE,
    DETECTABLE_OBJECTS,
    DEFAULT_DETECTION_CONFIG,
)


class ConfigManager:
    """
    Administra la configuración persistente .ini.

    Uso típico:
        config = ConfigManager()
        valor = config.get('General', 'save_path')
        config.set('General', 'save_path', '/nueva/ruta')
    """

    # -------------------------------------------------------------------------
    # VALORES POR DEFECTO
    # -------------------------------------------------------------------------
    # Estructura central que define todas las secciones y opciones posibles.
    # Si el archivo .ini no existe o le faltan claves, se crean con estos valores.
    DEFAULTS = {
        'General': {
            'save_path': str(DEFAULT_SAVE_PATH),  # Carpeta de capturas
            'capture_counter': '0',  # Contador global de capturas
            'video_source': 'Cámara Local (0)',  # Fuente de video inicial
            'camera_was_active': 'False',  # Estado de cámara al cerrar
            'left_panel_page': '0',  # Pestaña activa panel izquierdo
            'right_panel_page': '0',  # Pestaña activa panel derecho
            'rtsp_url_1': '',  # URL RTSP canal 1
            'rtsp_url_2': '',  # URL RTSP canal 2
            'yolo_enabled': 'False',  # Estado global de YOLO
        },
        'Detections': {
            # Activar/desactivar detección por tipo de objeto
            **{f'{obj}_enabled': str(DEFAULT_DETECTION_CONFIG[obj]['enabled']) for obj in DETECTABLE_OBJECTS},
            # Umbral de confianza por tipo de objeto
            **{f'{obj}_confidence': str(DEFAULT_DETECTION_CONFIG[obj]['confidence']) for obj in DETECTABLE_OBJECTS}
        },
        'Alerts': {
            'detection': 'True',  # Alerta sonora al detectar
            'connection': 'True',  # Alerta sonora al perder conexión
            'low_battery': 'False',  # Alerta sonora de batería baja
        },
        'Optics': {
            'clahe': 'False',  # Mejora de contraste
            'zoom': '1.0',  # Zoom digital
            'upscale': 'False',  # Superresolución
            'performance': 'Balanceado (Estandar)',  # Perfil de rendimiento
            'threads': '4',  # Hilos de CPU
        }
    }

    # -------------------------------------------------------------------------
    # INICIALIZACIÓN Y CARGA
    # -------------------------------------------------------------------------

    def __init__(self, filename=CONFIG_FILE):
        """
        Inicializa el gestor de configuración.

        Args:
            filename: Ruta al archivo .ini (por defecto CONFIG_FILE).
        """
        self.filename = Path(filename)
        self.config = configparser.ConfigParser()
        self.load()

    def load(self):
        """
        Carga la configuración desde el archivo.

        Si el archivo no existe, crea uno con valores por defecto.
        Si existe pero le faltan secciones/opciones, las agrega.
        """
        if not self.filename.exists():
            # Crear archivo con valores por defecto
            self.set_defaults()
            self.save()
        else:
            # Cargar archivo existente
            self.config.read(self.filename, encoding='utf-8')
            # Asegurar que no falten secciones/opciones
            self.ensure_defaults()

    def set_defaults(self):
        """
        Aplica la estructura completa de valores por defecto.

        Reemplaza cualquier configuración existente por los valores
        definidos en DEFAULTS.
        """
        self.config.read_dict(self.DEFAULTS)

    def ensure_defaults(self):
        """
        Garantiza la presencia de todas las secciones y opciones por defecto.

        Si falta alguna sección u opción, la agrega con el valor por defecto.
        Si se realizan cambios, guarda el archivo.
        """
        changed = False
        for section, options in self.DEFAULTS.items():
            if not self.config.has_section(section):
                self.config.add_section(section)
                changed = True
            for key, val in options.items():
                if not self.config.has_option(section, key):
                    self.config.set(section, key, str(val))
                    changed = True
        if changed:
            self.save()

    # -------------------------------------------------------------------------
    # GUARDADO
    # -------------------------------------------------------------------------

    def save(self):
        """
        Guarda la configuración actual en el archivo .ini.

        Usa encoding UTF-8 para soportar caracteres especiales.
        """
        with self.filename.open('w', encoding='utf-8') as f:
            self.config.write(f)

    # -------------------------------------------------------------------------
    # MÉTODOS DE ACCESO TIPADOS
    # -------------------------------------------------------------------------

    def get(self, section, key, fallback=None):
        """
        Obtiene un valor como string.

        Args:
            section: Nombre de la sección (ej: 'General').
            key: Nombre de la opción (ej: 'save_path').
            fallback: Valor a devolver si no existe (default: None).

        Returns:
            String con el valor o fallback si no existe.
        """
        return self.config.get(section, key, fallback=fallback)

    def getint(self, section, key, fallback=0):
        """
        Obtiene un valor como entero.

        Args:
            section: Nombre de la sección.
            key: Nombre de la opción.
            fallback: Valor a devolver si no existe o no es entero (default: 0).

        Returns:
            Entero o fallback.
        """
        return self.config.getint(section, key, fallback=fallback)

    def getboolean(self, section, key, fallback=False):
        """
        Obtiene un valor como booleano.

        Args:
            section: Nombre de la sección.
            key: Nombre de la opción.
            fallback: Valor a devolver si no existe (default: False).

        Returns:
            Booleano o fallback.
        """
        return self.config.getboolean(section, key, fallback=fallback)

    def getfloat(self, section, key, fallback=0.0):
        """
        Obtiene un valor como float.

        Args:
            section: Nombre de la sección.
            key: Nombre de la opción.
            fallback: Valor a devolver si no existe (default: 0.0).

        Returns:
            Float o fallback.
        """
        return self.config.getfloat(section, key, fallback=fallback)

    def set(self, section, key, value, save=True):
        """
        Establece un valor en la configuración.

        Args:
            section: Nombre de la sección.
            key: Nombre de la opción.
            value: Valor a establecer (se convierte a string).
            save: Si True (default), guarda inmediatamente en disco.
                  Si False, solo modifica en memoria (útil para guardados múltiples).
        """
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, key, str(value))
        if save:
            self.save()

    # -------------------------------------------------------------------------
    # MANEJO DE LISTAS (CÁMARAS DETECTADAS)
    # -------------------------------------------------------------------------

    def get_camera_list(self):
        """
        Obtiene la lista de cámaras guardadas en configuración.

        Returns:
            Lista de strings con nombres de cámaras, o None si no existe.
        """
        cameras_str = self.get('General', 'camera_list', fallback=None)
        if cameras_str:
            return [cam.strip() for cam in cameras_str.split(',') if cam.strip()]
        return None

    def set_camera_list(self, camera_list):
        """
        Guarda una lista de cámaras en configuración.

        Args:
            camera_list: Lista de strings con nombres de cámaras.
        """
        self.set('General', 'camera_list', ', '.join(camera_list))