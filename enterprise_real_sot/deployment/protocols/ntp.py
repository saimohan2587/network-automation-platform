"""
Purpose   : Protocol plugin generating Network Time Protocol (NTP) server synchronization CLI commands.
Consumes  : NetBox Config Context (`config.ntp`).
Produces  : Cisco IOS CLI (`ntp server ...`).
"""

from typing import Any, List, Mapping, Sequence


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("NtpProtocol")


class NtpProtocol(BaseProtocol):
    """Render NTP server and source interface CLI commands."""

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "ntp"

    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains NTP configuration."""
        settings = self._get_settings(device_context)
        return isinstance(settings, Mapping) and len(settings) > 0

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate NTP server list and optional source interface."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "NTP settings must be a mapping.",
            )

        servers = settings.get("servers")
        if servers is not None:
            if not isinstance(servers, Sequence):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "NTP servers setting must be a list/sequence.",
                )
            for server_entry in servers:
                self._validate_server_entry(server_entry)

        source_iface = settings.get("source_interface")
        if source_iface is not None:
            if not isinstance(source_iface, str) or not source_iface.strip() or "\n" in source_iface:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "NTP source_interface must be a valid single-line string.",
                )

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return NTP CLI configuration string."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            return ""

        commands: List[str] = []

        servers = settings.get("servers") or []
        for server_entry in servers:
            cmd = self._render_server_entry(server_entry)
            if cmd:
                commands.append(cmd)

        source_iface = settings.get("source_interface")
        if isinstance(source_iface, str) and source_iface.strip():
            commands.append(f"ntp source {source_iface.strip()}")

        if commands:
            logger.info("Generated NTP configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract NTP configuration dictionary from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("ntp")

    def _validate_server_entry(self, server_entry: Any) -> None:
        """Validate a single NTP server entry (string or mapping)."""
        if isinstance(server_entry, str):
            if not server_entry.strip() or "\n" in server_entry:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "NTP server address must be a non-empty single-line string.",
                )
        elif isinstance(server_entry, Mapping):
            address = server_entry.get("address")
            if not isinstance(address, str) or not address.strip() or "\n" in address:
                raise ProtocolValidationError(
                    self.protocol_name,
                    "NTP server address must be a non-empty single-line string.",
                )
            prefer = server_entry.get("prefer")
            if prefer is not None and not isinstance(prefer, bool):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "NTP server prefer option must be a boolean.",
                )
        else:
            raise ProtocolValidationError(
                self.protocol_name,
                "NTP server entry must be a string or a mapping.",
            )

    @staticmethod
    def _render_server_entry(server_entry: Any) -> str:
        """Render a single NTP server CLI command."""
        if isinstance(server_entry, str) and server_entry.strip():
            return f"ntp server {server_entry.strip()}"
        if isinstance(server_entry, Mapping):
            address = server_entry.get("address")
            if isinstance(address, str) and address.strip():
                prefer_str = " prefer" if server_entry.get("prefer") is True else ""
                return f"ntp server {address.strip()}{prefer_str}"
        return ""
