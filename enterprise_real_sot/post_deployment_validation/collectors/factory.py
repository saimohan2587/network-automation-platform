"""Factory for instantiating read-only transport collectors."""

from typing import Any, Mapping

from post_deployment_validation.collectors.base_collector import BaseCollector
from post_deployment_validation.collectors.ssh_collector import SSHCollector


class CollectorFactory:
    """Factory creating appropriate read-only collector based on connection driver/protocol."""

    @staticmethod
    def get_collector(connection_details: Mapping[str, Any]) -> BaseCollector:
        """Return collector instance based on transport metadata."""
        transport_type = connection_details.get("transport", "ssh").lower()

        if transport_type in ("ssh", "netmiko", "cli"):
            return SSHCollector()

        # Fallback to SSHCollector for standard CLI drivers
        return SSHCollector()
