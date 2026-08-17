"""Abstract contract for pre-deployment validation protocol plugins."""

from abc import ABC, abstractmethod
from typing import Any, Mapping, Optional, Sequence

from pre_deployment_validation.report import ValidationCheckResult


class BaseProtocolValidator(ABC):
    """Abstract contract implemented by every pre-deployment protocol validator plugin.

    Pre-deployment validator plugins operate strictly in-memory. They inspect
    both the desired NetBox intent (device context) and rendered Cisco CLI
    configuration text before SSH transport execution.
    """

    @property
    @abstractmethod
    def validator_name(self) -> str:
        """Return the unique string identifier for this validator plugin."""

    @property
    def priority(self) -> int:
        """Return execution priority order (lower numbers execute earlier).

        Default priority is 100.
        """
        return 100

    @abstractmethod
    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Check if this validator supports the target device platform and role.

        Args:
            device_context: The unified NetBox-derived device context dictionary.

        Returns:
            True if this plugin supports the target device hardware/platform;
            otherwise False.
        """

    @abstractmethod
    def is_configured(self, device_context: Mapping[str, Any]) -> bool:
        """Check if desired configuration intent for this protocol exists in context.

        Args:
            device_context: The unified NetBox-derived device context dictionary.

        Returns:
            True if relevant protocol configuration intent exists in NetBox context;
            otherwise False.
        """

    @abstractmethod
    def validate(
        self,
        device: Mapping[str, Any],
        device_context: Mapping[str, Any],
        generated_configuration: str,
        requested_protocols: Optional[Sequence[str]] = None,
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Sequence[ValidationCheckResult]:
        """Execute protocol-specific in-memory validation checks.

        Args:
            device: Target device dictionary from NetBox.
            device_context: Merged 3-tier device context dictionary.
            generated_configuration: Cisco CLI configuration text rendered by ConfigGenerator.
            requested_protocols: Optional list of protocol names requested for validation.
            requested_interfaces: Optional list of interface names requested for validation.

        Returns:
            A sequence of ValidationCheckResult objects detailing rule outcomes.
        """
