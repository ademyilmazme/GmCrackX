"""
3D Viewport widget backed by VTK + QVTKRenderWindowInteractor.

Rendering strategy for FE meshes
---------------------------------
Quadratic elements (C3D20, C3D10) are linearised to their corner-node
counterparts (C3D8, C3D4) before building the VTK grid.  This prevents
VTK from tessellating quadratic faces into sub-triangles ("triangle soup").

Pipeline:
  1. Linearise quadratic cells → corner nodes only
  2. vtkGeometryFilter → extract outer surface (clean quads for hex)
  3. SetInterpolationToFlat() → one colour per face, no normal averaging

Public API
----------
  display_geometry(brep_path)       — B-rep → tessellated surface actor
  display_mesh(mesh, mesh_type)     — MeshData → solid FE surface
  display_results(field_name, data) — scalar field coloured contour
  highlight_object(name)
  clear()
  fit_all()
"""
from __future__ import annotations

import vtkmodules.qt
vtkmodules.qt.PyQtImpl = "PyQt6"

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, QEvent, Qt

import numpy as np

import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkRenderingCore import (
    vtkRenderer, vtkActor, vtkPolyDataMapper, vtkLight,
)
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid, vtkPolyData
from vtkmodules.vtkCommonCore import vtkPoints, vtkFloatArray, vtkIdList, vtkLookupTable
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingAnnotation import vtkScalarBarActor, vtkAxesActor
from vtkmodules.vtkRenderingCore import vtkTextProperty
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter


# ---------------------------------------------------------------------------
# VTK cell type constants
# ---------------------------------------------------------------------------
VTK_TETRA        = 10
VTK_QUAD_TETRA   = 24
VTK_HEXAHEDRON   = 12
VTK_QUAD_HEX     = 25
VTK_WEDGE        = 13
VTK_QUAD_WEDGE   = 26
VTK_TRIANGLE      = 5
VTK_QUAD_TRIANGLE = 22

CCX_TO_VTK = {
    "C3D4":   VTK_TETRA,
    "C3D4R":  VTK_TETRA,
    "C3D10":  VTK_QUAD_TETRA,
    "C3D8":   VTK_HEXAHEDRON,
    "C3D8R":  VTK_HEXAHEDRON,
    "C3D20":  VTK_QUAD_HEX,
    "C3D20R": VTK_QUAD_HEX,
    "C3D6":   VTK_WEDGE,
    "C3D15":  VTK_QUAD_WEDGE,
    "TRI3":   VTK_TRIANGLE,
    "TRI6":   VTK_QUAD_TRIANGLE,
    "S3":     VTK_TRIANGLE,
    "S6":     VTK_QUAD_TRIANGLE,
}

# Quadratic → linear for display: VTK tessellates quadratic faces into
# sub-triangles, producing "triangle soup" with flat shading.  Linearising
# (keeping only corner nodes) gives clean quad/tri faces per element —
# matching PrePoMax / FEMAP / HyperMesh appearance.
_LINEARIZE: dict[int, tuple[int, int]] = {
    VTK_QUAD_HEX:      (VTK_HEXAHEDRON, 8),    # C3D20 → 8 corners
    VTK_QUAD_TETRA:    (VTK_TETRA, 4),          # C3D10 → 4 corners
    VTK_QUAD_WEDGE:    (VTK_WEDGE, 6),          # C3D15 → 6 corners
    VTK_QUAD_TRIANGLE: (VTK_TRIANGLE, 3),       # S6    → 3 corners
}

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
_MESH_COLOUR      = (0.78, 0.20, 0.17)   # PrePoMax-style red
_CRACK_COLOUR     = (0.20, 0.55, 0.85)   # blue for crack surface
_DEFAULT_COLOUR   = (0.78, 0.20, 0.17)
_HIGHLIGHT_COLOUR = (1.00, 0.80, 0.00)
_EDGE_COLOUR      = (0.12, 0.12, 0.12)

_GEOMETRY_COLOUR  = (0.65, 0.72, 0.78)   # blue-grey CAD surface

_OBJECT_COLOURS: dict[str, tuple[float, float, float]] = {
    "Geometry":      _GEOMETRY_COLOUR,
    "Mesh":          _MESH_COLOUR,
    "Crack Surface": _CRACK_COLOUR,
    "Crack Front":   (1.00, 0.85, 0.10),
    "Local Mesh":    (0.30, 0.70, 0.95),
    "K Factors":     (0.80, 0.30, 0.80),
}

# Edge visibility threshold — show edges only for meshes smaller than this
_EDGE_CELL_LIMIT = 50_000


