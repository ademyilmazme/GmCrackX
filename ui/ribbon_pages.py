"""
Page builders for each ribbon tab.

Each function populates a ``RibbonTab`` with panels and buttons,
registering every ``QAction`` in the shared *actions* dict so that
``RibbonBuilder.set_enabled()`` can control them.

Tabs
----
  File    — Load / Save / Open
  Home    — Model setup + Run
  Result  — Plot / Graph / Export
  Display — Camera presets, render mode, visibility toggles
  Tools   — Result conversion utilities
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QActionGroup, QIcon

from ui.ribbon import RibbonTab

_BMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bmp")


def _ico(filename: str) -> QIcon:
    path = os.path.join(_BMP_DIR, filename)
    return QIcon(path) if os.path.isfile(path) else QIcon()


# =====================================================================
# Helper
# =====================================================================

def _act(actions: dict, label: str, key: str, tip: str,
         slot=None) -> QAction:
    """Create a QAction, register it in *actions*, and connect *slot*."""
    a = QAction(label)
    a.setToolTip(tip)
    if slot is not None:
        a.triggered.connect(slot)
    actions[key] = a
    return a


# =====================================================================
# File tab
# =====================================================================

def build_file_tab(tab: RibbonTab, main_window, actions: dict) -> None:
    load = tab.add_panel("LOAD")
    frd_act = _act(actions, "Load FRD", "load_frd",
                   "Load FRD stress field",
                   main_window.load_frd)
    frd_act.setIcon(_ico("import_frd.png"))
    load.add_button(frd_act).setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonIconOnly)
    crack_load_act = _act(actions, "Load Crack", "load_crack",
                          "Load crack geometry (.stl / .brep / .step)",
                          main_window.load_crack)
    crack_load_act.setIcon(_ico("load_crack.png"))
    load.add_button(crack_load_act).setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonIconOnly)

    project = tab.add_panel("PROJECT")

    def _proj_btn(action, filename):
        action.setIcon(_ico(filename))
        project.add_button(action).setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly)

    _proj_btn(_act(actions, "Save Project", "save_project",
                   "Save current project state"),
              "save.ico")
    _proj_btn(_act(actions, "Open Project", "open_project",
                   "Open a saved project"),
              "open.ico")
    tab.finish()


# =====================================================================
# Home tab
# =====================================================================

def build_home_tab(tab: RibbonTab, main_window, actions: dict) -> None:
    model = tab.add_panel("MODEL")
    def _home_btn(action, filename):
        action.setIcon(_ico(filename))
        model.add_button(action).setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly)

    _home_btn(_act(actions, "Crack", "goto_crack",
                   "Navigate to crack surface properties",
                   main_window.goto_crack),
              "crack.png")

    _home_btn(_act(actions, "Insert", "insert_crack",
                   "Insert a new parametric crack",
                   main_window._on_crack_insert_requested),
              "crack.png")

    _home_btn(_act(actions, "Material", "goto_material",
                   "Edit Paris-law constants",
                   main_window.goto_material),
              "Material.ico")

    _home_btn(_act(actions, "Steps", "goto_steps",
                   "Edit propagation controls",
                   main_window.goto_steps),
              "Step.ico")

    solve = tab.add_panel("SOLVE")
    solve.add_button(
        _act(actions, "\u25b6  Run", "run_analysis",
             "Run crack propagation analysis",
             main_window.run_analysis),
        emphasise=True,
    )
    tab.finish()


# =====================================================================
# Result tab
# =====================================================================

def build_result_tab(tab: RibbonTab, main_window, actions: dict) -> None:

    def _result_btn(panel, action, filename):
        action.setIcon(_ico(filename))
        panel.add_button(action).setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly)

    # ── VIEW ───────────────────────────────────────────────
    view = tab.add_panel("VIEW")
    _result_btn(view, _act(actions, "Show Contour", "show_contour",
                            "Display selected contour field on crack front",
                            main_window.show_contour),
                "show_contour.png")
    _result_btn(view, _act(actions, "Crack Front", "plot_front",
                            "Show crack surface + front lines",
                            main_window.plot_crack),
                "crack_front.png")
    _result_btn(view, _act(actions, "Graphs", "show_graphs",
                            "Crack growth diagrams (a\u2013N, Paris, \u0394K)",
                            main_window.show_graphs),
                "graph.png")

    sb_act = _act(actions, "Scalar Bar", "toggle_scalar_bar",
                  "Show / hide the colour scalar bar",
                  main_window.toggle_scalar_bar)
    sb_act.setCheckable(True)
    sb_act.setChecked(False)
    _result_btn(view, sb_act, "scalar_bar.png")

    # ── RANGE ──────────────────────────────────────────────
    rng = tab.add_panel("RANGE")
    _result_btn(rng, _act(actions, "Auto Range", "auto_range",
                           "Scale contour to current step min/max",
                           main_window.auto_range),
                "auto_range.png")
    _result_btn(rng, _act(actions, "Global Range", "global_range",
                           "Scale contour to all-steps min/max",
                           main_window.global_range),
                "global_range.png")

    # ── TOOLS ──────────────────────────────────────────────
    tools = tab.add_panel("TOOLS")

    anim_act = _act(actions, "Animate", "animate",
                    "Animate through propagation steps",
                    main_window.animate_steps)
    anim_act.setIcon(_ico("Animate.ico"))
    tools.add_button(anim_act).setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonIconOnly)

    probe_act = _act(actions, "Probe", "probe",
                     "Probe scalar value at a node",
                     main_window.probe_value)
    probe_act.setCheckable(True)
    probe_act.setIcon(_ico("probe.ico"))
    tools.add_button(probe_act).setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonIconOnly)

    # ── EXPORT ─────────────────────────────────────────────
    export = tab.add_panel("EXPORT")

    csv_act = _act(actions, "Export CSV", "export_csv",
                   "Export results table to CSV file",
                   main_window.export_csv)
    csv_act.setIcon(_ico("export_csv.png"))
    export.add_button(csv_act).setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonIconOnly)

    img_act = _act(actions, "Export Image", "export_image",
                   "Save current 3D view as PNG",
                   main_window.export_image)
    img_act.setIcon(_ico("export_image.png"))
    export.add_button(img_act).setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonIconOnly)
    tab.finish()


# =====================================================================
# Display tab  (absorbs the former viewer_toolbar.py)
# =====================================================================

def build_display_tab(tab: RibbonTab, viewer, actions: dict) -> None:
    # ── CAMERA ──────────────────────────────────────────────
    cam = tab.add_panel("CAMERA")
    def _icon_only_btn(action, filename):
        action.setIcon(_ico(filename))
        btn = cam.add_button(action)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        return btn

    _icon_only_btn(_act(actions, "Fit All", "display_fit",
                        "Reset camera to fit all objects",
                        lambda c: viewer.fit_all()),
                   "ZoomToFit.ico")

    _icon_only_btn(_act(actions, "Reset", "display_reset",
                        "Reset to default isometric view",
                        lambda c: viewer.reset_view()),
                   "reset.png")

    _icon_only_btn(_act(actions, "Front", "display_front",
                        "View from front (\u2013Z)",
                        lambda c: viewer.view_front()),
                   "Front.ico")

    _icon_only_btn(_act(actions, "Top", "display_top",
                        "View from top (\u2013Y)",
                        lambda c: viewer.view_top()),
                   "Top.ico")

    _icon_only_btn(_act(actions, "Right", "display_right",
                        "View from right (\u2013X)",
                        lambda c: viewer.view_right()),
                   "Right.ico")

    _icon_only_btn(_act(actions, "Iso", "display_iso",
                        "Standard isometric view",
                        lambda c: viewer.view_isometric()),
                   "Isometric.ico")

    # ── RENDER (exclusive display mode) ─────────────────────
    render = tab.add_panel("RENDER")

    def _render_btn(action, filename):
        action.setIcon(_ico(filename))
        btn = render.add_button(action)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        return btn

    wire_act = _act(actions, "Wire", "display_wire",
                    "Wireframe display",
                    lambda c: viewer.set_display_mode("wireframe"))
    wire_act.setCheckable(True)

    surf_act = _act(actions, "Surface", "display_surface",
                    "Solid surface display",
                    lambda c: viewer.set_display_mode("surface"))
    surf_act.setCheckable(True)

    sedge_act = _act(actions, "S+Edge", "display_sedge",
                     "Surface + edge lines",
                     lambda c: viewer.set_display_mode("surface_edges"))
    sedge_act.setCheckable(True)
    sedge_act.setChecked(True)

    ag = QActionGroup(render)
    ag.setExclusive(True)
    ag.addAction(wire_act)
    ag.addAction(surf_act)
    ag.addAction(sedge_act)
    render._action_group = ag           # prevent garbage collection

    _render_btn(wire_act,  "Wireframe.ico")
    _render_btn(surf_act,  "Surface.ico")
    _render_btn(sedge_act, "surface_edges.ico")

    # ── VISIBILITY (independent toggles) ────────────────────
    vis = tab.add_panel("VISIBILITY")

    def _vis_btn(action, filename):
        action.setIcon(_ico(filename))
        btn = vis.add_button(action)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        return btn

    geom_act = _act(actions, "Geometry", "display_geometry",
                    "Toggle geometry surface visibility",
                    lambda c: viewer.set_actor_visibility("Geometry", c))
    geom_act.setCheckable(True)
    geom_act.setChecked(False)
    _vis_btn(geom_act, "Geometry.ico")

    mesh_act = _act(actions, "Mesh", "display_mesh",
                    "Toggle FE mesh visibility",
                    lambda c: viewer.set_actor_visibility("Mesh", c))
    mesh_act.setCheckable(True)
    mesh_act.setChecked(True)
    _vis_btn(mesh_act, "Mesh.ico")

    crack_act = _act(actions, "Crack", "display_crack",
                     "Toggle crack surface visibility",
                     lambda c: viewer.set_actor_visibility("Crack Surface", c))
    crack_act.setCheckable(True)
    crack_act.setChecked(True)
    _vis_btn(crack_act, "crack.png")

    edge_act = _act(actions, "Edges", "display_edges",
                    "Toggle edge line visibility",
                    viewer.set_edges_visible)
    edge_act.setCheckable(True)
    edge_act.setChecked(True)
    _vis_btn(edge_act, "edge.png")

    tab.finish()


# =====================================================================
# Tools tab
# =====================================================================

def build_tools_tab(tab: RibbonTab, main_window, actions: dict) -> None:
    convert = tab.add_panel("CONVERT")

    conv_act = _act(
        actions, "Convert Results", "convert_results",
        "Convert solver result files (RST, …) to CalculiX FRD",
        main_window.convert_results,
    )
    conv_act.setIcon(_ico("import_frd.png"))
    convert.add_button(conv_act).setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonIconOnly
    )
    tab.finish()
