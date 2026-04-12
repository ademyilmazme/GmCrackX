"""
Ribbon builder with backward-compatible ``ToolbarBuilder`` alias.

Replaces the old grouped-QToolBar approach with an ANSYS Mechanical-style
ribbon (see ``ribbon.py`` and ``ribbon_pages.py``).

Public API (unchanged from the previous ToolbarBuilder)
-------------------------------------------------------
  actions : dict[str, QAction]
      Maps action keys to their QActions.
  set_enabled(key, bool)
      Enable / disable a specific action.
  ribbon : RibbonBar
      The ribbon widget — caller places it in the layout.
"""
from __future__ import annotations


class RibbonBuilder:
    """Builds the ANSYS Mechanical-style ribbon for GmCrackX.

    Parameters
    ----------
    main_window : QMainWindow
        The main window whose slots are wired to ribbon actions.
    viewer : ViewerWidget or None
        If provided, the Display tab is built and wired to the viewer.
    """

    def __init__(self, main_window, viewer=None):
        self.main_window = main_window
        self.viewer = viewer
        self.actions: dict = {}
        self.ribbon = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self):
        from ui.ribbon import RibbonBar
        from ui.ribbon_pages import (
            build_file_tab, build_home_tab,
            build_result_tab, build_display_tab, build_tools_tab,
        )

        self.ribbon = RibbonBar()

        file_tab = self.ribbon.add_tab("File")
        build_file_tab(file_tab, self.main_window, self.actions)

        home_tab = self.ribbon.add_tab("Home")
        build_home_tab(home_tab, self.main_window, self.actions)

        result_tab = self.ribbon.add_tab("Result")
        build_result_tab(result_tab, self.main_window, self.actions)

        if self.viewer is not None:
            display_tab = self.ribbon.add_tab("Display")
            build_display_tab(display_tab, self.viewer, self.actions)

        tools_tab = self.ribbon.add_tab("Tools")
        build_tools_tab(tools_tab, self.main_window, self.actions)

        # Default to File tab (index 0)
        self.ribbon.set_current_tab(0)

        self._set_initial_state()

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _set_initial_state(self):
        """Only FILE + MODEL actions are available at launch."""
        self.set_enabled("run_analysis",  False)
        self.set_enabled("show_contour",  False)
        self.set_enabled("plot_front",    False)
        self.set_enabled("show_graphs",   False)
        self.set_enabled("toggle_scalar_bar", False)
        self.set_enabled("auto_range",    False)
        self.set_enabled("global_range",  False)
        self.set_enabled("animate",       False)
        self.set_enabled("probe",         False)
        self.set_enabled("export_csv",    False)
        self.set_enabled("export_image",  False)
        # Placeholders — not yet implemented
        self.set_enabled("save_project",  False)
        self.set_enabled("open_project",  False)

    def set_enabled(self, slot_name: str, enabled: bool):
        if slot_name in self.actions:
            self.actions[slot_name].setEnabled(enabled)


# Backward-compatible alias so existing imports keep working.
ToolbarBuilder = RibbonBuilder
