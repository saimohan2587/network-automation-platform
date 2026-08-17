"""
Purpose   : Protocol plugin generating Link Layer Discovery Protocol (LLDP) global CLI commands.
Consumes  : NetBox Config Context (`config.lldp`).
Produces  : Cisco IOS CLI (`lldp run`, `no lldp run`).
"""

from typing import Any, List, Mapping


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("LldpProtocol")


class LldpProtocol(BaseProtocol):
    """Render LLDP global CLI commands from device context."""

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "lldp"

    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains LLDP configuration."""
        settings = self._get_settings(device_context)
        return isinstance(settings, Mapping) and "enabled" in settings

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate LLDP configuration settings."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "LLDP configuration settings must be a mapping.",
            )

        enabled = settings.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise ProtocolValidationError(
                self.protocol_name,
                "LLDP 'enabled' setting must be a boolean.",
            )

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return LLDP CLI configuration string."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            return ""

        commands: List[str] = []
        enabled = settings.get("enabled")
        if enabled is True:
            commands.append("lldp run")
        elif enabled is False:
            commands.append("no lldp run")

        if commands:
            logger.info("Generated LLDP configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract LLDP configuration dictionary from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("lldp")
