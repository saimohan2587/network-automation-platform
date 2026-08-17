"""Network-as-Code (NAC) - Pre-Deployment Validation Layer.

Provides in-memory technical syntax, structural integrity, and policy validation
of rendered CLI configurations before SSH deployment execution.
"""

from pre_deployment_validation.base_validator import BaseProtocolValidator
from pre_deployment_validation.orchestrator import PreDeploymentValidator
from pre_deployment_validation.report import (
    PreDeploymentValidationReport,
    ValidationCheckResult,
)

__version__ = "1.0.0"

__all__ = [
    "BaseProtocolValidator",
    "PreDeploymentValidator",
    "PreDeploymentValidationReport",
    "ValidationCheckResult",
]
