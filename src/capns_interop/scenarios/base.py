"""Base classes for test scenarios."""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any


class ScenarioStatus(Enum):
    """Status of scenario execution."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


@dataclass
class ScenarioResult:
    """Result of scenario execution."""

    status: ScenarioStatus
    duration_ms: float
    error_message: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        status_str = self.status.value.upper()
        duration_str = f"{self.duration_ms:.2f}ms"

        if self.status == ScenarioStatus.PASS:
            return f"✓ {status_str} ({duration_str})"
        elif self.error_message:
            return f"✗ {status_str} ({duration_str}): {self.error_message}"
        else:
            return f"✗ {status_str} ({duration_str})"


class Scenario(ABC):
    """Base class for all test scenarios."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique scenario name."""
        pass

    @property
    def description(self) -> str:
        """Human-readable description."""
        return self.name

    @abstractmethod
    async def execute(self, host, plugin) -> ScenarioResult:
        """Execute scenario and return result."""
        pass

    async def _timed_execute(self, func):
        """Execute function and measure duration."""
        start = time.perf_counter()
        try:
            await func()
            duration_ms = (time.perf_counter() - start) * 1000
            return ScenarioResult(status=ScenarioStatus.PASS, duration_ms=duration_ms)
        except AssertionError as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return ScenarioResult(
                status=ScenarioStatus.FAIL,
                duration_ms=duration_ms,
                error_message=str(e),
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return ScenarioResult(
                status=ScenarioStatus.ERROR,
                duration_ms=duration_ms,
                error_message=f"{type(e).__name__}: {str(e)}",
            )
