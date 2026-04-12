"""
Write CalculiX .frd result files from a NeutralModel.

Produces ASCII output compatible with CalculiX / CGX and crack_io/frd_reader.py:
  - 1C / 1U  file identification header (program, date, version, …)
  - 2C        node coordinates (" -1" lines)
  - 3C        element connectivity (" -1" / " -2" lines)
  - Per increment: 1PSTEP + per result-block 100CL + "-4 / -5 / -1 / -3"
  - 9999      end-of-file sentinel

Fixed-width rules (mirrors CalculiX output):
  1U record:    "    1U" (6) + key (18, left-pad) + value (48, left-pad) = 72 chars
  2C/3C header: "    XC" (6) + count (I30) + 37 spaces + "1"           = 74 chars
  Node line:    " -1" (3) + nid (10) + x/y/z (12 each, %12.5E)
  Elem header:  " -1" (3) + eid (10) + etype (5) + grp (5) + mat (5)
  Conn line:    " -2" (3) + up to 10 × nid (10 each)
  1PSTEP:       "    1PSTEP" (10) + step (I26) + inc (I12) + 1 (I12) + 10 spaces
  100CL:        "  100CL" (7) + 101 (I5) + time (F12.9) + nentity (I12) +
                0 (I22) + 1 (I5) + 1 (I12)
  -4 header:    " -4  " (5) + name (12, left) + ncomp (d) + 1 (I5)
  -5 header:    " -5  " (5) + comp (12, left) + 1 (d) + ictype (I5) +
                idx1 (I5) + idx2 (I5) [+ extra]
  Data line:    " -1" (3) + nid (10) + up to 6 values (12 each, %12.5E)
  Cont line:    " -2" (3) + 10 spaces + up to 6 values (12 each)
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TextIO

import numpy as np

from .neutral_model import NeutralIncrement, NeutralModel, NeutralResultField


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# FRD element type code → number of -2 connectivity lines
# Mirrors _FRD_ETYPE_NLINES in crack_io/frd_reader.py
_ETYPE_NLINES: dict[int, int] = {
    1: 1,   # C3D8  (8 nodes)
    2: 1,   # C3D6  (6 nodes)
    3: 1,   # C3D4  (4 nodes)
    4: 2,   # C3D20 (20 nodes, 10 per line)
    5: 2,   # C3D15 (15 nodes, 10+5)
    6: 1,   # C3D10 (10 nodes)
    7: 1,   # S3    (3 nodes)
    8: 1,   # S6    (6 nodes)
    9: 1,   # S4    (4 nodes)
    10: 1,  # S8    (8 nodes)
}

# ictype per field name (CalculiX convention: 1=scalar, 2=vector, 4=tensor)
_FIELD_ICTYPE: dict[str, int] = {
    "DISP":   2,
    "STRESS": 4,
    "NDTEMP": 1,
    "FORC":   2,
}

# Per-field ordered list of (comp_name, idx1, idx2, extra_suffix).
# These drive both the -4 ncomp count and the -5 component header lines.
# idx1/idx2 follow CalculiX convention (tensor: row/col 1-3; vector: direction 1-3 / 0).
# extra_suffix appended verbatim after idx2 (e.g. "    1ALL" for the ALL pseudocomponent).
#
# The ALL pseudocomponent for vector fields is NOT a separate data column —
# it is a CalculiX descriptor.  n_data_comps excludes it so -1 data lines
# write only the real values (3 for DISP/FORC, 6 for STRESS, 1 for NDTEMP).
_FIELD_COMPONENTS: dict[str, list[tuple[str, int, int, str]]] = {
    "DISP": [
        ("D1",  1, 0, ""),
        ("D2",  2, 0, ""),
        ("D3",  3, 0, ""),
        ("ALL", 0, 0, "    1ALL"),  # pseudocomponent — no data column
    ],
    "STRESS": [
        ("SXX", 1, 1, ""),
        ("SYY", 2, 2, ""),
        ("SZZ", 3, 3, ""),
        ("SXY", 1, 2, ""),
        ("SYZ", 2, 3, ""),
        ("SZX", 3, 1, ""),
    ],
    "NDTEMP": [
        ("T",   0, 0, ""),
    ],
    "FORC": [
        ("F1",  1, 0, ""),
        ("F2",  2, 0, ""),
        ("F3",  3, 0, ""),
        ("ALL", 0, 0, "    1ALL"),  # pseudocomponent — no data column
    ],
}

# Number of actual data values written per node in -1 lines (excludes ALL).
_FIELD_N_DATA_COMPS: dict[str, int] = {
    "DISP":   3,
    "STRESS": 6,
    "NDTEMP": 1,
    "FORC":   3,
}

# Max data values per result line (CalculiX writes ≤6 per -1/-2 line)
_VALUES_PER_LINE = 6


# ---------------------------------------------------------------------------
# Public writer class
# ---------------------------------------------------------------------------

class FrdWriter:
    """Write a :class:`~convert.neutral_model.NeutralModel` to a CalculiX FRD file.

    Parameters
    ----------
    model:
        The neutral model to serialise.
    group_id:
        Element group ID written to every element header (default 1).
    mat_id:
        Material ID written to every element header (default 1).
    """

    def __init__(
        self,
        model: NeutralModel,
        group_id: int = 1,
        mat_id: int = 1,
    ) -> None:
        self._model = model
        self._group = group_id
        self._mat = mat_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, path: str | Path) -> None:
        """Serialise the model to *path* (creates or overwrites the file)."""
        path = Path(path)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            self._write_header(fh)
            self._write_nodes(fh)
            self._write_elements(fh)
            step_counter = 0
            for inc in self._model.increments:
                step_counter = self._write_increment(fh, inc, step_counter)
            fh.write("9999\n")

    # ------------------------------------------------------------------
    # Section writers
    # ------------------------------------------------------------------

    def _write_header(self, fh: TextIO) -> None:
        """Write the 1C / 1U file identification header block.

        Format mirrors CalculiX output:
          - One ``    1C`` title line (6 chars, no trailing spaces)
          - Ten ``    1U`` records, each padded to exactly 72 chars:
              ``    1U`` (6) + key (18, left-justified) + value (48, left-justified)
          - One ``    1UMAT`` record with fixed 12-char prefix + material tag
        """
        now = datetime.now()
        date_str = f"{now.day}.{now.strftime('%B').lower()}.{now.year}"
        time_str = now.strftime("%H:%M:%S")

        # 1C title line — no trailing spaces (matches CalculiX)
        fh.write("    1C\n")

        # Helper: 72-char 1U record
        def _u(key: str, value: str = "") -> None:
            fh.write(f"    1U{key:<18s}{value:<48s}\n")

        _u("USER")
        _u("DATE", date_str)
        _u("TIME", time_str)
        _u("HOST")
        _u("PGM", "GmCrackX")
        _u("VERSION", "Version 1.0")
        _u("COMPILETIME")
        _u("DIR")
        _u("DBN")

        # 1UMAT — special format: "    1UMAT    " (12) + "{n}C{name}" padded to 72
        # n = material index (1-based), C = type tag for name
        mat_name = (self._model.metadata.title or "GMCRACKX")[:20].upper()
        mat_prefix = f"    1UMAT    1C{mat_name}"
        fh.write(f"{mat_prefix:<72s}\n")

    # -- Nodes (2C) --------------------------------------------------------

    def _write_nodes(self, fh: TextIO) -> None:
        """Write 2C node-coordinate block."""
        n = len(self._model.nodes)
        # 74-char header: "    2C" (6) + count (I30) + 37 spaces + "1"
        fh.write(f"    2C{n:30d}                                     1\n")
        for nid in sorted(self._model.nodes):
            node = self._model.nodes[nid]
            fh.write(
                f" -1{nid:>10d}"
                f"{node.x:12.5E}"
                f"{node.y:12.5E}"
                f"{node.z:12.5E}\n"
            )
        fh.write(" -3\n")

    # -- Elements (3C) -----------------------------------------------------

    def _write_elements(self, fh: TextIO) -> None:
        """Write 3C element-connectivity block."""
        n = len(self._model.elements)
        # 74-char header: "    3C" (6) + count (I30) + 37 spaces + "1"
        fh.write(f"    3C{n:30d}                                     1\n")
        for eid in sorted(self._model.elements):
            elem = self._model.elements[eid]
            etype_code = int(elem.etype)
            # Element header line
            fh.write(
                f" -1{eid:>10d}"
                f"{etype_code:5d}"
                f"{self._group:5d}"
                f"{self._mat:5d}\n"
            )
            # Connectivity: split over n_lines -2 lines (10 nodes per line max)
            nids = elem.node_ids
            # C3D20: ANSYS delivers corners + bottom mids + top mids + vertical mids.
            # CalculiX FRD expects corners + bottom mids + vertical mids + top mids.
            # Swap the two groups at positions 12-15 and 16-19.
            if etype_code == 4 and len(nids) == 20:
                nids = nids[:12] + nids[16:20] + nids[12:16]
            n_lines = _ETYPE_NLINES.get(etype_code, 1)
            nodes_per_line = (len(nids) + n_lines - 1) // n_lines
            nodes_per_line = max(nodes_per_line, 1)
            for start in range(0, len(nids), nodes_per_line):
                chunk = nids[start : start + nodes_per_line]
                fh.write(" -2" + "".join(f"{nid:>10d}" for nid in chunk) + "\n")
        fh.write(" -3\n")

    # -- Increment ---------------------------------------------------------

    def _write_increment(
        self, fh: TextIO, inc: NeutralIncrement, step_counter: int = 0
    ) -> int:
        """Write one 1PSTEP + 100CL + result block per field.

        Each result type (DISP, STRESS, NDTEMP, …) gets its own 1PSTEP record
        with a globally-incrementing step number, matching CalculiX output:

            1PSTEP step=1  → DISP block
            1PSTEP step=2  → STRESS block
            1PSTEP step=3  → NDTEMP / FORC / … block

        Returns the updated step counter so the caller can pass it to the
        next increment.
        """
        for field_name, result_field in inc.fields.items():
            step_counter += 1
            fh.write(
                f"    1PSTEP{step_counter:26d}{inc.increment:12d}"
                f"{1:12d}          \n"
            )
            self._write_result_block(fh, field_name, result_field, inc.total_time)
        return step_counter

    # -- Result block (100CL / -4 / -5 / -1 / -3) -------------------------

    def _write_result_block(
        self,
        fh: TextIO,
        name: str,
        field: NeutralResultField,
        time_val: float = 1.0,
    ) -> None:
        """Write one 100CL / -4 / -5 / -1 / -3 result block.

        100CL format (mirrors CalculiX):
          "  100CL" (7) + irtype=101 (I5) + time (F12.9) +
          n_entities (I12) + 0 (I22) + 1 (I5) + 1 (I12)

        -4 format:
          " -4  " (5) + name (12, left-justified) + ncomp (d) + 1 (I5)

        -5 format:
          " -5  " (5) + comp (12, left-justified) + 1 (d) +
          ictype (I5) + idx1 (I5) + idx2 (I5) [+ extra_suffix]
        """
        comp_meta = _FIELD_COMPONENTS.get(name)
        if comp_meta is None:
            return  # unknown field — skip silently

        ictype = _FIELD_ICTYPE.get(name, 1)
        ncomp = len(comp_meta)
        n_data = _FIELD_N_DATA_COMPS.get(name, ncomp)
        n_entities = len(field.data)

        # 100CL result-description line
        fh.write(
            f"  100CL{101:5d}{time_val:12.9f}"
            f"{n_entities:12d}{0:22d}{1:5d}{1:12d}\n"
        )

        # -4 block header: name(12) + ncomp(variable) + nentity=1(I5)
        fh.write(f" -4  {name:<12s}{ncomp:d}{1:5d}\n")

        # -5 component definition lines
        for comp_name, idx1, idx2, extra in comp_meta:
            fh.write(
                f" -5  {comp_name:<12s}{1:d}{ictype:5d}"
                f"{idx1:5d}{idx2:5d}{extra}\n"
            )

        # -1 / -2 data lines (≤6 values per line, non-finite → 0.0)
        for nid in sorted(field.data):
            values = field.data[nid]
            # Take only the real data components (excludes ALL pseudocomponent)
            safe: list[float] = []
            for i in range(n_data):
                v = float(values[i]) if i < len(values) else 0.0
                safe.append(v if np.isfinite(v) else 0.0)

            # First line: " -1<nid><v1>...<v6>"
            first_chunk = safe[:_VALUES_PER_LINE]
            fh.write(
                f" -1{nid:>10d}"
                + "".join(f"{v:12.5E}" for v in first_chunk)
                + "\n"
            )

            # Continuation lines: " -2          <v7>...<v12>"
            for offset in range(_VALUES_PER_LINE, len(safe), _VALUES_PER_LINE):
                chunk = safe[offset : offset + _VALUES_PER_LINE]
                fh.write(
                    " -2          "
                    + "".join(f"{v:12.5E}" for v in chunk)
                    + "\n"
                )

        fh.write(" -3\n")
