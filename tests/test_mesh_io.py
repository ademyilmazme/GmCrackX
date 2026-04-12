"""
Tests for core/mesh_io.py, crack_io/inp_parser.py, crack_io/inp_writer.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
import pytest
from core.mesh_io import Node, Element, MeshData
from crack_io.inp_parser import parse_inp
from crack_io.inp_writer import write_inp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def simple_tet_mesh() -> MeshData:
    """Single C3D4 tet with 4 nodes."""
    mesh = MeshData()
    mesh.nodes = {
        1: Node(1, 0.0, 0.0, 0.0),
        2: Node(2, 1.0, 0.0, 0.0),
        3: Node(3, 0.0, 1.0, 0.0),
        4: Node(4, 0.0, 0.0, 1.0),
    }
    mesh.elements = {1: Element(1, "C3D4", [1, 2, 3, 4])}
    mesh.node_sets    = {"NALL": [1, 2, 3, 4]}
    mesh.element_sets = {"EALL": [1]}
    mesh.materials    = {"STEEL": {"E": 210000.0, "nu": 0.3}}
    mesh.boundaries   = {"FIX": [(1, 0.0), (2, 0.0), (3, 0.0)]}
    return mesh


INP_CONTENT = """\
** Mini mesh
*NODE
1, 0.0, 0.0, 0.0
2, 1.0, 0.0, 0.0
3, 0.0, 1.0, 0.0
4, 0.0, 0.0, 1.0
*ELEMENT, TYPE=C3D4, ELSET=EALL
1, 1, 2, 3, 4
*NSET, NSET=BOTTOM
1, 2, 3
*BOUNDARY
BOTTOM, 1, 3, 0.0
*MATERIAL, NAME=STEEL
*ELASTIC
210000.0, 0.3
"""


# ---------------------------------------------------------------------------
# Node / Element tests
# ---------------------------------------------------------------------------

def test_node_coords():
    n = Node(1, 1.0, 2.0, 3.0)
    assert n.coords() == (1.0, 2.0, 3.0)


def test_element_fields():
    el = Element(5, "C3D10", list(range(1, 11)))
    assert el.etype == "C3D10"
    assert len(el.nodes) == 10


def test_meshdata_counts():
    mesh = simple_tet_mesh()
    assert mesh.node_count() == 4
    assert mesh.element_count() == 1


def test_node_coords_array():
    import numpy as np
    mesh = simple_tet_mesh()
    arr  = mesh.node_coords_array()
    assert arr.shape == (4, 3)
    assert arr[0].tolist() == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# inp_parser tests
# ---------------------------------------------------------------------------

def test_parse_inp_nodes():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".inp", delete=False) as f:
        f.write(INP_CONTENT)
        path = f.name
    try:
        mesh = parse_inp(path)
        assert mesh.node_count() == 4
        assert mesh.nodes[2].x == 1.0
    finally:
        os.unlink(path)


def test_parse_inp_elements():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".inp", delete=False) as f:
        f.write(INP_CONTENT)
        path = f.name
    try:
        mesh = parse_inp(path)
        assert mesh.element_count() == 1
        assert mesh.elements[1].etype == "C3D4"
        assert mesh.elements[1].nodes == [1, 2, 3, 4]
    finally:
        os.unlink(path)


def test_parse_inp_nset():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".inp", delete=False) as f:
        f.write(INP_CONTENT)
        path = f.name
    try:
        mesh = parse_inp(path)
        assert "BOTTOM" in mesh.node_sets
        assert set(mesh.node_sets["BOTTOM"]) == {1, 2, 3}
    finally:
        os.unlink(path)


def test_parse_inp_material():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".inp", delete=False) as f:
        f.write(INP_CONTENT)
        path = f.name
    try:
        mesh = parse_inp(path)
        assert "STEEL" in mesh.materials
        assert mesh.materials["STEEL"]["E"]  == pytest.approx(210000.0)
        assert mesh.materials["STEEL"]["nu"] == pytest.approx(0.3)
    finally:
        os.unlink(path)


def test_parse_inp_boundary():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".inp", delete=False) as f:
        f.write(INP_CONTENT)
        path = f.name
    try:
        mesh = parse_inp(path)
        assert "BOTTOM" in mesh.boundaries
        # DOFs 1, 2, 3 all fixed at 0
        dofs = [d for d, v in mesh.boundaries["BOTTOM"]]
        assert sorted(dofs) == [1, 2, 3]
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# inp_writer / round-trip tests
# ---------------------------------------------------------------------------

def test_write_inp_roundtrip():
    mesh  = simple_tet_mesh()
    with tempfile.NamedTemporaryFile(suffix=".inp", delete=False) as f:
        path = f.name
    try:
        write_inp(mesh, path)
        mesh2 = parse_inp(path)
        assert mesh2.node_count()    == mesh.node_count()
        assert mesh2.element_count() == mesh.element_count()
        assert mesh2.nodes[1].x     == pytest.approx(0.0)
        assert mesh2.nodes[2].x     == pytest.approx(1.0)
        assert mesh2.elements[1].etype == "C3D4"
    finally:
        os.unlink(path)


def test_write_inp_material_roundtrip():
    mesh = simple_tet_mesh()
    with tempfile.NamedTemporaryFile(suffix=".inp", delete=False) as f:
        path = f.name
    try:
        write_inp(mesh, path)
        mesh2 = parse_inp(path)
        assert "STEEL" in mesh2.materials
        assert mesh2.materials["STEEL"]["E"] == pytest.approx(210000.0)
    finally:
        os.unlink(path)


def test_write_vtk():
    import numpy as np
    mesh = simple_tet_mesh()
    with tempfile.NamedTemporaryFile(suffix=".vtk", delete=False) as f:
        path = f.name
    try:
        mesh.write_vtk(path)
        content = open(path).read()
        assert "POINTS 4" in content
        assert "CELLS 1" in content
    finally:
        os.unlink(path)


def test_write_msh():
    mesh = simple_tet_mesh()
    with tempfile.NamedTemporaryFile(suffix=".msh", delete=False) as f:
        path = f.name
    try:
        mesh.write_msh(path)
        content = open(path).read()
        assert "$MeshFormat" in content
        assert "$Nodes" in content
        assert "$Elements" in content
    finally:
        os.unlink(path)
