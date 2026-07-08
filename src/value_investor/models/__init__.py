"""Value investment screening models."""

from value_investor.models.composite import CompositeValueModel
from value_investor.models.graham import GrahamDefensiveModel
from value_investor.models.graham_enterprising import GrahamEnterprisingModel
from value_investor.models.quality_value import QualityValueModel

__all__ = [
    "CompositeValueModel",
    "GrahamDefensiveModel",
    "GrahamEnterprisingModel",
    "QualityValueModel",
    "ALL_MODELS",
]

ALL_MODELS = [
    GrahamDefensiveModel(),
    GrahamEnterprisingModel(),
    QualityValueModel(),
    CompositeValueModel(),
]
