"""
CAE-style model tree (Abaqus / PrePoMax / Ansys layout).

Tree structure
--------------
Model
 ├─ Geometry       → show part geometry / FRD mesh
 ├─ Mesh           → show FE mesh with edges
 ├─ Crack          → show crack surface + front
 ├─ Material       → Paris-law parameters
 ├─ Steps          → propagation controls
 └─ Results
      ├─ Contours  → field output types (K1, K2, …)
      │    ├─ K1
      │    ├─ K2
      │    ├─ K3
      │    ├─ DeltaKEQ
      │    ├─ da/dN
      │    └─ PHI
      └─ Steps     → per-increment crack states
           ├─ Step-0
           ├─ Step-1
           ├─ …
           └─ Final Crack

Signals
-------
  item_selected(node_key)        — left-click on any item
  visibility_toggled(actor, vis) — right-click Show / Hide
  step_selected(inc_number)      — click on a Step-N child
  contour_selected(field_label)  — click on a contour child (e.g. "K1")
"""
from __future__ import annotations

import os

from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QAction, QFont, QIcon


# ---------------------------------------------------------------------------
# File-based icons  (loaded from  bmp/  next to the project root)
# ---------------------------------------------------------------------------

_BMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bmp")

# Parent nodes: label → icon filename.
# Used when the node HAS children.
_ICON_FILE_MAP: dict[str, str] = {
    "Geometry": "Geometry.ico",
    "Mesh":     "Mesh.ico",
    "Crack":    "crack.png",
    "Material": "Material.ico",
    "Steps":    "Step.ico",       # both top-level Steps and Steps group under Results
    "Results":  "result.ico",
    "Contours": "result.ico",     # sub-group under Results — shares result icon
}

# Leaf icon: used when the node has NO children (K1, K2, Step-N, Final Crack …)
_LEAF_ICON_FILE = "Dots_t.ico"


def _load_icon(filename: str) -> QIcon:
    """Load an icon from *_BMP_DIR*.  Returns an empty QIcon on failure."""
    path = os.path.join(_BMP_DIR, filename)
    if os.path.isfile(path):
        return QIcon(path)
    return QIcon()


def _icon_for(label: str, *, leaf: bool = False) -> QIcon:
    """Return the correct icon for a tree item.

    Parameters
    ----------
    label : str
        The item's display label (used for parent-node lookup).
    leaf : bool
        True  → node has no children → ``Dots_t.ico``
        False → node has children   → look up *_ICON_FILE_MAP* by label.
    """
    if leaf:
        return _load_icon(_LEAF_ICON_FILE)
    filename = _ICON_FILE_MAP.get(label)
    if filename:
        return _load_icon(filename)
    return QIcon()


# ---------------------------------------------------------------------------
# Node keys (used in signals and property-browser mapping)
# ---------------------------------------------------------------------------

KEY_GEOMETRY       = "geometry"
KEY_MESH           = "mesh"
KEY_CRACK          = "crack"
KEY_MATERIAL       = "material"
KEY_STEPS          = "steps"
KEY_RESULTS        = "results"
KEY_CONTOURS       = "results.contours"
KEY_CONTOUR_PREFIX = "results.contours."   # + label  (e.g. "K1")
KEY_STEPS_GROUP    = "results.steps"
KEY_STEP_PREFIX    = "results.step."       # + str(inc)
KEY_FINAL          = "results.final_crack"


# ---------------------------------------------------------------------------
# Contour types  (tree label → KEQ field name in FRD output)
# ---------------------------------------------------------------------------

CONTOUR_TYPES: dict[str, str] = {
    "K1":       "K1WORST",
    "K2":       "K2WORST",
    "K3":       "K3WORST",
    "DeltaKEQ": "DELTAKEQ",
    "da/dN":    "DADN",
    "PHI":      "PHI",
}


# ---------------------------------------------------------------------------
# Actor names (must match ViewerWidget actor registry)
# ---------------------------------------------------------------------------

