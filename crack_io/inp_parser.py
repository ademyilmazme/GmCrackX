"""
Parse a CalculiX .inp file into a MeshData object.

Supported keywords:
  *NODE, *ELEMENT, *NSET, *ELSET, *BOUNDARY, *CLOAD,
  *MATERIAL, *ELASTIC, *INCLUDE
"""
from __future__ import annotations
import re
from pathlib import Path

from core.mesh_io import MeshData, Node, Element


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_params(header: str) -> dict[str, str]:
    """Parse 'KEYWORD, KEY=VAL, KEY2=VAL2' into {'key': 'val', ...}."""
    parts = [p.strip() for p in header.split(",")]
    params: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.strip().upper()] = v.strip().upper()
        else:
            params[p.upper()] = ""
    return params


def _is_keyword(line: str) -> bool:
    """True for *KEYWORD lines (not ** comments)."""
    return line.startswith("*") and not line.startswith("**")


def _is_blank_or_comment(line: str) -> bool:
    """True for empty lines and ** comment lines — skip in data blocks."""
    return not line or line.startswith("**")


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_inp(path: str | Path) -> MeshData:
    """
    Read a CalculiX .inp file and return a populated MeshData.
    Handles *INCLUDE recursively.
    """
    path = Path(path)
    lines = _resolve_includes(path)
    return _parse_lines(lines, path.parent)


def _resolve_includes(path: Path) -> list[str]:
    lines: list[str] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.upper().startswith("*INCLUDE"):
                params = _split_params(stripped)
                inc_file = params.get("INPUT", "")
                inc_file = inc_file.strip("'\"")
                inc_path = path.parent / inc_file
                lines.extend(_resolve_includes(inc_path))
            else:
                lines.append(stripped)
    return lines


