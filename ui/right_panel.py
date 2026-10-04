# =============================================================================
# MÓDULO DE PANEL DERECHO (CAPTURAS Y LOGS)
# =============================================================================
# Este módulo implementa el panel derecho que contiene:
# 1. Pestaña de Capturas: Galería de imágenes capturadas con filtros
# 2. Pestaña de Logs: Registro de eventos del sistema
#
# El panel tiene una barra de navegación vertical con iconos para cambiar
# entre las pestañas. Puede expandirse/colapsarse haciendo clic en el icono
# de la pestaña activa.
#
# DEPENDENCIAS:
# - core.constants (dimensiones)
# - ui.widgets (HoverToolButton, TooltipMixin)
# - ui.captures_page (página de galería)
# - ui.logs_page (página de logs)
# =============================================================================

# =============================================================================
# IMPORTS DE PYQT
# =============================================================================
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QButtonGroup, QStyle
)

# =============================================================================
# IMPORTS INTERNOS
# =============================================================================
from core.constants import ICON_SIZE, NAV_BAR_WIDTH, TOOLBUTTON_SIZE
from ui.widgets import HoverToolButton, TooltipMixin
from ui.captures_page import CapturesPage
from ui.logs_page import LogsPage


class RightPanel(QWidget, TooltipMixin):
    """
    Panel lateral derecho con pestañas (capturas, logs).

    Este panel contiene 2 pestañas accesibles mediante iconos verticales:
    - Capturas: Galería de imágenes con filtros de búsqueda
    - Logs: Registro de eventos del sistema

    Señales emitidas:
        toggle_panel_requested(bool): Solicita expandir (True) o colapsar (False).

    Uso:
        right_panel = RightPanel(config_manager)
        right_panel.toggle_panel_requested.connect(on_toggle)
    """

    # Señal para expandir/colapsar el panel
    toggle_panel_requested = Signal(bool)  # True: expandir, False: colapsar

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def __init__(self, config_manager):
        """
        Inicializa el panel derecho.

        Args:
            config_manager: Instancia de ConfigManager para persistencia.
        """
        super().__init__()
        self.config = config_manager
        self.is_expanded = True  # Estado de expansión
        self.current_index = 0  # Pestaña activa (0 = Capturas)
        self.setup_ui()

        # El tooltip se creará cuando el panel se agregue a la ventana
        self.tooltip_label = None

    def showEvent(self, event):
        """
        Inicializa el tooltip cuando el panel se muestra.

        Args:
            event: Evento de muestra.
        """
        super().showEvent(event)
        self._ensure_tooltip()

    # =========================================================================
    # CONSTRUCCIÓN DE LA INTERFAZ
    # =========================================================================

    def setup_ui(self):
        """
        Configura el layout principal con contenido y barra de navegación.

        Estructura:
        [Contenido apilado] [Barra de iconos]
        La barra de iconos está a la derecha (a diferencia del panel izquierdo).
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---------------------------------------------------------------------
        # CONTENEDOR PRINCIPAL: CONTENIDO + BARRA LATERAL
        # ---------------------------------------------------------------------
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # =====================================================================
        # ÁREA DE CONTENIDO APILADO (IZQUIERDA)
        # =====================================================================
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("rightStack")

        # Crear página de capturas (galería)
        self.captures_page = CapturesPage(self.config)
        self.stacked_widget.addWidget(self.captures_page)

        # Crear página de logs
        self.logs_page = LogsPage()
        self.stacked_widget.addWidget(self.logs_page)

        # =====================================================================
        # BARRA LATERAL (ICONOS VERTICALES) A LA DERECHA
        # =====================================================================
        self.nav_bar = QWidget()
        self.nav_bar.setObjectName("rightNavBar")
        self.nav_bar.setFixedWidth(NAV_BAR_WIDTH)  # Ancho fijo para iconos

        nav_layout = QVBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        nav_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        # Grupo de botones para exclusividad
        self.nav_button_group = QButtonGroup(self)
        self.nav_button_group.setExclusive(True)

        # =====================================================================
        # BOTÓN DE CAPTURAS (ÍNDICE 0)
        # =====================================================================
        btn = HoverToolButton()
        btn.setCheckable(True)
        btn.setFixedSize(TOOLBUTTON_SIZE, TOOLBUTTON_SIZE)
        btn.setIconSize(ICON_SIZE)

        # Icono de carpeta
        icon = self.style().standardIcon(QStyle.SP_DirIcon)
        btn.setIcon(icon)
        btn.setObjectName("navButton")

        # Conexiones para tooltip (posición izquierda porque barra está a la derecha)
        tooltip_text = "Capturas <span style='color:#888888'>Alt+1</span>"
        btn.entered.connect(
            lambda b=btn, t=tooltip_text: self.show_tooltip(b, t, position='left')
        )
        btn.left.connect(self.hide_tooltip)

        # Agregar al grupo y layout
        self.nav_button_group.addButton(btn, 0)
        nav_layout.addWidget(btn)

        # Conectar clic
        btn.clicked.connect(lambda checked: self.on_nav_button_clicked(btn, 0))
        btn.setChecked(True)  # Seleccionado por defecto

        # =====================================================================
        # BOTÓN DE LOGS (ÍNDICE 1)
        # =====================================================================
        btn_logs = HoverToolButton()
        btn_logs.setCheckable(True)
        btn_logs.setFixedSize(TOOLBUTTON_SIZE, TOOLBUTTON_SIZE)
        btn_logs.setIconSize(ICON_SIZE)

        # Icono de información
        icon_logs = self.style().standardIcon(QStyle.SP_FileDialogInfoView)
        btn_logs.setIcon(icon_logs)
        btn_logs.setObjectName("navButton")

        # Conexiones para tooltip
        tooltip_text_logs = "Logs <span style='color:#888888'>Alt+2</span>"
        btn_logs.entered.connect(
            lambda b=btn_logs, t=tooltip_text_logs: self.show_tooltip(b, t, position='left')
        )
        btn_logs.left.connect(self.hide_tooltip)

        # Agregar al grupo y layout
        self.nav_button_group.addButton(btn_logs, 1)
        nav_layout.addWidget(btn_logs)

        # Conectar clic
        btn_logs.clicked.connect(lambda checked: self.on_nav_button_clicked(btn_logs, 1))

        # =====================================================================
        # AGREGAR AL LAYOUT HORIZONTAL
        # =====================================================================
        # Primero el contenido (expandible) y luego la barra (fija a la derecha)
        content_layout.addWidget(self.stacked_widget, 1)  # Stretch 1: expandir
        content_layout.addWidget(self.nav_bar)  # Fijo a la derecha

        layout.addLayout(content_layout)

    # =========================================================================
    # MANEJO DE NAVEGACIÓN
    # =========================================================================

    def on_nav_button_clicked(self, btn, index):
        """
        Maneja el clic en los iconos de navegación.

        Comportamiento:
        - Si se hace clic en la pestaña activa y está expandida, colapsa el panel.
        - Si el panel está colapsado, lo expande.
        - Cambia a la nueva pestaña.

        Args:
            btn: Botón de navegación clicado.
            index: Índice de la pestaña (0=Capturas, 1=Logs).
        """
        # Ocultar tooltip inmediatamente al hacer clic
        self.hide_tooltip()

        if index == self.current_index and self.is_expanded:
            # Colapsar porque se pulsó el icono activo
            self.toggle_panel_requested.emit(False)
            self.is_expanded = False
            self.stacked_widget.setVisible(False)
            btn.setChecked(False)
        else:
            # Expandir si estaba colapsado
            if not self.is_expanded:
                self.toggle_panel_requested.emit(True)
                self.is_expanded = True
                self.stacked_widget.setVisible(True)

            # Cambiar página
            self.stacked_widget.setCurrentIndex(index)
            self.current_index = index
            btn.setChecked(True)

    # =========================================================================
    # CONTROL DE EXPANSIÓN
    # =========================================================================

    def set_expanded(self, expanded: bool):
        """
        Expande o colapsa el panel (oculta/muestra el contenido).

        Args:
            expanded: True para expandir, False para colapsar.
        """
        self.is_expanded = expanded
        self.stacked_widget.setVisible(expanded)

        if expanded:
            # Expandir: permitir ancho máximo
            self.setMaximumWidth(16777215)  # Valor máximo de Qt
        else:
            # Colapsar: ancho fijo solo para la barra de iconos
            self.setFixedWidth(self.nav_bar.width())