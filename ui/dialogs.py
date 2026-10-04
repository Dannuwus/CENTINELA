# =============================================================================
# MÓDULO DE DIÁLOGOS
# =============================================================================
# Este módulo contiene los diálogos modales y no modales del sistema:
# 1. CaptureInspectorDialog: Tabla detallada de capturas con miniaturas
# 2. ShortcutsDialog: Lista de atajos de teclado disponibles
#
# DEPENDENCIAS:
# - core.constants (DEFAULT_SAVE_PATH)
# - PySide6.QtCore (Qt, QSize, QUrl)
# - PySide6.QtGui (QColor, QPixmap, QDesktopServices)
# - PySide6.QtWidgets (diálogos, tablas, botones)
# =============================================================================

# =============================================================================
# IMPORTS ESTÁNDAR
# =============================================================================
from pathlib import Path  # Manejo de rutas

# =============================================================================
# IMPORTS DE PYQT
# =============================================================================
from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QColor, QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QWidget, QToolButton
)

# =============================================================================
# IMPORTS INTERNOS
# =============================================================================
from core.constants import DEFAULT_SAVE_PATH


# =============================================================================
# DIÁLOGO INSPECTOR DE CAPTURAS
# =============================================================================

class CaptureInspectorDialog(QDialog):
    """
    Diálogo con tabla detallada de capturas.

    Este diálogo muestra una tabla con todas las capturas registradas,
    incluyendo:
    - Miniatura de la imagen
    - ID de captura
    - Tipo de objeto detectado
    - Fecha y hora
    - Confianza de detección

    Características:
    - No modal (permite interactuar con la ventana principal)
    - Ordenamiento por fecha (más reciente primero)
    - Botón para abrir carpeta de capturas
    - Botón para cerrar

    Uso:
        dialog = CaptureInspectorDialog(
            parent=self,
            captures=lista_capturas,
            save_path=ruta_guardado
        )
        dialog.show()
    """

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def __init__(self, parent=None, captures=None, save_path=None):
        """
        Inicializa el diálogo inspector.

        Args:
            parent: Widget padre (opcional).
            captures: Lista de diccionarios con datos de capturas.
            save_path: Ruta de la carpeta de capturas.
        """
        super().__init__(parent)

        # Datos
        self.captures = captures if captures else []
        self.save_path = save_path if save_path else DEFAULT_SAVE_PATH

        # Configuración de la ventana
        self.setWindowTitle("INSPECTOR DE CAPTURAS")
        self.resize(800, 500)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)  # Sin bordes nativos

        # Estilo oscuro personalizado
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                border: 1px solid #3e3e3e;
            }
            QTableWidget {
                background-color: #2a2a2a;
                border: 1px solid #3e3e3e;
                color: #dcdcdc;
                gridline-color: #3e3e3e;
            }
            QHeaderView::section {
                background-color: #1e1e1e;
                color: #8a8a8a;
                font-weight: bold;
                border: 1px solid #3e3e3e;
                padding: 4px;
            }
        """)

        # Construir interfaz
        self.setup_ui()

        # Cargar datos en la tabla
        self.load_captures()

    # =========================================================================
    # CONSTRUCCIÓN DE LA INTERFAZ
    # =========================================================================

    def setup_ui(self):
        """
        Configura la interfaz del diálogo.

        Estructura:
        [Cabecera: título + botón cerrar]
        [Tabla de capturas]
        [Pie: abrir carpeta + cerrar]
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---------------------------------------------------------------------
        # CABECERA CON TÍTULO Y BOTÓN CERRAR
        # ---------------------------------------------------------------------
        header = QWidget()
        header.setObjectName("captureHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        # Título
        title = QLabel("INSPECTOR DE CAPTURAS")
        title.setObjectName("captureTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Botón cerrar (X)
        btn_close = QToolButton()
        btn_close.setText("✕")
        btn_close.setObjectName("closeButton")
        btn_close.setFixedSize(28, 28)
        btn_close.clicked.connect(self.close)
        header_layout.addWidget(btn_close)

        layout.addWidget(header)

        # ---------------------------------------------------------------------
        # TABLA DE CAPTURAS
        # ---------------------------------------------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Miniatura", "ID", "Tipo", "Fecha/Hora", "Confianza"
        ])

        # Configuración de la tabla
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # Solo lectura
        self.table.setIconSize(QSize(50, 50))  # Tamaño de miniaturas
        self.table.verticalHeader().setDefaultSectionSize(60)  # Alto de filas

        # Configurar columnas
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Miniatura
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # ID
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Tipo
        header_view.setSectionResizeMode(3, QHeaderView.Stretch)  # Fecha/Hora
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Confianza

        layout.addWidget(self.table)

        # ---------------------------------------------------------------------
        # PIE CON BOTONES
        # ---------------------------------------------------------------------
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 8, 12, 8)

        # Botón abrir carpeta
        btn_open_folder = QPushButton("ABRIR UBICACIÓN")
        btn_open_folder.setObjectName("filterOption")
        btn_open_folder.clicked.connect(self.open_save_folder)
        footer_layout.addWidget(btn_open_folder)

        footer_layout.addStretch()

        # Botón cerrar
        btn_close_bottom = QPushButton("CERRAR")
        btn_close_bottom.setObjectName("filterOption")
        btn_close_bottom.clicked.connect(self.close)
        footer_layout.addWidget(btn_close_bottom)

        layout.addWidget(footer)

    # =========================================================================
    # CARGA DE DATOS EN LA TABLA
    # =========================================================================

    def load_captures(self):
        """
        Carga las capturas en la tabla (más reciente primero).

        Recorre la lista de capturas, las ordena por fecha/hora descendente
        y crea una fila en la tabla para cada una con:
        - Miniatura de la imagen
        - ID de captura
        - Tipo de objeto
        - Fecha y hora
        - Confianza
        """
        # Ordenar capturas por fecha/hora (más reciente primero)
        capturas_ordenadas = sorted(
            self.captures,
            key=lambda x: f"{x['date']} {x['time']}",
            reverse=True
        )

        # Configurar número de filas
        self.table.setRowCount(len(capturas_ordenadas))

        # Llenar tabla fila por fila
        for row, capture in enumerate(capturas_ordenadas):
            # -----------------------------------------------------------------
            # COLUMNA 0: MINIATURA
            # -----------------------------------------------------------------
            pixmap = QPixmap(capture['path'])
            if not pixmap.isNull():
                # Escalar miniatura a 50x50 manteniendo aspecto
                scaled = pixmap.scaled(
                    50, 50,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                lbl_img = QLabel()
                lbl_img.setPixmap(scaled)
                lbl_img.setAlignment(Qt.AlignCenter)
                self.table.setCellWidget(row, 0, lbl_img)

            # -----------------------------------------------------------------
            # COLUMNA 1: ID
            # -----------------------------------------------------------------
            self.table.setItem(row, 1, QTableWidgetItem(f"#{capture['id']}"))

            # -----------------------------------------------------------------
            # COLUMNA 2: TIPO DE OBJETO
            # -----------------------------------------------------------------
            tipos = capture.get('objectType', [])
            tipo_text = tipos[0] if tipos else "Manual"
            self.table.setItem(row, 2, QTableWidgetItem(tipo_text))

            # -----------------------------------------------------------------
            # COLUMNA 3: FECHA Y HORA
            # -----------------------------------------------------------------
            fecha_hora = f"{capture['date']} {capture['time']}"
            self.table.setItem(row, 3, QTableWidgetItem(fecha_hora))

            # -----------------------------------------------------------------
            # COLUMNA 4: CONFIANZA
            # -----------------------------------------------------------------
            conf = capture.get('confidence', 0.0)
            conf_text = f"{conf:.1f}%" if conf > 0 else "N/A"
            self.table.setItem(row, 4, QTableWidgetItem(conf_text))

    # =========================================================================
    # ACCIONES DEL INSPECTOR
    # =========================================================================

    def open_save_folder(self):
        """
        Abre la carpeta de capturas en el explorador de archivos.

        Crea la carpeta si no existe y la abre con la aplicación
        predeterminada del sistema.
        """
        save_path = Path(self.save_path)
        save_path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(save_path)))

    def update_captures(self, captures):
        """
        Actualiza la lista de capturas y refresca la tabla.

        Args:
            captures: Nueva lista de capturas.
        """
        self.captures = captures
        self.load_captures()

