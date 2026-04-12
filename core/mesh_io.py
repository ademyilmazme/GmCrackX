from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Node:
    id: int
    x: float
    y: float
    z: float

    def coords(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class Element:
    id: int
    etype: str          # "C3D4", "C3D10", "C3D8", "C3D20", etc.
    nodes: list[int]


@dataclass
class MeshData:
    nodes:        dict[int, Node]    = field(default_factory=dict)
    elements:     dict[int, Element] = field(default_factory=dict)
    node_sets:    dict[str, list[int]] = field(default_factory=dict)
    element_sets: dict[str, list[int]] = field(default_factory=dict)
    # Boundary conditions: {set_name: [(dof, value), ...]}
    boundaries:   dict[str, list[tuple[int, float]]] = field(default_factory=dict)
    # Concentrated loads: {set_name: [(dof, magnitude), ...]}
    cloads:       dict[str, list[tuple[int, float]]] = field(default_factory=dict)
    # Material blocks: {name: {key: value}}
    materials:    dict[str, dict] = field(default_factory=dict)

    # CalculiX element type → number of nodes
    ETYPE_NODES: dict[str, int] = field(default_factory=lambda: {
        "C3D4":   4,
        "C3D4R":  4,
        "C3D10":  10,
        "C3D8":   8,
        "C3D8R":  8,
        "C3D20":  20,
        "C3D20R": 20,
        "C3D6":   6,
        "C3D15":  15,
        "TRI3":   3,
        "TRI6":   6,
        "S3":     3,
        "S6":     6,
        "S4":     4,
        "S8":     8,
    })

    def node_count(self) -> int:
        return len(self.nodes)

    def element_count(self) -> int:
        return len(self.elements)

    def node_coords_array(self):
        """Return (N, 3) numpy array of node coordinates, ordered by node id."""
        import numpy as np
        ids = sorted(self.nodes)
        return np.array([[self.nodes[i].x, self.nodes[i].y, self.nodes[i].z] for i in ids])

    def write_vtk(self, path: str):
        """Write mesh to VTK legacy ASCII format for visualisation."""
        import numpy as np

        # CalculiX etype → VTK cell type
        VTK_TYPE = {
            "C3D4":  10,  # tetra
            "C3D10": 24,  # quadratic tetra
            "C3D8":  12,  # hex
            "C3D20": 25,  # quadratic hex
            "C3D6":  13,  # wedge
            "C3D15": 26,  # quadratic wedge
        }

        node_ids = sorted(self.nodes)
        id_to_idx = {nid: idx for idx, nid in enumerate(node_ids)}

        with open(path, "w") as f:
            f.write("# vtk DataFile Version 3.0\n")
            f.write("Crack3D mesh\n")
            f.write("ASCII\n")
            f.write("DATASET UNSTRUCTURED_GRID\n")

            f.write(f"POINTS {len(node_ids)} float\n")
            for nid in node_ids:
                n = self.nodes[nid]
                f.write(f"{n.x} {n.y} {n.z}\n")

            valid = {eid: el for eid, el in self.elements.items()
                     if el.etype in VTK_TYPE}
            total_size = sum(1 + len(el.nodes) for el in valid.values())
            f.write(f"\nCELLS {len(valid)} {total_size}\n")
            for el in valid.values():
                idx_list = [id_to_idx[n] for n in el.nodes]
                f.write(f"{len(idx_list)} " + " ".join(map(str, idx_list)) + "\n")

            f.write(f"\nCELL_TYPES {len(valid)}\n")
            for el in valid.values():
                f.write(f"{VTK_TYPE[el.etype]}\n")

    def write_msh(self, path: str):
        """Write mesh to Gmsh .msh v2 ASCII format."""
        # Gmsh element type codes
        MSH_TYPE = {
            "C3D4":  4,   # 4-node tet
            "C3D10": 11,  # 10-node tet
            "C3D8":  5,   # 8-node hex
            "C3D20": 17,  # 20-node hex
            "C3D6":  6,   # 6-node prism
            "C3D15": 18,  # 15-node prism
        }

        node_ids = sorted(self.nodes)

        with open(path, "w") as f:
            f.write("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n")

            f.write(f"$Nodes\n{len(node_ids)}\n")
            for nid in node_ids:
                n = self.nodes[nid]
                f.write(f"{nid} {n.x} {n.y} {n.z}\n")
            f.write("$EndNodes\n")

            valid = [(eid, el) for eid, el in self.elements.items()
                     if el.etype in MSH_TYPE]
            f.write(f"$Elements\n{len(valid)}\n")
            for eid, el in valid:
                mtype = MSH_TYPE[el.etype]
                nodes_str = " ".join(map(str, el.nodes))
                f.write(f"{eid} {mtype} 0 {nodes_str}\n")
            f.write("$EndElements\n")
