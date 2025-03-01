from enum import StrEnum


class IstaConsumptionType(StrEnum):
    """Types of consumption measurements from Ista Calista."""

    HEATING = "heating"
    HOT_WATER = "warmwater"
    WATER = "water"
    