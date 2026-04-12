"""Verify model tree <-> main window <-> property browser wiring works."""
import sys
import pytest

# QPixmap requires QApplication to exist before module-level icon creation
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)


# ==================================================================
# Property browser key mapping
# ==================================================================

def test_item_mapping_uses_key_constants():
    from ui.model_tree import (
        KEY_GEOMETRY, KEY_MESH, KEY_CRACK, KEY_MATERIAL,
        KEY_STEPS, KEY_RESULTS, KEY_FINAL, KEY_CONTOURS, KEY_STEPS_GROUP,
    )
    from ui.property_browser import _ITEM_MAPPING

    assert KEY_GEOMETRY in _ITEM_MAPPING
    assert KEY_MESH in _ITEM_MAPPING
    assert KEY_CRACK in _ITEM_MAPPING
    assert KEY_MATERIAL in _ITEM_MAPPING
    assert KEY_STEPS in _ITEM_MAPPING
    assert KEY_RESULTS in _ITEM_MAPPING
    assert KEY_CONTOURS in _ITEM_MAPPING
    assert KEY_STEPS_GROUP in _ITEM_MAPPING
    assert KEY_FINAL in _ITEM_MAPPING

    assert _ITEM_MAPPING[KEY_GEOMETRY] == ["FRD"]
    assert _ITEM_MAPPING[KEY_CRACK] == ["Crack Surface"]
    assert _ITEM_MAPPING[KEY_MATERIAL] == ["Material"]
    assert _ITEM_MAPPING[KEY_STEPS] == ["Controls"]
    assert _ITEM_MAPPING[KEY_RESULTS] == ["Results"]
    assert _ITEM_MAPPING[KEY_CONTOURS] == ["Results"]
    assert _ITEM_MAPPING[KEY_STEPS_GROUP] == ["Results"]


def test_key_to_actor_mapping():
    from ui.model_tree import KEY_GEOMETRY, KEY_MESH, KEY_CRACK
    from ui.main_window import _KEY_TO_ACTOR

    assert _KEY_TO_ACTOR[KEY_GEOMETRY] == "Geometry"
    assert _KEY_TO_ACTOR[KEY_MESH] == "Mesh"
    assert _KEY_TO_ACTOR[KEY_CRACK] == "Crack Surface"


def test_step_prefix_detection():
    from ui.model_tree import KEY_STEP_PREFIX

    test_key = KEY_STEP_PREFIX + "5"
    assert test_key.startswith(KEY_STEP_PREFIX)
    assert test_key == "results.step.5"


def test_property_browser_step_key_routing():
    from ui.model_tree import KEY_STEP_PREFIX
    from ui.property_browser import PropertyBrowser

    pb = PropertyBrowser()
    # Step-N keys should show only Results category
    pb.update_for_item(KEY_STEP_PREFIX + "3")
    for i in range(pb.topLevelItemCount()):
        cat_item = pb.topLevelItem(i)
        if cat_item.text(0) == "Results":
            assert not cat_item.isHidden()
        else:
            assert cat_item.isHidden(), f"{cat_item.text(0)} should be hidden for step key"


# ==================================================================
# Model tree
# ==================================================================

def test_model_tree_populate_results():
    from ui.model_tree import ModelTree, KEY_STEP_PREFIX

    tree = ModelTree()
    step_data = [
        {"inc": 0, "crlength": 0.2, "cycles": 0, "max_dkeq": 500.0, "n_front_nodes": 25},
        {"inc": 1, "crlength": 0.25, "cycles": 100, "max_dkeq": 520.0, "n_front_nodes": 26},
        {"inc": 2, "crlength": 0.3, "cycles": 250, "max_dkeq": 540.0, "n_front_nodes": 27},
    ]
    tree.populate_results(step_data)

    # Steps are now under _steps_group_item (Results > Steps)
    steps_grp = tree._steps_group_item
    assert steps_grp.childCount() == 4  # 3 steps + Final Crack

    # Results item has 2 static children: Contours + Steps groups
    assert tree._res_item.childCount() == 2

    # Check first step label
    first = steps_grp.child(0)
    assert "Step 0" in first.text(0)
    assert first.data(0, 0x0100) == KEY_STEP_PREFIX + "0"  # UserRole = 0x0100

    # Check Final Crack
    last = steps_grp.child(3)
    assert "Final Crack" in last.text(0)


