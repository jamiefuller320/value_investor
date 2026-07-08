"""Base class for models that need universe calibration."""

from __future__ import annotations

from abc import abstractmethod
from typing import Self

import pandas as pd

from value_investor.models.base import ValueModel
from value_investor.models.ranking import compute_derived_columns


class UniverseFittedModel(ValueModel):
    """Model that must be fitted on the full universe before per-row evaluation."""

    def __init__(self) -> None:
        self._universe: pd.DataFrame | None = None

    @abstractmethod
    def fit(self, universe: pd.DataFrame) -> Self:
        """Calibrate percentiles / ranks from the screening universe."""

    def _require_universe(self) -> pd.DataFrame:
        if self._universe is None or self._universe.empty:
            raise ValueError(f"{self.id} not fitted")
        return self._universe

    def _fit_base(self, universe: pd.DataFrame) -> pd.DataFrame:
        self._universe = compute_derived_columns(universe)
        return self._universe
