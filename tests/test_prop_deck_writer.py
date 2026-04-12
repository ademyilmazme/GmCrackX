"""
Tests for crack_io.prop_deck_writer — CalculiX *CRACK PROPAGATION deck generation.

The deck is built from:
  - FRD 2C/3C sections  → volume mesh  (nodes + elements)
  - crack surface INP   → S3 shell mesh (nodes + elements + CRACK_FRONT nset)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
from pathlib import Path

import pytest

from crack_io.prop_deck_writer import PropDeckWriter
from pipeline.prop_config import PropagationConfig

EXAMPLE_DIR = Path(__file__).parent / "example"
MASTER_FRD  = str(EXAMPLE_DIR / "masterII.frd")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _minimal_crack_inp(tmp_path: Path) -> str:
    """3-node / 1-element S3 INP with a 2-node CRACK_FRONT."""
    p = tmp_path / "crack_surface.inp"
    p.write_text(
        "*NODE\n"
        "1, 0.0, 0.0, 2.0\n"
        "2, 0.5, 0.0, 2.0\n"
        "3, 0.0, 0.1, 2.0\n"
        "*ELEMENT, TYPE=S3, ELSET=CRACK_SURFACE\n"
        "1, 1, 2, 3\n"
        "*NSET, NSET=CRACK_FRONT\n"
        "1, 2,\n"
    )
    return str(p)


def _minimal_frd(tmp_path: Path) -> str:
    """Tiny FRD with 2C node coords and 3C C3D4 elements (4 nodes each)."""
    p = tmp_path / "tiny.frd"
    p.write_text(
        "    1C\n"
        "    2C                             4                                     1\n"
        " -1       100 0.00000E+00 0.00000E+00 0.00000E+00\n"
        " -1       200 1.00000E+00 0.00000E+00 0.00000E+00\n"
        " -1       300 0.00000E+00 1.00000E+00 0.00000E+00\n"
        " -1       400 0.00000E+00 0.00000E+00 1.00000E+00\n"
        "    3C                             1                                     1\n"
        " -1         1    5    0    1\n"
        " -2       100       200       300       400\n"
        "9999\n"
    )
    return str(p)


def _make_config(**overrides) -> PropagationConfig:
    defaults = dict(
        uncracked_frd="dummy.frd",
        initial_crack="dummy.brep",
        paris_constants=(1e-4, 772.86, 3.1, 10.0, 177.09, 10.0, 3162.0, 0.5),
        material_name="CRACK",
        structural_material_name="CT3D_BENCHMARK",
        structural_elastic_E=210000.0,
        structural_elastic_nu=0.3,
        max_da=0.05,
        max_angle=10.0,
        max_increments=50,
        length_type="CUMULATIVE",
        shell_thickness=0.01,
    )
    defaults.update(overrides)
    return PropagationConfig(**defaults)


def _write_deck(tmp_path, frd_path=None, config=None) -> str:
    if config is None:
        config = _make_config()
    if frd_path is None:
        frd_path = _minimal_frd(tmp_path)
    crack_inp = _minimal_crack_inp(tmp_path)
    writer = PropDeckWriter(config, crack_inp, frd_path)
    deck_path = writer.write(str(tmp_path))
    return Path(deck_path).read_text()


# ---------------------------------------------------------------------------
# Keyword presence
# ---------------------------------------------------------------------------

class TestKeywordPresence:
    def test_node_nset_all(self, tmp_path):
        assert "*NODE,NSET=Nall" in _write_deck(tmp_path)

    def test_volume_element_block(self, tmp_path):
        # tiny.frd has 4-node elements → C3D4
        assert "*ELEMENT,TYPE=C3D4,ELSET=Evol" in _write_deck(tmp_path)

    def test_shell_element_block(self, tmp_path):
        assert "*ELEMENT,TYPE=S3,ELSET=Eshell" in _write_deck(tmp_path)

    def test_crack_front_nset(self, tmp_path):
        assert "*NSET,NSET=CRACK_FRONT" in _write_deck(tmp_path)

    def test_structural_material(self, tmp_path):
        assert "*MATERIAL,NAME=CT3D_BENCHMARK" in _write_deck(tmp_path)

    def test_elastic_keyword(self, tmp_path):
        assert "*ELASTIC" in _write_deck(tmp_path)

    def test_crack_material(self, tmp_path):
        assert "*MATERIAL,NAME=CRACK" in _write_deck(tmp_path)

    def test_user_material(self, tmp_path):
        assert "*USER MATERIAL,CONSTANTS=8" in _write_deck(tmp_path)

    def test_user_material_zero_continuation(self, tmp_path):
        """Line after the 8 Paris constants must be '0.'"""
        lines = _write_deck(tmp_path).split("\n")
        um_idx = next(i for i, l in enumerate(lines) if "*USER MATERIAL" in l)
        assert lines[um_idx + 2].strip() == "0."

    def test_solid_section(self, tmp_path):
        content = _write_deck(tmp_path)
        assert "*SOLID SECTION,ELSET=Evol,MATERIAL=CT3D_BENCHMARK" in content

    def test_shell_section(self, tmp_path):
        content = _write_deck(tmp_path)
        assert "*SHELL SECTION,ELSET=Eshell,MATERIAL=CT3D_BENCHMARK" in content

    def test_step_keyword(self, tmp_path):
        assert "*STEP,INC=" in _write_deck(tmp_path)

    def test_crack_propagation_keyword(self, tmp_path):
        assert "*CRACK PROPAGATION," in _write_deck(tmp_path)

    def test_node_file_keq_two_lines(self, tmp_path):
        lines = _write_deck(tmp_path).split("\n")
        nf = next(i for i, l in enumerate(lines) if "*NODE FILE" in l)
        assert lines[nf + 1].strip() == "KEQ"

    def test_end_step(self, tmp_path):
        assert "*END STEP" in _write_deck(tmp_path)


# ---------------------------------------------------------------------------
# Node and element data from FRD
# ---------------------------------------------------------------------------

class TestMeshFromFrd:
    def test_volume_nodes_written(self, tmp_path):
        """FRD nodes 100-400 must appear in the *NODE block."""
        content = _write_deck(tmp_path)
        for nid in (100, 200, 300, 400):
            assert str(nid) in content

    def test_crack_surface_nodes_offset(self, tmp_path):
        """Crack surface node 1 must be written as 401 (max_frd_nid=400 + 1)."""
        lines = _write_deck(tmp_path).split("\n")
        ns_idx = next(i for i, l in enumerate(lines) if "*NODE,NSET=Nall" in l)
        # Last node in the *NODE block belongs to crack surface
        node_ids_in_block = []
        for l in lines[ns_idx + 1:]:
            if l.startswith("*") or not l.strip():
                break
            try:
                node_ids_in_block.append(int(l.split(",")[0].strip()))
            except ValueError:
                pass
        assert 401 in node_ids_in_block, f"Expected 401 in {node_ids_in_block}"

    def test_volume_element_present(self, tmp_path):
        """Element 1 from tiny.frd must appear under *ELEMENT,TYPE=C3D4."""
        content = _write_deck(tmp_path)
        lines = content.split("\n")
        el_idx = next(i for i, l in enumerate(lines) if "ELSET=Evol" in l)
        eid = int(lines[el_idx + 1].split(",")[0].strip())
        assert eid == 1

    def test_c3d20_element_format_real_frd(self, tmp_path):
        """masterII.frd has C3D20 elements — must appear in deck."""
        content = _write_deck(tmp_path, frd_path=MASTER_FRD)
        assert "*ELEMENT,TYPE=C3D20,ELSET=Evol" in content

    def test_node_count_real_frd(self, tmp_path):
        """masterII.frd has 10017 volume nodes — all must be in *NODE block."""
        content = _write_deck(tmp_path, frd_path=MASTER_FRD)
        lines = content.split("\n")
        ns_idx = next(i for i, l in enumerate(lines) if "*NODE,NSET=Nall" in l)
        vol_count = 0
        for l in lines[ns_idx + 1:]:
            if l.startswith("*") or not l.strip():
                break
            vol_count += 1
        # 10017 volume + 3 crack surface = 10020 total
        assert vol_count == 10017 + 3


# ---------------------------------------------------------------------------
# Parameter values
# ---------------------------------------------------------------------------

class TestParameterValues:
    def test_material_name(self, tmp_path):
        cfg = _make_config(material_name="MY_MAT")
        content = _write_deck(tmp_path, config=cfg)
        assert "*MATERIAL,NAME=MY_MAT" in content
        assert "MATERIAL=MY_MAT," in content

    def test_structural_material_name(self, tmp_path):
        cfg = _make_config(structural_material_name="STEEL")
        content = _write_deck(tmp_path, config=cfg)
        assert "*MATERIAL,NAME=STEEL" in content
        assert "MATERIAL=STEEL" in content

    def test_elastic_values(self, tmp_path):
        cfg = _make_config(structural_elastic_E=200000., structural_elastic_nu=0.28)
        lines = _write_deck(tmp_path, config=cfg).split("\n")
        el_idx = next(i for i, l in enumerate(lines) if l.strip() == "*ELASTIC")
        data = lines[el_idx + 1]
        assert "200000" in data and "0.28" in data

    def test_frd_path_in_input(self, tmp_path):
        frd = _minimal_frd(tmp_path)
        content = _write_deck(tmp_path, frd_path=frd)
        # Relative path used — just check the filename appears
        assert "tiny.frd" in content

    def test_length_type(self, tmp_path):
        cfg = _make_config(length_type="INTERSECTION")
        assert "LENGTH=INTERSECTION" in _write_deck(tmp_path, config=cfg)

    def test_max_increments(self, tmp_path):
        cfg = _make_config(max_increments=10)
        assert "*STEP,INC=10" in _write_deck(tmp_path, config=cfg)

    def test_da_angle_line(self, tmp_path):
        """Data line after *CRACK PROPAGATION: max_da,max_angle."""
        cfg = _make_config(max_da=0.05, max_angle=10.0)
        lines = _write_deck(tmp_path, config=cfg).split("\n")
        cp = next(i for i, l in enumerate(lines) if "*CRACK PROPAGATION" in l)
        data = lines[cp + 1]
        assert "0.05" in data and "10" in data

    def test_shell_thickness(self, tmp_path):
        cfg = _make_config(shell_thickness=0.025)
        lines = _write_deck(tmp_path, config=cfg).split("\n")
        ss = next(i for i, l in enumerate(lines) if "*SHELL SECTION" in l)
        assert "0.025" in lines[ss + 1]

    def test_paris_first_constant(self, tmp_path):
        cfg = _make_config(paris_constants=(3e-5, 500., 2.5, 8., 150., 8., 2000., 0.3))
        assert "3.0000E-05" in _write_deck(tmp_path, config=cfg).upper()


# ---------------------------------------------------------------------------
# Deck structure and ordering
# ---------------------------------------------------------------------------

class TestDeckStructure:
    def test_keyword_order(self, tmp_path):
        content = _write_deck(tmp_path)
        lines = content.split("\n")
        ordered = [
            "*NODE,NSET=Nall",
            "*ELEMENT,TYPE=C3D4,ELSET=Evol",
            "*ELEMENT,TYPE=S3,ELSET=Eshell",
            "*ELASTIC",
            "*USER MATERIAL",
            "*SOLID SECTION",
            "*SHELL SECTION",
            "*STEP,INC=",
            "*CRACK PROPAGATION",
            "*NODE FILE",
            "*END STEP",
        ]
        positions = []
        for kw in ordered:
            pos = next((i for i, l in enumerate(lines) if kw in l), None)
            assert pos is not None, f"'{kw}' not found in deck"
            positions.append(pos)
        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1], (
                f"'{ordered[i]}' (line {positions[i]}) must precede "
                f"'{ordered[i+1]}' (line {positions[i+1]})"
            )

    def test_matches_crackIIcum_structure(self, tmp_path):
        """Deck must structurally match crackIIcum.inp (the CalculiX reference)."""
        cfg = _make_config(
            paris_constants=(1e-4, 772.86, 3.1, 10., 177.09, 10., 3162., 0.5),
            max_da=0.05, max_angle=10.0, max_increments=10,
            length_type="CUMULATIVE", material_name="CRACK",
            structural_material_name="CT3D_BENCHMARK",
        )
        content = _write_deck(tmp_path, frd_path=MASTER_FRD, config=cfg)
        lines = content.split("\n")

        assert "*ELEMENT,TYPE=C3D20,ELSET=Evol" in content   # ref: line 10159
        assert "*ELEMENT,TYPE=S3,ELSET=Eshell" in content    # ref: line 10078
        assert "*MATERIAL,NAME=CT3D_BENCHMARK" in content    # ref: line 14485
        assert "*MATERIAL,NAME=CRACK" in content             # ref: line 14498
        assert "*USER MATERIAL,CONSTANTS=8" in content       # ref: line 14499
        um_idx = next(i for i, l in enumerate(lines) if "*USER MATERIAL" in l)
        assert lines[um_idx + 2].strip() == "0."             # ref: line 14501
        assert "*SOLID SECTION,ELSET=Evol" in content        # ref: line 14502
        assert "*SHELL SECTION,ELSET=Eshell" in content      # ref: line 14503
        assert "*STEP,INC=10" in content                     # ref: line 14505
        cp = next(i for i, l in enumerate(lines) if "*CRACK PROPAGATION" in l)
        assert "INPUT=" in lines[cp]
        assert "MATERIAL=CRACK" in lines[cp]
        assert "LENGTH=CUMULATIVE" in lines[cp]
        assert "0.05" in lines[cp + 1]                      # ref: line 14507
        nf = next(i for i, l in enumerate(lines) if "*NODE FILE" in l)
        assert lines[nf + 1].strip() == "KEQ"               # ref: line 14509
        assert "*END STEP" in content                        # ref: line 14510

    def test_comment_header(self, tmp_path):
        assert _write_deck(tmp_path).startswith("**")

    def test_file_created(self, tmp_path):
        _write_deck(tmp_path)
        assert (tmp_path / "propagation.inp").exists()

    def test_returns_absolute_path(self, tmp_path):
        frd = _minimal_frd(tmp_path)
        crack = _minimal_crack_inp(tmp_path)
        path = PropDeckWriter(_make_config(), crack, frd).write(str(tmp_path))
        assert os.path.isabs(path)