def test_model_tree_contour_nodes():
    """Contours sub-tree must have static children for each CONTOUR_TYPES entry."""
    from ui.model_tree import ModelTree, KEY_CONTOUR_PREFIX, CONTOUR_TYPES

    tree = ModelTree()
    contours_item = tree._contours_item
    assert contours_item.childCount() == len(CONTOUR_TYPES)

    # Each child should have the right key
    for i in range(contours_item.childCount()):
        child = contours_item.child(i)
        label = child.text(0)
        assert label in CONTOUR_TYPES
        assert child.data(0, 0x0100) == KEY_CONTOUR_PREFIX + label


def test_model_tree_contour_signal():
    """Clicking a contour node must emit contour_selected with the label."""
    from ui.model_tree import ModelTree

    tree = ModelTree()
    received = []
    tree.contour_selected.connect(lambda lbl: received.append(lbl))

    # Select the first contour child (K1)
    first_contour = tree._contours_item.child(0)
    tree.setCurrentItem(first_contour)

    assert len(received) == 1
    assert received[0] == "K1"


def test_model_tree_set_geometry_loaded():
    from ui.model_tree import ModelTree

    tree = ModelTree()
    tree.set_geometry_loaded("masterII.frd", 10017, 2048)
    assert "masterII.frd" in tree._geom_item.text(0)
    assert "2048" in tree._mesh_item.text(0)
    assert "10017" in tree._mesh_item.text(0)


def test_model_tree_set_crack_loaded():
    from ui.model_tree import ModelTree

    tree = ModelTree()
    tree.set_crack_loaded("penny.stl", 120, 15)
    text = tree._crack_item.text(0)
    assert "120" in text
    assert "15" in text
    assert "S3" in text


# ==================================================================
# Toolbar: new structure
# ==================================================================

def _make_stub_window():
    """Create a stub QMainWindow with all slots expected by ToolbarBuilder."""
    from PyQt6.QtWidgets import QMainWindow

    class _StubWindow(QMainWindow):
        def load_frd(self): pass
        def load_crack(self): pass
        def goto_crack(self): pass
        def goto_material(self): pass
        def goto_steps(self): pass
        def run_analysis(self): pass
        def plot_crack(self): pass
        def show_contour(self): pass
        def show_graphs(self): pass
        def toggle_scalar_bar(self, c=False): pass
        def auto_range(self): pass
        def global_range(self): pass
        def animate_steps(self): pass
        def probe_value(self): pass
        def export_csv(self): pass
        def export_image(self): pass

    return _StubWindow()


class _StubViewer:
    """Minimal viewer stub for Display-tab tests."""
    def fit_all(self): pass
    def reset_view(self): pass
    def view_front(self): pass
    def view_top(self): pass
    def view_right(self): pass
    def view_isometric(self): pass
    def set_display_mode(self, m): pass
    def set_actor_visibility(self, n, v): pass
    def set_edges_visible(self, v): pass


def test_toolbar_has_run_action():
    """The unified Run button must exist and be initially disabled."""
    from ui.toolbar import ToolbarBuilder

    win = _make_stub_window()
    builder = ToolbarBuilder(win)
    builder.build()

    assert "run_analysis" in builder.actions
    assert not builder.actions["run_analysis"].isEnabled()   # disabled at start
    assert "load_frd" in builder.actions
    assert builder.actions["load_frd"].isEnabled()           # always enabled
    assert "show_contour" in builder.actions
    assert not builder.actions["show_contour"].isEnabled()   # disabled at start


def test_toolbar_has_model_actions():
    """MODEL group: Crack, Material, Steps — all enabled at start."""
    from ui.toolbar import ToolbarBuilder

    win = _make_stub_window()
    builder = ToolbarBuilder(win)
    builder.build()

    assert "goto_crack" in builder.actions
    assert builder.actions["goto_crack"].isEnabled()
    assert "goto_material" in builder.actions
    assert builder.actions["goto_material"].isEnabled()
    assert "goto_steps" in builder.actions
    assert builder.actions["goto_steps"].isEnabled()


def test_toolbar_no_old_actions():
    """Old split-workflow actions must NOT exist in the ribbon."""
    from ui.toolbar import ToolbarBuilder

    win = _make_stub_window()
    builder = ToolbarBuilder(win)
    builder.build()

    # Old workflow actions
    assert "build_inp" not in builder.actions
    assert "run_ccx" not in builder.actions
    assert "open_results" not in builder.actions
    assert "validate" not in builder.actions

    # Old view action names (superseded by display_ prefix in Display tab)
    assert "fit_view" not in builder.actions
    assert "view_wireframe" not in builder.actions
    assert "view_surface" not in builder.actions
    assert "view_surface_edges" not in builder.actions


