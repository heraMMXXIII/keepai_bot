from dataclasses import dataclass
from typing import Optional


@dataclass
class BalanceResult:
    service: str
    ok: bool
    value: Optional[float] = None
    unit: str = ""
    error: Optional[str] = None


@dataclass
class HealthResult:
    service: str
    ok: bool
    error: Optional[str] = None

