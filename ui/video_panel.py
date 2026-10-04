# =============================================================================
# MÓDULO DE PANEL DE VIDEO (VISUALIZACIÓN)
# =============================================================================
# Este módulo implementa el panel central que muestra el video en tiempo real.
#
# Funcionalidades:
# 1. Visualización de video en uno o dos canales (modo dual stream)
# 2. Manejo de clics para seleccionar canal activo (zoom/paneo)
# 3. Conversión de frames OpenCV (BGR) a QPixmap para Qt
# 4. Escalado automático manteniendo relación de aspecto
# 5. Resaltado visual del canal activo
# 6. Gestión de frames actuales para captura manual
#
# DEPENDENCIAS:
# - cv2 (OpenCV): Conversión de formato de color
# - PySide6.QtCore: Señales, Qt
# - PySide6.QtGui: QImage, QPixmap
# - PySide6.QtWidgets: Widgets base
# =============================================================================

# =============================================================================
# IMPORTS
# =============================================================================
import cv2  # OpenCV para conversión BGR->RGB
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget,  # Widget base
    QVBoxLayout,  # Layout vertical
    QHBoxLayout,  # Layout horizontal
    QLabel  # Contenedor de video
)


class VideoPanel(QWidget):
    """
    Panel central que muestra el video con bounding boxes y HUD.

    Soporta dos modos:
    - Modo simple: solo canal 1 visible
    - Modo dual: canales 1 y 2 lado a lado

    Señales emitidas:
        pan_signal(float, float): Coordenadas de paneo para canal 1.
        pan_signal_2(float, float): Coordenadas de paneo para canal 2.
        camera_focused(int): Canal activo (1 o 2) al hacer clic.
    """

    # Señales de paneo (coordenadas normalizadas 0-1)
    pan_signal = Signal(float, float)  # Canal 1
    pan_signal_2 = Signal(float, float)  # Canal 2

    # Señal de canal enfocado (1 o 2)
    camera_focused = Signal(int)

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def __init__(self):
        super().__init__()

        # Estado de frames
        self.current_frame = None  # Frame actual del canal 1
        self.current_frame_2 = None  # Frame actual del canal 2
        self.raw_frame = None  # Frame sin procesar (para captura)
        self.detections = []  # Detecciones actuales
        self.fps = 0.0  # FPS actuales

        # Configuración de mouse
        self.setMouseTracking(True)  # Rastrear mouse sin clic

        # Estado de modo dual
        self.is_dual_mode = False  # Por defecto: modo simple
        self.active_channel = 1  # Canal activo: 1 = izquierda, 2 = derecha

        # Construir interfaz
        self.setup_ui()

    # =========================================================================
    # CONSTRUCCIÓN DE LA INTERFAZ
    # =========================================================================

    def setup_ui(self):
        """
        Configura el layout con dos contenedores de video lado a lado.

        Estructura:
        [Canal 1] [Canal 2]
        Ambos con stretch factor 1 para ocupar espacio equitativamente.
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---------------------------------------------------------------------
        # LAYOUT HORIZONTAL PARA LOS DOS CANALES
        # ---------------------------------------------------------------------
        self.video_layout = QHBoxLayout()
        self.video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_layout.setSpacing(2)  # Pequeña separación entre canales

        # =====================================================================
        # CANAL 1 (IZQUIERDA)
        # =====================================================================
        self.video_container = QLabel()
        self.video_container.setAlignment(Qt.AlignCenter)
        self.video_container.setStyleSheet("background-color: #0a0c0f;")
        self.video_container.setMinimumSize(320, 240)
        self.video_container.setText("CANAL 1  (SIN SEÑAL)")

        # =====================================================================
        # CANAL 2 (DERECHA) - OCULTO POR DEFECTO
        # =====================================================================
        self.video_container_2 = QLabel()
        self.video_container_2.setAlignment(Qt.AlignCenter)
        self.video_container_2.setStyleSheet("background-color: #0a0c0f;")
        self.video_container_2.setMinimumSize(320, 240)
        self.video_container_2.setText("CANAL 2 (SIN SEÑAL)")
        self.video_container_2.hide()  # Oculto hasta activar modo dual

        # Agregar ambos al layout
        self.video_layout.addWidget(self.video_container, 1)  # Stretch 1
        self.video_layout.addWidget(self.video_container_2, 1)  # Stretch 1

        layout.addLayout(self.video_layout, 1)

    # =========================================================================
    # MANEJO DE EVENTOS DEL MOUSE
    # =========================================================================

    def mousePressEvent(self, event):
        """
        Al hacer clic, activa el canal y actualiza el paneo.

        Determina en qué contenedor se hizo clic y emite la señal
        de paneo correspondiente.

        Args:
            event: Evento de mouse.
        """
        self.update_pan(event.position())

    def mouseMoveEvent(self, event):
        """
        Al mover con botón presionado, actualizar paneo.

        Solo responde si el botón izquierdo está presionado.

        Args:
            event: Evento de movimiento del mouse.
        """
        if event.buttons() & Qt.LeftButton:
            self.update_pan(event.position())

    def update_pan(self, pos):
        """
        Convierte posición del mouse a coordenadas normalizadas.

        Flujo:
        1. Determinar en qué contenedor se hizo clic
        2. Activar ese canal
        3. Convertir posición global a local del contenedor
        4. Normalizar coordenadas (0-1)
        5. Emitir señal de paneo correspondiente

        Args:
            pos: Posición del mouse (QPointF).
        """
        # ---------------------------------------------------------------------
        # 1. DETERMINAR CONTENEDOR Y CANAL ACTIVO
        # ---------------------------------------------------------------------
        if self.is_dual_mode:
            # Modo dual: verificar ambos contenedores
            if self.video_container.geometry().contains(pos.toPoint()):
                self.active_channel = 1
                target = self.video_container
                self.camera_focused.emit(1)
            elif self.video_container_2.geometry().contains(pos.toPoint()):
                self.active_channel = 2
                target = self.video_container_2
                self.camera_focused.emit(2)
            else:
                return  # Clic fuera de ambos contenedores
        else:
            # Modo simple: solo canal 1
            self.active_channel = 1
            target = self.video_container
            self.camera_focused.emit(1)

        # ---------------------------------------------------------------------
        # 2. CONVERTIR A COORDENADAS LOCALES Y NORMALIZAR
        # ---------------------------------------------------------------------
        w = target.width()
        h = target.height()

        if w > 0 and h > 0:
            # Convertir posición global a local del contenedor
            local_pos = target.mapFrom(self, pos.toPoint())

            # Normalizar coordenadas (0-1) con límites seguros
            pan_x = max(0.0, min(1.0, local_pos.x() / w))
            pan_y = max(0.0, min(1.0, local_pos.y() / h))

            # Emitir señal según canal activo
            if self.active_channel == 1:
                self.pan_signal.emit(pan_x, pan_y)
            else:
                self.pan_signal_2.emit(pan_x, pan_y)

    # =========================================================================
    # GESTIÓN DE MODO DUAL
    # =========================================================================

    def set_active_channel(self, channel):
        """
        Resalta visualmente el canal activo con un borde de color.

        Args:
            channel: 1 para canal izquierdo, 2 para canal derecho.
        """
        self.active_channel = channel

        # Estilos para canal activo/inactivo
        active_style = "border: 2px solid #aaaaaa; background-color: #0a0c0f;"
        inactive_style = "border: 2px solid transparent; background-color: #0a0c0f;"

        # Aplicar estilos
        self.video_container.setStyleSheet(
            active_style if channel == 1 else inactive_style
        )
        self.video_container_2.setStyleSheet(
            active_style if channel == 2 else inactive_style
        )

    def toggle_dual_mode(self, enabled):
        """
        Alterna entre modo simple y dual.

        Args:
            enabled: True para activar modo dual, False para modo simple.
        """
        self.is_dual_mode = enabled
        self.video_container_2.setVisible(enabled)

        if not enabled:
            # Limpiar canal 2 al desactivar
            self.video_container_2.clear()
            self.video_container_2.setText("CANAL 2 (SIN SEÑAL)")
            self.current_frame_2 = None

    # =========================================================================
    # ACTUALIZACIÓN DE FRAMES
    # =========================================================================

    def update_frame(self, frame, detections, fps, channel=1):
        """
        Actualiza y muestra un frame en el canal especificado.

        Convierte el frame OpenCV (BGR) a QPixmap y lo muestra en el
        contenedor correspondiente, escalando para mantener aspecto.

        Args:
            frame: Imagen OpenCV en formato BGR.
            detections: Lista de detecciones (no se usa directamente).
            fps: Fotogramas por segundo actuales.
            channel: 1 para canal izquierdo, 2 para canal derecho.
        """
        if frame is None:
            return

        # Guardar frame según canal
        if channel == 1:
            self.current_frame = frame
            target_label = self.video_container
        else:
            self.current_frame_2 = frame
            target_label = self.video_container_2

        # Guardar datos auxiliares
        self.detections = detections
        self.fps = fps

        # ---------------------------------------------------------------------
        # CONVERSIÓN BGR -> RGB -> QImage -> QPixmap
        # ---------------------------------------------------------------------
        # 1. Convertir BGR a RGB (OpenCV usa BGR, Qt usa RGB)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # 2. Obtener dimensiones
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w

        # 3. Crear QImage directamente desde el buffer numpy
        qt_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)

        # 4. Convertir a QPixmap
        pixmap = QPixmap.fromImage(qt_img)

        # ---------------------------------------------------------------------
        # ESCALADO MANTENIENDO RELACIÓN DE ASPECTO
        # ---------------------------------------------------------------------
        scaled = pixmap.scaled(
            target_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        target_label.setPixmap(scaled)

    def clear_frame(self, channel=1):
        """
        Limpia el frame del canal especificado.

        Se usa al detener la cámara o perder conexión para mostrar
        el mensaje "SIN SEÑAL".

        Args:
            channel: 1 para canal izquierdo, 2 para canal derecho.
        """
        if channel == 1:
            # Limpiar canal 1
            self.current_frame = None
            self.raw_frame = None
            self.detections = []
            self.fps = 0.0
            self.video_container.clear()
            self.video_container.setPixmap(QPixmap())
            self.video_container.setText("CANAL 1 (SIN SEÑAL)")
            self.video_container.repaint()
        else:
            # Limpiar canal 2
            self.current_frame_2 = None
            self.video_container_2.clear()
            self.video_container_2.setPixmap(QPixmap())
            self.video_container_2.setText("CANAL 2 (SIN SEÑAL)")
            self.video_container_2.repaint()

    def set_raw_frame(self, raw_frame):
        """
        Guarda el frame sin procesar para captura manual.

        Args:
            raw_frame: Frame OpenCV en formato BGR.
        """
        # Copiar para evitar que el hilo de video lo modifique
        self.raw_frame = raw_frame.copy() if raw_frame is not None else None

    # =========================================================================
    # MANEJO DE REDIMENSIONAMIENTO
    # =========================================================================

    def resizeEvent(self, event):
        """
        Redimensiona el video al cambiar el tamaño del widget.

        Cuando el usuario redimensiona la ventana, los frames actuales
        se re-escalan automáticamente para ajustarse al nuevo tamaño.

        Args:
            event: Evento de redimensionamiento.
        """
        # Re-escalar canal 1 si hay frame
        if self.current_frame is not None:
            self.update_frame(self.current_frame, self.detections, self.fps, channel=1)

        # Re-escalar canal 2 si hay frame
        if self.current_frame_2 is not None:
            self.update_frame(self.current_frame_2, self.detections, self.fps, channel=2)

        super().resizeEvent(event)