def test_ribbon_has_display_tab():
    """When built with a viewer, the ribbon should have a Display tab
    with camera, render, and visibility actions."""
    from ui.toolbar import ToolbarBuilder

    win = _make_stub_window()
    viewer = _StubViewer()
    builder = ToolbarBuilder(win, viewer=viewer)
    builder.build()

    # Display actions should be registered
    for key in ("display_fit", "display_reset", "display_front",
                "display_top", "display_right", "display_iso",
                "display_wire", "display_surface", "display_sedge",
                "display_geometry", "display_mesh",
                "display_crack", "display_edges"):
        assert key in builder.actions, f"Missing display action: {key}"

    # Render mode actions should be checkable and exclusive
    assert builder.actions["display_wire"].isCheckable()
    assert builder.actions["display_surface"].isCheckable()
    assert builder.actions["display_sedge"].isCheckable()
    assert builder.actions["display_sedge"].isChecked()   # default

    # Visibility toggles should be checkable
    assert builder.actions["display_geometry"].isCheckable()
    assert builder.actions["display_mesh"].isCheckable()
    assert builder.actions["display_crack"].isCheckable()
    assert builder.actions["display_edges"].isCheckable()

    # Geometry starts unchecked (hidden by default), Mesh starts checked
    assert not builder.actions["display_geometry"].isChecked()
    assert builder.actions["display_mesh"].isChecked()


def test_ribbon_without_viewer_has_no_display():
    """Without a viewer, the Display tab should not be built."""
    from ui.toolbar import ToolbarBuilder

    win = _make_stub_window()
    builder = ToolbarBuilder(win)           # no viewer
    builder.build()

    assert "display_fit" not in builder.actions
    assert "display_wire" not in builder.actions


def test_ribbon_export_csv_action():
    """Export CSV action should exist and be initially disabled."""
    from ui.toolbar import ToolbarBuilder

    win = _make_stub_window()
    builder = ToolbarBuilder(win)
    builder.build()

    assert "export_csv" in builder.actions
    assert not builder.actions["export_csv"].isEnabled()


def test_ribbon_result_tab_actions():
    """New Result tab actions should exist and be initially disabled."""
    from ui.toolbar import ToolbarBuilder

    win = _make_stub_window()
    builder = ToolbarBuilder(win)
    builder.build()

    for key in ("show_contour", "plot_front", "show_graphs",
                "toggle_scalar_bar", "auto_range", "global_range",
                "animate", "probe", "export_csv", "export_image"):
        assert key in builder.actions, f"Missing Result action: {key}"
        assert not builder.actions[key].isEnabled(), f"{key} should be disabled at start"

    # Scalar bar toggle must be checkable
    assert builder.actions["toggle_scalar_bar"].isCheckable()

    # Old actions must NOT exist
    assert "plot_keq" not in builder.actions
    assert "plot_sif" not in builder.actions


# ==================================================================
# Graphs dialog
# ==================================================================

def test_graphs_dialog_no_data():
    """GraphsDialog should not crash with empty data."""
    from ui.graphs_dialog import GraphsDialog
    dlg = GraphsDialog(keq_increments=[], parent=None)
    assert dlg.windowTitle() == "Crack Growth Diagrams"
    dlg.close()


def test_extract_increment_data_empty():
    from ui.graphs_dialog import _extract_increment_data
    assert _extract_increment_data([]) == []


# ==================================================================
# Post-processing panel
# ==================================================================

def test_postproc_panel_exists_on_main_window():
    """MainWindow must expose a PostProcPanel instance."""
    from ui.main_window import MainWindow
    from ui.postproc_panel import PostProcPanel

    # PostProcPanel is imported and used in MainWindow
    assert hasattr(MainWindow, '_connect_signals')
    # Verify the import path works
    panel = PostProcPanel()
    assert hasattr(panel, 'row_selected')
    assert hasattr(panel, 'set_data')
    assert hasattr(panel, 'highlight_step')
    assert hasattr(panel, 'clear')


def test_postproc_panel_empty():
    """PostProcPanel should handle empty data without crashing."""
    from ui.postproc_panel import PostProcPanel

    panel = PostProcPanel()
    panel.set_data([])
    panel.clear()


def test_postproc_extract_data_empty():
    """extract_postproc_data should return empty list for no input."""
    from ui.postproc_panel import extract_postproc_data
    assert extract_postproc_data([]) == []


