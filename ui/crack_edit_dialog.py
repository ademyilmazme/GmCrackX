"""
Non-modal dialog for translating and rotating the crack surface.

Emits *transform_changed* on every spinbox tick (live VTK preview)
and *accepted_transform* when the user clicks Apply or OK.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QDoubleSpinBox, QPushButton, QGroupBox, QLabel,
)
from PyQt6.QtCore import Qt, pyqtSignal


class CrackEditDialog(QDialog):

    transform_changed = pyqtSignal(float, float, float, float, float, float)
    accepted_transform = pyqtSignal(float, float, float, float, float, float)
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Crack")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        )

        self._centroid: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._committed = False

        # --- Delta spinboxes ---------------------------------------------
        self._tx = self._make_translate_spin()
        self._ty = self._make_translate_spin()
        self._tz = self._make_translate_spin()
        self._rx = self._make_rotate_spin()
        self._ry = self._make_rotate_spin()
        self._rz = self._make_rotate_spin()

        delta_form = QFormLayout()
        delta_form.addRow("Translate X", self._tx)
        delta_form.addRow("Translate Y", self._ty)
        delta_form.addRow("Translate Z", self._tz)
        delta_form.addRow("Rotate X",    self._rx)
        delta_form.addRow("Rotate Y",    self._ry)
        delta_form.addRow("Rotate Z",    self._rz)

        delta_box = QGroupBox("Transform (delta)")
        delta_box.setLayout(delta_form)

        # --- Last-applied display ----------------------------------------
        self._lbl_tx = QLabel("0.000")
        self._lbl_ty = QLabel("0.000")
        self._lbl_tz = QLabel("0.000")
        self._lbl_rx = QLabel("0.0°")
        self._lbl_ry = QLabel("0.0°")
        self._lbl_rz = QLabel("0.0°")

        applied_form = QFormLayout()
        applied_form.addRow("Translate X", self._lbl_tx)
        applied_form.addRow("Translate Y", self._lbl_ty)
        applied_form.addRow("Translate Z", self._lbl_tz)
        applied_form.addRow("Rotate X",    self._lbl_rx)
        applied_form.addRow("Rotate Y",    self._lbl_ry)
        applied_form.addRow("Rotate Z",    self._lbl_rz)

        applied_box = QGroupBox("Last applied")
        applied_box.setLayout(applied_form)

        # --- Buttons -----------------------------------------------------
        btn_apply  = QPushButton("Apply")
        btn_ok     = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_reset  = QPushButton("Reset")

        btn_apply.clicked.connect(self._on_apply)
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel.clicked.connect(self._on_cancel)
        btn_reset.clicked.connect(self._on_reset)

        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_reset)

        # --- Main layout -------------------------------------------------
        layout = QVBoxLayout(self)
        layout.addWidget(delta_box)
        layout.addWidget(applied_box)
        layout.addLayout(btn_row)

        # Live preview on every value change
        for sb in (self._tx, self._ty, self._tz,
                   self._rx, self._ry, self._rz):
            sb.valueChanged.connect(self._emit_transform)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def set_centroid(self, cx: float, cy: float, cz: float) -> None:
        self._centroid = (cx, cy, cz)

    def reset_values(self) -> None:
        for sb in (self._tx, self._ty, self._tz,
                   self._rx, self._ry, self._rz):
            sb.blockSignals(True)
            sb.setValue(0.0)
            sb.blockSignals(False)
        self._emit_transform()

    def set_last_applied(self, tx: float, ty: float, tz: float,
                         rx: float, ry: float, rz: float) -> None:
        """Update the 'Last applied' group with the values that were committed."""
        self._lbl_tx.setText(f"{tx:.3f}")
        self._lbl_ty.setText(f"{ty:.3f}")
        self._lbl_tz.setText(f"{tz:.3f}")
        self._lbl_rx.setText(f"{rx:.1f}°")
        self._lbl_ry.setText(f"{ry:.1f}°")
        self._lbl_rz.setText(f"{rz:.1f}°")

    def values(self) -> tuple[float, float, float, float, float, float]:
        return (self._tx.value(), self._ty.value(), self._tz.value(),
                self._rx.value(), self._ry.value(), self._rz.value())

    # -----------------------------------------------------------------
    # Private
    # -----------------------------------------------------------------

    @staticmethod
    def _make_translate_spin() -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(-10000.0, 10000.0)
        sb.setSingleStep(0.1)
        sb.setDecimals(3)
        sb.setValue(0.0)
        return sb

    @staticmethod
    def _make_rotate_spin() -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(-360.0, 360.0)
        sb.setSingleStep(1.0)
        sb.setDecimals(1)
        sb.setValue(0.0)
        return sb

    def _emit_transform(self) -> None:
        self.transform_changed.emit(*self.values())

    def _on_apply(self) -> None:
        self._committed = True
        self.accepted_transform.emit(*self.values())

    def _on_ok(self) -> None:
        self._committed = True
        self.accepted_transform.emit(*self.values())
        self.close()

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self._committed = True  # prevent double-emit in closeEvent
        self.close()

    def _on_reset(self) -> None:
        self.reset_values()

    def closeEvent(self, event) -> None:
        if not self._committed:
            self.cancelled.emit()
        super().closeEvent(event)
