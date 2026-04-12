# Crack3D — UI Structure Document

PyQt6 desktop application for 3D crack growth simulation.
Backend: CalculiX (solver) + OpenCascade (geometry) + Gmsh (meshing).

---

## Application Layout

```
┌─────────────────────────────────────────────────────────┐
│  Toolbar                                                │
│  [Import INP] [Import Crack] [Mesh] [Solve] [Step] [All]│
├──────────────┬──────────────────────────────────────────┤
│              │                                          │
│  Model Tree  │          Viewer Widget                   │
│              │          (3D viewport)                   │
│              │                                          │
│              │                                          │
├──────────────┤                                          │
│              │                                          │
│  Property    │                                          │
│  Browser     │                                          │
│              │                                          │
├──────────────┴──────────────────────────────────────────┤
│  Status Bar: [Selected: ...] [Mesh: ...] [Step: ...]    │
└─────────────────────────────────────────────────────────┘
```

---

## File Structure

```
crack3d/
├── main.py                     # Entry point, QApplication setup
├── ui/
│   ├── __init__.py
│   ├── main_window.py          # QMainWindow — layout, toolbar, signals
│   ├── model_tree.py           # QTreeWidget — model hierarchy
│   ├── property_browser.py     # QTreeWidget — editable property table
│   ├── viewer_widget.py        # QWidget — 3D viewport (placeholder → VTK later)
│   ├── toolbar.py              # Toolbar builder (actions + icons)
│   └── status_manager.py       # Status bar update helper
├── resources/
│   ├── icons/                  # Toolbar icons (.svg or .png)
│   └── style.qss               # Application stylesheet
└── pyproject.toml
```

---

## Module Specifications

### 1. `main.py`

```python
"""Entry point. Creates QApplication and MainWindow."""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Crack3D")
    app.setOrganizationName("Crack3D")
    app.setApplicationVersion("0.1.0")
    app.setFont(QFont("Segoe UI", 9))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

---

### 2. `ui/main_window.py`

**Class:** `MainWindow(QMainWindow)`

**Responsibilities:**
- Assembles all widgets into the layout using QSplitter
- Creates toolbar via `ToolbarBuilder`
- Creates status bar via `StatusManager`
- Connects signals between widgets
- Holds placeholder slots for backend pipeline integration

**Layout construction:**

```
QMainWindow
├── QToolBar (top)
├── Central Widget
│   └── QSplitter (horizontal, main_splitter)
│       ├── QSplitter (vertical, left_splitter)  [stretch factor 0]
│       │   ├── ModelTree                         [stretch factor 1]
│       │   └── PropertyBrowser                   [stretch factor 1]
│       └── ViewerWidget                          [stretch factor 1]
└── QStatusBar (bottom)
```

**Splitter proportions:**
- `main_splitter`: left panel ~280px fixed, right panel stretches
- `left_splitter`: tree 60%, property browser 40%

**Signal connections:**

| Source                        | Signal                              | Slot                                  |
|-------------------------------|-------------------------------------|---------------------------------------|
| ModelTree                     | `item_selected(str)`                | MainWindow.`on_tree_item_selected`    |
| PropertyBrowser               | `property_changed(str, str, str)`   | MainWindow.`on_property_changed`      |
| Toolbar actions               | `triggered`                         | MainWindow.`import_inp`, `mesh`, etc. |

**Skeleton:**

```python
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Crack3D — 3D Crack Growth Simulation")
        self.setMinimumSize(1200, 800)

        # --- Create widgets ---
        self.model_tree = ModelTree()
        self.property_browser = PropertyBrowser()
        self.viewer = ViewerWidget()

        # --- Layout with splitters ---
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(self.model_tree)
        left_splitter.addWidget(self.property_browser)
        left_splitter.setStretchFactor(0, 3)    # tree gets 60%
        left_splitter.setStretchFactor(1, 2)    # props get 40%

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(self.viewer)
        main_splitter.setSizes([280, 900])       # initial pixel split
        main_splitter.setStretchFactor(0, 0)     # left panel fixed
        main_splitter.setStretchFactor(1, 1)     # viewer stretches

        self.setCentralWidget(main_splitter)

        # --- Toolbar ---
        self.toolbar_builder = ToolbarBuilder(self)
        self.toolbar_builder.build()

        # --- Status bar ---
        self.status_manager = StatusManager(self.statusBar())

        # --- Connect signals ---
        self._connect_signals()

    def _connect_signals(self):
        self.model_tree.item_selected.connect(self.on_tree_item_selected)
        self.property_browser.property_changed.connect(self.on_property_changed)

    # --- Slots: tree selection ---

    def on_tree_item_selected(self, item_name: str):
        """Called when user clicks a tree item."""
        print(f"Selected: {item_name}")
        self.viewer.highlight_object(item_name)
        self.property_browser.update_for_item(item_name)
        self.status_manager.set_selected(item_name)

    # --- Slots: property changes ---

    def on_property_changed(self, category: str, prop: str, value: str):
        """Called when user edits a property value."""
        print(f"Property changed: {category}.{prop} = {value}")

    # --- Slots: toolbar actions (backend integration points) ---

    def import_inp(self):
        """Open file dialog → load CalculiX .inp file."""
        print("Action: Import INP")
        self.status_manager.set_message("Importing INP file...")

    def import_crack(self):
        """Open file dialog → load crack .brep file."""
        print("Action: Import Crack")
        self.status_manager.set_message("Importing crack geometry...")

    def mesh(self):
        """Run meshing pipeline (divide local/global → remesh)."""
        print("Action: Mesh")
        self.status_manager.set_message("Meshing...")

    def solve(self):
        """Run CalculiX solver on current model."""
        print("Action: Solve")
        self.status_manager.set_message("Solving...")

    def run_step(self):
        """Execute one crack growth step."""
        print("Action: Run Step")
        self.status_manager.set_message("Running crack growth step...")

    def run_all(self):
        """Execute all crack growth steps until termination."""
        print("Action: Run All")
        self.status_manager.set_message("Running full crack growth analysis...")
