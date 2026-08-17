"""
Purpose   : Abstract base class defining the contract (is_applicable, validate, render) for all protocol plugins.
Consumes  : Abstract contract definition.
Produces  : Standardized interface for ConfigGenerator plugin discovery.
"""

from abc import ABC, abstractmethod
from typing import Any, Mapping



class ProtocolValidationError(ValueError):
    """Raised when a protocol plugin receives an invalid device context."""

    def __init__(self, protocol_name: str, message: str) -> None:
        super().__init__(f"Protocol '{protocol_name}' validation failed: {message}")


class BaseProtocol(ABC):
    """Abstract contract implemented by every configuration protocol plugin.

    Protocol plugins receive a unified, NetBox-derived device context from the
    configuration generator. They decide whether their feature applies, validate
    the data they require, and render only their own configuration fragment.
    Implementations must remain side-effect free: they must not access NetBox,
    read CSV files, or communicate with network devices.
    """

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Return the plugin's human-readable protocol identifier."""

    @abstractmethod
    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether this plugin applies to the supplied device context.

        Args:
            device_context: The unified context containing ``device_info``,
                ``config``, and ``interfaces``.

        Returns:
            ``True`` when the generator should validate and render this plugin;
            otherwise ``False``.
        """

    @abstractmethod
    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate protocol-specific data in the supplied device context.

        Implementations must raise :class:`ProtocolValidationError` with a
        precise, actionable message when required data is missing or invalid.

        Args:
            device_context: The unified context containing ``device_info``,
                ``config``, and ``interfaces``.
        """

    @abstractmethod
    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return this plugin's deterministic configuration fragment.

        The configuration generator calls this method only after applicability
        evaluation and successful validation. An applicable protocol with no
        required configuration may return an empty string.

        Args:
            device_context: The unified context containing ``device_info``,
                ``config``, and ``interfaces``.

        Returns:
            A configuration fragment owned exclusively by this plugin.
        """
