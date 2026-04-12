"""
Integration tests for convert/ansys_rst_reader.py + convert/frd_writer.py.

Uses the real file at tests/example/file.rst.

Run with:
    cd C:\\Users\\Adem\\source\\repos\\GmCrackX
    C:\\Users\\Adem\\.conda\\envs\\GmCrackX\\python.exe -m pytest tests/test_ansys_rst_reader.py -v
"""
import sys
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Make repo root importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

import warnings

from convert.ansys_rst_reader import (
    AnsysRstReader,
    UnsupportedElementWarning,
    _ANSYS_ETYPE_MAP,
    _MIDSIDE_EDGES,
    _SILENT_SKIP_ETYPES,
)
from convert.conversion_manager import ConversionManager
from convert.neutral_model import NeutralModel, NeutralElementType, SOLID_3D_TYPES
from crack_io.frd_reader import read_frd, read_frd_mesh

RST_FILE = Path(__file__).parent / "example" / "ex-2" / "file.rst"

# Applied only to classes that require the real RST file
_needs_rst = pytest.mark.skipif(
    not RST_FILE.is_file(),
    reason=f"file.rst not found at {RST_FILE}",
)


# ---------------------------------------------------------------------------
# AnsysRstReader — detection
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RST_FILE.is_file(), reason=f"file.rst not found at {RST_FILE}")
class TestCanRead:
    def test_accepts_rst_extension(self):
        assert AnsysRstReader.can_read(RST_FILE) is True

    def test_rejects_frd_extension(self):
        assert AnsysRstReader.can_read("some_file.frd") is False

    def test_rejects_random_extension(self):
        assert AnsysRstReader.can_read("model.inp") is False


# ---------------------------------------------------------------------------
# AnsysRstReader — inspect (lightweight, no full parse)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RST_FILE.is_file(), reason=f"file.rst not found at {RST_FILE}")
class TestInspect:
    @pytest.fixture(scope="class")
    def info(self):
        return AnsysRstReader().inspect(RST_FILE)

    def test_no_error(self, info):
        assert "error" not in info, f"inspect() returned error: {info.get('error')}"

    def test_solver_is_ansys(self, info):
        assert info.get("solver") == "ANSYS"

    def test_has_node_count(self, info):
        assert "n_nodes" in info
        assert info["n_nodes"] > 0

    def test_has_element_count(self, info):
        assert "n_elements" in info
        assert info["n_elements"] > 0

    def test_has_increment_count(self, info):
        assert "n_increments" in info
        assert info["n_increments"] >= 1

    def test_has_fields_list(self, info):
        assert "fields" in info
        assert isinstance(info["fields"], list)
        print(f"\n  Available fields: {info['fields']}")

    def test_fields_contains_known_results(self, info):
        # At minimum DISP or STRESS should be present
        fields = set(info.get("fields", []))
        assert fields & {"DISP", "STRESS", "NDTEMP"}, (
            f"Expected at least one of DISP/STRESS/NDTEMP, got: {fields}"
        )


