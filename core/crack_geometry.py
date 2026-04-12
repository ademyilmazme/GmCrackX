"""
Parametric crack geometry generators for the Insert Crack wizard.

Each crack type has a standalone generator function that returns raw
(vertices, triangles) numpy arrays.  The master ``generate_crack_mesh()``
dispatcher applies placement transforms and feeds the result through
``CrackSurfaceBuilder.from_triangles()`` to produce a ready-to-use
``CrackSurfaceState``.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np


# ---------------------------------------------------------------------------
# Crack type enumeration
# ---------------------------------------------------------------------------

class CrackType(enum.Enum):
    ELLIPTICAL_SURFACE = "elliptical_surface"
    CORNER             = "corner"
    EDGE               = "edge"
    THROUGH            = "through"
    USER_DEFINED       = "user_defined"


# ---------------------------------------------------------------------------
# Crack definition — flows through all wizard pages
# ---------------------------------------------------------------------------

@dataclass
class CrackDefinition:
    crack_type: CrackType = CrackType.ELLIPTICAL_SURFACE

    # Geometry (type-specific)
    a: float = 1.0              # semi-depth
    c: float = 2.0              # half-width
    thickness: float = 5.0      # plate thickness (through / edge)

    # Placement
    tx: float = 0.0
    ty: float = 0.0
    tz: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0

    # Meshing
    template_radius: float = 0.3    # relative to a
    front_point_count: int = 15
    mesh_refinement: float = 1.0    # density multiplier

    # User-defined only
    user_file_path: str = ""


# ---------------------------------------------------------------------------
# Transform helper (same Euler XYZ maths as main_window._apply_transform_numpy)
# ---------------------------------------------------------------------------

def _apply_transform(vertices: np.ndarray,
                     tx: float, ty: float, tz: float,
                     rx: float, ry: float, rz: float,
                     centroid: np.ndarray) -> np.ndarray:
    """Rotate around *centroid* (XYZ Euler, degrees) then translate."""
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


# ---------------------------------------------------------------------------
# gmsh triangle extraction helper (mirrors CrackSurfaceBuilder._triangulate_brep)
# ---------------------------------------------------------------------------

def _extract_gmsh_triangles() -> tuple[np.ndarray, np.ndarray]:
    """Extract vertices and triangles from current gmsh model.

    Must be called AFTER ``gmsh.model.mesh.generate(2)``.
    Returns (vertices, triangles) as numpy arrays.
    """
    import gmsh

    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    verts = np.array(coords).reshape(-1, 3)
    tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

    elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=2)

    all_tris: list[np.ndarray] = []
    for etype, etags, entags in zip(elem_types, elem_tags, elem_node_tags):
        if etype == 2:       # 3-node triangle
            nodes_per = 3
        elif etype == 3:     # 4-node quad → split into 2 tris
            nodes_per = 4
        else:
            continue
        n_elems = len(etags)
        conn = np.array(entags, dtype=np.int64).reshape(n_elems, nodes_per)
        if nodes_per == 3:
            all_tris.append(
                np.vectorize(tag_to_idx.get)(conn).astype(np.int32))
        else:
            t1 = np.stack([conn[:, 0], conn[:, 1], conn[:, 2]], axis=1)
            t2 = np.stack([conn[:, 0], conn[:, 2], conn[:, 3]], axis=1)
            for t in (t1, t2):
                all_tris.append(
                    np.vectorize(tag_to_idx.get)(t).astype(np.int32))

    if not all_tris:
        raise RuntimeError("gmsh produced no triangles.")

    tris = np.vstack(all_tris)
    valid = np.array([len(set(row)) == 3 for row in tris])
    return verts, tris[valid]


# ---------------------------------------------------------------------------
# Parametric generators
# ---------------------------------------------------------------------------

def generate_elliptical_surface(defn: CrackDefinition,
                                ) -> tuple[np.ndarray, np.ndarray]:
    """Half-elliptical surface crack in the XZ plane.

    Semi-depth *a* along Z, half-width *c* along X.
    Crack mouth sits on the Z=0 line (the free surface).
    The curved front is the half-ellipse arc at depth.
    """
    import gmsh

    a, c = defn.a, defn.c
    n_front = max(defn.front_point_count, 5)

    gmsh.initialize(interruptible=False)
    gmsh.option.setNumber("General.Verbosity", 0)
    try:
        # Half-ellipse boundary: arc from (-c,0,0) over (0,0,a) to (c,0,0)
        p_left  = gmsh.model.occ.addPoint(-c, 0, 0)
        p_right = gmsh.model.occ.addPoint( c, 0, 0)
        p_top   = gmsh.model.occ.addPoint( 0, 0, a)

        # Ellipse arc needs: start, centre, major-axis endpoint, end
        p_center = gmsh.model.occ.addPoint(0, 0, 0)
        arc1 = gmsh.model.occ.addEllipseArc(p_left, p_center, p_left, p_top)
        arc2 = gmsh.model.occ.addEllipseArc(p_top, p_center, p_left, p_right)

        # Straight mouth edge
        mouth = gmsh.model.occ.addLine(p_right, p_left)

        loop = gmsh.model.occ.addCurveLoop([arc1, arc2, mouth])
        gmsh.model.occ.addPlaneSurface([loop])
        gmsh.model.occ.synchronize()

        # Mesh sizing driven by front_point_count
        arc_length = math.pi * math.sqrt((a**2 + c**2) / 2.0)
        char_len = arc_length / n_front
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax",
                              char_len * defn.mesh_refinement)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin",
                              char_len * defn.template_radius)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)

        gmsh.model.mesh.generate(2)
        verts, tris = _extract_gmsh_triangles()
    finally:
        gmsh.finalize()

    return verts, tris


def generate_corner(defn: CrackDefinition,
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Quarter-elliptical corner crack in the XZ plane.

    Semi-depth *a* along Z, half-width *c* along X.
    Two straight mouth edges along the X and Z axes, arc in between.
    """
    import gmsh

    a, c = defn.a, defn.c
    n_front = max(defn.front_point_count, 5)

    gmsh.initialize(interruptible=False)
    gmsh.option.setNumber("General.Verbosity", 0)
    try:
        p_origin = gmsh.model.occ.addPoint(0, 0, 0)
        p_x      = gmsh.model.occ.addPoint(c, 0, 0)
        p_z      = gmsh.model.occ.addPoint(0, 0, a)

        arc = gmsh.model.occ.addEllipseArc(p_x, p_origin, p_x, p_z)

        edge_z = gmsh.model.occ.addLine(p_z, p_origin)
        edge_x = gmsh.model.occ.addLine(p_origin, p_x)

        loop = gmsh.model.occ.addCurveLoop([arc, edge_z, edge_x])
        gmsh.model.occ.addPlaneSurface([loop])
        gmsh.model.occ.synchronize()

        arc_length = 0.5 * math.pi * math.sqrt((a**2 + c**2) / 2.0)
        char_len = arc_length / n_front
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax",
                              char_len * defn.mesh_refinement)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin",
                              char_len * defn.template_radius)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)

        gmsh.model.mesh.generate(2)
        verts, tris = _extract_gmsh_triangles()
    finally:
        gmsh.finalize()

    return verts, tris


