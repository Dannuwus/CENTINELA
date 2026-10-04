# core/log_manager.py
"""
Gestor central de logs con buffer y emisión por lotes.

Este módulo proporciona una cola thread-safe (deque) para acumular mensajes
de log y emitirlos en lotes mediante una señal Qt. La emisión se realiza
cada cierto intervalo de tiempo (flush_interval_ms) para evitar sobrecargar
la interfaz con actualizaciones individuales.

Características:
- Buffer con tamaño máximo para evitar crecimiento descontrolado.
- Timer interno para vaciar el buffer periódicamente.
- Señal `log_batch` que emite una lista de strings listos para mostrar.
- Método `add_log` seguro para llamar desde cualquier hilo (es un slot).

Uso:
    log_manager = LogManager(parent=self)
    log_manager.log_batch.connect(self.logs_page.append_batch)
    log_manager.add_log("Mensaje", "INFO")
"""

from collections import deque
from pathlib import Path
import os
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QTimer, Slot


class LogManager(QObject):
    """Gestor central de logs con buffer y emisión por lotes."""

    # Señal emitida cuando se vacía el buffer.
    # El argumento es una lista de strings ya formateadas.
    log_batch = Signal(list)

    def __init__(self, max_entries=1000, flush_interval_ms=100, parent=None):
        """
        Inicializa el gestor de logs.

        Args:
            max_entries: Número máximo de entradas en el buffer.
            flush_interval_ms: Intervalo en milisegundos para vaciar el buffer.
            parent: Widget/QObject padre (opcional).
        """
        super().__init__(parent)

        # Buffer temporal para emisión: guarda tuplas (nivel, texto_formateado)
        self._buffer = deque(maxlen=max_entries)
        # Historial completo de la sesión: lista de tuplas (nivel, texto_formateado)
        self._history = []
        # Directorio donde se guardan los logs diarios
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)

        # Contador de líneas ya escritas al archivo
        self._written_count = 0

        # Timer para emitir lotes periódicamente
        self._timer = QTimer(self)

        # Niveles mínimos para cada destino
        self.ui_min_level = "INFO"    # La interfaz muestra INFO, WARNING, ERROR
        self.file_min_level = "DEBUG" # El archivo guarda todo (incluye DEBUG)

        self._timer.timeout.connect(self.flush)
        self._timer.start(flush_interval_ms)

    @Slot(str, str)
    def add_log(self, message: str, level: str = "INFO"):
        """
        Añade un mensaje al buffer con timestamp y nivel.

        Este método puede ser llamado desde cualquier hilo de forma segura
        porque simplemente agrega a un deque y no realiza operaciones de UI.

        Args:
            message: Texto del mensaje.
            level: Nivel de severidad (por ejemplo "INFO", "WARN", "ERROR").
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] [{level}] {message}"

        # Guardar como tupla (nivel, texto_formateado) en ambos buffers
        self._buffer.append((level, formatted))
        self._history.append((level, formatted))

        # Escribir inmediatamente en el archivo diario para evitar pérdidas
        self._write_to_daily_file(level, formatted)

    def _write_to_daily_file(self, level: str, formatted: str):
        """
        Escribe una línea de log en el archivo diario de forma inmediata.

        Args:
            level: Nivel del log (para filtrar si es necesario).
            formatted: Texto completo con timestamp y nivel.
        """
        # Solo escribir si el nivel está habilitado para archivo
        if not self._is_level_enabled(level, self.file_min_level):
            return

        # Evitar escribir líneas vacías
        if not formatted.strip():
            return

        path = self._get_daily_log_path()
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(formatted + "\n")
                f.flush()           # Vaciar buffer de Python
                os.fsync(f.fileno())  # Forzar escritura a disco
        except Exception as e:
            print(f"Error escribiendo log diario: {e}")

    def check_unexpected_shutdown(self):
        """
        Verifica si la última sesión terminó inesperadamente.

        Revisa el archivo de log del día actual (o el último existente)
        y si su última línea no contiene 'Aplicación cerrada por el usuario',
        registra una advertencia.
        """
        try:
            # Obtener lista de archivos de log
            log_files = sorted(self.log_dir.glob("log_*.txt"))
            if not log_files:
                return  # No hay logs anteriores, primera ejecución

            # Tomar el archivo más reciente
            last_file = log_files[-1]

            # Leer la última línea no vacía
            last_line = ""
            with open(last_file, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]
                if lines:
                    last_line = lines[-1]

            # Si no termina con el mensaje de cierre normal, advertir
            if "Aplicación cerrada por el usuario" not in last_line:
                self.add_log(
                    f"La sesión anterior no se cerró correctamente (último log: {last_line[:80]})",
                    "WARNING"
                )
        except Exception as e:
            # No interrumpir el arranque por fallos en esta comprobación
            pass

    def _get_daily_log_path(self) -> Path:
        """
        Obtiene la ruta del archivo de log diario.

        Returns:
            Path con el nombre 'log_YYYY-MM-DD.txt' dentro de la carpeta 'logs'.
        """
        fecha = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"log_{fecha}.txt"

    def _is_level_enabled(self, level: str, min_level: str) -> bool:
        """
        Verifica si un nivel está habilitado según el mínimo requerido.

        Orden de severidad: DEBUG < INFO < WARNING < ERROR < CRITICAL

        Args:
            level: Nivel del log a evaluar.
            min_level: Nivel mínimo permitido.

        Returns:
            True si el nivel es igual o más severo que min_level.
        """
        order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        try:
            return order.index(level) >= order.index(min_level)
        except ValueError:
            return True  # Si el nivel no está en la lista, permitir por defecto

    def flush(self):
        """
        Emite los logs acumulados como lote para la interfaz.

        Ya no escribe en archivo porque la escritura se hace en add_log.
        """
        if self._buffer:
            # Copiar y limpiar buffer
            all_items = list(self._buffer)
            self._buffer.clear()

            # Filtrar para interfaz
            batch = [
                formatted for level, formatted in all_items
                if self._is_level_enabled(level, self.ui_min_level)
            ]
            if batch:
                self.log_batch.emit(batch)