"""
PropRunner — single-pass orchestrator for CalculiX *CRACK PROPAGATION.

Pipeline:
  1. Validate config and FRD
  2. Build S3 crack surface mesh
  3. Write propagation INP deck
  4. Run CalculiX
  5. Read KEQ results from output FRD
  6. Return PropResult
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pipeline.prop_config import PropagationConfig
from core.crack_surface_s3 import CrackSurfaceBuilder, CrackSurfaceState
from crack_io.prop_deck_writer import PropDeckWriter
from crack_io.frd_reader import KEQIncrement, read_keq_results
from solver.calculix_solver import CalculiXSolver


@dataclass
class PropResult:
    """Container for crack propagation results."""

    keq_increments: list[KEQIncrement] = field(default_factory=list)
    """KEQ output from each propagation increment."""

    crack_surface: CrackSurfaceState | None = None
    """Initial crack surface (the S3 mesh that was fed to CalculiX)."""

    output_frd_path: str = ""
    """Path to the output .frd file from CalculiX."""

    deck_path: str = ""
    """Path to the propagation .inp deck that was written."""

    status: str = "not_run"
    """One of: not_run, success, ccx_error, no_results."""

    ccx_stdout: str = ""
    """CalculiX stdout (for diagnostics)."""

    @property
    def n_increments(self) -> int:
        return len(self.keq_increments)

    @property
    def final_crack_length(self) -> float:
        """CRLENGTH from the last increment's last node, or 0.0."""
        if not self.keq_increments:
            return 0.0
        last = self.keq_increments[-1]
        for nid in sorted(last.keq_data.keys()):
            val = last.keq_data[nid].get("CRLENGTH", 0.0)
            if val > 0:
                return val
        return 0.0


class PropRunner:
    """
    Single-pass orchestrator: validate → build S3 → write deck → run CCX → read.

    Usage::

        config = PropagationConfig(uncracked_frd="...", initial_crack="...", ...)
        result = PropRunner(config).run()
    """

    def __init__(self, config: PropagationConfig) -> None:
        self.config = config

    def run(
        self,
        progress_cb: Callable[[int, str], None] | None = None,
    ) -> PropResult:
        """
        Execute the full propagation pipeline.

        Parameters
        ----------
        progress_cb : optional callback(percent, message) for UI progress updates

        Returns
        -------
        PropResult with KEQ increments and metadata.
        """
        def _progress(pct: int, msg: str) -> None:
            if progress_cb is not None:
                progress_cb(pct, msg)

        result = PropResult()
        cfg = self.config
        work_dir = Path(cfg.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------
        # 1. Validate
        # ------------------------------------------------------------------
        _progress(5, "Validating configuration...")
        cfg.validate()

        # ------------------------------------------------------------------
        # 2. Build S3 crack surface
        # ------------------------------------------------------------------
        _progress(15, "Building S3 crack surface mesh...")
        builder = CrackSurfaceBuilder(
            cfg.initial_crack,
            mesh_size=cfg.crack_mesh_size,
            angular_deflection=cfg.crack_angular_deflection,
            normal_hint=cfg.normal_hint,
        )
        state = builder.build()
        result.crack_surface = state

        crack_inp_path = str(work_dir / "crack_surface.inp")
        CrackSurfaceBuilder.write_s3_inp(state, crack_inp_path)
        _progress(30, f"S3 mesh: {len(state.vertices)} nodes, {len(state.triangles)} elements")

        # ------------------------------------------------------------------
        # 3. Write propagation deck
        # ------------------------------------------------------------------
        _progress(40, "Writing propagation INP deck...")
        writer = PropDeckWriter(cfg, crack_inp_path, cfg.uncracked_frd)
        deck_path = writer.write(str(work_dir))
        result.deck_path = deck_path
        _progress(50, f"Deck written: {deck_path}")

        # ------------------------------------------------------------------
        # 4. Run CalculiX
        # ------------------------------------------------------------------
        _progress(55, "Running CalculiX...")
        solver = CalculiXSolver(ccx_path=cfg.ccx_path, n_cpus=cfg.n_cpus)

        try:
            frd_path = solver.run_crack_propagation(deck_path, n_cpus=cfg.n_cpus)
            result.output_frd_path = frd_path
        except RuntimeError as exc:
            result.status = "ccx_error"
            result.ccx_stdout = str(exc)
            _progress(100, f"CalculiX failed: {exc}")
            return result

        _progress(80, "CalculiX finished. Reading results...")

        # ------------------------------------------------------------------
        # 5. Read KEQ results
        # ------------------------------------------------------------------
        try:
            keq = read_keq_results(frd_path)
            result.keq_increments = keq
        except Exception as exc:
            result.status = "no_results"
            result.ccx_stdout = f"FRD parse error: {exc}"
            _progress(100, f"Result parsing failed: {exc}")
            return result

        if not keq:
            result.status = "no_results"
            _progress(100, "No KEQ data found in output FRD")
            return result

        result.status = "success"
        _progress(100, f"Done — {len(keq)} increments, final length={result.final_crack_length:.4f}")
        return result
