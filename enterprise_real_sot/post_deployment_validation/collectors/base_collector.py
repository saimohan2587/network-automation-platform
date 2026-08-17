"""Abstract base class for compliance data collection transports."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Mapping


class CollectionError(RuntimeError):
    """Raised when data collection fails over transport connection."""


class BaseCollector(ABC):
    """Abstract contract for read-only device state collectors."""

    @abstractmethod
    def collect(
        self,
        device_name: str,
        connection_details: Mapping[str, Any],
        commands_or_requests: List[str],
    ) -> Dict[str, str]:
        """Execute read-only data collection requests and return raw outputs dict."""
