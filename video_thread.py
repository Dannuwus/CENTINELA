# =============================================================================
# MÓDULO DE INGESTA DE VIDEO v3
#   - OpenCV  -> cámaras locales y archivos locales
#   - PyAV    -> streams de red (UDP / RTSP / HTTP / RTMP / SRT) con FFmpeg embebido
#   - IA desacoplada (YOLO + Re-ID + OCR) y HUD con telemetría incrustada
# Dependencias nuevas:  pip install av
# =============================================================================
import os

import cv2
from pathlib import Path
import time
import torch
import datetime
import re
import queue
import traceback
import numpy as np
import threading
import subprocess
import platform
from collections import deque
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode
from PySide6.QtCore import QThread, Signal, Slot
from ultralytics import YOLO

# =============================================================================
# DIAGNOSTICO DE CONSOLA
# =============================================================================
_CONSOLE_LOCK = threading.Lock()
DEBUG_CONSOLE_DEFAULT = True

ERROR_CODES = {
    1: "PyAV no instalado",
    2: "Fuente invalida / no se pudo abrir",
    3: "Video congelado / no se decodifican cuadros",
    4: "Error de decodificacion",
    5: "Cuadro corrupto",
    6: "Sin paquetes de video",
    7: "El stream no contiene video",
    8: "GUI con backpressure / cuadros omitidos",
    9: "Latencia interna alta",
    10: "Fallo de conexion / transporte de red",
}