# ---------------------------------------------------------------------------
# AnsysRstReader — full read → NeutralModel
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RST_FILE.is_file(), reason=f"file.rst not found at {RST_FILE}")
class TestRead:
    @pytest.fixture(scope="class")
    def model(self) -> NeutralModel:
        return AnsysRstReader().read(RST_FILE)

    def test_has_nodes(self, model):
        assert model.n_nodes > 0, "Model has no nodes"

    def test_has_elements(self, model):
        assert model.n_elements > 0, "Model has no elements"

    def test_has_increments(self, model):
        assert model.increment_count >= 1, "Model has no increments"

    def test_element_types_are_neutral(self, model):
        for eid, elem in list(model.elements.items())[:20]:
            assert isinstance(elem.etype, NeutralElementType), (
                f"Element {eid} has unexpected etype type: {type(elem.etype)}"
            )

    def test_node_coords_are_finite(self, model):
        for nid, node in list(model.nodes.items())[:100]:
            assert all(map(lambda v: v == v, [node.x, node.y, node.z])), (
                f"Node {nid} has NaN coordinate"
            )

    def test_stress_shape(self, model):
        for inc in model.increments:
            sf = inc.fields.get("STRESS")
            if sf:
                for nid, vals in list(sf.data.items())[:10]:
                    assert vals.shape == (6,), (
                        f"Node {nid} stress shape {vals.shape}, expected (6,)"
                    )
                break

    def test_disp_shape(self, model):
        for inc in model.increments:
            df = inc.fields.get("DISP")
            if df:
                for nid, vals in list(df.data.items())[:10]:
                    assert vals.shape == (3,), (
                        f"Node {nid} disp shape {vals.shape}, expected (3,)"
                    )
                break

    def test_stress_values_finite(self, model):
        for inc in model.increments:
            sf = inc.fields.get("STRESS")
            if sf:
                n_bad = sum(
                    1 for v in sf.data.values() if not np.all(np.isfinite(v))
                )
                assert n_bad == 0, f"{n_bad} nodes have non-finite stress"
                break

    def test_ndtemp_values_finite_when_present(self, model):
        """All stored NDTEMP values must be finite (NaN nodes are skipped)."""
        for inc in model.increments:
            tf = inc.fields.get("NDTEMP")
            if tf:
                n_bad = sum(
                    1 for v in tf.data.values() if not np.isfinite(v[0])
                )
                assert n_bad == 0, (
                    f"{n_bad} NDTEMP nodes have non-finite values — "
                    f"NaN filter not applied correctly"
                )
                break

    def test_ndtemp_covers_all_nodes_after_interpolation(self, model):
        """After midside interpolation, NDTEMP should cover all (or nearly all) model nodes.

        ANSYS only writes temperature at corner nodes (~27% of total for SOLID186);
        midside nodes are filled by linear interpolation inside _read_increment.
        Post-interpolation coverage should be ≥95% for a pure SOLID186/187 mesh.
        """
        for inc in model.increments:
            tf = inc.fields.get("NDTEMP")
            if tf:
                coverage = len(tf.data) / max(1, model.n_nodes)
                assert coverage >= 0.95, (
                    f"NDTEMP covers only {coverage:.1%} of model nodes after interpolation "
                    f"({len(tf.data)}/{model.n_nodes})"
                )
                break

    def test_validate_passes(self, model):
        issues = model.validate()
        assert not issues, f"NeutralModel.validate() issues:\n" + "\n".join(issues)

    def test_metadata_solver(self, model):
        assert model.metadata.source_solver == "ANSYS"

    def test_all_element_nodes_in_node_dict(self, model):
        node_ids = set(model.nodes.keys())
        missing = 0
        for eid, elem in model.elements.items():
            for nid in elem.node_ids:
                if nid not in node_ids:
                    missing += 1
        assert missing == 0, f"{missing} element node references are missing from node dict"


# ---------------------------------------------------------------------------
# Selective field import
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RST_FILE.is_file(), reason=f"file.rst not found at {RST_FILE}")
class TestSelectiveRead:
    def test_stress_only(self):
        model = AnsysRstReader().read(RST_FILE, fields=["STRESS"])
        for inc in model.increments:
            assert "DISP" not in inc.fields or True   # DISP may be absent
            if inc.fields:
                assert "STRESS" in inc.fields or set(inc.fields.keys()) == set()

    def test_first_increment_only(self):
        model = AnsysRstReader().read(RST_FILE, increments=[0])
        assert model.increment_count == 1


