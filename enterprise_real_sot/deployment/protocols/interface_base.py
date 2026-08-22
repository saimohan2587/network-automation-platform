"""
Purpose   : Protocol plugin generating interface descriptions, shutdown/no shutdown states, and SVI IPv4 address assignments.
Consumes  : NetBox Interfaces (`interfaces.<name>.description`, `enabled`, `ip_addresses`).
Produces  : Cisco IOS CLI (`interface GigabitEthernetX/Y`, `description ...`, `ip address ...`, `no shutdown`).
"""

import ipaddress
from typing import Any, List, Mapping, Sequence, Tuple


from deployment.logger import get_logger
from deployment.protocols.base_protocol import BaseProtocol, ProtocolValidationError

logger = get_logger("InterfaceBaseProtocol")


class InterfaceBaseProtocol(BaseProtocol):
    """Render base interface administrative state, descriptions, and SVI IPv4 configuration.

    Reads interface definitions and IP assignments from ``device_context["interfaces"]``.
    """

    @property
    def protocol_name(self) -> str:
        """Return the identifier used by ConfigGenerator discovery."""
        return "interface_base"

    @property
    def protocol_category(self) -> str:
        """Return functional protocol category."""
        return "BASE_INTERFACE"


    def is_applicable(self, device_context: Mapping[str, Any]) -> bool:
        """Return whether the context contains interface definitions."""
        interfaces = self._get_interfaces(device_context)
        return len(interfaces) > 0

    def validate(self, device_context: Mapping[str, Any]) -> None:
        """Validate interface descriptions, enabled states, and IPv4 address entries."""
        interfaces = self._get_interfaces(device_context)
        if not interfaces:
            return

        for interface_name, interface_data in interfaces:
            if not isinstance(interface_name, str) or not interface_name.strip():
                raise ProtocolValidationError(
                    self.protocol_name,
                    "all interface entries must have a non-empty string name.",
                )

            description = interface_data.get("description")
            if description is not None:
                if not isinstance(description, str) or "\n" in description or "\r" in description:
                    raise ProtocolValidationError(
                        self.protocol_name,
                        f"description for interface '{interface_name}' must be a single-line string.",
                    )

            enabled = interface_data.get("enabled")
            if enabled is not None and not isinstance(enabled, bool):
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"enabled state for interface '{interface_name}' must be a boolean.",
                )

            ip_addresses = interface_data.get("ip_addresses")
            if ip_addresses is not None and not isinstance(ip_addresses, Sequence):
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"ip_addresses for interface '{interface_name}' must be a list/sequence.",
                )

            if isinstance(ip_addresses, Sequence):
                for ip_item in ip_addresses:
                    self._validate_ip_item(interface_name, ip_item)

    def render(self, device_context: Mapping[str, Any]) -> str:
        """Return base interface CLI configuration for physical and SVI interfaces."""
        interfaces = self._get_interfaces(device_context)
        configuration_blocks: List[str] = []

        for interface_name, interface_data in interfaces:
            block = self._render_interface(interface_name, interface_data)
            if block:
                configuration_blocks.append(block)

        if configuration_blocks:
            logger.info("Generated base interface configuration for %d interface(s).", len(configuration_blocks))

        return "\n".join(configuration_blocks)

    @staticmethod
    def _get_interfaces(device_context: Mapping[str, Any]) -> List[Tuple[str, Mapping[str, Any]]]:
        """Extract sorted interface name and dictionary pairs from device context."""
        interfaces = device_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return []

        result: List[Tuple[str, Mapping[str, Any]]] = []
        for interface_name in sorted(interfaces, key=str):
            data = interfaces[interface_name]
            if isinstance(data, Mapping):
                result.append((interface_name, data))
        return result

    def _validate_ip_item(self, interface_name: str, ip_item: Any) -> None:
        """Validate single IP address entry."""
        address_str = self._extract_ip_string(ip_item)
        if address_str is None:
            return

        # Check if address is IPv4 with CIDR mask
        if ":" not in address_str:
            try:
                ipaddress.IPv4Interface(address_str)
            except ValueError as error:
                raise ProtocolValidationError(
                    self.protocol_name,
                    f"invalid IPv4 address '{address_str}' on interface '{interface_name}': {error}",
                ) from error

    @classmethod
    def _extract_ip_string(cls, ip_item: Any) -> Any:
        """Extract IP address string from string or dictionary representation."""
        if isinstance(ip_item, str):
            return ip_item.strip()
        if isinstance(ip_item, Mapping):
            addr = ip_item.get("address")
            if isinstance(addr, str):
                return addr.strip()
        return None

    def _render_interface(self, interface_name: str, interface_data: Mapping[str, Any]) -> str:
        """Render base CLI commands for a single interface."""
        commands: List[str] = []

        description = interface_data.get("description")
        if isinstance(description, str) and description.strip():
            commands.append(f"description {description.strip()}")

        enabled = interface_data.get("enabled")
        if enabled is not None:
            commands.append("no shutdown" if enabled else "shutdown")

        ip_addresses = interface_data.get("ip_addresses") or []
        for ip_item in ip_addresses:
            address_str = self._extract_ip_string(ip_item)
            if not address_str:
                continue

            # Process IPv4 addresses (skip IPv6)
            if ":" not in address_str and "/" in address_str:
                try:
                    iface = ipaddress.IPv4Interface(address_str)
                    commands.append(f"ip address {iface.ip} {iface.netmask}")
                except ValueError:
                    continue

        if not commands:
            return ""

        return "\n".join([f"interface {interface_name}", *commands, "exit"])
