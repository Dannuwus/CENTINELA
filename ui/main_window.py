# =============================================================================
# MÓDULO DE VENTANA PRINCIPAL (ORQUESTADOR)
# =============================================================================
# Este módulo implementa la ventana principal que orquesta todos los componentes:
# 1. Barra de título personalizada
# 2. Panel izquierdo (configuración)
# 3. Panel central (video)
# 4. Panel derecho (capturas y logs)
# 5. Panel inferior (telemetría)
# 6. Gestión de hilos de video (canal 1 y canal 2)
# 7. Sistema de atajos de teclado
# 8. Sonidos de alerta
# 9. Notificaciones toast
# 10. Persistencia de estado
#
# DEPENDENCIAS:
# - core.constants (dimensiones, rutas)
# - core.config_manager (persistencia)
# - core.video_thread (hilo de video)
# - ui.title_bar (barra de título)
# - ui.left_panel (panel izquierdo)
# - ui.right_panel (panel derecho)
# - ui.video_panel (panel de video)
# - ui.bottom_panel (panel inferior)
# - ui.dialogs (diálogos)
# - ui.toast (notificaciones)
# =============================================================================

from core.log_manager import LogManager

# =============================================================================
# IMPORTS ESTÁNDAR
# =============================================================================
from pathlib import Path  # Manejo de rutas
import time  # Para control de tiempo en actualizaciones de UI

# =============================================================================
# IMPORTS DE TERCEROS
# =============================================================================
import cv2  # OpenCV para guardar capturas

# =============================================================================
# IMPORTS DE PYQT
# =============================================================================
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap, QShortcut, QKeySequence
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QMessageBox, QApplication,
    QComboBox, QLineEdit, QSpinBox, QTextEdit
)

# =============================================================================
# IMPORTS INTERNOS
# =============================================================================
from core.constants import (
    DEFAULT_SAVE_PATH, LEFT_PANEL_WIDTH, RIGHT_PANEL_WIDTH,
    NAV_BAR_WIDTH
)
from core.config_manager import ConfigManager
from core.video_thread import VideoThread
from ui.title_bar import TitleBar
from ui.left_panel import LeftPanel
from ui.right_panel import RightPanel
from ui.video_panel import VideoPanel
from ui.bottom_panel import BottomPanel
from ui.dialogs import ShortcutsDialog
from ui.toast import ToastNotification