```

---

### 3. `ui/model_tree.py`

**Class:** `ModelTree(QTreeWidget)`

**Signal:** `item_selected = pyqtSignal(str)`

**Tree structure (built in constructor):**

```
Model
├── Geometry
│   ├── Solid
│   ├── Crack Surface
│   └── Crack Front
├── Mesh
│   ├── Global Mesh
│   └── Local Mesh
└── Results
    ├── Displacement
    ├── Stress
    └── K Factors
```

**Behavior:**
- Single column, header hidden
- Expand all on creation
- On `currentItemChanged` → emit `item_selected(item_text)`
- Each item stores a string role (e.g. `"geometry.solid"`) in `Qt.ItemDataRole.UserRole`
- Provides `add_child(parent_path, name)` and `remove_child(path)` for dynamic updates

**Skeleton:**

```python
class ModelTree(QTreeWidget):
    item_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self._build_default_tree()
        self.expandAll()
        self.currentItemChanged.connect(self._on_current_changed)

    def _build_default_tree(self):
        root = QTreeWidgetItem(self, ["Model"])

        geo = QTreeWidgetItem(root, ["Geometry"])
        QTreeWidgetItem(geo, ["Solid"])
        QTreeWidgetItem(geo, ["Crack Surface"])
        QTreeWidgetItem(geo, ["Crack Front"])

        mesh = QTreeWidgetItem(root, ["Mesh"])
        QTreeWidgetItem(mesh, ["Global Mesh"])
        QTreeWidgetItem(mesh, ["Local Mesh"])

        results = QTreeWidgetItem(root, ["Results"])
        QTreeWidgetItem(results, ["Displacement"])
        QTreeWidgetItem(results, ["Stress"])
        QTreeWidgetItem(results, ["K Factors"])

    def _on_current_changed(self, current: QTreeWidgetItem, previous):
        if current:
            self.item_selected.emit(current.text(0))

    def get_item_path(self, item: QTreeWidgetItem) -> str:
        """Return dotted path like 'Model.Geometry.Solid'."""
        parts = []
        while item:
            parts.append(item.text(0))
            item = item.parent()
        return ".".join(reversed(parts))
