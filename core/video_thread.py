# =============================================================================
# MÓDULO DE INGESTA DE VIDEO, INFERENCIA Y SEGUIMIENTO TÁCTICO
# =============================================================================
# Este módulo implementa un hilo de procesamiento de video en tiempo real que:
# 1. Captura frames desde una fuente (cámara local, RTSP, etc.)
# 2. Aplica mejoras visuales (zoom, CLAHE, nitidez, superresolución)
# 3. Ejecuta inferencia YOLO con seguimiento BoT-SORT
# 4. Implementa un sistema de memoria biométrica triple (HOG + HSV + ORB)
#    para reidentificar objetivos que salen y vuelven a entrar en escena
# 5. Genera capturas tácticas automáticas de objetivos nuevos
# 6. Emite señales para actualizar la UI, logs y telemetría
#
# DEPENDENCIAS:
# - OpenCV (cv2): Captura de video, procesamiento de imágenes, HOG, ORB
# - PyTorch (torch): Configuración de hilos CPU para inferencia
# - Ultralytics (YOLO): Modelo de detección y seguimiento
# - NumPy (np): Operaciones numéricas y vectores de características
# - PySide6: QThread y señales para comunicación con la UI
# =============================================================================

# =============================================================================
# IMPORTS ESTÁNDAR Y DE TERCEROS
# =============================================================================
import cv2  # OpenCV: captura y procesamiento de video
from pathlib import Path  # Manejo de rutas de archivos
import time  # Control de FPS y timestamps
import torch  # PyTorch: configuración de CPU
import datetime  # Timestamps para capturas y HUD
import numpy as np  # Operaciones numéricas y vectores

# =============================================================================
# IMPORTS DE QT
# =============================================================================
from PySide6.QtCore import QThread, Signal, Slot

# =============================================================================
# IMPORTS DE YOLO
# =============================================================================
from ultralytics import YOLO  # Modelo de detección y seguimiento


