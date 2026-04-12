"""
Abstract base class for all result-format readers.

Each reader knows how to detect, inspect, and convert one source format into
a :class:`~convert.neutral_model.NeutralModel`.  Readers are registered with
:class:`~convert.conversion_manager.ConversionManager` at import time.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .neutral_model import NeutralModel


class BaseResultReader(ABC):
    """Interface every format-specific reader must implement."""

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @classmethod
    @abstractmethod
    def can_read(cls, path: str | Path) -> bool:
        """Return *True* if this reader can handle the given file.

        The check should be fast (extension test + optional magic bytes) and
        must **not** raise — return *False* on any access error instead.
        """

    # ------------------------------------------------------------------
    # Inspection (light-weight, no full parse)
    # ------------------------------------------------------------------

    @abstractmethod
    def inspect(self, path: str | Path) -> dict:
        """Return a metadata dict describing the file without fully parsing it.

        Typical keys (all optional):
          ``n_nodes``       – node count
          ``n_elements``    – element count
          ``n_increments``  – result increment count
          ``fields``        – list of available field names (e.g. ["STRESS","DISP"])
          ``solver``        – originating solver string
          ``title``         – file title / description
        """

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    @abstractmethod
    def read(
        self,
        path: str | Path,
        fields: list[str] | None = None,
        increments: list[int] | None = None,
    ) -> NeutralModel:
        """Parse *path* and return a :class:`NeutralModel`.

        Parameters
        ----------
        path:
            Source file path.
        fields:
            Subset of result field names to import (``None`` = all).
            Unknown names are silently ignored.
        increments:
            0-based increment indices to import (``None`` = all).
            Out-of-range indices are silently ignored.
        """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Human-readable reader name (defaults to class name)."""
        return type(self).__name__

    def __repr__(self) -> str:
        return f"<{self.name}>"