```

---

### 4. `ui/property_browser.py`

**Class:** `PropertyBrowser(QTreeWidget)`

**Signal:** `property_changed = pyqtSignal(str, str, str)`
- Arguments: `(category, property_name, new_value)`

**Columns:** `Property | Value`

**Property definitions (default categories):**

```python
PROPERTY_DEFINITIONS = {
    "Geometry": {
        "Name": "",
        "Volume": "0.0",
        "Area": "0.0",
    },
    "Mesh": {
        "Element Count": "0",
        "Node Count": "0",
        "Min Size": "0.0",
        "Max Size": "0.0",
    },
    "Material": {
        "E": "210000.0",
        "nu": "0.3",
    },
    "Crack": {
        "Length": "0.0",
        "K_I": "0.0",
        "K_II": "0.0",
        "K_III": "0.0",
    },
}
```

**Behavior:**
- Category rows are not editable, bold font
- Value column (column 1) on property rows is editable via `Qt.ItemFlag.ItemIsEditable`
- On `itemChanged` → emit `property_changed(category, prop, value)`
- `update_for_item(name)` clears and rebuilds properties relevant to the selected tree item
- `set_property(category, name, value)` for programmatic updates from backend
- `get_property(category, name) -> str` to read current values

**Skeleton:**

```python
class PropertyBrowser(QTreeWidget):
    property_changed = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Property", "Value"])
        self.header().setStretchLastSection(True)
        self.setAlternatingRowColors(True)
        self._build_properties(PROPERTY_DEFINITIONS)
        self.itemChanged.connect(self._on_item_changed)

    def _build_properties(self, definitions: dict):
        self.clear()
        self._block_signals = True       # prevent itemChanged during build
        for category, props in definitions.items():
            cat_item = QTreeWidgetItem(self, [category, ""])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            cat_item.setExpanded(True)

            for prop_name, default_value in props.items():
                prop_item = QTreeWidgetItem(cat_item, [prop_name, default_value])
                prop_item.setFlags(
                    prop_item.flags() | Qt.ItemFlag.ItemIsEditable
                )
        self._block_signals = False

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._block_signals or column != 1:
            return
        parent = item.parent()
        if parent:
            category = parent.text(0)
            prop_name = item.text(0)
            value = item.text(1)
            self.property_changed.emit(category, prop_name, value)

    def update_for_item(self, item_name: str):
        """Update visible properties based on selected tree item."""
        # Map tree items to relevant property categories
        mapping = {
            "Solid": ["Geometry"],
            "Crack Surface": ["Geometry", "Crack"],
            "Crack Front": ["Crack"],
            "Global Mesh": ["Mesh"],
            "Local Mesh": ["Mesh"],
            "Displacement": ["Mesh"],
            "Stress": ["Mesh", "Material"],
            "K Factors": ["Crack", "Material"],
        }
        # Show all categories if item not in mapping
        categories = mapping.get(item_name, list(PROPERTY_DEFINITIONS.keys()))
        for i in range(self.topLevelItemCount()):
            cat_item = self.topLevelItem(i)
            cat_item.setHidden(cat_item.text(0) not in categories)

    def set_property(self, category: str, name: str, value: str):
        """Programmatically set a property value."""
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
        """Read current value of a property."""
        for i in range(self.topLevelItemCount()):
            cat_item = self.topLevelItem(i)
            if cat_item.text(0) == category:
                for j in range(cat_item.childCount()):
                    if cat_item.child(j).text(0) == name:
                        return cat_item.child(j).text(1)
        return ""
```

---

### 5. `ui/viewer_widget.py`

**Class:** `ViewerWidget(QWidget)`

**Current state:** Placeholder with black background.
**Future state:** Replace with `QVTKRenderWindowInteractor` for full 3D rendering.

**Public interface (stable API — backend calls these):**

```python
class ViewerWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        # Black background
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        self.setPalette(palette)

    # --- Public API (called by MainWindow / backend) ---

    def display_geometry(self, brep_path: str):
        """Load and display OCCT B-rep geometry in 3D viewport."""
        print(f"Viewer: display_geometry({brep_path})")
        # Future: OCCT → VTK polydata → renderer

    def display_mesh(self, mesh_path: str, mesh_type: str = "global"):
        """Load and display mesh (.msh or MeshData) as wireframe/surface."""
        print(f"Viewer: display_mesh({mesh_path}, type={mesh_type})")
        # Future: meshio → VTK unstructured grid → renderer

    def display_results(self, field_name: str, data: "np.ndarray | None" = None):
        """Show scalar field (displacement, stress, K) as color map on mesh."""
        print(f"Viewer: display_results(field={field_name})")
        # Future: VTK scalar bar + lookup table

    def highlight_object(self, name: str):
        """Highlight a named object in the viewport (selection feedback)."""
        print(f"Viewer: highlight_object({name})")
        # Future: change actor color/opacity for selected object

    def clear(self):
        """Remove all actors from the viewport."""
        print("Viewer: clear()")

    def fit_all(self):
        """Reset camera to fit all visible objects."""
        print("Viewer: fit_all()")