def generate_edge(defn: CrackDefinition,
                  ) -> tuple[np.ndarray, np.ndarray]:
    """Straight-fronted edge crack (rectangular patch) in the XZ plane.

    Depth *a* along Z, width *c* along X.
    Front is the top edge (Z=a). Mouth is the bottom (Z=0).
    """
    import gmsh

    a, c = defn.a, defn.c
    n_front = max(defn.front_point_count, 5)

    gmsh.initialize(interruptible=False)
    gmsh.option.setNumber("General.Verbosity", 0)
    try:
        p1 = gmsh.model.occ.addPoint(0, 0, 0)
        p2 = gmsh.model.occ.addPoint(c, 0, 0)
        p3 = gmsh.model.occ.addPoint(c, 0, a)
        p4 = gmsh.model.occ.addPoint(0, 0, a)

        l1 = gmsh.model.occ.addLine(p1, p2)
        l2 = gmsh.model.occ.addLine(p2, p3)
        l3 = gmsh.model.occ.addLine(p3, p4)
        l4 = gmsh.model.occ.addLine(p4, p1)

        loop = gmsh.model.occ.addCurveLoop([l1, l2, l3, l4])
        gmsh.model.occ.addPlaneSurface([loop])
        gmsh.model.occ.synchronize()

        char_len = c / n_front
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax",
                              char_len * defn.mesh_refinement)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin",
                              char_len * defn.template_radius)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)

        gmsh.model.mesh.generate(2)
        verts, tris = _extract_gmsh_triangles()
    finally:
        gmsh.finalize()

    return verts, tris


