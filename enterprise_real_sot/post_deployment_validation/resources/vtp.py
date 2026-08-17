"""VLAN Trunking Protocol (VTP) compliance resource plugin."""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class VtpResource(BaseResource):
    """VTP compliance resource plugin.

    Extracts desired VTP operating mode and domain from NetBox context
    and parses read-only Cisco IOS 'show vtp status' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "vtp"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS VTP CLI."""
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
        """Determine whether VTP settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("vtp"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired VTP operating mode and optional domain name."""
        config = device_context.get("config", {})
        vtp_data = config.get("vtp", {}) if isinstance(config, Mapping) else {}

        mode = str(vtp_data.get("mode", "transparent")).lower()
        res = {"mode": mode}
        if "domain" in vtp_data and vtp_data["domain"] is not None:
            res["domain"] = str(vtp_data["domain"]).strip()
        return res

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch VTP status on switch."""
        return ["show vtp status"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show vtp status' output into actual VTP state."""
        raw_text = raw_outputs.get("show vtp status", "")

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            actual = {"mode": "unknown"}
            if "domain" in desired_state:
                actual["domain"] = ""
            return actual

        mode = "transparent"
        domain = ""

        for line in raw_text.splitlines():
            if ":" not in line:
                continue

            key, value = [p.strip() for p in line.split(":", 1)]
            key_lower = key.lower()

            if "operating mode" in key_lower:
                mode = value.lower()
            elif "domain name" in key_lower:
                domain = value.strip()

        actual = {"mode": mode}
        if "domain" in desired_state:
            actual["domain"] = domain
        return actual
