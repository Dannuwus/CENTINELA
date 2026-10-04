# =============================================================================
# MÓDULO DE BARRA DE TÍTULO PERSONALIZADA
# =============================================================================
# Este módulo implementa una barra de título personalizada que reemplaza
# la barra nativa del sistema operativo (ventana sin bordes).
#
# Funcionalidades:
# 1. Logo de la aplicación
# 2. Botón de toggle rápido para YOLO (ON/OFF)
# 3. Botón de atajos de teclado (interrogación)
# 4. Botones de control de ventana (minimizar, maximizar, cerrar)
# 5. Arrastre de ventana (haciendo clic y moviendo)
#
# DEPENDENCIAS:
# - core.constants (rutas de recursos)
# - PySide6.QtCore (señales, Qt)
# - PySide6.QtGui (iconos)
# - PySide6.QtWidgets (widgets base)
# =============================================================================

# =============================================================================
# IMPORTS
# =============================================================================
from ui.widgets import HoverToolButton, TooltipMixin
from pathlib import Path  # Manejo de rutas de archivos
from core.constants import OBJ_COLORS, OBJ_LABEL
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget,  # Widget base
    QHBoxLayout,  # Layout horizontal
    QLabel,  # Etiqueta para logo
    QPushButton,  # Botón para YOLO
    QToolButton  # Botones de control
)