class ViewerWidget(QWidget):
    point_picked = pyqtSignal(float, float, float)   # world x, y, z

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)

        self._vtk_widget = QVTKRenderWindowInteractor(self)
        self._renderer   = vtkRenderer()

        # White background (user requirement)
        self._renderer.SetBackground(1.0, 1.0, 1.0)
        self._renderer.GradientBackgroundOff()

        rw = self._vtk_widget.GetRenderWindow()
        rw.AddRenderer(self._renderer)
        rw.SetMultiSamples(4)   # MSAA 4×

        style = vtkInteractorStyleTrackballCamera()
        rw.GetInteractor().SetInteractorStyle(style)

        # Two camera-relative lights: warm key + cool fill
        # Camera lights follow the camera so the model is always readable
        # from any view angle without requiring the user to orbit to find light.
        self._renderer.RemoveAllLights()
        self._renderer.AutomaticLightCreationOff()

        key = vtkLight()
        key.SetLightTypeToCameraLight()
        key.SetPosition(1.0, 1.5, 1.0)
        key.SetFocalPoint(0.0, 0.0, 0.0)
        key.SetIntensity(0.90)
        key.SetColor(1.0, 1.0, 0.97)
        self._renderer.AddLight(key)

        fill = vtkLight()
        fill.SetLightTypeToCameraLight()
        fill.SetPosition(-1.5, -1.0, 0.5)
        fill.SetFocalPoint(0.0, 0.0, 0.0)
        fill.SetIntensity(0.40)
        fill.SetColor(0.90, 0.93, 1.0)
        self._renderer.AddLight(fill)

        # Scalar bar — PrePoMax / Abaqus style
        self._scalar_bar = _create_scalar_bar()
        self._renderer.AddActor2D(self._scalar_bar)

        # Actor registry
        self._actors: dict[str, vtkActor] = {}
        self._actor_colours: dict[str, tuple[float, float, float]] = {}
        self._current_mesh_actor: vtkActor | None = None
        self._highlighted: str | None = None
        self._current_display_mode: str = "surface_edges"
        self._probe_enabled: bool = False
        self._probe_marker: vtkActor | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._vtk_widget)

        self._vtk_widget.Initialize()
        self._vtk_widget.Start()

        axes = vtkAxesActor()
        self._orientation_widget = vtkOrientationMarkerWidget()
        self._orientation_widget.SetOrientationMarker(axes)
        self._orientation_widget.SetInteractor(rw.GetInteractor())
        self._orientation_widget.SetViewport(0.0, 0.0, 0.15, 0.15)
        self._orientation_widget.SetEnabled(True)
        self._orientation_widget.InteractiveOff()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def display_geometry(self, brep_path: str, name: str = "geometry"):
        """Load an OCCT geometry file (.brep/.step), tessellate, and display."""
        try:
            poly = _brep_to_polydata(brep_path)
        except Exception as exc:
            import traceback
            print(f"Viewer: display_geometry failed: {exc}")
            traceback.print_exc()
            return

        if poly.GetNumberOfPolys() == 0:
            print(f"Viewer: WARNING — tessellation produced 0 triangles for '{brep_path}'")
            return

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly)
        mapper.ScalarVisibilityOff()

        actor = vtkActor()
        actor.SetMapper(mapper)
        colour = _OBJECT_COLOURS.get(name, _CRACK_COLOUR)
        _fe_solid_props(actor, colour, show_edges=True)
        actor.GetProperty().SetOpacity(0.85)

        self._replace_actor(name, actor)
        self._render()

    def display_mesh(self, mesh, mesh_type: str = "global"):
        """
        Display a MeshData object as a solid FE surface.

        For ``mesh_type="global"`` two independent actors are created:

        * **Geometry** — clean CAD-like surface (no edges, blue-grey).
          Hidden by default.
        * **Mesh** — FE mesh with element edges (red).
          Visible by default.

        This lets the tree / ribbon toggle them independently.

        Pipeline
        --------
        1. Quadratic cells (C3D20, C3D10, …) → linearised to corner nodes
           (C3D8, C3D4, …) so vtkGeometryFilter outputs clean quad/tri
           faces — not VTK's internal sub-triangle tessellation.
        2. vtkGeometryFilter → extract outer surface cells (quads for hex).
        3. SetInterpolationToFlat() → one colour per face, no normal
           averaging, no bumpy artefacts.
        """
        try:
            if isinstance(mesh, str):
                from crack_io.inp_parser import parse_inp
                mesh = parse_inp(mesh)
            grid = _meshdata_to_ugrid(mesh)
            n_cells  = grid.GetNumberOfCells()
            n_points = grid.GetNumberOfPoints()
            print(f"Viewer: grid has {n_cells} cells, {n_points} points")
            if n_cells == 0:
                print("Viewer: WARNING — no cells (unsupported element types?)")
                return
        except Exception as exc:
            import traceback
            print(f"Viewer: display_mesh failed: {exc}")
            traceback.print_exc()
            return

        # Extract outer surface (shared polydata)
        geo = vtkGeometryFilter()
        geo.SetInputData(grid)
        geo.Update()
        surface = geo.GetOutput()
        n_surface_cells = surface.GetNumberOfCells()

        if mesh_type == "global":
            # ── Geometry actor (clean CAD surface, hidden by default) ──
            mapper_g = vtkPolyDataMapper()
            mapper_g.SetInputData(surface)
            mapper_g.ScalarVisibilityOff()
            actor_g = vtkActor()
            actor_g.SetMapper(mapper_g)
            _fe_solid_props(actor_g, _GEOMETRY_COLOUR, show_edges=False)
            self._replace_actor("Geometry", actor_g)
            actor_g.SetVisibility(False)

            # ── Mesh actor (FE mesh with edges, visible by default) ────
            mapper_m = vtkPolyDataMapper()
            mapper_m.SetInputData(surface)
            mapper_m.ScalarVisibilityOff()
            actor_m = vtkActor()
            actor_m.SetMapper(mapper_m)
            _fe_solid_props(actor_m, _MESH_COLOUR,
                            show_edges=(n_surface_cells <= _EDGE_CELL_LIMIT))
            self._replace_actor("Mesh", actor_m)
            self._current_mesh_actor = actor_m
        else:
            name   = {"crack": "Crack Surface"}.get(mesh_type, "Local Mesh")
            colour = _OBJECT_COLOURS.get(name, _DEFAULT_COLOUR)

            mapper = vtkPolyDataMapper()
            mapper.SetInputData(surface)
            mapper.ScalarVisibilityOff()
            actor = vtkActor()
            actor.SetMapper(mapper)
            _fe_solid_props(actor, colour,
                            show_edges=(n_surface_cells <= _EDGE_CELL_LIMIT))
            self._replace_actor(name, actor)
            self._current_mesh_actor = actor

        self._render()

    def display_results(self, field_name: str, data: np.ndarray | None = None):
        """
        Colour the current mesh by a scalar field using cell (element) data.

        Each surface element receives a single constant colour computed by
        averaging the nodal values at its corner points.  This produces the
        standard FE postprocessor look (one shade per element, no blending).

        When data=None, reverts to the flat-shaded solid display.
        """
        if self._current_mesh_actor is None:
            return

        prop   = self._current_mesh_actor.GetProperty()
        mapper = self._current_mesh_actor.GetMapper()

        if data is None:
            # Restore solid FE appearance
            prop.SetInterpolationToFlat()
            prop.SetEdgeVisibility(True)
            mapper.ScalarVisibilityOff()
            inp = mapper.GetInput()
            if inp:
                inp.GetCellData().SetScalars(None)
                inp.GetPointData().SetScalars(None)
            self._scalar_bar.SetVisibility(False)
            self._render()
            return

        try:
            inp = mapper.GetInput()
            if inp is None:
                return

            n_cells = inp.GetNumberOfCells()
            n_data  = len(data)

            # --- Average nodal values per surface cell ---
            cell_scalars = vtkFloatArray()
            cell_scalars.SetName(field_name)

            for ci in range(n_cells):
                cell   = inp.GetCell(ci)
                n_pts  = cell.GetNumberOfPoints()
                total  = 0.0
                count  = 0
                for pi in range(n_pts):
                    pt_id = cell.GetPointId(pi)
                    if pt_id < n_data:
                        total += float(data[pt_id])
                        count += 1
                cell_scalars.InsertNextValue(total / count if count else 0.0)

            # Store as cell data; clear any stale point data
            inp.GetPointData().SetScalars(None)
            inp.GetCellData().SetScalars(cell_scalars)

            vmin = float(data.min())
            vmax = float(data.max())
            if vmax <= vmin:
                vmax = vmin + 1.0
            lut = _build_rainbow_lut(vmin, vmax)

            mapper.SetLookupTable(lut)
            mapper.SetScalarRange(vmin, vmax)
            mapper.SetScalarModeToUseCellData()
            mapper.SetInterpolateScalarsBeforeMapping(1)
            mapper.ScalarVisibilityOn()

            # Flat shading: one constant colour per element face, no blending
            prop.SetInterpolationToFlat()
            prop.SetEdgeVisibility(False)

            _update_scalar_bar(self._scalar_bar, lut, field_name)

        except Exception as exc:
            print(f"Viewer: display_results failed: {exc}")

        self._render()

    def display_crack_contour(
        self,
        nodes: dict,
        triangles: list,
        nid_values: dict,
        field_name: str,
    ) -> None:
        """Display the crack surface with per-element (cell) coloring.

        Each triangle receives a single constant colour equal to the average
        of its nodes' field values.  Nodes absent from *nid_values* contribute
        0.0 to the average.  Replaces the "Crack Surface" actor in-place.

        Parameters
        ----------
        nodes      : {nid: (x, y, z)}
        triangles  : [[nid1, nid2, nid3], ...]
        nid_values : {nid: float}  — sparse; only nodes with data
        field_name : scalar-bar label
        """
        from vtkmodules.vtkCommonDataModel import vtkCellArray

        if not nodes or not triangles or not nid_values:
            return

        # Build point array
        points = vtkPoints()
        nid_to_vtk: dict[int, int] = {}
        for nid in sorted(nodes.keys()):
            x, y, z = nodes[nid]
            nid_to_vtk[nid] = points.InsertNextPoint(float(x), float(y), float(z))

        # Build cell array + per-cell scalar (average of node values)
        polys = vtkCellArray()
        cell_scalars = vtkFloatArray()
        cell_scalars.SetName(field_name)

        for tri in triangles:
            if not all(nid in nid_to_vtk for nid in tri):
                continue
            polys.InsertNextCell(3)
            cell_avg = 0.0
            for nid in tri:
                polys.InsertCellPoint(nid_to_vtk[nid])
                cell_avg += float(nid_values.get(nid, 0.0))
            cell_scalars.InsertNextValue(cell_avg / 3.0)

        if cell_scalars.GetNumberOfTuples() == 0:
            return

        poly = vtkPolyData()
        poly.SetPoints(points)
        poly.SetPolys(polys)
        poly.GetCellData().SetScalars(cell_scalars)

        all_vals = list(nid_values.values())
        vmin = float(min(all_vals))
        vmax = float(max(all_vals))
        if vmax <= vmin:
            vmax = vmin + 1.0
        lut = _build_rainbow_lut(vmin, vmax)

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly)
        mapper.SetLookupTable(lut)
        mapper.SetScalarRange(vmin, vmax)
        mapper.SetScalarModeToUseCellData()
        mapper.SetInterpolateScalarsBeforeMapping(0)
        mapper.ScalarVisibilityOn()

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*_CRACK_COLOUR)   # base colour for highlight restore
        actor.GetProperty().SetInterpolationToFlat()
        actor.GetProperty().SetEdgeVisibility(False)
        actor.GetProperty().SetOpacity(1.0)
        actor.GetProperty().LightingOff()

        _update_scalar_bar(self._scalar_bar, lut, field_name)
        self._replace_actor("Crack Surface", actor)
        self._render()

    def display_front_keq(self, coords: np.ndarray, values: np.ndarray, field_name: str):
        """Display crack-front nodes as a coloured point cloud."""
        from vtkmodules.vtkFiltersGeneral import vtkVertexGlyphFilter

        points = vtkPoints()
        for x, y, z in coords:
            points.InsertNextPoint(float(x), float(y), float(z))

        scalars = vtkFloatArray()
        scalars.SetName(field_name)
        for v in values:
            scalars.InsertNextValue(float(v))

        poly = vtkPolyData()
        poly.SetPoints(points)

        glyph = vtkVertexGlyphFilter()
        glyph.SetInputData(poly)
        glyph.Update()
        out = glyph.GetOutput()
        out.GetPointData().SetScalars(scalars)

        vmin, vmax = float(values.min()), float(values.max())
        lut = _build_rainbow_lut(vmin, vmax if vmax > vmin else vmin + 1.0)

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(out)
        mapper.SetLookupTable(lut)
        mapper.SetScalarRange(vmin, vmax if vmax > vmin else vmin + 1.0)
        mapper.ScalarVisibilityOn()

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetPointSize(18)
        actor.GetProperty().LightingOff()

        _update_scalar_bar(self._scalar_bar, lut, field_name)

        self._replace_actor("KEQ Front", actor)
        self._render()

    def display_crack_front_lines(self, fronts: list[np.ndarray],
                                 colour: tuple = (0.0, 0.0, 0.0),
                                 line_width: float = 3.0):
        """Display multiple crack-front polylines (one per propagation increment).

        Each front is ordered by nearest-neighbour so lines follow the
        crack front continuously.
        """
        from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyLine

        points = vtkPoints()
        cells = vtkCellArray()
        pt_offset = 0

        for coords in fronts:
            if len(coords) < 2:
                continue
            order = _nearest_neighbour_order(coords)

            line = vtkPolyLine()
            line.GetPointIds().SetNumberOfIds(len(order))
            for i, idx in enumerate(order):
                x, y, z = coords[idx]
                points.InsertNextPoint(float(x), float(y), float(z))
                line.GetPointIds().SetId(i, pt_offset + i)
            cells.InsertNextCell(line)
            pt_offset += len(order)

        if pt_offset == 0:
            return

        poly = vtkPolyData()
        poly.SetPoints(points)
        poly.SetLines(cells)

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly)
        mapper.ScalarVisibilityOff()

        actor = vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*colour)
        prop.SetLineWidth(line_width)
        prop.LightingOff()
        prop.SetRenderLinesAsTubes(True)

        self._replace_actor("Crack Front", actor)
        self._render()

    def highlight_object(self, name: str):
        if self._highlighted and self._highlighted in self._actors:
            prev   = self._actors[self._highlighted]
            colour = self._actor_colours.get(self._highlighted, _DEFAULT_COLOUR)
            prev.GetProperty().SetColor(*colour)
        if name in self._actors:
            self._actors[name].GetProperty().SetColor(*_HIGHLIGHT_COLOUR)
            self._highlighted = name
        self._render()

    def clear_highlight(self):
        """Remove the highlight from whichever actor is currently highlighted."""
        if self._highlighted and self._highlighted in self._actors:
            prev   = self._actors[self._highlighted]
            colour = self._actor_colours.get(self._highlighted, _DEFAULT_COLOUR)
            prev.GetProperty().SetColor(*colour)
        self._highlighted = None
        self._render()

    def set_actor_visibility(self, name: str, visible: bool):
        """Show or hide a named actor without removing it."""
        if name in self._actors:
            self._actors[name].SetVisibility(visible)
            self._render()

    def remove_actor(self, name: str):
        if name in self._actors:
            self._renderer.RemoveActor(self._actors.pop(name))
            self._actor_colours.pop(name, None)
            if self._highlighted == name:
                self._highlighted = None
            self._render()

    def clear(self):
        for actor in self._actors.values():
            self._renderer.RemoveActor(actor)
        self._actors.clear()
        self._actor_colours.clear()
        self._current_mesh_actor = None
        self._highlighted = None
        self._scalar_bar.SetVisibility(False)
        self._render()

    def hide_scalar_bar(self):
        self._scalar_bar.SetVisibility(False)
        self._render()

    def set_scalar_bar_visible(self, visible: bool):
        """Show or hide the scalar bar."""
        self._scalar_bar.SetVisibility(visible)
        self._render()

    def save_screenshot(self, path: str):
        """Save the current 3D view to an image file (PNG)."""
        from vtkmodules.vtkIOImage import vtkPNGWriter
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter

        w2i = vtkWindowToImageFilter()
        w2i.SetInput(self._vtk_widget.GetRenderWindow())
        w2i.SetScale(2)  # 2× resolution
        w2i.ReadFrontBufferOff()
        w2i.Update()

        writer = vtkPNGWriter()
        writer.SetFileName(path)
        writer.SetInputConnection(w2i.GetOutputPort())
        writer.Write()

    def set_display_mode(self, mode: str):
        """Set mesh display mode across all actors.

        Parameters
        ----------
        mode : 'wireframe' | 'surface' | 'surface_edges'
        """
        for name, actor in self._actors.items():
            prop = actor.GetProperty()
            colour = self._actor_colours.get(name, _DEFAULT_COLOUR)

            if mode == "wireframe":
                prop.SetRepresentationToWireframe()
                prop.SetEdgeVisibility(False)
            elif mode == "surface":
                prop.SetRepresentationToSurface()
                prop.SetColor(*colour)
                prop.SetEdgeVisibility(False)
            elif mode == "surface_edges":
                prop.SetRepresentationToSurface()
                prop.SetColor(*colour)
                prop.SetEdgeVisibility(True)
                prop.SetEdgeColor(*_EDGE_COLOUR)
                prop.SetLineWidth(0.8)
        self._current_display_mode = mode
        self._render()

    def fit_all(self):
        self._renderer.ResetCamera()
        self._render()

    # ------------------------------------------------------------------
    # Camera presets
    # ------------------------------------------------------------------

    def reset_view(self):
        """Reset camera to default isometric view and fit all."""
        cam = self._renderer.GetActiveCamera()
        fp = list(cam.GetFocalPoint())
        dist = cam.GetDistance() or 1.0
        d = dist / 1.732
        cam.SetPosition(fp[0] + d, fp[1] + d, fp[2] + d)
        cam.SetViewUp(0, 1, 0)
        self._renderer.ResetCamera()
        self._render()

    def view_front(self):
        """Camera looking along -Z axis (front view)."""
        cam = self._renderer.GetActiveCamera()
        fp = list(cam.GetFocalPoint())
        dist = cam.GetDistance() or 1.0
        cam.SetPosition(fp[0], fp[1], fp[2] + dist)
        cam.SetViewUp(0, 1, 0)
        self._renderer.ResetCamera()
        self._render()

    def view_top(self):
        """Camera looking along -Y axis (top view)."""
        cam = self._renderer.GetActiveCamera()
        fp = list(cam.GetFocalPoint())
        dist = cam.GetDistance() or 1.0
        cam.SetPosition(fp[0], fp[1] + dist, fp[2])
        cam.SetViewUp(0, 0, -1)
        self._renderer.ResetCamera()
        self._render()

    def view_right(self):
        """Camera looking along -X axis (right view)."""
        cam = self._renderer.GetActiveCamera()
        fp = list(cam.GetFocalPoint())
        dist = cam.GetDistance() or 1.0
        cam.SetPosition(fp[0] + dist, fp[1], fp[2])
        cam.SetViewUp(0, 1, 0)
        self._renderer.ResetCamera()
        self._render()

    def view_isometric(self):
        """Standard isometric view."""
        cam = self._renderer.GetActiveCamera()
        fp = list(cam.GetFocalPoint())
        dist = cam.GetDistance() or 1.0
        d = dist / 1.732   # 1/sqrt(3) for equal axis contribution
        cam.SetPosition(fp[0] + d, fp[1] + d, fp[2] + d)
        cam.SetViewUp(0, 1, 0)
        self._renderer.ResetCamera()
        self._render()

    # ------------------------------------------------------------------
    # Edge visibility (independent of display mode)
    # ------------------------------------------------------------------

    def set_edges_visible(self, visible: bool):
        """Toggle edge visibility on all mesh actors."""
        for actor in self._actors.values():
            prop = actor.GetProperty()
            if visible:
                prop.SetEdgeVisibility(True)
                prop.SetEdgeColor(*_EDGE_COLOUR)
                prop.SetLineWidth(0.8)
            else:
                prop.SetEdgeVisibility(False)
        self._render()

    # ------------------------------------------------------------------
    # Probe / Query
    # ------------------------------------------------------------------

    def set_probe_mode(self, enabled: bool):
        """Toggle probe picking mode.

        When enabled, left-clicks pick the nearest rendered point
        (intercepted via event filter — no rotation).
        """
        self._probe_enabled = enabled
        if enabled:
            self._vtk_widget.installEventFilter(self)
            self._vtk_widget.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._vtk_widget.removeEventFilter(self)
            self._vtk_widget.setCursor(Qt.CursorShape.ArrowCursor)
            self._remove_probe_marker()

    def eventFilter(self, obj, event):
        if (self._probe_enabled and obj is self._vtk_widget
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            pos = event.position()
            dpr = self._vtk_widget.devicePixelRatio()
            self._do_pick(pos.x() * dpr, pos.y() * dpr)
            return True                          # consume — no rotation
        return super().eventFilter(obj, event)

    def _do_pick(self, sx: float, sy: float):
        """Pick the world position under (*sx*, *sy*) display coords."""
        from vtkmodules.vtkRenderingCore import vtkWorldPointPicker

        picker = vtkWorldPointPicker()
        h = self._vtk_widget.GetRenderWindow().GetSize()[1]
        picker.Pick(float(sx), float(h - sy), 0.0, self._renderer)
        wp = picker.GetPickPosition()
        self.show_probe_marker(wp[0], wp[1], wp[2])
        self.point_picked.emit(wp[0], wp[1], wp[2])

    def show_probe_marker(self, x: float, y: float, z: float):
        """Place a small red sphere at the probed location."""
        from vtkmodules.vtkFiltersSources import vtkSphereSource

        self._remove_probe_marker()

        # Scale radius to ~0.8 % of the visible scene diagonal
        bounds = self._renderer.ComputeVisiblePropBounds()
        diag = ((bounds[1] - bounds[0]) ** 2
                + (bounds[3] - bounds[2]) ** 2
                + (bounds[5] - bounds[4]) ** 2) ** 0.5
        radius = max(diag * 0.008, 0.01)

        sphere = vtkSphereSource()
        sphere.SetCenter(x, y, z)
        sphere.SetRadius(radius)
        sphere.SetThetaResolution(16)
        sphere.SetPhiResolution(16)
        sphere.Update()

        mapper = vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        mapper.ScalarVisibilityOff()

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(1.0, 0.2, 0.2)
        actor.GetProperty().LightingOff()

        self._probe_marker = actor
        self._renderer.AddActor(actor)
        self._render()

    def _remove_probe_marker(self):
        if self._probe_marker is not None:
            self._renderer.RemoveActor(self._probe_marker)
            self._probe_marker = None
            self._render()

    # ------------------------------------------------------------------
    # Actor transform  (used by Crack Edit dialog)
    # ------------------------------------------------------------------

    def apply_actor_transform(
        self, name: str,
        tx: float, ty: float, tz: float,
        rx: float, ry: float, rz: float,
        centroid: tuple[float, float, float],
    ) -> None:
        """Apply a translate+rotate transform to *name* for live preview."""
        if name not in self._actors:
            return
        from vtkmodules.vtkCommonTransforms import vtkTransform
        t = vtkTransform()
        t.PostMultiply()
        cx, cy, cz = centroid
        t.Translate(-cx, -cy, -cz)
        t.RotateX(rx)
        t.RotateY(ry)
        t.RotateZ(rz)
        t.Translate(cx, cy, cz)
        t.Translate(tx, ty, tz)
        self._actors[name].SetUserTransform(t)
        self._render()

    def clear_actor_transform(self, name: str) -> None:
        """Remove any user transform from *name*."""
        if name not in self._actors:
            return
        self._actors[name].SetUserTransform(None)
        self._render()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _replace_actor(self, name: str, actor: vtkActor) -> None:
        if name in self._actors:
            self._renderer.RemoveActor(self._actors[name])
        self._actors[name] = actor
        c = actor.GetProperty().GetColor()
        self._actor_colours[name] = (c[0], c[1], c[2])
        self._renderer.AddActor(actor)
        self._renderer.ResetCamera()

    def _render(self):
        self._vtk_widget.GetRenderWindow().Render()


# ---------------------------------------------------------------------------
# Actor material
# ---------------------------------------------------------------------------

def _fe_solid_props(
    actor: vtkActor,
    colour: tuple[float, float, float],
    show_edges: bool = True,
) -> None:
    """
    Apply FE-correct solid material settings.

    SetInterpolationToFlat()
        Assigns one constant colour per triangulated primitive, computed from
        that primitive's face normal.  For flat element faces all primitives
        share the same normal → uniform, clean face colour.  No normal
        averaging → no bumpy artefacts.
    """
    prop = actor.GetProperty()
    prop.SetInterpolationToFlat()
    prop.SetColor(*colour)
    prop.SetOpacity(1.0)
    prop.SetAmbient(0.18)
    prop.SetDiffuse(0.82)
    prop.SetSpecular(0.0)    # no highlight — engineering solid, not CAD chrome
    if show_edges:
        prop.SetEdgeVisibility(True)
        prop.SetEdgeColor(*_EDGE_COLOUR)
        prop.SetLineWidth(0.8)
    else:
        prop.SetEdgeVisibility(False)


# ---------------------------------------------------------------------------
# B-rep tessellation
# ---------------------------------------------------------------------------

def _brep_to_polydata(brep_path: str) -> vtkPolyData:
    """Tessellate an OCCT geometry file into triangles."""
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopoDS import topods
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.TopLoc import TopLoc_Location
    from vtkmodules.vtkCommonDataModel import vtkCellArray
    from core.crack_surface_s3 import _read_occ_shape

    shape = _read_occ_shape(brep_path)
    BRepMesh_IncrementalMesh(shape, 0.1, False, 0.5).Perform()

    points    = vtkPoints()
    triangles = []
    offset    = 0

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face  = topods.Face(explorer.Current())
        loc   = TopLoc_Location()
        tri   = BRep_Tool.Triangulation(face, loc)
        if tri is None:
            explorer.Next()
            continue

        trsf    = loc.Transformation() if not loc.IsIdentity() else None
        n_nodes = tri.NbNodes()
        for i in range(1, n_nodes + 1):
            p = tri.Node(i)
            if trsf:
                p = p.Transformed(trsf)
            points.InsertNextPoint(p.X(), p.Y(), p.Z())

        for i in range(1, tri.NbTriangles() + 1):
            n1, n2, n3 = tri.Triangle(i).Get()
            if face.Orientation() == 1:
                n1, n3 = n3, n1
            triangles.append((offset + n1 - 1, offset + n2 - 1, offset + n3 - 1))
        offset += n_nodes
        explorer.Next()

    poly  = vtkPolyData()
    poly.SetPoints(points)
    cells = vtkCellArray()
    for t in triangles:
        cells.InsertNextCell(3)
        for idx in t:
            cells.InsertCellPoint(idx)
    poly.SetPolys(cells)

    from vtkmodules.vtkCommonDataModel import vtkCellArray  # already imported above
    return poly


# ---------------------------------------------------------------------------
# FRD mesh → vtkUnstructuredGrid
# ---------------------------------------------------------------------------

_VOLUME_ETYPES  = {"C3D4", "C3D4R", "C3D10", "C3D8", "C3D8R",
                   "C3D20", "C3D20R", "C3D6", "C3D15"}
_SURFACE_ETYPES = {"TRI3", "TRI6", "S3", "S6", "S4", "S8"}


def _meshdata_to_ugrid(mesh) -> vtkUnstructuredGrid:
    """
    Convert MeshData → vtkUnstructuredGrid.

    Quadratic elements are linearised (corner nodes only) so that
    vtkGeometryFilter produces clean quad/tri faces instead of
    tessellated sub-triangles.  Surface elements are skipped when
    volume elements are present.
    """
    grid   = vtkUnstructuredGrid()
    points = vtkPoints()

    sorted_nids = sorted(mesh.nodes.keys())
    nid_to_idx  = {nid: i for i, nid in enumerate(sorted_nids)}

    for nid in sorted_nids:
        n = mesh.nodes[nid]
        points.InsertNextPoint(n.x, n.y, n.z)
    grid.SetPoints(points)

    has_volumes = any(el.etype in _VOLUME_ETYPES for el in mesh.elements.values())

    skipped: set[str] = set()
    for el in mesh.elements.values():
        if has_volumes and el.etype in _SURFACE_ETYPES:
            continue
        vtk_type = CCX_TO_VTK.get(el.etype)
        if vtk_type is None:
            skipped.add(el.etype)
            continue

        nodes = el.nodes

        # Linearise quadratic cells: keep only corner nodes so
        # vtkGeometryFilter outputs clean quad/tri faces, not sub-triangles.
        lin = _LINEARIZE.get(vtk_type)
        if lin:
            vtk_type, n_corners = lin
            nodes = nodes[:n_corners]

        if any(nid not in nid_to_idx for nid in nodes):
            continue
        id_list = vtkIdList()
        for nid in nodes:
            id_list.InsertNextId(nid_to_idx[nid])
        grid.InsertNextCell(vtk_type, id_list)

    if skipped:
        print(f"Viewer: skipped unsupported element types: {skipped}")
    return grid


# ---------------------------------------------------------------------------
# Colour map
# ---------------------------------------------------------------------------

def _build_rainbow_lut(vmin: float, vmax: float) -> vtkLookupTable:
    lut = vtkLookupTable()
    lut.SetNumberOfTableValues(256)
    lut.SetHueRange(0.667, 0.0)
    lut.SetRange(vmin, vmax)
    lut.Build()
    return lut


# ---------------------------------------------------------------------------
# Scalar bar — PrePoMax / Abaqus style
# ---------------------------------------------------------------------------

def _cae_font() -> vtkTextProperty:
    """Return a clean engineering-style text property (Arial, black, no shadow)."""
    tp = vtkTextProperty()
    tp.SetFontFamilyToArial()
    tp.SetColor(0.0, 0.0, 0.0)
    tp.SetBold(False)
    tp.SetItalic(False)
    tp.SetShadow(False)
    tp.SetFrameWidth(0)
    return tp


def _create_scalar_bar() -> vtkScalarBarActor:
    """Build a vtkScalarBarActor styled like PrePoMax / Abaqus / Ansys.

    Layout (top-left, vertical, thin):
        ┌──────────┐
        │ DELTAKEQ │  ← title
        │          │
        │ ██ 753.  │
        │ ██ 622.  │  ← 7 labels
        │ ██ 492.  │
        │ ██ 361.  │
        │ ██ 231.  │
        └──────────┘
    """
    bar = vtkScalarBarActor()
    bar.SetVisibility(False)
    bar.SetOrientationToVertical()
    bar.SetNumberOfLabels(7)
    bar.SetMaximumNumberOfColors(256)
    bar.SetBarRatio(0.3)               # colour swatch = 30% of total width
    bar.UnconstrainedFontSizeOn()
    bar.SetAnnotationLeaderPadding(8)

    # Remove the ugly frame / outline
    bar.SetDrawFrame(False)
    bar.SetDrawBackground(False)
    bar.SetDrawTickLabels(True)

    # Position — top-left corner
    bar.SetPosition(0.02, 0.22)        # (x, y) in normalised viewport coords
    bar.SetWidth(0.10)                 # 10% of viewport width
    bar.SetHeight(0.76)                # 76% of viewport height

    # Title text properties
    title_tp = _cae_font()
    title_tp.SetFontSize(14)
    title_tp.SetBold(True)
    title_tp.SetJustificationToCentered()
    title_tp.SetVerticalJustificationToTop()
    bar.SetTitleTextProperty(title_tp)

    # Label text properties
    label_tp = _cae_font()
    label_tp.SetFontSize(12)
    label_tp.SetJustificationToLeft()
    bar.SetLabelTextProperty(label_tp)

    # Label number format: 4 significant digits, auto-exponent
    bar.SetLabelFormat("%-#6.4g")

    # Annotation text (if used)
    ann_tp = _cae_font()
    ann_tp.SetFontSize(11)
    bar.SetAnnotationTextProperty(ann_tp)

    bar.SetTextPositionToPrecedeScalarBar()
    bar.SetTextPad(4)

    return bar


def _update_scalar_bar(bar: vtkScalarBarActor,
                       lut: vtkLookupTable,
                       title: str) -> None:
    """Bind a lookup table and title to the pre-styled scalar bar."""
    bar.SetLookupTable(lut)
    bar.SetTitle(title)
    bar.SetVisibility(True)


# ---------------------------------------------------------------------------
# Crack front ordering
# ---------------------------------------------------------------------------

def _nearest_neighbour_order(coords: np.ndarray) -> list[int]:
    """Order points by nearest-neighbour to form a continuous polyline.

    Starts from the point farthest from the centroid (an endpoint of the
    front) and greedily connects to the closest unused point.
    """
    n = len(coords)
    if n <= 2:
        return list(range(n))

    # Start from the point farthest from centroid (likely an endpoint)
    centroid = coords.mean(axis=0)
    start = int(np.argmax(np.sum((coords - centroid) ** 2, axis=1)))

    ordered = [start]
    used = np.zeros(n, dtype=bool)
    used[start] = True

    for _ in range(n - 1):
        last = coords[ordered[-1]]
        dists = np.sum((coords - last) ** 2, axis=1)
        dists[used] = np.inf
        nearest = int(np.argmin(dists))
        ordered.append(nearest)
        used[nearest] = True

    return ordered