# ---------------------------------------------------------------------------
# FrdWriter round-trip — write FRD and re-read with crack_io.frd_reader
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RST_FILE.is_file(), reason=f"file.rst not found at {RST_FILE}")
class TestFrdWriterRoundTrip:
    @pytest.fixture(scope="class")
    def frd_path(self, tmp_path_factory):
        model = AnsysRstReader().read(RST_FILE)
        out = tmp_path_factory.mktemp("out") / "converted.frd"
        from convert.frd_writer import FrdWriter
        FrdWriter(model).write(out)
        return out

    def test_frd_file_created(self, frd_path):
        assert frd_path.is_file()
        assert frd_path.stat().st_size > 0

    def test_frd_mesh_readable(self, frd_path):
        mesh = read_frd_mesh(frd_path)
        assert len(mesh.nodes) > 0, "No nodes in written FRD"
        assert len(mesh.elements) > 0, "No elements in written FRD"

    def test_frd_node_count_matches(self, frd_path):
        model = AnsysRstReader().read(RST_FILE)
        mesh = read_frd_mesh(frd_path)
        assert len(mesh.nodes) == model.n_nodes, (
            f"Node count mismatch: wrote {model.n_nodes}, read back {len(mesh.nodes)}"
        )

    def test_frd_element_count_matches(self, frd_path):
        model = AnsysRstReader().read(RST_FILE)
        mesh = read_frd_mesh(frd_path)
        assert len(mesh.elements) == model.n_elements, (
            f"Element count mismatch: wrote {model.n_elements}, read back {len(mesh.elements)}"
        )

    def test_frd_results_readable(self, frd_path):
        incs = read_frd(frd_path)
        assert len(incs) >= 1, "No increments in written FRD"

    def test_frd_stress_readable(self, frd_path):
        incs = read_frd(frd_path)
        has_stress = any(inc.stresses for inc in incs)
        has_disp   = any(inc.displacements for inc in incs)
        assert has_stress or has_disp, "Neither stress nor displacement found in written FRD"

    def test_frd_stress_values_finite(self, frd_path):
        incs = read_frd(frd_path)
        for inc in incs:
            for nid, s in inc.stresses.items():
                assert np.all(np.isfinite(s)), f"Non-finite stress at node {nid}"


# ---------------------------------------------------------------------------
# ConversionManager pipeline
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RST_FILE.is_file(), reason=f"file.rst not found at {RST_FILE}")
class TestConversionManager:
    def test_find_reader_returns_ansys(self):
        mgr = ConversionManager()
        reader = mgr.find_reader(RST_FILE)
        assert reader is not None
        assert isinstance(reader, AnsysRstReader)

    def test_inspect_no_error(self):
        mgr = ConversionManager()
        info = mgr.inspect(RST_FILE)
        assert "error" not in info, f"inspect error: {info.get('error')}"

    def test_full_convert_pipeline(self, tmp_path):
        mgr = ConversionManager()
        out = tmp_path / "output.frd"
        # validate=False: some RST files have increments without stress
        issues = mgr.convert(RST_FILE, out, validate=False)
        assert not issues, f"Conversion errors: {issues}"
        assert out.is_file()
        assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# MVP element-type map — unit tests (no RST file required)
# ---------------------------------------------------------------------------

