# Crack3D — Project Structure

3D crack growth simulation framework using **CalculiX** (solver), **OpenCascade** (geometry), **Gmsh** (meshing).

Based on the algorithm described in: *Krome et al., "Validation and Verification of Novel Three-Dimensional Crack Growth Simulation Software GmshCrack3D", Appl. Sci. 2026, 16, 384.*

---

## Directory tree

```
crack3d/
│
├── crack3d/                        # Python package root
│   │
│   ├── __init__.py
│   │
│   ├── core/                       # Low-level building blocks (no solver dependency)
│   │   ├── __init__.py
│   │   ├── mesh_io.py              # Read/write mesh formats (.inp, .msh, .vtk)
│   │   ├── geometry.py             # OCCT geometry operations (B-rep construction, Boolean)
│   │   ├── meshing.py              # Gmsh mesh generation, size fields, refinement
│   │   ├── submodel.py             # Crack-tip structured hex submodel creation
│   │   ├── fracture.py             # MCCI evaluation, G→K conversion, smoothing
│   │   ├── crack_law.py            # Paris law, crack growth increment, kink/twist angles
│   │   ├── mapping.py              # Field mapping (stress, displacement) between meshes
│   │   └── utils.py                # KDTree helpers, coordinate transforms, logging
│   │
│   ├── solver/                     # Solver abstraction layer
│   │   ├── __init__.py
│   │   ├── base_solver.py          # Abstract base class for any FE solver
│   │   ├── calculix_solver.py      # CalculiX-specific: write .inp, run ccx, parse .frd/.dat
│   │   └── result_reader.py        # Read CalculiX results (.frd nodal data, .dat section forces)
│   │
│   ├── pipeline/                   # Orchestration layer
│   │   ├── __init__.py
│   │   ├── config.py               # Dataclass-based configuration (all user parameters)
│   │   ├── crack_step.py           # Single crack growth iteration (Steps 2-10)
│   │   └── driver.py               # Main loop: iterate crack_step until termination
│   │
│   └── io/                         # File format converters
│       ├── __init__.py
│       ├── inp_parser.py           # CalculiX .inp reader (nodes, elements, sets, BCs)
│       ├── inp_writer.py           # CalculiX .inp writer (merged model output)
│       ├── frd_reader.py           # CalculiX .frd binary/ASCII result reader
│       └── brep_io.py              # OCCT .brep read/write wrappers
│
├── tests/
│   ├── test_mesh_io.py
│   ├── test_geometry.py
│   ├── test_fracture.py
│   ├── test_crack_law.py
│   ├── test_mini_ct.py             # Full benchmark: Mini-CT verification case
│   └── fixtures/
│       ├── mini_ct.inp             # Mini-CT CalculiX input
│       └── mini_ct_crack.brep      # Initial crack surface
│
├── examples/
│   ├── mini_ct/
│   │   ├── run_mini_ct.py          # Complete Mini-CT crack growth simulation
│   │   ├── mini_ct.inp
│   │   └── crack_initial.brep
│   └── README.md
│
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## Module responsibilities

### `core/mesh_io.py`
Reads CalculiX `.inp` mesh (nodes + elements) into internal data structures. Writes `.msh` (Gmsh) and `.vtk` for visualization. Handles element type mapping between CalculiX (C3D4, C3D10, C3D8, C3D20) and Gmsh element codes.

Key classes:
```python
@dataclass
class Node:
    id: int
    x: float
    y: float
    z: float

@dataclass
class Element:
    id: int
    etype: str          # "C3D4", "C3D10", etc.
    nodes: list[int]

@dataclass
class MeshData:
    nodes: dict[int, Node]
    elements: dict[int, Element]
    node_sets: dict[str, list[int]]
    element_sets: dict[str, list[int]]
