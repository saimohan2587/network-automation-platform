"""
Purpose   : Protocol plugin generating DHCP Snooping global protection and interface trust CLI commands.
Consumes  : NetBox Config Context (`config.dhcp_snooping`).
Produces  : Cisco IOS CLI (`ip dhcp snooping`, `ip dhcp snooping vlan ...`, `ip dhcp snooping trust`).
"""

from typing import Any, List, Mapping, Sequence


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("DhcpSnoopingProtocol")


class DhcpSnoopingProtocol(BaseProtocol):
    """Render DHCP Snooping global and interface trust CLI commands."""

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "dhcp_snooping"

    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains DHCP Snooping configuration."""
        settings = self._get_settings(device_context)
        return isinstance(settings, Mapping) and settings.get("enabled") is True

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate DHCP Snooping enabled state, VLAN list, and trusted interfaces."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping):
            raise ProtocolValidationError(
                self.protocol_name,
                "DHCP Snooping settings must be a mapping.",
            )

        enabled = settings.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise ProtocolValidationError(
                self.protocol_name,
                "DHCP Snooping 'enabled' must be a boolean.",
            )

        vlans = settings.get("vlans")
        if vlans is not None:
            if not isinstance(vlans, Sequence):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "DHCP Snooping 'vlans' must be a list/sequence.",
                )
            for vlan in vlans:
                if isinstance(vlan, bool) or not isinstance(vlan, int) or vlan < 1 or vlan > 4094:
                    raise ProtocolValidationError(
                        self.protocol_name,
                        f"DHCP Snooping VLAN ID must be between 1 and 4094. Got: {vlan}.",
                    )

        info_option = settings.get("information_option")
        if info_option is not None and not isinstance(info_option, bool):
            raise ProtocolValidationError(
                self.protocol_name,
                "DHCP Snooping 'information_option' must be a boolean.",
            )

        trusted_ifaces = settings.get("trusted_interfaces")
        if trusted_ifaces is not None:
            if not isinstance(trusted_ifaces, Sequence):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "DHCP Snooping 'trusted_interfaces' must be a list/sequence.",
                )
            for iface in trusted_ifaces:
                if not isinstance(iface, str) or not iface.strip() or "\n" in iface:
                    raise ProtocolValidationError(
                        self.protocol_name,
                        "DHCP Snooping trusted interface name must be a valid single-line string.",
                    )

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return DHCP Snooping CLI configuration string."""
        settings = self._get_settings(device_context)
        if not isinstance(settings, Mapping) or settings.get("enabled") is not True:
            return ""

        commands: List[str] = ["ip dhcp snooping"]

        vlans = settings.get("vlans")
        if isinstance(vlans, Sequence) and len(vlans) > 0:
            clean_vlans = sorted(set(v for v in vlans if isinstance(v, int) and not isinstance(v, bool)))
            if clean_vlans:
                vlans_str = ",".join(str(v) for v in clean_vlans)
                commands.append(f"ip dhcp snooping vlan {vlans_str}")

        if settings.get("information_option") is False:
            commands.append("no ip dhcp snooping information option")
        elif settings.get("information_option") is True:
            commands.append("ip dhcp snooping information option")

        trusted_interfaces = settings.get("trusted_interfaces") or []
        for iface in sorted(set(trusted_interfaces)):
            if isinstance(iface, str) and iface.strip():
                commands.append(f"interface {iface.strip()}")
                commands.append(" ip dhcp snooping trust")

        if commands:
            logger.info("Generated DHCP Snooping configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract DHCP Snooping settings dictionary from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("dhcp_snooping")
