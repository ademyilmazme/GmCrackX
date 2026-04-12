"""Check: are NaN stress nodes the midside nodes of SOLID186?"""
import sys, types
from pathlib import Path
import numpy as np

RST_FILE = Path(__file__).parent / "example" / "ex-2" / "file.rst"

def _stub(name, parent=None):
    mod = types.ModuleType(name); mod.__path__ = []; sys.modules[name] = mod
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], name.rsplit(".",1)[-1], mod)
    return mod
if "pyvista.utilities.sphinx_gallery" not in sys.modules:
    if "pyvista.utilities" not in sys.modules: _stub("pyvista.utilities")
    sg = _stub("pyvista.utilities.sphinx_gallery","pyvista.utilities"); sg._get_sg_image_scraper = lambda: None
try:
    import pyvista.plotting.utilities as _p
    if not hasattr(_p,"_get_sg_image_scraper"): _p._get_sg_image_scraper = lambda: None
except: pass
if "vtkmodules.vtkRenderingMatplotlib" not in sys.modules:
    _stub("vtkmodules.vtkRenderingMatplotlib","vtkmodules")

from ansys.mapdl.reader.common import read_binary
rst = read_binary(str(RST_FILE))
mesh = rst.mesh

corner_nids, midside_nids = set(), set()
for eid, etype, conn in zip(mesh.enum.tolist(), mesh.etype.tolist(), mesh.elem):
    if int(etype) != 186: continue
    nids = [int(n) for n in conn[10:] if n > 0]
    if len(nids) == 20:
        corner_nids.update(nids[:8])
        midside_nids.update(nids[8:])

only_corner  = corner_nids - midside_nids
only_midside = midside_nids - corner_nids

nnum_s, stress = rst.nodal_stress(0)
stress = np.asarray(stress)
nan_stress  = set(int(n) for n, s in zip(nnum_s.tolist(), stress[:, 0].tolist()) if not np.isfinite(s))
fin_stress  = set(int(n) for n, s in zip(nnum_s.tolist(), stress[:, 0].tolist()) if np.isfinite(s))

print(f"Stress NaN nodes              : {len(nan_stress)}")
print(f"Midside-only nodes            : {len(only_midside)}")
print(f"Corner-only nodes             : {len(only_corner)}")
print()
print(f"NaN stress ∩ corner-only      : {len(nan_stress & only_corner)}")
print(f"NaN stress ∩ midside-only     : {len(nan_stress & only_midside)}")
print(f"Finite stress ∩ midside-only  : {len(fin_stress & only_midside)}")
print(f"Finite stress ∩ corner-only   : {len(fin_stress & only_corner)}")
print()
if nan_stress == only_midside:
    print("CONCLUSION: NaN stress nodes ARE exactly the midside-only nodes.")
else:
    print("CONCLUSION: NaN stress does NOT map cleanly to midside-only nodes.")
    print(f"  NaN but not midside-only : {len(nan_stress - only_midside)}")
    print(f"  Midside-only but finite  : {len(only_midside - nan_stress)}")
