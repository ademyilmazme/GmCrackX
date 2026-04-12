"""
Investigate SOLID186 / C3D20 node ordering from ansys-mapdl-reader.

Checks:
1. Are midside nodes geometrically at the midpoints of their edge corners?
2. Does the ANSYS connectivity order match CalculiX C3D20 ordering?
3. Are DISP values NaN at midside nodes (like STRESS and NDTEMP)?
4. What does the element look like in the FRD for one sample element?

Run:
    cd C:\\Users\\Adem\\source\\repos\\GmCrackX
    python tests/investigate_c3d20_order.py
"""
import sys
sys.path.insert(0, '.')

import numpy as np
from pathlib import Path

RST_FILE = Path("tests/example/ex-2/file.rst")

# ---------------------------------------------------------------------------
# Open RST
# ---------------------------------------------------------------------------
from convert.ansys_rst_reader import AnsysRstReader
rst = AnsysRstReader._open(RST_FILE)
mesh = rst.mesh

# Node coordinates dict
nnum_all = mesh.nnum.tolist()
coords_all = mesh.nodes.tolist()
node_xyz = {int(n): np.array(c) for n, c in zip(nnum_all, coords_all)}

print(f"Total nodes in mesh: {len(node_xyz)}")

# ---------------------------------------------------------------------------
# Find first SOLID186 element (etype=186) and inspect connectivity
# ---------------------------------------------------------------------------
etype_arr = mesh.etype.tolist()
enum_arr  = mesh.enum.tolist()
econn     = mesh.elem

# C3D20 CalculiX expected midside edge table (local indices)
# Local idx → (cornerA_local, cornerB_local)
C3D20_MIDSIDE_EDGES = {
     8: (0, 1),  9: (1, 2), 10: (2, 3), 11: (3, 0),
    12: (4, 5), 13: (5, 6), 14: (6, 7), 15: (7, 4),
    16: (0, 4), 17: (1, 5), 18: (2, 6), 19: (3, 7),
}

# ANSYS SOLID186 midside edge table (local indices, I=0,...P=7, Q=8,...B=19)
# same as CalculiX C3D20 — checking if they match
ANSYS_SOLID186_EDGES = {
    8:  (0, 1),   # Q = mid(I,J)
    9:  (1, 2),   # R = mid(J,K)
    10: (2, 3),   # S = mid(K,L)
    11: (3, 0),   # T = mid(L,I)
    12: (4, 5),   # U = mid(M,N)
    13: (5, 6),   # V = mid(N,O)
    14: (6, 7),   # W = mid(O,P)
    15: (7, 4),   # X = mid(P,M)
    16: (0, 4),   # Y = mid(I,M)
    17: (1, 5),   # Z = mid(J,N)
    18: (2, 6),   # A = mid(K,O)
    19: (3, 7),   # B = mid(L,P)
}

print("\n--- Checking first 5 SOLID186 elements ---")
n_checked = 0
total_errors = 0

for eid, et, conn in zip(enum_arr, etype_arr, econn):
    if int(et) != 186:
        continue
    if n_checked >= 5:
        break

    nids = [int(n) for n in conn[10:] if n > 0]
    print(f"\nElement {eid}: {len(nids)} nodes")
    print(f"  conn[10:] raw = {list(conn[10:30])}")
    print(f"  nids (no zeros) = {nids}")

    if len(nids) < 20:
        print(f"  WARNING: only {len(nids)} nodes — expected 20!")
        n_checked += 1
        continue

    # Check each midside node is geometrically at the midpoint
    n_errors = 0
    for mid_local, (ca_local, cb_local) in C3D20_MIDSIDE_EDGES.items():
        mid_nid = nids[mid_local]
        ca_nid  = nids[ca_local]
        cb_nid  = nids[cb_local]

        mid_pos = node_xyz.get(mid_nid)
        ca_pos  = node_xyz.get(ca_nid)
        cb_pos  = node_xyz.get(cb_nid)

        if mid_pos is None or ca_pos is None or cb_pos is None:
            print(f"  ERROR: missing node coordinates for local-{mid_local}")
            n_errors += 1
            continue

        expected_mid = (ca_pos + cb_pos) * 0.5
        error = np.linalg.norm(mid_pos - expected_mid)

        if error > 1e-8:
            print(f"  MISMATCH local-{mid_local}: nid={mid_nid}")
            print(f"    position:  {mid_pos}")
            print(f"    expected:  {expected_mid}  (midpoint of {ca_nid},{cb_nid})")
            print(f"    error:     {error:.3e}")
            n_errors += 1

    if n_errors == 0:
        print(f"  OK: all 12 midside nodes are at correct edge midpoints")
    else:
        print(f"  {n_errors} MIDSIDE POSITION ERRORS")
    total_errors += n_errors
    n_checked += 1

print(f"\nTotal midside geometry errors: {total_errors}")

# ---------------------------------------------------------------------------
# Check DISP (nodal_solution) NaN at midside nodes
# ---------------------------------------------------------------------------
print("\n--- Checking DISP at midside nodes ---")
nnum_disp, disp = rst.nodal_solution(0)
disp_map = {}
for nid, d in zip(nnum_disp.tolist(), disp.tolist()):
    disp_map[int(nid)] = np.asarray(d[:3], dtype=float)

# Classify midside-only nodes from first 10 C3D20 elements
corner_nodes = set()
midside_nodes = set()
count = 0
for eid, et, conn in zip(enum_arr, etype_arr, econn):
    if int(et) != 186: continue
    nids = [int(n) for n in conn[10:] if n > 0]
    if len(nids) < 20: continue
    for i in range(8):  corner_nodes.add(nids[i])
    for i in range(8, 20): midside_nodes.add(nids[i])
    count += 1
    if count >= 20: break

midside_only = midside_nodes - corner_nodes

nan_disp_count = sum(
    1 for nid in midside_only
    if nid in disp_map and not np.all(np.isfinite(disp_map[nid]))
)
total_checked = sum(1 for nid in midside_only if nid in disp_map)

print(f"Midside-only nodes sampled : {len(midside_only)}")
print(f"With DISP in RST           : {total_checked}")
print(f"NaN DISP at midside nodes  : {nan_disp_count}")
if total_checked > 0:
    sample = next(iter(midside_only))
    print(f"Sample midside disp [nid={sample}]: {disp_map.get(sample)}")

# Also check a corner node for comparison
corner_sample = next(iter(corner_nodes - midside_nodes), None)
if corner_sample:
    print(f"Sample corner  disp [nid={corner_sample}]: {disp_map.get(corner_sample)}")

# ---------------------------------------------------------------------------
# Compare raw conn[10:30] layout — are zeros inserted between corners/midsides?
# ---------------------------------------------------------------------------
print("\n--- Raw conn layout for first SOLID186 ---")
for eid, et, conn in zip(enum_arr, etype_arr, econn):
    if int(et) != 186: continue
    print(f"Element {eid}:")
    print(f"  conn[8] (eid field)  = {conn[8]}")
    print(f"  conn[9]              = {conn[9]}")
    print(f"  conn[10:18] corners? = {list(conn[10:18])}")
    print(f"  conn[18:30] midsides?= {list(conn[18:30])}")
    # Check for zeros in the middle
    zeros_in_middle = [i for i in range(10, 30) if conn[i] == 0]
    if zeros_in_middle:
        print(f"  WARNING: zeros found at positions {zeros_in_middle}")
    else:
        print(f"  No zeros in conn[10:30]")
    break

print("\nDone.")
