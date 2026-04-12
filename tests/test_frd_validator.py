"""
Tests for crack_io.frd_validator — FRD validation rules FRD-0 through FRD-6.

All tests use synthetic FRD files written to tmp dirs (no OCC, no CalculiX).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
import warnings

import numpy as np
import pytest

from crack_io.frd_reader import FrdIncrement
from crack_io.frd_validator import FRDValidator, FRDValidationError
from core.mesh_io import MeshData, Node


# ---------------------------------------------------------------------------
# Helpers — write minimal FRD files
# ---------------------------------------------------------------------------

def _write_frd(path: str, increments: list[FrdIncrement]) -> None:
    """Write a minimal ASCII FRD file from FrdIncrement objects."""
    with open(path, "w") as f:
        for inc in increments:
            f.write(f"    1PSTEP {inc.step} {inc.increment} {inc.total_time:.6e}\n")

            if inc.displacements:
                f.write(" -4  DISP        3    1\n")
                f.write(" -5          D1          1    2    1    0\n")
                f.write(" -5          D2          1    2    2    0\n")
                f.write(" -5          D3          1    2    3    0\n")
                for nid, v in inc.displacements.items():
                    f.write(f" -1{nid:>10d} {v[0]:>12.5e} {v[1]:>12.5e} {v[2]:>12.5e}\n")

            if inc.stresses:
                f.write(" -4  STRESS      6    1\n")
                f.write(" -5          SXX         1    4    1    1\n")
                f.write(" -5          SYY         1    4    2    2\n")
                f.write(" -5          SZZ         1    4    3    3\n")
                f.write(" -5          SXY         1    4    1    2\n")
                f.write(" -5          SYZ         1    4    2    3\n")
                f.write(" -5          SXZ         1    4    1    3\n")
                for nid, s in inc.stresses.items():
                    vals = " ".join(f"{x:>12.5e}" for x in s)
                    f.write(f" -1{nid:>10d} {vals}\n")

        f.write("9999\n")


def _make_stress_dict(n: int, scale: float = 100.0) -> dict[int, np.ndarray]:
    """Create a stress dict for n nodes with plausible von Mises."""
    d = {}
    for i in range(1, n + 1):
        d[i] = np.array([scale, scale * 0.3, scale * 0.1,
                          scale * 0.1, scale * 0.05, scale * 0.02])
    return d


def _make_ref_mesh(n_nodes: int = 100) -> MeshData:
    """Create a reference MeshData with n_nodes at grid positions."""
    mesh = MeshData()
    for i in range(1, n_nodes + 1):
        mesh.nodes[i] = Node(i, float(i), 0.0, 0.0)
    return mesh


# ---------------------------------------------------------------------------
# FRD-0: file readable
# ---------------------------------------------------------------------------

class TestFRD0:
    def test_file_not_found(self):
        v = FRDValidator("/nonexistent/path.frd")
        with pytest.raises(FRDValidationError, match="FRD-0"):
            v.validate()

    def test_empty_file(self, tmp_path):
        frd = tmp_path / "empty.frd"
        frd.write_text("")
        v = FRDValidator(str(frd))
        with pytest.raises(FRDValidationError, match="FRD-0"):
            v.validate()


# ---------------------------------------------------------------------------
# FRD-1: stress block present
# ---------------------------------------------------------------------------

class TestFRD1:
    def test_no_stress_block(self, tmp_path):
        frd_path = str(tmp_path / "no_stress.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.displacements = {1: np.zeros(3)}
        _write_frd(frd_path, [inc])

        v = FRDValidator(frd_path)
        with pytest.raises(FRDValidationError, match="FRD-1"):
            v.validate()


# ---------------------------------------------------------------------------
# FRD-2: finite stresses
# ---------------------------------------------------------------------------

class TestFRD2:
    def test_nan_stress(self, tmp_path):
        frd_path = str(tmp_path / "nan.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = {1: np.array([100., 50., 30., 10., 5., float("nan")])}
        for i in range(2, 10):
            inc.stresses[i] = np.array([100., 50., 30., 10., 5., 2.])
        _write_frd(frd_path, [inc])

        v = FRDValidator(frd_path)
        with pytest.raises(FRDValidationError, match="FRD-2"):
            v.validate()

    def test_inf_stress(self, tmp_path):
        frd_path = str(tmp_path / "inf.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = {1: np.array([float("inf"), 50., 30., 10., 5., 2.])}
        for i in range(2, 10):
            inc.stresses[i] = np.array([100., 50., 30., 10., 5., 2.])
        _write_frd(frd_path, [inc])

        v = FRDValidator(frd_path)
        with pytest.raises(FRDValidationError, match="FRD-2"):
            v.validate()


# ---------------------------------------------------------------------------
# FRD-3: minimum node count
# ---------------------------------------------------------------------------

class TestFRD3:
    def test_too_few_nodes(self, tmp_path):
        frd_path = str(tmp_path / "few.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = {1: np.array([100., 50., 30., 10., 5., 2.])}
        _write_frd(frd_path, [inc])

        v = FRDValidator(frd_path)
        with pytest.raises(FRDValidationError, match="FRD-3"):
            v.validate()


# ---------------------------------------------------------------------------
# FRD-4/5: mesh cross-check
# ---------------------------------------------------------------------------

class TestFRD4_5:
    def test_missing_nodes_hard_fail(self, tmp_path):
        """If >10% of mesh nodes have no stress → hard fail."""
        frd_path = str(tmp_path / "mismatch.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = _make_stress_dict(10)  # nodes 1..10
        _write_frd(frd_path, [inc])

        mesh = _make_ref_mesh(200)  # nodes 1..200 → 190 missing (95%)

        v = FRDValidator(frd_path, reference_mesh=mesh)
        with pytest.raises(FRDValidationError, match="FRD-4"):
            v.validate()

    def test_extra_frd_nodes_warning(self, tmp_path):
        """FRD has nodes not in mesh → soft warning, not failure."""
        frd_path = str(tmp_path / "extra.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = _make_stress_dict(20)  # nodes 1..20
        _write_frd(frd_path, [inc])

        mesh = _make_ref_mesh(10)  # nodes 1..10 → FRD has 10 extra nodes

        v = FRDValidator(frd_path, reference_mesh=mesh)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = v.validate()
        assert result is not None
        frd4_warns = [x for x in w if "FRD-4" in str(x.message)]
        assert len(frd4_warns) >= 1


# ---------------------------------------------------------------------------
# FRD-6: stress scale sanity
# ---------------------------------------------------------------------------

class TestFRD6:
    def test_near_zero_stress_warning(self, tmp_path):
        frd_path = str(tmp_path / "tiny.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = _make_stress_dict(10, scale=1e-6)
        _write_frd(frd_path, [inc])

        v = FRDValidator(frd_path)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = v.validate()
        frd6_warns = [x for x in w if "FRD-6" in str(x.message)]
        assert len(frd6_warns) >= 1

    def test_huge_stress_warning(self, tmp_path):
        frd_path = str(tmp_path / "huge.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = _make_stress_dict(10, scale=1e12)
        _write_frd(frd_path, [inc])

        v = FRDValidator(frd_path)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = v.validate()
        frd6_warns = [x for x in w if "FRD-6" in str(x.message)]
        assert len(frd6_warns) >= 1


# ---------------------------------------------------------------------------
# Happy path: valid FRD passes all rules
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_valid_frd_passes(self, tmp_path):
        frd_path = str(tmp_path / "valid.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = _make_stress_dict(50)
        inc.displacements = {i: np.zeros(3) for i in range(1, 51)}
        _write_frd(frd_path, [inc])

        v = FRDValidator(frd_path)
        result = v.validate()
        assert len(result.stresses) == 50
        assert v.report is not None
        assert v.report.has_stress
        assert v.report.n_nodes == 50

    def test_valid_frd_with_mesh_passes(self, tmp_path):
        frd_path = str(tmp_path / "valid_mesh.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = _make_stress_dict(50)
        _write_frd(frd_path, [inc])

        mesh = _make_ref_mesh(50)

        v = FRDValidator(frd_path, reference_mesh=mesh)
        result = v.validate()
        assert len(result.stresses) == 50

    def test_report_summary(self, tmp_path):
        frd_path = str(tmp_path / "report.frd")
        inc = FrdIncrement(1, 1, 1.0)
        inc.stresses = _make_stress_dict(20)
        _write_frd(frd_path, [inc])

        v = FRDValidator(frd_path)
        v.validate()
        s = v.report.summary()
        assert "20" in s
        assert "stress" in s.lower()
