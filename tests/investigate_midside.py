"""
Quick check: are the NaN temperature nodes the midside nodes of SOLID186?

SOLID186 (C3D20) has 20 nodes per element:
  conn[10:18]  → 8 corner nodes  (indices 0-7 in element)
  conn[18:30]  → 12 midside nodes (indices 8-19 in element)

Run with:
    conda run --no-capture-output -n gmcrackx python tests/investigate_midside.py
"""
from __future__ import annotations
import sys, types
from pathlib import Path
import numpy as np

RST_FILE = Path(__file__).parent / "example" / "ex-2" / "file.rst"

# ---- pyvista patches -------------------------------------------------------
def _stub(name, parent=None):
    mod = types.ModuleType(name); mod.__path__ = []; sys.modules[name] = mod
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], name.rsplit(".", 1)[-1], mod)
    return mod

if "pyvista.utilities.sphinx_gallery" not in sys.modules:
    if "pyvista.utilities" not in sys.modules: _stub("pyvista.utilities")
    sg = _stub("pyvista.utilities.sphinx_gallery", "pyvista.utilities")
    sg._get_sg_image_scraper = lambda: None
try:
    import pyvista.plotting.utilities as _pvu
    if not hasattr(_pvu, "_get_sg_image_scraper"): _pvu._get_sg_image_scraper = lambda: None
except Exception: pass
if "vtkmodules.vtkRenderingMatplotlib" not in sys.modules:
    _stub("vtkmodules.vtkRenderingMatplotlib", "vtkmodules")

from ansys.mapdl.reader.common import read_binary
rst = read_binary(str(RST_FILE))
# ---------------------------------------------------------------------------

mesh = rst.mesh
nnum_t, temps = rst.nodal_temperature(0)
temps = np.asarray(temps)
nan_nids = set(int(n) for n, t in zip(nnum_t.tolist(), temps.tolist()) if not np.isfinite(float(t)))
finite_nids = set(int(n) for n, t in zip(nnum_t.tolist(), temps.tolist()) if np.isfinite(float(t)))

print(f"Total nodes        : {mesh.n_node}")
print(f"Finite temp nodes  : {len(finite_nids)}")
print(f"NaN temp nodes     : {len(nan_nids)}")
print()

# For SOLID186 elements classify corner vs midside
# conn layout: [mat,type,real,sect,esys,death,solid,tshape, eid, 0, n1..n20]
#               idx 0..7                                    8    9  10..29
corner_nids:  set[int] = set()
midside_nids: set[int] = set()

SOLID186 = 186
for eid, etype, conn in zip(mesh.enum.tolist(), mesh.etype.tolist(), mesh.elem):
    if int(etype) != SOLID186:
        continue
    node_ids = [int(n) for n in conn[10:] if n > 0]
    if len(node_ids) == 20:
        corner_nids.update(node_ids[:8])
        midside_nids.update(node_ids[8:])
    elif len(node_ids) == 8:
        corner_nids.update(node_ids)   # degenerate / linear

# A node can be a corner of one element and midside of another — classify by majority role
only_corner  = corner_nids - midside_nids
only_midside = midside_nids - corner_nids
both_roles   = corner_nids & midside_nids

print(f"SOLID186 corner-only nodes  : {len(only_corner)}")
print(f"SOLID186 midside-only nodes : {len(only_midside)}")
print(f"SOLID186 both-role nodes    : {len(both_roles)}")
print()

# Cross-check with NaN
nan_corner_only  = nan_nids & only_corner
nan_midside_only = nan_nids & only_midside
nan_both         = nan_nids & both_roles
nan_not_solid186 = nan_nids - corner_nids - midside_nids

print("NaN nodes breakdown by node role in SOLID186:")
print(f"  corner-only  nodes with NaN : {len(nan_corner_only):6d} / {len(only_corner):6d}  ({100.*len(nan_corner_only)/max(1,len(only_corner)):.1f}%)")
print(f"  midside-only nodes with NaN : {len(nan_midside_only):6d} / {len(only_midside):6d}  ({100.*len(nan_midside_only)/max(1,len(only_midside)):.1f}%)")
print(f"  both-role    nodes with NaN : {len(nan_both):6d} / {len(both_roles):6d}  ({100.*len(nan_both)/max(1,len(both_roles)):.1f}%)")
print(f"  not in SOLID186             : {len(nan_not_solid186):6d}")
print()

# Finite temp by role
fin_corner  = finite_nids & only_corner
fin_midside = finite_nids & only_midside
fin_both    = finite_nids & both_roles
print("Finite-temp nodes breakdown:")
print(f"  corner-only  : {len(fin_corner):6d} / {len(only_corner):6d}  ({100.*len(fin_corner)/max(1,len(only_corner)):.1f}%)")
print(f"  midside-only : {len(fin_midside):6d} / {len(only_midside):6d}  ({100.*len(fin_midside)/max(1,len(only_midside)):.1f}%)")
print(f"  both-role    : {len(fin_both):6d} / {len(both_roles):6d}  ({100.*len(fin_both)/max(1,len(both_roles)):.1f}%)")
print()

print("=" * 50)
if len(nan_corner_only) == 0 and len(nan_midside_only) == len(only_midside):
    print("CONCLUSION: NaN nodes ARE exclusively the midside nodes.")
elif len(nan_midside_only) == len(only_midside) and len(nan_corner_only) == 0:
    print("CONCLUSION: All midside-only nodes are NaN; no corner-only nodes are NaN.")
else:
    print("CONCLUSION: NaN does NOT map cleanly to midside-only nodes.")
    print(f"  Corner-only NaN  : {len(nan_corner_only)}")
    print(f"  Midside-only NaN : {len(nan_midside_only)} (of {len(only_midside)} total midside-only)")
