# =============================================================================
# MÓDULO DE WIDGETS REUTILIZABLES
# =============================================================================
# Este módulo contiene widgets personalizados que se usan en toda la interfaz:
# 1. HoverToolButton: QToolButton con señales de hover para tooltips
# 2. TooltipMixin: Mixin para tooltips personalizados flotantes
# 3. ToggleSwitch: Interruptor deslizante estilo iOS/Android
# 4. SeparadorGrueso: Línea divisoria gruesa (2px)
# 5. SeparadorDelgado: Línea divisoria delgada (1px)
# 6. FocusEscapableLineEdit: QLineEdit que pierde foco con Escape
# 7. ClickableLabel: QLabel con señales de doble clic y clic derecho
#
# DEPENDENCIAS:
# - PySide6.QtCore: Clases base, animaciones, señales
# - PySide6.QtGui: Renderizado, colores, iconos
# - PySide6.QtWidgets: Widgets base de Qt
# =============================================================================

# =============================================================================
# IMPORTS DE PYQT
# =============================================================================
from PySide6.QtCore import (
    Qt,  # Constantes de alineación, cursores, etc.
    Signal,  # Para definir señales personalizadas
    QPoint,  # Punto 2D para posicionamiento
    QRectF,  # Rectángulo con floats (para dibujo)
    QPropertyAnimation,  # Animación de propiedades
    QEasingCurve,  # Curvas de easing para animaciones
    Property  # Decorador para propiedades animables
)
from PySide6.QtGui import (
    QPainter,  # Renderizado 2D personalizado
    QColor,  # Colores RGB/HSL
)
from PySide6.QtWidgets import (
    QLabel,  # Etiqueta de texto/imagen
    QToolButton,  # Botón de barra de herramientas
    QCheckBox,  # Checkbox base (ToggleSwitch hereda de aquí)
    QFrame,  # Marco con bordes (separadores heredan de aquí)
    QLineEdit  # Campo de entrada de texto
)


# =============================================================================
# TOOLTIPS PARA LAS PESTAÑAS
# =============================================================================

class HoverToolButton(QToolButton):
    """
    QToolButton que emite señales al entrar y salir el mouse.

    A diferencia de QToolButton estándar, este widget emite señales
    personalizadas 'entered' y 'left' que permiten mostrar tooltips
    personalizados de forma instantánea al pasar el cursor.

    Señales:
        entered: Emitida cuando el mouse entra al widget.
        left: Emitida cuando el mouse sale del widget.
    """

    # Señales personalizadas
    entered = Signal()  # Mouse entró al widget
    left = Signal()  # Mouse salió del widget

    def enterEvent(self, event):
        """
        Se ejecuta cuando el mouse entra al widget.
        Emite la señal 'entered' antes de llamar al método padre.
        """
        self.entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """
        Se ejecuta cuando el mouse sale del widget.
        Emite la señal 'left' antes de llamar al método padre.
        """
        self.left.emit()
        super().leaveEvent(event)


