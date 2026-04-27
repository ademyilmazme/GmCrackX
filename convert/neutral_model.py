"""
Solver-independent intermediate representation for FE results.

This module defines the neutral data model that sits between format-specific
readers (ANSYS RST, Abaqus ODB, ...) and the FRD writer.  Every reader
produces a ``NeutralModel``; the FRD writer consumes one.

The ``NeutralElementType`` IntEnum values are chosen to equal the CalculiX FRD
numeric type codes, so ``int(elem.etype)`` gives the FRD code directly.

MVP scope
---------
The current conversion pipeline targets CalculiX crack propagation, which
requires 3-D solid volume elements.  The ANSYS RST reader (MVP) only emits
elements whose types appear in :data:`SOLID_3D_TYPES`.  Shell and other
element types are present in the enum for extensibility but are not produced
by any MVP reader.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np


# ---------------------------------------------------------------------------
# Element types  (values = FRD type codes)
# ---------------------------------------------------------------------------

class NeutralElementType(IntEnum):
    """Solver-independent element types.

    The integer value of each member equals the CalculiX FRD element-type code,
    so the FRD writer can use ``int(etype)`` without a lookup table.
    """
    C3D8  = 1     # 8-node hexahedron
    C3D6  = 2     # 6-node wedge / prism
    C3D4  = 3     # 4-node tetrahedron
    C3D20 = 4     # 20-node quadratic hexahedron
    C3D15 = 5     # 15-node quadratic wedge
    C3D10 = 6     # 10-node quadratic tetrahedron
    S3    = 7     # 3-node triangle shell
    S6    = 8     # 6-node quadratic triangle shell
    S4    = 9     # 4-node quadrilateral shell
    S8    = 10    # 8-node quadratic quadrilateral shell


# 3-D solid element types supported in the MVP conversion pipeline.
# Used by readers to filter elements and by the FRD writer to verify scope.
SOLID_3D_TYPES: frozenset[NeutralElementType] = frozenset({
    NeutralElementType.C3D8,
    NeutralElementType.C3D6,
    NeutralElementType.C3D4,
    NeutralElementType.C3D20,
    NeutralElementType.C3D15,
    NeutralElementType.C3D10,
})


# Number of nodes per element type (for connectivity validation)
_ETYPE_NNODES: dict[NeutralElementType, int] = {
    NeutralElementType.C3D8:  8,
    NeutralElementType.C3D6:  6,
    NeutralElementType.C3D4:  4,
    NeutralElementType.C3D20: 20,
    NeutralElementType.C3D15: 15,
    NeutralElementType.C3D10: 10,
    NeutralElementType.S3:    3,
    NeutralElementType.S6:    6,
    NeutralElementType.S4:    4,
    NeutralElementType.S8:    8,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NeutralNode:
    id: int
    x: float
    y: float
    z: float


@dataclass
class NeutralElement:
    id: int
    etype: NeutralElementType
    node_ids: list[int]


@dataclass
class NeutralResultField:
    """One result field for one increment.

    Examples
    --------
    STRESS: component_names = ["SXX","SYY","SZZ","SXY","SYZ","SXZ"], data nid→(6,)
    DISP:   component_names = ["D1","D2","D3"], data nid→(3,)
    NDTEMP: component_names = ["T"], data nid→(1,)
    """
    name: str
    component_names: list[str]
    data: dict[int, np.ndarray]        # nid → (n_components,)


@dataclass
class NeutralIncrement:
    step: int
    increment: int
    total_time: float
    fields: dict[str, NeutralResultField] = field(default_factory=dict)


@dataclass
class NeutralMetadata:
    source_solver: str = ""      # "ANSYS", "Abaqus", "Nastran"
    source_file: str = ""
    title: str = ""


@dataclass
class ComponentSet:
    """A named, element-based selection (component / named selection).

    Stores a frozen set of element IDs that belong to this component.
    Node membership is derived from element connectivity at export time.
    Designed to be extensible: future readers may add node-based or mixed
    components by subclassing or adding a ``node_ids`` field.
    """
    name: str
    element_ids: frozenset[int]

    @property
    def n_elements(self) -> int:
        return len(self.element_ids)


@dataclass
class NeutralModel:
    """Solver-independent FE result model.

    Central exchange format between readers and the FRD writer.
    """
    nodes: dict[int, NeutralNode] = field(default_factory=dict)
    elements: dict[int, NeutralElement] = field(default_factory=dict)
    increments: list[NeutralIncrement] = field(default_factory=list)
    metadata: NeutralMetadata = field(default_factory=NeutralMetadata)
    components: dict[str, ComponentSet] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def n_nodes(self) -> int:
        return len(self.nodes)

    @property
    def n_elements(self) -> int:
        return len(self.elements)

    @property
    def increment_count(self) -> int:
        return len(self.increments)

    @property
    def available_fields(self) -> set[str]:
        """Union of all field names across all increments."""
        out: set[str] = set()
        for inc in self.increments:
            out.update(inc.fields.keys())
        return out

    # ------------------------------------------------------------------
    # Subset export
    # ------------------------------------------------------------------

    def subset(self, component_names: list[str]) -> "NeutralModel":
        """Return a new NeutralModel restricted to the given named components.

        Collects all elements that belong to any of the named components,
        then collects all nodes required by those elements, and trims result
        fields so that only data for those nodes is included.  Increments that
        end up with no field data after trimming are dropped.

        Parameters
        ----------
        component_names:
            Names of :class:`ComponentSet` entries in :attr:`components` to
            include.  Unknown names are silently ignored.

        Returns
        -------
        NeutralModel
            New model with the same metadata; nodes/elements/results filtered
            to the requested scope.
        """
        # Collect element IDs from every named component
        elem_ids: set[int] = set()
        for name in component_names:
            comp = self.components.get(name)
            if comp is not None:
                elem_ids.update(comp.element_ids)

        # Filter elements
        sub_elements: dict[int, NeutralElement] = {
            eid: elem for eid, elem in self.elements.items()
            if eid in elem_ids
        }

        # Collect all node IDs referenced by those elements
        node_ids: set[int] = set()
        for elem in sub_elements.values():
            node_ids.update(elem.node_ids)

        # Filter nodes
        sub_nodes: dict[int, NeutralNode] = {
            nid: node for nid, node in self.nodes.items()
            if nid in node_ids
        }

        # Filter result data to subset nodes; drop empty increments
        sub_increments: list[NeutralIncrement] = []
        for inc in self.increments:
            sub_fields: dict[str, NeutralResultField] = {}
            for fname, rf in inc.fields.items():
                sub_data = {
                    nid: v for nid, v in rf.data.items() if nid in node_ids
                }
                if sub_data:
                    sub_fields[fname] = NeutralResultField(
                        name=rf.name,
                        component_names=rf.component_names,
                        data=sub_data,
                    )
            if sub_fields:
                sub_increments.append(NeutralIncrement(
                    step=inc.step,
                    increment=inc.increment,
                    total_time=inc.total_time,
                    fields=sub_fields,
                ))

        # Keep only the selected components in the returned model
        selected = set(component_names)
        sub_components = {
            name: comp for name, comp in self.components.items()
            if name in selected
        }

        return NeutralModel(
            nodes=sub_nodes,
            elements=sub_elements,
            increments=sub_increments,
            metadata=self.metadata,
            components=sub_components,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Return a list of issues (empty list = valid model)."""
        issues: list[str] = []

        if not self.nodes:
            issues.append("Model has no nodes.")
        if not self.elements:
            issues.append("Model has no elements.")
        if not self.increments:
            issues.append("Model has no result increments.")

        # Check element connectivity references valid nodes
        node_ids = set(self.nodes.keys())
        bad_elems = 0
        for eid, elem in self.elements.items():
            expected = _ETYPE_NNODES.get(elem.etype)
            if expected is not None and len(elem.node_ids) != expected:
                bad_elems += 1
            for nid in elem.node_ids:
                if nid not in node_ids:
                    bad_elems += 1
                    break
        if bad_elems:
            issues.append(
                f"{bad_elems} element(s) have invalid connectivity "
                f"(wrong node count or dangling node IDs).")

        # Check at least one increment has stress data
        has_stress = any(
            "STRESS" in inc.fields for inc in self.increments)
        if not has_stress:
            issues.append("No increment contains STRESS data.")

        # Check stress fields have 6 components
        for inc in self.increments:
            sf = inc.fields.get("STRESS")
            if sf and len(sf.component_names) != 6:
                issues.append(
                    f"STRESS field in step {inc.step} inc {inc.increment} "
                    f"has {len(sf.component_names)} components (expected 6).")
                break

        # Check for non-finite values in stress
        for inc in self.increments:
            sf = inc.fields.get("STRESS")
            if sf:
                n_bad = sum(
                    1 for v in sf.data.values() if not np.all(np.isfinite(v)))
                if n_bad:
                    issues.append(
                        f"STRESS in step {inc.step} inc {inc.increment}: "
                        f"{n_bad} node(s) have NaN/Inf values.")
                break  # only check first increment with stress

        return issues