class MainWindow(QMainWindow):
    """
    Ventana principal del sistema detector de objetos.

    Esta clase es el orquestador central que:
    - Crea y conecta todos los paneles
    - Gestiona los hilos de video (canal 1 y canal 2)
    - Maneja los atajos de teclado
    - Reproduce sonidos de alerta
    - Muestra notificaciones toast
    - Persiste el estado de la aplicación
    - Coordina la comunicación entre componentes

    Uso:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.showMaximized()
        sys.exit(app.exec())
    """

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def __init__(self):
        """Inicializa la ventana principal y todos sus componentes."""
        super().__init__()

        # Bandera para evitar operaciones durante el cierre
        self.is_closing = False

        # Configuración de ventana
        self.setWindowTitle("Sistema detector de objetos")
        self.setGeometry(100, 100, 1280, 720)
        self.setWindowFlags(Qt.FramelessWindowHint)  # Sin bordes nativos

        # ---------------------------------------------------------------------
        # CONFIGURACIÓN PERSISTENTE
        # ---------------------------------------------------------------------
        self.config = ConfigManager()

        # ---------------------------------------------------------------------
        # INICIALIZAR COMPONENTES DE UI
        # ---------------------------------------------------------------------
        self._init_components()

        # ---------------------------------------------------------------------
        # CONECTAR SEÑALES
        # ---------------------------------------------------------------------
        self._connect_signals()

        # ---------------------------------------------------------------------
        # CONFIGURAR LAYOUT Y ESTILOS
        # ---------------------------------------------------------------------
        self.setup_ui()
        self.apply_styles()

        # ---------------------------------------------------------------------
        # CONFIGURAR ATAJOS DE TECLADO
        # ---------------------------------------------------------------------
        self._setup_shortcuts()

        # ---------------------------------------------------------------------
        # INICIALIZAR ESTADO
        # ---------------------------------------------------------------------
        self._init_state()

        # ---------------------------------------------------------------------
        # RESTAURAR ESTADO PREVIO
        # ---------------------------------------------------------------------
        self._restore_state()

        # ---------------------------------------------------------------------
        # INICIALIZAR SONIDOS
        # ---------------------------------------------------------------------
        self.init_alert_sounds()

        # Verificar cierre inesperado de la sesión anterior
        self.log_manager.check_unexpected_shutdown()

        # Log de inicio
        self.log_manager.add_log("Aplicación iniciada correctamente", "INFO")

    # =========================================================================
    # INICIALIZACIÓN DE COMPONENTES
    # =========================================================================

    def _init_components(self):
        """
        Crea e inicializa todos los componentes de la UI.

        Componentes creados:
        - LeftPanel: Panel de configuración (izquierda)
        - VideoPanel: Panel de video (centro)
        - RightPanel: Panel de capturas/logs (derecha)
        - BottomPanel: Panel de telemetría (inferior)
        - TitleBar: Barra de título (superior)
        """
        # Panel izquierdo (configuración)
        self.left_panel = LeftPanel(self.config)

        # Gestor central de logs
        self.log_manager = LogManager(parent=self)

        # Panel de video (centro)
        self.video_panel = VideoPanel()
        self.video_panel.clear_frame()
        self.video_panel.set_active_channel(1)

        # Panel derecho (capturas y logs)
        self.right_panel = RightPanel(self.config)

        # Panel inferior (telemetría)
        self.bottom_panel = BottomPanel()

        # Barra de título
        self.title_bar = TitleBar()

    # =========================================================================
    # CONEXIÓN DE SEÑALES
    # =========================================================================

    def _connect_signals(self):
        """
        Conecta todas las señales entre componentes.

        Este método centraliza todas las conexiones para facilitar
        el mantenimiento y evitar conexiones perdidas.
        """
        # ---------------------------------------------------------------------
        # SEÑALES DEL PANEL IZQUIERDO
        # ---------------------------------------------------------------------
        self.left_panel.toggle_panel_requested.connect(self.on_toggle_left_panel)
        self.left_panel.log_signal.connect(self.log_manager.add_log)
        self.left_panel.camera_toggle_requested.connect(self.on_camera_toggle_requested)
        self.left_panel.camera_2_toggle_requested.connect(self.on_camera_2_toggle_requested)
        self.left_panel.camera_2_changed.connect(self.on_camera_2_changed)
        self.left_panel.optics_changed.connect(self.on_optics_changed)
        self.left_panel.dual_stream_toggled.connect(self.toggle_dual_stream)
        self.left_panel.rtsp_connect_requested.connect(self.on_connect_rtsp)
        self.left_panel.video_load_requested.connect(self.on_load_video)
        self.left_panel.settings_changed.connect(self.on_settings_changed)
        self.left_panel.video_source_changed.connect(self.on_video_source_changed)
        self.left_panel.stop_camera_requested.connect(self.on_stop_camera_requested)
        self.left_panel.yolo_toggle_changed.connect(self.on_yolo_toggle_changed)

        # Conexión para el OCR / LPR de placas
        self.left_panel.ocr_toggle_changed.connect(self.on_ocr_toggle_changed)

        # ---------------------------------------------------------------------
        # SEÑALES DEL PANEL DERECHO
        # ---------------------------------------------------------------------
        self.right_panel.toggle_panel_requested.connect(self.on_toggle_right_panel)
        # Conectar LogManager con la página de logs
        self.log_manager.log_batch.connect(self.right_panel.logs_page.append_batch)

        # ---------------------------------------------------------------------
        # SEÑALES DEL PANEL INFERIOR
        # ---------------------------------------------------------------------
        self.bottom_panel.slider_zoom.valueChanged.connect(self.on_bottom_zoom_changed)
        self.bottom_panel.capture_requested.connect(self.on_capture_requested)

        # ---------------------------------------------------------------------
        # SEÑALES DE LA BARRA DE TÍTULO
        # ---------------------------------------------------------------------
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self.toggle_maximize)
        self.title_bar.close_requested.connect(self.close)
        self.title_bar.shortcuts_requested.connect(self.show_shortcuts_dialog)
        self.title_bar.yolo_toggle_requested.connect(self.on_yolo_quick_toggle)
        self.title_bar.objeto_toggle_requested.connect(self.on_objeto_toggle_requested)
        self.title_bar.capture_requested.connect(self.on_capture_requested)
        self.title_bar.sound_toggle_requested.connect(self.toggle_mute)

        # ---------------------------------------------------------------------
        # SEÑALES DEL PANEL DE VIDEO
        # ---------------------------------------------------------------------
        self.video_panel.camera_focused.connect(self.on_camera_focused)

    # =========================================================================
    # CONFIGURACIÓN DE ATAJOS DE TECLADO
    # =========================================================================

    def _setup_shortcuts(self):
        """
        Configura todos los atajos de teclado del sistema.

        Los atajos se dividen en grupos:
        - Navegación y paneles (Ctrl+H, Ctrl+L, Ctrl+F)
        - Control de cámara (Ctrl+1, Ctrl+2, Ctrl+D)
        - Detección YOLO (Ctrl+Y, Ctrl+3 al 6)
        - Zoom y paneo (Ctrl++, Ctrl+-, flechas)
        - Captura (Ctrl+C)
        - Sonido (Ctrl+M)
        - Ayuda (Ctrl+/)
        """
        # ---------------------------------------------------------------------
        # ATAJOS GENERALES
        # ---------------------------------------------------------------------

        # Mostrar diálogo de atajos
        self.shortcuts_shortcut = QShortcut(QKeySequence("Ctrl+/"), self)
        self.shortcuts_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+/", "DEBUG"), self.show_shortcuts_dialog())
        )

        # Pantalla completa
        self.fullscreen_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.fullscreen_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+F", "DEBUG"), self.toggle_fullscreen())
        )

        # Inspector de capturas
        self.inspector_shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        self.inspector_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+Shift+I", "DEBUG"), self.open_inspector_shortcut())
        )

        # ---------------------------------------------------------------------
        # ATAJOS DE CÁMARA
        # ---------------------------------------------------------------------

        # Iniciar/detener cámara 1
        self.camera_1_shortcut = QShortcut(QKeySequence("Ctrl+1"), self)
        self.camera_1_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+1", "DEBUG"), self.on_camera_toggle_requested())
        )

        # Iniciar/detener cámara 2
        self.camera_2_shortcut = QShortcut(QKeySequence("Ctrl+2"), self)
        self.camera_2_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+2", "DEBUG"), self.on_camera_2_toggle_requested())
        )

        # Alternar modo dual stream
        self.dual_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
        self.dual_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+D", "DEBUG"), self.on_dual_shortcut())
        )

        # Cambiar cámara activa en modo dual
        self.switch_camera_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        self.switch_camera_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+Tab", "DEBUG"), self.toggle_active_camera())
        )

        # ---------------------------------------------------------------------
        # ATAJOS DE DETECCIÓN YOLO
        # ---------------------------------------------------------------------

        # Alternar YOLO
        self.yolo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.yolo_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+Y", "DEBUG"), self.on_yolo_quick_toggle())
        )

        # Toggles de detección individual
        self.person_shortcut = QShortcut(QKeySequence("Ctrl+3"), self)
        self.person_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+3", "DEBUG"), self.toggle_person_detection())
        )

        self.car_shortcut = QShortcut(QKeySequence("Ctrl+4"), self)
        self.car_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+4", "DEBUG"), self.toggle_car_detection())
        )

        self.boat_shortcut = QShortcut(QKeySequence("Ctrl+5"), self)
        self.boat_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+5", "DEBUG"), self.toggle_boat_detection())
        )

        self.helicopter_shortcut = QShortcut(QKeySequence("Ctrl+6"), self)
        self.helicopter_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+6", "DEBUG"), self.toggle_helicopter_detection())
        )

        # ---------------------------------------------------------------------
        # ATAJOS DE CAPTURA Y PANELES
        # ---------------------------------------------------------------------

        # Captura manual
        self.capture_shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
        self.capture_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+C", "DEBUG"), self.on_capture_requested())
        )

        # Mostrar/ocultar galería
        self.history_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        self.history_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+H", "DEBUG"), self.toggle_captures_panel())
        )

        # Mostrar/ocultar logs
        self.logs_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self.logs_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+L", "DEBUG"), self.toggle_logs_panel())
        )

        # ---------------------------------------------------------------------
        # ATAJOS DE ZOOM Y PANEO
        # ---------------------------------------------------------------------

        # Zoom in/out
        self.zoom_in_shortcut = QShortcut(QKeySequence("Ctrl++"), self)
        self.zoom_in_shortcut.activated.connect(self.zoom_in)

        self.zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self)
        self.zoom_out_shortcut.activated.connect(self.zoom_out)

        # Paneo con flechas
        self.pan_up_shortcut = QShortcut(QKeySequence("Ctrl+Up"), self)
        self.pan_up_shortcut.activated.connect(lambda: self.pan_zoom(0, -0.1))

        self.pan_down_shortcut = QShortcut(QKeySequence("Ctrl+Down"), self)
        self.pan_down_shortcut.activated.connect(lambda: self.pan_zoom(0, 0.1))

        self.pan_left_shortcut = QShortcut(QKeySequence("Ctrl+Left"), self)
        self.pan_left_shortcut.activated.connect(lambda: self.pan_zoom(-0.1, 0))

        self.pan_right_shortcut = QShortcut(QKeySequence("Ctrl+Right"), self)
        self.pan_right_shortcut.activated.connect(lambda: self.pan_zoom(0.1, 0))

        # ---------------------------------------------------------------------
        # ATAJO DE SILENCIO
        # ---------------------------------------------------------------------

        # Silenciar/activar sonidos
        self.mute_shortcut = QShortcut(QKeySequence("Ctrl+M"), self)
        self.mute_shortcut.activated.connect(
            lambda: (self.log_manager.add_log("Atajo usado: Ctrl+M", "DEBUG"), self.toggle_mute())
        )

    # =========================================================================
    # INICIALIZACIÓN DE ESTADO
    # =========================================================================

    def _init_state(self):
        """
        Inicializa todas las variables de estado del sistema.

        Variables:
        - video_thread: Hilo de video del canal 1
        - video_thread_2: Hilo de video del canal 2
        - camera_active: Estado de cámara 1
        - camera_2_active: Estado de cámara 2
        - yolo_enabled: Estado global de YOLO
        - dual_stream_enabled: Estado de modo dual
        - active_camera: Canal activo para zoom/paneo
        - zoom_cam1/zoom_cam2: Niveles de zoom por canal
        - inspector_open: Estado del inspector
        """
        # Estado de hilos de video
        self.video_thread = None
        self.video_thread_2 = None

        # Estado de cámaras
        self.camera_active = False
        self.camera_2_active = False

        # Estado de YOLO
        self.yolo_enabled = False
        self.yolo_loading = False

        # Estado de dual stream
        self.dual_stream_enabled = False

        # Estado de zoom/paneo
        self.active_camera = 1
        self.zoom_cam1 = 1.0
        self.zoom_cam2 = 1.0

        # Control de actualización de FPS en UI
        self.last_fps_update_1 = 0.0  # Timestamp última actualización canal 1
        self.last_fps_update_2 = 0.0  # Timestamp última actualización canal 2

        # Estado de silencio global
        self.muted = False

        # Inicializar botón de sonido en la barra de título
        if hasattr(self, 'title_bar'):
            self.title_bar.set_sound_active(not self.muted)

        # Estado del inspector
        self.inspector_open = False
        self._active_inspector = None

    # =========================================================================
    # RESTAURACIÓN DE ESTADO PREVIO
    # =========================================================================

    def _restore_state(self):
        """
        Restaura el estado guardado desde la última sesión.

        Restaura:
        - Estado de YOLO
        - Cámara activa (si estaba activa al cerrar)
        - Páginas activas de los paneles
        - Estado de expansión de paneles
        """
        # ---------------------------------------------------------------------
        # RESTAURAR ESTADO DE YOLO
        # ---------------------------------------------------------------------
        saved_yolo = self.config.getboolean('General', 'yolo_enabled', False)
        if saved_yolo:
            self.yolo_enabled = True
            self.left_panel.yolo_toggle.blockSignals(True)
            self.left_panel.yolo_toggle.setChecked(True)
            self.left_panel.yolo_toggle._animate(True)
            self.left_panel.yolo_toggle.update()
            self.left_panel.yolo_toggle.blockSignals(False)
            self.title_bar.set_yolo_active(True)

        # ---------------------------------------------------------------------
        # RESTAURAR CÁMARA ACTIVA
        # ---------------------------------------------------------------------
        if self.config.get('General', 'camera_was_active', 'False') == 'True':
            QTimer.singleShot(200, self.start_camera)
        # Restaurar fuente del canal 2
        saved_source_2 = self.config.get('General', 'video_source_2', '')
        if saved_source_2:
            # Buscar si existe en el combo y seleccionarla
            index = self.left_panel.combo_cameras_2.findText(saved_source_2)
            if index >= 0:
                self.left_panel.combo_cameras_2.setCurrentIndex(index)

        # ---------------------------------------------------------------------
        # RESTAURAR ESTADO DE PANELES
        # ---------------------------------------------------------------------
        QTimer.singleShot(100, self.restore_panel_state)

        # Asegurar que los hilos se detengan al cerrar
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        # Restaurar modo dual stream sin disparar logs
        saved_dual = self.config.getboolean('General', 'dual_stream_enabled', False)
        if saved_dual:
            # Bloquear señales para evitar log y efectos secundarios
            self.left_panel.chk_dual_stream.blockSignals(True)
            self.left_panel.chk_dual_stream.setChecked(True)
            self.left_panel.chk_dual_stream.blockSignals(False)

            # Activar el modo dual directamente sin pasar por el toggle
            self.dual_stream_enabled = True
            self.video_panel.toggle_dual_mode(True)
            # Habilitar widgets del canal 2
            self.left_panel.video_tabs.setTabEnabled(1, True)
            self.left_panel.combo_cameras_2.setEnabled(True)
            self.left_panel.btn_camera_2_toggle.setEnabled(True)

        # Sincronizar botones de objetos con configuración restaurada
        self.sync_object_buttons()

    # =========================================================================
    # GESTIÓN DE OCR / LPR
    # =========================================================================

    def on_ocr_toggle_changed(self, enabled):
        """Maneja el cambio de estado del interruptor de lectura de placas (OCR)."""
        if self.video_thread and hasattr(self.video_thread, 'set_ocr_enabled'):
            self.video_thread.set_ocr_enabled(enabled)
        if self.video_thread_2 and hasattr(self.video_thread_2, 'set_ocr_enabled'):
            self.video_thread_2.set_ocr_enabled(enabled)

    # =========================================================================
    # SISTEMA DE SONIDOS DE ALERTA
    # =========================================================================

    def init_alert_sounds(self):
        """
        Inicializa los efectos de sonido para alertas.

        Carga tres sonidos:
        - detection_alert.wav: Sonido al detectar objeto
        - connection_alert.wav: Sonido al perder/conectar cámara
        - battery_alert.wav: Sonido de batería baja

        Si un archivo no existe, muestra advertencia y continúa.
        """
        alert_sounds = {
            'detection': 'detection_alert.wav',
            'connection': 'connection_alert.wav',
            'low_battery': 'battery_alert.wav',
        }
        self.sounds = {}

        sounds_dir = Path(__file__).parent.parent / "resources" / "sounds"

        if not sounds_dir.exists():
            sounds_dir = Path(__file__).parent.parent / "sounds"

        for alert_type, filename in alert_sounds.items():
            sound_path = sounds_dir / filename
            if sound_path.exists():
                effect = QSoundEffect()
                effect.setSource(QUrl.fromLocalFile(str(sound_path)))
                effect.setVolume(0.7)
                effect.setMuted(self.muted)
                self.sounds[alert_type] = effect
            else:
                self.log_manager.add_log(f"No se encontró archivo de sonido: {sound_path}", "WARNING")
                self.sounds[alert_type] = None

    def play_alert_sound(self, alert_type):
        """
        Reproduce un sonido de alerta según el tipo.

        Args:
            alert_type: Clave del sonido ('detection', 'connection', 'low_battery').
        """
        if self.muted:
            return

        effect = self.sounds.get(alert_type)
        if effect:
            effect.play()

    def toggle_mute(self):
        """
        Alterna el silencio de todos los sonidos.

        Cambia el estado global y lo aplica a todos los efectos.
        """
        self.muted = not self.muted

        if hasattr(self, 'sounds'):
            for sound in self.sounds.values():
                if sound:
                    sound.setMuted(self.muted)

        self.title_bar.set_sound_active(not self.muted)

        estado = "desactivados" if self.muted else "activados"
        self.log_manager.add_log(f"Sonidos {estado}", "INFO")

    # =========================================================================
    # NOTIFICACIONES TOAST
    # =========================================================================

    def show_toast(self, message):
        """
        Muestra una notificación toast temporal.

        Args:
            message: Texto a mostrar en la notificación.
        """
        toast = ToastNotification(self, message)
        toast.show_at_corner(self)

        if not hasattr(self, '_active_toasts'):
            self._active_toasts = []
        self._active_toasts.append(toast)

        toast.closed.connect(lambda: self._remove_toast(toast))

    def _remove_toast(self, toast):
        """
        Elimina la referencia al toast cuando se cierra.

        Args:
            toast: Toast que se ha cerrado.
        """
        if hasattr(self, '_active_toasts') and toast in self._active_toasts:
            self._active_toasts.remove(toast)

    # =========================================================================
    # GESTIÓN DE PANELES LATERALES
    # =========================================================================

    def on_toggle_left_panel(self, expand):
        """
        Expande o colapsa el panel de configuración izquierdo.

        Args:
            expand: True para expandir, False para colapsar.
        """
        if expand:
            self.left_container.setFixedWidth(LEFT_PANEL_WIDTH)
            self.left_panel.stacked_widget.setVisible(True)
        else:
            self.left_container.setFixedWidth(NAV_BAR_WIDTH)
            self.left_panel.stacked_widget.setVisible(False)

    def on_toggle_right_panel(self, expand):
        """
        Expande o colapsa el panel derecho (capturas/logs).

        Args:
            expand: True para expandir, False para colapsar.
        """
        if expand:
            self.right_container.setFixedWidth(RIGHT_PANEL_WIDTH)
            self.right_panel.stacked_widget.setVisible(True)
        else:
            self.right_container.setFixedWidth(NAV_BAR_WIDTH)
            self.right_panel.stacked_widget.setVisible(False)

    def toggle_captures_panel(self):
        """
        Atajo Ctrl+H: Abre/cierra panel de capturas.
        """
        if self.inspector_open and self._active_inspector:
            self._active_inspector.close()
            self._active_inspector = None
            self.inspector_open = False

        if self.right_panel.is_expanded and self.right_panel.current_index == 0:
            self.on_toggle_right_panel(False)
            self.right_panel.is_expanded = False
            self.right_panel.stacked_widget.setVisible(False)
            for btn in self.right_panel.nav_button_group.buttons():
                btn.setChecked(False)
        else:
            self.on_toggle_right_panel(True)
            self.right_panel.is_expanded = True
            self.right_panel.stacked_widget.setVisible(True)
            self.right_panel.stacked_widget.setCurrentIndex(0)
            self.right_panel.current_index = 0
            buttons = self.right_panel.nav_button_group.buttons()
            if len(buttons) > 0:
                buttons[0].setChecked(True)

    def toggle_logs_panel(self):
        """
        Atajo Ctrl+L: Abre/cierra panel de logs.
        """
        if self.right_panel.is_expanded and self.right_panel.current_index == 1:
            self.on_toggle_right_panel(False)
            self.right_panel.is_expanded = False
            self.right_panel.stacked_widget.setVisible(False)
            for btn in self.right_panel.nav_button_group.buttons():
                btn.setChecked(False)
        else:
            self.on_toggle_right_panel(True)
            self.right_panel.is_expanded = True
            self.right_panel.stacked_widget.setVisible(True)
            self.right_panel.stacked_widget.setCurrentIndex(1)
            self.right_panel.current_index = 1
            buttons = self.right_panel.nav_button_group.buttons()
            if len(buttons) > 1:
                buttons[1].setChecked(True)

    # =========================================================================
    # GESTIÓN DE VENTANA
    # =========================================================================

    def toggle_maximize(self):
        """
        Alterna entre maximizado y normal.
        """
        if self.isMaximized():
            self.showNormal()
            self.title_bar.btn_maximize.setText("❐")
        else:
            self.showMaximized()
            self.title_bar.btn_maximize.setText("❐")

    def toggle_fullscreen(self):
        """
        Atajo Ctrl+F: Alterna pantalla completa.
        """
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def on_dual_shortcut(self):
        """
        Atajo de teclado Ctrl+D para alternar modo dual stream.
        """
        current_state = self.left_panel.chk_dual_stream.isChecked()
        self.left_panel.chk_dual_stream.setChecked(not current_state)

    def mousePressEvent(self, event):
        """
        Libera el foco de campos de entrada al hacer clic en áreas vacías.
        """
        super().mousePressEvent(event)

        focus_widget = QApplication.focusWidget()
        if isinstance(focus_widget, (QLineEdit, QTextEdit, QSpinBox, QComboBox)):
            if not focus_widget.geometry().contains(event.position().toPoint()):
                focus_widget.clearFocus()
                self.setFocus()

    # =========================================================================
    # GESTIÓN DE CÁMARAS
    # =========================================================================

    def on_camera_toggle_requested(self):
        """
        Alterna cámara 1 entre iniciar y detener.
        """
        if self.camera_active:
            self.stop_camera()
        else:
            self.start_camera()

    def on_camera_2_toggle_requested(self):
        """
        Alterna cámara 2 entre iniciar y detener.
        """
        if self.camera_2_active:
            self.stop_camera_2()
        else:
            self.start_camera_2()

    def toggle_dual_stream(self, enabled):
        """
        Activa/desactiva el modo dual stream.
        """
        estado = "activado" if enabled else "desactivado"
        self.log_manager.add_log(f"Modo dual stream {estado}", "INFO")

        self.dual_stream_enabled = enabled
        self.video_panel.toggle_dual_mode(enabled)

        if not enabled:
            self.stop_camera_2()
            self.on_camera_focused(1)

    def on_camera_focused(self, channel):
        """
        Actualiza la cámara activa al hacer clic en un contenedor de video.
        """
        self.active_camera = channel
        self.video_panel.set_active_channel(channel)

        if channel == 1:
            zoom_val = int(self.zoom_cam1 * 10)
        else:
            zoom_val = int(self.zoom_cam2 * 10)

        self.bottom_panel.slider_zoom.blockSignals(True)
        self.bottom_panel.slider_zoom.setValue(zoom_val)
        self.bottom_panel.slider_zoom.blockSignals(False)
        self.bottom_panel.lbl_zoom_val.setText(
            f"{self.zoom_cam1 if channel == 1 else self.zoom_cam2:.1f}x"
        )

    def toggle_active_camera(self):
        """
        Atajo Ctrl+Tab: Alterna entre canal 1 y 2 en modo dual.
        """
        if self.dual_stream_enabled:
            new_cam = 2 if self.active_camera == 1 else 1
            self.on_camera_focused(new_cam)

    def on_camera_2_changed(self, source_text):
        """
        Maneja cambio de cámara del canal 2.
        """
        if self.camera_2_active:
            self.stop_camera_2()
            self.start_camera_2()

    # =========================================================================
    # INICIO DE CÁMARAS
    # =========================================================================

    def _start_camera_on_channel(self, channel_id, source):
        """
        Inicia la cámara en el canal especificado.
        """
        if channel_id == 1:
            self.stop_camera()
        else:
            self.stop_camera_2()

        video_thread = self._create_video_thread(source, channel_id=channel_id)

        if channel_id == 1:
            self.video_thread = video_thread
            self.video_panel.pan_signal.connect(video_thread.set_pan)
            video_thread.change_pixmap_signal.connect(self.on_frame_ready)
            video_thread.telemetry_signal.connect(self.on_telemetry_update)
            video_thread.detection_log_signal.connect(self.on_detection_log)
            video_thread.object_captured_signal.connect(self.on_object_captured)
            video_thread.connection_status_signal.connect(self.on_connection_status)
            if hasattr(video_thread, 'log_signal'):
                video_thread.log_signal.connect(self.log_manager.add_log)
            self.camera_active = True
            self.left_panel.set_channel_button_state(1, True)
            self.video_panel.video_container.clear()
            self.video_panel.video_container.setPixmap(QPixmap())
            self.video_panel.video_container.setText("")
        else:
            self.video_thread_2 = video_thread
            self.video_panel.pan_signal_2.connect(video_thread.set_pan)
            video_thread.change_pixmap_signal.connect(self.on_frame_ready_2)
            video_thread.telemetry_signal.connect(self.on_telemetry_update_2)
            video_thread.detection_log_signal.connect(self.on_detection_log_2)
            video_thread.object_captured_signal.connect(self.on_object_captured_2)
            video_thread.connection_status_signal.connect(self.on_connection_status_2)
            if hasattr(video_thread, 'log_signal'):
                video_thread.log_signal.connect(self.log_manager.add_log)
            self.camera_2_active = True
            self.left_panel.set_channel_button_state(2, True)

        video_thread.start()

    def _stop_camera_on_channel(self, channel_id):
        """
        Detiene la cámara del canal especificado de forma segura.
        """
        if channel_id == 1:
            video_thread = self.video_thread
            if video_thread is None:
                return
            try:
                video_thread.change_pixmap_signal.disconnect(self.on_frame_ready)
                video_thread.telemetry_signal.disconnect(self.on_telemetry_update)
                video_thread.detection_log_signal.disconnect(self.on_detection_log)
                if hasattr(video_thread, 'log_signal'):
                    video_thread.log_signal.disconnect(self.log_manager.add_log)
                video_thread.object_captured_signal.disconnect(self.on_object_captured)
                video_thread.connection_status_signal.disconnect(self.on_connection_status)
                self.video_panel.pan_signal.disconnect(video_thread.set_pan)
            except Exception:
                pass

            if video_thread.isRunning():
                video_thread.stop()
                video_thread.wait()

            self.video_thread = None
            self.camera_active = False
            self.video_panel.clear_frame()
            self.left_panel.set_channel_button_state(1, False)
        else:
            video_thread = self.video_thread_2
            if video_thread is None:
                return
            try:
                video_thread.change_pixmap_signal.disconnect(self.on_frame_ready_2)
                video_thread.telemetry_signal.disconnect(self.on_telemetry_update_2)
                video_thread.detection_log_signal.disconnect(self.on_detection_log_2)
                if hasattr(video_thread, 'log_signal'):
                    video_thread.log_signal.disconnect(self.log_manager.add_log)
                video_thread.object_captured_signal.disconnect(self.on_object_captured_2)
                video_thread.connection_status_signal.disconnect(self.on_connection_status_2)
                self.video_panel.pan_signal_2.disconnect(video_thread.set_pan)
            except Exception:
                pass

            if video_thread.isRunning():
                video_thread.stop()
                video_thread.wait()

            self.video_thread_2 = None
            self.camera_2_active = False
            self.video_panel.clear_frame(channel=2)
            self.left_panel.set_channel_button_state(2, False)

    def start_camera(self, source_override=None):
        """
        Inicia la cámara del canal 1.
        """
        if self.camera_active:
            return

        if source_override is not None:
            source = source_override
        else:
            video_source = self.left_panel.video_combo.currentText()
            source = self._parse_video_source(video_source, canal=1)
            if source is None:
                return

        self._start_camera_on_channel(channel_id=1, source=source)

    def start_camera_2(self, source_override=None):
        """
        Inicia la cámara del canal 2.
        """
        if self.camera_2_active:
            return

        if source_override is not None:
            source = source_override
        else:
            video_source = self.left_panel.combo_cameras_2.currentText()
            source = self._parse_video_source(video_source, canal=2)
            if source is None:
                return

        self._start_camera_on_channel(channel_id=2, source=source)

    # =========================================================================
    # DETENCIÓN DE CÁMARAS
    # =========================================================================

    def stop_camera(self):
        """
        Detiene la cámara del canal 1 de forma segura.
        """
        self._stop_camera_on_channel(channel_id=1)

    def stop_camera_2(self):
        """
        Detiene la cámara del canal 2 de forma segura.
        """
        self._stop_camera_on_channel(channel_id=2)

    def on_stop_camera_requested(self):
        """
        Detiene la cámara si está activa.
        """
        if self.camera_active:
            self.stop_camera()

    # =========================================================================
    # MANEJO DE FRAMES Y TELEMETRÍA
    # =========================================================================

    def on_frame_ready(self, frame):
        """
        Recibe frame procesado del VideoThread (canal 1).
        """
        if self.is_closing or not self.camera_active:
            return

        self.video_panel.update_frame(frame, [], 0.0)
        self.video_panel.set_raw_frame(frame)

    def on_telemetry_update(self, fps, count):
        """
        Actualiza telemetría en el panel inferior (canal 1).
        """
        now = time.time()
        if now - self.last_fps_update_1 >= 0.5:
            self.bottom_panel.update_fps(fps)
            self.last_fps_update_1 = now

        self.bottom_panel.update_detections(count)

    def on_detection_log(self, message):
        """
        Maneja logs de detección del canal 1.
        """
        self.log_manager.add_log(f"[CH1] {message}", "INFO")

    def on_object_captured(self, capture_data):
        """
        Maneja capturas automáticas del VideoThread (canal 1).
        """
        self._handle_auto_capture(capture_data, channel_id=1)

    def on_connection_status(self, connected, message):
        """
        Maneja cambios de estado de conexión (canal 1).
        """
        if not connected:
            self.camera_active = False
            self.left_panel.set_channel_button_state(1, False)
            self.video_panel.clear_frame()

        if connected:
            self.show_toast("Cámara conectada")
        else:
            self.show_toast("Error de conexión")
            if self.left_panel.settings['alerts'].get('connection', True):
                self.play_alert_sound('connection')

    # -------------------------------------------------------------------------
    # MANEJO DE FRAMES CANAL 2
    # -------------------------------------------------------------------------

    def on_frame_ready_2(self, frame):
        """
        Recibe frame del canal 2.
        """
        if self.is_closing or not self.camera_2_active:
            return
        self.video_panel.update_frame(frame, [], 0.0, channel=2)

    def on_telemetry_update_2(self, fps, count):
        """
        Actualiza telemetría del canal 2 con retardo en FPS.
        """
        now = time.time()
        if now - self.last_fps_update_2 >= 0.5:
            self.bottom_panel.update_fps(fps)
            self.last_fps_update_2 = now

        self.bottom_panel.update_detections(count)

    def on_detection_log_2(self, message):
        """
        Logs del canal 2.
        """
        self.log_manager.add_log(f"[CH2] {message}", "INFO")

    def on_object_captured_2(self, capture_data):
        """
        Maneja capturas automáticas del canal 2.
        """
        self._handle_auto_capture(capture_data, channel_id=2)

    def on_connection_status_2(self, connected, message):
        """
        Estado de conexión del canal 2.
        """
        if not connected:
            self.camera_2_active = False
            self.left_panel.set_channel_button_state(2, False)
            self.video_panel.clear_frame(channel=2)

    # =========================================================================
    # CAPTURA AUTOMÁTICA
    # =========================================================================

    def _handle_auto_capture(self, capture_data, channel_id=1):
        """
        Procesa una captura automática de cualquier canal.
        """
        filename = Path(capture_data['path']).name
        object_type = capture_data['type'].lower()

        conf_str = capture_data.get('conf', '0%')
        try:
            confidence = float(conf_str.replace('%', ''))
        except Exception:
            confidence = 0.0

        counter = int(self.config.get('General', 'capture_counter', '0')) + 1
        self.config.set('General', 'capture_counter', str(counter))

        self.right_panel.captures_page.add_capture(
            None, filename, counter, [object_type], confidence
        )

        self.show_toast(f"Objetivo detectado: {capture_data['type']} #{capture_data['id']}")

        if self.left_panel.settings['alerts'].get('detection', True):
            self.play_alert_sound('detection')

    # =========================================================================
    # CAPTURA MANUAL
    # =========================================================================

    def on_capture_requested(self):
        """
        Captura el frame actual y lo guarda con detecciones.
        """
        self.log_manager.add_log("Captura manual solicitada", "INFO")
        if not self.camera_active or self.video_panel.current_frame is None:
            QMessageBox.warning(self, "Sin imagen", "No hay frame disponible para capturar.")
            return

        frame_to_save = self.video_panel.current_frame
        if frame_to_save is None:
            QMessageBox.warning(self, "Sin imagen", "No hay frame disponible para capturar.")
            return

        counter = int(self.config.get('General', 'capture_counter', '0')) + 1
        self.config.set('General', 'capture_counter', str(counter))

        detections = []
        if self.video_thread:
            detections = self.video_thread.get_current_detections()

        tipos_unicos = sorted(set(d['type'] for d in detections))
        confianza_maxima = max([d['conf'] for d in detections], default=0.0)

        sufijos = ''.join(f"_{t}" for t in tipos_unicos) if tipos_unicos else ""
        conf_int = int(confianza_maxima * 100)
        canal = getattr(self, 'active_camera', 1)
        filename = f"ch{canal}_{counter}{sufijos}_{conf_int}.jpg"

        save_path = Path(self.config.get('General', 'save_path', DEFAULT_SAVE_PATH))
        save_path.mkdir(parents=True, exist_ok=True)
        filepath = save_path / filename

        try:
            cv2.imwrite(str(filepath), frame_to_save)
        except Exception as e:
            self.log_manager.add_log(f"Error al guardar captura manual: {e}", "ERROR")
            QMessageBox.critical(self, "Error", f"No se pudo guardar la captura:\n{e}")
            return

        self.log_manager.add_log(f"Captura guardada: {filename}", "INFO")

        self.right_panel.captures_page.add_capture(
            frame_to_save, filename, counter, tipos_unicos,
            confianza_maxima * 100
        )

        self.show_toast(f"Captura guardada: {filename}")

    # =========================================================================
    # GESTIÓN DE YOLO
    # =========================================================================

    def on_yolo_toggle_changed(self, enabled):
        """
        Alterna la detección YOLO en ambos canales.
        """
        estado = "activada" if enabled else "desactivada"
        self.log_manager.add_log(f"Detección YOLO {estado}", "INFO")

        self.yolo_enabled = enabled
        self.title_bar.set_yolo_active(enabled)

        settings = self.left_panel.settings['detections']
        person_enabled = settings['person']['enabled']
        car_enabled = settings['car']['enabled']
        boat_enabled = settings['boat']['enabled']
        helicopter_enabled = settings['helicopter']['enabled']

        if enabled:
            targets = (person_enabled, car_enabled, boat_enabled, helicopter_enabled)
        else:
            targets = (False, False, False, False)

        if self.video_thread:
            self.video_thread.set_targets(*targets)

        if self.video_thread_2:
            self.video_thread_2.set_targets(*targets)

        self.sync_object_buttons()

    def on_yolo_quick_toggle(self):
        """
        Alterna YOLO desde el botón de la barra de título.
        """
        if self.yolo_loading:
            return

        self.yolo_enabled = not self.yolo_enabled

        self.left_panel.yolo_toggle.blockSignals(True)
        self.left_panel.yolo_toggle.setChecked(self.yolo_enabled)
        self.left_panel.yolo_toggle._animate(self.yolo_enabled)
        self.left_panel.yolo_toggle.update()
        self.left_panel.yolo_toggle.blockSignals(False)

        self.title_bar.set_yolo_active(self.yolo_enabled)

        self.on_yolo_toggle_changed(self.yolo_enabled)

    # =========================================================================
    # GESTIÓN DE CONFIGURACIÓN
    # =========================================================================

    def sync_object_buttons(self):
        """
        Sincroniza el estado visual de los botones de objetos en la barra de título.
        """
        if not hasattr(self.left_panel, 'settings'):
            return

        for obj_key in ['person', 'car', 'boat', 'helicopter']:
            enabled = self.left_panel.settings['detections'][obj_key]['enabled']
            self.title_bar.set_object_active(obj_key, enabled)

    def on_settings_changed(self, settings):
        """
        Actualiza la configuración de detección en VideoThread.
        """
        if self.yolo_enabled:
            targets = (
                settings['detections']['person']['enabled'],
                settings['detections']['car']['enabled'],
                settings['detections']['boat']['enabled'],
                settings['detections']['helicopter']['enabled']
            )
        else:
            targets = (False, False, False, False)

        if self.video_thread:
            self.video_thread.set_targets(*targets)

        if self.video_thread_2:
            self.video_thread_2.set_targets(*targets)

    def on_optics_changed(self, optics_dict):
        """
        Aplica la configuración óptica a los hilos de video activos.
        """
        if hasattr(self, '_last_performance') and self._last_performance != optics_dict['performance']:
            self.log_manager.add_log(f"Perfil de rendimiento cambiado a: {optics_dict['performance']}", "INFO")
        self._last_performance = optics_dict['performance']

        if hasattr(self, '_last_threads') and self._last_threads != optics_dict['threads']:
            self.log_manager.add_log(f"Hilos de CPU ajustados a {optics_dict['threads']}", "DEBUG")
        self._last_threads = optics_dict['threads']

        if self.video_thread:
            self.video_thread.set_optical_filters(optics_dict['clahe'])
            self.video_thread.set_zoom(optics_dict['zoom'], optics_dict['upscale'])
            self.video_thread.set_performance_mode(optics_dict['performance'])
            self.video_thread.set_cpu_resources(optics_dict['threads'])

        if self.video_thread_2:
            self.video_thread_2.set_optical_filters(optics_dict['clahe'])
            self.video_thread_2.set_zoom(optics_dict['zoom'], optics_dict['upscale'])
            self.video_thread_2.set_performance_mode(optics_dict['performance'])
            self.video_thread_2.set_cpu_resources(optics_dict['threads'])

    # =========================================================================
    # CONTROL DE ZOOM Y PANEO
    # =========================================================================

    def on_bottom_zoom_changed(self, value):
        """
        Maneja cambios en el slider de zoom.
        """
        zoom_level = value / 10.0
        self.bottom_panel.lbl_zoom_val.setText(f"{zoom_level:.1f}x")

        self.log_manager.add_log(f"Zoom ajustado a {zoom_level:.1f}x en canal {self.active_camera}", "DEBUG")

        if self.active_camera == 1:
            self.zoom_cam1 = zoom_level
            if self.video_thread:
                self.video_thread.set_zoom(zoom_level, self.left_panel.chk_upscale.isChecked())
        else:
            self.zoom_cam2 = zoom_level
            if self.video_thread_2:
                self.video_thread_2.set_zoom(zoom_level, self.left_panel.chk_upscale.isChecked())

    def zoom_in(self):
        """Atajo Ctrl++: Aumenta el zoom digital."""
        current_value = self.bottom_panel.slider_zoom.value()
        new_value = min(40, current_value + 2)
        self.bottom_panel.slider_zoom.setValue(new_value)

    def zoom_out(self):
        """Atajo Ctrl+-: Disminuye el zoom digital."""
        current_value = self.bottom_panel.slider_zoom.value()
        new_value = max(10, current_value - 2)
        self.bottom_panel.slider_zoom.setValue(new_value)

    def pan_zoom(self, dx, dy):
        """
        Ajusta el paneo del zoom.
        """
        if self.active_camera == 1 and self.video_thread:
            self.video_thread.set_pan(
                max(0, min(1, self.video_thread.pan_x + dx)),
                max(0, min(1, self.video_thread.pan_y + dy))
            )
        elif self.active_camera == 2 and self.video_thread_2:
            self.video_thread_2.set_pan(
                max(0, min(1, self.video_thread_2.pan_x + dx)),
                max(0, min(1, self.video_thread_2.pan_y + dy))
            )

        self.log_manager.add_log(f"Paneo ajustado en canal {self.active_camera}", "DEBUG")

    # =========================================================================
    # CIERRE DE LA APLICACIÓN
    # =========================================================================

    def closeEvent(self, event):
        """
        Maneja el cierre de la ventana.
        """
        if self.is_closing:
            event.accept()
            return

        try:
            self.config.set('General', 'camera_was_active', str(self.camera_active), save=False)
            self.config.set('General', 'video_source', self.left_panel.video_combo.currentText(), save=False)
            self.config.set('General', 'video_source_2', self.left_panel.combo_cameras_2.currentText(), save=False)
            self.config.set('General', 'left_panel_page', str(self.left_panel.current_index), save=False)
            self.config.set('General', 'right_panel_page', str(self.right_panel.current_index), save=False)
            self.config.set('General', 'left_panel_expanded', str(self.left_panel.is_expanded), save=False)
            self.config.set('General', 'right_panel_expanded', str(self.right_panel.is_expanded), save=False)
            self.config.set('General', 'yolo_enabled', str(self.yolo_enabled), save=False)
            self.config.set('General', 'dual_stream_enabled', str(self.dual_stream_enabled), save=False)
            self.config.set('General', 'rtsp_url_1', self.left_panel.input_rtsp_1.text(), save=False)
            self.config.set('General', 'rtsp_url_2', self.left_panel.input_rtsp_2.text(), save=False)
            self.config.save()
        except Exception as e:
            self.log_manager.add_log(f"Error guardando configuración: {e}", "ERROR")

        if self.video_thread is not None:
            try:
                self.video_thread.stop()
                self.video_thread.wait()
            except Exception as e:
                self.log_manager.add_log(f"Error deteniendo video_thread: {e}", "ERROR")
            finally:
                self.video_thread = None

        if self.video_thread_2 is not None:
            try:
                self.video_thread_2.stop()
                self.video_thread_2.wait()
            except Exception as e:
                self.log_manager.add_log(f"Error deteniendo video_thread_2: {e}", "ERROR")
            finally:
                self.video_thread_2 = None

        try:
            self.log_manager.add_log("Aplicación cerrada por el usuario", "INFO")
        except Exception:
            pass

        if hasattr(self.bottom_panel, 'timer'):
            self.bottom_panel.timer.stop()

        event.accept()

    # =========================================================================
    # MÉTODOS PARA RTSP Y VIDEO LOCAL
    # =========================================================================

    def on_connect_rtsp(self, url, canal):
        """
        Conecta a un stream RTSP en el canal indicado.
        """
        url = url.strip()
        if not url:
            QMessageBox.warning(self, "URL vacía", "Introduce una dirección RTSP válida.")
            return

        self.log_manager.add_log(f"Conexión RTSP solicitada en canal {canal}: {url}", "INFO")

        if canal == 1:
            self._start_camera_on_channel(channel_id=1, source=url)
        elif canal == 2:
            self._start_camera_on_channel(channel_id=2, source=url)

    def on_load_video(self, canal):
        """
        Abre un diálogo para seleccionar un archivo de video local.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar video",
            "",
            "Video Files (*.mp4 *.avi *.mkv *.mov)"
        )
        if not file_path:
            return

        self.log_manager.add_log(f"Carga de video local solicitada en canal {canal}: {file_path}", "INFO")

        if canal == 1:
            self._start_camera_on_channel(channel_id=1, source=file_path)
        elif canal == 2:
            self._start_camera_on_channel(channel_id=2, source=file_path)

    def _parse_video_source(self, video_source, canal=1):
        """
        Convierte el texto del combo en una fuente usable por OpenCV.
        """
        if not video_source:
            return None

        if video_source.startswith(("rtsp://", "http://", "https://", "udp://")):
            return video_source
        if Path(video_source).exists():
            return video_source

        if "Puerto" in video_source:
            try:
                return int(video_source.split("Puerto ")[1].replace(")", ""))
            except Exception:
                QMessageBox.warning(self, "Error", f"No se pudo determinar el ID de la cámara {canal}.")
                return None

        elif "Cámara Local" in video_source:
            try:
                return int(video_source.split("(")[1].split(")")[0])
            except Exception:
                QMessageBox.warning(self, "Error", f"No se pudo determinar el ID de la cámara {canal}.")
                return None

        return video_source

    def _create_video_thread(self, source, channel_id):
        """
        Crea y configura un VideoThread con la configuración actual de la UI.
        """
        save_path = Path(self.config.get('General', 'save_path', DEFAULT_SAVE_PATH))
        save_path.mkdir(parents=True, exist_ok=True)

        thread = VideoThread(
            source=source,
            cpu_threads=4,
            save_dir=str(save_path),
            channel_id=channel_id
        )

        # Configurar estado inicial del OCR en el hilo recién creado (Comprobación segura)
        ocr_active = self.left_panel.settings.get('ocr_enabled', False)
        if hasattr(thread, 'set_ocr_enabled'):
            thread.set_ocr_enabled(ocr_active)

        # Aplicar configuración óptica
        thread.set_optical_filters(self.left_panel.chk_clahe.isChecked())
        thread.set_zoom(
            self.bottom_panel.slider_zoom.value() / 10.0,
            self.left_panel.chk_upscale.isChecked()
        )
        thread.set_performance_mode(self.left_panel.combo_perf.currentText())
        thread.set_cpu_resources(self.left_panel.spin_threads.value())

        # Configurar objetivos según YOLO
        if self.yolo_enabled:
            detections = self.left_panel.settings['detections']
            person_enabled = detections.get('person', {}).get('enabled', True)
            car_enabled = detections.get('car', {}).get('enabled', True)
            boat_enabled = detections.get('boat', {}).get('enabled', True)
            helicopter_enabled = detections.get('helicopter', {}).get('enabled', False)
        else:
            person_enabled = False
            car_enabled = False
            boat_enabled = False
            helicopter_enabled = False

        thread.set_targets(
            person_enabled,
            car_enabled,
            boat_enabled,
            helicopter_enabled
        )

        return thread

    # =========================================================================
    # MÉTODOS DE UI Y UTILIDADES
    # =========================================================================

    def setup_ui(self):
        """
        Configura el layout principal con paneles laterales y panel inferior.
        """
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self.title_bar)

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self.left_container = QWidget()
        self.left_container.setFixedWidth(LEFT_PANEL_WIDTH)
        left_layout = QVBoxLayout(self.left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.left_panel)
        top_layout.addWidget(self.left_container)

        video_right_layout = QHBoxLayout()
        video_right_layout.setContentsMargins(0, 0, 0, 0)
        video_right_layout.setSpacing(0)
        video_right_layout.addWidget(self.video_panel, 1)

        self.right_container = QWidget()
        self.right_container.setFixedWidth(RIGHT_PANEL_WIDTH)
        right_layout = QVBoxLayout(self.right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.right_panel)
        video_right_layout.addWidget(self.right_container, 0)

        top_layout.addLayout(video_right_layout, 1)
        main_layout.addLayout(top_layout, 1)

        self.bottom_panel.setFixedHeight(36)
        main_layout.addWidget(self.bottom_panel, 0)

    def apply_styles(self):
        """
        Aplica los estilos globales desde el archivo styles.qss.
        """
        style_path = Path(__file__).parent.parent / "styles.qss"
        if style_path.exists():
            with style_path.open('r', encoding='utf-8') as f:
                QApplication.instance().setStyleSheet(f.read())
        else:
            self.log_manager.add_log(f"No se encontró archivo de estilos: {style_path}", "WARNING")

    def show_shortcuts_dialog(self):
        """
        Abre el diálogo de atajos de teclado (modal).
        """
        dialog = ShortcutsDialog(self)
        dialog.exec()

    def open_inspector_shortcut(self):
        """
        Atajo Ctrl+Shift+I: Abre inspector de capturas.
        """
        if hasattr(self.right_panel, 'captures_page'):
            self.right_panel.captures_page.open_inspector()

    def on_objeto_toggle_requested(self, obj_key):
        """
        Alterna la detección de un objeto desde la barra de título.
        """
        if not hasattr(self.left_panel, 'det_widgets'):
            return

        widget = self.left_panel.det_widgets.get(obj_key)
        if not widget:
            return

        switch = widget['switch']
        nuevo_estado = not switch.isChecked()
        switch.setChecked(nuevo_estado)

        self.title_bar.set_object_active(obj_key, nuevo_estado)

    def toggle_person_detection(self):
        """Atajo Ctrl+3: Alterna detección de personas."""
        self.on_objeto_toggle_requested('person')

    def toggle_car_detection(self):
        """Atajo Ctrl+4: Alterna detección de carros."""
        self.on_objeto_toggle_requested('car')

    def toggle_boat_detection(self):
        """Atajo Ctrl+5: Alterna detección de botes."""
        self.on_objeto_toggle_requested('boat')

    def toggle_helicopter_detection(self):
        """Atajo Ctrl+6: Alterna detección de helicópteros."""
        self.on_objeto_toggle_requested('helicopter')

    def on_video_source_changed(self, video_source):
        """
        Guarda la fuente seleccionada y detiene la cámara si está activa.
        """
        self.log_manager.add_log(f"Fuente de video cambiada a: {video_source}", "INFO")

        if self.camera_active:
            self.stop_camera()

    def restore_panel_state(self):
        """
        Restaura las páginas activas y estado de expansión de los paneles.
        """
        try:
            left_page = self.config.getint('General', 'left_panel_page', 0)
            if 0 <= left_page < self.left_panel.stacked_widget.count():
                self.left_panel.stacked_widget.setCurrentIndex(left_page)
                self.left_panel.current_index = left_page
                for i, btn in enumerate(self.left_panel.nav_buttons.values()):
                    btn.setChecked(i == left_page)

            right_page = self.config.getint('General', 'right_panel_page', 0)
            if 0 <= right_page < self.right_panel.stacked_widget.count():
                self.right_panel.stacked_widget.setCurrentIndex(right_page)
                self.right_panel.current_index = right_page
                buttons = self.right_panel.nav_button_group.buttons()
                for i, btn in enumerate(buttons):
                    btn.setChecked(i == right_page)

            left_expanded = self.config.getboolean('General', 'left_panel_expanded', True)
            if left_expanded != self.left_panel.is_expanded:
                self.on_toggle_left_panel(left_expanded)
                self.left_panel.is_expanded = left_expanded

            right_expanded = self.config.getboolean('General', 'right_panel_expanded', True)
            if right_expanded != self.right_panel.is_expanded:
                self.on_toggle_right_panel(right_expanded)
                self.right_panel.is_expanded = right_expanded
                self.right_panel.stacked_widget.setVisible(right_expanded)

        except Exception as e:
            print(f"Error restaurando estado de paneles: {e}")