_ACTOR_MAP: dict[str, str] = {
    KEY_GEOMETRY: "Geometry",
    KEY_MESH:     "Mesh",
    KEY_CRACK:    "Crack Surface",
}


class ModelTree(QTreeWidget):
    item_selected      = pyqtSignal(str)          # node key
    visibility_toggled = pyqtSignal(str, bool)     # (actor_name, visible)
    step_selected      = pyqtSignal(int)           # increment number
    contour_selected   = pyqtSignal(str)           # contour label (e.g. "K1")
    crack_edit_requested   = pyqtSignal()          # right-click → Edit on Crack
    crack_insert_requested = pyqtSignal()          # right-click → Insert Crack

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setIndentation(18)
        self.setAnimated(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._hidden_actors: set[str] = set()

        self._build_tree()
        self.expandAll()
        self.currentItemChanged.connect(self._on_current_changed)

    # ------------------------------------------------------------------
    # Tree construction
    # ------------------------------------------------------------------

    def _build_tree(self):
        _leaf = _icon_for("", leaf=True)       # Dots_t.ico for all leaf nodes

        root = self._add("Model", None, key="model")

        # Top-level nodes — each has its own named icon
        self._geom_item  = self._add("Geometry", root, _icon_for("Geometry"), KEY_GEOMETRY)
        self._mesh_item  = self._add("Mesh",     root, _icon_for("Mesh"),     KEY_MESH)
        self._crack_item = self._add("Crack",    root, _icon_for("Crack"),    KEY_CRACK)
        self._mat_item   = self._add("Material", root, _icon_for("Material"), KEY_MATERIAL)
        self._step_item  = self._add("Steps",    root, _icon_for("Steps"),    KEY_STEPS)
        self._res_item   = self._add("Results",  root, _icon_for("Results"),  KEY_RESULTS)

        # ── Contours sub-group (has children → category icon) ────
        self._contours_item = self._add(
            "Contours", self._res_item, _icon_for("Contours"), KEY_CONTOURS)
        # Contour children use Dots.ico (not Dots_t)
        _dots = _load_icon("Dots.ico")
        for label in CONTOUR_TYPES:
            self._add(label, self._contours_item, _dots, KEY_CONTOUR_PREFIX + label)

        # ── Steps sub-group (has children → Step icon) ───────────
        self._steps_group_item = self._add(
            "Steps", self._res_item, _icon_for("Steps"), KEY_STEPS_GROUP)

        # Make root label bold
        bold = QFont()
        bold.setBold(True)
        root.setFont(0, bold)

    def _add(self, label: str, parent, icon: QIcon | None = None,
             key: str = "") -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent or self, [label])
        if icon:
            item.setIcon(0, icon)
        if key:
            item.setData(0, Qt.ItemDataRole.UserRole, key)
        return item

    # ------------------------------------------------------------------
    # Update tree state as the workflow progresses
    # ------------------------------------------------------------------

    def set_geometry_loaded(self, filename: str, n_nodes: int, n_elems: int):
        self._geom_item.setText(0, f"Geometry  ({filename})")
        self._mesh_item.setText(0, f"Mesh  ({n_elems} elems, {n_nodes} nodes)")

    def set_crack_loaded(self, filename: str, n_tris: int, n_front: int):
        self._crack_item.setText(0, f"Crack  ({n_tris} S3, {n_front} front)")

    def set_material_name(self, name: str):
        self._mat_item.setText(0, f"Material  ({name})")

    # ------------------------------------------------------------------
    # Populate step results after simulation
    # ------------------------------------------------------------------

    def populate_results(self, step_data: list[dict]):
        """Add Step-N children under Results > Steps.

        step_data: list of dicts, one per increment, each with keys:
            inc, max_dkeq, crlength, cycles, n_front_nodes
        """
        _dots = _load_icon("Dots.ico")   # step children use Dots.ico

        # Clear previous step items
        self._clear_children(self._steps_group_item)

        for sd in step_data:
            inc = sd["inc"]
            crl = sd.get("crlength", 0)
            cyc = sd.get("cycles", 0)
            label = f"Step {inc}   (a={crl:.4f}, N={cyc:.0f})"
            key = f"{KEY_STEP_PREFIX}{inc}"
            self._add(label, self._steps_group_item, _dots, key)

        # Final crack child
        if step_data:
            last = step_data[-1]
            label = f"Final Crack  (a={last.get('crlength',0):.4f})"
            self._add(label, self._steps_group_item, _dots, KEY_FINAL)

        n = len(step_data)
        self._steps_group_item.setText(0, f"Steps  ({n})")
        self._res_item.setText(0, f"Results  ({n} steps)")
        self._res_item.setExpanded(True)
        self._steps_group_item.setExpanded(True)

    def clear_results(self):
        self._clear_children(self._steps_group_item)
        self._steps_group_item.setText(0, "Steps")
        self._res_item.setText(0, "Results")

    @staticmethod
    def _clear_children(item: QTreeWidgetItem):
        while item.childCount() > 0:
            item.removeChild(item.child(0))

    # ------------------------------------------------------------------
    # Context menu  (Show / Hide for actors)
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return

        key = item.data(0, Qt.ItemDataRole.UserRole) or ""
        actor_name = _ACTOR_MAP.get(key)

        menu = QMenu(self)

        if actor_name:
            is_hidden = actor_name in self._hidden_actors

            show_act = QAction("Show", self)
            show_act.setEnabled(is_hidden)
            show_act.triggered.connect(
                lambda: self._set_visibility(actor_name, True))
            menu.addAction(show_act)

            hide_act = QAction("Hide", self)
            hide_act.setEnabled(not is_hidden)
            hide_act.triggered.connect(
                lambda: self._set_visibility(actor_name, False))
            menu.addAction(hide_act)

            menu.addSeparator()

        if key == KEY_CRACK:
            edit_act = QAction("Edit", self)
            edit_act.triggered.connect(
                lambda: self.crack_edit_requested.emit())
            menu.addAction(edit_act)

            insert_act = QAction("Insert Crack", self)
            insert_act.triggered.connect(
                lambda: self.crack_insert_requested.emit())
            menu.addAction(insert_act)

        if not menu.isEmpty():
            menu.exec(self.viewport().mapToGlobal(pos))

    def _set_visibility(self, actor_name: str, visible: bool):
        """Set an actor's visibility and emit the signal."""
        if visible:
            self._hidden_actors.discard(actor_name)
        else:
            self._hidden_actors.add(actor_name)
        self.visibility_toggled.emit(actor_name, visible)

    def _select_item(self, item: QTreeWidgetItem):
        """Programmatically select an item (used by Properties action)."""
        self.setCurrentItem(item)

    # ------------------------------------------------------------------
    # Selection handling
    # ------------------------------------------------------------------

    def _on_current_changed(self, current: QTreeWidgetItem, previous):
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole) or ""
        self.item_selected.emit(key)

        # Contour node clicked → emit contour_selected
        if key.startswith(KEY_CONTOUR_PREFIX):
            label = key[len(KEY_CONTOUR_PREFIX):]
            self.contour_selected.emit(label)
            return

        # Step-N node clicked → emit step_selected
        if key.startswith(KEY_STEP_PREFIX):
            try:
                inc = int(key[len(KEY_STEP_PREFIX):])
                self.step_selected.emit(inc)
            except ValueError:
                pass
        elif key == KEY_FINAL:
            # Final crack → emit last step number
            grp = self._steps_group_item
            last_child = grp.child(grp.childCount() - 2)
            if last_child:
                lk = last_child.data(0, Qt.ItemDataRole.UserRole) or ""
                if lk.startswith(KEY_STEP_PREFIX):
                    try:
                        self.step_selected.emit(int(lk[len(KEY_STEP_PREFIX):]))
                    except ValueError:
                        pass

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_item_path(self, item: QTreeWidgetItem) -> str:
        parts = []
        while item:
            parts.append(item.text(0))
            item = item.parent()
        return ".".join(reversed(parts))
