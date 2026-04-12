"""
Unit tests for convert/frd_writer.py — header, section, and format correctness.

These tests do NOT require any external FRD or RST files; they create minimal
NeutralModel instances in-memory and verify the written FRD structure.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from convert.frd_writer import FrdWriter
from convert.neutral_model import (
    NeutralElement,
    NeutralElementType,
    NeutralIncrement,
    NeutralMetadata,
    NeutralModel,
    NeutralNode,
    NeutralResultField,
)

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_model(title: str = "TEST") -> NeutralModel:
    """8-node C3D8 hex with a single stress increment."""
    model = NeutralModel(metadata=NeutralMetadata(
        source_solver="ANSYS", source_file="test.rst", title=title,
    ))
    # 8 corner nodes of a unit cube
    coords = [
        (0., 0., 0.), (1., 0., 0.), (1., 1., 0.), (0., 1., 0.),
        (0., 0., 1.), (1., 0., 1.), (1., 1., 1.), (0., 1., 1.),
    ]
    for nid, (x, y, z) in enumerate(coords, start=1):
        model.nodes[nid] = NeutralNode(id=nid, x=x, y=y, z=z)
    model.elements[1] = NeutralElement(
        id=1, etype=NeutralElementType.C3D8,
        node_ids=list(range(1, 9)),
    )
    stress_data = {nid: np.zeros(6, dtype=float) for nid in range(1, 9)}
    inc = NeutralIncrement(step=1, increment=1, total_time=1.0)
    inc.fields["STRESS"] = NeutralResultField(
        name="STRESS",
        component_names=["SXX", "SYY", "SZZ", "SXY", "SYZ", "SXZ"],
        data=stress_data,
    )
    model.increments.append(inc)
    return model


def _write_to_string(model: NeutralModel) -> str:
    """Write the model to an in-memory string via a temp file."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".frd", delete=False, encoding="utf-8", newline="\n"
    ) as fh:
        tmp = fh.name
    try:
        FrdWriter(model).write(tmp)
        return Path(tmp).read_text(encoding="utf-8")
    finally:
        os.unlink(tmp)


def _header_lines(content: str) -> list[str]:
    """Return lines up to (not including) the first 2C line."""
    lines = content.splitlines()
    out = []
    for line in lines:
        if line.strip().startswith("2C"):
            break
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# Header — 1C line
# ---------------------------------------------------------------------------

class TestHeader1C:
    def test_first_line_is_1c(self):
        content = _write_to_string(_minimal_model())
        first = content.splitlines()[0]
        assert first == "    1C", f"Expected '    1C', got {repr(first)}"

    def test_1c_is_exactly_6_chars(self):
        content = _write_to_string(_minimal_model())
        first = content.splitlines()[0]
        assert len(first) == 6, f"1C line length {len(first)}, expected 6"

    def test_1c_no_trailing_space(self):
        content = _write_to_string(_minimal_model())
        first = content.splitlines()[0]
        assert not first.endswith(" "), "1C line must not have trailing spaces"


# ---------------------------------------------------------------------------
# Header — 1U records
# ---------------------------------------------------------------------------

class TestHeader1U:
    @pytest.fixture(scope="class")
    def header(self):
        return _header_lines(_write_to_string(_minimal_model()))

    def test_has_user_record(self, header):
        assert any(l.startswith("    1UUSER") for l in header)

    def test_has_date_record(self, header):
        assert any(l.startswith("    1UDATE") for l in header)

    def test_has_time_record(self, header):
        assert any(l.startswith("    1UTIME") for l in header)

    def test_has_host_record(self, header):
        assert any(l.startswith("    1UHOST") for l in header)

    def test_has_pgm_record(self, header):
        assert any(l.startswith("    1UPGM") for l in header)

    def test_has_version_record(self, header):
        assert any(l.startswith("    1UVERSION") for l in header)

    def test_has_compiletime_record(self, header):
        assert any(l.startswith("    1UCOMPILETIME") for l in header)

    def test_has_dir_record(self, header):
        assert any(l.startswith("    1UDIR") for l in header)

    def test_has_dbn_record(self, header):
        assert any(l.startswith("    1UDBN") for l in header)

    def test_has_mat_record(self, header):
        assert any(l.startswith("    1UMAT") for l in header)

    def test_all_1u_records_are_72_chars(self, header):
        for line in header:
            if line.startswith("    1U") and not line.startswith("    1UMAT"):
                assert len(line) == 72, (
                    f"1U record wrong length ({len(line)}): {repr(line)}"
                )

    def test_mat_record_is_72_chars(self, header):
        for line in header:
            if line.startswith("    1UMAT"):
                assert len(line) == 72, (
                    f"1UMAT record wrong length ({len(line)}): {repr(line)}"
                )

    def test_pgm_value_is_gmcrackx(self, header):
        for line in header:
            if line.startswith("    1UPGM"):
                assert "GmCrackX" in line, f"PGM value not 'GmCrackX': {repr(line)}"
                return
        pytest.fail("No 1UPGM record found")

    def test_version_value_present(self, header):
        for line in header:
            if line.startswith("    1UVERSION"):
                assert "Version" in line, f"VERSION missing 'Version': {repr(line)}"
                return
        pytest.fail("No 1UVERSION record found")

    def test_date_has_dynamic_value(self, header):
        for line in header:
            if line.startswith("    1UDATE"):
                # Should contain the current year
                assert str(datetime.now().year) in line, (
                    f"DATE record does not contain current year: {repr(line)}"
                )
                return
        pytest.fail("No 1UDATE record found")

    def test_time_matches_hh_mm_ss_format(self, header):
        for line in header:
            if line.startswith("    1UTIME"):
                # Value part starts at column 24 (after "    1U" + 18-char key)
                value = line[24:].strip()
                assert re.match(r"^\d{2}:\d{2}:\d{2}$", value), (
                    f"TIME value not HH:MM:SS: {repr(value)}"
                )
                return
        pytest.fail("No 1UTIME record found")

    def test_mat_record_contains_1c_tag(self, header):
        for line in header:
            if line.startswith("    1UMAT"):
                assert "1C" in line, f"1UMAT missing '1C' sub-tag: {repr(line)}"
                return
        pytest.fail("No 1UMAT record found")

    def test_header_order(self, header):
        """1C must be first; all 1U records must follow before 2C."""
        assert header[0] == "    1C", "First line must be '    1C'"
        for line in header[1:]:
            assert line.startswith("    1U"), (
                f"Non-1U line in header block: {repr(line)}"
            )


