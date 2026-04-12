from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QStyledItemDelegate, QComboBox,
)
from PyQt6.QtCore import pyqtSignal, Qt

from ui.model_tree import (
    KEY_GEOMETRY, KEY_MESH, KEY_CRACK, KEY_MATERIAL,
    KEY_STEPS, KEY_RESULTS, KEY_CONTOURS, KEY_CONTOUR_PREFIX,
    KEY_STEPS_GROUP, KEY_STEP_PREFIX, KEY_FINAL,
)

PROPERTY_DEFINITIONS = {
    "FRD": {
        "File":         "",
        "Status":       "not loaded",
    },
    "Mesh": {
        "Elements":     "0",
        "Nodes":        "0",
    },
    "Crack Surface": {
        "File":         "",
        "Vertices":     "0",
        "Triangles":    "0",
        "Front Nodes":  "0",
    },
    "Material": {
        "Name":         "CRACK",
        "(da/dN)_ref":  "1e-4",
        "DK_ref":       "772.86",
        "m":            "3.1",
        "epsilon":      "10.0",
        "DK_th":        "177.09",
        "delta":        "10.0",
        "K_c":          "3162.0",
        "w":            "0.5",
    },
    "Controls": {
        "Max Increment":  "0.05",
        "Max Angle":      "10.0",
        "Max Steps (INC)":"50",
        "Length Type":    "CUMULATIVE",
    },
    "Results": {
        "Increments":    "0",
        "Final Length":  "0.0",
        "Max DELTAKEQ":  "0.0",
        "Max DADN":      "0.0",
        "Total Cycles":  "0",
        "Status":        "not run",
    },
}

# Categories whose values are display-only (not user-editable)
_READ_ONLY_CATEGORIES = {"FRD", "Mesh", "Crack Surface", "Results"}

# Properties that use a fixed drop-down list: (category, prop) → choices
_COMBO_OPTIONS: dict[tuple[str, str], list[str]] = {
    ("Controls", "Length Type"): ["CUMULATIVE", "INTERSECTION", "PRINCIPAL"],
}

# Which property categories are relevant for each tree item
_ITEM_MAPPING = {
    KEY_GEOMETRY:    ["FRD"],
    KEY_MESH:        ["Mesh"],
    KEY_CRACK:       ["Crack Surface"],
    KEY_MATERIAL:    ["Material"],
    KEY_STEPS:       ["Controls"],
    KEY_RESULTS:     ["Results"],
    KEY_CONTOURS:    ["Results"],
    KEY_STEPS_GROUP: ["Results"],
    KEY_FINAL:       ["Results"],
}


class _PropertyDelegate(QStyledItemDelegate):
    """Shows a QComboBox for properties listed in _COMBO_OPTIONS."""

    def createEditor(self, parent, option, index):
        cat  = index.parent().data(Qt.ItemDataRole.DisplayRole) or ""
        prop = index.sibling(index.row(), 0).data(Qt.ItemDataRole.DisplayRole) or ""
        opts = _COMBO_OPTIONS.get((cat, prop))
        if opts:
            cb = QComboBox(parent)
            cb.addItems(opts)
            return cb
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            val = index.data(Qt.ItemDataRole.DisplayRole) or ""
            i = editor.findText(val)
            editor.setCurrentIndex(i if i >= 0 else 0)
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)


class PropertyBrowser(QTreeWidget):
    property_changed = pyqtSignal(str, str, str)  # category, prop, value

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Property", "Value"])
        self.header().setStretchLastSection(True)
        self.header().hide()
        self.setAlternatingRowColors(True)
        self.setItemDelegate(_PropertyDelegate(self))
        self._block_signals = False
        self._build_properties(PROPERTY_DEFINITIONS)
        self.itemChanged.connect(self._on_item_changed)

    def _build_properties(self, definitions: dict):
        self.clear()
        self._block_signals = True
        for category, props in definitions.items():
            cat_item = QTreeWidgetItem(self, [category, ""])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            cat_item.setExpanded(True)

            read_only = category in _READ_ONLY_CATEGORIES
            for prop_name, default_value in props.items():
                prop_item = QTreeWidgetItem(cat_item, [prop_name, default_value])
                if read_only:
                    prop_item.setFlags(prop_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    prop_item.setFlags(prop_item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._block_signals = False

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._block_signals or column != 1:
            return
        parent = item.parent()
        if parent:
            self.property_changed.emit(parent.text(0), item.text(0), item.text(1))

    def update_for_item(self, item_name: str):
        # Step-N keys (e.g. "results.step.3") → show Results category
        if item_name.startswith(KEY_STEP_PREFIX):
            categories = ["Results"]
        # Contour keys (e.g. "results.contours.K1") → show Results category
        elif item_name.startswith(KEY_CONTOUR_PREFIX):
            categories = ["Results"]
        else:
            categories = _ITEM_MAPPING.get(item_name, list(PROPERTY_DEFINITIONS.keys()))
        for i in range(self.topLevelItemCount()):
            cat_item = self.topLevelItem(i)
            cat_item.setHidden(cat_item.text(0) not in categories)

    def set_property(self, category: str, name: str, value: str):
        for i in range(self.topLevelItemCount()):
            cat_item = self.topLevelItem(i)
            if cat_item.text(0) == category:
                for j in range(cat_item.childCount()):
                    prop_item = cat_item.child(j)
                    if prop_item.text(0) == name:
                        self._block_signals = True
                        prop_item.setText(1, value)
                        self._block_signals = False
                        return

    def get_property(self, category: str, name: str) -> str:
        for i in range(self.topLevelItemCount()):
            cat_item = self.topLevelItem(i)
            if cat_item.text(0) == category:
                for j in range(cat_item.childCount()):
                    if cat_item.child(j).text(0) == name:
                        return cat_item.child(j).text(1)
        return ""
