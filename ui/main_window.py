"""
GmCrackX main window — CAE-style single-button workflow.

Ribbon tabs:  File | Home | Result | Display

The user loads an FRD + crack geometry, edits material/controls in the
property browser, and clicks **Run**.  Everything else (INP generation,
CalculiX execution, result parsing, tree population, visualisation) is
handled automatically.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QFileDialog, QMessageBox,
    QWidget, QVBoxLayout,
)
from PyQt6.QtCore import Qt

from ui.model_tree import (
    ModelTree, KEY_GEOMETRY, KEY_MESH, KEY_CRACK, KEY_MATERIAL,
    KEY_STEPS, KEY_RESULTS, KEY_STEP_PREFIX, KEY_FINAL,
    KEY_CONTOURS, KEY_CONTOUR_PREFIX, KEY_STEPS_GROUP, CONTOUR_TYPES,
)
from ui.property_browser import PropertyBrowser
from ui.viewer_widget import ViewerWidget
from ui.toolbar import ToolbarBuilder
from ui.status_manager import StatusManager
from ui.worker import Worker
from ui.postproc_panel import PostProcPanel


# Node key → VTK actor name (for highlighting on tree click)
_KEY_TO_ACTOR: dict[str, str] = {
    KEY_GEOMETRY: "Geometry",
    KEY_MESH:     "Mesh",
    KEY_CRACK:    "Crack Surface",
}


def _apply_transform_numpy(vertices, tx, ty, tz, rx, ry, rz, centroid):
    """Rotate around *centroid* (XYZ Euler, degrees) then translate."""
    import numpy as np
    rx_r, ry_r, rz_r = np.radians(rx), np.radians(ry), np.radians(rz)
    Rx = np.array([[1, 0, 0],
                   [0, np.cos(rx_r), -np.sin(rx_r)],
                   [0, np.sin(rx_r),  np.cos(rx_r)]])
    Ry = np.array([[ np.cos(ry_r), 0, np.sin(ry_r)],
                   [0, 1, 0],
                   [-np.sin(ry_r), 0, np.cos(ry_r)]])
    Rz = np.array([[np.cos(rz_r), -np.sin(rz_r), 0],
                   [np.sin(rz_r),  np.cos(rz_r), 0],
                   [0, 0, 1]])
    R = Rz @ Ry @ Rx
    return (vertices - centroid) @ R.T + centroid + np.array([tx, ty, tz])


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GmCrackX \u2014 CalculiX Crack Propagation")
        self.setMinimumSize(1200, 800)

        # --- Application state ---
        self._frd_path:       str | None = None
        self._crack_path:     str | None = None
        self._deck_path:      str | None = None
        self._output_frd_path: str | None = None
        self._prop_config     = None   # PropagationConfig
        self._prop_result     = None   # PropResult
        self._crack_surface   = None   # CrackSurfaceState
        self._output_frd_mesh = None   # FrdMesh from output (grown crack)
        self._worker: Worker | None = None
        self._active_contour: str | None = None  # current contour label (e.g. "K1")
        self._probe_nids: list[int] = []       # node IDs for current contour display
        self._probe_info: dict | None = None   # last picked node info
        self._probe_dlg = None                 # ProbeDialog instance
        self._crack_edit_dlg = None            # CrackEditDialog instance
        self._crack_pre_edit_vertices = None   # vertex snapshot for Cancel
        self._crack_insert_wizard = None       # CrackInsertWizard instance
        self._crack_pre_insert_state = None    # CrackSurfaceState snapshot for Cancel

        # --- Widgets ---
        self.model_tree       = ModelTree()
        self.property_browser = PropertyBrowser()
        self.viewer           = ViewerWidget()
        self.postproc_panel   = PostProcPanel()

        # --- Ribbon (built first so viewer reference is available) ---
        self.toolbar_builder = ToolbarBuilder(self, viewer=self.viewer)
        self.toolbar_builder.build()

        # --- Layout ---
        #  ┌── ribbon ────────────────────────────────────────┐
        #  ├── main (H) ──────────────────────────────────────┤
        #  │ ┌ left (V) ──┐  ┌ right (V) ───────────────────┐ │
        #  │ │ model_tree  │  │ viewer (3D)                  │ │
        #  │ │             │  │                              │ │
        #  │ ├─────────────┤  ├──────────────────────────────┤ │
        #  │ │ prop_browser│  │ postproc_panel (plot+table)  │ │
        #  │ └─────────────┘  └──────────────────────────────┘ │
        #  └───────────────────────────────────────────────────┘
        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self.model_tree)
        left.addWidget(self.property_browser)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 2)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.viewer)
        right.addWidget(self.postproc_panel)
        right.setSizes([600, 250])
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 1)

        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(left)
        main.addWidget(right)
        main.setSizes([280, 920])
        main.setStretchFactor(0, 0)
        main.setStretchFactor(1, 1)

        # Wrap ribbon + main splitter in a container widget
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self.toolbar_builder.ribbon)
        vbox.addWidget(main, 1)

        self.setCentralWidget(container)

        # --- Status bar ---
        self.status_manager = StatusManager(self.statusBar())

        # --- Signals ---
        self._connect_signals()

    def _connect_signals(self):
        self.model_tree.item_selected.connect(self.on_tree_item_selected)
        self.model_tree.visibility_toggled.connect(self._on_visibility_toggled)
        self.model_tree.step_selected.connect(self._on_step_selected)
        self.model_tree.contour_selected.connect(self._on_contour_selected)
        self.model_tree.crack_edit_requested.connect(self._on_crack_edit_requested)
        self.model_tree.crack_insert_requested.connect(self._on_crack_insert_requested)
        self.viewer.point_picked.connect(self._on_point_picked)
        self.property_browser.property_changed.connect(self.on_property_changed)
        self.postproc_panel.row_selected.connect(self._on_postproc_row_selected)

    # ==================================================================
    # Tree + property slots
    # ==================================================================

    def on_tree_item_selected(self, key: str):
        if key == KEY_GEOMETRY:
            self._switch_to_geometry_view()
        elif key == KEY_MESH:
            self._switch_to_mesh_view()
        else:
            actor_name = _KEY_TO_ACTOR.get(key)
            if actor_name:
                self.viewer.highlight_object(actor_name)
            else:
                self.viewer.clear_highlight()
        self.property_browser.update_for_item(key)
        self.status_manager.set_selected(key)

    def _on_visibility_toggled(self, actor_name: str, visible: bool):
        self.viewer.set_actor_visibility(actor_name, visible)

    def on_property_changed(self, category: str, prop: str, value: str):
        pass  # Material/Controls edits are read at run time

    # ==================================================================
    # FILE: Load FRD
    # ==================================================================

    def load_frd(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load FRD Stress Field", "", "FRD Files (*.frd)"
        )
        if not path:
            return

        self._frd_path = path
        self._set_busy(True)
        self.status_manager.set_message("Validating FRD file...")

        def task(progress_cb):
            progress_cb(10, "Parsing FRD...")
            from crack_io.frd_validator import FRDValidator
            from crack_io.frd_reader import read_frd_mesh
            validator = FRDValidator(path)
            frd_increment = validator.validate()
            progress_cb(70, "Parsing mesh geometry...")
            try:
                frd_mesh = read_frd_mesh(path)
            except Exception:
                frd_mesh = None
            progress_cb(100, "FRD validated")
            return (frd_increment, validator.report, frd_mesh)

        w = Worker(task)
        w.progress.connect(lambda pct, msg: self.status_manager.set_progress(pct, msg))
        w.finished.connect(self._on_frd_loaded)
        w.error.connect(self._on_worker_error)
        self._worker = w
        w.start()

    def _on_frd_loaded(self, result):
        frd_increment, report, frd_mesh = result

        n_stress = len(frd_increment.stresses)

        filename = self._frd_path.split("/")[-1].split("\\")[-1]
        self.property_browser.set_property("FRD", "File", filename)
        self.property_browser.set_property("FRD", "Status", "validated")

        # Update model tree
        n_nodes = len(frd_mesh.nodes) if frd_mesh else n_stress
        n_elems = len(frd_mesh.elements) if frd_mesh else 0
        self.model_tree.set_geometry_loaded(filename, n_nodes, n_elems)

        # Display mesh geometry from the FRD 2C/3C sections.
        # display_mesh(mesh_type="global") creates both Geometry + Mesh actors,
        # then we immediately switch to the Geometry view (clean CAD surface).
        if frd_mesh and frd_mesh.nodes:
            try:
                self._display_frd_mesh(frd_mesh, mesh_type="global")
                self.property_browser.set_property("Mesh", "Nodes", str(len(frd_mesh.nodes)))
                self.property_browser.set_property("Mesh", "Elements", str(len(frd_mesh.elements)))
                # Default to Geometry view and select it in the tree
                self._switch_to_geometry_view()
                self.model_tree.setCurrentItem(self.model_tree._geom_item)
                self.viewer.fit_all()
            except Exception as exc:
                print(f"FRD mesh display failed: {exc}")

        self.status_manager.set_message(f"FRD validated: {n_stress} stress nodes")
        self._set_busy(False)

    # ==================================================================
    # FILE: Load Crack
    # ==================================================================

    def load_crack(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Crack Geometry", "",
            "Crack Files (*.stl *.brep *.brp *.step *.stp);;"
            "STL Files (*.stl);;"
            "BREP Files (*.brep *.brp);;"
            "STEP Files (*.step *.stp)"
        )
        if not path:
            return

        self._crack_path = path
        self._set_busy(True)
        self.status_manager.set_message("Building S3 crack surface...")

        mesh_size = float(
            self.property_browser.get_property("Controls", "Max Increment") or "1.0"
        )

        def task(progress_cb):
            progress_cb(10, "Triangulating crack geometry...")
            from core.crack_surface_s3 import CrackSurfaceBuilder
            builder = CrackSurfaceBuilder(path, mesh_size=mesh_size)
            state = builder.build()
            progress_cb(100, "S3 surface built")
            return state

        w = Worker(task)
        w.progress.connect(lambda pct, msg: self.status_manager.set_progress(pct, msg))
        w.finished.connect(self._on_crack_loaded)
        w.error.connect(self._on_worker_error)
        self._worker = w
        w.start()

    def _on_crack_loaded(self, state):
        self._crack_surface = state

        filename = self._crack_path.split("/")[-1].split("\\")[-1]
        self.property_browser.set_property("Crack Surface", "File", filename)
        self.property_browser.set_property("Crack Surface", "Vertices", str(len(state.vertices)))
        self.property_browser.set_property("Crack Surface", "Triangles", str(len(state.triangles)))
        self.property_browser.set_property("Crack Surface", "Front Nodes", str(len(state.front_node_ids)))

        # Update model tree
        self.model_tree.set_crack_loaded(filename, len(state.triangles), len(state.front_node_ids))

        self.status_manager.set_message(
            f"Crack surface: {len(state.vertices)} verts, "
            f"{len(state.triangles)} tris, {len(state.front_node_ids)} front nodes"
        )
        self._set_busy(False)

        # Auto-display initial crack surface
        self.plot_crack()

    # ==================================================================
    # CRACK EDIT: translate / rotate dialog
    # ==================================================================

    def _on_crack_edit_requested(self):
        if self._crack_surface is None:
            self._show_error("Edit Crack", "No crack surface loaded.")
            return
        if len(self._crack_surface.vertices) == 0:
            return

        import numpy as np
        self._crack_pre_edit_vertices = self._crack_surface.vertices.copy()

        centroid = self._crack_surface.vertices.mean(axis=0)

        from ui.crack_edit_dialog import CrackEditDialog
        if self._crack_edit_dlg is not None:
            self._crack_edit_dlg.close()

        dlg = CrackEditDialog(parent=self)
        dlg.set_centroid(*centroid)
        dlg.transform_changed.connect(self._on_crack_transform_preview)
        dlg.accepted_transform.connect(self._on_crack_transform_apply)
        dlg.cancelled.connect(self._on_crack_transform_cancel)
        self._crack_edit_dlg = dlg
        dlg.show()

    def _on_crack_transform_preview(self, tx, ty, tz, rx, ry, rz):
        if self._crack_pre_edit_vertices is None:
            return
        centroid = tuple(self._crack_pre_edit_vertices.mean(axis=0))
        self.viewer.apply_actor_transform(
            "Crack Surface", tx, ty, tz, rx, ry, rz, centroid)

    def _on_crack_transform_apply(self, tx, ty, tz, rx, ry, rz):
        if self._crack_surface is None or self._crack_pre_edit_vertices is None:
            return
        centroid = self._crack_pre_edit_vertices.mean(axis=0)
        self._crack_surface.vertices = _apply_transform_numpy(
            self._crack_pre_edit_vertices, tx, ty, tz, rx, ry, rz, centroid)

        self.viewer.clear_actor_transform("Crack Surface")
        self.plot_crack()

        self._crack_pre_edit_vertices = self._crack_surface.vertices.copy()
        if self._crack_edit_dlg is not None:
            new_centroid = self._crack_surface.vertices.mean(axis=0)
            self._crack_edit_dlg.set_centroid(*new_centroid)
            self._crack_edit_dlg.set_last_applied(tx, ty, tz, rx, ry, rz)
            self._crack_edit_dlg.reset_values()
        self.status_manager.set_message("Crack transform applied")

    def _on_crack_transform_cancel(self):
        if self._crack_surface is not None and self._crack_pre_edit_vertices is not None:
            self._crack_surface.vertices = self._crack_pre_edit_vertices.copy()
        self.viewer.clear_actor_transform("Crack Surface")
        self.plot_crack()
        self._crack_pre_edit_vertices = None
        self._crack_edit_dlg = None
        self.status_manager.set_message("Crack edit cancelled")

    # ==================================================================
    # Crack Insert Wizard
    # ==================================================================

    def _on_crack_insert_requested(self):
        from ui.crack_insert_wizard import CrackInsertWizard

        # Snapshot current crack for cancel-restore
        self._crack_pre_insert_state = self._crack_surface

        if self._crack_insert_wizard is not None:
            self._crack_insert_wizard.close()

        wizard = CrackInsertWizard(parent=self)
        wizard.preview_requested.connect(self._on_crack_insert_preview)
        wizard.crack_accepted.connect(self._on_crack_insert_accepted)
        wizard.cancelled.connect(self._on_crack_insert_cancelled)
        self._crack_insert_wizard = wizard
        wizard.show()

    def _on_crack_insert_preview(self, defn):
        from core.crack_geometry import generate_crack_mesh
        try:
            state = generate_crack_mesh(defn)
            self._crack_surface = state
            self.plot_crack()
            if self._crack_insert_wizard is not None:
                self._crack_insert_wizard.update_preview_stats(
                    len(state.vertices),
                    len(state.triangles),
                    len(state.front_node_ids),
                )
        except Exception as exc:
            self.status_manager.set_message(f"Preview error: {exc}")

    def _on_crack_insert_accepted(self, state):
        self._crack_surface = state
        self._crack_path = "(inserted)"
        self.property_browser.set_property("Crack Surface", "File",        "(inserted)")
        self.property_browser.set_property("Crack Surface", "Vertices",    str(len(state.vertices)))
        self.property_browser.set_property("Crack Surface", "Triangles",   str(len(state.triangles)))
        self.property_browser.set_property("Crack Surface", "Front Nodes", str(len(state.front_node_ids)))
        self.model_tree.set_crack_loaded(
            "(inserted)", len(state.triangles), len(state.front_node_ids))
        self.plot_crack()
        self.status_manager.set_message(
            f"Crack inserted: {len(state.vertices)} verts, "
            f"{len(state.triangles)} tris, {len(state.front_node_ids)} front nodes"
        )
        self._crack_insert_wizard = None
        self._crack_pre_insert_state = None
        self._update_toolbar_state()

    def _on_crack_insert_cancelled(self):
        self._crack_surface = self._crack_pre_insert_state
        if self._crack_surface is not None:
            self.plot_crack()
        else:
            self.viewer.remove_actor("Crack Surface")
        self._crack_insert_wizard = None
        self._crack_pre_insert_state = None
        self.status_manager.set_message("Crack insertion cancelled")

    # ==================================================================
    # MODEL: navigation shortcuts
    # ==================================================================

    def goto_crack(self):
        """Select Crack node in the tree — shows crack surface properties."""
        self.model_tree.setCurrentItem(self.model_tree._crack_item)

    def goto_material(self):
        """Select Material node in the tree — shows Paris-law properties."""
        self.model_tree.setCurrentItem(self.model_tree._mat_item)

    def goto_steps(self):
        """Select Steps node in the tree — shows propagation controls."""
        self.model_tree.setCurrentItem(self.model_tree._step_item)

    # ==================================================================
    # SOLVE: unified Run pipeline
    # ==================================================================

    def run_analysis(self):
        """Single-button workflow: validate \u2192 build INP \u2192 run CCX \u2192 read \u2192 display.

        The user never sees the intermediate INP file.  Everything from
        deck generation through result visualisation is handled here.
        """
        # --- pre-flight validation (synchronous, fast) ----------------
        errors = self._validate_model()
        if errors:
            QMessageBox.warning(self, "Cannot Run", "\n".join(errors))
            return

        # Clear any previous results
        self.model_tree.clear_results()
        self.postproc_panel.clear()
        self._prop_result = None
        self._output_frd_mesh = None

        # --- capture UI values (must be on main thread) ---------------
        pb = self.property_browser
        paris = (
            float(pb.get_property("Material", "(da/dN)_ref") or "1e-4"),
            float(pb.get_property("Material", "DK_ref")      or "772.86"),
            float(pb.get_property("Material", "m")            or "3.1"),
            float(pb.get_property("Material", "epsilon")      or "10.0"),
            float(pb.get_property("Material", "DK_th")        or "177.09"),
            float(pb.get_property("Material", "delta")        or "10.0"),
            float(pb.get_property("Material", "K_c")          or "3162.0"),
            float(pb.get_property("Material", "w")            or "0.5"),
        )
        max_da      = float(pb.get_property("Controls", "Max Increment")  or "0.05")
        max_angle   = float(pb.get_property("Controls", "Max Angle")      or "10.0")
        max_inc     = int(pb.get_property("Controls",   "Max Steps (INC)") or "50")
        length_type = pb.get_property("Controls", "Length Type") or "CUMULATIVE"
        mat_name    = pb.get_property("Material", "Name") or "CRACK"

        frd_path      = self._frd_path
        crack_path    = self._crack_path
        crack_surface = self._crack_surface

        self._set_busy(True)

        # --- background worker: build → solve → read ------------------
        def task(progress_cb):
            import os
            from pipeline.prop_config import PropagationConfig
            from core.crack_surface_s3 import CrackSurfaceBuilder
            from crack_io.prop_deck_writer import PropDeckWriter
            from solver.calculix_solver import CalculiXSolver
            from crack_io.frd_reader import read_keq_results, read_frd_mesh

            work_dir = os.path.join(os.path.dirname(frd_path), "prop_work")
            os.makedirs(work_dir, exist_ok=True)

            # Phase 2 — S3 crack surface mesh (written first so PropagationConfig
            # can use the real INP path for validation regardless of origin)
            progress_cb(10, "Building S3 crack surface mesh\u2026")
            crack_inp = os.path.join(work_dir, "crack_surface.inp")
            CrackSurfaceBuilder.write_s3_inp(crack_surface, crack_inp)

            # Phase 1 — configuration (uses crack_inp, not the original file path)
            progress_cb(5, "Validating configuration\u2026")
            cfg = PropagationConfig(
                uncracked_frd=frd_path,
                initial_crack=crack_inp,
                paris_constants=paris,
                material_name=mat_name,
                max_da=max_da,
                max_angle=max_angle,
                max_increments=max_inc,
                length_type=length_type,
                work_dir=work_dir,
            )
            cfg.validate()

            # Phase 3 — propagation INP deck
            progress_cb(20, "Writing propagation deck\u2026")
            writer = PropDeckWriter(cfg, crack_inp, frd_path)
            deck_path = writer.write(work_dir)

            # Phase 4 — CalculiX
            progress_cb(30, "Running CalculiX \u2026 (this may take several minutes)")
            solver = CalculiXSolver(
                ccx_path=cfg.ccx_path,
                n_cpus=cfg.n_cpus,
            )
            output_frd = solver.run_crack_propagation(deck_path, n_cpus=cfg.n_cpus)

            # Phase 5 — read results
            progress_cb(80, "Reading KEQ results\u2026")
            keq = read_keq_results(output_frd)

            progress_cb(90, "Reading output mesh\u2026")
            frd_mesh = read_frd_mesh(output_frd)

            progress_cb(100, "Analysis complete")
            return (cfg, deck_path, output_frd, keq, frd_mesh, mat_name)

        w = Worker(task)
        w.progress.connect(lambda pct, msg: self.status_manager.set_progress(pct, msg))
        w.finished.connect(self._on_run_complete)
        w.error.connect(self._on_worker_error)
        self._worker = w
        w.start()

    # ------------------------------------------------------------------

    def _on_run_complete(self, result_tuple):
        """Handle the completed analysis — populate everything."""
        cfg, deck_path, output_frd, keq, frd_mesh, mat_name = result_tuple

        # Store state
        self._prop_config     = cfg
        self._deck_path       = deck_path
        self._output_frd_path = output_frd
        self._output_frd_mesh = frd_mesh

        from pipeline.prop_runner import PropResult
        result = PropResult(keq_increments=keq)
        result.status = "success" if keq else "no_results"
        result.output_frd_path = output_frd
        result.deck_path = deck_path
        self._prop_result = result

        # ---- property browser ----------------------------------------
        n_inc = len(keq)
        self.property_browser.set_property("Results", "Increments", str(n_inc))
        self.property_browser.set_property(
            "Results", "Final Length", f"{result.final_crack_length:.4f}"
        )
        self.property_browser.set_property(
            "Results", "Status", "success" if n_inc > 0 else "no results"
        )

        if keq:
            max_dkeq = max_dadn = total_cycles = 0.0
            for inc in keq:
                for nid, fields in inc.keq_data.items():
                    max_dkeq    = max(max_dkeq,    abs(fields.get("DELTAKEQ", 0.0)))
                    max_dadn    = max(max_dadn,    abs(fields.get("DADN", 0.0)))
                    total_cycles = max(total_cycles, fields.get("CYCLES", 0.0))
            self.property_browser.set_property("Results", "Max DELTAKEQ", f"{max_dkeq:.4g}")
            self.property_browser.set_property("Results", "Max DADN",     f"{max_dadn:.4g}")
            self.property_browser.set_property("Results", "Total Cycles", f"{total_cycles:.0f}")

        # ---- model tree: per-increment step entries ------------------
        if keq:
            from collections import defaultdict
            last = keq[-1]
            inc_groups: dict[int, list] = defaultdict(list)
            for nid, fields in last.keq_data.items():
                if fields.get("DELTAKEQ", 0.0) == 0.0:
                    continue
                inc_groups[int(fields.get("INC", 0))].append(fields)

            step_data = []
            for iv in sorted(inc_groups.keys()):
                nodes = inc_groups[iv]
                step_data.append({
                    "inc":       iv,
                    "max_dkeq":  max(abs(f.get("DELTAKEQ", 0.0)) for f in nodes),
                    "crlength":  max(f.get("CRLENGTH", 0.0) for f in nodes),
                    "cycles":    max(f.get("CYCLES", 0.0) for f in nodes),
                    "n_front_nodes": len(nodes),
                })
            self.model_tree.populate_results(step_data)

        # ---- model tree: material label ------------------------------
        self.model_tree.set_material_name(mat_name)

        # ---- post-processing panel -----------------------------------
        if keq:
            self.postproc_panel.set_data(keq)
        else:
            self.postproc_panel.clear()

        # ---- 3D viewer: output mesh + auto-display crack -------------
        if frd_mesh and frd_mesh.nodes:
            try:
                self._display_frd_mesh(frd_mesh, mesh_type="global")
            except Exception as exc:
                print(f"Output FRD mesh display failed: {exc}")

        # Show the final crack surface + all front lines automatically
        self.plot_crack()

        self.status_manager.set_message(
            f"Analysis complete: {n_inc} increments, "
            f"final length = {result.final_crack_length:.4f}"
        )
        self._set_busy(False)

    # ------------------------------------------------------------------

    def _validate_model(self) -> list[str]:
        """Pre-flight checks.  Returns a list of error strings (empty = OK)."""
        errors: list[str] = []
        if not self._frd_path:
            errors.append("No FRD file loaded.")
        if self._crack_surface is None and not self._crack_path:
            errors.append("No crack geometry loaded.")
        if self._crack_surface is None:
            errors.append("Crack surface not built.")
        elif len(self._crack_surface.triangles) == 0:
            errors.append("Crack surface has no triangles.")
        elif len(self._crack_surface.front_node_ids) < 2:
            errors.append("Crack front has fewer than 2 nodes.")
        return errors

    # ==================================================================
    # RESULTS: Plot Crack
    # ==================================================================

    def plot_crack(self):
        # Hide KEQ overlay when switching to crack view
        self.viewer.remove_actor("KEQ Front")
        self.viewer.hide_scalar_bar()

        # After propagation: show grown crack from output FRD (S3 elements)
        output_mesh = self._output_frd_mesh
        if output_mesh and output_mesh.elem_types:
            from core.mesh_io import MeshData, Node, Element
            mesh = MeshData()
            crack_eids = [eid for eid, t in output_mesh.elem_types.items() if t == 7]
            if crack_eids:
                needed_nids: set[int] = set()
                for eid in crack_eids:
                    needed_nids.update(output_mesh.elements[eid])
                for nid in needed_nids:
                    co = output_mesh.nodes[nid]
                    mesh.nodes[nid] = Node(nid, float(co[0]), float(co[1]), float(co[2]))
                for eid in crack_eids:
                    nids = output_mesh.elements[eid]
                    mesh.elements[eid] = Element(eid, "S3", nids)

                self.viewer.display_mesh(mesh, mesh_type="crack")
                self._add_crack_front_line()
                self.viewer.fit_all()
                self.status_manager.set_message(
                    f"Grown crack: {len(crack_eids)} S3 elements, {len(needed_nids)} nodes"
                )
                return

        # Before propagation: show initial crack surface
        if self._crack_surface is None:
            self._show_error("Plot Crack", "No crack surface available.")
            return

        from core.mesh_io import MeshData, Node, Element
        state = self._crack_surface
        mesh = MeshData()
        for i, (x, y, z) in enumerate(state.vertices):
            mesh.nodes[i + 1] = Node(i + 1, float(x), float(y), float(z))
        for i, (a, b, c) in enumerate(state.triangles):
            mesh.elements[i + 1] = Element(i + 1, "S3", [int(a) + 1, int(b) + 1, int(c) + 1])

        self.viewer.display_mesh(mesh, mesh_type="crack")
        self.viewer.fit_all()
        self.status_manager.set_message("Displaying initial crack surface")

    def _add_crack_front_line(self, max_inc: int | None = None):
        """Display crack-front polylines from KEQ data.

        Parameters
        ----------
        max_inc : int or None
            If given, only draw fronts for increments <= max_inc.
            If None, draw all increments.
        """
        if not self._prop_result or not self._prop_result.keq_increments:
            return
        if self._output_frd_mesh is None:
            return

        import numpy as np
        from collections import defaultdict
        last_inc = self._prop_result.keq_increments[-1]

        fronts: dict[float, list] = defaultdict(list)
        for nid in sorted(last_inc.keq_data.keys()):
            d = last_inc.keq_data[nid]
            if d.get("DELTAKEQ", 0.0) == 0.0:
                continue
            inc_val = d.get("INC", 0.0)
            if nid in self._output_frd_mesh.nodes:
                fronts[inc_val].append(self._output_frd_mesh.nodes[nid])

        front_lines = []
        for inc_val in sorted(fronts.keys()):
            if max_inc is not None and inc_val > max_inc:
                continue
            pts = fronts[inc_val]
            if len(pts) >= 2:
                front_lines.append(np.array(pts))

        if front_lines:
            self.viewer.display_crack_front_lines(front_lines)

    # ==================================================================
    # RESULTS: Step selection (tree / table / programmatic)
    # ==================================================================

    def _show_step(self, inc: int):
        """Update the 3D viewer to show crack state at *inc* (viewer only).

        This is the shared viewer-update logic called by both the tree
        and the post-processing table handlers.
        """
        output_mesh = self._output_frd_mesh
        if not output_mesh or not output_mesh.elem_types:
            return

        self.viewer.remove_actor("KEQ Front")
        self.viewer.hide_scalar_bar()

        from core.mesh_io import MeshData, Node, Element

        crack_eids = [eid for eid, t in output_mesh.elem_types.items() if t == 7]
        if not crack_eids:
            return

        mesh = MeshData()
        needed_nids: set[int] = set()
        for eid in crack_eids:
            needed_nids.update(output_mesh.elements[eid])
        for nid in needed_nids:
            co = output_mesh.nodes[nid]
            mesh.nodes[nid] = Node(nid, float(co[0]), float(co[1]), float(co[2]))
        for eid in crack_eids:
            nids = output_mesh.elements[eid]
            mesh.elements[eid] = Element(eid, "S3", nids)

        self.viewer.display_mesh(mesh, mesh_type="crack")
        self._add_crack_front_line(max_inc=inc)
        self.viewer.fit_all()
        self.status_manager.set_message(f"Crack at step {inc}")

    def _on_step_selected(self, inc: int):
        """Tree click on a Step-N node — update viewer + post-proc panel."""
        self._show_step(inc)
        self.postproc_panel.highlight_step(inc)

    def _on_postproc_row_selected(self, inc: int):
        """Table row click in post-proc panel — update viewer + tree."""
        self._show_step(inc)
        # Select the matching step item in the tree without re-triggering
        self.model_tree.blockSignals(True)
        try:
            steps_grp = self.model_tree._steps_group_item
            for i in range(steps_grp.childCount()):
                child = steps_grp.child(i)
                key = child.data(0, Qt.ItemDataRole.UserRole)
                if key == f"{KEY_STEP_PREFIX}{inc}":
                    self.model_tree.setCurrentItem(child)
                    break
        finally:
            self.model_tree.blockSignals(False)

    # ==================================================================
    # RESULTS: Contour display (tree-driven)
    # ==================================================================

    def _on_contour_selected(self, label: str):
        """Tree click on a contour child (e.g. 'K1') — store and display."""
        self._active_contour = label
        self._show_contour(label)
        self._refresh_probe()

    def _show_contour(self, label: str):
        """Display the named contour field on the crack surface (cell-based)."""
        field_name = CONTOUR_TYPES.get(label)
        if field_name is None:
            return

        if not self._prop_result or not self._prop_result.keq_increments:
            self._show_error("Show Contour", "No KEQ results available.")
            return

        if self._output_frd_mesh is None or not self._output_frd_mesh.nodes:
            self._show_error("Show Contour", "No output FRD mesh available.")
            return

        self.viewer.remove_actor("Crack Front")

        last_inc = self._prop_result.keq_increments[-1]

        # Build sparse {nid: field_value} for all active crack-front nodes
        nid_values: dict[int, float] = {}
        nids: list[int] = []
        for nid, keq in last_inc.keq_data.items():
            if keq.get("DELTAKEQ", 0.0) == 0.0:
                continue
            nid_values[nid] = keq.get(field_name, 0.0)
            nids.append(nid)

        self._probe_nids = nids

        if not nid_values:
            self._show_error("Show Contour", f"No crack-front nodes with {field_name} data.")
            return

        output_mesh = self._output_frd_mesh
        crack_eids = (
            [eid for eid, t in output_mesh.elem_types.items() if t == 7]
            if output_mesh.elem_types else []
        )

        if crack_eids:
            triangles = [output_mesh.elements[eid] for eid in crack_eids]
            needed = {n for tri in triangles for n in tri}
            nodes = {
                nid: tuple(float(c) for c in output_mesh.nodes[nid])
                for nid in needed if nid in output_mesh.nodes
            }
            self.viewer.display_crack_contour(nodes, triangles, nid_values, field_name)
            self.viewer.fit_all()
            self.status_manager.set_message(
                f"{field_name} on crack surface ({len(crack_eids)} elements,"
                f" increment {last_inc.increment})"
            )
        else:
            # Fallback: point cloud (no S3 elements in output)
            import numpy as np
            coords = [output_mesh.nodes[nid] for nid in nids if nid in output_mesh.nodes]
            vals   = [nid_values[nid]         for nid in nids if nid in output_mesh.nodes]
            if coords:
                self.viewer.display_front_keq(np.array(coords), np.array(vals), field_name)
            self.viewer.fit_all()
            self.status_manager.set_message(
                f"{field_name} at {len(nids)} front nodes (increment {last_inc.increment})"
            )

    def show_contour(self):
        """Ribbon button: display the currently selected contour field."""
        if self._active_contour:
            self._show_contour(self._active_contour)
        else:
            self._show_error("Show Contour",
                             "Select a contour type in the tree first\n"
                             "(Results \u2192 Contours \u2192 K1, K2, \u2026)")

    # ==================================================================
    # RESULTS: Ribbon post-processing tools
    # ==================================================================

    def toggle_scalar_bar(self, checked: bool):
        """Ribbon toggle: show or hide the scalar colour bar."""
        self.viewer.set_scalar_bar_visible(checked)

    def auto_range(self):
        """Scale contour to current step min/max (placeholder)."""
        self.status_manager.set_message("Auto Range — not yet implemented")

    def global_range(self):
        """Scale contour to all-steps min/max (placeholder)."""
        self.status_manager.set_message("Global Range — not yet implemented")

    def animate_steps(self):
        """Open the animation dialog and step through propagation results."""
        if not self._prop_result or not self._prop_result.keq_increments:
            self._show_error("Animate", "No results available.")
            return

        steps = self._get_step_list()
        if not steps:
            self._show_error("Animate", "No propagation steps found.")
            return

        # Build the full crack mesh once (stays constant across frames)
        self._build_animation_crack_mesh()

        step_names = [f"Step {s}" for s in steps]

        from ui.animation_dialog import AnimationDialog
        if hasattr(self, '_anim_dlg') and self._anim_dlg is not None:
            self._anim_dlg.close()

        self._anim_steps = steps
        self._anim_dlg = AnimationDialog(
            len(steps), step_names, parent=self)
        self._anim_dlg.step_changed.connect(
            lambda idx: self._animate_to_step(self._anim_steps[idx]))
        self._anim_dlg.save_requested.connect(self._save_animation)
        self._anim_dlg.show()

        # Show first frame
        self._animate_to_step(steps[0])

    # ------------------------------------------------------------------
    # Animation internals
    # ------------------------------------------------------------------

    def _get_step_list(self) -> list[int]:
        """Return sorted unique propagation increment numbers from KEQ data."""
        if not self._prop_result or not self._prop_result.keq_increments:
            return []
        last_inc = self._prop_result.keq_increments[-1]
        steps: set[int] = set()
        for data in last_inc.keq_data.values():
            if data.get("DELTAKEQ", 0.0) != 0.0:
                steps.add(int(data.get("INC", 0)))
        return sorted(steps)

    def _build_animation_crack_mesh(self):
        """Display the full crack mesh (all S3 elements) for animation."""
        output_mesh = self._output_frd_mesh
        if not output_mesh or not output_mesh.elem_types:
            return

        from core.mesh_io import MeshData, Node, Element
        crack_eids = [eid for eid, t in output_mesh.elem_types.items()
                      if t == 7]
        if not crack_eids:
            return

        mesh = MeshData()
        needed_nids: set[int] = set()
        for eid in crack_eids:
            needed_nids.update(output_mesh.elements[eid])
        for nid in needed_nids:
            co = output_mesh.nodes[nid]
            mesh.nodes[nid] = Node(
                nid, float(co[0]), float(co[1]), float(co[2]))
        for eid in crack_eids:
            nids = output_mesh.elements[eid]
            mesh.elements[eid] = Element(eid, "S3", nids)

        self.viewer.display_mesh(mesh, mesh_type="crack")
        self.viewer.fit_all()

    def _animate_to_step(self, inc: int):
        """Render one animation frame at propagation step *inc*."""
        # Clear previous contour overlay (front lines stay)
        self.viewer.remove_actor("KEQ Front")

        # Front lines up to this step
        self._add_crack_front_line(max_inc=inc)

        # Contour overlay if an active result is selected
        if self._active_contour:
            self._show_step_contour(inc)
        else:
            self.viewer.hide_scalar_bar()

        # Refresh probe if active
        self._refresh_probe()

        self.status_manager.set_message(f"Animating \u2014 Step {inc}")

    def _show_step_contour(self, max_inc: int):
        """Show contour on crack surface for nodes with INC \u2264 *max_inc* (cell-based)."""
        field_name = CONTOUR_TYPES.get(self._active_contour)
        if not field_name:
            return
        if not self._prop_result or not self._prop_result.keq_increments:
            return
        if self._output_frd_mesh is None:
            return

        last_inc = self._prop_result.keq_increments[-1]

        # Nodes active up to this step
        nid_values: dict[int, float] = {}
        nids: list[int] = []
        for nid, keq in last_inc.keq_data.items():
            if keq.get("DELTAKEQ", 0.0) == 0.0:
                continue
            if int(keq.get("INC", 0)) > max_inc:
                continue
            nid_values[nid] = keq.get(field_name, 0.0)
            nids.append(nid)

        self._probe_nids = nids

        if not nid_values:
            return

        output_mesh = self._output_frd_mesh
        crack_eids = (
            [eid for eid, t in output_mesh.elem_types.items() if t == 7]
            if output_mesh.elem_types else []
        )

        if crack_eids:
            triangles = [output_mesh.elements[eid] for eid in crack_eids]
            needed = {n for tri in triangles for n in tri}
            nodes = {
                nid: tuple(float(c) for c in output_mesh.nodes[nid])
                for nid in needed if nid in output_mesh.nodes
            }
            self.viewer.display_crack_contour(nodes, triangles, nid_values, field_name)
        else:
            import numpy as np
            coords = [output_mesh.nodes[nid] for nid in nids if nid in output_mesh.nodes]
            vals   = [nid_values[nid]         for nid in nids if nid in output_mesh.nodes]
            if coords:
                self.viewer.display_front_keq(np.array(coords), np.array(vals), field_name)

    def _save_animation(self):
        """Export the animation as a GIF (or PNG sequence as fallback)."""
        if not hasattr(self, '_anim_steps') or not self._anim_steps:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Animation", "",
            "GIF Image (*.gif);;PNG Sequence (*.png)")
        if not path:
            return

        import os
        import tempfile

        steps = self._anim_steps
        save_gif = path.lower().endswith(".gif")

        # Determine frame output directory
        if save_gif:
            tmp_dir = tempfile.mkdtemp(prefix="gmcrackx_anim_")
        else:
            tmp_dir = os.path.dirname(path)
            base = os.path.splitext(os.path.basename(path))[0]

        self.status_manager.set_message("Saving animation frames\u2026")

        frame_paths: list[str] = []
        for i, inc in enumerate(steps):
            self._animate_to_step(inc)
            # Force render so the screenshot captures the updated frame
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()

            if save_gif:
                fp = os.path.join(tmp_dir, f"frame_{i:04d}.png")
            else:
                fp = os.path.join(tmp_dir, f"{base}_{i:04d}.png")
            self.viewer.save_screenshot(fp)
            frame_paths.append(fp)

        if save_gif and frame_paths:
            try:
                from PIL import Image

                fps = (self._anim_dlg._fps_spin.value()
                       if self._anim_dlg else 5)
                duration = int(1000 / fps)

                imgs = [Image.open(fp) for fp in frame_paths]
                imgs[0].save(
                    path,
                    save_all=True,
                    append_images=imgs[1:],
                    duration=duration,
                    loop=0,
                )
                # Clean up temp PNGs
                for fp in frame_paths:
                    os.remove(fp)
                os.rmdir(tmp_dir)

                self.status_manager.set_message(
                    f"Animation saved: {path}  ({len(steps)} frames)")
            except ImportError:
                self.status_manager.set_message(
                    f"Pillow not installed \u2014 saved {len(steps)} PNG "
                    f"frames in {tmp_dir}")
            except Exception as exc:
                self.status_manager.set_message(f"GIF save failed: {exc}")
        else:
            self.status_manager.set_message(
                f"Saved {len(frame_paths)} frames: {frame_paths[0]}")

    def probe_value(self, checked: bool = False):
        """Toggle probe mode — left-click picks the nearest node."""
        if checked:
            if not self._active_contour:
                self._show_error(
                    "Probe",
                    "Select a contour type first\n"
                    "(Results \u2192 Contours \u2192 K1, K2, \u2026)")
                self._sync_ribbon_toggle("probe", False)
                return
            if not self._prop_result or not self._prop_result.keq_increments:
                self._show_error("Probe", "No results available.")
                self._sync_ribbon_toggle("probe", False)
                return
        self.viewer.set_probe_mode(checked)
        if not checked:
            self._probe_info = None
            if self._probe_dlg:
                self._probe_dlg.hide()

    # ------------------------------------------------------------------
    # Probe internals
    # ------------------------------------------------------------------

    def _on_point_picked(self, wx: float, wy: float, wz: float):
        """Viewer picked a world point — find nearest node and show result."""
        if not self._probe_nids or not self._active_contour:
            return
        if self._output_frd_mesh is None:
            return

        import numpy as np
        pick = np.array([wx, wy, wz])

        coords = np.array([
            self._output_frd_mesh.nodes[nid] for nid in self._probe_nids
        ])
        dists = np.sum((coords - pick) ** 2, axis=1)

        # Reject clicks too far from any node (> 5 % of scene diagonal)
        idx = int(np.argmin(dists))
        bounds = self.viewer._renderer.ComputeVisiblePropBounds()
        diag = ((bounds[1] - bounds[0]) ** 2
                + (bounds[3] - bounds[2]) ** 2
                + (bounds[5] - bounds[4]) ** 2) ** 0.5
        if dists[idx] ** 0.5 > diag * 0.05:
            return

        self._probe_info = {"nid": self._probe_nids[idx]}
        self._show_probe_result()

    def _show_probe_result(self):
        """Display / update the probe dialog for the stored node."""
        if not self._probe_info or not self._active_contour:
            return
        if not self._prop_result or not self._prop_result.keq_increments:
            return

        nid = self._probe_info["nid"]
        field_name = CONTOUR_TYPES.get(self._active_contour)
        if not field_name:
            return

        last_inc = self._prop_result.keq_increments[-1]
        data = last_inc.keq_data.get(nid, {})
        value = data.get(field_name, 0.0)
        step = int(data.get("INC", 0))

        co = self._output_frd_mesh.nodes[nid]
        x, y, z = float(co[0]), float(co[1]), float(co[2])

        # Move the marker to the exact node position
        self.viewer.show_probe_marker(x, y, z)

        # Show / update dialog
        from ui.probe_dialog import ProbeDialog
        if self._probe_dlg is None:
            self._probe_dlg = ProbeDialog(self)
        self._probe_dlg.set_result(
            nid, x, y, z, step, self._active_contour, value)
        self._probe_dlg.show()
        self._probe_dlg.raise_()

        self.status_manager.set_message(
            f"Probe: Node {nid}, {self._active_contour} = {value:.4g}")

    def _refresh_probe(self):
        """Re-display probe result when contour or step changes."""
        if self._probe_info and self.viewer._probe_enabled:
            self._show_probe_result()

    def export_image(self):
        """Save current 3D view as PNG."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Image", "", "PNG Files (*.png)")
        if not path:
            return
        self.viewer.save_screenshot(path)
        self.status_manager.set_message(f"Image saved: {path}")

    # ==================================================================
    # RESULTS: Graphs (matplotlib)
    # ==================================================================

    def show_graphs(self):
        if not self._prop_result or not self._prop_result.keq_increments:
            self._show_error("Graphs", "No KEQ results available.")
            return

        from ui.graphs_dialog import GraphsDialog
        dlg = GraphsDialog(self._prop_result.keq_increments, parent=self)
        dlg.show()

    # ==================================================================
    # RESULTS: Export CSV
    # ==================================================================

    def export_csv(self):
        """Export post-processing results table to CSV file."""
        self.postproc_panel.export_csv()

    # ==================================================================
    # TOOLS: Convert Results
    # ==================================================================

    def convert_results(self):
        """Open the result-conversion dialog (Tools → Convert Results)."""
        from ui.convert_dialog import ConvertDialog
        dlg = ConvertDialog(self)
        dlg.exec()

    # ==================================================================
    # FRD mesh → viewer helper
    # ==================================================================

    def _display_frd_mesh(self, frd_mesh, mesh_type: str = "global"):
        """Convert FrdMesh to MeshData with correct FRD\u2192VTK reordering."""
        from core.mesh_io import MeshData, Node, Element

        _FRD_TYPE_TO_CCX = {
            1: "C3D8",  2: "C3D6",  3: "C3D4",
            4: "C3D20", 5: "C3D15", 6: "C3D10",
            7: "S3",    8: "S6",    9: "S4",   10: "S8",
            11: "B31",  12: "B32",
        }
        _NODE_COUNT_TO_CCX = {
            4: "C3D4", 8: "C3D8", 6: "C3D6",
            10: "C3D10", 20: "C3D20", 15: "C3D15",
            3: "S3", 2: "S3",
        }

        mesh_data = MeshData()
        for nid, coords in frd_mesh.nodes.items():
            mesh_data.nodes[nid] = Node(nid, float(coords[0]), float(coords[1]), float(coords[2]))

        etypes = frd_mesh.elem_types or {}
        for eid, nids in frd_mesh.elements.items():
            frd_type = etypes.get(eid, 0)
            etype = _FRD_TYPE_TO_CCX.get(frd_type) or _NODE_COUNT_TO_CCX.get(len(nids), "C3D4")

            if frd_type == 4 and len(nids) == 20:
                nids = nids[:12] + nids[16:20] + nids[12:16]
            elif frd_type == 5 and len(nids) >= 6:
                nids = [nids[i] for i in (0, 2, 1, 3, 5, 4)]
                etype = "C3D6"

            mesh_data.elements[eid] = Element(eid, etype, nids)

        self.viewer.display_mesh(mesh_data, mesh_type=mesh_type)
        return mesh_data

    # ==================================================================
    # Geometry / Mesh view switching
    # ==================================================================

    def _switch_to_geometry_view(self):
        """Switch to clean CAD-like geometry surface view.

        Shows the Geometry actor (smooth surface, no edges),
        hides the Mesh actor to avoid z-fighting, and updates
        the ribbon toggles to reflect the new state.
        """
        self.viewer.set_actor_visibility("Geometry", True)
        self.viewer.set_actor_visibility("Mesh", False)
        self.viewer.set_display_mode("surface")
        self.viewer.highlight_object("Geometry")

        # Keep model-tree hidden-actors set consistent
        self.model_tree._hidden_actors.discard("Geometry")
        self.model_tree._hidden_actors.add("Mesh")

        # Sync ribbon visibility toggles
        self._sync_ribbon_toggle("display_geometry", True)
        self._sync_ribbon_toggle("display_mesh", False)
        self._sync_ribbon_toggle("display_surface", True)

    def _switch_to_mesh_view(self):
        """Switch to FE mesh view with element edges.

        Shows the Mesh actor (surface + edges), hides the Geometry
        actor, and updates the ribbon toggles.
        """
        self.viewer.set_actor_visibility("Mesh", True)
        self.viewer.set_actor_visibility("Geometry", False)
        self.viewer.set_display_mode("surface_edges")
        self.viewer.highlight_object("Mesh")

        self.model_tree._hidden_actors.add("Geometry")
        self.model_tree._hidden_actors.discard("Mesh")

        self._sync_ribbon_toggle("display_mesh", True)
        self._sync_ribbon_toggle("display_geometry", False)
        self._sync_ribbon_toggle("display_sedge", True)

    def _sync_ribbon_toggle(self, action_key: str, checked: bool):
        """Programmatically sync a ribbon toggle without firing its slot.

        ``QAction.setChecked()`` emits ``toggled`` but NOT ``triggered``,
        so our slots (connected to ``triggered``) are not re-invoked.
        """
        action = self.toolbar_builder.actions.get(action_key)
        if action is not None:
            action.setChecked(checked)

    # ==================================================================
    # Helpers
    # ==================================================================

    def _update_toolbar_state(self):
        has_frd     = self._frd_path is not None
        has_crack   = self._crack_path is not None and self._crack_surface is not None
        has_results = self._prop_result is not None and self._prop_result.keq_increments

        tb = self.toolbar_builder
        tb.set_enabled("run_analysis",      has_frd and has_crack)
        tb.set_enabled("plot_front",        has_crack)
        tb.set_enabled("show_contour",      bool(has_results))
        tb.set_enabled("show_graphs",       bool(has_results))
        tb.set_enabled("toggle_scalar_bar", bool(has_results))
        tb.set_enabled("auto_range",        bool(has_results))
        tb.set_enabled("global_range",      bool(has_results))
        tb.set_enabled("animate",           bool(has_results))
        tb.set_enabled("probe",             bool(has_results))
        tb.set_enabled("export_csv",        bool(has_results))
        tb.set_enabled("export_image",      True)

    def _set_busy(self, busy: bool):
        if busy:
            for name, action in self.toolbar_builder.actions.items():
                if not name.startswith("display_"):
                    action.setEnabled(False)
        else:
            # Re-enable always-available buttons first
            for name in ("load_frd", "load_crack", "goto_crack",
                         "goto_material", "goto_steps"):
                self.toolbar_builder.set_enabled(name, True)
            # Then apply pipeline-dependent state
            self._update_toolbar_state()

    def _on_worker_error(self, tb: str):
        self._set_busy(False)
        self.status_manager.hide_progress()
        self.status_manager.set_message("Error \u2014 see console")
        print("=== Worker Error ===")
        print(tb)
        QMessageBox.critical(self, "Error", tb[-800:])

    def _show_error(self, title: str, message: str):
        QMessageBox.critical(self, title, message)