# ---------------------------------------------------------------------------
# Section headers — 2C / 3C
# ---------------------------------------------------------------------------

class TestSectionHeaders:
    @pytest.fixture(scope="class")
    def content(self):
        return _write_to_string(_minimal_model())

    def _find_section(self, content: str, tag: str) -> str:
        for line in content.splitlines():
            if line.strip().startswith(tag):
                return line
        pytest.fail(f"No {tag} section header found")

    def test_2c_header_length(self, content):
        line = self._find_section(content, "2C")
        assert len(line) == 74, (
            f"2C header length {len(line)}, expected 74: {repr(line)}"
        )

    def test_3c_header_length(self, content):
        line = self._find_section(content, "3C")
        assert len(line) == 74, (
            f"3C header length {len(line)}, expected 74: {repr(line)}"
        )

    def test_2c_ends_with_1(self, content):
        line = self._find_section(content, "2C")
        assert line.endswith("1"), f"2C header must end with '1': {repr(line)}"

    def test_3c_ends_with_1(self, content):
        line = self._find_section(content, "3C")
        assert line.endswith("1"), f"3C header must end with '1': {repr(line)}"

    def test_2c_node_count_correct(self, content):
        line = self._find_section(content, "2C")
        # The count field is a right-justified integer in the 30 chars after "    2C"
        count_str = line[6:36].strip()
        assert int(count_str) == 8, f"2C count should be 8 (nodes), got {count_str}"

    def test_3c_element_count_correct(self, content):
        line = self._find_section(content, "3C")
        count_str = line[6:36].strip()
        assert int(count_str) == 1, f"3C count should be 1 (element), got {count_str}"


# ---------------------------------------------------------------------------
# End-of-file sentinel
# ---------------------------------------------------------------------------

class TestEndSentinel:
    def test_last_line_is_9999(self):
        content = _write_to_string(_minimal_model())
        last = content.rstrip("\n").splitlines()[-1]
        assert last == "9999", f"Last line must be '9999', got {repr(last)}"


# ---------------------------------------------------------------------------
# Full structure sanity
# ---------------------------------------------------------------------------

class TestFullStructure:
    @pytest.fixture(scope="class")
    def lines(self):
        return _write_to_string(_minimal_model()).splitlines()

    def test_structure_order(self, lines):
        """Verify 1C → 1U... → 2C → 3C → 1PSTEP → 9999 ordering."""
        seen = []
        for line in lines:
            s = line.strip()
            if s == "1C":
                seen.append("1C")
            elif s.startswith("1U"):
                seen.append("1U")
            elif s.startswith("2C"):
                seen.append("2C")
            elif s.startswith("3C"):
                seen.append("3C")
            elif s.startswith("1PSTEP"):
                seen.append("1PSTEP")
            elif s == "9999":
                seen.append("9999")

        assert seen[0] == "1C", "Must start with 1C"
        assert "2C" in seen, "Must have 2C section"
        assert "3C" in seen, "Must have 3C section"
        assert seen[-1] == "9999", "Must end with 9999"
        assert seen.index("2C") > seen.index("1C"), "2C must follow 1C"
        assert seen.index("3C") > seen.index("2C"), "3C must follow 2C"