def generate_through(defn: CrackDefinition,
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Through-thickness crack (rectangular patch) in the XY plane.

    Half-length *a* along X (crack extends ±a), thickness along Y.
    Two crack fronts at X = ±a.
    """
    import gmsh

    a = defn.a
    t = defn.thickness
    n_front = max(defn.front_point_count, 5)

    gmsh.initialize(interruptible=False)
    gmsh.option.setNumber("General.Verbosity", 0)
    try:
        p1 = gmsh.model.occ.addPoint(-a, 0, 0)
        p2 = gmsh.model.occ.addPoint( a, 0, 0)
        p3 = gmsh.model.occ.addPoint( a, t, 0)
        p4 = gmsh.model.occ.addPoint(-a, t, 0)

        l1 = gmsh.model.occ.addLine(p1, p2)
        l2 = gmsh.model.occ.addLine(p2, p3)
        l3 = gmsh.model.occ.addLine(p3, p4)
        l4 = gmsh.model.occ.addLine(p4, p1)

        loop = gmsh.model.occ.addCurveLoop([l1, l2, l3, l4])
        gmsh.model.occ.addPlaneSurface([loop])
        gmsh.model.occ.synchronize()

        char_len = t / n_front
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax",
                              char_len * defn.mesh_refinement)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin",
                              char_len * defn.template_radius)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)

        gmsh.model.mesh.generate(2)
        verts, tris = _extract_gmsh_triangles()
    finally:
        gmsh.finalize()

    return verts, tris


def generate_user_defined(defn: CrackDefinition,
                          ) -> tuple[np.ndarray, np.ndarray]:
    """Load crack geometry from a user-supplied file.

    Delegates to ``CrackSurfaceBuilder.build()`` which handles
    STL / BREP / STEP formats.
    """
    from core.crack_surface_s3 import CrackSurfaceBuilder

    builder = CrackSurfaceBuilder(
        defn.user_file_path,
        mesh_size=defn.mesh_refinement,
    )
    state = builder.build()
    return state.vertices, state.triangles


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_GENERATORS: dict[CrackType, Callable] = {
    CrackType.ELLIPTICAL_SURFACE: generate_elliptical_surface,
    CrackType.CORNER:             generate_corner,
    CrackType.EDGE:               generate_edge,
    CrackType.THROUGH:            generate_through,
    CrackType.USER_DEFINED:       generate_user_defined,
}


def generate_crack_mesh(defn: CrackDefinition):
    """Master entry point: generate geometry, apply transform, build state.

    Returns a ``CrackSurfaceState`` ready for propagation.
    """
    from core.crack_surface_s3 import CrackSurfaceBuilder

    gen = _GENERATORS[defn.crack_type]
    verts, tris = gen(defn)

    # Apply placement transform
    centroid = verts.mean(axis=0)
    has_transform = any(v != 0.0 for v in (defn.tx, defn.ty, defn.tz,
                                            defn.rx, defn.ry, defn.rz))
    if has_transform:
        verts = _apply_transform(verts, defn.tx, defn.ty, defn.tz,
                                 defn.rx, defn.ry, defn.rz, centroid)

    # Build final CrackSurfaceState (normal consistency + front detection)
    normal_hint = np.array([0.0, 1.0, 0.0])
    return CrackSurfaceBuilder.from_triangles(verts, tris,
                                              normal_hint=normal_hint)