```

**VTK upgrade path (Phase 2):**
- Replace `QWidget` base with `QVTKRenderWindowInteractor`
- Add `vtkRenderer`, `vtkRenderWindow`
- `display_geometry` → use `IVtkOCC_Shape` or convert OCCT → VTK polydata
- `display_mesh` → `vtkUnstructuredGrid` from meshio
- `display_results` → `vtkLookupTable` + `vtkScalarBarActor`
- `highlight_object` → change actor property (color, edge visibility)

---

### 6. `ui/toolbar.py`

**Class:** `ToolbarBuilder`

Builds the main toolbar and connects actions to `MainWindow` slots.

```python
class ToolbarBuilder:

    # Action definitions: (name, icon_name, tooltip, slot_name)
    ACTIONS = [
        ("Import INP",   "file-inp",   "Import CalculiX .inp model",    "import_inp"),
        ("Import Crack", "file-crack", "Import crack surface .brep",    "import_crack"),
        ("---", None, None, None),   # separator
        ("Mesh",         "mesh",       "Run meshing pipeline",           "mesh"),
        ("Solve",        "solve",      "Run CalculiX solver",           "solve"),
        ("---", None, None, None),   # separator
        ("Run Step",     "step",       "Execute one crack growth step", "run_step"),
        ("Run All",      "run-all",    "Run all steps until completion","run_all"),
    ]

    def __init__(self, main_window: "MainWindow"):
        self.main_window = main_window
        self.actions: dict[str, QAction] = {}

    def build(self):
        toolbar = self.main_window.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        for name, icon_name, tooltip, slot_name in self.ACTIONS:
            if name == "---":
                toolbar.addSeparator()
                continue

            action = QAction(name, self.main_window)
            action.setToolTip(tooltip)
            # action.setIcon(QIcon(f"resources/icons/{icon_name}.svg"))

            # Connect to MainWindow slot
            slot = getattr(self.main_window, slot_name)
            action.triggered.connect(slot)

            toolbar.addAction(action)
            self.actions[slot_name] = action

    def set_enabled(self, slot_name: str, enabled: bool):
        """Enable/disable a toolbar action by slot name."""
        if slot_name in self.actions:
            self.actions[slot_name].setEnabled(enabled)
```

**Action enable/disable logic (future):**

| State                   | Import INP | Import Crack | Mesh | Solve | Run Step | Run All |
|-------------------------|:----------:|:------------:|:----:|:-----:|:--------:|:-------:|
| Initial (empty)         | ✓          | ✗            | ✗    | ✗     | ✗        | ✗       |
| INP loaded              | ✓          | ✓            | ✗    | ✗     | ✗        | ✗       |
| Crack loaded            | ✓          | ✓            | ✓    | ✗     | ✗        | ✗       |
| Meshed                  | ✓          | ✓            | ✓    | ✓     | ✗        | ✗       |
| Solved                  | ✓          | ✓            | ✓    | ✓     | ✓        | ✓       |

---

### 7. `ui/status_manager.py`

**Class:** `StatusManager`

Manages the status bar with multiple permanent labels.

```python
class StatusManager:

    def __init__(self, status_bar: QStatusBar):
        self.status_bar = status_bar

        # Permanent labels (always visible)
        self.label_selected = QLabel("Selected: —")
        self.label_mesh = QLabel("Mesh: —")
        self.label_crack = QLabel("Crack: —")
        self.label_step = QLabel("Step: 0")

        # Add separators between labels
        for label in [self.label_selected, self.label_mesh,
                      self.label_crack, self.label_step]:
            self.status_bar.addPermanentWidget(label)

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
        """Show temporary message (auto-clears after timeout)."""
        self.status_bar.showMessage(message, timeout_ms)
```

---

## Signal Flow Diagram

```
User clicks tree item
    │
    ▼
ModelTree.item_selected(str)
    │
    ├──► MainWindow.on_tree_item_selected()
    │       │
    │       ├──► ViewerWidget.highlight_object(name)
    │       ├──► PropertyBrowser.update_for_item(name)
    │       └──► StatusManager.set_selected(name)
    │
    ▼

User edits property value
    │
    ▼
PropertyBrowser.property_changed(category, prop, value)
    │
    ├──► MainWindow.on_property_changed()
    │       │
    │       └──► (future: push to backend config)
    │
    ▼

