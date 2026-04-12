"""
Parse CalculiX .frd result files (ASCII format).

Extracts nodal results per increment:
  - Displacements (DISP / U)
  - Stresses      (STRESS / S)
  - Forces        (FORC / RF)

For *CRACK PROPAGATION output (*NODE FILE, KEQ):
  - DELTAKEQ, KEQMIN, KEQMAX
  - K1WORST, K2WORST, K3WORST
  - PHI, R, DADN, KTH
  - INC, CYCLES, CRLENGTH

Reference: CalculiX CrunchiX User's Manual, Appendix B and §6.9.27.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Standard FRD increment (displacements, stresses, forces)
# ---------------------------------------------------------------------------

@dataclass
class FrdIncrement:
    step:           int
    increment:      int
    total_time:     float
    displacements:  dict[int, np.ndarray] = field(default_factory=dict)  # nid → (3,)
    stresses:       dict[int, np.ndarray] = field(default_factory=dict)  # nid → (6,) Sxx Syy Szz Sxy Syz Sxz
    forces:         dict[int, np.ndarray] = field(default_factory=dict)  # nid → (3,)


# ---------------------------------------------------------------------------
# KEQ increment (crack propagation output)
# ---------------------------------------------------------------------------

# Field names in the order CalculiX writes them to the KEQ output block
KEQ_FIELDS = (
    "DELTAKEQ", "KEQMIN", "KEQMAX",
    "K1WORST", "K2WORST", "K3WORST",
    "PHI", "R", "DADN", "KTH",
    "INC", "CYCLES", "CRLENGTH",
)

# Block names that CalculiX uses in -4 headers for KEQ output
_KEQ_BLOCK_NAMES = frozenset(KEQ_FIELDS)


@dataclass
class KEQIncrement:
    """Per-increment container for *CRACK PROPAGATION KEQ output.

    keq_data maps node_id → dict of field_name → float value.
    Each crack-front node has one entry per KEQ field.
    """
    step:       int
    increment:  int
    total_time: float
    keq_data:   dict[int, dict[str, float]] = field(default_factory=dict)

    @property
    def node_ids(self) -> list[int]:
        return sorted(self.keq_data.keys())

    def get_field_array(self, field_name: str) -> tuple[np.ndarray, np.ndarray]:
        """Return (node_ids, values) arrays for a given KEQ field."""
        nids = self.node_ids
        vals = np.array([self.keq_data[n].get(field_name, 0.0) for n in nids])
        return np.array(nids), vals


# ---------------------------------------------------------------------------
# Fixed-width line parser
# ---------------------------------------------------------------------------

def _parse_data_line(line: str) -> tuple[int, np.ndarray] | None:
    """
    Parse a CalculiX FRD -1 data line.

    CalculiX uses fixed-width format:
      " -1" (3 chars) + node_id (10 chars) + values (12 chars each).
    When negative values are present, the minus sign consumes the leading
    space, merging the node ID with the first value in split() output.

    Strategy: try split() first (works for well-spaced data), fall back
    to fixed-width extraction when split() can't separate node ID and values.
    """
    if len(line) < 5:
        return None

    # Try split() first (handles space-delimited synthetic data)
    parts = line.split()
    if len(parts) >= 2:
        try:
            nid = int(parts[1])
            values = np.array([float(v) for v in parts[2:]])
            return nid, values
        except ValueError:
            pass

    # Fallback: fixed-width extraction (handles real CalculiX packed format)
    if len(line) < 13:
        return None
    try:
        nid = int(line[3:13])
    except ValueError:
        return None

    vals_str = line[13:].rstrip("\n")
    if not vals_str.strip():
        return nid, np.array([])

    values = []
    pos = 0
    while pos < len(vals_str):
        chunk = vals_str[pos:pos + 12].strip()
        if chunk:
            try:
                values.append(float(chunk))
            except ValueError:
                break
        pos += 12

    return nid, np.array(values)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def read_frd(path: str | Path) -> list[FrdIncrement]:
    """
    Parse a CalculiX .frd file and return a list of FrdIncrement objects,
    one per increment found in the file.
    """
    path = Path(path)
    increments: list[FrdIncrement] = []
    current: FrdIncrement | None = None

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    i = 0
    while i < len(lines):
        line = lines[i]

        # New increment header: "    1PSTEP ..."
        if line.startswith("    1") and "STEP" in line.upper():
            parts = line.split()
            try:
                step_no = int(parts[1]) if len(parts) > 1 else 0
                inc_no  = int(parts[2]) if len(parts) > 2 else 0
                t_time  = float(parts[3]) if len(parts) > 3 else 0.0
            except (ValueError, IndexError):
                step_no, inc_no, t_time = 0, 0, 0.0
            current = FrdIncrement(step_no, inc_no, t_time)
            increments.append(current)
            i += 1
            continue

        # Result block header: " -4  DISP ..." or " -4  STRESS ..."
        if line.startswith(" -4") and current is not None:
            block_name = line[5:].split()[0].upper() if len(line) > 5 else ""
            i += 1

            # Skip component header lines (" -5 ...")
            while i < len(lines) and lines[i].startswith(" -5"):
                i += 1

            # Read data lines (" -1" prefix, fixed-width)
            while i < len(lines) and lines[i].startswith(" -1"):
                parsed = _parse_data_line(lines[i])
                if parsed is None:
                    i += 1
                    continue
                nid, values = parsed

                if block_name in ("DISP", "U"):
                    current.displacements[nid] = values[:3]
                elif block_name in ("STRESS", "S"):
                    current.stresses[nid] = values[:6]
                elif block_name in ("FORC", "RF"):
                    current.forces[nid] = values[:3]

                i += 1
            continue

        # End of file marker
        if line.startswith("9999"):
            break

        i += 1

    return increments


def read_keq_results(path: str | Path) -> list[KEQIncrement]:
    """
    Parse KEQ output blocks from a *CRACK PROPAGATION .frd file.

    CalculiX writes all KEQ fields as components of a SINGLE -4 result
    block (typically named ``CT3D-MIS``).  The -5 header lines list
    component names such as DeltaKEQ, KEQMIN, …, CRLENGTH, DOM_SLIP.
    Each node's data spans multiple lines (6 values per -1/-2 line):

        -4  CT3D-MIS   15    1
        -5  DOM_STEP    …
        -5  DeltaKEQ    …
        …   (15 component headers)
        -1  <nid> v1 v2 v3 v4 v5 v6
        -2        v7 v8 v9 v10 v11 v12
        -2        v13 v14 v15
        -1  <nid> …
    """
    path = Path(path)

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    keq_map: dict[tuple[int, int], KEQIncrement] = {}
    current_step = 0
    current_inc  = 0
    current_time = 0.0

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # Increment header:  "    1PSTEP ... <step> <numinc> <inc>"
        if line.startswith("    1") and "STEP" in line.upper():
            parts = line.split()
            try:
                current_step = int(parts[1]) if len(parts) > 1 else 0
                current_inc  = int(parts[2]) if len(parts) > 2 else 0
                current_time = float(parts[3]) if len(parts) > 3 else 0.0
            except (ValueError, IndexError):
                current_step, current_inc, current_time = 0, 0, 0.0
            i += 1
            continue

        # Result block header: " -4  <name>  <ncomps>  <ictype>"
        if line.startswith(" -4"):
            i += 1

            # Read component names from -5 header lines
            comp_names: list[str] = []
            while i < n and lines[i].startswith(" -5"):
                raw = lines[i][5:].split()[0] if len(lines[i]) > 5 else ""
                comp_names.append(raw)
                i += 1

            # Detect KEQ block: must contain at least DeltaKEQ and KEQMAX
            upper_names = [c.upper() for c in comp_names]
            # Normalise: "DeltaKEQ" → "DELTAKEQ", "PHI(DEG)" → "PHI"
            has_keq = any("DELTAKEQ" in c for c in upper_names) and \
                      any("KEQMAX" in c for c in upper_names)

            if not has_keq:
                # Not a KEQ block — skip its data lines
                while i < n and (lines[i].startswith(" -1") or lines[i].startswith(" -2")):
                    i += 1
                continue

            # Normalise component names to our canonical KEQ_FIELDS names
            norm_names = _normalise_comp_names(comp_names)
            ncomps = len(norm_names)

            key = (current_step, current_inc)
            if key not in keq_map:
                keq_map[key] = KEQIncrement(current_step, current_inc, current_time)
            keq_inc = keq_map[key]

            # Read multi-line node data
            while i < n and lines[i].startswith(" -1"):
                # First line: " -1  <nid>  v1 v2 v3 v4 v5 v6"
                parsed = _parse_data_line(lines[i])
                i += 1
                if parsed is None:
                    continue
                nid, vals = parsed
                all_vals = list(vals)

                # Continuation lines (" -2 ...")
                while i < n and lines[i].startswith(" -2"):
                    cparts = lines[i].split()
                    for v in cparts[1:]:
                        try:
                            all_vals.append(float(v))
                        except ValueError:
                            # Handle packed format: "-1.23E+01-4.56E+02"
                            import re
                            for m in re.finditer(r'[+-]?\d+\.?\d*[eE][+-]?\d+', v):
                                all_vals.append(float(m.group()))
                    i += 1

                # Map values to component names
                node_data: dict[str, float] = {}
                for ci in range(min(ncomps, len(all_vals))):
                    name = norm_names[ci]
                    if name:   # skip unmapped components
                        node_data[name] = all_vals[ci]

                if node_data:
                    keq_inc.keq_data[nid] = node_data

            continue

        if line.startswith("9999"):
            break

        i += 1

    return [keq_map[k] for k in sorted(keq_map.keys())]


def _normalise_comp_names(raw_names: list[str]) -> list[str]:
    """Map raw FRD -5 component names to canonical KEQ_FIELDS names.

    CalculiX writes e.g. ``DeltaKEQ``, ``PHI(DEG)``, ``DOM_STEP``.
    We normalise to the uppercase names in KEQ_FIELDS, plus keep
    DOM_STEP and DOM_SLIP as-is for completeness.
    """
    # Build lookup from uppercase variants to canonical name
    canonical = {f.upper(): f for f in KEQ_FIELDS}
    # Extra aliases
    canonical["DOM_STEP"]  = "DOM_STEP"
    canonical["DOM_SLIP"]  = "DOM_SLIP"
    canonical["PHI(DEG)"]  = "PHI"
    canonical["PHI"]       = "PHI"
    canonical["DELTAKEQ"]  = "DELTAKEQ"

    result: list[str] = []
    for raw in raw_names:
        key = raw.upper().strip()
        if key in canonical:
            result.append(canonical[key])
        else:
            # Try partial match (e.g. "DeltaKEQ" → "DELTAKEQ")
            matched = ""
            for ckey, cval in canonical.items():
                if key == ckey or key.replace("(", "").replace(")", "") == ckey:
                    matched = cval
                    break
            result.append(matched)
    return result


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# FRD mesh geometry (node coords + element connectivity from 2C/3C sections)
# ---------------------------------------------------------------------------

@dataclass
class FrdMesh:
    """Node coordinates and element connectivity from the 2C/3C sections of a
    CalculiX FRD file.  Used for visualisation only — not analysis."""
    nodes:      dict[int, np.ndarray]        # nid → (3,) xyz
    elements:   dict[int, list[int]]         # eid → [nid, nid, ...]
    elem_types: dict[int, int] | None = None # eid → FRD numeric type (1-12)


# FRD numeric element type → number of -2 continuation lines
_FRD_ETYPE_NLINES = {
    1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1,
    7: 1, 8: 1, 9: 1, 10: 1, 11: 1, 12: 1,
}


def read_frd_mesh(path: str | Path) -> FrdMesh:
    """Parse node coordinates (2C) and element connectivity (3C) from an FRD file.

    Returns an FrdMesh with ``nodes``, ``elements``, and ``elem_types``
    populated.  ``elem_types`` maps eid → FRD numeric element type code
    (1 = C3D8, 4 = C3D20, etc.) so the caller can apply the correct
    FRD→VTK node reordering.
    """
    path = Path(path)
    nodes:      dict[int, np.ndarray] = {}
    elements:   dict[int, list[int]]  = {}
    elem_types: dict[int, int]        = {}

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    i = 0
    in_node_section = False
    in_elem_section = False
    current_eid:   int | None = None
    current_etype: int = 0
    current_nids:  list[int] = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Node coordinates section header  "    2C ..."
        if stripped.startswith("2C"):
            in_node_section = True
            in_elem_section = False
            i += 1
            continue

        # Element connectivity section header  "    3C ..."
        if stripped.startswith("3C"):
            # Flush any pending element
            if current_eid is not None and current_nids:
                elements[current_eid] = current_nids
                elem_types[current_eid] = current_etype
                current_eid = None
                current_nids = []
            in_elem_section = True
            in_node_section = False
            i += 1
            continue

        # End of node or element section when we hit a different section code
        if stripped and stripped[0].isdigit() and not stripped.startswith("2C") and not stripped.startswith("3C"):
            if in_node_section or in_elem_section:
                # Flush
                if current_eid is not None and current_nids:
                    elements[current_eid] = current_nids
                    elem_types[current_eid] = current_etype
                    current_eid = None
                    current_nids = []
                in_node_section = False
                in_elem_section = False

        if line.startswith("9999"):
            break

        # Node data line  " -1<10 char nid><12 char x><12 char y><12 char z>"
        if in_node_section and line.startswith(" -1"):
            parsed = _parse_data_line(line)
            if parsed is not None:
                nid, vals = parsed
                if len(vals) >= 3:
                    nodes[nid] = vals[:3]
            i += 1
            continue

        # Element -1 header:  " -1  <eid>  <etype>  <group>  <mat>"
        if in_elem_section and line.startswith(" -1"):
            if current_eid is not None and current_nids:
                elements[current_eid] = current_nids
                elem_types[current_eid] = current_etype
            parts = line.split()
            try:
                current_eid   = int(parts[1])
                current_etype = int(parts[2]) if len(parts) > 2 else 0
            except (ValueError, IndexError):
                current_eid   = None
                current_etype = 0
            current_nids = []
            i += 1
            continue

        # Element -2 connectivity line (node IDs, up to 10 per line)
        if in_elem_section and line.startswith(" -2"):
            parts = line.split()
            try:
                current_nids.extend(int(p) for p in parts[1:])
            except ValueError:
                pass
            i += 1
            continue

        i += 1

    # Flush last element
    if current_eid is not None and current_nids:
        elements[current_eid] = current_nids
        elem_types[current_eid] = current_etype

    return FrdMesh(nodes=nodes, elements=elements, elem_types=elem_types)


def get_last_displacements(path: str | Path) -> dict[int, np.ndarray]:
    """Convenience: return displacement dict from the last increment."""
    incs = read_frd(path)
    if not incs:
        return {}
    return incs[-1].displacements


def get_last_forces(path: str | Path) -> dict[int, np.ndarray]:
    """Convenience: return nodal forces from the last increment."""
    incs = read_frd(path)
    if not incs:
        return {}
    return incs[-1].forces


def get_last_stresses(path: str | Path) -> dict[int, np.ndarray]:
    """Convenience: return stress dict from the last increment."""
    incs = read_frd(path)
    if not incs:
        return {}
    return incs[-1].stresses


def extract_front_displacements(
    path: str | Path,
    front_node_ids: list[int],
) -> np.ndarray:
    """
    Read displacements for specific crack-front node IDs from the last increment.

    Returns (N, 3) array. Nodes not found get zero displacement (with a warning).
    """
    import warnings
    incs = read_frd(path)
    if not incs:
        return np.zeros((len(front_node_ids), 3))

    disp = incs[-1].displacements
    result = np.zeros((len(front_node_ids), 3))
    missing = []
    for idx, nid in enumerate(front_node_ids):
        if nid in disp:
            result[idx] = disp[nid]
        else:
            missing.append(nid)

    if missing:
        warnings.warn(
            f"extract_front_displacements: {len(missing)} of "
            f"{len(front_node_ids)} front nodes not found in FRD "
            f"(e.g. node {missing[0]}). Zero displacement assumed.",
            UserWarning,
            stacklevel=2,
        )
    return result
