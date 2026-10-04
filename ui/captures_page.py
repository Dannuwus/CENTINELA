# =============================================================================
# MÓDULO DE PÁGINA DE CAPTURAS (GALERÍA)
# =============================================================================
# Este módulo implementa la galería de capturas del sistema.
#
# Funcionalidades:
# 1. Visualización de capturas en cuadrícula vertical (1 columna)
# 2. Filtros por fecha (hoy, ayer, todas)
# 3. Filtros por hora (mañana, tarde, noche, todo el día)
# 4. Filtros por tipo de objeto (todos, coches, barcos, helicópteros)
# 5. Doble clic para abrir imagen con aplicación predeterminada
# 6. Clic derecho para menú contextual (eliminar)
# 7. Selección de carpeta de capturas
# 8. Inspector de capturas (tabla detallada)
#
# DEPENDENCIAS:
# - core.constants (DEFAULT_SAVE_PATH, THUMBNAIL_SIZE, TIME_RANGES)
# - ui.widgets (HoverToolButton, TooltipMixin, ClickableLabel)
# - ui.dialogs (CaptureInspectorDialog)
# =============================================================================

# =============================================================================
# IMPORTS ESTÁNDAR
# =============================================================================
from datetime import datetime, timedelta  # Filtros por fecha
from pathlib import Path  # Manejo de rutas

# =============================================================================
# IMPORTS DE PYQT
# =============================================================================
from PySide6.QtCore import Qt, QUrl, QSize, QRect
from PySide6.QtGui import QDesktopServices, QCursor, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGridLayout, QFileDialog, QMessageBox,
    QSizePolicy, QButtonGroup, QMenu, QStyle
)

# =============================================================================
# IMPORTS INTERNOS
# =============================================================================
from core.constants import DEFAULT_SAVE_PATH, THUMBNAIL_SIZE, TIME_RANGES
from ui.widgets import HoverToolButton, TooltipMixin, ClickableLabel
from ui.dialogs import CaptureInspectorDialog


