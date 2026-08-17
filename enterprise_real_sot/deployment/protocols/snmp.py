"""
Purpose   : Protocol plugin generating Simple Network Management Protocol (SNMP) server community strings and contact CLI commands.
Consumes  : NetBox Config Context (`config.snmp`).
Produces  : Cisco IOS CLI (`snmp-server community ...`, `snmp-server location ...`, `snmp-server contact ...`).
"""

from typing import Any, List, Mapping, Sequence


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("SnmpProtocol")


class SnmpProtocol(BaseProtocol):
    """Render SNMP community, location, contact, traps, and host CLI commands."""

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "snmp"

    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains SNMP configuration."""
        settings = self._get_settings(device_context)
        return isinstance(settings, Mapping) and len(settings) > 0

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate SNMP communities, location, contact, and traps."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "SNMP settings must be a mapping.",
            )

        for text_field in ("location", "contact"):
            val = settings.get(text_field)
            if val is not None and (not isinstance(val, str) or not val.strip() or "\n" in val):
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"SNMP {text_field} must be a valid single-line string.",
                )

        communities = settings.get("communities")
        if communities is not None:
            if not isinstance(communities, Mapping):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "SNMP communities must be a mapping.",
                )
            for comm_name, comm_data in communities.items():
                self._validate_community(comm_name, comm_data)

        traps = settings.get("traps")
        if traps is not None:
            if not isinstance(traps, Mapping):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "SNMP traps setting must be a mapping.",
                )
            servers = traps.get("servers")
            if servers is not None and not isinstance(servers, Sequence):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "SNMP trap servers must be a list/sequence.",
                )

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return SNMP CLI configuration string."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            return ""

        commands: List[str] = []

        # Communities
        communities = settings.get("communities")
        if isinstance(communities, Mapping):
            for comm_name in sorted(communities, key=str):
                comm_data = communities[comm_name]
                cmd = self._render_community(comm_name, comm_data)
                if cmd:
                    commands.append(cmd)

        location = settings.get("location")
        if isinstance(location, str) and location.strip():
            commands.append(f"snmp-server location {location.strip()}")

        contact = settings.get("contact")
        if isinstance(contact, str) and contact.strip():
            commands.append(f"snmp-server contact {contact.strip()}")

        # Traps
        traps = settings.get("traps")
        if isinstance(traps, Mapping):
            enabled_traps = traps.get("enabled_traps") or []
            if isinstance(enabled_traps, Sequence) and len(enabled_traps) > 0:
                clean_traps = [t.strip() for t in enabled_traps if isinstance(t, str) and t.strip()]
                if clean_traps:
                    commands.append(f"snmp-server enable traps {' '.join(clean_traps)}")

            servers = traps.get("servers") or []
            for server in servers:
                if isinstance(server, str) and server.strip():
                    commands.append(f"snmp-server host {server.strip()}")

        if commands:
            logger.info("Generated SNMP configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract SNMP configuration dictionary from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("snmp")

    def _validate_community(self, comm_name: str, comm_data: Any) -> None:
        """Validate single SNMP community definition."""
        if not isinstance(comm_name, str) or not comm_name.strip() or "\n" in comm_name:
            raise ProtocolValidationError(
                self.protocol_name,
                "SNMP community name must be a single-line string.",
            )
        if isinstance(comm_data, Mapping):
            access = comm_data.get("access")
            if access is not None and (not isinstance(access, str) or access.lower() not in ("ro", "rw")):
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"SNMP community access for '{comm_name}' must be 'ro' or 'rw'.",
                )

    @staticmethod
    def _render_community(comm_name: str, comm_data: Any) -> str:
        """Render single SNMP community CLI statement."""
        access_str = "RO"
        acl_str = ""

        if isinstance(comm_data, Mapping):
            access = comm_data.get("access")
            if isinstance(access, str) and access.lower() == "rw":
                access_str = "RW"
            acl = comm_data.get("acl")
            if acl is not None:
                acl_str = f" {str(acl).strip()}"

        return f"snmp-server community {comm_name} {access_str}{acl_str}"