# =============================================================================
# DIÁLOGO DE ATAJOS DE TECLADO
# =============================================================================

class ShortcutsDialog(QDialog):
    """
    Diálogo que muestra la lista de atajos de teclado disponibles.

    Este diálogo modal presenta una tabla con todos los atajos de teclado
    del sistema, organizados en dos columnas:
    - Atajo: Combinación de teclas (ej: Ctrl+1)
    - Acción: Descripción de lo que hace

    Características:
    - Modal (bloquea la ventana principal mientras está abierto)
    - Tabla de solo lectura
    - Atajos resaltados en azul
    - Botón de cierre

    Uso:
        dialog = ShortcutsDialog(self)
        dialog.exec()  # Modal
    """

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def __init__(self, parent=None):
        """
        Inicializa el diálogo de atajos.

        Args:
            parent: Widget padre (opcional).
        """
        super().__init__(parent)
        self.setWindowTitle("ATAJOS DE TECLADO")
        self.resize(450, 500)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)  # Sin bordes nativos

        # Estilo oscuro personalizado
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                border: 1px solid #3e3e3e;
            }
            QTableWidget {
                background-color: #2a2a2a;
                border: 1px solid #3e3e3e;
                color: #dcdcdc;
                gridline-color: #3e3e3e;
            }
            QHeaderView::section {
                background-color: #1e1e1e;
                color: #8a8a8a;
                font-weight: bold;
                border: 1px solid #3e3e3e;
                padding: 4px;
            }
        """)

        self.setup_ui()

    # =========================================================================
    # CONSTRUCCIÓN DE LA INTERFAZ
    # =========================================================================

    def setup_ui(self):
        """
        Configura la interfaz del diálogo de atajos.

        Estructura:
        [Cabecera: título + botón cerrar]
        [Tabla de atajos]
        [Pie: botón cerrar]
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---------------------------------------------------------------------
        # CABECERA
        # ---------------------------------------------------------------------
        header = QWidget()
        header.setObjectName("captureHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        title = QLabel("ATAJOS DE TECLADO")
        title.setObjectName("captureTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        btn_close = QToolButton()
        btn_close.setText("✕")
        btn_close.setObjectName("closeButton")
        btn_close.setFixedSize(28, 28)
        btn_close.clicked.connect(self.close)
        header_layout.addWidget(btn_close)

        layout.addWidget(header)

        # ---------------------------------------------------------------------
        # TABLA DE ATAJOS
        # ---------------------------------------------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Atajo", "Acción"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # Solo lectura

        # Configurar columnas
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)  # Ocultar números de fila

        # ---------------------------------------------------------------------
        # LISTA DE ATAJOS
        # ---------------------------------------------------------------------
        shortcuts = [
            ("Ctrl+1", "Iniciar/detener cámara 1"),
            ("Ctrl+2", "Iniciar/detener cámara 2"),
            ("Ctrl+3", "Activar/desactivar detección de personas"),
            ("Ctrl+4", "Activar/desactivar detección de carros"),
            ("Ctrl+5", "Activar/desactivar detección de botes"),
            ("Ctrl+6", "Activar/desactivar detección de helicópteros"),
            ("Ctrl+Y", "Alternar detección YOLO"),
            ("Ctrl+D", "Alternar modo dual stream"),
            ("Ctrl+F", "Pantalla completa"),
            ("Ctrl+C", "Capturar frame actual"),
            ("Ctrl+H", "Mostrar/ocultar galería"),
            ("Ctrl+L", "Mostrar/ocultar logs"),
            ("Ctrl+M", "Silenciar sonidos"),
            ("Ctrl+Tab", "Cambiar cámara activa en modo dual"),
            ("Ctrl++", "Aumentar zoom"),
            ("Ctrl+-", "Disminuir zoom"),
            ("Ctrl+↑/↓/←/→", "Paneo del zoom"),
            ("Ctrl+/", "Abrir este diálogo de atajos"),
        ]

        # Llenar tabla
        self.table.setRowCount(len(shortcuts))

        for row, (key, desc) in enumerate(shortcuts):
            # Columna 0: Atajo (azul y en negrita)
            item_key = QTableWidgetItem(key)
            item_key.setTextAlignment(Qt.AlignCenter)
            item_key.setForeground(QColor("#0099ff"))  # Azul
            font = item_key.font()
            font.setBold(True)
            item_key.setFont(font)
            self.table.setItem(row, 0, item_key)

            # Columna 1: Descripción
            item_desc = QTableWidgetItem(desc)
            item_desc.setForeground(QColor("#dcdcdc"))  # Gris claro
            self.table.setItem(row, 1, item_desc)

        layout.addWidget(self.table)

        # ---------------------------------------------------------------------
        # PIE CON BOTÓN CERRAR
        # ---------------------------------------------------------------------
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 8, 12, 8)

        footer_layout.addStretch()

        btn_close_bottom = QPushButton("CERRAR")
        btn_close_bottom.setObjectName("filterOption")
        btn_close_bottom.clicked.connect(self.close)
        footer_layout.addWidget(btn_close_bottom)

        layout.addWidget(footer)