def test_postproc_panel_highlight_no_data():
    """highlight_step should not crash when there is no data."""
    from ui.postproc_panel import PostProcPanel

    panel = PostProcPanel()
    panel.highlight_step(0)    # no data loaded, must not raise


def test_postproc_panel_row_signal():
    """Clicking a table row emits row_selected(inc)."""
    from ui.postproc_panel import PostProcPanel, _DataTable

    table = _DataTable()
    received = []
    table.row_clicked.connect(lambda inc: received.append(inc))

    # Populate with synthetic data
    data = [
        {"inc": 0, "cycles": 0, "crlength": 0.2, "max_dkeq": 500,
         "max_keqmin": 100, "max_keqmax": 600, "max_k1worst": 450,
         "max_k2worst": 30, "max_k3worst": 10, "mean_phi": 5.0,
         "max_dadn": 1e-4, "n_nodes": 20},
        {"inc": 1, "cycles": 100, "crlength": 0.25, "max_dkeq": 520,
         "max_keqmin": 110, "max_keqmax": 620, "max_k1worst": 460,
         "max_k2worst": 32, "max_k3worst": 11, "mean_phi": 5.1,
         "max_dadn": 1.1e-4, "n_nodes": 21},
    ]
    table.populate(data)

    # Simulate selecting row 1 (inc=1)
    table._table.setCurrentCell(1, 0)
    assert 1 in received


def test_main_window_has_postproc_handler():
    """MainWindow must have _on_postproc_row_selected and _show_step."""
    from ui.main_window import MainWindow

    assert hasattr(MainWindow, '_on_postproc_row_selected')
    assert hasattr(MainWindow, '_show_step')
    assert hasattr(MainWindow, '_on_step_selected')


# ==================================================================
# Viewer toolbar
# ==================================================================

def test_viewer_toolbar_has_camera_buttons():
    """ViewerToolbar must expose camera preset buttons."""
    from ui.viewer_toolbar import ViewerToolbar

    class _StubViewer:
        def fit_all(self): pass
        def reset_view(self): pass
        def view_front(self): pass
        def view_top(self): pass
        def view_right(self): pass
        def view_isometric(self): pass
        def set_display_mode(self, m): pass
        def set_actor_visibility(self, n, v): pass
        def set_edges_visible(self, v): pass

    vt = ViewerToolbar(_StubViewer())
    # Should instantiate without error and have children
    assert vt.objectName() == "viewerToolbar"
    assert vt.layout().count() > 0


def test_geometry_and_mesh_are_independent_actors():
    """Geometry and Mesh must map to different actor names."""
    from ui.model_tree import _ACTOR_MAP, KEY_GEOMETRY, KEY_MESH

    assert _ACTOR_MAP[KEY_GEOMETRY] != _ACTOR_MAP[KEY_MESH]
    assert _ACTOR_MAP[KEY_GEOMETRY] == "Geometry"
    assert _ACTOR_MAP[KEY_MESH] == "Mesh"


def test_model_tree_context_menu_show_hide():
    """Context menu _set_visibility updates hidden_actors and emits signal."""
    from ui.model_tree import ModelTree

    tree = ModelTree()
    received = []
    tree.visibility_toggled.connect(lambda a, v: received.append((a, v)))

    # Hide Geometry
    tree._set_visibility("Geometry", False)
    assert "Geometry" in tree._hidden_actors
    assert received[-1] == ("Geometry", False)

    # Show Geometry
    tree._set_visibility("Geometry", True)
    assert "Geometry" not in tree._hidden_actors
    assert received[-1] == ("Geometry", True)

    # Mesh independent
    tree._set_visibility("Mesh", False)
    assert "Mesh" in tree._hidden_actors
    assert "Geometry" not in tree._hidden_actors


def test_main_window_has_view_switch_methods():
    """MainWindow must have Geometry/Mesh view-switching methods."""
    from ui.main_window import MainWindow

    assert hasattr(MainWindow, '_switch_to_geometry_view')
    assert hasattr(MainWindow, '_switch_to_mesh_view')
    assert hasattr(MainWindow, '_sync_ribbon_toggle')


def test_main_window_has_goto_crack():
    """MainWindow must have goto_crack method."""
    from ui.main_window import MainWindow
    assert hasattr(MainWindow, 'goto_crack')


def test_main_window_has_contour_methods():
    """MainWindow must have tree-driven contour display methods."""
    from ui.main_window import MainWindow
    assert hasattr(MainWindow, '_on_contour_selected')
    assert hasattr(MainWindow, '_show_contour')
    assert hasattr(MainWindow, 'show_contour')
    assert hasattr(MainWindow, 'toggle_scalar_bar')
    assert hasattr(MainWindow, 'export_image')