class VideoThread(QThread):
    """
    Hilo de procesamiento de video con detección YOLO y memoria biométrica.

    Esta clase extiende QThread para ejecutar el bucle de captura y procesamiento
    en un hilo separado, evitando bloquear la interfaz de usuario. Utiliza el
    modelo YOLOv8n con seguimiento BoT-SORT para detectar y rastrear objetivos,
    y un sistema de reidentificación basado en características visuales
    (HOG, HSV y ORB) para mantener identidades estables a lo largo del tiempo.

    Características principales:
    - Captura de video desde cámara, RTSP o archivo
    - Mejoras visuales: zoom digital, CLAHE, nitidez, superresolución
    - Detección y seguimiento con YOLO + BoT-SORT
    - Memoria biométrica para reidentificación (HOG + HSV + ORB)
    - Capturas tácticas automáticas de objetivos nuevos
    - Telemetría en tiempo real (FPS, conteo de detecciones)
    - HUD con hora y uptime del sistema
    """

    # =========================================================================
    # SEÑALES EMITIDAS HACIA LA UI PRINCIPAL
    # =========================================================================

    # Señal unificada de log: (mensaje, nivel)
    log_signal = Signal(str, str)

    # Frame procesado listo para mostrar en el panel de video
    change_pixmap_signal = Signal(np.ndarray)

    # Telemetría: (FPS actual, número de detecciones)
    telemetry_signal = Signal(float, int)

    # Mensaje de log para el panel de logs
    detection_log_signal = Signal(str)

    # Datos de una captura táctica (dict con id, tipo, confianza, ruta)
    object_captured_signal = Signal(dict)

    # Estado de conexión: (conectado, mensaje descriptivo)
    connection_status_signal = Signal(bool, str)

    # =========================================================================
    # INICIALIZACIÓN DEL HILO
    # =========================================================================

    def __init__(self, source=0, conf_threshold=0.5, cpu_threads=4, save_dir=None, channel_id=1):
        """
        Inicializa el hilo de video con la configuración especificada.

        Args:
            source: Fuente de video (índice de cámara, URL RTSP o ruta de archivo).
            conf_threshold: Umbral de confianza mínimo para detecciones (0-1).
            cpu_threads: Número de hilos de CPU a utilizar.
            save_dir: Carpeta donde guardar capturas tácticas.
            channel_id: Identificador del canal (1 o 2 para dual stream).
        """
        super().__init__()

        # =====================================================================
        # CONFIGURACIÓN BÁSICA
        # =====================================================================
        self.source = source  # Fuente de video (int o str)
        self.conf_threshold = conf_threshold  # Umbral de confianza YOLO
        self._is_running = True  # Bandera de ejecución del hilo
        self.channel_id = channel_id  # ID del canal (1 o 2)

        # =====================================================================
        # ESTADO DEL MÓDULO ÓPTICO (mejoras visuales)
        # =====================================================================
        self.filter_clahe = False  # Mejora de contraste y nitidez
        self.zoom_level = 1.0  # Zoom digital (1.0 = sin zoom)
        self.ai_upscale = False  # Superresolución AI (costosa en CPU)

        # =====================================================================
        # COORDENADAS TÁCTICAS DE PAN/ZOOM (seguimiento del cursor)
        # =====================================================================
        self.pan_x = 0.5  # Centro horizontal normalizado (0-1)
        self.pan_y = 0.5  # Centro vertical normalizado (0-1)

        # =====================================================================
        # CONFIGURACIÓN DE CPU Y MODELO YOLO
        # =====================================================================
        self.set_cpu_resources(cpu_threads)  # Configurar hilos CPU
        self.model = YOLO("modelos/yolov8n.pt")  # Cargar modelo preentrenado

        # Log de depuración: modelo cargado
        self.log_signal.emit("Modelo YOLO cargado: modelos/yolov8n.pt", "DEBUG")

        # =====================================================================
        # FILTROS DE OBJETIVOS (por tipo específico)
        # =====================================================================
        self.filters = {
            'person': True,  # clase 0: personas
            'car': True,  # clases 2,3,5,7: vehículos terrestres
            'boat': True,  # clase 8: botes
            'helicopter': False  # clase 4: airplane (aproximación)
        }

        # =====================================================================
        # REGISTRO DE IDENTIDADES
        # =====================================================================
        self.logged_ids = set()  # IDs ya registrados (evitar duplicados)
        self.current_detections = []  # Detecciones del último frame

        # =====================================================================
        # BANCO DE MEMORIA TRIPLE (HOG + HSV + ORB + Aspect Ratio)
        # =====================================================================
        self.appearance_memory = {}  # Firmas biométricas por ID real
        self.id_mapping = {}  # Mapeo: YOLO ID -> ID real reidentificado

        # =====================================================================
        # OPTIMIZACIÓN DE CPU: Control de extracción biométrica
        # =====================================================================
        self.frame_count = 0  # Contador global de frames

        # Control de FPS bajo sostenido
        self.low_fps_start_time = None  # Momento en que comenzó el FPS bajo
        self.low_fps_warning_emitted = False  # Evitar múltiples warnings

        self.last_extraction_frame = {}  # Último frame de extracción por ID

        # =====================================================================
        # DESCRIPTORES Y EXTRACTORES DE CARACTERÍSTICAS
        # =====================================================================
        # Descriptor HOG para forma geométrica
        self.hog_descriptor = cv2.HOGDescriptor(
            (64, 128),  # Tamaño de ventana
            (16, 16),  # Tamaño de bloque
            (8, 8),  # Desplazamiento de bloque
            (8, 8),  # Tamaño de celda
            9  # Número de bins de orientación
        )

        # Extractor ORB para texturas y detalles
        self.orb = cv2.ORB_create(nfeatures=150)

        # Matcher para comparar descriptores ORB
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

        # =====================================================================
        # DIRECTORIO DE CAPTURAS TÁCTICAS
        # =====================================================================
        self.save_dir = Path(save_dir) if save_dir else Path("capturas")
        self.save_dir.mkdir(parents=True, exist_ok=True)

        # =====================================================================
        # PARÁMETROS DE INFERENCIA Y TELEMETRÍA
        # =====================================================================
        self.imgsz = 256  # Resolución de inferencia YOLO
        self.start_time_uptime = None  # Timestamp de inicio (para uptime)

    # =========================================================================
    # MÉTODOS AUXILIARES DE VISUALIZACIÓN
    # =========================================================================

    def _get_source_display_name(self, source) -> str:
        """
        Devuelve un nombre descriptivo para la fuente de video.

        Args:
            source: Fuente original (int para cámara local, str para RTSP/archivo).

        Returns:
            String con nombre descriptivo.
        """
        if isinstance(source, int):
            # Intentar obtener nombre desde la configuración guardada
            try:
                from core.config_manager import ConfigManager
                config = ConfigManager()
                cameras = config.get_camera_list()
                if cameras and source < len(cameras):
                    return cameras[source]
            except Exception:
                pass
            return f"Cámara Local ({source})"
        else:
            # Para RTSP o archivo, devolver la ruta o URL
            return f"Sensor [{source}]"

    # =========================================================================
    # MÉTODOS DE CONFIGURACIÓN EN TIEMPO DE EJECUCIÓN
    # =========================================================================

    def set_cpu_resources(self, threads: int):
        """
        Configura el número de hilos de CPU para PyTorch y OpenCV.

        Args:
            threads: Número de hilos a utilizar (1-16).
        """
        try:
            torch.set_num_threads(threads)
            cv2.setNumThreads(threads)
        except Exception:
            pass  # Si falla, se mantiene la configuración por defecto

    def set_performance_mode(self, mode: str):
        """
        Ajusta la resolución de inferencia según el modo de rendimiento.

        Args:
            mode: String con el nombre del perfil:
                  - "Minimo (Ahorro CPU)": imgsz=160, rápido
                  - "Balanceado (Estandar)": imgsz=256, equilibrado
                  - "Exigente / Maxima Precision": imgsz=320, lento
        """
        if "Minimo" in mode:
            self.imgsz = 160
        elif "Balanceado" in mode:
            self.imgsz = 256
        elif "Exigente" in mode:
            self.imgsz = 320

    def set_targets(self, person: bool = True, car: bool = True, boat: bool = True, helicopter: bool = False):
        """
        Configura qué tipos de objetos se detectarán.

        Args:
            person: Detectar personas (clase COCO 0).
            car: Detectar coches y vehículos (clases COCO 2,3,5,7).
            boat: Detectar botes (clase COCO 8).
            helicopter: Detectar helicópteros (aproximación con clase 4).
        """
        self.filters['person'] = person
        self.filters['car'] = car
        self.filters['boat'] = boat
        self.filters['helicopter'] = helicopter

    def set_optical_filters(self, clahe: bool):
        """
        Activa o desactiva el filtro CLAHE + nitidez.

        Args:
            clahe: True para activar mejora de contraste.
        """
        self.filter_clahe = clahe

    def set_zoom(self, level: float, upscale: bool):
        """
        Configura el zoom digital y la superresolución.

        Args:
            level: Nivel de zoom (1.0 = sin zoom, >1.0 = acercamiento).
            upscale: True para activar superresolución AI.
        """
        self.zoom_level = level
        self.ai_upscale = upscale

    @Slot(float, float)
    def set_pan(self, x: float, y: float):
        """
        Recibe coordenadas normalizadas del cursor para dirigir el zoom.

        Args:
            x: Posición horizontal normalizada (0-1).
            y: Posición vertical normalizada (0-1).
        """
        self.pan_x = x
        self.pan_y = y

    # =========================================================================
    # MEJORA VISUAL DE FRAMES
    # =========================================================================

    def enhance_frame(self, frame):
        """
        Aplica mejoras visuales al frame: zoom, CLAHE, nitidez y superresolución.

        Args:
            frame: Imagen OpenCV en formato BGR.

        Returns:
            Frame procesado con las mejoras aplicadas.
        """
        # =====================================================================
        # 1. ZOOM DIGITAL CON SEGUIMIENTO DEL CURSOR
        # =====================================================================
        if self.zoom_level > 1.0:
            h, w = frame.shape[:2]
            new_h = int(h / self.zoom_level)
            new_w = int(w / self.zoom_level)

            # Calcular centro del zoom basado en posición del cursor (pan)
            center_x = int(w * self.pan_x)
            center_y = int(h * self.pan_y)

            # Recortar región de interés con límites seguros
            x1 = max(0, min(w - new_w, center_x - new_w // 2))
            y1 = max(0, min(h - new_h, center_y - new_h // 2))
            x2 = x1 + new_w
            y2 = y1 + new_h

            # Aplicar zoom y redimensionar al tamaño original
            crop = frame[y1:y2, x1:x2]
            frame = cv2.resize(crop, (w, h), interpolation=cv2.INTER_LANCZOS4)

            # Superresolución AI (solo si está activada; consume mucha CPU)
            if self.ai_upscale:
                frame = cv2.detailEnhance(frame, sigma_s=10, sigma_r=0.15)

        # =====================================================================
        # 2. MEJORA CLAHE + NITIDEZ GLOBAL
        # =====================================================================
        if self.filter_clahe:
            # Convertir a espacio LAB para ecualizar solo el canal de luminosidad
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)

            # Aplicar CLAHE (ecualización adaptativa de histograma)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)

            # Recombinar canales y volver a BGR
            frame = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)

            # Aplicar filtro de nitidez (kernel de realce de bordes)
            kernel = np.array([[0, -1, 0],
                               [-1, 5, -1],
                               [0, -1, 0]])
            frame = cv2.filter2D(frame, -1, kernel)

        return frame

    # =========================================================================
    # SISTEMA DE MEMORIA BIOMÉTRICA TRIPLE
    # =========================================================================
    # Este sistema combina tres tipos de características visuales para crear
    # una "firma" única por objetivo, permitiendo reidentificarlo aunque YOLO
    # le asigne un ID diferente (por oclusión, salida de escena, etc.)
    #
    # Las tres características son:
    # 1. COLOR (HSV): Histograma de tono y saturación (resistente a sombras)
    # 2. FORMA (HOG): Histograma de gradientes orientados (geometría del cuerpo)
    # 3. TEXTURA (ORB): Puntos clave y descriptores (detalles finos)
    #
    # Además se usa el ASPECT RATIO (relación ancho/alto) como filtro rápido
    # para descartar candidatos imposibles antes de comparar firmas completas.
    # =========================================================================

    def extract_signature(self, crop):
        """
        Extrae la firma biométrica de un recorte de imagen.

        Combina tres tipos de características para crear una identidad visual
        robusta ante cambios de iluminación, ángulo y distancia.

        Args:
            crop: Recorte del objetivo en formato BGR.

        Returns:
            Diccionario con claves:
            - 'color': Histograma HSV normalizado
            - 'shape': Vector HOG normalizado
            - 'aspect_ratio': Relación ancho/alto
            - 'orb_des': Descriptores ORB (o None si no hay puntos)
        """
        h, w = crop.shape[:2]
        aspect_ratio = float(w) / float(max(h, 1))

        # =====================================================================
        # 1. FIRMA DE COLOR (HSV)
        # =====================================================================
        # Usar HSV porque separa luminosidad de cromaticidad, haciendo la
        # firma más resistente a cambios de iluminación.
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # Ecualizar el canal de brillo (V) para normalizar iluminación
        hsv[:, :, 2] = cv2.equalizeHist(hsv[:, :, 2])

        # Calcular histograma 2D de tono (H) y saturación (S)
        color_hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])

        # Normalizar para que la suma sea 1 (independiente del tamaño del crop)
        cv2.normalize(color_hist, color_hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

        # =====================================================================
        # 2. FIRMA DE GEOMETRÍA (HOG - Histogram of Oriented Gradients)
        # =====================================================================
        # HOG captura la forma y estructura del objeto (silueta, postura)
        # Redimensionar a tamaño estándar para HOG
        resized_for_hog = cv2.resize(crop, (64, 128))

        # Calcular descriptor HOG
        hog_features = self.hog_descriptor.compute(resized_for_hog)
        hog_features = hog_features.flatten()

        # Normalizar para que tenga norma unitaria (invariante a escala)
        if np.linalg.norm(hog_features) > 0:
            hog_features = hog_features / np.linalg.norm(hog_features)

        # =====================================================================
        # 3. FIRMA DE TEXTURAS Y DETALLES (ORB)
        # =====================================================================
        # ORB detecta puntos clave y sus descriptores, capturando texturas
        # y detalles finos (ropa, colores específicos, patrones)

        # Convertir a escala de grises
        gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        # Aplicar CLAHE "microscópico" para mejorar contraste local
        clahe_micro = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        gray_crop = clahe_micro.apply(gray_crop)

        # Detectar puntos clave y computar descriptores
        kp, des = self.orb.detectAndCompute(gray_crop, None)

        return {
            'color': color_hist,  # Histograma HSV 50x60
            'shape': hog_features,  # Vector HOG normalizado
            'aspect_ratio': aspect_ratio,  # Relación ancho/alto
            'orb_des': des  # Descriptores ORB (puede ser None)
        }

    def get_true_id(self, yolo_id, crop, threshold=0.70):
        """
        Determina la identidad real de un objetivo usando memoria biométrica.

        Si el objetivo ya fue visto antes, actualiza su firma y devuelve el ID
        real. Si es nuevo, busca coincidencias con el banco de memoria.

        Flujo de decisión:
        1. Si el crop es inválido, usar el YOLO ID directamente.
        2. Si el YOLO ID ya está mapeado, actualizar firma y retornar ID real.
        3. Si es un ID nuevo, comparar con memoria y buscar coincidencia.
        4. Si hay coincidencia fuerte, fusionar identidades.
        5. Si no hay coincidencia, registrar como nuevo objetivo.

        Args:
            yolo_id: ID asignado por el tracker YOLO.
            crop: Recorte del objetivo en formato BGR.
            threshold: Puntaje mínimo de similitud (0-1) para considerar match.

        Returns:
            ID real del objetivo (reidentificado o nuevo).
        """
        # =====================================================================
        # VALIDACIÓN DEL CROP
        # =====================================================================
        # Rechazar recortes demasiado pequeños o vacíos
        if crop is None or crop.size == 0 or crop.shape[0] < 20 or crop.shape[1] < 20:
            return self.id_mapping.get(yolo_id, yolo_id)

        # Extraer firma actual
        try:
            current_sig = self.extract_signature(crop)
        except Exception:
            # Si falla la extracción, usar YOLO ID como fallback
            return self.id_mapping.get(yolo_id, yolo_id)

        # =====================================================================
        # CASO 1: EL YOLO ID YA ESTÁ MAPEADO A UN ID REAL
        # =====================================================================
        if yolo_id in self.id_mapping:
            true_id = self.id_mapping[yolo_id]
            past_sig = self.appearance_memory[true_id]['signature']

            # Actualizar firma con promedio ponderado (70% pasado, 30% actual)
            # Esto permite adaptación gradual a cambios de iluminación/ángulo
            updated_color = (past_sig['color'] * 0.7) + (current_sig['color'] * 0.3)
            updated_shape = (past_sig['shape'] * 0.7) + (current_sig['shape'] * 0.3)
            updated_ratio = (past_sig['aspect_ratio'] * 0.7) + (current_sig['aspect_ratio'] * 0.3)

            # Conservar la mejor descripción ORB (la que tenga más puntos)
            if (current_sig['orb_des'] is not None and
                    past_sig['orb_des'] is not None and
                    len(current_sig['orb_des']) > len(past_sig['orb_des'])):
                best_orb = current_sig['orb_des']
            else:
                best_orb = past_sig['orb_des']

            # Guardar firma actualizada
            self.appearance_memory[true_id]['signature'] = {
                'color': updated_color,
                'shape': updated_shape,
                'aspect_ratio': updated_ratio,
                'orb_des': best_orb
            }
            return true_id

        # =====================================================================
        # CASO 2: BUSCAR COINCIDENCIA EN EL BANCO DE MEMORIA
        # =====================================================================
        best_match_id = None
        highest_score = 0.0

        # Recorrer todos los objetivos conocidos
        for past_id, data in self.appearance_memory.items():
            past_sig = data['signature']

            # ----------------------------------------------------------------
            # FILTRO RÁPIDO: Rechazo por diferencia de aspecto
            # ----------------------------------------------------------------
            # Evita comparaciones innecesarias con objetos de forma muy diferente
            ratio_diff = abs(current_sig['aspect_ratio'] - past_sig['aspect_ratio'])
            if ratio_diff > 1.2:
                continue  # Diferencia de aspecto demasiado grande, saltar

            # ----------------------------------------------------------------
            # COMPARACIÓN 1: COLOR (correlación de histogramas HSV)
            # ----------------------------------------------------------------
            # HISTCMP_CORREL: 1 = perfecto, 0 = sin correlación, -1 = inverso
            color_score = cv2.compareHist(
                current_sig['color'],
                past_sig['color'],
                cv2.HISTCMP_CORREL
            )
            color_score = max(0, color_score)  # Ignorar correlación negativa

            # ----------------------------------------------------------------
            # COMPARACIÓN 2: FORMA ESTRUCTURAL (producto punto de HOG)
            # ----------------------------------------------------------------
            # Producto punto: 1 = vectores idénticos, 0 = ortogonales
            shape_score = np.dot(current_sig['shape'], past_sig['shape'])

            # ----------------------------------------------------------------
            # COMPARACIÓN 3: TEXTURA ORB (número de coincidencias)
            # ----------------------------------------------------------------
            orb_score = 0.0
            if current_sig['orb_des'] is not None and past_sig['orb_des'] is not None:
                # Encontrar coincidencias entre descriptores
                matches = self.matcher.match(current_sig['orb_des'], past_sig['orb_des'])
                # Normalizar: 12 coincidencias = score máximo (1.0)
                orb_score = min(1.0, len(matches) / 12.0)

            # ----------------------------------------------------------------
            # PUNTAJE HÍBRIDO
            # ----------------------------------------------------------------
            # Ponderación: 45% textura (ORB), 35% forma (HOG), 20% color (HSV)
            # La textura tiene más peso porque es más discriminativa
            total_score = (shape_score * 0.35) + (orb_score * 0.45) + (color_score * 0.20)

            # Actualizar mejor coincidencia si supera el máximo actual
            if total_score > highest_score:
                highest_score = total_score
                best_match_id = past_id

        # =====================================================================
        # SI HAY COINCIDENCIA FUERTE, FUSIONAR IDENTIDADES
        # =====================================================================
        if best_match_id is not None and highest_score > threshold:
            # Mapear YOLO ID al ID real existente
            self.id_mapping[yolo_id] = best_match_id
            past_sig = self.appearance_memory[best_match_id]['signature']

            # Fusionar firmas con promedio 50/50 (mayor adaptación)
            updated_color = (past_sig['color'] * 0.5) + (current_sig['color'] * 0.5)
            updated_shape = (past_sig['shape'] * 0.5) + (current_sig['shape'] * 0.5)
            updated_ratio = (past_sig['aspect_ratio'] * 0.5) + (current_sig['aspect_ratio'] * 0.5)

            # Conservar mejor ORB
            if (current_sig['orb_des'] is not None and
                    past_sig['orb_des'] is not None and
                    len(current_sig['orb_des']) > len(past_sig['orb_des'])):
                best_orb = current_sig['orb_des']
            else:
                best_orb = past_sig['orb_des']

            # Guardar firma fusionada
            self.appearance_memory[best_match_id]['signature'] = {
                'color': updated_color,
                'shape': updated_shape,
                'aspect_ratio': updated_ratio,
                'orb_des': best_orb
            }
            return best_match_id

            # Log de reidentificación exitosa (solo DEBUG, no es crítico)
            self.log_signal.emit(
                f"Reidentificación: YOLO ID {yolo_id} -> Real ID {best_match_id} (score: {highest_score:.2f})",
                "DEBUG"
            )

        # =====================================================================
        # CASO 3: NUEVO OBJETIVO (REGISTRAR EN MEMORIA)
        # =====================================================================
        # No hay coincidencia suficiente, registrar como identidad nueva
        self.id_mapping[yolo_id] = yolo_id
        self.appearance_memory[yolo_id] = {'signature': current_sig}
        return yolo_id

    # =========================================================================
    # BUCLE PRINCIPAL DE PROCESAMIENTO DE VIDEO
    # =========================================================================

    def run(self):
        """
        Ejecuta el bucle principal de captura y procesamiento de video.

        Este método se ejecuta automáticamente al iniciar el hilo. El flujo es:
        1. Abrir fuente de video (cámara, RTSP o archivo)
        2. Verificar conexión y emitir señal de estado
        3. Bucle principal:
           a. Capturar frame
           b. Aplicar mejoras visuales (zoom, CLAHE, nitidez)
           c. Ejecutar YOLO con seguimiento BoT-SORT
           d. Procesar detecciones y aplicar memoria biométrica
           e. Generar capturas tácticas de objetivos nuevos
           f. Dibujar bounding boxes, etiquetas y HUD
           g. Emitir señales (frame, telemetría, logs)
        4. Liberar recursos al terminar
        """

        # =====================================================================
        # 1. ABRIR FUENTE DE VIDEO
        # =====================================================================
        # Para cámara local, usar CAP_DSHOW (más rápido en Windows)
        # Para RTSP/archivo, usar el método por defecto
        if isinstance(self.source, int):
            cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(self.source)

        # Verificar si la fuente se abrió correctamente
        if not cap.isOpened():
            self.connection_status_signal.emit(
                False,
                f"ERROR: No se pudo conectar a la fuente [{self.source}]."
            )
            # Emitir log unificado
            self.log_signal.emit(
                f"No se pudo conectar a la fuente [{self.source}].",
                "ERROR"
            )
            return

        # Emitir señal de conexión exitosa
        source_name = self._get_source_display_name(self.source) # Obtener nombre descriptivo de la fuente si es cámara local
        self.connection_status_signal.emit(
            True,
            f"{source_name} en línea. Transmitiendo video..."
        )
        # Emitir log unificado con prefijo de canal
        self.log_signal.emit(
            f"[CH{self.channel_id}] {source_name} en línea. Transmitiendo video...",
            "INFO"
        )

        # Registrar tiempo de inicio para el HUD de uptime
        self.start_time_uptime = time.time()

        # =====================================================================
        # 2. CONTROL DE FPS
        # =====================================================================
        # Limitar a 24 FPS para evitar saturar la CPU
        target_fps = 24
        frame_time_limit = 1.0 / target_fps

        # =====================================================================
        # 3. BUCLE PRINCIPAL
        # =====================================================================
        self.log_signal.emit("Iniciando bucle de captura...", "DEBUG")
        while self._is_running and cap.isOpened():
            # Marcar tiempo de inicio del ciclo (para control de FPS)
            loop_start_time = time.time()

            # Marcar tick de OpenCV (para cálculo preciso de FPS)
            start_tick = cv2.getTickCount()

            # Capturar frame
            ret, frame = cap.read()

            # Incrementar contador global de frames
            self.frame_count += 1

            if ret:
                # =============================================================
                # A. PREPROCESAMIENTO VISUAL
                # =============================================================
                # Aplicar zoom, CLAHE, nitidez y superresolución según config
                frame = self.enhance_frame(frame)

                # =============================================================
                # B. INFERENCIA YOLO CON SEGUIMIENTO BoT-SORT
                # =============================================================
                # El parámetro persist=True mantiene IDs entre frames
                # El tracker "botsort.yaml" es el más preciso disponible
                results = self.model.track(
                    frame,
                    persist=True,
                    tracker="botsort.yaml",
                    verbose=False,
                    conf=self.conf_threshold,
                    imgsz=self.imgsz
                )[0]

                detected_count = 0  # Contador de detecciones válidas
                frame_detections = []  # Lista de detecciones del frame

                # =============================================================
                # C. PROCESAR DETECCIONES
                # =============================================================
                if results.boxes is not None and results.boxes.id is not None:
                    # Extraer coordenadas, IDs, clases y confianzas
                    boxes = results.boxes.xyxy.cpu().numpy()
                    track_ids = results.boxes.id.int().cpu().numpy()
                    clss = results.boxes.cls.int().cpu().numpy()
                    confs = results.boxes.conf.cpu().numpy()

                    # Iterar sobre cada detección
                    for box, yolo_id, cls_id, conf in zip(boxes, track_ids, clss, confs):
                        # -----------------------------------------------------
                        # Determinar tipo de objeto según clase COCO y filtros
                        # -----------------------------------------------------
                        obj_type = None

                        if cls_id == 0 and self.filters['person']:
                            obj_type = "persona"
                        elif cls_id in [2, 3, 5, 7] and self.filters['car']:
                            obj_type = "carro"
                        elif cls_id == 8 and self.filters['boat']:
                            obj_type = "bote"
                        elif cls_id == 4 and self.filters['helicopter']:
                            obj_type = "helicoptero"  # Aproximación con airplane

                        # -----------------------------------------------------
                        # Si el objeto pasó los filtros, procesarlo
                        # -----------------------------------------------------
                        if obj_type is not None:
                            detected_count += 1
                            x1, y1, x2, y2 = map(int, box)

                            # Recortar región del objetivo con límites seguros
                            h_f, w_f, _ = frame.shape
                            crop_y1 = max(0, y1)
                            crop_y2 = min(h_f, y2)
                            crop_x1 = max(0, x1)
                            crop_x2 = min(w_f, x2)
                            crop_img = frame[crop_y1:crop_y2, crop_x1:crop_x2]

                            # -------------------------------------------------
                            # REIDENTIFICACIÓN BIOMÉTRICA
                            # -------------------------------------------------
                            # Extracción intermitente para optimizar CPU:
                            # - Si el ID es nuevo, extraer siempre
                            # - Si ya existe, extraer cada 15 frames
                            if (yolo_id not in self.id_mapping or
                                    self.frame_count - self.last_extraction_frame.get(yolo_id, 0) > 15):
                                # Extracción completa de firma biométrica
                                real_id = self.get_true_id(yolo_id, crop_img)
                                self.last_extraction_frame[yolo_id] = self.frame_count
                            else:
                                # Usar ID ya mapeado sin re-extraer
                                real_id = self.id_mapping.get(yolo_id, yolo_id)

                            # -------------------------------------------------
                            # ETIQUETA Y COLOR SEGÚN TIPO DE OBJETO
                            # -------------------------------------------------
                            label = f"{obj_type.capitalize()} #{real_id} ({conf * 100:.0f}%)"

                            # Paleta de colores BGR por tipo
                            colores = {
                                'persona': (0, 0, 255),  # Rojo (BGR)
                                'carro': (0, 255, 0),  # Verde (BGR)
                                'bote': (255, 0, 0),  # Azul (BGR)
                                'helicoptero': (0, 165, 255)  # Naranja (BGR)
                            }
                            color = colores.get(obj_type, (0, 255, 0))

                            # Log de nuevo objetivo (solo la primera vez)
                            if real_id not in self.logged_ids:
                                self.log_signal.emit(
                                    f"[CH{self.channel_id}] [NUEVO OBJETIVO] {obj_type.capitalize()} #{real_id} ({conf * 100:.0f}%)",
                                    "INFO"
                                )

                            # -------------------------------------------------
                            # CAPTURA TÁCTICA DE OBJETIVOS NUEVOS
                            # -------------------------------------------------
                            if real_id not in self.logged_ids and crop_img.size > 0:
                                self.logged_ids.add(real_id)

                                # Generar nombre de archivo con timestamp
                                timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                                conf_int = int(conf * 100)
                                img_path = self.save_dir / f"ch{self.channel_id}_{real_id}_{obj_type}_{conf_int}.jpg"

                                # Guardar imagen del objetivo con manejo de errores
                                try:
                                    cv2.imwrite(str(img_path), crop_img)
                                except Exception as e:
                                    # Registrar error en el sistema de logs
                                    self.log_signal.emit(
                                        f"Error al guardar captura automática: {e}",
                                        "ERROR"
                                    )
                                    # Continuar con el siguiente objetivo
                                    continue

                                # Preparar datos de la captura
                                capture_data = {
                                    "id": real_id,
                                    "type": obj_type,
                                    "conf": f"{conf * 100:.1f}%",
                                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "path": str(img_path),
                                    "desc": f"Dim: {x2 - x1}x{y2 - y1} px | Certeza: {conf * 100:.1f}%"
                                }

                                # Emitir señales de captura
                                self.object_captured_signal.emit(capture_data)

                                # Emitir log unificado
                                self.log_signal.emit(
                                    f"[CH{self.channel_id}] [CAPTURA AUTOMÁTICA] {obj_type.capitalize()} #{real_id} ({conf * 100:.0f}%)",
                                    "INFO"
                                )

                            # -------------------------------------------------
                            # DIBUJAR BOUNDING BOX Y ETIQUETA
                            # -------------------------------------------------
                            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                            cv2.putText(
                                frame,
                                label,
                                (x1, max(y1 - 10, 15)),  # Evitar que salga del frame
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                color,
                                2
                            )

                            # Agregar detección a la lista del frame
                            frame_detections.append({
                                'type': obj_type,
                                'conf': float(conf),
                                'id': real_id
                            })

                # =============================================================
                # D. ACTUALIZAR DETECCIONES ACTUALES
                # =============================================================
                self.current_detections = frame_detections

                # =============================================================
                # E. HUD: HORA ACTUAL
                # =============================================================
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                overlay = frame.copy()
                cv2.rectangle(overlay, (10, 10), (260, 42), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)  # 50% transparencia
                cv2.putText(
                    frame,
                    f"HORA: {now_str}",
                    (20, 32),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    2
                )

                # =============================================================
                # F. HUD: UPTIME DEL SISTEMA
                # =============================================================
                elapsed_sec = int(time.time() - self.start_time_uptime)
                uptime_str = time.strftime("%H:%M:%S", time.gmtime(elapsed_sec))
                h, w, _ = frame.shape
                overlay = frame.copy()
                cv2.rectangle(overlay, (w - 210, 10), (w - 10, 42), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)  # 50% transparencia
                cv2.putText(
                    frame,
                    f"UPTIME: {uptime_str}",
                    (w - 195, 32),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    2
                )

                # =============================================================
                # G. CALCULAR FPS Y EMITIR SEÑALES
                # =============================================================
                end_tick = cv2.getTickCount()
                fps = cv2.getTickFrequency() / max(1, (end_tick - start_tick))

                # ---------------------------------------------------------
                # MONITOREO DE FPS BAJO SOSTENIDO
                # ---------------------------------------------------------
                if fps < 15.0:  # Umbral de FPS bajo
                    if self.low_fps_start_time is None:
                        self.low_fps_start_time = time.time()
                    elif (time.time() - self.low_fps_start_time > 5.0 and
                          not self.low_fps_warning_emitted):
                        # Emitir advertencia solo una vez por episodio
                        self.log_signal.emit(
                            f"FPS bajo sostenido: {fps:.1f} FPS durante más de 5 segundos",
                            "WARNING"
                        )
                        self.low_fps_warning_emitted = True
                else:
                    # Restablecer si el FPS se recupera
                    self.low_fps_start_time = None
                    self.low_fps_warning_emitted = False

                # Emitir frame procesado y telemetría
                self.change_pixmap_signal.emit(frame)
                self.telemetry_signal.emit(fps, detected_count)

            else:
                # =============================================================
                # MANEJO DE ERROR DE LECTURA DE FRAME
                # =============================================================
                if isinstance(self.source, str) and not self.source.startswith("rtsp"):
                    # Registro de fin de video
                    self.log_signal.emit(
                        "Fin del archivo de video. Reiniciando reproducción...",
                        "WARNING"
                    )
                    # Para archivos de video: reiniciar al principio
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                else:
                    # Para cámaras/RTSP: salir del bucle
                    break

            # =================================================================
            # CONTROL DE FPS
            # =================================================================
            # Calcular tiempo transcurrido en este ciclo
            elapsed_loop_time = time.time() - loop_start_time

            # Si el ciclo fue más rápido que el límite, esperar
            if elapsed_loop_time < frame_time_limit:
                time.sleep(frame_time_limit - elapsed_loop_time)

        # =====================================================================
        # 4. LIBERAR RECURSOS
        # =====================================================================
        self.log_signal.emit("Bucle de captura finalizado. Liberando recursos...", "DEBUG")
        cap.release()

    # =========================================================================
    # MÉTODOS DE CONSULTA Y CONTROL
    # =========================================================================

    def get_current_detections(self):
        """
        Devuelve las detecciones del último frame procesado.

        Returns:
            Lista de diccionarios con claves:
            - 'type': Tipo de objeto ('persona', 'carro', 'bote', 'helicoptero')
            - 'conf': Confianza de la detección (0-1)
            - 'id': ID real reidentificado
        """
        return self.current_detections

    def stop(self):
        """
        Detiene el hilo de forma segura y espera a que termine.

        Establece la bandera de ejecución a False y bloquea hasta que
        el hilo complete su ciclo actual y libere recursos.
        """
        self._is_running = False
        self.wait()  # Bloquear hasta que el hilo termine