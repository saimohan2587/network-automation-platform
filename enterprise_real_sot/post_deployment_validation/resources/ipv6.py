import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class Ipv6Resource(BaseResource):
    """IPv6 compliance resource plugin.

    Extracts desired global IPv6 unicast routing setting from NetBox context
    and parses read-only Cisco IOS CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "ipv6"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS IPv6 CLI."""
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
        """Determine whether IPv6 settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("ipv6"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired IPv6 unicast_routing setting."""
        config = device_context.get("config", {})
        ipv6_data = config.get("ipv6", {}) if isinstance(config, Mapping) else {}

        unicast_routing = bool(ipv6_data.get("unicast_routing", True))
        return {
            "unicast_routing": unicast_routing,
        }

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only commands to fetch IPv6 parameters on switch."""
        return ["show ipv6 interface brief", "show running-config | include ipv6 unicast-routing"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse CLI outputs into actual IPv6 state."""
        raw_run = ""
        if isinstance(raw_outputs, Mapping):
            for cmd_key, text in raw_outputs.items():
                key_norm = cmd_key.strip().lower()
                if "include ipv6 unicast-routing" in key_norm:
                    raw_run = text

        unicast_routing = bool(re.search(r"^\s*ipv6\s+unicast-routing\b", raw_run, re.MULTILINE | re.IGNORECASE))

        return {
            "unicast_routing": unicast_routing,
        }
