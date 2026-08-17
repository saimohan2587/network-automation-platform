"""SNMP compliance resource plugin."""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class SnmpResource(BaseResource):
    """SNMP compliance resource plugin.

    Extracts desired SNMP location and contact settings from NetBox context
    and parses read-only Cisco IOS 'show snmp' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "snmp"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS SNMP CLI."""
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
        """Determine whether SNMP settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("snmp"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired SNMP location and contact strings."""
        config = device_context.get("config", {})
        snmp_data = config.get("snmp", {}) if isinstance(config, Mapping) else {}

        location = str(snmp_data.get("location", "")).strip()
        contact = str(snmp_data.get("contact", "")).strip()

        return {
            "location": location,
            "contact": contact,
        }

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch SNMP parameters on switch."""
        return ["show snmp"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show snmp' output into actual SNMP state."""
        raw_text = raw_outputs.get("show snmp", "")

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return {
                "location": "",
                "contact": "",
            }

        location = ""
        contact = ""

        for line in raw_text.splitlines():
            line_str = line.strip()
            if line_str.lower().startswith("logging"):
                continue
            if "location:" in line_str.lower():
                parts = line_str.split(":", 1)
                if len(parts) == 2:
                    location = parts[1].strip()
            elif "contact:" in line_str.lower():
                parts = line_str.split(":", 1)
                if len(parts) == 2:
                    contact = parts[1].strip()

        return {
            "location": location,
            "contact": contact,
        }
