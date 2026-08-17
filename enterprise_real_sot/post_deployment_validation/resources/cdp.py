"""Cisco Discovery Protocol (CDP) compliance resource plugin."""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class CdpResource(BaseResource):
    """CDP compliance resource plugin.

    Extracts desired global CDP state from NetBox context
    and parses read-only Cisco IOS 'show cdp' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "cdp"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS CDP CLI."""
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
        """Determine whether CDP settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("cdp"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired global CDP enabled state."""
        config = device_context.get("config", {})
        cdp_data = config.get("cdp", {}) if isinstance(config, Mapping) else {}

        enabled = bool(cdp_data.get("enabled", True))
        return {"enabled": enabled}

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch CDP status on switch."""
        return ["show cdp"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show cdp' output into actual CDP state."""
        raw_text = ""
        if isinstance(raw_outputs, Mapping):
            for cmd_key, text in raw_outputs.items():
                if cmd_key.strip().lower() == "show cdp":
                    raw_text = text
                    break

        if not raw_text or not isinstance(raw_text, str) or not raw_text.strip():
            return {"enabled": False}

        raw_lower = raw_text.lower()
        if (
            "% invalid" in raw_lower
            or "% error" in raw_lower
            or "cdp is not active" in raw_lower
            or "cdp is disabled" in raw_lower
        ):
            return {"enabled": False}

        if (
            "global cdp information" in raw_lower
            or "sending cdp" in raw_lower
            or "cdp is enabled" in raw_lower
            or "sending cdpv2 advertisements" in raw_lower
        ):
            return {"enabled": True}

        return {"enabled": False}
