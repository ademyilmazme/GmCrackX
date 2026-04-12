"""
Non-modal animation dialog for stepping through crack propagation results.

Controls
--------
  |<   First step
  <    Previous step
  Play / Pause toggle
  >    Next step
  >|   Last step
  Slider — scrub to any step
  Speed spinner (1–30 fps, default 5)
  Loop checkbox

Emits ``step_changed(index)`` whenever the active frame changes.
The caller maps *index* → actual propagation increment number.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QCheckBox, QSpinBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont


class AnimationDialog(QDialog):
    step_changed = pyqtSignal(int)          # 0-based index into step list
    save_requested = pyqtSignal()           # user clicked Save

    def __init__(self, n_steps: int,
                 step_names: list[str] | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Animate Steps")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMinimumWidth(400)

        self._n_steps = n_steps
        self._names = step_names or [f"Step {i}" for i in range(n_steps)]
        self._current = 0
        self._playing = False

        # --- Timer ---
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

        # --- Transport buttons ---
        ctrl = QHBoxLayout()

        self._btn_first = QPushButton("|<")
        self._btn_first.setFixedWidth(36)
        self._btn_first.setToolTip("First step")
        self._btn_first.clicked.connect(self._go_first)

        self._btn_prev = QPushButton("<")
        self._btn_prev.setFixedWidth(36)
        self._btn_prev.setToolTip("Previous step")
        self._btn_prev.clicked.connect(self._go_prev)

        self._btn_play = QPushButton("\u25b6")      # ▶
        self._btn_play.setFixedWidth(56)
        self._btn_play.setToolTip("Play / Pause")
        self._btn_play.clicked.connect(self._toggle_play)

        self._btn_next = QPushButton(">")
        self._btn_next.setFixedWidth(36)
        self._btn_next.setToolTip("Next step")
        self._btn_next.clicked.connect(self._go_next)

        self._btn_last = QPushButton(">|")
        self._btn_last.setFixedWidth(36)
        self._btn_last.setToolTip("Last step")
        self._btn_last.clicked.connect(self._go_last)

        self._step_label = QLabel(self._format_label())
        self._step_label.setFont(QFont("Segoe UI", 9))
        self._step_label.setMinimumWidth(140)

        ctrl.addWidget(self._btn_first)
        ctrl.addWidget(self._btn_prev)
        ctrl.addWidget(self._btn_play)
        ctrl.addWidget(self._btn_next)
        ctrl.addWidget(self._btn_last)
        ctrl.addSpacing(12)
        ctrl.addWidget(self._step_label)
        ctrl.addStretch()

        # --- Slider ---
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, max(n_steps - 1, 0))
        self._slider.setValue(0)
        self._slider.valueChanged.connect(self._on_slider)

        # --- Options ---
        opts = QHBoxLayout()

        opts.addWidget(QLabel("Speed:"))
        self._fps_spin = QSpinBox()
        self._fps_spin.setRange(1, 30)
        self._fps_spin.setValue(5)
        self._fps_spin.setSuffix(" fps")
        self._fps_spin.valueChanged.connect(self._on_fps_changed)
        opts.addWidget(self._fps_spin)

        opts.addSpacing(16)
        self._loop_cb = QCheckBox("Loop")
        opts.addWidget(self._loop_cb)

        opts.addStretch()

        self._btn_save = QPushButton("Save\u2026")
        self._btn_save.setToolTip("Export animation as GIF or PNG sequence")
        self._btn_save.clicked.connect(self._on_save)
        opts.addWidget(self._btn_save)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.addLayout(ctrl)
        layout.addWidget(self._slider)
        layout.addLayout(opts)

    # ------------------------------------------------------------------
    # Label
    # ------------------------------------------------------------------

    def _format_label(self) -> str:
        name = (self._names[self._current]
                if self._current < len(self._names) else "")
        return f"{name}   ({self._current + 1} / {self._n_steps})"

    # ------------------------------------------------------------------
    # Step control
    # ------------------------------------------------------------------

    def _set_step(self, idx: int):
        idx = max(0, min(idx, self._n_steps - 1))
        if idx == self._current:
            return
        self._current = idx
        self._slider.blockSignals(True)
        self._slider.setValue(idx)
        self._slider.blockSignals(False)
        self._step_label.setText(self._format_label())
        self.step_changed.emit(idx)

    def _on_slider(self, value: int):
        self._current = value
        self._step_label.setText(self._format_label())
        self.step_changed.emit(value)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def _toggle_play(self):
        if self._playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        self._playing = True
        self._btn_play.setText("\u23f8")              # ⏸
        fps = self._fps_spin.value()
        self._timer.start(int(1000 / fps))

    def _pause(self):
        self._playing = False
        self._btn_play.setText("\u25b6")              # ▶
        self._timer.stop()

    def _on_tick(self):
        nxt = self._current + 1
        if nxt >= self._n_steps:
            if self._loop_cb.isChecked():
                nxt = 0
            else:
                self._pause()
                return
        self._set_step(nxt)

    def _on_fps_changed(self, fps: int):
        if self._playing:
            self._timer.start(int(1000 / fps))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_first(self):
        self._set_step(0)

    def _go_prev(self):
        self._set_step(self._current - 1)

    def _go_next(self):
        self._set_step(self._current + 1)

    def _go_last(self):
        self._set_step(self._n_steps - 1)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _on_save(self):
        self._pause()
        self.save_requested.emit()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._pause()
        super().closeEvent(event)
