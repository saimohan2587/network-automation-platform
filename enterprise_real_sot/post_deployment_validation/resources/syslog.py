"""Syslog compliance resource plugin."""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from post_deployment_validation.resources.base_resource import BaseResource


class SyslogResource(BaseResource):
    """Syslog compliance resource plugin.

    Extracts desired Syslog facility and trap levels from NetBox context
    and parses read-only Cisco IOS 'show logging' CLI outputs.
    """

    @property
    def resource_name(self) -> str:
        """Return unique plugin identifier."""
        return "syslog"

    def supports_device(self, device_context: Mapping[str, Any]) -> bool:
        """Return True if device platform supports Cisco IOS Syslog CLI."""
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
        """Determine whether Syslog settings exist in NetBox config context."""
        config = device_context.get("config", {})
        return isinstance(config, Mapping) and isinstance(config.get("syslog"), Mapping)

    def extract_desired_state(
        self,
        device_context: Mapping[str, Any],
        requested_interfaces: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Extract desired Syslog facility and trap levels."""
        config = device_context.get("config", {})
        syslog_data = config.get("syslog", {}) if isinstance(config, Mapping) else {}

        facility = str(syslog_data.get("facility", "local7")).strip()
        trap = str(syslog_data.get("trap", "informational")).strip()

        return {
            "facility": facility,
            "trap": trap,
        }

    def get_collection_requests(
        self,
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> List[str]:
        """Return read-only command to fetch logging status on switch."""
        return ["show logging"]

    def parse_actual_state(
        self,
        raw_outputs: Dict[str, str],
        device_context: Mapping[str, Any],
        desired_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse 'show logging' output into actual Syslog state."""
        raw_text = raw_outputs.get("show logging", "")

        if "% Invalid" in raw_text or "% Error" in raw_text or not raw_text.strip():
            return {
                "facility": "",
                "trap": "",
            }

        facility = "local7"
        trap = "informational"

        for line in raw_text.splitlines():
            line_lower = line.strip().lower()
            if "logging facility:" in line_lower:
                parts = line.strip().split(":", 1)
                if len(parts) == 2:
                    facility = parts[1].split(",")[0].strip()
            elif "trap logging:" in line_lower:
                parts = line.strip().split(":", 1)
                if len(parts) == 2:
                    val = parts[1].split(",")[0].replace("level", "").strip()
                    if val:
                        trap = val

        return {
            "facility": facility,
            "trap": trap,
        }
