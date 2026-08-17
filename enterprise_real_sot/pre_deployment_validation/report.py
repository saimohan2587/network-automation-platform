"""Pre-Deployment Validation reporting objects and outcome dataclasses."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence


# Severity level constants for validation rule outcomes
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"

# Category classification constants for validation rule domain
RULE_TYPE_TECHNICAL = "TECHNICAL"
RULE_TYPE_POLICY = "POLICY"


@dataclass(frozen=True)
class ValidationCheckResult:
    """Outcome of an individual validation rule check."""

    check_name: str
    passed: bool
    severity: str  # "INFO", "WARNING", "ERROR"
    rule_type: str  # "TECHNICAL", "POLICY"
    message: str


@dataclass(frozen=True)
class PreDeploymentValidationReport:
    """Aggregated pre-deployment validation report for a target device."""

    device_name: str
    is_valid: bool
    total_checks: int
    passed_checks: int
    failed_checks: int
    error_messages: Sequence[str]
    check_results: Sequence[ValidationCheckResult]
    validator_names: Sequence[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    execution_time_ms: float = 0.0
    validation_version: str = "1.0.0"