class CapturesPage(QWidget, TooltipMixin):
    """
    Página de capturas que muestra las imágenes en cuadrícula.

    La galería muestra las capturas más recientes primero. Incluye un panel
    de filtros desplegable para buscar capturas específicas por fecha,
    hora del día o tipo de objeto detectado.

    Interacciones:
    - Doble clic en una imagen: abrir con aplicación predeterminada
    - Clic derecho en una imagen: menú contextual (eliminar)
    - Botón de filtro: mostrar/ocultar panel de filtros
    - Botón de carpeta: cambiar ubicación de guardado
    - Botón de inspector: abrir tabla detallada de capturas

    Uso:
        captures_page = CapturesPage(config_manager)
        captures_page.add_capture(image, filename, counter, types, confidence)
    """

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def __init__(self, config_manager):
        """
        Inicializa la página de capturas.

        Args:
            config_manager: Instancia de ConfigManager para persistencia.
        """
        super().__init__()
        self.config = config_manager

        # Estado de capturas
        self.captures = []  # Lista completa de capturas
        self.filtered_captures = []  # Capturas después de aplicar filtros

        # Filtros activos
        self.filter = {
            "date": "all",  # 'all', 'today', 'yesterday'
            "timeSlot": "all",  # 'all', 'morning', 'afternoon', 'evening'
            "objectType": "all"  # 'all', 'car', 'boat', 'helicopter', 'person'
        }

        self.filter_widget = None  # Panel de filtros desplegable
        self.tooltip_label = None  # Tooltip personalizado

        # Construir interfaz
        self.setup_ui()

        # Cargar capturas existentes desde disco
        self.load_captures_from_disk()

    def showEvent(self, event):
        """
        Inicializa el tooltip cuando la página se muestra.

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
        Configura el layout de la página de capturas.

        Estructura:
        [Cabecera: título + botones]
        [Panel de filtros (oculto por defecto)]
        [Área de scroll con galería]
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # =====================================================================
        # CABECERA CON TÍTULO Y BOTONES
        # =====================================================================
        header = QWidget()
        header.setObjectName("captureHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        # Título
        self.title_label = QLabel("CAPTURAS")
        self.title_label.setObjectName("captureTitle")
        header_layout.addWidget(self.title_label)

        # ---------------------------------------------------------------------
        # BOTÓN DE FILTRO
        # ---------------------------------------------------------------------
        self.btn_filter = HoverToolButton()
        self.btn_filter.setObjectName("filterBtn")
        self.btn_filter.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogContentsView)
        )
        self.btn_filter.setIconSize(QSize(16, 16))

        # Tooltip personalizado
        self.btn_filter.entered.connect(
            lambda: self.show_tooltip(self.btn_filter, "Filtrar capturas", position='bottom')
        )
        self.btn_filter.left.connect(self.hide_tooltip)

        # Acción
        self.btn_filter.clicked.connect(self.toggle_filter_panel)
        header_layout.addWidget(self.btn_filter)

        # ---------------------------------------------------------------------
        # BOTÓN DE SELECCIÓN DE CARPETA
        # ---------------------------------------------------------------------
        self.btn_folder = HoverToolButton()
        self.btn_folder.setObjectName("folderBtn")
        self.btn_folder.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        self.btn_folder.setIconSize(QSize(16, 16))

        # Tooltip personalizado
        self.btn_folder.entered.connect(
            lambda: self.show_tooltip(self.btn_folder, "Seleccionar carpeta de capturas", position='bottom')
        )
        self.btn_folder.left.connect(self.hide_tooltip)

        # Acción
        self.btn_folder.clicked.connect(self.select_capture_folder)
        header_layout.addWidget(self.btn_folder)

        # ---------------------------------------------------------------------
        # BOTÓN DE INSPECTOR
        # ---------------------------------------------------------------------
        self.btn_inspector = HoverToolButton()
        self.btn_inspector.setObjectName("inspectorBtn")
        self.btn_inspector.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogInfoView)
        )
        self.btn_inspector.setIconSize(QSize(16, 16))

        # Tooltip personalizado
        self.btn_inspector.entered.connect(
            lambda: self.show_tooltip(self.btn_inspector, "Abrir inspector de capturas", position='bottom')
        )
        self.btn_inspector.left.connect(self.hide_tooltip)

        # Acción
        self.btn_inspector.clicked.connect(self.open_inspector)
        header_layout.addWidget(self.btn_inspector)

        layout.addWidget(header)

        # =====================================================================
        # PANEL DE FILTROS (INICIALMENTE OCULTO)
        # =====================================================================
        self._setup_filter_panel()
        layout.addWidget(self.filter_panel)

        # =====================================================================
        # ÁREA DE SCROLL PARA LA GALERÍA
        # =====================================================================
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("galleryScroll")

        # Widget de galería
        self.gallery_widget = QWidget()
        self.gallery_widget.setObjectName("galleryWidget")
        self.gallery_layout = QGridLayout(self.gallery_widget)
        self.gallery_layout.setContentsMargins(4, 4, 4, 4)
        self.gallery_layout.setSpacing(8)

        # Configurar para 1 columna centrada
        self.gallery_layout.setColumnStretch(0, 1)
        self.gallery_layout.setRowStretch(0, 0)

        self.scroll_area.setWidget(self.gallery_widget)
        layout.addWidget(self.scroll_area)

    def _setup_filter_panel(self):
        """
        Configura el panel de filtros desplegable.

        El panel contiene:
        - Filtro por fecha (Todas, Hoy, Ayer)
        - Filtro por hora (Todo el día, Mañana, Tarde, Noche)
        - Filtro por tipo de objeto (Todos, Coches, Barcos, Helicópteros)
        - Botones Aplicar y Restablecer
        """
        self.filter_panel = QWidget()
        self.filter_panel.setObjectName("filterPanel")
        self.filter_panel.setVisible(False)  # Oculto por defecto

        filter_layout = QVBoxLayout(self.filter_panel)
        filter_layout.setContentsMargins(12, 8, 12, 8)

        # ---------------------------------------------------------------------
        # FILTRO POR FECHA
        # ---------------------------------------------------------------------
        date_label = QLabel("Fecha")
        date_label.setObjectName("filterLabel")
        filter_layout.addWidget(date_label)

        self.date_buttons = self._create_filter_group(
            filter_layout,
            [('all', 'Todas'), ('today', 'Hoy'), ('yesterday', 'Ayer')],
            lambda k: self.set_filter('date', k),
            group_name="date"
        )

        # ---------------------------------------------------------------------
        # FILTRO POR HORA
        # ---------------------------------------------------------------------
        time_label = QLabel("Hora del día")
        time_label.setObjectName("filterLabel")
        filter_layout.addWidget(time_label)

        self.time_buttons = self._create_filter_group(
            filter_layout,
            [
                ('all', 'Todo el día'),
                ('morning', 'Mañana'),
                ('afternoon', 'Tarde'),
                ('evening', 'Noche')
            ],
            lambda k: self.set_filter('timeSlot', k),
            group_name="time"
        )

        # ---------------------------------------------------------------------
        # FILTRO POR TIPO DE OBJETO
        # ---------------------------------------------------------------------
        lbl_obj = QLabel("Tipo de objeto")
        lbl_obj.setObjectName("filterLabel")
        filter_layout.addWidget(lbl_obj)

        obj_layout = QHBoxLayout()

        # Botones de tipo de objeto
        self.btn_obj_all = QPushButton("Todos")
        self.btn_obj_car = QPushButton("Coches")
        self.btn_obj_boat = QPushButton("Barcos")
        self.btn_obj_heli = QPushButton("Helicópteros")

        for btn in [self.btn_obj_all, self.btn_obj_car, self.btn_obj_boat, self.btn_obj_heli]:
            btn.setCheckable(True)
            btn.setObjectName("filterOption")
            btn.clicked.connect(lambda checked, b=btn: self.update_filter_obj(b))

        self.btn_obj_all.setChecked(True)  # "Todos" seleccionado por defecto

        obj_layout.addWidget(self.btn_obj_all)
        obj_layout.addWidget(self.btn_obj_car)
        obj_layout.addWidget(self.btn_obj_boat)
        obj_layout.addWidget(self.btn_obj_heli)
        filter_layout.addLayout(obj_layout)

        # ---------------------------------------------------------------------
        # BOTONES APLICAR / RESTABLECER
        # ---------------------------------------------------------------------
        action_layout = QHBoxLayout()
        action_layout.addStretch()

        btn_reset = QPushButton("RESTABLECER")
        btn_reset.setObjectName("filterReset")
        btn_reset.clicked.connect(self.reset_filters)

        btn_apply = QPushButton("APLICAR")
        btn_apply.setObjectName("filterApply")
        btn_apply.clicked.connect(self.apply_filters)

        action_layout.addWidget(btn_reset)
        action_layout.addWidget(btn_apply)
        filter_layout.addLayout(action_layout)

    # =========================================================================
    # CREACIÓN DE GRUPOS DE FILTROS
    # =========================================================================

    def _create_filter_group(self, parent_layout, options, callback, group_name, default_key='all'):
        """
        Crea un grupo de botones de filtro mutuamente excluyentes.

        Args:
            parent_layout: Layout donde se insertará el grupo.
            options: Lista de tuplas (clave, texto_visible).
            callback: Función a llamar con la clave seleccionada.
            group_name: Nombre identificador del grupo (no usado actualmente).
            default_key: Clave del botón seleccionado por defecto.

        Returns:
            Diccionario {clave: botón} para referencia posterior.
        """
        h_layout = QHBoxLayout()
        buttons = {}

        # Grupo para exclusividad (solo un botón activo a la vez)
        button_group = QButtonGroup(self)
        button_group.setExclusive(True)

        for key, text in options:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setObjectName("filterOption")
            btn.setProperty("filterKey", key)

            # Marcar botón por defecto
            if key == default_key:
                btn.setChecked(True)

            # Conectar clic
            btn.clicked.connect(lambda checked, k=key: callback(k))

            button_group.addButton(btn)
            h_layout.addWidget(btn)
            buttons[key] = btn

        parent_layout.addLayout(h_layout)
        return buttons

    # =========================================================================
    # GESTIÓN DE FILTROS
    # =========================================================================

    def set_filter(self, key, value):
        """
        Actualiza cualquier clave del diccionario de filtros.

        Args:
            key: Clave del filtro ('date', 'timeSlot', 'objectType').
            value: Valor del filtro.
        """
        self.filter[key] = value

    def toggle_filter_panel(self):
        """
        Muestra u oculta el panel de filtros.

        También actualiza el estilo del botón de filtro para indicar
        visualmente si el panel está abierto o cerrado.
        """
        visible = self.filter_panel.isVisible()
        self.filter_panel.setVisible(not visible)

        # Actualizar estilo del botón
        if not visible:
            # Panel ahora visible: resaltar botón
            self.btn_filter.setStyleSheet("border-color: #0099ff; color: #0099ff;")
        else:
            # Panel ahora oculto: estilo normal
            self.btn_filter.setStyleSheet("")

    def update_filter_obj(self, btn):
        """
        Actualiza el filtro de tipo de objeto según el botón pulsado.

        Args:
            btn: Botón de tipo de objeto clicado.
        """
        # Marcar solo el botón clicado
        for b in [self.btn_obj_all, self.btn_obj_car, self.btn_obj_boat, self.btn_obj_heli]:
            b.setChecked(b is btn)

        # Actualizar filtro según botón
        if btn is self.btn_obj_all:
            self.filter['objectType'] = 'all'
        elif btn is self.btn_obj_car:
            self.filter['objectType'] = 'car'
        elif btn is self.btn_obj_boat:
            self.filter['objectType'] = 'boat'
        else:
            self.filter['objectType'] = 'helicopter'

    def reset_filters(self):
        """
        Restablece todos los filtros a 'all'.

        Marca los botones "Todas", "Todo el día" y "Todos" y aplica
        los filtros inmediatamente.
        """
        # Restablecer botones de fecha
        self.date_buttons['all'].setChecked(True)

        # Restablecer botones de hora
        self.time_buttons['all'].setChecked(True)

        # Restablecer botón de tipo
        self.btn_obj_all.setChecked(True)

        # Restablecer diccionario de filtros
        self.filter = {"date": "all", "timeSlot": "all", "objectType": "all"}

        # Aplicar filtros
        self.apply_filters()

    def apply_filters(self):
        """
        Aplica los filtros y actualiza la galería.

        Cierra el panel de filtros y refresca la visualización
        con las capturas filtradas.
        """
        self.refresh_gallery()
        self.filter_panel.setVisible(False)
        self.btn_filter.setStyleSheet("")

    # =========================================================================
    # CARGA DE CAPTURAS DESDE DISCO
    # =========================================================================

    def load_captures_from_disk(self):
        """
        Carga las capturas desde la carpeta de guardado.

        Escanea el directorio de capturas en busca de archivos de imagen,
        extrae metadatos del nombre de archivo (ID, tipo, confianza) y
        los ordena por fecha de modificación (más reciente primero).

        Formatos de nombre soportados:
        - Nuevo: Captura_ID_TIPO_CONFIANZA (ej: Captura_1_persona_85.jpg)
        - Manual: Captura_NUMERO_TIPO1_TIPO2_CONFIANZA (ej: Captura_2_persona_carro_90.jpg)
        - Antiguo: target_ch1_ID_TIMESTAMP (ej: target_ch1_5_20250101_120000.jpg)
        """
        # Obtener ruta de guardado desde configuración
        save_path = Path(self.config.get('General', 'save_path', DEFAULT_SAVE_PATH))

        # Crear carpeta si no existe
        if not save_path.exists():
            save_path.mkdir(parents=True, exist_ok=True)
            return

        # Resetear lista de capturas
        self.captures = []

        # Recorrer todos los archivos de la carpeta
        for file_path in save_path.iterdir():
            # Filtrar solo archivos de imagen
            if file_path.is_file() and file_path.suffix.lower() in ('.jpg', '.jpeg', '.png'):
                fname = file_path.name

                try:
                    # Formato: ch{canal}_{id}_{tipo1}_{tipo2}_{confianza}
                    # Ejemplo: ch2_5_carro_persona_85.jpg
                    name_without_ext = file_path.stem
                    parts = name_without_ext.split('_')

                    if len(parts) >= 3 and parts[0].startswith('ch'):
                        # Extraer número de canal (ch1 -> 1, ch2 -> 2)
                        channel = int(parts[0].replace('ch', ''))

                        # Extraer ID
                        idx = int(parts[1])

                        # Verificar si hay tipos y confianza
                        if len(parts) >= 4:
                            # Formato: ch1_5_persona_85.jpg
                            tipos = parts[2:-1]  # Tipos intermedios
                            confidence = int(parts[-1])  # Confianza (último)
                        else:
                            # Formato sin tipo: ch1_58_0.jpg
                            tipos = []  # Sin tipos detectados
                            confidence = int(parts[2])  # Solo confianza (0)

                        # Guardar canal en la captura
                        channel_id = channel
                    else:
                        # Formato no reconocido, ignorar archivo
                        continue

                except (ValueError, IndexError):
                    # Error numérico o formato incorrecto
                    continue

                # -----------------------------------------------------------------
                # OBTENER TIMESTAMP DE MODIFICACIÓN
                # Usar la fecha de modificación del archivo como timestamp
                # de la captura (más confiable que parsear el nombre)
                # -----------------------------------------------------------------
                mtime = file_path.stat().st_mtime
                dt = datetime.fromtimestamp(mtime)

                # Agregar captura a la lista
                self.captures.append({
                    'id': idx,  # ID de la captura
                    'filename': fname,  # Nombre completo del archivo
                    'path': str(file_path),  # Ruta absoluta
                    'date': dt.strftime("%Y-%m-%d"),  # Fecha de captura
                    'time': dt.strftime("%H:%M:%S"),  # Hora de captura
                    'objectType': tipos,  # Tipos de objetos detectados
                    'confidence': confidence,  # Confianza de detección (0-1)
                    'channel': channel_id,  # Canal de origen (1 o 2)
                })

        # Ordenar por fecha/hora (más reciente primero)
        self.captures.sort(key=lambda x: f"{x['date']} {x['time']}", reverse=True)

        # Actualizar visualización de la galería
        self.refresh_gallery()

    # =========================================================================
    # FILTRADO Y REFRESCO DE GALERÍA
    # =========================================================================

    def refresh_gallery(self):
        """
        Actualiza la galería según los filtros actuales.

        Aplica los filtros de fecha, hora y tipo de objeto a la lista
        completa de capturas y actualiza la visualización.
        """
        filtered = self.captures.copy()

        # ---------------------------------------------------------------------
        # FILTRO POR FECHA
        # ---------------------------------------------------------------------
        if self.filter['date'] == 'today':
            today = datetime.now().strftime("%Y-%m-%d")
            filtered = [c for c in filtered if c['date'] == today]
        elif self.filter['date'] == 'yesterday':
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            filtered = [c for c in filtered if c['date'] == yesterday]

        # ---------------------------------------------------------------------
        # FILTRO POR HORA DEL DÍA
        # ---------------------------------------------------------------------
        selected_time = self.filter.get('timeSlot')
        if selected_time in TIME_RANGES:
            filtered = [
                c for c in filtered
                if int(c['time'].split(':')[0]) in TIME_RANGES[selected_time]
            ]

        # ---------------------------------------------------------------------
        # FILTRO POR TIPO DE OBJETO
        # ---------------------------------------------------------------------
        if self.filter['objectType'] != 'all':
            filtered = [
                c for c in filtered
                if self.filter['objectType'] in c['objectType']
            ]

        # Actualizar lista filtrada y visualización
        self.filtered_captures = filtered
        self.update_gallery()

    # =========================================================================
    # VISUALIZACIÓN DE LA GALERÍA
    # =========================================================================

    def update_gallery(self):
        """
        Muestra las capturas en cuadrícula con el nombre truncado debajo.

        Limpia todos los widgets actuales y reconstruye la galería
        con las capturas filtradas. Cada captura se muestra como:
        [Miniatura] [Nombre truncado]
        """
        # ---------------------------------------------------------------------
        # LIMPIAR WIDGETS ACTUALES
        # ---------------------------------------------------------------------
        while self.gallery_layout.count():
            item = self.gallery_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ---------------------------------------------------------------------
        # CASO: NO HAY CAPTURAS EN ABSOLUTO
        # ---------------------------------------------------------------------
        if not self.captures:
            container = QWidget()
            container.setObjectName("emptyContainer")
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.addStretch()

            empty_label = QLabel("Esta carpeta está vacía")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setObjectName("emptyLabel")

            vbox.addWidget(empty_label)
            vbox.addStretch()

            self.gallery_layout.addWidget(container, 0, 0, 1, 1)
            self.gallery_layout.setRowStretch(0, 1)
            self.gallery_layout.setColumnStretch(0, 1)
            return

        # ---------------------------------------------------------------------
        # MOSTRAR CAPTURAS FILTRADAS
        # ---------------------------------------------------------------------
        row = 0
        self.gallery_layout.setColumnStretch(0, 1)  # Columna 0 expandible

        for capture in self.filtered_captures:
            # Crear widget para cada captura
            item_widget = QWidget()
            item_widget.setObjectName("captureItem")
            item_layout = QVBoxLayout(item_widget)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(2)
            item_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            item_widget.setFixedHeight(THUMBNAIL_SIZE + 24)  # Miniatura + texto

            # -----------------------------------------------------------------
            # MINIATURA CLICABLE
            # -----------------------------------------------------------------
            img_label = ClickableLabel(capture['path'])
            img_label.doubleClicked.connect(self.open_capture)
            img_label.rightClicked.connect(self.show_context_menu)
            img_label.setAlignment(Qt.AlignCenter)

            # Cargar y escalar imagen
            pixmap = QPixmap(capture['path'])
            if not pixmap.isNull():
                size = THUMBNAIL_SIZE

                # Escalar y recortar para llenar el cuadrado
                scaled = pixmap.scaled(
                    size, size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )

                # Recortar centro para obtener cuadrado perfecto
                crop_rect = QRect(
                    (scaled.width() - size) // 2,
                    (scaled.height() - size) // 2,
                    size, size
                )
                cropped = scaled.copy(crop_rect)
                img_label.setPixmap(cropped)
                img_label.setFixedSize(size, size)
            else:
                # Imagen no disponible: mostrar emoji
                img_label.setText("¿?")
                img_label.setFixedSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE)

            img_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            # -----------------------------------------------------------------
            # NOMBRE DE ARCHIVO TRUNCADO
            # -----------------------------------------------------------------
            full_name = capture['filename']
            display_name = full_name[:15] + "..." if len(full_name) > 15 else full_name

            name_label = QLabel(display_name)
            name_label.setObjectName("captureName")
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setWordWrap(True)
            name_label.setToolTip(full_name)  # Tooltip con nombre completo
            name_label.setStyleSheet("font-size: 9px; color: #c9d1d9;")
            name_label.setFixedWidth(THUMBNAIL_SIZE)

            # Agregar al layout
            item_layout.addWidget(img_label, 0, Qt.AlignCenter)
            item_layout.addWidget(name_label, 0, Qt.AlignCenter)
            item_layout.addStretch()

            # Agregar widget a la cuadrícula centrado
            self.gallery_layout.addWidget(
                item_widget, row, 0,
                Qt.AlignHCenter | Qt.AlignTop
            )
            row += 1

        # Ajustar tamaño del widget al contenido
        self.gallery_widget.adjustSize()

    # =========================================================================
    # ACCIONES DE USUARIO
    # =========================================================================

    def open_capture(self, path):
        """
        Abre la imagen con la aplicación predeterminada del sistema.

        Args:
            path: Ruta de la imagen a abrir.
        """
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def show_context_menu(self, path):
        """
        Muestra un menú contextual para la captura.

        Args:
            path: Ruta de la captura sobre la que se hizo clic derecho.
        """
        menu = QMenu(self)

        # Acción Eliminar
        delete_action = menu.addAction("Eliminar")
        delete_action.triggered.connect(lambda: self.delete_capture(path))

        # Mostrar menú en la posición global del cursor
        menu.exec(QCursor.pos())

    def delete_capture(self, path):
        """
        Elimina la captura seleccionada.

        Muestra confirmación antes de eliminar. Si se confirma:
        1. Elimina el archivo del disco
        2. Elimina de la lista en memoria
        3. Refresca la galería

        Args:
            path: Ruta de la captura a eliminar.
        """
        path_obj = Path(path)

        # Confirmación
        reply = QMessageBox.question(
            self,
            "Eliminar captura",
            f"¿Seguro que deseas eliminar esta captura?\n{path_obj.name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                # Eliminar archivo del disco
                path_obj.unlink()
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Error",
                    f"No se pudo eliminar el archivo:\n{e}"
                )
                return

            # Eliminar de la lista en memoria
            self.captures = [
                c for c in self.captures
                if Path(c['path']) != path_obj
            ]

            # Refrescar visualización
            self.refresh_gallery()

    def select_capture_folder(self):
        """
        Abre diálogo para seleccionar carpeta de capturas.

        Permite al usuario cambiar la ubicación donde se guardan
        las capturas. Después de cambiar, recarga la galería.
        """
        initial_dir = str(self.config.get('General', 'save_path', DEFAULT_SAVE_PATH))

        folder = QFileDialog.getExistingDirectory(
            self,
            "Cambiar ubicación de capturas",
            initial_dir
        )

        if folder:
            folder_path = Path(folder)
            self.config.set('General', 'save_path', str(folder_path))

            # Recargar capturas desde la nueva ubicación
            self.load_captures_from_disk()

    def open_inspector(self):
        """
        Abre el inspector de capturas (diálogo no modal).

        El inspector muestra una tabla detallada con todas las capturas:
        miniatura, ID, tipo, fecha/hora y confianza.
        """
        save_path = self.config.get('General', 'save_path', DEFAULT_SAVE_PATH)

        self._active_inspector = CaptureInspectorDialog(
            parent=self,
            captures=self.captures,
            save_path=save_path
        )
        self._active_inspector.show()
        self.inspector_open = True

        # Sincronizar con MainWindow
        main_window = self.window()
        if hasattr(main_window, '_active_inspector'):
            main_window._active_inspector = self._active_inspector
            main_window.inspector_open = True

    # =========================================================================
    # AÑADIR NUEVA CAPTURA
    # =========================================================================

    def add_capture(self, image, filename, counter, object_types=None, confidence=0.0):
        """
        Añade una nueva captura a la galería.

        Args:
            image: Imagen OpenCV (no se usa, la imagen ya está guardada en disco).
            filename: Nombre del archivo guardado.
            counter: Número de captura global.
            object_types: Lista de tipos de objetos detectados.
            confidence: Confianza máxima de detección (porcentaje).
        """
        if object_types is None:
            object_types = []

        # Obtener ruta de guardado
        save_path = Path(self.config.get('General', 'save_path', DEFAULT_SAVE_PATH))
        filepath = save_path / filename

        # Extraer canal del nombre del archivo (ch1, ch2)
        # El nombre ya incluye el canal porque lo genera main_window/video_thread
        try:
            channel = int(filename.split('_')[0].replace('ch', ''))
        except (ValueError, IndexError):
            channel = 1  # fallback solo si el formato es inesperado

        # Crear entrada de captura con timestamp actual
        now = datetime.now()

        capture_entry = {
            'id': counter,
            'filename': filename,
            'path': str(filepath),
            'date': now.strftime("%Y-%m-%d"),
            'time': now.strftime("%H:%M:%S"),
            'objectType': object_types,
            'confidence': confidence,
            'channel': channel,
        }

        # Agregar a la lista
        self.captures.append(capture_entry)

        # Re-ordenar para que el más reciente quede primero
        self.captures.sort(
            key=lambda x: f"{x['date']} {x['time']}",
            reverse=True
        )

        # Refrescar galería
        self.refresh_gallery()

        # Actualizar inspector si está abierto
        if hasattr(self, 'inspector_open') and self.inspector_open and hasattr(self, '_active_inspector'):
            if self._active_inspector:
                self._active_inspector.update_captures(self.captures)