import sys
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from scia.main_window import SciaGui
from scia.shared.ui import resources_rc
from scia.shared.ui.theme import apply_global_theme


def main() -> None:
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(":/icons/app"))
    apply_global_theme(app)
    window = SciaGui()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec())
