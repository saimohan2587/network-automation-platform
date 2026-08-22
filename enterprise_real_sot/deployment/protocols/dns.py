"""
Purpose   : Protocol plugin generating DNS domain lookup and name-server CLI commands.
Consumes  : NetBox Config Context (`config.dns`).
Produces  : Cisco IOS CLI (`ip domain name ...`, `ip name-server ...`).
"""

from typing import Any, List, Mapping, Sequence


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("DnsProtocol")


class DnsProtocol(BaseProtocol):
    """Render DNS domain name, domain lookup, and name server CLI commands."""

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "dns"

    @property
    def protocol_category(self) -> str:
        """Return functional protocol category."""
        return "GLOBAL_MANAGEMENT"


    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains DNS configuration."""
        settings = self._get_settings(device_context)
        return isinstance(settings, Mapping) and len(settings) > 0

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate DNS domain name, domain lookup, and name servers."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "DNS settings must be a mapping.",
            )

        domain_name = settings.get("domain_name")
        if domain_name is not None:
            if not isinstance(domain_name, str) or not domain_name.strip() or "\n" in domain_name:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "DNS domain_name must be a non-empty single-line string.",
                )

        lookup = settings.get("domain_lookup")
        if lookup is not None and not isinstance(lookup, bool):
            raise ProtocolValidationError(
                self.protocol_name,
                "DNS domain_lookup setting must be a boolean.",
            )

        servers = settings.get("servers")
        if servers is not None:
            if not isinstance(servers, Sequence):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "DNS servers setting must be a list/sequence.",
                )
            for server in servers:
                if not isinstance(server, str) or not server.strip() or "\n" in server:
                    raise ProtocolValidationError(
                        self.protocol_name,
                        "DNS name server IP must be a valid single-line string.",
                    )

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return DNS CLI configuration string."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            return ""

        commands: List[str] = []

        domain_name = settings.get("domain_name")
        if isinstance(domain_name, str) and domain_name.strip():
            commands.append(f"ip domain name {domain_name.strip()}")


        lookup = settings.get("domain_lookup")
        if lookup is True:
            commands.append("ip domain lookup")
        elif lookup is False:
            commands.append("no ip domain lookup")

        servers = settings.get("servers") or []
        for server in servers:
            if isinstance(server, str) and server.strip():
                commands.append(f"ip name-server {server.strip()}")

        if commands:
            logger.info("Generated DNS configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract DNS configuration dictionary from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("dns")
