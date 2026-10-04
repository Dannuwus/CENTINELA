# =============================================================================
# MÓDULO DE NOTIFICACIÓN TOAST
# =============================================================================
# Este módulo implementa notificaciones flotantes temporales (toast).
#
# Funcionalidades:
# 1. Aparición en la esquina inferior derecha de la ventana
# 2. Auto-cierre después de un tiempo configurable (default: 5 segundos)
# 3. Sin bordes y siempre visible por encima de otras ventanas
# 4. Transparente para eventos del mouse (no bloquea clics)
# 5. Animación de desvanecimiento al cerrar
#
# Las notificaciones toast se usan para informar al usuario sobre:
# - Detección de objetos
# - Conexión/desconexión de cámaras
# - Capturas guardadas
# - Errores
#
# DEPENDENCIAS:
# - PySide6.QtCore (Qt, QTimer, Signal, animaciones)
# - PySide6.QtWidgets (QWidget, QLabel)
# =============================================================================
from core.constants import TOAST_BG, TOAST_BORDER, TOAST_TEXT
# =============================================================================
# IMPORTS DE PYQT
# =============================================================================
from PySide6.QtCore import (
    Qt,  # Constantes de alineación, flags
    QTimer,  # Timer para auto-cierre
    Signal,  # Señales personalizadas
    QPropertyAnimation,  # Animación de propiedades (opacidad)
    QEasingCurve,  # Curvas de animación (aceleración/desaceleración)
)
from PySide6.QtWidgets import (
    QWidget,  # Widget base
    QVBoxLayout,  # Layout vertical
    QLabel,  # Etiqueta de mensaje
    QGraphicsOpacityEffect,  # Efecto de opacidad para animaciones
)

class ToastNotification(QWidget):
    """
    Notificación flotante temporal tipo toast.

    Aparece en la esquina inferior derecha de la ventana padre y se
    cierra automáticamente después de un tiempo configurable.

    Características:
    - Sin bordes (frameless)
    - Siempre visible (WindowStaysOnTopHint)
    - No bloquea interacción del usuario (TransparentForMouseEvents)
    - Auto-cierre con timer
    - Animación de desvanecimiento

    Señales:
        closed: Emitida cuando la notificación se cierra.

    Uso:
        toast = ToastNotification(parent, "Mensaje de prueba", duration=3000)
        toast.show_at_corner(ventana_principal)
    """

    # Señal emitida cuando el toast se cierra
    closed = Signal()

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def __init__(self, parent=None, message="", duration=5000):
        """
        Inicializa la notificación toast.

        Args:
            parent: Widget padre (opcional, normalmente MainWindow).
            message: Texto a mostrar en la notificación.
            duration: Tiempo en milisegundos antes de auto-cerrar (default: 5000ms).
        """
        super().__init__(parent)

        # El widget principal debe ser translúcido para permitir esquinas redondeadas
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # ---------------------------------------------------------------------
        # ESTILO LOCAL (porque los estilos globales no llegan a ventanas ToolTip)
        # ---------------------------------------------------------------------
        self.setStyleSheet(f"""
            QWidget#toastContainer {{
                background-color: {TOAST_BG};
                border: 1px solid {TOAST_BORDER};
                border-radius: 6px;
            }}
            QWidget#toastContainer QLabel {{
                color: {TOAST_TEXT};
                font-size: 12px;
                padding: 8px 12px;
                font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
                background: transparent;
                border: none;
            }}
        """)

        # ---------------------------------------------------------------------
        # CONFIGURACIÓN DE VENTANA
        # ---------------------------------------------------------------------
        self.setWindowFlags(
            Qt.FramelessWindowHint |  # Sin bordes
            Qt.ToolTip |  # Tipo tooltip (sin foco)
            Qt.WindowStaysOnTopHint  # Siempre visible
        )

        # Atributos especiales
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # No robar foco
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # No bloquear clics

        # ---------------------------------------------------------------------
        # CONTENEDOR INTERNO (fondo visible)
        # ---------------------------------------------------------------------
        # Creamos un widget hijo que será el que pinte el fondo, borde y radio
        self.container = QWidget(self)
        self.container.setObjectName("toastContainer")  # ← El QSS lo estiliza

        # Layout principal del toast (solo contiene al contenedor)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        # Layout interno del contenedor (contiene la etiqueta de mensaje)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)

        # Etiqueta con el mensaje
        self.label = QLabel(message)
        self.label.setAlignment(Qt.AlignCenter)
        container_layout.addWidget(self.label)

        # Ajustar tamaño al contenido
        self.adjustSize()

        # ---------------------------------------------------------------------
        # TIMER PARA AUTO-CIERRE
        # ---------------------------------------------------------------------
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fade_out)
        self.timer.start(duration)  # Iniciar countdown

        # ---------------------------------------------------------------------
        # ANIMACIÓN DE OPACIDAD
        # ---------------------------------------------------------------------
        self.opacity_effect = None  # Efecto de opacidad
        self.fade_animation = None  # Animación de desvanecimiento

    # =========================================================================
    # POSICIONAMIENTO
    # =========================================================================

    def show_at_corner(self, parent_widget):
        """
        Muestra el toast en la esquina inferior derecha del widget padre.

        Calcula la posición correcta basada en la geometría del widget
        padre para que el toast aparezca en la esquina inferior derecha
        con un margen de 20px horizontal y 40px vertical.

        Args:
            parent_widget: Widget padre (normalmente MainWindow).
        """
        if parent_widget:
            parent_rect = parent_widget.geometry()

            # Calcular posición: esquina inferior derecha con márgenes
            x = parent_rect.right() - self.width() - 20
            y = parent_rect.bottom() - self.height() - 40

            self.move(x, y)

        self.show()

    # =========================================================================
    # CIERRE Y ANIMACIÓN
    # =========================================================================

    def fade_out(self):
        """
        Inicia la animación de desvanecimiento y cierra la notificación.

        Se llama automáticamente cuando el timer llega a cero.
        Detiene el timer, crea un efecto de opacidad y anima
        la transparencia hasta 0.0 antes de cerrar el widget.
        """
        # Detener timer para evitar múltiples llamadas
        self.timer.stop()

        # Crear efecto de opacidad si no existe
        if self.opacity_effect is None:
            self.opacity_effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self.opacity_effect)

        # Crear animación de desvanecimiento
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(300)  # 300 ms de fade-out suave
        self.fade_animation.setStartValue(1.0)
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.setEasingCurve(QEasingCurve.OutQuad)  # Curva suave

        # Conectar fin de animación con el cierre real
        self.fade_animation.finished.connect(self._on_fade_finished)

        # Iniciar animación
        self.fade_animation.start()

    def _on_fade_finished(self):
        """
        Se ejecuta cuando la animación de desvanecimiento termina.

        Emite la señal 'closed' y cierra el widget definitivamente.
        """
        # Emitir señal de cierre
        self.closed.emit()

        # Cerrar widget
        self.close()