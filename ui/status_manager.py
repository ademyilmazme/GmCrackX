from PyQt6.QtWidgets import QStatusBar, QLabel, QProgressBar


class StatusManager:

    def __init__(self, status_bar: QStatusBar):
        self.status_bar = status_bar

        self.label_selected = QLabel("Selected: —")
        self.label_mesh     = QLabel("Mesh: —")
        self.label_crack    = QLabel("Crack: —")
        self.label_step     = QLabel("Step: 0")

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)

        for label in [self.label_selected, self.label_mesh,
                      self.label_crack, self.label_step]:
            self.status_bar.addPermanentWidget(label)

        self.status_bar.addPermanentWidget(self.progress_bar)

    def set_selected(self, name: str):
        self.label_selected.setText(f"Selected: {name}")

    def set_mesh_info(self, elements: int, nodes: int):
        self.label_mesh.setText(f"Mesh: {elements} elems, {nodes} nodes")

    def set_crack_info(self, length: float, k1: float):
        self.label_crack.setText(f"Crack: a={length:.2f}mm, K_I={k1:.2f}")

    def set_step(self, step: int, total: int = 0):
        if total > 0:
            self.label_step.setText(f"Step: {step}/{total}")
        else:
            self.label_step.setText(f"Step: {step}")

    def set_message(self, message: str, timeout_ms: int = 3000):
        self.status_bar.showMessage(message, timeout_ms)

    def set_progress(self, pct: int, message: str = ""):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(pct)
        if message:
            self.status_bar.showMessage(message)
        if pct >= 100:
            self.progress_bar.setVisible(False)

    def hide_progress(self):
        self.progress_bar.setVisible(False)
