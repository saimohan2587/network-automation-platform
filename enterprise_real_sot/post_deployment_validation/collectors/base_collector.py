"""Abstract base class for compliance data collection transports."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Mapping


class CollectionError(RuntimeError):
    """Raised when data collection fails over transport connection."""


class DeviceUnreachableError(CollectionError):
    """Raised specifically when a device cannot be reached at all for
    post-deployment validation -- SSH connection timeout, TCP connection
    refused, network unreachable, or SSH authentication rejected by the
    device before any command could be sent. Distinct from a CollectionError
    caused by an unexpected parsing/runtime bug during collection: this one
    means the device itself was never reachable, so post_deployment_validation
    classifies it as UNREACHABLE rather than the generic FAILED verdict.
    Subclasses CollectionError so any existing `except CollectionError`
    handling continues to catch it unchanged."""


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
