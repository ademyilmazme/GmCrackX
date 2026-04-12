"""
Crack growth diagrams — matplotlib embedded in Qt.

Three tabs:
  1. a–N curve   (crack length vs. fatigue cycles)
  2. ΔK_eq vs step  (max + mean SIF range per increment)
  3. Paris diagram   (da/dN vs ΔK, log-log)
"""
from __future__ import annotations

from collections import defaultdict
import numpy as np

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTabWidget, QWidget
from PyQt6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class GraphsDialog(QDialog):
    """Tabbed dialog showing crack growth curves."""

    def __init__(self, keq_increments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crack Growth Diagrams")
        self.setMinimumSize(900, 600)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self._data = _extract_increment_data(keq_increments)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._tab_an(),    "a – N Curve")
        tabs.addTab(self._tab_dkeq(),  "ΔK_eq vs Step")
        tabs.addTab(self._tab_paris(), "Paris Diagram")

    # ------------------------------------------------------------------
    # Plot tabs
    # ------------------------------------------------------------------

    def _tab_an(self) -> QWidget:
        """Crack length vs. fatigue cycles."""
        fig = Figure(figsize=(8, 5), dpi=100)
        ax = fig.add_subplot(111)

        if self._data:
            cycles  = [d["cycles"]   for d in self._data]
            lengths = [d["crlength"] for d in self._data]
            ax.plot(cycles, lengths, "b-o", markersize=4, linewidth=1.5)
            ax.set_xlabel("Fatigue Cycles  N")
            ax.set_ylabel("Crack Length  a")
            ax.set_title("Crack Growth Curve  (a – N)")
            ax.grid(True, alpha=0.3)
        else:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes)

        fig.tight_layout()
        return _wrap(fig)

    def _tab_dkeq(self) -> QWidget:
        """Max / mean ΔK_eq per propagation increment."""
        fig = Figure(figsize=(8, 5), dpi=100)
        ax = fig.add_subplot(111)

        if self._data:
            incs    = [d["inc"]       for d in self._data]
            max_dk  = [d["max_dkeq"]  for d in self._data]
            mean_dk = [d["mean_dkeq"] for d in self._data]
            ax.plot(incs, max_dk,  "r-s", markersize=4, linewidth=1.5, label="Max ΔK_eq")
            ax.plot(incs, mean_dk, "g-^", markersize=3, linewidth=1.0, label="Mean ΔK_eq")
            ax.set_xlabel("Increment")
            ax.set_ylabel("ΔK_eq")
            ax.set_title("Stress Intensity Factor Range per Increment")
            ax.grid(True, alpha=0.3)
            ax.legend()
        else:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes)

        fig.tight_layout()
        return _wrap(fig)

    def _tab_paris(self) -> QWidget:
        """Paris diagram: da/dN vs ΔK (log-log)."""
        fig = Figure(figsize=(8, 5), dpi=100)
        ax = fig.add_subplot(111)

        if self._data:
            dk   = [d["mean_dkeq"] for d in self._data if d["mean_dadn"] > 0]
            dadn = [d["mean_dadn"] for d in self._data if d["mean_dadn"] > 0]
            if dk and dadn:
                ax.loglog(dk, dadn, "ko", markersize=5)
                ax.set_xlabel("ΔK_eq  (log)")
                ax.set_ylabel("da/dN  (log)")
                ax.set_title("Paris Diagram")
                ax.grid(True, alpha=0.3, which="both")
            else:
                ax.text(0.5, 0.5, "No da/dN > 0 data available",
                        ha="center", va="center", transform=ax.transAxes)
        else:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes)

        fig.tight_layout()
        return _wrap(fig)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap(fig: Figure) -> QWidget:
    """Wrap a matplotlib Figure in a QWidget for tab display."""
    canvas = FigureCanvasQTAgg(fig)
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(canvas)
    return w


def _extract_increment_data(keq_increments) -> list[dict]:
    """Group KEQ nodes by INC field, compute per-increment statistics."""
    if not keq_increments:
        return []

    last = keq_increments[-1]
    groups: dict[int, list] = defaultdict(list)
    for nid, fields in last.keq_data.items():
        if fields.get("DELTAKEQ", 0.0) == 0.0:
            continue
        inc_val = int(fields.get("INC", 0))
        groups[inc_val].append(fields)

    data = []
    for iv in sorted(groups.keys()):
        nodes = groups[iv]
        dadn_vals = [abs(f.get("DADN", 0.0)) for f in nodes]
        dkeq_vals = [abs(f.get("DELTAKEQ", 0.0)) for f in nodes]
        data.append({
            "inc":       iv,
            "crlength":  max(f.get("CRLENGTH", 0.0) for f in nodes),
            "cycles":    max(f.get("CYCLES", 0.0) for f in nodes),
            "max_dkeq":  max(dkeq_vals),
            "mean_dkeq": float(np.mean(dkeq_vals)),
            "max_dadn":  max(dadn_vals),
            "mean_dadn": float(np.mean(dadn_vals)),
            "n_nodes":   len(nodes),
        })
    return data
