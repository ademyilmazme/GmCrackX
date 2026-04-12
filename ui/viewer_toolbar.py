"""
Compact viewport toolbar — camera presets, display modes, visibility toggles.

Sits directly above the QVTKRenderWindowInteractor inside ViewerWidget.
Visually distinct from the main workflow toolbar: smaller, flat, neutral.

Layout
------
  [Fit][Reset] | [Front][Top][Right][Iso] | [Wire][Surface][S+Edge] | [Mesh][Crack][Edges]
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QToolButton, QFrame, QButtonGroup,
)
from PyQt6.QtCore import Qt


# =====================================================================
# Stylesheet
# =====================================================================

_STYLE = """
/* ── toolbar strip ─────────────────────────────────── */
QWidget#viewerToolbar {
    background: qlineargradient(y1:0, y2:1,
                stop:0 #eef0f2, stop:1 #e2e5e8);
    border-bottom: 1px solid #c0c4c8;
}

/* ── buttons ───────────────────────────────────────── */
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 2px 7px;
    font-size: 8pt;
    color: #3c4650;
    margin: 1px 0px;
    min-height: 16px;
}

QToolButton:hover {
    background: #d4dce4;
    border: 1px solid #a0aeb8;
}

QToolButton:pressed {
    background: #c0ccd6;
    border: 1px solid #8898a8;
}

QToolButton:checked {
    background: #c4d4e4;
    border: 1px solid #8898b0;
    font-weight: bold;
}

QToolButton:disabled {
    color: #b0b8c0;
}

/* ── vertical separators ───────────────────────────── */
QFrame#vsep {
    background: #c0c4c8;
    max-width: 1px;
    min-width: 1px;
    margin: 3px 5px;
}
"""


class ViewerToolbar(QWidget):
    """Compact viewport control bar for camera, display, and visibility."""

    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self._viewer = viewer
        self.setObjectName("viewerToolbar")
        self.setStyleSheet(_STYLE)
        self.setFixedHeight(26)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(1)

        # ── Camera ──────────────────────────────────────────
        self._btn("Fit",   "Reset camera to fit all objects", self._fit, lay)
        self._btn("Reset", "Reset to default isometric view", self._reset, lay)
        self._sep(lay)

        # ── Preset views ────────────────────────────────────
        self._btn("Front", "View from front (-Z)",   self._front, lay)
        self._btn("Top",   "View from top (-Y)",     self._top,   lay)
        self._btn("Right", "View from right (-X)",   self._right, lay)
        self._btn("Iso",   "Standard isometric view", self._iso,  lay)
        self._sep(lay)

        # ── Display mode (exclusive) ────────────────────────
        dg = QButtonGroup(self)
        dg.setExclusive(True)
        self._btn("Wire",    "Wireframe",        self._wire,  lay, checkable=True, group=dg)
        self._btn("Surface", "Solid surface",    self._surf,  lay, checkable=True, group=dg)
        b = self._btn("S+Edge", "Surface + edges", self._sedge, lay, checkable=True, group=dg)
        b.setChecked(True)
        self._sep(lay)

        # ── Visibility toggles ──────────────────────────────
        bm = self._btn("Mesh",  "Toggle global-mesh visibility",    self._toggle_mesh,  lay, checkable=True)
        bc = self._btn("Crack", "Toggle crack-surface visibility",  self._toggle_crack, lay, checkable=True)
        be = self._btn("Edges", "Toggle edge-line visibility",      self._toggle_edges, lay, checkable=True)
        bm.setChecked(True)
        bc.setChecked(True)
        be.setChecked(True)

        lay.addStretch()

    # ── helpers ─────────────────────────────────────────────

    def _btn(self, text: str, tip: str, slot, layout,
             *, checkable: bool = False,
             group: QButtonGroup | None = None) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.clicked.connect(slot)
        if group is not None:
            group.addButton(b)
        layout.addWidget(b)
        return b

    @staticmethod
    def _sep(layout):
        s = QFrame()
        s.setObjectName("vsep")
        s.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(s)

    # ── camera ──────────────────────────────────────────────

    def _fit(self):
        self._viewer.fit_all()

    def _reset(self):
        self._viewer.reset_view()

    def _front(self):
        self._viewer.view_front()

    def _top(self):
        self._viewer.view_top()

    def _right(self):
        self._viewer.view_right()

    def _iso(self):
        self._viewer.view_isometric()

    # ── display mode ────────────────────────────────────────

    def _wire(self):
        self._viewer.set_display_mode("wireframe")

    def _surf(self):
        self._viewer.set_display_mode("surface")

    def _sedge(self):
        self._viewer.set_display_mode("surface_edges")

    # ── visibility ──────────────────────────────────────────

    def _toggle_mesh(self, checked: bool):
        self._viewer.set_actor_visibility("Global Mesh", checked)
        self._viewer.set_actor_visibility("Solid", checked)

    def _toggle_crack(self, checked: bool):
        self._viewer.set_actor_visibility("Crack Surface", checked)

    def _toggle_edges(self, checked: bool):
        self._viewer.set_edges_visible(checked)
