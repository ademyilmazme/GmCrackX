"""
ANSYS Mechanical-style ribbon widget infrastructure.

Three reusable classes that know nothing about GmCrackX logic:

  RibbonPanel — bordered group of buttons with a title label
  RibbonTab   — horizontal row of panels (one per tab page)
  RibbonBar   — tabbed container with ribbon styling

The visual result::

    [ File ][ Home ][ Result ][ Display ]        <- dark tab bar
    +----------------------------------------------+
    | ┌─ LOAD ────┐ ┌─ PROJECT ──┐                |  <- light content
    | | [Load FRD]| | [Save]     |                |
    | | [Load  …] | | [Open]     |                |
    | └───────────┘ └────────────┘                 |
    +----------------------------------------------+
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QToolButton, QTabWidget,
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt


# =====================================================================
# Stylesheet — scoped to RibbonBar and its descendants
# =====================================================================

_RIBBON_STYLE = """
/* ── dark background visible behind / around tabs ──── */
QWidget#ribbonBar {
    background: #4a5668;
}

/* ── tab content pane (white) ──────────────────────── */
QTabWidget#ribbonTabs::pane {
    background: #ffffff;
    border: 1px solid #d0d3d8;
    border-top: none;
    top: -1px;
}

/* ── tab-bar alignment ─────────────────────────────── */
QTabWidget#ribbonTabs::tab-bar {
    left: 0px;
}

/* ── individual tab buttons ────────────────────────── */
QTabWidget#ribbonTabs > QTabBar::tab {
    background: #ffffff;
    color: #5a6270;
    font-size: 9pt;
    font-weight: 600;
    padding: 5px 18px;
    border: 1px solid #d0d3d8;
    border-bottom: none;
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
    margin-right: 1px;
    min-width: 54px;
}

QTabWidget#ribbonTabs > QTabBar::tab:selected {
    background: #ffffff;
    color: #2c3e50;
    border: 1px solid #d0d3d8;
    border-bottom: 1px solid #ffffff;
    margin-bottom: -1px;
}

QTabWidget#ribbonTabs > QTabBar::tab:hover:!selected {
    background: #e8edf2;
    color: #2c3e50;
}

QTabWidget#ribbonTabs > QTabBar::tab:!selected {
    margin-top: 2px;
}

/* ── panel group frames ────────────────────────────── */
QFrame#ribbonPanel {
    background: transparent;
    border: none;
}

/* ── panel title (bottom label) ────────────────────── */
QLabel#panelTitle {
    font-size: 7pt;
    font-weight: 600;
    color: #78808a;
    background: transparent;
    border: none;
    border-top: 1px solid #d4d8dc;
    padding: 1px 0px;
    margin-top: 2px;
}

/* ── thin vertical separator between panels ────────── */
QFrame#panelSep {
    background: #c4c8ce;
    margin: 6px 3px;
}

/* ── standard action buttons ───────────────────────── */
QToolButton#actionBtn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 4px 11px;
    font-size: 9pt;
    color: #2c3e50;
    min-height: 20px;
}

QToolButton#actionBtn:hover {
    background: qlineargradient(y1:0, y2:1,
                stop:0 #dce6f0, stop:1 #c8d8ea);
    border: 1px solid #8fb0d0;
}

QToolButton#actionBtn:pressed {
    background: qlineargradient(y1:0, y2:1,
                stop:0 #c0d2e4, stop:1 #a8c0d8);
    border: 1px solid #7098c0;
}

QToolButton#actionBtn:disabled {
    color: #b0b8c2;
}

/* ── Run button (emphasised green) ─────────────────── */
QToolButton#runBtn {
    background: qlineargradient(y1:0, y2:1,
                stop:0 #5cb85c, stop:1 #449d44);
    color: white;
    font-weight: bold;
    font-size: 10pt;
    border: 1px solid #398039;
    border-radius: 3px;
    padding: 5px 24px;
    min-height: 22px;
}

QToolButton#runBtn:hover {
    background: qlineargradient(y1:0, y2:1,
                stop:0 #6cca6c, stop:1 #4fb04f);
    border: 1px solid #2d6b2d;
}

