"""
Tests for KEQ block parsing in crack_io.frd_reader.

Uses synthetic KEQ FRD data (no real CalculiX *CRACK PROPAGATION output needed).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest

from crack_io.frd_reader import KEQIncrement, KEQ_FIELDS, read_keq_results, read_frd


# ---------------------------------------------------------------------------
# Helper — write synthetic KEQ FRD
# ---------------------------------------------------------------------------


# Component names as CalculiX writes them in -5 headers (CT3D-MIS block)
_ALL_COMP_NAMES = [
    "DOM_STEP", "DeltaKEQ", "KEQMIN", "KEQMAX",
    "K1WORST", "K2WORST", "K3WORST", "PHI(DEG)",
    "R", "DADN", "KTH", "INC", "CYCLES", "CRLENGTH", "DOM_SLIP",
]

# Map from CalculiX component header name → canonical KEQ_FIELDS name
_COMP_TO_CANON = {
    "DOM_STEP": "DOM_STEP", "DeltaKEQ": "DELTAKEQ", "KEQMIN": "KEQMIN",
    "KEQMAX": "KEQMAX", "K1WORST": "K1WORST", "K2WORST": "K2WORST",
    "K3WORST": "K3WORST", "PHI(DEG)": "PHI", "R": "R", "DADN": "DADN",
    "KTH": "KTH", "INC": "INC", "CYCLES": "CYCLES", "CRLENGTH": "CRLENGTH",
    "DOM_SLIP": "DOM_SLIP",
}


def _write_keq_frd(
    path: str,
    increments: list[dict],
) -> None:
    """
    Write a minimal FRD file that mimics real CalculiX *CRACK PROPAGATION
    KEQ output (single CT3D-MIS block with 15 components per increment).

    Each entry in `increments` is a dict:
        {"step": int, "inc": int, "time": float,
         "nodes": {nid: {field_name: value, ...}, ...}}
    """
    ncomps = len(_ALL_COMP_NAMES)

    with open(path, "w") as f:
        f.write("    1C\n")

        for inc_data in increments:
            step  = inc_data["step"]
            inc   = inc_data["inc"]
            time  = inc_data.get("time", 0.0)
            nodes = inc_data["nodes"]

            # Increment header
            f.write(f"    1PSTEP {step} {inc} {time:.6e}\n")

            # Single multi-component block (CT3D-MIS with 15 components)
            f.write(f" -4  CT3D-MIS   {ncomps:2d}    1\n")

            # Component header lines (-5)
            for cname in _ALL_COMP_NAMES:
                f.write(f" -5  {cname:12s}    1    1    0    0\n")

            # Node data: 6 values per -1/-2 line
            for nid in sorted(nodes.keys()):
                ndata = nodes[nid]
                vals = []
                for cname in _ALL_COMP_NAMES:
                    canon = _COMP_TO_CANON[cname]
                    vals.append(ndata.get(canon, 0.0))

                # First line: " -1  <nid>  v1 v2 v3 v4 v5 v6"
                chunk = vals[:6]
                f.write(f" -1{nid:>10d}")
                for v in chunk:
                    f.write(f"{v:>12.5e}")
                f.write("\n")

                # Continuation lines: " -2  <padding>  v7 v8 ..."
                pos = 6
                while pos < len(vals):
                    chunk = vals[pos:pos + 6]
                    f.write(" -2          ")
                    for v in chunk:
                        f.write(f"{v:>12.5e}")
                    f.write("\n")
                    pos += 6

            # Block end
            f.write(" -3\n")

        f.write("9999\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEmptyFRD:
    def test_empty_file(self, tmp_path):
        frd = tmp_path / "empty.frd"
        frd.write_text("    1C\n9999\n")
        result = read_keq_results(str(frd))
        assert result == []

    def test_no_keq_blocks(self, tmp_path):
        """FRD with only DISP blocks → empty KEQ result."""
        frd = tmp_path / "disp_only.frd"
        with open(frd, "w") as f:
            f.write("    1C\n")
            f.write("    1PSTEP 1 1 1.000000e+00\n")
            f.write(" -4  DISP        3    1\n")
            f.write(" -5          D1          1    2    1    0\n")
            f.write(" -5          D2          1    2    2    0\n")
            f.write(" -5          D3          1    2    3    0\n")
            f.write(" -1         1  1.00000e-03  2.00000e-03  3.00000e-03\n")
            f.write(" -3\n")
            f.write("9999\n")

        result = read_keq_results(str(frd))
        assert result == []


class TestSingleIncrement:
    def test_single_node_all_fields(self, tmp_path):
        """One increment, one node, all KEQ fields."""
        frd_path = str(tmp_path / "single.frd")
        _write_keq_frd(frd_path, [{
            "step": 1, "inc": 1, "time": 1.0,
            "nodes": {
                100: {
                    "DELTAKEQ":  500.0,
                    "KEQMIN":    200.0,
                    "KEQMAX":    700.0,
                    "K1WORST":   650.0,
                    "K2WORST":   50.0,
                    "K3WORST":   10.0,
                    "PHI":       5.3,
                    "DADN":      1.2e-5,
                    "INC":       1.0,
                    "CYCLES":    1000.0,
                    "CRLENGTH":  3.5,
                },
            },
        }])

        result = read_keq_results(frd_path)
        assert len(result) == 1

        inc = result[0]
        assert inc.step == 1
        assert inc.increment == 1
        assert 100 in inc.keq_data
        assert inc.keq_data[100]["DELTAKEQ"] == pytest.approx(500.0, rel=1e-4)
        assert inc.keq_data[100]["KEQMAX"] == pytest.approx(700.0, rel=1e-4)
        assert inc.keq_data[100]["DADN"] == pytest.approx(1.2e-5, rel=1e-4)
        assert inc.keq_data[100]["CRLENGTH"] == pytest.approx(3.5, rel=1e-4)

    def test_node_ids_property(self, tmp_path):
        frd_path = str(tmp_path / "nids.frd")
        _write_keq_frd(frd_path, [{
            "step": 1, "inc": 1, "time": 0.0,
            "nodes": {
                10: {"DELTAKEQ": 1.0},
                5:  {"DELTAKEQ": 2.0},
                20: {"DELTAKEQ": 3.0},
            },
        }])

        result = read_keq_results(frd_path)
        assert result[0].node_ids == [5, 10, 20]  # sorted

    def test_get_field_array(self, tmp_path):
        frd_path = str(tmp_path / "arr.frd")
        _write_keq_frd(frd_path, [{
            "step": 1, "inc": 1, "time": 0.0,
            "nodes": {
                1: {"DELTAKEQ": 100.0, "K1WORST": 90.0},
                2: {"DELTAKEQ": 200.0, "K1WORST": 180.0},
                3: {"DELTAKEQ": 300.0, "K1WORST": 270.0},
            },
        }])

        inc = read_keq_results(frd_path)[0]
        nids, vals = inc.get_field_array("DELTAKEQ")
        assert list(nids) == [1, 2, 3]
        np.testing.assert_allclose(vals, [100.0, 200.0, 300.0], rtol=1e-4)


class TestMultipleIncrements:
    def test_three_increments(self, tmp_path):
        frd_path = str(tmp_path / "multi.frd")
        _write_keq_frd(frd_path, [
            {"step": 1, "inc": 1, "time": 1.0,
             "nodes": {1: {"DELTAKEQ": 100.0, "CRLENGTH": 1.0}}},
            {"step": 1, "inc": 2, "time": 2.0,
             "nodes": {1: {"DELTAKEQ": 150.0, "CRLENGTH": 1.5}}},
            {"step": 1, "inc": 3, "time": 3.0,
             "nodes": {1: {"DELTAKEQ": 200.0, "CRLENGTH": 2.0}}},
        ])

        result = read_keq_results(frd_path)
        assert len(result) == 3
        assert result[0].increment == 1
        assert result[1].increment == 2
        assert result[2].increment == 3
        assert result[2].keq_data[1]["CRLENGTH"] == pytest.approx(2.0, rel=1e-4)

    def test_increments_sorted(self, tmp_path):
        frd_path = str(tmp_path / "sorted.frd")
        _write_keq_frd(frd_path, [
            {"step": 1, "inc": 3, "time": 3.0,
             "nodes": {1: {"DELTAKEQ": 300.0}}},
            {"step": 1, "inc": 1, "time": 1.0,
             "nodes": {1: {"DELTAKEQ": 100.0}}},
        ])

        result = read_keq_results(frd_path)
        # Should be sorted by (step, inc)
        assert result[0].increment == 1
        assert result[1].increment == 3


class TestMultipleNodes:
    def test_five_front_nodes(self, tmp_path):
        frd_path = str(tmp_path / "nodes5.frd")
        nodes = {}
        for nid in [10, 20, 30, 40, 50]:
            nodes[nid] = {
                "DELTAKEQ": float(nid) * 10,
                "K1WORST":  float(nid) * 9,
                "DADN":     float(nid) * 1e-6,
                "CYCLES":   1000.0,
                "CRLENGTH": 5.0,
            }
        _write_keq_frd(frd_path, [{"step": 1, "inc": 1, "time": 1.0, "nodes": nodes}])

        result = read_keq_results(frd_path)
        assert len(result) == 1
        inc = result[0]
        assert len(inc.keq_data) == 5
        assert inc.keq_data[30]["DELTAKEQ"] == pytest.approx(300.0, rel=1e-4)
        assert inc.keq_data[50]["DADN"] == pytest.approx(50e-6, rel=1e-4)


class TestMixedBlocks:
    def test_keq_with_disp_blocks(self, tmp_path):
        """KEQ block (CT3D-MIS) mixed with DISP/STRESS should only parse KEQ."""
        ncomps = len(_ALL_COMP_NAMES)
        frd_path = str(tmp_path / "mixed.frd")
        with open(frd_path, "w") as f:
            f.write("    1C\n")
            f.write("    1PSTEP 1 1 1.000000e+00\n")

            # DISP block (should be ignored by read_keq_results)
            f.write(" -4  DISP        3    1\n")
            f.write(" -5          D1          1    2    1    0\n")
            f.write(" -5          D2          1    2    2    0\n")
            f.write(" -5          D3          1    2    3    0\n")
            f.write(" -1         1  1.00000e-03  2.00000e-03  3.00000e-03\n")
            f.write(" -3\n")

            # CT3D-MIS block with KEQ data (DELTAKEQ=500, KEQMAX=700)
            f.write(f" -4  CT3D-MIS   {ncomps:2d}    1\n")
            for cname in _ALL_COMP_NAMES:
                f.write(f" -5  {cname:12s}    1    1    0    0\n")
            # Node 1: DOM_STEP=0, DELTAKEQ=500, KEQMIN=200, KEQMAX=700,
            #          K1-3=0, PHI=0, R=0, DADN=0, KTH=0, INC=1, CYCLES=0,
            #          CRLENGTH=0, DOM_SLIP=0
            f.write(" -1         1  0.00000e+00  5.00000e+02  2.00000e+02  7.00000e+02  0.00000e+00  0.00000e+00\n")
            f.write(" -2            0.00000e+00  0.00000e+00  0.00000e+00  0.00000e+00  1.00000e+00  0.00000e+00\n")
            f.write(" -2            0.00000e+00  0.00000e+00  0.00000e+00\n")
            f.write(" -3\n")

            # STRESS block (should be ignored by read_keq_results)
            f.write(" -4  STRESS      6    1\n")
            f.write(" -5          SXX         1    4    1    1\n")
            f.write(" -5          SYY         1    4    2    0\n")
            f.write(" -5          SZZ         1    4    3    0\n")
            f.write(" -5          SXY         1    4    4    0\n")
            f.write(" -5          SYZ         1    4    5    0\n")
            f.write(" -5          SXZ         1    4    6    0\n")
            f.write(" -1         1  1.00000e+02  5.00000e+01  3.00000e+01  1.00000e+01  5.00000e+00  2.00000e+00\n")
            f.write(" -3\n")

            f.write("9999\n")

        keq_result = read_keq_results(frd_path)
        assert len(keq_result) == 1
        assert keq_result[0].keq_data[1]["DELTAKEQ"] == pytest.approx(500.0, rel=1e-4)
        assert keq_result[0].keq_data[1]["KEQMAX"] == pytest.approx(700.0, rel=1e-4)

        # read_frd should still parse the DISP block separately
        frd_result = read_frd(frd_path)
        assert len(frd_result) == 1
        assert 1 in frd_result[0].displacements


class TestKEQIncrementDataclass:
    def test_get_field_array_missing_field(self, tmp_path):
        """Requesting a field not present in data should return zeros."""
        frd_path = str(tmp_path / "missing.frd")
        _write_keq_frd(frd_path, [{
            "step": 1, "inc": 1, "time": 0.0,
            "nodes": {1: {"DELTAKEQ": 100.0}},
        }])

        inc = read_keq_results(frd_path)[0]
        nids, vals = inc.get_field_array("NONEXISTENT")
        assert len(vals) == 1
        assert vals[0] == 0.0
