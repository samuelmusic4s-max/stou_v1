from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QLabel, QSizePolicy, QToolBar, QWidget

from scia.shared.ui.theme import PALETTE, make_icon

NAV_ITEMS = [
    ("home", "Inicio", ":/icons/home"),
    ("tasks", "Tareas", ":/icons/tasks"),
    ("document", "Proyectos", ":/icons/document"),
    ("sources", "Subidos", ":/icons/sources"),
]

SETTINGS_ITEM = ("settings", "Configuración", ":/icons/settings")


class Sidebar(QToolBar):
    page_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Navegación", parent)
        self.setObjectName("sidebar")
        self.setOrientation(Qt.Orientation.Vertical)
        self.setMovable(False)
        self.setFloatable(False)
        self.setFixedWidth(196)
        self.setIconSize(QSize(18, 18))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        self._group = QActionGroup(self)
        self._group.setExclusive(True)
        self._actions: dict[str, QAction] = {}

        brand = QLabel(
            f'SC<span style="color:{PALETTE["accent"]};">.IA</span>'
        )
        brand.setObjectName("sidebarBrand")
        self.addWidget(brand)

        for key, label, icon in NAV_ITEMS:
            self._add_nav_action(key, label, icon)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.addWidget(spacer)

        self._add_nav_action(*SETTINGS_ITEM)
        self.set_active_page("home")

    def _add_nav_action(self, key: str, label: str, icon: str):
        action = QAction(
            make_icon(
                icon,
                color=PALETTE["text_secondary"],
                active=PALETTE["primary_light"],
            ),
            f"  {label}",
            self,
        )
        action.setCheckable(True)
        action.triggered.connect(lambda _=False, k=key: self.page_selected.emit(k))
        self._group.addAction(action)
        self.addAction(action)
        self._actions[key] = action

    def set_active_page(self, key: str):
        if key in self._actions:
            self._actions[key].setChecked(True)
