"""
Franc3D-style parametric crack insertion wizard.

Five-page QDialog (QStackedWidget):
  0 — Crack Type
  1 — Geometry Parameters
  2 — Placement / Orientation
  3 — Meshing Template
  4 — Review / Finish

Signals
-------
preview_requested(object)   — emits CrackDefinition; main window generates preview
crack_accepted(object)      — emits CrackSurfaceState on Finish
cancelled()                 — user closed or clicked Cancel
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QStackedWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QRadioButton, QButtonGroup,
    QDoubleSpinBox, QSpinBox, QPushButton,
    QLineEdit, QFileDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from core.crack_geometry import CrackType, CrackDefinition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dbl_spin(lo: float, hi: float, step: float, dec: int,
              val: float) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setSingleStep(step)
    sb.setDecimals(dec)
    sb.setValue(val)
    return sb


def _int_spin(lo: int, hi: int, val: int) -> QSpinBox:
    sb = QSpinBox()
    sb.setRange(lo, hi)
    sb.setValue(val)
    return sb


# ---------------------------------------------------------------------------
# Page 0 — Crack Type
# ---------------------------------------------------------------------------

class _CrackTypePage(QWidget):

    _LABELS = {
        CrackType.ELLIPTICAL_SURFACE: "Elliptical / Surface Crack",
        CrackType.CORNER:             "Corner Crack",
        CrackType.EDGE:               "Edge Crack",
        CrackType.THROUGH:            "Through Crack",
        CrackType.USER_DEFINED:       "User-defined Crack (file)",
    }

    def __init__(self, defn: CrackDefinition, parent=None):
        super().__init__(parent)
        self._defn = defn

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Select crack type:</b>"))

        self._bg = QButtonGroup(self)
        for ctype, label in self._LABELS.items():
            rb = QRadioButton(label)
            rb.setProperty("crack_type", ctype)
            if ctype == defn.crack_type:
                rb.setChecked(True)
            self._bg.addButton(rb)
            layout.addWidget(rb)

        # User-defined file row (shown only for USER_DEFINED)
        self._file_row = QWidget()
        fr = QHBoxLayout(self._file_row)
        fr.setContentsMargins(20, 0, 0, 0)
        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText("Path to STL / BREP / STEP file…")
        self._file_edit.setText(defn.user_file_path)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_file)
        fr.addWidget(self._file_edit)
        fr.addWidget(browse_btn)
        layout.addWidget(self._file_row)

        layout.addStretch()
        self._update_file_row_visibility()
        self._bg.buttonClicked.connect(self._on_type_changed)
        self._file_edit.textChanged.connect(self._on_file_changed)

    def _on_type_changed(self, button: QRadioButton):
        self._defn.crack_type = button.property("crack_type")
        self._update_file_row_visibility()

    def _update_file_row_visibility(self):
        self._file_row.setVisible(
            self._defn.crack_type == CrackType.USER_DEFINED)

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Crack Geometry",
            self._file_edit.text(),
            "Geometry (*.stl *.brep *.brp *.step *.stp)"
        )
        if path:
            self._file_edit.setText(path)

    def _on_file_changed(self, text: str):
        self._defn.user_file_path = text


# ---------------------------------------------------------------------------
# Page 1 — Geometry Parameters
# ---------------------------------------------------------------------------

class _GeomParamsPage(QWidget):
    """Inner QStackedWidget: one sub-page per crack type."""

    changed = pyqtSignal()

    def __init__(self, defn: CrackDefinition, parent=None):
        super().__init__(parent)
        self._defn = defn

        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("<b>Geometry parameters:</b>"))

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)
        outer.addStretch()

        self._pages: dict[CrackType, int] = {}
        self._pages[CrackType.ELLIPTICAL_SURFACE] = self._stack.addWidget(
            self._make_elliptical())
        self._pages[CrackType.CORNER] = self._stack.addWidget(
            self._make_corner())
        self._pages[CrackType.EDGE] = self._stack.addWidget(
            self._make_edge())
        self._pages[CrackType.THROUGH] = self._stack.addWidget(
            self._make_through())
        self._pages[CrackType.USER_DEFINED] = self._stack.addWidget(
            self._make_user_defined())

        self.sync_type()

    # ---- sub-page builders -----------------------------------------------

    def _make_elliptical(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._a_ell = _dbl_spin(0.01, 1e5, 0.1, 3, self._defn.a)
        self._c_ell = _dbl_spin(0.01, 1e5, 0.1, 3, self._defn.c)
        self._ratio_lbl = QLabel()
        self._update_ratio()
        form.addRow("Semi-depth a:", self._a_ell)
        form.addRow("Half-width c:", self._c_ell)
        form.addRow("Aspect ratio a/c:", self._ratio_lbl)
        self._a_ell.valueChanged.connect(self._on_ell_changed)
        self._c_ell.valueChanged.connect(self._on_ell_changed)
        return w

    def _on_ell_changed(self):
        self._defn.a = self._a_ell.value()
        self._defn.c = self._c_ell.value()
        self._update_ratio()
        self.changed.emit()

    def _update_ratio(self):
        c = self._c_ell.value() if hasattr(self, "_c_ell") else self._defn.c
        a = self._a_ell.value() if hasattr(self, "_a_ell") else self._defn.a
        ratio = a / c if c != 0 else 0.0
        self._ratio_lbl.setText(f"{ratio:.3f}")

    def _make_corner(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._a_cor = _dbl_spin(0.01, 1e5, 0.1, 3, self._defn.a)
        self._c_cor = _dbl_spin(0.01, 1e5, 0.1, 3, self._defn.c)
        form.addRow("Semi-depth a:", self._a_cor)
        form.addRow("Half-width c:", self._c_cor)
        self._a_cor.valueChanged.connect(self._on_corner_changed)
        self._c_cor.valueChanged.connect(self._on_corner_changed)
        return w

    def _on_corner_changed(self):
        self._defn.a = self._a_cor.value()
        self._defn.c = self._c_cor.value()
        self.changed.emit()

    def _make_edge(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._a_edg = _dbl_spin(0.01, 1e5, 0.1, 3, self._defn.a)
        self._c_edg = _dbl_spin(0.01, 1e5, 0.1, 3, self._defn.c)
        form.addRow("Crack depth a:", self._a_edg)
        form.addRow("Crack width c:", self._c_edg)
        self._a_edg.valueChanged.connect(self._on_edge_changed)
        self._c_edg.valueChanged.connect(self._on_edge_changed)
        return w

    def _on_edge_changed(self):
        self._defn.a = self._a_edg.value()
        self._defn.c = self._c_edg.value()
        self.changed.emit()

    def _make_through(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._a_thr = _dbl_spin(0.01, 1e5, 0.1, 3, self._defn.a)
        self._t_thr = _dbl_spin(0.01, 1e5, 0.1, 3, self._defn.thickness)
        form.addRow("Half-length a:", self._a_thr)
        form.addRow("Plate thickness:", self._t_thr)
        self._a_thr.valueChanged.connect(self._on_through_changed)
        self._t_thr.valueChanged.connect(self._on_through_changed)
        return w

    def _on_through_changed(self):
        self._defn.a = self._a_thr.value()
        self._defn.thickness = self._t_thr.value()
        self.changed.emit()

    def _make_user_defined(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._mesh_sz = _dbl_spin(0.001, 1e4, 0.01, 3, 0.05)
        form.addRow("Mesh size:", self._mesh_sz)
        form.addRow("", QLabel("File selected on the previous page."))
        self._mesh_sz.valueChanged.connect(self._on_user_changed)
        return w

    def _on_user_changed(self):
        self._defn.mesh_refinement = self._mesh_sz.value()
        self.changed.emit()

    # ---- public ----------------------------------------------------------

    def sync_type(self):
        """Switch the inner stack to match defn.crack_type."""
        idx = self._pages.get(self._defn.crack_type, 0)
        self._stack.setCurrentIndex(idx)


# ---------------------------------------------------------------------------
# Page 2 — Placement / Orientation
# ---------------------------------------------------------------------------

class _PlacementPage(QWidget):

    changed = pyqtSignal()

    def __init__(self, defn: CrackDefinition, parent=None):
        super().__init__(parent)
        self._defn = defn

        layout = QVBoxLayout(self)

        # Translate group
        t_box = QGroupBox("Translate")
        t_form = QFormLayout(t_box)
        self._tx = _dbl_spin(-1e5, 1e5, 0.1, 3, defn.tx)
        self._ty = _dbl_spin(-1e5, 1e5, 0.1, 3, defn.ty)
        self._tz = _dbl_spin(-1e5, 1e5, 0.1, 3, defn.tz)
        t_form.addRow("X:", self._tx)
        t_form.addRow("Y:", self._ty)
        t_form.addRow("Z:", self._tz)
        layout.addWidget(t_box)

        # Rotate group
        r_box = QGroupBox("Rotate (°)")
        r_form = QFormLayout(r_box)
        self._rx = _dbl_spin(-360.0, 360.0, 1.0, 1, defn.rx)
        self._ry = _dbl_spin(-360.0, 360.0, 1.0, 1, defn.ry)
        self._rz = _dbl_spin(-360.0, 360.0, 1.0, 1, defn.rz)
        r_form.addRow("X:", self._rx)
        r_form.addRow("Y:", self._ry)
        r_form.addRow("Z:", self._rz)
        layout.addWidget(r_box)
        layout.addStretch()

        for sb in (self._tx, self._ty, self._tz,
                   self._rx, self._ry, self._rz):
            sb.valueChanged.connect(self._on_changed)

    def _on_changed(self):
        self._defn.tx = self._tx.value()
        self._defn.ty = self._ty.value()
        self._defn.tz = self._tz.value()
        self._defn.rx = self._rx.value()
        self._defn.ry = self._ry.value()
        self._defn.rz = self._rz.value()
        self.changed.emit()

    def placement_values(self):
        return (self._tx.value(), self._ty.value(), self._tz.value(),
                self._rx.value(), self._ry.value(), self._rz.value())


# ---------------------------------------------------------------------------
# Page 3 — Meshing Template
# ---------------------------------------------------------------------------

class _MeshingPage(QWidget):

    changed = pyqtSignal()

    def __init__(self, defn: CrackDefinition, parent=None):
        super().__init__(parent)
        self._defn = defn

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Crack-front meshing template:</b>"))

        form_box = QGroupBox()
        form = QFormLayout(form_box)

        self._radius = _dbl_spin(0.01, 10.0, 0.05, 3, defn.template_radius)
        self._nfront = _int_spin(3, 200, defn.front_point_count)
        self._refine = _dbl_spin(0.1, 5.0, 0.1, 2, defn.mesh_refinement)

        self._radius.setToolTip(
            "Refinement zone radius around the crack front, "
            "relative to semi-depth a")
        self._nfront.setToolTip("Target number of nodes along the crack front")
        self._refine.setToolTip(
            "Mesh density multiplier (1.0 = default, >1 = coarser, <1 = finer)")

        form.addRow("Template radius:", self._radius)
        form.addRow("Front point count:", self._nfront)
        form.addRow("Mesh refinement:", self._refine)
        layout.addWidget(form_box)
        layout.addStretch()

        self._radius.valueChanged.connect(self._on_changed)
        self._nfront.valueChanged.connect(self._on_changed)
        self._refine.valueChanged.connect(self._on_changed)

    def _on_changed(self):
        self._defn.template_radius   = self._radius.value()
        self._defn.front_point_count = self._nfront.value()
        self._defn.mesh_refinement   = self._refine.value()
        self.changed.emit()


# ---------------------------------------------------------------------------
# Page 4 — Review / Finish
# ---------------------------------------------------------------------------

class _ReviewPage(QWidget):

    def __init__(self, defn: CrackDefinition, parent=None):
        super().__init__(parent)
        self._defn = defn

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Review crack definition:</b>"))

        self._summary = QLabel()
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(False)
        font = self._summary.font()
        font.setFamily("Consolas, monospace")
        self._summary.setFont(font)
        self._summary.setStyleSheet(
            "background: palette(base); padding: 8px; border: 1px solid palette(mid);")

        layout.addWidget(self._summary)
        layout.addStretch()

    def update_summary(self, defn: CrackDefinition,
                       n_verts: int = 0, n_tris: int = 0, n_front: int = 0):
        type_names = {
            CrackType.ELLIPTICAL_SURFACE: "Elliptical / Surface",
            CrackType.CORNER:             "Corner",
            CrackType.EDGE:               "Edge",
            CrackType.THROUGH:            "Through",
            CrackType.USER_DEFINED:       "User-defined",
        }
        lines = [
            f"{'Type:':<22}{type_names[defn.crack_type]}",
            f"{'Semi-depth a:':<22}{defn.a:.3f}",
            f"{'Half-width c:':<22}{defn.c:.3f}",
        ]
        if defn.crack_type == CrackType.THROUGH:
            lines.append(f"{'Plate thickness:':<22}{defn.thickness:.3f}")
        if defn.crack_type == CrackType.USER_DEFINED:
            lines.append(f"{'File:':<22}{defn.user_file_path or '(none)'}")
        lines += [
            "",
            f"{'Translate:':<22}({defn.tx:.3f}, {defn.ty:.3f}, {defn.tz:.3f})",
            f"{'Rotate (°):':<22}({defn.rx:.1f}, {defn.ry:.1f}, {defn.rz:.1f})",
            "",
            f"{'Front points:':<22}{defn.front_point_count}",
            f"{'Template radius:':<22}{defn.template_radius:.3f}",
            f"{'Mesh refinement:':<22}{defn.mesh_refinement:.2f}",
        ]
        if n_verts or n_tris or n_front:
            lines += [
                "─" * 38,
                f"{'Vertices:':<22}{n_verts}",
                f"{'Triangles:':<22}{n_tris}",
                f"{'Front nodes:':<22}{n_front}",
            ]
        self._summary.setText("\n".join(lines))


# ---------------------------------------------------------------------------
# Main wizard dialog
# ---------------------------------------------------------------------------

class CrackInsertWizard(QDialog):

    preview_requested = pyqtSignal(object)    # CrackDefinition
    crack_accepted    = pyqtSignal(object)    # CrackSurfaceState
    cancelled         = pyqtSignal()

    _PAGE_TITLES = [
        "Step 1 of 5 — Crack Type",
        "Step 2 of 5 — Geometry Parameters",
        "Step 3 of 5 — Placement / Orientation",
        "Step 4 of 5 — Meshing Template",
        "Step 5 of 5 — Review & Finish",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Crack")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(400)

        self._defn = CrackDefinition()
        self._committed = False
        self._last_state = None        # cached preview CrackSurfaceState
        self._n_verts = self._n_tris = self._n_front = 0

        # Debounce timer for geometry preview (avoids spamming gmsh)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(300)
        self._preview_timer.timeout.connect(self._emit_preview)

        # Build pages
        self._p0 = _CrackTypePage(self._defn)
        self._p1 = _GeomParamsPage(self._defn)
        self._p2 = _PlacementPage(self._defn)
        self._p3 = _MeshingPage(self._defn)
        self._p4 = _ReviewPage(self._defn)

        # Connect page signals
        self._p1.changed.connect(self._schedule_preview)
        self._p2.changed.connect(self._on_placement_changed)
        self._p3.changed.connect(self._schedule_preview)

        # Stack
        self._stack = QStackedWidget()
        for page in (self._p0, self._p1, self._p2, self._p3, self._p4):
            self._stack.addWidget(page)

        # Title label
        self._title_lbl = QLabel(self._PAGE_TITLES[0])
        font = self._title_lbl.font()
        font.setBold(True)
        self._title_lbl.setFont(font)

        # Navigation buttons
        self._btn_back   = QPushButton("< Back")
        self._btn_next   = QPushButton("Next >")
        self._btn_finish = QPushButton("Finish")
        self._btn_cancel = QPushButton("Cancel")

        self._btn_back.setEnabled(False)
        self._btn_finish.setEnabled(False)

        self._btn_back.clicked.connect(self._go_back)
        self._btn_next.clicked.connect(self._go_next)
        self._btn_finish.clicked.connect(self._on_finish)
        self._btn_cancel.clicked.connect(self._on_cancel)

        nav = QHBoxLayout()
        nav.addWidget(self._btn_cancel)
        nav.addStretch()
        nav.addWidget(self._btn_back)
        nav.addWidget(self._btn_next)
        nav.addWidget(self._btn_finish)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_lbl)
        layout.addWidget(self._stack)
        layout.addLayout(nav)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _current_index(self) -> int:
        return self._stack.currentIndex()

    def _go_back(self):
        idx = self._current_index()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
            self._on_page_changed(idx - 1)

    def _go_next(self):
        idx = self._current_index()
        if idx == 0:
            # Sync geometry page to selected crack type
            self._p1.sync_type()
        if idx < self._stack.count() - 1:
            self._stack.setCurrentIndex(idx + 1)
            self._on_page_changed(idx + 1)

    def _on_page_changed(self, idx: int):
        self._title_lbl.setText(self._PAGE_TITLES[idx])
        self._btn_back.setEnabled(idx > 0)
        self._btn_next.setEnabled(idx < self._stack.count() - 1)
        self._btn_finish.setEnabled(idx == self._stack.count() - 1)

        if idx == self._stack.count() - 1:
            # Arriving on Review page: update summary with cached stats
            self._p4.update_summary(
                self._defn, self._n_verts, self._n_tris, self._n_front)
            # Trigger a fresh preview so stats are current
            self._schedule_preview()

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _schedule_preview(self):
        """Restart debounce timer — preview fires 300 ms after last change."""
        self._preview_timer.start()

    def _on_placement_changed(self):
        """Placement page: use fast actor transform, not full regeneration."""
        self.preview_requested.emit(self._defn)

    def _emit_preview(self):
        """Called by debounce timer: emit for full mesh regeneration."""
        self.preview_requested.emit(self._defn)

    def update_preview_stats(self, n_verts: int, n_tris: int, n_front: int):
        """Called by MainWindow after a successful preview generation."""
        self._n_verts  = n_verts
        self._n_tris   = n_tris
        self._n_front  = n_front
        # Refresh Review page if it's currently shown
        if self._current_index() == self._stack.count() - 1:
            self._p4.update_summary(
                self._defn, n_verts, n_tris, n_front)

    # ------------------------------------------------------------------
    # Finish / Cancel
    # ------------------------------------------------------------------

    def _on_finish(self):
        from core.crack_geometry import generate_crack_mesh
        try:
            state = generate_crack_mesh(self._defn)
        except Exception as exc:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Crack Generation Failed", str(exc))
            return
        self._committed = True
        self.crack_accepted.emit(state)
        self.close()

    def _on_cancel(self):
        self.cancelled.emit()
        self._committed = True
        self.close()

    def closeEvent(self, event):
        if not self._committed:
            self.cancelled.emit()
        super().closeEvent(event)