def console_log(level, message):
    """Imprime diagnostico con timestamp y flush inmediato para depuracion real."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    with _CONSOLE_LOCK:
        print(f"[{stamp}] [{level}] {message}", flush=True)


def error_text(code):
    return ERROR_CODES.get(int(code), "Error desconocido")

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    import av
    HAS_AV = True
except ImportError:
    HAS_AV = False


# =============================================================================
# CAPTURA LOCAL (OpenCV): cámaras y fallback
# =============================================================================
class LocalCaptureGrabber(threading.Thread):
    """Drena cv2.VideoCapture en un hilo y conserva solo el cuadro más reciente."""

    def __init__(self, cap):
        super().__init__(daemon=True)
        self.cap = cap
        self.running = True
        self.cond = threading.Condition()
        self._latest = None
        self.latest_ts = 0.0

        self.frames_decoded = 0
        self.frames_overwritten = 0
        self.last_age_ms = 0.0
        self.width = 0
        self.height = 0
        self.last_frame_time = time.time()

    def run(self):
        while self.running and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
            except Exception:
                time.sleep(0.005)
                continue
            if not ret or frame is None:
                time.sleep(0.002)
                continue

            now = time.time()
            with self.cond:
                if self._latest is not None:
                    self.frames_overwritten += 1
                self._latest = frame
                self.latest_ts = now
                self.frames_decoded += 1
                self.last_frame_time = now
                self.height, self.width = frame.shape[:2]
                self.cond.notify()

    def read(self, timeout=0.1):
        with self.cond:
            if self._latest is None:
                self.cond.wait(timeout)
            if self._latest is None:
                return False, None
            f = self._latest
            self._latest = None
            self.last_age_ms = (time.time() - self.latest_ts) * 1000.0
            return True, f

    def stop(self):
        self.running = False
        with self.cond:
            self.cond.notify_all()


# =============================================================================
# CAPTURA DE RED (PyAV / FFmpeg): DECODIFICADOR DE ÚLTIMO CUADRO
# =============================================================================
class FFmpegStreamReader(threading.Thread):
    """Lector de streams de red con FFmpeg/PyAV, orientado a baja latencia.

    Diseño deliberadamente sencillo y seguro:
      - Un único hilo posee y usa el demuxer y el decoder.
      - No existe una cola Python de paquetes comprimidos.
      - Solo se conserva el último VideoFrame decodificado.
      - Si llegan cuadros más rápido de lo que la GUI los consume, los viejos
        se sobrescriben y no se convierten en retraso acumulado.
      - Ante una caída real del stream, el propio lector reconecta.

    FFmpeg queda a cargo de detectar automáticamente el contenedor/codec del
    stream. Para UDP se añaden únicamente opciones de transporte pensadas para
    evitar acumulación excesiva y sobrevivir a overrun.
    """

    def __init__(self, url, rtsp_transport="tcp", max_backlog_ms=250,
                 open_timeout=4.0, read_timeout=2.0, thread_type="AUTO",
                 udp_fifo_packets=1024, udp_buffer_bytes=262144,
                 frame_stall_timeout=4.0, packet_stall_timeout=4.0,
                 debug_console=True, log_fn=None):
        super().__init__(daemon=True)
        self.url = str(url)
        self.rtsp_transport = rtsp_transport
        self.max_backlog_ms = max_backlog_ms
        self.open_timeout = float(open_timeout)
        self.read_timeout = float(read_timeout)
        self.thread_type = thread_type
        # Limites superiores para impedir que una configuracion heredada
        # (por ejemplo fifo=3000) vuelva a introducir segundos de buffer.
        self.udp_fifo_packets = min(1024, max(256, int(udp_fifo_packets)))
        self.udp_buffer_bytes = min(262144, max(65536, int(udp_buffer_bytes)))
        self.frame_stall_timeout = max(2.0, float(frame_stall_timeout))
        self.packet_stall_timeout = max(2.0, float(packet_stall_timeout))
        self.debug_console = bool(debug_console)
        self.log = log_fn or (lambda m: None)
        self.running = True

        # Estado del diagnostico. Estos contadores distinguen:
        #   sin paquetes -> problema de red/transporte (ERR 10)
        #   paquetes pero sin frames -> problema de video/decoder (ERR 3)
        self.codec_name = "?"
        self.container_format = "?"
        self.last_error_code = 0
        self.last_error = ""
        self._stall_reported = False
        self._packet_stall_reported = False
        self._last_console_ts = 0.0
        self._last_console_dec = 0
        self._last_console_pkt = 0
        self._last_console_overwrite = 0
        self._last_console_decode_errors = 0
        self._last_console_corrupt = 0
        self._last_console_reconnects = 0
        self._last_console_state = ""

        # Solo un slot para el cuadro más reciente.
        self.cond = threading.Condition()
        self._latest = None
        self.latest_ts = 0.0

        # Telemetría pública.
        self.state = "CONECTANDO"
        self.last_error = ""
        self.reconnects = 0
        self.frames_decoded = 0
        self.frames_overwritten = 0
        self.pkts_total = 0
        self.pkts_dropped = 0
        self.resyncs = 0
        self.gaps = 0
        self.decode_errors = 0
        self.corrupt_frames = 0
        self.bitrate_kbps = 0.0
        self.gop = 0
        self.jitter_ms = 0.0
        self.decode_ms = 0.0
        self.lat_rx_ms = 0.0
        self.last_age_ms = 0.0
        self.width = 0
        self.height = 0
        self.last_frame_time = time.time()
        self.last_packet_time = time.time()

        # Internos de medición.
        self._bytes_win = 0
        self._win_t = time.time()
        self._since_key = 0
        self._last_arr = None
        self._last_dts = None
        self._dt_ema = None

    @staticmethod
    def _is_key(packet):
        return bool(getattr(packet, "is_keyframe", False))

    def backlog_ms(self):
        """No hay cola Python de paquetes: el backlog interno deliberadamente es 0."""
        return 0.0

    def _console(self, level, message):
        if self.debug_console:
            console_log(level, message)

    def _set_error(self, code, message, emit_signal=False):
        """Registra un error numerado y lo muestra en consola de inmediato."""
        code = int(code)
        self.last_error_code = code
        self.last_error = str(message)
        self._console(
            "ERROR",
            f"ERR-{code:02d} {error_text(code)} | {message} | URL={self.url}"
        )
        if emit_signal:
            try:
                self.log(f"ERR-{code:02d} {error_text(code)}: {message}")
            except Exception:
                pass

    def _console_snapshot(self, now):
        """Resumen 1 Hz: red, decoder, cuadros, jitter, perdida y silencio."""
        if not self.debug_console or (now - self._last_console_ts) < 1.0:
            return

        dt = max(0.001, now - self._last_console_ts) if self._last_console_ts else 1.0
        dec = self.frames_decoded
        pkt = self.pkts_total
        dec_fps = (dec - self._last_console_dec) / dt
        pkt_ps = (pkt - self._last_console_pkt) / dt
        overwritten_ps = (self.frames_overwritten - self._last_console_overwrite) / dt
        err_delta = self.decode_errors - self._last_console_decode_errors
        corrupt_delta = self.corrupt_frames - self._last_console_corrupt

        no_pkt = max(0.0, now - self.last_packet_time) if self.last_packet_time else 0.0
        no_frame = max(0.0, now - self.last_frame_time) if self.last_frame_time else 0.0
        age = max(0.0, self.last_age_ms)

        self._console(
            "STREAM",
            f"STATE={self.state} CODEC={self.codec_name} FORMAT={self.container_format} "
            f"RES={self.width}x{self.height} RX={dec_fps:.1f}fps "
            f"PKT={pkt_ps:.0f}/s BITRATE={self.bitrate_kbps:.0f}kbps "
            f"JITTER_RX={self.jitter_ms:.1f}ms GAPS={self.gaps} "
            f"DECODE={self.decode_ms:.1f}ms FRAME_AGE={age:.1f}ms "
            f"NO_PKT={no_pkt:.1f}s NO_FRAME={no_frame:.1f}s "
            f"OVERWRITE={overwritten_ps:.1f}/s DROP_APP={self.pkts_dropped} "
            f"ERR_DEC={err_delta} CORRUPT={corrupt_delta} RECON={self.reconnects} "
            f"ERR_CODE={self.last_error_code}"
        )

        self._last_console_ts = now
        self._last_console_dec = dec
        self._last_console_pkt = pkt
        self._last_console_overwrite = self.frames_overwritten
        self._last_console_decode_errors = self.decode_errors
        self._last_console_corrupt = self.corrupt_frames
        self._last_console_reconnects = self.reconnects
        self._last_console_state = self.state

    def _options(self):
        # Se privilegia una detección suficientemente robusta para aceptar
        # MPEG-TS, H.264/H.265 u otros formatos que FFmpeg pueda identificar,
        # sin usar analyzeduration=0/probesize diminuto que podía romper la
        # autodetección de fuentes genéricas.
        opts = {
            "fflags": "nobuffer+discardcorrupt",
            "flags": "low_delay",
            "avioflags": "direct",
            "flush_packets": "1",
            "max_delay": "0",
            "probesize": "1048576",
            "analyzeduration": "500000",
        }
        if self.url.lower().startswith("rtsp://"):
            opts["rtsp_transport"] = self.rtsp_transport
            # No acumular una gran cola de reordenamiento RTSP.
            opts["reorder_queue_size"] = "0"
        return opts

    def _reset_connection_state(self):
        self._since_key = 0
        self._last_arr = None
        self._last_dts = None
        self._dt_ema = None
        self._bytes_win = 0
        self._win_t = time.time()
        self.last_packet_time = time.time()
        self.last_frame_time = time.time()
        self.state = "CONECTANDO"
        self.codec_name = "?"
        self.container_format = "?"
        self.last_error_code = 0
        self.last_error = ""
        self._stall_reported = False
        self._packet_stall_reported = False
        self._last_console_ts = 0.0
        self._last_console_dec = self.frames_decoded
        self._last_console_pkt = self.pkts_total
        self._last_console_overwrite = self.frames_overwritten
        self._last_console_decode_errors = self.decode_errors
        self._last_console_corrupt = self.corrupt_frames

    def _on_packet(self, packet, now):
        self.pkts_total += 1
        self.last_packet_time = now
        self._packet_stall_reported = False
        self._bytes_win += max(0, int(getattr(packet, "size", 0)))

        if now - self._win_t >= 1.0:
            self.bitrate_kbps = self._bytes_win * 8.0 / 1000.0 / max(now - self._win_t, 1e-6)
            self._bytes_win = 0
            self._win_t = now

        if self._is_key(packet):
            if self._since_key > 0:
                self.gop = self._since_key
            self._since_key = 0
        self._since_key += 1

        ts = packet.dts if packet.dts is not None else packet.pts
        if ts is None or packet.time_base is None:
            return
        try:
            ts_s = float(ts * packet.time_base)
        except Exception:
            return

        if self._last_arr is not None and self._last_dts is not None:
            d_arr = now - self._last_arr
            d_ts = ts_s - self._last_dts
            if d_ts > 0:
                dev_ms = abs(d_arr - d_ts) * 1000.0
                self.jitter_ms += (dev_ms - self.jitter_ms) / 16.0
                if self._dt_ema is None:
                    self._dt_ema = d_ts
                elif d_ts > 2.2 * self._dt_ema:
                    self.gaps += 1
                else:
                    self._dt_ema += (d_ts - self._dt_ema) * 0.1

        self._last_arr = now
        self._last_dts = ts_s

    def _publish_frame(self, frame, packet_arrival_ts):
        if getattr(frame, "is_corrupt", False):
            self.corrupt_frames += 1
            if self.corrupt_frames <= 3 or self.corrupt_frames % 50 == 0:
                self._set_error(5, f"Cuadro corrupto #{self.corrupt_frames}", emit_signal=True)
            return

        now = time.time()
        lat = max(0.0, (now - packet_arrival_ts) * 1000.0)
        self.lat_rx_ms = lat if self.lat_rx_ms == 0 else self.lat_rx_ms * 0.9 + lat * 0.1

        with self.cond:
            if self._latest is not None:
                self.frames_overwritten += 1
            self._latest = frame
            self.latest_ts = now
            self.frames_decoded += 1
            self.last_frame_time = now
            self.width, self.height = int(frame.width), int(frame.height)
            self.state = "EN VIVO"
            self._stall_reported = False
            self.cond.notify()

    def _configure_decoder(self, vstream):
        ctx = vstream.codec_context
        try:
            ctx.thread_type = self.thread_type
        except Exception:
            pass

        # Estas opciones son aceptadas por la mayoría de decodificadores FFmpeg
        # relevantes para video en vivo. Si alguna versión de PyAV/codec no las
        # admite, simplemente se conserva la configuración por defecto.
        try:
            if hasattr(ctx, "options"):
                current = dict(ctx.options or {})
                current.setdefault("flags", "low_delay")
                ctx.options = current
        except Exception:
            pass

    def _open_container(self):
        self._console("INFO", f"Intentando abrir stream | URL={self.url}")
        return av.open(
            self.url,
            mode="r",
            options=self._options(),
            timeout=(self.open_timeout, self.read_timeout),
        )

    def run(self):
        while self.running:
            container = None
            self._reset_connection_state()
            self._console("INFO", f"Conector iniciado | URL={self.url} | intento={self.reconnects + 1}")
            try:
                container = self._open_container()

                try:
                    self.container_format = str(getattr(getattr(container, "format", None), "name", "?"))
                except Exception:
                    self.container_format = "?"

                vstream = next((s for s in container.streams if s.type == "video"), None)
                if vstream is None:
                    self._set_error(7, "El contenedor se abrio pero no existe stream de video", emit_signal=True)
                    raise RuntimeError("El stream no contiene video")

                self._configure_decoder(vstream)
                self.codec_name = str(getattr(vstream.codec_context, "name", "?"))
                self.state = "ESPERANDO VIDEO"
                self.log(
                    f"STREAM: FFmpeg/PyAV conectado | {self.url} | "
                    f"format={self.container_format} codec={self.codec_name}"
                )
                self._console(
                    "OK",
                    f"Conexion establecida | FORMAT={self.container_format} | "
                    f"CODEC={self.codec_name} | STREAM_INDEX={getattr(vstream, 'index', '?')}"
                )

                # Un solo hilo posee demux + decoder. No hay cola Python de paquetes.
                for packet in container.demux(vstream):
                    if not self.running:
                        break

                    now = time.time()

                    # Demux sin paquete utilizable.
                    if getattr(packet, "size", 0) <= 0:
                        self._console_snapshot(now)
                        continue

                    arr = now
                    self._on_packet(packet, arr)

                    t0 = time.time()
                    try:
                        frames = vstream.codec_context.decode(packet)
                    except Exception as exc:
                        self.decode_errors += 1
                        if self.decode_errors <= 3 or self.decode_errors % 50 == 0:
                            self._set_error(4, f"decode(): {type(exc).__name__}: {exc}", emit_signal=True)
                        self._console_snapshot(time.time())
                        continue

                    dt = (time.time() - t0) * 1000.0
                    self.decode_ms = dt if self.decode_ms == 0 else self.decode_ms * 0.9 + dt * 0.1

                    for frame in frames:
                        self._publish_frame(frame, arr)

                    now = time.time()

                    # Caso A: no hay paquetes -> ERR 10 (transporte/red).
                    if now - self.last_packet_time > self.packet_stall_timeout:
                        if not self._packet_stall_reported:
                            self._set_error(10, f"No llegan paquetes desde hace {now - self.last_packet_time:.1f}s", emit_signal=True)
                            self._packet_stall_reported = True
                        raise TimeoutError("Sin paquetes del stream")

                    # Caso B: sí llegan paquetes pero no aparecen cuadros -> ERR 3.
                    if now - self.last_frame_time > self.frame_stall_timeout:
                        if not self._stall_reported:
                            self._set_error(3, f"Hay trafico, pero no se decodifican cuadros desde hace {now - self.last_frame_time:.1f}s", emit_signal=True)
                            self._stall_reported = True
                        raise TimeoutError("Video congelado / sin frames decodificados")

                    self._console_snapshot(now)

            except Exception as exc:
                # Si la excepcion ocurre fuera de decode(), tratamos la apertura/demux
                # como problema de red/transporte. El decoder ya reporta ERR 4 aparte.
                if self.last_error_code not in (3, 4, 5, 7, 10):
                    self._set_error(10, f"{type(exc).__name__}: {exc}", emit_signal=True)
                else:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                self.state = "RECONECTANDO" if self.running else "DETENIENDO"

                if self.running:
                    self.log(
                        f"STREAM: conexion perdida ({self.last_error}). Reintentando..."
                    )
                    self._console(
                        "WARN",
                        f"Reconectando | code={self.last_error_code} | {self.last_error}"
                    )

            finally:
                if container is not None:
                    try:
                        container.close()
                    except Exception:
                        pass

                with self.cond:
                    self._latest = None
                    self.cond.notify_all()

            if not self.running:
                break

            self.reconnects += 1
            self.state = "RECONECTANDO"
            self._console("INFO", f"Pausa de reconexion | RECONEXIONES={self.reconnects}")
            for _ in range(10):
                if not self.running:
                    break
                time.sleep(0.1)

    def read(self, timeout=0.1):
        with self.cond:
            if self._latest is None:
                self.cond.wait(timeout)
            if self._latest is None:
                return False, None

            vf = self._latest
            self._latest = None
            self.last_age_ms = max(0.0, (time.time() - self.latest_ts) * 1000.0)

        try:
            img = np.ascontiguousarray(vf.to_ndarray(format="bgr24"))
        except Exception as exc:
            self._set_error(5, f"Conversion VideoFrame->BGR fallo: {type(exc).__name__}: {exc}", emit_signal=True)
            return False, None
        return True, img

    def stop(self):
        self.running = False
        with self.cond:
            self.cond.notify_all()


# =============================================================================
# HILO DE IA (YOLO + RE-ID)
# =============================================================================
class AIWorker(threading.Thread):
    """Ejecuta la inferencia pesada en segundo plano sin congelar el video."""

    def __init__(self, video_thread):
        super().__init__(daemon=True)
        self.vt = video_thread
        self.pending_frame = None
        self.latest_detections = []
        self.result_ts = 0.0
        self.is_busy = False
        self.running = True
        self.infer_count = 0
        self.infer_ms = 0.0
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)

    def submit_frame(self, frame):
        with self.lock:
            if self.is_busy:
                return False
            self.is_busy = True
        frame_copy = frame.copy()
        with self.cond:
            self.pending_frame = frame_copy
            self.cond.notify()
        return True

    def get_latest_detections(self, max_age=1.5):
        with self.lock:
            if time.time() - self.result_ts > max_age:
                return []
            return list(self.latest_detections)

    def run(self):
        try:
            self.vt.warmup_model()
        except Exception:
            traceback.print_exc()

        while self.running:
            with self.cond:
                while self.pending_frame is None and self.running:
                    self.cond.wait(timeout=0.1)
                if not self.running:
                    break
                frame_to_process = self.pending_frame
                self.pending_frame = None

            t0 = time.time()
            try:
                detections = self.vt._process_ai_pipeline(frame_to_process)
                dt = (time.time() - t0) * 1000.0
                with self.lock:
                    self.latest_detections = detections
                    self.result_ts = time.time()
                    self.infer_ms = dt if self.infer_ms == 0 else (self.infer_ms * 0.8 + dt * 0.2)
                    self.infer_count += 1
            except Exception:
                traceback.print_exc()
            finally:
                with self.lock:
                    self.is_busy = False

    def stop(self):
        self.running = False
        with self.cond:
            self.cond.notify_all()


# =============================================================================
# OCR EN HILO APARTE
# =============================================================================
class OCRWorker(threading.Thread):
    def __init__(self, read_fn, callback):
        super().__init__(daemon=True)
        self.read_fn = read_fn
        self.callback = callback
        self.q = queue.Queue(maxsize=4)
        self.running = True

    def submit(self, key, crop):
        try:
            self.q.put_nowait((key, crop.copy()))
        except queue.Full:
            pass

    def run(self):
        while self.running:
            try:
                key, crop = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                text = self.read_fn(crop)
                if text:
                    self.callback(key, text)
            except Exception:
                pass

    def stop(self):
        self.running = False


# =============================================================================
# TELEMETRÍA DE RED (PING + JITTER + PACKET LOSS EN VENTANA DESLIZANTE)
# =============================================================================
class NetworkTelemetry:
    """Monitoreo no bloqueante de latencia hacia el emisor (ICMP)."""

    def __init__(self, source_url, ping_host=None):
        self.ip = ping_host or self._extract_host(source_url)
        self.ping_ms = 0.0
        self.avg_ms = 0.0
        self.jitter_ms = 0.0
        self.packet_loss = 0
        self.history = deque(maxlen=20)
        self.status = "ESCUCHA" if not self.ip else "Iniciando..."
        self.running = True

        if self.ip:
            self.thread = threading.Thread(target=self._ping_loop, daemon=True)
            self.thread.start()

    def _extract_host(self, url):
        if isinstance(url, int):
            return None
        s = str(url).strip()
        match = re.search(r'([0-9]{1,3}(?:\.[0-9]{1,3}){3})', s)
        if match:
            ip = match.group(1)
            first = int(ip.split(".")[0])
            if ip in ("0.0.0.0", "127.0.0.1") or 224 <= first <= 239:
                return None
            return ip
        try:
            host = urlparse(s).hostname
            if host and host != "localhost" and re.fullmatch(r'[A-Za-z0-9.\-]+', host):
                return host
        except Exception:
            pass
        return None

    def _ping_once(self):
        is_windows = platform.system().lower() == "windows"
        cmd = ["ping", "-n" if is_windows else "-c", "1",
               "-w" if is_windows else "-W", "1000" if is_windows else "1", self.ip]
        kwargs = {}
        if is_windows:
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  errors="ignore", timeout=3, **kwargs)
            out = (proc.stdout or "") + (proc.stderr or "")
        except Exception:
            return None
        m = re.search(r'(?:tiempo|time)\s*[=<]\s*([\d.,]+)\s*ms?', out, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                return 1.0
        if proc.returncode == 0 and "ttl" in out.lower():
            return 1.0
        return None

    def _ping_loop(self):
        while self.running:
            ms = self._ping_once()
            self.history.append(ms)
            valid = [x for x in self.history if x is not None]
            lost = len(self.history) - len(valid)
            self.packet_loss = int(100 * lost / max(1, len(self.history)))
            if ms is not None:
                self.ping_ms = ms
            if valid:
                self.avg_ms = sum(valid) / len(valid)
                diffs = [abs(a - b) for a, b in zip(valid[1:], valid[:-1])]
                self.jitter_ms = (sum(diffs) / len(diffs)) if diffs else 0.0
            last3 = list(self.history)[-3:]
            if len(last3) == 3 and all(x is None for x in last3):
                self.status = "Conexion Perdida"
            elif self.packet_loss >= 30:
                self.status = "Inestable (Perdida)"
            elif self.ping_ms > 150 or self.jitter_ms > 50:
                self.status = "Lag Alto"
            else:
                self.status = "Estable"
            time.sleep(1.0)

    def stop(self):
        self.running = False


# =============================================================================
# HILO PRINCIPAL DE VIDEO Y RENDERIZADO (PYSIDE)
# =============================================================================
class VideoThread(QThread):
    change_pixmap_signal = Signal(np.ndarray)
    telemetry_signal = Signal(float, int)
    detection_log_signal = Signal(str)
    object_captured_signal = Signal(dict)
    connection_status_signal = Signal(bool, str)
    network_stats_signal = Signal(dict)

    def __init__(self, source=0, conf_threshold=0.5, cpu_threads=4, save_dir=None,
                 channel_id=1, ping_host=None, udp_fifo_packets=1024,
                 udp_buffer_bytes=262144, rtsp_transport="tcp", max_latency_ms=250,
                 debug_console=True):
        super().__init__()
        self.source = source
        self.conf_threshold = conf_threshold
        self._is_running = True
        self.channel_id = channel_id
        self.source_type = self._detect_source_type(source)
        self.ping_host = ping_host
        self.udp_fifo_packets = udp_fifo_packets
        self.udp_buffer_bytes = udp_buffer_bytes
        self.rtsp_transport = rtsp_transport
        self.max_latency_ms = max_latency_ms
        self.debug_console = bool(debug_console)

        # Motor de captura: PyAV exclusivamente para red; OpenCV exclusivamente para local.
        self.use_pyav = (self.source_type == "NETWORK")
        self.engine_name = "PyAV/FFmpeg" if self.use_pyav else "OpenCV"

        self.filter_clahe = False
        self.zoom_level = 1.0
        self.ai_upscale = False
        self.pan_x = 0.5
        self.pan_y = 0.5
        self.show_hud = True
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self._sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)

        self.set_cpu_resources(cpu_threads)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.use_half = (self.device == "cuda")
        self.model = YOLO("modelos/yolov8n.pt")
        self.filters = {'person': True, 'car': True, 'boat': True, 'helicopter': False}
        self.ocr_enabled = False

        self.logged_ids = set()
        self.confirmed_tracks = set()
        self.current_detections = []
        self.appearance_memory = {}
        self.id_mapping = {}
        self.plates = {}

        self.frame_count = 0
        self.ai_frame_count = 0
        self.last_extraction_time = {}
        self.last_ocr_time = {}

        self.orb = cv2.ORB_create(nfeatures=150)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

        self.save_dir = Path(save_dir) if save_dir else Path("capturas")
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.imgsz = 320
        self.start_time_uptime = None
        self.last_frame_time = time.time()
        self.stall_timeout = 3.0          # solo para fuentes OpenCV
        self.network_monitor = None
        self.reader = None
        self.ai_worker = None
        self.ocr_worker = None

        self.max_display_fps = 30
        self._min_emit_interval = 1.0 / (self.max_display_fps + 2)
        self._last_emit = 0.0
        self.gui_backpressure = False
        self._gui_pending = 0
        self._ack_lock = threading.Lock()
        self.gui_skipped = 0
        self.reconnects = 0
        self.rendered_frames = 0
        self.render_fps = 0.0

        self.stats = {
            'rx_fps': 0.0, 'render_fps': 0.0, 'ai_fps': 0.0, 'ai_ms': 0.0,
            'drop_ps': 0.0, 'age_ms': 0.0, 'res': "-",
            'gui_skipped': 0, 'reconnects': 0,
            'ping_ms': None, 'avg_ms': None, 'jitter_ping_ms': None, 'loss': None,
            'status': "-",
            # Telemetría del stream (solo motor PyAV)
            'state': "-", 'bitrate_kbps': 0.0, 'gop': 0, 'jitter_ms': 0.0,
            'gaps_ps': 0.0, 'decode_ms': 0.0, 'backlog_ms': 0.0, 'resyncs': 0,
            'pkts_dropped': 0, 'decode_errors': 0, 'lat_rx_ms': 0.0,
            'error_code': 0, 'error_text': '', 'codec': '-', 'format': '-',
            'no_packet_s': 0.0, 'no_frame_s': 0.0, 'packet_rate': 0.0,
            'stream_started': False,
        }
        self._stat_t = time.time()
        self._prev = {'dec': 0, 'ren': 0, 'ai': 0, 'drop': 0, 'gaps': 0}
        self._console_stat_t = 0.0
        self._debug_last_stall_code = 0
        self._debug_last_gui_skipped = 0
        self._debug_last_latency_warning = 0.0

    # ------------------------------------------------------------------ util
    def _detect_source_type(self, source):
        try:
            if isinstance(source, int) or str(source).isdigit():
                return "WEBCAM"
            s_str = str(source).strip().lower()
            if s_str.startswith(("rtsp://", "udp://", "http://", "https://", "rtmp://", "srt://")):
                return "NETWORK"
            if Path(str(source)).exists():
                return "VIDEO_FILE"
            return "WEBCAM"
        except Exception:
            return "WEBCAM"

    def _prepare_source_url(self, source):
        """Normaliza fuentes de red sin asumir codec/container.

        Admite explícitamente: UDP, RTSP, RTP, HTTP(S), RTMP y SRT.
        También acepta el formato práctico ``IP:puerto`` como UDP.
        """
        s_str = str(source).strip()
        if not s_str:
            return s_str

        # Conveniencia: "192.168.1.38:5005" => "udp://192.168.1.38:5005".
        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}:\d{1,5}", s_str):
            s_str = f"udp://{s_str}"

        if not s_str.lower().startswith(("udp://", "rtp://")):
            return s_str

        parts = urlsplit(s_str)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))

        # Opciones de transporte; no modificamos las que el usuario ya haya
        # especificado en la URL.
        query.setdefault("overrun_nonfatal", "1")
        query.setdefault("fifo_size", str(self.udp_fifo_packets))
        query.setdefault("buffer_size", str(self.udp_buffer_bytes))
        query.setdefault("reuse", "1")
        query.setdefault("timeout", str(int(2.0 * 1_000_000)))

        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def set_cpu_resources(self, threads: int):
        try:
            torch.set_num_threads(threads)
            cv2.setNumThreads(threads)
        except Exception:
            pass

    def set_performance_mode(self, mode: str):
        if "Minimo" in mode:
            self.imgsz = 160
        elif "Balanceado" in mode:
            self.imgsz = 320
        elif "Exigente" in mode:
            self.imgsz = 480
        elif "Maximo" in mode:
            self.imgsz = 640

    def set_targets(self, person=True, car=True, boat=True, helicopter=False):
        self.filters['person'] = person
        self.filters['car'] = car
        self.filters['boat'] = boat
        self.filters['helicopter'] = helicopter

    def set_ocr_enabled(self, enabled: bool):
        self.ocr_enabled = enabled

    def set_optical_filters(self, clahe: bool):
        self.filter_clahe = clahe

    def set_zoom(self, level: float, upscale: bool):
        self.zoom_level = level
        self.ai_upscale = upscale

    def set_hud_visible(self, visible: bool):
        self.show_hud = visible

    def set_max_latency(self, ms: int):
        """Cambia en caliente la latencia máxima tolerada del stream de red."""
        self.max_latency_ms = ms
        if self.source_type == "NETWORK" and self.reader:
            self.reader.max_backlog_ms = ms

    @Slot(float, float)
    def set_pan(self, x: float, y: float):
        self.pan_x = x
        self.pan_y = y

    def enable_gui_backpressure(self, enabled: bool = True):
        self.gui_backpressure = enabled

    @Slot()
    def frame_ack(self):
        with self._ack_lock:
            self._gui_pending = max(0, self._gui_pending - 1)

    # ------------------------------------------------------------- imagen
    def enhance_frame(self, frame):
        if self.zoom_level > 1.0:
            h, w = frame.shape[:2]
            new_h, new_w = int(h / self.zoom_level), int(w / self.zoom_level)
            center_x = int(w * self.pan_x)
            center_y = int(h * self.pan_y)
            x1 = max(0, min(w - new_w, center_x - new_w // 2))
            y1 = max(0, min(h - new_h, center_y - new_h // 2))
            crop = frame[y1:y1 + new_h, x1:x1 + new_w]
            frame = cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)

        if self.ai_upscale:
            blur = cv2.GaussianBlur(frame, (0, 0), 1.5)
            frame = cv2.addWeighted(frame, 1.6, blur, -0.6, 0)

        if self.filter_clahe:
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            cl = self._clahe.apply(l)
            frame = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)
            frame = cv2.filter2D(frame, -1, self._sharpen_kernel)

        return frame

    def read_license_plate(self, car_crop):
        if not HAS_TESSERACT or car_crop is None or car_crop.size == 0:
            return ""
        try:
            h, w = car_crop.shape[:2]
            lower_half = car_crop[int(h * 0.4):, :]
            if lower_half.size == 0:
                return ""
            gray = cv2.cvtColor(lower_half, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            blur = cv2.bilateralFilter(gray, 11, 17, 17)
            thresh = cv2.adaptiveThreshold(
                blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )
            custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            text = pytesseract.image_to_string(thresh, config=custom_config)
            clean_text = re.sub(r'[^A-Z0-9]', '', text.upper())
            if 4 <= len(clean_text) <= 8:
                return clean_text
        except Exception:
            pass
        return ""

    def _on_plate(self, real_id, text):
        if self.plates.get(real_id) != text:
            self.plates[real_id] = text
            self.detection_log_signal.emit(f"OCR PLACA DETECTADA: [{text}] en Carro #{real_id}")

    # ------------------------------------------------------------- Re-ID
    def extract_signature(self, crop):
        h, w = crop.shape[:2]
        aspect_ratio = float(w) / float(max(h, 1))
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hsv[:, :, 2] = cv2.equalizeHist(hsv[:, :, 2])
        color_hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(color_hist, color_hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        gray_hog_img = cv2.cvtColor(cv2.resize(crop, (64, 128)), cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray_hog_img, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray_hog_img, cv2.CV_32F, 0, 1, ksize=3)
        mag, _ = cv2.cartToPolar(gx, gy, angleInDegrees=True)
        shape_features = cv2.resize(mag, (16, 16)).flatten()
        if np.linalg.norm(shape_features) > 0:
            shape_features = shape_features / np.linalg.norm(shape_features)
        gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        clahe_micro = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        gray_crop = clahe_micro.apply(gray_crop)
        kp, des = self.orb.detectAndCompute(gray_crop, None)
        return {'color': color_hist, 'shape': shape_features,
                'aspect_ratio': aspect_ratio, 'orb_des': des}

    @staticmethod
    def _blend_signature(past, cur, keep):
        best_orb = cur['orb_des'] if (
                cur['orb_des'] is not None and past['orb_des'] is not None and
                len(cur['orb_des']) > len(past['orb_des'])) else past['orb_des']
        return {
            'color': past['color'] * keep + cur['color'] * (1 - keep),
            'shape': past['shape'] * keep + cur['shape'] * (1 - keep),
            'aspect_ratio': past['aspect_ratio'] * keep + cur['aspect_ratio'] * (1 - keep),
            'orb_des': best_orb
        }

    def get_true_id(self, yolo_id, crop, threshold=0.70):
        if len(self.appearance_memory) > 30:
            overflow = len(self.appearance_memory) - 30
            for k in list(self.appearance_memory.keys())[:overflow]:
                del self.appearance_memory[k]

        if crop is None or crop.size == 0 or crop.shape[0] < 20 or crop.shape[1] < 20:
            return self.id_mapping.get(yolo_id, yolo_id)

        try:
            current_sig = self.extract_signature(crop)
        except Exception:
            return self.id_mapping.get(yolo_id, yolo_id)

        if yolo_id in self.id_mapping:
            true_id = self.id_mapping[yolo_id]
            mem = self.appearance_memory.get(true_id)
            if mem is not None:
                mem['signature'] = self._blend_signature(mem['signature'], current_sig, 0.7)
                return true_id
            del self.id_mapping[yolo_id]   # memoria purgada: re-evaluar (evita KeyError)

        best_match_id = None
        highest_score = 0.0

        for past_id, data in self.appearance_memory.items():
            past_sig = data['signature']
            if abs(current_sig['aspect_ratio'] - past_sig['aspect_ratio']) > 1.2:
                continue
            color_score = max(0, cv2.compareHist(current_sig['color'], past_sig['color'], cv2.HISTCMP_CORREL))
            shape_score = float(np.dot(current_sig['shape'], past_sig['shape']))
            orb_score = 0.0
            if current_sig['orb_des'] is not None and past_sig['orb_des'] is not None:
                matches = self.matcher.match(current_sig['orb_des'], past_sig['orb_des'])
                orb_score = min(1.0, len(matches) / 12.0)
            total_score = (shape_score * 0.35) + (orb_score * 0.45) + (color_score * 0.20)
            if total_score > highest_score:
                highest_score = total_score
                best_match_id = past_id

        if best_match_id is not None and highest_score > threshold:
            self.id_mapping[yolo_id] = best_match_id
            mem = self.appearance_memory[best_match_id]
            mem['signature'] = self._blend_signature(mem['signature'], current_sig, 0.5)
            return best_match_id

        self.id_mapping[yolo_id] = yolo_id
        self.appearance_memory[yolo_id] = {'signature': current_sig}
        return yolo_id

    # ------------------------------------------------------------- HUD
    def draw_network_hud(self, frame, h, w, cap=None):
        """Incrusta telemetría en el video: red, stream, decoder, latencia e IA."""
        try:
            green, orange, red = (0, 255, 0), (0, 165, 255), (0, 0, 255)
            s = self.stats
            now = time.time()
            silent = now - self.last_frame_time
            stype = self.source_type
            lines = []

            if stype == "NETWORK":
                nm = self.network_monitor
                state = s['state'] if self.use_pyav else ("EN LINEA" if silent < 2.0 else "SIN SENAL")
                bad = silent > 2.0 or state in ("RECONECTANDO", "CONECTANDO", "SIN SENAL")
                if nm and nm.ip:
                    st = nm.status
                    if bad or st == "Conexion Perdida":
                        st, color = "RECONECTANDO...", red
                    elif nm.packet_loss > 0 or nm.ping_ms > 150 or nm.jitter_ms > 50:
                        color = orange
                    else:
                        color = green
                    lines.append((f"RED: {st} | PING {nm.ping_ms:.0f}ms (prom {nm.avg_ms:.0f}) | "
                                  f"JITTER {nm.jitter_ms:.0f}ms | LOSS {nm.packet_loss}% | {self.engine_name}", color))
                else:
                    color = red if bad else green
                    lines.append((f"RED: {state} | PING: N/A (modo escucha) | {self.engine_name}", color))
            elif stype == "VIDEO_FILE" and cap is not None:
                try:
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    curr_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                    curr_str = time.strftime("%H:%M:%S", time.gmtime(int(curr_frame / max(1, video_fps))))
                    total_str = time.strftime("%H:%M:%S", time.gmtime(int(total_frames / max(1, video_fps))))
                    lines.append((f"VIDEO LOCAL: {curr_str}/{total_str} | Frame: {curr_frame}/{total_frames}", green))
                except Exception:
                    lines.append(("VIDEO LOCAL: REPRODUCIENDO", green))
            else:
                if silent > 2.0:
                    st, color = "RECONECTANDO...", red
                else:
                    st, color = "EN LINEA", green
                src_id = self.source if (isinstance(self.source, int) or str(self.source).isdigit()) else 0
                lines.append((f"CAMARA LOCAL: {st} | CAM #{src_id}", color))

            head_color = lines[0][1]

            perf_color = orange if (
                    s['ai_ms'] > 250 or (s['rx_fps'] and s['render_fps'] < s['rx_fps'] * 0.7)) else green
            lines.append((f"RX {s['rx_fps']:.0f}fps | RENDER {s['render_fps']:.0f}fps | "
                          f"IA {s['ai_fps']:.1f}fps ({s['ai_ms']:.0f}ms)", perf_color))

            if stype == "NETWORK":
                c3 = orange if (s['jitter_ms'] > 40 or s['gaps_ps'] > 0) else green
                lines.append((f"STREAM: {s['bitrate_kbps']:.0f}kbps | GOP {s['gop']} | "
                              f"JITTER RX {s['jitter_ms']:.0f}ms | HUECOS {s['gaps_ps']:.1f}/s", c3))

                c4 = green
                if s['backlog_ms'] > 250 or s['decode_ms'] > 40:
                    c4 = orange
                if s['backlog_ms'] > 600:
                    c4 = red
                lines.append((f"DECODER: {s['decode_ms']:.1f}ms | COLA {s['backlog_ms']:.0f}ms | "
                              f"RECORTES {s['resyncs']} | ERR {s['decode_errors']}", c4))

                total_lat = s['lat_rx_ms'] + s['age_ms']
                lines.append((f"LAT RX ~{total_lat:.0f}ms | {s['res']} | GUI omit {s['gui_skipped']} | "
                              f"RECONEX {s['reconnects']}", orange if total_lat > 300 else green))
            elif stype != "VIDEO_FILE":
                buf_color = orange if (s['drop_ps'] > 2 or s['age_ms'] > 150) else green
                lines.append((f"BUFFER: edad {s['age_ms']:.0f}ms | descartados {s['drop_ps']:.0f}/s | {s['res']}",
                              buf_color))
                lines.append((f"GUI omitidos: {s['gui_skipped']} | RECONEXIONES: {s['reconnects']}", green))

            font = cv2.FONT_HERSHEY_SIMPLEX
            scale, lh, pad = 0.42, 18, 6
            widths = [cv2.getTextSize(t, font, scale, 1)[0][0] for t, _ in lines]
            rect_w = min(w - 10, max(widths) + 40)
            rect_h = len(lines) * lh + pad * 2
            y2 = h - 8
            y1 = max(0, y2 - rect_h)
            x1, x2 = 5, min(w - 1, 5 + rect_w)

            roi = frame[y1:y2, x1:x2]
            if roi.size:
                overlay = np.full_like(roi, (2, 6, 23))
                cv2.addWeighted(overlay, 0.75, roi, 0.25, 0, roi)

            for i, (text, color) in enumerate(lines):
                cv2.putText(frame, text, (x1 + 8, y1 + pad + lh * (i + 1) - 5), font, scale, color, 1)
            cv2.circle(frame, (x2 - 12, y1 + pad + 9), 5, head_color, -1)
        except Exception:
            pass

    # ------------------------------------------------------ captura / reconexión
    def _open_capture_source(self):
        """Apertura con OpenCV únicamente para webcam y archivo local."""
        if self.source_type == "NETWORK":
            raise RuntimeError("Las fuentes de red usan PyAV/FFmpeg; OpenCV queda reservado para local.")

        prep_source = self._prepare_source_url(self.source)
        if self.source_type == "WEBCAM":
            idx = int(prep_source) if str(prep_source).isdigit() else 0
            backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
            cap = cv2.VideoCapture(idx, backend)
        else:
            cap = cv2.VideoCapture(str(prep_source))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _start_local_grabber(self, cap):
        if self.source_type == "VIDEO_FILE" or not cap.isOpened():
            return None
        g = LocalCaptureGrabber(cap)
        g.start()
        return g

    def _reconnect_local(self, cap):
        self.detection_log_signal.emit("WATCHDOG: Señal perdida o corrupta. Reintentando conexion...")
        self.reconnects += 1
        if self.reader:
            self.reader.stop()
            self.reader.join(timeout=4.0)
        cap.release()
        time.sleep(1.0)
        cap = self._open_capture_source()
        self.reader = self._start_local_grabber(cap)
        self.last_frame_time = time.time()
        if cap.isOpened():
            self.detection_log_signal.emit("WATCHDOG: Conexion restablecida con exito.")
        return cap

    def warmup_model(self):
        dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        self.model.predict(dummy, imgsz=self.imgsz, verbose=False,
                           device=self.device, half=self.use_half)

    # ------------------------------------------------------------ pipeline IA
    @staticmethod
    def _prune(d, limit=400):
        if len(d) > limit:
            for k in list(d.keys())[:len(d) - limit]:
                d.pop(k, None)

    def _process_ai_pipeline(self, frame):
        self.ai_frame_count += 1
        now = time.time()
        try:
            results = self.model.track(
                frame,
                persist=True,
                tracker="bytetrack.yaml",
                verbose=False,
                conf=min(self.conf_threshold, 0.30),
                imgsz=self.imgsz,
                device=self.device,
                half=self.use_half
            )[0]
        except Exception:
            traceback.print_exc()
            return []

        frame_detections = []
        if results is None or results.boxes is None or results.boxes.id is None:
            return frame_detections

        boxes = results.boxes.xyxy.cpu().numpy()
        track_ids = results.boxes.id.int().cpu().numpy()
        clss = results.boxes.cls.int().cpu().numpy()
        confs = results.boxes.conf.cpu().numpy()
        h_f, w_f = frame.shape[:2]
        reid_budget = 3

        for box, yolo_id, cls_id, conf in zip(boxes, track_ids, clss, confs):
            yolo_id, cls_id = int(yolo_id), int(cls_id)
            if conf < self.conf_threshold and yolo_id not in self.confirmed_tracks:
                continue

            obj_type = None
            if cls_id == 0 and self.filters['person']:
                obj_type = "persona"
            elif cls_id in (2, 3, 5, 7) and self.filters['car']:
                obj_type = "carro"
            elif cls_id == 8 and self.filters['boat']:
                obj_type = "bote"
            elif cls_id == 4 and self.filters['helicopter']:
                obj_type = "helicoptero"
            if obj_type is None:
                continue

            self.confirmed_tracks.add(yolo_id)
            x1, y1, x2, y2 = map(int, box)
            crop_img = frame[max(0, y1):min(h_f, y2), max(0, x1):min(w_f, x2)]

            need_reid = (yolo_id not in self.id_mapping) or (now - self.last_extraction_time.get(yolo_id, 0) > 1.0)
            if need_reid and reid_budget > 0 and crop_img.size > 0:
                real_id = self.get_true_id(yolo_id, crop_img)
                self.last_extraction_time[yolo_id] = now
                reid_budget -= 1
            else:
                real_id = self.id_mapping.get(yolo_id, yolo_id)

            if (self.ocr_enabled and obj_type == "carro" and self.ocr_worker is not None
                    and crop_img.shape[1] >= 60 and not self.plates.get(real_id)
                    and now - self.last_ocr_time.get(yolo_id, 0) > 1.5):
                self.last_ocr_time[yolo_id] = now
                self.ocr_worker.submit(real_id, crop_img)

            plate_text = self.plates.get(real_id, "")

            if real_id not in self.logged_ids and crop_img.size > 0:
                self.logged_ids.add(real_id)
                timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                img_path = self.save_dir / f"target_ch{self.channel_id}_{real_id}_{timestamp_str}.jpg"
                cv2.imwrite(str(img_path), crop_img)

                capture_data = {
                    "id": real_id,
                    "type": obj_type,
                    "conf": f"{conf * 100:.1f}%",
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "path": str(img_path),
                    "desc": f"Dim: {x2 - x1}x{y2 - y1} px | Certeza: {conf * 100:.1f}%" + (
                        f" | Placa: {plate_text}" if plate_text else "")
                }
                self.object_captured_signal.emit(capture_data)
                self.detection_log_signal.emit(f"CAPTURA TACTICA: {obj_type} Real-ID #{real_id} -> Registrado")

            frame_detections.append({
                'box': (x1, y1, x2, y2), 'type': obj_type,
                'conf': float(conf), 'id': real_id, 'plate': plate_text
            })

        if self.ai_frame_count % 100 == 0:
            self._prune(self.id_mapping)
            self._prune(self.last_extraction_time)
            self._prune(self.last_ocr_time)
            self._prune(self.plates)
            if len(self.confirmed_tracks) > 1000:
                self.confirmed_tracks.clear()

        return frame_detections

    # ------------------------------------------------------------ estadísticas
    def _update_stats(self, now):
        dt = now - self._stat_t
        if dt < 1.0:
            return

        g, w, nm = self.reader, self.ai_worker, self.network_monitor
        dec = g.frames_decoded if g else self.rendered_frames
        drop = g.frames_overwritten if g else 0
        ai_n = w.infer_count if w else 0
        gaps = g.gaps if (self.use_pyav and g) else 0

        s = self.stats
        s['rx_fps'] = (dec - self._prev['dec']) / dt
        s['render_fps'] = (self.rendered_frames - self._prev['ren']) / dt
        s['ai_fps'] = (ai_n - self._prev['ai']) / dt
        s['drop_ps'] = (drop - self._prev['drop']) / dt
        s['ai_ms'] = w.infer_ms if w else 0.0
        s['age_ms'] = g.last_age_ms if g else 0.0
        s['res'] = f"{g.width}x{g.height}" if (g and g.width) else "-"
        s['gui_skipped'] = self.gui_skipped

        if self.use_pyav and g:
            s['reconnects'] = g.reconnects
            s['state'] = g.state
            s['bitrate_kbps'] = g.bitrate_kbps
            s['gop'] = g.gop
            s['jitter_ms'] = g.jitter_ms
            s['gaps_ps'] = (gaps - self._prev['gaps']) / dt
            s['decode_ms'] = g.decode_ms
            s['backlog_ms'] = g.backlog_ms()
            s['resyncs'] = g.resyncs
            s['pkts_dropped'] = g.pkts_dropped
            s['decode_errors'] = g.decode_errors + g.corrupt_frames
            s['lat_rx_ms'] = g.lat_rx_ms
            s['error_code'] = g.last_error_code
            s['error_text'] = (g.last_error or error_text(g.last_error_code)) if g.last_error_code else ''
            s['codec'] = g.codec_name
            s['format'] = g.container_format
            s['no_packet_s'] = max(0.0, now - g.last_packet_time) if g.last_packet_time else 0.0
            s['no_frame_s'] = max(0.0, now - g.last_frame_time) if g.last_frame_time else 0.0
            s['stream_started'] = bool(g.frames_decoded > 0 or g.pkts_total > 0)
            # Paquetes por segundo aproximados desde la ventana estadistica.
            s['packet_rate'] = (g.pkts_total - self._prev.get('pkts', g.pkts_total)) / dt if dt > 0 else 0.0
        else:
            s['reconnects'] = self.reconnects

        if nm and nm.ip:
            s.update(ping_ms=nm.ping_ms, avg_ms=nm.avg_ms, jitter_ping_ms=nm.jitter_ms,
                     loss=nm.packet_loss, status=nm.status)

        self.render_fps = s['render_fps']
        self._prev = {'dec': dec, 'ren': self.rendered_frames, 'ai': ai_n, 'drop': drop, 'gaps': gaps,
                      'pkts': g.pkts_total if (self.use_pyav and g) else 0}
        self._stat_t = now
        self.network_stats_signal.emit(dict(s))

    # ------------------------------------------------------------ diagnostico consola
    def _console_debug_tick(self, now):
        """Emite una linea de diagnostico de red cada segundo, fuera del HUD."""
        if not self.debug_console or self.source_type != "NETWORK":
            return
        if now - self._console_stat_t < 1.0:
            return

        g = self.reader
        nm = self.network_monitor
        s = self.stats
        if g is None:
            console_log("NET", f"SOURCE={self.source} | READER=None | ERR-02 {error_text(2)}")
            self._console_stat_t = now
            return

        ping = f"{nm.ping_ms:.0f}ms" if nm and nm.ip else "N/A"
        avg = f"{nm.avg_ms:.0f}ms" if nm and nm.ip else "N/A"
        pj = f"{nm.jitter_ms:.0f}ms" if nm and nm.ip else "N/A"
        loss = f"{nm.packet_loss}%" if nm and nm.ip else "N/A"

        no_pkt = max(0.0, now - g.last_packet_time)
        no_frame = max(0.0, now - g.last_frame_time)

        level = "NET"
        if g.last_error_code in (3, 10):
            level = "ERROR"
        elif no_pkt > 1.5 or no_frame > 1.5:
            level = "WARN"

        console_log(
            level,
            f"SRC={self.source} | STATE={g.state} | CODEC={g.codec_name} | "
            f"RES={g.width}x{g.height} | BITRATE={g.bitrate_kbps:.0f}kbps | "
            f"RX={s['rx_fps']:.1f}fps RENDER={s['render_fps']:.1f}fps AI={s['ai_fps']:.1f}fps | "
            f"PING={ping} AVG={avg} PING_JIT={pj} LOSS_ICMP={loss} | "
            f"JIT_RX={g.jitter_ms:.1f}ms GAPS/s={s['gaps_ps']:.1f} | "
            f"DEC={g.decode_ms:.1f}ms AGE={g.last_age_ms:.1f}ms "
            f"NO_PKT={no_pkt:.1f}s NO_FRAME={no_frame:.1f}s | "
            f"PKTS={g.pkts_total} DROP_APP={g.pkts_dropped} OVERWRITE={g.frames_overwritten} | "
            f"RECON={g.reconnects} ERR_DEC={g.decode_errors} CORRUPT={g.corrupt_frames} "
            f"GUI_SKIP={self.gui_skipped} ERR={g.last_error_code}"
        )

        # ERR 8: la GUI esta reteniendo cuadros. No es perdida de red, sino
        # backpressure/consumo lento del lado Qt cuando esa opcion esta activa.
        gui_delta = self.gui_skipped - self._debug_last_gui_skipped
        if gui_delta > 0:
            console_log(
                "WARN",
                f"ERR-08 {error_text(8)} | saltados en el ultimo segundo={gui_delta} | "
                f"pending={self._gui_pending}"
            )
        self._debug_last_gui_skipped = self.gui_skipped

        # ERR 9: latencia interna alta. Esto NO es latencia extremo-a-extremo;
        # mide trabajo dentro del receptor desde la llegada del paquete hasta decode.
        if (g.lat_rx_ms > 250.0 or g.decode_ms > 80.0 or g.last_age_ms > 150.0) and (now - self._debug_last_latency_warning) > 5.0:
            console_log(
                "WARN",
                f"ERR-09 {error_text(9)} | lat_rx={g.lat_rx_ms:.1f}ms "
                f"decode={g.decode_ms:.1f}ms age={g.last_age_ms:.1f}ms"
            )
            self._debug_last_latency_warning = now

        # Error 3: trafico presente, pero no hay video.
        if g.frames_decoded > 0 and no_frame > 3.0 and no_pkt <= 1.5:
            if self._debug_last_stall_code != 3:
                console_log("ERROR", f"ERR-03 {error_text(3)} | paquetes siguen llegando")
                self._debug_last_stall_code = 3
        # Error 10: ni siquiera llegan paquetes.
        elif no_pkt > 3.0:
            if self._debug_last_stall_code != 10:
                console_log("ERROR", f"ERR-10 {error_text(10)} | sin paquetes desde {no_pkt:.1f}s")
                self._debug_last_stall_code = 10
        else:
            self._debug_last_stall_code = 0

        self._console_stat_t = now

    # ------------------------------------------------------------ bucle principal
    def run(self):
        stype = self.source_type
        if stype == "NETWORK" or self.ping_host:
            self.network_monitor = NetworkTelemetry(self.source, self.ping_host)

        cap = None
        if stype == "NETWORK":
            console_log("BOOT", f"NETWORK source={self.source} | HAS_AV={HAS_AV} | PyAV={getattr(av, '__version__', '?') if HAS_AV else 'N/A'}") if self.debug_console else None
            if not HAS_AV:
                msg = (
                    "ERROR: PyAV no esta instalado en este entorno. "
                    "La red (UDP/RTSP/etc.) requiere PyAV/FFmpeg. "
                    "Instala con: python -m pip install av"
                )
                if self.debug_console:
                    console_log("ERROR", f"ERR-01 {error_text(1)} | {msg}")
                self.detection_log_signal.emit(msg)
                self.connection_status_signal.emit(False, msg)
                return

            prepared = self._prepare_source_url(self.source)
            if self.debug_console:
                console_log(
                    "BOOT",
                    f"SOURCE_TYPE=NETWORK | ENGINE=PyAV/FFmpeg | URL={prepared} | "
                    f"RTSP={self.rtsp_transport} | UDP_FIFO={min(1024, max(256, int(self.udp_fifo_packets)))} "
                    f"UDP_BUF={min(262144, max(65536, int(self.udp_buffer_bytes)))}"
                )

            self.reader = FFmpegStreamReader(
                prepared,
                rtsp_transport=self.rtsp_transport,
                max_backlog_ms=self.max_latency_ms,
                udp_fifo_packets=self.udp_fifo_packets,
                udp_buffer_bytes=self.udp_buffer_bytes,
                frame_stall_timeout=4.0,
                packet_stall_timeout=4.0,
                debug_console=self.debug_console,
                log_fn=self.detection_log_signal.emit)
            self.reader.start()
        else:
            cap = self._open_capture_source()
            self.reader = self._start_local_grabber(cap)

        self.ai_worker = AIWorker(self)
        self.ai_worker.start()
        if HAS_TESSERACT:
            self.ocr_worker = OCRWorker(self.read_license_plate, self._on_plate)
            self.ocr_worker.start()

        self.connection_status_signal.emit(
            True, f"Sensor [{self.source}] iniciado ({self.engine_name}). Esperando video...")

        file_interval = 0.04
        if stype == "VIDEO_FILE" and cap is not None and cap.isOpened():
            file_interval = 1.0 / max(1.0, cap.get(cv2.CAP_PROP_FPS) or 25.0)

        self.start_time_uptime = time.time()
        self.last_frame_time = time.time()
        self._stat_t = time.time()

        colores = {'persona': (0, 255, 0), 'carro': (255, 165, 0),
                   'bote': (255, 0, 0), 'helicoptero': (0, 255, 255)}

        while self._is_running:
            loop_t0 = time.time()

            if stype == "NETWORK":
                # El lector PyAV/FFmpeg se reconecta solo; aquí únicamente consumimos cuadros.
                ret, frame = self.reader.read(timeout=0.05)
            elif stype == "VIDEO_FILE":
                ret, frame = cap.read()
            else:
                stalled = (loop_t0 - self.last_frame_time) > self.stall_timeout
                if not cap.isOpened() or stalled:
                    cap = self._reconnect_local(cap)
                    continue
                ret, frame = self.reader.read(timeout=0.05) if self.reader else (False, None)

            now = time.time()

            if ret and frame is not None and frame.size > 0 and frame.shape[0] > 10 and frame.shape[1] > 10:
                self.last_frame_time = now          # SOLO se actualiza con cuadros reales
                self.frame_count += 1
                self.rendered_frames += 1

                frame = self.enhance_frame(frame)
                self.ai_worker.submit_frame(frame)   # copia interna: los recortes quedan sin HUD

                detections = self.ai_worker.get_latest_detections()
                self.current_detections = detections

                for det in detections:
                    x1, y1, x2, y2 = det['box']
                    obj_type = det['type']
                    label = f"{obj_type.capitalize()} #{det['id']} ({det['conf'] * 100:.0f}%)"
                    if det['plate']:
                        label += f" | Placa: {det['plate']}"
                    color = colores.get(obj_type, (0, 255, 0))
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, label, (x1, max(y1 - 10, 15)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                h, w, _ = frame.shape
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cv2.rectangle(frame, (5, 5), (230, 30), (2, 6, 23), -1)
                cv2.putText(frame, f"HORA: {now_str}", (10, 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (56, 189, 248), 1)

                elapsed_sec = int(time.time() - self.start_time_uptime)
                uptime_str = time.strftime("%H:%M:%S", time.gmtime(elapsed_sec))
                cv2.rectangle(frame, (w - 180, 5), (w - 5, 30), (2, 6, 23), -1)
                cv2.putText(frame, f"UPTIME: {uptime_str}", (w - 170, 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (16, 185, 129), 1)

                if self.show_hud:
                    self.draw_network_hud(frame, h, w, cap)

                emit_ok = (now - self._last_emit) >= self._min_emit_interval
                if emit_ok and self.gui_backpressure:
                    with self._ack_lock:
                        if self._gui_pending >= 2:
                            emit_ok = False
                            self.gui_skipped += 1
                        else:
                            self._gui_pending += 1
                if emit_ok:
                    self._last_emit = now
                    self.change_pixmap_signal.emit(frame)
                    self.telemetry_signal.emit(self.render_fps, len(detections))

                if stype == "VIDEO_FILE":
                    time.sleep(max(0.0, file_interval - (time.time() - loop_t0)))
            else:
                # Sin cuadro nuevo: NO tocar last_frame_time (así el watchdog sí detecta cortes)
                if not self.use_pyav:
                    self._update_stats(now)
                if stype == "VIDEO_FILE":
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.last_frame_time = time.time()
                    time.sleep(0.01)

            # Estadisticas y diagnostico deben seguir corriendo aunque NO haya frame.
            now_diag = time.time()
            self._update_stats(now_diag)
            self._console_debug_tick(now_diag)

        if self.debug_console and self.source_type == "NETWORK" and self.reader:
            console_log(
                "STOP",
                f"STREAM detenido | RECON={self.reader.reconnects} | FRAMES={self.reader.frames_decoded} | "
                f"PKTS={self.reader.pkts_total} | ERR_DEC={self.reader.decode_errors} | "
                f"CORRUPT={self.reader.corrupt_frames} | LAST_ERR={self.reader.last_error_code}"
            )

        for wkr in (self.ai_worker, self.ocr_worker):
            if wkr:
                wkr.stop()
        if self.reader:
            self.reader.stop()
            self.reader.join(timeout=6.0)
        if cap is not None:
            cap.release()
        if self.network_monitor:
            self.network_monitor.stop()

    def get_current_detections(self):
        return self.current_detections

    def stop(self):
        self._is_running = False
        self.wait(10000)
