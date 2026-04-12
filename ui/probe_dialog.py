"""
Non-modal dialog that shows the result of a Probe / Query pick.

Displays a single node's data for the **active** contour field only.
The dialog stays open and updates in-place when the user picks a new
node or changes the active result / step.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt


class ProbeDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Probe Result")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        )

        self._label = QLabel()
        self._label.setFont(QFont("Consolas", 10))
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.addWidget(self._label)

    def set_result(self, node_id: int, x: float, y: float, z: float,
                   step: int, result_name: str, value: float):
        """Update the dialog with a new probe result."""
        text = (
            f"Node:    {node_id}\n"
            f"X:       {x:.3f}\n"
            f"Y:       {y:.3f}\n"
            f"Z:       {z:.3f}\n"
            f"Step:    {step}\n"
            f"Result:  {result_name}\n"
            f"Value:   {value:.4g}"
        )
        self._label.setText(text)
        self.adjustSize()