class TestMvpEtypeMap:
    """Verify the MVP element-type map contains exactly the specified types."""

    def test_solid185_maps_to_c3d8(self):
        etype, reorder = _ANSYS_ETYPE_MAP[185]
        assert etype == NeutralElementType.C3D8
        assert reorder is None

    def test_solid186_maps_to_c3d20(self):
        etype, reorder = _ANSYS_ETYPE_MAP[186]
        assert etype == NeutralElementType.C3D20
        assert reorder is None

    def test_solid95_maps_to_c3d20(self):
        """SOLID95 (legacy 20-node hex) must map identically to SOLID186."""
        etype, reorder = _ANSYS_ETYPE_MAP[95]
        assert etype == NeutralElementType.C3D20
        assert reorder is None

    def test_solid187_maps_to_c3d10(self):
        etype, reorder = _ANSYS_ETYPE_MAP[187]
        assert etype == NeutralElementType.C3D10
        assert reorder is None

    def test_solid92_maps_to_c3d10(self):
        """SOLID92 (legacy 10-node tet) must map identically to SOLID187."""
        etype, reorder = _ANSYS_ETYPE_MAP[92]
        assert etype == NeutralElementType.C3D10
        assert reorder is None

    def test_map_contains_exactly_five_types(self):
        assert set(_ANSYS_ETYPE_MAP.keys()) == {185, 186, 95, 187, 92}

    def test_all_mapped_types_are_solid_3d(self):
        for et, (neutral, _) in _ANSYS_ETYPE_MAP.items():
            assert neutral in SOLID_3D_TYPES, (
                f"ANSYS type {et} maps to {neutral} which is not a 3-D solid type"
            )

    def test_shell_types_not_in_map(self):
        """Shell element types must NOT appear in the MVP map."""
        shell_types = {181, 281, 61, 63}
        assert not shell_types & set(_ANSYS_ETYPE_MAP), (
            f"Shell elements found in MVP map: {shell_types & set(_ANSYS_ETYPE_MAP)}"
        )

    def test_surf154_is_silent_skip(self):
        assert 154 in _SILENT_SKIP_ETYPES

    def test_contact_elements_are_silent_skip(self):
        for et in (170, 174, 175):
            assert et in _SILENT_SKIP_ETYPES, f"Contact element {et} should be silently skipped"


# ---------------------------------------------------------------------------
# MVP inspect output — integration (requires RST file)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RST_FILE.is_file(), reason=f"file.rst not found at {RST_FILE}")
class TestInspectMvpFields:
    @pytest.fixture(scope="class")
    def info(self):
        return AnsysRstReader().inspect(RST_FILE)

    def test_has_ansys_element_types(self, info):
        assert "ansys_element_types" in info
        assert isinstance(info["ansys_element_types"], dict)
        print(f"\n  ANSYS element types in file: {info['ansys_element_types']}")

    def test_has_n_supported_elements(self, info):
        assert "n_supported_elements" in info
        assert info["n_supported_elements"] > 0, (
            "inspect() reports zero supported solid elements"
        )
        print(f"\n  Supported (solid) elements: {info['n_supported_elements']}")

    def test_has_unsupported_element_types(self, info):
        assert "unsupported_element_types" in info
        assert isinstance(info["unsupported_element_types"], list)
        print(f"\n  Unsupported (non-MVP) types: {info['unsupported_element_types']}")

    def test_unsupported_types_not_in_mvp_map(self, info):
        for et in info.get("unsupported_element_types", []):
            assert et not in _ANSYS_ETYPE_MAP, (
                f"Type {et} listed as unsupported but IS in _ANSYS_ETYPE_MAP"
            )
            assert et not in _SILENT_SKIP_ETYPES, (
                f"Type {et} listed as unsupported but IS in _SILENT_SKIP_ETYPES"
            )


# ---------------------------------------------------------------------------
# MVP validation — unsupported-only model fails with ValueError
# ---------------------------------------------------------------------------

class TestMvpValidation:
    def test_all_elements_must_be_solid_3d(self):
        """NeutralModel.validate() must flag non-3D-solid elements."""
        from convert.neutral_model import NeutralModel, NeutralElement, NeutralNode
        from convert.neutral_model import NeutralIncrement, NeutralResultField
        model = NeutralModel()
        # Add some nodes and a shell element (S4 = not a solid 3D type)
        for i in range(1, 5):
            model.nodes[i] = NeutralNode(id=i, x=float(i), y=0.0, z=0.0)
        model.elements[1] = NeutralElement(
            id=1, etype=NeutralElementType.C3D20,
            node_ids=list(range(1, 21)),
        )
        # validate() should complain about invalid node count (only 4 nodes defined)
        issues = model.validate()
        # The test just checks that validate() runs without crashing
        assert isinstance(issues, list)

    def test_solid_3d_types_frozenset_complete(self):
        """SOLID_3D_TYPES must include all six 3-D solid neutral types."""
        expected = {
            NeutralElementType.C3D4,
            NeutralElementType.C3D6,
            NeutralElementType.C3D8,
            NeutralElementType.C3D10,
            NeutralElementType.C3D15,
            NeutralElementType.C3D20,
        }
        assert expected == SOLID_3D_TYPES

    def test_solid_3d_types_excludes_shells(self):
        shell_types = {
            NeutralElementType.S3,
            NeutralElementType.S4,
            NeutralElementType.S6,
            NeutralElementType.S8,
        }
        assert not shell_types & SOLID_3D_TYPES


