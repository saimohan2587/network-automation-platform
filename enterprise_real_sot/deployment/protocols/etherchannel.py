"""
Purpose   : Protocol plugin generating EtherChannel / Link Aggregation Group (LAG) member assignment CLI commands.
Consumes  : NetBox Interfaces (`interfaces.<name>.lag`).
Produces  : Cisco IOS CLI (`interface <name>`, `channel-group X mode active`).
"""

from typing import Any, List, Mapping, Tuple


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("EtherChannelProtocol")


class EtherChannelProtocol(BaseProtocol):
    """Render EtherChannel (LAG) CLI commands from device context."""

    VALID_MODES = {"active", "passive", "on", "desirable", "auto"}

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "etherchannel"

    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains EtherChannel configuration."""
        settings = self._get_settings(device_context)
        if isinstance(settings, Mapping) and settings.get("enabled"):
            return True

        return len(self._get_interface_lag_memberships(device_context)) > 0

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate EtherChannel settings and member interface assignments."""
        settings = self._get_settings(device_context)
        if settings is not None and not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "EtherChannel configuration settings must be a mapping.",
            )

        for interface_name, group_id, mode in self._get_interface_lag_memberships(device_context):
            if not isinstance(group_id, int) or group_id < 1 or group_id > 128:
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"channel-group ID for interface '{interface_name}' must be an integer between 1 and 128.",
                )
            if mode and mode.lower() not in self.VALID_MODES:
                valid_modes_str = ", ".join(sorted(self.VALID_MODES))
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"channel-group mode '{mode}' for interface '{interface_name}' must be one of: {valid_modes_str}.",
                )

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return EtherChannel member assignment CLI configuration."""
        commands: List[str] = []

        memberships = self._get_interface_lag_memberships(device_context)
        for interface_name, group_id, mode in memberships:
            mode_str = mode.lower() if mode else "active"
            commands.append(f"interface {interface_name}")
            commands.append(f" channel-group {group_id} mode {mode_str}")

        if commands:
            logger.info("Generated EtherChannel configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract EtherChannel settings from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("etherchannel")

    @staticmethod
    def _get_interface_lag_memberships(device_context: Mapping[str, Any]) -> List[Tuple[str, int, str]]:
        """Extract interface name, channel-group ID, and mode tuples."""
        interfaces = device_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return []

        memberships: List[Tuple[str, int, str]] = []
        for interface_name in sorted(interfaces, key=str):
            data = interfaces[interface_name]
            if not isinstance(data, Mapping):
                continue

            lag = data.get("lag")
            if not lag:
                continue

            group_id = None
            mode = "active"

            if isinstance(lag, int):
                group_id = lag
            elif isinstance(lag, str):
                # Extract number from string like 'Port-channel1' or '1'
                digits = "".join(c for c in lag if c.isdigit())
                if digits:
                    group_id = int(digits)
            elif isinstance(lag, Mapping):
                name = lag.get("name", "")
                digits = "".join(c for c in name if c.isdigit())
                if digits:
                    group_id = int(digits)
                mode = lag.get("mode", "active")

            if group_id is not None:
                memberships.append((interface_name, group_id, mode))

        return memberships
