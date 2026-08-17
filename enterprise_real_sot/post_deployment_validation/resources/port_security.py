"""Port Security compliance resource plugin."""

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class PortSecurityResource(BaseResource):
    """Port Security compliance resource plugin.

    Extracts desired Port Security settings from NetBox interface custom fields
    and parses read-only Cisco IOS 'show port-security interface' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "port_security"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if the device platform supports Cisco IOS Port Security CLI."""
        platform = device_context.get("platform", {})
        if isinstance(platform, Mapping):
            slug = platform.get("slug", "").replace("-", "_").lower()
            if slug in ("cisco_ios", "cisco_xe", "cisco_ios_xe"):
                return True

        # Fallback check if platform name or vendor indicates Cisco IOS switch
        device_type = device_context.get("device_type", {})
        if isinstance(device_type, Mapping):
            manufacturer = device_type.get("manufacturer", {})
            if isinstance(manufacturer, Mapping) and manufacturer.get("slug") == "cisco":
                return True

        return True

    def is_configured(self, device_context: Mapping[str, Any]) -> bool:
        """Determine whether Port Security settings are configured in NetBox interface custom fields."""
        interfaces = device_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return False

        for interface_data in interfaces.values():
            if isinstance(interface_data, Mapping):
                custom_fields = interface_data.get("custom_fields", {})
                if (
                    isinstance(custom_fields, Mapping)
                    and custom_fields.get("port_security") is not None
                ):
                    return True
        return False

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract and normalize desired Port Security settings from NetBox context."""
        interfaces = device_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return {"interfaces": {}}

        # Filter target interfaces if caller requested specific interfaces
        target_interfaces = None
        if requested_interfaces is not None and "all" not in [i.lower() for i in requested_interfaces]:
            target_interfaces = set(requested_interfaces)

        desired_interfaces: Dict[str, Any] = {}
        for iface_name in sorted(interfaces, key=str):
            if target_interfaces and iface_name not in target_interfaces:
                continue

            iface_data = interfaces[iface_name]
            if not isinstance(iface_data, Mapping):
                continue

            custom_fields = iface_data.get("custom_fields", {})
            if not isinstance(custom_fields, Mapping):
                continue

            ps_settings = custom_fields.get("port_security")
            if not isinstance(ps_settings, Mapping):
                continue

            # Normalize values to standard primitive types
            enabled = bool(ps_settings.get("enabled", True))
            max_mac = int(ps_settings.get("max_mac_addresses", 1))
            violation = str(ps_settings.get("violation", "shutdown")).strip().lower()
            aging_time = int(ps_settings.get("aging_time", 0))
            aging_type = str(ps_settings.get("aging_type", "absolute")).strip().lower()

            desired_interfaces[iface_name] = {
                "enabled": enabled,
                "max_mac_addresses": max_mac,
                "violation": violation,
                "aging_time": aging_time,
                "aging_type": aging_type,
            }

        return {"interfaces": desired_interfaces}

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return list of read-only show commands for target interfaces."""
        interfaces = desired_state.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return []

        commands: List[str] = []
        for iface_name in sorted(interfaces, key=str):
            commands.append(f"show port-security interface {iface_name}")
        return commands

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse CLI show output into normalized key-value state tree."""
        desired_interfaces = desired_state.get("interfaces", {})
        actual_interfaces: Dict[str, Any] = {}

        for iface_name in desired_interfaces:
            command = f"show port-security interface {iface_name}"
            raw_text = raw_outputs.get(command, "")

            actual_interfaces[iface_name] = self._parse_show_port_security(raw_text)

        return {"interfaces": actual_interfaces}

    @staticmethod
    def _parse_show_port_security(raw_text: str) -> Dict[str, Any]:
        """Parse output lines from 'show port-security interface <name>'."""
        # Handle cases where the interface does not exist or switch returns CLI syntax error
        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return {
                "enabled": "N/A (Interface Invalid/Missing on Switch)",
                "max_mac_addresses": "N/A",
                "violation": "N/A",
                "aging_time": "N/A",
                "aging_type": "N/A",
            }

        parsed: Dict[str, Any] = {
            "enabled": False,
            "max_mac_addresses": 1,
            "violation": "shutdown",
            "aging_time": 0,
            "aging_type": "absolute",
        }

        for line in raw_text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue

            key, value = [part.strip() for part in line.split(":", 1)]
            key_lower = key.lower()

            if key_lower == "port security":
                parsed["enabled"] = value.lower() == "enabled"
            elif key_lower == "maximum mac addresses":
                try:
                    parsed["max_mac_addresses"] = int(value)
                except ValueError:
                    pass
            elif key_lower == "violation mode":
                parsed["violation"] = value.lower()
            elif key_lower == "aging time":
                # Parse numeric minutes from strings like '10 mins' or '0 mins'
                match = re.search(r"(\d+)", value)
                if match:
                    parsed["aging_time"] = int(match.group(1))
            elif key_lower == "aging type":
                parsed["aging_type"] = value.lower()

        return parsed

