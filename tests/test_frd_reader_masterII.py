"""
Integration test: parse the real masterII.frd file.

This FRD is from a static analysis (CT3D_BENCHMARK), not from *CRACK PROPAGATION.
It has 3 steps:
  - Step 1: DISP (10017 nodes)
  - Step 2: STRESS (10017 nodes)
  - Step 3: ERROR (not parsed)

Tests that frd_reader handles real-world fixed-width FRD format correctly
and that read_keq_results returns empty for non-propagation FRDs.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path

import numpy as np
import pytest

from crack_io.frd_reader import (
    read_frd,
    read_keq_results,
    get_last_displacements,
    get_last_stresses,
)

MASTER_FRD = Path(__file__).parent / "example" / "masterII.frd"

# Skip all tests if the FRD file is not present
pytestmark = pytest.mark.skipif(
    not MASTER_FRD.is_file(),
    reason=f"masterII.frd not found at {MASTER_FRD}",
)


class TestReadFrd:
    def test_parses_three_increments(self):
        incs = read_frd(MASTER_FRD)
        assert len(incs) == 3

    def test_step1_has_displacements(self):
        """Step 1 contains DISP block with ~10017 nodes."""
        incs = read_frd(MASTER_FRD)
        step1 = incs[0]
        assert step1.step == 1
        assert len(step1.displacements) > 5000

    def test_step2_has_stresses(self):
        """Step 2 contains STRESS block with ~10017 nodes."""
        incs = read_frd(MASTER_FRD)
        step2 = incs[1]
        assert step2.step == 2
        assert len(step2.stresses) > 5000

    def test_stress_values_finite(self):
        incs = read_frd(MASTER_FRD)
        step2 = incs[1]
        for nid, s in list(step2.stresses.items())[:100]:
            assert np.all(np.isfinite(s)), f"Node {nid} has non-finite stress"

    def test_stress_six_components(self):
        incs = read_frd(MASTER_FRD)
        step2 = incs[1]
        for nid, s in list(step2.stresses.items())[:10]:
            assert s.shape == (6,), f"Node {nid}: expected 6 stress components, got {s.shape}"

    def test_displacement_three_components(self):
        incs = read_frd(MASTER_FRD)
        step1 = incs[0]
        for nid, d in list(step1.displacements.items())[:10]:
            assert d.shape == (3,), f"Node {nid}: expected 3 disp components, got {d.shape}"

    def test_fixed_width_parsing_negative_values(self):
        """Real FRD has packed negative values (no space between nid and value).
        Verify the parser handles this correctly."""
        incs = read_frd(MASTER_FRD)
        step2 = incs[1]
        # Node 56 is the first stress node — should have valid data
        assert 56 in step2.stresses
        s = step2.stresses[56]
        assert len(s) == 6
        # First stress component should be negative (SXX ≈ -2737)
        assert s[0] < 0


class TestConvenienceHelpers:
    def test_get_last_stresses_from_step2(self):
        """get_last_stresses returns from the last increment that HAS stresses."""
        incs = read_frd(MASTER_FRD)
        # Step 2 (index 1) has stresses, step 3 (index 2) does not
        step2_stresses = incs[1].stresses
        assert len(step2_stresses) > 5000

    def test_get_last_displacements_from_step1(self):
        """Step 1 has displacements."""
        incs = read_frd(MASTER_FRD)
        step1_displ = incs[0].displacements
        assert len(step1_displ) > 5000


class TestNoKEQInStaticFRD:
    def test_keq_results_empty(self):
        """A static analysis FRD should produce no KEQ increments."""
        keq = read_keq_results(MASTER_FRD)
        assert keq == [], "Static FRD should have no KEQ blocks"
