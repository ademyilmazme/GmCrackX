"""
PropDeckWriter — generates a self-contained CalculiX *CRACK PROPAGATION deck.

The volume mesh (nodes + elements) is read directly from the INPUT= FRD file
(sections 2C / 3C).  The crack surface S3 elements come from the crack-surface
INP built by CrackSurfaceBuilder.  No reference INP is required.

Generated deck structure (mirrors crackIIcum.inp):

  *NODE,NSET=Nall
    <volume nodes from FRD 2C section>
    <crack surface nodes, IDs offset above volume mesh>
  *ELEMENT,TYPE=<vol_type>,ELSET=Evol
    <volume elements from FRD 3C section>
  *ELEMENT,TYPE=S3,ELSET=Eshell
    <crack surface S3 elements>
  *NSET,NSET=CRACK_FRONT
    <crack front node IDs>
  *MATERIAL,NAME=<structural_material>
  *ELASTIC
    E, nu
  *MATERIAL,NAME=<crack_material>
  *USER MATERIAL,CONSTANTS=8
    c0,c1,c2,c3,c4,c5,c6,c7
  0.
  *SOLID SECTION,ELSET=Evol,MATERIAL=<structural_material>
  *SHELL SECTION,ELSET=Eshell,MATERIAL=<structural_material>
    <thickness>
  *STEP,INC=<max_increments>
  *CRACK PROPAGATION,INPUT=<frd>,MATERIAL=<crack_material>,LENGTH=<type>
    <max_da>,<max_angle>.
  *NODE FILE
  KEQ
  *END STEP
"""
from __future__ import annotations

import os
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from pipeline.prop_config import PropagationConfig

# CalculiX element type strings keyed by node count
_NODE_COUNT_TO_ETYPE: dict[int, str] = {
    4:  "C3D4",
    6:  "C3D6",
    8:  "C3D8",
    10: "C3D10",
    15: "C3D15",
    20: "C3D20",
}

# Nodes written per continuation line (matches crackIIcum.inp style)
_NODES_PER_LINE = 10

# NSET IDs per data line
_NSET_PER_LINE = 16


