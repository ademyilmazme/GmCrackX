"""
Orchestrates the read → validate → write conversion pipeline.

Usage::

    manager = ConversionManager()
    reader  = manager.find_reader("results.rst")
    model   = reader.read("results.rst", fields=["STRESS","DISP"])
    issues  = model.validate()
    if not issues:
        manager.write_frd(model, "results.frd")
"""
from __future__ import annotations

import warnings
from pathlib import Path

from .base_reader import BaseResultReader
from .frd_writer import FrdWriter
from .neutral_model import NeutralModel


# ---------------------------------------------------------------------------
# Reader registry
# ---------------------------------------------------------------------------

def _build_default_registry() -> list[BaseResultReader]:
    """Instantiate all readers whose optional dependencies are available."""
    readers: list[BaseResultReader] = []

    # ANSYS RST (requires ansys-mapdl-reader)
    try:
        from .ansys_rst_reader import AnsysRstReader  # type: ignore
        readers.append(AnsysRstReader())
    except ImportError:
        warnings.warn(
            "ansys-mapdl-reader not found; ANSYS RST import is disabled. "
            "Install with:  pip install ansys-mapdl-reader",
            ImportWarning,
            stacklevel=2,
        )

    return readers


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ConversionManager:
    """High-level pipeline: detect format → read → validate → write FRD.

    Parameters
    ----------
    readers:
        Explicit list of reader instances.  If *None* the default registry
        is used (all readers whose dependencies are installed).
    """

    def __init__(
        self,
        readers: list[BaseResultReader] | None = None,
    ) -> None:
        self._readers: list[BaseResultReader] = (
            readers if readers is not None else _build_default_registry()
        )

    # ------------------------------------------------------------------
    # Reader discovery
    # ------------------------------------------------------------------

    @property
    def available_readers(self) -> list[BaseResultReader]:
        """All registered reader instances."""
        return list(self._readers)

    def find_reader(self, path: str | Path) -> BaseResultReader | None:
        """Return the first registered reader that claims it can handle *path*.

        Returns *None* if no reader is found.
        """
        for reader in self._readers:
            try:
                if reader.can_read(path):
                    return reader
            except Exception:
                continue
        return None

    def inspect(self, path: str | Path) -> dict:
        """Lightweight metadata extraction (no full parse).

        Returns an info dict; includes ``"error"`` key on failure.
        """
        reader = self.find_reader(path)
        if reader is None:
            return {"error": f"No reader found for: {path}"}
        try:
            return reader.inspect(path)
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Conversion pipeline
    # ------------------------------------------------------------------

    def convert(
        self,
        source: str | Path,
        dest: str | Path,
        fields: list[str] | None = None,
        increments: list[int] | None = None,
        validate: bool = True,
        component_names: list[str] | None = None,
    ) -> list[str]:
        """Convert *source* to a CalculiX FRD file at *dest*.

        Parameters
        ----------
        source:
            Input result file (e.g. ``.rst``).
        dest:
            Output ``.frd`` path (created/overwritten).
        fields:
            Subset of field names to convert (``None`` = all available).
        increments:
            0-based increment indices (``None`` = all).
        validate:
            If *True* (default), run :meth:`NeutralModel.validate` before
            writing and return issues as a non-empty list on failure.
        component_names:
            If given, restrict the export to elements belonging to the named
            components (named selections).  ``None`` = full model.

        Returns
        -------
        list[str]
            Empty on success.  Non-empty = validation errors (file NOT written).
        """
        reader = self.find_reader(source)
        if reader is None:
            return [f"No reader found for: {source}"]

        model: NeutralModel = reader.read(source, fields=fields, increments=increments)

        if component_names:
            model = model.subset(component_names)

        if validate:
            issues = model.validate()
            if issues:
                return issues

        writer = FrdWriter(model)
        writer.write(dest)
        return []

    def write_frd(self, model: NeutralModel, dest: str | Path) -> None:
        """Write an already-built NeutralModel directly to *dest*."""
        FrdWriter(model).write(dest)