```

### `core/geometry.py`
All OpenCascade operations. Two main tasks:

1. **Mesh-to-B-rep reconstruction** (Step 3): Extract boundary faces from local tet mesh → build OCC vertices, edges, face loops → sew into closed shell → create solid. This is the hardest OCCT piece.

2. **Crack insertion** (Step 4): Load crack surface `.brep`, load local solid `.brep`, perform `BRepAlgoAPI_Splitter` (or use Gmsh `occ.fragment()`). Classify resulting faces into crack surface, crack boundary, crack front edge groups.

Key functions:
```python
def mesh_to_brep(mesh: MeshData, element_ids: list[int]) -> TopoDS_Solid:
    """Reconstruct B-rep solid from local mesh boundary faces."""

def insert_crack(solid_brep: str, crack_brep: str) -> tuple[str, dict]:
    """Boolean fragment crack into solid. Returns new .brep path + physical groups."""

def build_new_crack_surface(
    old_crack_brep: str,
    front_points: np.ndarray,      # (N, 3) new front positions
    front_connectivity: list[list[int]]
) -> str:
    """Create updated crack surface via B-spline fill. Returns new .brep path."""
```

### `core/meshing.py`
All Gmsh mesh operations.

- Define distance + threshold size fields for crack front and crack surface
- Generate 3D tet mesh with anisotropic refinement
- Fix inverted surface normals on crack faces
- Create physical groups for crack surface, front, boundary

Key functions:
```python
def remesh_local_with_crack(
    local_brep: str,
    crack_front_tags: list[int],
    crack_surface_tags: list[int],
    min_size: float = 0.05,
    max_size: float = 1.0,
    refinement_distance: float = 2.0,
) -> MeshData:
    """Remesh local model with anisotropic refinement around crack."""

def divide_local_global(
    mesh: MeshData,
    crack_surface_brep: str,
    local_model_size: float,
) -> tuple[MeshData, MeshData]:
    """Split mesh into local (near crack) and global (far) parts."""
```

### `core/submodel.py`
Creates the structured hexahedral submodel around the crack front for fracture mechanics evaluation.

For each crack front node:
1. Evaluate parametric derivatives → tangent vector **t** along front
2. Evaluate surface normal → crack opening normal **n**
3. Cross product → crack growth direction **m** = **t** × **n**
4. Extrude structured hex layers along **n** and **m**

Uses Gmsh `setTransfinite` for structured meshing.

Key function:
```python
def create_crack_tip_submodel(
    crack_front_nodes: np.ndarray,    # (N, 3) front coordinates
    tangent_vectors: np.ndarray,       # (N, 3) per-node tangent
    normal_vectors: np.ndarray,        # (N, 3) per-node crack opening normal
    n_elements_around: int = 4,        # elements per front node
    submodel_radius: float = 0.5,
) -> MeshData:
    """Build structured hex submodel around crack front."""
```

### `core/fracture.py`
Modified Crack Closure Integral (MCCI) evaluation + K-factor computation.

The MCCI formula from the paper:
```
G_I   = 0.5 * F_n   * Δu_n   / (Δa * Δt)
G_II  = 0.5 * F_s1  * Δu_s1  / (Δa * Δt)
G_III = 0.5 * F_s2  * Δu_s2  / (Δa * Δt)
```

Where:
- `F` = nodal force at crack-tip node (normal, in-plane shear, out-of-plane shear)
- `Δu` = relative displacement of duplicated nodes one element ahead of tip
- `Δa` = element length ahead of tip
- `Δt` = partial width assigned to that tip node

Then convert G → K:
```
K_I   = sqrt(G_I   * E / (1 - ν²))
K_II  = sqrt(G_II  * E / (1 - ν²))
K_III = sqrt(G_III * E / (1 - ν))
```

Key functions:
```python
def compute_energy_release_rates(
    tip_forces: np.ndarray,           # (N, 3) forces at crack-tip nodes
    crack_face_displacements: np.ndarray,  # (N, 3) relative Δu
    delta_a: np.ndarray,              # (N,) element length ahead
    delta_t: np.ndarray,              # (N,) partial width
) -> np.ndarray:
    """Returns (N, 3) array of [G_I, G_II, G_III] per front node."""

