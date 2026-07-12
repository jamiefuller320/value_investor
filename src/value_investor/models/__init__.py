"""Value investment screening models."""

from value_investor.models.buffett import BuffettQualityModel, EconomicMoatModel
from value_investor.models.carlisle import AcquirersMultipleModel
from value_investor.models.classic import (
    DeepValueModel,
    EarningsYieldModel,
    FCFYieldModel,
    LynchPEGModel,
    SchlossModel,
)
from value_investor.models.composite import CompositeValueModel
from value_investor.models.dividend import DividendGrowthModel, HighDividendYieldModel
from value_investor.models.dreman import DremanContrarianModel
from value_investor.models.graham import GrahamDefensiveModel
from value_investor.models.graham_enterprising import GrahamEnterprisingModel
from value_investor.models.greenblatt import MagicFormulaModel
from value_investor.models.neff import LowPEHighYieldModel, NeffPEGYModel
from value_investor.models.net_net import NetNetModel
from value_investor.models.piotroski import PiotroskiFScoreModel
from value_investor.models.quality_value import QualityValueModel
from value_investor.models.risk import EarningsQualityModel, FinancialHealthModel

__all__ = [
    "GrahamDefensiveModel",
    "GrahamEnterprisingModel",
    "QualityValueModel",
    "CompositeValueModel",
    "LynchPEGModel",
    "SchlossModel",
    "DeepValueModel",
    "FCFYieldModel",
    "EarningsYieldModel",
    "MagicFormulaModel",
    "AcquirersMultipleModel",
    "NetNetModel",
    "PiotroskiFScoreModel",
    "DremanContrarianModel",
    "HighDividendYieldModel",
    "DividendGrowthModel",
    "BuffettQualityModel",
    "EconomicMoatModel",
    "NeffPEGYModel",
    "LowPEHighYieldModel",
    "EarningsQualityModel",
    "FinancialHealthModel",
    "ALL_MODELS",
]

ALL_MODELS = [
    # Graham family
    GrahamDefensiveModel(),
    GrahamEnterprisingModel(),
    NetNetModel(),
    # Classic value
    SchlossModel(),
    DeepValueModel(),
    EarningsYieldModel(),
    FCFYieldModel(),
    LowPEHighYieldModel(),
    # Growth at reasonable price
    LynchPEGModel(),
    NeffPEGYModel(),
    # Quality / moat
    QualityValueModel(),
    BuffettQualityModel(),
    EconomicMoatModel(),
    # Dividend
    HighDividendYieldModel(),
    DividendGrowthModel(),
    # Quantitative ranked
    MagicFormulaModel(),
    AcquirersMultipleModel(),
    DremanContrarianModel(),
    PiotroskiFScoreModel(),
    CompositeValueModel(),
    # Risk
    EarningsQualityModel(),
    FinancialHealthModel(),
]
