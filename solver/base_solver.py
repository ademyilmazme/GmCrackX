from abc import ABC, abstractmethod
import numpy as np
from core.mesh_io import MeshData


class BaseSolver(ABC):

    @abstractmethod
    def write_input(self, mesh: MeshData, bcs: dict, output_path: str) -> str:
        """Write solver input file. Return path."""

    @abstractmethod
    def run(self, input_path: str, n_cpus: int = 4) -> str:
        """Execute solver. Return results directory path."""

    @abstractmethod
    def read_displacements(self, results_path: str) -> dict[int, np.ndarray]:
        """Read nodal displacements {node_id: (3,)} from results."""

    @abstractmethod
    def read_nodal_forces(self, results_path: str) -> dict[int, np.ndarray]:
        """Read nodal reaction forces {node_id: (3,)} from results."""
