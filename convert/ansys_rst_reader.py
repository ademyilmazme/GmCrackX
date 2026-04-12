"""
ANSYS Mechanical RST result reader — MVP scope.

Converts an ANSYS binary RST file into a :class:`~convert.neutral_model.NeutralModel`
using the *ansys-mapdl-reader* library (``pip install ansys-mapdl-reader``).

MVP supported element types (3-D solid elements for CalculiX crack propagation):
    SOLID185  — 8-node linear hexahedron  → C3D8
    SOLID186  — 20-node quadratic hexahedron → C3D20
    SOLID187  — 10-node quadratic tetrahedron → C3D10
    SOLID92   — 10-node quadratic tet (legacy) → C3D10
    SOLID95   — 20-node quadratic hex (legacy) → C3D20

All other element types are skipped:
    • Contact / surface auxiliary elements (SURF154, TARGE170, CONTA17x) are
      silently skipped — they routinely appear alongside volume meshes.
    • Any other unsupported type generates an :class:`UnsupportedElementWarning`
      so the caller is aware of what was dropped.

Conversion fails with :class:`ValueError` if no supported solid elements
remain after filtering.

Temperature results (NDTEMP) are included when present.
ANSYS → CalculiX node-ordering remaps are applied as needed.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np

from .base_reader import BaseResultReader
from .neutral_model import (
    NeutralElement,
    NeutralElementType,
    NeutralIncrement,
    NeutralMetadata,
    NeutralModel,
    NeutralNode,
    NeutralResultField,
)


# ---------------------------------------------------------------------------
# Warning class
# ---------------------------------------------------------------------------

class UnsupportedElementWarning(UserWarning):
    """Issued when ANSYS elements of unsupported types are skipped.

    Only raised for element types that are not explicitly known to be
    auxiliary (contact/surface).  Inspect the warning message for the
    ANSYS element type numbers and counts that were dropped.
    """


# ---------------------------------------------------------------------------
# MVP element-type map
# ---------------------------------------------------------------------------
# Maps ANSYS element type number → (NeutralElementType, node_reorder).
# node_reorder is a list of 0-based indices that re-sequences ANSYS
# connectivity to match CalculiX ordering.  None = same ordering.
#
# Only 3-D solid elements required by CalculiX crack propagation are listed.
# Extend this dict in future versions to add shell / beam / other solids.

_ANSYS_ETYPE_MAP: dict[int, tuple[NeutralElementType, list[int] | None]] = {
    # SOLID185 — 8-node linear brick (same corner order as C3D8)
    185: (NeutralElementType.C3D8,  None),
    # SOLID186 — 20-node quadratic brick (same order as C3D20)
    186: (NeutralElementType.C3D20, None),
    # SOLID95  — 20-node quadratic brick, legacy (same order as C3D20)
    95:  (NeutralElementType.C3D20, None),
    # SOLID187 — 10-node quadratic tet (same order as C3D10)
    187: (NeutralElementType.C3D10, None),
    # SOLID92  — 10-node quadratic tet, legacy (same order as C3D10)
    92:  (NeutralElementType.C3D10, None),
}

# ANSYS element types that are always auxiliary and silently skipped.
# These routinely appear in ANSYS models alongside volume elements.
_SILENT_SKIP_ETYPES: frozenset[int] = frozenset({
    154,  # SURF154   — surface-effect (load application)
    170,  # TARGE170  — contact target surface
    174,  # CONTA174  — surface-to-surface contact
    175,  # CONTA175  — node-to-surface contact
    176,  # CONTA176  — node-to-surface contact (line)
    177,  # CONTA177  — edge-to-edge contact
    178,  # CONTA178  — node-to-node contact
})

# Fields we know how to extract from the RST reader
_KNOWN_FIELDS = {"DISP", "STRESS", "NDTEMP"}

# ---------------------------------------------------------------------------
# Midside-edge tables for quadratic element types
# ---------------------------------------------------------------------------
# Maps NeutralElementType → {midside_local_index: (cornerA_local_idx, cornerB_local_idx)}
# Used by _build_midside_map() to derive midside_nid → (cornerA_nid, cornerB_nid) from
# element connectivity, so that result fields can be linearly interpolated at midside nodes.
#
# ANSYS only writes stress / temperature results at corner nodes of quadratic elements.
# Midside nodes receive NaN from PyAnsys and must be approximated before writing FRD.
#
# C3D20 corners   (local 0-7):  I J K L M N O P
# C3D20 midsides  (local 8-19): Q R S T U V W X Y Z A B
#   Q(8)  = mid(I,J)  = mid(0,1)    R(9)  = mid(J,K)  = mid(1,2)
#   S(10) = mid(K,L)  = mid(2,3)    T(11) = mid(L,I)  = mid(3,0)
#   U(12) = mid(M,N)  = mid(4,5)    V(13) = mid(N,O)  = mid(5,6)
#   W(14) = mid(O,P)  = mid(6,7)    X(15) = mid(P,M)  = mid(7,4)
#   Y(16) = mid(I,M)  = mid(0,4)    Z(17) = mid(J,N)  = mid(1,5)
#   A(18) = mid(K,O)  = mid(2,6)    B(19) = mid(L,P)  = mid(3,7)
#
# C3D10 corners   (local 0-3):  I J K L
# C3D10 midsides  (local 4-9):  M N O P Q R
#   M(4) = mid(I,J) = mid(0,1)    N(5) = mid(J,K) = mid(1,2)
#   O(6) = mid(K,I) = mid(2,0)    P(7) = mid(I,L) = mid(0,3)
#   Q(8) = mid(J,L) = mid(1,3)    R(9) = mid(K,L) = mid(2,3)

_MIDSIDE_EDGES: dict[NeutralElementType, dict[int, tuple[int, int]]] = {
    NeutralElementType.C3D20: {
         8: (0, 1),  9: (1, 2), 10: (2, 3), 11: (3, 0),
        12: (4, 5), 13: (5, 6), 14: (6, 7), 15: (7, 4),
        16: (0, 4), 17: (1, 5), 18: (2, 6), 19: (3, 7),
    },
    NeutralElementType.C3D10: {
        4: (0, 1),  5: (1, 2),  6: (2, 0),
        7: (0, 3),  8: (1, 3),  9: (2, 3),
    },
}


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

class AnsysRstReader(BaseResultReader):
    """Read ANSYS Mechanical RST binary files via *ansys-mapdl-reader*."""

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @classmethod
    def can_read(cls, path: str | Path) -> bool:
        """Return True for *.rst* files (case-insensitive)."""
        try:
            return Path(path).suffix.lower() == ".rst"
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def inspect(self, path: str | Path) -> dict:
        """Return lightweight metadata without parsing all results.

        The returned dict always contains:
            ``solver``                  "ANSYS"
            ``source_file``             str path
            ``n_nodes``                 total node count
            ``n_elements``              total element count (including unsupported)
            ``n_supported_elements``    count of MVP solid elements
            ``n_increments``            number of result sets
            ``fields``                  list of available field names
            ``ansys_element_types``     dict ANSYS-type → count (all types present)
            ``unsupported_element_types`` list of non-MVP, non-auxiliary type numbers
        """
        try:
            rst = self._open(path)
        except Exception as exc:
            return {"error": str(exc)}

        info: dict[str, Any] = {
            "solver": "ANSYS",
            "source_file": str(path),
        }
        try:
            info["n_nodes"] = rst.mesh.n_node
            info["n_elements"] = rst.mesh.n_elem
        except Exception:
            pass
        try:
            info["n_increments"] = rst.nsets
        except Exception:
            pass

        # Element-type breakdown — early detection of unsupported types
        try:
            etype_arr: np.ndarray = rst.mesh.etype
            type_counts: dict[int, int] = {}
            for et in etype_arr.tolist():
                key = int(et)
                type_counts[key] = type_counts.get(key, 0) + 1
            info["ansys_element_types"] = type_counts

            n_supported = sum(
                cnt for et, cnt in type_counts.items()
                if et in _ANSYS_ETYPE_MAP
            )
            info["n_supported_elements"] = n_supported

            unsupported = sorted(
                et for et in type_counts
                if et not in _ANSYS_ETYPE_MAP and et not in _SILENT_SKIP_ETYPES
            )
            info["unsupported_element_types"] = unsupported
        except Exception:
            info.setdefault("ansys_element_types", {})
            info.setdefault("n_supported_elements", 0)
            info.setdefault("unsupported_element_types", [])

        fields: list[str] = []
        try:
            if rst.nsets > 0:
                if rst.nodal_solution(0) is not None:
                    fields.append("DISP")
                try:
                    if rst.nodal_stress(0) is not None:
                        fields.append("STRESS")
                except Exception:
                    pass
                try:
                    if rst.nodal_temperature(0) is not None:
                        fields.append("NDTEMP")
                except Exception:
                    pass
        except Exception:
            pass
        info["fields"] = fields
        return info

    # ------------------------------------------------------------------
    # Full conversion
    # ------------------------------------------------------------------

    def read(
        self,
        path: str | Path,
        fields: list[str] | None = None,
        increments: list[int] | None = None,
    ) -> NeutralModel:
        """Parse the RST file and return a NeutralModel."""
        rst = self._open(path)

        want_fields = {f.upper() for f in fields} if fields else _KNOWN_FIELDS
        want_incs = set(increments) if increments is not None else None

        model = NeutralModel(
            metadata=NeutralMetadata(
                source_solver="ANSYS",
                source_file=str(path),
                title=Path(path).stem,
            )
        )

        # --- Mesh ---
        self._read_mesh(rst, model)

        # Build midside interpolation map once from element connectivity.
        # C3D20 and C3D10 elements store ANSYS results only at corner nodes;
        # midside nodes receive NaN from PyAnsys and are filled by linear
        # interpolation: v_mid = (v_A + v_B) / 2 for the adjacent corners A, B.
        midside_map = self._build_midside_map(model)

        # --- Results ---
        n_sets = getattr(rst, "nsets", 0)
        for i in range(n_sets):
            if want_incs is not None and i not in want_incs:
                continue
            inc = self._read_increment(rst, i, want_fields, midside_map=midside_map)
            if inc is not None:
                model.increments.append(inc)

        return model

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _open(path: str | Path):
        """Import ansys-mapdl-reader and open the RST file.

        ansys-mapdl-reader 0.55 has two compatibility issues with newer
        pyvista / older VTK environments:

        1. ``__init__.py`` tries ``from pyvista.utilities.sphinx_gallery import
           _get_sg_image_scraper`` — removed in pyvista >= 0.44.
        2. ``_configure_pyvista()`` accesses ``pv.global_theme`` which lazily
           imports ``pyvista.plotting``, which in turn imports
           ``vtkmodules.vtkRenderingMatplotlib`` — not present in VTK 9.3.x.

        We inject minimal stubs into ``sys.modules`` before the first import so
        all of the above succeed without actually loading any rendering code.
        We only need the binary-reader backend, not pyvista visualisation.
        """
        import sys
        import types

        def _stub(name: str, parent: str | None = None) -> types.ModuleType:
            mod = types.ModuleType(name)
            mod.__path__ = []  # type: ignore[attr-defined]
            sys.modules[name] = mod
            if parent and parent in sys.modules:
                setattr(sys.modules[parent], name.rsplit(".", 1)[-1], mod)
            return mod

        # ── Patch 1: pyvista.utilities.sphinx_gallery ──────────────────────
        # ansys.mapdl.reader.__init__ falls back to this import when
        # pyvista.plotting.utilities._get_sg_image_scraper is missing.
        if "pyvista.utilities.sphinx_gallery" not in sys.modules:
            if "pyvista.utilities" not in sys.modules:
                _stub("pyvista.utilities")
            sg = _stub("pyvista.utilities.sphinx_gallery", "pyvista.utilities")
            sg._get_sg_image_scraper = lambda: None  # type: ignore[attr-defined]

        # Also patch the attribute directly in case pyvista.plotting.utilities
        # is already loaded but lacks the symbol.
        try:
            import pyvista.plotting.utilities as _pvu  # type: ignore
            if not hasattr(_pvu, "_get_sg_image_scraper"):
                _pvu._get_sg_image_scraper = lambda: None
        except Exception:
            pass

        # ── Patch 2: vtkmodules.vtkRenderingMatplotlib ─────────────────────
        # pyvista.plotting._vtk does `import vtkmodules.vtkRenderingMatplotlib`
        # as a side-effect import (F401).  The module does not exist in VTK
        # 9.3.x (only in VTK 9.4+).  Inject an empty stub so the import
        # succeeds without loading any real rendering code.
        if "vtkmodules.vtkRenderingMatplotlib" not in sys.modules:
            _stub("vtkmodules.vtkRenderingMatplotlib", "vtkmodules")

        try:
            from ansys.mapdl.reader.common import read_binary  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "ansys-mapdl-reader is required to read ANSYS RST files.\n"
                f"Install it with:  pip install ansys-mapdl-reader\n"
                f"(underlying error: {exc})"
            ) from None
        return read_binary(str(path))

    def _read_mesh(self, rst, model: NeutralModel) -> None:
        """Populate model.nodes and model.elements from the RST mesh.

        Raises
        ------
        ValueError
            If the RST contains no supported MVP solid elements at all.

        Warns
        -----
        UnsupportedElementWarning
            For each non-auxiliary ANSYS element type that is skipped because
            it is not in the MVP supported set.
        """
        mesh = rst.mesh

        # -- Nodes --
        nnum: np.ndarray = mesh.nnum     # (N,) node numbers
        coords: np.ndarray = mesh.nodes  # (N, 3) xyz
        for nid, (x, y, z) in zip(nnum.tolist(), coords.tolist()):
            model.nodes[nid] = NeutralNode(id=nid, x=x, y=y, z=z)

        # -- Elements --
        # ansys-mapdl-reader 0.55 API:
        #   mesh.etype  — per-element ANSYS element type number (e.g. 186, 154)
        #   mesh.enum   — (E,) element numbers
        #   mesh.elem   — list of arrays: [8 headers, eid, 0, n1, n2, ..., nN]
        #                 Node IDs start at index 10.
        enum: np.ndarray     = mesh.enum
        etype_arr: np.ndarray = mesh.etype
        econn: list           = mesh.elem

        # Accumulate skip counts by ANSYS element type for end-of-loop warning
        skipped: dict[int, int] = {}  # ansys_etype → skip count
        n_supported = 0

        for eid, ansys_etype, conn in zip(enum.tolist(), etype_arr.tolist(), econn):
            ansys_etype_int = int(ansys_etype)
            mapping = _ANSYS_ETYPE_MAP.get(ansys_etype_int)
            if mapping is None:
                skipped[ansys_etype_int] = skipped.get(ansys_etype_int, 0) + 1
                continue

            neutral_etype, reorder = mapping
            # conn format: [mat, type, real, sect, esys, death, solid, tshape,
            #               eid, 0, n1, n2, ..., nN]
            nids: list[int] = [int(n) for n in conn[10:] if n > 0]
            if reorder is not None:
                try:
                    nids = [nids[r] for r in reorder]
                except IndexError:
                    pass  # leave as-is if reorder fails

            model.elements[int(eid)] = NeutralElement(
                id=int(eid),
                etype=neutral_etype,
                node_ids=nids,
            )
            n_supported += 1

        # -- Validation: must have at least one supported element --
        if n_supported == 0:
            found_types = sorted(skipped.keys())
            supported_names = "SOLID185, SOLID186, SOLID95, SOLID187, SOLID92"
            raise ValueError(
                f"No MVP solid elements found in RST file. "
                f"Supported types: {supported_names} "
                f"(ANSYS type numbers {sorted(_ANSYS_ETYPE_MAP)}). "
                f"File contains ANSYS element types: {found_types}. "
                f"Non-solid elements (shells, beams, contact) are not supported "
                f"in the MVP conversion."
            )

        # -- Warn about non-auxiliary unsupported types --
        unsupported = {
            et: cnt for et, cnt in skipped.items()
            if et not in _SILENT_SKIP_ETYPES
        }
        if unsupported:
            summary = ", ".join(
                f"type {et} ({cnt} elem)" for et, cnt in sorted(unsupported.items())
            )
            warnings.warn(
                f"Skipped unsupported ANSYS element types (MVP supports 3-D solid "
                f"elements only: SOLID185/186/95/187/92): {summary}",
                UnsupportedElementWarning,
                stacklevel=3,
            )

    @staticmethod
    def _build_midside_map(model: NeutralModel) -> dict[int, tuple[int, int]]:
        """Return midside_nid → (cornerA_nid, cornerB_nid) for all quadratic elements.

        Iterates every C3D20 and C3D10 element in *model* and records which
        global node IDs sit at each midside position and which two corner node
        IDs bound that edge.  The result is consumed by :meth:`_read_increment`
        to linearly interpolate result values at midside nodes.

        If the same midside node appears in multiple elements (shared face), the
        last entry wins — adjacent corner nodes are the same regardless.
        """
        midside_map: dict[int, tuple[int, int]] = {}
        for elem in model.elements.values():
            edge_table = _MIDSIDE_EDGES.get(elem.etype)
            if edge_table is None:
                continue
            nids = elem.node_ids
            for mid_local, (ca_local, cb_local) in edge_table.items():
                if mid_local >= len(nids) or ca_local >= len(nids) or cb_local >= len(nids):
                    continue  # degenerate element — skip
                midside_map[nids[mid_local]] = (nids[ca_local], nids[cb_local])
        return midside_map

    def _read_increment(
        self,
        rst,
        index: int,
        want_fields: set[str],
        midside_map: dict[int, tuple[int, int]] | None = None,
    ) -> NeutralIncrement | None:
        """Extract one result set from the RST reader."""
        try:
            time_val: float = float(rst.time_values[index])
        except (IndexError, AttributeError):
            time_val = float(index)

        inc = NeutralIncrement(
            step=1,
            increment=index + 1,
            total_time=time_val,
        )

        has_data = False

        # -- Displacements --
        if "DISP" in want_fields:
            try:
                nnum, disp = rst.nodal_solution(index)
                # disp shape: (N, 3) or (N, 6) — take first 3
                data: dict[int, np.ndarray] = {}
                for nid, d in zip(nnum.tolist(), disp.tolist()):
                    data[int(nid)] = np.asarray(d[:3], dtype=float)
                inc.fields["DISP"] = NeutralResultField(
                    name="DISP",
                    component_names=["D1", "D2", "D3"],
                    data=data,
                )
                has_data = True
            except Exception as exc:
                warnings.warn(
                    f"DISP extraction failed for increment {index}: {exc}",
                    UserWarning,
                    stacklevel=2,
                )

        # -- Stresses --
        if "STRESS" in want_fields:
            try:
                nnum, stress = rst.nodal_stress(index)
                # stress shape: (N, 6) SXX SYY SZZ SXY SYZ SXZ
                # Surface/constraint nodes (e.g. SURF154) may have NaN —
                # skip them so the model stays valid.
                data = {}
                for nid, s in zip(nnum.tolist(), stress.tolist()):
                    arr = np.asarray(s[:6], dtype=float)
                    if np.all(np.isfinite(arr)):
                        data[int(nid)] = arr
                inc.fields["STRESS"] = NeutralResultField(
                    name="STRESS",
                    component_names=["SXX", "SYY", "SZZ", "SXY", "SYZ", "SXZ"],
                    data=data,
                )
                has_data = True
            except Exception as exc:
                warnings.warn(
                    f"STRESS extraction failed for increment {index}: {exc}",
                    UserWarning,
                    stacklevel=2,
                )

        # -- Temperatures --
        if "NDTEMP" in want_fields:
            try:
                nnum, temps = rst.nodal_temperature(index)
                data = {}
                n_total = 0
                for nid, t in zip(nnum.tolist(), temps.tolist()):
                    val = float(t if np.isscalar(t) else t[0])
                    n_total += 1
                    if np.isfinite(val):
                        data[int(nid)] = np.array([val], dtype=float)

                # Warn when coverage is partial — indicates temperature was
                # applied as a body load to a subset of elements only.
                # Root cause: ANSYS structural analysis with partial thermal
                # loading; nodes outside the loaded region return NaN from
                # PyAnsys and are skipped here (same approach as STRESS).
                if data and n_total > 0:
                    coverage = len(data) / n_total
                    if coverage < 0.99:
                        warnings.warn(
                            f"NDTEMP increment {index}: only {len(data)}/{n_total} "
                            f"nodes ({coverage:.0%}) have finite temperature values. "
                            f"Temperature was likely applied as a partial body load "
                            f"(not all elements have TEMP defined). "
                            f"NaN nodes are skipped; {len(data)} nodes written to FRD.",
                            UserWarning,
                            stacklevel=2,
                        )

                if data:
                    inc.fields["NDTEMP"] = NeutralResultField(
                        name="NDTEMP",
                        component_names=["T"],
                        data=data,
                    )
                    has_data = True
                # If every node was NaN, skip the field entirely rather than
                # writing an empty NDTEMP block to the FRD.
            except Exception:
                pass  # temperature is optional — no warning

        # -- Midside interpolation (C3D20 / C3D10) --
        # ANSYS only writes corner-node results; midside nodes have NaN in the
        # RST file.  For each midside node on edge A-B, fill the missing value
        # with v_mid = (v_A + v_B) / 2.  Applied to both STRESS and NDTEMP.
        if midside_map:
            for field_name in ("STRESS", "NDTEMP"):
                field = inc.fields.get(field_name)
                if field is None:
                    continue
                for mid_nid, (ca_nid, cb_nid) in midside_map.items():
                    if mid_nid in field.data:
                        continue  # already has a value (shouldn't happen for ANSYS)
                    ca = field.data.get(ca_nid)
                    cb = field.data.get(cb_nid)
                    if ca is not None and cb is not None:
                        field.data[mid_nid] = (ca + cb) * 0.5

        return inc if has_data else None