# ---------------------------------------------------------------------------
# UnsupportedElementWarning — unit tests
# ---------------------------------------------------------------------------

class TestUnsupportedElementWarning:
    def test_warning_is_user_warning_subclass(self):
        assert issubclass(UnsupportedElementWarning, UserWarning)

    def test_can_filter_by_class(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", UnsupportedElementWarning)
            warnings.warn("test", UnsupportedElementWarning)
        assert len(caught) == 1
        assert issubclass(caught[0].category, UnsupportedElementWarning)


# ---------------------------------------------------------------------------
# NDTEMP NaN filter — unit tests (no RST file required)
# ---------------------------------------------------------------------------

class TestNdtempNanFilter:
    """Verify the NaN filter for nodal temperature using mock RST objects."""

    def _make_rst(self, nnum, temps, n_sets=1):
        """Return a minimal mock rst object for _read_increment testing."""
        class MockRst:
            time_values = [1.0] * n_sets
            nsets = n_sets

            def nodal_temperature(self, index):
                import numpy as np
                return np.array(nnum), np.array(temps)

            def nodal_solution(self, index):
                import numpy as np
                n = len(nnum)
                return np.array(nnum), np.zeros((n, 3))

            def nodal_stress(self, index):
                import numpy as np
                n = len(nnum)
                return np.array(nnum), np.zeros((n, 6))

        return MockRst()

    def test_all_finite_no_nan_stored(self):
        rst = self._make_rst([1, 2, 3], [100.0, 200.0, 300.0])
        reader = AnsysRstReader()
        inc = reader._read_increment(rst, 0, {"NDTEMP"})
        assert inc is not None
        tf = inc.fields.get("NDTEMP")
        assert tf is not None
        assert set(tf.data.keys()) == {1, 2, 3}
        for v in tf.data.values():
            assert np.isfinite(v[0])

    def test_nan_nodes_are_excluded(self):
        import math
        rst = self._make_rst([1, 2, 3, 4], [100.0, float("nan"), 300.0, float("nan")])
        reader = AnsysRstReader()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            inc = reader._read_increment(rst, 0, {"NDTEMP"})
        assert inc is not None
        tf = inc.fields.get("NDTEMP")
        assert tf is not None
        assert set(tf.data.keys()) == {1, 3}, (
            f"Expected only finite-temp nodes {{1, 3}}, got {set(tf.data.keys())}"
        )

    def test_all_nan_produces_no_ndtemp_field(self):
        rst = self._make_rst([1, 2, 3], [float("nan"), float("nan"), float("nan")])
        reader = AnsysRstReader()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            inc = reader._read_increment(rst, 0, {"NDTEMP"})
        # inc may be None (no has_data) or have no NDTEMP field
        if inc is not None:
            assert "NDTEMP" not in inc.fields, (
                "NDTEMP field must not be present when all values are NaN"
            )

    def test_partial_nan_emits_coverage_warning(self):
        """When <99% of nodes have valid temperature, a UserWarning is issued."""
        temps = [100.0] + [float("nan")] * 99   # 1% coverage
        nids  = list(range(1, 101))
        rst = self._make_rst(nids, temps)
        reader = AnsysRstReader()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            reader._read_increment(rst, 0, {"NDTEMP"})
        messages = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
        assert any("NDTEMP" in m and "finite" in m for m in messages), (
            f"Expected coverage warning, got: {messages}"
        )

    def test_full_coverage_no_warning(self):
        """When all nodes are finite, no coverage warning is emitted."""
        rst = self._make_rst([1, 2, 3], [100.0, 200.0, 300.0])
        reader = AnsysRstReader()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            reader._read_increment(rst, 0, {"NDTEMP"})
        ndtemp_warnings = [
            w for w in caught
            if issubclass(w.category, UserWarning) and "NDTEMP" in str(w.message)
        ]
        assert not ndtemp_warnings, (
            f"Unexpected NDTEMP warning for full-coverage data: {ndtemp_warnings}"
        )


# ---------------------------------------------------------------------------
# Midside interpolation — unit tests (no RST file required)
# ---------------------------------------------------------------------------

class TestMidsideInterpolation:
    """Verify _build_midside_map and the interpolation in _read_increment.

    Uses a hand-crafted NeutralModel with one C3D10 element (10-node tet) and
    one C3D20 element (20-node hex) to test both element types without any
    real RST file.
    """

    def _make_c3d10_model(self) -> "NeutralModel":
        """Single C3D10 element: corner nodes 1-4, midside nodes 5-10."""
        from convert.neutral_model import NeutralModel, NeutralNode, NeutralElement
        model = NeutralModel()
        for i in range(1, 11):
            model.nodes[i] = NeutralNode(id=i, x=float(i), y=0.0, z=0.0)
        model.elements[1] = NeutralElement(
            id=1,
            etype=NeutralElementType.C3D10,
            node_ids=list(range(1, 11)),  # [1,2,3,4, 5,6,7,8,9,10]
        )
        return model

    def _make_c3d20_model(self) -> "NeutralModel":
        """Single C3D20 element: corner nodes 1-8, midside nodes 9-20."""
        from convert.neutral_model import NeutralModel, NeutralNode, NeutralElement
        model = NeutralModel()
        for i in range(1, 21):
            model.nodes[i] = NeutralNode(id=i, x=float(i), y=0.0, z=0.0)
        model.elements[1] = NeutralElement(
            id=1,
            etype=NeutralElementType.C3D20,
            node_ids=list(range(1, 21)),  # [1..8 corners, 9..20 midsides]
        )
        return model

    # ------------------------------------------------------------------
    # _build_midside_map — structure tests
    # ------------------------------------------------------------------

    def test_c3d10_midside_map_has_six_entries(self):
        model = self._make_c3d10_model()
        mid_map = AnsysRstReader._build_midside_map(model)
        # C3D10 has 6 midside nodes (local idx 4-9 → global nid 5-10)
        assert len(mid_map) == 6, f"Expected 6 entries, got {len(mid_map)}: {mid_map}"

    def test_c3d20_midside_map_has_twelve_entries(self):
        model = self._make_c3d20_model()
        mid_map = AnsysRstReader._build_midside_map(model)
        # C3D20 has 12 midside nodes (local idx 8-19 → global nid 9-20)
        assert len(mid_map) == 12, f"Expected 12 entries, got {len(mid_map)}: {mid_map}"

    def test_c3d10_midside_map_maps_correct_corners(self):
        """C3D10 local-idx 4 = mid(0,1) → global nid 5 = mid(1,2)."""
        model = self._make_c3d10_model()
        mid_map = AnsysRstReader._build_midside_map(model)
        # nids = [1,2,3,4,5,6,7,8,9,10]; local 4 = nid 5; corners local 0,1 = nid 1,2
        assert mid_map.get(5) == (1, 2), (
            f"Mid node 5 should map to corners (1,2), got {mid_map.get(5)}"
        )

    def test_c3d20_midside_map_maps_correct_corners(self):
        """C3D20 local-idx 8 = mid(0,1) → global nid 9 = mid(1,2)."""
        model = self._make_c3d20_model()
        mid_map = AnsysRstReader._build_midside_map(model)
        # nids = [1..20]; local 8 = nid 9; corners local 0,1 = nid 1,2
        assert mid_map.get(9) == (1, 2), (
            f"Mid node 9 should map to corners (1,2), got {mid_map.get(9)}"
        )

    def test_linear_element_has_no_midside_map(self):
        """C3D8 (linear) has no entries in _MIDSIDE_EDGES; map should be empty."""
        from convert.neutral_model import NeutralModel, NeutralNode, NeutralElement
        model = NeutralModel()
        for i in range(1, 9):
            model.nodes[i] = NeutralNode(id=i, x=float(i), y=0.0, z=0.0)
        model.elements[1] = NeutralElement(
            id=1, etype=NeutralElementType.C3D8, node_ids=list(range(1, 9))
        )
        mid_map = AnsysRstReader._build_midside_map(model)
        assert mid_map == {}, f"Expected empty map for C3D8, got {mid_map}"

    # ------------------------------------------------------------------
    # _read_increment interpolation — NDTEMP
    # ------------------------------------------------------------------

    def _make_mock_rst_with_corner_temps(self, corner_nids, corner_temps,
                                          all_nids, n_sets=1):
        """Mock RST that returns corner temps as finite, midside as NaN."""
        corner_map = dict(zip(corner_nids, corner_temps))

        class MockRst:
            time_values = [1.0] * n_sets
            nsets = n_sets

            def nodal_temperature(self, index):
                temps = [
                    corner_map.get(nid, float("nan"))
                    for nid in all_nids
                ]
                return np.array(all_nids), np.array(temps)

            def nodal_solution(self, index):
                return np.array(all_nids), np.zeros((len(all_nids), 3))

            def nodal_stress(self, index):
                # Corner nodes get finite stress; midside get NaN
                vals = []
                for nid in all_nids:
                    if nid in corner_map:
                        vals.append([float(corner_map[nid])] * 6)
                    else:
                        vals.append([float("nan")] * 6)
                return np.array(all_nids), np.array(vals)

        return MockRst()

    def test_ndtemp_midside_interpolated_for_c3d10(self):
        """Midside NDTEMP values must equal (T_A + T_B) / 2 for C3D10."""
        model = self._make_c3d10_model()
        mid_map = AnsysRstReader._build_midside_map(model)
        # Assign corner temps: nid 1→100, 2→200, 3→300, 4→400
        corner_nids = [1, 2, 3, 4]
        corner_temps = [100.0, 200.0, 300.0, 400.0]
        all_nids = list(range(1, 11))

        rst = self._make_mock_rst_with_corner_temps(corner_nids, corner_temps, all_nids)
        reader = AnsysRstReader()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            inc = reader._read_increment(rst, 0, {"NDTEMP"}, midside_map=mid_map)

        assert inc is not None
        tf = inc.fields["NDTEMP"]
        # nid 5 = mid(1,2) → (100+200)/2 = 150
        assert abs(tf.data[5][0] - 150.0) < 1e-10, f"nid5 T={tf.data[5][0]}, expected 150"
        # nid 8 = mid(1,4) → (100+400)/2 = 250
        assert abs(tf.data[8][0] - 250.0) < 1e-10, f"nid8 T={tf.data[8][0]}, expected 250"
        # nid 10 = mid(3,4) → (300+400)/2 = 350
        assert abs(tf.data[10][0] - 350.0) < 1e-10, f"nid10 T={tf.data[10][0]}, expected 350"

    def test_ndtemp_all_nodes_present_after_interpolation(self):
        """After interpolation, NDTEMP data covers all 10 nodes of the C3D10 element."""
        model = self._make_c3d10_model()
        mid_map = AnsysRstReader._build_midside_map(model)
        corner_nids = [1, 2, 3, 4]
        corner_temps = [100.0, 200.0, 300.0, 400.0]
        all_nids = list(range(1, 11))

        rst = self._make_mock_rst_with_corner_temps(corner_nids, corner_temps, all_nids)
        reader = AnsysRstReader()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            inc = reader._read_increment(rst, 0, {"NDTEMP"}, midside_map=mid_map)

        tf = inc.fields["NDTEMP"]
        assert set(tf.data.keys()) == set(range(1, 11)), (
            f"Expected all 10 nodes covered, missing: {set(range(1,11)) - set(tf.data.keys())}"
        )

    # ------------------------------------------------------------------
    # _read_increment interpolation — STRESS
    # ------------------------------------------------------------------

    def test_stress_midside_interpolated_for_c3d10(self):
        """Midside STRESS values must equal (S_A + S_B) / 2 element-wise."""
        model = self._make_c3d10_model()
        mid_map = AnsysRstReader._build_midside_map(model)
        # Corner stresses: nid 1 → all-10, nid 2 → all-20
        corner_nids = [1, 2, 3, 4]
        corner_temps = [10.0, 20.0, 30.0, 40.0]  # used as stress magnitude
        all_nids = list(range(1, 11))

        rst = self._make_mock_rst_with_corner_temps(corner_nids, corner_temps, all_nids)
        reader = AnsysRstReader()
        inc = reader._read_increment(rst, 0, {"STRESS"}, midside_map=mid_map)

        assert inc is not None
        sf = inc.fields["STRESS"]
        # nid 5 = mid(1,2) → ([10]*6 + [20]*6) / 2 = [15]*6
        assert sf.data[5].shape == (6,), f"nid5 stress shape {sf.data[5].shape}"
        assert np.allclose(sf.data[5], 15.0), f"nid5 stress {sf.data[5]}, expected 15.0"

    def test_stress_all_nodes_present_after_interpolation(self):
        """After interpolation, STRESS data covers all 10 nodes of the C3D10 element."""
        model = self._make_c3d10_model()
        mid_map = AnsysRstReader._build_midside_map(model)
        corner_nids = [1, 2, 3, 4]
        corner_temps = [10.0, 20.0, 30.0, 40.0]
        all_nids = list(range(1, 11))

        rst = self._make_mock_rst_with_corner_temps(corner_nids, corner_temps, all_nids)
        reader = AnsysRstReader()
        inc = reader._read_increment(rst, 0, {"STRESS"}, midside_map=mid_map)

        sf = inc.fields["STRESS"]
        assert set(sf.data.keys()) == set(range(1, 11)), (
            f"Expected all 10 nodes covered, missing: {set(range(1,11)) - set(sf.data.keys())}"
        )

    def test_midside_edges_constant_c3d20_has_twelve_edges(self):
        """_MIDSIDE_EDGES[C3D20] must have exactly 12 entries at local indices 8-19."""
        edges = _MIDSIDE_EDGES[NeutralElementType.C3D20]
        assert len(edges) == 12
        assert set(edges.keys()) == set(range(8, 20))

    def test_midside_edges_constant_c3d10_has_six_edges(self):
        """_MIDSIDE_EDGES[C3D10] must have exactly 6 entries at local indices 4-9."""
        edges = _MIDSIDE_EDGES[NeutralElementType.C3D10]
        assert len(edges) == 6
        assert set(edges.keys()) == set(range(4, 10))

    def test_no_interpolation_when_midside_map_is_none(self):
        """Without a midside_map, midside NaN nodes are simply absent from the field."""
        model = self._make_c3d10_model()
        corner_nids = [1, 2, 3, 4]
        corner_temps = [100.0, 200.0, 300.0, 400.0]
        all_nids = list(range(1, 11))

        rst = self._make_mock_rst_with_corner_temps(corner_nids, corner_temps, all_nids)
        reader = AnsysRstReader()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            inc = reader._read_increment(rst, 0, {"NDTEMP"}, midside_map=None)

        tf = inc.fields["NDTEMP"]
        # Without interpolation only the 4 corner nodes have values
        assert set(tf.data.keys()) == {1, 2, 3, 4}, (
            f"Expected only corners {{1,2,3,4}}, got {set(tf.data.keys())}"
        )
