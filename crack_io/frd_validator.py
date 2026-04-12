"""
FRDValidator — validates a user-provided CalculiX FRD file for compatibility
with the *CRACK PROPAGATION pipeline.

Validation rules (hard = raises FRDValidationError, soft = warnings.warn):

  FRD-0  File readable and non-empty                         hard
  FRD-1  STRESS block present in last increment              hard
  FRD-2  All stress values finite (no NaN / Inf)             hard
  FRD-3  Node count >= 4                                     hard
  FRD-4  Node IDs consistent with reference INP (optional)   soft/hard
  FRD-5  Bounding box matches reference INP (optional)       hard
  FRD-6  RMS von Mises stress is in a sane range             soft
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from crack_io.frd_reader import FrdIncrement, read_frd

if TYPE_CHECKING:
    from core.mesh_io import MeshData


class FRDValidationError(ValueError):
    """Raised when the user-provided FRD fails a hard validation rule."""


@dataclass
class ValidationReport:
    frd_path: str
    n_nodes: int
    n_increments: int
    has_stress: bool
    has_disp: bool
    rms_von_mises: float
    warnings: list[str]
    errors: list[str]

    def summary(self) -> str:
        lines = [
            f"FRD: {self.frd_path}",
            f"  increments : {self.n_increments}",
            f"  nodes      : {self.n_nodes}",
            f"  stress     : {'yes' if self.has_stress else 'NO'}",
            f"  disp       : {'yes' if self.has_disp else 'no'}",
            f"  RMS vM     : {self.rms_von_mises:.3e}",
        ]
        for w in self.warnings:
            lines.append(f"  WARN  {w}")
        for e in self.errors:
            lines.append(f"  ERROR {e}")
        return "\n".join(lines)


class FRDValidator:
    """
    Validates a user-provided FRD file for use with *CRACK PROPAGATION.

    Usage:
        validator = FRDValidator("results.frd", reference_mesh=mesh_data)
        increment = validator.validate()   # raises FRDValidationError on failure
        print(validator.report.summary())
    """

    def __init__(
        self,
        frd_path: str | Path,
        reference_mesh: MeshData | None = None,
    ) -> None:
        self.frd_path = str(frd_path)
        self.ref_mesh = reference_mesh
        self.report: ValidationReport | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self) -> FrdIncrement:
        """
        Run all validation rules.  Returns the last FrdIncrement on success.
        Raises FRDValidationError on any hard failure.
        Emits warnings.warn() for soft failures.
        """
        warn_list: list[str] = []
        error_list: list[str] = []

        # FRD-0: file readable
        increments = self._load(error_list)
        if error_list:
            self.report = ValidationReport(
                self.frd_path, 0, 0, False, False, 0.0, warn_list, error_list
            )
            raise FRDValidationError(error_list[0])

        # FRD-1: find the last increment that has a STRESS block
        stress_inc = None
        for inc in reversed(increments):
            if inc.stresses:
                stress_inc = inc
                break

        if stress_inc is None:
            msg = (
                "FRD-1: no STRESS block found in any increment. "
                "*CRACK PROPAGATION requires a stress field."
            )
            last_inc = increments[-1]
            self.report = ValidationReport(
                self.frd_path, 0, len(increments), False,
                bool(last_inc.displacements), 0.0, warn_list, [msg]
            )
            raise FRDValidationError(msg)

        last = stress_inc

        # FRD-2: finite stresses
        bad_nodes = [
            nid for nid, s in last.stresses.items()
            if not np.isfinite(s).all()
        ]
        if bad_nodes:
            msg = (
                f"FRD-2: NaN/Inf stress at {len(bad_nodes)} node(s) "
                f"(first: {bad_nodes[0]}). FE analysis likely diverged."
            )
            error_list.append(msg)
            self.report = ValidationReport(
                self.frd_path, len(last.stresses), len(increments),
                True, bool(last.displacements), 0.0, warn_list, error_list
            )
            raise FRDValidationError(msg)

        # FRD-3: minimum node count
        if len(last.stresses) < 4:
            msg = (
                f"FRD-3: only {len(last.stresses)} node(s) with stress — "
                "file is likely empty or corrupt."
            )
            error_list.append(msg)
            self.report = ValidationReport(
                self.frd_path, len(last.stresses), len(increments),
                True, bool(last.displacements), 0.0, warn_list, error_list
            )
            raise FRDValidationError(msg)

        # FRD-4 / FRD-5: cross-check with reference mesh (optional)
        if self.ref_mesh is not None:
            self._cross_check_mesh(last, warn_list, error_list)
            if error_list:
                self.report = ValidationReport(
                    self.frd_path, len(last.stresses), len(increments),
                    True, bool(last.displacements), 0.0, warn_list, error_list
                )
                raise FRDValidationError(error_list[-1])

        # FRD-6: stress scale sanity
        rms_vm = self._von_mises_rms(last.stresses)
        if rms_vm < 1.0:
            w = (
                f"FRD-6: RMS von Mises stress = {rms_vm:.3e}. "
                "Near-zero loading or wrong stress units?"
            )
            warn_list.append(w)
            warnings.warn(w, UserWarning, stacklevel=2)
        if rms_vm > 1e9:
            w = (
                f"FRD-6: RMS von Mises stress = {rms_vm:.3e}. "
                "Suspiciously large — check unit system."
            )
            warn_list.append(w)
            warnings.warn(w, UserWarning, stacklevel=2)

        # Soft: warn if no displacements
        if not last.displacements:
            w = "FRD has no DISP block — displacement-based post-processing unavailable."
            warn_list.append(w)
            warnings.warn(w, UserWarning, stacklevel=2)

        # Soft: warn if only one increment
        if len(increments) == 1:
            w = "FRD contains only one increment — CalculiX will use its stress field for all cycles."
            warn_list.append(w)
            warnings.warn(w, UserWarning, stacklevel=2)

        self.report = ValidationReport(
            frd_path=self.frd_path,
            n_nodes=len(last.stresses),
            n_increments=len(increments),
            has_stress=True,
            has_disp=bool(last.displacements),
            rms_von_mises=rms_vm,
            warnings=warn_list,
            errors=error_list,
        )
        return last

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self, error_list: list[str]) -> list[FrdIncrement]:
        try:
            incs = read_frd(self.frd_path)
        except FileNotFoundError:
            error_list.append(f"FRD-0: file not found: {self.frd_path}")
            return []
        except Exception as exc:  # noqa: BLE001
            error_list.append(f"FRD-0: could not read FRD: {exc}")
            return []
        if not incs:
            error_list.append(
                f"FRD-0: file is empty or contains no recognised increments: {self.frd_path}"
            )
        return incs

    def _cross_check_mesh(
        self,
        last: FrdIncrement,
        warn_list: list[str],
        error_list: list[str],
    ) -> None:
        """Rules FRD-4 and FRD-5: cross-check FRD against reference INP mesh."""
        mesh = self.ref_mesh
        frd_ids = set(last.stresses.keys())
        mesh_ids = set(mesh.nodes.keys())

        # FRD-4a: FRD has nodes not in mesh (harmless extra nodes)
        extra = frd_ids - mesh_ids
        if extra:
            w = (
                f"FRD-4: {len(extra)} FRD node(s) not present in reference INP "
                f"(e.g. node {next(iter(extra))}). Extra nodes are ignored."
            )
            warn_list.append(w)
            warnings.warn(w, UserWarning, stacklevel=3)

        # FRD-4b: mesh nodes missing from FRD (potential interpolation issue)
        missing = mesh_ids - frd_ids
        pct_missing = len(missing) / max(len(mesh_ids), 1) * 100.0
        if pct_missing > 10.0:
            msg = (
                f"FRD-4: {len(missing)} mesh nodes ({pct_missing:.1f}%) have no "
                "stress in the FRD. Mesh/FRD mismatch — check that the FRD was "
                "produced from the same model as reference_inp."
            )
            error_list.append(msg)
            return
        elif missing:
            w = (
                f"FRD-4: {len(missing)} mesh nodes ({pct_missing:.1f}%) missing "
                "from FRD — CalculiX will interpolate stress at those locations."
            )
            warn_list.append(w)
            warnings.warn(w, UserWarning, stacklevel=3)

        # FRD-5: bounding box check using shared node IDs
        shared = frd_ids & mesh_ids
        if len(shared) < 4:
            # Not enough overlap to check bbox — skip
            return
        coords = np.array([[mesh.nodes[n].x, mesh.nodes[n].y, mesh.nodes[n].z]
                           for n in shared])
        all_coords = np.array([[n.x, n.y, n.z] for n in mesh.nodes.values()])

        bbox_shared = coords.max(axis=0) - coords.min(axis=0)
        bbox_all    = all_coords.max(axis=0) - all_coords.min(axis=0)

        char_len = float(np.linalg.norm(bbox_all))
        if char_len < 1e-12:
            return  # degenerate mesh

        rel_diff = np.linalg.norm(bbox_shared - bbox_all) / char_len
        if rel_diff > 0.10:
            msg = (
                f"FRD-5: bounding box of FRD nodes differs from full mesh bbox by "
                f"{rel_diff*100:.1f}% of characteristic length. Check coordinate "
                "system and units — FRD and INP may not be from the same model."
            )
            error_list.append(msg)

    @staticmethod
    def _von_mises_rms(stresses: dict[int, np.ndarray]) -> float:
        """
        Compute RMS von Mises stress over all nodes.
        Stress vector: [Sxx, Syy, Szz, Sxy, Syz, Sxz]
        """
        arr = np.array(list(stresses.values()))  # (N, 6)
        s11, s22, s33 = arr[:, 0], arr[:, 1], arr[:, 2]
        s12, s23, s13 = arr[:, 3], arr[:, 4], arr[:, 5]
        vm2 = 0.5 * ((s11 - s22)**2 + (s22 - s33)**2 + (s33 - s11)**2
                     + 6.0 * (s12**2 + s23**2 + s13**2))
        return float(np.sqrt(np.mean(vm2)))
