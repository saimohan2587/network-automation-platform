"""DNS compliance resource plugin."""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class DnsResource(BaseResource):
    """DNS compliance resource plugin.

    Extracts desired DNS domain name and lookup settings from NetBox context
    and parses read-only Cisco IOS 'show hosts' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "dns"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS DNS CLI."""
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
        """Determine whether DNS settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("dns"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired DNS domain name and lookup setting."""
        config = device_context.get("config", {})
        dns_data = config.get("dns", {}) if isinstance(config, Mapping) else {}

        domain_name = str(dns_data.get("domain_name", "")).strip()
        domain_lookup = bool(dns_data.get("domain_lookup", True))

        return {
            "domain_name": domain_name,
            "domain_lookup": domain_lookup,
        }

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch DNS parameters on switch."""
        return ["show hosts"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show hosts' output into actual DNS state."""
        raw_text = raw_outputs.get("show hosts", "")

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return {
                "domain_name": "",
                "domain_lookup": False,
            }

        domain_name = ""
        domain_lookup = False

        for line in raw_text.splitlines():
            line_lower = line.strip().lower()
            if "default domain is" in line_lower:
                parts = line.strip().split("is", 1)
                if len(parts) == 2:
                    domain_name = parts[1].strip()
            elif "lookup" in line_lower:
                if any(k in line_lower for k in ("uses domain service", "is enabled", "enabled")) and not any(
                    k in line_lower for k in ("does not use", "is disabled", "disabled")
                ):
                    domain_lookup = True
                elif any(k in line_lower for k in ("does not use", "is disabled", "disabled")):
                    domain_lookup = False

        return {
            "domain_name": domain_name,
            "domain_lookup": domain_lookup,
        }
