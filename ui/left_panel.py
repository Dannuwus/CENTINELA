# =============================================================================
# MÓDULO DE PANEL IZQUIERDO (CONFIGURACIÓN CON LPR Y TELEMETRÍA DE RED)
# =============================================================================

import cv2

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QComboBox, QStackedWidget, QButtonGroup,
    QStyle, QSizePolicy, QSpinBox, QTabWidget, QFrame
)

from core.constants import (
    DEFAULT_SETTINGS, DEFAULT_SAVE_PATH, ICON_SIZE,
    NAV_BAR_WIDTH, TOOLBUTTON_SIZE, OBJ_COLORS, OBJ_LABEL
)
from ui.widgets import (
    HoverToolButton, ToggleSwitch, SeparadorGrueso,
    SeparadorDelgado, TooltipMixin, FocusEscapableLineEdit
)


class LeftPanel(QWidget, TooltipMixin):
    toggle_panel_requested = Signal(bool)
    settings_changed = Signal(dict)
    camera_toggle_requested = Signal()
    camera_2_toggle_requested = Signal()
    stop_camera_requested = Signal()
    video_source_changed = Signal(str)
    yolo_toggle_changed = Signal(bool)
    ocr_toggle_changed = Signal(bool)  # NUEVA SEÑAL PARA OCR LPR
    optics_changed = Signal(dict)
    dual_stream_toggled = Signal(bool)
    camera_2_changed = Signal(str)
    rtsp_connect_requested = Signal(str, int)
    video_load_requested = Signal(int)
    log_signal = Signal(str, str)

    def __init__(self, config_manager):
        super().__init__()
        self.config = config_manager
        self.settings = self.load_settings_from_config()
        self.is_expanded = True
        self.current_index = 0
        self.setup_ui()
        self.tooltip_label = None

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_tooltip()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.nav_bar = QWidget()
        self.nav_bar.setObjectName("leftNavBar")
        self.nav_bar.setFixedWidth(NAV_BAR_WIDTH)

        nav_layout = QVBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        nav_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        self.nav_button_group = QButtonGroup(self)
        self.nav_button_group.setExclusive(True)

        pages = [
            ("detection", "Detección", QStyle.SP_FileDialogContentsView, "Ctrl+1"),
            ("video", "Fuente de video", QStyle.SP_ComputerIcon, "Ctrl+2"),
            ("optics", "Mejora Visual", QStyle.SP_FileDialogDetailedView, "Ctrl+3"),
            ("performance", "Rendimiento", QStyle.SP_FileDialogListView, "Ctrl+4"),
            ("alerts", "Alertas", QStyle.SP_MessageBoxWarning, "Ctrl+5"),
        ]

        self.nav_buttons = {}
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("leftStack")

        for idx, (key, tooltip, icon_standard, shortcut) in enumerate(pages):
            if key == "detection":
                page = self.create_detection_page()
            elif key == "video":
                page = self.create_video_page()
            elif key == "optics":
                page = self.create_optics_page()
            elif key == "performance":
                page = self.create_rendimiento_page()
            elif key == "alerts":
                page = self.create_alerts_page()
            else:
                page = QWidget()

            self.stacked_widget.addWidget(page)

            btn = HoverToolButton()
            btn.setCheckable(True)
            btn.setFixedSize(TOOLBUTTON_SIZE, TOOLBUTTON_SIZE)
            btn.setIconSize(ICON_SIZE)
            icon = self.style().standardIcon(icon_standard)
            btn.setIcon(icon)
            btn.setObjectName("navButton")

            tooltip_text = f"{tooltip} <span style='color:#888888'>{shortcut}</span>"
            btn.entered.connect(lambda b=btn, t=tooltip_text: self.show_tooltip(b, t))
            btn.left.connect(self.hide_tooltip)

            self.nav_button_group.addButton(btn, idx)
            nav_layout.addWidget(btn)
            self.nav_buttons[key] = btn

            btn.clicked.connect(
                lambda checked, index=idx, btn=btn: self.on_nav_button_clicked(btn, index)
            )

        self.nav_buttons["detection"].setChecked(True)
        self.stacked_widget.setCurrentIndex(0)
        self.current_index = 0

        content_layout.addWidget(self.nav_bar)

        content_wrapper = QWidget()
        content_wrapper.setObjectName("leftContent")
        wrapper_layout = QVBoxLayout(content_wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(self.stacked_widget)
        content_layout.addWidget(content_wrapper, 1)

        layout.addLayout(content_layout, 1)

    def on_nav_button_clicked(self, btn, index):
        self.hide_tooltip()

        if index == self.current_index and self.is_expanded:
            self.toggle_panel_requested.emit(False)
            self.is_expanded = False
            btn.setChecked(False)
        else:
            if not self.is_expanded:
                self.toggle_panel_requested.emit(True)
                self.is_expanded = True

            self.stacked_widget.setCurrentIndex(index)
            self.current_index = index

            for b in self.nav_buttons.values():
                b.setChecked(False)
            btn.setChecked(True)

    def _add_section_title(self, layout, text):
        title = QLabel(text)
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setContentsMargins(0, 0, 0, 4)
        layout.addWidget(title)
        layout.addWidget(SeparadorGrueso())

    def create_detection_page(self):
        page = QWidget()
        det_layout = QVBoxLayout(page)
        det_layout.setContentsMargins(8, 8, 8, 8)
        det_layout.setSpacing(0)

        self._add_section_title(det_layout, "DETECCIÓN")

        # =====================================================================
        # SWITCH YOLO PRINCIPAL
        # =====================================================================
        yolo_container = QWidget()
        yolo_layout = QHBoxLayout(yolo_container)
        yolo_layout.setContentsMargins(0, 8, 0, 8)
        yolo_layout.setSpacing(10)

        yolo_label = QLabel("Activar detección YOLO")
        yolo_label.setObjectName("yoloLabel")
        yolo_layout.addWidget(yolo_label)
        yolo_layout.addStretch()

        self.yolo_toggle = ToggleSwitch()
        self.yolo_toggle.setObjectName("yoloToggle")
        self.yolo_toggle.setChecked(False)
        self.yolo_toggle.toggled.connect(self.on_yolo_toggle_changed)
        yolo_layout.addWidget(self.yolo_toggle)

        det_layout.addWidget(yolo_container)
        det_layout.addWidget(SeparadorDelgado())

        # =====================================================================
        # SWITCH LPR (OCR PARA PLACAS)
        # =====================================================================
        ocr_container = QWidget()
        ocr_layout = QHBoxLayout(ocr_container)
        ocr_layout.setContentsMargins(0, 8, 0, 8)
        ocr_layout.setSpacing(10)

        ocr_label = QLabel("Lectura de Placas (LPR)")
        ocr_label.setObjectName("yoloLabel")
        ocr_layout.addWidget(ocr_label)
        ocr_layout.addStretch()

        self.ocr_toggle = ToggleSwitch()
        self.ocr_toggle.setObjectName("ocrToggle")
        self.ocr_toggle.setChecked(self.settings.get('ocr_enabled', False))
        self.ocr_toggle.toggled.connect(self.on_ocr_toggle_changed)
        ocr_layout.addWidget(self.ocr_toggle)

        det_layout.addWidget(ocr_container)
        det_layout.addWidget(SeparadorDelgado())

        # =====================================================================
        # CONFIGURACIÓN POR TIPO DE OBJETO
        # =====================================================================
        self.det_widgets = {}

        objetos = [
            ('person', 'Personas', OBJ_COLORS['person']['border']),
            ('car', 'Carros', OBJ_COLORS['car']['border']),
            ('boat', 'Botes', OBJ_COLORS['boat']['border']),
            ('helicopter', 'Helicópteros', OBJ_COLORS['helicopter']['border']),
        ]

        for obj_key, obj_label, obj_color in objetos:
            obj_title = QLabel(obj_label)
            obj_title.setObjectName("objectTitle")
            det_layout.addWidget(obj_title)

            obj_widget = QWidget()
            obj_layout = QHBoxLayout(obj_widget)
            obj_layout.setContentsMargins(0, 4, 0, 4)
            obj_layout.setSpacing(8)

            color_indicator = QLabel()
            color_indicator.setFixedSize(10, 10)
            color_indicator.setStyleSheet(
                f"background-color: {obj_color}; border-radius: 5px;"
            )
            obj_layout.addWidget(color_indicator)

            conf_slider = QSlider(Qt.Horizontal)
            conf_slider.setMinimum(50)
            conf_slider.setMaximum(99)
            conf_slider.setValue(int(self.settings['detections'][obj_key]['confidence'] * 100))
            conf_slider.valueChanged.connect(
                lambda val, o=obj_key: self.on_conf_slider(o, val)
            )
            obj_layout.addWidget(conf_slider, 1)

            conf_label = QLabel(f"{int(self.settings['detections'][obj_key]['confidence'] * 100)}%")
            conf_label.setObjectName("confLabel")
            conf_label.setFixedWidth(35)
            conf_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            obj_layout.addWidget(conf_label)

            obj_switch = ToggleSwitch()
            obj_switch.setChecked(self.settings['detections'][obj_key]['enabled'])
            obj_switch.toggled.connect(
                lambda checked, o=obj_key: self.on_det_toggle(o, checked)
            )
            obj_layout.addWidget(obj_switch)

            det_layout.addWidget(obj_widget)

            self.det_widgets[obj_key] = {
                'checkbox': obj_switch,
                'slider': conf_slider,
                'label': obj_title,
                'indicator': color_indicator,
                'switch': obj_switch,
                'conf_label': conf_label
            }

        det_layout.addStretch()
        return page

    def create_rendimiento_page(self):
        page = QWidget()
        rendimiento_layout = QVBoxLayout(page)
        rendimiento_layout.setContentsMargins(8, 8, 8, 8)
        rendimiento_layout.setSpacing(0)

        self._add_section_title(rendimiento_layout, "RENDIMIENTO")

        perf_container = QWidget()
        perf_layout = QVBoxLayout(perf_container)
        perf_layout.setContentsMargins(0, 8, 0, 4)
        perf_layout.setSpacing(4)

        perf_label = QLabel("Perfil de Rendimiento")
        perf_label.setObjectName("filterLabel")
        perf_layout.addWidget(perf_label)

        self.combo_perf = QComboBox()
        self.combo_perf.addItems([
            "Minimo (Ahorro CPU)",
            "Balanceado (Estandar)",
            "Exigente / Maxima Precision"
        ])
        self.combo_perf.setCurrentText(self.settings['optics']['performance'])
        self.combo_perf.currentTextChanged.connect(self.on_optics_changed)
        perf_layout.addWidget(self.combo_perf)

        rendimiento_layout.addWidget(perf_container)

        threads_container = QWidget()
        threads_layout = QVBoxLayout(threads_container)
        threads_layout.setContentsMargins(0, 4, 0, 8)
        threads_layout.setSpacing(4)

        threads_label = QLabel("Hilos de CPU")
        threads_label.setObjectName("filterLabel")
        threads_layout.addWidget(threads_label)

        self.spin_threads = QSpinBox()
        self.spin_threads.setMinimum(1)
        max_threads = psutil.cpu_count(logical=True) if HAS_PSUTIL else 8
        self.spin_threads.setMaximum(max_threads)
        self.spin_threads.setValue(self.settings['optics']['threads'])
        self.spin_threads.valueChanged.connect(self.on_optics_changed)
        threads_layout.addWidget(self.spin_threads)

        rendimiento_layout.addWidget(threads_container)
        rendimiento_layout.addStretch()
        return page

    def create_optics_page(self):
        page = QWidget()
        optics_layout = QVBoxLayout(page)
        optics_layout.setContentsMargins(8, 8, 8, 8)
        optics_layout.setSpacing(0)

        self._add_section_title(optics_layout, "MEJORA VISUAL")

        clahe_row = QWidget()
        clahe_layout = QHBoxLayout(clahe_row)
        clahe_layout.setContentsMargins(0, 8, 0, 8)

        clahe_label = QLabel("CLAHE + Nitidez")
        clahe_label.setObjectName("alertLabel")

        self.chk_clahe = ToggleSwitch()
        self.chk_clahe.setChecked(self.settings['optics']['clahe'])
        self.chk_clahe.toggled.connect(self.on_optics_changed)

        clahe_layout.addWidget(clahe_label)
        clahe_layout.addStretch()
        clahe_layout.addWidget(self.chk_clahe)
        optics_layout.addWidget(clahe_row)

        upscale_row = QWidget()
        upscale_layout = QHBoxLayout(upscale_row)
        upscale_layout.setContentsMargins(0, 8, 0, 8)

        upscale_label = QLabel("Superresolución AI")
        upscale_label.setObjectName("alertLabel")

        self.chk_upscale = ToggleSwitch()
        self.chk_upscale.setChecked(self.settings['optics']['upscale'])
        self.chk_upscale.toggled.connect(self.on_optics_changed)

        upscale_layout.addWidget(upscale_label)
        upscale_layout.addStretch()
        upscale_layout.addWidget(self.chk_upscale)
        optics_layout.addWidget(upscale_row)

        optics_layout.addStretch()
        return page

    def on_optics_changed(self, *args):
        optics_dict = {
            'clahe': self.chk_clahe.isChecked(),
            'zoom': 1.0,
            'upscale': self.chk_upscale.isChecked(),
            'performance': self.combo_perf.currentText(),
            'threads': self.spin_threads.value()
        }

        self.config.set('Optics', 'clahe', str(optics_dict['clahe']), save=False)
        self.config.set('Optics', 'zoom', str(optics_dict['zoom']), save=False)
        self.config.set('Optics', 'upscale', str(optics_dict['upscale']), save=False)
        self.config.set('Optics', 'performance', optics_dict['performance'], save=False)
        self.config.set('Optics', 'threads', str(optics_dict['threads']), save=False)
        self.config.save()
        self.optics_changed.emit(optics_dict)

    def create_video_page(self):
        page = QWidget()
        video_layout = QVBoxLayout(page)
        video_layout.setContentsMargins(8, 8, 8, 8)
        video_layout.setSpacing(0)

        self._add_section_title(video_layout, "FUENTE DE VIDEO")
        self._available_cameras = self.detectar_camaras()

        dual_container = QWidget()
        dual_layout = QHBoxLayout(dual_container)
        dual_layout.setContentsMargins(0, 8, 0, 4)
        dual_layout.setSpacing(10)

        dual_label = QLabel("Modo Dual Stream")
        dual_label.setObjectName("yoloLabel")
        dual_layout.addWidget(dual_label)
        dual_layout.addStretch()

        self.chk_dual_stream = ToggleSwitch()
        self.chk_dual_stream.setChecked(False)
        self.chk_dual_stream.toggled.connect(self.on_dual_stream_toggled)
        dual_layout.addWidget(self.chk_dual_stream)
        video_layout.addWidget(dual_container)
        video_layout.addWidget(SeparadorDelgado())
        video_layout.addSpacing(8)

        self.video_tabs = QTabWidget()
        self.video_tabs.setObjectName("videoTabs")
        self.video_tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # TAB CANAL 1
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        tab1_layout.setContentsMargins(8, 4, 8, 8)
        tab1_layout.setSpacing(4)
        tab1_layout.setAlignment(Qt.AlignTop)

        source1_label = QLabel("Tipo de fuente:")
        source1_label.setObjectName("filterLabel")
        tab1_layout.addWidget(source1_label)

        self.combo_source_type_1 = QComboBox()
        self.combo_source_type_1.addItems(["Cámara", "RTSP", "Video local"])
        self.combo_source_type_1.currentIndexChanged.connect(self.on_source_type_1_changed)
        tab1_layout.addWidget(self.combo_source_type_1)
        tab1_layout.addSpacing(8)
        tab1_layout.addWidget(SeparadorDelgado())
        tab1_layout.addSpacing(8)

        self.source_stack_1 = QStackedWidget()
        self.source_stack_1.setObjectName("sourceStack1")
        self.source_stack_1.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.source_stack_1.addWidget(self._build_source_camera_widget(1))
        self.source_stack_1.addWidget(self._build_source_rtsp_widget(1))
        self.source_stack_1.addWidget(self._build_source_video_widget(1))
        self.source_stack_1.setCurrentIndex(0)
        tab1_layout.addWidget(self.source_stack_1)

        # AGREGAR PANEL DE TELEMETRÍA CANAL 1
        tab1_layout.addSpacing(8)
        tab1_layout.addWidget(SeparadorDelgado())
        tab1_layout.addWidget(self._build_telemetry_widget(channel=1))

        # TAB CANAL 2
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        tab2_layout.setContentsMargins(8, 4, 8, 8)
        tab2_layout.setSpacing(4)
        tab2_layout.setAlignment(Qt.AlignTop)

        source2_label = QLabel("Tipo de fuente:")
        source2_label.setObjectName("filterLabel")
        tab2_layout.addWidget(source2_label)

        self.combo_source_type_2 = QComboBox()
        self.combo_source_type_2.addItems(["Cámara", "RTSP", "Video local"])
        self.combo_source_type_2.currentIndexChanged.connect(self.on_source_type_2_changed)
        tab2_layout.addWidget(self.combo_source_type_2)
        tab2_layout.addSpacing(8)
        tab2_layout.addWidget(SeparadorDelgado())
        tab2_layout.addSpacing(8)

        self.source_stack_2 = QStackedWidget()
        self.source_stack_2.setObjectName("sourceStack2")
        self.source_stack_2.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.source_stack_2.addWidget(self._build_source_camera_widget(2))
        self.source_stack_2.addWidget(self._build_source_rtsp_widget(2))
        self.source_stack_2.addWidget(self._build_source_video_widget(2))
        tab2_layout.addWidget(self.source_stack_2)

        # AGREGAR PANEL DE TELEMETRÍA CANAL 2
        tab2_layout.addSpacing(8)
        tab2_layout.addWidget(SeparadorDelgado())
        tab2_layout.addWidget(self._build_telemetry_widget(channel=2))

        self.video_tabs.addTab(tab1, "Canal 1")
        self.video_tabs.addTab(tab2, "Canal 2")
        self.video_tabs.setTabEnabled(1, False)
        video_layout.addWidget(self.video_tabs)
        video_layout.addStretch()
        return page

    def _build_telemetry_widget(self, channel):
        """Construye un cuadro visual de monitoreo de conexión e IP en el Panel Izquierdo."""
        frame = QFrame()
        frame.setObjectName("telemetryBox")
        frame.setStyleSheet("""
            QFrame#telemetryBox {
                background-color: #020617;
                border: 1px solid #1e293b;
                border-radius: 6px;
                padding: 6px;
            }
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_title = QLabel(f"ESTADO EN VIVO CH{channel}")
        header_title.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px;")

        led_indicator = QLabel()
        led_indicator.setFixedSize(8, 8)
        led_indicator.setStyleSheet("background-color: #64748b; border-radius: 4px;")

        header_layout.addWidget(header_title)
        header_layout.addStretch()
        header_layout.addWidget(led_indicator)
        layout.addLayout(header_layout)

        lbl_status = QLabel("Estado: Desconectado")
        lbl_status.setStyleSheet("color: #94a3b8; font-size: 11px;")

        lbl_ping = QLabel("Latencia: -- ms")
        lbl_ping.setStyleSheet("color: #94a3b8; font-size: 11px;")

        lbl_loss = QLabel("Pérdida Paquetes: -- %")
        lbl_loss.setStyleSheet("color: #94a3b8; font-size: 11px;")

        layout.addWidget(lbl_status)
        layout.addWidget(lbl_ping)
        layout.addWidget(lbl_loss)

        if channel == 1:
            self.led_status_ch1 = led_indicator
            self.lbl_status_ch1 = lbl_status
            self.lbl_ping_ch1 = lbl_ping
            self.lbl_loss_ch1 = lbl_loss
        else:
            self.led_status_ch2 = led_indicator
            self.lbl_status_ch2 = lbl_status
            self.lbl_ping_ch2 = lbl_ping
            self.lbl_loss_ch2 = lbl_loss

        return frame

    def update_telemetry_ch1(self, status="EN LINEA", ping=0, loss=0, color="#10b981"):
        """Actualiza las etiquetas de telemetría del Canal 1."""
        if hasattr(self, 'lbl_status_ch1'):
            self.lbl_status_ch1.setText(f"Estado: {status}")
            self.lbl_ping_ch1.setText(f"Latencia: {ping} ms" if ping > 0 else "Latencia: Local")
            self.lbl_loss_ch1.setText(f"Pérdida Paquetes: {loss}%")
            self.led_status_ch1.setStyleSheet(f"background-color: {color}; border-radius: 4px;")

    def update_telemetry_ch2(self, status="EN LINEA", ping=0, loss=0, color="#10b981"):
        """Actualiza las etiquetas de telemetría del Canal 2."""
        if hasattr(self, 'lbl_status_ch2'):
            self.lbl_status_ch2.setText(f"Estado: {status}")
            self.lbl_ping_ch2.setText(f"Latencia: {ping} ms" if ping > 0 else "Latencia: Local")
            self.lbl_loss_ch2.setText(f"Pérdida Paquetes: {loss}%")
            self.led_status_ch2.setStyleSheet(f"background-color: {color}; border-radius: 4px;")

    def _build_source_camera_widget(self, channel):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel(f"Cámara Canal {channel}:")
        label.setObjectName("filterLabel")
        layout.addWidget(label)

        combo = QComboBox()
        combo.setObjectName("videoCombo")
        combo.addItems(self._available_cameras)

        if channel == 1:
            self.video_combo = combo
            initial_source = self.settings.get('video_source', 'Cámara Local (0)')
            combo.setCurrentText(initial_source)
            self._last_valid_source_1 = initial_source
        else:
            self.combo_cameras_2 = combo
            combo.setEnabled(False)
            if len(self._available_cameras) > 1:
                initial_source = self._available_cameras[1]
            elif self._available_cameras:
                initial_source = self._available_cameras[0]
            else:
                initial_source = ""
            combo.setCurrentText(initial_source)
            self._last_valid_source_2 = initial_source

        combo.addItem("Volver a escanear…")
        rescan_index = combo.count() - 1

        if channel == 1:
            self.rescan_index_1 = rescan_index
            combo.currentIndexChanged.connect(
                lambda idx, ch=channel: self.on_camera_combo_changed(ch, idx)
            )
        else:
            self.rescan_index_2 = rescan_index
            combo.currentIndexChanged.connect(
                lambda idx, ch=channel: self.on_camera_combo_changed(ch, idx)
            )

        layout.addWidget(combo)

        btn = QPushButton(f"Iniciar fuente {channel}")
        btn.setObjectName("cameraToggleBtn")

        if channel == 1:
            self.btn_camera_toggle = btn
            btn.clicked.connect(self.camera_toggle_requested.emit)
        else:
            self.btn_camera_2_toggle = btn
            btn.clicked.connect(self.camera_2_toggle_requested.emit)
            btn.setEnabled(False)

        layout.addWidget(btn)
        return widget

    def _build_source_rtsp_widget(self, channel):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        input_field = FocusEscapableLineEdit()
        input_field.setPlaceholderText("rtsp://usuario:contraseña@ip:puerto/stream")
        input_field.setObjectName("rtspInput")
        layout.addWidget(input_field)

        if channel == 1:
            saved_url = self.config.get('General', 'rtsp_url_1', '')
            self.input_rtsp_1 = input_field
        else:
            saved_url = self.config.get('General', 'rtsp_url_2', '')
            self.input_rtsp_2 = input_field

        if saved_url:
            input_field.setText(saved_url)

        btn = QPushButton("Conectar RTSP")
        btn.setObjectName("rtspBtn")
        btn.clicked.connect(
            lambda: self.rtsp_connect_requested.emit(input_field.text(), channel)
        )
        layout.addWidget(btn)

        if channel == 1:
            self.btn_rtsp_1 = btn
        else:
            self.btn_rtsp_2 = btn

        return widget

    def _build_source_video_widget(self, channel):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        btn = QPushButton("Cargar video local")
        btn.setObjectName("videoBtn")
        btn.clicked.connect(lambda: self.video_load_requested.emit(channel))
        layout.addWidget(btn)

        if channel == 1:
            self.btn_video_1 = btn
        else:
            self.btn_video_2 = btn

        return widget

    def on_source_type_1_changed(self, index):
        self.source_stack_1.setCurrentIndex(index)

    def on_source_type_2_changed(self, index):
        self.source_stack_2.setCurrentIndex(index)

    def on_camera_combo_changed(self, channel, index):
        if channel == 1:
            combo = self.video_combo
            rescan_idx = self.rescan_index_1
            last_valid_attr = '_last_valid_source_1'
        else:
            combo = self.combo_cameras_2
            rescan_idx = self.rescan_index_2
            last_valid_attr = '_last_valid_source_2'

        if index == rescan_idx:
            last_valid = getattr(self, last_valid_attr)
            self.rescan_cameras()
            cameras = self._available_cameras
            if last_valid in cameras:
                combo.setCurrentText(last_valid)
            elif cameras:
                combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(-1)
            setattr(self, last_valid_attr, combo.currentText())
            return

        selected_text = combo.currentText()
        setattr(self, last_valid_attr, selected_text)

        if channel == 1:
            self.on_video_source_changed(selected_text)
        else:
            self.on_camera_2_changed(selected_text)

    def detectar_camaras(self, max_camaras=5, force_rescan=False):
        if not force_rescan:
            saved_cameras = self.config.get_camera_list()
            if saved_cameras is not None:
                return saved_cameras

        disponibles = []
        try:
            from pygrabber.dshow_graph import FilterGraph
            graph = FilterGraph()
            devices = graph.get_input_devices()
            for index, device_name in enumerate(devices):
                disponibles.append(f"{device_name} (Puerto {index})")
        except ImportError:
            backends = [cv2.CAP_ANY, cv2.CAP_MSMF, cv2.CAP_DSHOW]
            for i in range(max_camaras):
                for backend in backends:
                    cap = cv2.VideoCapture(i, backend)
                    if cap.isOpened():
                        disponibles.append(f"Cámara Local ({i})")
                        cap.release()
                        break
                    cap.release()

        self.config.set_camera_list(disponibles)
        self.log_signal.emit(f"Cámaras detectadas: {disponibles}", "DEBUG")
        return disponibles

    def rescan_cameras(self):
        self.stop_camera_requested.emit()
        cameras = self.detectar_camaras(force_rescan=True)
        self._available_cameras = cameras

        self.video_combo.blockSignals(True)
        self.video_combo.clear()
        self.video_combo.addItems(cameras)
        self.video_combo.addItem("Volver a escanear…")
        self.rescan_index_1 = self.video_combo.count() - 1

        last_valid = getattr(self, '_last_valid_source_1', '')
        if last_valid in cameras:
            self.video_combo.setCurrentText(last_valid)
        elif cameras:
            self.video_combo.setCurrentIndex(0)
        else:
            self.video_combo.setCurrentIndex(-1)
        self.video_combo.blockSignals(False)

        if hasattr(self, 'combo_cameras_2'):
            self.combo_cameras_2.blockSignals(True)
            self.combo_cameras_2.clear()
            self.combo_cameras_2.addItems(cameras)
            self.combo_cameras_2.addItem("Volver a escanear…")
            self.rescan_index_2 = self.combo_cameras_2.count() - 1

            last_valid = getattr(self, '_last_valid_source_2', '')
            if last_valid in cameras:
                self.combo_cameras_2.setCurrentText(last_valid)
            elif len(cameras) > 1:
                self.combo_cameras_2.setCurrentIndex(1)
            elif cameras:
                self.combo_cameras_2.setCurrentIndex(0)
            else:
                self.combo_cameras_2.setCurrentIndex(-1)
            self.combo_cameras_2.blockSignals(False)

    def create_alerts_page(self):
        page = QWidget()
        alerts_layout = QVBoxLayout(page)
        alerts_layout.setContentsMargins(8, 8, 8, 8)
        alerts_layout.setSpacing(0)

        self._add_section_title(alerts_layout, "ALERTAS")
        self.alert_checks = {}

        alert_items = [
            ('detection', 'Detección de objetos'),
            ('connection', 'Pérdida de conexión'),
            ('low_battery', 'Batería baja')
        ]

        for key, label_text in alert_items:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 8, 0, 8)
            row_layout.setSpacing(10)

            label = QLabel(label_text)
            label.setObjectName("alertLabel")
            row_layout.addWidget(label)
            row_layout.addStretch()

            toggle = ToggleSwitch()
            toggle.setChecked(self.settings['alerts'][key])
            toggle.toggled.connect(
                lambda checked, k=key: self.on_alert_toggle(k, checked)
            )
            row_layout.addWidget(toggle)

            alerts_layout.addWidget(row_widget)
            self.alert_checks[key] = toggle

        alerts_layout.addStretch()
        return page

    def set_camera_button_state(self, active):
        self.set_channel_button_state(1, active)

    def set_channel_button_state(self, channel, active):
        if channel == 1:
            button = getattr(self, 'btn_camera_toggle', None)
        elif channel == 2:
            button = getattr(self, 'btn_camera_2_toggle', None)
        else:
            return

        if button is not None:
            if active:
                button.setText(f"Detener señal de fuente {channel}")
            else:
                button.setText(f"Iniciar fuente {channel}")

    def load_settings_from_config(self):
        settings = DEFAULT_SETTINGS.copy()

        for obj in ['person', 'car', 'boat', 'helicopter']:
            enabled = self.config.get('Detections', f'{obj}_enabled', 'True') == 'True'
            conf = float(self.config.get(
                'Detections',
                f'{obj}_confidence',
                str(DEFAULT_SETTINGS['detections'][obj]['confidence'])
            ))
            settings['detections'][obj]['enabled'] = enabled
            settings['detections'][obj]['confidence'] = conf

        # Cargar configuración del módulo OCR
        settings['ocr_enabled'] = self.config.getboolean('Detections', 'ocr_enabled', fallback=False)

        settings['video_source'] = self.config.get(
            'General',
            'video_source',
            DEFAULT_SETTINGS['video_source']
        )

        for key in ['detection', 'connection', 'low_battery']:
            settings['alerts'][key] = self.config.get('Alerts', key, 'True') == 'True'

        settings['save_path'] = self.config.get(
            'General',
            'save_path',
            DEFAULT_SAVE_PATH
        )

        settings['optics'] = {
            'clahe': self.config.getboolean('Optics', 'clahe', False),
            'zoom': self.config.getfloat('Optics', 'zoom', 1.0),
            'upscale': self.config.getboolean('Optics', 'upscale', False),
            'performance': self.config.get('Optics', 'performance', 'Balanceado (Estandar)'),
            'threads': self.config.getint('Optics', 'threads', 4),
        }

        return settings

    def on_yolo_toggle_changed(self, checked):
        self.yolo_toggle_changed.emit(checked)

    def on_ocr_toggle_changed(self, checked):
        """Maneja cambios en el toggle de reconocimiento de placas."""
        self.settings['ocr_enabled'] = checked
        self.config.set('Detections', 'ocr_enabled', str(checked))

        estado = "activada" if checked else "desactivada"
        self.log_signal.emit(f"Lectura de placas OCR {estado}", "INFO")

        self.ocr_toggle_changed.emit(checked)
        self.emit_settings()

    def on_det_toggle(self, obj, checked):
        self.settings['detections'][obj]['enabled'] = checked
        self.config.set('Detections', f'{obj}_enabled', str(checked))

        estado = "activada" if checked else "desactivada"
        nombres = {
            'person': 'personas',
            'car': 'carros',
            'boat': 'botes',
            'helicopter': 'helicópteros'
        }
        nombre_legible = nombres.get(obj, obj)

        self.log_signal.emit(f"Detección de {nombre_legible} {estado}", "INFO")
        self.emit_settings()

    def on_conf_slider(self, obj, value):
        conf = value / 100.0
        self.settings['detections'][obj]['confidence'] = conf
        self.det_widgets[obj]['conf_label'].setText(f"{value}%")
        self.config.set('Detections', f'{obj}_confidence', str(conf))
        self.emit_settings()

    def on_video_source_changed(self, text):
        self.settings['video_source'] = text
        self.config.set('General', 'video_source', text)
        self.emit_settings()
        self.video_source_changed.emit(text)

    def on_dual_stream_toggled(self, enabled):
        self.video_tabs.setTabEnabled(1, enabled)
        if not enabled:
            self.video_tabs.setCurrentIndex(0)
        self.combo_cameras_2.setEnabled(enabled)
        self.btn_camera_2_toggle.setEnabled(enabled)
        self.dual_stream_toggled.emit(enabled)

    def on_camera_2_changed(self, text):
        self.camera_2_changed.emit(text)

    def on_alert_toggle(self, key, checked):
        self.settings['alerts'][key] = checked
        self.config.set('Alerts', key, str(checked))
        self.emit_settings()

    def emit_settings(self):
        self.settings_changed.emit(self.settings)