class PropDeckWriter:
    """
    Write a single *CRACK PROPAGATION input deck.

    Parameters
    ----------
    config            : PropagationConfig
    crack_surface_inp : path to the S3 crack surface INP (from write_s3_inp)
    frd_path          : path to the FRD file (INPUT= and mesh source)
    """

    def __init__(
        self,
        config: PropagationConfig,
        crack_surface_inp: str,
        frd_path: str,
    ) -> None:
        self.cfg = config
        self.crack_surface_inp = str(crack_surface_inp)
        self.frd_path = str(frd_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, out_dir: str) -> str:
        """Write propagation.inp to *out_dir*. Returns the absolute path."""
        out_dir = str(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        deck_path = os.path.join(out_dir, "propagation.inp")

        # ----------------------------------------------------------
        # 1. Read volume mesh from FRD (2C nodes + 3C elements)
        # ----------------------------------------------------------
        from crack_io.frd_reader import read_frd_mesh
        frd_mesh = read_frd_mesh(self.frd_path)
        if not frd_mesh.nodes:
            raise RuntimeError(
                f"FRD file '{self.frd_path}' contains no node coordinate data "
                "(2C section missing).  Cannot build propagation deck."
            )

        # ----------------------------------------------------------
        # 2. Read crack surface mesh (S3 nodes + elements + CRACK_FRONT)
        # ----------------------------------------------------------
        from crack_io.inp_parser import parse_inp
        crack_mesh = parse_inp(self.crack_surface_inp)

        # ----------------------------------------------------------
        # 3. ID offsets so crack surface IDs don't clash with FRD
        # ----------------------------------------------------------
        node_offset = max(frd_mesh.nodes.keys())
        elem_offset = max(frd_mesh.elements.keys())

        # ----------------------------------------------------------
        # 4. Group FRD elements by element type (keyed on node count)
        # ----------------------------------------------------------
        elems_by_type: dict[str, dict[int, list[int]]] = defaultdict(dict)
        for eid, nids in frd_mesh.elements.items():
            etype = _NODE_COUNT_TO_ETYPE.get(len(nids), "C3D4")
            elems_by_type[etype][eid] = nids

        # ----------------------------------------------------------
        # 5. Copy FRD into output directory so INPUT= uses just the
        #    filename — CalculiX must be run from that same folder.
        # ----------------------------------------------------------
        frd_basename = os.path.basename(self.frd_path)
        frd_dest = os.path.join(out_dir, frd_basename)
        if os.path.abspath(self.frd_path) != os.path.abspath(frd_dest):
            shutil.copy2(self.frd_path, frd_dest)

        c0, c1, c2, c3, c4, c5, c6, c7 = self.cfg.paris_constants
        struct_mat = self.cfg.structural_material_name

        # ----------------------------------------------------------
        # 6. Write deck
        # ----------------------------------------------------------
        with open(deck_path, "w") as fh:

            # ---- header --------------------------------------------
            fh.write("**\n")
            fh.write("** GmCrackX — crack propagation deck\n")
            fh.write(f"** Generated : {datetime.now().isoformat(timespec='seconds')}\n")
            fh.write(f"** FRD       : {self.frd_path}\n")
            fh.write("**\n")

            # ---- all nodes in one block ----------------------------
            # Format matches crackIIcum.inp: nid right-justified 7 chars,
            # coordinates in %.12e (18 chars each) — total ≤ 64 chars/line,
            # well within CalculiX's 80-char field limit.
            fh.write("*NODE,NSET=Nall\n")
            for nid in sorted(frd_mesh.nodes.keys()):
                xyz = frd_mesh.nodes[nid]
                fh.write(
                    f"{nid:>7},"
                    f"{xyz[0]:.12e},"
                    f"{xyz[1]:.12e},"
                    f"{xyz[2]:.12e}\n"
                )
            for nid in sorted(crack_mesh.nodes.keys()):
                n = crack_mesh.nodes[nid]
                new_id = nid + node_offset
                fh.write(
                    f"{new_id:>7},"
                    f"{n.x:.12e},"
                    f"{n.y:.12e},"
                    f"{n.z:.12e}\n"
                )

            # ---- volume elements (one *ELEMENT block per type) -----
            for etype in sorted(elems_by_type.keys()):
                fh.write(f"*ELEMENT,TYPE={etype},ELSET=Evol\n")
                for eid in sorted(elems_by_type[etype].keys()):
                    _write_element(fh, eid, elems_by_type[etype][eid])

            # ---- crack surface S3 elements -------------------------
            fh.write("*ELEMENT,TYPE=S3,ELSET=Eshell\n")
            for eid in sorted(crack_mesh.elements.keys()):
                el = crack_mesh.elements[eid]
                offset_nids = [n + node_offset for n in el.nodes]
                _write_element(fh, eid + elem_offset, offset_nids)

            # ---- crack front NSET ----------------------------------
            front_raw = crack_mesh.node_sets.get("CRACK_FRONT", [])
            if front_raw:
                front_ids = [n + node_offset for n in front_raw]
                fh.write("*NSET,NSET=CRACK_FRONT\n")
                _write_id_list(fh, front_ids, per_line=_NSET_PER_LINE)

            fh.write("**\n")

            # ---- structural elastic material -----------------------
            fh.write(f"*MATERIAL,NAME={struct_mat}\n")
            fh.write("*ELASTIC\n")
            fh.write(f"{self.cfg.structural_elastic_E:.6g},"
                     f"{self.cfg.structural_elastic_nu:.6g}\n")
            fh.write("**\n")

            # ---- Paris-law crack material --------------------------
            fh.write(f"*MATERIAL,NAME={self.cfg.material_name}\n")
            fh.write("*USER MATERIAL,CONSTANTS=8\n")
            fh.write(
                f"{c0:.4E},{c1:.2f},{c2:.1f},{c3:.0f}.,"
                f"{c4:.2f},{c5:.0f}.,{c6:.0f}.,{c7:.1f}\n"
            )
            fh.write("0.\n")
            fh.write("**\n")

            # ---- section assignments -------------------------------
            fh.write(f"*SOLID SECTION,ELSET=Evol,MATERIAL={struct_mat}\n")
            fh.write(f"*SHELL SECTION,ELSET=Eshell,MATERIAL={struct_mat}\n")
            fh.write(f"{self.cfg.shell_thickness}\n")
            fh.write("**\n")

            # ---- propagation step ----------------------------------
            fh.write(f"*STEP,INC={self.cfg.max_increments}\n")
            fh.write(
                f"*CRACK PROPAGATION,"
                f"INPUT={frd_basename},"
                f"MATERIAL={self.cfg.material_name},"
                f"LENGTH={self.cfg.length_type}\n"
            )
            fh.write(f"{self.cfg.max_da:.6g},{self.cfg.max_angle:.6g}.\n")
            fh.write("*NODE FILE\n")
            fh.write("KEQ\n")
            fh.write("*END STEP\n")

        return os.path.abspath(deck_path)


# ---------------------------------------------------------------------------
# Low-level writers
# ---------------------------------------------------------------------------

def _write_element(fh, eid: int, nids: list[int]) -> None:
    """Write one element in CalculiX multi-line format.

    First data line: element_id + up to _NODES_PER_LINE node IDs (trailing
    comma if more nodes follow).  Continuation lines: _NODES_PER_LINE nodes
    each (trailing comma except on the last line).
    """
    all_values = [eid] + list(nids)
    # Split into chunks: first chunk has _NODES_PER_LINE + 1 values (eid + nodes)
    chunks: list[list[int]] = []
    chunks.append(all_values[:_NODES_PER_LINE + 1])
    rest = all_values[_NODES_PER_LINE + 1:]
    while rest:
        chunks.append(rest[:_NODES_PER_LINE])
        rest = rest[_NODES_PER_LINE:]

    for i, chunk in enumerate(chunks):
        is_last = (i == len(chunks) - 1)
        # Indent continuation lines to match reference style
        indent = "" if i == 0 else "       "
        values_str = ",".join(f"{v:>6}" for v in chunk)
        if is_last:
            fh.write(f"{indent}{values_str}\n")
        else:
            fh.write(f"{indent}{values_str},\n")


def _write_id_list(fh, ids: list[int], per_line: int = 16) -> None:
    """Write integer IDs *per_line* per row, comma-separated with trailing comma."""
    for i in range(0, len(ids), per_line):
        chunk = ids[i : i + per_line]
        fh.write(", ".join(str(n) for n in chunk) + ",\n")
