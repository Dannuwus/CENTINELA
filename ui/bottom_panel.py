# =============================================================================
# MÓDULO DE PANEL INFERIOR (TELEMETRÍA Y ZOOM)
# =============================================================================
# Este módulo implementa el panel inferior de la aplicación que muestra:
# 1. Control de zoom digital (slider)
# 2. Telemetría del sistema (FPS, detecciones, CPU, RAM, GPU, batería)
# 3. Botón de captura rápida
#
# La telemetría se actualiza automáticamente cada segundo mediante un QTimer.
#
# DEPENDENCIAS:
# - datetime (hora UTC)
# - psutil (opcional, para CPU/RAM/batería)
# - PySide6.QtCore (timer, señales)
# - PySide6.QtWidgets (widgets base)
# =============================================================================

# =============================================================================
# IMPORTS ESTÁNDAR
# =============================================================================
from datetime import datetime  # Para hora UTC

# =============================================================================
# IMPORTS OPCIONALES (con manejo de ausencia)
# =============================================================================
try:
    import psutil  # Para leer CPU, RAM, batería

    HAS_PSUTIL = True  # Bandera: psutil disponible
except ImportError:
    HAS_PSUTIL = False  # psutil no instalado, usar valores N/A

# =============================================================================
# IMPORTS DE PYQT
# =============================================================================
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget,  # Widget base
    QHBoxLayout,  # Layout horizontal
    QLabel,  # Etiquetas de telemetría
    QPushButton,  # Botón de captura
    QSlider  # Slider de zoom
)


