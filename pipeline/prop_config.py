"""
PropagationConfig — user input contract for the CalculiX *CRACK PROPAGATION pipeline.

The user provides:
  - An FRD file from an externally-solved uncracked static analysis (mandatory)
  - An initial crack geometry: .brep, .step, or .stl (mandatory)
  - Paris material constants (8-vector for *USER MATERIAL, CONSTANTS=8)
  - Propagation controls

The software does NOT solve the initial static analysis.
CalculiX handles all crack propagation physics internally.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PropagationConfig:

    # ------------------------------------------------------------------
    # Required inputs
    # ------------------------------------------------------------------

    uncracked_frd: str = ""
    """Path to user-provided FRD file containing stress results from the
    uncracked structure.  Must contain a STRESS block.
    Used as INPUT= in the *CRACK PROPAGATION deck."""

    initial_crack: str = ""
    """Path to the initial crack geometry.
    Accepted formats: .brep, .step / .stp (OpenCASCADE), or .stl (triangle mesh).
    Must be a simply-connected surface (topological disk)."""

    # ------------------------------------------------------------------
    # Structural material for volume mesh and crack surface shell section
    # ------------------------------------------------------------------

    structural_material_name: str = "CT3D_BENCHMARK"
    """Name written after *MATERIAL,NAME= for the elastic material that is
    assigned to both the volume (*SOLID SECTION) and the crack surface
    (*SHELL SECTION).  Must be a valid CalculiX material identifier."""

    structural_elastic_E: float = 210000.0
    """Young's modulus for the structural elastic material [stress unit].
    Used to write *ELASTIC in the propagation deck.
    Default: 210 000 MPa (structural steel)."""

    structural_elastic_nu: float = 0.3
    """Poisson ratio for the structural elastic material (dimensionless).
    Default: 0.3."""

    # ------------------------------------------------------------------
    # Paris material law — *USER MATERIAL, CONSTANTS=8
    # ------------------------------------------------------------------

    paris_constants: tuple = (1e-4, 772.86, 3.1, 10., 177.09, 10., 3162., 0.5)
    """Eight material constants passed verbatim to CalculiX *USER MATERIAL.

    Ordering (per CalculiX §6.9.27):
      (da/dN)_ref  — reference crack growth rate  [L/cycle]
      DK_ref       — reference stress intensity range  [F/L^(3/2)]
      m            — Paris exponent
      epsilon      — threshold correction exponent
      DK_th        — threshold stress intensity range  [F/L^(3/2)]
      delta        — critical correction exponent
      K_c          — fracture toughness  [F/L^(3/2)]
      w            — R-ratio exponent

    IMPORTANT: units must be consistent with the stress field in uncracked_frd.
    CalculiX does NOT check unit consistency.
    """

    material_name: str = "CRACK"
    """Name used for *MATERIAL and MATERIAL= parameter in the deck."""

    # ------------------------------------------------------------------
    # Shell section
    # ------------------------------------------------------------------

    shell_thickness: float = 0.01
    """Thickness written on the *SHELL SECTION data line [length unit].
    CalculiX requires the field but does not use it for crack propagation
    physics — any positive value consistent with the model scale is fine."""

    # ------------------------------------------------------------------
    # Propagation controls
    # ------------------------------------------------------------------

    max_da: float = 0.05
    """Maximum crack increment per CalculiX increment [same length unit as FRD].
    Passed as the first value on the line below *CRACK PROPAGATION."""

    max_angle: float = 10.0
    """Maximum deflection angle per CalculiX increment [degrees].
    Passed as the second value on the line below *CRACK PROPAGATION."""

    max_increments: int = 50
    """Value for *STEP, INC=.  Controls how many propagation increments
    CalculiX performs within the single propagation run."""

    length_type: str = "CUMULATIVE"
    """LENGTH option for *CRACK PROPAGATION.
    Allowed: 'CUMULATIVE' or 'INTERSECTION'."""

    # ------------------------------------------------------------------
    # S3 crack surface mesh generation
    # ------------------------------------------------------------------

    crack_mesh_size: float = 0.05
    """Target linear deflection for BRepMesh_IncrementalMesh triangulation [length unit].
    Smaller values produce finer S3 meshes (more accurate crack front, slower)."""

    crack_angular_deflection: float = 0.08
    """Angular deflection [radians] for BRepMesh_IncrementalMesh.
    Controls curvature-based refinement — smaller = finer on curved edges."""

    normal_hint: tuple | None = None
    """Optional unit vector (3-tuple) indicating the expected crack normal direction,
    e.g. (0, 0, 1) for a crack in the XY plane.  Used to orient the S3 mesh
    normals in the correct half-space.  If None, the first triangle normal is used
    as the seed for the BFS consistency pass."""

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    work_dir: str = "./prop_work"
    """Root working directory for the propagation run."""

    # ------------------------------------------------------------------
    # CalculiX
    # ------------------------------------------------------------------

    ccx_path: str = r"C:\Users\Adem\source\repos\GmCrackX\CalculixSolver\ccx_dynamic.exe"
    """Path to the CalculiX executable."""

    n_cpus: int = 4
    """Number of OpenMP threads (OMP_NUM_THREADS) for CalculiX."""

    def validate(self) -> None:
        """Raise ValueError for obviously wrong config values."""
        import os
        if not self.uncracked_frd:
            raise ValueError("PropagationConfig.uncracked_frd must be set")
        if not os.path.isfile(self.uncracked_frd):
            raise FileNotFoundError(f"uncracked_frd not found: {self.uncracked_frd}")
        if not self.initial_crack:
            raise ValueError("PropagationConfig.initial_crack must be set")
        if not os.path.isfile(self.initial_crack):
            raise FileNotFoundError(f"initial_crack not found: {self.initial_crack}")
        if len(self.paris_constants) != 8:
            raise ValueError(
                f"paris_constants must have exactly 8 values, got {len(self.paris_constants)}"
            )
        if self.max_da <= 0:
            raise ValueError(f"max_da must be > 0, got {self.max_da}")
        if self.max_angle <= 0 or self.max_angle > 90:
            raise ValueError(f"max_angle must be in (0, 90], got {self.max_angle}")
        if self.length_type not in ("CUMULATIVE", "INTERSECTION"):
            raise ValueError(
                f"length_type must be CUMULATIVE or INTERSECTION, "
                f"got {self.length_type!r}"
            )
        if self.normal_hint is not None and len(self.normal_hint) != 3:
            raise ValueError("normal_hint must be a 3-tuple, e.g. (0, 0, 1)")
