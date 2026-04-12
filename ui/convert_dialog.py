"""
Result conversion dialog — Tools tab → Convert Results.

Workflow:
  1. User browses for a source file.
  2. The dialog inspects the file and lists available fields / increments.
  3. User picks which fields / increments to include and sets an output path.
  4. Clicking Convert runs the conversion in a background Worker thread.
  5. On success a summary label shows; on error the message is displayed.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .worker import Worker


class ConvertDialog(QDialog):
    """Modal dialog for converting result files to CalculiX FRD format."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert Results to FRD")
        self.setMinimumWidth(520)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._manager = None   # set lazily to avoid import at dialog creation
        self._info: dict = {}
        self._worker: Worker | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # --- Source file ---
        src_grp = QGroupBox("Source File")
        src_layout = QHBoxLayout(src_grp)
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("Select a result file (e.g. .rst)")
        self._src_edit.setReadOnly(True)
        src_browse = QPushButton("Browse…")
        src_browse.clicked.connect(self._browse_source)
        src_layout.addWidget(self._src_edit)
        src_layout.addWidget(src_browse)
        root.addWidget(src_grp)

        # --- File info ---
        self._info_label = QLabel()
        self._info_label.setWordWrap(True)
        self._info_label.setStyleSheet("color: gray; font-size: 11px;")
        root.addWidget(self._info_label)

        # --- Fields selection ---
        fields_grp = QGroupBox("Fields to Include")
        fields_layout = QVBoxLayout(fields_grp)
        self._fields_list = QListWidget()
        self._fields_list.setFixedHeight(90)
        fields_layout.addWidget(self._fields_list)
        root.addWidget(fields_grp)

        # --- Increments selection ---
        inc_grp = QGroupBox("Increments")
        inc_layout = QVBoxLayout(inc_grp)
        self._all_incs_cb = QCheckBox("All increments")
        self._all_incs_cb.setChecked(True)
        self._all_incs_cb.toggled.connect(self._on_all_incs_toggled)
        self._incs_list = QListWidget()
        self._incs_list.setFixedHeight(80)
        self._incs_list.setSelectionMode(
            QListWidget.SelectionMode.MultiSelection
        )
        self._incs_list.setEnabled(False)
        inc_layout.addWidget(self._all_incs_cb)
        inc_layout.addWidget(self._incs_list)
        root.addWidget(inc_grp)

        # --- Output file ---
        out_grp = QGroupBox("Output FRD File")
        out_layout = QHBoxLayout(out_grp)
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("Output .frd path")
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._browse_output)
        out_layout.addWidget(self._out_edit)
        out_layout.addWidget(out_browse)
        root.addWidget(out_grp)

        # --- Progress ---
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.hide()
        root.addWidget(self._progress)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        # --- Buttons ---
        btn_box = QDialogButtonBox()
        self._convert_btn = QPushButton("Convert")
        self._convert_btn.setDefault(True)
        self._convert_btn.setEnabled(False)
        self._convert_btn.clicked.connect(self._run_convert)
        btn_box.addButton(self._convert_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        close_btn = btn_box.addButton(QDialogButtonBox.StandardButton.Close)
        close_btn.clicked.connect(self.reject)
        root.addWidget(btn_box)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Result File",
            "",
            "ANSYS RST (*.rst);;All files (*.*)",
        )
        if not path:
            return
        self._src_edit.setText(path)
        # Auto-fill output path
        src = Path(path)
        self._out_edit.setText(str(src.with_suffix(".frd")))
        self._inspect_source(path)

    def _inspect_source(self, path: str) -> None:
        """Run lightweight inspection and populate field/increment lists."""
        mgr = self._get_manager()
        if mgr is None:
            return

        self._info = mgr.inspect(path)
        if "error" in self._info:
            self._info_label.setText(f"Error: {self._info['error']}")
            self._convert_btn.setEnabled(False)
            return

        n_nodes = self._info.get("n_nodes", "?")
        n_elems = self._info.get("n_elements", "?")
        n_incs = self._info.get("n_increments", "?")
        self._info_label.setText(
            f"Nodes: {n_nodes}   Elements: {n_elems}   Increments: {n_incs}"
        )

        # Populate fields list (all checked by default)
        self._fields_list.clear()
        for fname in self._info.get("fields", []):
            item = QListWidgetItem(fname)
            item.setCheckState(Qt.CheckState.Checked)
            self._fields_list.addItem(item)

        # Populate increments list
        self._incs_list.clear()
        n = self._info.get("n_increments", 0)
        if isinstance(n, int):
            for i in range(n):
                self._incs_list.addItem(QListWidgetItem(f"Increment {i + 1}"))

        self._convert_btn.setEnabled(True)

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save FRD File As",
            self._out_edit.text() or "",
            "CalculiX FRD (*.frd);;All files (*.*)",
        )
        if path:
            self._out_edit.setText(path)

    def _on_all_incs_toggled(self, checked: bool) -> None:
        self._incs_list.setEnabled(not checked)

    def _run_convert(self) -> None:
        source = self._src_edit.text().strip()
        dest = self._out_edit.text().strip()
        if not source or not dest:
            QMessageBox.warning(self, "Convert", "Please set source and output paths.")
            return

        # Collect selected fields
        fields: list[str] = []
        for row in range(self._fields_list.count()):
            item = self._fields_list.item(row)
            if item and item.checkState() == Qt.CheckState.Checked:
                fields.append(item.text())

        # Collect increments
        increments: list[int] | None = None
        if not self._all_incs_cb.isChecked():
            selected = self._incs_list.selectedItems()
            increments = [self._incs_list.row(it) for it in selected]

        self._set_busy(True)
        self._status_label.setText("Converting…")

        mgr = self._get_manager()

        def task(progress_cb):
            progress_cb(10, "Reading source file…")
            issues = mgr.convert(
                source, dest,
                fields=fields if fields else None,
                increments=increments,
                validate=True,
            )
            progress_cb(100, "Done")
            return issues

        self._worker = Worker(task)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ------------------------------------------------------------------
    # Worker callbacks
    # ------------------------------------------------------------------

    def _on_progress(self, pct: int, msg: str) -> None:
        self._progress.setValue(pct)
        if msg:
            self._status_label.setText(msg)

    def _on_finished(self, issues: object) -> None:
        self._set_busy(False)
        if issues:
            self._status_label.setText(
                "Validation errors:\n" + "\n".join(str(i) for i in issues)  # type: ignore[arg-type]
            )
        else:
            dest = self._out_edit.text()
            self._status_label.setText(f"Done — saved to: {dest}")

    def _on_error(self, msg: str) -> None:
        self._set_busy(False)
        self._status_label.setText(f"Error:\n{msg}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._convert_btn.setEnabled(not busy)
        if busy:
            self._progress.show()
            self._progress.setValue(0)
        else:
            self._progress.hide()

    def _get_manager(self):
        if self._manager is None:
            try:
                from convert import ConversionManager
                self._manager = ConversionManager()
            except Exception as exc:
                QMessageBox.critical(
                    self, "Error",
                    f"Failed to initialise ConversionManager:\n{exc}"
                )
                return None
        return self._manager
