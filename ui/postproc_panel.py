"""
Embedded post-processing panel: plot (left) + data table (right).

Sits below the 3D viewer in the main window.  Both halves stay
synchronised: selecting a row in the table highlights the
corresponding point on the plot (and vice-versa via the parent).

Layout
------
  ┌─ PostProcPanel (QSplitter horizontal) ────────────────────┐
  │ ┌─ _PlotArea ──────────────┐  ┌─ _DataTable ───────────┐ │
  │ │ X:[▾]  Y:[▾]  [Clr][CSV]│  │ Step│Cycles│CrLen│ΔKeq… │ │
  │ │ ─── mpl nav toolbar ─── │  │  0  │    0 │ 0.20│530.2 │ │
  │ │                          │  │ ▸1  │  412 │ 0.22│545.8 │ │
  │ │    matplotlib canvas     │  │  2  │  891 │ 0.23│558.1 │ │
  │ └──────────────────────────┘  └─────────────────────────┘ │
  └───────────────────────────────────────────────────────────┘

Signals
-------
  row_selected(int)   emitted when the user clicks a table row
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QFileDialog,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure


# =====================================================================
# Field definitions
# =====================================================================

# (display label, internal data key) — order matters for combo boxes
_PLOT_FIELDS: list[tuple[str, str]] = [
    ("Increment",      "inc"),
    ("Cycles",         "cycles"),
    ("Crack Length",   "crlength"),
    ("Max \u0394K\u2091\u2099", "max_dkeq"),
    ("Mean \u0394K\u2091\u2099", "mean_dkeq"),
    ("Max K\u2091\u2099\u2098\u1d62\u2099", "max_keqmin"),
    ("Max K\u2091\u2099\u2098\u2090\u2093", "max_keqmax"),
    ("Max K\u2081",    "max_k1worst"),
    ("Max K\u2082",    "max_k2worst"),
    ("Max K\u2083",    "max_k3worst"),
    ("Mean \u03c6",    "mean_phi"),
    ("Max da/dN",      "max_dadn"),
    ("Mean da/dN",     "mean_dadn"),
]

# Table columns (shown left-to-right)
_TABLE_COLS: list[tuple[str, str]] = [
    ("Step",       "inc"),
    ("Cycles",     "cycles"),
    ("CrLength",   "crlength"),
    ("\u0394K\u2091\u2099", "max_dkeq"),
    ("K\u2091\u2099 min", "max_keqmin"),
    ("K\u2091\u2099 max", "max_keqmax"),
    ("K\u2081",    "max_k1worst"),
    ("K\u2082",    "max_k2worst"),
    ("K\u2083",    "max_k3worst"),
    ("\u03c6",     "mean_phi"),
    ("da/dN",      "max_dadn"),
    ("Nodes",      "n_nodes"),
]

# Default axis combo indices (Cycles vs. Crack Length → a–N curve)
_DEFAULT_X = 1   # Cycles
_DEFAULT_Y = 2   # Crack Length


# =====================================================================
# Data extraction
# =====================================================================

def extract_postproc_data(keq_increments) -> list[dict]:
    """Compute comprehensive per-increment statistics from KEQ output.

    Returns a list of dicts, one per propagation increment, with keys
    matching the internal keys in ``_PLOT_FIELDS`` / ``_TABLE_COLS``.
    """
    if not keq_increments:
        return []

    last = keq_increments[-1]
    groups: dict[int, list] = defaultdict(list)
    for nid, fields in last.keq_data.items():
        if fields.get("DELTAKEQ", 0.0) == 0.0:
            continue
        groups[int(fields.get("INC", 0))].append(fields)

    data: list[dict] = []
    for iv in sorted(groups.keys()):
        nodes = groups[iv]
        dkeq  = [abs(f.get("DELTAKEQ", 0.0)) for f in nodes]
        dadn  = [abs(f.get("DADN", 0.0))     for f in nodes]
        data.append({
            "inc":          iv,
            "cycles":       max(f.get("CYCLES", 0.0) for f in nodes),
            "crlength":     max(f.get("CRLENGTH", 0.0) for f in nodes),
            "max_dkeq":     max(dkeq),
            "mean_dkeq":    float(np.mean(dkeq)),
            "max_keqmin":   max(abs(f.get("KEQMIN", 0.0)) for f in nodes),
            "max_keqmax":   max(abs(f.get("KEQMAX", 0.0)) for f in nodes),
            "max_k1worst":  max(abs(f.get("K1WORST", 0.0)) for f in nodes),
            "max_k2worst":  max(abs(f.get("K2WORST", 0.0)) for f in nodes),
            "max_k3worst":  max(abs(f.get("K3WORST", 0.0)) for f in nodes),
            "mean_phi":     float(np.mean([f.get("PHI", 0.0) for f in nodes])),
            "max_dadn":     max(dadn),
            "mean_dadn":    float(np.mean(dadn)),
            "n_nodes":      len(nodes),
        })
    return data


# =====================================================================
# _PlotArea — left side: matplotlib with axis selectors
# =====================================================================

class _PlotArea(QWidget):
    """Matplotlib canvas with X/Y combo-boxes and engineering styling."""

    plot_changed = pyqtSignal()           # combo selection changed

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── combo bar ────────────────────────────────────────────────
        combo_bar = QHBoxLayout()
        combo_bar.setContentsMargins(0, 0, 0, 0)

        combo_bar.addWidget(QLabel("X:"))
        self._x_combo = QComboBox()
        self._x_combo.setMinimumWidth(110)
        combo_bar.addWidget(self._x_combo)

        combo_bar.addWidget(QLabel("  Y:"))
        self._y_combo = QComboBox()
        self._y_combo.setMinimumWidth(110)
        combo_bar.addWidget(self._y_combo)

        combo_bar.addSpacing(12)

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedWidth(52)
        btn_clear.clicked.connect(self._clear)
        combo_bar.addWidget(btn_clear)

        combo_bar.addStretch()

        # populate combos
        for label, key in _PLOT_FIELDS:
            self._x_combo.addItem(label, key)
            self._y_combo.addItem(label, key)
        self._x_combo.setCurrentIndex(_DEFAULT_X)
        self._y_combo.setCurrentIndex(_DEFAULT_Y)

        self._x_combo.currentIndexChanged.connect(lambda: self.plot_changed.emit())
        self._y_combo.currentIndexChanged.connect(lambda: self.plot_changed.emit())

        # ── matplotlib canvas ────────────────────────────────────────
        self._fig = Figure(figsize=(5, 2.8), dpi=100, facecolor="white")
        self._ax  = self._fig.add_subplot(111)
        self._canvas  = FigureCanvasQTAgg(self._fig)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)

        # ── assembly ─────────────────────────────────────────────────
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 2)
        lay.setSpacing(2)
        lay.addLayout(combo_bar)
        lay.addWidget(self._toolbar)
        lay.addWidget(self._canvas, 1)

        self._data:          list[dict] = []
        self._highlight_inc: int | None = None

        self._draw_placeholder()

    # ----- public API ------------------------------------------------

    def x_key(self) -> str:
        return self._x_combo.currentData() or "cycles"

    def y_key(self) -> str:
        return self._y_combo.currentData() or "crlength"

    def x_label(self) -> str:
        return self._x_combo.currentText()

    def y_label(self) -> str:
        return self._y_combo.currentText()

    def set_data(self, data: list[dict]):
        self._data = data

    def redraw(self, highlight_inc: int | None = None):
        """Redraw the plot with current combo selections."""
        self._highlight_inc = highlight_inc
        self._ax.clear()

        if not self._data:
            self._draw_placeholder()
            return

        xk, yk = self.x_key(), self.y_key()
        xs = [d.get(xk, 0) for d in self._data]
        ys = [d.get(yk, 0) for d in self._data]

        self._ax.plot(xs, ys, color="#1f77b4", marker="o",
                      markersize=3.5, linewidth=1.3)

        # highlight selected step
        if highlight_inc is not None:
            for d in self._data:
                if d["inc"] == highlight_inc:
                    self._ax.plot(d.get(xk, 0), d.get(yk, 0),
                                  "o", color="#d62728", markersize=9, zorder=5)
                    break

        self._ax.set_xlabel(self.x_label(), fontsize=9)
        self._ax.set_ylabel(self.y_label(), fontsize=9)
        self._ax.tick_params(labelsize=8)
        self._ax.grid(True, alpha=0.30, linewidth=0.5)

        self._fig.tight_layout(pad=1.0)
        self._canvas.draw_idle()

    def highlight(self, inc: int):
        self.redraw(highlight_inc=inc)

    # ----- private ---------------------------------------------------

    def _clear(self):
        self._ax.clear()
        self._draw_placeholder()

    def _draw_placeholder(self):
        self._ax.set_facecolor("white")
        self._ax.text(0.5, 0.5, "No results \u2014 run analysis first",
                      ha="center", va="center", fontsize=10, color="#aaa",
                      transform=self._ax.transAxes)
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._fig.tight_layout()
        self._canvas.draw_idle()


# =====================================================================
# _DataTable — right side: QTableWidget
# =====================================================================

class _DataTable(QWidget):
    """Read-only data grid showing per-increment KEQ results."""

    row_clicked = pyqtSignal(int)         # increment number

    _ROW_HIGHLIGHT = QColor(215, 230, 250)

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── toolbar ──────────────────────────────────────────────────
        tb = QHBoxLayout()
        tb.setContentsMargins(0, 0, 0, 0)
        tb.addStretch()
        btn_csv = QPushButton("Export CSV")
        btn_csv.setFixedWidth(86)
        btn_csv.clicked.connect(self._export_csv)
        tb.addWidget(btn_csv)

        # ── table ────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignRight)
        self._table.currentCellChanged.connect(self._on_cell_changed)

        # ── assembly ─────────────────────────────────────────────────
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 2)
        lay.setSpacing(2)
        lay.addLayout(tb)
        lay.addWidget(self._table, 1)

        self._data: list[dict] = []

    # ----- public API ------------------------------------------------

    def populate(self, data: list[dict]):
        self._data = data
        headers = [label for label, _ in _TABLE_COLS]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(data))

        for row, d in enumerate(data):
            for col, (_, key) in enumerate(_TABLE_COLS):
                val = d.get(key, 0)
                text = str(int(val)) if key in ("inc", "n_nodes") else f"{val:.4g}"
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self._table.setItem(row, col, item)

        self._table.resizeColumnsToContents()
        hh = self._table.horizontalHeader()
        hh.setStretchLastSection(True)

    def select_increment(self, inc: int):
        """Highlight a row without emitting ``row_clicked``."""
        self._table.blockSignals(True)
        for row, d in enumerate(self._data):
            if d.get("inc") == inc:
                self._table.selectRow(row)
                self._table.scrollTo(self._table.model().index(row, 0))
                break
        self._table.blockSignals(False)

    def clear_data(self):
        self._data = []
        self._table.setRowCount(0)

    # ----- private ---------------------------------------------------

    def _on_cell_changed(self, row, _col, _prev_row, _prev_col):
        if 0 <= row < len(self._data):
            self.row_clicked.emit(self._data[row]["inc"])

    def _export_csv(self):
        if not self._data:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "results.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        keys = [k for _, k in _TABLE_COLS]
        labels = [l for l, _ in _TABLE_COLS]
        with open(path, "w") as f:
            f.write(",".join(labels) + "\n")
            for d in self._data:
                vals = []
                for k in keys:
                    v = d.get(k, 0)
                    vals.append(str(int(v)) if k in ("inc", "n_nodes") else f"{v:.6g}")
                f.write(",".join(vals) + "\n")


# =====================================================================
# PostProcPanel — the combined widget
# =====================================================================

class PostProcPanel(QWidget):
    """Embedded post-processing panel with plot (left) + table (right).

    Signals
    -------
    row_selected(int)   — emitted when the user clicks a table row.
                          The integer is the propagation increment number.
    """

    row_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._plot  = _PlotArea()
        self._table = _DataTable()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._plot)
        splitter.addWidget(self._table)
        splitter.setSizes([550, 450])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(splitter)

        self._data: list[dict] = []

        # ── internal signals ─────────────────────────────────────────
        self._table.row_clicked.connect(self._on_table_row)
        self._plot.plot_changed.connect(self._on_combo_changed)

    # ----- public API ------------------------------------------------

    def set_data(self, keq_increments):
        """Extract data from KEQ increments and populate plot + table."""
        self._data = extract_postproc_data(keq_increments)
        self._plot.set_data(self._data)
        self._table.populate(self._data)
        self._plot.redraw()

    def highlight_step(self, inc: int):
        """Highlight a step in plot + table (no signal emitted)."""
        self.blockSignals(True)
        self._table.select_increment(inc)
        self.blockSignals(False)
        self._plot.highlight(inc)

    def clear(self):
        self._data = []
        self._plot.set_data([])
        self._plot.redraw()
        self._table.clear_data()

    def export_csv(self):
        """Trigger CSV export from the data table."""
        self._table._export_csv()

    # ----- private ---------------------------------------------------

    def _on_table_row(self, inc: int):
        self._plot.highlight(inc)
        self.row_selected.emit(inc)

    def _on_combo_changed(self):
        inc = None
        sel = self._table._table.currentRow()
        if 0 <= sel < len(self._data):
            inc = self._data[sel]["inc"]
        self._plot.redraw(highlight_inc=inc)