def _parse_lines(lines: list[str], base_dir: Path) -> MeshData:
    mesh = MeshData()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip blank lines and comments in the top-level loop
        if _is_blank_or_comment(line):
            i += 1
            continue

        if not _is_keyword(line):
            i += 1
            continue

        upper = line.upper()

        # ------------------------------------------------------------------
        # *NODE
        # ------------------------------------------------------------------
        if re.match(r"\*NODE\b", upper):
            params = _split_params(line)
            nset = params.get("NSET", "")
            i += 1
            collected: list[int] = []
            while i < len(lines) and not _is_keyword(lines[i]):
                ln = lines[i]
                i += 1
                if _is_blank_or_comment(ln):
                    continue
                parts = ln.split(",")
                if len(parts) >= 4:
                    nid = int(parts[0].strip())
                    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                    mesh.nodes[nid] = Node(nid, x, y, z)
                    collected.append(nid)
            if nset:
                mesh.node_sets.setdefault(nset, []).extend(collected)

        # ------------------------------------------------------------------
        # *ELEMENT
        # ------------------------------------------------------------------
        elif re.match(r"\*ELEMENT\b", upper):
            params = _split_params(line)
            etype = params.get("TYPE", "C3D4")
            elset = params.get("ELSET", "")
            i += 1
            collected_el: list[int] = []
            while i < len(lines) and not _is_keyword(lines[i]):
                ln = lines[i]
                if _is_blank_or_comment(ln):
                    i += 1
                    continue
                # Connectivity may span multiple lines (continuation with comma at end)
                raw = ln
                while raw.rstrip().endswith(",") and i + 1 < len(lines) and not _is_keyword(lines[i + 1]):
                    i += 1
                    next_ln = lines[i]
                    if _is_blank_or_comment(next_ln):
                        break
                    raw += next_ln
                i += 1
                parts = [p.strip() for p in raw.split(",") if p.strip()]
                if parts:
                    try:
                        eid = int(parts[0])
                        nodes = [int(p) for p in parts[1:]]
                        mesh.elements[eid] = Element(eid, etype, nodes)
                        collected_el.append(eid)
                    except ValueError:
                        pass  # skip malformed lines
            if elset:
                mesh.element_sets.setdefault(elset, []).extend(collected_el)

        # ------------------------------------------------------------------
        # *NSET
        # ------------------------------------------------------------------
        elif re.match(r"\*NSET\b", upper):
            params = _split_params(line)
            name = params.get("NSET", "UNNAMED")
            generate = "GENERATE" in params
            i += 1
            ids: list[int] = []
            while i < len(lines) and not _is_keyword(lines[i]):
                ln = lines[i]
                i += 1
                if _is_blank_or_comment(ln):
                    continue
                parts = [p.strip() for p in ln.split(",") if p.strip()]
                if generate and len(parts) == 3:
                    start, stop, step = int(parts[0]), int(parts[1]), int(parts[2])
                    ids.extend(range(start, stop + 1, step))
                else:
                    for p in parts:
                        try:
                            ids.append(int(p))
                        except ValueError:
                            pass
            mesh.node_sets.setdefault(name, []).extend(ids)

        # ------------------------------------------------------------------
        # *ELSET
        # ------------------------------------------------------------------
        elif re.match(r"\*ELSET\b", upper):
            params = _split_params(line)
            name = params.get("ELSET", "UNNAMED")
            generate = "GENERATE" in params
            i += 1
            ids = []
            while i < len(lines) and not _is_keyword(lines[i]):
                ln = lines[i]
                i += 1
                if _is_blank_or_comment(ln):
                    continue
                parts = [p.strip() for p in ln.split(",") if p.strip()]
                if generate and len(parts) == 3:
                    start, stop, step = int(parts[0]), int(parts[1]), int(parts[2])
                    ids.extend(range(start, stop + 1, step))
                else:
                    for p in parts:
                        try:
                            ids.append(int(p))
                        except ValueError:
                            pass
            mesh.element_sets.setdefault(name, []).extend(ids)

        # ------------------------------------------------------------------
        # *BOUNDARY
        # ------------------------------------------------------------------
        elif re.match(r"\*BOUNDARY\b", upper):
            i += 1
            while i < len(lines) and not _is_keyword(lines[i]):
                ln = lines[i]
                i += 1
                if _is_blank_or_comment(ln):
                    continue
                parts = [p.strip() for p in ln.split(",")]
                if len(parts) >= 3:
                    try:
                        set_name = parts[0]
                        dof_first = int(parts[1])
                        dof_last  = int(parts[2])
                        value = float(parts[3]) if len(parts) > 3 and parts[3] else 0.0
                        for dof in range(dof_first, dof_last + 1):
                            mesh.boundaries.setdefault(set_name, []).append((dof, value))
                    except ValueError:
                        pass

        # ------------------------------------------------------------------
        # *CLOAD
        # ------------------------------------------------------------------
        elif re.match(r"\*CLOAD\b", upper):
            i += 1
            while i < len(lines) and not _is_keyword(lines[i]):
                ln = lines[i]
                i += 1
                if _is_blank_or_comment(ln):
                    continue
                parts = [p.strip() for p in ln.split(",")]
                if len(parts) >= 3:
                    try:
                        set_name = parts[0]
                        dof = int(parts[1])
                        mag = float(parts[2])
                        mesh.cloads.setdefault(set_name, []).append((dof, mag))
                    except ValueError:
                        pass

        # ------------------------------------------------------------------
        # *MATERIAL + *ELASTIC (simplified: store E, nu)
        # ------------------------------------------------------------------
        elif re.match(r"\*MATERIAL\b", upper):
            params = _split_params(line)
            mat_name = params.get("NAME", "MATERIAL")
            mesh.materials[mat_name] = {}
            i += 1
            # Skip non-keyword lines until we hit a keyword
            while i < len(lines) and not _is_keyword(lines[i]):
                i += 1
            # Look ahead for *ELASTIC inside this material block
            while i < len(lines):
                kw = lines[i].upper()
                if _is_blank_or_comment(lines[i]):
                    i += 1
                elif re.match(r"\*ELASTIC\b", kw):
                    i += 1
                    while i < len(lines) and not _is_keyword(lines[i]):
                        ln = lines[i]
                        i += 1
                        if _is_blank_or_comment(ln):
                            continue
                        parts = [p.strip() for p in ln.split(",")]
                        if len(parts) >= 2:
                            try:
                                mesh.materials[mat_name]["E"]  = float(parts[0])
                                mesh.materials[mat_name]["nu"] = float(parts[1])
                            except ValueError:
                                pass
                        break  # only first data line under *ELASTIC
                elif _is_keyword(lines[i]) and not re.match(
                        r"\*(ELASTIC|DENSITY|PLASTIC|EXPANSION|CONDUCTIVITY|SPECIFIC)", kw):
                    break
                else:
                    i += 1

        else:
            i += 1

    return mesh
