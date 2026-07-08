"""Base types for value screening models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelResult:
    model_id: str
    model_name: str
    passed: bool
    score: float  # 0.0 – 1.0 within this model
    reasons: list[str] = field(default_factory=list)
    failed_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "passed": self.passed,
            "score": round(self.score, 4),
            "reasons": self.reasons,
            "failed_criteria": self.failed_criteria,
        }


class ValueModel(ABC):
    id: str
    name: str

    @abstractmethod
    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        """Evaluate a single company's metrics."""

    def _result(
        self,
        *,
        passed: bool,
        score: float,
        reasons: list[str] | None = None,
        failed_criteria: list[str] | None = None,
    ) -> ModelResult:
        return ModelResult(
            model_id=self.id,
            model_name=self.name,
            passed=passed,
            score=max(0.0, min(1.0, score)),
            reasons=reasons or [],
            failed_criteria=failed_criteria or [],
        )