def smooth_along_front(values: np.ndarray, order: int = 4) -> np.ndarray:
    """Polynomial smoothing of G or K distributions along crack front."""

def g_to_k(G: np.ndarray, E: float, nu: float) -> np.ndarray:
    """Convert energy release rates to stress intensity factors."""

def compute_kv_and_angles(
    K: np.ndarray,   # (N, 3) [K_I, K_II, K_III]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Effective K_V, kink angle φ, twist angle ψ via σ'₁ criterion."""
```

### `core/crack_law.py`
Crack growth increment calculation.

```python
def paris_increment(
    K_V: np.ndarray,      # (N,) effective SIF per front node
    C: float,             # Paris constant
    m: float,             # Paris exponent
    max_da: float,        # maximum allowed increment
) -> tuple[np.ndarray, float]:
    """
    Returns:
        da: (N,) crack growth increment per front node, scaled so max(da) = max_da
        dN: estimated load cycles for this increment
    """

def growth_direction_vectors(
    normal: np.ndarray,    # (N, 3) crack opening normal
    inplane: np.ndarray,   # (N, 3) in-plane direction
    phi: np.ndarray,       # (N,) kink angle
    psi: np.ndarray,       # (N,) twist angle
) -> np.ndarray:
    """Returns (N, 3) unit growth direction vectors per front node."""
```

### `core/mapping.py`
Field transfer between meshes (stress, displacement).

```python
def map_displacements_to_submodel(
    global_nodes: np.ndarray,         # (M, 3) global node coords
    global_displacements: np.ndarray, # (M, 3) nodal U from .frd
    submodel_boundary_nodes: np.ndarray,  # (P, 3) submodel boundary coords
) -> np.ndarray:
    """Interpolate global displacements onto submodel boundary. Returns (P, 3)."""

def map_initial_stresses(
    source_mesh: MeshData,
    source_stresses: np.ndarray,      # integration point stresses
    target_mesh: MeshData,
) -> np.ndarray:
    """Map initial/residual stresses to new mesh via interpolation."""
```

### `solver/base_solver.py`
Abstract interface so the framework stays solver-independent.

```python
from abc import ABC, abstractmethod

class BaseSolver(ABC):
    @abstractmethod
    def write_input(self, mesh: MeshData, bcs: dict, output_path: str) -> str:
        """Write solver input file. Return path."""

    @abstractmethod
    def run(self, input_path: str, n_cpus: int = 4) -> str:
        """Execute solver. Return results directory path."""

    @abstractmethod
    def read_displacements(self, results_path: str) -> np.ndarray:
        """Read nodal displacements from results."""

    @abstractmethod
    def read_nodal_forces(self, results_path: str) -> np.ndarray:
        """Read nodal reaction forces from results."""
```

### `solver/calculix_solver.py`
CalculiX implementation of `BaseSolver`.

- Writes `.inp` with `*NODE`, `*ELEMENT`, `*BOUNDARY`, `*CLOAD`, `*MATERIAL`, etc.
- Runs `ccx` subprocess
- Parses `.frd` for displacements, `.dat` for nodal forces
- Handles `*SUBMODEL` or manual displacement BCs for the submodel run

### `pipeline/config.py`
All user-tunable parameters in one place.

```python
@dataclass
class Crack3DConfig:
    # Paths
    global_inp: str                  # Path to CalculiX .inp
    initial_crack_brep: str          # Path to initial crack .brep
    work_dir: str = "./crack_work"

    # Local-global division
    local_model_size: float = 4.0    # LMS radius

    # Meshing
    crack_tip_min_size: float = 0.05
    crack_tip_max_size: float = 1.0
    refinement_distance: float = 2.0

    # Submodel
    submodel_elements_around: int = 4
    submodel_radius: float = 0.5

    # Material
    E: float = 210000.0              # Young's modulus [MPa]
    nu: float = 0.3                  # Poisson's ratio

    # Crack growth law
    paris_C: float = 1e-11           # Paris constant
    paris_m: float = 3.0             # Paris exponent
    max_da: float = 0.2              # Max increment per step [mm]
    smoothing_order: int = 4         # Polynomial smoothing order

    # Termination
    max_steps: int = 50
    max_crack_length: float = 15.0   # [mm]

    # Solver
    ccx_path: str = "ccx"
    n_cpus: int = 4
```

### `pipeline/crack_step.py`
Executes one complete crack growth iteration (Steps 2→10).

```python
class CrackStep:
    def __init__(self, config: Crack3DConfig, step_number: int):
        self.config = config
        self.step = step_number
        self.work_dir = Path(config.work_dir) / f"Crack_{step_number}"

    def run(self, global_mesh: MeshData, crack_brep: str) -> CrackStepResult:
        """
        Execute one full crack growth step:
        1. divide_local_global()
        2. mesh_to_brep()
        3. insert_crack()
        4. remesh_local_with_crack()
        5. create_crack_tip_submodel()
        6. merge_and_write_global_inp()
        7. run_global_analysis()
        8. map_displacements_to_submodel()
        9. run_submodel_analysis()
        10. evaluate_fracture_mechanics()
        11. compute_crack_increment()
        12. build_new_crack_surface()

        Returns CrackStepResult with K, G, da, dN, new_crack_brep
        """
```

### `pipeline/driver.py`
Main entry point.

```python
class CrackGrowthDriver:
    def __init__(self, config: Crack3DConfig):
        self.config = config
        self.solver = CalculiXSolver(config.ccx_path, config.n_cpus)

    def run(self) -> list[CrackStepResult]:
        """
        Main loop:
        1. Load initial mesh + crack
        2. For step in range(max_steps):
             result = CrackStep(config, step).run(mesh, crack_brep)
             Check termination (max length, K_IC, etc.)
             Update crack_brep for next step
        3. Write summary (a vs N, K vs a)
        """
```

---

## Dependencies

```toml
[project]
name = "crack3d"
requires-python = ">=3.11"
dependencies = [
    "numpy",
    "scipy",
    "gmsh",                  # Gmsh Python API
    "OCP",                   # pythonocc / CadQuery OCCT bindings
    "meshio",                # Mesh format conversion
]

[project.optional-dependencies]
viz = ["pyvista", "vtk"]     # For visualization
test = ["pytest"]
```

---

## Implementation priority

**Phase 1 — Foundation (get the loop working on Mini-CT)**

1. `io/inp_parser.py` — Read CalculiX .inp into MeshData
2. `core/meshing.py` — `divide_local_global()` with distance field
3. `core/geometry.py` — `mesh_to_brep()` reconstruction
4. `core/geometry.py` — `insert_crack()` Boolean fragment
5. `core/meshing.py` — `remesh_local_with_crack()` with size fields
6. `solver/calculix_solver.py` — Write merged .inp + run ccx
7. `io/frd_reader.py` — Read .frd displacements

**Phase 2 — Fracture mechanics evaluation**

8. `core/submodel.py` — Structured hex submodel
9. `core/mapping.py` — Displacement mapping to submodel BCs
10. `core/fracture.py` — MCCI evaluation + G→K
11. `core/crack_law.py` — Paris increment + direction

**Phase 3 — Close the loop**

12. `core/geometry.py` — `build_new_crack_surface()` B-spline update
13. `pipeline/crack_step.py` + `driver.py` — Full automation
14. `tests/test_mini_ct.py` — Verify K_I ≈ 12.99 MPa√m for a=4.5mm, F=1kN