QToolButton#runBtn:pressed {
    background: qlineargradient(y1:0, y2:1,
                stop:0 #449d44, stop:1 #398039);
}

QToolButton#runBtn:disabled {
    background: qlineargradient(y1:0, y2:1,
                stop:0 #c4c8cc, stop:1 #b0b4b8);
    color: #e0e4e8;
    border: 1px solid #a0a4a8;
}

/* ── toggle / checkable buttons ────────────────────── */
QToolButton#toggleBtn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 4px 10px;
    font-size: 9pt;
    color: #2c3e50;
    min-height: 20px;
}

QToolButton#toggleBtn:hover {
    background: #d4dce6;
    border: 1px solid #a0b0c4;
}

QToolButton#toggleBtn:checked {
    background: #c0d0e4;
    border: 1px solid #8098b8;
    font-weight: bold;
}

QToolButton#toggleBtn:pressed {
    background: #b0c4d8;
    border: 1px solid #7090b0;
}
"""


# =====================================================================
# RibbonPanel
# =====================================================================

class RibbonPanel(QFrame):
    """Bordered group of buttons with a centred title at the bottom.

    ::

        ┌──────────────────────────┐
        │  [Btn A]  [Btn B]        │   <- button row
        │..........................│
        │        TITLE             │   <- centred small title
        └──────────────────────────┘
    """

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ribbonPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 2)
        root.setSpacing(0)

        self._btn_row = QHBoxLayout()
        self._btn_row.setContentsMargins(0, 0, 0, 0)
        self._btn_row.setSpacing(2)
        root.addLayout(self._btn_row, 1)

        lbl = QLabel(title)
        lbl.setObjectName("panelTitle")
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(lbl)

    def add_button(self, action: QAction, *,
                   emphasise: bool = False) -> QToolButton:
        """Add an action as a styled QToolButton.

        The button type is chosen automatically:
        - *emphasise* → green ``runBtn``
        - *action.isCheckable()* → ``toggleBtn``
        - otherwise → ``actionBtn``

        Returns the button so the caller can add it to a
        ``QButtonGroup`` / ``QActionGroup`` if needed.
        """
        btn = QToolButton()
        btn.setDefaultAction(action)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        if emphasise:
            btn.setObjectName("runBtn")
        elif action.isCheckable():
            btn.setObjectName("toggleBtn")
        else:
            btn.setObjectName("actionBtn")

        self._btn_row.addWidget(btn)
        return btn


# =====================================================================
# RibbonTab
# =====================================================================

class RibbonTab(QWidget):
    """A single tab page containing a horizontal row of ``RibbonPanel``s."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 2, 6, 0)
        self._layout.setSpacing(0)
        self._has_panels = False
        self._finished = False

    def add_panel(self, title: str) -> RibbonPanel:
        """Create a new panel group and append it to this tab."""
        if self._has_panels:
            sep = QFrame()
            sep.setObjectName("panelSep")
            sep.setFixedWidth(1)
            self._layout.addWidget(sep)
        self._has_panels = True

        panel = RibbonPanel(title)
        self._layout.addWidget(panel)
        return panel

    def finish(self):
        """Add a terminal stretch.  Call once after all panels are added."""
        if not self._finished:
            self._layout.addStretch()
            self._finished = True


# =====================================================================
# RibbonBar
# =====================================================================

class RibbonBar(QWidget):
    """ANSYS Mechanical-style tabbed ribbon bar.

    Dark tab-bar background with a light content pane below.
    The selected tab blends seamlessly into the content area.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ribbonBar")
        self.setFixedHeight(85)
        self.setStyleSheet(_RIBBON_STYLE)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("ribbonTabs")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._tabs)

    def add_tab(self, title: str) -> RibbonTab:
        """Create a new ribbon tab and return it for population."""
        tab = RibbonTab()
        self._tabs.addTab(tab, title)
        return tab

    def set_current_tab(self, index: int):
        """Switch to a specific tab by index."""
        if 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)