# ==================================================================
# Probe / Query
# ==================================================================

def test_probe_dialog_creation():
    """ProbeDialog should display formatted result text."""
    from ui.probe_dialog import ProbeDialog

    dlg = ProbeDialog()
    dlg.set_result(2451, 12.431, -4.220, 8.551, 12, "K1", 31.42)
    text = dlg._label.text()
    assert "2451" in text
    assert "K1" in text
    assert "31.42" in text
    assert "12.431" in text
    dlg.close()


def test_probe_dialog_update():
    """ProbeDialog must update when set_result is called again."""
    from ui.probe_dialog import ProbeDialog

    dlg = ProbeDialog()
    dlg.set_result(100, 1.0, 2.0, 3.0, 5, "K1", 10.0)
    assert "K1" in dlg._label.text()

    dlg.set_result(100, 1.0, 2.0, 3.0, 5, "DeltaKEQ", 28.73)
    text = dlg._label.text()
    assert "DeltaKEQ" in text
    assert "28.73" in text
    assert "K1" not in text
    dlg.close()


def test_viewer_has_probe_api():
    """ViewerWidget must expose probe mode API and signal."""
    from ui.viewer_widget import ViewerWidget
    assert hasattr(ViewerWidget, 'set_probe_mode')
    assert hasattr(ViewerWidget, 'point_picked')
    assert hasattr(ViewerWidget, 'show_probe_marker')


def test_main_window_has_probe_methods():
    """MainWindow must have probe wiring methods."""
    from ui.main_window import MainWindow
    assert hasattr(MainWindow, 'probe_value')
    assert hasattr(MainWindow, '_on_point_picked')
    assert hasattr(MainWindow, '_show_probe_result')
    assert hasattr(MainWindow, '_refresh_probe')


def test_ribbon_probe_is_checkable():
    """Probe action must be checkable (toggle mode)."""
    from ui.toolbar import ToolbarBuilder

    win = _make_stub_window()
    builder = ToolbarBuilder(win)
    builder.build()

    assert "probe" in builder.actions
    assert builder.actions["probe"].isCheckable()


# ==================================================================
# Animation
# ==================================================================

def test_animation_dialog_creation():
    """AnimationDialog should initialise with correct step count."""
    from ui.animation_dialog import AnimationDialog

    dlg = AnimationDialog(5, ["Step 0", "Step 1", "Step 2", "Step 3", "Step 4"])
    assert dlg._n_steps == 5
    assert dlg._current == 0
    assert dlg._slider.maximum() == 4
    dlg.close()


def test_animation_dialog_step_navigation():
    """Step forward/back/first/last must update _current and emit signal."""
    from ui.animation_dialog import AnimationDialog

    dlg = AnimationDialog(5)
    received = []
    dlg.step_changed.connect(lambda idx: received.append(idx))

    dlg._go_next()       # 0 → 1
    assert dlg._current == 1
    assert received[-1] == 1

    dlg._go_next()       # 1 → 2
    dlg._go_prev()       # 2 → 1
    assert dlg._current == 1

    dlg._go_last()       # → 4
    assert dlg._current == 4

    dlg._go_first()      # → 0
    assert dlg._current == 0

    dlg.close()


def test_animation_dialog_slider_emits():
    """Dragging the slider must emit step_changed."""
    from ui.animation_dialog import AnimationDialog

    dlg = AnimationDialog(10)
    received = []
    dlg.step_changed.connect(lambda idx: received.append(idx))

    dlg._slider.setValue(7)
    assert 7 in received
    dlg.close()


def test_animation_dialog_bounds():
    """Step navigation must clamp at 0 and n_steps-1."""
    from ui.animation_dialog import AnimationDialog

    dlg = AnimationDialog(3)
    dlg._go_prev()       # already at 0 — should stay
    assert dlg._current == 0

    dlg._set_step(2)
    dlg._go_next()       # at max — should stay
    assert dlg._current == 2
    dlg.close()


def test_main_window_has_animation_methods():
    """MainWindow must have animation wiring methods."""
    from ui.main_window import MainWindow

    assert hasattr(MainWindow, 'animate_steps')
    assert hasattr(MainWindow, '_animate_to_step')
    assert hasattr(MainWindow, '_show_step_contour')
    assert hasattr(MainWindow, '_get_step_list')
    assert hasattr(MainWindow, '_build_animation_crack_mesh')