class BottomPanel(QWidget):
    """
    Panel inferior configurado para telemetría local y control de zoom.

    Este panel muestra información en tiempo real del sistema y permite
    ajustar el zoom digital de la cámara activa.

    Señales emitidas:
        capture_requested: Solicita capturar el frame actual.

    Elementos visuales:
        - Slider de zoom (10-40, equivalente a 1.0x-4.0x)
        - Telemetría: objetos, CPU, RAM, GPU, hora UTC, FPS, batería
        - Botón de captura rápida
    """

    # Señal para solicitar captura de frame
    capture_requested = Signal()

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def __init__(self):
        super().__init__()
        self.setObjectName("bottomPanel")

        # Variables de estado
        self.detections_count = 0  # Número de objetos detectados
        self.fps = 0.0  # FPS actuales

        # Construir interfaz
        self.setup_ui()

        # Timer para actualizar telemetría cada 1 segundo
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_system_info)
        self.timer.start(1000)  # 1000 ms = 1 segundo

    # =========================================================================
    # CONSTRUCCIÓN DE LA INTERFAZ
    # =========================================================================

    def setup_ui(self):
        """
        Configura el layout del panel inferior.

        Estructura:
        [ZOOM: slider 1.0x] [--- Telemetría centrada ---] [CAPTURAR]
        """
        # ---------------------------------------------------------------------
        # LAYOUT PRINCIPAL
        # ---------------------------------------------------------------------
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 2, 10, 2)
        main_layout.setSpacing(0)

        # =====================================================================
        # 1. CONTROL DE ZOOM (IZQUIERDA)
        # =====================================================================
        zoom_label = QLabel("ZOOM:")
        zoom_label.setObjectName("infoLabel")
        main_layout.addWidget(zoom_label)

        # Slider de zoom
        self.slider_zoom = QSlider(Qt.Horizontal)
        self.slider_zoom.setMinimum(10)  # Mínimo: 1.0x (10/10)
        self.slider_zoom.setMaximum(40)  # Máximo: 4.0x (40/10)
        self.slider_zoom.setValue(10)  # Valor inicial: 1.0x
        self.slider_zoom.setFixedWidth(80)  # Ancho compacto
        main_layout.addWidget(self.slider_zoom)

        # Etiqueta de valor de zoom
        self.lbl_zoom_val = QLabel("1.0x")
        self.lbl_zoom_val.setObjectName("infoLabel")
        self.lbl_zoom_val.setFixedWidth(35)  # Ancho fijo para evitar saltos
        main_layout.addWidget(self.lbl_zoom_val)

        # Espaciador flexible
        main_layout.addStretch(1)

        # =====================================================================
        # 2. TELEMETRÍA (CENTRO)
        # =====================================================================
        # Contenedor centrado
        telemetry_container = QWidget()
        telemetry_layout = QHBoxLayout(telemetry_container)
        telemetry_layout.setContentsMargins(0, 0, 0, 0)
        telemetry_layout.setSpacing(10)

        # Crear etiquetas de telemetría
        self.labels = {}
        keys = ["objects", "cpu", "ram", "gpu", "utc", "fps", "bat"]

        for key in keys:
            lbl = QLabel(f"{key.upper()}: --")
            lbl.setObjectName("infoLabel")
            telemetry_layout.addWidget(lbl)
            self.labels[key] = lbl

        # Agregar al layout principal centrado
        main_layout.addWidget(telemetry_container, alignment=Qt.AlignCenter)

        # Espaciador flexible
        main_layout.addStretch(1)

        # =====================================================================
        # 3. BOTÓN DE CAPTURA RÁPIDA (DERECHA)
        # =====================================================================
        self.btn_capture = QPushButton("CAPTURAR")
        self.btn_capture.setObjectName("captureQuickButton")
        self.btn_capture.setCursor(Qt.PointingHandCursor)
        self.btn_capture.clicked.connect(self.capture_requested.emit)
        main_layout.addWidget(self.btn_capture)

        # Padding derecho
        main_layout.addSpacing(15)

        # Cargar valores iniciales de telemetría
        self.update_system_info()

    # =========================================================================
    # ACTUALIZACIÓN DE TELEMETRÍA
    # =========================================================================

    def update_system_info(self):
        """
        Actualiza telemetría completa: CPU, RAM, GPU, hora UTC, batería.

        Este método se llama automáticamente cada segundo por el QTimer.
        Si psutil no está disponible, muestra "N/A" en los campos.
        """
        # ---------------------------------------------------------------------
        # HORA UTC ACTUAL
        # ---------------------------------------------------------------------
        time_str = datetime.utcnow().strftime("%H:%M:%S")
        self.labels["utc"].setText(f"UTC: {time_str}")

        # ---------------------------------------------------------------------
        # TELEMETRÍA DEL SISTEMA (requiere psutil)
        # ---------------------------------------------------------------------
        if HAS_PSUTIL:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=None)
            self.labels["cpu"].setText(f"CPU: {cpu_percent:.0f}%")

            # RAM
            ram = psutil.virtual_memory()
            self.labels["ram"].setText(f"RAM: {ram.percent:.0f}%")

            # GPU (detectar si hay CUDA disponible)
            self._update_gpu_info()

            # Batería
            battery = psutil.sensors_battery()
            if battery is not None:
                self.labels["bat"].setText(f"BAT: {int(battery.percent)}%")
            else:
                self.labels["bat"].setText("BAT: AC")  # Enchufado
        else:
            # psutil no disponible
            self.labels["cpu"].setText("CPU: N/A")
            self.labels["ram"].setText("RAM: N/A")
            self.labels["gpu"].setText("GPU: N/A")
            self.labels["bat"].setText("BAT: N/A")

    def _update_gpu_info(self):
        """
        Detecta y muestra información de la GPU.

        Intenta importar torch para detectar CUDA. Si no está disponible
        o no hay GPU compatible, muestra "N/A".
        """
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                # Acortar nombre si es muy largo
                if len(gpu_name) > 15:
                    gpu_name = gpu_name[:12] + "..."
                self.labels["gpu"].setText(f"GPU: {gpu_name}")
            else:
                self.labels["gpu"].setText("GPU: N/A")
        except ImportError:
            # torch no instalado
            self.labels["gpu"].setText("GPU: N/A")

    # =========================================================================
    # MÉTODOS DE ACTUALIZACIÓN DESDE EL HILO DE VIDEO
    # =========================================================================

    def update_fps(self, current_fps: float):
        """
        Actualiza el valor de FPS mostrado.

        Este método es llamado desde el hilo de video con los FPS actuales.

        Args:
            current_fps: Fotogramas por segundo actuales.
        """
        self.fps = current_fps
        self.labels["fps"].setText(f"FPS: {int(self.fps)}")

    def update_detections(self, count: int):
        """
        Actualiza el contador de objetos detectados.

        Este método es llamado desde el hilo de video con el número
        de detecciones del frame actual.

        Args:
            count: Número de objetos detectados.
        """
        self.detections_count = count
        self.labels["objects"].setText(f"OBJECTS: {self.detections_count}")

    # =========================================================================
    # CONTROL DE ZOOM
    # =========================================================================

    def set_zoom_value(self, value):
        """
        Actualiza el valor del zoom mostrado.

        Args:
            value: Valor del slider (10-40, donde 10 = 1.0x).
        """
        zoom_level = value / 10.0
        self.lbl_zoom_val.setText(f"{zoom_level:.1f}x")
        self.slider_zoom.setValue(value)