User clicks toolbar button
    │
    ▼
QAction.triggered
    │
    ├──► MainWindow.import_inp() / mesh() / solve() / run_step() / run_all()
    │       │
    │       ├──► (future: call pipeline.driver)
    │       ├──► ViewerWidget.display_*()
    │       ├──► PropertyBrowser.set_property()
    │       └──► StatusManager.set_*()
    │
    ▼
```

---

## Backend Integration Points

When connecting the `crack3d` pipeline (from the project structure document), these are the touch points:

```python
# In MainWindow — example integration pattern

def import_inp(self):
    path, _ = QFileDialog.getOpenFileName(
        self, "Import CalculiX Model", "", "CalculiX Files (*.inp)"
    )
    if not path:
        return

    # Backend call
    from crack3d.io.inp_parser import parse_inp
    self.mesh_data = parse_inp(path)

    # Update UI
    self.viewer.display_mesh(path, mesh_type="global")
    self.property_browser.set_property("Mesh", "Element Count",
                                        str(len(self.mesh_data.elements)))
    self.property_browser.set_property("Mesh", "Node Count",
                                        str(len(self.mesh_data.nodes)))
    self.status_manager.set_mesh_info(
        len(self.mesh_data.elements), len(self.mesh_data.nodes)
    )
    self.status_manager.set_message(f"Loaded: {path}")
    self.toolbar_builder.set_enabled("import_crack", True)


def run_step(self):
    # Backend call (run in QThread to keep UI responsive)
    from crack3d.pipeline.crack_step import CrackStep
    step = CrackStep(self.config, self.current_step)
    result = step.run(self.mesh_data, self.crack_brep)

    # Update UI
    self.viewer.display_results("K_I", result.K[:, 0])
    self.property_browser.set_property("Crack", "K_I",
                                        f"{result.K_max[0]:.2f}")
    self.property_browser.set_property("Crack", "Length",
                                        f"{result.crack_length:.2f}")
    self.status_manager.set_step(self.current_step)
    self.status_manager.set_crack_info(result.crack_length, result.K_max[0])
    self.current_step += 1
```

**Threading note:** All backend calls (`mesh()`, `solve()`, `run_step()`, `run_all()`) should run in a `QThread` with progress signals. The pattern:

```python
class WorkerThread(QThread):
    progress = pyqtSignal(int, str)      # percent, message
    finished = pyqtSignal(object)        # result object
    error = pyqtSignal(str)              # error message

    def __init__(self, func, *args):
        super().__init__()
        self.func = func
        self.args = args

    def run(self):
        try:
            result = self.func(*self.args)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
```

---

## Dependencies

```toml
[project]
name = "crack3d"
requires-python = ">=3.11"
dependencies = [
    "PyQt6 >= 6.6",
]

[project.optional-dependencies]
vtk = [
    "vtk >= 9.3",
    "vtkmodules",
]
full = [
    "numpy",
    "scipy",
    "gmsh",
    "OCP",
    "meshio",
    "pyvista",
]
```

---

## Implementation Phases

### Phase 1 — Skeleton (this document)
- MainWindow layout with splitters
- ModelTree with default hierarchy
- PropertyBrowser with editable categories
- ViewerWidget as black placeholder
- Toolbar with connected print-only slots
- Status bar with permanent labels
- All signals connected and working

### Phase 2 — VTK Viewer
- Replace ViewerWidget base with QVTKRenderWindowInteractor
- Implement `display_geometry()` with OCCT → VTK conversion
- Implement `display_mesh()` with meshio → VTK
- Implement `display_results()` with scalar color mapping
- Implement `highlight_object()` with actor selection
- Mouse interaction: rotate, pan, zoom, pick

### Phase 3 — Backend Integration
- Connect `import_inp()` to `crack3d.io.inp_parser`
- Connect `import_crack()` to `crack3d.io.brep_io`
- Connect `mesh()` to `crack3d.core.meshing`
- Connect `solve()` to `crack3d.solver.calculix_solver`
- Connect `run_step()` / `run_all()` to `crack3d.pipeline`
- QThread workers for long-running operations
- Progress bar in status bar

### Phase 4 — Polish
- Icons for toolbar actions
- QSS stylesheet for consistent appearance
- Keyboard shortcuts (Ctrl+I import, F5 run step, etc.)
- Recent files menu
- Save/load project state
- Console/log panel (toggle-able)
