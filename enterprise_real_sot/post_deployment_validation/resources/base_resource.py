"""Abstract base class for all compliance resource plugins."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Mapping, Optional, Sequence


class ComplianceResourceError(RuntimeError):
    """Raised when a compliance resource plugin fails during processing."""


class BaseResource(ABC):
    """Contract that every compliance resource plugin must implement."""

    @property
    @abstractmethod
    def resource_name(self) -> str:
        """Unique identifier string for the resource plugin (e.g., 'port_security', 'ospf')."""

    @abstractmethod
    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Determine whether this plugin supports the device platform/vendor capability."""

    @abstractmethod
    def is_configured(self, device_context: Mapping[str, Any]) -> bool:
        """Determine whether desired state for this resource exists in NetBox context."""

    @abstractmethod
    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract and normalize desired state dictionary from NetBox device context."""

    @abstractmethod
    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return list of read-only show commands / API endpoints needed to gather actual state."""

    @abstractmethod
    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse raw device CLI outputs into a normalized key-value state dictionary."""
