"""
CalculiX solver implementation.

Writes a complete .inp file, runs ccx as a subprocess,
and parses the resulting .frd and .dat files.
"""
from __future__ import annotations
import subprocess
import shutil
from pathlib import Path

import numpy as np

from core.mesh_io import MeshData
from solver.base_solver import BaseSolver
from crack_io.inp_writer import write_inp
from crack_io.frd_reader import get_last_displacements, get_last_forces


class CalculiXSolver(BaseSolver):

    def __init__(self, ccx_path: str = "ccx", n_cpus: int = 4):
        self.ccx_path = ccx_path
        self.n_cpus   = n_cpus

    # ------------------------------------------------------------------
    # write_input
    # ------------------------------------------------------------------

    def write_input(self, mesh: MeshData, bcs: dict, output_path: str) -> str:
        """
        Write a CalculiX .inp file for a static linear-elastic analysis.

        bcs dict keys (all optional):
          'step_name'   : str
          'output_vars' : list[str]  e.g. ['U', 'S', 'RF']
          'nlgeom'      : bool
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        step_name   = bcs.get("step_name",   "Static")
        output_vars = bcs.get("output_vars", ["U", "S", "RF"])
        nlgeom      = bcs.get("nlgeom",      False)

        # Write mesh
        write_inp(mesh, path, title=f"Crack3D — {step_name}")

        # Append step definition
        with open(path, "a") as f:
            nlgeom_flag = ", NLGEOM" if nlgeom else ""
            f.write(f"\n*STEP{nlgeom_flag}\n")
            f.write(f"*STATIC\n")
            f.write("\n*NODE FILE\n")
            for v in output_vars:
                if v in ("U", "RF"):
                    f.write(f"{v}\n")
            f.write("\n*EL FILE\n")
            for v in output_vars:
                if v in ("S", "E"):
                    f.write(f"{v}\n")
            f.write("\n*NODE PRINT, NSET=NALL\n")
            f.write("RF\n")
            f.write("\n*END STEP\n")

        return str(path)

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self, input_path: str, n_cpus: int | None = None) -> str:
        """
        Execute CalculiX on the given .inp file.
        Returns the directory where results (.frd, .dat) are written.
        """
        n_cpus = n_cpus or self.n_cpus
        inp    = Path(input_path)
        stem   = inp.stem
        work   = inp.parent

        # CalculiX is invoked without the .inp extension
        cmd = [self.ccx_path, "-i", stem]

        env = {"OMP_NUM_THREADS": str(n_cpus)}
        import os
        full_env = {**os.environ, **env}

        result = subprocess.run(
            cmd,
            cwd=str(work),
            capture_output=True,
            text=True,
            env=full_env,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"CalculiX failed (exit {result.returncode}):\n"
                f"{result.stdout[-2000:]}\n{result.stderr[-1000:]}"
            )

        return str(work)

    # ------------------------------------------------------------------
    # read_displacements / read_nodal_forces
    # ------------------------------------------------------------------

    def read_displacements(self, results_path: str) -> dict[int, np.ndarray]:
        frd = self._find_frd(results_path)
        return get_last_displacements(frd)

    def read_nodal_forces(self, results_path: str) -> dict[int, np.ndarray]:
        frd = self._find_frd(results_path)
        return get_last_forces(frd)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_frd(self, results_path: str) -> str:
        work = Path(results_path)
        frds = list(work.glob("*.frd"))
        if not frds:
            raise FileNotFoundError(f"No .frd file found in {results_path}")
        # Return the most recently modified
        return str(sorted(frds, key=lambda p: p.stat().st_mtime)[-1])

    # ------------------------------------------------------------------
    # Crack propagation support
    # ------------------------------------------------------------------

    def run_crack_propagation(
        self,
        prop_deck_path: str,
        n_cpus: int | None = None,
    ) -> str:
        """
        Run a *CRACK PROPAGATION input deck.

        Returns the path to the output .frd file.
        Raises RuntimeError if CalculiX returns non-zero exit code.
        """
        results_dir = self.run(prop_deck_path, n_cpus=n_cpus)
        return self._find_frd(results_dir)

    def is_available(self) -> bool:
        """Check whether the ccx executable exists (full path or on PATH)."""
        return Path(self.ccx_path).is_file() or shutil.which(self.ccx_path) is not None
