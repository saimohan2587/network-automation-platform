"""
Purpose   : Protocol plugin generating Syslog logging host server CLI commands.
Consumes  : NetBox Config Context (`config.syslog`).
Produces  : Cisco IOS CLI (`logging host ...`, `logging trap ...`).
"""

from typing import Any, List, Mapping, Sequence


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("SyslogProtocol")


class SyslogProtocol(BaseProtocol):
    """Render Syslog logging host, facility, trap, and buffered CLI commands."""

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "syslog"

    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains Syslog configuration."""
        settings = self._get_settings(device_context)
        return isinstance(settings, Mapping) and len(settings) > 0

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate Syslog hosts, facility, trap, and buffered settings."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "Syslog settings must be a mapping.",
            )

        facility = settings.get("facility")
        if facility is not None:
            if not isinstance(facility, str) or not facility.strip() or "\n" in facility:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "Syslog facility must be a valid single-line string.",
                )

        trap = settings.get("trap")
        if trap is not None:
            if not isinstance(trap, str) or not trap.strip() or "\n" in trap:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "Syslog trap level must be a valid single-line string.",
                )

        buffered = settings.get("logging_buffered")
        if buffered is not None:
            if isinstance(buffered, bool) or not isinstance(buffered, int) or buffered < 1:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "Syslog logging_buffered must be a positive integer size.",
                )

        servers = settings.get("servers")
        if servers is not None:
            if not isinstance(servers, Sequence):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "Syslog servers setting must be a list/sequence.",
                )
            for server_entry in servers:
                self._validate_server_entry(server_entry)

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return Syslog CLI configuration string."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            return ""

        commands: List[str] = []

        buffered = settings.get("logging_buffered")
        if isinstance(buffered, int) and not isinstance(buffered, bool):
            commands.append(f"logging buffered {buffered}")

        facility = settings.get("facility")
        if isinstance(facility, str) and facility.strip():
            commands.append(f"logging facility {facility.strip()}")

        trap = settings.get("trap")
        if isinstance(trap, str) and trap.strip():
            commands.append(f"logging trap {trap.strip()}")

        servers = settings.get("servers") or []
        for server_entry in servers:
            cmd = self._render_server_entry(server_entry)
            if cmd:
                commands.append(cmd)

        if commands:
            logger.info("Generated Syslog configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract Syslog configuration dictionary from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("syslog")

    def _validate_server_entry(self, server_entry: Any) -> None:
        """Validate single Syslog server host entry."""
        if isinstance(server_entry, str):
            if not server_entry.strip() or "\n" in server_entry:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "Syslog server address must be a non-empty single-line string.",
                )
        elif isinstance(server_entry, Mapping):
            address = server_entry.get("address")
            if not isinstance(address, str) or not address.strip() or "\n" in address:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "Syslog server address must be a non-empty single-line string.",
                )
        else:
            raise ProtocolValidationError(
                self.protocol_name,
                "Syslog server entry must be a string or a mapping.",
            )

    @staticmethod
    def _render_server_entry(server_entry: Any) -> str:
        """Render single Syslog server host CLI command."""
        if isinstance(server_entry, str) and server_entry.strip():
            return f"logging host {server_entry.strip()}"
        if isinstance(server_entry, Mapping):
            address = server_entry.get("address")
            if isinstance(address, str) and address.strip():
                return f"logging host {address.strip()}"
        return ""