class TitleBar(QWidget, TooltipMixin):
    """
    Barra de título personalizada con logo y botones de control.

    Esta barra reemplaza la barra de título nativa del sistema operativo.
    Proporciona:
    - Logo de la aplicación
    - Toggle rápido de YOLO
    - Botones de minimizar, maximizar y cerrar
    - Arrastre de ventana
    - Acceso rápido a atajos de teclado

    Señales emitidas:
        minimize_requested: Solicita minimizar la ventana.
        maximize_requested: Solicita maximizar/restaurar la ventana.
        close_requested: Solicita cerrar la ventana.
        yolo_toggle_requested: Solicita alternar estado de YOLO.
        capture_requested: Solicita captura rápida.
        shortcuts_requested: Solicita mostrar diálogo de atajos.
    """

    # =========================================================================
    # SEÑALES
    # =========================================================================

    # Señal para minimizar la ventana principal
    minimize_requested = Signal()

    # Señal para maximizar/restaurar la ventana principal
    maximize_requested = Signal()

    # Señal para cerrar la ventana principal
    close_requested = Signal()

    # Señal para alternar YOLO desde la barra de título
    yolo_toggle_requested = Signal()

    # Señal para captura rápida (no se usa actualmente)
    capture_requested = Signal()

    # Señal para mostrar diálogo de atajos
    shortcuts_requested = Signal()

    # Señal para alternar sonido (silencio)
    sound_toggle_requested = Signal()

    # Señal para alternar un tipo de objeto (clave: 'person', 'car', 'boat', 'helicopter')
    objeto_toggle_requested = Signal(str)

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def __init__(self, parent=None):
        """
        Inicializa la barra de título personalizada.

        Args:
            parent: Widget padre (opcional, normalmente MainWindow).
        """
        super().__init__(parent)

        # ---------------------------------------------------------------------
        # CONFIGURACIÓN BÁSICA
        # ---------------------------------------------------------------------
        self.setObjectName("titleBar")
        self.setFixedHeight(36)  # Altura fija de la barra
        self.drag_pos = None  # Posición para arrastre de ventana

        # ---------------------------------------------------------------------
        # LAYOUT PRINCIPAL
        # ---------------------------------------------------------------------
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 5, 0)  # (izq, arriba, der, abajo)
        layout.setSpacing(4)  # Espaciado entre elementos

        # =====================================================================
        # 1. LOGO DE LA APLICACIÓN
        # =====================================================================
        self.logo_label = QLabel()
        self.logo_label.setObjectName("logoLabel")
        self.logo_label.setFixedSize(24, 24)
        self.logo_label.setAlignment(Qt.AlignCenter)

        # Cargar logo con fallback seguro
        self._load_logo()

        layout.addWidget(self.logo_label)
        layout.addSpacing(6)  # Separación entre logo y botones

        # =====================================================================
        # 2. BOTÓN DE TOGGLE YOLO
        # =====================================================================
        self.btn_yolo_toggle = QPushButton("YOLO: OFF")
        self.btn_yolo_toggle.setObjectName("yoloQuickToggle")
        self.btn_yolo_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_yolo_toggle.clicked.connect(self.yolo_toggle_requested.emit)
        self.btn_yolo_toggle.setFixedHeight(24)
        layout.addWidget(self.btn_yolo_toggle)

        # Establecer estado visual inicial (desactivado)
        self.set_yolo_active(False)

        # =====================================================================
        # 2.1 BOTONES DE OBJETOS DETECTABLES
        # =====================================================================
        self.object_buttons = {}  # Almacena botones por clave

        # Lista de objetos: (clave, texto corto)
        objetos = [
            ('person', 'P'),
            ('car', 'C'),
            ('boat', 'B'),
            ('helicopter', 'H')
        ]

        for obj_key, short_text in objetos:
            btn = HoverToolButton()
            btn.setText(short_text)
            btn.setCheckable(True)
            btn.setObjectName("objectQuickToggle")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(24)
            btn.setMinimumWidth(28)
            btn.setMaximumWidth(28)
            btn.setStyleSheet("padding: 0px 2px;")
            # Tooltip con nombre y atajo correspondiente
            atajos = {
                'person': 'Ctrl+3',
                'car': 'Ctrl+4',
                'boat': 'Ctrl+5',
                'helicopter': 'Ctrl+6'
            }
            tooltip_text = f"{obj_key.capitalize()} <span style='color:#888888'>{atajos.get(obj_key, '')}</span>"

            btn.entered.connect(lambda b=btn, t=tooltip_text: self.show_tooltip(b, t, position='bottom'))
            btn.left.connect(self.hide_tooltip)

            # Conectar clic para emitir señal con la clave
            btn.clicked.connect(lambda checked, k=obj_key: self.objeto_toggle_requested.emit(k))
            self.object_buttons[obj_key] = btn
            layout.addWidget(btn)

        # Inicialmente todos desactivados (gris)
        for key in self.object_buttons:
            self.set_object_active(key, False)

        # =====================================================================
        # 3. ESPACIADOR DINÁMICO
        # =====================================================================
        # Empuja los botones de control a la derecha
        layout.addStretch()

        # =====================================================================
        # 4. BOTÓN DE SONIDO (CAMPANITA)
        # =====================================================================
        self.btn_sound = HoverToolButton()
        self.btn_sound.setObjectName("soundQuickToggle")
        self.btn_sound.setCursor(Qt.PointingHandCursor)
        self.btn_sound.setFixedSize(28, 28)
        self.btn_sound.setCheckable(True)

        # Tooltip personalizado
        self.btn_sound.entered.connect(
            lambda b=self.btn_sound, t="Sonido <span style='color:#888888'>Ctrl+M</span>": self.show_tooltip(b, t, position='bottom')
        )
        self.btn_sound.left.connect(self.hide_tooltip)
        self.btn_sound.clicked.connect(self.sound_toggle_requested.emit)
        layout.addWidget(self.btn_sound)

        # Estado inicial (sonido activado)
        self.set_sound_active(True)

        # =====================================================================
        # 5. BOTÓN DE ATAJOS (INTERROGACIÓN)
        # =====================================================================
        self.btn_shortcuts = QToolButton()
        self.btn_shortcuts.setText("?")
        self.btn_shortcuts.setObjectName("titleButton")
        self.btn_shortcuts.setFixedSize(28, 28)
        self.btn_shortcuts.clicked.connect(self.shortcuts_requested.emit)
        layout.addWidget(self.btn_shortcuts)

        # =====================================================================
        # 6. BOTONES DE CONTROL DE VENTANA
        # =====================================================================

        # Botón Minimizar
        self.btn_minimize = QToolButton()
        self.btn_minimize.setText("—")  # Carácter de guión largo
        self.btn_minimize.setObjectName("titleButton")
        self.btn_minimize.setFixedSize(28, 28)
        self.btn_minimize.clicked.connect(self.minimize_requested.emit)
        layout.addWidget(self.btn_minimize)

        # Botón Maximizar / Restaurar
        self.btn_maximize = QToolButton()
        self.btn_maximize.setText("❐")  # Símbolo de maximizar
        self.btn_maximize.setObjectName("titleButton")
        self.btn_maximize.setFixedSize(28, 28)
        self.btn_maximize.clicked.connect(self.maximize_requested.emit)
        layout.addWidget(self.btn_maximize)

        # Botón Cerrar
        self.btn_close = QToolButton()
        self.btn_close.setText("✕")  # Símbolo de cierre
        self.btn_close.setObjectName("closeButton")  # Estilo especial (rojo al hover)
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.clicked.connect(self.close_requested.emit)
        layout.addWidget(self.btn_close)

        # Inicializar atributo del tooltip personalizado
        self.tooltip_label = None

    def showEvent(self, event):
        """
        Inicializa el tooltip personalizado cuando la barra se muestra.

        Args:
            event: Evento de muestra.
        """
        super().showEvent(event)
        self._ensure_tooltip()

    # =========================================================================
    # MÉTODOS DE CARGA DE LOGO
    # =========================================================================

    def _load_logo(self):
        """
        Carga el logo de la aplicación con manejo de errores.

        Intenta cargar el logo SVG primero, luego ICO como fallback.
        Si ninguno existe o no se puede decodificar, muestra "?".
        """
        # Ruta al logo SVG (preferido por ser escalable)
        logo_path = Path(__file__).parent.parent / "resources" / "assets" / "logo_white.svg"

        if logo_path.exists():
            icon = QIcon(str(logo_path))
            if not icon.isNull():
                self.logo_label.setPixmap(icon.pixmap(24, 24))
                return

        # Fallback: intentar con ICO
        ico_path = Path(__file__).parent.parent / "resources" / "assets" / "logo_white.ico"
        if ico_path.exists():
            icon = QIcon(str(ico_path))
            if not icon.isNull():
                self.logo_label.setPixmap(icon.pixmap(24, 24))
                return

        # Último recurso: mostrar signo de interrogación
        self.logo_label.setText("?")

    # =========================================================================
    # MÉTODOS DE ESTADO VISUAL
    # =========================================================================

    def set_object_active(self, obj_key: str, active: bool):
        """
        Actualiza el estilo visual del botón de objeto según su estado.

        Args:
            obj_key: Clave del objeto ('person', 'car', 'boat', 'helicopter').
            active: True para activo (color), False para inactivo (gris).
        """
        btn = self.object_buttons.get(obj_key)
        if not btn:
            return

        color = OBJ_COLORS.get(obj_key, {}).get('border', '#aaaaaa')
        if active:
            btn.setStyleSheet(f"""
                QToolButton#objectQuickToggle {{
                    background-color: {color};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                }}
                QToolButton#objectQuickToggle:hover {{
                    background-color: {color};
                }}
            """)
        else:
            btn.setStyleSheet("""
                QToolButton#objectQuickToggle {
                    background-color: #555555;
                    color: #888888;
                    border: none;
                    border-radius: 4px;
                    font-weight: normal;
                }
                QToolButton#objectQuickToggle:hover {
                    background-color: #666666;
                }
            """)
        btn.setChecked(active)

    def set_sound_active(self, active: bool):
        """
        Actualiza el icono y estilo del botón de sonido según su estado.

        Args:
            active: True si el sonido está activado, False si silenciado.
        """
        if active:
            self.btn_sound.setText("🕭")  # Altavoz con ondas
            self.btn_sound.setStyleSheet("""
                QToolButton#soundQuickToggle {
                    background-color: transparent;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                }
                QToolButton#soundQuickToggle:hover {
                    background-color: #3a3a3a;
                }
            """)
        else:
            self.btn_sound.setText("🕭⃠")  # Altavoz silenciado
            self.btn_sound.setStyleSheet("""
                QToolButton#soundQuickToggle {
                    background-color: transparent;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                    color: #888888;
                }
                QToolButton#soundQuickToggle:hover {
                    background-color: #3a3a3a;
                }
            """)

    def set_yolo_active(self, active):
        """
        Actualiza el estilo y texto del botón YOLO según su estado.

        Args:
            active: True para estado activo (verde), False para inactivo (rojo).
        """
        # Asegurar que el botón esté habilitado
        self.btn_yolo_toggle.setEnabled(True)

        if active:
            # Estado activo: verde
            self.btn_yolo_toggle.setText("YOLO: ON")
            self.btn_yolo_toggle.setStyleSheet("""
                QPushButton#yoloQuickToggle {
                    background-color: #4CAF50;  /* Verde */
                    color: white;
                    border: none;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton#yoloQuickToggle:hover {
                    background-color: #45a049;  /* Verde más oscuro al hover */
                }
            """)
        else:
            # Estado inactivo: rojo
            self.btn_yolo_toggle.setText("YOLO: OFF")
            self.btn_yolo_toggle.setStyleSheet("""
                QPushButton#yoloQuickToggle {
                    background-color: #f44336;  /* Rojo */
                    color: white;
                    border: none;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton#yoloQuickToggle:hover {
                    background-color: #d32f2f;  /* Rojo más oscuro al hover */
                }
            """)

    def set_yolo_loading(self):
        """
        Pone el botón YOLO en estado de carga.

        Se usa cuando el modelo YOLO está cargando para indicar
        que no se puede interactuar temporalmente.
        """
        self.btn_yolo_toggle.setText("YOLO: Loading...")
        self.btn_yolo_toggle.setEnabled(False)  # Deshabilitar durante carga
        self.btn_yolo_toggle.setStyleSheet("""
            QPushButton#yoloQuickToggle {
                background-color: #666666;  /* Gris neutro */
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)

    # =========================================================================
    # MANEJO DE ARRASTRE DE VENTANA
    # =========================================================================

    def mousePressEvent(self, event):
        """
        Inicia el arrastre de la ventana al hacer clic izquierdo.

        Guarda la posición relativa del clic respecto a la ventana
        para poder moverla correctamente durante el arrastre.

        Args:
            event: Evento de mouse.
        """
        if event.button() == Qt.LeftButton:
            # Calcular offset entre el clic y la esquina de la ventana
            self.drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """
        Mueve la ventana durante el arrastre.

        Args:
            event: Evento de movimiento del mouse.
        """
        if event.buttons() & Qt.LeftButton and self.drag_pos is not None:
            # Mover la ventana a la nueva posición
            self.window().move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        """
        Finaliza el arrastre de la ventana.

        Args:
            event: Evento de liberación del mouse.
        """
        self.drag_pos = None  # Limpiar posición de arrastre
        event.accept()