"""
Investigation script: why do nodal temperature results contain NaN values?

Run with:
    conda run --no-capture-output -n gmcrackx python tests/investigate_ndtemp_nan.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

RST_FILE = Path(__file__).parent / "example" / "ex-2" / "file.rst"

# ---------------------------------------------------------------------------
# Patch pyvista / VTK compatibility issues (same as AnsysRstReader._open)
# ---------------------------------------------------------------------------

def _stub(name, parent=None):
    mod = types.ModuleType(name)
    mod.__path__ = []
    sys.modules[name] = mod
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], name.rsplit(".", 1)[-1], mod)
    return mod

if "pyvista.utilities.sphinx_gallery" not in sys.modules:
    if "pyvista.utilities" not in sys.modules:
        _stub("pyvista.utilities")
    sg = _stub("pyvista.utilities.sphinx_gallery", "pyvista.utilities")
    sg._get_sg_image_scraper = lambda: None

try:
    import pyvista.plotting.utilities as _pvu
    if not hasattr(_pvu, "_get_sg_image_scraper"):
        _pvu._get_sg_image_scraper = lambda: None
except Exception:
    pass

if "vtkmodules.vtkRenderingMatplotlib" not in sys.modules:
    _stub("vtkmodules.vtkRenderingMatplotlib", "vtkmodules")

from ansys.mapdl.reader.common import read_binary  # type: ignore
rst = read_binary(str(RST_FILE))

# ---------------------------------------------------------------------------
# Section 1 — File / solver overview
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 1 — File overview")
print("=" * 70)
print(f"  RST file      : {RST_FILE}")
print(f"  n_sets        : {rst.nsets}")
print(f"  time_values   : {rst.time_values}")
mesh = rst.mesh
print(f"  mesh.n_node   : {mesh.n_node}")
print(f"  mesh.n_elem   : {mesh.n_elem}")
print()

# ---------------------------------------------------------------------------
# Section 2 — ANSYS element types present
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 2 — Element types in mesh")
print("=" * 70)
etype_arr = mesh.etype
unique_etypes, counts = np.unique(etype_arr, return_counts=True)
for et, cnt in zip(unique_etypes.tolist(), counts.tolist()):
    print(f"  ANSYS element type {et:4d}  : {cnt:6d} elements")
print()

# ---------------------------------------------------------------------------
# Section 3 — Temperature availability per increment
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 3 — Temperature availability per increment")
print("=" * 70)

SOLID_ETYPES = {185, 186, 187, 92, 95}

for i in range(rst.nsets):
    label = f"  Set {i} (t={rst.time_values[i]:.4g})"
    try:
        result = rst.nodal_temperature(i)
        if result is None:
            print(f"{label}  → nodal_temperature() returned None")
            continue
        nnum_t, temps = result
        temps = np.asarray(temps)

        # Handle both (N,) and (N,1) shapes
        if temps.ndim == 2:
            temps = temps[:, 0]

        n_total  = len(nnum_t)
        n_nan    = int(np.sum(np.isnan(temps)))
        n_finite = n_total - n_nan
        print(f"{label}  → {n_total} nodes, {n_finite} finite, {n_nan} NaN  "
              f"({100.*n_nan/n_total:.1f}% NaN)")

        # Store set 0 for detailed analysis
        if i == 0:
            nnum_temp0 = nnum_t
            temps0     = temps

    except Exception as exc:
        print(f"{label}  → EXCEPTION: {exc}")
print()

# ---------------------------------------------------------------------------
# Section 4 — Detailed NaN analysis for set 0
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 4 — NaN node analysis (set 0)")
print("=" * 70)

nan_mask   = np.isnan(temps0)
nan_nids   = set(nnum_temp0[nan_mask].tolist())
finite_nids = set(nnum_temp0[~nan_mask].tolist())

print(f"  Total temperature nodes  : {len(nnum_temp0)}")
print(f"  Finite (non-NaN) nodes   : {len(finite_nids)}")
print(f"  NaN nodes                : {len(nan_nids)}")
print(f"  NaN value range          : {np.nanmin(temps0):.4g} … {np.nanmax(temps0):.4g}")
if len(finite_nids):
    finite_vals = temps0[~nan_mask]
    print(f"  Finite value range       : {finite_vals.min():.4g} … {finite_vals.max():.4g}")
print()

# ---------------------------------------------------------------------------
# Section 5 — Which element types own the NaN nodes?
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 5 — Element-type ownership of NaN nodes")
print("=" * 70)

# Build node → set of owning ANSYS element types
node_to_etypes: dict[int, set] = {}
for eid_val, etype_val, conn in zip(mesh.enum.tolist(), etype_arr.tolist(), mesh.elem):
    nids = [int(n) for n in conn[10:] if n > 0]
    for nid in nids:
        node_to_etypes.setdefault(nid, set()).add(int(etype_val))

# For NaN nodes: what element types own them?
nan_etype_counts: dict[int, int] = {}
nan_nodes_not_in_elem = 0
for nid in nan_nids:
    if nid not in node_to_etypes:
        nan_nodes_not_in_elem += 1
    else:
        for et in node_to_etypes[nid]:
            nan_etype_counts[et] = nan_etype_counts.get(et, 0) + 1

print(f"  NaN nodes NOT connected to any element : {nan_nodes_not_in_elem}")
print(f"  NaN nodes connected to element types:")
for et, cnt in sorted(nan_etype_counts.items()):
    is_solid = "SOLID" if et in SOLID_ETYPES else "non-solid"
    print(f"    ANSYS type {et:4d} ({is_solid:8s}) : {cnt} NaN nodes")
print()

# Are any NaN nodes EXCLUSIVELY owned by non-solid elements?
nan_only_nonsolid = 0
nan_mixed = 0
nan_only_solid = 0
for nid in nan_nids:
    etypes = node_to_etypes.get(nid, set())
    has_solid    = bool(etypes & SOLID_ETYPES)
    has_nonsolid = bool(etypes - SOLID_ETYPES)
    if has_solid and has_nonsolid:
        nan_mixed += 1
    elif has_solid:
        nan_only_solid += 1
    elif has_nonsolid:
        nan_only_nonsolid += 1
    # else: not in any element (counted above)

print(f"  NaN nodes owned ONLY by solid elements   : {nan_only_solid}")
print(f"  NaN nodes owned ONLY by non-solid elems  : {nan_only_nonsolid}")
print(f"  NaN nodes shared solid + non-solid        : {nan_mixed}")
print()

# ---------------------------------------------------------------------------
# Section 6 — Compare temperature vs displacement coverage
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 6 — Displacement NaN coverage (set 0, for comparison)")
print("=" * 70)

try:
    nnum_d, disp = rst.nodal_solution(0)
    disp = np.asarray(disp)
    # Check first component (Ux)
    ux = disp[:, 0]
    n_disp_nan = int(np.sum(np.isnan(ux)))
    print(f"  Displacement nodes : {len(nnum_d)}, NaN in Ux : {n_disp_nan}")
    # Which displacement nodes also appear as temperature-NaN?
    disp_nids = set(nnum_d.tolist())
    overlap = nan_nids & disp_nids
    print(f"  Temp-NaN nodes also in disp result : {len(overlap)} of {len(nan_nids)}")
    print(f"  Temp-NaN nodes NOT in disp result  : {len(nan_nids - disp_nids)}")
except Exception as exc:
    print(f"  nodal_solution() failed: {exc}")
print()

# ---------------------------------------------------------------------------
# Section 7 — Compare temperature vs stress coverage
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 7 — Stress NaN coverage (set 0, for comparison)")
print("=" * 70)

try:
    nnum_s, stress = rst.nodal_stress(0)
    stress = np.asarray(stress)
    sxx = stress[:, 0]
    n_stress_nan = int(np.sum(np.isnan(sxx)))
    stress_nids = set(nnum_s.tolist())
    print(f"  Stress nodes : {len(nnum_s)}, NaN in SXX : {n_stress_nan}")
    # Nodes that have NaN temperature AND valid (finite) stress
    finite_stress_nids = set(
        int(nid) for nid, v in zip(nnum_s.tolist(), sxx.tolist()) if not np.isnan(v)
    )
    nan_temp_finite_stress = nan_nids & finite_stress_nids
    print(f"  Nodes with NaN temp BUT finite stress : {len(nan_temp_finite_stress)}")
    nan_temp_nan_stress = nan_nids & (stress_nids - finite_stress_nids)
    print(f"  Nodes with NaN temp AND NaN stress    : {len(nan_temp_nan_stress)}")
    nan_temp_not_in_stress = nan_nids - stress_nids
    print(f"  NaN temp nodes absent from stress set : {len(nan_temp_not_in_stress)}")
except Exception as exc:
    print(f"  nodal_stress() failed: {exc}")
print()

# ---------------------------------------------------------------------------
# Section 8 — PyAnsys result type introspection
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 8 — PyAnsys internal: how is temperature stored?")
print("=" * 70)

# ansys-mapdl-reader stores result types in rst.result_type or similar
try:
    print(f"  rst.result_type  : {rst.result_type}")
except Exception:
    print("  rst.result_type  : (not available)")

try:
    rt = rst._resulttypes
    print(f"  rst._resulttypes : {rt}")
except Exception:
    print("  rst._resulttypes : (not available)")

# Check available result names
try:
    rnames = rst.result_names
    print(f"  rst.result_names : {rnames}")
except Exception:
    print("  rst.result_names : (not available)")

# Check if elemental temperature is separate from nodal
try:
    nnum_et, elem_temp = rst.element_temperature(0)
    elem_temp = np.asarray(elem_temp)
    n_et_nan = int(np.sum(np.isnan(elem_temp)))
    print(f"  element_temperature(0): {len(nnum_et)} entries, {n_et_nan} NaN")
except AttributeError:
    print("  element_temperature()  : method not available in this version")
except Exception as exc:
    print(f"  element_temperature()  : {exc}")

# nodal_temperature underlying storage
try:
    raw = rst._nodal_temperature(0)
    print(f"  _nodal_temperature()   : type={type(raw)}, shape-like={np.asarray(raw[1]).shape if raw else 'None'}")
except Exception:
    pass

print()

# ---------------------------------------------------------------------------
# Section 9 — Sample NaN nodes detail
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 9 — Sample NaN nodes (first 10)")
print("=" * 70)

nan_sample = sorted(nan_nids)[:10]
coords = mesh.nodes  # (N,3)
nnum_all = mesh.nnum.tolist()
nid_to_idx = {nid: idx for idx, nid in enumerate(nnum_all)}

print(f"  {'NID':>8}  {'x':>12}  {'y':>12}  {'z':>12}  {'elem_types'}")
for nid in nan_sample:
    idx = nid_to_idx.get(nid)
    if idx is not None:
        x, y, z = coords[idx]
        etypes_str = str(sorted(node_to_etypes.get(nid, set())))
    else:
        x = y = z = float('nan')
        etypes_str = "(not in mesh.nnum)"
    print(f"  {nid:>8d}  {x:12.4f}  {y:12.4f}  {z:12.4f}  {etypes_str}")
print()

# ---------------------------------------------------------------------------
# Section 10 — Summary / conclusion
# ---------------------------------------------------------------------------
print("=" * 70)
print("SECTION 10 — Root cause summary")
print("=" * 70)

total_nan = len(nan_nids)
pct = 100. * total_nan / len(nnum_temp0) if len(nnum_temp0) else 0

causes = []
if nan_only_nonsolid > 0:
    causes.append(
        f"  [CAUSE A] {nan_only_nonsolid} NaN nodes are owned ONLY by non-solid elements "
        f"(surface/contact). Temperature is not solved on these element types."
    )
if nan_only_solid > 0:
    causes.append(
        f"  [CAUSE B] {nan_only_solid} NaN nodes are owned ONLY by solid elements. "
        f"This may indicate temperature was not requested/solved for all elements, "
        f"or the result set does not contain TEMP DOF."
    )
if nan_mixed > 0:
    causes.append(
        f"  [CAUSE C] {nan_mixed} NaN nodes are shared between solid and non-solid "
        f"elements. PyAnsys may report NaN when the best-available elemental value "
        f"comes from a non-solid element."
    )
if nan_nodes_not_in_elem > 0:
    causes.append(
        f"  [CAUSE D] {nan_nodes_not_in_elem} NaN nodes are not connected to any element "
        f"— orphaned/constraint nodes with no result."
    )

print(f"  Total NaN temp nodes : {total_nan} / {len(nnum_temp0)} ({pct:.1f}%)")
print()
for cause in causes:
    print(cause)
if not causes:
    print("  No clear structural cause identified — may be a step/DOF issue.")
print()
print("  RECOMMENDATION:")
print("  For CalculiX crack propagation, NDTEMP is optional.")
print("  If NaN nodes belong exclusively to non-solid (surface/contact) elements,")
print("  the correct fix is to skip temperature altogether, OR filter NaN nodes")
print("  before writing to FRD (as is already done for stress).")