class TooltipMixin:
    """
    Mixin que proporciona funcionalidad de tooltip personalizado.

    Este mixin permite a cualquier widget mostrar tooltips flotantes
    personalizados en lugar de los tooltips nativos del sistema.

    Las clases que hereden este mixin deben:
    1. Llamar a self._init_tooltip() en su __init__ o showEvent
    2. Tener un atributo tooltip_label inicializado a None

    Uso:
        class MiWidget(QWidget, TooltipMixin):
            def __init__(self):
                super().__init__()
                self.tooltip_label = None
                self._init_tooltip()
    """

    def _init_tooltip(self):
        """
        Inicializa el QLabel del tooltip como hijo de la ventana principal.

        El tooltip se crea como hijo de la ventana principal para que
        pueda mostrarse fuera de los límites del widget que lo invoca.
        """
        if not hasattr(self, 'tooltip_label'):
            self.tooltip_label = None

    def _ensure_tooltip(self):
        """
        Crea el tooltip si aún no existe.

        El tooltip es un QLabel flotante con estilo personalizado que
        se posiciona dinámicamente cerca del widget de referencia.
        """
        if self.tooltip_label is None:
            self.tooltip_label = QLabel(self.window())
            self.tooltip_label.setObjectName("customTooltip")
            self.tooltip_label.setAttribute(Qt.WA_StyledBackground, True)
            self.tooltip_label.setAlignment(Qt.AlignVCenter)
            self.tooltip_label.setFixedHeight(36)
            self.tooltip_label.setVisible(False)
            self.tooltip_label.raise_()  # Asegurar que esté por encima

    def show_tooltip(self, widget, text, position='right'):
        """
        Muestra el tooltip en la posición especificada.

        Args:
            widget: Widget de referencia para posicionar el tooltip.
            text: Texto a mostrar en el tooltip.
            position: Posición relativa al widget ('right', 'left', 'bottom').
        """
        self._ensure_tooltip()

        # Configurar texto y ajustar tamaño
        self.tooltip_label.setText(text)
        self.tooltip_label.adjustSize()

        # Obtener posición global del widget de referencia
        global_pos = widget.mapToGlobal(QPoint(0, 0))

        # Calcular posición del tooltip según la dirección
        if position == 'right':
            x = global_pos.x() + widget.width() + 5
            y = global_pos.y() + (widget.height() - self.tooltip_label.height()) // 2
        elif position == 'left':
            x = global_pos.x() - self.tooltip_label.width() - 5
            y = global_pos.y() + (widget.height() - self.tooltip_label.height()) // 2
        elif position == 'bottom':
            x = global_pos.x() + (widget.width() - self.tooltip_label.width()) // 2
            y = global_pos.y() + widget.height() + 5
        else:  # Fallback: esquina superior izquierda
            x = global_pos.x()
            y = global_pos.y()

        # Posicionar y mostrar
        self.tooltip_label.move(x, y)
        self.tooltip_label.setVisible(True)
        self.tooltip_label.raise_()

    def hide_tooltip(self):
        """
        Oculta el tooltip personalizado.

        Se llama cuando el mouse sale del widget para limpiar la UI.
        """
        if hasattr(self, 'tooltip_label') and self.tooltip_label is not None:
            self.tooltip_label.setVisible(False)


# =============================================================================
# TOGGLE SWITCH REUTILIZABLE
# =============================================================================

