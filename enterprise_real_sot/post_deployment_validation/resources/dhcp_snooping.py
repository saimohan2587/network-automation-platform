import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class DhcpSnoopingResource(BaseResource):
    """DHCP Snooping compliance resource plugin.

    Extracts desired DHCP Snooping settings from NetBox context
    and parses read-only Cisco IOS 'show ip dhcp snooping' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "dhcp_snooping"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS DHCP Snooping CLI."""
        platform = device_context.get("platform", {})
        if isinstance(platform, Mapping):
            slug = platform.get("slug", "").replace("-", "_").lower()
            if slug in ("cisco_ios", "cisco_xe", "cisco_ios_xe"):
                return True

        device_type = device_context.get("device_type", {})
        if isinstance(device_type, Mapping):
            manufacturer = device_type.get("manufacturer", {})
            if isinstance(manufacturer, Mapping) and manufacturer.get("slug") == "cisco":
                return True

        return True

    def is_configured(self, device_context: Mapping[str, Any]) -> bool:
        """Determine whether DHCP Snooping settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("dhcp_snooping"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired DHCP Snooping enabled state and information option setting."""
        config = device_context.get("config", {})
        dhcp_data = config.get("dhcp_snooping", {}) if isinstance(config, Mapping) else {}

        enabled = bool(dhcp_data.get("enabled", True))
        info_option = bool(dhcp_data.get("information_option", True))

        return {
            "enabled": enabled,
            "information_option": info_option,
        }

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch DHCP Snooping parameters on switch."""
        return ["show ip dhcp snooping"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show ip dhcp snooping' output into actual DHCP Snooping state."""
        raw_text = ""
        if isinstance(raw_outputs, Mapping):
            for cmd_key, text in raw_outputs.items():
                if cmd_key.strip().lower() == "show ip dhcp snooping":
                    raw_text = text
                    break

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return {
                "enabled": False,
                "information_option": False,
            }

        enabled = False
        info_option = False

        for line in raw_text.splitlines():
            line_lower = line.strip().lower()
            is_enabled = bool(re.search(r"\benabled\b", line_lower)) and "disabled" not in line_lower

            if "switch dhcp snooping is" in line_lower or "dhcp snooping is" in line_lower:
                if is_enabled:
                    enabled = True
            elif "insertion of option 82" in line_lower or "option 82" in line_lower:
                if is_enabled or "is allowed" in line_lower:
                    info_option = True

        return {
            "enabled": enabled,
            "information_option": info_option,
        }
