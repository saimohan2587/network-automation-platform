"""
Purpose   : Protocol plugin generating IPv6 unicast-routing and interface IPv6 address assignment CLI commands.
Consumes  : NetBox Config Context (`config.ipv6`) and Interfaces (`interfaces.<name>.ip_addresses`).
Produces  : Cisco IOS CLI (`ipv6 unicast-routing`, `interface <name>`, `ipv6 address ...`).
"""

from typing import Any, List, Mapping, Sequence, Tuple


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("Ipv6Protocol")


class Ipv6Protocol(BaseProtocol):
    """Render global IPv6 unicast-routing and interface IPv6 address CLI commands."""

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "ipv6"

    @property
    def protocol_category(self) -> str:
        """Return functional protocol category."""
        return "LAYER3_ROUTING"


    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains IPv6 global or interface configuration."""
        settings = self._get_settings(device_context)
        if isinstance(settings, Mapping) and "unicast_routing" in settings:
            return True

        return len(self._get_interface_ipv6_addresses(device_context)) > 0

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate global IPv6 unicast routing setting and interface IPv6 entries."""
        settings = self._get_settings(device_context)
        if settings is not None:
            if not isinstance(settings, Mapping):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "IPv6 settings must be a mapping.",
                )
            unicast_routing = settings.get("unicast_routing")
            if unicast_routing is not None and not isinstance(unicast_routing, bool):
                raise ProtocolValidationError(
                    self.protocol_name,
                    "IPv6 'unicast_routing' must be a boolean.",
                )

        for interface_name, address in self._get_interface_ipv6_addresses(device_context):
            if not isinstance(address, str) or not address.strip() or "\n" in address:
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"IPv6 address for interface '{interface_name}' must be a valid single-line string.",
                )

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return IPv6 CLI configuration string."""
        commands: List[str] = []

        settings = self._get_settings(device_context)
        if isinstance(settings, Mapping) and "unicast_routing" in settings:
            unicast_routing = settings.get("unicast_routing")
            if unicast_routing is True:
                commands.append("ipv6 unicast-routing")
            elif unicast_routing is False:
                commands.append("no ipv6 unicast-routing")

        for interface_name, address in self._get_interface_ipv6_addresses(device_context):
            commands.append(f"interface {interface_name}")
            commands.append(f" ipv6 address {address.strip()}")
            commands.append(" ipv6 enable")
            commands.append(" exit")

        if commands:
            logger.info("Generated IPv6 configuration (%d command(s)).", len(commands))

        return "\n".join(commands)

    @staticmethod
    def _get_settings(device_context: Mapping[str, Any]) -> Any:
        """Extract IPv6 configuration dictionary from config context."""
        config = device_context.get("config", {})
        if not isinstance(config, Mapping):
            return None
        return config.get("ipv6")

    @staticmethod
    def _get_interface_ipv6_addresses(device_context: Mapping[str, Any]) -> List[Tuple[str, str]]:
        """Extract interface name and IPv6 address pairs from device context."""
        interfaces = device_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return []

        result: List[Tuple[str, str]] = []
        for interface_name in sorted(interfaces, key=str):
            data = interfaces[interface_name]
            if not isinstance(data, Mapping):
                continue
            ip_addresses = data.get("ip_addresses") or []
            if isinstance(ip_addresses, Sequence):
                for ip_item in ip_addresses:
                    addr_str = None
                    if isinstance(ip_item, str):
                        addr_str = ip_item.strip()
                    elif isinstance(ip_item, Mapping):
                        raw_addr = ip_item.get("address")
                        if isinstance(raw_addr, str):
                            addr_str = raw_addr.strip()

                    if addr_str and ":" in addr_str:
                        result.append((interface_name, addr_str))

        return result