class ToggleSwitch(QCheckBox):
    """
    Interruptor deslizante personalizado (toggle switch).

    Reemplaza visualmente al checkbox estándar por un interruptor animado
    estilo iOS/Android. Mantiene toda la funcionalidad de QCheckBox pero
    con una apariencia más moderna y atractiva.

    Características:
    - Animación suave de deslizamiento (200ms)
    - Color verde cuando está activo
    - Color gris oscuro cuando está inactivo
    - Bola blanca que se desliza
    - Tamaño fijo: 44x28 píxeles

    Uso:
        toggle = ToggleSwitch()
        toggle.toggled.connect(mi_funcion)  # Señal cuando cambia estado
        toggle.setChecked(True)             # Activar
    """

    def __init__(self, parent=None):
        """
        Inicializa el interruptor deslizante.

        Args:
            parent: Widget padre (opcional).
        """
        super().__init__(parent)

        # Configuración visual
        self.setCursor(Qt.PointingHandCursor)  # Cursor de mano al pasar
        self.setFixedSize(44, 28)  # Tamaño estándar para todos

        # Dimensiones internas
        self._margin = 6  # Margen para la bola
        self._ball_size = 20  # Tamaño visual de la bola (referencia)
        self._track_color = QColor("#39393d")  # Color del track (gris)
        self._ball_x = self._margin  # Posición inicial de la bola

        # Animación de deslizamiento
        self._position_animation = QPropertyAnimation(self, b"ballPosition")
        self._position_animation.setDuration(200)  # 200ms de duración
        self._position_animation.setEasingCurve(QEasingCurve.InOutCubic)

        # Conectar señal de cambio de estado a la animación
        self.toggled.connect(self._animate)

    # =========================================================================
    # PROPIEDAD ANIMABLE
    # =========================================================================

    def get_ball_position(self):
        """
        Obtiene la posición actual de la bola (para la animación).

        Returns:
            float: Posición X de la bola en píxeles.
        """
        return self._ball_x

    def set_ball_position(self, x):
        """
        Establece la posición de la bola (usado por la animación).

        Args:
            x: Nueva posición X en píxeles.
        """
        self._ball_x = x
        self.update()  # Redibujar el widget

    # Propiedad Qt para la animación
    ballPosition = Property(float, get_ball_position, set_ball_position)

    # =========================================================================
    # ANIMACIÓN
    # =========================================================================

    def _animate(self, checked):
        """
        Anima la bola al cambiar el estado del interruptor.

        Args:
            checked: True si el interruptor está activado, False si no.
        """
        # Actualizar color del track según estado
        if checked:
            self._track_color = QColor("#34c759")  # Verde (activo)
            # Posición derecha: más separada del borde
            target_x = self.width() - self._margin - 18  # 18 = tamaño real de bola
        else:
            self._track_color = QColor("#39393d")  # Gris oscuro (inactivo)
            # Posición izquierda
            target_x = self._margin

        # Redibujar con el nuevo color
        self.update()

        # Reiniciar y ejecutar animación de deslizamiento
        self._position_animation.stop()
        self._position_animation.setStartValue(self._ball_x)
        self._position_animation.setEndValue(target_x)
        self._position_animation.start()

    # =========================================================================
    # RENDERIZADO PERSONALIZADO
    # =========================================================================

    def paintEvent(self, event):
        """
        Dibuja el interruptor personalizado (track + bola).

        Este método reemplaza completamente el dibujo estándar del checkbox.
        Dibuja un track redondeado y una bola que se desliza.

        Args:
            event: Evento de pintado (no se usa directamente).
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # Bordes suaves

        # Dimensiones de la bola
        actual_ball_size = 18

        # Calcular margen vertical para centrar la bola
        vertical_margin = (self.height() - actual_ball_size) / 2

        # Dimensiones del track
        track_height = self.height() - 4  # 2px de margen arriba y abajo
        track_radius = track_height / 2  # Radio para bordes redondeados

        # Dibujar el track (fondo del interruptor)
        track_rect = QRectF(2, 2, self.width() - 4, track_height)
        painter.setPen(Qt.NoPen)  # Sin borde
        painter.setBrush(self._track_color)  # Color del track
        painter.drawRoundedRect(track_rect, track_radius, track_radius)

        # Dibujar la bola (thumb) centrada verticalmente
        thumb_rect = QRectF(self._ball_x, vertical_margin, actual_ball_size, actual_ball_size)
        painter.setBrush(QColor("#ffffff"))  # Bola blanca
        painter.drawEllipse(thumb_rect)  # Bola circular

    # =========================================================================
    # MANEJO DE EVENTOS DEL MOUSE
    # =========================================================================

    def mousePressEvent(self, event):
        """
        Maneja clic izquierdo alternando el estado del switch.

        A diferencia del checkbox estándar, este switch responde al clic
        en cualquier parte del widget, no solo en el indicador.

        Args:
            event: Evento de mouse.
        """
        if event.button() == Qt.LeftButton:
            self.setChecked(not self.isChecked())
            event.accept()
        else:
            super().mousePressEvent(event)


# =============================================================================
# SEPARADORES REUTILIZABLES
# =============================================================================

class SeparadorGrueso(QFrame):
    """
    Línea horizontal gruesa (2px) para separar títulos de sección.

    Se usa para separar visualmente las secciones principales dentro
    de los paneles de configuración. Tiene un color blanco brillante
    que destaca sobre el fondo oscuro.

    Uso:
        layout.addWidget(SeparadorGrueso())
    """

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.HLine)  # Línea horizontal
        self.setObjectName("dividerLineThick")
        self.setFixedHeight(2)  # Altura fija de 2px
        self.setStyleSheet("""
            QFrame#dividerLineThick {
                background-color: #ffffff;  /* Blanco brillante */
                border: none;
                margin: 4px 0px;  /* Espaciado vertical */
            }
        """)


class SeparadorDelgado(QFrame):
    """
    Línea horizontal delgada (1px) para separar opciones dentro de una sección.

    Se usa para separar opciones individuales dentro de una misma sección.
    Tiene un color gris más sutil para no competir visualmente con los
    separadores gruesos.

    Uso:
        layout.addWidget(SeparadorDelgado())
    """

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.HLine)  # Línea horizontal
        self.setObjectName("dividerLine")
        self.setFixedHeight(1)  # Altura fija de 1px
        self.setStyleSheet("""
            QFrame#dividerLine {
                background-color: #3e3e3e;  /* Gris oscuro sutil */
                border: none;
                margin: 8px 0px;  /* Más espaciado vertical */
            }
        """)


# =============================================================================
# WIDGETS DE ENTRADA DE TEXTO
# =============================================================================

class FocusEscapableLineEdit(QLineEdit):
    """
    QLineEdit que pierde el foco al presionar la tecla Escape.

    Este comportamiento es útil para campos de URL RTSP donde el usuario
    puede querer salir rápidamente del campo sin usar el mouse. Al presionar
    Escape, el foco vuelve a la ventana principal, permitiendo usar atajos
    de teclado globales sin interferencias.

    Uso:
        campo_url = FocusEscapableLineEdit()
        campo_url.setPlaceholderText("rtsp://...")
    """

    def keyPressEvent(self, event):
        """
        Maneja la pulsación de teclas, especialmente Escape.

        Args:
            event: Evento de teclado.
        """
        if event.key() == Qt.Key_Escape:
            # Quitar el foco del campo de texto
            self.clearFocus()

            # Devolver el foco a la ventana principal
            if self.window():
                self.window().setFocus()

            # Consumir el evento para que no se propague
            event.accept()
        else:
            # Para cualquier otra tecla, comportamiento normal
            super().keyPressEvent(event)


# =============================================================================
# LABEL CON SEÑALES DE MOUSE
# =============================================================================

class ClickableLabel(QLabel):
    """
    QLabel que emite señales personalizadas para doble clic y clic derecho.

    Se usa principalmente en la galería de capturas para permitir:
    - Doble clic: abrir la imagen con la aplicación predeterminada
    - Clic derecho: mostrar menú contextual (eliminar, etc.)

    Señales:
        doubleClicked(str): Emitida con la ruta al hacer doble clic.
        rightClicked(str): Emitida con la ruta al hacer clic derecho.

    Uso:
        label = ClickableLabel("/ruta/a/imagen.jpg")
        label.doubleClicked.connect(abrir_imagen)
        label.rightClicked.connect(mostrar_menu)
    """

    # Señales personalizadas
    doubleClicked = Signal(str)  # Emitida con la ruta al hacer doble clic
    rightClicked = Signal(str)  # Emitida con la ruta al hacer clic derecho

    def __init__(self, path=""):
        """
        Inicializa la etiqueta clicable.

        Args:
            path: Ruta de la imagen asociada (opcional).
        """
        super().__init__()
        self.path = path  # Ruta de la imagen

    def mouseDoubleClickEvent(self, event):
        """
        Maneja el evento de doble clic.

        Emite la señal 'doubleClicked' con la ruta si existe.

        Args:
            event: Evento de doble clic.
        """
        if self.path:
            self.doubleClicked.emit(self.path)
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        """
        Maneja el evento de clic.

        Para clic derecho, emite la señal 'rightClicked'.
        Para otros botones, comportamiento normal.

        Args:
            event: Evento de mouse.
        """
        if event.button() == Qt.RightButton and self.path:
            self.rightClicked.emit(self.path)
            event.accept()
        else:
            super().mousePressEvent(event)