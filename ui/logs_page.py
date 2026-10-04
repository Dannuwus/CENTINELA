# =============================================================================
# MÓDULO DE PÁGINA DE LOGS (OPTIMIZADO)
# =============================================================================
# Este módulo implementa la página de logs del sistema con mejoras de rendimiento:
# 1. Uso de QPlainTextEdit en lugar de QTextEdit (más ligero para texto plano).
# 2. Recepción de lotes de logs (lista de strings) en lugar de logs individuales.
# 3. Límite máximo de líneas visibles para controlar el uso de memoria.
# 4. Auto-scroll al final solo cuando se recibe un lote completo.
#
# Los logs se agregan mediante el método append_batch(), que recibe una lista
# de mensajes ya formateados desde el LogManager y los inserta de una sola vez.
#
# DEPENDENCIAS:
# - PySide6.QtWidgets (widgets base)
# - PySide6.QtCore (Slot para recepción de señales)
# =============================================================================

# =============================================================================
# IMPORTS DE PYQT
# =============================================================================
from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QWidget,           # Widget base
    QVBoxLayout,       # Layout vertical
    QHBoxLayout,       # Layout horizontal
    QLabel,            # Etiqueta de título
    QPushButton,       # Botón de limpiar
    QPlainTextEdit     # Área de texto optimizada para logs
)
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont

class LogHighlighter(QSyntaxHighlighter):
    """
    Resaltador de sintaxis para los logs.

    Aplica colores y negrita según el nivel de severidad contenido
    en cada línea. Los niveles esperados son: DEBUG, INFO, WARNING, ERROR, CRITICAL.
    El patrón busca al inicio de la línea el texto [NIVEL] y aplica el formato
    correspondiente a toda la línea.
    """

    # Diccionario de estilos por nivel
    STYLES = {
        "DEBUG": QTextCharFormat(),
        "INFO": QTextCharFormat(),
        "WARNING": QTextCharFormat(),
        "ERROR": QTextCharFormat(),
        "CRITICAL": QTextCharFormat(),
    }

    def __init__(self, document):
        super().__init__(document)
        self._init_styles()

    def _init_styles(self):
        """Configura los formatos de color y fuente para cada nivel."""
        # DEBUG: azul grisáceo
        fmt = self.STYLES["DEBUG"]
        fmt.setForeground(QColor("#6c8ebf"))
        fmt.setFontWeight(QFont.Normal)

        # INFO: blanco puro
        fmt = self.STYLES["INFO"]
        fmt.setForeground(QColor("#ffffff"))
        fmt.setFontWeight(QFont.Normal)

        # WARNING: amarillo/naranja
        fmt = self.STYLES["WARNING"]
        fmt.setForeground(QColor("#f0ad4e"))
        fmt.setFontWeight(QFont.Bold)

        # ERROR: rojo
        fmt = self.STYLES["ERROR"]
        fmt.setForeground(QColor("#ff5252"))
        fmt.setFontWeight(QFont.Bold)

        # CRITICAL: rojo intenso con fondo
        fmt = self.STYLES["CRITICAL"]
        fmt.setForeground(QColor("#ffffff"))
        fmt.setBackground(QColor("#b71c1c"))
        fmt.setFontWeight(QFont.Bold)

    def highlightBlock(self, text):
        # Buscar patrón [NIVEL] en cualquier parte de la línea
        import re
        pattern = r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]:?"
        match = re.search(pattern, text)
        if match:
            level = match.group(1)
            fmt = self.STYLES.get(level)
            if fmt:
                self.setFormat(0, len(text), fmt)

class LogsPage(QWidget):
    """
    Página de logs para mostrar eventos del sistema (optimizada).
    ...
    """

    # Número máximo de bloques (líneas) visibles
    MAX_VISIBLE_LINES = 1000

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("captureHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        title_label = QLabel("LOGS DEL SISTEMA")
        title_label.setObjectName("captureTitle")
        header_layout.addWidget(title_label)

        btn_clear = QPushButton("LIMPIAR")
        btn_clear.setObjectName("filterOption")
        btn_clear.clicked.connect(self.clear_logs)
        header_layout.addWidget(btn_clear)

        layout.addWidget(header)

        self.txt_logs = QPlainTextEdit()
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setObjectName("logDisplay")
        self.txt_logs.setMaximumBlockCount(self.MAX_VISIBLE_LINES)
        # Aplicar resaltador de sintaxis para colorear por nivel
        self.highlighter = LogHighlighter(self.txt_logs.document())

        layout.addWidget(self.txt_logs)

    @Slot(list)
    def append_batch(self, logs: list):
        if logs:
            text = "\n".join(logs)
            self.txt_logs.appendPlainText(text)
            scrollbar = self.txt_logs.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def clear_logs(self):
        self.txt_logs.clear()