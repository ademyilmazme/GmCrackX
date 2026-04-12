"""
S3 crack surface representation for CalculiX *CRACK PROPAGATION.

CalculiX requires the crack surface to be discretized as S3 (3-node shell)
elements.  The crack front is auto-detected by CalculiX as the set of free
edges (edges shared by exactly one S3 element).  No ELSET or SURFACE
definition is needed for the crack front.

Classes
-------
CrackSurfaceState  — immutable snapshot of vertices + triangles at one step
CrackSurfaceBuilder — build initial S3 mesh from B-rep / STL / numpy arrays
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class CrackSurfaceState:
    """
    Complete description of the crack surface at one point in time.

    vertices      — (V, 3) node coordinates (1-indexed when written to INP)
    triangles     — (T, 3) vertex indices into `vertices` (0-based internally)
    front_node_ids — ordered chain of 0-based vertex indices forming the crack front
                     (free edges of the triangle mesh, ordered as a spatial chain)
    mouth_node_ids — 0-based vertex indices where the crack intersects a free surface
                     (these nodes are NOT advanced during surface extension)
    step_added     — maps triangle index → step number it was added (0 = initial)
    """
    vertices:       np.ndarray                  # (V, 3) float64
    triangles:      np.ndarray                  # (T, 3) int32, 0-based
    front_node_ids: list[int]                   # ordered chain, 0-based
    mouth_node_ids: list[int] = field(default_factory=list)
    step_added:     dict[int, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise to JSON-compatible dict (for checkpoint files)."""
        return {
            "vertices":       self.vertices.tolist(),
            "triangles":      self.triangles.tolist(),
            "front_node_ids": self.front_node_ids,
            "mouth_node_ids": self.mouth_node_ids,
            "step_added":     {str(k): v for k, v in self.step_added.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> CrackSurfaceState:
        """Deserialise from checkpoint dict."""
        return cls(
            vertices=np.array(d["vertices"]),
            triangles=np.array(d["triangles"], dtype=np.int32),
            front_node_ids=d["front_node_ids"],
            mouth_node_ids=d.get("mouth_node_ids", []),
            step_added={int(k): v for k, v in d.get("step_added", {}).items()},
        )

    def front_coords(self) -> np.ndarray:
        """(N, 3) coordinates of crack-front nodes, in front chain order."""
        return self.vertices[self.front_node_ids]

    def crack_length(self) -> float:
        """Arc length of the ordered crack front."""
        pts = self.front_coords()
        if len(pts) < 2:
            return 0.0
        return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class CrackSurfaceBuilder:
    """
    Build an initial S3 crack surface mesh from geometry.

    Supported sources
    -----------------
    - B-rep (.brep / .step / .stp) — triangulated via OCC BRepMesh
    - STL (.stl) — loaded directly as triangles (no OCC needed)
    - numpy arrays — use `from_triangles()` class method

    Parameters
    ----------
    crack_path : path to crack geometry file
    mesh_size  : linear deflection for BRepMesh (ignored for STL / arrays)
    normal_hint : optional (3,) unit vector; if supplied, the BFS normal
                  consistency pass ensures all normals point toward this half-space
    """

    def __init__(
        self,
        crack_path: str | Path,
        mesh_size: float = 0.05,
        angular_deflection: float = 0.08,
        normal_hint: Sequence[float] | None = None,
    ) -> None:
        self.crack_path         = Path(crack_path)
        self.mesh_size          = float(mesh_size)
        self.angular_deflection = float(angular_deflection)
        self.normal_hint = np.asarray(normal_hint, dtype=float) if normal_hint is not None else None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def build(self) -> CrackSurfaceState:
        """Triangulate the crack geometry and return a CrackSurfaceState."""
        ext = self.crack_path.suffix.lower()
        if ext == ".stl":
            verts, tris = self._load_stl()
        else:
            verts, tris = self._triangulate_brep()

        tris = self._enforce_consistent_normals(verts, tris)
        tris = self._orient_toward_hint(verts, tris)

        front_ids = self._find_crack_front(tris)
        step_added = {i: 0 for i in range(len(tris))}

        return CrackSurfaceState(
            vertices=verts,
            triangles=tris.astype(np.int32),
            front_node_ids=front_ids,
            mouth_node_ids=[],
            step_added=step_added,
        )

    @classmethod
    def from_triangles(
        cls,
        vertices: np.ndarray,
        triangles: np.ndarray,
        normal_hint: Sequence[float] | None = None,
    ) -> CrackSurfaceState:
        """
        Build directly from numpy arrays — no OCC / file I/O required.
        Useful for tests and programmatic surface construction.

        Parameters
        ----------
        vertices  : (V, 3)
        triangles : (T, 3) int, 0-based vertex indices
        """
        builder = cls.__new__(cls)
        builder.crack_path   = Path("(in-memory)")
        builder.mesh_size    = 1.0
        builder.normal_hint  = (
            np.asarray(normal_hint, dtype=float) if normal_hint is not None else None
        )

        verts = np.asarray(vertices, dtype=float)
        tris  = np.asarray(triangles, dtype=np.int32)

        tris = builder._enforce_consistent_normals(verts, tris)
        tris = builder._orient_toward_hint(verts, tris)

        front_ids = builder._find_crack_front(tris)
        return CrackSurfaceState(
            vertices=verts,
            triangles=tris,
            front_node_ids=front_ids,
            mouth_node_ids=[],
            step_added={i: 0 for i in range(len(tris))},
        )

    # ------------------------------------------------------------------
    # INP writer
    # ------------------------------------------------------------------

    @staticmethod
    def write_s3_inp(state: CrackSurfaceState, path: str | Path) -> None:
        """
        Write the S3 crack surface to a CalculiX .inp file.

        Format:
          *NODE
          nid, x, y, z
          ...
          *ELEMENT, TYPE=S3, ELSET=CRACK_SURFACE
          eid, n0, n1, n2
          ...
          *NSET, NSET=CRACK_FRONT
          n0, n1, ...
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        V = len(state.vertices)
        T = len(state.triangles)

        with open(path, "w") as fh:
            # Nodes — 1-indexed
            fh.write("*NODE\n")
            for i, (x, y, z) in enumerate(state.vertices):
                fh.write(f"{i + 1}, {x:.10g}, {y:.10g}, {z:.10g}\n")

            # S3 elements — 1-indexed, both node IDs and element IDs
            fh.write("*ELEMENT, TYPE=S3, ELSET=CRACK_SURFACE\n")
            for i, (a, b, c) in enumerate(state.triangles):
                fh.write(f"{i + 1}, {a + 1}, {b + 1}, {c + 1}\n")

            # CRACK_FRONT node set (1-indexed)
            fh.write("*NSET, NSET=CRACK_FRONT\n")
            front_1indexed = [n + 1 for n in state.front_node_ids]
            _write_id_list(fh, front_1indexed)

    # ------------------------------------------------------------------
    # Private — triangulation
    # ------------------------------------------------------------------

    def _triangulate_brep(self) -> tuple[np.ndarray, np.ndarray]:
        """Use gmsh to mesh the crack surface geometry (.brep/.step/.iges/.stl)."""
        import gmsh

        gmsh.initialize(interruptible=False)
        gmsh.option.setNumber("General.Verbosity", 0)
        try:
            ext = self.crack_path.suffix.lower()
            if ext in (".brep", ".brp"):
                gmsh.model.occ.importShapes(str(self.crack_path))
            elif ext in (".step", ".stp", ".iges", ".igs"):
                gmsh.model.occ.importShapes(str(self.crack_path))
            else:
                raise ValueError(f"Unsupported format for gmsh: {ext}")

            gmsh.model.occ.synchronize()

            # Set global mesh size
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", self.mesh_size * 0.5)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", self.mesh_size)
            gmsh.option.setNumber("Mesh.Algorithm", 6)       # Frontal-Delaunay (best quality)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)    # linear elements
            gmsh.option.setNumber("Mesh.SaveAll", 0)

            gmsh.model.mesh.generate(2)  # surface mesh only

            # Extract nodes and triangles
            node_tags, coords, _ = gmsh.model.mesh.getNodes()
            coords = np.array(coords).reshape(-1, 3)
            # Build tag → 0-based index map
            tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

            elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=2)

            all_tris: list[np.ndarray] = []
            for etype, etags, entags in zip(elem_types, elem_tags, elem_node_tags):
                if etype == 2:   # 3-node triangle
                    nodes_per = 3
                elif etype == 3: # 4-node quad — split into 2 tris
                    nodes_per = 4
                else:
                    continue
                n_elems = len(etags)
                conn = np.array(entags, dtype=np.int64).reshape(n_elems, nodes_per)
                if nodes_per == 3:
                    tris = np.vectorize(tag_to_idx.get)(conn).astype(np.int32)
                    all_tris.append(tris)
                else:  # quad → 2 tris
                    t1 = np.stack([conn[:, 0], conn[:, 1], conn[:, 2]], axis=1)
                    t2 = np.stack([conn[:, 0], conn[:, 2], conn[:, 3]], axis=1)
                    for t in (t1, t2):
                        all_tris.append(
                            np.vectorize(tag_to_idx.get)(t).astype(np.int32)
                        )
        finally:
            gmsh.finalize()

        if not all_tris:
            raise RuntimeError(
                f"gmsh produced no triangles for {self.crack_path}. "
                "Check the geometry file."
            )

        tris_arr = np.vstack(all_tris)
        # Remove degenerate triangles
        valid = np.array([len(set(row)) == 3 for row in tris_arr])
        tris_arr = tris_arr[valid]

        return coords, tris_arr

    def _load_stl(self) -> tuple[np.ndarray, np.ndarray]:
        """Load an ASCII or binary STL file into vertices + triangles."""
        try:
            import numpy as np
            # Try scipy if available (fastest)
            # Fall back to manual parser
            return _parse_stl(self.crack_path)
        except Exception as exc:
            raise RuntimeError(f"Failed to load STL {self.crack_path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Private — topology helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _enforce_consistent_normals(
        verts: np.ndarray,
        tris: np.ndarray,
    ) -> np.ndarray:
        """
        Ensure all triangle normals point in the same half-space.

        Uses BFS over the triangle adjacency graph.  For each unvisited
        triangle, if its normal opposes the seed triangle's normal, flip
        the winding order (swap nodes[1] ↔ nodes[2]).
        """
        tris = tris.copy()
        n = len(tris)
        if n == 0:
            return tris

        adj = _build_adjacency(tris)
        visited = np.zeros(n, dtype=bool)

        # Seed: first non-degenerate triangle
        seed = 0
        for s in range(n):
            if _triangle_normal(verts, tris[s]) is not None:
                seed = s
                break

        n_seed = _triangle_normal(verts, tris[seed])
        if n_seed is None:
            return tris  # all degenerate — nothing to do

        queue = [seed]
        visited[seed] = True

        while queue:
            t = queue.pop()
            n_t = _triangle_normal(verts, tris[t])
            if n_t is None:
                continue
            for t2 in adj.get(t, []):
                if visited[t2]:
                    continue
                n_t2 = _triangle_normal(verts, tris[t2])
                if n_t2 is not None and np.dot(n_t, n_t2) < 0:
                    tris[t2, 1], tris[t2, 2] = tris[t2, 2], tris[t2, 1]
                visited[t2] = True
                queue.append(t2)

        return tris

    def _orient_toward_hint(
        self,
        verts: np.ndarray,
        tris: np.ndarray,
    ) -> np.ndarray:
        """
        If normal_hint is provided, flip all normals that oppose the hint.
        Called AFTER _enforce_consistent_normals so all normals are already
        mutually consistent — this just sets the global sign.
        """
        if self.normal_hint is None:
            return tris

        hint = self.normal_hint / (np.linalg.norm(self.normal_hint) + 1e-300)

        # Average normal
        avg_n = np.zeros(3)
        for tri in tris:
            n = _triangle_normal(verts, tri)
            if n is not None:
                avg_n += n
        if np.linalg.norm(avg_n) < 1e-12:
            return tris

        if np.dot(avg_n, hint) < 0:
            # Flip all triangles
            tris = tris.copy()
            tris[:, 1], tris[:, 2] = tris[:, 2].copy(), tris[:, 1].copy()

        return tris

    @staticmethod
    def _find_crack_front(tris: np.ndarray) -> list[int]:
        """
        Return an ordered chain of vertex indices that form the crack front.

        The crack front = free edges (edges shared by exactly one triangle).
        The chain is sorted spatially by nearest-neighbour traversal.
        """
        return _find_and_chain_front(tris)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _triangle_normal(verts: np.ndarray, tri: np.ndarray) -> np.ndarray | None:
    """Return unit normal of a triangle, or None if degenerate."""
    v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
    n = np.cross(v1 - v0, v2 - v0)
    mag = np.linalg.norm(n)
    if mag < 1e-300:
        return None
    return n / mag


def _build_adjacency(tris: np.ndarray) -> dict[int, list[int]]:
    """Map triangle index → list of triangle indices sharing an edge."""
    edge_to_tris: dict[tuple[int, int], list[int]] = {}
    for t_idx, tri in enumerate(tris):
        for i in range(3):
            e = (min(tri[i], tri[(i + 1) % 3]), max(tri[i], tri[(i + 1) % 3]))
            edge_to_tris.setdefault(e, []).append(t_idx)

    adj: dict[int, list[int]] = {}
    for neighbors in edge_to_tris.values():
        if len(neighbors) == 2:
            a, b = neighbors
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
    return adj


def _find_and_chain_front(tris: np.ndarray) -> list[int]:
    """
    Find free edges (edges shared by exactly one triangle) and return
    their nodes as a spatially ordered chain.

    Returns a list of 0-based vertex indices (the chain).
    The chain is OPEN (first ≠ last) since the crack front is an open curve,
    not a closed loop.  For a closed crack (embedded penny crack), the chain
    will be a closed loop.
    """
    edge_count: dict[tuple[int, int], int] = {}
    for tri in tris:
        for i in range(3):
            e = (min(tri[i], tri[(i + 1) % 3]), max(tri[i], tri[(i + 1) % 3]))
            edge_count[e] = edge_count.get(e, 0) + 1

    free_edges = [e for e, c in edge_count.items() if c == 1]
    if not free_edges:
        return []

    return _chain_edges(free_edges)


def _chain_edges(edges: list[tuple[int, int]]) -> list[int]:
    """
    Convert an unordered list of edges into an ordered node chain.

    Builds an adjacency list, then walks from an endpoint (degree-1 node)
    or any node if the front is a closed loop.
    """
    from collections import defaultdict
    adj: dict[int, list[int]] = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)

    # Find a starting node: prefer degree-1 (open chain endpoint)
    start = next(
        (n for n, nbrs in adj.items() if len(nbrs) == 1),
        next(iter(adj)),  # fallback: any node (closed loop)
    )

    chain: list[int] = [start]
    prev = -1
    current = start
    while True:
        nbrs = [n for n in adj[current] if n != prev]
        if not nbrs:
            break
        nxt = nbrs[0]
        if nxt == chain[0] and len(chain) > 2:
            break  # closed loop
        chain.append(nxt)
        prev, current = current, nxt

    return chain


def _read_occ_shape(path: str):
    """Load a B-rep or STEP/IGES file into an OCC TopoDS_Shape.

    Dispatches on file extension:
      .brep / .brp  — native OCC B-Rep format
      .step / .stp  — STEP AP203/214
      .iges / .igs  — IGES
    """
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    if ext in ("brep", "brp"):
        from OCC.Core.BRep import BRep_Builder
        from OCC.Core.BRepTools import breptools
        from OCC.Core.TopoDS import TopoDS_Shape
        builder = BRep_Builder()
        shape = TopoDS_Shape()
        breptools.Read(shape, path, builder)
        return shape

    if ext in ("step", "stp"):
        from OCC.Core.STEPControl import STEPControl_Reader
        from OCC.Core.IFSelect import IFSelect_RetDone
        reader = STEPControl_Reader()
        if reader.ReadFile(path) != IFSelect_RetDone:
            raise RuntimeError(f"STEP reader failed for '{path}'")
        reader.TransferRoots()
        return reader.OneShape()

    if ext in ("iges", "igs"):
        from OCC.Core.IGESControl import IGESControl_Reader
        from OCC.Core.IFSelect import IFSelect_RetDone
        reader = IGESControl_Reader()
        if reader.ReadFile(path) != IFSelect_RetDone:
            raise RuntimeError(f"IGES reader failed for '{path}'")
        reader.TransferRoots()
        return reader.OneShape()

    raise ValueError(
        f"Unsupported geometry format '{ext}' for '{path}'. "
        "Supported: .brep, .brp, .step, .stp, .iges, .igs"
    )


def _merge_close_vertices(
    verts: np.ndarray,
    tris: np.ndarray,
    tol: float = 1e-8,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Merge vertices that are closer than `tol` to eliminate seams between
    B-rep faces.  Returns (new_verts, new_tris) with 0-based indexing.
    """
    from scipy.spatial import cKDTree
    tree = cKDTree(verts)
    pairs = tree.query_pairs(tol)

    # Union-find to group close vertices
    parent = list(range(len(verts)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for a, b in pairs:
        union(a, b)

    # Build canonical index mapping
    roots = [find(i) for i in range(len(verts))]
    unique_roots = sorted(set(roots))
    root_to_new = {r: i for i, r in enumerate(unique_roots)}
    new_verts = verts[unique_roots]
    new_tris = np.array(
        [[root_to_new[roots[n]] for n in tri] for tri in tris],
        dtype=np.int32,
    )

    # Remove degenerate triangles (two or more identical vertices after merge)
    valid = np.array([len(set(tri)) == 3 for tri in new_tris])
    new_tris = new_tris[valid]

    return new_verts, new_tris


def _parse_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """
    Parse an ASCII or binary STL file.
    Returns (vertices, triangles) where triangles reference deduplicated vertices.
    """
    # Try binary STL first (most common)
    try:
        with open(path, "rb") as f:
            header = f.read(80)
            n_tris = int.from_bytes(f.read(4), "little")
            raw = np.frombuffer(
                f.read(n_tris * 50), dtype=np.dtype([
                    ("normal", "<f4", 3),
                    ("v0",     "<f4", 3),
                    ("v1",     "<f4", 3),
                    ("v2",     "<f4", 3),
                    ("attr",   "<u2"),
                ])
            )
        verts_flat = np.vstack([raw["v0"], raw["v1"], raw["v2"]]).astype(float)
        tris_flat  = np.arange(len(verts_flat), dtype=np.int32).reshape(-1, 3)
        # note: verts_flat rows are: [tri0_v0, tri1_v0, ... tri0_v1, tri1_v1, ...]
        # reorder to [tri0_v0, tri0_v1, tri0_v2, tri1_v0, ...]
        T = n_tris
        verts_ordered = np.empty((T * 3, 3))
        verts_ordered[0::3] = raw["v0"]
        verts_ordered[1::3] = raw["v1"]
        verts_ordered[2::3] = raw["v2"]
        tris_ordered = np.arange(T * 3, dtype=np.int32).reshape(T, 3)
        return _merge_close_vertices(verts_ordered.astype(float), tris_ordered)
    except Exception:
        pass

    # ASCII STL
    verts_list: list[np.ndarray] = []
    tris_list:  list[list[int]]  = []
    with open(path, "r") as f:
        content = f.read()

    import re
    vertex_re = re.compile(r"vertex\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)")
    idx = 0
    for m in re.finditer(r"facet normal.*?endfacet", content, re.DOTALL):
        vertices_in_facet = vertex_re.findall(m.group())
        if len(vertices_in_facet) == 3:
            base = len(verts_list)
            for vxyz in vertices_in_facet:
                verts_list.append(np.array([float(c) for c in vxyz]))
            tris_list.append([base, base + 1, base + 2])
        idx += 1

    if not verts_list:
        raise RuntimeError(f"No facets found in STL: {path}")

    return _merge_close_vertices(
        np.array(verts_list, dtype=float),
        np.array(tris_list,  dtype=np.int32),
    )


def _write_id_list(fh, ids: list[int], per_line: int = 16) -> None:
    """Write a comma-separated ID list with `per_line` values per line."""
    for start in range(0, len(ids), per_line):
        chunk = ids[start: start + per_line]
        fh.write(", ".join(str(i) for i in chunk) + "\n")
