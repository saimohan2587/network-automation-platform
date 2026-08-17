"""AAA & TACACS+ compliance resource plugin."""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class AaaResource(BaseResource):
    """AAA compliance resource plugin.

    Extracts desired AAA new-model setting from NetBox context
    and parses read-only Cisco IOS 'show aaa sessions' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "aaa"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS AAA CLI."""
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
        """Determine whether AAA settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("aaa"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired AAA new_model setting."""
        config = device_context.get("config", {})
        aaa_data = config.get("aaa", {}) if isinstance(config, Mapping) else {}

        new_model = bool(aaa_data.get("new_model", True))
        return {
            "new_model": new_model,
        }

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch AAA status on switch."""
        return ["show aaa sessions"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show aaa sessions' output into actual AAA state."""
        raw_text = raw_outputs.get("show aaa sessions", "")

        if "% AAA not enabled" in raw_text or "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return {
                "new_model": False,
            }

        return {
            "new_model": True,
        }
