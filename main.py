# main.py
import sys
import ctypes
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from ui.main_window import MainWindow

if __name__ == "__main__":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DetectorV5")
    except AttributeError:
        pass

    app = QApplication(sys.argv)

    icon_path = Path(__file__).parent / "resources" / "assets" / "logo_white.ico"
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)

    window = MainWindow()

    if icon_path.exists():  
        window.setWindowIcon(app_icon)
    else:
        print("Ruta de icono no encontrada")

    window.showMaximized()

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        window.close()
        sys.exit(0)